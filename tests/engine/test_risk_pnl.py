import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.instruments import FixedBond, IRSwap, Side
from rates_trainer.engine.pnl import (
    first_order_pnl, key_rate_first_order_pnl, pnl_report, revalue_pnl,
)
from rates_trainer.engine.risk import (
    Portfolio, by_tenor, dv01_hedge_swap, key_rate_dv01, par_basis, par_fra, par_irs, par_ois,
    parallel_dv01, solve_key_rate_hedge, unit_dv01,
)

BP = 1e-4


def test_receiver_dv01_positive_payer_negative(mkt):
    r = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    p = par_irs(Side.PAY, 100e6, 10, mkt)
    assert parallel_dv01(r, mkt) > 0
    assert parallel_dv01(p, mkt) == pytest.approx(-parallel_dv01(r, mkt))


@pytest.mark.parametrize("years", [1, 2, 5, 10, 30])
def test_par_irs_dv01_equals_notional_times_annuity_times_1bp(mkt, years):
    """Closed form: for a par swap dPV/dS = -N*A, so DV01 = N * A * 1bp (A = 30E/360 fixed-leg annuity on OIS)."""
    s = par_irs(Side.RECEIVE, 100e6, years, mkt)
    assert parallel_dv01(s, mkt) == pytest.approx(100e6 * s.annuity(mkt) * BP, rel=1e-6)


@pytest.mark.parametrize("years", [1, 5, 10, 30])
def test_par_ois_dv01_equals_notional_times_annuity_times_1bp(mkt, years):
    s = par_ois(Side.RECEIVE, 100e6, years, mkt)
    assert parallel_dv01(s, mkt) == pytest.approx(100e6 * s.annuity(mkt) * BP, rel=1e-6)


def test_headline_example_magnitude(mkt):
    """EUR 250m 10Y receiver is roughly EUR 200-230k/bp: the number to have in your head."""
    assert 200_000 < parallel_dv01(par_irs(Side.RECEIVE, 250e6, 10, mkt), mkt) < 230_000


def test_par_irs_risk_sits_in_its_own_key_only(mkt):
    kr = key_rate_dv01(par_irs(Side.RECEIVE, 100e6, 10, mkt), mkt)
    assert kr[("E6M", 120)] == pytest.approx(sum(kr.values()), rel=1e-6)
    assert all(abs(v) < 1e-3 for k, v in kr.items() if k != ("E6M", 120))   # incl. every OIS key: Euribor refits


def test_par_ois_risk_sits_in_its_own_key_only(mkt):
    kr = key_rate_dv01(par_ois(Side.RECEIVE, 100e6, 5, mkt), mkt)
    assert kr[("OIS", 60)] == pytest.approx(sum(kr.values()), rel=1e-6)
    assert all(abs(v) < 1e-3 for k, v in kr.items() if k != ("OIS", 60))


def test_off_pillar_and_off_market_risk_spreads_across_keys_and_curves(mkt):
    kr = key_rate_dv01(par_irs(Side.RECEIVE, 100e6, 8, mkt), mkt)           # 8Y is not a pillar
    assert kr[("E6M", 84)] > 0 and kr[("E6M", 120)] > 0
    assert abs(kr[("E6M", 24)]) < 1e-3 * kr[("E6M", 84)]
    off_market = key_rate_dv01(IRSwap.new(Side.RECEIVE, 100e6, 0.045, mkt.spot, 120), mkt)   # deep in the money
    assert abs(off_market[("OIS", 120)]) > 1.0                              # discounting risk appears in OIS keys


def test_key_rates_sum_to_parallel(mkt):
    s = par_irs(Side.RECEIVE, 100e6, 12, mkt)
    assert sum(by_tenor(key_rate_dv01(s, mkt)).values()) == pytest.approx(parallel_dv01(s, mkt), rel=2e-3)


def test_irs_vs_ois_package_is_a_spread_position(mkt):
    """Receive 10Y IRS / pay 10Y OIS, DV01-neutral: flat to a parallel move, exposed to IRS-OIS spread."""
    irs = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    ois = dv01_hedge_swap(parallel_dv01(irs, mkt), 10, mkt, kind="OIS")
    book = Portfolio([irs, ois])
    assert ois.side is Side.PAY
    assert parallel_dv01(book, mkt) == pytest.approx(0, abs=1e-6 * parallel_dv01(irs, mkt))
    assert revalue_pnl(book, mkt, CurveShock.parallel(10)) == pytest.approx(0, abs=0.01 * 10 * parallel_dv01(irs, mkt))
    # IRS rates up 3bp with OIS unchanged (spread widens): the IRS receiver loses
    widen = revalue_pnl(book, mkt, CurveShock.parallel(3), curves=("E6M",))
    assert widen == pytest.approx(-3 * parallel_dv01(irs, mkt), rel=0.01) and widen < 0


def test_basis_swap_risk(mkt):
    long_basis = par_basis(Side.PAY, 100e6, 10, mkt)
    kr = key_rate_dv01(long_basis, mkt)
    assert kr[("BASIS_3S6S", 120)] < 0                  # P&L for a 1bp FALL in the spread is negative for a payer
    assert kr[("BASIS_3S6S", 120)] == pytest.approx(
        -100e6 * BP * sum((p.end - p.start).days / 360 * mkt.ois.df(p.pay) for p in long_basis.periods_3m), rel=1e-3)
    # it is nearly flat to outright rates compared with its spread risk
    assert abs(parallel_dv01(long_basis, mkt)) < 0.15 * abs(kr[("BASIS_3S6S", 120)])


