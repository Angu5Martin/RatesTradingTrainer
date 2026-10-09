"""The local HTTP layer and the live desk's information rules, against the real episode machinery (no mock engine).

A twin in-process Session with the same seed supplies the reference decisions that are POSTed to the server, so the whole loop
start -> observe -> commit -> result -> continue -> ... -> debrief runs through HTTP exactly as the browser drives it.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rates_trainer.episodes.api import Session, episode_for_level
from rates_trainer.episodes.episode import reference_decision
from rates_trainer.episodes.serial import encode_decision
from rates_trainer.questions.api import catalogue
from rates_trainer.web import store
from rates_trainer.web.app import create_app

HIDDEN_KEYS = {"informed", "posterior", "signal_right", "truth", "z", "uniform", "uniforms", "seed", "market_seed", "answer", "ctx", "lean",
               "leans", "toxicity", "evidence_vs_truth", "view_truth", "record"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RATES_TRAINER_HOME", str(tmp_path))
    return TestClient(create_app())


def _keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _keys(v)


def _play(client, level, seed, stop_before_continue=False):
    """Drive a whole episode over HTTP with the reference policy; returns (id, states, results)."""
    st = client.post("/api/desk/start", json={"level": level, "seed": seed}).json()
    twin = Session.start(episode_for_level(level, seed), seed, reveal_inference=False)
    states, results = [st], []
    while st["phase"] == "awaiting":
        dec = encode_decision(reference_decision(twin._ep, twin._current()))
        twin.submit(dec)
        r = client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec})
        assert r.status_code == 200, r.text
        body = r.json()
        results.append(body["result"])
        assert body["state"]["phase"] == "settled" and body["state"]["observation"] is None
        if stop_before_continue and twin.done:
            return st["id"], states, results
        st = client.post(f"/api/desk/{st['id']}/continue").json()
        states.append(st)
    return st["id"], states, results


@pytest.mark.parametrize("level", [1, 2])
def test_a_whole_level_runs_over_http(client, level):
    sid, states, results = _play(client, level, 3)
    assert states[-1]["phase"] == "done" and states[-1]["observation"] is None and states[-1]["pending"] is None
    assert all(r["assessment"] is None or "rating" in r["assessment"] for r in results)
    d = client.get(f"/api/desk/{sid}/debrief").json()
    assert {"decisions", "outcome", "luck", "clients", "counterfactuals"} <= set(d) and d["counterfactuals"] is None
    full = client.get(f"/api/desk/{sid}/debrief", params={"compare": "true"}).json()
    assert full["counterfactuals"]["policies"] and full["luck"] == d["luck"]
    rec = client.get(f"/api/desk/{sid}/record").json()
    assert rec["complete"] and Session.replay(rec).done


def test_the_next_observation_is_not_available_until_continue(client):
    st = client.post("/api/desk/start", json={"level": 1, "seed": 3}).json()
    twin = Session.start(episode_for_level(1, 3), 3)
    dec = encode_decision(reference_decision(twin._ep, twin._current()))
    r = client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec}).json()
    s = client.get(f"/api/desk/{st['id']}").json()                       # a reload after the commit
    assert s["phase"] == "settled" and s["observation"] is None and s["pending"]["result"] == r["result"]
    assert s["pending"]["observation"]["kind"] == "quote"                # the state the decision was taken in, not the next one
    assert client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec}).status_code == 409    # no second commit
    assert client.post(f"/api/desk/{st['id']}/parse", json={"text": "none"}).status_code == 409
    nxt = client.post(f"/api/desk/{st['id']}/continue").json()
    assert nxt["phase"] == "awaiting" and nxt["observation"]["episode"]["round"] >= 0 and nxt["pending"] is None
    assert client.post(f"/api/desk/{st['id']}/continue").status_code == 409


def test_debrief_and_record_are_closed_until_the_last_result_has_been_continued(client):
    sid, _, _ = _play(client, 1, 3, stop_before_continue=True)
    for path in ("debrief", "record"):
        assert client.get(f"/api/desk/{sid}/{path}").status_code == 409
    client.post(f"/api/desk/{sid}/continue")
    assert client.get(f"/api/desk/{sid}/debrief").status_code == 200 and client.get(f"/api/desk/{sid}/record").status_code == 200


def test_the_record_with_its_seeds_is_never_in_a_live_response(client):
    sid, states, results = _play(client, 2, 4)
    for payload in (*states, *results):
        assert not (set(_keys(payload)) & HIDDEN_KEYS)
    assert "seed" not in json.dumps(states).lower().replace("seed_", "")


def test_parse_endpoint_resolves_macros_and_reports_errors_without_committing(client):
    st = client.post("/api/desk/start", json={"level": 1, "seed": 3}).json()
    sid = st["id"]
    bad = client.post(f"/api/desk/{sid}/parse", json={"text": "3.32 3.30"}).json()
    assert bad["ok"] is False and "offer" in bad["error"]
    ok = client.post(f"/api/desk/{sid}/parse", json={"text": "3.30 3.34"}).json()
    assert ok["ok"] and ok["decision"] == {"type": "quote", "bid": 0.033, "offer": 0.0334}
    assert client.get(f"/api/desk/{sid}").json()["observation"]["episode"]["round"] == 0       # still waiting
    # a wrong kind of decision, and unreadable input, are refused without moving the episode
    assert client.post(f"/api/desk/{sid}/submit", json={"decision": {"type": "rfq", "level": None}}).status_code == 400
    assert client.post(f"/api/desk/{sid}/submit", json={"text": "abc"}).status_code == 400
    assert client.get(f"/api/desk/{sid}").json()["phase"] == "awaiting"
    assert client.post(f"/api/desk/{sid}/submit", json={"decision": ok["decision"]}).status_code == 200


def test_a_hedge_macro_is_resolved_by_the_engine_into_explicit_legs(client):
    st = client.post("/api/desk/start", json={"level": 2, "seed": 3}).json()
    twin = Session.start(episode_for_level(2, 3), 3, reveal_inference=False)
    while st["phase"] == "awaiting" and st["observation"]["kind"] != "hedge":
        dec = encode_decision(reference_decision(twin._ep, twin._current()))
        twin.submit(dec)
        client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec})
        st = client.post(f"/api/desk/{st['id']}/continue").json()
    assert st["observation"]["kind"] == "hedge"
    r = client.post(f"/api/desk/{st['id']}/parse", json={"text": "100%"}).json()
    assert r["ok"] and r["decision"]["type"] == "hedge" and r["decision"]["trades"] and r["decision"]["trades"][0]["kind"] == "swap"
    none = client.post(f"/api/desk/{st['id']}/parse", json={"text": "none"}).json()
    assert none["decision"]["trades"] == []
    assert client.post(f"/api/desk/{st['id']}/parse", json={"text": "sell 300 fgbl"}).json()["ok"] is False      # no futures on this desk


def test_unknown_session_and_bad_level(client):
    assert client.get("/api/desk/nope").status_code == 404
    assert client.post("/api/desk/start", json={"level": 9}).status_code == 400


def test_finished_episodes_are_saved_for_review(client, tmp_path):
    assert client.get("/api/review/sessions").json() == []
    sid, _, _ = _play(client, 1, 3)
    listed = client.get("/api/review/sessions").json()
    assert len(listed) == 1 and listed[0]["id"] == sid and listed[0]["level"] == 1 and set(listed[0]["ratings"]) == {"sound", "defensible", "poor", "error"}
    f = next(Path(tmp_path, "episodes").glob("*.json"))
    j = json.loads(f.read_text())
    assert {"record", "transcript", "summary", "debrief"} <= set(j) and j["record"]["complete"]
    assert Session.replay(j["record"]).done and len(j["transcript"]) == len(j["record"]["decisions"])
    assert store.list_episodes()[0]["id"] == sid


def test_unfinished_sessions_can_be_listed_for_resume(client):
    st = client.post("/api/desk/start", json={"level": 2, "seed": 1}).json()
    live = client.get("/api/desk").json()
    assert [d["id"] for d in live] == [st["id"]] and live[0]["episode"]["level"] == 2


def test_listing_identifies_sessions_without_revealing_the_seed(client):
    a = client.post("/api/desk/start", json={"level": 2, "seed": 1}).json()
    b = client.post("/api/desk/start", json={"level": 1, "seed": 2}).json()
    live = client.get("/api/desk").json()
    assert [d["id"] for d in live] == [b["id"], a["id"]]                       # newest first
    assert {"id", "phase", "episode", "started", "decisions", "in_history"} <= set(live[0])
    assert live[0]["phase"] == "awaiting" and live[0]["decisions"] == 0 and live[0]["in_history"] is False
    assert not (set(_keys(live)) & HIDDEN_KEYS)


def test_discarding_an_unfinished_session_removes_it_for_good(client, tmp_path):
    st = client.post("/api/desk/start", json={"level": 2, "seed": 1}).json()
    keep = client.post("/api/desk/start", json={"level": 2, "seed": 2}).json()
    assert client.delete(f"/api/desk/{st['id']}").json() == {"deleted": st["id"]}
    assert [d["id"] for d in client.get("/api/desk").json()] == [keep["id"]]
    assert client.get(f"/api/desk/{st['id']}").status_code == 404               # it cannot be reopened, resumed, committed or continued
    assert client.post(f"/api/desk/{st['id']}/continue").status_code == 404
    assert client.get(f"/api/desk/{st['id']}?transcript=true").status_code == 404
    assert client.post(f"/api/desk/{st['id']}/submit", json={"decision": {"type": "rfq", "level": None}}).status_code == 404
    assert client.delete(f"/api/desk/{st['id']}").status_code == 404            # deleting twice is an error, not a silent success
    assert client.get(f"/api/desk/{keep['id']}").status_code == 200             # the other session is untouched
    assert not list(Path(tmp_path).glob("episodes/*.json"))                     # and nothing was written to history


def test_discarding_never_submits_or_advances_anything(client):
    st = client.post("/api/desk/start", json={"level": 2, "seed": 4}).json()
    twin = Session.start(episode_for_level(2, 4), 4, reveal_inference=False)
    dec = encode_decision(reference_decision(twin._ep, twin._current()))
    client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec})         # a result is pending, the next observation not yet fetched
    before = client.get(f"/api/desk/{st['id']}").json()
    assert before["phase"] == "settled" and before["observation"] is None
    other = client.post("/api/desk/start", json={"level": 2, "seed": 4}).json()
    client.delete(f"/api/desk/{other['id']}")
    assert client.get(f"/api/desk/{st['id']}").json() == before                 # deleting a neighbour changes nothing
    client.delete(f"/api/desk/{st['id']}")
    assert client.get(f"/api/desk/{st['id']}").status_code == 404


def test_finished_episodes_are_not_deletable_here_and_stay_in_review(client, tmp_path):
    sid, _, _ = _play(client, 1, 3)
    assert client.get("/api/desk").json() == []                                # finished: not in the unfinished list
    assert client.delete(f"/api/desk/{sid}").status_code == 409
    assert len(client.get("/api/review/sessions").json()) == 1
    assert len(list(Path(tmp_path).glob("episodes/*.json"))) == 1


def test_an_episode_saved_but_whose_last_result_is_unseen_can_be_discarded_without_touching_history(client, tmp_path):
    sid, _, _ = _play(client, 1, 3, stop_before_continue=True)
    live = client.get("/api/desk").json()
    assert [d["id"] for d in live] == [sid] and live[0]["in_history"] is True
    assert client.delete(f"/api/desk/{sid}").status_code == 200
    assert client.get(f"/api/desk/{sid}").status_code == 404
    assert len(client.get("/api/review/sessions").json()) == 1                  # its saved record is Review's, left alone


def test_discard_all_removes_unfinished_sessions_only(client):
    done, _, _ = _play(client, 1, 3)
    for sd in (1, 2, 3):
        client.post("/api/desk/start", json={"level": 2, "seed": sd})
    gone = client.delete("/api/desk").json()["deleted"]
    assert len(gone) == 3 and client.get("/api/desk").json() == []
    assert client.get(f"/api/desk/{done}").status_code == 200                   # the finished one is not unfinished: left as it was
    assert client.delete("/api/desk").json() == {"deleted": []}


# ---- the decided information rules ---------------------------------------------------------------------------------------------

def test_the_live_desk_never_sends_the_models_probability_of_informed_but_the_debrief_has_it(client):
    seen_in_debrief = False
    for seed in range(3):
        sid, states, results = _play(client, 5, seed)
        blob = json.dumps(results)
        assert "P(informed" not in blob and "p_informed" not in blob
        d = client.get(f"/api/desk/{sid}/debrief").json()
        seen_in_debrief |= any("P(informed)" in r for dec in d["decisions"] for r in dec["reasons"]) and bool(d["evidence_vs_truth"])
    assert seen_in_debrief


def test_reveal_inference_is_a_session_setting_not_a_change_to_the_assessment():
    a, b = Session.start("mm.ep5_information_views", 1), Session.start("mm.ep5_information_views", 1, reveal_inference=False)
    ra = rb = None
    while not a.done:
        d = encode_decision(reference_decision(a._ep, a._current()))
        ra, rb = a.submit(d), b.submit(d)
        assert ra["assessment"]["rating"] == rb["assessment"]["rating"] and ra["assessment"]["expected_pnl"] == rb["assessment"]["expected_pnl"]
        assert ra["events"] == rb["events"]


# ---- the input.unit fix --------------------------------------------------------------------------------------------------------

def test_input_unit_is_a_unit_not_the_hint():
    from rates_trainer.episodes.episode import Episode
    units = {}
    for eid, seed in (("mm.ep1_single_trade", 1), ("mm.ep4_products_overnight", 3), ("mm.ep3_curve_book_ldi", 3)):
        ep = Episode(eid, seed)
        while not ep.done:
            o = ep.observe()
            spec = o.view["input"]
            if spec["type"] == "number":
                units[eid] = spec["unit"]
                assert spec["unit"] != spec["hint"] and spec["hint"] and " " not in spec["unit"]
            elif spec["type"] in ("quote", "rfq"):
                assert spec["unit"] == "%"
            else:
                assert "unit" not in spec
            ep.submit(reference_decision(ep, o))
    assert units == {"mm.ep1_single_trade": "EUR", "mm.ep4_products_overnight": "contracts", "mm.ep3_curve_book_ldi": "EUR"}


# ---- question catalogue plumbing -----------------------------------------------------------------------------------------------

def test_question_catalogue_is_plain_and_complete(client):
    c = catalogue()
    assert json.loads(json.dumps(c)) == c and c["sources"] == 62
    skills = [s for t in c["tracks"] for s in t["skills"]]
    assert len(skills) == 41 and sum(s["sources"] for s in skills) == 62
    assert all(s["sources"] == 0 for s in skills if s["planned"])
    assert client.get("/api/catalogue").json()["train"] == c
    assert [e["level"] for e in client.get("/api/catalogue").json()["episodes"]] == [1, 2, 3, 3, 4, 5]
