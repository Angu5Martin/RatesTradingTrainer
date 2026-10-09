"""QuestionSession: the public, plain-data surface of the question engine used by TRAIN.

It must expose the existing generation and grading unchanged (the terminal loop and QuestionSession give the same marks for the same answers), ask a
multi-part question one part at a time, and never put an answer, tolerance, option key, rationale or worked solution into a view before it is due.
"""

import json
import random
from collections import Counter

import pytest

from rates_trainer.curriculum.skills import SKILLS
from rates_trainer.questions.api import QuestionSession, catalogue
from rates_trainer.questions.model import ChoicePart, NumericPart
from rates_trainer.questions.practice import KINDS, kind_of, source_kinds
from rates_trainer.questions.registry import all_specs, generate
from rates_trainer.session import build_queue, plan_queue, run_session

FORBIDDEN_KEYS = {"answer", "approx", "tol", "tolerance", "correct_index", "facts", "bare_scale_answer", "sign_hint", "why", "solution", "expected", "detail",
                  "result", "feedback", "submitted", "question_correct"}


def reference(part) -> str:
    return chr(65 + part.correct) if isinstance(part, ChoicePart) else repr(part.answer)


def keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from keys(v)


def drive(sess, answer):
    """Answer every part with answer(part) -> raw; returns the per-part result dicts."""
    out = []
    while not sess.done:
        v = sess.question_view()
        q = sess._q(sess._qi)
        part = q.parts[v["current"]["index"]]
        out.append(sess.submit(answer(part)))
        sess.next()
    return out


# --------------------------------------------------------------------------------------------------------------------- nothing is hidden wrongly

def test_a_view_before_the_answer_contains_no_answer_material():
    """Over every source and several seeds: at every step the view has no answer keys, and no answer text that is not already in the question itself."""
    n = 0
    for spec in all_specs():
        for seed in (0, 1, 2):
            s = QuestionSession.single(spec.id, seed)
            q = s._q(0)
            public = q.stem + " ".join(p.prompt + " ".join(getattr(p, "options", [])) + getattr(p, "note", "") for p in q.parts)
            while not s.done:
                st = s.state()
                v = st["question"]
                if st["phase"] == "answering":
                    cur = v["current"]
                    assert not (set(keys(cur)) & FORBIDDEN_KEYS), (spec.id, set(keys(cur)) & FORBIDDEN_KEYS)
                    # earlier parts' results were given and are shown; but the part being asked, later parts and the solution are not in the view
                    blob = json.dumps(cur) + json.dumps(v["solution"])
                    assert v["solution"] is None
                    part = q.parts[cur["index"]]
                    for secret in ([part.display()] if isinstance(part, NumericPart) else []) + ([part.why] if isinstance(part, ChoicePart) and part.why else []):
                        if secret not in public:
                            assert secret not in blob, (spec.id, seed, secret)
                    assert len(v["parts_done"]) == cur["index"]                       # a later part's prompt is not shown early
                    s.submit(reference(part))
                    n += 1
                s.next()
    assert n > 300


def test_the_worked_solution_appears_with_the_last_result_only():
    for spec in all_specs():
        s = QuestionSession.single(spec.id, 1)
        q = s._q(0)
        for i, part in enumerate(q.parts):
            assert s.question_view()["solution"] is None
            s.submit(reference(part))
            v = s.question_view()
            assert (v["solution"] == q.solution) == (i == len(q.parts) - 1), spec.id
            assert v["current"] is None
            s.next()


def test_a_numeric_views_tolerance_and_answer_never_travel():
    spec = next(s for s in all_specs() if not s.curated and kind_of(generate(s.id, 1)) == "calculation")
    s = QuestionSession.single(spec.id, 1)
    q = s._q(0)
    blob = json.dumps(s.state())
    num = next(p for p in q.parts if isinstance(p, NumericPart))
    assert repr(num.answer) not in blob and "tol" not in blob and "approx" not in blob


# --------------------------------------------------------------------------------------------------------------------- grading is the existing grading

def test_every_source_is_solved_by_its_own_reference_answers():
    for spec in all_specs():
        for seed in (0, 1, 2, 3):
            s = QuestionSession.single(spec.id, seed)
            res = drive(s, reference)
            assert res and all(r["correct"] for r in res), (spec.id, seed, [r["feedback"] for r in res])
            assert s.summary()["questions"][0]["correct"] is True


def test_marks_and_feedback_equal_part_grade_for_right_wrong_and_slipped_answers():
    specs = [s for s in all_specs() if kind_of(generate(s.id, 1)) == "calculation"][:12]
    checked = 0
    for spec in specs:
        q = generate(spec.id, 1)
        for part in q.parts:
            if not isinstance(part, NumericPart) or part.answer == 0:
                continue
            for raw in (repr(part.answer), repr(-part.answer), repr(part.answer * 1000), repr(part.answer / 1000), "0.5", "17"):
                s = QuestionSession.single(spec.id, 1)
                s._qi, s._phase = 0, "answering"
                s._done[0] = []                                   # position at this part by answering the earlier ones with reference answers
                for earlier in q.parts[:part_index(q, part)]:
                    s.submit(reference(earlier)); s.next()
                r = s.submit(raw)
                g = part.grade(raw)
                assert (r["correct"], r["feedback"], r["expected"], r["detail"]) == (g.correct, g.feedback, g.expected, g.detail)
                checked += 1
    assert checked > 60


