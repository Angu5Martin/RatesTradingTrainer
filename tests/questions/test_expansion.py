"""The TRAIN expansion: every new source recomputed independently of its template, curriculum coverage, filters, and that nothing that existed changed.

Each test rebuilds the answer from first principles or from the engine through a different route from the one the template used (a closed form against a
bump-and-reprice, an enumeration against a formula, a finite difference against an annuity), then checks the template's number and its tolerance window.
"""

import json
import math
from collections import deque
from functools import lru_cache
from pathlib import Path

import pytest

from rates_trainer.curriculum.skills import SKILLS
from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.dates import TARGET, add_months
from rates_trainer.engine.instruments import IRSwap, Side, bond_price
from rates_trainer.engine.pnl import revalue_pnl
from rates_trainer.engine.risk import Portfolio, key_rate_dv01, par_irs, parallel_dv01, unit_dv01
from rates_trainer.marketmaking.quoting import BP, ClientAction, make_quote
from rates_trainer.questions.api import catalogue
from rates_trainer.questions.model import ChoicePart, NumericPart
from rates_trainer.questions.practice import QuestionSession, kind_of, source_kinds
from rates_trainer.questions.registry import all_specs, generate, select
from rates_trainer.questions.templates.risk_book import BUCKETS, LOADINGS, bucketed

HERE = Path(__file__).parent
S = range(12)

NEW_TEMPLATES = [
    "math.bootstrap_par_curve", "math.df_forward_solve", "math.interp_log_linear", "math.ois_policy_path",
    "bonds.bill_price_yield", "bonds.mm_day_count", "swaps.estr_compounding", "bonds.clean_dirty_accrued", "bonds.price_to_yield_move",
    "swaps.mtm_off_market", "swaps.cashflow_conventions", "swaps.fra_settlement", "swaps.forward_start_inverse",
    "risk.key_rate_read", "risk.key_rate_hedge", "risk.factor_exposure", "risk.convexity_barbell", "curves.butterfly", "curves.move_decomposition",
    "curves.equal_notional_trap", "portfolio.bucket_book", "portfolio.scenario_pnl", "pnl.realised_unrealised",
    "mm.bid_offer_drill", "mm.requote_sequence", "mm.stale_quote", "mm.client_net_edge", "mm.quote_review", "mm.adverse_selection_edge",
    "mm.cross_product_hedge", "mm.event_sizing", "mm.event_repricing", "futures.contract_specs_pnl",
    "rv.swap_spread_pnl", "pnl.convexity_asymmetry", "basis.tenor_compounding",
]


@lru_cache(maxsize=None)
def q(tid: str, seed: int):
    return generate(tid, seed)


def correct_text(part: ChoicePart) -> str:
    return part.options[part.correct]


# ---------------------------------------------------------------------------------------------------------------- nothing that existed changed

def test_every_existing_source_regenerates_exactly_as_before():
    """A practice record is (template id, seed): changing what a source produces would silently rewrite history. Digests taken before the expansion."""
    snap = json.loads((HERE / "data" / "legacy_snapshot.json").read_text())
    ids = {k.rpartition("#")[0] for k in snap}
    assert {s.id for s in all_specs()} >= ids                      # nothing was removed or renamed

    def sig(qu):
        import hashlib
        parts = []
        for p in qu.parts:
            if isinstance(p, NumericPart):
                parts.append(["n", p.prompt, round(p.answer, 9), p.unit, None if p.approx is None else round(p.approx, 9), p.tol.rel, p.tol.abs])
            else:
                parts.append(["c", p.prompt, p.options, p.correct])
        return hashlib.sha256(json.dumps([qu.stem, parts, qu.solution, qu.difficulty, qu.skill], sort_keys=True, default=str).encode()).hexdigest()[:16]

    bad = [k for k, v in snap.items() if sig(generate(k.rpartition("#")[0], int(k.rpartition("#")[2]))) != v]
    assert bad == []


# ---------------------------------------------------------------------------------------------------------------- curriculum coverage

def test_every_skill_now_has_standalone_questions_and_none_is_left_planned():
    by_skill: dict[str, int] = {}
    for sp in all_specs():
        by_skill[sp.skill] = by_skill.get(sp.skill, 0) + 1
    assert [sid for sid in SKILLS if by_skill.get(sid, 0) == 0] == []
    assert [sid for sid, sk in SKILLS.items() if sk.planned] == []
    c = catalogue()
    assert all(s["sources"] > 0 and not s["planned"] for t in c["tracks"] for s in t["skills"])


@pytest.mark.parametrize("skill", ["risk.key_rate", "mm.requote_loop", "mm.cross_product_hedging", "mm.views_and_events"])
def test_the_previously_episode_only_skills_have_real_standalone_questions(skill):
    """These four were practised only in the Live Desk. Each now has calculation AND conceptual sources of its own, at more than one level of difficulty."""
    specs = [s for s in all_specs() if s.skill == skill]
    kinds = source_kinds()
    assert {kinds[s.id] for s in specs} == {"conceptual", "calculation"}
    assert len({s.difficulty for s in specs}) >= 2 and len(specs) >= 5


@pytest.mark.parametrize("skill", ["math.bootstrapping", "math.interpolation", "bonds.money_market", "risk.convexity", "curve.butterfly", "portfolio.aggregation", "portfolio.scenarios"])
def test_the_formerly_planned_skills_each_have_both_kinds_of_question(skill):
    specs = [s for s in all_specs() if s.skill == skill]
    kinds = source_kinds()
    assert {kinds[s.id] for s in specs} == {"conceptual", "calculation"}


def test_new_templates_keep_their_kind_and_valid_metadata_across_seeds():
    """source_kinds() classifies a source from seed 0, so a template must not change kind with the seed."""
    kinds = source_kinds()
    ids = {s.id for s in all_specs()}
    for tid in NEW_TEMPLATES:
        assert tid in ids
        spec = next(s for s in all_specs() if s.id == tid)
        assert spec.skill in SKILLS and spec.difficulty in (1, 2, 3) and not spec.curated
        assert spec.kind in ("conceptual", "calculation")                       # declared, so the catalogue does not have to generate it to classify it
        assert {kind_of(q(tid, sd)) for sd in range(25)} == {spec.kind} == {kinds[tid]}


