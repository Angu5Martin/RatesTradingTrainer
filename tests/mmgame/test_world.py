"""The curated world-knowledge bank and the model of what everybody can know about one fact."""

import re
from fractions import Fraction

import pytest

from rates_trainer.mmgame.probability import EffectError
from rates_trainer.mmgame.world import AltResolution, Clue, WorldModel, bank_by_id, fmt_num, load_bank

BANK = load_bank()


def test_bank_size_and_variety():
    assert len(BANK) >= 480 and len([i for i in BANK if i.added == 2]) >= 380 and len([i for i in BANK if i.added == 1]) == 92
    assert len({i.id for i in BANK}) == len(BANK)
    assert {i.category for i in BANK} >= {"geography", "history", "science", "sport", "economics", "politics", "culture"}
    assert {i.difficulty for i in BANK} == {1, 2, 3}
    assert sum(1 for i in BANK if i.alt) >= 10
    assert len({i.question for i in BANK}) == len(BANK)


@pytest.mark.parametrize("item", BANK, ids=lambda i: i.id)
def test_every_item_is_complete_and_consistent(item):
    assert item.question.endswith("?") and len(item.question) > 15
    assert item.rule.strip() and item.source.strip() and item.as_of.strip()
    assert "http" not in item.source                                    # named references only: no invented links
    assert item.lo < item.hi and item.lo <= item.answer <= item.hi, "the public settlement range must contain the answer"
    assert item.spread > 0 and item.tick > 0
    assert 1 <= item.difficulty <= 3
    # the question and the public rule must not give the answer away
    shown = fmt_num(item.answer)
    if len(shown) >= 3:
        assert shown not in re.sub(r"[,]", "", item.question + " " + item.rule), "the answer is stated in the question or rule"
    if item.alt:
        assert item.alt["rule"].strip() and item.alt["answer"] != item.answer
        assert item.lo <= item.alt["answer"] <= item.hi, "the redefined answer must also sit inside the public range"
        assert abs(item.alt["answer"] - item.answer) <= abs(item.answer) * 2 + 5


def test_a_hand_checked_sample_of_answers():
    b = bank_by_id()
    for k, v in {"bastille": 1789, "gold_z": 79, "chess_squares": 64, "marathon": Fraction("42.195"), "everest": Fraction("8848.86"), "eur_dem": Fraction("1.95583"), "commons": 650,
                 "bones": 206, "rome": 1957, "mast_debt": 60, "light": Fraction("299.792458")}.items():
        assert b[k].answer == v, k
    assert b["rome"].alt["answer"] == 1958 and b["planets"].alt["answer"] == 9 and b["teeth"].alt["answer"] == 28


def test_belief_is_centred_on_the_crowd_not_the_truth_and_clues_truncate_it():
    it = bank_by_id()["bastille"]
    m = WorldModel(it, 1.0)
    mean0, sd0 = m.belief()
    assert abs(float(mean0) - (1789 + it.spread)) < 3 and 0.5 * it.spread < sd0 <= it.spread * 1.05
    Clue("ge", "1790").apply_world(m)
    mean1, sd1 = m.belief()
    assert mean1 > mean0 and sd1 < sd0 and m.bounds()[0] == 1790
    Clue("lt", "1800").apply_world(m)
    assert m.bounds() == (1790.0, 1800.0) and m.belief()[1] < sd1


def test_clue_must_inform_and_stay_consistent():
    m = WorldModel(bank_by_id()["bastille"], 0.0)
    with pytest.raises(EffectError):
        Clue("ge", "1500").apply_world(m)                                # below the public range: says nothing
    Clue("ge", "1700").apply_world(m)
    with pytest.raises(EffectError):
        Clue("ge", "1650").apply_world(m)
    with pytest.raises(EffectError):
        Clue("lt", "1650").apply_world(m)                                # would contradict an earlier clue


def test_alt_resolution_changes_only_the_definition():
    it = bank_by_id()["rome"]
    m = WorldModel(it, 0.5, -0.5)
    assert m.realise() == 1957 and "signed" in m.rule
    txt = m.apply(AltResolution())
    assert m.realise() == 1958 and "ENTERED INTO FORCE" in m.rule and txt.startswith("Resolution change") and "unchanged" in txt
    assert m.floor is None and m.ceil is None
    with pytest.raises(EffectError):
        m.apply(AltResolution())                                         # only once
    with pytest.raises(EffectError):
        WorldModel(bank_by_id()["bastille"], 0).apply(AltResolution())  # no alt for this item


def test_world_questions_do_not_leak_in_describe():
    m = WorldModel(bank_by_id()["gold_z"], 0.0)
    assert "79" not in " ".join(m.describe())


def test_fmt_num():
    assert fmt_num(Fraction("8848.86")) == "8848.86" and fmt_num(Fraction(1789)) == "1789" and fmt_num(Fraction("-273.15")) == "-273.15" and fmt_num(0) == "0"
