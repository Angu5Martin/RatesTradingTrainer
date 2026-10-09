"""The bots: what each personality does with a quote, that they trade only at my price, and that the three levels field different fields."""

import statistics

import pytest

from rates_trainer.mmgame.bots import Bot, Look, PERSONALITIES, consider, make_bots
from rates_trainer.mmgame.game import Game
from rates_trainer.mmgame.levels import LEVELS
from rates_trainer.mmgame.rng import Stream
from tests.mmgame.helpers import add_dice, empty_game


def look(fair=10.0, sd=2.0, bid=9.0, offer=11.0, lagged=None, truth=None, buy=4, sell=4):
    return Look("M1", fair, sd, fair if lagged is None else lagged, fair if truth is None else truth, bid, offer, 0.1, buy, sell)


def freq(key, lk, phase="A", n=1500):
    """How often the bot trades, and on which side, over n independent draws."""
    out = {"buy": 0, "sell": 0, None: 0}
    sizes = []
    for i in range(n):
        o = consider(Bot("CP-1", key), lk, Stream(i, "b"), phase)
        out[o.bot_side if o else None] += 1
        if o:
            sizes.append(o.qty)
    return out, sizes


def test_panels_by_level():
    assert [b.key for b in make_bots(LEVELS[1].bots)].count("retail") == 2
    keys = {lv: {b.key for b in make_bots(LEVELS[lv].bots)} for lv in (1, 2, 3)}
    assert keys[1] == {"retail", "value", "anchor"} and keys[2] == keys[1] | {"sniper"} and keys[3] == keys[2] | {"insider"}
    assert [b.id for b in make_bots(LEVELS[3].bots)] == [f"CP-{i}" for i in range(1, 8)]


def test_retail_trades_both_ways_around_fair_and_is_put_off_by_a_wide_market():
    tight, _ = freq("retail", look(bid=9.7, offer=10.3))
    wide, _ = freq("retail", look(bid=7.0, offer=13.0))
    assert tight["buy"] > 150 and tight["sell"] > 150 and abs(tight["buy"] - tight["sell"]) < 120
    assert wide["buy"] + wide["sell"] < 0.2 * (tight["buy"] + tight["sell"])           # flow dries up as the spread widens
    assert max(freq("retail", look())[1] or [1]) == 1                                    # retail is always small


def test_retail_follows_a_skewed_quote():
    cheap_offer, _ = freq("retail", look(bid=7.5, offer=10.2))                            # offer just above fair, bid far below
    assert cheap_offer["buy"] > 3 * max(cheap_offer["sell"], 1)


def test_value_bot_only_trades_a_quote_that_is_clearly_off_fair():
    centred, _ = freq("value", look(bid=9.4, offer=10.6))
    assert centred["buy"] + centred["sell"] < 40                                           # nothing to do at a fair market
    high, sz = freq("value", look(bid=11.5, offer=12.5))                                   # my bid is above fair: it sells to me
    assert high["sell"] > 400 and high["buy"] == 0 and statistics.mean(sz) > 1
    low, _ = freq("value", look(bid=7.5, offer=8.5))                                       # my offer is below fair: it buys from me
    assert low["buy"] > 400 and low["sell"] == 0


def test_anchor_bot_prices_off_the_old_fair_value():
    new_fair_high = look(fair=14.0, lagged=10.0, bid=9.5, offer=10.5)                      # truth moved up, the bot still thinks 10
    out, _ = freq("anchor", new_fair_high)
    assert out["buy"] + out["sell"] < 250                                                  # at the stale price it sees an almost fair market
    stale_hit, _ = freq("anchor", look(fair=10.0, lagged=14.0, bid=9.5, offer=10.5))
    assert stale_hit["buy"] > 3 * (out["buy"] + out["sell"])
    out2, _ = freq("anchor", look(fair=10.0, lagged=14.0, bid=9.5, offer=10.5))            # it believes 14: buys my 10.5 offer
    assert out2["buy"] > 300


def test_sniper_and_insider_react_in_phase_b_and_the_others_do_not():
    stale = look(fair=14.0, bid=9.5, offer=10.5, truth=14.0)
    for key in ("retail", "value", "anchor"):
        assert freq(key, stale, "B", 200)[0]["buy"] == 0
    s, sz = freq("sniper", stale, "B", 400)
    assert s["buy"] == 400 and max(sz) > 1                                                 # certain, and with size
    i, _ = freq("insider", stale, "B", 400)
    assert 250 < i["buy"] < 400                                                            # usually, not always
    a, _ = freq("sniper", stale, "A", 600)
    assert 0 < a["buy"] < 250                                                              # in normal flow it is rare


