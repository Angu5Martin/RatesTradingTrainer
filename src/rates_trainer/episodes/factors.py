"""Named market factors: a TRAINING ABSTRACTION that makes risk and market moves interpretable.

These are not claimed to be the true, or the only, drivers of the EUR curve. They are a small set of named shapes that a trader can
reason about ("I am hedged for level but long slope"), with stylised vols, used for two things that must agree:

  * RISK the trainee is shown: a book's exposure to each factor (EUR for a 1bp FALL of the factor, the DV01 convention) and the
    standard deviation of its P&L over the next step, sigma^2 = sum_k (x_k v_k)^2 (factors independent by construction);
  * MOVES that happen: factor moves are drawn with the same vols and carried onto the curve's par quotes with a CurveShock.

Loadings are piecewise linear in tenor (years) and flat outside their knots. A factor move of 1 moves a tenor's par rate by its loading in bp.
Levels 1-3 and 5 use level, slope and curvature; level 4 adds two SPREAD factors (swap spread, futures basis) that move the market
overlay of products.SpreadMarket rather than the curve. All vols are stated training assumptions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..engine.curve import CurveShock
from ..engine.marketdata import MarketCurves

GRID = (0.25, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0, 20.0, 30.0)


@dataclass(frozen=True)
class Factor:
    name: str
    label: str
    vol_bp_day: float                          # stylised normal-regime vol of a 1-unit move, per day
    knots: tuple[tuple[float, float], ...] = ((1.0, 0.0),)     # curve factors: (tenor in years, loading)
    spread_key: str | None = None              # spread factors: the market overlay entry they move (products.py)
    unit: float = 1.0                          # spread factors: overlay change for a 1-unit move

    @property
    def is_curve(self) -> bool:
        return self.spread_key is None

    def loading(self, years: float) -> float:
        return CurveShock(self.knots).bp_at(years) if self.is_curve else 0.0


FACTORS: dict[str, Factor] = {f.name: f for f in (
    Factor("level", "level (all rates together)", 5.0, ((1.0, 1.0),)),
    Factor("slope", "slope (2s30s twist about the 10Y)", 2.0, ((2.0, -1.0), (10.0, 0.0), (30.0, 1.0))),
    Factor("curvature", "curvature (5Y belly against the wings)", 1.0, ((1.0, -0.5), (5.0, 1.0), (15.0, -0.5))),
    # spread factors (level 4): unit = 1bp of ASW (+ = bonds cheapen against swaps) and 1 tick of futures price (+ = futures cheapen)
    Factor("swap_spread", "swap spread (bond ASW against swaps)", 0.8, spread_key="asw", unit=1e-4),
    Factor("fut_basis", "futures basis (futures against their CTD)", 1.0, spread_key="fut", unit=0.01),
)}
CURVE_FACTORS = ("level", "slope", "curvature")
SPREAD_FACTORS = ("swap_spread", "fut_basis")


def shock(moves: Mapping[str, float]) -> CurveShock:
    """The curve move (bp at each grid tenor) implied by the CURVE factors among `moves`."""
    return CurveShock.points({t: sum(FACTORS[k].loading(t) * x for k, x in moves.items() if FACTORS[k].is_curve) for t in GRID})


def apply_moves(m, moves: Mapping[str, float]):
    """The market after factor moves: the curve shifted, and any spread factors applied to the overlay (products.SpreadMarket)."""
    out = m.shifted(shock(moves))
    for k, x in moves.items():
        f = FACTORS[k]
        if not f.is_curve and x:
            out = out.with_spread(f.spread_key, x * f.unit)
    return out


def step_vol(name: str, vol: float, dt: float) -> float:
    """Standard deviation (bp) of a factor over a step of dt days in a regime with vol multiplier `vol`."""
    return FACTORS[name].vol_bp_day * vol * math.sqrt(dt)


class FactorRisk:
    """Factor exposures on one market, by central difference (re-bootstrapping, like every risk number in the engine).

    The +/-0.5bp factor-shifted markets are built once and reused for every instrument, so many candidate hedges cost little."""

    def __init__(self, mkt: MarketCurves, names: Sequence[str] = CURVE_FACTORS):
        self.mkt = mkt
        self.names = tuple(names)
        self._up = {k: apply_moves(mkt, {k: +0.5}) for k in self.names}
        self._dn = {k: apply_moves(mkt, {k: -0.5}) for k in self.names}

    def exposures(self, inst) -> dict[str, float]:
        """EUR P&L for a 1bp FALL of each factor (positive = long that factor's duration)."""
        return {k: inst.pv(self._dn[k]) - inst.pv(self._up[k]) for k in self.names}


def variance(x: Mapping[str, float], vol: float, dt: float) -> float:
    return sum((x.get(k, 0.0) * step_vol(k, vol, dt)) ** 2 for k in x)


def first_order_pnl(x: Mapping[str, float], moves: Mapping[str, float]) -> dict[str, float]:
    """-exposure x move, by factor."""
    return {k: -x.get(k, 0.0) * moves.get(k, 0.0) for k in x}


def add(*xs: Mapping[str, float], scale: Sequence[float] | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for i, x in enumerate(xs):
        s = 1.0 if scale is None else scale[i]
        for k, v in x.items():
            out[k] = out.get(k, 0.0) + s * v
    return out
