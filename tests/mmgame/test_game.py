"""The game core: several simultaneous markets, quoting rules, execution accounting, limits, schedule and settlement."""

from fractions import Fraction

import pytest

from rates_trainer.mmgame.game import Game, GameError
from rates_trainer.mmgame.probability import Target
from tests.mmgame.helpers import add_deck, add_dice, add_world, empty_game, trade


def two_market_game():
    g = empty_game(2, 3)
    a = add_dice(g, "M1", n=2, resolves_at=3)
    b = add_dice(g, "M2", n=3, resolves_at=5, target=Target("count", {"kind": "odd"}))
    return g, a, b


# ----------------------------------------------------------------------------- quoting rules

def test_quote_validation():
    g, a, _ = two_market_game()
    with pytest.raises(GameError, match="offer must be above"):
        g.set_quote("M1", 7, 7, 1)
    with pytest.raises(GameError, match="offer must be above"):
        g.set_quote("M1", 8, 7, 1)
    with pytest.raises(GameError, match="multiple of the tick"):
        g.set_quote("M1", 6.55, 7.5, 1)
    with pytest.raises(GameError, match="inside"):
        g.set_quote("M1", -1, 7, 1)
    with pytest.raises(GameError, match="inside"):
        g.set_quote("M1", 7, 101, 1)
    with pytest.raises(GameError, match="size"):
        g.set_quote("M1", 6, 8, 0)
    with pytest.raises(GameError, match="size"):
        g.set_quote("M1", 6, 8, g.lv.size_max + 1)
    with pytest.raises(GameError, match="must be a number"):
        g.set_quote("M1", "abc", 8, 1)
    with pytest.raises(GameError, match="must be a number"):
        g.set_quote("M1", True, 8, 1)
    with pytest.raises(GameError, match="unknown market"):
        g.set_quote("M9", 6, 8, 1)
    assert a.quote is None and g.actions == []                    # refused requests change nothing and record nothing
    g.set_quote("M1", 6.5, 7.5, 2)
    assert (a.quote.bid, a.quote.offer, a.quote.size) == (65, 75, 2)


def test_quotes_are_on_the_tick_grid_exactly():
    g, a, _ = two_market_game()
    for ok in (0.3, "0.3", 7, "7.0", 7.0):
        g.set_quote("M1", ok, 12, 1)
        assert a.quote.bid in (3, 70)
    with pytest.raises(GameError, match="multiple of the tick"):
        g.set_quote("M1", 0.1 + 0.2, 7, 1)           # 0.30000000000000004: floating-point noise is not a price
    g.set_quote("M1", 3.1, 3.2, 1)
    assert (a.quote.bid, a.quote.offer) == (31, 32)


def test_batch_quotes_are_all_or_nothing():
    g, a, b = two_market_game()
    with pytest.raises(GameError):
        g.set_quotes([{"market": "M1", "bid": 6, "offer": 8}, {"market": "M2", "bid": 5, "offer": 4}])
    assert a.quote is None and b.quote is None and g.actions == []
    with pytest.raises(GameError, match="twice"):
        g.set_quotes([{"market": "M1", "bid": 6, "offer": 8}, {"market": "M1", "bid": 5, "offer": 9}])
    g.set_quotes([{"market": "M1", "bid": 6, "offer": 8}, {"market": "M2", "bid": 1, "offer": 2, "size": 2}])
    assert a.quote.size == 1 and b.quote.size == 2


def test_pause_resume_acknowledge_semantics():
    g, a, _ = two_market_game()
    g.set_quote("M1", 6, 8)
    g.pause("M1")
    assert a.status(0) == "paused" and a.quote is not None
    g.advance()
    assert a.trades == []                                          # a paused market does not trade
    g.pause("M1", False)
    assert a.status(1) == "active"
    g.pause("M1")
    g.set_quote("M1", 6, 8)
    assert a.status(1) == "active"                                 # quoting a paused market puts it back on
    a.status_flags["shocked"] = True
    assert a.status(1) == "shocked"
    g.acknowledge("M1")
    assert a.status(1) == "active" and a.quote.bid == 60          # acknowledging does not change the quote


def test_status_precedence_and_upcoming():
    g = empty_game(2, 3)
    m = add_dice(g, "M1", opens_at=2, resolves_at=6)
    assert m.status(0) == "upcoming" and m.status(2) == "active"
    with pytest.raises(GameError, match="not open yet"):
        g.set_quote("M1", 6, 8)
    m.status_flags.update(paused=True, shocked=True)
    assert m.status(2) == "paused"
    m.status_flags["resolved"] = True
    assert m.status(2) == "resolved"


# ----------------------------------------------------------------------------- execution and accounting

