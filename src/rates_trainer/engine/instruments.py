"""Instruments. Every instrument exposes pv(market) from the HOLDER's view.

`market` is anything with `.ois` (discount Curve) and `.projection(index)` (projection Curve);
see marketdata.MarketCurves. Instruments are immutable and carry their own dated schedules.

Conventions (EUR market standard, with the simplifications listed in dates.py)
  * IRS    fixed annual 30E/360 vs 6M Euribor semi-annual ACT/360, discounted on the ESTR-OIS curve.
  * OIS    fixed annual ACT/360 vs compounded ESTR annual ACT/360; float leg PV = DF(start) - DF(end).
  * FRA    settled at the period start, rate set at the period start:
               payoff = N * tau * (K - F) / (1 + F * tau)   for the receiver of K.
  * Basis  3M Euribor + spread (quarterly) vs 6M Euribor flat (semi-annual); side is that of the SPREAD.
  * Bond   annual coupon, regular period accrual exactly 1.0 (ACT/ACT ICMA), valued ON a coupon date (`new`, clean = dirty) or mid-period (`from_maturity`)
           discounted on the OIS curve.

Sign conventions
  * Side.RECEIVE = receive fixed (long duration), Side.PAY = pay fixed (short duration).
  * Swap notionals are positive; FixedBond.notional is signed (positive = long).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import Enum
from typing import Protocol

from .curve import Curve
from .dates import DayCount, Period, add_months, make_schedule
from .numerics import find_root


class Side(Enum):
    PAY = "pay"          # pay fixed, receive float: short duration
    RECEIVE = "receive"  # receive fixed, pay float: long duration

    @property
    def sign(self) -> int:
        """+1 for long duration (receiver), -1 for short duration (payer)."""
        return 1 if self is Side.RECEIVE else -1

    @property
    def opposite(self) -> "Side":
        return Side.PAY if self is Side.RECEIVE else Side.RECEIVE


class Market(Protocol):
    anchor: date
    @property
    def ois(self) -> Curve: ...
    def projection(self, index: str) -> Curve: ...
    def fixing(self, index: str, period: Period) -> float: ...
    def ois_growth(self, start: date) -> float: ...


class Instrument(Protocol):
    def pv(self, market: Market) -> float: ...


def _trim(periods: tuple[Period, ...], anchor: date) -> tuple[Period, ...]:
    """Unpaid periods only; one that has already started is re-started at the anchor."""
    return tuple(Period(max(p.start, anchor), p.end, p.pay) for p in periods if p.pay > anchor)


def _check_notional(n: float) -> None:
    if n <= 0:
        raise ValueError("notional must be positive; use side for direction")


def _accrual_annuity(periods: tuple[Period, ...], dc: DayCount, disc: Curve) -> float:
    """PV of 1 per year of accrual over the periods still to be paid (pay date after the valuation date).

    An in-progress period counts in FULL: its whole coupon is paid later, accrued part included.
    """
    return sum(dc.fraction(p.start, p.end) * disc.df(p.pay) for p in periods if p.pay > disc.anchor)


def _float_pv(periods: tuple[Period, ...], m: Market, index: str) -> float:
    """PV per unit notional of a floating leg still to be paid.

    Future period:       (P(a)/P(b) - 1) x DF(pay)           [= tau x F x DF]
    In-progress period:  tau x FIXING x DF(pay)              (rate was set at the period start)
    Paid period:         excluded.
    """
    proj, disc, anchor = m.projection(index), m.ois, m.anchor
    total = 0.0
    for p in periods:
        if p.pay <= anchor:
            continue
        if p.start >= anchor:
            accrual = proj.df(p.start) / proj.df(p.end) - 1.0
        else:
            accrual = DayCount.ACT_360.fraction(p.start, p.end) * m.fixing(index, p)
        total += accrual * disc.df(p.pay)
    return total


@dataclass(frozen=True)
class IRSwap:
    """EUR fixed-for-6M-Euribor swap. Start can be forward (start_months after spot)."""

    side: Side
    notional: float
    fixed_rate: float
    fixed_periods: tuple[Period, ...]
    float_periods: tuple[Period, ...]
    index: str = "E6M"

    def __post_init__(self) -> None:
        _check_notional(self.notional)

    @classmethod
    def new(cls, side: Side, notional: float, fixed_rate: float, spot: date, tenor_months: int,
            start_months: int = 0) -> "IRSwap":
        return cls(side, notional, fixed_rate,
                   make_schedule(spot, start_months, tenor_months, 12),
                   make_schedule(spot, start_months, tenor_months, 6))

    @property
    def start(self) -> date:
        return self.fixed_periods[0].start

    @property
    def maturity(self) -> date:
        return self.fixed_periods[-1].end

    def remaining(self, anchor: date) -> "IRSwap":
        """The CLEAN swap over the same remaining dates: unpaid periods only, an in-progress period re-started
        at `anchor` (a stub). Its par rate is the curve's rate 'for the remaining maturity'; aged minus clean is
        the accrued net coupon."""
        return replace(self, fixed_periods=_trim(self.fixed_periods, anchor), float_periods=_trim(self.float_periods, anchor))

    def annuity(self, m: Market) -> float:
        """PV of 1 per year on the fixed leg (30E/360 accrual), per unit notional."""
        return _accrual_annuity(self.fixed_periods, DayCount.THIRTY_E_360, m.ois)

    def float_leg_pv(self, m: Market) -> float:
        return _float_pv(self.float_periods, m, self.index)

    def par_rate(self, m: Market) -> float:
        return self.float_leg_pv(m) / self.annuity(m)

    def pv(self, m: Market) -> float:
        return self.side.sign * self.notional * (self.fixed_rate * self.annuity(m) - self.float_leg_pv(m))


@dataclass(frozen=True)
class OISSwap:
    """EUR fixed vs compounded ESTR. Periods are annual (a tenor under 12M is a single period)."""

    side: Side
    notional: float
    fixed_rate: float
    periods: tuple[Period, ...]

    def __post_init__(self) -> None:
        _check_notional(self.notional)

    @classmethod
    def new(cls, side: Side, notional: float, fixed_rate: float, spot: date, tenor_months: int,
            start_months: int = 0) -> "OISSwap":
        return cls(side, notional, fixed_rate, make_schedule(spot, start_months, tenor_months, 12))

    @property
    def start(self) -> date:
        return self.periods[0].start

    @property
    def maturity(self) -> date:
        return self.periods[-1].end

    def remaining(self, anchor: date) -> "OISSwap":
        """The CLEAN swap over the same remaining dates (see IRSwap.remaining)."""
        return replace(self, periods=_trim(self.periods, anchor))

    def annuity(self, m: Market) -> float:
        return _accrual_annuity(self.periods, DayCount.ACT_360, m.ois)

    def float_leg_pv(self, m: Market) -> float:
        """Per period: DF(a) - DF(b). An in-progress period uses the REALISED compounding to date:
        growth(a -> anchor) - DF(b), since the unrealised remainder compounds at the forwards."""
        disc, total = m.ois, 0.0
        for p in self.periods:
            if p.pay <= m.anchor:
                continue
            opening = disc.df(p.start) if p.start >= m.anchor else m.ois_growth(p.start)
            total += opening - disc.df(p.end)
        return total

    def par_rate(self, m: Market) -> float:
        return self.float_leg_pv(m) / self.annuity(m)

    def pv(self, m: Market) -> float:
        return self.side.sign * self.notional * (self.fixed_rate * self.annuity(m) - self.float_leg_pv(m))


@dataclass(frozen=True)
class FRA:
    """Forward rate agreement. Side.PAY = pay the FRA rate K (buyer; gains if rates rise)."""

    side: Side
    notional: float
    rate: float
    period: Period
    index: str = "E6M"

    def __post_init__(self) -> None:
        _check_notional(self.notional)

    @classmethod
    def new(cls, side: Side, notional: float, rate: float, spot: date, start_months: int, end_months: int,
            index: str | None = None) -> "FRA":
        length = end_months - start_months
        if length not in (3, 6):
            raise ValueError("FRAs here are on 3M or 6M Euribor")
        (period,) = make_schedule(spot, start_months, length, length)
        return cls(side, notional, rate, period, index or ("E3M" if length == 3 else "E6M"))

    @property
    def maturity(self) -> date:
        return self.period.end

    def forward(self, m: Market) -> float:
        return m.projection(self.index).forward_rate(self.period.start, self.period.end)

    def par_rate(self, m: Market) -> float:
        return self.forward(m)

    def pv(self, m: Market) -> float:
        tau = DayCount.ACT_360.fraction(self.period.start, self.period.end)
        f = self.forward(m)
        settle = self.notional * tau * (self.rate - f) / (1.0 + f * tau)    # receiver of K
        return self.side.sign * settle * m.ois.df(self.period.start)


@dataclass(frozen=True)
class BasisSwap:
    """3M Euribor + spread vs 6M Euribor flat. The side is that of the SPREAD (like a fixed rate):

    Side.PAY     = pay 3M + spread, receive 6M  => LONG the basis: gains when the 3s6s spread widens.
    Side.RECEIVE = receive 3M + spread, pay 6M  => SHORT the basis.
    """

    side: Side
    notional: float
    spread: float
    periods_3m: tuple[Period, ...]
    periods_6m: tuple[Period, ...]

    def __post_init__(self) -> None:
        _check_notional(self.notional)

    @classmethod
    def new(cls, side: Side, notional: float, spread: float, spot: date, tenor_months: int,
            start_months: int = 0) -> "BasisSwap":
        return cls(side, notional, spread,
                   make_schedule(spot, start_months, tenor_months, 3),
                   make_schedule(spot, start_months, tenor_months, 6))

    @property
    def maturity(self) -> date:
        return self.periods_6m[-1].end

    def _legs(self, m: Market) -> tuple[float, float, float]:
        disc = m.ois
        leg3 = _float_pv(self.periods_3m, m, "E3M")
        leg6 = _float_pv(self.periods_6m, m, "E6M")
        annuity3 = _accrual_annuity(self.periods_3m, DayCount.ACT_360, disc)
        return leg3, leg6, annuity3

    def par_spread(self, m: Market) -> float:
        leg3, leg6, annuity3 = self._legs(m)
        return (leg6 - leg3) / annuity3

    def pv(self, m: Market) -> float:
        leg3, leg6, annuity3 = self._legs(m)
        value_receive_3m = leg3 + self.spread * annuity3 - leg6     # receive 3M + spread, pay 6M
        return self.side.sign * self.notional * value_receive_3m    # PAY (sign -1) is the reverse


@dataclass(frozen=True)
class FixedBond:
    """Annual-coupon bullet bond (EUR government convention). notional is signed (+ = long). `new` builds a bond valued ON a coupon
    date; `from_maturity` builds one with its own coupon calendar, valued mid-period (dirty = pv, clean = dirty - accrued).

    PRICE. The bond is priced off the swap (OIS) curve plus its asset-swap spread:
        dirty price per unit face = V - asw x A
    with V = coupons + principal discounted on the OIS curve ("swap-curve value") and A = the spread annuity, the PV of
    1 per year paid on the bond's coupon dates, accrued ACT/360 (the floating leg of the asset swap). A CHEAP bond has a
    POSITIVE asw. asw is a property of the bond (a constant spread to the swap curve): moving it is how you shock
    "the bond cheapening against swaps".

    FINANCING. funding_spread is the repo rate minus ESTR (decimal; NEGATIVE = the bond is on special). It affects only
    carry (engine.carry), never the price.

    ACCRUAL. Regular periods are ACT/ACT (ICMA): a coupon accrues pro rata over its period.
    """

    notional: float
    coupon: float
    periods: tuple[Period, ...]
    asw: float = 0.0
    funding_spread: float = 0.0

    @classmethod
    def new(cls, notional: float, coupon: float, spot: date, maturity_years: int, asw: float = 0.0,
            funding_spread: float = 0.0) -> "FixedBond":
        if notional == 0:
            raise ValueError("notional must be non-zero")
        return cls(notional, coupon, make_schedule(spot, 0, 12 * maturity_years, 12), asw, funding_spread)

    @classmethod
    def from_maturity(cls, notional: float, coupon: float, maturity: date, anchor: date, asw: float = 0.0,
                      funding_spread: float = 0.0) -> "FixedBond":
        """A bond with its own calendar: annual coupons on the anniversaries of `maturity`, valued at `anchor` MID-PERIOD.

        Coupon dates are NOT business-day adjusted (a coupon is paid on its date), so accrued interest and the cash flow
        agree exactly. The first period starts at the last coupon date on or before `anchor`. notional=100 gives prices
        and accrued per 100 face, which is how the futures-basket maths is done."""
        if notional == 0:
            raise ValueError("notional must be non-zero")
        ends, k = [], 0
        while True:
            d = add_months(maturity, -12 * k)
            ends.append(d)
            if d <= anchor:
                break
            k += 1
        ends.reverse()
        if len(ends) < 2:
            raise ValueError("bond has matured")
        return cls(notional, coupon, tuple(Period(a, b, b) for a, b in zip(ends, ends[1:])), asw, funding_spread)

    @property
    def maturity(self) -> date:
        return self.periods[-1].end

    def with_asw(self, asw: float) -> "FixedBond":
        return replace(self, asw=asw)

    def spread_annuity(self, m: Market) -> float:
        """A: PV of 1 per year on the unpaid coupon dates, ACT/360 (what one unit of asw is worth per unit face)."""
        disc = m.ois
        return sum(DayCount.ACT_360.fraction(p.start, p.end) * disc.df(p.pay) for p in self.periods if p.pay > m.anchor)

    def swap_curve_value(self, m: Market) -> float:
        """V per unit face: the bond's cash flows discounted on the OIS curve (price if asw were zero)."""
        disc = m.ois
        coupons = sum(disc.df(p.pay) for p in self.periods if p.pay > m.anchor)
        return self.coupon * coupons + disc.df(self.maturity)

    def pv(self, m: Market) -> float:
        return self.notional * (self.swap_curve_value(m) - self.asw * self.spread_annuity(m))

    def price(self, m: Market) -> float:
        """Dirty price per 100 face."""
        return 100.0 * self.pv(m) / self.notional

    def asw_from_price(self, m: Market, dirty_price: float) -> float:
        """The par-par asset-swap spread (decimal) that reproduces a quoted dirty price per 100 face."""
        return (self.swap_curve_value(m) - dirty_price / 100.0) / self.spread_annuity(m)

    def accrued(self, anchor: date) -> float:
        """Accrued coupon in EUR at `anchor` (ACT/ACT ICMA, pro rata within the period)."""
        for p in self.periods:
            if p.start < anchor < p.end:
                return self.notional * self.coupon * (anchor - p.start).days / (p.end - p.start).days
        return 0.0

    # --- dated yield maths: ICMA with a fractional first period -----------------------
    def _cash_flows(self, anchor: date) -> list[tuple[float, float]]:
        """(time in years, cash per 100 face) for each unpaid coupon; time = w + i, w = fraction of the first period left."""
        unpaid = [p for p in self.periods if p.pay > anchor]
        first = unpaid[0]
        w = (first.end - anchor).days / (first.end - first.start).days
        n = len(unpaid)
        return [(w + i, 100.0 * self.coupon + (100.0 if i == n - 1 else 0.0)) for i in range(n)]

    def dirty_from_yield(self, anchor: date, y: float) -> float:
        return sum(cf / (1.0 + y) ** t for t, cf in self._cash_flows(anchor))

    def yield_from_dirty(self, anchor: date, dirty_price: float) -> float:
        """Annually-compounded ICMA yield for a dirty price per 100 face at `anchor`."""
        return find_root(lambda y: self.dirty_from_yield(anchor, y) - dirty_price, -0.05, 0.40, tol=1e-13)

    def modified_duration(self, anchor: date, y: float) -> float:
        h = 1e-6
        p0 = self.dirty_from_yield(anchor, y)
        return -(self.dirty_from_yield(anchor, y + h) - self.dirty_from_yield(anchor, y - h)) / (2 * h) / p0


