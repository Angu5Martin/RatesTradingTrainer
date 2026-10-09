"""The episode runner: a deterministic state machine over planned rounds of  pricing -> fill -> risk decision -> market move -> mark.

    ep = Episode("mm.ep1_single_trade", seed=7)
    while not ep.done:
        obs = ep.observe()               # plain data: what the trainee sees and what is being asked
        result = ep.submit(decision)     # assessment (ex ante) + what happened (ex post)
    ep.debrief()                         # decision quality vs outcome vs luck; other policies on the same path

A round follows its RoundPlan (state.py): an optional pricing decision (two-way quote or a client request), one risk decision (hedge,
position, overnight, re-hedge) and a market move (intraday, event, or overnight with carry, roll-down and funding). Levels 1-2 are plans of
identical rounds; levels 3-5 vary them.

DETERMINISM AND FAIRNESS. Four random streams are seeded from (episode id, seed, stream name) and drawn IN FULL when the episode is
created, before any decision: `setup` (market, book, regime), `arrivals` (which client asks, its side, size, tenor and whether it is
informed), `fills` (one uniform per inquiry) and `market` (factor moves, and at level 5 whether the research view is right). No decision can
change them. Your price changes only the PROBABILITY that a client deals with you, which is compared with a fixed uniform. So the same
(id, seed) replayed with other decisions faces the same clients and the same market path, and a difference in outcome is caused by the
decisions. An informed client's trade moves the market whether or not it traded with you (it trades with someone).

The UI is not here: observations and results carry their text and their data, and a front end renders them (episode_session.py).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable

from ..engine.carry import accrual_estimate, financing_cost
from ..engine.dates import TARGET
from ..engine.instruments import IRSwap, Side
from ..engine.risk import key_rate_dv01
from ..marketmaking.flow import CLIENT_TYPES, fill_probability, improvement_bp
from ..marketmaking.quoting import BP, ClientAction, Quote
from ..questions.market import curve_line, eur_m, pct
from ..questions.model import Grade, NumericPart, Tolerance, fmt_eur
from .assess import (Assessment, DecisionContext, Info, VisibleClient, _held_products, _switch_decision, assess_hedge, assess_quote,
                     assess_rfq, best_alternative)
from .evidence import Evidence, posterior
from .factors import CURVE_FACTORS, FACTORS, FactorRisk, apply_moves, first_order_pnl, step_vol
from .products import BondPosition, FuturePosition
from .render import debrief_lines, observation_lines, result_lines
from .state import (INFORMED_DRIFT_BP, NEIGHBOURS, BondTrade, CheckpointAnswer, Desk, FuturesTrade, HedgeDecision, HedgeTrade, Inquiry,
                    LedgerEntry, Limits, NamedClient, Position, QuoteDecision, Rating, Regime, RFQDecision, RoundPlan, Signal, book)
from .views import debrief_view, observation_view

LEG_MIN_SHARE = 0.002      # a hedge leg below this share of the DV01 limit is not worth a trade
OVERNIGHT_DT = 0.5          # an overnight's market risk, in days of normal vol (a stated training assumption)
DECISION_KINDS = ("hedge", "position", "overnight", "rehedge")


@dataclass(frozen=True)
class Setup:
    title: str
    briefing: str
    mkt: object                     # MarketCurves, or products.SpreadMarket at level 4
    tenor: int                      # focus / home tenor
    limit: float
    positions: tuple[Position, ...]
    regime: Regime
    rounds: int
    mode: str                       # "twoway" (level 1) | "rfq" (level 2+)
    checkpoint: bool = False        # level 1: ask for the book's DV01 once, after the first fill
    desk: Desk | None = None
    plans: tuple[RoundPlan, ...] | None = None
    signal: Signal | None = None
    clients: tuple[NamedClient, ...] = ()
    many_paths: bool = False
    extra_lines: tuple[str, ...] = ()   # standing information shown with the book (e.g. the product menu)
    _leans: dict = field(default_factory=dict, compare=False)   # level 5: each named client's direction today (setup stream)

    def plan(self, r: int) -> RoundPlan:
        if self.plans:
            return self.plans[r]
        return RoundPlan(pricing="quote" if self.mode == "twoway" else "rfq",
                         checkpoint="dv01_after_fill" if self.checkpoint else None)

    def the_desk(self) -> Desk:
        return self.desk or Desk((self.tenor, *NEIGHBOURS[self.tenor]), Limits(self.limit))


@dataclass(frozen=True)
class EpisodeSpec:
    id: str
    level: int
    skill: str
    title: str
    build: Callable[[random.Random], Setup]
    draw_inquiry: Callable[[random.Random, Setup], Inquiry]
    policies: dict | None = None    # name -> policy(ep, obs); None = the level 1-2 set


@dataclass
class Observation:
    kind: str                       # "quote" | "rfq" | "checkpoint" | "hedge" | "position" | "overnight" | "rehedge"
    round: int
    lines: list[str]
    prompt: str
    input_hint: str
    ctx: DecisionContext | None = None
    part: NumericPart | None = None
    view: dict | None = None        # the public ObservationView (None for render=False counterfactual runs)


@dataclass
class StepResult:
    lines: list[str]
    assessment: Assessment | None = None
    grade: Grade | None = None
    events: list = field(default_factory=list)      # what happened, as plain dicts; `lines` are rendered from them


@dataclass
class RoundRecord:
    round: int
    inquiry: Inquiry
    plan: RoundPlan = field(default_factory=RoundPlan)
    decisions: list[tuple[str, object, Assessment | None]] = field(default_factory=list)
    filled: bool = False
    p_fill: float = 0.0
    moves: dict[str, float] = field(default_factory=dict)
    expected: float = 0.0
    variance: float = 0.0
    pnl: float = 0.0
    x_after: dict[str, float] = field(default_factory=dict)     # exposures carried through this round's move
    fixed: float = 0.0              # P&L not caused by the move: edge, costs, carry, funding


_REGISTRY: dict[str, EpisodeSpec] = {}


def register_episode(spec: EpisodeSpec) -> None:
    if spec.id in _REGISTRY:
        raise ValueError(f"duplicate episode id {spec.id}")
    _REGISTRY[spec.id] = spec


def all_episodes() -> list[EpisodeSpec]:
    from . import specs  # noqa: F401  (registers)
    return sorted(_REGISTRY.values(), key=lambda s: (s.level, s.id))


def get_episode(eid: str) -> EpisodeSpec:
    all_episodes()
    try:
        return _REGISTRY[eid]
    except KeyError:
        raise KeyError(f"unknown episode {eid!r}") from None


def _streams(eid: str, seed: int, name: str) -> random.Random:
    return random.Random(f"{eid}:{seed}:{name}")


def bucket_dv01(inst, mkt, buckets=(2, 5, 10, 30)) -> dict[int, float]:
    """Key-rate DV01 (engine) summed into the nearest of a few tenor buckets (OIS and Euribor keys together)."""
    kr = key_rate_dv01(inst, mkt, curves=("OIS", "E6M"))
    out = {b: 0.0 for b in buckets}
    for (_, m), d in kr.items():
        b = min(buckets, key=lambda x: abs(math.log(m / 12.0) - math.log(x)))
        out[b] += d
    return out


class Episode:
    def __init__(self, eid: str, seed: int, market_seed: int | None = None, render: bool = True):
        self.render = render            # False for counterfactual runs: decisions and P&L only, no screens
        self.spec = get_episode(eid)
        self.seed = seed
        self.market_seed = market_seed
        self.setup = self.spec.build(_streams(eid, seed, "setup"))
        s = self.setup
        arrivals = _streams(eid, seed, "arrivals")
        self.inquiries = [self.spec.draw_inquiry(arrivals, s) for _ in range(s.rounds)]
        fills = _streams(eid, seed, "fills")
        self.uniforms = [fills.random() for _ in range(s.rounds)]
        market = _streams(eid, seed if market_seed is None else market_seed, "market")
        self.factors = s.the_desk().factors
        self.z = [{k: market.gauss(0.0, 1.0) for k in self.factors} for _ in range(s.rounds)]
        self.signal_right = (market.random() < s.signal.reliability) if s.signal else False

        self.mkt = s.mkt
        self.positions: tuple[Position, ...] = s.positions
        self.regime = s.regime
        self.limits = s.the_desk().limits
        self.ledger: list[LedgerEntry] = []
        self.records: list[RoundRecord] = []
        self.checkpoints: list[Grade] = []
        self.evidence: list[Evidence] = []
        self.cash = 0.0
        self._deferred: list[dict] = []          # a checkpoint grade held back until after pricing (level 3)
        self.pv0 = book(self.positions).pv(self.mkt)
        self.round = 0
        self._ctx: DecisionContext | None = None
        self._start_round()

    # ------------------------------------------------------------------ state helpers
    @property
    def done(self) -> bool:
        return self.phase == "done"

    @property
    def record(self) -> RoundRecord:
        return self.records[-1]

    @property
    def plan(self) -> RoundPlan:
        return self.setup.plan(self.round)

    def desk(self) -> Desk:
        return replace(self.setup.the_desk(), limits=self.limits)

    def _start_round(self) -> None:
        p = self.plan
        if p.regime is not None:
            self.regime = p.regime
        if p.limits is not None:
            self.limits = p.limits
        self.records.append(RoundRecord(self.round, self.inquiries[self.round], p))
        self._phases = ([] if p.checkpoint != "slope_if_dealt" else ["checkpoint"]) + ([p.pricing] if p.pricing else [])
        if p.checkpoint in ("dv01_after_fill", "futures_contracts"):
            self._phases.append("checkpoint")
        self._phases.append(p.decision)
        self.phase = self._phases[0]
        self._ctx = None

    def _next_phase(self) -> None:
        self._phases.pop(0)
        while self._phases and self._phases[0] == "checkpoint" and not self._checkpoint_applies():
            self._phases.pop(0)
        self.phase = self._phases[0]
        self._ctx = None

    def _checkpoint_applies(self) -> bool:
        cp = self.plan.checkpoint
        if cp == "dv01_after_fill":
            return self.record.filled and not self.checkpoints
        return True

    def inquiry_tenor(self) -> int:
        return self.inquiries[self.round].tenor or self.setup.tenor

    def _visible_client(self) -> VisibleClient | None:
        if not self.plan.pricing:
            return None
        q = self.inquiries[self.round]
        return VisibleClient(q.ctype, q.action, q.notional, q.tenor, q.name)

    def info(self, kind: str) -> Info:
        """Observable and stated information for the current decision (never the hidden truth)."""
        s, p = self.setup, self.plan
        kw: dict = {}
        if kind in DECISION_KINDS:
            kw["vol_mult"] = p.vol_mult
            if kind == "overnight":
                kw["dt"] = OVERNIGHT_DT
                kw["overnight_to"] = self.next_day()
        if s.signal:
            per = s.signal.view_bp / s.rounds
            kw.update(signal_drift_bp=s.signal.reliability * per if kind in DECISION_KINDS else 0.0,
                      view_bp=s.signal.view_bp * (s.rounds - self.round) / s.rounds, reliability=s.signal.reliability)
        q = self.inquiries[self.round]
        if q.name is not None and p.pricing:
            kw["posterior"] = self.posterior_of(q.name)
        return Info(**kw)

    def posterior_of(self, name: str) -> float:
        prior = CLIENT_TYPES[next(c.ctype for c in self.setup.clients if c.name == name)].p_informed
        return posterior(prior, [e for e in self.evidence if e.name == name])

    def next_day(self) -> date:
        return TARGET.add_business_days(self.mkt.anchor, 1)

    def context(self) -> DecisionContext:
        """The decision context for the current phase: only information the trainee has."""
        if self._ctx is None:
            client = None if self.phase == "quote" else self._visible_client()
            kind = self.phase if self.phase != "checkpoint" else "hedge"
            self._ctx = DecisionContext(self.mkt, self.positions, self.limits.dv01, self.regime, self.inquiry_tenor(), client,
                                        desk=self.desk(), info=self.info(kind), home=self.setup.tenor)
        return self._ctx

    def pnl_total(self) -> float:
        return sum(e.amount for e in self.ledger)

    # ------------------------------------------------------------------ observation
    def observe(self) -> Observation:
        """The current decision. `.view` is the public view-model (views.ObservationView); `.lines` is that view rendered for the terminal;
        `.ctx` and `.part` are engine-side (policies, assessment, tests) and are NOT part of the frontend contract."""
        if self.done:
            raise RuntimeError("episode finished")
        ctx, r = self.context(), self.round
        if not self.render:
            part = self._checkpoint_part(ctx) if self.phase == "checkpoint" else None
            return Observation(self.phase, r, [], "", "", ctx, part)
        part = self._checkpoint_part(ctx) if self.phase == "checkpoint" else None
        prompt, hint = (part.prompt, part.note or "EUR") if part else self._phase_prompt()
        view = observation_view(self, prompt, hint, part.unit if part else None)
        return Observation(self.phase, r, observation_lines(view), prompt, hint, ctx, part, view)

    def _phase_prompt(self) -> tuple[str, str]:
        if self.phase == "quote":
            return (f"Show your two-way market in the {self.setup.tenor}Y (bid / offer).",
                    "two rates in %, e.g. 2.843 2.847 (you pay fixed at your bid, receive at your offer)")
        if self.phase == "rfq":
            q = self.inquiries[self.round]
            return (f"Your rate for the client to {q.action.value.rstrip('s')} at (or 'pass')?", "a rate in %, e.g. 2.8465, or 'pass'")
        return self._decision_prompt()

    def _decision_prompt(self) -> tuple[str, str]:
        s, d = self.setup, self.desk()
        if self.phase == "position":
            return ("What risk do you want to run into the next step? (Take, keep or cut: inventory is not the only reason.)",
                    "'keep'; 'target +100k' / 'target -50k' / 'flat' (DV01, done in the focus tenor); or explicit swaps like 'pay 100m 10y'")
        base = (f"'none'; '50%' (of your DV01, in the {s.tenor}Y); '100% 5y'; 'pay 150m 10y'; or two legs: 'pay 150m 10y + receive 60m 30y'")
        if d.multi_tenor:
            base = "'none'; '100% 10y' (of your DV01); 'flatten' (level, slope and curvature); or legs: 'pay 150m 10y + receive 60m 30y'"
        if d.products:
            base += "; futures and bonds: 'sell 300 fgbl', 'buy 120 fgbm', 'sell 50m ctd'; 'switch' closes product hedges into swaps"
        prompt = {"overnight": "What do you carry overnight? Hedge, partly hedge, switch, or keep.",
                  "rehedge": "Liquidity is back. Re-hedge, switch, or keep your hedges as they are?"}.get(self.phase, "Hedge, partly hedge, or warehouse?")
        return prompt, base

    def _checkpoint_part(self, ctx: DecisionContext) -> NumericPart:
        cp = self.plan.checkpoint
        if cp == "slope_if_dealt":
            q = self.inquiries[self.round]
            after = ctx.slope + ctx.trade_exposure(q.action, q.notional, self.inquiry_tenor())["slope"]
            return NumericPart("If this client deals, what will your SLOPE exposure be (EUR per bp of slope)?", after,
                               Tolerance(rel=0.10, abs=0.02 * self.limits.dv01), "EUR",
                               sign_hint="Slope exposure is the P&L for a 1bp FLATTENING: receiving in the 30Y adds (+), receiving in the 2Y subtracts (-).",
                               note="current slope exposure + the trade's DV01 x the slope loading of its tenor")
        if cp == "futures_contracts":
            code = next(p.code for p in self.desk().products if p.kind == "future")
            per = ctx.unit_product(code)["level"]
            return NumericPart(f"How many {code} contracts would hedge your book's DV01? (sell = negative)", -ctx.dv01 / per,
                               Tolerance(rel=0.06), "contracts", sign_hint="A long book is hedged by SELLING futures.",
                               note="book DV01 / DV01 per contract, opposite sign")
        return NumericPart("What is the DV01 of your whole book now (EUR per bp, + if long duration)?", ctx.dv01, Tolerance(rel=0.05),
                           "EUR", sign_hint="Receiving fixed is long duration (+); paying fixed is short (-).",
                           note="add the new trade's DV01 to what you had")

    # ------------------------------------------------------------------ transitions
    # Every transition returns EVENTS (plain dicts, see render.result_lines for their fields); the lines of a StepResult are rendered from them.
    def submit(self, decision) -> StepResult:
        if self.done:
            raise RuntimeError("episode finished")
        if self.phase == "quote":
            return self._on_quote(decision)
        if self.phase == "rfq":
            return self._on_rfq(decision)
        if self.phase == "checkpoint":
            return self._on_checkpoint(decision)
        return self._on_decision(decision)

    @staticmethod
    def _result(events: list[dict], assessment: Assessment | None = None, grade: Grade | None = None) -> StepResult:
        return StepResult(result_lines(events), assessment, grade, events)

    def _fill(self, ctx: DecisionContext, quote_rate: float, action: ClientAction, p: float) -> list[dict]:
        q = self.inquiries[self.round]
        t = self.inquiry_tenor()
        self.record.p_fill = p
        self.record.filled = self.uniforms[self.round] < p
        if not self.record.filled:
            return [{"type": "fill", "filled": False, "p_win": p}]
        swap = IRSwap.new(action.dealer_side, q.notional, quote_rate, self.mkt.spot, 12 * t)
        edge = swap.pv(self.mkt)
        self.positions = self.positions + (Position(swap, "client", f"client, round {self.round + 1}", self.round),)
        self.ledger.append(LedgerEntry(self.round, "edge", edge))
        self.record.fixed += edge
        return [{"type": "fill", "filled": True, "p_win": p, "action": action.value, "notional": q.notional, "tenor": t, "rate": quote_rate,
                 "dealer_side": action.dealer_side.value, "edge": edge}]

    def _on_quote(self, d: QuoteDecision) -> StepResult:
        ctx = self.context()
        a = assess_quote(ctx, d.quote)
        self.record.decisions.append(("quote", d, a))
        self.record.expected += a.expected_pnl
        self.record.variance += a.variance
        q = self.inquiries[self.round]
        ct = CLIENT_TYPES[q.ctype]
        p = fill_probability(ct, improvement_bp(q.action, d.quote, ctx.street()))
        events = [{"type": "client_arrives", "name": q.name, "short": ct.description.split(";")[0].lower(), "description": ct.description,
                   "action": q.action.value, "notional": q.notional, "your_rate": d.quote.client_rate(q.action),
                   "street_rate": ctx.street().client_rate(q.action)}]
        events += self._fill(ctx, d.quote.client_rate(q.action), q.action, p)
        self._next_phase()
        return self._result(events + self._auto_hedge_if_flat(), a)

    def _on_rfq(self, d: RFQDecision) -> StepResult:
        ctx = self.context()
        a = assess_rfq(ctx, d.level)
        self.record.decisions.append(("rfq", d, a))
        self.record.expected += a.expected_pnl
        self.record.variance += a.variance
        q = self.inquiries[self.round]
        if d.level is None:
            events = [{"type": "passed"}]
            self.record.p_fill = 0.0
        else:
            events = self._fill(ctx, d.level, q.action, a.metrics["p_win"])
        events = self._deferred + events
        self._deferred = []
        self._next_phase()
        return self._result(events + self._auto_hedge_if_flat(), a)

    def _auto_hedge_if_flat(self) -> list[dict]:
        """Nothing to decide with a flat book (levels 1-2 hedges only): no hedge, and the market moves on."""
        if self.phase != "hedge" or self.desk().multi_tenor or self.desk().products:
            return []
        ctx = self.context()
        if abs(ctx.dv01) > 0.02 * self.limits.dv01 or abs(ctx.curve_position()) > 0.05 * self.limits.dv01:
            return []
        return [{"type": "flat_book"}] + self._on_decision(HedgeDecision((), "flat: nothing to hedge"), record=False).events

    def _on_checkpoint(self, d: CheckpointAnswer) -> StepResult:
        part = self._checkpoint_part(self.context())
        g = part.grade(d.raw)
        self.checkpoints.append(g)
        self._next_phase()
        grade = {"type": "checkpoint_grade", "correct": bool(g.correct), "feedback": g.feedback, "expected": g.expected, "label": None}
        if self.plan.checkpoint == "slope_if_dealt":
            # the answer IS the trade's effect on the whole book: revealing it before the price would do the pricing work for the trainee
            self._deferred = [{**grade, "label": "Your slope check"}]
            return self._result([{"type": "checkpoint_recorded"}])
        return self._result([grade], grade=g)

    def _leg_dv01(self, ctx: DecisionContext, tr) -> float:
        if isinstance(tr, HedgeTrade):
            return tr.notional / 1e6 * ctx.dv01_per_m(tr.tenor)
        if isinstance(tr, FuturesTrade):
            return tr.contracts * ctx.unit_product(tr.code)["level"]
        return tr.face / 1e6 * ctx.unit_product(tr.code)["level"]

    @staticmethod
    def _leg_text(tr) -> str:
        if isinstance(tr, HedgeTrade):
            return f"{tr.side.value} fixed €{tr.notional / 1e6:,.2f}m {tr.tenor}Y"
        if isinstance(tr, FuturesTrade):
            return f"{'buy' if tr.contracts > 0 else 'sell'} {abs(tr.contracts):,.1f} {tr.code}"
        return f"{'buy' if tr.face > 0 else 'sell'} €{abs(tr.face) / 1e6:,.2f}m of the {tr.code} bond"

    def _without_dust(self, ctx: DecisionContext, d: HedgeDecision) -> tuple[HedgeDecision, list[dict]]:
        """Legs smaller than LEG_MIN_SHARE of the DV01 limit are not worth a trade (a 'EUR 0m' leg from rounding a hedge): they are dropped
        BEFORE assessment and execution so the book, the ledger and the grade all describe the same trades."""
        keep, skipped = [], []
        for tr in d.trades:
            if abs(self._leg_dv01(ctx, tr)) < LEG_MIN_SHARE * ctx.limit:
                skipped.append({"type": "skipped_trade", "description": self._leg_text(tr), "threshold_pct": LEG_MIN_SHARE * 100})
            else:
                keep.append(tr)
        return (replace(d, trades=tuple(keep)) if skipped else d), skipped

    def _execute(self, ctx: DecisionContext, tr) -> dict:
        if isinstance(tr, HedgeTrade):
            dv = tr.notional / 1e6 * ctx.dv01_per_m(tr.tenor)
            hs = ctx.swap_cost(tr.tenor, dv) / dv if dv else 0.0          # spread incl. any late-session impact, in bp
            rate = ctx.mid(tr.tenor) + (hs if tr.side is Side.PAY else -hs) * BP
            swap = IRSwap.new(tr.side, tr.notional, rate, self.mkt.spot, 12 * tr.tenor)
            cost = swap.pv(self.mkt)
            self.positions = self.positions + (Position(swap, "hedge", f"hedge, round {self.round + 1}", self.round),)
            self.ledger.append(LedgerEntry(self.round, "hedge cost", cost))
            self.record.fixed += cost
            return {"type": "hedge_trade", "kind": "swap", "side": tr.side.value, "notional": tr.notional, "tenor": tr.tenor, "rate": rate,
                    "cost": cost}
        qty = tr.contracts if isinstance(tr, FuturesTrade) else tr.face / 1e6
        cost = -ctx.product_cost(tr.code, qty)
        pos = ctx.product_position(tr.code, qty)
        if isinstance(pos, FuturePosition):
            pos = replace(pos, entry=pos.price(self.mkt))          # margined: worth zero when traded
        else:
            self.cash -= pos.pv(self.mkt)                            # a bond is paid for (financed in repo); a short sale brings cash in
        self.positions = self.positions + (Position(pos, "hedge", f"hedge, round {self.round + 1}", self.round),)
        self.cash += cost
        self.ledger.append(LedgerEntry(self.round, "hedge cost", cost))
        self.record.fixed += cost
        if isinstance(tr, FuturesTrade):
            return {"type": "hedge_trade", "kind": "future", "code": tr.code, "contracts": tr.contracts, "cost": cost}
        return {"type": "hedge_trade", "kind": "bond", "code": tr.code, "face": tr.face, "cost": cost}

    def _on_decision(self, d: HedgeDecision, record: bool = True) -> StepResult:
        ctx = self.context()
        kind = self.phase
        d, skipped = self._without_dust(ctx, d)
        a = assess_hedge(ctx, d, "position" if kind == "position" else "hedge")
        a.kind = kind
        if record:
            self.record.decisions.append((kind, d, a))
        events = skipped + [self._execute(ctx, tr) for tr in d.trades]
        if not d.trades and record:
            events.append({"type": "no_trade"})
        x, _ = ctx.after(d)
        self.record.expected += -a.metrics["cost"] - x["level"] * ctx.pending_drift_bp()
        self.record.variance += a.variance
        events += self._move()
        self.round += 1
        if self.round >= self.setup.rounds:
            self.phase = "done"
        else:
            self._start_round()
        return self._result(events, a)

    # ------------------------------------------------------------------ the market
    def _moves(self, dt: float) -> dict[str, float]:
        reg, p = self.regime, self.plan
        moves = {k: self.z[self.round][k] * step_vol(k, reg.vol * p.vol_mult, dt) for k in self.factors}
        q = self.inquiries[self.round]
        if p.pricing and q.informed:
            moves["level"] += (1.0 if q.action is ClientAction.PAYS else -1.0) * INFORMED_DRIFT_BP * reg.vol
        if self.setup.signal and self.signal_right:
            moves["level"] += self.setup.signal.view_bp / self.setup.rounds
        return moves

    def _overnight_time(self) -> tuple[list[dict], object]:
        """Roll one business day on an unchanged curve: carry, roll-down, funding, futures convergence."""
        new_anchor = self.next_day()
        rolled = self.mkt.rolled(new_anchor, "static")
        curves = getattr(self.mkt, "curves", self.mkt)
        causes: dict[str, float] = {}
        for p in self.positions:
            dpv = p.inst.pv(rolled) - p.inst.pv(self.mkt)
            if isinstance(p.inst, IRSwap):
                carry = accrual_estimate(p.inst, curves, new_anchor)
                causes["time: swap carry"] = causes.get("time: swap carry", 0.0) + carry
                causes["time: swap roll-down"] = causes.get("time: swap roll-down", 0.0) + dpv - carry
            elif isinstance(p.inst, BondPosition):
                causes["time: bond accrual and roll"] = causes.get("time: bond accrual and roll", 0.0) + dpv
                fund = -financing_cost(p.inst.materialise(self.mkt), self.mkt, new_anchor)
                causes["funding (repo)"] = causes.get("funding (repo)", 0.0) + fund
                self.cash += fund
            else:
                causes["time: futures convergence"] = causes.get("time: futures convergence", 0.0) + dpv
        for k, v in causes.items():
            self.ledger.append(LedgerEntry(self.round, k, v))
            self.record.fixed += v
        events = [{"type": "overnight", "causes": [{"name": k, "amount": v} for k, v in causes.items()]}] if causes else []
        return events, rolled

    def _move(self) -> list[dict]:
        """The market moves (factor draws + any informed drift + any research-view drift), explained by factor, both paths."""
        p = self.plan
        events: list[dict] = []
        if p.move == "overnight":
            events, base = self._overnight_time()
            dt = OVERNIGHT_DT
        else:
            base, dt = self.mkt, self.regime.dt
        moves = self._moves(dt)
        self.record.moves = moves
        risk = FactorRisk(base, self.factors)
        bk = book(self.positions)
        x = risk.exposures(bk)
        self.record.x_after = x
        new = apply_moves(base, moves)
        full = bk.pv(new) - bk.pv(base)
        first = first_order_pnl(x, moves)
        for k in self.factors:
            self.ledger.append(LedgerEntry(self.round, f"market: {k}", first[k]))
        resid = full - sum(first.values())
        self.ledger.append(LedgerEntry(self.round, "convexity/cross", resid))
        q = self.inquiries[self.round]
        if q.name is not None and p.pricing:
            sd, mu = self._evidence_noise(dt)
            self.evidence.append(Evidence(q.name, 1 if q.action is ClientAction.PAYS else -1, moves["level"], sd,
                                          INFORMED_DRIFT_BP * self.regime.vol, mu))
        self.mkt = new
        self.record.pnl = sum(e.amount for e in self.ledger if e.round == self.round)
        t = self.setup.tenor
        move_t = sum(FACTORS[k].loading(t) * v for k, v in moves.items() if FACTORS[k].is_curve)
        tenor_moves = [{"tenor": k, "bp": sum(FACTORS[f].loading(k) * v for f, v in moves.items() if FACTORS[f].is_curve)} for k in (2, 5, 10, 30)]
        events.append({"type": "market", "focus_tenor": t, "move_bp": move_t, "release": p.vol_mult > 1, "tenor_moves": tenor_moves,
                       "factor_moves": [{"name": k, "value": v} for k, v in moves.items()],
                       "first_order": [{"name": k, "pnl": first[k]} for k in self.factors], "first_total": sum(first.values()),
                       "full_revaluation": full, "convexity_cross": resid})
        events.append({"type": "round_pnl", "round_pnl": self.record.pnl, "total_pnl": self.pnl_total()})
        return events

    def _evidence_noise(self, dt: float) -> tuple[float, float]:
        """(sd, mean) of the level move that is NOT the client's information: factor noise and the research view at its stated reliability."""
        sd = step_vol("level", self.regime.vol * self.plan.vol_mult, dt)
        mu = 0.0
        if self.setup.signal:
            per = self.setup.signal.view_bp / self.setup.rounds
            r = self.setup.signal.reliability
            mu = r * per
            sd = math.sqrt(sd ** 2 + r * (1 - r) * per ** 2)
        return sd, mu

    # ------------------------------------------------------------------ the end
    def policies(self) -> dict:
        return self.spec.policies or POLICIES

    def debrief_view(self, compare: bool = True):
        """The debrief as structured sections (views.DebriefView): decisions, outcome, luck, clients, same-path policies, level-5 market paths."""
        return debrief_view(self, compare)

    def debrief(self, compare: bool = True) -> list[str]:
        return debrief_lines(self.debrief_view(compare))


