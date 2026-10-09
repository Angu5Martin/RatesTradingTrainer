"""Ex-ante assessment of decisions: what a decision was worth on the information available WHEN it was taken.

Nothing here can see the market path, whether a client is informed or whether a research view is right: a DecisionContext is built from
the state before the move and from what the trainee was shown (plus `Info`, which holds only observable or stated quantities: the
posterior from observed evidence, the view's STATED reliability, the announced event). Tests assess the same decisions under different
market paths, flipped informed flags and flipped view outcomes, and require identical results.

HEDGES (and level 5 POSITION decisions) are judged by EFFICIENCY, as a benchmark of sensibleness, not as a search for one optimal hedge.
Each decision is placed among alternatives built from the same state on
    E      expected P&L to the next mark: - cost of trading now - expected cost of exiting what is left later (net of client flow) - exposure
           x expected drift (inquiries from often-informed clients, a research view at its stated reliability) + carry, roll-down and funding
           when the horizon is overnight
    sigma  standard deviation of the P&L over the next step from the factor exposures (factors.py; spread factors at level 4)
and rated over a band of risk appetites R (utility E - sigma^2 / 2R): SOUND if, for some R in the band, it is close to the best alternative;
DEFENSIBLE if not far behind; POOR if clearly beaten for every R. Several decisions can be sound at once: that is the point of the band.
Errors (a hedge that adds risk, ending over a limit) are flagged as errors whatever the numbers say.

QUOTES and RFQ responses are graded primarily on DIRECTION and RELATIVE size against the stylised reference quote (quoting.make_quote),
as the quote model's own docstring requires. From level 3 the reference prices off the book's RISK-EQUIVALENT inventory in the inquiry's
tenor; at level 5 it is decomposed into inventory skew, information widening (posterior) and view lean, each reported separately.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ..engine.carry import financing_cost
from ..engine.instruments import IRSwap, Side
from ..marketmaking.flow import CLIENT_TYPES, fill_probability, improvement_bp, interdealer_half_spread_bp, street_quote
from ..marketmaking.quoting import BP, ClientAction, Quote, QuoteBreakdown, QuotingContext, make_quote
from .factors import FACTORS, FactorRisk, add, step_vol, variance
from .products import BondPosition, FuturePosition
from .serial import plain
from .state import (BASE_HALF_SPREAD_BP, INFORMED_DRIFT_BP, NEIGHBOURS, BondTrade, Desk, FuturesTrade, HedgeDecision, HedgeTrade,
                    Limits, Position, Rating, Regime, book, worst)

NETTING_INQUIRIES, P_DEAL = 4, 0.4       # the rest of the day's flow that can net a position before you would exit it
R_BAND = (0.3, 1.5)            # risk-appetite band, as multiples of the reference R (see DecisionContext.r_ref)
R_GRID = 9
SOUND_GAP, DEFENSIBLE_GAP = 0.20, 0.60      # utility gap to the best alternative, in units of the cost of a full hedge
CURVE_LEGS = (2, 30)           # an unwanted slope position is closed with a 2s30s package


@dataclass(frozen=True)
class VisibleClient:
    """What the trainee knows about an inquiry: never whether it is informed."""

    ctype: str
    action: ClientAction
    notional: float
    tenor: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class Info:
    """Observable or stated information beyond the book and the screen (levels 4-5). Never the hidden truth."""

    posterior: float | None = None      # P(the inquiring client is informed | evidence seen so far); None = use its type's prior
    signal_drift_bp: float = 0.0        # expected level move per step from the research view, at its STATED reliability
    view_bp: float = 0.0                # the research view still to play out (for the reference quote's lean)
    reliability: float = 0.0            # its stated reliability
    dt: float | None = None             # horizon of this decision, if not the regime's step (overnight)
    vol_mult: float = 1.0               # an announced event in the coming step
    overnight_to: date | None = None    # when set, carry / roll-down / funding to this date are part of E


@dataclass
class Assessment:
    kind: str
    rating: Rating
    reasons: list[str]
    expected_pnl: float = 0.0                   # ex-ante expected P&L of the decision to the next mark
    variance: float = 0.0                       # ex-ante variance of the next step's P&L
    table: list[tuple[str, float, float, Rating]] = field(default_factory=list)   # benchmark alternatives: label, E, sigma, rating
    metrics: dict = field(default_factory=dict)


class DecisionContext:
    """The state a decision is taken in. Built only from information the trainee has."""

    def __init__(self, mkt, positions: tuple[Position, ...], limit: float, regime: Regime, tenor: int,
                 client: VisibleClient | None = None, desk: Desk | None = None, info: Info | None = None, home: int | None = None):
        self.mkt, self.positions, self.regime, self.tenor, self.client = mkt, positions, regime, tenor, client
        self.desk = desk or Desk((tenor, *NEIGHBOURS[tenor]), Limits(limit))
        self.limits = self.desk.limits
        self.limit = self.limits.dv01
        self.home = home or tenor                       # the tenor whose bid/offer prices exiting a residual position
        self.info = info or Info()
        self.risk = FactorRisk(mkt, self.desk.factors)
        self.x = self.risk.exposures(book(positions))
        self._unit: dict[int, dict[str, float]] = {}
        self._uprod: dict[str, dict[str, float]] = {}
        self._mid: dict[int, float] = {}
        self._rolled = None
        self._time: dict = {}

    # ---- horizon ----
    @property
    def dt(self) -> float:
        return self.info.dt if self.info.dt is not None else self.regime.dt

    @property
    def vol(self) -> float:
        return self.regime.vol * self.info.vol_mult

    # ---- market numbers ----
    @property
    def dv01(self) -> float:
        """Parallel DV01 of the book (= its level-factor exposure: the level factor IS a parallel move)."""
        return self.x["level"]

    @property
    def slope(self) -> float:
        return self.x.get("slope", 0.0)

    def mid(self, t: int) -> float:
        if t not in self._mid:
            self._mid[t] = self.mkt.par_irs_rate(12 * t)
        return self._mid[t]

    def unit(self, t: int) -> dict[str, float]:
        """Factor exposures of RECEIVING EUR 1m of an at-market t-year swap."""
        if t not in self._unit:
            s = IRSwap.new(Side.RECEIVE, 1e6, self.mid(t), self.mkt.spot, 12 * t)
            self._unit[t] = self.risk.exposures(s)
        return self._unit[t]

    def unit_product(self, code: str) -> dict[str, float]:
        """Factor exposures of BUYING one futures contract, or EUR 1m face of a bond."""
        if code not in self._uprod:
            self._uprod[code] = self.risk.exposures(self.product_position(code, 1.0))
        return self._uprod[code]

    def product_position(self, code: str, qty: float):
        p = self.desk.product(code)
        if p.kind == "future":
            return FuturePosition(p.obj, qty, code)
        return BondPosition(p.obj, qty * 1e6, code)

    def dv01_per_m(self, t: int) -> float:
        return self.unit(t)["level"]

    def base_hs(self, t: int) -> float:
        return BASE_HALF_SPREAD_BP[t]

    def id_hs(self, t: int, now: bool = True) -> float:
        """Half the interdealer bid/offer in t-year swaps (bp): what crossing it costs NOW (session effect included), or later (normal)."""
        hs = interdealer_half_spread_bp(self.base_hs(t), self.regime.vol, self.regime.liquidity)
        return hs * (self.regime.swap_cost_mult if now else 1.0)

    def swap_cost(self, t: int, dv01_abs: float, now: bool = True) -> float:
        """EUR cost of hedging |DV01| in t-year swaps: half the spread, times the late-session impact factor when trading now."""
        depth = self.regime.swap_depth_dv01
        impact = (1.0 + dv01_abs / depth) if (now and depth) else 1.0
        return self.id_hs(t, now) * dv01_abs * impact

    def product_cost(self, code: str, qty: float) -> float:
        """EUR cost of crossing half the bid/offer on `qty` contracts (futures) or EUR m face (bond)."""
        p = self.desk.product(code)
        per = p.half_spread * (1000.0 if p.kind == "future" else 1e4)     # price points x EUR per point per contract / per EUR 1m face
        return abs(qty) * per

    def street(self, t: int | None = None) -> Quote:
        t = t or self.tenor
        return street_quote(self.mid(t), self.base_hs(t), self.regime.vol, self.regime.liquidity, self.regime.informed_share)

    def expected_flow_dv01(self) -> float:
        """Signed DV01 the desk expects to acquire from expected client flow (+ = clients pay, you get longer)."""
        ef = self.regime.expected_flow
        if not ef:
            return 0.0
        sign = 1.0 if ef.action is ClientAction.PAYS else -1.0
        return sign * ef.probability * ef.notional / 1e6 * self.dv01_per_m(self.home)

    def factor_vols(self) -> dict[str, float]:
        return {k: step_vol(k, self.vol, self.dt) for k in self.desk.factors}

    def risk_equivalent(self, t: int) -> float:
        """DV01 in tenor t that best matches the book's risk: the variance-minimising position, Cov(book, swap t) / Var(swap t)."""
        u, v = self.unit(t), self.factor_vols()
        den = sum((u[k] * v[k]) ** 2 for k in v)
        return sum(self.x[k] * u[k] * v[k] ** 2 for k in v) / den * u["level"] if den else 0.0

    def inventory_for_quote(self, t: int) -> float:
        return self.risk_equivalent(t) if self.desk.multi_tenor else self.dv01

    def reference(self, adverse: float | None = None, t: int | None = None, view: bool = True) -> QuoteBreakdown:
        t = t or self.tenor
        return make_quote(QuotingContext(
            fair_value=self.mid(t), base_half_spread_bp=self.base_hs(t), inventory_dv01=self.inventory_for_quote(t),
            dv01_limit=self.limit, vol_multiplier=self.regime.vol, liquidity=self.regime.liquidity,
            adverse_selection=self.regime.informed_share if adverse is None else adverse,
            expected_flow_dv01=self.expected_flow_dv01(),
            view_bp=self.info.view_bp if view else 0.0, conviction=self.info.reliability if view else 0.0))

    def p_informed(self) -> float:
        """The probability the current inquiry is informed, from what is known: the posterior if there is evidence, else the type's prior."""
        c = self.client
        if c is None:
            return 0.0
        return self.info.posterior if self.info.posterior is not None else CLIENT_TYPES[c.ctype].p_informed

    def pending_drift_bp(self) -> float:
        """Expected level move before the next mark: from the inquiry just seen, plus any research view at its stated reliability."""
        drift = self.info.signal_drift_bp
        c = self.client
        if c is not None:
            sign = 1.0 if c.action is ClientAction.PAYS else -1.0       # a payer profits if rates rise
            drift += sign * self.p_informed() * INFORMED_DRIFT_BP * self.regime.vol
        return drift

    def trade_dv01(self, action: ClientAction, notional: float, t: int | None = None) -> float:
        """Signed DV01 the dealer acquires if the client trades."""
        t = t or self.tenor
        return (1.0 if action.dealer_side is Side.RECEIVE else -1.0) * notional / 1e6 * self.dv01_per_m(t)

    def trade_exposure(self, action: ClientAction, notional: float, t: int | None = None) -> dict[str, float]:
        t = t or self.tenor
        s = (1.0 if action.dealer_side is Side.RECEIVE else -1.0) * notional / 1e6
        return {k: s * v for k, v in self.unit(t).items()}

    # ---- hedging ----
    def hedge_trade_for(self, fraction: float, t: int) -> HedgeTrade | None:
        """The trade that removes `fraction` of the book's parallel DV01 using an at-market t-year swap."""
        target = -fraction * self.dv01
        if abs(target) < 0.002 * self.limit:          # nothing worth trading
            return None
        return HedgeTrade(t, Side.RECEIVE if target > 0 else Side.PAY, abs(target) / self.dv01_per_m(t) * 1e6)

    def product_trade_for(self, fraction: float, code: str):
        """Contracts (futures) or EUR face (bond) that remove `fraction` of the book's parallel DV01."""
        per = self.unit_product(code)["level"]
        qty = -fraction * self.dv01 / per
        if abs(fraction * self.dv01) < 0.002 * self.limit:
            return None
        p = self.desk.product(code)
        return FuturesTrade(code, qty) if p.kind == "future" else BondTrade(code, qty * 1e6)

    def trade_effect(self, tr) -> tuple[dict[str, float], float]:
        """(factor exposures added, cost now) of one hedge trade."""
        if isinstance(tr, HedgeTrade):
            s = (1.0 if tr.side is Side.RECEIVE else -1.0) * tr.notional / 1e6
            return {k: s * v for k, v in self.unit(tr.tenor).items()}, self.swap_cost(tr.tenor, abs(s * self.dv01_per_m(tr.tenor)))
        if isinstance(tr, FuturesTrade):
            return {k: tr.contracts * v for k, v in self.unit_product(tr.code).items()}, self.product_cost(tr.code, tr.contracts)
        q = tr.face / 1e6
        return {k: q * v for k, v in self.unit_product(tr.code).items()}, self.product_cost(tr.code, q)

    def after(self, decision: HedgeDecision) -> tuple[dict[str, float], float]:
        """Factor exposures after the decision, and its cost (half the bid/offer of each leg)."""
        x, cost = dict(self.x), 0.0
        for tr in decision.trades:
            dx, c = self.trade_effect(tr)
            x = add(x, dx)
            cost += c
        return x, cost

    def level_and_slope_hedge(self, other: int, first: int | None = None) -> HedgeDecision | None:
        """Two at-market swaps (`first`, default the focus tenor, and `other`) that remove both the level and the slope exposure."""
        first = first or self.tenor
        a, b = self.unit(first), self.unit(other)
        det = a["level"] * b["slope"] - b["level"] * a["slope"]
        if abs(det) < 1e-9:
            return None
        xl, xs = -self.x["level"], -self.x["slope"]
        na = (xl * b["slope"] - b["level"] * xs) / det           # EUR m of receiver in each tenor
        nb = (a["level"] * xs - a["slope"] * xl) / det
        trades = tuple(HedgeTrade(t, Side.RECEIVE if n > 0 else Side.PAY, abs(n) * 1e6) for t, n in ((first, na), (other, nb))
                       if abs(n) * 1e6 >= 1e5)
        return HedgeDecision(trades, f"Hedge level and curve ({first}Y + {other}Y)") if trades else None

    def flatten_curve_hedge(self, tenors: tuple[int, int, int] | None = None) -> HedgeDecision | None:
        """Three swaps that remove level, slope and curvature together: the cheapest such triple from the hedge tenors."""
        from itertools import combinations

        from ..engine.numerics import solve_linear
        ks = ("level", "slope", "curvature")
        best = None
        for triple in ([tenors] if tenors else combinations(self.desk.hedge_tenors, 3)):
            m = [[self.unit(t)[k] for t in triple] for k in ks]
            try:
                n = solve_linear(m, [-self.x[k] for k in ks])
            except Exception:
                continue
            trades = tuple(HedgeTrade(t, Side.RECEIVE if q > 0 else Side.PAY, abs(q) * 1e6) for t, q in zip(triple, n) if abs(q) * 1e6 >= 1e5)
            if not trades:
                continue
            d = HedgeDecision(trades, "Flatten level, slope and curvature (" + " + ".join(f"{t}Y" for t in triple) + ")")
            if best is None or self.after(d)[1] < self.after(best)[1]:
                best = d
        return best

    def future_flow(self) -> tuple[float, float]:
        """(mean, standard deviation) of the net DV01 the rest of the day's clients will leave you with, before you would exit.

        A stated assumption of the trainer: NETTING_INQUIRIES more typical inquiries, each dealing with you with probability P_DEAL,
        on the side mix of today's flow; the mean also carries the desk's expected flow."""
        typical = abs(self.trade_dv01(ClientAction.PAYS, self.regime.typical_notional, self.home))
        n = NETTING_INQUIRIES * P_DEAL
        drift = (2 * self.regime.p_pays - 1) * n * typical
        return self.expected_flow_dv01() + drift, typical * math.sqrt(n)

    def exit_cost(self, level: float) -> float:
        """Expected cost, caused by keeping `level` now, of exiting the net position later:
            c x (E|level + N| - E|N|),   N ~ Normal(future flow)
        Small positions are mostly netted away by two-way flow (the cost is nearly zero); large ones cost almost c x |level|; flow
        expected on the opposite side lowers it, on the same side raises it."""
        mu, sd = self.future_flow()
        c = self.id_hs(self.home, now=False)
        return c * max(0.0, _abs_normal(level + mu, sd) - _abs_normal(mu, sd))

    def absorbed(self, level: float) -> float:
        """The part of a position the assessment expects client flow to net away: |level| - exit cost / c."""
        return max(0.0, abs(level) - self.exit_cost(level) / self.id_hs(self.home, now=False))

    def other_exit_cost(self, x: dict[str, float]) -> float:
        """Exiting what client flow does not net: a curve position (multi-tenor desks: a 2s30s package) and a swap-spread position
        (desks with products: unwind the product hedge and replace it with swaps)."""
        cost = 0.0
        if self.desk.multi_tenor or self.limits.slope is not None:
            cost += sum(self.id_hs(t, now=False) for t in CURVE_LEGS) / 2 * abs(x.get("slope", 0.0))
        if "swap_spread" in x and self.desk.products:
            fut = next((p for p in self.desk.products if p.kind == "future"), None)
            per_dv01 = (self.product_cost(fut.code, 1.0) / abs(self.unit_product(fut.code)["level"])) if fut else 0.0
            cost += (per_dv01 + self.id_hs(self.home, now=False)) * abs(x["swap_spread"])
        return cost

    def r_ref(self) -> float:
        """Reference risk appetite R (utility E - sigma^2/2R): the one-step, normal-vol P&L risk of a book at its limit.

        At R a trader would pay about half of a full-limit book's one-step sigma to remove it, and much less for small positions (the
        penalty is quadratic). The band R_BAND runs from cautious (0.3 R) to relaxed (1.5 R). It is a stated assumption of the trainer."""
        return self.limit * FACTORS["level"].vol_bp_day * math.sqrt(self.dt)

    def curve_position(self, x: dict[str, float] | None = None) -> float:
        """Slope exposure BEYOND what an outright position in the focus tenor carries (EUR per bp of slope): a curve trade."""
        x = self.x if x is None else x
        return x.get("slope", 0.0) - FACTORS["slope"].loading(self.tenor) * x["level"]

    # ---- time (overnight decisions) ----
    def _time_of(self, inst) -> float:
        """Carry + roll-down + funding of an instrument to the overnight date on an unchanged curve (static roll)."""
        if self.info.overnight_to is None:
            return 0.0
        if self._rolled is None:
            self._rolled = self.mkt.rolled(self.info.overnight_to, "static")
        out = inst.pv(self._rolled) - inst.pv(self.mkt)
        if isinstance(inst, BondPosition):
            out -= financing_cost(inst.materialise(self.mkt), self.mkt, self.info.overnight_to)
        return out

    def time_pnl(self, decision: HedgeDecision | None = None) -> float:
        if self.info.overnight_to is None:
            return 0.0
        if "book" not in self._time:
            self._time["book"] = sum(self._time_of(p.inst) for p in self.positions)
        total = self._time["book"]
        for tr in (decision.trades if decision else ()):
            if isinstance(tr, HedgeTrade):
                key = ("swap", tr.tenor)
                if key not in self._time:
                    self._time[key] = self._time_of(IRSwap.new(Side.RECEIVE, 1e6, self.mid(tr.tenor), self.mkt.spot, 12 * tr.tenor))
                total += (1.0 if tr.side is Side.RECEIVE else -1.0) * tr.notional / 1e6 * self._time[key]
            else:
                key = ("product", tr.code)
                if key not in self._time:
                    self._time[key] = self._time_of(self.product_position(tr.code, 1.0))
                total += (tr.contracts if isinstance(tr, FuturesTrade) else tr.face / 1e6) * self._time[key]
        return total

    def hedge_value(self, decision: HedgeDecision) -> tuple[float, float, dict[str, float], float]:
        """(E, variance, exposures after, cost now)."""
        x, cost = self.after(decision)
        level = x["level"]
        e = -cost - self.exit_cost(level) - self.other_exit_cost(x) - level * self.pending_drift_bp() + self.time_pnl(decision)
        return e, variance(x, self.vol, self.dt), x, cost


