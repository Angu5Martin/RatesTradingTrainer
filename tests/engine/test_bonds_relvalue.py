"""Bonds vs swaps: ASW pricing, the asset-swap package, ICMA yield maths, repo financing and bond carry."""

from datetime import timedelta

import pytest

from rates_trainer.engine.carry import attribute, carry_roll, financing_cost
from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.instruments import AssetSwapPackage, FixedBond, bond_price
from rates_trainer.engine.risk import par_irs, parallel_dv01
from rates_trainer.engine.instruments import Side

BP = 1e-4


# ------------------------------------------------------------------ asset-swap spread

def test_asw_is_the_spread_between_swap_curve_value_and_market_price(mkt):
    """Cheap bond (price below swap-curve value) <=> positive ASW; the price is V - asw x A exactly."""
    b0 = FixedBond.new(100e6, 0.03, mkt.spot, 10)
    v = b0.swap_curve_value(mkt)
    a = b0.spread_annuity(mkt)
    assert b0.price(mkt) == pytest.approx(100 * v, rel=1e-12)
    for asw in (-0.0020, 0.0, 0.0040, 0.0120):
        b = b0.with_asw(asw)
        assert b.price(mkt) == pytest.approx(100 * (v - asw * a), rel=1e-12)
        assert b0.asw_from_price(mkt, b.price(mkt)) == pytest.approx(asw, abs=1e-13)
    assert b0.with_asw(0.004).price(mkt) < b0.price(mkt) < b0.with_asw(-0.002).price(mkt)    # wider ASW = cheaper


def test_asw_is_about_yield_minus_swap_rate_on_a_bond_basis(mkt):
    """Independent route: ASW ~ (bond yield - OIS par yield at the same maturity), for a bond not far from par."""
    for years, coupon in ((5, 0.026), (10, 0.0285), (30, 0.030)):
        par_yield = mkt.bond_basis_swap_rate(years)
        par_bond = FixedBond.new(1.0, par_yield, mkt.spot, years)
        assert par_bond.price(mkt) == pytest.approx(100.0, abs=1e-9)                 # the bond-basis par rate IS par
        b = FixedBond.new(100e6, coupon, mkt.spot, years, asw=0.0050)
        y = b.yield_from_dirty(mkt.anchor, b.price(mkt))
        assert (y - par_yield) == pytest.approx(0.0050, abs=0.0003 + 0.05 * 0.0050)


def test_spread_annuity_is_the_float_leg_annuity_on_the_bond_dates(mkt):
    b = FixedBond.new(1.0, 0.03, mkt.spot, 10)
    by_hand = sum((p.end - p.start).days / 360 * mkt.ois.df(p.pay) for p in b.periods)
    assert b.spread_annuity(mkt) == pytest.approx(by_hand, rel=1e-14)
    assert 8.3 < b.spread_annuity(mkt) < 9.4


# ------------------------------------------------------------------ the package

def test_asset_swap_package_is_par_at_inception_and_a_pure_spread_instrument(mkt):
    b = FixedBond.new(100e6, 0.03, mkt.spot, 10, asw=0.0040)
    pkg = AssetSwapPackage(b, locked_spread=0.0040)
    assert pkg.pv(mkt) == pytest.approx(100e6, rel=1e-12)                              # par-par: costs par
    a = b.spread_annuity(mkt)
    for new_asw in (0.0020, 0.0040, 0.0075):
        moved = AssetSwapPackage(b.with_asw(new_asw), 0.0040)
        closed_form = 100e6 * (1 + (0.0040 - new_asw) * a)                              # independent closed form
        assert moved.pv(mkt) == pytest.approx(closed_form, rel=1e-12)
    # tightening 10bp gains N x A x 10bp; widening loses the same
    gain = AssetSwapPackage(b.with_asw(0.0030), 0.0040).pv(mkt) - pkg.pv(mkt)
    assert gain == pytest.approx(100e6 * a * 10 * BP, rel=1e-12) and gain > 0
    # ...and it carries no outright rate risk at inception: a parallel move leaves it at par
    assert parallel_dv01(pkg, mkt) == pytest.approx(0, abs=1e-3)
    for shift in (-50, 50):
        assert pkg.pv(mkt.shifted(CurveShock.parallel(shift))) == pytest.approx(100e6, rel=1e-12)