def part_index(q, part):
    return next(i for i, p in enumerate(q.parts) if p is part)


def test_unreadable_input_is_not_marked_and_changes_nothing():
    spec = next(s for s in all_specs() if kind_of(generate(s.id, 1)) == "calculation" and isinstance(generate(s.id, 1).parts[0], NumericPart))
    s = QuestionSession.single(spec.id, 1)
    before = json.dumps(s.state())
    for junk in ("banana", "", "12 monkeys"):
        with pytest.raises(ValueError):
            s.submit(junk)
        assert not s.check(junk)["ok"]
    assert json.dumps(s.state()) == before and s.summary()["parts_total"] == 0
    ch = next(s for s in all_specs() if s.curated)
    c = QuestionSession.single(ch.id, 1)
    with pytest.raises(ValueError, match="letter"):
        c.submit("Z")
    assert c.summary()["parts_total"] == 0


def test_check_reads_a_number_the_way_the_grader_does_and_grades_nothing():
    spec = next(s for s in all_specs() if isinstance(generate(s.id, 1).parts[0], NumericPart) and generate(s.id, 1).parts[0].unit == "EUR")
    s = QuestionSession.single(spec.id, 1)
    r = s.check("-225k")
    assert r == {"ok": True, "read_as": generate(spec.id, 1).parts[0].display(-225_000.0)}
    assert s.check("1.2m")["read_as"] == generate(spec.id, 1).parts[0].display(1_200_000.0)
    assert s.summary()["parts_total"] == 0


def test_skip_marks_wrong_and_shows_the_answer_like_the_terminal():
    spec = next(s for s in all_specs() if kind_of(generate(s.id, 1)) == "calculation")
    s = QuestionSession.single(spec.id, 1)
    q = generate(spec.id, 1)
    r = s.skip()
    assert r["status"] == "skipped" and not r["correct"] and r["expected"] == q.parts[0].display()


def test_session_totals_equal_the_terminal_loops_for_the_same_answers():
    specs = [s for s in all_specs() if s.skill.startswith(("swaps", "risk", "mm"))]
    plan = plan_queue(specs, 8, random.Random(3))
    qs = [generate(t, sd) for t, sd in plan]
    rng = random.Random(9)
    script = []                                                  # right, wrong or skip, per part, in order
    for q in qs:
        for p in q.parts:
            r = rng.random()
            wrong = chr(65 + (p.correct + 1) % len(p.options)) if isinstance(p, ChoicePart) else "123456789"
            script.append("skip" if r < .15 else reference(p) if r < .6 else wrong)
    it = iter(script)
    res = run_session(qs, ask=lambda _p: next(it), say=lambda _s: None)
    sess = QuestionSession(plan, "mixed", "x")
    for raw in script:
        sess.skip() if raw == "skip" else sess.submit(raw)
        sess.next()
    s = sess.summary()
    assert (s["parts_total"], s["parts_correct"]) == (res.parts_total, res.parts_correct)
    assert {k["skill"]: [k["correct"], k["total"]] for k in s["by_skill"]} == {k: v for k, v in res.by_skill.items()}
    assert s["missed"] == res.missed


# --------------------------------------------------------------------------------------------------------------------- order and gating

def test_a_multi_part_question_reveals_one_part_at_a_time_in_order():
    spec = next(s for s in all_specs() if len(generate(s.id, 1).parts) >= 4)
    q = generate(spec.id, 1)
    s = QuestionSession.single(spec.id, 1)
    for i, part in enumerate(q.parts):
        v = s.question_view()
        assert v["parts_total"] == len(q.parts) and v["current"]["index"] == i and v["current"]["prompt"] == part.prompt
        assert [d["prompt"] for d in v["parts_done"]] == [p.prompt for p in q.parts[:i]]
        s.submit(reference(part))
        s.next() if i < len(q.parts) - 1 else None
    assert s.state()["phase"] == "feedback"


def test_nothing_moves_without_its_step():
    spec = next(s for s in all_specs() if s.curated)
    s = QuestionSession.single(spec.id, 1)
    with pytest.raises(PermissionError):
        s.next()                                                  # nothing has been answered
    s.submit("A")
    with pytest.raises(PermissionError):
        s.submit("A")                                             # one answer per part
    with pytest.raises(PermissionError):
        s.check("A")
    s.next()
    assert s.done                                                 # the one question is over
    s = QuestionSession.start(skills=["swaps.dv01"], kind="conceptual", count=2, seed=1)
    s.finish()
    assert s.done
    with pytest.raises(PermissionError):
        s.submit("A")
    assert s.state()["question"] is None


# --------------------------------------------------------------------------------------------------------------------- modes and selection

