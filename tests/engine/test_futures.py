"""Bond futures: conversion factors, basis analytics, CTD, the curve-consistent contract, hedging and the long-basis payoff.

Validation routes: closed forms and hand worked examples (conversion factors, a no-coupon and a coupon basis line), explicit cash-flow
simulation (implied repo), round trips (price a future from bond i, recover bond i's repo), identities (net basis = CF x (F_i - F)),
and the structural property that the future is SHORT the delivery option (fair F <= every F_i, equality at the CTD).
"""

from datetime import date

import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.futures import (
    BOBL, BUND, SCHATZ, BondFuture, basis_line, calibrated, clean_price, contracts_to_hedge, conversion_factor, ctd_line,
    delivery_date, delivery_scenario_prices, forward_clean, is_deliverable, long_basis_pnl_at_delivery, next_delivery, ranked,
    ranked_by_implied_repo, remaining_months, term_repo)
from rates_trainer.engine.instruments import FixedBond
from rates_trainer.engine.risk import parallel_dv01

from ..conftest import make_market

DELIVERY = date(2026, 12, 10)


# ------------------------------------------------------------------------------------------ dates

def test_remaining_months_rounds_down():
    assert remaining_months(date(2026, 3, 10), date(2035, 2, 15)) == 107          # 107 months + 5 days
    assert remaining_months(date(2026, 3, 10), date(2035, 2, 4)) == 106           # day-of-month 4 < 10: one month less
    assert remaining_months(date(2026, 3, 10), date(2035, 3, 10)) == 108
    assert remaining_months(date(2026, 12, 10), date(2036, 12, 10)) == 120


def test_delivery_date_is_the_tenth_following_and_next_delivery_respects_the_gap():
    assert delivery_date(2026, 12) == date(2026, 12, 10)
    assert delivery_date(2029, 3) == date(2029, 3, 12)                              # 10 Mar 2029 is a Saturday
    assert next_delivery(date(2026, 10, 12), 20) == date(2026, 12, 10)
    assert next_delivery(date(2026, 11, 25), 20) == date(2027, 3, 10)               # only 15 days to the December date
    with pytest.raises(ValueError):
        delivery_date(2026, 5)


def test_deliverable_window_is_inclusive_8p5_to_10p5_years():
    d = DELIVERY
    assert is_deliverable(date(2035, 6, 10), d, BUND) and is_deliverable(date(2037, 6, 10), d, BUND)
    assert not is_deliverable(date(2035, 6, 9), d, BUND) and not is_deliverable(date(2037, 6, 11), d, BUND)
    assert is_deliverable(date(2031, 6, 15), d, BOBL) and not is_deliverable(date(2036, 12, 15), d, BOBL)
    assert is_deliverable(date(2029, 3, 4), d, SCHATZ)


# ------------------------------------------------------------------------------------------ conversion factors

def test_conversion_factor_hand_worked_example():
    """2.5% bond maturing 15 Feb 2035, delivery 10 Mar 2026: 107 whole months remain, next coupon in 11 months, accrued 1/12 of a coupon.
    The cash flows are laid out explicitly here, not by the engine's formula."""
    y, c = 0.06, 0.025
    times = [11 / 12 + j for j in range(9)]                                   # 11, 23, ..., 107 months
    dirty = sum(c / (1 + y) ** t for t in times) + 1.0 / (1 + y) ** times[-1]
    by_hand = round(dirty - c * 1 / 12, 6)
    assert conversion_factor(0.025, date(2035, 2, 15), date(2026, 3, 10)) == by_hand
    # the trader's route: CF ~ 1 - (6% - coupon) x annuity at 6% over the remaining life (107/12 years)
    assert by_hand == pytest.approx(1 - (0.06 - c) * (1 - 1.06 ** (-107 / 12)) / 0.06, abs=3e-3)


