"""Probability experiments for the market-making game: exact distributions, a hidden outcome tape, and the effects (shocks) that act on them.

A market is on one number, the *answer variable*, built from an experiment by a Target:

    Experiment   a set of independent trials (dice, coins, random integers) or a deck of cards, with a state: which trials are still to be rolled,
                 which are already rolled (hidden) or revealed, and the rules each will follow.
    Target       how the answer is read off the experiment: sum / count of a condition / max / min / sum of the top two; optionally turned into an
                 event, which pays 100 if true and 0 if not (so its price is a probability in percentage points).

Everything the player and the bots can know is a distribution computed *exactly* (fractions, no sampling). The outcome itself is never stored as a number: each
trial has a hidden 53-bit tape value fixed by the seed, and a pending trial is rolled only at resolution, by mapping its tape value through the faces and
weights *in force at that moment*. A rule change therefore re-rolls the unrolled trials under the new rule, and a trial that has been rolled or revealed is
not affected by later rules. Nothing here knows about the game, the player or the bots.

Three kinds of effect, with different semantics (see Effect.category):
    experiment   changes the experiment itself for the trials not yet rolled (restrict faces, change the number of sides, load a face, add or remove trials,
                 remove cards from the deck, change the number of draws).
    information  reveals something true about trials that have *already* been rolled; the experiment and the resolution rule are unchanged.
    resolution   changes how the answer is read off the experiment (the threshold, the condition being counted, which dice count); the dice are unchanged.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product
from typing import Callable

from .rng import U_BITS

PRIMES = (2, 3, 5, 7, 11, 13)
MAX_TRIALS = 12


class EffectError(ValueError):
    """The effect cannot be applied to this state (it would leave nothing to roll, or refers to something that is not there)."""


# ---------------------------------------------------------------- predicates on integer faces

def face_pred(p: dict) -> Callable[[int], bool]:
    k, v = p["kind"], p.get("v")
    return {
        "odd": lambda x: x % 2 == 1, "even": lambda x: x % 2 == 0, "prime": lambda x: x in PRIMES,
        "ge": lambda x: x >= v, "le": lambda x: x <= v, "eq": lambda x: x == v, "ne": lambda x: x != v,
        "mult": lambda x: v is not None and x % v == 0 and x != 0,
    }[k]


def face_pred_text(p: dict) -> str:
    k, v = p["kind"], p.get("v")
    return {"odd": "odd", "even": "even", "prime": "prime (2, 3, 5, 7, 11, 13)", "ge": f"{v} or more", "le": f"{v} or less",
            "eq": f"exactly {v}", "ne": f"anything but {v}", "mult": f"a multiple of {v}"}[k]


# ---------------------------------------------------------------- predicates on cards

SUIT_NAME = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
SUIT_GLYPH = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
RANK_GLYPH = {1: "A", 11: "J", 12: "Q", 13: "K"}


def card_name(c: str) -> str:
    if c.startswith("JK"):
        return "joker"
    return f"{RANK_GLYPH.get(int(c[:-1]), c[:-1])}{SUIT_GLYPH[c[-1]]}"


def card_pred(p: dict) -> Callable[[str], bool]:
    k, v = p["kind"], p.get("v")

    def f(c: str) -> bool:
        if c.startswith("JK"):
            return False
        rank, suit = int(c[:-1]), c[-1]
        return {"suit": suit == v, "color": (suit in "HD") == (v == "red"), "face": rank >= 11, "ace": rank == 1,
                "high": rank >= 10 or rank == 1}[k]
    return f


def card_pred_text(p: dict) -> str:
    k, v = p["kind"], p.get("v")
    return {"suit": SUIT_NAME.get(v, ""), "color": f"{v} cards", "face": "face cards (J, Q, K)", "ace": "aces", "high": "tens, face cards and aces"}[k]


# ---------------------------------------------------------------- target

@dataclass(frozen=True)
class Target:
    """agg: sum | count | max | min | top2. pred (count only): a face predicate (dice) or card predicate (deck). event: {"op": ge|le|eq, "t": int} or None."""
    agg: str
    pred: dict | None = None
    event: dict | None = None

    @property
    def binary(self) -> bool:
        return self.event is not None

    def key(self) -> str:
        return repr((self.agg, sorted((self.pred or {}).items()), sorted((self.event or {}).items())))

    def to_dict(self) -> dict:
        return {"agg": self.agg, "pred": self.pred, "event": self.event}

    @staticmethod
    def from_dict(d: dict) -> "Target":
        return Target(d["agg"], d.get("pred"), d.get("event"))


def event_holds(event: dict, x: int) -> bool:
    return {"ge": x >= event["t"], "le": x <= event["t"], "eq": x == event["t"]}[event["op"]]


def event_text(event: dict) -> str:
    return {"ge": f"is {event['t']} or more", "le": f"is {event['t']} or less", "eq": f"is exactly {event['t']}"}[event["op"]]


# ---------------------------------------------------------------- distributions (exact)

Pmf = dict[int, Fraction]


def mean(p: Pmf) -> Fraction:
    return sum(k * v for k, v in p.items())


def variance(p: Pmf) -> Fraction:
    m = mean(p)
    return sum((k - m) ** 2 * v for k, v in p.items())


def _norm(w: dict[int, int]) -> Pmf:
    t = sum(w.values())
    return {f: Fraction(x, t) for f, x in sorted(w.items())}


def _convolve(a: Pmf, b: Pmf) -> Pmf:
    out: dict[int, Fraction] = {}
    for x, px in a.items():
        for y, py in b.items():
            out[x + y] = out.get(x + y, 0) + px * py
    return out


def agg_pmf(trials: list[Pmf], target: Target) -> Pmf:
    """Distribution of the aggregate of independent trials with the given (already public) distributions."""
    agg = target.agg
    if agg == "sum":
        out: Pmf = {0: Fraction(1)}
        for t in trials:
            out = _convolve(out, t)
    elif agg == "count":
        f = face_pred(target.pred)
        out = {0: Fraction(1)}
        for t in trials:
            p = sum(v for k, v in t.items() if f(k))
            out = _convolve(out, {0: 1 - p, 1: p} if 0 < p < 1 else ({1: Fraction(1)} if p == 1 else {0: Fraction(1)}))
    elif agg in ("max", "min"):
        support = sorted({k for t in trials for k in t})
        cdfs = [{m: sum(v for k, v in t.items() if k <= m) for m in support} for t in trials]
        # P(max <= m) = prod F_i(m);  P(min <= m) = 1 - prod (1 - F_i(m))
        if agg == "max":
            cum = {m: math.prod((c[m] for c in cdfs), start=Fraction(1)) for m in support}
        else:
            cum = {m: 1 - math.prod((1 - c[m] for c in cdfs), start=Fraction(1)) for m in support}
        out, prev = {}, Fraction(0)
        for m in support:
            if cum[m] != prev:
                out[m] = cum[m] - prev
            prev = cum[m]
    elif agg == "top2":
        # exact dynamic programme over the two highest values seen so far: state (highest, second highest), 0 = nothing yet
        state: dict[tuple[int, int], Fraction] = {(0, 0): Fraction(1)}
        for t in trials:
            nxt: dict[tuple[int, int], Fraction] = {}
            for (a, b), pr in state.items():
                for v, pv in t.items():
                    k = (v, a) if v >= a else (a, v) if v >= b else (a, b)
                    nxt[k] = nxt.get(k, 0) + pr * pv
            state = nxt
        out = {}
        for (a, b), pr in state.items():
            out[a + b] = out.get(a + b, 0) + pr
    else:
        raise ValueError(agg)
    return dict(sorted(out.items()))


def apply_event(p: Pmf, target: Target) -> Pmf:
    if not target.binary:
        return p
    yes = sum(v for k, v in p.items() if event_holds(target.event, k))
    return {k: v for k, v in ((0, 1 - yes), (100, yes)) if v}


def aggregate_values(values: list[int], target: Target) -> int:
    """The answer for fixed trial values (used at resolution)."""
    if target.agg == "sum":
        x = sum(values)
    elif target.agg == "count":
        f = face_pred(target.pred)
        x = sum(1 for v in values if f(v))
    elif target.agg == "max":
        x = max(values)
    elif target.agg == "min":
        x = min(values)
    else:
        x = sum(sorted(values, reverse=True)[:2])
    return (100 if event_holds(target.event, x) else 0) if target.binary else x


def pick(weights: dict[int, int], u53: int) -> int:
    """Quantile of the weighted faces at the tape value u53/2^53, in exact integer arithmetic."""
    total, acc = sum(weights.values()), 0
    x = u53 * total
    for face in sorted(weights):
        acc += weights[face]
        if x < acc << U_BITS:
            return face
    return max(weights)


# ---------------------------------------------------------------- dice, coins, random integers

@dataclass
class Trial:
    slot: int                                   # which tape value this trial uses (fixed for its life)
    label: str
    weights: dict[int, int]
    state: str = "pending"                      # pending | rolled (outcome fixed, hidden, may be partly known) | revealed (outcome public)
    value: int | None = None

    def pmf(self) -> Pmf:
        return {self.value: Fraction(1)} if self.state == "revealed" else _norm(self.weights)


def faces_text(w: dict[int, int]) -> str:
    fs = sorted(w)
    runs, start = [], fs[0]
    for a, b in zip(fs, fs[1:] + [None]):
        if b != a + 1:
            runs.append(str(start) if start == a else (f"{start}, {a}" if a == start + 1 else f"{start}–{a}"))
            start = b
    base = min(w.values())
    heavy = [f"{f} is {w[f] // base if w[f] % base == 0 else round(w[f] / base, 1)}× as likely" for f in fs if w[f] > base]
    return ", ".join(runs) + (f" ({'; '.join(heavy)})" if heavy else "")


@dataclass
class DiceExperiment:
    noun: str                                   # die | coin | integer
    base: dict[int, int]                        # the weights new trials start with
    trials: list[Trial]
    tape: tuple[int, ...]                       # hidden 53-bit values, one per slot
    kind: str = "dice"

    # --- what is public
    def signature(self) -> tuple:
        return (self.noun, tuple((t.state, tuple(sorted(t.weights.items())), t.value if t.state == "revealed" else None) for t in self.trials))

    def pmf(self, target: Target) -> Pmf:
        return _cached(("dice", self.signature(), target.key()), lambda: _dice_pmf(self.signature(), target))

    def pending(self) -> list[Trial]:
        return [t for t in self.trials if t.state == "pending"]

    def support(self, target: Target) -> tuple[int, int]:
        p = self.pmf(target)
        return min(p), max(p)

    def describe(self) -> list[str]:
        lines = []
        pend = self.pending()
        if pend:
            groups: dict[str, int] = {}
            for t in pend:
                groups[faces_text(t.weights)] = groups.get(faces_text(t.weights), 0) + 1
            for ft, n in groups.items():
                if self.noun == "coin":
                    lines.append(f"{n} {self._noun(n)} still to be flipped at resolution (heads = 1, tails = 0; faces {ft}).")
                else:
                    lines.append(f"{n} {self._noun(n)} still to be rolled at resolution: faces {ft}.")
        for t in self.trials:
            if t.state == "revealed":
                lines.append(f"{t.label} has been rolled: {t.value}.")
            elif t.state == "rolled":
                lines.append(f"{t.label} has been rolled; all that is known is that it is one of {faces_text(t.weights)}.")
        return lines

    def _noun(self, n: int) -> str:
        return {"die": ("die", "dice"), "coin": ("coin", "coins"), "integer": ("random integer", "random integers")}[self.noun][0 if n == 1 else 1]

    # --- the hidden outcome
    def values(self) -> list[int]:
        return [t.value if t.state != "pending" else pick(t.weights, self.tape[t.slot]) for t in self.trials]

    def realise(self, target: Target) -> int:
        return aggregate_values(self.values(), target)

    # --- effects
    def apply(self, effect: "Effect") -> str:
        return effect.apply_experiment(self)

    def _roll(self, t: Trial) -> int:
        return pick(t.weights, self.tape[t.slot])


_CACHE: dict = {}


def _cached(key: tuple, make: Callable[[], Pmf]) -> Pmf:
    """Distributions are pure functions of public state, so they are cached (the bots ask for them every round); bounded, cleared when full."""
    hit = _CACHE.get(key)
    if hit is None:
        if len(_CACHE) > 20000:
            _CACHE.clear()
        hit = _CACHE[key] = make()
    return hit


def _dice_pmf(sig: tuple, target: Target) -> Pmf:
    trials = []
    for state, weights, value in sig[1]:
        trials.append({value: Fraction(1)} if state == "revealed" else _norm(dict(weights)))
    return apply_event(agg_pmf(trials, target), target)


# ---------------------------------------------------------------- a deck of cards

ALL_CARDS = tuple(f"{r}{s}" for s in "SHDC" for r in range(1, 14)) + ("JK1", "JK2")


@dataclass
class DeckExperiment:
    draws: int                                  # cards drawn in all, including those already seen
    order: tuple[str, ...]                      # hidden shuffled order of every card that could ever be in the deck
    jokers_in: int = 0
    removed: set[str] = field(default_factory=set)
    seen: list[str] = field(default_factory=list)
    kind: str = "deck"

    def active(self) -> list[str]:
        return [c for c in self.order if c not in self.removed and c not in self.seen and (not c.startswith("JK") or int(c[2:]) <= self.jokers_in)]

    def signature(self) -> tuple:
        return ("deck", self.draws, self.jokers_in, tuple(sorted(self.removed)), tuple(self.seen))

    def left(self) -> int:
        return self.draws - len(self.seen)

    def pmf(self, target: Target) -> Pmf:
        return _cached(("deck", self.signature(), target.key()), lambda: _deck_pmf(self.signature(), target))

    def support(self, target: Target) -> tuple[int, int]:
        p = self.pmf(target)
        return min(p), max(p)

    def describe(self) -> list[str]:
        act = self.active()
        lines = [f"{self.draws} cards are drawn without replacement from a shuffled deck; {self.left()} still to be drawn from the {len(act)} cards left in it."]
        removed = sorted(self.removed, key=lambda c: ALL_CARDS.index(c))
        if removed and len(removed) <= 6:
            lines.append("Taken out of the deck: " + ", ".join(card_name(c) for c in removed) + ".")
        elif removed:
            lines.append(f"{len(removed)} cards have been taken out of the deck.")
        if self.jokers_in:
            lines.append(f"{self.jokers_in} joker{'s' if self.jokers_in > 1 else ''} added to the deck (a joker matches no suit, colour or rank).")
        if self.seen:
            lines.append("Already drawn: " + ", ".join(card_name(c) for c in self.seen) + ".")
        return lines

    def values(self) -> list[str]:
        return self.seen + self.active()[: self.left()]

    def realise(self, target: Target) -> int:
        f = card_pred(target.pred)
        x = sum(1 for c in self.values() if f(c))
        return (100 if event_holds(target.event, x) else 0) if target.binary else x

    def apply(self, effect: "Effect") -> str:
        return effect.apply_experiment(self)


def _hyper(N: int, K: int, m: int) -> Pmf:
    den = math.comb(N, m)
    return {j: Fraction(math.comb(K, j) * math.comb(N - K, m - j), den) for j in range(max(0, m - (N - K)), min(K, m) + 1)}


def _deck_pmf(sig: tuple, target: Target) -> Pmf:
    _, draws, jokers_in, removed, seen = sig
    f = card_pred(target.pred)
    active = [c for c in ALL_CARDS if c not in removed and c not in seen and (not c.startswith("JK") or int(c[2:]) <= jokers_in)]
    m = draws - len(seen)
    base = sum(1 for c in seen if f(c))
    h = _hyper(len(active), sum(1 for c in active if f(c)), m)
    return apply_event({base + j: p for j, p in h.items()}, target)


Experiment = DiceExperiment | DeckExperiment


def mean_sd(exp, target: Target) -> tuple[Fraction, float]:
    p = exp.pmf(target)
    return mean(p), math.sqrt(float(variance(p)))


# ---------------------------------------------------------------- effects

class Effect:
    """category: experiment | information | resolution. scope: where it is applied. Subclasses implement apply_experiment or apply_target and return the public text."""
    category = "experiment"
    scope = "experiment"
    kind = ""
    experiments: tuple[str, ...] = ("dice",)

    def apply_experiment(self, exp) -> str:
        raise EffectError("not an experiment effect")

    def apply_target(self, target: Target, exp) -> tuple[Target, str]:
        raise EffectError("not a resolution effect")

    def to_dict(self) -> dict:
        return {"kind": self.kind, **{k: v for k, v in self.__dict__.items()}}


def _need_pending(exp: DiceExperiment) -> list[Trial]:
    pend = exp.pending()
    if not pend:
        raise EffectError("every trial has already been rolled")
    return pend


@dataclass
class RestrictFaces(Effect):
    """The faces the unrolled trials can show are cut down by a rule: 'No odd numbers', 'No numbers from 1 to 4'."""
    rule: dict
    category = "experiment"
    kind = "restrict_faces"

    def apply_experiment(self, exp):
        keep = face_pred(self.rule)
        pend = _need_pending(exp)
        gone: set[int] = set()
        for t in pend:
            new = {f: w for f, w in t.weights.items() if keep(f)}
            if not new:
                raise EffectError("no face would be left")
            gone |= set(t.weights) - set(new)
            t.weights = new
        if not gone:
            raise EffectError("no face is removed")
        names = {"even": "No odd numbers", "odd": "No even numbers", "ge": f"No numbers below {self.rule.get('v')}", "le": f"No numbers above {self.rule.get('v')}",
                 "ne": f"The {self.rule.get('v')} is removed"}
        k = len(pend)
        return f"{names[self.rule['kind']]}: the {k} {exp._noun(k)} not yet rolled can no longer show {', '.join(str(f) for f in sorted(gone))}. Each now shows one of the remaining faces with equal chance."


@dataclass
class SetSides(Effect):
    sides: int
    category = "experiment"
    kind = "set_sides"

    def apply_experiment(self, exp):
        if exp.noun == "coin":
            raise EffectError("a coin has two sides")
        pend = _need_pending(exp)
        old = max(max(t.weights) for t in pend)
        if self.sides == old:
            raise EffectError("no change")
        for t in pend:
            t.weights = {f: 1 for f in range(1, self.sides + 1)}
        exp.base = {f: 1 for f in range(1, self.sides + 1)}
        k = len(pend)
        return f"Range change: the {k} {exp._noun(k)} not yet rolled now have faces 1–{self.sides} instead of 1–{old}."


@dataclass
class LoadFace(Effect):
    face: int
    factor: int
    category = "experiment"
    kind = "load_face"

    def apply_experiment(self, exp):
        pend = _need_pending(exp)
        hit = [t for t in pend if self.face in t.weights]
        if not hit:
            raise EffectError("face not present")
        for t in hit:
            t.weights = {**t.weights, self.face: t.weights[self.face] * self.factor}
        what = "heads" if exp.noun == "coin" and self.face == 1 else ("tails" if exp.noun == "coin" else f"the {self.face}")
        k = len(hit)
        return f"Loaded: {what} is now {self.factor}× as likely as before on the {k} {exp._noun(k)} not yet rolled."


@dataclass
class AddTrials(Effect):
    n: int
    category = "experiment"
    kind = "add_trials"

    def apply_experiment(self, exp):
        if len(exp.trials) + self.n > MAX_TRIALS or len(exp.trials) + self.n > len(exp.tape):
            raise EffectError("too many trials")
        for _ in range(self.n):
            slot = len(exp.trials)
            exp.trials.append(Trial(slot, f"{exp.noun.capitalize()} {slot + 1}", dict(exp.base)))
        return f"{self.n} more {exp._noun(self.n)} will be rolled at resolution (faces {faces_text(exp.base)}); the existing ones are unchanged."


@dataclass
class RemoveTrials(Effect):
    n: int
    category = "experiment"
    kind = "remove_trials"

    def apply_experiment(self, exp):
        pend = _need_pending(exp)
        if len(pend) < self.n or len(exp.trials) - self.n < 1:
            raise EffectError("cannot remove that many")
        for t in pend[-self.n:]:
            exp.trials.remove(t)
        return f"{self.n} {exp._noun(self.n)} will not be rolled after all; the rest are unchanged."


@dataclass
class RevealTrials(Effect):
    """Hard information: the first n unrolled trials are rolled now and their results shown. The experiment and the resolution rule are unchanged."""
    n: int
    category = "information"
    kind = "reveal_trials"

    def apply_experiment(self, exp):
        pend = _need_pending(exp)
        if self.n > len(pend):
            raise EffectError("not enough trials")
        done = []
        for t in pend[: self.n]:
            t.value, t.state = exp._roll(t), "revealed"
            done.append(f"{t.label} shows {t.value}")
        return "Information: " + "; ".join(done) + ". Nothing else has changed: the other trials are still to be rolled under the same rules."


@dataclass
class RevealClass(Effect):
    """Partial information: the first unrolled trial is rolled now, and the public learns which half of its faces it is in (parity or high/low)."""
    how: str                                    # parity | half
    category = "information"
    kind = "reveal_class"

    def apply_experiment(self, exp):
        t = _need_pending(exp)[0]
        faces = sorted(t.weights)
        if len(faces) < 2:
            raise EffectError("nothing to learn")
        v = exp._roll(t)
        if self.how == "parity":
            keep = {f: w for f, w in t.weights.items() if (f % 2) == (v % 2)}
            said = "odd" if v % 2 else "even"
        else:
            cut = faces[(len(faces) - 1) // 2]
            low = v <= cut
            keep = {f: w for f, w in t.weights.items() if (f <= cut) == low}
            said = f"{faces[0]}–{cut}" if low else f"{faces[(len(faces) - 1) // 2 + 1]}–{faces[-1]}"
        if len(keep) == len(t.weights):
            raise EffectError("uninformative")
        t.weights, t.state, t.value = keep, "rolled", v
        return f"Information: {t.label} has been rolled and is {said}. Its exact value is not shown, and nothing else has changed."


@dataclass
class SetThreshold(Effect):
    """Resolution change: the event (or the counted condition) uses a different threshold. The dice are unchanged."""
    t: int
    category = "resolution"
    scope = "market"
    kind = "set_threshold"
    experiments = ("dice", "deck")

    def apply_target(self, target, exp):
        if target.event:
            if target.event["t"] == self.t:
                raise EffectError("no change")
            old = target.event["t"]
            new = Target(target.agg, target.pred, {**target.event, "t": self.t})
            return new, f"Resolution change: the event now {event_text(new.event)} (it was {old}). The experiment itself is unchanged."
        if target.pred and target.pred["kind"] in ("ge", "le") and target.pred["v"] != self.t:
            old = target.pred["v"]
            new = Target(target.agg, {**target.pred, "v": self.t})
            return new, f"Resolution change: results now count if they are {face_pred_text(new.pred)} (it was {old}). The dice are unchanged."
        raise EffectError("no threshold to change")


@dataclass
class SetPred(Effect):
    """Resolution change: a different condition is counted (e.g. odd results become results of 5 or more)."""
    pred: dict
    category = "resolution"
    scope = "market"
    kind = "set_pred"
    experiments = ("dice",)

    def apply_target(self, target, exp):
        if target.agg != "count" or target.pred == self.pred:
            raise EffectError("nothing to change")
        return Target("count", self.pred, target.event), (f"Resolution change: the market now counts results that are {face_pred_text(self.pred)} "
                                                           f"instead of {face_pred_text(target.pred)}. The dice are unchanged.")


@dataclass
class SetAgg(Effect):
    """Resolution change: a different way of reading the dice (the sum now counts only the highest two dice)."""
    agg: str
    category = "resolution"
    scope = "market"
    kind = "set_agg"
    experiments = ("dice",)

    def apply_target(self, target, exp):
        if target.agg != "sum" or self.agg != "top2" or len(exp.trials) < 3:
            raise EffectError("not applicable")
        return Target("top2", None, target.event), "Resolution change: the answer is now the sum of the HIGHEST TWO dice only (it was the sum of all). The dice are unchanged."


@dataclass
class RemoveCards(Effect):
    pred: dict
    category = "experiment"
    kind = "remove_cards"
    experiments = ("deck",)

    def apply_experiment(self, exp):
        f = card_pred(self.pred)
        gone = [c for c in exp.active() if f(c)]
        if not gone or len(exp.active()) - len(gone) < exp.left():
            raise EffectError("cannot remove")
        exp.removed |= set(gone)
        return f"Deck change: all {card_pred_text(self.pred)} still in the deck ({len(gone)} cards) are taken out before the draw."


@dataclass
class AddJokers(Effect):
    n: int
    category = "experiment"
    kind = "add_jokers"
    experiments = ("deck",)

    def apply_experiment(self, exp):
        if exp.jokers_in + self.n > 2:
            raise EffectError("no more jokers")
        exp.jokers_in += self.n
        return f"Deck change: {self.n} joker{'s' if self.n > 1 else ''} shuffled into the deck (a joker matches no suit, colour or rank)."


@dataclass
class ChangeDraws(Effect):
    delta: int
    category = "experiment"
    kind = "change_draws"
    experiments = ("deck",)

    def apply_experiment(self, exp):
        new = exp.draws + self.delta
        if new < len(exp.seen) + 1 or new > len(exp.active()) + len(exp.seen):
            raise EffectError("invalid number of draws")
        exp.draws = new
        return f"Draw change: {abs(self.delta)} {'more' if self.delta > 0 else 'fewer'} card{'s' if abs(self.delta) > 1 else ''} will be drawn ({new} in all)."


@dataclass
class RevealCards(Effect):
    n: int
    category = "information"
    kind = "reveal_cards"
    experiments = ("deck",)

    def apply_experiment(self, exp):
        if self.n > exp.left() - 0 or self.n < 1:
            raise EffectError("not enough draws left")
        drawn = exp.active()[: self.n]
        exp.seen = exp.seen + drawn
        return "Information: the first " + (f"{self.n} cards drawn are " if self.n > 1 else "card drawn is ") + ", ".join(card_name(c) for c in drawn) + \
               ". They count towards the draw; the rest is still to come from the cards left, under the same rules."


@dataclass
class SetSpecial(Effect):
    pred: dict
    category = "resolution"
    scope = "market"
    kind = "set_special"
    experiments = ("deck",)

    def apply_target(self, target, exp):
        if target.pred == self.pred:
            raise EffectError("no change")
        return Target("count", self.pred, target.event), (f"Resolution change: the market now counts {card_pred_text(self.pred)} instead of "
                                                          f"{card_pred_text(target.pred)}. The deck is unchanged.")


EFFECT_TYPES = {c.kind: c for c in (RestrictFaces, SetSides, LoadFace, AddTrials, RemoveTrials, RevealTrials, RevealClass, SetThreshold, SetPred, SetAgg,
                                    RemoveCards, AddJokers, ChangeDraws, RevealCards, SetSpecial)}


def effect_from_dict(d: dict) -> Effect:
    d = dict(d)
    return EFFECT_TYPES[d.pop("kind")](**d)


def try_apply(exp, target: Target, effect: Effect) -> tuple[object, Target] | None:
    """Apply an effect to *copies*; return (experiment, target) after it, or None when it cannot apply or leaves a degenerate (certain) answer."""
    e2 = copy.deepcopy(exp)
    t2 = target
    try:
        if effect.scope == "experiment":
            if e2.kind not in effect.experiments:
                return None
            e2.apply(effect)
        else:
            if e2.kind not in effect.experiments:
                return None
            t2, _ = effect.apply_target(target, e2)
        p = e2.pmf(t2)
    except EffectError:
        return None
    return (e2, t2) if len(p) > 1 else None


def build_dice(noun: str, sides: int | dict, n: int, tape: list[int], weights: dict | None = None) -> DiceExperiment:
    base = dict(weights) if weights else ({0: 1, 1: 1} if noun == "coin" else {f: 1 for f in range(1, sides + 1)})
    return DiceExperiment(noun, base, [Trial(i, f"{noun.capitalize()} {i + 1}", dict(base)) for i in range(n)], tuple(tape))


def build_deck(draws: int, order: list[str]) -> DeckExperiment:
    return DeckExperiment(draws, tuple(order))