# ---------------------------------------------------------------------------------- many paths (level 5)

PATHS = 200


def path_pnls(ep: Episode, n: int = PATHS) -> list[float]:
    """First-order P&L of an episode's ACTUAL decisions (its exposures through each move, its edge and costs) over n alternative market
    paths drawn from the same model: new factor draws, a new realisation of the research view, new informed flags for the named clients.
    The clients, fills and decisions are held fixed: this is what your exposures could have produced, not a replay of the episode."""
    s = ep.setup
    rng = random.Random(f"{ep.spec.id}:{ep.seed}:paths")
    fixed = sum(r.fixed for r in ep.records)
    out = []
    for _ in range(n):
        right = s.signal is not None and rng.random() < s.signal.reliability
        flags = {c.name: rng.random() < CLIENT_TYPES[c.ctype].p_informed for c in s.clients}
        total = fixed
        for rec in ep.records:
            reg = rec.plan.regime or s.regime
            dt = OVERNIGHT_DT if rec.plan.move == "overnight" else reg.dt
            moves = {k: rng.gauss(0.0, 1.0) * step_vol(k, reg.vol * rec.plan.vol_mult, dt) for k in rec.x_after}
            q = rec.inquiry
            informed = flags.get(q.name, q.informed) if q.name else q.informed
            if rec.plan.pricing and informed:
                moves["level"] += (1.0 if q.action is ClientAction.PAYS else -1.0) * INFORMED_DRIFT_BP * reg.vol
            if right:
                moves["level"] += s.signal.view_bp / s.rounds
            total += sum(-rec.x_after[k] * moves[k] for k in rec.x_after)
        out.append(total)
    return out


