"""The probability engine: exact distributions, resolution, and the three kinds of effect with their distinct semantics."""

import copy
import itertools
import math
from fractions import Fraction

import pytest

from rates_trainer.mmgame.probability import (ALL_CARDS, AddJokers, AddTrials, ChangeDraws, DeckExperiment, DiceExperiment, EffectError, LoadFace, RemoveCards, RemoveTrials, RestrictFaces,
                                              RevealCards, RevealClass, RevealTrials, SetAgg, SetPred, SetSides, SetSpecial, SetThreshold, Target, aggregate_values, build_deck, build_dice,
                                              mean, pick, try_apply, variance)
from rates_trainer.mmgame.rng import Stream


def tape(seed=1, n=16):
    return [Stream(seed, "t", i).u53() for i in range(n)]


def brute(faces_list, target):
    out = {}
    n = len(faces_list)
    for combo in itertools.product(*[sorted(f) for f in faces_list]):
        pr = math.prod((Fraction(faces_list[i][v], sum(faces_list[i].values())) for i, v in enumerate(combo)), start=Fraction(1))
        v = aggregate_values(list(combo), target)
        out[v] = out.get(v, 0) + pr
    return dict(sorted(out.items()))


TARGETS = [Target("sum"), Target("count", {"kind": "odd"}), Target("count", {"kind": "ge", "v": 4}), Target("count", {"kind": "prime"}), Target("max"), Target("min"), Target("top2"),
           Target("sum", None, {"op": "ge", "t": 10}), Target("count", {"kind": "even"}, {"op": "ge", "t": 2}), Target("max", None, {"op": "eq", "t": 6})]


@pytest.mark.parametrize("target", TARGETS, ids=lambda t: t.key()[:40])
@pytest.mark.parametrize("n,sides", [(1, 6), (2, 6), (3, 6), (3, 8)])
def test_dice_distribution_equals_brute_force(n, sides, target):
    e = build_dice("die", sides, n, tape())
    p = e.pmf(target)
    assert sum(p.values()) == 1
    assert p == brute([{f: 1 for f in range(1, sides + 1)}] * n, target)


def test_weighted_and_coin_distributions():
    e = build_dice("coin", 2, 6, tape(), {0: 1, 1: 2})
    t = Target("count", {"kind": "eq", "v": 1})
    p = e.pmf(t)
    assert p[6] == Fraction(2, 3) ** 6 and mean(p) == 4
    assert p == brute([{0: 1, 1: 2}] * 6, t)
    d = build_dice("die", 6, 2, tape())
    d.apply(LoadFace(6, 3))
    assert d.pmf(Target("sum")) == brute([{1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 3}] * 2, Target("sum"))


def test_known_values():
    e = build_dice("die", 6, 2, tape())
    p = e.pmf(Target("sum"))
    assert p[7] == Fraction(1, 6) and p[2] == Fraction(1, 36) and mean(p) == 7 and variance(p) == Fraction(35, 6)
    assert build_dice("die", 6, 3, tape()).pmf(Target("sum", None, {"op": "ge", "t": 11}))[100] == Fraction(1, 2)
    assert build_dice("die", 6, 4, tape()).pmf(Target("count", {"kind": "odd"}))[2] == Fraction(6, 16)


def test_deck_hypergeometric_equals_enumeration():
    order = Stream(3, "d").shuffle(ALL_CARDS)
    for pred in ({"kind": "suit", "v": "H"}, {"kind": "color", "v": "red"}, {"kind": "face"}, {"kind": "ace"}):
        e = build_deck(3, order)
        t = Target("count", pred)
        from rates_trainer.mmgame.probability import card_pred
        f = card_pred(pred)
        deck = [c for c in ALL_CARDS if not c.startswith("JK")]
        counts = {}
        for combo in itertools.combinations(deck, 3):
            k = sum(1 for c in combo if f(c))
            counts[k] = counts.get(k, 0) + 1
        total = sum(counts.values())
        assert e.pmf(t) == {k: Fraction(v, total) for k, v in sorted(counts.items())}


def test_quantile_pick_is_exact_and_weighted():
    w = {1: 1, 2: 1, 3: 2}
    top = (1 << 53) - 1
    assert pick(w, 0) == 1 and pick(w, top) == 3 and pick(w, (1 << 52)) == 3 and pick(w, (1 << 51)) == 2


