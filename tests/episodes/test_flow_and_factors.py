"""The two stylised models under the episodes: client fills and named market factors."""

import math

import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.instruments import Side
from rates_trainer.engine.risk import par_irs, parallel_dv01
from rates_trainer.episodes.factors import FACTORS, FactorRisk, first_order_pnl, shock, step_vol, variance
from rates_trainer.marketmaking.flow import CLIENT_TYPES, fill_probability, improvement_bp, street_quote
from rates_trainer.marketmaking.quoting import BP, ClientAction, Liquidity, Quote


# ------------------------------------------------------------------------------------------ flow

def test_fill_probability_at_the_street_and_its_monotonicity():
    for ct in CLIENT_TYPES.values():
        assert fill_probability(ct, 0.0) == pytest.approx(ct.p_at_street)
        ps = [fill_probability(ct, x) for x in (-1.0, -0.3, 0.0, 0.3, 1.0)]
        assert all(a < b for a, b in zip(ps, ps[1:]))
        assert 0 < ps[0] and ps[-1] < 1


def test_informed_types_are_less_price_sensitive_than_real_money():
    fund, pension = CLIENT_TYPES["fast_money"], CLIENT_TYPES["pension"]
    assert fund.p_informed > 0.4 > CLIENT_TYPES["corporate"].p_informed
    # a 0.3bp worse price costs far less fill probability with a client that needs to trade
    assert fill_probability(fund, 0.0) - fill_probability(fund, -0.3) < fill_probability(pension, 0.0) - fill_probability(pension, -0.3)


def test_improvement_sign_convention_matches_the_quote_convention():
    street = Quote(0.02843, 0.02847)
    higher = Quote(0.02844, 0.02848)              # skewed up 0.1bp: a better BID for receivers, a worse OFFER for payers
    assert improvement_bp(ClientAction.RECEIVES, higher, street) == pytest.approx(+0.1)
    assert improvement_bp(ClientAction.PAYS, higher, street) == pytest.approx(-0.1)
    pension = CLIENT_TYPES["pension"]
    assert fill_probability(pension, improvement_bp(ClientAction.RECEIVES, higher, street)) > pension.p_at_street
    assert fill_probability(pension, improvement_bp(ClientAction.PAYS, higher, street)) < pension.p_at_street


def test_street_is_symmetric_and_widens_with_vol_liquidity_and_informed_flow():
    base = street_quote(0.03, 0.2, 1.0, Liquidity.NORMAL, 0.0)
    assert base.mid == pytest.approx(0.03) and base.width_bp == pytest.approx(0.4)
    for wider in (street_quote(0.03, 0.2, 1.8, Liquidity.NORMAL, 0.0), street_quote(0.03, 0.2, 1.0, Liquidity.THIN, 0.0),
                  street_quote(0.03, 0.2, 1.0, Liquidity.NORMAL, 0.4)):
        assert wider.width_bp > base.width_bp and wider.mid == pytest.approx(0.03)


# ------------------------------------------------------------------------------------------ factors

def test_factor_loadings_and_the_curve_move_they_imply():
    level = shock({"level": 3.0})
    assert all(level.bp_at(t) == pytest.approx(3.0) for t in (0.5, 2, 10, 30))
    slope = shock({"slope": 2.0})
    assert slope.bp_at(10) == pytest.approx(0.0) and slope.bp_at(2) == pytest.approx(-2.0) and slope.bp_at(30) == pytest.approx(2.0)
    both = shock({"level": 1.0, "slope": 1.0, "curvature": 1.0})
    assert both.bp_at(5) == pytest.approx(1.0 + FACTORS["slope"].loading(5) + 1.0)


def test_level_exposure_is_the_engines_parallel_dv01_and_a_10y_swap_has_no_slope_risk(mkt):
    risk = FactorRisk(mkt)
    swap = par_irs(Side.RECEIVE, 100e6, 10, mkt)
    x = risk.exposures(swap)
    assert x["level"] == pytest.approx(parallel_dv01(swap, mkt), rel=1e-9)
    assert abs(x["slope"]) < 0.01 * x["level"]                         # the slope factor pivots on the 10Y
    two = risk.exposures(par_irs(Side.RECEIVE, 100e6, 2, mkt))
    # a steepening lowers the 2Y rate, so a 2Y receiver GAINS: its slope exposure (P&L per bp FALL of the factor) is minus its level exposure
    assert two["slope"] == pytest.approx(-two["level"], rel=0.02)
    # first-order factor P&L matches full revaluation for a small move (the convexity/cross term is second order)
    moves = {"level": 2.0, "slope": -1.0, "curvature": 0.5}
    full = swap.pv(mkt.shifted(shock(moves))) - swap.pv(mkt)
    assert sum(first_order_pnl(x, moves).values()) == pytest.approx(full, rel=0.01)


def test_variance_is_the_sum_of_factor_variances_scaled_by_vol_and_time():
    x = {"level": 100_000.0, "slope": -50_000.0, "curvature": 0.0}
    v = variance(x, vol=1.0, dt=0.25)
    assert v == pytest.approx((100_000 * 5 * 0.5) ** 2 + (50_000 * 2 * 0.5) ** 2)
    assert variance(x, vol=1.8, dt=0.25) == pytest.approx(1.8 ** 2 * v)
    assert step_vol("level", 1.0, 1.0) == 5.0 and step_vol("level", 1.0, 0.25) == pytest.approx(2.5)