def test_conversion_factor_equals_the_annuity_closed_form():
    """CF = (1+y)^(-k/12) [c + c (1 - v^n)/y + v^n] - c (12-k)/12, with n coupons after the next one."""
    y = 0.06
    for coupon in (0.0, 0.01, 0.025, 0.04, 0.06, 0.08):
        for maturity in (date(2035, 2, 15), date(2035, 8, 4), date(2036, 11, 15), date(2036, 12, 10), date(2031, 5, 15)):
            m = remaining_months(DELIVERY, maturity)
            k = m % 12 or 12
            n = (m - k) // 12
            v = 1 / (1 + y)
            closed = v ** (k / 12) * (coupon + coupon * (1 - v ** n) / y + v ** n) - coupon * (12 - k) / 12
            assert conversion_factor(coupon, maturity, DELIVERY) == pytest.approx(closed, abs=5e-7)


def test_conversion_factor_properties():
    assert conversion_factor(0.06, date(2036, 12, 10), DELIVERY) == pytest.approx(1.0, abs=1e-6)       # whole years, 6% coupon = par
    assert conversion_factor(0.0, date(2036, 5, 15), DELIVERY) < conversion_factor(0.025, date(2036, 5, 15), DELIVERY) < 1.0
    assert conversion_factor(0.08, date(2036, 5, 15), DELIVERY) > 1.0
    # for a sub-6% coupon a SHORTER bond is closer to par, so its CF is higher
    assert conversion_factor(0.025, date(2035, 8, 15), DELIVERY) > conversion_factor(0.025, date(2036, 8, 15), DELIVERY)
    # rounded to 6 decimal places
    cf = conversion_factor(0.0275, date(2035, 11, 4), DELIVERY)
    assert cf == round(cf, 6)
    with pytest.raises(ValueError):
        conversion_factor(0.02, date(2026, 3, 1), DELIVERY)


def test_cf_does_not_depend_on_where_the_market_is():
    """The conversion factor is a fixed number: this is exactly why it cannot equalise bonds when yields are not 6%."""
    a = conversion_factor(0.0225, date(2036, 5, 15), DELIVERY)
    assert a == conversion_factor(0.0225, date(2036, 5, 15), DELIVERY)


# ------------------------------------------------------------------------------------------ basis analytics (quoted prices)

def _bond(coupon, maturity, anchor=date(2026, 10, 12)):
    return FixedBond.from_maturity(100.0, coupon, maturity, anchor)


def test_from_maturity_builds_unadjusted_annual_periods_and_accrues_act_act():
    b = _bond(0.025, date(2035, 6, 15), date(2026, 10, 12))
    assert b.periods[0].start == date(2026, 6, 15) and b.periods[0].end == date(2027, 6, 15)
    assert len(b.periods) == 9 and b.maturity == date(2035, 6, 15)
    assert b.accrued(date(2026, 10, 12)) == pytest.approx(2.5 * 119 / 365, rel=1e-12)
    on_coupon = FixedBond.from_maturity(100.0, 0.025, date(2035, 6, 15), date(2026, 6, 15))
    assert on_coupon.periods[0].start == date(2026, 6, 15) and on_coupon.accrued(date(2026, 6, 15)) == 0.0


def test_basis_line_hand_worked_no_coupon():
    """Clean 98.00, coupon 2.5% (accrued 119 days today), repo 2%, 59 days to delivery, F = 127.50."""
    anchor = date(2026, 10, 12)
    b = _bond(0.025, date(2035, 6, 15), anchor)
    line = basis_line(b, 98.00, 0.02, anchor, DELIVERY, 127.50)
    a0, ad = 2.5 * 119 / 365, 2.5 * (119 + 59) / 365
    dirty = 98.00 + a0
    financing = dirty * 0.02 * 59 / 360
    assert line.days == 59 and line.coupon_paid == 0.0
    assert line.accrued0 == pytest.approx(a0, rel=1e-12) and line.accrued_delivery == pytest.approx(ad, rel=1e-12)
    assert line.financing == pytest.approx(financing, rel=1e-12)
    assert line.carry == pytest.approx((ad - a0) - financing, rel=1e-12)
    cf = conversion_factor(0.025, date(2035, 6, 15), DELIVERY)
    assert line.cf == cf
    assert line.gross_basis == pytest.approx(98.00 - 127.50 * cf, rel=1e-12)
    assert line.net_basis == pytest.approx(line.gross_basis - line.carry, rel=1e-12)
    assert line.implied_repo == pytest.approx(((127.50 * cf + ad) / dirty - 1) * 360 / 59, rel=1e-12)