def test_insider_trades_toward_the_truth_whatever_the_public_fair_value_says():
    up, _ = freq("insider", look(fair=10.0, truth=12.0, bid=9.0, offer=11.0))
    down, _ = freq("insider", look(fair=10.0, truth=8.0, bid=9.0, offer=11.0))
    flat, _ = freq("insider", look(fair=10.0, truth=10.0, bid=9.0, offer=11.0))
    assert up["buy"] > 300 and up["sell"] == 0 and down["sell"] > 300 and down["buy"] == 0
    assert flat["buy"] + flat["sell"] < 40                                                 # no edge: no trade (absence of trading is information)


def test_bots_respect_room_and_size():
    out, sz = freq("sniper", look(fair=14.0, bid=9.5, offer=10.5, buy=2), "B", 200)
    assert max(sz) <= 2
    out, _ = freq("sniper", look(fair=14.0, bid=9.5, offer=10.5, buy=0), "B", 200)
    assert out["buy"] == 0                                                                 # my offer is closed: nobody can lift it


def test_decisions_are_deterministic_per_stream():
    a = [consider(Bot("CP-1", "value"), look(bid=11.5, offer=12.5), Stream(5, "x", i), "A") for i in range(50)]
    b = [consider(Bot("CP-1", "value"), look(bid=11.5, offer=12.5), Stream(5, "x", i), "A") for i in range(50)]
    assert a == b


def test_bots_trade_only_at_my_quoted_price_and_never_more_than_my_size():
    for level in (1, 2, 3):
        g = empty_game(level, 9)
        m = add_dice(g, "M1", n=3, resolves_at=12)
        g.set_quote("M1", 9.5, 11.5, 2)
        for _ in range(8):
            g.advance()
            if m.resolved:
                break
        assert m.trades
        for t in m.trades:
            assert t.price in (t.bid, t.offer) and t.qty <= 2 and (t.me == "buy") == (t.price == t.bid)
            assert abs(t.pos_after) <= m.limit


def test_a_paused_or_unquoted_market_gets_no_flow():
    g = empty_game(1, 3)
    m = add_dice(g, "M1", resolves_at=8)
    g.advance()
    assert not m.trades
    g.set_quote("M1", 6, 8)
    g.pause("M1")
    for _ in range(3):
        g.advance()
    assert not m.trades


def test_an_insider_rations_its_size_across_markets():
    g = empty_game(3, 2)
    ms = [add_dice(g, f"M{i}", n=3, resolves_at=12) for i in range(1, 7)]
    for m in ms:
        g.set_quote(m.id, 1.0, 1.5, 4)                     # absurdly cheap offers: every market is a gift to someone who knows the answer
    g.advance()
    for bot in g.bots:
        if bot.p.capacity:
            got = sum(t.qty for m in ms for t in m.trades if t.bot == bot.id and t.round == 1)
            assert got <= bot.p.capacity


# ----------------------------------------------------------------------------- the incentives, measured on whole games

def mean_result(level, strategy, seeds, **kw):
    from rates_trainer.mmgame import debrief
    from fractions import Fraction
    tot = {"pnl": [], "adverse": [], "edge": []}
    for seed in seeds:
        g = Game(level, seed)
        while not g.done:
            for m in g.markets:
                if not m.is_open(g.round):
                    continue
                if strategy == "stale" and m.quote is not None:
                    continue
                f, sd = m.public(g.exps)
                bias = kw.get("bias", 0.0) * sd
                h = max(float(m.tick), kw.get("half", 0.5) * sd)
                b = round((float(f) + bias - h) / float(m.tick)) * m.tick
                o = round((float(f) + bias + h) / float(m.tick)) * m.tick
                if o <= b:
                    o = b + m.tick
                lo, hi = m.price_lo, m.price_hi
                b, o = max(lo, min(b, hi - m.tick)), min(hi, max(o, lo + m.tick))
                g.set_quote(m.id, float(b), float(o), 1)
            g.advance()
        d = debrief.build(g)
        tot["pnl"].append(d["totals"]["pnl"]); tot["adverse"].append(d["totals"]["adverse_selection"]); tot["edge"].append(d["totals"]["decision_edge"])
    return {k: statistics.mean(v) for k, v in tot.items()}


@pytest.mark.parametrize("level", [1, 2, 3])
def test_quoting_fair_with_a_sensible_spread_beats_a_mispriced_market(level):
    seeds = range(100, 112)
    good = mean_result(level, "fair", seeds, half=0.5)
    bad = mean_result(level, "fair", seeds, half=0.5, bias=0.8)
    assert good["pnl"] > bad["pnl"] + 100 and good["edge"] > bad["edge"] + 200


def test_never_requoting_after_shocks_costs_money_at_level_2():
    seeds = range(200, 214)
    live = mean_result(2, "fair", seeds)
    stale = mean_result(2, "stale", seeds)
    assert live["pnl"] > stale["pnl"] + 100


def test_informed_counterparties_cost_something_at_level_3_and_not_at_level_1():
    assert mean_result(3, "fair", range(300, 312))["adverse"] < -300
    assert mean_result(1, "fair", range(300, 312))["adverse"] == 0                  # nobody informed at level 1: adverse selection is exactly zero
