"""Carry, roll-down and P&L attribution over a holding period.

Time passes in one of two ways, and the difference between them is the whole lesson:

    STATIC curve      every par swap rate BY TENOR is unchanged. The position's remaining life gets shorter
                      so it "rolls down" the curve. This is what a desk means by "carry and roll-down".
    FORWARDS REALISED the forward curve is unchanged: spot rates drift to what today's forwards imply.

After time h the position is an AGED swap (its in-progress periods carry the known fixing). Its CLEAN twin is the
same remaining dates restarted at the new spot (a stub swap): its par rate is what a curve screen shows 'for the
remaining maturity'. The static-curve P&L splits into three parts, each matching a mental calculation:

    carry      = the CASH accrual: fixed coupon accrued minus floating accrued over the horizon (days x rates).
                 Mental version is the same arithmetic: N x (K x time - short rate x days/360).
    roll-down  = clean mark-to-market change on the static curve: clean twin repriced minus today's PV.
                 Mental version: DV01 x (K - curve rate for the remaining maturity). Agrees to the annuity ratio
                 (a few %), because the clean twin's annuity is a little shorter than today's DV01 implies.
    other      = what is left: the time value of the accrued coupons (a fixed coupon accrued now is paid up to a year
                 later, so its PV is ~2% below its face accrual) plus the floating leg's reset effect (its in-progress
                 coupon was fixed at the old rate, not where a sloped front end would reset it). Small, and larger
                 for short tenors.
    total      = PV change if the curve does not move = carry + roll-down + other.

Identities the tests verify (they are the intuition):

    1. FORWARDS REALISED, par swap:   total = 0 (exactly). The non-carry part of the P&L, `mtm_forward`, is what
       the forwards force on the mark-to-market: carry is the market's expected drift being paid to you.
       It is not free money.
    2. STATIC, par swap:   total ~ DV01 x (forward rate - spot rate, both for the remaining maturity).
       You earn the forward-minus-spot spread if the curve simply sits still.
    3. BREAKEVEN: the parallel rise in rates that wipes out total is  total / DV01  (about the forward-implied drift).

Limitations (raised as errors, not silently ignored): the horizon must not cross a payment date, and only
swaps (IRS, OIS) are supported. Bond carry needs repo financing, which comes with the repo module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .curve import CurveShock
from .dates import DayCount, Period
from .instruments import FixedBond, Instrument, IRSwap, OISSwap
from .marketdata import MarketCurves
from .numerics import find_root
from .pnl import key_rate_first_order_pnl
from .risk import RiskKey, parallel_dv01, key_rate_dv01


def _legs(inst: Instrument) -> list[Instrument]:
    return list(getattr(inst, "instruments", (inst,)))


def _check_supported(inst: Instrument, mkt: MarketCurves, new_anchor: date) -> None:
    for leg in _legs(inst):
        if isinstance(leg, IRSwap):
            periods = leg.fixed_periods + leg.float_periods
        elif isinstance(leg, OISSwap):
            periods = leg.periods
        elif isinstance(leg, FixedBond):
            periods = leg.periods
        else:
            raise NotImplementedError(
                f"carry/roll-down is implemented for IRS, OIS and bonds, not {type(leg).__name__}")
        if any(mkt.anchor < p.pay <= new_anchor for p in periods):
            raise ValueError("the horizon crosses a payment date; shorten it (cash flows inside the window are not supported)")


def _overlap(p: Period, a0: date, a1: date) -> tuple[date, date] | None:
    s, e = max(p.start, a0), min(p.end, a1)
    return (s, e) if e > s else None


def financing_cost(bond: FixedBond, mkt: MarketCurves, new_anchor: date) -> float:
    """Repo financing (EUR) of the bond's market value over [today, new_anchor]: MV x (ESTR growth + spread x days/360).

    Positive for a long (you pay), negative for a short (you earn it). ESTR is the forward path implied by today's OIS curve;
    funding_spread is the bond's repo rate minus ESTR (negative = special)."""
    days = (new_anchor - mkt.anchor).days
    growth = mkt.ois.df(mkt.anchor) / mkt.ois.df(new_anchor) - 1.0
    return bond.pv(mkt) * (growth + bond.funding_spread * days / 360.0)


def _bond_cash_carry(bond: FixedBond, mkt: MarketCurves, new_anchor: date) -> float:
    """Coupon accrued over the horizon (ACT/ACT) minus repo financing."""
    for p in bond.periods:
        if p.pay > mkt.anchor:
            coupon_accrual = bond.notional * bond.coupon * (min(p.end, new_anchor) - max(p.start, mkt.anchor)).days / (p.end - p.start).days
            break
    return coupon_accrual - financing_cost(bond, mkt, new_anchor)