def test_asw01_equals_notional_times_annuity_and_is_close_to_a_swap_dv01(mkt):
    b = FixedBond.new(100e6, 0.03, mkt.spot, 10, asw=0.003)
    asw01 = 100e6 * b.spread_annuity(mkt) * BP
    cheaper = b.with_asw(0.003 + BP)
    assert b.pv(mkt) - cheaper.pv(mkt) == pytest.approx(asw01, rel=1e-12)
    swap_dv01 = parallel_dv01(par_irs(Side.RECEIVE, 100e6, 10, mkt), mkt)
    assert asw01 == pytest.approx(swap_dv01, rel=0.05)             # a bp of ASW is worth about a bp of swap rate


def test_package_refuses_an_aged_market(mkt):
    b = FixedBond.new(1e6, 0.03, mkt.spot, 10, asw=0.003)
    with pytest.raises(ValueError):
        AssetSwapPackage(b, 0.003).pv(mkt.rolled(mkt.horizon_date(months=1), "static"))


# ------------------------------------------------------------------ ICMA yield maths

def test_dated_yield_maths_reduces_to_whole_year_maths_at_a_coupon_date(mkt):
    b = FixedBond.new(1.0, 0.0275, mkt.spot, 10)
    for y in (0.01, 0.0275, 0.045):
        assert b.dirty_from_yield(mkt.anchor, y) == pytest.approx(bond_price(0.0275, 10, y), rel=1e-12)
    assert b.yield_from_dirty(mkt.anchor, 97.5) == pytest.approx(
        b.yield_from_dirty(mkt.anchor, bond_price(0.0275, 10, b.yield_from_dirty(mkt.anchor, 97.5))))
    p = b.dirty_from_yield(mkt.anchor, 0.031)
    assert b.yield_from_dirty(mkt.anchor, p) == pytest.approx(0.031, abs=1e-12)


def test_dirty_price_at_constant_yield_accretes_exactly_by_the_fraction_of_period(mkt):
    """dirty(anchor + d days, y) = dirty(0, y) x (1+y)^(d / period days), by construction of ICMA time."""
    b = FixedBond.new(1.0, 0.03, mkt.spot, 10)
    a1 = mkt.horizon_date(months=3)
    first = b.periods[0]
    frac = (a1 - mkt.anchor).days / (first.end - first.start).days
    assert b.dirty_from_yield(a1, 0.034) == pytest.approx(b.dirty_from_yield(mkt.anchor, 0.034) * 1.034 ** frac, rel=1e-12)


def test_accrued_interest_is_pro_rata_within_the_period(mkt):
    b = FixedBond.new(100e6, 0.03, mkt.spot, 10)
    assert b.accrued(mkt.anchor) == 0.0
    a1 = mkt.anchor + timedelta(days=73)
    first = b.periods[0]
    assert b.accrued(a1) == pytest.approx(100e6 * 0.03 * 73 / (first.end - first.start).days)
    assert b.accrued(first.end) == 0.0                   # a coupon date: accrued resets


def test_modified_duration_matches_the_closed_form(mkt):
    from rates_trainer.engine.instruments import bond_modified_duration
    b = FixedBond.new(1.0, 0.03, mkt.spot, 10)
    assert b.modified_duration(mkt.anchor, 0.033) == pytest.approx(bond_modified_duration(0.03, 10, 0.033), rel=1e-6)


# ------------------------------------------------------------------ repo financing and bond carry

def make_bond(mkt, notional=100e6, coupon=0.03, years=10, asw=0.0, fs=0.0):
    return FixedBond.new(notional, coupon, mkt.spot, years, asw=asw, funding_spread=fs)


