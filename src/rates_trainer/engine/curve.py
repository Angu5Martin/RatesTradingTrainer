"""A date-based, log-linear curve and curve shocks.

`Curve` stores factors at node dates, with value 1 at the anchor. It is used for two things:
  * a DISCOUNT curve: value(d) = DF(d), the PV at the anchor of 1 paid on d;
  * a PROJECTION curve: value(d) = P(d), a factor whose ratios give forward fixings,
        F(a, b) = (P(a) / P(b) - 1) / ACT360(a, b).
    P is not a discount factor: with a single curve P = DF, with two curves P(6M) != DF.

Interpolation is linear in ln(value) against calendar days (piecewise-flat forwards);
beyond the last node the last segment's slope continues. Dates before the anchor are rejected.
Because interpolation is linear in days, re-anchoring to a later date is exact (used for roll-down).
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from .dates import DayCount

BP = 1e-4


class Curve:
    def __init__(self, anchor: date, dates: tuple[date, ...], values: tuple[float, ...]):
        if len(dates) != len(values) or not dates:
            raise ValueError("dates and values must be non-empty and equal length")
        days = tuple((d - anchor).days for d in dates)
        if days[0] <= 0 or any(b <= a for a, b in zip(days, days[1:])):
            raise ValueError("node dates must be strictly increasing and after the anchor")
        if any(v <= 0 for v in values):
            raise ValueError("curve values must be positive")
        self.anchor = anchor
        self.dates = dates
        self.values = values
        self._days = (0,) + days
        self._ln = (0.0,) + tuple(math.log(v) for v in values)

    def df(self, d: date) -> float:
        n = (d - self.anchor).days
        if n < 0:
            raise ValueError(f"{d} is before the curve anchor {self.anchor}")
        days, ln = self._days, self._ln
        i = bisect_left(days, n)          # first node with days[i] >= n
        if i == 0:
            return 1.0
        if i >= len(days):                # beyond the last node: continue the last segment
            i = len(days) - 1
        j = i - 1
        slope = (ln[i] - ln[j]) / (days[i] - days[j])
        return math.exp(ln[j] + slope * (n - days[j]))

    def zero_rate(self, d: date) -> float:
        """Annually compounded, ACT/365F zero rate to d."""
        t = DayCount.ACT_365F.fraction(self.anchor, d)
        return self.df(d) ** (-1.0 / t) - 1.0

    def forward_rate(self, a: date, b: date) -> float:
        """Simple forward fixing between a and b, ACT/360."""
        return (self.df(a) / self.df(b) - 1.0) / DayCount.ACT_360.fraction(a, b)

    def annual_forward(self, a: date, b: date) -> float:
        """Annually compounded, ACT/365F forward rate between a and b (equals the simple rate for 1 year)."""
        tau = DayCount.ACT_365F.fraction(a, b)
        return (self.df(a) / self.df(b)) ** (1.0 / tau) - 1.0

    def reanchored(self, new_anchor: date) -> "Curve":
        """The same forward curve seen from a later date (exact for this interpolation)."""
        base = self.df(new_anchor)
        keep = [(d, v / base) for d, v in zip(self.dates, self.values) if d > new_anchor]
        return Curve(new_anchor, tuple(d for d, _ in keep), tuple(v for _, v in keep))


@dataclass(frozen=True)
class CurveShock:
    """A move in rates in bp, specified at a few tenors (in YEARS).

    Linear interpolation in tenor between the points, flat outside. So CurveShock.parallel(4) is
    +4bp everywhere and CurveShock.points({2: -5, 10: 3}) is a 2s10s steepening.
    """

    knots: tuple[tuple[float, float], ...]

    @staticmethod
    def parallel(bp: float) -> "CurveShock":
        return CurveShock(((1.0, float(bp)),))

    @staticmethod
    def points(moves_bp: Mapping[float, float]) -> "CurveShock":
        if not moves_bp:
            raise ValueError("need at least one point")
        return CurveShock(tuple(sorted((float(t), float(b)) for t, b in moves_bp.items())))

    def bp_at(self, years: float) -> float:
        k = self.knots
        if years <= k[0][0]:
            return k[0][1]
        if years >= k[-1][0]:
            return k[-1][1]
        for (t0, b0), (t1, b1) in zip(k, k[1:]):
            if t0 <= years <= t1:
                return b0 + (b1 - b0) * (years - t0) / (t1 - t0)
        raise AssertionError("unreachable")