def test_new_curated_questions_have_distinct_options_a_rationale_and_no_hidden_giveaway():
    new = [s for s in all_specs() if s.curated and s.id.partition(".")[2] in _new_curated_ids()]
    assert len(new) >= 65
    for s in new:
        (part,) = q(s.id, 0).parts
        assert isinstance(part, ChoicePart) and 3 <= len(part.options) <= 5 and len(set(part.options)) == len(part.options)
        assert part.why.strip() and len(q(s.id, 0).stem) > 40
        letters = {q(s.id, sd).parts[0].correct for sd in range(30)}
        assert len(letters) > 1                                       # the correct answer moves around, it is not always option A


def _new_curated_ids() -> set[str]:
    import tomllib
    out = set()
    for name in ("foundations.toml", "mm_judgement.toml"):
        path = Path(__file__).parents[2] / "src" / "rates_trainer" / "curriculum" / "curated" / name
        out |= {it["id"] for it in tomllib.loads(path.read_text(encoding="utf-8"))["question"]}
    return out


def test_the_new_curated_options_do_not_give_the_answer_away_by_their_length():
    """A tell: if the right option is usually the longest (or the shortest), test-taking skill substitutes for knowledge. Detail belongs in the rationale."""
    rows = []
    for s in all_specs():
        if s.curated and s.id.partition(".")[2] in _new_curated_ids():
            part = q(s.id, 0).parts[0]
            right = len(correct_text(part))
            others = [len(o) for i, o in enumerate(part.options) if i != part.correct]
            rows.append((right, others))
    n = len(rows)
    assert sum(r > max(o) for r, o in rows) / n <= 0.40
    assert sum(r < min(o) for r, o in rows) / n <= 0.40
    assert not [1 for r, o in rows if r > 1.6 * max(o)]


# ---------------------------------------------------------------------------------------------------------------- filters and the session

def test_filters_reach_the_new_sources_by_track_skill_difficulty_and_kind():
    sp = all_specs()
    assert {s.id for s in select(sp, skills={"risk.key_rate"})} >= {"risk.key_rate_read", "risk.key_rate_hedge", "risk.factor_exposure"}
    assert "mm.requote_sequence" in {s.id for s in select(sp, tracks={"mm"}, difficulty=3)}
    assert "math.bootstrap_par_curve" in {s.id for s in select(sp, tracks={"math"}, max_difficulty=2)}
    kinds = source_kinds()
    ss = QuestionSession.start(skills=["risk.key_rate"], kind="calculation", count=6, seed=3)
    assert {t for t, _ in ss.plan} <= {s.id for s in sp if s.skill == "risk.key_rate" and kinds[s.id] == "calculation"}
    cc = QuestionSession.start(skills=["mm.views_and_events"], kind="conceptual", count=50, seed=1)
    assert {t for t, _ in cc.plan} <= {s.id for s in sp if s.skill == "mm.views_and_events" and kinds[s.id] == "conceptual"}
    again = QuestionSession.start(skills=["risk.key_rate"], kind="calculation", count=6, seed=3)
    assert ss.plan == again.plan                                     # deterministic


@pytest.mark.parametrize("tid", NEW_TEMPLATES)
def test_a_new_source_runs_through_the_session_without_leaking_before_its_part_is_answered(tid):
    ss = QuestionSession.single(tid, 4)
    secret = q(tid, 4)
    while not ss.done:
        view = ss.state()["question"]
        blob = json.dumps(view)
        for p in secret.parts[len(view["parts_done"]) + 1:]:           # later parts are not on screen yet
            assert p.prompt not in blob
        assert view["solution"] is None
        assert all(k not in view["current"] for k in ("answer", "tol", "approx", "correct", "why", "expected"))
        part = secret.parts[view["current"]["index"]]
        res = ss.submit(chr(65 + part.correct) if isinstance(part, ChoicePart) else repr(part.answer))
        assert res["correct"]
        ss.next()
    summary = ss.summary()
    assert summary["parts_total"] == summary["parts_correct"] == len(secret.parts)


# ---------------------------------------------------------------------------------------------------------------- math

def test_bootstrap_reprices_its_own_par_swaps_and_reads_back_consistently():
    for sd in range(30):
        qu = q("math.bootstrap_par_curve", sd)
        f = qu.facts
        par, dfs, n = f["par"], f["dfs"], f["n"]
        for k in range(n):                                              # a par swap is worth zero: S x sum(DF) = 1 - DF_n
            assert par[k] * sum(dfs[: k + 1]) == pytest.approx(1 - dfs[k], abs=1e-9)
        zero, fwd = dfs[n - 1] ** (-1 / n) - 1, dfs[n - 2] / dfs[n - 1] - 1
        assert f["zero"] == pytest.approx(zero, abs=1e-9) and f["fwd"] == pytest.approx(fwd, abs=1e-9)
        nums = [p for p in qu.parts if isinstance(p, NumericPart)]
        assert nums[2].answer == pytest.approx(zero * 100, abs=1e-8) and nums[3].answer == pytest.approx(fwd * 100, abs=1e-8)
        if f["reverse"]:
            assert nums[1].answer == pytest.approx(par[-1] * 100, abs=1e-8) and nums[0].answer == pytest.approx(par[1] * 100, abs=1e-8)
        else:
            assert nums[0].answer == pytest.approx(dfs[1], abs=1e-9) and nums[1].answer == pytest.approx(dfs[-1], abs=1e-9)
            assert not nums[1].tol.allows(f["naive"], dfs[-1])          # the shortcut is wrong by more than the tolerance
        assert (correct_text(qu.parts[-1]).startswith("The zero")) == (zero > par[-1])


def test_df_forward_solve_round_trips_and_orders_forward_against_zero():
    for sd in S:
        qu = q("math.df_forward_solve", sd)
        f = qu.facts
        fwd = (f["dfa"] / f["dfb"] - 1) * 360 / f["days"]
        assert qu.parts[0].answer == pytest.approx(fwd * 100, abs=1e-9)
        dfb2 = f["dfa"] / (1 + f["f2"] * f["days"] / 360)
        assert qu.parts[1].answer == pytest.approx(dfb2, abs=1e-12)
        assert (1 + f["f2"] * f["days"] / 360) * dfb2 == pytest.approx(f["dfa"], rel=1e-12)       # the inverse really inverts
        assert correct_text(qu.parts[3]).startswith("Above") == (f["fwd"] > f["zb"])


