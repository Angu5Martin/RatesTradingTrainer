"""QuestionSession: a serialisable public interface to the question engine, for TRAIN (the counterpart of episodes/api.Session).

    start practice -> question view -> answer a part -> result -> next part / next question -> ... -> summary

Everything it returns is plain JSON-ready data. Generation (registry.generate) and grading (Part.grade) are the existing ones and are called, never reimplemented:
a question is still (template id, seed), a numeric answer is still accepted by Tolerance, an unreadable entry is still re-prompted and not penalised, and a
multi-part question is still asked one part at a time, each part graded and revealed before the next is shown (later parts can build on earlier ones).

What a view never contains: the expected answer, the tolerance, the first-order estimate, which option is correct, the rationale, the worked solution or the
generation facts. They appear only in the result of the part they belong to, and the worked solution only after the last part.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from ..curriculum.skills import SKILLS, TRACKS
from ..session import plan_queue
from .model import ChoicePart, NumericPart, Part, Question, parse_number
from .registry import TemplateSpec, all_specs, from_id, generate, get_spec, select

KINDS = ("conceptual", "calculation")
DIFFICULTY = {1: "single concept", 2: "concept and calculation", 3: "multi-step trading situation"}
UNIT_LABEL = {"EUR": "euros", "bp": "basis points", "%": "percent", "pts": "price points", "contracts": "contracts", "cf": "conversion factor", "df": "discount factor", "years": "years", "x": "multiple"}
FORMAT = "rates-trainer-practice"
VERSION = 1


def kind_of(q: Question) -> str:
    """Conceptual = every part is a multiple-choice; calculation = at least one part is a number to work out."""
    return "calculation" if any(isinstance(p, NumericPart) for p in q.parts) else "conceptual"


@lru_cache(maxsize=1)
def source_kinds() -> dict[str, str]:
    """{template id: kind}. A curated question is a single multiple choice, so conceptual; a template that declares its kind is taken at its word (a test generates it and checks);
    any other source is found once by generating it at seed 0 (a source's kind does not change with the seed)."""
    return {s.id: s.kind or ("conceptual" if s.curated else kind_of(generate(s.id, 0))) for s in all_specs()}


def _entry_hint(p: NumericPart) -> str:
    base = "Type a number; k, m and bn suffixes are read (-225k, 1.2m)."
    if p.unit == "EUR":
        base += " A bare number is read as euros." if p.bare_scale == 1.0 else f" A bare number is multiplied by {p.bare_scale:g}."
    elif p.unit in ("bp", "%"):
        base = f"Type a number in {UNIT_LABEL[p.unit]}; a trailing {p.unit} is allowed."
    else:
        base = f"Type a number ({UNIT_LABEL.get(p.unit, p.unit)})."
    return base


def part_view(p: Part, index: int) -> dict:
    """The part as asked: prompt, options and entry conventions. Nothing of the answer."""
    if isinstance(p, ChoicePart):
        return {"index": index, "kind": "choice", "prompt": p.prompt, "options": list(p.options)}
    return {"index": index, "kind": "numeric", "prompt": p.prompt, "unit": p.unit, "unit_label": UNIT_LABEL.get(p.unit, p.unit), "note": p.note,
            "bare_scale": p.bare_scale, "entry_hint": _entry_hint(p)}


def _is_input_error(feedback: str) -> bool:
    """The rule the terminal loop uses: these two grader messages mean 'could not read that', which is re-prompted, not marked."""
    return "Answer with a letter" in feedback or "could not read" in feedback


@dataclass
class _Done:
    """A graded part, kept for the record and shown back with the question."""
    index: int
    kind: str
    submitted: str
    correct: bool
    skipped: bool
    feedback: str
    expected: str
    detail: str
    why: str
    at: str

    def view(self, part: Part) -> dict:
        v = part_view(part, self.index)
        v["submitted"] = self.submitted
        v["result"] = {"correct": self.correct, "skipped": self.skipped, "status": "skipped" if self.skipped else ("correct" if self.correct else "incorrect"),
                       "feedback": self.feedback, "expected": self.expected, "detail": self.detail, "why": self.why}
        return v


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class QuestionSession:
    """A queue of questions worked through one part at a time. Generated lazily, so starting is instant."""

    plan: list[tuple[str, int]]
    mode: str                              # focused | mixed | single | replay
    label: str
    selection: dict = field(default_factory=dict)
    seed: int | None = None
    started: str = field(default_factory=_now)
    ended_early: bool = False

    def __post_init__(self) -> None:
        if not self.plan:
            raise ValueError("no questions match those filters")
        self._cache: dict[int, Question] = {}
        self._done: list[list[_Done]] = [[] for _ in self.plan]
        self._qi = 0                       # current question
        self._phase = "answering"          # answering | feedback | done

    # ------------------------------------------------------------------------------------------------------------ construction

    @classmethod
    def start(cls, *, tracks: Iterable[str] = (), skills: Iterable[str] = (), difficulty: int | None = None, max_difficulty: int | None = None,
              kind: str | None = None, count: int = 10, seed: int | None = None) -> "QuestionSession":
        """Focused (one track or skill) or mixed (several, or everything) practice. Selection logic is registry.select; kind filters conceptual / calculation."""
        tracks, skills = set(tracks), set(skills)
        for t in tracks:
            if t not in TRACKS:
                raise ValueError(f"unknown track {t!r}")
        for s in skills:
            if s not in SKILLS:
                raise ValueError(f"unknown skill {s!r}")
        if kind is not None and kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if not 1 <= count <= 50:
            raise ValueError("count must be between 1 and 50")
        specs = select(all_specs(), tracks or None, skills or None, difficulty, max_difficulty)
        if kind:
            kinds = source_kinds()
            specs = [s for s in specs if kinds[s.id] == kind]
        if not specs:
            raise ValueError("no questions match those filters")
        seed = random.randrange(1_000_000) if seed is None else seed
        plan = plan_queue(specs, count, random.Random(seed))
        curated = {s.id for s in specs if s.curated}
        seen: set[str] = set()
        unique = []
        for tid, sd in plan:                            # a curated question is a fixed text: show it once, not again with the options reshuffled
            if tid in curated:
                if tid in seen:
                    continue
                seen.add(tid)
            unique.append((tid, sd))
        n_sel = len(tracks) + len(skills)
        mode = "focused" if n_sel == 1 else "mixed"
        label = (SKILLS[next(iter(skills))].title if len(skills) == 1 and not tracks else TRACKS[next(iter(tracks))] if len(tracks) == 1 and not skills
                 else "Mixed practice" + ("" if n_sel else " (everything)"))
        sel = {"tracks": sorted(tracks), "skills": sorted(skills), "difficulty": difficulty, "max_difficulty": max_difficulty, "kind": kind, "count": count, "pool": len(specs)}
        return cls(unique, mode, label, sel, seed)

    @classmethod
    def single(cls, template_id: str, seed: int | None = None) -> "QuestionSession":
        """One question, from a source of your choice: a fresh instance of it, or the exact (template, seed) when a seed is given."""
        spec = get_spec(template_id)
        seed = random.randrange(1_000_000) if seed is None else seed
        return cls([(spec.id, seed)], "single", spec.id, {"template": spec.id}, seed)

    @classmethod
    def replay(cls, ids: Iterable[str], label: str = "Replay") -> "QuestionSession":
        """Exact questions again by id ('template#seed'), for example the ones missed."""
        plan = []
        for i in ids:
            q = from_id(i)                              # validates the id
            plan.append((q.template_id, q.seed))
        return cls(plan, "replay", label, {"ids": [f"{t}#{s}" for t, s in plan]})

    # ------------------------------------------------------------------------------------------------------------ reading

    def _q(self, i: int) -> Question:
        if i not in self._cache:
            self._cache[i] = generate(*self.plan[i])
        return self._cache[i]

    @property
    def total(self) -> int:
        return len(self.plan)

    @property
    def done(self) -> bool:
        return self._phase == "done"

    def _part_index(self) -> int:
        return len(self._done[self._qi])

    def _question_complete(self) -> bool:
        return len(self._done[self._qi]) == len(self._q(self._qi).parts)

    def question_view(self) -> dict | None:
        """The current question as the trainee may see it now: the stem, the parts already answered (with their results) and, while answering, the current part.
        The worked solution is present only once every part has been answered."""
        if self._phase == "done":
            return None
        q = self._q(self._qi)
        spec = get_spec(q.template_id)
        done = [d.view(q.parts[d.index]) for d in self._done[self._qi]]
        complete = self._question_complete()
        out = {
            "id": q.id, "template_id": q.template_id, "skill": q.skill, "skill_title": SKILLS[q.skill].title, "track": q.skill.split(".")[0],
            "track_title": TRACKS[q.skill.split(".")[0]], "difficulty": q.difficulty, "difficulty_label": DIFFICULTY[q.difficulty], "kind": kind_of(q),
            "curated": spec.curated, "stem": q.stem, "parts_total": len(q.parts), "parts_done": done,
            "current": None if complete or self._phase == "feedback" else part_view(q.parts[self._part_index()], self._part_index()),   # the next part waits for Next
            "solution": list(q.solution) if complete else None,
            "question_correct": all(d.correct for d in self._done[self._qi]) if complete else None,
        }
        return out

    def state(self) -> dict:
        n_ok = sum(1 for qs in self._done for d in qs if d.correct)
        n_all = sum(len(qs) for qs in self._done)
        return {"mode": self.mode, "label": self.label, "selection": self.selection, "started": self.started,
                "index": self._qi, "total": self.total, "phase": self._phase, "ended_early": self.ended_early,
                "parts_correct": n_ok, "parts_answered": n_all, "question": self.question_view()}

    # ------------------------------------------------------------------------------------------------------------ acting

    def _current_part(self) -> tuple[Question, Part]:
        if self._phase != "answering":
            raise PermissionError("there is nothing to answer now")
        q = self._q(self._qi)
        return q, q.parts[self._part_index()]

    def check(self, raw: str) -> dict:
        """Can this entry be read? It is not graded and nothing is recorded. For a number, says how it was read (the grader's own parse)."""
        _, part = self._current_part()
        if isinstance(part, NumericPart):
            try:
                v = parse_number(raw, part.bare_scale)
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            return {"ok": True, "read_as": part.display(v)}
        g = part.grade(raw)
        if _is_input_error(g.feedback):
            return {"ok": False, "error": g.feedback}
        return {"ok": True, "read_as": raw.strip().upper().rstrip(".)")}

    def submit(self, raw: str) -> dict:
        """Grade the current part. An unreadable entry raises ValueError and changes nothing (it is not marked wrong)."""
        q, part = self._current_part()
        if isinstance(part, NumericPart):
            parse_number(raw, part.bare_scale)          # raises ValueError for anything that is not a readable number (including an unknown suffix): not marked
        g = part.grade(raw)
        if _is_input_error(g.feedback):
            raise ValueError(g.feedback)
        return self._record(q, part, raw.strip(), g.correct, False, g.feedback, g.expected, g.detail)

    def skip(self) -> dict:
        """Give up on this part: marked wrong, the answer shown, exactly as the terminal's 'skip'."""
        q, part = self._current_part()
        return self._record(q, part, "", False, True, "Skipped.", part.display(), part.detail() if isinstance(part, NumericPart) else "")

    def _record(self, q: Question, part: Part, raw: str, correct: bool, skipped: bool, feedback: str, expected: str, detail: str) -> dict:
        idx = self._part_index()
        why = part.why if isinstance(part, ChoicePart) and len(q.parts) > 1 else ""   # single-part: the rationale is the worked solution
        d = _Done(idx, part.kind, raw, correct, skipped, feedback, expected, detail, why, _now())
        self._done[self._qi].append(d)
        self._phase = "feedback"
        return d.view(part)["result"]

    def next(self) -> None:
        """Move on: to the next part of this question, the next question, or the end. Only after the part's result has been given."""
        if self._phase != "feedback":
            raise PermissionError("answer the current part first")
        if not self._question_complete():
            self._phase = "answering"
        elif self._qi + 1 < self.total:
            self._qi += 1
            self._phase = "answering"
        else:
            self._phase = "done"

    def finish(self) -> None:
        """End the session now (what has been answered stays recorded)."""
        if self._phase != "done":
            self.ended_early = True
            self._phase = "done"

    # ------------------------------------------------------------------------------------------------------------ summary and record

    def _answered_questions(self) -> list[int]:
        return [i for i, qs in enumerate(self._done) if qs]

    def summary(self) -> dict:
        """Parts correct overall and by skill, and the questions to replay. Counted per part, as the terminal's summary does."""
        by_skill: dict[str, list[int]] = {}
        missed: list[str] = []
        per_question = []
        for i in self._answered_questions():
            q = self._q(i)
            ds = self._done[i]
            full = len(ds) == len(q.parts)
            s = by_skill.setdefault(q.skill, [0, 0])
            for d in ds:
                s[1] += 1
                s[0] += d.correct
            if any(not d.correct for d in ds) or not full:
                missed.append(q.id)
            per_question.append({"id": q.id, "skill": q.skill, "skill_title": SKILLS[q.skill].title, "difficulty": q.difficulty, "kind": kind_of(q),
                                 "parts_correct": sum(d.correct for d in ds), "parts_answered": len(ds), "parts_total": len(q.parts),
                                 "correct": full and all(d.correct for d in ds)})
        total = sum(v[1] for v in by_skill.values())
        ok = sum(v[0] for v in by_skill.values())
        return {"parts_total": total, "parts_correct": ok, "questions": per_question, "questions_planned": self.total, "ended_early": self.ended_early,
                "by_skill": [{"skill": k, "title": SKILLS[k].title, "correct": v[0], "total": v[1]} for k, v in sorted(by_skill.items())],
                "missed": missed}

    def record(self, session_id: str = "") -> dict:
        """What is kept for Review: every answered part with what was submitted and how it was marked, by question. No answer keys beyond the expected text shown at the time."""
        qs = []
        for i in self._answered_questions():
            q = self._q(i)
            qs.append({"id": q.id, "template_id": q.template_id, "seed": q.seed, "skill": q.skill, "track": q.skill.split(".")[0], "difficulty": q.difficulty,
                       "kind": kind_of(q), "parts_total": len(q.parts),
                       "parts": [{"index": d.index, "kind": d.kind, "submitted": d.submitted, "correct": d.correct, "skipped": d.skipped, "feedback": d.feedback,
                                  "expected": d.expected, "at": d.at} for d in self._done[i]]})
        return {"format": FORMAT, "version": VERSION, "id": session_id, "started": self.started, "mode": self.mode, "label": self.label,
                "selection": self.selection, "seed": self.seed, "finished": self.done and not self.ended_early, "ended_early": self.ended_early,
                "questions": qs, "summary": self.summary()}


__all__ = ["KINDS", "QuestionSession", "kind_of", "source_kinds", "part_view"]