def test_bot_buying_from_me_lifts_my_offer_and_selling_to_me_hits_my_bid():
    g, a, _ = two_market_game()
    g.set_quote("M1", 6.5, 7.5, 3)
    trade(g, a, "CP-1", "buy", 2)             # the bot BUYS from me: it lifts my offer; I SELL
    t = a.trades[-1]
    assert (t.me, t.qty, t.price) == ("sell", 2, Fraction(15, 2)) and a.pos == -2 and a.cash == 2 * Fraction(15, 2) * a.pv
    trade(g, a, "CP-2", "sell", 1)            # the bot SELLS to me: it hits my bid; I BUY
    t = a.trades[-1]
    assert (t.me, t.qty, t.price) == ("buy", 1, Fraction(13, 2)) and a.pos == -1
    assert a.cash == (2 * Fraction(15, 2) - Fraction(13, 2)) * a.pv


def test_settlement_pnl_is_cash_plus_position_times_outcome():
    g, a, b = two_market_game()
    g.set_quote("M1", 6.5, 7.5, 3)
    g.set_quote("M2", 1.0, 2.0, 3)
    trade(g, a, "CP-1", "buy", 2)             # I sell 2 @ 7.5
    trade(g, a, "CP-2", "sell", 3)            # I buy 3 @ 6.5
    trade(g, b, "CP-3", "sell", 2)            # I buy 2 @ 1.0
    S1 = a.truth(g.exps)
    S2 = b.truth(g.exps)
    exp_a = (2 * Fraction(15, 2) - 3 * Fraction(13, 2) + (3 - 2) * S1) * a.pv
    exp_b = (-2 * Fraction(1) + 2 * S2) * b.pv
    g.m("M1").resolves_at = 1
    g.m("M2").resolves_at = 1
    g.pause("M1")                                   # paused markets do not trade, so only the scripted trades are in the ledger
    g.pause("M2")
    g.advance()
    assert a.settle == S1 and a.cash == exp_a and a.pos == 0 and a.settled_pos == 1
    assert b.settle == S2 and b.cash == exp_b
    assert g.done and g.view()["portfolio"]["pnl_total"] == float(exp_a + exp_b)


def test_aggregate_position_and_pnl_across_markets():
    g, a, b = two_market_game()
    g.set_quote("M1", 6.5, 7.5)
    g.set_quote("M2", 1, 2)
    trade(g, a, "CP-1", "buy", 1)
    trade(g, b, "CP-1", "sell", 1)
    trade(g, b, "CP-2", "sell", 1)
    v = g.view()
    assert v["portfolio"]["net_lots"] == -1 + 2 and v["portfolio"]["gross_lots"] == 3 and v["portfolio"]["trades"] == 3
    mid_a = (Fraction(13, 2) + Fraction(15, 2)) / 2
    exp_open = (a.cash + a.pos * mid_a * a.pv) + (b.cash + b.pos * Fraction(3, 2) * b.pv)
    assert v["portfolio"]["pnl_open"] == pytest.approx(float(exp_open)) and v["portfolio"]["pnl_settled"] == 0


def test_average_price_moves_with_adds_reductions_and_flips():
    g, a, _ = two_market_game()
    g.set_quote("M1", 6, 8, 4)
    trade(g, a, "CP-1", "sell", 2)            # buy 2 @ 6
    assert a.avg_price() == 6
    g.set_quote("M1", 5, 7, 4)
    trade(g, a, "CP-1", "sell", 1)            # buy 1 @ 5: average (12+5)/3
    assert a.avg_price() == Fraction(17, 3)
    trade(g, a, "CP-1", "buy", 1)             # sell 1 @ 7: reducing keeps the average
    assert a.avg_price() == Fraction(17, 3) and a.pos == 2
    trade(g, a, "CP-1", "buy", 3)             # sell 3 @ 7: crosses zero, new position at 7
    assert a.pos == -1 and a.avg_price() == 7


def test_position_limit_closes_the_side_and_caps_fills():
    g, a, _ = two_market_game()
    g.set_quote("M1", 6, 8, g.lv.size_max)
    assert g.lv.limit == 5 and g._room(a, "buy") == 4
    a.pos = 4
    assert g._room(a, "buy") == 1 and g._room(a, "sell") == 4
    a.pos = 5
    assert g._room(a, "buy") == 0 and g.closed_sides(a) == {"bid": True, "offer": False}
    a.pos = -5
    assert g._room(a, "sell") == 0 and g.closed_sides(a) == {"bid": False, "offer": True}