def test_implied_repo_by_explicit_cash_flow_simulation_with_a_coupon_in_the_window():
    """Borrow the dirty price at the implied repo, receive the coupon (reinvested at that repo) and the invoice: it all nets to zero."""
    anchor = date(2026, 10, 12)
    b = _bond(0.0275, date(2035, 11, 4), anchor)                                # coupon paid 4 Nov 2026, inside the window
    line = basis_line(b, 99.30, 0.019, anchor, DELIVERY, 127.00)
    assert line.coupon_paid == pytest.approx(2.75) and line.coupon_days == (DELIVERY - date(2026, 11, 4)).days
    r = line.implied_repo
    owed = line.dirty * (1 + r * line.days / 360)                              # loan repaid at delivery
    coupon_value = 2.75 * (1 + r * line.coupon_days / 360)                     # coupon received and reinvested
    assert owed - coupon_value == pytest.approx(line.invoice, rel=1e-12)
    # a coupon inside the window shifts accrued back to ~0, and the reported carry includes the coupon
    assert line.accrued_delivery < line.accrued0
    assert line.carry == pytest.approx((line.accrued_delivery - line.accrued0)
                                       + 2.75 * (1 + 0.019 * line.coupon_days / 360) - line.financing, rel=1e-12)


@pytest.mark.parametrize("maturity,coupon", [(date(2035, 6, 15), 0.025), (date(2035, 11, 4), 0.0275), (date(2036, 2, 15), 0.01)])
def test_price_a_future_from_one_bond_and_recover_that_bonds_repo(maturity, coupon):
    """Round trip: if F is exactly F_i the bond's implied repo IS its repo and its net basis is zero."""
    anchor = date(2026, 10, 12)
    b = _bond(coupon, maturity, anchor)
    for repo in (0.0, 0.0185, 0.034, -0.002):
        probe = basis_line(b, 98.5, repo, anchor, DELIVERY, 100.0)
        f_i = probe.futures_equiv
        line = basis_line(b, 98.5, repo, anchor, DELIVERY, f_i)
        assert line.implied_repo == pytest.approx(repo, abs=1e-12)
        assert line.net_basis == pytest.approx(0.0, abs=1e-10)
        assert forward_clean(b, 98.5, repo, anchor, DELIVERY) == pytest.approx(f_i * line.cf, rel=1e-13)


def test_net_basis_identities_and_monotonicity_in_the_futures_price():
    anchor = date(2026, 10, 12)
    b = _bond(0.025, date(2035, 6, 15), anchor)
    lo = basis_line(b, 98.0, 0.02, anchor, DELIVERY, 126.0)
    hi = basis_line(b, 98.0, 0.02, anchor, DELIVERY, 127.0)
    for line in (lo, hi):
        assert line.net_basis == pytest.approx(line.cf * (line.futures_equiv - line.futures_price), rel=1e-12)
        assert line.net_basis == pytest.approx(line.gross_basis - line.carry, rel=1e-12)
        assert line.net_basis_in_futures_points * line.cf == pytest.approx(line.net_basis, rel=1e-12)
    # a RICHER future (higher F) means a higher implied repo and a LOWER net basis: the cash-and-carry gets more attractive
    assert hi.implied_repo > lo.implied_repo and hi.net_basis < lo.net_basis
    # one tick of F is worth CF x 0.01 of net basis and moves the implied repo by 0.01 x CF / dirty x 360/days
    assert lo.net_basis - hi.net_basis == pytest.approx(lo.cf * 1.0, rel=1e-12)
    assert hi.implied_repo - lo.implied_repo == pytest.approx(lo.cf * 360 / (lo.dirty * lo.days), rel=1e-12)


def test_carry_sign_is_coupon_income_versus_financing():
    anchor = date(2026, 10, 12)
    high = basis_line(_bond(0.04, date(2035, 6, 15), anchor), 98.0, 0.01, anchor, DELIVERY, 127.0)
    low = basis_line(_bond(0.0, date(2035, 6, 15), anchor), 98.0, 0.04, anchor, DELIVERY, 127.0)
    assert high.carry > 0 > low.carry
    assert low.carry == pytest.approx(-(98.0 * 0.04 * 59 / 360), rel=1e-12)           # zero coupon: pure financing cost
    # positive carry lowers the forward price; negative carry raises it
    assert high.forward_clean < 98.0 < low.forward_clean