def _abs_normal(m: float, s: float) -> float:
    """E|X| for X ~ Normal(m, s^2)."""
    if s <= 0:
        return abs(m)
    z = m / s
    return s * math.sqrt(2 / math.pi) * math.exp(-0.5 * z * z) + m * math.erf(z / math.sqrt(2))


def _sd(var: float) -> str:
    return f"sigma €{math.sqrt(max(var, 0.0)):,.0f}"


# ------------------------------------------------------------------------------------------------- alternatives

def _hedge_alternatives(ctx: DecisionContext, kind: str = "hedge") -> list[HedgeDecision]:
    if kind == "position":
        return _position_alternatives(ctx)
    out = [HedgeDecision((), "Warehouse (no hedge)")]
    if ctx.desk.multi_tenor:
        for t in ctx.desk.hedge_tenors:
            for f in (0.5, 1.0):
                tr = ctx.hedge_trade_for(f, t)
                if tr:
                    out.append(HedgeDecision((tr,), f"Hedge {f:.0%} of the level in the {t}Y"))
        pairs = [(10, 30), (10, 2), (5, 30), (2, 30)]
        best = sorted((d for d in (ctx.level_and_slope_hedge(b, a) for a, b in pairs) if d), key=lambda d: ctx.after(d)[1])[:2]
        out += best
        flat = ctx.flatten_curve_hedge()
        if flat:
            out.append(flat)
    else:
        for f in (0.25, 0.5, 0.75, 1.0):
            tr = ctx.hedge_trade_for(f, ctx.tenor)
            if tr:
                out.append(HedgeDecision((tr,), f"Hedge {f:.0%} in the {ctx.tenor}Y"))
        for n in NEIGHBOURS[ctx.tenor]:
            tr = ctx.hedge_trade_for(1.0, n)
            if tr:
                out.append(HedgeDecision((tr,), f"Hedge 100% in the {n}Y"))
        if abs(ctx.curve_position()) > 0.05 * ctx.limit:
            best = None
            for n in NEIGHBOURS[ctx.tenor]:
                d = ctx.level_and_slope_hedge(n)
                if d and (best is None or ctx.after(d)[1] < ctx.after(best)[1]):
                    best = d
            if best:
                out.append(best)
    for p in ctx.desk.products:
        tr = ctx.product_trade_for(1.0, p.code)
        if tr:
            out.append(HedgeDecision((tr,), f"Hedge 100% with {p.label}"))
    held = _held_products(ctx)
    if held:
        out.append(_switch_decision(ctx, held))
    return out