def test_log_linear_interpolation_is_flat_forward_between_nodes():
    for sd in range(30):
        qu = q("math.interp_log_linear", sd)
        f = qu.facts
        (a, b, c), (za, zb, zc), qq = f["nodes"], f["zeros"], f["q"]
        ln = {t: -t * math.log1p(z) for t, z in ((a, za), (b, zb), (c, zc))}
        lnq = ln[a] + (ln[b] - ln[a]) * (qq - a) / (b - a)
        assert qu.parts[0].answer == pytest.approx(math.exp(lnq), abs=1e-9)
        seg = math.exp((ln[a] - ln[b]) / (b - a)) - 1
        assert qu.parts[1].answer == pytest.approx(seg * 100, abs=1e-8)                          # every year of the segment has the same forward
        assert not qu.parts[0].tol.allows(f["df_lin"], f["df_q"]) and not qu.parts[1].tol.allows(f["f_lin"] * 100, f["f1"] * 100)
        if f["inside"]:
            assert correct_text(qu.parts[2]).startswith("Identical")
        else:
            nxt = math.exp((ln[b] - ln[c]) / (c - b)) - 1
            assert correct_text(qu.parts[2]).startswith("Higher" if nxt > seg else "Lower")
        assert correct_text(qu.parts[3]).startswith("Those in the two segments")


def test_ois_policy_path_reads_the_forward_the_engine_gives():
    seen = set()
    for sd in range(40):
        qu = q("math.ois_policy_path", sd)
        f = qu.facts
        mkt = f["mkt"]
        d0 = mkt.spot
        d3, d6 = TARGET.adjust(add_months(d0, 3)), TARGET.adjust(add_months(d0, 6))
        fwd = (mkt.ois.df(d3) / mkt.ois.df(d6) - 1) * 360 / (d6 - d3).days
        assert qu.parts[0].answer == pytest.approx(fwd * 100, abs=1e-8)
        assert qu.parts[1].answer == pytest.approx((fwd - mkt.quotes["OIS"][3]) * 1e4, abs=1e-6)       # the 3M OIS rate IS the first-quarter average
        assert qu.parts[1].answer == pytest.approx(f["step_bp"])
        assert qu.parts[0].tol.allows(qu.parts[0].approx, qu.parts[0].answer)
        assert correct_text(qu.parts[3]).startswith("Receive" if f["view_dovish"] else "Pay")
        seen.add(f["priced"])
    assert seen >= {"cuts", "hikes"}


# ---------------------------------------------------------------------------------------------------------------- money markets and bond pricing

def test_bill_price_dv01_and_pnl_against_finite_differences():
    for sd in range(30):
        qu = q("bonds.bill_price_yield", sd)
        f = qu.facts
        tau = f["days"] / 360

        def price(y):
            return 100 / (1 + y * tau)

        assert qu.parts[0].answer == pytest.approx(price(f["y"]), abs=1e-12)
        fd = f["face"] * (price(f["y"] - 0.5e-4) - price(f["y"] + 0.5e-4)) / 100                  # EUR per 1bp fall, central difference
        assert qu.parts[2].answer == pytest.approx(fd, rel=1e-5)
        assert qu.parts[3].answer == pytest.approx(f["face"] * (price(f["y"] + f["move"] * 1e-4) - price(f["y"])) / 100, rel=1e-9)
        assert correct_text(qu.parts[4]).startswith("Rich") == (f["ois"] > f["y"])
        assert 0 < qu.parts[2].answer < 0.01 * f["face"]                                         # a bill's DV01 is tiny next to its face


def test_day_count_conversion_preserves_the_cash():
    for sd in S:
        qu = q("bonds.mm_day_count", sd)
        f = qu.facts
        assert qu.parts[0].answer == pytest.approx(f["cash_a"])
        n = f["cash_b"] / (f["rb"] * f["days"] / 365)                                            # the notional, recovered
        assert n * f["rb360"] * f["days"] / 360 == pytest.approx(f["cash_b"], rel=1e-12)          # same cash on either basis
        assert qu.parts[3].answer == pytest.approx(((1 + f["ra"] * f["days"] / 360) ** (365 / f["days"]) - 1) * 100, abs=1e-9)
        assert correct_text(qu.parts[2]).startswith("Bank B") == (f["cash_b"] > f["cash_a"])


def test_estr_compounding_by_a_different_route():
    for sd in range(30):
        qu = q("swaps.estr_compounding", sd)
        f = qu.facts
        daily = [(r, 3 if i == 4 else 1) for i, r in enumerate(f["fixes"])]
        growth = 1.0
        for r, d in daily:
            growth *= 1 + r * d / 360
        assert f["growth"] == pytest.approx(growth, rel=1e-14)
        assert sum(d for _, d in daily) == 7
        assert qu.parts[0].answer == pytest.approx((growth - 1) * 360 / 7 * 100, abs=1e-9)
        # for a week the compounded rate is the day-weighted average to within a fraction of a bp
        assert qu.parts[0].answer == pytest.approx(sum(r * d for r, d in daily) / 7 * 100, abs=0.001)
        assert not qu.parts[0].tol.allows(f["naive"] * 100, qu.parts[0].answer)                  # forgetting that Friday counts three times
        assert qu.parts[1].answer == pytest.approx(f["notional"] * (growth - 1))


def test_clean_dirty_accrued_and_price_move():
    for sd in range(30):
        qu = q("bonds.clean_dirty_accrued", sd)
        f = qu.facts
        bond, anchor = f["bond"], f["anchor"]
        per = next(p for p in bond.periods if p.start < anchor < p.end)
        assert qu.parts[0].answer == pytest.approx(bond.coupon * 100 * (anchor - per.start).days / (per.end - per.start).days, abs=1e-9)
        assert qu.parts[1].answer == pytest.approx(f["clean"] + qu.parts[0].answer)
        # price the unpaid cash flows from the printed yield by hand: time = fraction of the current period left + whole periods after
        unpaid = [p for p in bond.periods if p.pay > anchor]
        w = (unpaid[0].end - anchor).days / (unpaid[0].end - unpaid[0].start).days
        pv = lambda y: sum((100 * bond.coupon + (100 if i == len(unpaid) - 1 else 0)) / (1 + y) ** (w + i) for i in range(len(unpaid)))
        assert pv(f["y"]) == pytest.approx(f["dirty"], abs=1e-6)
        assert qu.parts[3].answer == pytest.approx(pv(f["y"] + _move_of(qu)) - pv(f["y"]), abs=1e-6)
        assert qu.parts[3].tol.allows(qu.parts[3].approx, qu.parts[3].answer)
        assert correct_text(qu.parts[4]).startswith("It falls") == (f["clean"] > 100)


