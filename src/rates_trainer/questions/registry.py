"""Template registry: every question source (Python template or curated TOML) is a TemplateSpec.

A question is fully determined by (template_id, seed), so any question the trainer has
ever shown can be regenerated exactly -- useful for review and for bug reports.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Iterable

from .model import Question, QuestionBody

Generator = Callable[[random.Random], QuestionBody]


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    skill: str
    difficulty: int  # 1 = single concept, 2 = concept + calculation, 3 = multi-step trading situation
    fn: Generator
    curated: bool = False


_REGISTRY: dict[str, TemplateSpec] = {}
_LOADED = False


def register(spec: TemplateSpec) -> None:
    if spec.id in _REGISTRY:
        raise ValueError(f"duplicate template id {spec.id}")
    _REGISTRY[spec.id] = spec


def template(id: str, skill: str, difficulty: int = 1) -> Callable[[Generator], Generator]:
    """Decorator registering a parameterised template."""

    def deco(fn: Generator) -> Generator:
        register(TemplateSpec(id, skill, difficulty, fn))
        return fn

    return deco


def load_all() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True  # set first: the imports below call back into register()
    from . import templates  # noqa: F401  (import side effect: registers templates)
    from .curated import register_curated

    register_curated()


def all_specs() -> list[TemplateSpec]:
    load_all()
    return sorted(_REGISTRY.values(), key=lambda s: s.id)


def get_spec(template_id: str) -> TemplateSpec:
    load_all()
    try:
        return _REGISTRY[template_id]
    except KeyError:
        raise KeyError(f"unknown template {template_id!r}") from None


def generate(template_id: str, seed: int) -> Question:
    spec = get_spec(template_id)
    rng = random.Random(f"{spec.id}:{seed}")
    body = spec.fn(rng)
    return Question(spec.id, seed, spec.skill, spec.difficulty, body.stem, body.parts, body.solution, body.facts)


def from_id(question_id: str) -> Question:
    """Regenerate from 'template_id#seed'."""
    tid, _, seed = question_id.rpartition("#")
    return generate(tid, int(seed))


def select(
    specs: Iterable[TemplateSpec],
    tracks: set[str] | None = None,
    skills: set[str] | None = None,
    difficulty: int | None = None,
    max_difficulty: int | None = None,
) -> list[TemplateSpec]:
    out = []
    for s in specs:
        if tracks and s.skill.split(".")[0] not in tracks:
            continue
        if skills and s.skill not in skills:
            continue
        if difficulty is not None and s.difficulty != difficulty:
            continue
        if max_difficulty is not None and s.difficulty > max_difficulty:
            continue
        out.append(s)
    return out
