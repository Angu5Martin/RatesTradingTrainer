import pytest

from rates_trainer.questions.model import ChoicePart, NumericPart, Tolerance, fmt_eur, parse_number


@pytest.mark.parametrize("raw,scale,expected", [
    ("225k", 1, 225e3), ("-225K", 1, -225e3), ("€1.2m", 1, 1.2e6), ("0.8mm", 1, 0.8e6),
    ("2.845%", 1, 2.845), ("3bp", 1, 3.0), ("1,250,000", 1, 1.25e6), ("−40k", 1, -40e3),
    ("300", 1e6, 300e6), ("300m", 1e6, 300e6), ("1.5bn", 1, 1.5e9), ("+12", 1, 12.0),
])
def test_parse_number(raw, scale, expected):
    assert parse_number(raw, scale) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "abc", "12x", "k"])
def test_parse_number_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_number(raw)


def test_numeric_grading_tolerance_and_feedback():
    p = NumericPart("x", 215_000, Tolerance(rel=0.03), "EUR", sign_hint="Receivers are long.")
    assert p.grade("215k").correct
    assert p.grade("220k").correct             # +2.3%
    assert not p.grade("230k").correct         # +7%
    g = p.grade("-215k")
    assert not g.correct and "wrong sign" in g.feedback and "Receivers are long." in g.feedback
    g = p.grade("215m")
    assert not g.correct and "1000x" in g.feedback
    g = p.grade("2.15m")
    assert not g.correct and "10x" in g.feedback
    assert not p.grade("nonsense").correct


def test_numeric_negative_expected_and_abs_tolerance():
    p = NumericPart("x", -100.0, Tolerance(rel=0.0, abs=5), "EUR")
    assert p.grade("-104").correct and not p.grade("-110").correct
    z = NumericPart("x", 0.0, Tolerance(rel=0.0, abs=50), "EUR")
    assert z.grade("30").correct and not z.grade("100").correct


def test_bare_scale():
    p = NumericPart("x", 300e6, Tolerance(rel=0.01), "EUR", bare_scale=1e6)
    assert p.grade("300").correct and p.grade("300m").correct


def test_choice_grading():
    c = ChoicePart("q", ["a", "b", "c"], 1, "because")
    assert c.grade("B").correct and c.grade("b.").correct and c.grade("2").correct
    assert not c.grade("A").correct
    assert "A-C" in c.grade("zzz").feedback


def test_fmt_eur():
    assert fmt_eur(215_340) == "+€215.3k"
    assert fmt_eur(-1_234_000) == "-€1.23m"
    assert fmt_eur(500, signed=False) == "€500"
    assert fmt_eur(-1e-9) == "€0" and fmt_eur(0.0) == "€0" and fmt_eur(0.4) == "€0"   # no "-€0" from float noise