def _move_of(qu) -> float:
    import re
    m = re.search(r"Yields (rise|fall) (\d+)bp", qu.parts[3].prompt)
    return (1 if m.group(1) == "rise" else -1) * int(m.group(2)) * 1e-4


def test_price_to_yield_move_reprices():
    for sd in range(30):
        qu = q("bonds.price_to_yield_move", sd)
        f = qu.facts
        p2 = bond_price(f["coupon"], f["maturity"], f["y"] + f["dy_bp"] * 1e-4)
        assert f["d_price"] == pytest.approx(p2 - bond_price(f["coupon"], f["maturity"], f["y"]), abs=0.0051)
        assert qu.parts[0].answer == f["dy_bp"] and qu.parts[0].tol.allows(f["implied"], f["dy_bp"])
        assert (qu.parts[1].answer > 0) == ((f["d_price"] > 0) == f["long"])
        assert abs(qu.parts[1].answer / qu.parts[2].answer + f["dy_bp"]) < 0.15 * abs(f["dy_bp"])     # P&L / DV01 recovers the move


# ---------------------------------------------------------------------------------------------------------------- swaps

def test_off_market_swap_value_is_pv01_times_rate_difference():
    for sd in S:
        qu = q("swaps.mtm_off_market", sd)
        f = qu.facts
        swap, mkt = f["swap"], f["mkt"]
        a = swap.annuity(mkt)
        assert qu.parts[0].answer == pytest.approx(swap.side.sign * swap.notional * a * (swap.fixed_rate - swap.par_rate(mkt)), rel=1e-9)
        assert f["pv01"] == pytest.approx(swap.notional * a * 1e-4)
        assert qu.parts[0].tol.allows(f["mental"], f["pv"])                     # the mental route through the printed rates passes
        assert qu.parts[2].answer == pytest.approx(f["pv"] - f["pv01"] * f["half"])
        assert qu.parts[1].answer == pytest.approx(swap.pv(mkt.shifted(CurveShock.parallel(f["move"]))))
        asset = f["pv"] > 0
        assert correct_text(qu.parts[3]).startswith("An asset") == asset
        text = correct_text(qu.parts[3])
        assert ("the fixed leg you receive is worth more" in text) == (asset and swap.side is Side.RECEIVE)
        assert ("the floating leg you pay is worth more" in text) == ((not asset) and swap.side is Side.RECEIVE)


def test_cash_flow_conventions_from_the_dates():
    for sd in range(30):
        qu = q("swaps.cashflow_conventions", sd)
        f = qu.facts
        swap = f["swap"]
        p, fx = swap.float_periods[0], swap.fixed_periods[0]
        assert qu.parts[0].answer == (p.end - p.start).days
        assert qu.parts[1].answer == pytest.approx(swap.notional * f["fixing"] * (p.end - p.start).days / 360)
        d1, d2 = min(fx.start.day, 30), min(fx.end.day, 30)                      # 30E/360 by hand
        frac = (360 * (fx.end.year - fx.start.year) + 30 * (fx.end.month - fx.start.month) + (d2 - d1)) / 360
        assert qu.parts[2].answer == pytest.approx(swap.notional * swap.fixed_rate * frac)
        assert 357 / 360 <= frac <= 363 / 360                                      # a rolled date can shorten or lengthen the year by a few days
        for d in (p.start, p.end, fx.end):
            assert TARGET.is_business_day(d)


def test_fra_settlement_discounts_the_difference_and_matches_the_engine():
    for sd in range(30):
        qu = q("swaps.fra_settlement", sd)
        f = qu.facts
        fra, mkt, tau = f["fra"], f["mkt"], f["tau"]
        sign = 1 if fra.side is Side.RECEIVE else -1
        assert qu.parts[0].answer == pytest.approx(sign * fra.notional * tau * (fra.rate - f["fix"]) / (1 + f["fix"] * tau))
        assert (qu.parts[0].answer > 0) == ((f["fix"] > fra.rate) == (fra.side is Side.PAY))      # payers gain when the fixing is above the FRA rate
        assert qu.parts[2].answer == pytest.approx(fra.pv(mkt), rel=0.01, abs=fra.notional * tau * 0.3e-4)    # printed rounded forward and DF
        assert qu.parts[0].tol.allows(f["undiscounted"], qu.parts[0].answer)
        assert correct_text(qu.parts[1]).startswith("At the START")


def test_forward_start_inverse_recovers_the_spot_rate():
    for sd in range(30):
        qu = q("swaps.forward_start_inverse", sd)
        f = qu.facts
        mkt, a, b = f["mkt"], f["a"], f["b"]
        assert f["exact"] == pytest.approx(mkt.par_irs_rate(12 * b), abs=2e-5)     # the printed (rounded) numbers reproduce the engine's spot rate to 0.2bp
        assert qu.parts[0].answer == pytest.approx(f["exact"] * 100)
        assert not qu.parts[0].tol.allows(f["naive"] * 100, f["exact"] * 100)
        sens = (f["ab"] - f["aa"]) / f["ab"]                                        # d S_b / d F = A_fwd / A_b
        assert qu.parts[1].answer == pytest.approx(f["bump"] * sens)
        assert 0.2 < sens < 0.85


# ---------------------------------------------------------------------------------------------------------------- risk

def test_key_rate_read_buckets_hedge_and_classification():
    for sd in range(25):
        qu = q("risk.key_rate_read", sd)
        f = qu.facts
        mkt, book = f["mkt"], f["book"]
        bk = bucketed(key_rate_dv01(book, mkt, curves=("E6M",)))["E6M"]
        assert bk == pytest.approx(f["buckets"])
        assert qu.parts[0].answer == pytest.approx(sum(bk.values()))
        net, gross = sum(bk.values()), sum(abs(v) for v in bk.values())
        mode = f["mode"]
        assert (abs(net) > 0.7 * gross) == mode.startswith("outright")
        label = correct_text(qu.parts[1])
        if mode in ("steepener", "flattener"):
            assert label.startswith("A curve " + mode)
            live = [b for b in BUCKETS if abs(bk[b]) > 1]
            assert (bk[min(live)] > 0 > bk[max(live)]) == (mode == "steepener")      # steepener: long duration at the short end, short at the long end
        elif mode == "fly_long":
            mid = sorted(b for b in BUCKETS if abs(bk[b]) > 1)[1]
            assert label.startswith("A butterfly long the belly") and bk[mid] > 0
        # the single hedge named in part 3 really flattens that bucket
        big = f["big"]
        hedge = par_irs(Side.RECEIVE if f["hedge_to_flat"] > 0 else Side.PAY, abs(f["hedge_to_flat"]), big, mkt)
        after = bucketed(key_rate_dv01(Portfolio([*book.instruments, hedge]), mkt, curves=("E6M",)))["E6M"]
        assert abs(after[big]) < 0.01 * abs(bk[big])
        assert qu.parts[2].answer == pytest.approx(f["full"]) and qu.parts[2].tol.allows(f["first"], f["full"])
        assert correct_text(qu.parts[4]).startswith("Swaps in the") and "its own bucket's DV01" in correct_text(qu.parts[4])