def test_ctd_is_the_lowest_net_basis_and_with_one_repo_the_highest_implied_repo():
    anchor = date(2026, 10, 12)
    bonds = [_bond(c, m, anchor) for c, m in ((0.025, date(2035, 6, 15)), (0.01, date(2035, 8, 15)), (0.0275, date(2035, 11, 4)))]
    cleans = (97.9, 85.4, 100.1)
    lines = [basis_line(b, p, 0.019, anchor, DELIVERY, 127.2) for b, p in zip(bonds, cleans)]
    best = ctd_line(lines)
    assert best.net_basis == min(l.net_basis for l in lines) and best.futures_equiv == min(l.futures_equiv for l in lines)
    assert [l.net_basis for l in ranked(lines)] == sorted(l.net_basis for l in lines)
    # with ONE repo rate the two rankings are the same ranking
    assert [l.implied_repo for l in ranked(lines)] == sorted((l.implied_repo for l in lines), reverse=True)
    assert ranked_by_implied_repo(lines)[0] is best


# ------------------------------------------------------------------------------------------ the curve-consistent contract

@pytest.fixture(scope="module")
def case():
    m = make_market()
    anchor = m.anchor
    dl = next_delivery(anchor, 40)
    spec = [
        (0.0250, date(2035, 6, 15), 0.0004), (0.0100, date(2035, 8, 15), 0.0010), (0.0275, date(2035, 11, 4), -0.0002),
        (0.0300, date(2036, 2, 15), 0.0006), (0.0225, date(2036, 5, 15), 0.0008),
    ]
    basket = [FixedBond.from_maturity(100.0, c, mt, anchor, asw=a) for c, mt, a in spec]
    f0 = calibrated(BUND, dl, basket, m, 0.0).fair_price(m)
    return m, calibrated(BUND, dl, basket, m, round(f0 - 0.10, 2))


def test_calibration_reproduces_the_traded_price_and_pv_is_contracts_times_point_value(case):
    m, fut = case
    assert fut.price(m) == pytest.approx(fut.fair_price(m) - fut.price_offset, abs=1e-12)
    assert fut.pv(m) == pytest.approx(fut.price(m) * 1000.0, rel=1e-13)
    assert fut.with_contracts(-25).pv(m) == pytest.approx(-25 * fut.pv(m), rel=1e-13)
    assert BUND.tick_value == 10.0 and BUND.point_value == 1000.0


def test_the_ctd_sets_the_price_and_has_the_highest_implied_repo(case):
    m, fut = case
    f_i = fut.futures_equivalents(m)
    i = fut.ctd_index(m)
    assert f_i[i] == min(f_i) == fut.fair_price(m)
    lines = fut.lines(m)
    assert lines[i] is ctd_line(lines) or lines[i].implied_repo == max(l.implied_repo for l in lines)
    # with price_offset > 0 the CTD's net basis is CF x offset and its implied repo sits BELOW its repo
    assert lines[i].net_basis == pytest.approx(lines[i].cf * fut.price_offset, rel=1e-9)
    assert lines[i].implied_repo < lines[i].repo
    # at the fair price (no option premium) the CTD's implied repo equals its repo
    at_fair = fut.lines(m, futures_price=fut.fair_price(m))[i]
    assert at_fair.implied_repo == pytest.approx(at_fair.repo, abs=1e-12) and at_fair.net_basis == pytest.approx(0, abs=1e-10)


def test_lines_use_curve_prices_and_repo_from_ois_plus_funding_spread(case):
    m, fut = case
    b = fut.basket[0]
    assert term_repo(b, m, fut.delivery) == pytest.approx(
        (m.ois.df(m.anchor) / m.ois.df(fut.delivery) - 1) * 360 / (fut.delivery - m.anchor).days, rel=1e-12)      # funding_spread = 0
    special = FixedBond.from_maturity(100.0, 0.025, date(2035, 6, 15), m.anchor, funding_spread=-0.003)
    assert term_repo(special, m, fut.delivery) == pytest.approx(term_repo(b, m, fut.delivery) - 0.003, abs=1e-14)


