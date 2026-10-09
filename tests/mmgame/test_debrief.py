"""The debrief: P&L attribution checked by hand and independently, and the classification of decisions versus luck."""

import random
from fractions import Fraction

import pytest

from rates_trainer.mmgame import debrief
from rates_trainer.mmgame.game import Game
from rates_trainer.mmgame.probability import RestrictFaces, Target
from tests.mmgame.helpers import add_dice, add_world, empty_game, shock, trade
from tests.mmgame.test_hidden_replay import walk


def finish(g):
    for m in g.markets:
        g.pause(m.id)
    while not g.done:
        g.advance()
    return debrief.build(g)


def test_a_single_sale_attributed_by_hand():
    g = empty_game(2, 4)
    m = add_dice(g, "M1", n=2, resolves_at=2)
    add_dice(g, "M2", n=2, resolves_at=2)
    g.set_quote("M1", 6.5, 7.5, 1)
    trade(g, m, "CP-1", "buy", 1)                                  # the bot lifts my 7.5 offer: I sell 1 at 7.5; fair value is exactly 7
    S, pv = m.truth(g.exps), m.pv
    d = finish(g)["markets"][0]
    assert d["pnl"]["total"] == float((Fraction(15, 2) - S) * pv)
    assert d["pnl"]["spread_capture"] == float(Fraction(1, 2) * pv)                        # half of the 1.0 spread
    assert d["pnl"]["mispricing"] == 0.0                                                   # my mid was exactly fair value
    assert d["pnl"]["edge"] == float(Fraction(1, 2) * pv)
    assert d["pnl"]["news_drift"] == 0.0 and d["pnl"]["adverse_selection"] == 0.0
    assert d["pnl"]["settlement_luck"] == float(-(S - 7) * pv)                              # short 1, answer S against an expectation of 7
    assert d["trades"][0]["fair"] == 7.0 and d["trades"][0]["edge"] == float(Fraction(1, 2) * pv)


def test_a_skewed_quote_shows_up_as_mispricing_not_spread():
    g = empty_game(2, 4)
    m = add_dice(g, "M1", n=2, resolves_at=2)
    add_dice(g, "M2", n=2, resolves_at=2)
    g.set_quote("M1", 5.5, 6.5, 1)                                  # mid 6.0 against fair 7.0: skewed to buy... I sell at 6.5, which is BELOW fair
    trade(g, m, "CP-1", "buy", 2)
    d = finish(g)["markets"][0]
    pv = m.pv
    assert d["pnl"]["spread_capture"] == float(2 * Fraction(1, 2) * pv)
    assert d["pnl"]["mispricing"] == float(2 * (Fraction(6) - 7) * pv)                    # a sale with mid 1.0 below fair: -1.0 per lot
    assert d["pnl"]["edge"] == float(2 * (Fraction(13, 2) - 7) * pv) and d["trades"][0]["edge"] < 0


def test_news_drift_is_the_move_in_fair_value_after_the_trade():
    g = empty_game(2, 4)
    m = add_dice(g, "M1", n=2, resolves_at=3)
    add_dice(g, "M2", n=2, resolves_at=3)
    g.set_quote("M1", 6.5, 7.5, 1)
    trade(g, m, "CP-1", "buy", 1)                                  # sold 1 at fair 7
    shock(g, 1, RestrictFaces({"kind": "ge", "v": 4}), "E_M1", "experiment")           # dice now 4-6: fair 10
    g.pause("M1"); g.pause("M2")
    g.advance(); g.advance(); g.advance()
    d = debrief.build(g)["markets"][0]
    assert d["final_fair"] == 10.0
    assert d["pnl"]["news_drift"] == float(-1 * (10 - 7) * m.pv)                            # short while fair value rose by 3
    assert d["shocks"][0]["fair_moved_sd"] > 1 and d["shocks"][0]["position"] == -1 and d["shocks"][0]["mark_impact"] == float(-1 * 3 * m.pv)
    assert d["shocks"][0]["requoted_at_once"] is False and d["shocks"][0]["quote_was_off_by_sd"] < 0


def test_informed_counterparty_trades_are_adverse_selection_not_luck():
    g = empty_game(3, 4)
    m = add_dice(g, "M1", n=2, resolves_at=2)
    add_dice(g, "M2", n=2, resolves_at=2)
    insider = next(b.id for b in g.bots if b.p.informed)
    retail = next(b.id for b in g.bots if b.key == "retail")
    g.set_quote("M1", 6.5, 7.5, 3)
    trade(g, m, retail, "buy", 1)
    trade(g, m, insider, "buy", 2)
    d = finish(g)
    pnl = d["markets"][0]["pnl"]
    S, pv = m.truth(g.exps), m.pv
    assert pnl["adverse_selection"] == float(-2 * (S - 7) * pv) and pnl["settlement_luck"] == float(-1 * (S - 7) * pv)
    assert pnl["total"] == pytest.approx(pnl["edge"] + pnl["adverse_selection"] + pnl["news_drift"] + pnl["settlement_luck"])
    assert [t["informed"] for t in d["markets"][0]["trades"]] == [False, True]
    c = {x["id"]: x for x in d["counterparties"]}
    assert c[insider]["label"] == "Informed" and c[insider]["trades"] == 1 and c[retail]["label"] == "Retail flow"


