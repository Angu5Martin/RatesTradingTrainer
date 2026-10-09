"""P&L for a curve move, along two deliberately separate paths.

    FIRST-ORDER (the trader's mental estimate):   P&L ~ -DV01 x move
        first_order_pnl, key_rate_first_order_pnl
        Uses only risk numbers. Fast, linear, and wrong by exactly the convexity.

    FULL REVALUATION (the numerical truth):        P&L = PV(shocked market) - PV(base market)
        revalue_pnl
        Reprices every instrument. Includes convexity and every cross effect.

The two share no code, so each validates the other: the gap between them is the convexity /
cross-gamma P&L, it scales with move^2, and for a long-duration book it is positive.
Questions accept the first-order route as a legitimate answer for small moves, and show both
numbers afterwards so you can see how big the approximation error actually was.
"""

from __future__ import annotations

from dataclasses import dataclass

from .curve import CurveShock
from .instruments import Instrument
from .marketdata import DEFAULT_SHOCK_CURVES, MarketCurves
from .risk import RiskKey, key_rate_dv01


def first_order_pnl(dv01: float, move_bp: float) -> float:
    """-DV01 x move. DV01 is P&L per 1bp FALL, so a rise of move_bp loses dv01*move_bp if long."""
    return -dv01 * move_bp


def key_rate_first_order_pnl(kr_dv01: dict[RiskKey, float], shock: CurveShock,
                             curves: tuple[str, ...] = DEFAULT_SHOCK_CURVES) -> float:
    """First-order P&L from a bucketed risk vector and a (possibly non-parallel) shock."""
    return sum(first_order_pnl(d, shock.bp_at(m / 12.0)) for (name, m), d in kr_dv01.items() if name in curves)


def revalue_pnl(inst: Instrument, mkt: MarketCurves, shock: CurveShock,
                curves: tuple[str, ...] = DEFAULT_SHOCK_CURVES) -> float:
    """Full revaluation: reprice on the shocked market."""
    return inst.pv(mkt.shifted(shock, curves)) - inst.pv(mkt)


@dataclass(frozen=True)
class PnLReport:
    full: float                    # full revaluation
    delta: float                   # first-order, bucketed
    second_order: float            # full - delta: convexity / cross-gamma residual
    delta_by_key: dict[RiskKey, float]


def pnl_report(inst: Instrument, mkt: MarketCurves, shock: CurveShock,
               curves: tuple[str, ...] = DEFAULT_SHOCK_CURVES) -> PnLReport:
    """Both paths side by side."""
    kr = key_rate_dv01(inst, mkt)
    by_key = {k: first_order_pnl(d, shock.bp_at(k[1] / 12.0)) for k, d in kr.items() if k[0] in curves}
    delta = sum(by_key.values())
    full = revalue_pnl(inst, mkt, shock, curves)
    return PnLReport(full, delta, full - delta, by_key)