def test_forwards_realised_reproduces_the_repo_forward_price_when_no_coupon_is_paid(case):
    """Independent check of the financing arithmetic: the bond's price on the forward curve at delivery IS the repo-implied forward
    (spread 0, no coupon in the window). With a coupon the constant-ASW price model drifts by ~ASW x 1y: shocks are applied as changes."""
    m, fut = case
    fwd_market = m.rolled(fut.delivery, "forward")
    for b in fut.basket:
        if any(m.anchor < p.pay <= fut.delivery for p in b.periods):
            continue
        assert clean_price(b, fwd_market) == pytest.approx(
            forward_clean(b, clean_price(b, m), term_repo(b, m, fut.delivery), m.anchor, fut.delivery), abs=2e-6)


def test_futures_dv01_is_positive_for_a_long_and_close_to_the_ctd_dv01_over_cf(case):
    m, fut = case
    dv01 = parallel_dv01(fut, m)
    assert dv01 > 0 and parallel_dv01(fut.with_contracts(-10), m) == pytest.approx(-10 * dv01, rel=1e-9)
    i = fut.ctd_index(m)
    b = fut.basket[i]
    cf = fut.conversion_factors()[i]
    dirty = clean_price(b, m) + b.accrued(m.anchor)
    d_mod = b.modified_duration(m.anchor, b.yield_from_dirty(m.anchor, dirty))
    mental = dirty * d_mod * 1e-4 / cf * 1000.0
    assert dv01 == pytest.approx(mental, rel=0.04)
    assert 70 < dv01 < 130                                                       # a Bund contract is ~EUR 90-100 per bp


def test_cf_weighted_hedge_neutralises_a_ctd_position(case):
    m, fut = case
    i = fut.ctd_index(m)
    b = fut.basket[i]
    cf = fut.conversion_factors()[i]
    face = 50e6
    position = FixedBond.from_maturity(face, b.coupon, b.maturity, m.anchor, asw=b.asw)
    n = contracts_to_hedge(face, cf, BUND)
    assert n == pytest.approx(-face * cf / 100_000)
    hedge = fut.with_contracts(n)
    bond_dv01 = parallel_dv01(position, m)
    assert bond_dv01 > 0 > parallel_dv01(hedge, m)
    assert parallel_dv01(hedge, m) + bond_dv01 == pytest.approx(0, abs=0.03 * bond_dv01)
    # the naive "face / 100k contracts" over-hedges by 1/CF - 1
    naive = parallel_dv01(fut.with_contracts(-face / 100_000), m)
    assert -naive / bond_dv01 == pytest.approx(1 / cf, rel=0.04)


def test_the_future_is_short_the_delivery_option(case):
    """F = min_i F_i <= F_ctd(y) at every curve level, with equality at today's. So the future has LESS convexity than the CTD."""
    m, fut = case
    i0 = fut.ctd_index(m)
    assert fut.futures_equivalents(m)[i0] == pytest.approx(fut.fair_price(m), abs=1e-12)
    for bp in (-150, -80, -30, 30, 80, 150, 250):
        mm = m.shifted(CurveShock.parallel(bp))
        f = fut.futures_equivalents(mm)
        assert fut.fair_price(mm) <= f[i0] + 1e-12
    # With yields far BELOW the 6% notional coupon the shortest-duration bond is cheapest; a big enough selloff (towards 6%) hands the
    # crown to a longer-duration bond, and a rally never does.
    shifted = {bp: fut.ctd_index(m.shifted(CurveShock.parallel(bp))) for bp in (-300, -150, 0, 100, 200, 400)}
    assert shifted[-300] == shifted[-150] == shifted[0] == shifted[100] == 0
    assert shifted[200] != 0 and shifted[400] != 0
    longer = lambda k: fut.basket[k].maturity
    assert longer(shifted[400]) > longer(shifted[0])
    assert fut.price(m) - fut.price(m.shifted(CurveShock.parallel(-100))) <= 0       # price rises when rates fall


def test_futures_p_and_l_matches_price_difference_both_paths(case):
    m, fut = case
    from rates_trainer.engine.pnl import first_order_pnl, revalue_pnl
    pos = fut.with_contracts(100)
    dv01 = parallel_dv01(pos, m)
    full = revalue_pnl(pos, m, CurveShock.parallel(+10))
    assert full < 0 and first_order_pnl(dv01, +10) == pytest.approx(full, rel=0.03)
    assert full == pytest.approx(100 * 1000 * (fut.price(m.shifted(CurveShock.parallel(10))) - fut.price(m)), rel=1e-12)


