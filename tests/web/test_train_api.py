"""TRAIN over HTTP: the whole practice journey through the real question engine, what is and is not sent, reload safety and the attempt record."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rates_trainer.questions.model import ChoicePart
from rates_trainer.questions.registry import all_specs, generate
from rates_trainer.web.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RATES_TRAINER_HOME", str(tmp_path))
    return TestClient(create_app())


def ref(part) -> str:
    return chr(65 + part.correct) if isinstance(part, ChoicePart) else repr(part.answer)


def wrong(part) -> str:
    """A readable answer that is certainly not right: an implausible number, or a letter other than the correct one."""
    if isinstance(part, ChoicePart):
        return chr(65 + (part.correct + 1) % len(part.options))
    return "123456789"


def play(client, body, answer=ref):
    """Answer a whole practice session over HTTP with answer(part) -> raw; returns (id, results, states)."""
    st = client.post("/api/train/start", json=body).json()
    sid, results, states = st["id"], [], [st]
    while st["phase"] != "done":
        assert st["phase"] == "answering"
        q = generate(st["question"]["template_id"], int(st["question"]["id"].rpartition("#")[2]))
        part = q.parts[st["question"]["current"]["index"]]
        r = client.post(f"/api/train/{sid}/answer", json={"text": answer(part)})
        assert r.status_code == 200, r.text
        results.append(r.json()["result"])
        st = client.post(f"/api/train/{sid}/continue").json()
        states.append(st)
    return sid, results, states


def keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from keys(v)


def test_a_focused_session_runs_from_start_to_summary(client):
    sid, results, states = play(client, {"skills": ["swaps.dv01"], "count": 4, "seed": 5})
    assert results and all(r["correct"] for r in results)
    assert states[-1]["phase"] == "done" and states[-1]["question"] is None and states[-1]["parts_correct"] == len(results)
    s = client.get(f"/api/train/{sid}/summary").json()
    assert s["parts_total"] == s["parts_correct"] == len(results) and s["missed"] == [] and s["by_skill"][0]["skill"] == "swaps.dv01"


def test_answers_are_withheld_until_they_are_due(client):
    st = client.post("/api/train/start", json={"kind": "calculation", "count": 3, "seed": 2}).json()
    sid = st["id"]
    assert not ({"answer", "approx", "tol", "facts", "why", "correct_index", "expected", "result"} & set(keys(st)))
    assert st["question"]["solution"] is None and st["question"]["parts_done"] == []
    assert "seed" not in st["question"]                                    # only the id, as the terminal shows
    # a reload before answering is the same screen
    assert client.get(f"/api/train/{sid}").json() == st
    # check does not grade or record anything
    cur = st["question"]["current"]
    c = client.post(f"/api/train/{sid}/check", json={"text": "-225k" if cur["kind"] == "numeric" else "A"}).json()
    assert c["ok"] and "read_as" in c
    assert client.get(f"/api/train/{sid}").json() == st


def test_the_next_part_waits_for_continue_and_a_reload_lands_on_the_result(client):
    sid = client.post("/api/train/start", json={"template_id": "basis.irs_vs_ois", "seed": 1}).json()["id"]     # a multi-part source
    q = generate("basis.irs_vs_ois", 1)
    r = client.post(f"/api/train/{sid}/answer", json={"text": ref(q.parts[0])})
    assert r.status_code == 200 and r.json()["result"]["correct"]
    st = r.json()["state"]
    assert st["phase"] == "feedback" and st["question"]["current"] is None                     # the next prompt is not in the response
    assert q.parts[1].prompt not in json.dumps(st)
    assert client.get(f"/api/train/{sid}").json() == st                                         # reload: same result, still not the next prompt
    assert client.post(f"/api/train/{sid}/answer", json={"text": "A"}).status_code == 409     # one answer per part
    nxt = client.post(f"/api/train/{sid}/continue").json()
    assert nxt["phase"] == "answering" and nxt["question"]["current"]["prompt"] == q.parts[1].prompt
    assert [d["prompt"] for d in nxt["question"]["parts_done"]] == [q.parts[0].prompt]
    assert client.post(f"/api/train/{sid}/continue").status_code == 409                         # nothing to continue past


def test_the_worked_solution_comes_with_the_last_part_only(client):
    sid = client.post("/api/train/start", json={"template_id": "basis.irs_vs_ois", "seed": 1}).json()["id"]
    q = generate("basis.irs_vs_ois", 1)
    for i, p in enumerate(q.parts):
        st = client.post(f"/api/train/{sid}/answer", json={"text": ref(p)}).json()["state"]
        assert (st["question"]["solution"] == q.solution) == (i == len(q.parts) - 1)
        if i < len(q.parts) - 1:
            client.post(f"/api/train/{sid}/continue")


def test_unreadable_input_is_refused_not_marked(client):
    sid = client.post("/api/train/start", json={"kind": "calculation", "count": 2, "seed": 1}).json()["id"]
    before = client.get(f"/api/train/{sid}").json()
    for junk in ("banana", "", "12 monkeys"):
        assert client.post(f"/api/train/{sid}/answer", json={"text": junk}).status_code == 400
        assert client.post(f"/api/train/{sid}/check", json={"text": junk}).json()["ok"] is False
    assert client.get(f"/api/train/{sid}").json() == before
    assert client.get("/api/train/history").json() == []                                       # nothing was recorded


def test_skip_marks_wrong_and_shows_the_expected_answer(client):
    sid = client.post("/api/train/start", json={"kind": "calculation", "count": 1, "seed": 1}).json()["id"]
    r = client.post(f"/api/train/{sid}/answer", json={"skip": True}).json()
    assert r["result"]["status"] == "skipped" and r["result"]["correct"] is False and r["result"]["expected"]
    s = client.post(f"/api/train/{sid}/finish").json()
    assert s["parts_total"] == 1 and s["parts_correct"] == 0 and len(s["missed"]) == 1


def test_replaying_missed_questions_regenerates_exactly_those(client):
    sid, _, _ = play(client, {"skills": ["swaps.dv01"], "kind": "calculation", "count": 2, "seed": 9}, answer=wrong)
    missed = client.get(f"/api/train/{sid}/summary").json()["missed"]
    assert missed
    st = client.post("/api/train/start", json={"ids": missed}).json()
    assert st["mode"] == "replay" and st["total"] == len(missed) and st["question"]["id"] == missed[0]


def test_bad_requests_are_400_and_unknown_sessions_404(client):
    for body in ({"tracks": ["nope"]}, {"kind": "speed"}, {"count": 0}, {"template_id": "no.such"}, {"ids": ["no.such#1"]}, {"skills": ["swaps.dv01"], "difficulty": 3}):
        assert client.post("/api/train/start", json=body).status_code == 400, body
    for path in ("", "/summary"):
        assert client.get(f"/api/train/zzz{path}").status_code == 404
    assert client.post("/api/train/zzz/answer", json={"text": "A"}).status_code == 404


def test_attempts_are_recorded_for_review_as_they_happen(client, tmp_path):
    st = client.post("/api/train/start", json={"skills": ["swaps.dv01"], "count": 3, "seed": 5}).json()
    sid = st["id"]
    assert client.get("/api/train/history").json() == []                                   # nothing answered, nothing to keep
    q = generate(st["question"]["template_id"], int(st["question"]["id"].rpartition("#")[2]))
    client.post(f"/api/train/{sid}/answer", json={"text": ref(q.parts[0])})
    files = list(Path(tmp_path, "practice").glob("*.json"))
    assert len(files) == 1                                                                  # written at the first graded part, not only at the end
    rec = json.loads(files[0].read_text())
    assert rec["id"] == sid and rec["finished"] is False and rec["questions"][0]["parts"][0]["submitted"] == ref(q.parts[0])
    assert {"skill", "track", "difficulty", "kind", "template_id", "seed"} <= set(rec["questions"][0])
    client.post(f"/api/train/{sid}/finish")
    h = client.get("/api/train/history").json()
    assert len(h) == 1 and h[0]["id"] == sid and h[0]["ended_early"] is True and h[0]["parts_total"] == 1
    assert len(list(Path(tmp_path, "practice").glob("*.json"))) == 1                       # rewritten, not duplicated


def test_a_finished_session_is_recorded_as_finished_and_live_desk_history_is_untouched(client, tmp_path):
    play(client, {"skills": ["swaps.dv01"], "kind": "conceptual", "count": 2, "seed": 1})
    h = client.get("/api/train/history").json()
    assert len(h) == 1 and h[0]["finished"] is True and h[0]["ended_early"] is False
    assert client.get("/api/review/sessions").json() == []
    assert not list(Path(tmp_path).glob("episodes/*"))


def test_the_catalogue_endpoint_carries_the_new_fields_and_the_old_ones(client):
    t = client.get("/api/catalogue").json()["train"]
    s = t["tracks"][1]["skills"][0]
    assert {"id", "title", "planned", "prereqs", "sources", "curated", "difficulties"} <= set(s) and {"kinds", "items"} <= set(s)
    assert t["sources"] == len(all_specs())


NEW_STANDALONE = ["risk.key_rate", "mm.requote_loop", "mm.cross_product_hedging", "mm.views_and_events", "math.bootstrapping", "math.interpolation", "bonds.money_market",
                  "risk.convexity", "curve.butterfly", "portfolio.aggregation", "portfolio.scenarios"]


@pytest.mark.parametrize("skill", NEW_STANDALONE)
def test_the_newly_covered_skills_run_start_to_summary_over_http_and_record_in_the_test_home(client, tmp_path, skill):
    """Every skill that used to be planned or episode-only is a normal TRAIN selection now: start, answer each part, continue, summary, one record."""
    sid, results, states = play(client, {"skills": [skill], "count": 6, "seed": 3})
    assert results and all(r["correct"] for r in results)
    assert states[-1]["phase"] == "done" and states[-1]["parts_correct"] == len(results)
    s = client.get(f"/api/train/{sid}/summary").json()
    assert s["missed"] == [] and {x["skill"] for x in s["by_skill"]} == {skill}
    files = list(Path(tmp_path, "practice").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["id"] == sid          # recorded in the private test home and nowhere else


def test_the_new_sources_honour_the_kind_and_difficulty_filters_over_http(client):
    def part_kinds(body):
        st, seen = client.post("/api/train/start", json=body).json(), set()
        while st["phase"] != "done":
            seen.add(st["question"]["current"]["kind"])
            q = generate(st["question"]["template_id"], int(st["question"]["id"].rpartition("#")[2]))
            client.post(f"/api/train/{st['id']}/answer", json={"text": ref(q.parts[st["question"]["current"]["index"]])})
            st = client.post(f"/api/train/{st['id']}/continue").json()
        return seen

    assert "numeric" in part_kinds({"skills": ["risk.key_rate"], "kind": "calculation", "count": 8, "seed": 1})      # a calculation has at least one number to work out
    assert part_kinds({"skills": ["mm.views_and_events"], "kind": "conceptual", "count": 8, "seed": 2}) == {"choice"}   # a conceptual question is only choices
    hard = client.post("/api/train/start", json={"skills": ["mm.requote_loop"], "difficulty": 3, "count": 4, "seed": 1}).json()
    assert hard["question"]["difficulty"] == 3 and hard["question"]["template_id"] == "mm.requote_sequence"


def test_a_new_numeric_source_refuses_an_unreadable_entry_without_marking_it(client, tmp_path):
    st = client.post("/api/train/start", json={"template_id": "risk.key_rate_read"}).json()
    sid = st["id"]
    assert st["question"]["current"]["kind"] == "numeric"
    r = client.post(f"/api/train/{sid}/answer", json={"text": "about two hundred"})
    assert r.status_code == 400
    assert client.get(f"/api/train/{sid}").json()["parts_answered"] == 0              # not marked, nothing recorded
    assert not list(Path(tmp_path, "practice").glob("*.json"))


def test_the_tests_run_against_a_private_data_home(client, tmp_path):
    from rates_trainer.web import store
    assert Path(store.home()).resolve() == Path(tmp_path).resolve()
