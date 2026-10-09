"""The public view-models: everything a frontend is allowed to know, as plain JSON-ready dicts.

    ObservationView   what the trainee sees and is asked at the current decision (Episode -> observation_view)
    StepResultView    what happened after a decision: events, the ex-ante assessment, any checkpoint grade (step_result_view)
    AssessmentView    rating, reasons, benchmark table and metrics as plain data (assessment_view)
    DebriefView       the four-part debrief as structured sections (debrief_view)

(Additive since the first UI milestone: the `market` event carries `tenor_moves`, the par change in bp at 2/5/10/30, and level 5's `market_paths`
carry the 200 `samples` in whole euros, so the browser can draw the curve change and the distribution without any finance of its own.)

They are built from an explicit list of observable facts, never by serialising an engine object, so nothing hidden can ride along:
no `ctx`, no informed flags or probabilities, no research-view truth, no future moves, no random streams, no seeds, no checkpoint answer.
Post-commitment, StepResultView and DebriefView DO carry what the design reveals after the trainee has committed (ratings, the benchmark
table, the evidence against the truth). Rendering to text is render.py; the views are the contract (docs/EPISODES.md section 19).
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, TypedDict

from ..marketmaking.flow import CLIENT_TYPES
from .assess import Assessment, _held_products
from .factors import FACTORS
from .products import BondPosition, FuturePosition
from .serial import plain
from .state import NEIGHBOURS

if TYPE_CHECKING:
    from .episode import Episode

SCHEMA = 1
CARD_TENORS = (2, 5, 10, 30)


class ObservationView(TypedDict, total=False):
    schema: int
    kind: str                   # quote | rfq | checkpoint | hedge | position | overnight | rehedge
    episode: dict               # id, title, level, round, rounds, round_title
    header: dict                # title, round, rounds, round_title, briefing, notes, show_risk_card
    risk_card: dict             # the training assumptions behind the numbers (factor vols and loadings)
    market: dict | None         # mode single|ladder; curve, focus, ladder rows, product lines
    book: dict | None           # swaps, hedges, dv01, limit_dv01, buckets, slope, curvature, curve_position, spreads, pnl_so_far
    conditions: dict | None     # volatility, liquidity, flow, swap_cost, desk_expectation, research, named_clients, calendar, extra_lines
    clients_today: list         # quote phase: who may call
    inquiry: dict | None        # rfq phase: the request and its own DV01 (never its effect on the book)
    last_inquiry: dict | None   # risk-decision phases: the request just handled
    hedge_menu: list | None
    overnight: dict | None      # carry report for the overnight decision
    next_step: dict | None      # trading_hours until the next move
    checkpoint: dict | None     # intro, prompt, unit, note (never the answer)
    prompt: str
    input: dict                 # type, hint, and for hedges the allowed tenors/products


class StepResultView(TypedDict, total=False):
    schema: int
    events: list                # what happened, in order (fill, trades, overnight, market, P&L): render.result_lines turns them into text
    assessment: dict | None     # AssessmentView
    grade: dict | None          # checkpoint grade (correct, feedback, expected)
    done: bool


class DebriefView(TypedDict, total=False):
    schema: int
    decisions: list
    calculation_checks: list
    outcome: dict
    luck: dict
    clients: list
    evidence_vs_truth: list | None
    view_truth: dict | None
    counterfactuals: dict | None
    market_paths: dict | None


# ------------------------------------------------------------------------------------------------- observation

def _short(ctype: str) -> str:
    return CLIENT_TYPES[ctype].description.split(";")[0].lower()


def _market(ep: "Episode", ctx) -> dict:
    s, d = ep.setup, ep.desk()
    if not d.multi_tenor and not d.products:
        t = s.tenor
        st = ctx.street()
        tenors = sorted({2, 5, 10, 30} | {t})
        return {"mode": "single",
                "curve": [{"tenor": x, "mid": ep.mkt.quotes["E6M"][round(x * 12)]} for x in tenors],
                "focus": {"tenor": t, "mid": ctx.mid(t), "bid": st.bid, "offer": st.offer, "dv01_per_m": ctx.dv01_per_m(t)},
                "ladder": [], "products": []}
    ladder = []
    for t in d.hedge_tenors:
        st = ctx.street(t)
        ladder.append({"tenor": t, "mid": ctx.mid(t), "bid": st.bid, "offer": st.offer, "dv01_per_m": ctx.dv01_per_m(t), "cost_bp": ctx.id_hs(t)})
    products = []
    for p in d.products:
        dv = ctx.unit_product(p.code)["level"]
        if p.kind == "future":
            products.append({"code": p.code, "kind": "future", "label": p.label, "price": FuturePosition(p.obj, 1.0, p.code).price(ep.mkt),
                             "dv01_per_unit": dv, "unit": "contract", "half_spread_ticks": p.half_spread / 0.01,
                             "cost_per_unit": ctx.product_cost(p.code, 1), "info": p.info})
        else:
            fb = BondPosition(p.obj, 100.0, p.code).materialise(ep.mkt)
            dirty = fb.pv(ep.mkt)
            products.append({"code": p.code, "kind": "bond", "label": p.label, "clean": dirty - fb.accrued(ep.mkt.anchor),
                             "yield": fb.yield_from_dirty(ep.mkt.anchor, dirty), "asw_bp": fb.asw * 1e4, "dv01_per_unit": dv,
                             "unit": "EUR 1m face", "half_spread": p.half_spread, "cost_per_unit": ctx.product_cost(p.code, 1), "info": p.info})
    return {"mode": "ladder", "curve": [], "focus": None, "ladder": ladder, "products": products}


def _book(ep: "Episode", ctx) -> dict:
    from .episode import bucket_dv01        # (late import: episode imports this module)
    from .state import book as _book_of
    from ..engine.instruments import IRSwap
    d, lim = ep.desk(), ep.limits
    swaps, net = [], {}
    for p in ep.positions:
        if isinstance(p.inst, IRSwap):
            swaps.append({"label": p.label, "side": p.inst.side.value, "notional": p.inst.notional,
                          "tenor": round(len(p.inst.fixed_periods)), "rate": p.inst.fixed_rate})
        elif isinstance(p.inst, FuturePosition):
            net[p.inst.code] = net.get(p.inst.code, 0.0) + p.inst.contracts
        else:
            net[p.inst.code] = net.get(p.inst.code, 0.0) + p.inst.face
    hedges = [{"code": c, "kind": "bond" if c == "CTD" else "future", "quantity": q} for c, q in net.items() if abs(q) >= 0.5]
    b = {"swaps": swaps, "hedges": hedges, "dv01": ctx.dv01, "limit_dv01": lim.dv01, "focus_tenor": ep.setup.tenor,
         "buckets": None, "slope": None, "curvature": None, "curve_position": None, "spreads": None, "pnl_so_far": ep.pnl_total()}
    if d.multi_tenor:
        bk = bucket_dv01(_book_of(ep.positions), getattr(ep.mkt, "curves", ep.mkt)) if ep.positions else {}
        b["buckets"] = [{"tenor": t, "dv01": v} for t, v in bk.items()]
        b["slope"] = {"exposure": ctx.slope, "limit": lim.slope}
        b["curvature"] = ctx.x.get("curvature", 0.0)
    else:
        cp = ctx.curve_position()
        if abs(cp) > 0.05 * lim.dv01:
            b["curve_position"] = cp
    if "swap_spread" in ctx.x and abs(ctx.x["swap_spread"]) > 1:
        b["spreads"] = {"swap_spread": ctx.x["swap_spread"], "fut_basis": ctx.x.get("fut_basis", 0.0)}
    return b


def research_view(ep: "Episode") -> dict | None:
    """The research view as the grader uses it. The view is a drift spread EVENLY over the session's steps (right or not, whatever has been
    seen so far), so what is left at round r is view x (rounds - r) / rounds. Nothing here depends on whether the call is right."""
    s = ep.setup
    if not s.signal:
        return None
    n, r = s.rounds, ep.round
    per = s.signal.view_bp / n
    return {"text": s.signal.text, "reliability": s.signal.reliability, "steps_total": n, "steps_left": n - r,
            "total_bp": s.signal.view_bp, "remaining_bp": per * (n - r), "per_step_bp": per, "expected_per_step_bp": s.signal.reliability * per}


def _conditions(ep: "Episode") -> dict:
    s = ep.setup
    named = []
    if ep.evidence and s.clients:
        for c in s.clients:
            ev = [e for e in ep.evidence if e.name == c.name]
            if ev:
                named.append({"name": c.name, "description": _short(c.ctype),
                              "observations": [{"side": "paid" if e.sign > 0 else "received", "move_bp": e.move} for e in ev]})
    out = dict(ep.regime.facts())
    out["research"] = research_view(ep)
    out["named_clients"] = named
    out["calendar"] = {"vol_mult": ep.plan.vol_mult} if ep.plan.vol_mult > 1 else None
    out["extra_lines"] = list(s.extra_lines)
    return out


def risk_card(ep: "Episode") -> dict:
    """The training abstraction behind every risk number, shown so relative risk can be reasoned about (not market estimates)."""
    rows = []
    for k in ep.factors:
        f = FACTORS[k]
        rows.append({"name": k, "label": f.label, "normal_daily_vol": f.vol_bp_day,
                     "vol_unit": " tick" if k == "fut_basis" else "bp",
                     "loadings": [{"tenor": t, "bp_per_unit": f.loading(t)} for t in CARD_TENORS] if f.is_curve else None})
    return {"title": "Training assumptions (a simplified model for this exercise, not estimates of true market volatility)",
            "regime_vol": ep.regime.vol, "step_days": ep.regime.dt, "factors": rows}


def _inquiry_view(ep: "Episode", ctx) -> dict:
    q = ep.inquiries[ep.round]
    ct = CLIENT_TYPES[q.ctype]
    t = ep.inquiry_tenor()
    return {"name": q.name, "ctype": q.ctype, "description": ct.description, "short": _short(q.ctype), "action": q.action.value,
            "notional": q.notional, "tenor": t, "dv01": ctx.trade_dv01(q.action, q.notional, t)}


def input_spec(ep: "Episode", ctx, kind: str, hint: str, unit: str | None = None) -> dict:
    """What the prompt expects. `hint` is the typing help; `unit` is the unit of the answer ("%" for rates, the checkpoint's own unit for a number)."""
    d = ep.desk()
    spec = {"type": {"quote": "quote", "rfq": "rfq", "checkpoint": "number", "position": "position"}.get(kind, "hedge"), "hint": hint}
    if spec["type"] in ("quote", "rfq"):
        spec["unit"] = "%"
    elif spec["type"] == "number":
        spec["unit"] = unit
    if spec["type"] in ("hedge", "position"):
        spec.update(swap_tenors=list(d.hedge_tenors) if (d.multi_tenor or d.products) else [ep.setup.tenor, *NEIGHBOURS[ep.setup.tenor]],
                    products=[p.code for p in d.products], can_flatten=bool(d.multi_tenor), can_switch=bool(_held_products(ctx)),
                    can_target=(kind == "position"))
    return spec


def observation_view(ep: "Episode", prompt: str, hint: str, unit: str | None = None) -> ObservationView:
    """Build the view for the episode's current phase. `prompt` and `hint` are the phase's question and input hint; `unit` the checkpoint's."""
    s, ctx, r, kind = ep.setup, ep.context(), ep.round, ep.phase
    first_phase = kind == (ep._phases[0] if ep._phases else kind) and not ep.record.decisions
    p = ep.plan
    v: ObservationView = {
        "schema": SCHEMA, "kind": kind,
        "episode": {"id": s_id(ep), "title": s.title, "level": ep.spec.level, "round": r, "rounds": s.rounds, "round_title": p.title},
        "header": {"title": s.title, "round": r, "rounds": s.rounds, "round_title": p.title,
                   "briefing": s.briefing if (r == 0 and first_phase) else None, "notes": list(p.notes) if first_phase else [],
                   "show_risk_card": bool(r == 0 and first_phase)},
        "risk_card": risk_card(ep), "market": None, "book": None, "conditions": None, "clients_today": [], "inquiry": None,
        "last_inquiry": None, "hedge_menu": None, "overnight": None, "next_step": None, "checkpoint": None,
        "prompt": prompt, "input": input_spec(ep, ctx, kind, hint, unit)}
    if kind == "checkpoint":
        slope = p.checkpoint == "slope_if_dealt"
        inq = None
        if slope:
            q = ep.inquiries[r]
            inq = {"action": q.action.value, "notional": q.notional, "tenor": ep.inquiry_tenor()}
            v["market"], v["book"] = _market(ep, ctx), _book(ep, ctx)
        v["checkpoint"] = {"intro": "Before you price it:" if slope else "Before you decide on a hedge:", "with_screen": slope, "inquiry": inq,
                           "prompt": prompt, "note": hint}
        return v
    v["market"], v["book"] = _market(ep, ctx), _book(ep, ctx)
    if kind == "quote":
        v["conditions"] = _conditions(ep)
        v["clients_today"] = [_short(t) for t, _ in ep.regime.client_mix]
    elif kind == "rfq":
        v["conditions"] = _conditions(ep) if (r == 0 or s.desk) else None
        v["inquiry"] = _inquiry_view(ep, ctx)
    else:
        rec = ep.record
        if p.pricing:
            q = ep.inquiries[r]
            outcome = ("it dealt with you" if rec.filled else
                       "you passed" if any(k == "rfq" and getattr(d, "level", 0) is None for k, d, _ in rec.decisions) else "it dealt elsewhere")
            v["last_inquiry"] = {"short": _short(q.ctype), "action": q.action.value, "notional": q.notional, "tenor": ep.inquiry_tenor(),
                                 "outcome": outcome}
        v["conditions"] = _conditions(ep)
        d = ep.desk()
        if not d.multi_tenor and not d.products:
            v["hedge_menu"] = [{"tenor": t, "dv01_per_m": ctx.dv01_per_m(t), "cost_bp": ctx.id_hs(t)} for t in (s.tenor, *NEIGHBOURS[s.tenor])]
        if kind == "overnight":
            v["overnight"] = {"time_pnl": ctx.time_pnl()}
        else:
            v["next_step"] = {"trading_hours": ep.regime.dt * 8}
    return v


def s_id(ep: "Episode") -> str:
    return ep.spec.id


# ------------------------------------------------------------------------------------------------- results

_P_INFORMED = re.compile(r"\s*\(P\(informed\) \d+% from the evidence\)")


def assessment_view(a: Assessment, reveal_inference: bool = True) -> dict:
    """The assessment as plain data. With `reveal_inference=False` (the live desk) the model's probability that a client is informed is left out: the
    metric and the phrase quoting it. It stays in the debrief, where it explains the assessment."""
    metrics = plain(a.metrics)
    reasons = list(a.reasons)
    if not reveal_inference:
        metrics.pop("p_informed", None)
        reasons = [_P_INFORMED.sub("", r) for r in reasons]
    return {"kind": a.kind, "rating": a.rating.value, "reasons": reasons, "expected_pnl": a.expected_pnl, "variance": a.variance,
            "table": [{"label": l, "expected": e, "sigma": sd, "rating": rt.value} for l, e, sd, rt in a.table],
            "metrics": metrics}


def grade_view(g) -> dict | None:
    return None if g is None else {"correct": bool(g.correct), "feedback": g.feedback, "expected": g.expected}


def step_result_view(events: list[dict], assessment: Assessment | None, grade, done: bool, reveal_inference: bool = True) -> StepResultView:
    return {"schema": SCHEMA, "events": plain(events), "assessment": assessment_view(assessment, reveal_inference) if assessment else None,
            "grade": grade_view(grade), "done": done}


# ------------------------------------------------------------------------------------------------- debrief

def _stats(xs: list[float]) -> dict:
    ys = sorted(xs)

    def q(p: float) -> float:
        return ys[min(len(ys) - 1, max(0, int(p * (len(ys) - 1))))]
    return {"mean": sum(xs) / len(xs), "p05": q(0.05), "p95": q(0.95), "samples": [round(x) for x in xs]}      # whole euros, to draw the distribution


def debrief_view(ep: "Episode", compare: bool = True) -> DebriefView:
    from .episode import PATHS, path_pnls, run_policy
    from .assess import DecisionContext
    if not ep.done:
        raise RuntimeError("finish the episode first")
    s = ep.setup
    decisions = [{"round": rec.round, "kind": kind, "rating": a.rating.value, "headline": a.reasons[0] if a.reasons else "",
                  "reasons": list(a.reasons)}          # in full, including the evidence-based P(informed) the live desk leaves out
                 for rec in ep.records for kind, _, a in rec.decisions if a is not None]
    by_cause: dict[str, float] = {}
    for e in ep.ledger:
        by_cause[e.cause] = by_cause.get(e.cause, 0.0) + e.amount
    total = ep.pnl_total()
    ctx = DecisionContext(ep.mkt, ep.positions, ep.limits.dv01, ep.regime, s.tenor, desk=ep.desk(), home=s.tenor)
    outcome = {"by_cause": [{"cause": k, "amount": v} for k, v in by_cause.items()], "total": total,
               "exposures_by_round": ([{"round": r.round, "level": r.x_after.get("level", 0.0), "slope": r.x_after.get("slope", 0.0)}
                                       for r in ep.records] if ep.desk().multi_tenor else None),
               "spread_note": None, "risk_left": {"dv01": ctx.dv01, "flatten_cost": ctx.id_hs(s.tenor) * abs(ctx.dv01)}}
    if "swap_spread" in by_cause or any(k.startswith("market: swap") for k in by_cause):
        ss, fb = by_cause.get("market: swap_spread", 0.0), by_cause.get("market: fut_basis", 0.0)
        if abs(ss) + abs(fb) > 0.1 * max(1.0, abs(total)):
            outcome["spread_note"] = {"swap_spread": ss, "fut_basis": fb}
    expected = sum(r.expected for r in ep.records)
    sigma = math.sqrt(sum(r.variance for r in ep.records))
    luck = {"label": "Expected P&L from execution uncertainty", "expected_pnl": expected, "realised_pnl": total, "luck": total - expected,
            "sigma_units": (total - expected) / sigma if sigma > 1 else None}
    clients = [{"round": rec.round, "name": rec.inquiry.name, "ctype": rec.inquiry.ctype, "action": rec.inquiry.action.value,
                "notional": rec.inquiry.notional, "tenor": rec.inquiry.tenor, "informed": rec.inquiry.informed, "traded": rec.filled}
               for rec in ep.records if rec.plan.pricing]
    evidence = None
    if s.clients:
        evidence = []
        for c in s.clients:
            seen = [rec for rec in ep.records if rec.inquiry.name == c.name and rec.plan.pricing]
            if seen:
                ps = [a.metrics.get("p_informed") for rec in seen for k, _, a in rec.decisions if k == "rfq" and a]
                evidence.append({"name": c.name, "posteriors": [p for p in ps if p is not None], "informed": c.informed})
    view_truth = {"right": ep.signal_right, "reliability": s.signal.reliability} if s.signal else None
    cf = paths = None
    if compare:
        others = {}
        pol_rows = []
        for name, pol in ep.policies().items():
            other = run_policy(ep.spec.id, ep.seed, pol)
            others[name] = other
            pol_rows.append({"name": name, "pnl": other.pnl_total(),
                             "ratings": [a.rating.value for r in other.records for _, _, a in r.decisions if a]})
        cf = {"policies": pol_rows, "you": total}
        if s.many_paths:
            yours = path_pnls(ep)
            ref_ep = others.get(next(iter(ep.policies())))
            paths = {"label": "Market-path P&L distribution conditional on these decisions and fills", "n": PATHS, "yours": _stats(yours),
                     "rank": sum(1 for x in yours if x <= total) / len(yours),
                     "reference": _stats(path_pnls(ref_ep)) if ref_ep is not None else None}
    return {"schema": SCHEMA, "decisions": decisions,
            "calculation_checks": [{"correct": bool(g.correct), "expected": g.expected} for g in ep.checkpoints],
            "outcome": outcome, "luck": luck, "clients": clients, "evidence_vs_truth": evidence, "view_truth": view_truth,
            "counterfactuals": cf, "market_paths": paths}