# ------------------------------------------------------------------------------------------ the long-basis payoff

def test_long_basis_pnl_is_option_payoff_minus_net_basis(case):
    """Buy the CTD, repo it, short CF futures, deliver:  P&L = -net basis + CF x (F_i' - min_j F_j')  >= -net basis."""
    m, fut = case
    lines = fut.lines(m)
    i = fut.ctd_index(m)
    cf = fut.conversion_factors()[i]
    for bp in (-120, -50, -10, 0, 10, 50, 120, 300):
        shock = CurveShock.parallel(bp)
        prices, f_final = delivery_scenario_prices(fut, m, shock)
        by_formula = -lines[i].net_basis + cf * (prices[i] / cf - f_final)
        assert long_basis_pnl_at_delivery(fut, m, i, shock) == pytest.approx(by_formula, abs=1e-10)
        assert long_basis_pnl_at_delivery(fut, m, i, shock) >= -lines[i].net_basis - 1e-10
    # nothing happens (forwards realised): the whole net basis is lost
    assert long_basis_pnl_at_delivery(fut, m, i, CurveShock.parallel(0)) == pytest.approx(-lines[i].net_basis, abs=1e-10)
    # a big move gains: the option is worth more than its premium for a large enough selloff or rally
    assert max(long_basis_pnl_at_delivery(fut, m, i, CurveShock.parallel(bp)) for bp in (-250, 250, 400)) > 0


def test_long_basis_in_a_non_ctd_bond_keeps_its_out_of_the_money_value(case):
    """A bond that is not the CTD has a net basis made of the option premium PLUS how far it is out of the money. If nothing happens
    the future converges to the CTD, so the holder loses only CF x price_offset: the out-of-the-money part is not lost, it stays option value."""
    m, fut = case
    lines = fut.lines(m)
    i = fut.ctd_index(m)
    j = max(range(len(lines)), key=lambda k: lines[k].net_basis)
    assert j != i and lines[j].net_basis > lines[i].net_basis
    cf_j = lines[j].cf
    pnl0 = long_basis_pnl_at_delivery(fut, m, j, CurveShock.parallel(0))
    assert pnl0 == pytest.approx(-cf_j * fut.price_offset, abs=1e-10)
    assert pnl0 > -lines[j].net_basis
    # the general identity, for any bond and any move
    for bp in (-100, 0, 60, 200):
        prices, f_final = delivery_scenario_prices(fut, m, CurveShock.parallel(bp))
        assert long_basis_pnl_at_delivery(fut, m, j, CurveShock.parallel(bp)) == pytest.approx(
            -lines[j].net_basis + cf_j * (prices[j] / cf_j - f_final), abs=1e-10)


def test_empty_or_non_deliverable_baskets_are_rejected(case):
    m, fut = case
    with pytest.raises(ValueError):
        BondFuture(BUND, fut.delivery, ())
    with pytest.raises(ValueError):
        BondFuture(BUND, fut.delivery, (FixedBond.from_maturity(100.0, 0.02, date(2030, 1, 15), m.anchor),))


def test_a_special_bond_can_be_the_ctd_without_the_highest_implied_repo():
    """The short delivers the bond with the lowest net basis, financing each at its own repo. Specialness cuts a bond's financing cost,
    so it lowers its net basis one-for-one (about dirty x spread x days/360), whatever that does to the ranking by implied repo."""
    anchor = date(2026, 10, 12)
    a, b = _bond(0.025, date(2035, 6, 15), anchor), _bond(0.0275, date(2035, 11, 4), anchor)
    base = [basis_line(a, 97.9, 0.019, anchor, DELIVERY, 127.0), basis_line(b, 99.2, 0.019, anchor, DELIVERY, 127.0)]
    special = basis_line(b, 99.2, 0.019 - 0.004, anchor, DELIVERY, 127.0)
    # (a coupon paid inside the window is reinvested at the repo too, so its interest falls by the same spread)
    saving = (special.dirty * special.days - special.coupon_paid * special.coupon_days) * 0.004 / 360
    assert base[1].net_basis - special.net_basis == pytest.approx(saving, rel=1e-12)
    flipped = [base[0], special]
    assert ctd_line(base) is not ctd_line(flipped) or base[1].net_basis > base[0].net_basis


