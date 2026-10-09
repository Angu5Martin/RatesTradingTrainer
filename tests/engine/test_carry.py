"""Carry, roll-down and attribution: exact identities first, then behaviour and signs."""

from datetime import date, timedelta

import pytest

from rates_trainer.engine.carry import (
    accrual_estimate, attribute, carry_roll, rolled_rates,
)
from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.instruments import FixedBond, IRSwap, Side
from rates_trainer.engine.marketdata import MarketCurves
from rates_trainer.engine.risk import Portfolio, par_fra, par_irs, par_ois, parallel_dv01

from ..conftest import BASIS, E6M, OIS, TRADE_DATE, make_market

HORIZONS = (dict(days=1), dict(days=7), dict(months=1), dict(months=3))


def gross(swap, days):
    return swap.notional * swap.fixed_rate * days / 360


# ------------------------------------------------------------------ rolled markets

def test_static_roll_keeps_quotes_by_tenor_and_moves_the_anchor(mkt):
    a1 = mkt.horizon_date(months=3)
    st = mkt.rolled(a1, "static")
    assert st.anchor == a1 and st.history is mkt
    assert st.quotes == mkt.quotes
    assert st.par_irs_rate(120) == pytest.approx(E6M[120], abs=1e-12)          # the 10Y is still 10Y
    assert st.ois.dates[-1] > mkt.ois.dates[-1]                                 # ...but its maturity date moved


def test_forward_roll_preserves_forwards_and_implies_new_quotes(mkt):
    a1 = mkt.horizon_date(months=3)
    fw = mkt.rolled(a1, "forward")
    d1, d2 = mkt.ois.dates[4], mkt.ois.dates[6]
    assert fw.ois.forward_rate(d1, d2) == pytest.approx(mkt.ois.forward_rate(d1, d2), rel=1e-12)
    e1, e2 = mkt.projection("E6M").dates[3], mkt.projection("E6M").dates[5]
    assert fw.projection("E6M").forward_rate(e1, e2) == pytest.approx(mkt.projection("E6M").forward_rate(e1, e2), rel=1e-12)
    assert fw.quotes["E6M"][120] != E6M[120]                                    # the 10Y par rate drifts with the forwards


def test_roll_validation(mkt):
    with pytest.raises(ValueError):
        mkt.rolled(mkt.anchor, "static")                                        # not forward in time
    with pytest.raises(ValueError):
        mkt.rolled(date(2026, 10, 17), "static")                                # a Saturday
    with pytest.raises(ValueError):
        mkt.rolled(mkt.horizon_date(months=1), "sideways")


def test_aged_swap_needs_a_fixing_source(mkt):
    swap = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    a1 = mkt.horizon_date(months=3)
    fresh = MarketCurves(TRADE_DATE + timedelta(days=0), {"OIS": OIS, "E6M": E6M})   # same dates, no history
    aged_no_history = MarketCurves(mkt.rolled(a1, "static").trade_date, mkt.quotes)
    with pytest.raises(ValueError, match="fixing"):
        swap.pv(aged_no_history)
    # an explicit fixing makes it priceable, and equals pricing through history
    p = swap.float_periods[0]
    explicit = MarketCurves(aged_no_history.trade_date, mkt.quotes,
                            fixings={"E6M": {p.start: mkt.projection("E6M").forward_rate(p.start, p.end)}})
    assert swap.pv(explicit) == pytest.approx(swap.pv(mkt.rolled(a1, "static")), rel=1e-12)
    assert fresh.anchor == mkt.anchor


# ------------------------------------------------------------------ the exact identities

@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("make", [par_irs, par_ois])
@pytest.mark.parametrize("side", list(Side))
def test_forwards_realised_par_swap_earns_nothing(mkt, horizon, make, side):
    """Identity 1: carry is exactly offset by the MTM drift the forwards impose. Total = 0."""
    s = make(side, 100e6, 10, mkt)
    c = carry_roll(s, mkt, mkt.horizon_date(**horizon))
    assert c.total_forward == pytest.approx(0, abs=1e-6)
    assert c.mtm_forward == pytest.approx(-c.carry, abs=1e-6)


@pytest.mark.parametrize("horizon", HORIZONS)
def test_forwards_realised_off_market_swap_just_grows_at_the_funding_rate(mkt, horizon):
    """General form: PV_h = PV_0 / DF_0(h)  =>  total_forward = PV_0 x (1/DF - 1)."""
    s = IRSwap.new(Side.RECEIVE, 100e6, 0.040, mkt.spot, 120)                  # deep in the money
    a1 = mkt.horizon_date(**horizon)
    c = carry_roll(s, mkt, a1)
    assert c.total_forward == pytest.approx(s.pv(mkt) * (1 / mkt.ois.df(a1) - 1), rel=1e-9)


