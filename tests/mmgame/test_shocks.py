"""Every shock type, played through the real round loop: what it changes, what it must not, who is hit, and what the player is told."""

from fractions import Fraction

import pytest

from rates_trainer.mmgame.probability import (EFFECT_TYPES, AddJokers, AddTrials, ChangeDraws, LoadFace, RemoveCards, RemoveTrials, RestrictFaces, RevealCards, RevealClass, RevealTrials, SetAgg,
                                              SetPred, SetSides, SetSpecial, SetThreshold, Target)
from rates_trainer.mmgame.world import AltResolution, Clue
from tests.mmgame.helpers import add_deck, add_dice, add_world, empty_game, shock, trade

DICE = Target("sum")
COUNT_EVENT = Target("count", {"kind": "ge", "v": 5}, {"op": "ge", "t": 2})


def build(kind: str):
    """A game with the market the effect acts on (M1), an unrelated control market (M2) and a world control (M3); returns (game, effect, the market hit, scope, ref)."""
    g = empty_game(2, 11)
    if kind in ("remove_cards", "add_jokers", "change_draws", "reveal_cards", "set_special"):
        m = add_deck(g, "M1", draws=5, resolves_at=6, event={"op": "ge", "t": 1} if kind == "set_special" else None)
    elif kind in ("clue", "alt_resolution"):
        m = add_world(g, "M1", "rome" if kind == "alt_resolution" else "bastille", z=1.0, resolves_at=6)
    elif kind in ("set_threshold",):
        m = add_dice(g, "M1", n=4, target=COUNT_EVENT, resolves_at=6)
    elif kind == "set_pred":
        m = add_dice(g, "M1", n=4, target=Target("count", {"kind": "even"}), resolves_at=6)
    else:
        m = add_dice(g, "M1", n=3, target=DICE, resolves_at=6)
    add_dice(g, "M2", n=2, resolves_at=6, key="E_ctrl")
    add_world(g, "M3", "gold_z", resolves_at=6)
    eff = {"restrict_faces": RestrictFaces({"kind": "ge", "v": 4}), "set_sides": SetSides(10), "load_face": LoadFace(6, 3), "add_trials": AddTrials(2), "remove_trials": RemoveTrials(1),
           "remove_cards": RemoveCards({"kind": "color", "v": "black"}), "add_jokers": AddJokers(2), "change_draws": ChangeDraws(2),
           "reveal_trials": RevealTrials(2), "reveal_class": RevealClass("half"), "reveal_cards": RevealCards(2), "clue": Clue("ge", "1790"),
           "set_threshold": SetThreshold(1), "set_pred": SetPred({"kind": "ge", "v": 5}), "set_agg": SetAgg("top2"), "set_special": SetSpecial({"kind": "color", "v": "red"}),
           "alt_resolution": AltResolution()}[kind]
    scope = "market" if (eff.scope == "market" or m.world) else "experiment"
    ref = m.id if scope == "market" else m.exp_id
    return g, eff, m, scope, ref


ALL_KINDS = sorted(set(EFFECT_TYPES) | {"clue", "alt_resolution"})
EXPECT_CATEGORY = {"restrict_faces": "experiment", "set_sides": "experiment", "load_face": "experiment", "add_trials": "experiment", "remove_trials": "experiment", "remove_cards": "experiment",
                   "add_jokers": "experiment", "change_draws": "experiment", "reveal_trials": "information", "reveal_class": "information", "reveal_cards": "information", "clue": "information",
                   "set_threshold": "resolution", "set_pred": "resolution", "set_agg": "resolution", "set_special": "resolution", "alt_resolution": "resolution"}