def test_trade_verdicts_separate_stale_mispriced_unlucky_and_good():
    g = empty_game(2, 4)
    m = add_dice(g, "M1", n=2, resolves_at=3)
    add_dice(g, "M2", n=2, resolves_at=3)
    g.set_quote("M1", 6.5, 7.5, 3)
    trade(g, m, "CP-1", "buy", 1)                                  # fair-priced sale at the start
    shock(g, 1, RestrictFaces({"kind": "ge", "v": 5}), "E_M1", "experiment")
    g.pause("M2")
    g.advance()                                                    # the sniper hits my stale offer after the shock
    g.pause("M1")
    g.advance(); g.advance()
    d = debrief.build(g)
    rows = d["markets"][0]["trades"]
    stale = [r for r in rows if r["stale"]]
    assert stale and all(r["edge"] < 0 for r in stale)
    assert {r["cause"] for r in stale} <= {"stale", "lucky"} and any(r["cause"] == "stale" for r in stale)
    assert any(x["kind"] == "stale" for x in d["decisions"])
    assert d["trade_causes"]["stale"] >= 1


def test_quote_review_recognises_centred_skewed_and_off_quotes():
    g = empty_game(2, 4)
    m = add_dice(g, "M1", n=2, resolves_at=6)
    add_dice(g, "M2", n=2, resolves_at=6)
    for x in g.markets:
        g.set_quote(x.id, 6.5, 7.5, 3)
    g.pause("M1")                                                  # no bot flow: the only trades are the scripted ones
    g.pause("M2")
    g.set_quote("M1", 6.5, 7.5, 3)                                 # round 1: centred (this also un-pauses M1; pause again below)
    g.pause("M1")
    g.advance()
    g.set_quote("M1", 6.5, 7.5, 3)
    trade(g, m, "CP-1", "sell", 3)                                 # I buy 3: long 3
    g.pause("M1")
    g.set_quote("M1", 5.5, 6.5, 1)                                 # long 3, mid 6.0 well below fair 7: skewed to sell, sensible
    g.pause("M1")
    g.advance()
    g.set_quote("M1", 7.5, 8.5, 1)                                 # still long, mid above fair: adds risk
    g.pause("M1")
    g.advance()
    g.set_quote("M1", 1.0, 2.0, 1)                                 # nonsense
    g.pause("M1")
    g.advance()
    while not g.done:
        g.advance()
    q = debrief.build(g)["markets"][0]["quotes"]
    verdicts = [x["verdict"] for x in q if x["round"] > 1]
    assert verdicts[0] == "centred on fair value" or q[0]["verdict"] == "centred on fair value"
    assert "skewed to reduce inventory (sensible)" in verdicts and "skewed the same way as inventory (adds risk)" in verdicts and "off fair value" in verdicts
    assert q[0]["spread"] == "reasonable" and q[0]["error_sd"] == pytest.approx(0, abs=0.01)


def test_the_world_question_is_scored_against_the_crowd_belief_and_shows_the_source():
    g = empty_game(2, 4)
    m = add_world(g, "M1", "bastille", z=1.0, resolves_at=2)
    add_dice(g, "M2", resolves_at=2)
    g.set_quote("M1", 1788, 1790, 1)
    d = finish(g)["markets"][0]
    assert d["settle"] == 1789 and d["source"].startswith("Encyclopaedia") and d["as_of"] == "2025" and d["kind"] == "world"


@pytest.mark.parametrize("level", [1, 2, 3])
def test_totals_recomputed_independently_from_raw_trades(level):
    g = walk(Game(level, 500 + level), random.Random(level))
    d = debrief.build(g)
    tot = Fraction(0)
    for m in g.markets:
        # independent: cash from raw trades plus the settlement of the final position
        cash = Fraction(0)
        pos = 0
        for t in m.trades:
            s = t.qty if t.me == "buy" else -t.qty
            cash -= s * t.price * m.pv
            pos += s
        cash += pos * m.settle * m.pv
        assert cash == m.cash and pos == m.settled_pos
        tot += cash
        dm = next(x for x in d["markets"] if x["id"] == m.id)
        assert dm["pnl"]["total"] == pytest.approx(float(cash))
        parts = dm["pnl"]
        assert parts["total"] == pytest.approx(parts["edge"] + parts["adverse_selection"] + parts["news_drift"] + parts["settlement_luck"], abs=1e-6)
        assert parts["edge"] == pytest.approx(parts["spread_capture"] + parts["mispricing"], abs=1e-6)
    t = d["totals"]
    assert t["pnl"] == pytest.approx(float(tot)) and t["decision_result"] == pytest.approx(t["decision_edge"] + t["adverse_selection"])
    assert t["pnl"] == pytest.approx(t["decision_result"] + t["luck"], abs=1e-6)
    assert sum(len(m["trades"]) for m in d["markets"]) == d["game"]["trades"]
    assert {c["id"] for c in d["counterparties"]} == {b.id for b in g.bots} and all(c["label"] and c["description"] for c in d["counterparties"])
    assert d["convention"] and "adverse selection" in d["convention"].lower()


def test_debrief_does_not_exist_before_the_end():
    g = Game(1, 5)
    with pytest.raises(ValueError):
        debrief.build(g)
