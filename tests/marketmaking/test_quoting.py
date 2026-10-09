import pytest

from rates_trainer.engine.instruments import Side
from rates_trainer.engine.risk import parallel_dv01
from rates_trainer.marketmaking.quoting import (
    BP, ClientAction, Liquidity, Quote, QuotingContext, make_quote,
)

FV = 0.02845


def test_client_pays_hits_offer_and_dealer_receives_fixed_long_duration(mkt):
    q = Quote(0.02843, 0.02847)
    swap = q.dealer_swap(ClientAction.PAYS, 300e6, mkt, 10)
    assert swap.side is Side.RECEIVE
    assert swap.fixed_rate == 0.02847
    assert parallel_dv01(swap, mkt) > 0  # long duration


def test_client_receives_hits_bid_and_dealer_pays_fixed_short_duration(mkt):
    q = Quote(0.02843, 0.02847)
    swap = q.dealer_swap(ClientAction.RECEIVES, 300e6, mkt, 10)
    assert swap.side is Side.PAY and swap.fixed_rate == 0.02843
    assert parallel_dv01(swap, mkt) < 0


def test_quote_mid_width_and_crossed_rejected():
    q = Quote(0.02843, 0.02847)
    assert q.mid == pytest.approx(0.02845)
    assert q.width_bp == pytest.approx(0.4)
    with pytest.raises(ValueError):
        Quote(0.0285, 0.0284)


def test_client_always_gets_the_worse_side_of_mid():
    q = Quote(0.02843, 0.02847)
    assert q.client_rate(ClientAction.PAYS) > q.mid      # pays more than mid
    assert q.client_rate(ClientAction.RECEIVES) < q.mid  # receives less than mid


def test_flat_inventory_no_view_is_symmetric():
    b = make_quote(QuotingContext(FV))
    assert b.direction == "neutral" and b.encouraged_client_action is None
    assert b.quote.mid == pytest.approx(FV)
    assert b.quote.width_bp == pytest.approx(2 * 0.2)


def test_long_duration_inventory_quotes_higher_and_encourages_client_receiving():
    b = make_quote(QuotingContext(FV, inventory_dv01=300_000))
    assert b.direction == "higher"
    assert b.quote.bid > FV - 0.2 * BP and b.quote.offer > FV + 0.2 * BP  # both sides up
    assert b.encouraged_client_action is ClientAction.RECEIVES  # dealer pays fixed: reduces long


def test_short_duration_inventory_quotes_lower_and_encourages_client_paying():
    b = make_quote(QuotingContext(FV, inventory_dv01=-300_000))
    assert b.direction == "lower"
    assert b.encouraged_client_action is ClientAction.PAYS


def test_skew_is_antisymmetric_in_inventory():
    up = make_quote(QuotingContext(FV, inventory_dv01=250_000))
    dn = make_quote(QuotingContext(FV, inventory_dv01=-250_000))
    assert up.inventory_skew_bp == pytest.approx(-dn.inventory_skew_bp)


def test_skew_increases_with_inventory_and_convexly_near_limit():
    s = [make_quote(QuotingContext(FV, inventory_dv01=x)).inventory_skew_bp for x in (0, 100e3, 250e3, 400e3, 500e3)]
    assert s == sorted(s) and s[0] == 0
    assert (s[4] - s[3]) / 100e3 > (s[2] - s[1]) / 150e3  # steeper near the limit


def test_bearish_view_with_conviction_quotes_higher_and_no_conviction_does_nothing():
    assert make_quote(QuotingContext(FV, view_bp=5, conviction=0.8)).direction == "higher"
    assert make_quote(QuotingContext(FV, view_bp=5, conviction=0.0)).direction == "neutral"
    assert make_quote(QuotingContext(FV, view_bp=-5, conviction=0.8)).direction == "lower"


def test_view_and_inventory_can_offset():
    b = make_quote(QuotingContext(FV, inventory_dv01=400_000, view_bp=-3, conviction=1.0))
    assert abs(b.net_shift_bp) < abs(b.inventory_skew_bp)


def test_vol_liquidity_adverse_selection_widen_the_market():
    base = make_quote(QuotingContext(FV)).quote.width_bp
    assert make_quote(QuotingContext(FV, vol_multiplier=1.5)).quote.width_bp > base
    assert make_quote(QuotingContext(FV, liquidity=Liquidity.THIN)).quote.width_bp > base
    assert make_quote(QuotingContext(FV, liquidity=Liquidity.DEEP)).quote.width_bp < base
    assert make_quote(QuotingContext(FV, adverse_selection=0.5)).quote.width_bp > base


def test_near_limit_long_widens_only_the_risk_adding_offer_side():
    b = make_quote(QuotingContext(FV, inventory_dv01=480_000))
    assert b.offer_half_width_bp > b.bid_half_width_bp
    assert b.limit_widening_bp > 0
    far = make_quote(QuotingContext(FV, inventory_dv01=100_000))
    assert far.limit_widening_bp == 0 and far.offer_half_width_bp == far.bid_half_width_bp


def test_near_limit_short_widens_the_bid_side():
    b = make_quote(QuotingContext(FV, inventory_dv01=-480_000))
    assert b.bid_half_width_bp > b.offer_half_width_bp


def test_expected_flow_adding_to_long_increases_skew_up():
    a = make_quote(QuotingContext(FV, inventory_dv01=200_000))
    b = make_quote(QuotingContext(FV, inventory_dv01=200_000, expected_flow_dv01=200_000))
    c = make_quote(QuotingContext(FV, inventory_dv01=200_000, expected_flow_dv01=-200_000))
    assert b.net_shift_bp > a.net_shift_bp > c.net_shift_bp
    assert b.flow_skew_bp > 0 > c.flow_skew_bp


def test_never_crossed_for_extreme_contexts():
    for inv in (-900e3, 0, 900e3):
        b = make_quote(QuotingContext(FV, inventory_dv01=inv, vol_multiplier=2, adverse_selection=1,
                                      liquidity=Liquidity.THIN, view_bp=10, conviction=1))
        assert b.quote.offer > b.quote.bid
