"""The smallest local record of what has been played: one JSON file per finished episode, and one per practice session, under a home directory.

Each file holds the replay record (episode id, seeds, decisions), the transcript the trainee saw (observation and result per decision), a short
summary and the debrief without the same-path comparison. Practice sessions (questions/practice.py `record()`) are rewritten after every graded part, so an abandoned session still keeps what was answered. Review will read these. Plain files, local, single user: no database, no accounts.
The home is $RATES_TRAINER_HOME or ~/.rates_trainer.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("RATES_TRAINER_HOME") or Path.home() / ".rates_trainer")


def summarise(view: dict, transcript: list[dict], debrief: dict) -> dict:
    ratings = [d["rating"] for d in debrief["decisions"]]
    return {"level": view["episode"]["level"], "episode": view["episode"]["id"], "title": view["episode"]["title"],
            "rounds": view["episode"]["rounds"], "decisions": len(ratings),
            "ratings": {r: ratings.count(r) for r in ("sound", "defensible", "poor", "error")},
            "pnl": debrief["outcome"]["total"], "luck": debrief["luck"]["luck"],
            "checkpoints_correct": sum(1 for c in debrief["calculation_checks"] if c["correct"]), "checkpoints": len(debrief["calculation_checks"])}


def save_episode(session_id: str, record: dict, transcript: list[dict], summary: dict, debrief: dict) -> Path:
    d = home() / "episodes"
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    path = d / f"{stamp}_{record['episode']}_{record['seed']}_{session_id[:8]}.json"
    path.write_text(json.dumps({"id": session_id, "saved": stamp, "summary": summary, "record": record, "transcript": transcript,
                                "debrief": debrief}, indent=1))
    return path


def list_episodes() -> list[dict]:
    d = home() / "episodes"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), reverse=True):
        try:
            j = json.loads(p.read_text())
            out.append({"id": j["id"], "saved": j["saved"], **j["summary"]})
        except (OSError, ValueError, KeyError):
            continue
    return out


def save_practice(session_id: str, record: dict) -> Path:
    """One file per practice session, named by its start time and id, rewritten as the session goes on (a small file: the attempts so far)."""
    d = home() / "practice"
    d.mkdir(parents=True, exist_ok=True)
    stamp = record["started"].replace("-", "").replace(":", "")
    path = d / f"{stamp}_{session_id[:8]}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1))
    tmp.replace(path)                                   # never leave a half-written record
    return path


def list_practice() -> list[dict]:
    d = home() / "practice"
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), reverse=True):
        try:
            j = json.loads(p.read_text())
            out.append({"id": j["id"], "started": j["started"], "mode": j["mode"], "label": j["label"], "finished": j["finished"], "ended_early": j["ended_early"],
                        "questions": len(j["questions"]), "parts_total": j["summary"]["parts_total"], "parts_correct": j["summary"]["parts_correct"]})
        except (OSError, ValueError, KeyError):
            continue
    return out