def _held_products(ctx: DecisionContext) -> dict[str, float]:
    """Net product positions held: {code: contracts or EUR m face}."""
    held: dict[str, float] = {}
    for p in ctx.positions:
        if isinstance(p.inst, FuturePosition):
            held[p.inst.code] = held.get(p.inst.code, 0.0) + p.inst.contracts
        elif isinstance(p.inst, BondPosition):
            held[p.inst.code] = held.get(p.inst.code, 0.0) + p.inst.face / 1e6
    return {k: v for k, v in held.items() if abs(v) > 1e-9}


def _switch_decision(ctx: DecisionContext, held: dict[str, float], t: int | None = None) -> HedgeDecision:
    """Close every product hedge and replace its DV01 with swaps in the home tenor."""
    t = t or ctx.home
    trades, level = [], 0.0
    for code, q in held.items():
        p = ctx.desk.product(code)
        trades.append(FuturesTrade(code, -q) if p.kind == "future" else BondTrade(code, -q * 1e6))
        level += q * ctx.unit_product(code)["level"]
    if abs(level) > 1e-9:
        trades.append(HedgeTrade(t, Side.RECEIVE if level > 0 else Side.PAY, abs(level) / ctx.dv01_per_m(t) * 1e6))
    return HedgeDecision(tuple(trades), f"Switch the product hedges into {t}Y swaps")


