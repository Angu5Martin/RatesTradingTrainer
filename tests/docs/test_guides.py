"""The How To guides (docs/LIVE_DESK_GUIDE.md, docs/MARKET_MAKING_GAME/*.md) against the code they describe.

A guide that quotes a number the engine does not produce is a wrong guide. These tests recompute the guides' exact probabilities with the game's own
engine, check the level, bot and client tables against the parameters in code, check that every link resolves to a real file and heading, and
check that the world-markets guide does not give away questions from the bank. Measured numbers (from scripts/measure_game_policies.py) are not
re-run here: that takes minutes; the script is deterministic.
"""

import math
import re
from fractions import Fraction
from pathlib import Path

import pytest

from rates_trainer.episodes.state import BASE_HALF_SPREAD_BP, INFORMED_DRIFT_BP
from rates_trainer.marketmaking.flow import CLIENT_TYPES, fill_probability
from rates_trainer.mmgame.bots import PERSONALITIES
from rates_trainer.mmgame.levels import LEVELS
from rates_trainer.mmgame.probability import (ALL_CARDS, AddJokers, AddTrials, LoadFace, RemoveCards, RemoveTrials, RestrictFaces, RevealClass, RevealTrials,
                                              SetSides, Target, build_deck, build_dice, mean, variance)
from rates_trainer.mmgame.markets import nice_pv
from rates_trainer.mmgame.world import load_bank

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
GUIDES = [DOCS / "LIVE_DESK_GUIDE.md", DOCS / "MARKET_MAKING_GAME" / "OVERVIEW.md", DOCS / "MARKET_MAKING_GAME" / "WORLD_MARKETS.md",
          DOCS / "MARKET_MAKING_GAME" / "PROBABILITY_MARKETS.md"]
TEXT = {p.name: p.read_text(encoding="utf-8") for p in GUIDES}
LIVE, OVERVIEW, WORLD, PROB = (TEXT[p.name] for p in GUIDES)


def slug(heading: str) -> str:
    h = re.sub(r"`([^`]*)`|\*\*([^*]+)\*\*|\*([^*]+)\*", lambda m: next(g for g in m.groups() if g is not None), heading)
    return re.sub(r"[^\w\- ]", "", h.lower(), flags=re.UNICODE).replace("_", "").replace(" ", "-")


def anchors(md: str) -> set[str]:
    out, seen = set(), {}
    in_code = False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            s = slug(m.group(2))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
    return out


# ---------------------------------------------------------------- structure and links

@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_every_link_resolves_to_a_file_and_heading(path):
    for href in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
        target, _, anchor = href.partition("#")
        f = (path.parent / target).resolve() if target else path
        assert f.exists(), f"{path.name}: {href} points at a missing file"
        if anchor and f.suffix == ".md":
            assert anchor in anchors(f.read_text(encoding="utf-8")), f"{path.name}: {href} points at a missing heading"


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_details_blocks_are_balanced_and_titled(path):
    md = path.read_text(encoding="utf-8")
    assert md.count("<details>") == md.count("</details>") == md.count("<summary>") >= 3
    assert md.count("```") % 2 == 0


def test_the_overview_links_both_specialist_guides_and_they_link_back():
    assert "(WORLD_MARKETS.md)" in OVERVIEW and "(PROBABILITY_MARKETS.md)" in OVERVIEW
    assert "OVERVIEW.md" in WORLD and "OVERVIEW.md" in PROB


# ---------------------------------------------------------------- the game's parameters, as the guides state them

def test_level_table_matches_levels_py():
    rows = {r.split("|")[1].strip(): [c.strip() for c in r.split("|")[2:5]] for r in OVERVIEW.splitlines() if r.startswith("| ") and r.count("|") == 5}
    assert rows["Markets (min / default / max)"] == [" / ".join(map(str, LEVELS[n].markets)) for n in (1, 2, 3)]
    assert rows["Rounds"] == [str(LEVELS[n].rounds) for n in (1, 2, 3)]
    assert rows["Markets that open late"] == [str(LEVELS[n].later_markets) for n in (1, 2, 3)]
    assert rows["Position limit / max size"] == [f"±{LEVELS[n].limit} / {LEVELS[n].size_max}" for n in (1, 2, 3)]
    assert rows["Risk budget"] == ["none", "none", f"{LEVELS[3].risk_budget:,} credits"]
    assert rows["Smallest move of a non-information shock"] == ["any", f"{LEVELS[2].min_shift}σ", f"{LEVELS[3].min_shift}σ"]
    for n in (1, 2, 3):
        lo, hi = LEVELS[n].shocks
        assert f"{lo}–{hi}" in rows["Shocks per game"][n - 1]


