"""One JSON file per game under <home>/mmgame/<id>.json, rewritten after every action (atomically). Separate from TRAIN practice files (<home>/practice) and Live Desk
episodes (<home>/episodes): nothing here reads, writes or lists those, and they never list these.

A file holds the replay record (seed, configuration and the player's actions: enough to rebuild the game exactly) and a small summary for the list of games.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ID = re.compile(r"^[0-9a-f]{16}$")


def folder(home: Path) -> Path:
    return home / "mmgame"


def valid_id(game_id: str) -> bool:
    return bool(ID.match(game_id))


def save(home: Path, record: dict, summary: dict) -> Path:
    d = folder(home)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{record['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"summary": summary, "record": record}, indent=1))
    tmp.replace(path)                                    # never leave a half-written file
    return path


def load(home: Path, game_id: str) -> dict | None:
    if not valid_id(game_id):
        return None
    p = folder(home) / f"{game_id}.json"
    try:
        return json.loads(p.read_text())["record"]
    except (OSError, ValueError, KeyError):
        return None


def delete(home: Path, game_id: str) -> bool:
    if not valid_id(game_id):
        return False
    p = folder(home) / f"{game_id}.json"
    try:
        p.unlink()
        return True
    except OSError:
        return False


def list_games(home: Path) -> list[dict]:
    d = folder(home)
    if not d.exists():
        return []
    out = []
    for p in d.glob("*.json"):
        try:
            out.append(json.loads(p.read_text())["summary"])
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda s: s.get("started", ""), reverse=True)