def test_key_rate_hedge_zeroes_both_buckets_and_equal_notional_is_the_rule():
    for sd in range(8):
        qu = q("risk.key_rate_hedge", sd)
        f = qu.facts
        mkt, fwd, a, b = f["mkt"], f["fwd"], f["a"], f["b"]
        hedges = [par_irs(Side.RECEIVE if n > 0 else Side.PAY, abs(n), t, mkt) for n, t in ((qu.parts[0].answer, b), (qu.parts[1].answer, a))]
        kr = key_rate_dv01(Portfolio([fwd, *hedges]), mkt, curves=("E6M",))
        assert abs(kr[("E6M", 12 * a)]) < 0.01 * abs(f["ka"]) and abs(kr[("E6M", 12 * b)]) < 0.01 * abs(f["kb"])
        # the identity: the forward swap is the longer swap minus the shorter one at the SAME notional (hedges are equal and opposite)
        assert abs(qu.parts[0].answer) == pytest.approx(f["notional"], rel=0.01) and abs(qu.parts[1].answer) == pytest.approx(f["notional"], rel=0.01)
        assert qu.parts[0].answer * qu.parts[1].answer < 0
        assert f["ka"] * f["kb"] < 0
        # a single DV01 hedge leaves the a-bucket where it was
        left = key_rate_dv01(Portfolio([fwd, f["one"]]), mkt, curves=("E6M",))
        assert left[("E6M", 12 * a)] == pytest.approx(f["ka"], rel=0.02)                      # untouched
        assert left[("E6M", 12 * b)] == pytest.approx(-f["ka"], rel=0.03)                     # the total is netted: the b bucket now offsets the a bucket
        assert sum(left.values()) == pytest.approx(0, abs=0.01 * abs(f["kb"]))
        assert qu.parts[2].answer == pytest.approx(f["resid"]) and qu.parts[2].tol.allows(f["first"], f["resid"])


def test_factor_exposure_loadings_are_orthogonal_and_the_scenario_adds_up():
    names = list(LOADINGS)
    for i in range(3):
        for j in range(i + 1, 3):
            assert sum(x * y for x, y in zip(LOADINGS[names[i]], LOADINGS[names[j]])) == pytest.approx(0)
    for sd in range(8):
        qu = q("risk.factor_exposure", sd)
        f = qu.facts
        d = [f["buckets"][b] for b in BUCKETS]
        for k, name in enumerate(("level", "slope", "curvature")):
            assert qu.parts[k].answer == pytest.approx(sum(x * l for x, l in zip(d, LOADINGS[name])))
        move = {b: sum(f["move"][n] * LOADINGS[n][i] for n in LOADINGS) for i, b in enumerate(BUCKETS)}
        assert qu.parts[3].answer == pytest.approx(revalue_pnl(f["book"], f["mkt"], CurveShock.points({float(b): m for b, m in move.items()}), curves=("E6M",)))
        assert qu.parts[3].tol.allows(f["first"], qu.parts[3].answer)
        assert correct_text(qu.parts[4]).startswith(f["order"][0].capitalize())


def test_convexity_barbell_is_long_convexity_both_ways():
    for sd in range(8):
        qu = q("risk.convexity_barbell", sd)
        f = qu.facts
        assert f["dv_down"] > 0 > f["dv_up"] and f["pnl_down"] > 0 and f["pnl_up"] > 0
        assert abs(parallel_dv01(f["book"], f["mkt"])) < 0.01 * max(abs(x) for x in f["legs_down"])      # neutral today
        for part in qu.parts[1:3]:
            assert part.tol.allows(part.approx, part.answer)
        # P&L grows with the square of the move: half the move earns about a quarter
        half = revalue_pnl(f["book"], f["mkt"], CurveShock.parallel(-f["m"] / 2))
        assert half == pytest.approx(f["pnl_down"] / 4, rel=0.25)


def test_butterfly_weights_and_what_it_profits_from():
    for sd in range(8):
        qu = q("curves.butterfly", sd)
        f = qu.facts
        mkt, belly, wa, wc = f["mkt"], f["belly"], f["wa"], f["wc"]
        d_b, d_a, d_c = (parallel_dv01(x, mkt) for x in (belly, wa, wc))
        assert d_a == pytest.approx(-d_b / 2, rel=1e-6) and d_c == pytest.approx(-d_b / 2, rel=1e-6)
        assert qu.parts[0].answer == pytest.approx(wa.notional) and qu.parts[1].answer == pytest.approx(wc.notional)
        ma, mb, mc = f["moves"]
        assert qu.parts[2].answer == pytest.approx(-(d_b / 2) * (2 * mb - ma - mc), rel=0.06, abs=qu.parts[2].tol.abs)       # = -(belly DV01 / 2) x the change in the fly spread
        sc = f["scenarios"]
        par = next(v for k, v in sc.items() if k.startswith("parallel"))
        assert abs(par) < 0.02 * abs(d_b) * 10                                      # a parallel move earns nothing, beyond convexity
        assert correct_text(qu.parts[3]) == f["right"] and sc[f["right"]] == max(sc.values())


def test_move_decomposition_names_and_pays_the_slope():
    names = {("up", "steeper"): "bear steepening", ("up", "flatter"): "bear flattening", ("down", "steeper"): "bull steepening", ("down", "flatter"): "bull flattening"}
    seen = set()
    for sd in range(40):
        qu = q("curves.move_decomposition", sd)
        f = qu.facts
        direction, shape = ("up" if f["ms"] + f["ml"] > 0 else "down"), ("steeper" if f["ml"] > f["ms"] else "flatter")
        assert correct_text(qu.parts[0]) == names[(direction, shape)]
        assert qu.parts[1].answer == pytest.approx((f["ms"] + f["ml"]) / 2) and qu.parts[2].answer == pytest.approx(f["ml"] - f["ms"])
        expected = (f["ml"] - f["ms"]) * abs(f["d_l"]) * (1 if f["steepener"] else -1)
        assert qu.parts[3].answer == pytest.approx(expected, rel=0.03, abs=qu.parts[3].tol.abs)
        assert qu.parts[3].approx == pytest.approx(expected)                                            # the mental route carries the trade's sign
        seen.add(f["name"])
    assert seen == set(names.values())