def test_every_effect_type_is_covered_here():
    assert set(ALL_KINDS) == set(EXPECT_CATEGORY) and len(ALL_KINDS) == 17


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_effect_in_the_round_loop(kind):
    g, eff, m, scope, ref = build(kind)
    assert eff.category == EXPECT_CATEGORY[kind]
    # M1 is quoted and then paused, so no bot trade can touch its quote or position: what is left is the effect itself
    q1 = (round(float(m.price_lo) + float(m.tick) * 3, 6), round(float(m.price_lo) + float(m.tick) * 5, 6))
    g.set_quote("M1", *q1, 1)
    g.pause("M1")
    ctrl_before = {x.id: x.public(g.exps) for x in g.markets if x.id != "M1"}
    quote_before = (m.quote.bid, m.quote.offer, m.quote.size)
    fair_before, sd_before = m.public(g.exps)
    support_before = m.support(g.exps)
    shock(g, 1, eff, ref, scope)
    rep = g.advance()
    ev = [e for e in rep["events"] if e["type"] == "shock"]
    assert len(ev) == 1 and ev[0]["category"] == EXPECT_CATEGORY[kind] and ev[0]["markets"] == ["M1"] and ev[0]["text"] and ev[0]["headline"] in ("RULE CHANGE", "NEW INFORMATION", "RESOLUTION CHANGE")
    # the hit market is flagged, annotated, and its quote and position are untouched
    assert m.status_flags["shocked"] and m.notes[-1]["text"] == ev[0]["text"] and m.notes[-1]["category"] == EXPECT_CATEGORY[kind]
    assert (m.quote.bid, m.quote.offer, m.quote.size) == quote_before and m.pos == 0
    # an unrelated market is not affected at all
    assert {x.id: x.public(g.exps) for x in g.markets if x.id != "M1"} == ctrl_before and not any(x.status_flags["shocked"] for x in g.markets if x.id != "M1")
    fair_after, _ = m.public(g.exps)
    if kind not in ("reveal_trials", "reveal_class", "reveal_cards", "clue", "add_jokers", "change_draws", "set_special"):
        assert fair_after != fair_before or m.support(g.exps) != support_before, "the effect should change what the market is worth or can settle at"
    # re-quoting clears the flag
    g.set_quote("M1", *q1, 1)
    assert not m.status_flags["shocked"]


def played(kind):
    g, eff, m, scope, ref = build(kind)
    shock(g, 1, eff, ref, scope)
    return g, m, ref, [e for e in g.advance()["events"] if e["type"] == "shock"][0]["text"]


def test_semantics_distinguish_experiment_information_and_resolution():
    # experiment: the trials change, the target does not
    g, eff, m, scope, ref = build("restrict_faces")
    trials_before, target_before = [dict(t.weights) for t in g.exps[ref].trials], m.target
    shock(g, 1, eff, ref, scope)
    g.advance()
    assert [dict(t.weights) for t in g.exps[ref].trials] != trials_before and m.target == target_before
    # information: the rules do not change (the unrolled trial keeps its weights), the target is the same, and the outcome is exactly what it was
    g, eff, m, scope, ref = build("reveal_trials")
    answer_before = m.truth(g.exps)
    pend_before = [dict(t.weights) for t in g.exps[ref].trials if t.state == "pending"]
    shock(g, 1, eff, ref, scope)
    g.advance()
    assert [dict(t.weights) for t in g.exps[ref].trials if t.state == "pending"] == pend_before[2:]
    assert m.target == DICE and m.truth(g.exps) == answer_before
    # resolution: the trials do not change at all, the target does
    g, eff, m, scope, ref = build("set_agg")
    trials_before = [(t.state, dict(t.weights)) for t in g.exps[m.exp_id].trials]
    shock(g, 1, eff, ref, scope)
    g.advance()
    assert [(t.state, dict(t.weights)) for t in g.exps[m.exp_id].trials] == trials_before and m.target.agg == "top2"
    # and the texts say which kind they are
    t_restrict, t_info, t_res = (played(k)[3] for k in ("restrict_faces", "reveal_class", "set_threshold"))
    assert "no longer" in t_restrict and "nothing else has changed" in t_info.lower() and "unchanged" in t_res and t_res.startswith("Resolution change")


def test_information_text_does_not_reveal_unrolled_outcomes():
    g, eff, m, scope, ref = build("reveal_class")
    shock(g, 1, eff, ref, scope)
    text = [e for e in g.advance()["events"] if e["type"] == "shock"][0]["text"]
    assert "shows" not in text and "exact value is not shown" in text
    g, eff, m, scope, ref = build("reveal_trials")
    shock(g, 1, eff, ref, scope)
    text = [e for e in g.advance()["events"] if e["type"] == "shock"][0]["text"]
    assert text.count("shows") == 2 and "still to be rolled" in text                 # two dice are shown; the rest are explicitly still open
    trials = g.exps[ref].trials
    assert [t.state for t in trials] == ["revealed", "revealed", "pending"]


