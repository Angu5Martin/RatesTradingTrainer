#!/usr/bin/env python3
"""Record a real MARKET MAKING GAME through the real HTTP app into frontend/src/fixtures/game_l1.json (private home; nothing real is touched).

The frontend's component tests replay these payloads with a stand-in server, so they run against what the Python code actually sends. Re-run after changing the game's
payloads:  .venv/bin/python scripts/dump_game_fixtures.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
os.environ["RATES_TRAINER_HOME"] = tempfile.mkdtemp(prefix="rates-fixture-")

from fastapi.testclient import TestClient  # noqa: E402

from rates_trainer.web.app import create_app  # noqa: E402


def tick(m, x):
    return round(round(x / m["tick"]) * m["tick"], 6)


def main(level=1, seed=2):
    c = TestClient(create_app())
    lst = c.get("/api/mmgame").json()
    start = c.post("/api/mmgame/start", json={"level": level, "seed": seed}).json()
    gid, st, steps, first = start["id"], start, [], True
    quotes_sent = None
    while st["phase"] != "done":
        if first:
            qs = []
            for m in st["markets"]:
                lo, hi = m["range"]
                mid = lo + (hi - lo) * (0.5 if m["kind"] == "world" else 0.3)
                qs.append({"market": m["id"], "bid": tick(m, mid - 2 * m["tick"]), "offer": tick(m, mid + 2 * m["tick"]), "size": 1})
            quotes_sent = qs
            st = c.post(f"/api/mmgame/{gid}/quotes", json={"quotes": qs}).json()
            quoted = st
            first = False
        r = c.post(f"/api/mmgame/{gid}/advance").json()
        st = r["state"]
        steps.append(r)
    debrief = c.get(f"/api/mmgame/{gid}/debrief").json()
    out = {"list": lst, "start": start, "quotes_sent": quotes_sent, "quoted": quoted, "steps": steps, "debrief": debrief}
    path = root / "frontend" / "src" / "fixtures" / "game_l1.json"
    path.write_text(json.dumps(out))
    print(f"wrote {path} ({path.stat().st_size // 1024} KB): {len(steps)} rounds, {len(start['markets'])} markets")


if __name__ == "__main__":
    main()