def test_bot_table_matches_personalities():
    P = PERSONALITIES
    want = {"Retail flow": P["retail"], "Value fund": P["value"], "Slow money": P["anchor"], "Fast money (sniper)": P["sniper"], "Informed": P["insider"]}
    for label, p in want.items():
        row = next(r for r in OVERVIEW.splitlines() if r.startswith(f"| {label} |"))
        cells = [c.strip() for c in row.split("|")[1:-1]]
        assert cells[1].startswith(f"{round(p.activity * 100)}%"), label
        assert f"{p.noise}σ".lstrip("0") in cells[2].replace("0.", "."), label
        assert cells[3].replace("−", "-").startswith(f"{p.thr}σ"), label
        assert cells[4].startswith(str(p.max_size)), label
    assert P["anchor"].lag == 2 and "two rounds ago" in OVERVIEW
    assert P["insider"].capacity == 5 and "each at most 5 lots a round" in OVERVIEW
    assert P["sniper"].fast_activity == 1.0 and P["insider"].fast_activity == 0.8


def test_lot_value_rule_and_examples():
    assert nice_pv(5) == 20 and nice_pv(100) == 1 and nice_pv(200) == Fraction(1, 2)          # world guide: lot value 20 -> sigma about 5, 1 -> 100, 0.5 -> 200
    assert nice_pv(math.sqrt(8.75)) == 50 and nice_pv(100 * math.sqrt(5 / 8 * 3 / 8)) == 2    # probability guide: Sum of 3d6, P(Sum of 3d6 >= 10)
    for sd in (0.3, 1.0, 2.96, 7.0, 48.4, 350.0):
        assert 1 / 1.7 < float(nice_pv(sd)) * sd / 100 < 1.7                                    # "within a factor of about 1.6"


# ---------------------------------------------------------------- the probability guide's numbers, from the engine

def dice(n, sides=6):
    return build_dice("die", sides, n, [i * 7919 + 1 for i in range(16)])


def ms(exp, t):
    p = exp.pmf(t)
    return mean(p), math.sqrt(float(variance(p)))


def ev(agg, op, t, pred=None):
    return Target(agg, pred, {"op": op, "t": t})


def p100(exp, t):
    return exp.pmf(t).get(100, Fraction(0))


S = Target("sum")


def test_probability_tables():
    assert ms(dice(3), S) == (Fraction(21, 2), pytest.approx(2.958, abs=1e-3))
    assert p100(dice(3), ev("sum", "ge", 10)) == Fraction(5, 8) and p100(dice(3), ev("sum", "ge", 11)) == Fraction(1, 2)
    assert p100(dice(3), ev("sum", "ge", 12)) == Fraction(81, 216)
    assert p100(dice(2), ev("sum", "ge", 8)) == Fraction(5, 12)
    assert ms(dice(2), Target("max"))[0] == Fraction(161, 36) and ms(dice(3), Target("max"))[0] == Fraction(119, 24)
    assert ms(dice(3), Target("min"))[0] == Fraction(49, 24) and ms(dice(3), Target("top2"))[0] == Fraction(203, 24)
    assert ms(dice(3), Target("count", {"kind": "odd"}))[0] == Fraction(3, 2)
    assert ms(dice(4), Target("count", {"kind": "ge", "v": 5}))[0] == Fraction(4, 3)
    assert ms(dice(4), Target("count", {"kind": "ge", "v": 4}))[0] == 2
    assert ms(dice(3), Target("count", {"kind": "le", "v": 2}))[0] == 1
    coins = build_dice("coin", 2, 8, [i * 7919 + 1 for i in range(16)])
    heads = Target("count", {"kind": "eq", "v": 1})
    assert ms(coins, heads) == (4, pytest.approx(math.sqrt(2)))
    assert p100(coins, ev("count", "ge", 6, {"kind": "eq", "v": 1})) == Fraction(37, 256)
    deck = build_deck(5, list(ALL_CARDS))
    hearts = Target("count", {"kind": "suit", "v": "H"})
    m, sd = ms(deck, hearts)
    assert m == Fraction(5, 4) and sd == pytest.approx(math.sqrt(5 * 0.25 * 0.75 * 47 / 51)) and deck.pmf(hearts)[0] == Fraction(2109, 9520)
    assert ms(build_deck(5, list(ALL_CARDS)), Target("count", {"kind": "color", "v": "red"}))[0] == Fraction(5, 2)
    aces = build_deck(6, list(ALL_CARDS))
    assert ms(aces, Target("count", {"kind": "ace"}))[0] == Fraction(6, 13) and float(aces.pmf(Target("count", {"kind": "ace"}))[0]) == pytest.approx(0.603, abs=5e-4)
    assert 1 - Fraction(5, 6) ** 3 == Fraction(91, 216)
    for text in ("21/2 = 10.5", "62.5 (5/8)", "161/36", "119/24", "49/24", "203/24", "37/256", "2109/9520", "6/13", "91/216", "81/216 = 37.5%"):
        assert text in PROB, text