def test_focused_and_mixed_modes_follow_the_selection():
    f = QuestionSession.start(skills=["swaps.dv01"], count=5, seed=1)
    assert f.mode == "focused" and f.label == SKILLS["swaps.dv01"].title
    assert {SKILLS and generate(t, sd).skill for t, sd in f.plan} == {"swaps.dv01"}
    t = QuestionSession.start(tracks=["futures"], count=6, seed=1)
    assert t.mode == "focused" and {generate(a, b).skill.split(".")[0] for a, b in t.plan} == {"futures"}
    m = QuestionSession.start(tracks=["futures", "curve"], count=8, seed=1)
    assert m.mode == "mixed" and {generate(a, b).skill.split(".")[0] for a, b in m.plan} <= {"futures", "curve"}
    assert QuestionSession.start(count=4, seed=1).mode == "mixed"


def test_difficulty_and_kind_filters_use_the_catalogues_classification():
    d3 = QuestionSession.start(difficulty=3, count=6, seed=2)
    assert {generate(a, b).difficulty for a, b in d3.plan} == {3}
    c = QuestionSession.start(kind="calculation", count=8, seed=2)
    assert all(kind_of(generate(a, b)) == "calculation" for a, b in c.plan)
    k = QuestionSession.start(kind="conceptual", count=8, seed=2)
    assert all(kind_of(generate(a, b)) == "conceptual" for a, b in k.plan)
    low = QuestionSession.start(max_difficulty=1, count=6, seed=2)
    assert {generate(a, b).difficulty for a, b in low.plan} == {1}


def test_bad_selections_are_refused_not_widened():
    for kw in ({"tracks": ["nonsense"]}, {"skills": ["nonsense"]}, {"kind": "speed"}, {"count": 0}, {"count": 500}, {"skills": ["math.bootstrapping"]},
               {"skills": ["swaps.dv01"], "difficulty": 3}):
        with pytest.raises(ValueError):
            QuestionSession.start(**kw)


def test_the_same_seed_gives_the_same_session_and_curated_questions_are_not_repeated():
    a = QuestionSession.start(tracks=["swaps"], count=10, seed=7)
    b = QuestionSession.start(tracks=["swaps"], count=10, seed=7)
    assert a.plan == b.plan and [a._q(i).stem for i in range(a.total)] == [b._q(i).stem for i in range(b.total)]
    conceptual = QuestionSession.start(skills=["swaps.dv01"], kind="conceptual", count=10, seed=1)
    ids = [t for t, _ in conceptual.plan]
    assert len(ids) == len(set(ids)) == 2                         # two curated questions exist for this skill: each once
    assert conceptual.selection["pool"] == 2


def test_the_plan_is_exactly_what_the_terminal_would_build():
    specs = [s for s in all_specs() if s.skill.startswith("curve")]
    plan = plan_queue(specs, 7, random.Random(4))
    assert [q.id for q in build_queue(specs, 7, random.Random(4))] == [f"{t}#{s}" for t, s in plan]


def test_single_question_by_source_and_exact_replay_by_id():
    spec = next(s for s in all_specs() if not s.curated)
    s = QuestionSession.single(spec.id, 42)
    assert s.mode == "single" and s.question_view()["id"] == f"{spec.id}#42"
    r = QuestionSession.replay([f"{spec.id}#42"])
    assert r.question_view()["stem"] == s.question_view()["stem"]
    with pytest.raises(KeyError):
        QuestionSession.single("no.such.source")
    with pytest.raises(KeyError):
        QuestionSession.replay(["no.such.source#1"])


# --------------------------------------------------------------------------------------------------------------------- record and catalogue

def test_the_record_keeps_what_review_needs_and_survives_ending_early():
    s = QuestionSession.start(skills=["mm.client_trade"], count=3, seed=3)
    q = s._q(0)
    s.submit(reference(q.parts[0]))
    s.next()
    s.skip()
    s.finish()
    rec = s.record("abc")
    json.dumps(rec)                                              # plain
    assert rec["format"] == "rates-trainer-practice" and rec["id"] == "abc" and rec["ended_early"] and not rec["finished"]
    one = rec["questions"][0]
    assert {"id", "template_id", "seed", "skill", "track", "difficulty", "kind", "parts_total", "parts"} <= set(one)
    assert one["parts"][0]["submitted"] == reference(q.parts[0]) and one["parts"][0]["correct"] is True and one["parts"][0]["at"]
    assert one["parts"][1]["skipped"] is True and one["parts"][1]["submitted"] == ""
    assert rec["summary"]["parts_total"] == 2 and rec["summary"]["parts_correct"] == 1
    assert one["id"] in rec["summary"]["missed"]


def test_catalogue_items_cover_every_source_and_classify_each_once():
    c = catalogue()
    items = [i for t in c["tracks"] for s in t["skills"] for i in s["items"]]
    assert len(items) == c["sources"] == len(all_specs())
    assert Counter(i["kind"] for i in items) == Counter(source_kinds().values())
    assert set(source_kinds().values()) <= set(KINDS)
    for t in c["tracks"]:
        for s in t["skills"]:
            assert sum(s["kinds"].values()) == s["sources"] == len(s["items"])
    assert all(i["kind"] == "conceptual" for i in items if i["curated"])
