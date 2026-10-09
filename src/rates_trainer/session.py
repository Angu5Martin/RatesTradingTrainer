"""Interactive session loop. I/O is injected so it can be tested without a terminal."""

from __future__ import annotations

import random
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .questions.model import ChoicePart, NumericPart, Question
from .questions.registry import TemplateSpec, generate


class Quit(Exception):
    pass


@dataclass
class Result:
    parts_total: int = 0
    parts_correct: int = 0
    by_skill: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    missed: list[str] = field(default_factory=list)  # question ids to replay
    quit_early: bool = False


def plan_queue(specs: Sequence[TemplateSpec], n: int, rng: random.Random) -> list[tuple[str, int]]:
    """n (template id, seed) pairs cycling through shuffled templates (no immediate repeats), fresh random seeds. Nothing is generated yet."""
    if not specs:
        raise ValueError("no questions match those filters")
    plan: list[tuple[str, int]] = []
    pool: list[TemplateSpec] = []
    last = None
    while len(plan) < n:
        if not pool:
            pool = list(specs)
            rng.shuffle(pool)
            if len(pool) > 1 and pool[-1].id == last:
                pool[0], pool[-1] = pool[-1], pool[0]
        spec = pool.pop()
        if spec.id == last and len(specs) > 1:
            pool.insert(0, spec)
            continue
        last = spec.id
        plan.append((spec.id, rng.randrange(1_000_000)))
    return plan


def build_queue(specs: Sequence[TemplateSpec], n: int, rng: random.Random) -> list[Question]:
    """n questions cycling through shuffled templates (no immediate repeats), fresh random seeds."""
    return [generate(tid, seed) for tid, seed in plan_queue(specs, n, rng)]


def _wrap(text: str, indent: str = "") -> str:
    out = []
    for line in text.split("\n"):
        out.append(textwrap.fill(line, width=100, initial_indent=indent, subsequent_indent=indent + "  ")
                   if line.strip() else "")
    return "\n".join(out)


def run_session(
    questions: Sequence[Question],
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    color: bool = False,
) -> Result:
    def c(code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if color else s

    res = Result()
    total = len(questions)
    try:
        for i, q in enumerate(questions, 1):
            say("")
            say(c("1", f"── Question {i}/{total} ── {q.skill} · level {q.difficulty} ── {q.id}"))
            say(_wrap(q.stem))
            all_correct = True
            for j, part in enumerate(q.parts, 1):
                say("")
                label = f"({j}/{len(q.parts)}) " if len(q.parts) > 1 else ""
                say(c("36", _wrap(f"{label}{part.prompt}")))
                if isinstance(part, ChoicePart):
                    for k, opt in enumerate(part.options):
                        say(_wrap(f"{chr(65 + k)}. {opt}", "   "))
                elif part.note:
                    say(f"   [{part.unit}; {part.note}; or 'skip']")
                else:
                    say(f"   [{part.unit}; or 'skip']")
                while True:
                    raw = ask("> ").strip()
                    if raw.lower() in {"q", "quit", "exit"}:
                        raise Quit
                    if raw.lower() in {"s", "skip"}:
                        grade_correct, fb, expected, detail = False, "Skipped.", part.display(), (
                            part.detail() if isinstance(part, NumericPart) else "")
                        break
                    g = part.grade(raw)
                    if not g.correct and ("Answer with a letter" in g.feedback or "could not read" in g.feedback):
                        say("   " + g.feedback)  # input error: don't penalise, re-prompt
                        continue
                    grade_correct, fb, expected, detail = g.correct, g.feedback, g.expected, g.detail
                    break
                res.parts_total += 1
                res.by_skill[q.skill][1] += 1
                if grade_correct:
                    res.parts_correct += 1
                    res.by_skill[q.skill][0] += 1
                    say(c("32", "   ✓ " + fb))
                else:
                    all_correct = False
                    say(c("31", "   ✗ " + fb))
                    say(f"   Answer: {expected}")
                if detail:
                    say(c("2", _wrap(detail, "   ")))
                if isinstance(part, ChoicePart) and part.why and len(q.parts) > 1:   # single-part: it is the solution
                    say(_wrap(part.why, "   "))
            if not all_correct:
                res.missed.append(q.id)
            say("")
            say(c("2", "Worked solution"))
            for line in q.solution:
                say(_wrap("• " + line, "  "))
    except (Quit, EOFError, KeyboardInterrupt):
        res.quit_early = True
        say("")
    return res


def print_summary(res: Result, say: Callable[[str], None] = print) -> None:
    say("═" * 60)
    if not res.parts_total:
        say("No questions answered.")
        return
    pct = 100 * res.parts_correct / res.parts_total
    say(f"Score: {res.parts_correct}/{res.parts_total} parts ({pct:.0f}%)" + ("  [ended early]" if res.quit_early else ""))
    for skill, (ok, n) in sorted(res.by_skill.items()):
        say(f"  {skill:<28} {ok}/{n}")
    if res.missed:
        say("Replay what you missed:  rates-trainer --replay " + " --replay ".join(res.missed))