def shocked(effect, n=3, target=S, sides=6):
    e = dice(n, sides)
    e.apply(effect)
    return e, ms(e, target)[0]


def test_probability_shock_examples():
    assert shocked(RestrictFaces({"kind": "even"}))[1] == 12
    e, m = shocked(RestrictFaces({"kind": "ge", "v": 5}), n=2)
    assert m == 11 and e.support(S) == (10, 12)
    e, m = shocked(RestrictFaces({"kind": "le", "v": 4}))
    assert m == Fraction(15, 2) and p100(e, ev("sum", "ge", 11)) == Fraction(1, 16)
    assert shocked(SetSides(10))[1] == Fraction(33, 2)
    assert shocked(LoadFace(6, 2))[1] == Fraction(81, 7)
    assert shocked(AddTrials(1))[1] == 14 and shocked(RemoveTrials(1))[1] == 7
    e = dice(2)
    e.apply(RestrictFaces({"kind": "even"}))
    assert p100(e, ev("sum", "ge", 10)) == Fraction(1, 3)
    # information: one die only (the experiment-versus-information contrast: 12 against 11)
    e = dice(3)
    e.apply(RevealTrials(1))
    assert ms(e, S)[0] == e.trials[0].value + 7
    e = dice(3)
    text = e.apply(RevealClass("parity"))
    assert ms(e, S)[0] == (3 if "odd" in text else 4) + 7
    # cards
    d = build_deck(5, list(ALL_CARDS))
    d.apply(RemoveCards({"kind": "suit", "v": "C"}))
    assert ms(d, Target("count", {"kind": "suit", "v": "H"}))[0] == Fraction(5, 3)
    d = build_deck(5, list(ALL_CARDS))
    d.apply(AddJokers(2))
    assert ms(d, Target("count", {"kind": "suit", "v": "H"}))[0] == Fraction(65, 54)
    assert 2 + Fraction(3 * 11, 50) == Fraction(133, 50) and "2.66" in PROB


def test_shock_texts_quoted_in_the_guide_are_the_engines():
    for effect, words in ((RestrictFaces({"kind": "even"}), "No odd numbers"), (RestrictFaces({"kind": "ge", "v": 5}), "No numbers below 5"),
                          (RestrictFaces({"kind": "le", "v": 4}), "No numbers above 4"), (SetSides(10), "Range change"), (LoadFace(6, 2), "Loaded: the 6 is now 2× as likely"),
                          (AddTrials(1), "1 more die will be rolled at resolution"), (RemoveTrials(1), "1 die will not be rolled after all")):
        assert words in dice(3).apply(effect) and words in PROB, words
    d = build_deck(5, list(ALL_CARDS))
    assert "jokers shuffled into the deck" in d.apply(AddJokers(2)) and "jokers shuffled into the deck" in PROB


def test_linked_sum_and_max_correlation():
    from itertools import product
    o = list(product(range(1, 7), repeat=3))
    s, m = [sum(x) for x in o], [max(x) for x in o]
    ms_, mm = sum(s) / 216, sum(m) / 216
    cov = sum(a * b for a, b in zip(s, m)) / 216 - ms_ * mm
    corr = cov / math.sqrt((sum(a * a for a in s) / 216 - ms_ ** 2) * (sum(b * b for b in m) / 216 - mm ** 2))
    assert round(corr, 2) == 0.76 and "about **0.76**" in PROB


