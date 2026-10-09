"""World-knowledge markets: a curated bank of numeric facts, and the model of what everybody can know about one.

A world market is on a number with an objective answer (a year, a count, a height). The *public belief* is the crowd's: a normal distribution around a guess that is
off from the truth by a random amount of about one "spread" (the typical error of an informed guess), cut off to the settlement range and to whatever clues have
been confirmed. That belief is what the value-style bots trade on and what the debrief calls fair value. The player may know better; whoever does is paid for it.

Two effects act on a world market, the same two categories as in probability.py:
    Clue              information: a statement that is TRUE of the answer is confirmed ("at least 1800"); the threshold is chosen from the public guess, never from the answer,
                      so the statement is a fair partition and the truncated belief is the right update.
    AltResolution     resolution: the market is redefined to a nearby version of the same fact (the date of entry into force instead of signing; the count with Pluto);
                      the fact itself is unchanged, only what the market settles on. Items without an alt cannot have one.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from .probability import Effect, EffectError

DATA = Path(__file__).with_name("data") / "world_questions.toml"
GRID = 401


def fmt_num(x: Fraction | float | int, places: int = 6) -> str:
    """A number as the player would write it: no trailing zeros ('8848.86', '1789')."""
    f = Fraction(x).limit_denominator(10 ** places)
    s = f"{float(f):.{places}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


@dataclass(frozen=True)
class WorldItem:
    id: str
    category: str
    difficulty: int
    question: str
    unit: str
    answer: Fraction
    lo: Fraction
    hi: Fraction
    spread: float
    tick: Fraction
    rule: str
    source: str
    as_of: str
    alt: dict | None = None                     # {rule, answer, as_of}
    added: int = 1                              # the bank version that introduced it (see bank_items)


@lru_cache(maxsize=1)
def load_bank() -> tuple[WorldItem, ...]:
    raw = tomllib.loads(DATA.read_text(encoding="utf-8"))["item"]
    out = []
    for r in raw:
        alt = r.get("alt")
        out.append(WorldItem(r["id"], r["category"], int(r["difficulty"]), r["question"], r["unit"], Fraction(r["answer"]), Fraction(r["lo"]), Fraction(r["hi"]),
                             float(r["spread"]), Fraction(r["tick"]), r["rule"], r["source"], r["as_of"],
                             {"rule": alt["rule"], "answer": Fraction(alt["answer"]), "as_of": alt["as_of"]} if alt else None, int(r.get("added", 1))))
    return tuple(out)


def latest_bank() -> int:
    return max(i.added for i in load_bank())


def bank_items(version: int | None = None) -> tuple[WorldItem, ...]:
    """The items of a bank version: every item added at or before it, in file order. A game is dealt from one version and remembers it, so growing the bank never
    changes the table a saved game replays (the originals keep their order and the selection only ever sees the items of its own version)."""
    v = latest_bank() if version is None else version
    return tuple(i for i in load_bank() if i.added <= v)


def bank_by_id() -> dict[str, WorldItem]:
    return {i.id: i for i in load_bank()}


class WorldModel:
    kind = "world"

    def __init__(self, item: WorldItem, z: float, z_alt: float = 0.0):
        self.item = item
        self.rule, self.answer, self.as_of = item.rule, item.answer, item.as_of
        self.z, self.z_alt = z, z_alt
        self.floor: Fraction | None = None      # confirmed: answer >= floor
        self.ceil: Fraction | None = None       # confirmed: answer < ceil
        self.alt_used = False
        self.clues: list[str] = []

    @property
    def mu(self) -> float:
        z = self.z_alt if self.alt_used else self.z
        return min(max(float(self.answer) + self.item.spread * z, float(self.item.lo)), float(self.item.hi))

    def bounds(self) -> tuple[float, float]:
        a, b = float(self.item.lo), float(self.item.hi)
        if self.floor is not None:
            a = max(a, float(self.floor))
        if self.ceil is not None:
            b = min(b, float(self.ceil))
        return a, b

    def belief(self) -> tuple[Fraction, float]:
        """Mean and standard deviation of the public belief: the crowd's normal, truncated to what is known."""
        a, b = self.bounds()
        if b - a < 1e-9:
            return Fraction(a).limit_denominator(10 ** 6), 0.0
        xs = [a + (b - a) * i / (GRID - 1) for i in range(GRID)]
        sd = self.item.spread
        z2 = [((x - self.mu) / sd) ** 2 for x in xs]
        m = min(z2)
        w = [math.exp(-0.5 * (z - m)) for z in z2]
        tot = sum(w)
        mean = sum(x * wi for x, wi in zip(xs, w)) / tot
        var = sum((x - mean) ** 2 * wi for x, wi in zip(xs, w)) / tot
        return Fraction(mean).limit_denominator(10 ** 6), math.sqrt(var)

    def mean(self) -> Fraction:
        return self.belief()[0]

    def support(self) -> tuple[Fraction, Fraction]:
        a, b = self.bounds()
        return Fraction(a).limit_denominator(10 ** 6), Fraction(b).limit_denominator(10 ** 6)

    def realise(self) -> Fraction:
        return self.answer

    def describe(self) -> list[str]:
        lines = [f"Settles on the true value of: {self.rule}"]
        lines += self.clues
        return lines

    def apply(self, effect: Effect) -> str:
        return effect.apply_world(self)


@dataclass
class Clue(Effect):
    direction: str                              # ge | lt
    bound: str                                  # a Fraction as text
    category = "information"
    scope = "experiment"
    kind = "clue"
    experiments = ("world",)

    def apply_world(self, m: WorldModel) -> str:
        b = Fraction(self.bound)
        lo, hi = m.item.lo, m.item.hi
        if self.direction == "ge":
            if m.floor is not None and b <= m.floor or b <= lo:
                raise EffectError("no information")
            m.floor = b
            said = f"at least {fmt_num(b)}"
        else:
            if m.ceil is not None and b >= m.ceil or b >= hi:
                raise EffectError("no information")
            m.ceil = b
            said = f"below {fmt_num(b)}"
        if not (m.floor is None or m.ceil is None or m.floor < m.ceil):
            raise EffectError("inconsistent")
        m.clues.append(f"Confirmed: the answer is {said}.")
        return f"Information: it is confirmed that the answer is {said} ({m.item.unit or 'the value'}). The question and the way it settles are unchanged."


@dataclass
class AltResolution(Effect):
    category = "resolution"
    scope = "market"
    kind = "alt_resolution"
    experiments = ("world",)

    def apply_world(self, m: WorldModel) -> str:
        alt = m.item.alt
        if alt is None or m.alt_used:
            raise EffectError("no alternative resolution")
        m.alt_used = True
        m.rule, m.answer, m.as_of = alt["rule"], alt["answer"], alt["as_of"]
        m.floor = m.ceil = None
        m.clues = []
        return f"Resolution change: the market is redefined. It now settles on: {m.rule} The underlying facts are unchanged, and earlier clues no longer apply."


def world_effect_from_dict(d: dict) -> Effect:
    d = dict(d)
    k = d.pop("kind")
    return {"clue": Clue, "alt_resolution": AltResolution}[k](**d)