@dataclass(frozen=True)
class AssetSwapPackage:
    """Par-par asset swap: long the bond, PAY its coupons in a swap, RECEIVE ESTR flat + the spread locked at trade.

    Priced as bond + swap leg, each from the curve, so the closed form below is an independent check:
        package value = N x [1 + (locked_spread - bond.asw) x A]
    i.e. at inception (bond.asw == locked_spread) the package is worth PAR, and afterwards it is a nearly pure SPREAD
    instrument: it gains N x A per unit that the bond's asw TIGHTENS (the bond richens) and has almost no outright
    interest-rate risk. Only valid at the first coupon date (no aged periods).
    """

    bond: FixedBond
    locked_spread: float

    def pv(self, m: Market) -> float:
        b = self.bond
        if b.periods[0].start < m.anchor:
            raise ValueError("AssetSwapPackage is priced at the first coupon date only")
        disc = m.ois
        fixed_leg = b.coupon * sum(disc.df(p.pay) for p in b.periods)          # coupons paid in the swap, accrual 1.0
        float_leg = disc.df(b.periods[0].start) - disc.df(b.maturity)           # ESTR flat on face, annual
        swap_leg = b.notional * (float_leg + self.locked_spread * b.spread_annuity(m) - fixed_leg)
        return b.pv(m) + swap_leg