# ---------------------------------------------------------------------------------- policies (counterfactuals and tests)

def reference_decision(ep: Episode, obs: Observation, hedge: str = "ref", ctx: DecisionContext | None = None):
    ctx = ctx or obs.ctx
    if obs.kind == "quote":
        q = ctx.reference().quote
        return QuoteDecision(q.bid, q.offer)
    if obs.kind == "rfq":
        a = assess_rfq(ctx, None)
        if a.metrics["breach"]:
            return RFQDecision(None)
        return RFQDecision(a.metrics["ref_level"])
    if obs.kind == "checkpoint":
        return CheckpointAnswer(repr(obs.part.answer))
    if hedge == "none":
        return HedgeDecision((), "Warehouse (no hedge)")
    if hedge == "full":
        tr = ctx.hedge_trade_for(1.0, ep.setup.tenor)
        return HedgeDecision((tr,) if tr else (), "Hedge 100%")
    return best_alternative(ctx, "position" if obs.kind == "position" else "hedge")


_ref_decision = reference_decision      # the name used by levels 1-2 and their tests


POLICIES: dict[str, Callable] = {
    "reference desk (model quotes, mid-appetite hedge)": lambda ep, obs: reference_decision(ep, obs, "ref"),
    "model quotes, always hedge fully": lambda ep, obs: reference_decision(ep, obs, "full"),
    "model quotes, never hedge": lambda ep, obs: reference_decision(ep, obs, "none"),
}


def run_policy(eid: str, seed: int, policy: Callable, market_seed: int | None = None, render: bool = False) -> Episode:
    ep = Episode(eid, seed, market_seed, render=render)
    while not ep.done:
        ep.submit(policy(ep, ep.observe()))
    return ep
