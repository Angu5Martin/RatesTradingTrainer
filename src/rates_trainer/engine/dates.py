"""Calendar, day counts and schedule generation (stdlib only).

Simplifications, stated deliberately:
  * One calendar: TARGET2 (the euro-area settlement calendar).
  * No end-of-month roll rule; roll dates are the unadjusted start + k x frequency months
    (day clamped to month end), then adjusted Modified Following.
  * No stubs: tenors must be whole multiples of the leg frequency (or shorter than it, giving one period).
  * No payment lag, no fixing lag: payment on the adjusted accrual end; each period's rate set at its start.
"""

from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from functools import lru_cache


def easter_sunday(year: int) -> date:
    """Western Easter (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


class BDC(Enum):
    FOLLOWING = "F"
    MODIFIED_FOLLOWING = "MF"
    PRECEDING = "P"


class Target:
    """TARGET2 calendar: weekends plus 1 Jan, Good Friday, Easter Monday, 1 May, 25 and 26 Dec."""

    @staticmethod
    @lru_cache(maxsize=None)
    def _holidays(year: int) -> frozenset[date]:
        easter = easter_sunday(year)
        return frozenset({
            date(year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1),
            date(year, 5, 1), date(year, 12, 25), date(year, 12, 26),
        })

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holidays(d.year)

    def adjust(self, d: date, bdc: BDC = BDC.MODIFIED_FOLLOWING) -> date:
        if self.is_business_day(d):
            return d
        if bdc is BDC.PRECEDING:
            return self._step(d, -1)
        out = self._step(d, +1)
        if bdc is BDC.MODIFIED_FOLLOWING and out.month != d.month:
            out = self._step(d, -1)
        return out

    def _step(self, d: date, direction: int) -> date:
        while not self.is_business_day(d):
            d += timedelta(days=direction)
        return d

    def add_business_days(self, d: date, n: int) -> date:
        step = 1 if n >= 0 else -1
        for _ in range(abs(n)):
            d = self._step(d + timedelta(days=step), step)
        return d


TARGET = Target()


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return date(y, m + 1, min(d.day, _cal.monthrange(y, m + 1)[1]))


def spot_date(trade_date: date, cal: Target = TARGET, lag: int = 2) -> date:
    """EUR spot is T+2 TARGET business days."""
    return cal.add_business_days(trade_date, lag)


class DayCount(Enum):
    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"
    THIRTY_E_360 = "30E/360"

    def fraction(self, d1: date, d2: date) -> float:
        if self is DayCount.ACT_360:
            return (d2 - d1).days / 360.0
        if self is DayCount.ACT_365F:
            return (d2 - d1).days / 365.0
        day1, day2 = min(d1.day, 30), min(d2.day, 30)
        return (360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (day2 - day1)) / 360.0


@dataclass(frozen=True)
class Period:
    """One accrual period. start/end/pay are all adjusted dates."""

    start: date
    end: date
    pay: date


@lru_cache(maxsize=None)
def make_schedule(spot: date, start_months: int, tenor_months: int, freq_months: int) -> tuple[Period, ...]:
    """Periods of a leg that starts start_months after spot and runs tenor_months.

    A tenor shorter than the frequency gives a single period of the whole tenor.
    """
    if tenor_months < 1 or start_months < 0:
        raise ValueError("tenor must be positive and start non-negative")
    freq = min(freq_months, tenor_months)
    if tenor_months % freq:
        raise ValueError(f"{tenor_months}M is not a whole number of {freq_months}M periods (stubs unsupported)")
    base = add_months(spot, start_months)
    rolls = [TARGET.adjust(add_months(base, k * freq)) for k in range(tenor_months // freq + 1)]
    return tuple(Period(a, b, b) for a, b in zip(rolls, rolls[1:]))
