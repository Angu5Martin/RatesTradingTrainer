"""MARKET MAKING GAME over HTTP: the whole lifecycle through the real app, what is and is not sent, persistence and replay across a restart, and separation from TRAIN and the Live Desk."""

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rates_trainer.web import store
from rates_trainer.web.app import create_app


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("RATES_TRAINER_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def client(home):
    return TestClient(create_app())


def tickify(m, x):
    return round(round(x / m["tick"]) * m["tick"], 6)


def quote_all(c, gid, st, size=1):
    """Post a market in every open, unquoted market: near the lower third of its range."""
    quotes = []
    for m in st["markets"]:
        if m["status"] in ("upcoming", "resolved") or m.get("quote"):
            continue
        lo, hi = m["range"]
        mid = lo + (hi - lo) * (0.5 if m["kind"] == "world" else 0.3)
        quotes.append({"market": m["id"], "bid": tickify(m, mid - 2 * m["tick"]), "offer": tickify(m, mid + 2 * m["tick"]), "size": size})
    if quotes:
        r = c.post(f"/api/mmgame/{gid}/quotes", json={"quotes": quotes})
        assert r.status_code == 200, r.text
        return r.json()
    return st


def play_out(c, gid, st, log):
    while st["phase"] != "done":
        st = quote_all(c, gid, st)
        log.append(json.dumps(st))
        r = c.post(f"/api/mmgame/{gid}/advance")
        assert r.status_code == 200, r.text
        st = r.json()["state"]
        log.append(json.dumps(r.json()))
    return st


def test_levels_and_empty_list(client):
    r = client.get("/api/mmgame").json()
    assert [l["name"] for l in r["levels"]] == ["Beginner", "Intermediate", "Advanced"] and r["games"] == [] and r["mixes"] == ["mixed", "probability", "world"]
    assert [l["rounds"] for l in r["levels"]] == [8, 12, 14]


@pytest.mark.parametrize("level", [1, 2, 3])
def test_full_lifecycle_over_http(client, home, level):
    st = client.post("/api/mmgame/start", json={"level": level, "seed": 77}).json()
    gid = st["id"]
    assert st["phase"] == "quoting" and st["round"] == 0 and st["level"] == level and len(st["markets"]) == [3, 5, 7][level - 1]
    assert client.get(f"/api/mmgame/{gid}/debrief").status_code == 409                  # not before the end
    log = [json.dumps(st)]
    done = play_out(client, gid, st, log)
    assert done["phase"] == "done" and all(m["status"] == "resolved" for m in done["markets"])
    d = client.get(f"/api/mmgame/{gid}/debrief")
    assert d.status_code == 200
    d = d.json()
    assert d["seed"] == 77 and d["totals"]["pnl"] == pytest.approx(done["portfolio"]["pnl_settled"], abs=1e-6)
    assert d["totals"]["pnl"] == pytest.approx(d["totals"]["decision_result"] + d["totals"]["luck"], abs=1e-6)
    blob = "\n".join(log)
    assert '"seed"' not in blob
    assert not any(k in blob for k in ('"tape"', '"shock_plan"', '"informed"', '"fair_hist"'))
    # the saved file is under mmgame/ and nowhere else
    files = sorted(p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file())
    assert files == [f"mmgame/{gid}.json"]


def test_hidden_information_is_absent_from_every_payload_during_play(client):
    st = client.post("/api/mmgame/start", json={"level": 3, "seed": 424242}).json()
    gid, log = st["id"], [json.dumps(st)]
    for _ in range(5):
        st = quote_all(client, gid, st)
        r = client.post(f"/api/mmgame/{gid}/advance").json()
        st = r["state"]
        log += [json.dumps(r), json.dumps(st)]
    blob = "\n".join(log)
    assert "424242" not in blob
    for forbidden in ('"seed"', '"tape"', '"shock_plan"', '"informed"', '"fair"', '"final_fair"', '"answer"'):
        for m in st["markets"]:
            if m["status"] != "resolved":
                assert forbidden not in json.dumps(m), (forbidden, m["id"])
    assert [c["type"] for c in st["counterparties"]] == [None] * 7                       # level 3 shows no counterparty types


def test_refused_requests_are_400_and_change_nothing(client):
    st = client.post("/api/mmgame/start", json={"level": 1, "seed": 5}).json()
    gid, m = st["id"], st["markets"][0]
    base = f"/api/mmgame/{gid}"
    bad = [("quote", {"market": m["id"], "bid": 5, "offer": 5}), ("quote", {"market": m["id"], "bid": "x", "offer": 5}), ("quote", {"market": "M99", "bid": 1, "offer": 2}),
           ("quote", {"market": m["id"], "bid": m["range"][0] - 5, "offer": m["range"][0] + 1}), ("quote", {"market": m["id"], "bid": m["range"][0] + 1, "offer": m["range"][0] + 2, "size": 99}),
           ("quote", {"market": m["id"], "bid": m["range"][0] + m["tick"] / 3, "offer": m["range"][1]}), ("pause", {"market": "M99"}), ("ack", {"market": "M99"})]
    for path, body in bad:
        r = client.post(f"{base}/{path}", json=body)
        assert r.status_code == 400 and r.json()["detail"], (path, body)
    assert client.post(f"{base}/quote", json={"market": m["id"]}).status_code == 422
    after = client.get(base).json()
    assert after["markets"][0]["quote"] is None and after["round"] == 0
    # a batch with one bad quote applies none of them
    good = {"market": st["markets"][1]["id"], "bid": st["markets"][1]["range"][0] + 1, "offer": st["markets"][1]["range"][0] + 2}
    assert client.post(f"{base}/quotes", json={"quotes": [good, bad[0][1]]}).status_code == 400
    assert client.get(base).json()["markets"][1]["quote"] is None


def test_unknown_game_and_bad_ids(client):
    for gid in ("0" * 16, "nope", "..", "..%2F..%2Fetc"):
        assert client.get(f"/api/mmgame/{gid}").status_code in (404, 405)
        assert client.post(f"/api/mmgame/{gid}/advance").status_code in (404, 405)
    assert client.post("/api/mmgame/start", json={"level": 9}).status_code == 400
    assert client.post("/api/mmgame/start", json={"level": 1, "mix": "bananas"}).status_code == 400
    assert client.post("/api/mmgame/start", json={}).status_code == 422


def test_options_markets_and_mix_and_seed_reproduce(client):
    a = client.post("/api/mmgame/start", json={"level": 2, "seed": 9, "markets": 4, "mix": "world"}).json()
    b = client.post("/api/mmgame/start", json={"level": 2, "seed": 9, "markets": 4, "mix": "world"}).json()
    assert a["id"] != b["id"] and [m["title"] for m in a["markets"]] == [m["title"] for m in b["markets"]] and len(a["markets"]) == 4
    assert {m["kind"] for m in a["markets"]} == {"world"} and [m["opens_at"] for m in a["markets"]] == [m["opens_at"] for m in b["markets"]]
    p = client.post("/api/mmgame/start", json={"level": 1, "seed": 9, "markets": 2, "mix": "probability"}).json()
    assert {m["kind"] for m in p["markets"]} == {"probability"} and len(p["markets"]) == 2
    big = client.post("/api/mmgame/start", json={"level": 1, "seed": 9, "markets": 50}).json()
    assert len(big["markets"]) == 4                                                       # clamped to the level's maximum
    c = client.post("/api/mmgame/start", json={"level": 1, "seed": 10, "markets": 4}).json()
    assert [m["title"] for m in c["markets"]] != [m["title"] for m in big["markets"]]


def test_pause_acknowledge_and_quote_flow(client):
    st = client.post("/api/mmgame/start", json={"level": 1, "seed": 3}).json()
    gid, m = st["id"], st["markets"][0]
    base = f"/api/mmgame/{gid}"
    lo = m["range"][0]
    s = client.post(f"{base}/quote", json={"market": m["id"], "bid": lo + 1, "offer": lo + 2, "size": 2}).json()
    q = s["markets"][0]["quote"]
    assert (q["bid"], q["offer"], q["size"]) == (lo + 1, lo + 2, 2)
    s = client.post(f"{base}/pause", json={"market": m["id"]}).json()
    assert s["markets"][0]["status"] == "paused"
    s = client.post(f"{base}/pause", json={"market": m["id"], "paused": False}).json()
    assert s["markets"][0]["status"] == "active"
    assert client.post(f"{base}/ack", json={"market": m["id"]}).status_code == 200


def test_game_survives_a_server_restart_and_replays_exactly(home):
    c1 = TestClient(create_app())
    st = c1.post("/api/mmgame/start", json={"level": 2, "seed": 31}).json()
    gid = st["id"]
    for _ in range(3):
        st = quote_all(c1, gid, st)
        st = c1.post(f"/api/mmgame/{gid}/advance").json()["state"]
    c2 = TestClient(create_app())                                    # a new process: nothing in memory
    again = c2.get(f"/api/mmgame/{gid}")
    assert again.status_code == 200 and again.json() == st
    lst = c2.get("/api/mmgame").json()["games"]
    assert [g["id"] for g in lst] == [gid] and lst[0]["done"] is False and lst[0]["round"] == 3 and "seed" not in lst[0]
    nxt1 = c1.post(f"/api/mmgame/{gid}/advance").json()
    nxt2 = c2.post(f"/api/mmgame/{gid}/advance").json()
    assert nxt1 == nxt2                                              # the replayed game continues identically
    done = play_out(c2, gid, nxt2["state"], [])
    assert c2.get(f"/api/mmgame/{gid}/debrief").status_code == 200
    assert c2.get("/api/mmgame").json()["games"][0]["done"] is True


def test_abandon_removes_unfinished_games_but_keeps_finished_ones(client, home):
    a = client.post("/api/mmgame/start", json={"level": 1, "seed": 1}).json()["id"]
    b = client.post("/api/mmgame/start", json={"level": 1, "seed": 2}).json()
    assert (home / "mmgame" / f"{a}.json").exists()
    assert client.delete(f"/api/mmgame/{a}").json() == {"deleted": a}
    assert not (home / "mmgame" / f"{a}.json").exists() and client.get(f"/api/mmgame/{a}").status_code == 404
    play_out(client, b["id"], b, [])
    assert client.delete(f"/api/mmgame/{b['id']}").status_code == 409 and (home / "mmgame" / f"{b['id']}.json").exists()


def test_a_corrupt_saved_file_is_skipped_in_the_list_and_refused_not_crashed(home, client):
    gid = client.post("/api/mmgame/start", json={"level": 1, "seed": 1}).json()["id"]
    (home / "mmgame" / "garbage.json").write_text("{not json")
    assert [g["id"] for g in client.get("/api/mmgame").json()["games"]] == [gid]
    p = home / "mmgame" / f"{gid}.json"
    j = json.loads(p.read_text())
    j["record"]["actions"] = [{"t": "quote", "market": "M99", "bid": "1", "offer": "2", "size": 1}]
    p.write_text(json.dumps(j))
    fresh = TestClient(create_app())
    assert fresh.get(f"/api/mmgame/{gid}").status_code == 409


# ----------------------------------------------------------------------------- separation from the rest

def test_game_and_train_and_desk_do_not_touch_each_others_data(client, home):
    # TRAIN: answer one part; a Live Desk episode is started; a game is played through
    t = client.post("/api/train/start", json={"template_id": "swaps.dv01_pnl", "seed": 3}).json()
    client.post(f"/api/train/{t['id']}/answer", json={"text": "", "skip": True})
    desk = client.post("/api/desk/start", json={"level": 1, "seed": 1}).json()
    train_files = sorted(p.name for p in (home / "practice").glob("*"))
    g = client.post("/api/mmgame/start", json={"level": 1, "seed": 4}).json()
    play_out(client, g["id"], g, [])
    assert sorted(p.name for p in (home / "practice").glob("*")) == train_files
    assert not (home / "episodes").exists() or list((home / "episodes").glob("*")) == []
    assert [p.name for p in (home / "mmgame").glob("*")] == [f"{g['id']}.json"]
    assert client.get("/api/train/history").json()[0]["id"] == t["id"] and len(client.get("/api/train/history").json()) == 1
    assert client.get("/api/review/sessions").json() == []                                  # games are not Live Desk episodes
    assert client.get(f"/api/desk/{desk['id']}").status_code == 200
    assert all("mmgame" not in str(p) for p in (home / "practice").rglob("*"))


def test_existing_endpoints_are_unchanged(client):
    cat = client.get("/api/catalogue").json()
    assert set(cat) == {"episodes", "train"} and cat["train"]["sources"] >= 160 and len(cat["episodes"]) >= 5
    h = client.get("/api/health").json()
    assert h["ok"] and h["app"] == "rates-trainer"
    for url, method in (("/api/desk", "get"), ("/api/train/history", "get"), ("/api/review/sessions", "get")):
        assert getattr(client, method)(url).status_code == 200
    assert client.post("/api/desk/start", json={"level": 1, "seed": 1}).status_code == 200
    assert client.post("/api/train/start", json={"template_id": "swaps.dv01_pnl", "seed": 1}).status_code == 200


def test_tests_use_a_private_home_never_the_real_one(home):
    assert store.home() == home and store.home() != Path.home() / ".rates_trainer"


def test_the_game_package_is_independent_of_the_rates_engine_trainer_questions_and_desk():
    root = Path(__file__).resolve().parents[2] / "src" / "rates_trainer"
    banned = ("engine", "questions", "episodes", "curriculum", "session", "episode_session", "marketmaking", "cli")
    for f in (root / "mmgame").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = []
            if isinstance(node, ast.ImportFrom):
                mods = [("." * node.level) + (node.module or "")]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                name = m.lstrip(".").split(".")[0] if m.startswith(".") else (m.split(".")[1] if m.startswith("rates_trainer.") else "")
                assert name not in banned and not m.startswith("..") , (f.name, m)
    # and nothing outside the game mentions it except the HTTP router and the app that mounts it
    for f in root.rglob("*.py"):
        if "mmgame" in f.parts or f.name in ("mmgame_routes.py", "app.py"):
            continue
        assert "mmgame" not in f.read_text(), f.name
