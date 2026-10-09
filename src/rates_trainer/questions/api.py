"""Public, plain-data surface of the question system (the counterpart of episodes/api.py).

The read-only catalogue (what can be practised, by track and skill, down to each source) and `QuestionSession` (practice.py): the current question
with no answers in it, answer -> result, solution, summary. The question generators and grading are not touched.
"""

from __future__ import annotations

from collections import Counter

from ..curriculum.skills import SKILLS, TRACKS
from .practice import KINDS, QuestionSession, source_kinds
from .registry import all_specs


def catalogue() -> dict:
    """{"tracks": [{id, title, sources, skills: [{id, title, planned, prereqs, sources, curated, difficulties, kinds, items}]}], "sources": n}
    `kinds` counts the sources by conceptual / calculation; `items` lists each source (id, difficulty, curated, kind) for single-question practice."""
    specs = all_specs()
    kinds = source_kinds()
    by_skill: dict[str, list] = {}
    for s in specs:
        by_skill.setdefault(s.skill, []).append(s)
    tracks = []
    for tid, title in TRACKS.items():
        skills = []
        for sk in SKILLS.values():
            if sk.track != tid:
                continue
            src = by_skill.get(sk.id, [])
            diff = Counter(s.difficulty for s in src)
            skills.append({"id": sk.id, "title": sk.title, "planned": sk.planned, "prereqs": list(sk.prereqs), "sources": len(src),
                           "curated": sum(s.curated for s in src), "difficulties": {str(d): diff.get(d, 0) for d in (1, 2, 3)},
                           "kinds": {k: sum(kinds[s.id] == k for s in src) for k in KINDS},
                           "items": [{"id": s.id, "difficulty": s.difficulty, "curated": s.curated, "kind": kinds[s.id]} for s in src]})
        tracks.append({"id": tid, "title": title, "skills": skills, "sources": sum(k["sources"] for k in skills)})
    return {"tracks": tracks, "sources": len(specs)}


__all__ = ["QuestionSession", "catalogue"]