def test_equal_notional_curve_trade_has_unwanted_duration():
    for sd in S:
        qu = q("curves.equal_notional_trap", sd)
        f = qu.facts
        assert qu.parts[0].answer == pytest.approx(f["d_l"] + f["d_s"]) and abs(f["d_l"]) > abs(f["d_s"])          # the longer leg has more DV01 per euro
        assert abs(f["pnl_neutral"]) < 0.17 * abs(f["pnl"])
        assert qu.parts[2].answer == pytest.approx(f["neutral"].notional) and f["neutral"].notional > f["book"].instruments[1].notional
        assert (f["net"] < 0) == (f["steepener"])                                                                  # a payer long-end leg dominates a steepener


# ---------------------------------------------------------------------------------------------------------------- portfolio and P&L

def test_bucket_book_columns_totals_and_hedge():
    for sd in range(8):
        qu = q("portfolio.bucket_book", sd)
        f = qu.facts
        mkt = f["mkt"]
        net = {b: 0.0 for b in BUCKETS}
        for t in f["trades"]:
            for b, v in bucketed(key_rate_dv01(t[5], mkt, curves=("E6M",)))["E6M"].items():
                net[b] += v
        assert net == pytest.approx(f["net"])
        assert qu.parts[0].answer == pytest.approx(net[f["big"]]) and qu.parts[1].answer == pytest.approx(sum(net.values()))
        assert sum(net.values()) == pytest.approx(parallel_dv01(Portfolio([t[5] for t in f["trades"]]), mkt), rel=0.02)    # buckets add up to the parallel DV01
        assert qu.parts[3].answer == pytest.approx(-net[f["big"]] / unit_dv01(f["big"], mkt) * 1e6)
        assert qu.parts[2].answer == pytest.approx(f["slope_full"]) and qu.parts[2].tol.allows(f["slope_pnl"], f["slope_full"])


def test_scenario_pnl_uses_the_right_columns():
    for sd in range(6):
        qu = q("portfolio.scenario_pnl", sd)
        f = qu.facts
        bk = f["bk"]
        e6m, ois = sum(bk["E6M"].values()), sum(bk["OIS"].values())
        # scenario C moves only the Euribor swap curve: first order = -(Euribor total) x the bump, whatever the OIS positions are
        assert qu.parts[2].approx == pytest.approx(-e6m * f["spread"])
        for part, (full, first, tol) in zip(qu.parts[:3], f["res"]):
            assert part.answer == pytest.approx(full) and part.approx == pytest.approx(first) and part.tol.allows(first, full)
        assert correct_text(qu.parts[3]) == f"Scenario {'ABC'[f['worst']]}" and f["res"][f["worst"]][0] == min(r[0] for r in f["res"])
        assert abs(ois) > 0


def test_realised_unrealised_fifo_by_an_independent_ledger():
    for sd in range(30):
        qu = q("pnl.realised_unrealised", sd)
        f = qu.facts
        lots = deque([[n, r] for n, r in f["lots"]])
        to_close, realised = f["n3"], 0.0
        while to_close > 1e-6:
            n, r = lots[0]
            take = min(n, to_close)
            realised += (r - f["r3"]) * 1e4 * f["pv01_100"] * take / 100e6
            lots[0][0] -= take
            to_close -= take
            if lots[0][0] <= 1e-6:
                lots.popleft()
        assert qu.parts[0].answer == pytest.approx(realised)
        open_n = sum(n for n, _ in lots)
        assert qu.parts[1].answer == pytest.approx(open_n)
        unreal = sum((r - f["r_end"]) * 1e4 * f["pv01_100"] * n / 100e6 for n, r in lots)
        assert qu.parts[3].answer == pytest.approx(unreal)
        assert qu.parts[2].answer == pytest.approx(sum(n * r for n, r in lots) / open_n * 100)
        assert qu.parts[4].answer == pytest.approx(open_n / 100e6 * f["pv01_100"])
        # cross-check the formula against the engine: receive at r1 and pay at r3 on the same swap is worth N x annuity x (r1 - r3)
        mkt, tenor = f["mkt"], f["tenor"]
        n1, r1 = f["lots"][0]
        pair = Portfolio([IRSwap.new(Side.RECEIVE, n1, r1, mkt.spot, tenor * 12), IRSwap.new(Side.PAY, n1, f["r3"], mkt.spot, tenor * 12)])
        assert pair.pv(mkt) == pytest.approx(n1 / 100e6 * f["pv01_100"] * (r1 - f["r3"]) * 1e4, rel=0.03)


# ---------------------------------------------------------------------------------------------------------------- market making

def test_bid_offer_drill_side_position_and_inventory():
    for sd in range(30):
        qu = q("mm.bid_offer_drill", sd)
        f = qu.facts
        quote, action = f["quote"], f["action"]
        assert qu.parts[0].answer == pytest.approx((quote.offer if action is ClientAction.PAYS else quote.bid) * 100)
        assert correct_text(qu.parts[1]).startswith("Receive" if action is ClientAction.PAYS else "Pay")
        assert (f["dv01"] > 0) == (action is ClientAction.PAYS)
        assert qu.parts[2].answer == pytest.approx(f["inv0"] + f["dv01"])
        long_after = f["inv0"] + f["dv01"] > 0
        assert correct_text(qu.parts[3]).startswith(f"A client who {'receives' if long_after else 'pays'} fixed")
        assert f["want"] is (ClientAction.RECEIVES if long_after else ClientAction.PAYS)