@pytest.mark.parametrize("target", [Target("sum"), Target("count", {"kind": "odd"}), Target("max"), Target("sum", None, {"op": "ge", "t": 8})], ids=lambda t: t.agg + str(bool(t.event)))
def test_resolution_follows_the_distribution(target):
    """Rolling at resolution from many tapes reproduces the exact distribution (to sampling error): resolution and probability agree."""
    n_games = 4000
    counts = {}
    for i in range(n_games):
        e = build_dice("die", 6, 2 if target.agg != "count" else 4, [Stream(i, "x", j).u53() for j in range(16)])
        v = e.realise(target)
        counts[v] = counts.get(v, 0) + 1
    p = build_dice("die", 6, 2 if target.agg != "count" else 4, tape()).pmf(target)
    assert set(counts) <= set(p)
    for k, pr in p.items():
        assert abs(counts.get(k, 0) / n_games - float(pr)) < 0.03


def test_realise_is_deterministic_and_never_a_stored_number():
    a, b = build_dice("die", 6, 3, tape()), build_dice("die", 6, 3, tape())
    assert a.realise(Target("sum")) == b.realise(Target("sum"))
    assert "value" not in repr([t.__dict__ for t in a.trials]).replace("'value': None", "")      # nothing is rolled until it must be


def test_realised_outcome_respects_rules_in_force_at_resolution():
    for s in range(30):
        e = build_dice("die", 6, 3, [Stream(s, "q", i).u53() for i in range(16)])
        e.apply(RestrictFaces({"kind": "even"}))
        assert all(v % 2 == 0 for v in e.values())
        e.apply(RestrictFaces({"kind": "ge", "v": 4}))
        assert all(v in (4, 6) for v in e.values())


# --------------------------------------------------------------------------- effects: the three categories

def sig(e):
    return [(t.slot, t.state, dict(t.weights)) for t in e.trials]


def test_experiment_effects_change_unrolled_trials_only():
    e = build_dice("die", 6, 3, tape())
    e.apply(RevealTrials(1))                                   # trial 0 is now fixed
    fixed = e.trials[0].value
    e.apply(RestrictFaces({"kind": "even"}))
    assert e.trials[0].value == fixed and e.trials[0].state == "revealed"
    assert all(t.weights == {2: 1, 4: 1, 6: 1} for t in e.trials[1:])
    e.apply(SetSides(8))
    assert e.trials[1].weights == {f: 1 for f in range(1, 9)} and e.trials[0].value == fixed
    e.apply(AddTrials(2))
    assert len(e.trials) == 5 and e.trials[4].weights == {f: 1 for f in range(1, 9)}
    e.apply(RemoveTrials(1))
    assert len(e.trials) == 4
    with pytest.raises(EffectError):
        e.apply(RemoveTrials(9))


def test_restrict_that_removes_nothing_or_everything_is_refused():
    e = build_dice("die", 6, 2, tape())
    with pytest.raises(EffectError):
        e.apply(RestrictFaces({"kind": "ge", "v": 1}))
    with pytest.raises(EffectError):
        e.apply(RestrictFaces({"kind": "ge", "v": 9}))
    assert all(t.weights == {f: 1 for f in range(1, 7)} for t in e.trials)         # a refused effect changes nothing


def test_information_leaves_experiment_and_target_unchanged_and_is_true():
    for seed in range(25):
        e = build_dice("die", 6, 3, [Stream(seed, "i", j).u53() for j in range(16)])
        t = Target("sum")
        truth_before = e.values()
        txt = e.apply(RevealTrials(1))
        assert txt.startswith("Information") and "Nothing else has changed" in txt
        assert e.values() == truth_before                                           # revealing does not alter the outcome: it was already determined by the tape
        e2 = build_dice("die", 6, 3, [Stream(seed, "i", j).u53() for j in range(16)])
        e2.apply(RevealClass("parity"))
        v0 = e2.trials[0].value
        assert set(e2.trials[0].weights) == {f for f in range(1, 7) if f % 2 == v0 % 2}       # the announced class is TRUE of the hidden value
        assert e2.trials[0].state == "rolled" and sum(1 for x in e2.trials if x.state == "pending") == 2
        e3 = build_dice("die", 6, 3, [Stream(seed, "i", j).u53() for j in range(16)])
        e3.apply(RevealClass("half"))
        assert e3.trials[0].value in e3.trials[0].weights


def test_rolled_trial_is_not_changed_by_later_rule_changes():
    e = build_dice("die", 6, 2, tape(5))
    e.apply(RevealClass("parity"))
    held = dict(e.trials[0].weights)
    e.apply(RestrictFaces({"kind": "ge", "v": 5}))
    assert e.trials[0].weights == held and e.trials[1].weights == {5: 1, 6: 1}