def _position_alternatives(ctx: DecisionContext) -> list[HedgeDecision]:
    """Level 5: what level of DV01 to run into the next step, in the focus tenor."""
    out = [HedgeDecision((), "Keep the book as it is")]
    for f in (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0):
        target = f * ctx.limit * 0.95
        change = target - ctx.dv01
        if abs(change) < 0.01 * ctx.limit:
            continue
        tr = HedgeTrade(ctx.tenor, Side.RECEIVE if change > 0 else Side.PAY, abs(change) / ctx.dv01_per_m(ctx.tenor) * 1e6)
        out.append(HedgeDecision((tr,), f"Run {'flat' if f == 0 else f'{target / 1e3:+,.0f}k DV01'}"))
    return out


# ------------------------------------------------------------------------------------------------- hedge / position assessment

def _rate_by_band(utilities: list[list[float]], i: int, scale: float) -> tuple[Rating, float]:
    """utilities[c][r]: alternative c at appetite r. Rating of alternative i, and its smallest gap to the best (in units of `scale`,
    the cost of a full hedge: the natural money unit of a hedging decision) over the band of appetites."""
    best_gap = math.inf
    for r in range(len(utilities[0])):
        col = [u[r] for u in utilities]
        best_gap = min(best_gap, (max(col) - col[i]) / scale)
    rating = Rating.SOUND if best_gap <= SOUND_GAP else (Rating.DEFENSIBLE if best_gap <= DEFENSIBLE_GAP else Rating.POOR)
    return rating, best_gap


