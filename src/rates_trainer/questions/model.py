"""Question data model and grading. UI-agnostic: a Question is plain data plus grade()."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Grade:
    correct: bool
    feedback: str
    expected: str  # human-readable expected answer
    detail: str = ""  # e.g. first-order estimate vs full revaluation


@dataclass(frozen=True)
class Tolerance:
    """A numeric answer is accepted if |got - expected| <= max(rel*|expected|, abs)."""

    rel: float = 0.03
    abs: float = 0.0

    def allows(self, got: float, expected: float) -> bool:
        return abs(got - expected) <= max(self.rel * abs(expected), self.abs) + 1e-12


_SUFFIX = {"k": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9}
_NUM = re.compile(r"^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([a-z]*)\s*$")


def parse_number(raw: str, bare_scale: float = 1.0) -> float:
    """Parse '-225k', '€1.2m', '0.8mm', '2.845%', '3bp', '1,250,000'.

    A number typed with no suffix is multiplied by bare_scale (e.g. 1e6 when the
    question asks for 'EUR m'). '%' and 'bp' suffixes are accepted and ignored.
    """
    s = raw.strip().lower().replace(",", "").replace("€", "").replace("eur", "").replace("−", "-")
    s = s.replace("%", "").replace("bps", "").replace("bp", "").strip()
    m = _NUM.match(s)
    if not m:
        raise ValueError(f"could not read a number from {raw!r}")
    value, suffix = float(m.group(1)), m.group(2)
    if suffix == "":
        return value * bare_scale
    if suffix in _SUFFIX:
        return value * _SUFFIX[suffix]
    raise ValueError(f"unknown suffix {suffix!r} in {raw!r}")


def fmt_eur(x: float, signed: bool = True) -> str:
    a = abs(x)
    if a < 0.5:
        return "€0"                     # a true zero, not "-€0" from float noise
    sign = "-" if x < 0 else ("+" if signed and x > 0 else "")
    if a >= 1e6:
        body = f"{a / 1e6:,.2f}m"
    elif a >= 1e3:
        body = f"{a / 1e3:,.1f}k"
    else:
        body = f"{a:,.0f}"
    return f"{sign}€{body}"


@dataclass
class NumericPart:
    prompt: str
    answer: float
    tol: Tolerance = field(default_factory=Tolerance)
    unit: str = "EUR"          # "EUR", "bp", "%", "years", "x" ...
    bare_scale: float = 1.0    # multiplier for answers typed without a suffix
    sign_hint: str = ""        # shown when the magnitude is right but the sign is wrong
    note: str = ""             # input-format hint shown under the prompt
    # `answer` is the PRECISE value (full revaluation / exact formula) and is what the tests validate.
    # `approx` is the fast first-order estimate a trader does in their head (e.g. -DV01 x move).
    # When set and accept_approx is True, an answer matching either is correct. The solution always
    # shows both, so the size of the approximation error is part of the lesson.
    approx: float | None = None
    approx_label: str = "first-order estimate (-DV01 x move)"
    accept_approx: bool = True

    kind = "numeric"

    def display(self, value: float | None = None) -> str:
        v = self.answer if value is None else value
        if self.unit == "EUR":
            return fmt_eur(v)
        if self.unit == "%":
            return f"{v:.3f}%"
        if self.unit == "bp":
            return f"{v:+.2f}bp"
        if self.unit == "cf":
            return f"{v:.6f}"
        if self.unit == "pts":
            return f"{v:,.3f} pts"
        if self.unit == "contracts":
            return f"{v:,.0f} contracts"
        return f"{v:,.3f} {self.unit}".strip()

    def detail(self) -> str:
        """First-order vs precise, with the gap. Empty if the part has no first-order route."""
        if self.approx is None:
            return ""
        gap = self.answer - self.approx
        rel = f" ({gap / self.answer * 100:+.1f}% of the precise figure)" if abs(self.answer) > 1e-9 else ""
        return (f"{self.approx_label}: {self.display(self.approx)} | precise: {self.display()} | "
                f"difference {self.display(gap)}{rel}")

    def _targets(self) -> list[float]:
        t = [self.answer]
        if self.approx is not None and self.accept_approx:
            t.append(self.approx)
        return t

    def grade(self, raw: str) -> Grade:
        expected, detail = self.display(), self.detail()
        try:
            got = parse_number(raw, self.bare_scale)
        except ValueError as e:
            return Grade(False, str(e), expected, detail)
        targets = self._targets()
        if any(self.tol.allows(got, e) for e in targets):
            return Grade(True, "Correct.", expected, detail)
        if any(e != 0 and self.tol.allows(-got, e) for e in targets):
            hint = f" {self.sign_hint}" if self.sign_hint else ""
            return Grade(False, f"Right size, wrong sign.{hint}", expected, detail)
        if got != 0:
            for factor, label in ((1e3, "1000x too large"), (1e-3, "1000x too small"),
                                  (1e2, "100x too large"), (1e-2, "100x too small"),
                                  (10, "10x too large"), (0.1, "10x too small")):
                if any(e != 0 and self.tol.allows(got / factor, e) for e in targets):
                    return Grade(False, f"Check units: that looks {label}.", expected, detail)
        return Grade(False, "Not quite.", expected, detail)


@dataclass
class ChoicePart:
    prompt: str
    options: list[str]
    correct: int
    why: str = ""

    kind = "choice"

    def display(self) -> str:
        return f"{chr(65 + self.correct)}. {self.options[self.correct]}"

    def grade(self, raw: str) -> Grade:
        s = raw.strip().upper().rstrip(".)")
        idx = None
        if len(s) == 1 and "A" <= s <= chr(64 + len(self.options)):
            idx = ord(s) - 65
        elif s.isdigit() and 1 <= int(s) <= len(self.options):
            idx = int(s) - 1
        if idx is None:
            return Grade(False, f"Answer with a letter A-{chr(64 + len(self.options))}.", self.display())
        if idx == self.correct:
            return Grade(True, "Correct.", self.display())
        return Grade(False, "Not quite.", self.display())


Part = NumericPart | ChoicePart


def shuffled_choice(rng, prompt: str, options: list[str], why: str = "") -> ChoicePart:
    """ChoicePart from options whose FIRST entry is correct; order is shuffled by rng."""
    correct_text = options[0]
    opts = list(options)
    rng.shuffle(opts)
    return ChoicePart(prompt, opts, opts.index(correct_text), why)


@dataclass
class Question:
    template_id: str
    seed: int
    skill: str
    difficulty: int
    stem: str
    parts: list[Part]
    solution: list[str]
    facts: dict = field(default_factory=dict)  # generation inputs/outputs, for independent tests

    @property
    def id(self) -> str:
        """Reproducible handle: regenerate with registry.generate(template_id, seed)."""
        return f"{self.template_id}#{self.seed}"


@dataclass
class QuestionBody:
    """What a template produces; the registry adds identity (template id, seed, skill)."""

    stem: str
    parts: list[Part]
    solution: list[str]
    facts: dict = field(default_factory=dict)