class _CleanBook:
    def __init__(self, legs):
        self.legs = legs

    def pv(self, m) -> float:
        return sum(leg.pv(m) for leg in self.legs)


class _Clean:
    """A bond's CLEAN value: dirty minus accrued interest (the market convention for 'price')."""

    def __init__(self, bond: FixedBond, anchor: date):
        self.bond, self.anchor = bond, anchor

    def pv(self, m) -> float:
        return self.bond.pv(m) - self.bond.accrued(self.anchor)


def _funding(inst: Instrument, mkt: MarketCurves, new_anchor: date) -> float:
    """Total financing cost of any bonds in the instrument (0 for swaps)."""
    return sum(financing_cost(leg, mkt, new_anchor) for leg in _legs(inst) if isinstance(leg, FixedBond))


def accrual_estimate(inst: Instrument, mkt: MarketCurves, new_anchor: date) -> float:
    """Undiscounted net accrual (EUR) over [today, new_anchor] at today's fixings and forwards, holder's side.

    Receiver: + fixed accrued - floating accrued. Independent of pv(): it only counts days times rates. This is the
    desk's 'carry' arithmetic, and it IS the engine's `carry`. Its PV is about 2% smaller (the coupon is paid later);
    that difference is reported separately in `other`.
    """
    _check_supported(inst, mkt, new_anchor)
    a0, total = mkt.anchor, 0.0
    for leg in _legs(inst):
        if isinstance(leg, IRSwap):
            fixed = sum(DayCount.THIRTY_E_360.fraction(*ov) for p in leg.fixed_periods if (ov := _overlap(p, a0, new_anchor)))
            float_acc = 0.0
            for p in leg.float_periods:
                if ov := _overlap(p, a0, new_anchor):
                    rate = (mkt.projection(leg.index).forward_rate(p.start, p.end) if p.start >= a0
                            else mkt.fixing(leg.index, p))
                    float_acc += DayCount.ACT_360.fraction(*ov) * rate
            total += leg.side.sign * leg.notional * (leg.fixed_rate * fixed - float_acc)
        elif isinstance(leg, FixedBond):
            total += _bond_cash_carry(leg, mkt, new_anchor)
        else:   # OISSwap: fixed ACT/360 vs compounded ESTR growth over the overlap
            fixed = sum(DayCount.ACT_360.fraction(*ov) for p in leg.periods if (ov := _overlap(p, a0, new_anchor)))
            float_acc = sum(mkt.ois.df(ov[0]) / mkt.ois.df(ov[1]) - 1.0
                            for p in leg.periods if (ov := _overlap(p, a0, new_anchor)))
            total += leg.side.sign * leg.notional * (leg.fixed_rate * fixed - float_acc)
    return total


def _clean(inst: Instrument, anchor: date):
    """The clean twin of an instrument (or each leg of a portfolio)."""
    from .risk import Portfolio
    if hasattr(inst, "instruments"):
        return _CleanBook([_clean(leg, anchor) for leg in inst.instruments])
    if isinstance(inst, FixedBond):
        return _Clean(inst, anchor)
    return inst.remaining(anchor)


@dataclass(frozen=True)
class CarryRoll:
    horizon_days: int
    carry: float             # cash accrual: fixed accrued minus floating accrued (undiscounted)
    roll_down: float         # clean MTM change on the static curve
    other: float             # time value of accrued coupons + floating reset effect (= total - carry - roll_down)
    total_static: float      # PV change if the curve does not move
    total_forward: float     # PV change if forwards are realised (= PV0 x (1/DF - 1); 0 for a par swap)
    mtm_forward: float       # everything except the cash accrual if forwards are realised = total_forward - carry
    dv01: float              # parallel DV01 today
    breakeven_bp: float | None         # parallel move (bp, + = rates up) that zeroes total P&L, by full revaluation
    breakeven_approx_bp: float | None  # total_static / dv01: the mental version