@pytest.mark.parametrize("asw", [-0.001, 0.0, 0.004, 0.012])
@pytest.mark.parametrize("coupon", [0.01, 0.03, 0.045])
@pytest.mark.parametrize("months", [1, 3])
def test_bond_funded_at_forward_estr_earns_nothing_if_forwards_are_realised(mkt, asw, coupon, months):
    """The bond analogue of identity 1: whatever the price or ASW, funding at the forward ESTR path means the
    mark-to-market drift exactly cancels the carry. Positive carry is paid for by the forwards, not free."""
    b = make_bond(mkt, coupon=coupon, asw=asw)
    c = carry_roll(b, mkt, mkt.horizon_date(months=months))
    assert c.total_forward == pytest.approx(0, abs=1e-6)
    assert c.mtm_forward == pytest.approx(-c.carry, abs=1e-6)


@pytest.mark.parametrize("fs", [-0.0030, -0.0010, 0.0010])
def test_specialness_is_worth_market_value_times_spread_times_time(mkt, fs):
    a1 = mkt.horizon_date(months=3)
    days = (a1 - mkt.anchor).days
    gc, sp = make_bond(mkt, asw=0.004), make_bond(mkt, asw=0.004, fs=fs)
    cg, cs = carry_roll(gc, mkt, a1), carry_roll(sp, mkt, a1)
    gain = -fs * gc.pv(mkt) * days / 360
    assert cs.carry - cg.carry == pytest.approx(gain, rel=1e-9)               # on special (fs<0) => better carry
    assert cs.total_static - cg.total_static == pytest.approx(gain, rel=1e-9)
    assert cs.roll_down == pytest.approx(cg.roll_down)                         # financing does not touch the roll
    assert cs.total_forward == pytest.approx(gain, rel=1e-9)                   # special repo is a genuine edge even at forwards


def test_bond_carry_is_exactly_coupon_accrual_minus_financing(mkt):
    b = make_bond(mkt, coupon=0.032, asw=0.003, fs=-0.0005)
    a1 = mkt.horizon_date(months=3)
    days = (a1 - mkt.anchor).days
    first = b.periods[0]
    coupon_accrual = b.notional * 0.032 * days / (first.end - first.start).days
    estr_growth = mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1
    financing = b.pv(mkt) * (estr_growth - 0.0005 * days / 360)
    assert carry_roll(b, mkt, a1).carry == pytest.approx(coupon_accrual - financing, rel=1e-12)
    assert financing_cost(b, mkt, a1) == pytest.approx(financing, rel=1e-12)


def test_bond_other_is_zero_and_total_is_carry_plus_clean_roll(mkt):
    b = make_bond(mkt, asw=0.004, fs=-0.001)
    a1 = mkt.horizon_date(months=3)
    c = carry_roll(b, mkt, a1)
    static = mkt.rolled(a1, "static")
    assert c.other == pytest.approx(0, abs=1e-6)
    assert c.roll_down == pytest.approx(b.pv(static) - b.accrued(a1) - b.pv(mkt))        # clean price change
    assert c.total_static == pytest.approx(b.pv(static) - b.pv(mkt) - financing_cost(b, mkt, a1))


def test_short_bond_flips_every_term_and_carry_signs_follow_repo_versus_yield(mkt):
    a1 = mkt.horizon_date(months=3)
    long_, short = make_bond(mkt, asw=0.004, fs=-0.001), make_bond(mkt, notional=-100e6, asw=0.004, fs=-0.001)
    cl, cs = carry_roll(long_, mkt, a1), carry_roll(short, mkt, a1)
    for f in ("carry", "roll_down", "total_static", "total_forward"):
        assert getattr(cs, f) == pytest.approx(-getattr(cl, f), rel=1e-9, abs=1e-6)
    # a low coupon funded at ESTR is negative carry; a high coupon positive; breakeven repo ~ coupon / dirty price
    assert carry_roll(make_bond(mkt, coupon=0.005), mkt, a1).carry < 0 < carry_roll(make_bond(mkt, coupon=0.05), mkt, a1).carry


