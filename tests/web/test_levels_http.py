"""Levels 3-5 through the real server and episode engine, as the browser drives them: the commit/reveal flow, what the live responses may and may not carry, the
macros the new tickets use (flatten, switch, target, keep, products), and the two additive view fields."""

import json

import pytest
from fastapi.testclient import TestClient

from rates_trainer.episodes.api import Session, episode_for_level
from rates_trainer.episodes.episode import reference_decision
from rates_trainer.episodes.serial import encode_decision
from rates_trainer.web.app import create_app

from .test_api import HIDDEN_KEYS, _keys, _play

LIVE_HIDDEN = HIDDEN_KEYS | {"p_informed", "informed", "evidence_vs_truth", "view_truth"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RATES_TRAINER_HOME", str(tmp_path))
    return TestClient(create_app())


@pytest.mark.parametrize("level,seed", [(3, 1), (3, 2), (4, 1), (5, 1), (5, 2)])
def test_a_whole_level_runs_over_http_and_nothing_hidden_is_in_a_live_response(client, level, seed):
    sid, states, results = _play(client, level, seed)
    assert states[-1]["phase"] == "done"
    for payload in (*states, *results):
        assert not (set(_keys(payload)) & LIVE_HIDDEN), set(_keys(payload)) & LIVE_HIDDEN
    blob = json.dumps([states, results])
    assert "P(informed" not in blob and "p_informed" not in blob
    markets = [e for r in results for e in r["events"] if e["type"] == "market"]
    assert markets and all([m["tenor"] for m in e["tenor_moves"]] == [2, 5, 10, 30] for e in markets)      # the additive field, on every market move
    d = client.get(f"/api/desk/{sid}/debrief").json()
    assert (d["evidence_vs_truth"] is not None) == (level == 5)                                          # the hidden state arrives only in the debrief
    full = client.get(f"/api/desk/{sid}/debrief", params={"compare": "true"}).json()
    assert (full["market_paths"] is not None) == (level == 5)
    if level == 5:
        assert len(full["market_paths"]["yours"]["samples"]) == 200
    else:
        assert d["outcome"]["exposures_by_round"] is not None or level == 4


@pytest.mark.parametrize("level", [3, 4, 5])
def test_the_next_observation_waits_for_continue_at_every_level(client, level):
    st = client.post("/api/desk/start", json={"level": level, "seed": 1}).json()
    twin = Session.start(episode_for_level(level, 1), 1)
    dec = encode_decision(reference_decision(twin._ep, twin._current()))
    r = client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec}).json()
    s = client.get(f"/api/desk/{st['id']}").json()
    assert s["phase"] == "settled" and s["observation"] is None and s["pending"]["result"] == r["result"]
    assert s["pending"]["observation"]["kind"] == st["observation"]["kind"]
    assert client.post(f"/api/desk/{st['id']}/submit", json={"decision": dec}).status_code == 409
    assert client.post(f"/api/desk/{st['id']}/parse", json={"text": "none"}).status_code == 409
    assert client.post(f"/api/desk/{st['id']}/continue").json()["phase"] in ("awaiting",)


def _advance_to(client, sid, level, seed, kind, nth=0):
    """Play the reference policy over HTTP until the prompt of this kind (the nth such), returning its observation."""
    twin = Session.start(episode_for_level(level, seed), seed, reveal_inference=False)
    seen = 0
    while True:
        obs = client.get(f"/api/desk/{sid}").json()["observation"]
        if obs["kind"] == kind:
            if seen == nth:
                return obs
            seen += 1
        dec = encode_decision(reference_decision(twin._ep, twin._current()))
        twin.submit(dec)
        client.post(f"/api/desk/{sid}/submit", json={"decision": dec})
        client.post(f"/api/desk/{sid}/continue")


def _parse(client, sid, text):
    return client.post(f"/api/desk/{sid}/parse", json={"text": text}).json()


def test_level_3_macros_resolve_to_legs_and_the_hedge_menu_is_the_ladder(client):
    sid = client.post("/api/desk/start", json={"level": 3, "seed": 1}).json()["id"]
    obs = _advance_to(client, sid, 3, 1, "hedge")
    assert obs["hedge_menu"] is None and [r["tenor"] for r in obs["market"]["ladder"]] == [2, 5, 10, 30] and obs["input"]["can_flatten"]
    legs = _parse(client, sid, "flatten")
    assert legs["ok"] and 1 <= len(legs["decision"]["trades"]) <= 3 and all(t["kind"] == "swap" for t in legs["decision"]["trades"])
    two = _parse(client, sid, "pay 100m 10y + receive 40m 2y")
    assert [t["tenor"] for t in two["decision"]["trades"]] == [10, 2]
    assert not _parse(client, sid, "banana")["ok"]