def test_carry_roll_total_decomposes_exactly(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    c = carry_roll(s, mkt, mkt.horizon_date(months=3))
    assert c.carry + c.roll_down + c.other == pytest.approx(c.total_static)
    assert c.carry + c.mtm_forward == pytest.approx(c.total_forward, abs=1e-6)


@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("make", [par_irs, par_ois])
def test_carry_is_exactly_the_cash_accrual_arithmetic(mkt, horizon, make):
    """Independent route: fixed accrued minus floating accrued, days times rates, undiscounted. Nothing else."""
    from rates_trainer.engine.dates import DayCount
    s = make(Side.RECEIVE, 100e6, 10, mkt)
    a1 = mkt.horizon_date(**horizon)
    c = carry_roll(s, mkt, a1)
    days = (a1 - mkt.anchor).days
    if make is par_irs:
        p0 = s.float_periods[0]
        float_rate = mkt.projection("E6M").forward_rate(p0.start, p0.end)
        fixed_time = DayCount.THIRTY_E_360.fraction(mkt.anchor, a1)
    else:
        float_rate = (mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1) / (days / 360)
        fixed_time = days / 360
    by_hand = 100e6 * (s.fixed_rate * fixed_time - float_rate * days / 360)
    assert c.carry == pytest.approx(by_hand, rel=1e-12)
    assert c.carry == pytest.approx(accrual_estimate(s, mkt, a1), rel=1e-12)


@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("make,limit", [(par_ois, 0.04), (par_irs, 0.13)])
def test_other_is_small_next_to_the_gross_accrual(mkt, horizon, make, limit):
    """`other` = time value of accrued coupons (+ the floating reset effect on an IRS): a few % of the gross accrual."""
    s = make(Side.RECEIVE, 100e6, 10, mkt)
    c = carry_roll(s, mkt, mkt.horizon_date(**horizon))
    assert abs(c.other) <= limit * gross(s, c.horizon_days)


def test_roll_down_is_the_clean_mark_to_market_and_matches_the_screen_rate_estimate(mkt):
    """roll-down = clean twin repriced on the unchanged curve minus today's PV, and DV01 x (K - rate for the remaining
    maturity) predicts it to within the annuity ratio (~ horizon / tenor)."""
    for make in (par_irs, par_ois):
        for tenor, months in ((5, 3), (10, 3), (10, 1), (30, 3)):
            s = make(Side.RECEIVE, 100e6, tenor, mkt)
            a1 = mkt.horizon_date(months=months)
            c = carry_roll(s, mkt, a1)
            static = mkt.rolled(a1, "static")
            assert c.roll_down == pytest.approx(s.remaining(a1).pv(static) - s.pv(mkt), rel=1e-12)
            s_rem, _ = rolled_rates(s, mkt, a1)
            predicted = c.dv01 * (s.fixed_rate - s_rem) * 1e4
            assert c.roll_down == pytest.approx(predicted, rel=0.02 + months / 12 / tenor, abs=0.06 * abs(c.dv01))


def test_sign_symmetry_and_linearity(mkt):
    r = par_irs(Side.RECEIVE, 100e6, 7, mkt)
    p = par_irs(Side.PAY, 100e6, 7, mkt)
    big = par_irs(Side.RECEIVE, 300e6, 7, mkt)
    a1 = mkt.horizon_date(months=3)
    cr, cp, cb = carry_roll(r, mkt, a1), carry_roll(p, mkt, a1), carry_roll(big, mkt, a1)
    for f in ("carry", "roll_down", "other", "total_static"):
        assert getattr(cp, f) == pytest.approx(-getattr(cr, f), rel=1e-9)
        assert getattr(cb, f) == pytest.approx(3 * getattr(cr, f), rel=1e-9)
    assert cb.breakeven_bp == pytest.approx(cr.breakeven_bp, rel=1e-6)       # breakeven is per-bp: notional free


def test_upward_slope_pays_a_receiver_inverted_curve_charges_one():
    s = make_market()
    r = carry_roll(par_irs(Side.RECEIVE, 100e6, 10, s), s, s.horizon_date(months=3))
    assert r.carry > 0 and r.roll_down > 0 and r.total_static > 0 and r.breakeven_bp > 0
    inverted = MarketCurves(TRADE_DATE, {
        "OIS": {m: 0.032 - 0.00008 * m ** 0.9 for m in OIS},
        "E6M": {m: 0.0335 - 0.00008 * m ** 0.9 for m in E6M}})
    assert inverted.quotes["E6M"][6] > inverted.quotes["E6M"][360]
    ri = carry_roll(par_irs(Side.RECEIVE, 100e6, 10, inverted), inverted, inverted.horizon_date(months=3))
    assert ri.carry < 0 and ri.roll_down < 0 and ri.total_static < 0           # pays to wait
    rp = carry_roll(par_irs(Side.PAY, 100e6, 10, inverted), inverted, inverted.horizon_date(months=3))
    assert rp.total_static > 0 and rp.breakeven_bp < 0       # the payer is paid to wait, and loses if rates FALL by ~2.7bp


def test_forward_start_swap_rolls_down_without_carrying(mkt):
    """A 5y5y receiver has not started: no coupon accrues (carry exactly 0), but its start moves closer."""
    s = par_irs(Side.RECEIVE, 100e6, 5, mkt, start_years=5)
    c = carry_roll(s, mkt, mkt.horizon_date(months=3))
    assert c.carry == pytest.approx(0, abs=1e-9)
    assert c.roll_down > 0 and c.total_static == pytest.approx(c.roll_down)
    assert c.total_forward == pytest.approx(0, abs=1e-6)


def test_ois_breakeven_equals_the_forward_drift(mkt):
    """Identity 2/3 on a single-curve product: total/DV01 and the exact breakeven are the forward-minus-spot drift."""
    s = par_ois(Side.RECEIVE, 100e6, 10, mkt)
    for months in (1, 3):
        a1 = mkt.horizon_date(months=months)
        c = carry_roll(s, mkt, a1)
        spot, fwd = rolled_rates(s, mkt, a1)
        assert c.breakeven_bp == pytest.approx((fwd - spot) * 1e4, abs=0.02)
        assert c.total_static == pytest.approx(c.dv01 * (fwd - spot) * 1e4, rel=0.03)


def test_irs_breakeven_is_close_to_the_forward_drift(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    a1 = mkt.horizon_date(months=3)
    c = carry_roll(s, mkt, a1)
    spot, fwd = rolled_rates(s, mkt, a1)
    assert c.breakeven_bp == pytest.approx((fwd - spot) * 1e4, abs=0.3)          # multi-curve fixing effect, not a bug
    assert c.breakeven_approx_bp == pytest.approx(c.breakeven_bp, abs=0.2)


def test_breakeven_really_zeroes_the_pnl(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    a1 = mkt.horizon_date(months=3)
    c = carry_roll(s, mkt, a1)
    static = mkt.rolled(a1, "static")
    total = s.pv(static.shifted(CurveShock.parallel(c.breakeven_bp))) - s.pv(mkt)
    assert total == pytest.approx(0, abs=1.0)
    assert s.pv(static.shifted(CurveShock.parallel(c.breakeven_bp - 1))) - s.pv(mkt) > 0   # rates lower than BE => profit


def test_breakeven_is_none_for_a_dv01_flat_book(mkt):
    r, p = par_irs(Side.RECEIVE, 100e6, 10, mkt), par_irs(Side.PAY, 100e6, 10, mkt)
    c = carry_roll(Portfolio([r, p]), mkt, mkt.horizon_date(months=1))
    assert c.breakeven_bp is None and c.total_static == pytest.approx(0, abs=1e-6)


def test_portfolio_is_the_sum_of_its_legs(mkt):
    a = par_irs(Side.RECEIVE, 100e6, 2, mkt)
    b = par_irs(Side.PAY, 25e6, 10, mkt)
    a1 = mkt.horizon_date(months=3)
    both, ca, cb = carry_roll(Portfolio([a, b]), mkt, a1), carry_roll(a, mkt, a1), carry_roll(b, mkt, a1)
    for f in ("carry", "roll_down", "other", "total_static"):
        assert getattr(both, f) == pytest.approx(getattr(ca, f) + getattr(cb, f), rel=1e-9)


def test_horizon_and_instrument_limits(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    with pytest.raises(ValueError, match="payment date"):
        carry_roll(s, mkt, mkt.horizon_date(months=7))                          # crosses the 6M float payment
    with pytest.raises(NotImplementedError):
        carry_roll(par_fra(Side.RECEIVE, 10e6, 6, 12, mkt), mkt, mkt.horizon_date(months=1))


# ------------------------------------------------------------------ attribution

def test_attribution_with_no_move_is_just_time(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    a1 = mkt.horizon_date(months=1)
    a = attribute(s, mkt, a1, CurveShock.parallel(0))
    c = carry_roll(s, mkt, a1)
    assert a.carry == pytest.approx(c.carry) and a.roll_down == pytest.approx(c.roll_down)
    assert a.other_time == pytest.approx(c.other) and a.time == pytest.approx(c.total_static)
    assert a.total == pytest.approx(c.total_static)
    assert a.delta == pytest.approx(0, abs=1e-9) and a.residual == pytest.approx(0, abs=1e-6)


def test_attribution_components_sum_and_the_residual_is_convexity(mkt):
    s = par_irs(Side.RECEIVE, 250e6, 30, mkt)
    a1 = mkt.horizon_date(months=1)
    r50 = attribute(s, mkt, a1, CurveShock.parallel(50))
    r100 = attribute(s, mkt, a1, CurveShock.parallel(100))
    for a in (r50, r100):
        assert a.time + a.delta + a.residual == pytest.approx(a.total)
        assert a.carry + a.roll_down + a.other_time == pytest.approx(a.time)
        assert a.delta < 0 and a.residual > 0                                   # rates up: lose on delta, convexity helps
    assert r100.residual / r50.residual == pytest.approx(4.0, rel=0.1)           # second order
    assert r100.delta == pytest.approx(2 * r50.delta, rel=0.01)                  # first order
    # carry+roll are the same whatever the market does
    assert r100.carry == pytest.approx(r50.carry) and r100.roll_down == pytest.approx(r50.roll_down)


def test_attribution_by_key_for_a_curve_move(mkt):
    two = par_irs(Side.RECEIVE, 100e6, 2, mkt)
    ten = par_irs(Side.PAY, 20e6, 10, mkt)
    shock = CurveShock.points({2: -5, 10: 3})
    a = attribute(Portfolio([two, ten]), mkt, mkt.horizon_date(months=1), shock)
    assert a.delta == pytest.approx(sum(a.delta_by_key.values()))
    assert a.delta_by_key[("E6M", 24)] > 0 and a.delta_by_key[("E6M", 120)] > 0   # both legs make money from this move


def test_weekend_carry_accrues_on_calendar_days():
    """Spot on a Friday: a one-day horizon rolls to Monday, so three days of carry accrue in one step."""
    fri = MarketCurves(date(2026, 10, 14), {"OIS": OIS, "E6M": E6M})              # Wed trade date => Fri 16 Oct spot
    assert fri.anchor == date(2026, 10, 16) and fri.anchor.weekday() == 4
    s = par_irs(Side.RECEIVE, 100e6, 10, fri)
    over_weekend = carry_roll(s, fri, fri.horizon_date(days=1))
    assert over_weekend.horizon_days == 3
    mon = MarketCurves(date(2026, 10, 19), {"OIS": OIS, "E6M": E6M})              # Mon trade date => Wed spot
    midweek = carry_roll(par_irs(Side.RECEIVE, 100e6, 10, mon), mon, mon.horizon_date(days=1))
    assert midweek.horizon_days == 1
    assert over_weekend.carry == pytest.approx(3 * midweek.carry, rel=0.06)


def test_paid_periods_drop_out_of_aged_pricing(mkt):
    """Aged pricing must exclude coupons already paid (the horizon check keeps carry_roll from crossing one, so
    this guards the pricing code directly): 13 months on, the 12M fixed coupon and the first two float periods are gone."""
    swap = par_irs(Side.RECEIVE, 1.0, 10, mkt)
    a1 = mkt.horizon_date(months=13)
    aged_mkt = mkt.rolled(a1, "static")
    remaining = [p for p in swap.fixed_periods if p.pay > a1]
    assert len(remaining) == len(swap.fixed_periods) - 1
    from rates_trainer.engine.dates import DayCount
    expected = sum(DayCount.THIRTY_E_360.fraction(p.start, p.end) * aged_mkt.ois.df(p.pay) for p in remaining)
    assert swap.annuity(aged_mkt) == pytest.approx(expected, rel=1e-12)
    assert len([p for p in swap.float_periods if p.pay > a1]) == len(swap.float_periods) - 2
    # and the OIS flavour: the float leg only counts unpaid periods
    ois = par_ois(Side.RECEIVE, 1.0, 10, mkt)
    unpaid = [p for p in ois.periods if p.pay > a1]
    assert len(unpaid) == 9
    assert ois.float_leg_pv(aged_mkt) == pytest.approx(
        sum((aged_mkt.ois.df(p.start) if p.start >= a1 else aged_mkt.ois_growth(p.start)) - aged_mkt.ois.df(p.end) for p in unpaid))