def test_requote_sequence_follows_the_quote_model():
    kinds = set()
    for sd in range(40):
        qu = q("mm.requote_sequence", sd)
        f = qu.facts
        b0, b1 = make_quote(f["ctx0"]), make_quote(f["ctx1"])
        shift = b1.net_shift_bp - b0.net_shift_bp
        assert f["shift"] == pytest.approx(shift)
        assert correct_text(qu.parts[2]).startswith("Higher" if shift > 0 else "Lower")
        assert (f["dv"] > 0) == (f["action"] is ClientAction.PAYS)                         # a client who pays fixed leaves the dealer receiving it: long duration
        assert (f["inv1"] > f["inv0"]) == (f["dv"] > 0) and qu.parts[1].answer == pytest.approx(f["inv1"])
        assert correct_text(qu.parts[0]).startswith("Receive" if f["dv"] > 0 else "Pay")
        assert (f["u1"] > 1.05) == f["breach"] and (f["breach"] or f["u1"] < 0.55)
        assert correct_text(qu.parts[4]).startswith("Hedge at least" if f["breach"] else "Keep working")
        kinds.add(f["kind"])
    assert {"larger", "smaller", "flips"} <= kinds                                       # all three behaviours of the skew occur across seeds


def test_stale_quote_loss_and_new_market():
    for sd in S:
        qu = q("mm.stale_quote", sd)
        f = qu.facts
        quote, move, w = f["quote"], f["move"], f["w"]
        assert f["edge"] == pytest.approx(abs(f["dv01"]) * w, rel=1e-3)                  # the half-width, on the DV01, marked at mid
        assert qu.parts[1].answer == pytest.approx(f["loss"]) and f["loss"] < 0
        assert f["loss"] == pytest.approx(f["edge"] - f["dv01"] * move, rel=0.05, abs=0.01 * abs(f["dv01"]))
        assert qu.parts[1].tol.allows(f["approx"], f["loss"])
        new_mid = quote.mid + move * BP
        assert qu.parts[2].answer == pytest.approx((new_mid + w * BP if f["up"] else new_mid - w * BP) * 100)
        assert correct_text(qu.parts[0]).startswith("The OFFER" if f["up"] else "The BID")


def test_client_net_edge_and_the_hedge_is_dv01_neutral():
    for sd in S:
        qu = q("mm.client_net_edge", sd)
        f = qu.facts
        assert parallel_dv01(f["swap"], f["mkt"]) + parallel_dv01(f["hedge"], f["mkt"]) == pytest.approx(0, abs=1e-6 * abs(f["dv01"]))
        assert qu.parts[0].answer == pytest.approx(f["w"] * abs(f["dv01"])) and qu.parts[1].answer == pytest.approx(f["h"] * abs(f["dv01"]))
        assert qu.parts[2].answer == pytest.approx(qu.parts[0].answer - qu.parts[1].answer) and f["net"] > 0
        assert qu.parts[3].answer == pytest.approx(f["net"] / abs(f["dv01"]))
        assert correct_text(qu.parts[4]).startswith("You can meet it") == f["match_ok"]


def test_quote_review_picks_the_model_quote_not_its_mirror_or_a_symmetric_one():
    for sd in S:
        qu = q("mm.quote_review", sd)
        f = qu.facts
        b, ctx = f["breakdown"], f["ctx"]
        assert b.net_shift_bp == pytest.approx(make_quote(ctx).net_shift_bp)
        fmt = lambda shift, bid_w, off_w: f"{(ctx.fair_value + (shift - bid_w) * BP) * 100:.4f}% / {(ctx.fair_value + (shift + off_w) * BP) * 100:.4f}%"
        assert f["right"] == fmt(b.net_shift_bp, b.bid_half_width_bp, b.offer_half_width_bp)           # the model's own market, built by hand
        assert f["proposals"][1] == fmt(-b.net_shift_bp, b.bid_half_width_bp, b.offer_half_width_bp)    # the mirror image
        assert f["proposals"][2] == fmt(0.0, ctx.base_half_spread_bp, ctx.base_half_spread_bp)          # the normal-day market, ignoring the state
        assert correct_text(qu.parts[0]) == f["right"] == f["proposals"][0]
        mirrored = f["proposals"][1]
        assert mirrored != f["right"] and f["proposals"][2] != f["right"] and f["proposals"][3] != f["right"]
        assert abs(b.net_shift_bp) >= 0.12
        enc = b.encouraged_client_action
        assert correct_text(qu.parts[2]).startswith("A client who RECEIVES" if enc is ClientAction.RECEIVES else "A client who PAYS")
        assert mirrored in qu.parts[1].prompt


def test_adverse_selection_expectation_by_enumeration():
    for sd in range(30):
        qu = q("mm.adverse_selection_edge", sd)
        f = qu.facts
        outcomes = [(1 - f["p"], f["w"]), (f["p"], f["w"] - f["mu"])]                    # (probability, edge in bp per DV01)
        assert qu.parts[0].answer == pytest.approx(f["dv"] * sum(pr * e for pr, e in outcomes))
        zero = f["p"] * f["mu"]
        assert sum(pr * (zero - f["mu"] * (i == 1)) for i, (pr, _) in enumerate(outcomes)) == pytest.approx(0, abs=1e-12)    # at w = p x mu the expectation is nil
        assert qu.parts[1].answer == pytest.approx(zero) and qu.parts[2].answer == pytest.approx(f["p2"] * f["mu"])
        assert f["p2"] > f["p"]


def test_cross_product_hedge_neutralises_dv01_and_costs_add_up():
    for sd in range(8):
        qu = q("mm.cross_product_hedge", sd)
        f = qu.facts
        mkt, case, swap = f["mkt"], f["case"], f["swap"]
        book = Portfolio([swap, case.fut.with_contracts(f["n"])])
        assert parallel_dv01(book, mkt) == pytest.approx(0, abs=0.005 * abs(f["dv01"]))
        assert qu.parts[0].answer == pytest.approx(f["n"]) and (f["n"] > 0) == (f["dv01"] < 0)             # long duration is hedged by selling
        assert qu.parts[2].answer == pytest.approx(abs(f["n"]) * case.spec.tick_value / 2)
        assert qu.parts[3].answer < 0                                                                   # the stated move is against you
        assert qu.parts[4].answer == pytest.approx(f["saving"] / abs(f["dv01"])) and f["saving"] > 0
        assert qu.parts[3].tol.allows(qu.parts[3].approx, qu.parts[3].answer)


def test_event_sizing_formulas_and_the_view_agrees_with_the_position():
    for sd in range(30):
        qu = q("mm.event_sizing", sd)
        f = qu.facts
        d, s, k = abs(f["d0"]), f["sigma"], f["k"]
        assert qu.parts[0].answer == pytest.approx(d * s) and qu.parts[1].answer == pytest.approx(d * s * k) and qu.parts[2].answer == pytest.approx(d / k)
        assert d / k * s * k == pytest.approx(d * s)                                                   # the scaled position has the normal-day risk on the event day
        assert f["edge"] == pytest.approx(f["view"] - f["priced"])
        assert qu.parts[3].answer == pytest.approx(-f["d0"] * f["edge"]) and qu.parts[3].answer > 0
        assert not qu.parts[3].tol.allows(-f["d0"] * f["view"], qu.parts[3].answer)                    # ignoring what is already priced is wrong
        assert d > f["limit"] / k                                                                       # the position exceeds the volatility-scaled limit