# --- Yield-based bond maths (closed form, independent of any curve) -------------------

def _whole_years(x: float) -> int:
    n = round(x)
    if n < 1 or abs(x - n) > 1e-9:
        raise ValueError(f"period must be a whole number of years >= 1, got {x}")
    return n


def _cashflows(coupon: float, n: int) -> list[tuple[int, float]]:
    return [(i, 100.0 * coupon + (100.0 if i == n else 0.0)) for i in range(1, n + 1)]


def bond_price(coupon: float, maturity: float, y: float) -> float:
    """Price per 100 at annually-compounded yield y."""
    n = _whole_years(maturity)
    return sum(cf / (1.0 + y) ** i for i, cf in _cashflows(coupon, n))


def bond_macaulay_duration(coupon: float, maturity: float, y: float) -> float:
    n = _whole_years(maturity)
    p = bond_price(coupon, maturity, y)
    return sum(i * cf / (1.0 + y) ** i for i, cf in _cashflows(coupon, n)) / p


def bond_modified_duration(coupon: float, maturity: float, y: float) -> float:
    return bond_macaulay_duration(coupon, maturity, y) / (1.0 + y)


def bond_convexity(coupon: float, maturity: float, y: float) -> float:
    """(1/P) d2P/dy2, in years^2."""
    n = _whole_years(maturity)
    p = bond_price(coupon, maturity, y)
    return sum(i * (i + 1) * cf / (1.0 + y) ** (i + 2) for i, cf in _cashflows(coupon, n)) / p


def bond_dv01_per_100(coupon: float, maturity: float, y: float) -> float:
    """Price change per 100 face for a 1bp FALL in yield (positive for a long)."""
    return bond_price(coupon, maturity, y) * bond_modified_duration(coupon, maturity, y) * 1e-4
