"""The two additive public-view fields the level 3-5 screens needed, and that they are only that: derived from numbers the engine already had."""

import pytest

from rates_trainer.episodes.api import Session
from rates_trainer.episodes.episode import PATHS, reference_decision
from rates_trainer.episodes.factors import FACTORS
from rates_trainer.episodes.serial import encode_decision


def _play(eid, seed):
    s = Session.start(eid, seed, reveal_inference=False)
    results = []
    while not s.done:
        d = encode_decision(reference_decision(s._ep, s._current()))
        results.append(s.submit(d))
    return s, results


@pytest.mark.parametrize("eid", ["mm.ep3_curve_book_ldi", "mm.ep4_products_overnight", "mm.ep5_information_views"])
def test_market_events_carry_the_par_change_by_tenor_consistent_with_the_factor_moves(eid):
    s, results = _play(eid, 1)
    seen = 0
    for r in results:
        for e in r["events"]:
            if e["type"] != "market":
                continue
            seen += 1
            assert [m["tenor"] for m in e["tenor_moves"]] == [2, 5, 10, 30]
            fm = {m["name"]: m["value"] for m in e["factor_moves"]}
            for m in e["tenor_moves"]:
                want = sum(FACTORS[k].loading(m["tenor"]) * v for k, v in fm.items() if FACTORS[k].is_curve)
                assert m["bp"] == pytest.approx(want)
            focus = next(m for m in e["tenor_moves"] if m["tenor"] == e["focus_tenor"]) if e["focus_tenor"] in (2, 5, 10, 30) else None
            if focus:
                assert focus["bp"] == pytest.approx(e["move_bp"])
    assert seen >= 4


def test_the_additive_event_field_changes_nothing_the_replay_depends_on():
    a, _ = _play("mm.ep3_curve_book_ldi", 2)
    b = Session.replay(a.record(), reveal_inference=False)
    assert b.record()["decisions"] == a.record()["decisions"]
    assert a.debrief(compare=False)["outcome"]["total"] == pytest.approx(b.debrief(compare=False)["outcome"]["total"])


def test_level_5_market_paths_carry_the_samples_behind_the_statistics_and_other_levels_have_none():
    s, _ = _play("mm.ep5_information_views", 1)
    mp = s.debrief(compare=True)["market_paths"]
    for k in ("yours", "reference"):
        xs = mp[k]["samples"]
        assert len(xs) == PATHS and all(isinstance(x, int) for x in xs)
        assert sum(xs) / len(xs) == pytest.approx(mp[k]["mean"], abs=1.0)           # whole-euro rounding only
        assert min(xs) <= mp[k]["p05"] <= mp[k]["p95"] <= max(xs)
    s3, _ = _play("mm.ep3_curve_book_ldi", 1)
    assert s3.debrief(compare=True)["market_paths"] is None


def test_the_live_desk_views_still_hide_what_they_hid():
    s, results = _play("mm.ep5_information_views", 1)
    blob = str(results)
    assert "p_informed" not in blob and "P(informed" not in blob
