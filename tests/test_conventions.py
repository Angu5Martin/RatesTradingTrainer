"""Worked examples that pin down the sign conventions end to end.

Each test is one chain of reasoning from docs/DESIGN.md's convention table, checked numerically:
    client action -> trade rate -> dealer side -> dealer duration/DV01 -> P&L direction
    -> skew direction -> which client trade the quote encourages -> what that trade does to inventory.
All use the conftest market, whose 10Y IRS mid is 2.845%.
"""

import dataclasses

import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.instruments import IRSwap, Side
from rates_trainer.engine.pnl import first_order_pnl
from rates_trainer.engine.risk import Portfolio, parallel_dv01
from rates_trainer.marketmaking.quoting import ClientAction, Quote, QuotingContext, make_quote

MARKET = Quote(0.02843, 0.02847)   # 10Y: mid 2.845, 0.4bp wide


def total_pnl(swap, mkt, move_bp):
    """P&L since execution (cash flows at inception are zero): PV after the move."""
    return swap.pv(mkt.shifted(CurveShock.parallel(move_bp)))


def test_the_fixture_mid_is_the_quote_mid(mkt):
    assert mkt.par_irs_rate(120) == pytest.approx(MARKET.mid, abs=1e-12)


# 1. client PAYS -> offer -> dealer RECEIVES fixed -> long duration
def test_example_client_pays_300m(mkt):
    s = MARKET.dealer_swap(ClientAction.PAYS, 300e6, mkt, 10)
    dv01 = parallel_dv01(s, mkt)
    assert s.fixed_rate == 0.02847 and s.side is Side.RECEIVE
    assert 240e3 < dv01 < 270e3                                        # long duration, ~ €250k/bp
    assert s.pv(mkt) == pytest.approx(0.2 * dv01, rel=1e-3)            # edge: half-spread x DV01
    assert total_pnl(s, mkt, -2) > total_pnl(s, mkt, +2)               # profits when rates FALL
    # first-order: edge - DV01 x move
    for move in (-2, +2):
        assert total_pnl(s, mkt, move) == pytest.approx(0.2 * dv01 + first_order_pnl(dv01, move), rel=0.01)
    assert total_pnl(s, mkt, +0.2) == pytest.approx(0, abs=0.01 * dv01)   # 0.2bp of edge absorbs a 0.2bp adverse move


# 2. client RECEIVES -> bid -> dealer PAYS fixed -> short duration
def test_example_client_receives_300m(mkt):
    s = MARKET.dealer_swap(ClientAction.RECEIVES, 300e6, mkt, 10)
    dv01 = parallel_dv01(s, mkt)
    assert s.fixed_rate == 0.02843 and s.side is Side.PAY
    assert dv01 < 0                                                    # short duration
    assert s.pv(mkt) == pytest.approx(0.2 * abs(dv01), rel=1e-3)
    assert total_pnl(s, mkt, +2) > total_pnl(s, mkt, -2)               # profits when rates RISE


# 3. the client always deals on the worse side of mid; the dealer earns the whole width on a round trip
def test_example_round_trip_earns_full_width_and_is_flat(mkt):
    pays = MARKET.dealer_swap(ClientAction.PAYS, 300e6, mkt, 10)
    recv = MARKET.dealer_swap(ClientAction.RECEIVES, 300e6, mkt, 10)
    book = Portfolio([pays, recv])
    assert parallel_dv01(book, mkt) == pytest.approx(0, abs=1e-3 * abs(parallel_dv01(pays, mkt)))
    assert book.pv(mkt) == pytest.approx(MARKET.width_bp * parallel_dv01(pays, mkt), rel=1e-3)
    assert MARKET.client_rate(ClientAction.PAYS) > MARKET.mid > MARKET.client_rate(ClientAction.RECEIVES)