def test_a_shock_on_a_shared_experiment_hits_every_market_on_it_but_a_resolution_shock_hits_one():
    g = empty_game(3, 5)
    a = add_dice(g, "M1", n=4, key="E_shared", resolves_at=6)
    b = add_dice(g, "M2", n=4, key="E_shared", target=Target("count", {"kind": "odd"}), resolves_at=6)
    c = add_dice(g, "M3", n=2, key="E_other", resolves_at=6)
    shock(g, 1, RestrictFaces({"kind": "even"}), "E_shared", "experiment")
    shock(g, 2, SetPred({"kind": "ge", "v": 4}), "M2", "market")
    for m in (a, b, c):
        g.set_quote(m.id, 1, 2)
        g.pause(m.id)
    g.advance()
    assert a.status_flags["shocked"] and b.status_flags["shocked"] and not c.status_flags["shocked"]
    assert g.shock_log[0]["markets"] == ["M1", "M2"]
    for m in (a, b):
        g.acknowledge(m.id)
    g.advance()
    assert b.status_flags["shocked"] and not a.status_flags["shocked"] and b.target.pred == {"kind": "ge", "v": 4} and a.target == DICE
    assert a.exp_id == b.exp_id == "E_shared" and len(g.exps) == 2


def test_a_shock_is_never_planned_for_a_market_that_is_not_open_or_has_resolved():
    from rates_trainer.mmgame.generator import build
    for level in (2, 3):
        for seed in range(25):
            sp = build(level, seed)
            by_id = {m.id: m for m in sp.markets}
            for s in sp.shocks:
                hit = [m for m in sp.markets if m.exp_id == s.ref] if s.scope == "experiment" else [by_id[s.ref]]
                for m in hit:
                    assert m.opens_at < s.round < m.resolves_at, (level, seed, s.id, m.id)


# ----------------------------------------------------------------------------- the fast reaction: stale quotes

def stale_setup(level):
    g = empty_game(level, 7)
    m = add_dice(g, "M1", n=2, resolves_at=6)                                # fair 7
    g.set_quote("M1", 6.5, 7.5, g.lv.size_max)
    shock(g, 1, RestrictFaces({"kind": "ge", "v": 5}), "E_M1", "experiment")  # dice now 5 or 6: fair 11, far above my offer
    return g, m


def test_at_level_2_the_sniper_hits_the_stale_quote_in_the_same_round():
    for seed in range(1, 6):
        g, m = stale_setup(2)
        g.seed = seed
        g.advance()
        fast = [t for t in m.trades if t.phase == "B"]
        assert fast, "a quote left 3+ standard deviations stale must be picked off in the instant after the shock"
        assert all(t.me == "sell" and t.price == Fraction(15, 2) and t.stale for t in fast)
        assert m.pos < 0 and m.status_flags["shocked"]
        assert {g._bot_type(t.bot) for t in fast} == {"Prop"}


def test_no_fast_reaction_at_level_1_and_none_when_not_shocked():
    g, m = stale_setup(1)
    g.advance()
    assert all(t.phase == "A" for t in m.trades)                             # level 1 has no fast traders: the player can always react first
    g, m = stale_setup(2)
    g._plan.clear()
    g.advance()
    assert all(t.phase == "A" for t in m.trades)


def test_requoting_after_a_shock_stops_the_bleeding():
    g, m = stale_setup(2)
    g.advance()
    pos = m.pos
    g.set_quote("M1", 10.5, 11.5, 1)
    g.advance()
    assert not [t for t in m.trades if t.round == 2 and t.phase == "B"]
    assert not m.status_flags["shocked"]
    assert all(not t.stale for t in m.trades if t.round == 2)


def test_insiders_at_level_3_also_react_within_the_round():
    hits = 0
    for seed in range(1, 7):
        g, m = stale_setup(3)
        g.seed = seed
        g.advance()
        hits += any(t.phase == "B" and t.informed for t in m.trades)
    assert hits >= 3
