import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.instruments import (
    FRA, BasisSwap, FixedBond, IRSwap, OISSwap, Side, bond_convexity, bond_dv01_per_100,
    bond_macaulay_duration, bond_modified_duration, bond_price,
)
from rates_trainer.engine.marketdata import _View
from rates_trainer.engine.risk import par_basis, par_fra, par_irs, par_ois


@pytest.mark.parametrize("make", [par_irs, par_ois])
@pytest.mark.parametrize("years", [1, 5, 10, 30])
def test_par_swaps_have_zero_pv_both_sides(mkt, make, years):
    for side in Side:
        assert make(side, 100e6, years, mkt).pv(mkt) == pytest.approx(0, abs=1e-3)


def test_payer_is_negative_of_receiver_and_moneyness(mkt):
    r = IRSwap.new(Side.RECEIVE, 50e6, 0.03, mkt.spot, 84)
    p = IRSwap.new(Side.PAY, 50e6, 0.03, mkt.spot, 84)
    assert r.pv(mkt) == pytest.approx(-p.pv(mkt))
    par = mkt.par_irs_rate(84)
    assert IRSwap.new(Side.RECEIVE, 10e6, par + 0.001, mkt.spot, 84).pv(mkt) > 0
    assert IRSwap.new(Side.PAY, 10e6, par + 0.001, mkt.spot, 84).pv(mkt) < 0


def test_swap_pv_equals_strike_minus_par_times_annuity(mkt):
    """Independent route: PV = N (K - S) A for a spot-start receiver."""
    s = IRSwap.new(Side.RECEIVE, 100e6, 0.032, mkt.spot, 120)
    assert s.pv(mkt) == pytest.approx(100e6 * (0.032 - mkt.par_irs_rate(120)) * s.annuity(mkt), rel=1e-12)
    o = OISSwap.new(Side.RECEIVE, 100e6, 0.032, mkt.spot, 120)
    assert o.pv(mkt) == pytest.approx(100e6 * (0.032 - mkt.par_ois_rate(120)) * o.annuity(mkt), rel=1e-12)


def test_forward_start_par_swap_zero_pv_and_validation(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 5, mkt, start_years=5)
    assert s.start > mkt.spot and s.pv(mkt) == pytest.approx(0, abs=1e-3)
    with pytest.raises(ValueError):
        IRSwap.new(Side.PAY, -1e6, 0.02, mkt.spot, 60)
    with pytest.raises(ValueError):
        IRSwap.new(Side.PAY, 1e6, 0.02, mkt.spot, 15)       # stub


def test_ois_float_leg_is_discount_factor_difference(mkt):
    s = OISSwap.new(Side.RECEIVE, 1.0, 0.0, mkt.spot, 60, start_months=12)
    assert s.float_leg_pv(mkt) == pytest.approx(mkt.ois.df(s.start) - mkt.ois.df(s.maturity), rel=1e-14)


def test_ois_annuity_uses_act360(mkt):
    s = OISSwap.new(Side.RECEIVE, 1.0, 0.0, mkt.spot, 12)
    assert len(s.periods) == 1
    assert s.annuity(mkt) == pytest.approx(365 / 360 * mkt.ois.df(s.maturity), rel=1e-12)


# ---- FRA ----

def test_par_fra_zero_pv_and_direction(mkt):
    f = par_fra(Side.PAY, 100e6, 6, 12, mkt)
    assert f.pv(mkt) == pytest.approx(0, abs=1e-3)
    assert f.rate == pytest.approx(mkt.projection("E6M").forward_rate(f.period.start, f.period.end))
    up = mkt.shifted(CurveShock.parallel(5))
    assert f.pv(up) > 0                                             # buyer (pays fixed) gains when rates rise
    assert FRA.new(Side.RECEIVE, 100e6, f.rate, mkt.spot, 6, 12).pv(up) == pytest.approx(-f.pv(up))