# 4. long duration dealer: quote UP in rate; encouraged trade is client RECEIVING, which cuts the long
def test_example_long_inventory_skews_up_and_encourages_client_receiving(mkt):
    ctx = QuotingContext(0.02845, inventory_dv01=300e3, dv01_limit=500e3)
    b = make_quote(ctx)
    symmetric = make_quote(QuotingContext(0.02845))
    assert b.direction == "higher"
    assert b.quote.bid > symmetric.quote.bid and b.quote.offer > symmetric.quote.offer   # both sides up
    # the bid is BETTER for a client receiving fixed than at the symmetric quote; the offer is WORSE for a client paying
    assert b.quote.client_rate(ClientAction.RECEIVES) > symmetric.quote.client_rate(ClientAction.RECEIVES)
    assert b.quote.client_rate(ClientAction.PAYS) > symmetric.quote.client_rate(ClientAction.PAYS)
    assert b.encouraged_client_action is ClientAction.RECEIVES

    def next_skew(action):
        swap = b.quote.dealer_swap(action, 100e6, mkt, 10)
        inv = ctx.inventory_dv01 + parallel_dv01(swap, mkt)
        return inv, make_quote(dataclasses.replace(ctx, inventory_dv01=inv)).net_shift_bp

    inv_enc, skew_enc = next_skew(ClientAction.RECEIVES)      # dealer pays fixed: inventory falls
    inv_dis, skew_dis = next_skew(ClientAction.PAYS)          # dealer receives fixed: inventory rises
    assert inv_enc < ctx.inventory_dv01 < inv_dis
    assert skew_enc < b.net_shift_bp < skew_dis               # re-quote: skew eases / intensifies


# 5. short duration dealer is the exact mirror image
def test_example_short_inventory_skews_down_and_encourages_client_paying(mkt):
    ctx = QuotingContext(0.02845, inventory_dv01=-300e3, dv01_limit=500e3)
    b = make_quote(ctx)
    assert b.direction == "lower" and b.encouraged_client_action is ClientAction.PAYS
    swap = b.quote.dealer_swap(ClientAction.PAYS, 100e6, mkt, 10)          # dealer receives: less short
    assert ctx.inventory_dv01 + parallel_dv01(swap, mkt) > ctx.inventory_dv01
    mirror = make_quote(dataclasses.replace(ctx, inventory_dv01=300e3))
    assert b.net_shift_bp == pytest.approx(-mirror.net_shift_bp)


# 6. a view that rates will rise = wants to be SHORT duration = quotes UP, builds a payer, and wins if right
def test_example_bearish_view_chain(mkt):
    b = make_quote(QuotingContext(0.02845, view_bp=4, conviction=0.8))      # flat book, expects rates +4bp
    assert b.direction == "higher"
    assert b.encouraged_client_action is ClientAction.RECEIVES              # clients receiving => dealer PAYS
    swap = b.quote.dealer_swap(ClientAction.RECEIVES, 200e6, mkt, 10)
    assert swap.side is Side.PAY and parallel_dv01(swap, mkt) < 0           # dealer ends short duration...
    assert total_pnl(swap, mkt, +4) > 0 > total_pnl(swap, mkt, -4)         # ...wins if rates rise, loses if they fall


# 7. price-vs-rate mapping: "more willing to sell" (price) is "quote higher" (rate)
def test_example_price_view_equivalence(mkt):
    """Receiving fixed at a rate K is economically 'buying' a bond with coupon K at par. A HIGHER rate K means a
    LOWER price paid: the dealer's rate-OFFER (higher) is its bond-price BID (lower). A long dealer 'sells
    cheaper' = quotes both sides at lower prices = higher rates."""
    low, high = (IRSwap.new(Side.RECEIVE, 100e6, k, mkt.spot, 120) for k in (0.02843, 0.02847))
    assert high.pv(mkt) > low.pv(mkt)      # receiving a higher fixed rate is worth more: the 'cheaper bond'
    assert MARKET.offer > MARKET.bid