def test_level_4_products_are_hedged_switched_and_reported_after_the_commit(client):
    sid = client.post("/api/desk/start", json={"level": 4, "seed": 1}).json()["id"]
    obs = _advance_to(client, sid, 4, 1, "hedge")
    assert {p["code"] for p in obs["market"]["products"]} == {"FGBM", "FGBL", "CTD"} and obs["book"]["spreads"] is None and not obs["input"]["can_switch"]
    sell = _parse(client, sid, "sell 5000 fgbm")["decision"]
    assert sell["trades"] == [{"kind": "future", "code": "FGBM", "contracts": -5000.0}]
    bond = _parse(client, sid, "sell 40m ctd")["decision"]
    assert bond["trades"][0]["kind"] == "bond"
    r = client.post(f"/api/desk/{sid}/submit", json={"decision": sell}).json()
    assert [e["kind"] for e in r["result"]["events"] if e["type"] == "hedge_trade"] == ["future"]
    assert "swap_spread" in r["result"]["assessment"]["metrics"]["exposures"]                      # the residual spread risk is revealed by the result
    client.post(f"/api/desk/{sid}/continue")
    nxt = _advance_to(client, sid, 4, 1, "overnight")
    assert nxt["overnight"]["time_pnl"] is not None and nxt["input"]["can_switch"]
    assert nxt["book"]["hedges"] and nxt["book"]["spreads"] is not None                            # held futures show as hedges and as spread exposure
    sw = _parse(client, sid, "switch")
    assert sw["ok"] and any(t["kind"] == "future" for t in sw["decision"]["trades"])
    for cause in client.post(f"/api/desk/{sid}/submit", json={"decision": {"type": "hedge", "label": "keep", "trades": []}}).json()["result"]["events"]:
        if cause["type"] == "overnight":
            assert {c["name"] for c in cause["causes"]} >= {"time: swap carry"}


def test_level_5_position_macros_and_keep_are_the_same_decision_however_it_is_labelled(client):
    sid = client.post("/api/desk/start", json={"level": 5, "seed": 1}).json()["id"]
    obs = _advance_to(client, sid, 5, 1, "position")
    assert obs["input"]["can_target"] and obs["conditions"]["research"] and obs["conditions"]["calendar"]
    keep = _parse(client, sid, "keep")["decision"]
    assert keep["trades"] == [] and keep["label"] == "Keep the book as it is"
    tgt = _parse(client, sid, "target 150k")["decision"]
    assert len(tgt["trades"]) == 1 and tgt["trades"][0]["kind"] == "swap"
    flat = _parse(client, sid, "flat")["decision"]
    assert flat["trades"][0]["side"] == "pay"                                                       # the book is long: flat is a pay
    # the browser's N key sends an empty hedge labelled as a warehouse: the same decision as 'keep' as far as the engine is concerned
    a, b = Session.start(episode_for_level(5, 1), 1, reveal_inference=False), Session.start(episode_for_level(5, 1), 1, reveal_inference=False)
    while a.observe()["kind"] != "position":
        d = encode_decision(reference_decision(a._ep, a._current()))
        a.submit(d)
        b.submit(d)
    ra = a.submit({"type": "hedge", "label": "Keep the book as it is", "trades": []})
    rb = b.submit({"type": "hedge", "label": "Warehouse (no hedge)", "trades": []})
    assert ra["assessment"]["rating"] == rb["assessment"]["rating"] and ra["assessment"]["expected_pnl"] == rb["assessment"]["expected_pnl"]
    assert [e for e in ra["events"] if e["type"] == "round_pnl"] == [e for e in rb["events"] if e["type"] == "round_pnl"]


def test_level_5_live_views_carry_the_evidence_and_the_view_but_not_the_truth_about_either(client):
    sid = client.post("/api/desk/start", json={"level": 5, "seed": 1}).json()["id"]
    obs = _advance_to(client, sid, 5, 1, "rfq", nth=1)
    c = obs["conditions"]
    assert c["research"]["reliability"] == pytest.approx(0.3) and set(c["research"]) >= {"text", "remaining_bp", "steps_left"}
    assert c["named_clients"] and all(set(o) == {"side", "move_bp"} for cl in c["named_clients"] for o in cl["observations"])
    assert not (set(_keys(obs)) & LIVE_HIDDEN)
