"""Turning typed text into decisions (no I/O). Raises ValueError with a readable message when the input cannot be understood."""

from __future__ import annotations

import re

from ..engine.instruments import Side
from ..questions.model import parse_number
from .assess import DecisionContext
from .state import (BASE_HALF_SPREAD_BP, BondTrade, CheckpointAnswer, FuturesTrade, HedgeDecision, HedgeTrade, QuoteDecision,
                    RFQDecision)


def parse(observation, text: str):
    """THE entry point from typed text to a typed decision, for whatever the current observation asks (quote, rfq, position, any hedge kind,
    or a checkpoint answer). Raises ValueError/KeyError with a readable message when the text cannot be understood; the episode is untouched.

    `observation` is the engine-side Observation (it carries the decision context that sizes '50%', 'flatten', 'switch', 'target'); a
    frontend never holds one: it calls api.Session.parse(text), which does this against the session's current observation.
    """
    raw = text.strip()
    kind = observation.kind
    if kind == "quote":
        return parse_quote(raw)
    if kind == "rfq":
        return parse_rfq(raw)
    if kind == "position":
        return parse_position(raw, observation.ctx)
    if kind in ("hedge", "overnight", "rehedge"):
        return parse_hedge(raw, observation.ctx)
    return CheckpointAnswer(raw)


def _rate(tok: str) -> float:
    x = float(tok.strip().rstrip("%"))
    if not 0.0 < x < 15.0:
        raise ValueError(f"{tok!r} does not look like a rate in %")
    return x / 100.0


def parse_quote(raw: str) -> QuoteDecision:
    toks = [t for t in re.split(r"[\s/,]+", raw.strip()) if t]
    if len(toks) != 2:
        raise ValueError("give a bid and an offer, e.g. 2.843 2.847")
    bid, offer = _rate(toks[0]), _rate(toks[1])
    if offer <= bid:
        raise ValueError("the offer (where you receive fixed) must be above the bid (where you pay fixed)")
    return QuoteDecision(bid, offer)


def parse_rfq(raw: str) -> RFQDecision:
    s = raw.strip().lower()
    if s in {"pass", "p", "no", "decline"}:
        return RFQDecision(None)
    return RFQDecision(_rate(s))


_TENOR = re.compile(r"^(\d+)y$")


def parse_position(raw: str, ctx: DecisionContext) -> HedgeDecision:
    """Level 5 position decisions: 'keep', 'flat', 'target +100k' (DV01, done in the focus tenor), or anything parse_hedge accepts."""
    s = raw.strip().lower()
    if s in {"keep", "hold", "none", "no"}:
        return HedgeDecision((), "Keep the book as it is")
    if s in {"flat", "target 0", "flatten level"}:
        s = "target 0"
    if s.startswith("target"):
        target = parse_number(s.split(None, 1)[1] if len(s.split()) > 1 else "", bare_scale=1.0)
        change = target - ctx.dv01
        if abs(change) < 1.0:
            return HedgeDecision((), "Keep the book as it is")
        notional = abs(change) / ctx.dv01_per_m(ctx.tenor) * 1e6
        return HedgeDecision((HedgeTrade(ctx.tenor, Side.RECEIVE if change > 0 else Side.PAY, notional),),
                             f"Run {target / 1e3:+,.0f}k DV01")
    return parse_hedge(raw, ctx)


def parse_hedge(raw: str, ctx: DecisionContext) -> HedgeDecision:
    s = raw.strip().lower()
    if s in {"none", "no", "0", "0%", "warehouse", "keep", "nothing"}:
        return HedgeDecision((), "Warehouse (no hedge)")
    if s == "flatten":
        d = ctx.flatten_curve_hedge()
        if d is None:
            raise ValueError("nothing to flatten")
        return d
    if s.startswith("switch"):
        from .assess import _held_products, _switch_decision
        held = _held_products(ctx)
        if not held:
            raise ValueError("you hold no futures or bonds to switch")
        toks = s.split()
        t = int(toks[1].rstrip("y")) if len(toks) > 1 else None
        return _switch_decision(ctx, held, t)
    if "+" in s or " and " in s:
        legs = [parse_hedge(x, ctx) for x in re.split(r"\+| and ", s) if x.strip()]
        if any("%" in x for x in re.split(r"\+| and ", s)):
            raise ValueError("give each leg as 'pay/receive <notional> <tenor>y'")
        return HedgeDecision(tuple(t for leg in legs for t in leg.trades), " + ".join(leg.label for leg in legs))
    toks = s.split()
    tenor = ctx.tenor
    if toks and _TENOR.match(toks[-1]):
        tenor = int(_TENOR.match(toks[-1]).group(1))
        toks = toks[:-1]
        if tenor not in BASE_HALF_SPREAD_BP:
            raise ValueError(f"no {tenor}Y hedge here; use one of {sorted(BASE_HALF_SPREAD_BP)}")
    if len(toks) == 1 and toks[0].endswith("%"):
        frac = float(toks[0][:-1]) / 100.0
        if not 0.0 < frac <= 2.0:
            raise ValueError("a hedge percentage between 1% and 200%")
        tr = ctx.hedge_trade_for(frac, tenor)
        return HedgeDecision((tr,) if tr else (), f"Hedge {frac:.0%} in the {tenor}Y")
    if len(toks) == 3 and toks[0] in {"buy", "sell"}:
        sign = 1.0 if toks[0] == "buy" else -1.0
        code = toks[2].upper()
        if code in {"BOND", "CTD"}:
            ctx.desk.product("CTD")
            face = parse_number(toks[1], bare_scale=1e6)
            return HedgeDecision((BondTrade("CTD", sign * face),), f"{toks[0]} €{face / 1e6:,.0f}m of the CTD bond")
        ctx.desk.product(code)                      # raises KeyError for an unknown contract
        n = float(toks[1])
        return HedgeDecision((FuturesTrade(code, sign * n),), f"{toks[0]} {n:,.0f} {code}")
    if len(toks) == 2 and toks[0] in {"pay", "receive", "rec"}:
        notional = parse_number(toks[1], bare_scale=1e6)
        if notional <= 0:
            raise ValueError("notional must be positive")
        side = Side.PAY if toks[0] == "pay" else Side.RECEIVE
        return HedgeDecision((HedgeTrade(tenor, side, notional),), f"{side.value} fixed €{notional / 1e6:,.0f}m {tenor}Y")
    raise ValueError("try 'none', '50%', '100% 5y', 'pay 150m 10y', 'flatten', or (with products) 'sell 300 fgbl' / 'switch'")