def test_event_repricing_translates_a_surprise_into_a_book_pnl():
    for sd in range(8):
        qu = q("mm.event_repricing", sd)
        f = qu.facts
        assert qu.parts[1].answer == pytest.approx(f["m10"] - f["m2"])
        assert qu.parts[2].answer == pytest.approx(revalue_pnl(f["book"], f["mkt"], CurveShock.points({2.0: f["m2"], 10.0: f["m10"]})))
        assert f["pnl"] * f["opp"] < 0                                                                 # one direction of surprise loses what the other earns
        hurts_hot = (f["pnl"] if f["s"] > 0 else f["opp"]) < 0
        assert correct_text(qu.parts[3]).startswith("A hotter" if hurts_hot else "A softer")
        assert (f["m2"] > 0) == (f["s"] > 0) and abs(f["m2"]) > abs(f["m10"])


def test_contract_specs_pnl_ticks_and_yield_move():
    for sd in range(20):
        qu = q("futures.contract_specs_pnl", sd)
        f = qu.facts
        sp = f["case"].spec
        assert sp.tick_value == pytest.approx(10.0)
        assert qu.parts[0].answer == f["ticks"]
        assert qu.parts[1].answer == pytest.approx((1 if f["long"] else -1) * f["n"] * f["ticks"] * 10.0)
        # a price move of ticks x 0.01 against a DV01 per contract: the yield moves the other way
        assert qu.parts[2].answer == pytest.approx(-f["ticks"] * 10.0 / f["fut_dv01"])
        assert (qu.parts[2].answer > 0) == (f["ticks"] < 0)
        assert correct_text(qu.parts[3]).startswith("You receive" if qu.parts[1].answer > 0 else "You pay")


def test_swap_spread_package_earns_the_change_in_the_spread():
    for sd in range(20):
        qu = q("rv.swap_spread_pnl", sd)
        f = qu.facts
        assert qu.parts[0].answer == pytest.approx((f["swap_rate"] - f["y_b"]) * 1e4, abs=1e-6)
        assert qu.parts[1].answer == pytest.approx(f["s0"] + f["dy_s"] - f["dy_b"])
        assert f["swap"].side is Side.PAY
        # the bond leg, priced by explicit discounting of its annual cash flows
        price = lambda y: sum((100 * f["coupon"] + (100 if t == f["years"] else 0)) / (1 + y) ** t for t in range(1, f["years"] + 1))
        assert f["bond_pnl"] == pytest.approx(f["face"] / 100 * (price(f["y_b"] + f["dy_b"] * 1e-4) - price(f["y_b"])), rel=1e-9)
        assert f["bond_dv01"] == pytest.approx(f["face"] / 100 * (price(f["y_b"] - 0.5e-4) - price(f["y_b"] + 0.5e-4)), rel=2e-3)
        assert qu.parts[2].answer == pytest.approx(f["bond_pnl"] + f["swap_pnl"])
        assert qu.parts[2].tol.allows(f["approx"], f["pnl"])
        assert (f["pnl"] > 0) == (f["dy_s"] - f["dy_b"] > 0)                         # the package is long the spread
        assert parallel_dv01(f["swap"], f["mkt"]) == pytest.approx(-f["bond_dv01"], rel=1e-6)


def test_convexity_asymmetry_favours_the_receiver_and_costs_the_payer():
    for sd in range(20):
        qu = q("pnl.convexity_asymmetry", sd)
        f = qu.facts
        recv = f["swap"].side is Side.RECEIVE
        assert (f["mid"] > 0) == recv
        if recv:
            assert f["p_dn"] > f["first"] > -f["p_up"] > 0                        # the gain from a fall beats the loss from a rise
        else:
            assert -f["p_dn"] > f["first"] > f["p_up"] > 0
        assert qu.parts[2].answer == pytest.approx((f["p_dn"] + f["p_up"]) / 2) and qu.parts[2].tol.allows(f["est"], f["mid"])
        assert f["est"] == pytest.approx((f["dv_after"] - f["dv_after_up"]) * f["m"] / 4)
        assert not qu.parts[0].tol.allows(f["dv01"] * f["m"], f["p_dn"])        # DV01 alone is not accepted: it misses the convexity


def test_tenor_compounding_gap_by_hand():
    for sd in range(20):
        qu = q("basis.tenor_compounding", sd)
        f = qu.facts
        comp = ((1 + f["f1"] * f["t1"]) * (1 + f["f2"] * f["t2"]) - 1) / f["t6"]
        assert qu.parts[0].answer == pytest.approx(comp * 100) and qu.parts[1].answer == pytest.approx((f["f6"] - comp) * 1e4)
        assert qu.parts[1].answer > 1.2 and f["t6"] == pytest.approx(f["t1"] + f["t2"])
        assert not qu.parts[0].tol.allows((f["f1"] + f["f2"]) / 2 * 100, comp * 100)      # the plain average is not accepted
        assert correct_text(qu.parts[2]).startswith("The tenor premium")


@pytest.mark.parametrize("tid", NEW_TEMPLATES)
def test_every_new_source_explains_itself(tid):
    """A worked solution that walks through the numbers with the reasoning, and a rationale for every multiple-choice part: not a bare answer."""
    for sd in range(6):
        qu = q(tid, sd)
        assert len(qu.solution) >= 3 and all(len(line) >= 25 for line in qu.solution) and len(" ".join(qu.solution)) >= 300
        assert sum(ch.isdigit() for ch in " ".join(qu.solution)) >= 10 or kind_of(qu) == "conceptual"
        for p in qu.parts:
            if isinstance(p, ChoicePart):
                assert len(p.why) >= 60, (tid, p.prompt)                                   # why the right option is right, and what makes the others tempting
            else:
                assert p.note or p.approx is not None or p.sign_hint or p.unit in ("df", "bp", "%", "EUR"), (tid, p.prompt)
        assert all(len(set(p.options)) == len(p.options) >= 2 for p in qu.parts if isinstance(p, ChoicePart))