def test_no_trades_without_a_quote_and_none_after_resolution():
    g = empty_game(2, 3)
    a = add_dice(g, "M1", resolves_at=2)
    add_dice(g, "M2", resolves_at=4)
    g.advance()
    assert a.trades == []
    g.set_quote("M1", 6, 8)
    g.advance()
    assert a.resolved and not g.done
    with pytest.raises(GameError, match="already resolved"):
        g.set_quote("M1", 6, 8)
    with pytest.raises(GameError, match="already resolved"):
        g.pause("M1")
    g.advance()
    g.advance()
    assert g.done
    with pytest.raises(GameError, match="over"):
        g.advance()


def test_risk_budget_blocks_trades_that_add_risk_but_not_those_that_reduce_it():
    g = empty_game(3, 3)
    ms = [add_dice(g, f"M{i}", n=3, resolves_at=9) for i in range(1, 4)]
    r1 = g._risk(ms[0], 1)                                       # 1σ risk of one lot, in credits
    assert 50 < r1 < 400
    object.__setattr__(g.lv, "risk_budget", int(r1 * 2.5))       # room for two lots, and half a lot more
    try:
        for m in ms:
            g.set_quote(m.id, 9, 12, 4)
        ms[0].pos = 2
        assert g._room(ms[1], "buy") == 0 and g._room(ms[1], "sell") == 0      # no budget left for new risk, either direction
        assert g._room(ms[0], "sell") == 4                       # reducing the position is always allowed
        assert g._room(ms[0], "buy") == 0
        ms[0].pos = 1
        assert g._room(ms[1], "buy") == 1                        # one lot of budget freed: exactly one lot fits
    finally:
        object.__setattr__(g.lv, "risk_budget", 1100)            # the level table is shared: restore it


def test_levels_differ_in_structure():
    from rates_trainer.mmgame.levels import LEVELS
    assert [LEVELS[i].rounds for i in (1, 2, 3)] == [8, 12, 14]
    assert LEVELS[1].markets[1] < LEVELS[2].markets[1] < LEVELS[3].markets[1]
    assert LEVELS[1].risk_budget is None and LEVELS[3].risk_budget
    assert "insider" not in LEVELS[2].bots and "insider" in LEVELS[3].bots and "sniper" not in LEVELS[1].bots and "sniper" in LEVELS[2].bots
    assert LEVELS[3].linked == 1 and LEVELS[1].linked == 0
    assert LEVELS[1].shocks[1] < LEVELS[2].shocks[1] < LEVELS[3].shocks[1]
    assert LEVELS[1].later_markets == 0 and LEVELS[2].later_markets > 0


def test_markets_resolve_at_different_times_and_the_game_ends_with_the_last():
    g = empty_game(2, 4)
    for i, r in enumerate((2, 4, 7), 1):
        add_dice(g, f"M{i}", resolves_at=r)
    g.set_quotes([{"market": f"M{i}", "bid": 6, "offer": 8} for i in (1, 2, 3)])
    seen = []
    while not g.done:
        rep = g.advance()
        seen.append((rep["round"], [e["market"] for e in rep["events"] if e["type"] == "resolved"]))
    assert [(r, m) for r, m in seen if m] == [(2, ["M1"]), (4, ["M2"]), (7, ["M3"])]
    assert [m.resolved_round for m in g.markets] == [2, 4, 7]


def test_late_opening_market():
    g = empty_game(2, 4)
    add_dice(g, "M1", resolves_at=6)
    late = add_dice(g, "M2", opens_at=2, resolves_at=6)
    assert g.view()["markets"][1]["status"] == "upcoming" and "question" not in g.view()["markets"][1]
    g.advance()
    g.advance()
    assert late.is_open(g.round) and any(e["type"] == "opened" for e in g.reports[-1]["events"]) and len(late.fair_hist) == 1
    assert g.view()["markets"][1]["question"]


def test_world_and_dice_markets_side_by_side_and_a_deck():
    g = empty_game(2, 4)
    add_world(g, "M1", "bastille", resolves_at=3)
    add_dice(g, "M2", resolves_at=3)
    add_deck(g, "M3", resolves_at=3)
    g.set_quotes([{"market": "M1", "bid": 1780, "offer": 1790, "size": 1}, {"market": "M2", "bid": 6.5, "offer": 7.5}, {"market": "M3", "bid": 1, "offer": 2}])
    while not g.done:
        g.advance()
    assert g.m("M1").settle == 1789 and all(m.resolved for m in g.markets)


def test_every_market_view_has_what_a_player_needs():
    g, a, _ = two_market_game()
    g.set_quote("M1", 6, 8)
    mv = g.view()["markets"][0]
    for k in ("question", "rules", "resolution_rule", "unit", "tick", "range", "possible", "remaining", "limit", "position", "quote", "trades", "status", "lot_value", "closed"):
        assert k in mv, k
    assert mv["remaining"] == 3 and mv["unit"] == "points" and "Settles" in mv["resolution_rule"]