def test_information_posterior_equals_conditioning():
    """After 'die 1 is odd', the distribution of the sum is the unconditional one restricted to die 1 odd (exact)."""
    e = build_dice("die", 6, 2, tape(9))
    e.apply(RevealClass("parity"))
    odd = e.trials[0].weights == {1: 1, 3: 1, 5: 1}
    faces = [f for f in range(1, 7) if (f % 2 == 1) == odd]
    assert e.pmf(Target("sum")) == brute([{f: 1 for f in faces}, {f: 1 for f in range(1, 7)}], Target("sum"))


def test_resolution_effects_change_target_not_dice():
    e = build_dice("die", 6, 4, tape())
    t = Target("count", {"kind": "ge", "v": 5}, {"op": "ge", "t": 2})
    s0 = sig(e)
    t2, txt = SetThreshold(1).apply_target(t, e)
    assert t2.event["t"] == 1 and sig(e) == s0 and "Resolution change" in txt and "unchanged" in txt
    t3, _ = SetPred({"kind": "odd"}).apply_target(Target("count", {"kind": "even"}), e)
    assert t3.pred == {"kind": "odd"} and sig(e) == s0
    t4, _ = SetAgg("top2").apply_target(Target("sum"), e)
    assert t4.agg == "top2" and e.pmf(t4) == brute([{f: 1 for f in range(1, 7)}] * 4, Target("top2"))
    with pytest.raises(EffectError):
        SetAgg("top2").apply_target(Target("sum"), build_dice("die", 6, 2, tape()))
    with pytest.raises(EffectError):
        SetThreshold(3).apply_target(Target("sum"), e)


def test_experiment_effect_does_not_touch_the_target():
    e = build_dice("die", 6, 3, tape())
    t = Target("count", {"kind": "odd"}, {"op": "ge", "t": 2})
    out = try_apply(e, t, RestrictFaces({"kind": "even"}))
    assert out is None                                                           # all even: odd count is certainly 0, degenerate: refused
    e2, t2 = try_apply(e, t, AddTrials(1))
    assert t2 == t and len(e2.trials) == 4 and len(e.trials) == 3                # worked on a copy


def test_try_apply_refuses_degenerate_and_wrong_kind():
    e = build_dice("die", 6, 2, tape())
    assert try_apply(e, Target("sum"), RemoveCards({"kind": "face"})) is None
    d = build_deck(3, Stream(1, "d").shuffle(ALL_CARDS))
    assert try_apply(d, Target("count", {"kind": "suit", "v": "H"}), RestrictFaces({"kind": "even"})) is None


def test_deck_effects():
    order = Stream(2, "deck").shuffle(ALL_CARDS)
    d = build_deck(5, order)
    t = Target("count", {"kind": "suit", "v": "H"})
    base = mean(d.pmf(t))
    assert base == Fraction(5 * 13, 52)
    d.apply(RemoveCards({"kind": "color", "v": "red"}))
    assert d.pmf(t) == {0: Fraction(1)}
    d = build_deck(5, order)
    d.apply(AddJokers(2))
    assert mean(d.pmf(t)) == Fraction(5 * 13, 54)
    d.apply(ChangeDraws(2))
    assert d.draws == 7 and mean(d.pmf(t)) == Fraction(7 * 13, 54)
    with pytest.raises(EffectError):
        d.apply(ChangeDraws(100))
    d2 = build_deck(5, order)
    first = d2.active()[:2]
    d2.apply(RevealCards(2))
    assert d2.seen == first and d2.left() == 3
    k = sum(1 for c in first if c.endswith("H"))
    assert min(d2.pmf(t)) >= k                                                  # revealed hearts count towards the answer
    real = d2.realise(t)
    assert real >= k and real == sum(1 for c in d2.values() if c.endswith("H")) and len(d2.values()) == 5
    t2, _ = SetSpecial({"kind": "color", "v": "red"}).apply_target(t, d2)
    assert t2.pred == {"kind": "color", "v": "red"}


def test_reveal_cards_information_is_consistent_with_resolution():
    for seed in range(20):
        d = build_deck(5, Stream(seed, "rc").shuffle(ALL_CARDS))
        t = Target("count", {"kind": "face"})
        final_before = d.realise(t)
        d.apply(RevealCards(2))
        assert d.realise(t) == final_before                                       # revealing does not change the outcome


def test_top2_distribution_with_many_dice_is_exact_and_fast():
    from rates_trainer.mmgame.probability import Target as T
    e = build_dice("die", 12, 9, tape())
    p = e.pmf(T("top2"))
    assert sum(p.values()) == 1 and max(p) == 24 and min(p) == 2
    small = build_dice("die", 6, 5, tape())
    assert small.pmf(T("top2")) == brute([{f: 1 for f in range(1, 7)}] * 5, T("top2"))
