"""Portfolio, DV01 / key-rate risk and hedge sizing.

DV01 sign convention (fixed project-wide):
    DV01 = P&L for a 1bp FALL in rates.
    Long duration (receiver, long bond) => positive. Short duration (payer) => negative.
    Fast estimate of P&L for a move of m bp: -DV01 * m   (see pnl.first_order_pnl).

Risk is measured the way a desk measures it: bump ONE par quote by +/-0.5bp, re-bootstrap, reprice,
and take the central difference per 1bp. Risk keys are (curve, pillar_months): ("OIS", 120) is the
10Y OIS quote, ("E6M", 120) the 10Y 6M-Euribor swap quote, ("BASIS_3S6S", 120) the 10Y 3s6s spread.

Consequences worth knowing (all tested):
  * A par instrument struck at its own pillar has risk ONLY in its own key. A par 10Y IRS is
    entirely ("E6M", 120); bumping OIS leaves its PV at zero because the Euribor curve re-fits.
  * A NON-par or off-pillar instrument spreads across neighbouring keys, and across curves
    (discounting risk shows up in the OIS keys).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .curve import CurveShock
from .instruments import FRA, BasisSwap, Instrument, IRSwap, OISSwap, Side
from .marketdata import DEFAULT_SHOCK_CURVES, MarketCurves
from .numerics import solve_linear

RiskKey = tuple[str, int]


@dataclass(frozen=True)
class Portfolio:
    """A set of positions. Quantity is carried inside each instrument's notional/side."""

    instruments: tuple[Instrument, ...] = ()

    def __init__(self, instruments: Sequence[Instrument] = ()):
        object.__setattr__(self, "instruments", tuple(instruments))

    def pv(self, market) -> float:
        return sum(i.pv(market) for i in self.instruments)

    def plus(self, *others: Instrument) -> "Portfolio":
        return Portfolio(self.instruments + tuple(others))


def key_rate_dv01(inst: Instrument, mkt: MarketCurves, bump_bp: float = 1.0,
                  curves: tuple[str, ...] | None = None) -> dict[RiskKey, float]:
    """DV01 per quote (EUR per 1bp fall), by central difference."""
    h = bump_bp / 2.0
    out: dict[RiskKey, float] = {}
    for name, m in mkt.risk_keys(curves):
        up = inst.pv(mkt.bumped(name, m, +h))
        dn = inst.pv(mkt.bumped(name, m, -h))
        out[(name, m)] = (dn - up) / bump_bp
    return out


def by_tenor(kr: dict[RiskKey, float], curves: tuple[str, ...] = DEFAULT_SHOCK_CURVES) -> dict[int, float]:
    """Collapse a risk vector to one number per tenor (months), summing across the given curves."""
    out: dict[int, float] = {}
    for (name, m), d in kr.items():
        if name in curves:
            out[m] = out.get(m, 0.0) + d
    return out


def parallel_dv01(inst: Instrument, mkt: MarketCurves, bump_bp: float = 1.0,
                  curves: tuple[str, ...] = DEFAULT_SHOCK_CURVES) -> float:
    """DV01 for a parallel move of the given curves' quotes (EUR per 1bp fall), central difference."""
    h = bump_bp / 2.0
    up = inst.pv(mkt.shifted(CurveShock.parallel(+h), curves))
    dn = inst.pv(mkt.shifted(CurveShock.parallel(-h), curves))
    return (dn - up) / bump_bp


# ---------- at-market instrument factories (tenors in YEARS, whole months implied) ----------

def _months(years: float) -> int:
    m = round(years * 12)
    if m < 1 or abs(years * 12 - m) > 1e-9:
        raise ValueError(f"{years}Y is not a whole number of months")
    return m


def par_irs(side: Side, notional: float, tenor_years: float, mkt: MarketCurves, start_years: float = 0.0) -> IRSwap:
    """At-market EUR IRS vs 6M Euribor (the 'EUR 10Y swap')."""
    t, s = _months(tenor_years), round(start_years * 12)
    return IRSwap.new(side, notional, mkt.par_irs_rate(t, s), mkt.spot, t, s)


def par_ois(side: Side, notional: float, tenor_years: float, mkt: MarketCurves, start_years: float = 0.0) -> OISSwap:
    t, s = _months(tenor_years), round(start_years * 12)
    return OISSwap.new(side, notional, mkt.par_ois_rate(t, s), mkt.spot, t, s)


def par_fra(side: Side, notional: float, start_months: int, end_months: int, mkt: MarketCurves) -> FRA:
    template = FRA.new(side, notional, 0.0, mkt.spot, start_months, end_months)
    return FRA.new(side, notional, template.par_rate(mkt), mkt.spot, start_months, end_months)


def par_basis(side: Side, notional: float, tenor_years: float, mkt: MarketCurves) -> BasisSwap:
    t = _months(tenor_years)
    return BasisSwap.new(side, notional, BasisSwap.new(side, 1.0, 0.0, mkt.spot, t).par_spread(mkt), mkt.spot, t)


def unit_dv01(tenor_years: float, mkt: MarketCurves, kind: str = "IRS", notional: float = 1e6) -> float:
    """Parallel DV01 of a receiver par swap of the given notional (positive)."""
    make = {"IRS": par_irs, "OIS": par_ois}[kind]
    return parallel_dv01(make(Side.RECEIVE, notional, tenor_years, mkt), mkt)


def dv01_hedge_swap(target_dv01: float, tenor_years: float, mkt: MarketCurves, kind: str = "IRS"):
    """At-market swap whose parallel DV01 offsets target_dv01.

    A long-duration target (DV01 > 0) is hedged by PAYING fixed; short by RECEIVING.
    """
    per_million = unit_dv01(tenor_years, mkt, kind)
    notional = abs(target_dv01) / per_million * 1e6
    make = {"IRS": par_irs, "OIS": par_ois}[kind]
    return make(Side.PAY if target_dv01 > 0 else Side.RECEIVE, notional, tenor_years, mkt)


def solve_key_rate_hedge(target: dict[RiskKey, float], hedges: Sequence[tuple[str, float]],
                         mkt: MarketCurves) -> list[Instrument]:
    """Exactly neutralise the target's risk in the keys of the chosen hedge swaps.

    hedges: [("IRS", 10), ("IRS", 5), ("OIS", 10)] -> one at-market swap per entry (tenor in years).
    The hedge keys are ("E6M", m) for an IRS and ("OIS", m) for an OIS. Risk in every OTHER key is
    untouched and remains as residual -- that is the point of the exercise.
    """
    keys: list[RiskKey] = [("E6M" if k == "IRS" else "OIS", _months(t)) for k, t in hedges]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate hedge instruments")
    unit = 1e6
    makers = {"IRS": par_irs, "OIS": par_ois}
    cols = [key_rate_dv01(makers[k](Side.RECEIVE, unit, t, mkt), mkt) for k, t in hedges]
    matrix = [[cols[j][key] for j in range(len(cols))] for key in keys]
    qty = solve_linear(matrix, [-target.get(key, 0.0) for key in keys])   # signed millions of receiver
    out: list[Instrument] = []
    for (k, t), q in zip(hedges, qty):
        if abs(q) > 1e-9:
            out.append(makers[k](Side.RECEIVE if q > 0 else Side.PAY, abs(q) * unit, t, mkt))
    return out