def test_fra_dv01_sign_and_size(mkt):
    fra = par_fra(Side.RECEIVE, 100e6, 6, 12, mkt)       # receive fixed on 6x12: long duration, short-dated
    d = parallel_dv01(fra, mkt)
    assert d > 0
    assert d == pytest.approx(100e6 * 0.5 * BP * mkt.ois.df(fra.period.end), rel=0.03)   # N x tau x DF x 1bp


def test_bond_dv01_close_to_yield_based(mkt):
    b = FixedBond.new(100e6, 0.03, mkt.spot, 10)
    assert parallel_dv01(b, mkt) == pytest.approx(100e6 * BP * 8.5, rel=0.1)


# ---------- hedging ----------

def test_single_instrument_hedge_neutralises_parallel_dv01(mkt):
    trade = par_irs(Side.RECEIVE, 300e6, 10, mkt)
    hedge = dv01_hedge_swap(parallel_dv01(trade, mkt), 5, mkt)
    assert hedge.side is Side.PAY
    assert parallel_dv01(Portfolio([trade, hedge]), mkt) == pytest.approx(0, abs=1)
    assert hedge.notional > trade.notional
    assert hedge.notional / trade.notional == pytest.approx(unit_dv01(10, mkt) / unit_dv01(5, mkt), rel=1e-6)


def test_single_hedge_leaves_curve_residual(mkt):
    """10Y receiver hedged with 5Y payer: flat vs parallel, but wins on a 5s10s flattening."""
    trade = par_irs(Side.RECEIVE, 300e6, 10, mkt)
    book = Portfolio([trade, dv01_hedge_swap(parallel_dv01(trade, mkt), 5, mkt)])
    d = parallel_dv01(trade, mkt)
    assert revalue_pnl(book, mkt, CurveShock.parallel(10)) == pytest.approx(0, abs=0.01 * 10 * d)
    flattener = CurveShock.points({5: 0, 10: -3})        # the 10Y rallies against the 5Y: the 10Y receiver wins
    assert revalue_pnl(book, mkt, flattener) == pytest.approx(3 * d, rel=0.01)


def test_multi_instrument_hedge_zeroes_those_keys(mkt):
    book = Portfolio([par_irs(Side.RECEIVE, 100e6, 8, mkt), par_irs(Side.PAY, 40e6, 3, mkt)])
    target = key_rate_dv01(book, mkt)
    hedges = solve_key_rate_hedge(target, [("IRS", 3), ("IRS", 7), ("IRS", 10)], mkt)
    residual = key_rate_dv01(book.plus(*hedges), mkt)
    for key in (("E6M", 36), ("E6M", 84), ("E6M", 120)):
        assert residual[key] == pytest.approx(0, abs=1e-3)


# ---------- first-order vs full revaluation ----------

def test_first_order_matches_revaluation_for_small_moves(mkt):
    s = par_irs(Side.RECEIVE, 250e6, 10, mkt)
    d = parallel_dv01(s, mkt)
    for move in (-4, -1, 1, 4):
        assert first_order_pnl(d, move) == -d * move
        assert revalue_pnl(s, mkt, CurveShock.parallel(move)) == pytest.approx(first_order_pnl(d, move), rel=5e-3)


def test_first_order_error_is_convexity_scales_with_move_squared_and_has_the_right_sign(mkt):
    s = par_irs(Side.RECEIVE, 250e6, 30, mkt)
    d = parallel_dv01(s, mkt)
    err = {m: revalue_pnl(s, mkt, CurveShock.parallel(m)) - first_order_pnl(d, m) for m in (-100, -50, 50, 100)}
    assert all(e > 0 for e in err.values())                       # long duration => long convexity => always positive
    assert err[100] / err[50] == pytest.approx(4.0, rel=0.1)      # second-order: doubles the move, x4 the error
    assert err[-100] / err[-50] == pytest.approx(4.0, rel=0.1)
    payer = par_irs(Side.PAY, 250e6, 30, mkt)                      # short duration => short convexity
    assert revalue_pnl(payer, mkt, CurveShock.parallel(100)) - first_order_pnl(-d, 100) == pytest.approx(-err[100], rel=1e-6)


def test_report_gives_both_paths_and_they_reconcile(mkt):
    steep = Portfolio([par_irs(Side.RECEIVE, 100e6, 2, mkt), par_irs(Side.PAY, 20e6, 10, mkt)])
    shock = CurveShock.points({2: -5, 10: 3})
    rep = pnl_report(steep, mkt, shock)
    assert rep.delta + rep.second_order == pytest.approx(rep.full)
    assert rep.delta == pytest.approx(sum(rep.delta_by_key.values()))
    assert rep.delta == pytest.approx(key_rate_first_order_pnl(key_rate_dv01(steep, mkt), shock))
    assert rep.full == pytest.approx(rep.delta, rel=0.02)
    assert {k[0] for k in rep.delta_by_key} == {"OIS", "E6M"}
