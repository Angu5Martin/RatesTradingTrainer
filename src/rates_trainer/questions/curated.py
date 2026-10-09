"""Curated conceptual questions, authored as data in curriculum/curated/*.toml.

Schema (one [[question]] table per item):
    id         unique slug
    skill      skill id from curriculum.skills
    difficulty 1-3
    stem       scenario / question text
    options    list of strings; the FIRST is the correct one (order is shuffled per seed)
    why        explanation shown after answering
"""

from __future__ import annotations

import random
import tomllib
from importlib import resources

from .model import ChoicePart, QuestionBody
from .registry import TemplateSpec, register


def load_curated() -> list[dict]:
    items: list[dict] = []
    root = resources.files("rates_trainer.curriculum") / "curated"
    for f in sorted(root.iterdir(), key=lambda p: p.name):
        if f.name.endswith(".toml"):
            items.extend(tomllib.loads(f.read_text(encoding="utf-8")).get("question", []))
    return items


def _make(item: dict):
    def gen(rng: random.Random) -> QuestionBody:
        opts = list(item["options"])
        correct_text = opts[0]
        rng.shuffle(opts)
        part = ChoicePart(item.get("ask", "Which is correct?"), opts, opts.index(correct_text), item["why"])
        return QuestionBody(item["stem"], [part], [item["why"]])

    return gen


def register_curated() -> None:
    for item in load_curated():
        register(TemplateSpec(f"curated.{item['id']}", item["skill"], int(item["difficulty"]),
                              _make(item), curated=True))