def test_world_guide_truncated_normal_examples():
    phi = lambda z: math.exp(-z * z / 2) / math.sqrt(2 * math.pi)
    Phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))
    assert round(1900 + 10 * phi(0) / 0.5) == 1908 and round(10 * math.sqrt(1 - 2 / math.pi), 1) == 6.0
    assert round(1900 - 10 * phi(0.6) / Phi(0.6), 1) == 1895.4
    assert "1908" in WORLD and "1895.4" in WORLD and "6.0" in WORLD


def test_world_guide_gives_no_bank_question_away():
    lower = WORLD.lower() + OVERVIEW.lower() + PROB.lower()
    for item in load_bank():
        assert item.question.lower() not in lower, item.id


# ---------------------------------------------------------------- the Live Desk guide against the desk's model

def test_client_type_table_matches_flow_model():
    rows = {"Corporate treasurer": "corporate", "Pension fund (LDI)": "pension", "Bank treasury": "bank_treasury", "Real-money asset manager": "asset_manager",
            "Macro hedge fund": "macro_fund", "Fast money": "fast_money"}
    for label, key in rows.items():
        c = CLIENT_TYPES[key]
        row = next(r for r in LIVE.splitlines() if r.startswith(f"| {label} |"))
        cells = [x.strip() for x in row.split("|")[1:-1]]
        assert cells[1] == f"{round(c.p_informed * 100)}%", label
        assert cells[2] == f"{c.p_informed * INFORMED_DRIFT_BP:g}bp", label
        assert cells[3] == f"{round(c.p_at_street * 100)}%", label
        assert cells[4] == f"{c.sensitivity_bp:.2f}bp", label


def test_fill_probability_examples():
    pen, fast = CLIENT_TYPES["pension"], CLIENT_TYPES["fast_money"]
    assert [round(fill_probability(pen, i) * 100) for i in (-0.1, 0, 0.1)] == [19, 35, 55]
    assert [round(fill_probability(fast, i) * 100) for i in (-0.1, 0, 0.1)] == [43, 50, 57]


def test_slope_and_curvature_formulas_use_the_risk_cards_loadings():
    from rates_trainer.episodes.factors import FACTORS
    slope = {t: round(FACTORS["slope"].loading(t), 4) for t in (2, 5, 10, 30)}
    curv = {t: round(FACTORS["curvature"].loading(t), 4) for t in (2, 5, 10, 30)}
    assert slope == {2: -1.0, 5: -0.625, 10: 0.0, 30: 1.0} and curv == {2: -0.125, 5: 1.0, 10: 0.25, 30: -0.5}
    kr = {2: -68_000.0, 5: 0.0, 10: 89_000.0, 30: 0.0}                                         # worked example 3
    slope_exp = -sum(kr[t] * -slope[t] for t in kr)                                             # P&L for a 1bp flattening = -sum(KR x move), move = -loading
    curv_exp = -sum(kr[t] * -curv[t] for t in kr)
    assert slope_exp == 68_000 and round(curv_exp / 1000) == 31
    assert "KR30 − KR2 − 0.625 × KR5" in LIVE and "KR5 + 0.25 × KR10 − 0.125 × KR2 − 0.5 × KR30" in LIVE
    assert {f.name: f.vol_bp_day for f in FACTORS.values()}["level"] == 5.0


def test_costs_and_steps_quoted_in_the_live_desk_guide():
    assert BASE_HALF_SPREAD_BP == {2: 0.10, 5: 0.15, 10: 0.20, 30: 0.40}
    assert round(0.5 * BASE_HALF_SPREAD_BP[10] * 1.0 * 1.0, 3) == 0.10                         # 10Y cost to cross, normal vol and liquidity
    assert round(0.5 * BASE_HALF_SPREAD_BP[10] * 0.6 * 0.8, 3) == 0.048                        # calm vol, deep liquidity (example 6: "about 0.05bp")
    assert round(5 * math.sqrt(0.125), 2) == 1.77 and round(5 * 0.6 * math.sqrt(0.25), 2) == 1.5
    from rates_trainer.episodes.episode import OVERNIGHT_DT
    assert OVERNIGHT_DT == 0.5 and "an overnight is 0.5 day" in LIVE