def test_fra_formula_and_single_curve_identity(mkt):
    """FRA payoff N tau (K - F)/(1 + F tau) settled at the START and discounted from there. With a single
    curve, 1 + F tau = DF(start)/DF(end), so the PV collapses to N tau (K - F) DF(end): a one-period swap."""
    single = _View(mkt.ois, {"E6M": mkt.ois})
    fra = FRA.new(Side.RECEIVE, 1e6, 0.025, mkt.spot, 6, 12)
    tau = (fra.period.end - fra.period.start).days / 360
    f = single.ois.forward_rate(fra.period.start, fra.period.end)
    expected = 1e6 * tau * (0.025 - f) / (1 + f * tau) * single.ois.df(fra.period.start)
    assert fra.pv(single) == pytest.approx(expected, rel=1e-12)
    assert expected == pytest.approx(1e6 * tau * (0.025 - f) * single.ois.df(fra.period.end), rel=1e-12)


def test_fra_validation(mkt):
    with pytest.raises(ValueError):
        FRA.new(Side.PAY, 1e6, 0.02, mkt.spot, 3, 12)      # 9M: only 3M and 6M FRAs are offered
    assert FRA.new(Side.PAY, 1e6, 0.02, mkt.spot, 3, 6).index == "E3M"
    assert FRA.new(Side.PAY, 1e6, 0.02, mkt.spot, 6, 12).index == "E6M"
    assert FRA.new(Side.PAY, 1e6, 0.02, mkt.spot, 3, 9).index == "E6M"


# ---- basis swap ----

def test_par_basis_zero_pv_and_direction(mkt):
    b = par_basis(Side.PAY, 100e6, 10, mkt)                         # long the basis
    assert b.pv(mkt) == pytest.approx(0, abs=1e-3)
    assert b.spread == pytest.approx(mkt.quotes["BASIS_3S6S"][120], abs=1e-12)
    wider = mkt.bumped("BASIS_3S6S", 120, 1.0)
    assert b.pv(wider) > 0                                          # pay spread, spread widens => gain
    assert BasisSwap.new(Side.RECEIVE, 100e6, b.spread, mkt.spot, 120).pv(wider) == pytest.approx(-b.pv(wider))
    # PV of 1bp spread = N * 1bp * annuity of the 3M leg
    leg_annuity = sum((p.end - p.start).days / 360 * mkt.ois.df(p.pay) for p in b.periods_3m)
    assert b.pv(wider) == pytest.approx(100e6 * 1e-4 * leg_annuity, rel=1e-3)


# ---- bonds ----

def test_bond_curve_pv_is_discounted_cash_flows(mkt):
    b = FixedBond.new(10e6, 0.025, mkt.spot, 10)
    expected = 10e6 * (0.025 * sum(mkt.ois.df(p.pay) for p in b.periods) + mkt.ois.df(b.maturity))
    assert b.pv(mkt) == pytest.approx(expected)
    z = FixedBond.new(10e6, 0.0, mkt.spot, 5)
    assert z.price(mkt) == pytest.approx(100 * mkt.ois.df(z.maturity))
    short = FixedBond.new(-10e6, 0.025, mkt.spot, 10)
    assert short.pv(mkt) == pytest.approx(-b.pv(mkt))


def test_bond_at_par_yield_prices_at_100():
    for n in (2, 10, 30):
        assert bond_price(0.03, n, 0.03) == pytest.approx(100.0)


def test_bond_price_closed_form():
    c, n, y = 0.025, 10, 0.034
    v = 1 / (1 + y)
    assert bond_price(c, n, y) == pytest.approx(100 * c * (1 - v**n) / y + 100 * v**n, rel=1e-12)


def test_zero_coupon_duration_is_maturity():
    assert bond_macaulay_duration(0.0, 7, 0.03) == pytest.approx(7.0)
    assert bond_modified_duration(0.0, 7, 0.03) == pytest.approx(7 / 1.03)


@pytest.mark.parametrize("c,n,y", [(0.025, 10, 0.03), (0.0, 5, 0.01), (0.04, 30, 0.035)])
def test_bond_duration_convexity_vs_finite_difference(c, n, y):
    h = 1e-5
    p0, up, dn = bond_price(c, n, y), bond_price(c, n, y + h), bond_price(c, n, y - h)
    assert bond_modified_duration(c, n, y) == pytest.approx(-(up - dn) / (2 * h) / p0, rel=1e-6)
    assert bond_convexity(c, n, y) == pytest.approx((up - 2 * p0 + dn) / h**2 / p0, rel=1e-4)
    assert bond_dv01_per_100(c, n, y) == pytest.approx((dn - up) / (2 * h) * 1e-4, rel=1e-6)
