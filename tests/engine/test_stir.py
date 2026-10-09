"""3M Euribor futures: contract mechanics, the sign conventions and a strip against a swap."""

from datetime import date

import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.dates import DayCount
from rates_trainer.engine.dates import Period
from rates_trainer.engine.instruments import FRA, Side
from rates_trainer.engine.pnl import first_order_pnl, revalue_pnl
from rates_trainer.engine.risk import Portfolio, par_irs, parallel_dv01
from rates_trainer.engine.stir import (
    BP_VALUE, POINT_VALUE, STIRFuture, convexity_adjustment, imm_dates_after, strip, third_wednesday)


def test_third_wednesday_and_imm_dates():
    assert third_wednesday(2026, 12) == date(2026, 12, 16)
    assert third_wednesday(2027, 3) == date(2027, 3, 17)
    assert all(third_wednesday(y, m).weekday() == 2 and 15 <= third_wednesday(y, m).day <= 21 for y in (2026, 2027) for m in (3, 6, 9, 12))
    dates = imm_dates_after(date(2026, 10, 12), 4)
    assert dates == [date(2026, 12, 16), date(2027, 3, 17), date(2027, 6, 16), date(2027, 9, 15), date(2027, 12, 15)]
    assert imm_dates_after(date(2026, 12, 16), 1)[0] == date(2027, 3, 17)            # strictly after


def test_price_is_100_minus_rate_and_a_tick_is_12_50_euro(mkt):
    f = STIRFuture(1, date(2027, 3, 17), date(2027, 6, 16))
    fwd = mkt.projection("E3M").forward_rate(f.start, f.end)
    assert f.price(mkt) == pytest.approx(100 - 100 * fwd, abs=1e-12)
    assert POINT_VALUE * 0.005 == 12.5 and BP_VALUE == 25.0 and POINT_VALUE * 0.01 == BP_VALUE      # 1bp = 0.01 price points
    assert f.pv(mkt) == pytest.approx(2500 * f.price(mkt))


def test_long_future_is_long_duration_and_dv01_is_about_25_per_bp(mkt):
    f = STIRFuture(1, date(2027, 3, 17), date(2027, 6, 16))
    dv01 = parallel_dv01(f, mkt)
    # EUR 25 per bp of the FORWARD rate; a 1bp parallel move of the par swap quotes moves a 3M forward by about 0.96bp (the FRA finding
    # in docs/DESIGN.md: 30E/360 par rates against ACT/360 forwards), so the risk per swap-quote bp is a few % below EUR 25
    assert 23.5 < dv01 < 26.0
    tau = DayCount.ACT_360.fraction(f.start, f.end)
    assert dv01 == pytest.approx(25.0 * 0.965, rel=0.01) and tau * 1e6 * 1e-4 == pytest.approx(25.0, rel=0.02)
    assert revalue_pnl(f, mkt, CurveShock.parallel(+10)) < 0 < revalue_pnl(f, mkt, CurveShock.parallel(-10))   # rates down, price up
    assert first_order_pnl(dv01, 10) == pytest.approx(revalue_pnl(f, mkt, CurveShock.parallel(10)), rel=0.01)


def test_long_future_behaves_like_a_receiver_fra(mkt):
    """Long a 3M future ~ receive the FRA rate (long duration); same sign of risk, DV01 within the day-count difference."""
    f = STIRFuture(1, date(2027, 3, 17), date(2027, 6, 16))
    fra = FRA(Side.RECEIVE, 1e6, f.forward(mkt), Period(f.start, f.end, f.end), "E3M")
    assert parallel_dv01(fra, mkt) * parallel_dv01(f, mkt) > 0
    assert parallel_dv01(fra, mkt) == pytest.approx(parallel_dv01(f, mkt), rel=0.05)


def test_convexity_adjustment_makes_the_futures_rate_higher_and_grows_with_time(mkt):
    ca1, ca2, ca5 = (convexity_adjustment(t, t + 0.25) for t in (1.0, 2.0, 5.0))
    assert 0 < ca1 < ca2 < ca5
    assert ca2 == pytest.approx(0.5 * 0.007 ** 2 * 2.0 * 2.25)
    assert ca2 * 1e4 == pytest.approx(1.1, abs=0.05)                                 # about 1bp two years out
    plain = STIRFuture(1, date(2028, 12, 20), date(2029, 3, 21))
    adjusted = STIRFuture(1, date(2028, 12, 20), date(2029, 3, 21), convexity=ca5)
    assert adjusted.rate(mkt) == pytest.approx(plain.rate(mkt) + ca5) and adjusted.price(mkt) < plain.price(mkt)
    assert parallel_dv01(adjusted, mkt) == pytest.approx(parallel_dv01(plain, mkt), rel=1e-9)     # a fixed adjustment adds no risk


def test_strip_dv01_is_about_25_per_quarter_and_hedges_a_swaps_parallel_risk(mkt):
    for years in (2, 3):
        n = 4 * years
        s = strip(mkt.anchor, n)
        assert len(s) == n and all(a.end == b.start for a, b in zip(s, s[1:]))
        strip_dv01 = sum(parallel_dv01(c, mkt) for c in s)
        assert strip_dv01 == pytest.approx(25.0 * n, rel=0.05)
        swap = par_irs(Side.RECEIVE, 100e6, years, mkt)
        k = -parallel_dv01(swap, mkt) / strip_dv01                                    # contracts per quarter: SELL
        assert k < 0
        book = Portfolio([swap] + [STIRFuture(k, c.start, c.end, c.convexity) for c in s])
        assert parallel_dv01(book, mkt) == pytest.approx(0, abs=1e-9 * abs(parallel_dv01(swap, mkt)) + 1e-6)
        # the mental route: swap DV01 / (EUR 25 x quarters) is within a few % of the exact number of contracts per quarter
        assert -k == pytest.approx(parallel_dv01(swap, mkt) / (25.0 * n), rel=0.06)
        # hedged against a parallel move, left with a small residual (stub before the first IMM, discounting, 6M vs 3M)
        resid = revalue_pnl(book, mkt, CurveShock.parallel(10))
        assert abs(resid) < 0.05 * abs(first_order_pnl(parallel_dv01(swap, mkt), 10))