# ------------------------------------------------------------------------------------------ claims made by the curated questions

def _duration_at(bond, m):
    dirty = clean_price(bond, m) + bond.accrued(m.anchor)
    return bond.modified_duration(m.anchor, bond.yield_from_dirty(m.anchor, dirty))


def test_ctd_is_the_shortest_duration_bond_below_6_percent_and_a_longer_one_above(case):
    m, fut = case
    durations = [_duration_at(b, m) for b in fut.basket]
    assert durations[fut.ctd_index(m)] == min(durations)                          # yields ~2.5%: lowest duration is cheapest
    high = m.shifted(CurveShock.parallel(500))                                    # yields ~7.5%: above the 6% notional coupon
    d_high = [_duration_at(b, high) for b in fut.basket]
    # a TENDENCY, not a theorem (coupon and carry also count): the new CTD is among the two longest-duration bonds and clearly longer than before
    assert d_high[fut.ctd_index(high)] >= sorted(d_high)[-2]
    assert d_high[fut.ctd_index(high)] > d_high[fut.ctd_index(m)]


def test_a_higher_repo_raises_the_fair_futures_price(case):
    m, fut = case
    from dataclasses import replace
    pricier = BondFuture(fut.spec, fut.delivery, tuple(replace(b, funding_spread=b.funding_spread + 0.0025) for b in fut.basket), fut.price_offset)
    assert pricier.fair_price(m) > fut.fair_price(m)
    b = fut.basket[fut.ctd_index(m)]
    cf = fut.conversion_factors()[fut.ctd_index(m)]
    days = (fut.delivery - m.anchor).days
    dirty = clean_price(b, m) + b.accrued(m.anchor)
    # the CTD's forward price (and so F x CF) rises by about dirty x 25bp x days/360 (a coupon paid in the window trims it a little)
    assert (pricier.fair_price(m) - fut.fair_price(m)) * cf == pytest.approx(dirty * 0.0025 * days / 360, rel=0.05)


def test_gross_basis_of_the_ctd_converges_to_zero_and_of_the_others_to_a_positive_number(case):
    m, fut = case
    for bp in (-60, 0, 60):
        prices, f_final = delivery_scenario_prices(fut, m, CurveShock.parallel(bp))
        gross = [p - f_final * cf for p, cf in zip(prices, fut.conversion_factors())]
        assert min(gross) == pytest.approx(0, abs=1e-12) and all(g >= -1e-12 for g in gross)
        assert sum(g > 1e-6 for g in gross) == len(gross) - 1


def test_specialness_saves_dirty_price_times_spread_times_days_over_360_in_net_basis():
    anchor = date(2026, 10, 12)
    b = _bond(0.025, date(2035, 6, 15), anchor)                                   # no coupon in the window
    plain = basis_line(b, 98.0, 0.02, anchor, DELIVERY, 127.0)
    special = basis_line(b, 98.0, 0.02 - 0.003, anchor, DELIVERY, 127.0)
    assert plain.net_basis - special.net_basis == pytest.approx(plain.dirty * 0.003 * 59 / 360, rel=1e-12)


def test_implied_repo_above_repo_means_a_riskless_cash_and_carry_profit():
    """Buy the CTD at its dirty price, repo it at r, sell the future at F: the profit by delivery is invoice - dirty x (1 + r d/360)."""
    anchor = date(2026, 10, 12)
    b = _bond(0.025, date(2035, 6, 15), anchor)
    rich = basis_line(b, 98.0, 0.0230, anchor, DELIVERY, 127.60)
    assert rich.implied_repo > rich.repo and rich.net_basis < 0
    profit = rich.invoice - rich.dirty * (1 + rich.repo * rich.days / 360)
    assert profit == pytest.approx(-rich.net_basis, rel=1e-9) and profit > 0
    assert profit == pytest.approx(rich.dirty * (rich.implied_repo - rich.repo) * rich.days / 360, rel=1e-9)