def carry_roll(inst: Instrument, mkt: MarketCurves, new_anchor: date) -> CarryRoll:
    """Exact (full revaluation) carry / roll-down decomposition. Questions approximate this; the engine does not."""
    _check_supported(inst, mkt, new_anchor)
    static, fwd = mkt.rolled(new_anchor, "static"), mkt.rolled(new_anchor, "forward")
    pv0 = inst.pv(mkt)
    funding = _funding(inst, mkt, new_anchor)                  # repo cost of any bonds (0 for swaps)
    total_static = inst.pv(static) - pv0 - funding
    total_forward = inst.pv(fwd) - pv0 - funding
    carry = accrual_estimate(inst, mkt, new_anchor)
    roll = _clean(inst, new_anchor).pv(static) - pv0
    dv01 = parallel_dv01(inst, mkt)

    breakeven = approx = None
    if abs(dv01) > 1e-6 * max(1.0, abs(total_static)):
        approx = total_static / dv01
        breakeven = breakeven_move(inst, mkt, new_anchor, CurveShock.parallel(1.0), _static=static,
                                   _guess=max(5.0, 3 * abs(approx)))
    return CarryRoll((new_anchor - mkt.anchor).days, carry, roll, total_static - carry - roll, total_static,
                     total_forward, total_forward - carry, dv01, breakeven, approx)


def breakeven_move(inst: Instrument, mkt: MarketCurves, new_anchor: date, unit_shock: CurveShock, *,
                   _static: MarketCurves | None = None, _guess: float = 20.0) -> float | None:
    """The size x of a move x * unit_shock, applied to the unchanged curve, that makes the holding-period P&L zero.

    Full revaluation. unit_shock=CurveShock.parallel(1) gives the parallel breakeven in bp (+ = rates up);
    CurveShock.points({short: 0, long: 1}) gives the breakeven change in a short/long spread (+ = widening).
    Returns None if no such move exists within a wide bracket (e.g. a book with no exposure to that shape).
    """
    static = _static or mkt.rolled(new_anchor, "static")
    pv0 = inst.pv(mkt)
    funding = _funding(inst, mkt, new_anchor)

    def gap(x: float) -> float:
        scaled = CurveShock(tuple((t, b * x) for t, b in unit_shock.knots))
        return inst.pv(static.shifted(scaled)) - pv0 - funding

    for span in (_guess, 4 * _guess, 16 * _guess):
        if gap(-span) * gap(span) <= 0:
            return find_root(gap, -span, span, tol=1e-6)
    return None


@dataclass(frozen=True)
class Attribution:
    total: float                       # full revaluation of the actual outcome
    carry: float                       # cash accrual
    roll_down: float                   # clean MTM on the unchanged curve
    other_time: float                  # accrued-coupon discounting + floating reset
    delta: float                       # first-order market-move P&L: -sum(KR DV01 at the horizon x move)
    delta_by_key: dict[RiskKey, float]
    residual: float                    # convexity / cross-gamma = total - (carry + roll + other_time + delta)

    @property
    def time(self) -> float:
        """Everything due to time passing on an unchanged curve."""
        return self.carry + self.roll_down + self.other_time


def attribute(inst: Instrument, mkt: MarketCurves, new_anchor: date, shock: CurveShock) -> Attribution:
    """Explain a holding-period P&L: time (carry, roll-down) then the market move (delta, convexity).

    The actual outcome is the STATIC curve shocked by `shock` (a move relative to where the curve sat).
    """
    _check_supported(inst, mkt, new_anchor)
    static = mkt.rolled(new_anchor, "static")
    pv0 = inst.pv(mkt)
    funding = _funding(inst, mkt, new_anchor)
    carry = accrual_estimate(inst, mkt, new_anchor)
    roll = _clean(inst, new_anchor).pv(static) - pv0
    other = inst.pv(static) - pv0 - funding - carry - roll
    total = inst.pv(static.shifted(shock)) - pv0 - funding
    kr = key_rate_dv01(inst, static, curves=("OIS", "E6M"))
    delta = key_rate_first_order_pnl(kr, shock)
    by_key = {k: -d * shock.bp_at(k[1] / 12.0) for k, d in kr.items()}
    return Attribution(total, carry, roll, other, delta, by_key, total - carry - roll - other - delta)


# ---- helpers for questions: the rates a trader reads off the screen ----

def rolled_rates(leg: Instrument, mkt: MarketCurves, new_anchor: date) -> tuple[float, float]:
    """(rate for the remaining maturity on the unchanged curve, same rate if forwards are realised).

    Both are par rates of the leg's CLEAN twin over its remaining dates (a stub swap, so no quoted instrument
    matches exactly; a curve screen interpolates). Their gap is the forward drift the market implies.
    """
    clean = leg.remaining(new_anchor)
    return clean.par_rate(mkt.rolled(new_anchor, "static")), clean.par_rate(mkt.rolled(new_anchor, "forward"))