def test_carry_changes_sign_at_roughly_the_current_yield_on_dirty_price(mkt):
    """Carry = 0 when the repo rate equals coupon x (360/period days) / dirty price per unit; the quick form is the
    current yield c / (P/100), within about the 360/365 day-count factor."""
    a1 = mkt.horizon_date(months=3)
    days = (a1 - mkt.anchor).days
    b = make_bond(mkt, coupon=0.02, asw=0.002)
    estr = (mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1) * 360 / days
    price = b.price(mkt)
    breakeven_all_in = 0.02 / (price / 100) * 360 / 365
    spread_needed = breakeven_all_in - estr
    zero = make_bond(mkt, coupon=0.02, asw=0.002, fs=spread_needed)
    assert carry_roll(zero, mkt, a1).carry == pytest.approx(0, abs=0.01 * abs(carry_roll(b, mkt, a1).carry) + 500)


def test_yield_pickup_over_repo_and_curve_roll_decompose_the_roll(mkt):
    """roll-down = pull-to-par (clean drift at constant yield) + curve roll (DV01 x yield change);
    carry + pull-to-par ~ MV x (yield - repo) x time."""
    for coupon, years, asw in ((0.03, 10, 0.004), (0.01, 10, 0.0), (0.045, 5, 0.002)):
        b = make_bond(mkt, coupon=coupon, years=years, asw=asw, fs=-0.001)
        a1 = mkt.horizon_date(months=3)
        days = (a1 - mkt.anchor).days
        c = carry_roll(b, mkt, a1)
        p0 = b.price(mkt)
        y0 = b.yield_from_dirty(mkt.anchor, p0)
        pull = b.notional / 100 * b.dirty_from_yield(a1, y0) - b.accrued(a1) - b.pv(mkt)
        static = mkt.rolled(a1, "static")
        yh = b.yield_from_dirty(a1, b.pv(static) / b.notional * 100)
        dv01 = b.notional / 100 * p0 * b.modified_duration(mkt.anchor, y0) * BP
        assert c.roll_down - pull == pytest.approx(dv01 * (y0 - yh) * 1e4, rel=0.06, abs=0.1 * dv01)
        # EXACT: at an unchanged yield the dirty price grows by (1+y)^(days / period days); carry + pull-to-par is that
        # growth less financing
        period_days = (b.periods[0].end - b.periods[0].start).days
        growth = b.pv(mkt) * ((1 + y0) ** (days / period_days) - 1)
        assert c.carry + pull == pytest.approx(growth - financing_cost(b, mkt, a1), rel=1e-9)
        # the mental form 'MV x (yield - repo) x time' is within the compounding / day-count slop
        repo = financing_cost(b, mkt, a1) / b.pv(mkt) * 360 / days
        assert c.carry + pull == pytest.approx(b.pv(mkt) * (y0 * days / 365 - repo * days / 360), rel=0.06)


def test_bond_pull_to_par_has_the_sign_of_price_versus_par(mkt):
    a1 = mkt.horizon_date(months=3)
    for coupon, expect_up in ((0.005, True), (0.06, False)):           # discount bond accretes up, premium bond pulls down
        b = make_bond(mkt, coupon=coupon)
        y0 = b.yield_from_dirty(mkt.anchor, b.price(mkt))
        pull = b.notional / 100 * b.dirty_from_yield(a1, y0) - b.accrued(a1) - b.pv(mkt)
        assert (pull > 0) == expect_up and (b.price(mkt) < 100) == expect_up


def test_breakeven_for_a_funded_bond_zeroes_the_pnl_after_funding(mkt):
    b = make_bond(mkt, asw=0.004, fs=-0.001)
    a1 = mkt.horizon_date(months=3)
    c = carry_roll(b, mkt, a1)
    static = mkt.rolled(a1, "static")
    after = b.pv(static.shifted(CurveShock.parallel(c.breakeven_bp))) - b.pv(mkt) - financing_cost(b, mkt, a1)
    assert after == pytest.approx(0, abs=1.0)
    assert c.breakeven_bp == pytest.approx(c.total_static / c.dv01, abs=0.15)


def test_attribution_includes_financing_for_bonds(mkt):
    b = make_bond(mkt, asw=0.004, fs=-0.001)
    a1 = mkt.horizon_date(months=1)
    att = attribute(b, mkt, a1, CurveShock.parallel(0))
    c = carry_roll(b, mkt, a1)
    assert att.total == pytest.approx(c.total_static) and att.carry == pytest.approx(c.carry)
    assert att.time + att.delta + att.residual == pytest.approx(att.total)