def best_alternative(ctx: DecisionContext, kind: str = "hedge") -> HedgeDecision:
    """The alternative with the best utility at the middle of the appetite band (the reference desk's choice)."""
    r = ctx.r_ref()
    return max(_hedge_alternatives(ctx, kind), key=lambda a: (lambda e, v, *_: e - v / (2 * r))(*ctx.hedge_value(a)))


def assess_hedge(ctx: DecisionContext, decision: HedgeDecision, kind: str = "hedge") -> Assessment:
    alts = _hedge_alternatives(ctx, kind)
    rs = [ctx.r_ref() * math.exp(math.log(R_BAND[0]) + (math.log(R_BAND[1]) - math.log(R_BAND[0])) * k / (R_GRID - 1))
          for k in range(R_GRID)]
    values = [ctx.hedge_value(a) for a in alts] + [ctx.hedge_value(decision)]
    utilities = [[e - v / (2 * r) for r in rs] for e, v, _, _ in values]
    scale = ctx.id_hs(ctx.home, now=False) * max(abs(ctx.dv01), abs(ctx.curve_position()), 0.1 * ctx.limit)
    table = []
    for k, a in enumerate(alts):
        rating, _ = _rate_by_band(utilities, k, scale)
        e, v, x, _ = values[k]
        table.append((a.label, e, math.sqrt(v), rating))
    rating, gap = _rate_by_band(utilities, len(alts), scale)
    e, v, x, cost = values[-1]
    level0, level1 = ctx.dv01, x["level"]
    reasons = [f"Your choice: cost now €{cost:,.0f}, risk over the next step {_sd(v)} (keeping the book as it is: {_sd(table[0][2] ** 2)})."]
    if kind != "position" and decision.trades and abs(level1) > abs(level0) + 0.02 * ctx.limit and level0 * (level1 - level0) > 0:
        rating = Rating.ERROR
        reasons.append(f"The hedge ADDS to your risk: DV01 goes from {level0:+,.0f} to {level1:+,.0f}. To reduce a "
                       f"{'long' if level0 > 0 else 'short'} you {'pay' if level0 > 0 else 'receive'} fixed (or sell futures / bonds).")
    if abs(level1) > ctx.limit:
        rating = Rating.ERROR
        reasons.append(f"You end over your DV01 limit ({abs(level1):,.0f} against {ctx.limit:,.0f}). A limit is not a view: get back inside it.")
    if ctx.limits.slope is not None and abs(x.get("slope", 0.0)) > ctx.limits.slope:
        rating = Rating.ERROR
        reasons.append(f"You end over your curve limit (slope exposure {abs(x['slope']):,.0f} against {ctx.limits.slope:,.0f}).")
    if rating is not Rating.ERROR:
        best = max(range(len(alts)), key=lambda k: utilities[k][R_GRID // 2])
        reasons.insert(0, {Rating.SOUND: "A reasonable trade-off for a reasonable risk appetite.",
                           Rating.DEFENSIBLE: "Defensible, but another choice gives a clearly better balance of cost and risk for any appetite in the range.",
                           Rating.POOR: "Clearly beaten: another choice costs less, or removes much more risk for little extra cost, whatever your risk appetite."}[rating]
                       + f" For a middle-of-the-range appetite the best balance is: {alts[best].label.lower()}.")
        curve = x.get("slope", 0.0) if ctx.desk.multi_tenor else ctx.curve_position(x)
        if abs(curve) > 0.05 * ctx.limit:
            reasons.append(f"You are left with a curve position: {curve:+,.0f} EUR per bp of slope"
                           + ("" if ctx.desk.multi_tenor else " beyond your outright risk")
                           + ". A DV01 hedge in another tenor hedges the level, not the curve.")
        if "swap_spread" in x and abs(x["swap_spread"]) > 0.05 * ctx.limit:
            reasons.append(f"You are left with swap-spread risk: {x['swap_spread']:+,.0f} EUR per bp of ASW tightening. Futures and bonds hedge rates, "
                           "but they are not swaps: if bonds cheapen against swaps your hedge underperforms.")
        if ctx.client and ctx.p_informed() >= 0.3 and abs(level1) > 0.2 * ctx.limit and level1 * ctx.pending_drift_bp() > 0:
            reasons.append("The client that just traded may well be informed, and its trade points the market against what you are keeping: "
                           f"an expected adverse move of about {abs(ctx.pending_drift_bp()):.2f}bp.")
        if ctx.info.signal_drift_bp and abs(level1) > 0.1 * ctx.limit:
            with_view = level1 * ctx.info.signal_drift_bp < 0
            reasons.append(f"The research view (stated reliability {ctx.info.reliability:.0%}) points the market "
                           + ("in your favour" if with_view else "against your position") + f": about {abs(ctx.info.signal_drift_bp):.2f}bp expected this step.")
        if ctx.info.vol_mult > 1 and abs(level1) > 0.3 * ctx.limit:
            reasons.append(f"The next step contains the release (vol x{ctx.info.vol_mult:g}): risk kept through it costs {ctx.info.vol_mult:g}x as much sigma.")
        if ctx.info.overnight_to is not None:
            reasons.append(f"Overnight carry, roll-down and funding of the book you keep: {ctx.time_pnl(decision):+,.0f} EUR on an unchanged curve.")
        if kind != "position" and abs(level1) > 0.05 * ctx.limit:
            share = ctx.absorbed(level1) / abs(level1) if abs(level1) > 1 else 0.0
            if share > 0.25:
                reasons.append(f"Client flow over the rest of the day should net away roughly {share:.0%} of what you keep: that is the case for "
                               "warehousing it rather than paying to hedge it now.")
    metrics = {"dv01_before": level0, "dv01_after": level1, "cost": cost, "sigma": math.sqrt(v), "exposures": x,
               "gap": gap, "r_ref": ctx.r_ref(), "curve_after": ctx.curve_position(x), "slope_after": x.get("slope", 0.0)}
    return Assessment(kind, rating, reasons, e, v, table, metrics)


# ------------------------------------------------------------------------------------------------- quotes

def _expected_quote_value(ctx: DecisionContext, q: Quote) -> dict:
    """Expected consequences of a two-way quote for the next inquiry, over the client mix and both sides."""
    st = ctx.street()
    mid = ctx.mid(ctx.tenor)
    out, total_w = {"E": 0.0, "E2": 0.0}, sum(w for _, w in ctx.regime.client_mix)
    for action, p_side in ((ClientAction.PAYS, ctx.regime.p_pays), (ClientAction.RECEIVES, 1 - ctx.regime.p_pays)):
        edge_bp = (q.offer - mid) / BP if action is ClientAction.PAYS else (mid - q.bid) / BP
        dv = abs(ctx.trade_dv01(action, ctx.regime.typical_notional))
        p_fill = 0.0
        for t, w in ctx.regime.client_mix:
            ct = CLIENT_TYPES[t]
            pf = fill_probability(ct, improvement_bp(action, q, st))
            p_fill += w / total_w * pf
            value = (edge_bp - ct.p_informed * INFORMED_DRIFT_BP * ctx.regime.vol) * dv
            out["E"] += p_side * w / total_w * pf * value
            out["E2"] += p_side * w / total_w * pf * value ** 2
        out[action] = p_fill
    out["var"] = max(0.0, out["E2"] - out["E"] ** 2)
    return out


def assess_quote(ctx: DecisionContext, q: Quote) -> Assessment:
    ref = ctx.reference()
    st = ctx.street()
    mid = ctx.mid(ctx.tenor)
    hs = ctx.base_hs(ctx.tenor)
    shift = (q.mid - mid) / BP
    width = q.width_bp / 2
    ref_width = (ref.bid_half_width_bp + ref.offer_half_width_bp) / 2
    reasons, parts = [], []
    if q.bid >= st.offer or q.offer <= st.bid:
        reasons.append("Your market crosses the street's: other dealers can trade with you and lay the risk off at a profit straight away.")
        parts.append(Rating.ERROR)
    r = ref.net_shift_bp
    pressure = "long" if ctx.inventory_for_quote(ctx.tenor) + 0.5 * ctx.expected_flow_dv01() > 0 else "short"
    view_part = ref.view_skew_bp
    risk_part = ref.inventory_skew_bp + ref.flow_skew_bp
    why_dir = ("your view" if abs(view_part) > abs(risk_part) else f"your {pressure} risk")
    if abs(r) >= 0.05:
        if shift * r > 0 and abs(shift) >= 0.02:
            parts.append(Rating.SOUND)
            reasons.append(f"Skew in the right direction: {'higher' if r > 0 else 'lower'}, because of {why_dir} "
                           f"({'clients who receive fixed hit your bid' if r > 0 else 'clients who pay fixed lift your offer'}).")
        elif abs(shift) < 0.02:
            parts.append(Rating.DEFENSIBLE)
            reasons.append(f"No skew: given {why_dir} you would normally quote {'higher' if r > 0 else 'lower'}.")
        else:
            parts.append(Rating.POOR)
            reasons.append(f"Skewed the wrong way: given {why_dir} you should quote {'HIGHER' if r > 0 else 'LOWER'}. "
                           "Your skew attracts the trade you do not want.")
    else:
        if abs(shift) <= max(0.1, hs):
            parts.append(Rating.SOUND)
            reasons.append("Little inventory pressure, and your market is close to centred: fine.")
        else:
            parts.append(Rating.DEFENSIBLE)
            reasons.append(f"A {shift:+.2f}bp skew without much inventory to work: it costs you flow on one side for no risk reason.")
    ratio = width / ref_width
    if 0.6 <= ratio <= 1.8:
        parts.append(Rating.SOUND)
    elif 0.35 <= ratio <= 3.0:
        parts.append(Rating.DEFENSIBLE)
        reasons.append(f"Width {width:.2f}bp a side against about {ref_width:.2f}bp for today's conditions: "
                       + ("tight: you are paying for flow with edge." if ratio < 1 else "wide: you will see little flow."))
    else:
        parts.append(Rating.POOR)
        reasons.append(f"Width {width:.2f}bp a side against about {ref_width:.2f}bp for today's conditions: "
                       + ("far too tight for the vol, liquidity and flow quality." if ratio < 1 else "so wide you are not really making a market."))
    if ctx.info.reliability:
        reasons.append(f"Reference decomposition: inventory and flow skew {risk_part:+.2f}bp, view lean {view_part:+.2f}bp (view at its stated reliability).")
    yours, refv = _expected_quote_value(ctx, q), _expected_quote_value(ctx, ref.quote)
    metrics = {"shift_bp": shift, "half_width_bp": width, "ref": plain(ref), "street": plain(st),
               "p_fill_pays": yours[ClientAction.PAYS], "p_fill_receives": yours[ClientAction.RECEIVES],
               "ref_p_fill_pays": refv[ClientAction.PAYS], "ref_p_fill_receives": refv[ClientAction.RECEIVES],
               "E_ref": refv["E"]}
    return Assessment("quote", worst(*parts), reasons, yours["E"], yours["var"], [], metrics)


def assess_rfq(ctx: DecisionContext, level: float | None) -> Assessment:
    c = ctx.client
    assert c is not None
    ct = CLIENT_TYPES[c.ctype]
    t = c.tenor or ctx.tenor
    mid = ctx.mid(t)
    hs = ctx.base_hs(t)
    st = ctx.street(t)
    sign = 1.0 if c.action is ClientAction.PAYS else -1.0            # client pays -> you receive: a HIGHER rate is better for you
    p_inf = ctx.p_informed()
    ref = ctx.reference(adverse=p_inf, t=t)
    ref_level = ref.quote.client_rate(c.action)
    ref_charge = sign * (ref_level - mid) / BP
    trade = ctx.trade_dv01(c.action, c.notional, t)
    dx = ctx.trade_exposure(c.action, c.notional, t)
    x_after = add(ctx.x, dx)
    after = x_after["level"]
    if ctx.desk.multi_tenor:
        v_before, v_after = variance(ctx.x, ctx.vol, ctx.dt), variance(x_after, ctx.vol, ctx.dt)
        reduces = v_after < v_before and v_before > (0.05 * ctx.limit * FACTORS["level"].vol_bp_day * math.sqrt(ctx.dt)) ** 2
    else:
        reduces = ctx.dv01 * trade < 0 and abs(ctx.dv01) > 0.05 * ctx.limit
    # a breach is a trade that creates or worsens a limit excess (one that shrinks an existing excess is not)
    breach = (abs(after) > ctx.limit and abs(after) > abs(ctx.dv01)) or (
        ctx.limits.slope is not None and abs(x_after.get("slope", 0.0)) > ctx.limits.slope and abs(x_after.get("slope", 0.0)) > abs(ctx.slope))
    util_after = max(abs(after) / ctx.limit, abs(x_after.get("slope", 0.0)) / ctx.limits.slope if ctx.limits.slope else 0.0)
    street_level = st.client_rate(c.action)
    adverse = p_inf * INFORMED_DRIFT_BP * ctx.regime.vol
    reasons: list[str] = []

    def p_win(lv: float) -> float:
        imp = sign * (street_level - lv) / BP
        return fill_probability(ct, imp)

    if level is None:
        if breach:
            rating, why = Rating.SOUND, "Passing keeps you inside your limits."
        elif reduces:
            rating, why = Rating.POOR, "You passed on an axe: this client wanted to take risk OFF you and would have paid a spread to do it."
        elif p_inf >= 0.4:
            rating, why = Rating.DEFENSIBLE, ("Passing on flow that may be informed protects you, but it also gives up the edge and the relationship; "
                                              "a wider price does the same job.")
        elif util_after > 0.6:
            rating, why = Rating.DEFENSIBLE, "Passing on risk-adding flow when you are already well into your limit is defensible; a wider price also works."
        else:
            rating, why = Rating.POOR, "You are paid to make prices: this trade is well within your limits, so price it (wider if you must) rather than pass."
        reasons.append(why)
        e, charge, pw, fill_var = 0.0, None, 0.0, 0.0
    else:
        charge = sign * (level - mid) / BP
        diff = charge - ref_charge
        pw = p_win(level)
        e = pw * (charge - adverse) * abs(trade)
        fill_var = pw * (1 - pw) * ((charge - adverse) * abs(trade)) ** 2
        sound_band, def_band = 0.5 * hs + 0.05, 1.5 * hs + 0.05
        if breach and charge < ref_charge + 0.2:
            rating = Rating.POOR
            reasons.append("If this fills you are over a limit. Pass, or price it wide and plan the hedge.")
        elif reduces and -ctx.id_hs(t) - 0.05 <= charge <= ref_charge + sound_band:
            rating = Rating.SOUND
            reasons.append("This trade takes risk off your book, and you priced to win it: being aggressive on an axe is cheaper than hedging in the street.")
        elif reduces and charge < -ctx.id_hs(t) - 0.05:
            rating = Rating.DEFENSIBLE
            reasons.append(f"You want this trade, but you priced {abs(charge):.2f}bp through mid: more than the {ctx.id_hs(t):.2f}bp it would cost to lay the "
                           "risk off in the street.")
        elif not reduces and util_after > 0.6 and diff >= -sound_band:
            rating = Rating.SOUND
            reasons.append("Risk-adding trade with your limit getting full: pricing it wide is the right instinct.")
        elif abs(diff) <= sound_band:
            rating = Rating.SOUND
            reasons.append("A price in line with your book, the conditions and what you know about this client.")
        elif abs(diff) <= def_band:
            rating = Rating.DEFENSIBLE
            reasons.append(("Tighter" if diff < 0 else "Wider") + f" than the conditions suggest by {abs(diff):.2f}bp: "
                           + ("you will win more, but give away edge." if diff < 0 else "you will win less often."))
        else:
            rating = Rating.POOR
            reasons.append(("Much tighter" if diff < 0 else "Much wider") + f" than the conditions suggest ({diff:+.2f}bp): "
                           + ("you are paying this client to take its trade." if diff < 0 else "you are effectively not making a price."))
        if charge < 0 and not reduces:
            rating = Rating.POOR
            reasons.append("You priced THROUGH mid on a trade that adds to your risk: you pay to take risk you do not want.")
        if p_inf >= 0.4 and diff < 0:
            reasons.append("What you know about this client says it may well be informed: tight prices to it tend to be followed by moves against you.")
        if ctx.desk.multi_tenor and reduces and ctx.dv01 * trade > 0 and abs(ctx.dv01) > 0.1 * ctx.limit:
            reasons.append(f"Although it adds to your DV01, this {t}Y trade REDUCES your book's risk: it offsets your curve exposure. "
                           f"Your book behaves like {ctx.risk_equivalent(t):+,.0f} of {t}Y DV01.")
        elif ctx.desk.multi_tenor and not reduces and ctx.dv01 * trade < 0 and abs(ctx.dv01) > 0.1 * ctx.limit:
            reasons.append(f"Although it cuts your DV01, this {t}Y trade ADDS to your book's risk once the curve is counted: your book behaves like "
                           f"{ctx.risk_equivalent(t):+,.0f} of {t}Y DV01.")
    metrics = {"ref_level": ref_level, "ref_charge": ref_charge, "charge": charge, "street_level": street_level, "p_win": pw,
               "p_win_ref": p_win(ref_level), "trade_dv01": trade, "dv01_after": after, "reduces": reduces, "breach": breach,
               "x_after": x_after, "p_informed": p_inf}
    if ctx.info.reliability or ctx.info.posterior is not None:
        inv_only = ctx.reference(adverse=ctx.regime.informed_share, t=t, view=False)
        no_view = ctx.reference(adverse=p_inf, t=t, view=False)
        parts = {"inventory": sign * (inv_only.quote.client_rate(c.action) - mid) / BP,
                 "information": sign * (no_view.quote.client_rate(c.action) - inv_only.quote.client_rate(c.action)) / BP,
                 "view": sign * (ref_level - no_view.quote.client_rate(c.action)) / BP}
        metrics["decomposition"] = parts
        reasons.append(f"Reference charge {ref_charge:+.2f}bp = inventory and flow {parts['inventory']:+.2f} + information {parts['information']:+.2f} "
                       f"(P(informed) {p_inf:.0%} from the evidence) + view lean {parts['view']:+.2f}.")
        if level is not None and p_inf >= 0.5 and charge is not None and charge < parts["inventory"] - 0.05 and rating is Rating.SOUND:
            rating = Rating.DEFENSIBLE
            reasons.append("The evidence on this client argued for a wider price than your inventory alone would give; you priced tighter.")
    return Assessment("rfq", rating, reasons, e, fill_var, [], metrics)
