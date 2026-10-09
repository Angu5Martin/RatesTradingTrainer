"""Generic invariants for every question source, and independent recomputation per template."""

import math
from functools import lru_cache

import pytest

from rates_trainer.curriculum.skills import SKILLS, TRACKS, validate
from rates_trainer.engine.carry import carry_roll, financing_cost
from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.dates import DayCount
from rates_trainer.engine.instruments import Side, bond_price
from rates_trainer.engine.risk import Portfolio, par_irs, parallel_dv01
from rates_trainer.marketmaking.quoting import ClientAction, make_quote
from rates_trainer.questions.model import ChoicePart, NumericPart
from rates_trainer.questions.registry import all_specs, from_id, generate

SEEDS = range(30)
SPEC_IDS = [s.id for s in all_specs()]
PY_TEMPLATES = [s.id for s in all_specs() if not s.curated]


@lru_cache(maxsize=None)
def q(tid: str, seed: int):
    return generate(tid, seed)


# ---------- curriculum structure ----------

def test_skill_graph_is_valid():
    assert validate() == []
    assert {s.track for s in SKILLS.values()} <= set(TRACKS)


def test_every_question_source_maps_to_a_known_skill():
    for spec in all_specs():
        assert spec.skill in SKILLS, spec.id
        assert spec.difficulty in (1, 2, 3), spec.id


def test_active_skills_have_questions_and_planned_skills_do_not():
    from rates_trainer.episodes.episode import all_episodes
    covered = {s.skill for s in all_specs()} | {e.skill for e in all_episodes()}
    assert {e.skill for e in all_episodes()} <= set(SKILLS)
    for sid, sk in SKILLS.items():
        if sk.planned:
            assert sid not in covered, f"{sid} is marked planned but has questions: clear the flag"
        else:
            assert sid in covered, f"{sid} is active but has no questions"


def test_curated_ids_unique_and_have_distinct_options():
    ids = [s.id for s in all_specs()]
    assert len(ids) == len(set(ids))
    for s in all_specs():
        if s.curated:
            (part,) = q(s.id, 0).parts
            assert len(set(part.options)) == len(part.options) >= 3


# ---------- invariants for everything ----------

@pytest.mark.parametrize("tid", SPEC_IDS)
def test_generation_invariants(tid):
    for seed in SEEDS:
        qu = q(tid, seed)
        assert qu.stem.strip() and qu.parts and qu.solution
        assert qu.id == f"{tid}#{seed}"
        for p in qu.parts:
            assert p.prompt.strip()
            if isinstance(p, NumericPart):
                assert math.isfinite(p.answer)
                assert p.tol.rel >= 0 and p.tol.abs >= 0
                # the exact answer must grade correct; its negation must not (unless ~0)
                assert p.grade(repr(p.answer)).correct
                if abs(p.answer) > 1e-6 and not p.tol.allows(-p.answer, p.answer) and (
                        p.approx is None or not p.tol.allows(-p.answer, p.approx)):
                    assert "sign" in p.grade(repr(-p.answer)).feedback
                if p.approx is not None:
                    assert math.isfinite(p.approx)
                    assert p.detail()                                      # both numbers are always shown
                    if p.accept_approx:
                        # the mental first-order route must itself pass the grader: tolerance is set accordingly
                        assert p.tol.allows(p.approx, p.answer), (qu.id, p.prompt, p.approx, p.answer)
                        assert p.grade(repr(p.approx)).correct
            else:
                assert isinstance(p, ChoicePart)
                assert 0 <= p.correct < len(p.options)
                assert len(set(p.options)) == len(p.options)
                assert p.grade(chr(65 + p.correct)).correct
                assert not p.grade(chr(65 + (p.correct + 1) % len(p.options))).correct


@pytest.mark.parametrize("tid", SPEC_IDS)
def test_deterministic_and_regenerable_from_id(tid):
    a, b = generate(tid, 42), from_id(f"{tid}#42")
    assert a.stem == b.stem and a.solution == b.solution
    assert [getattr(p, "answer", getattr(p, "correct", None)) for p in a.parts] == \
           [getattr(p, "answer", getattr(p, "correct", None)) for p in b.parts]


@pytest.mark.parametrize("tid", PY_TEMPLATES)
def test_seeds_give_variety(tid):
    assert len({q(tid, s).stem for s in range(30)}) > 20


@pytest.mark.parametrize("tid", PY_TEMPLATES)
def test_choice_answers_are_not_always_the_same_letter(tid):
    parts = [p for s in range(40) for p in q(tid, s).parts if isinstance(p, ChoicePart) and len(p.options) > 2]
    if parts:
        assert len({p.correct for p in parts}) > 1


# ---------- independent recomputation, template by template ----------

def test_forward_matches_closed_form():
    for seed in SEEDS:
        f = q("math.forward_1y", seed).facts
        s, za, zb = f["s"], f["za"], f["zb"]
        expected = (1 + zb) ** (s + 1) / (1 + za) ** s - 1
        assert q("math.forward_1y", seed).parts[0].answer == pytest.approx(expected * 100, abs=1e-9)
        assert (q("math.forward_1y", seed).parts[1].correct == 0) == (expected > zb)


def test_swap_dv01_pnl_matches_annuity_formula():
    for seed in SEEDS:
        qu = q("swaps.dv01_pnl", seed)
        f = qu.facts
        swap, mkt, move = f["swap"], f["mkt"], f["move"]
        periods = getattr(swap, "fixed_periods", None) or swap.periods
        dc = DayCount.THIRTY_E_360 if hasattr(swap, "fixed_periods") else DayCount.ACT_360
        annuity = sum(dc.fraction(p.start, p.end) * mkt.ois.df(p.pay) for p in periods)
        dv01_part, pnl_part = qu.parts
        assert abs(dv01_part.answer) == pytest.approx(swap.notional * annuity * 1e-4, rel=1e-5)
        assert (dv01_part.answer > 0) == (swap.side is Side.RECEIVE)
        assert pnl_part.answer == pytest.approx(-dv01_part.answer * move, rel=0.02)   # first order vs full reval
        assert pnl_part.approx == pytest.approx(-dv01_part.answer * move)
        assert (pnl_part.answer - pnl_part.approx) * dv01_part.answer >= 0            # convexity helps the long, hurts the short


def test_forward_start_matches_additivity_identity():
    for seed in SEEDS:
        qu = q("swaps.forward_start", seed)
        f = qu.facts
        mkt, a, b = f["mkt"], f["a"], f["b"]
        part = qu.parts[0]
        assert part.answer == pytest.approx(f["fwd"].par_rate(mkt) * 100, abs=1e-9)
        # the displayed (2dp) annuities reproduce the engine's forward within a bp
        assert f["exact"] == pytest.approx(f["fwd"].par_rate(mkt), abs=1e-4)
        assert part.tol.allows(f["exact"] * 100, part.answer)
        assert (qu.parts[1].options[qu.parts[1].correct] == "Above") == (f["fwd"].par_rate(mkt) > mkt.par_irs_rate(12 * b))


def test_fra_template_dv01_decomposition():
    """DV01 = N tau D(start)/(1 + F tau) x dF/dS: checked against a directly measured forward move."""
    for seed in SEEDS:
        qu = q("swaps.fra_dv01_pnl", seed)
        f = qu.facts
        fra, mkt = f["fra"], f["mkt"]
        tau = (fra.period.end - fra.period.start).days / 360
        up, dn = mkt.shifted(CurveShock.parallel(0.5)), mkt.shifted(CurveShock.parallel(-0.5))
        d_fwd_bp = (fra.forward(up) - fra.forward(dn)) / 1e-4
        sign = 1 if fra.side is Side.RECEIVE else -1
        disc = mkt.ois.df(fra.period.start) / (1 + fra.forward(mkt) * tau)
        dv01_part, pnl_part = qu.parts[:2]
        assert dv01_part.answer == pytest.approx(sign * fra.notional * tau * disc * 1e-4 * d_fwd_bp, rel=2e-3)
        assert 0.9 < d_fwd_bp < 1.05                                  # a 1bp par move is ~0.96bp on the ACT/360 forward
        assert 0.90 <= abs(dv01_part.answer) / (fra.notional * tau * 1e-4) <= 1.0     # mental N x tau x 1bp is a bit rich
        assert dv01_part.tol.allows(sign * fra.notional * tau * 1e-4, dv01_part.answer)  # ...but inside the tolerance
        assert pnl_part.answer == pytest.approx(-dv01_part.answer * f["move"], rel=0.01)


def test_hedge_template_is_dv01_neutral_with_right_direction():
    for seed in SEEDS:
        qu = q("hedging.swap_swap", seed)
        f = qu.facts
        trade, hedge, mkt = f["trade"], f["hedge"], f["mkt"]
        d_t, d_h = parallel_dv01(trade, mkt), parallel_dv01(hedge, mkt)
        assert d_t + d_h == pytest.approx(0, abs=1e-6 * abs(d_t))
        side_part, notional_part, pnl_part = qu.parts
        assert (side_part.correct == 0) == (d_t > 0)            # long duration => pay fixed hedge
        assert notional_part.answer == pytest.approx(hedge.notional)
        assert pnl_part.answer == pytest.approx(-f["move"] * d_t, rel=0.03)


def test_bond_template_matches_independent_reprice():
    for seed in SEEDS:
        qu = q("bonds.duration_convexity_pnl", seed)
        f = qu.facts
        dv01_part, dur_part, conv_part, exact_part = qu.parts
        sgn = -1 if f["short"] else 1
        h = 1e-6
        p_up = bond_price(f["coupon"], f["maturity"], f["y"] + h)
        p_dn = bond_price(f["coupon"], f["maturity"], f["y"] - h)
        fd_dv01 = sgn * f["face"] / 100 * (p_dn - p_up) / (2 * h) * 1e-4
        assert dv01_part.answer == pytest.approx(fd_dv01, rel=1e-5)
        assert (dv01_part.answer > 0) == (not f["short"])
        # duration + convexity is close to exact repricing (third-order error only) and always on the right side
        assert exact_part.approx == pytest.approx(dur_part.answer + conv_part.answer)
        assert exact_part.answer == pytest.approx(exact_part.approx, abs=0.04 * abs(exact_part.answer))
        assert (conv_part.answer > 0) == (not f["short"])
        assert abs(dur_part.answer - exact_part.answer) > abs(exact_part.approx - exact_part.answer)  # convexity improves it


def test_curve_trade_is_dv01_neutral_and_pnl_consistent():
    for seed in SEEDS:
        qu = q("curves.curve_trade", seed)
        f = qu.facts
        mkt, long_leg, short_leg = f["mkt"], f["long_leg"], f["short_leg"]
        d_long, d_short = parallel_dv01(long_leg, mkt), parallel_dv01(short_leg, mkt)
        assert d_long + d_short == pytest.approx(0, abs=1e-6 * abs(d_long))
        assert (long_leg.side is Side.PAY) == f["steepener"]    # steepener = pay the long end, receive the short end
        legs_part, notional_part, pnl_part, _ = qu.parts
        assert legs_part.options[legs_part.correct].startswith("Receive" if f["steepener"] else "Pay")
        sign = 1 if f["steepener"] else -1
        expected = sign * (f["b"] - f["a"]) * abs(d_long)       # steepener = spread change x |DV01|
        assert pnl_part.answer == pytest.approx(expected, abs=abs(d_long) * (0.01 + 0.01 * max(abs(f['a']), abs(f['b']))))   # net of two large legs: convexity
        assert notional_part.answer == pytest.approx(short_leg.notional)


def test_irs_vs_ois_template():
    for seed in SEEDS:
        qu = q("basis.irs_vs_ois", seed)
        f = qu.facts
        mkt, irs, ois, book = f["mkt"], f["irs"], f["ois"], f["book"]
        assert parallel_dv01(book, mkt) == pytest.approx(0, abs=1e-6 * abs(f["irs_dv01"]))
        assert irs.side is ois.side.opposite
        _, pnl_part, _ = qu.parts
        assert pnl_part.answer == pytest.approx(-f["move"] * f["irs_dv01"], rel=0.02)
        # receive IRS / pay OIS loses when the IRS rate rises relative to OIS
        assert (pnl_part.answer < 0) == ((irs.side is Side.RECEIVE) == (f["move"] > 0))


def test_tenor_basis_template():
    for seed in SEEDS:
        qu = q("basis.tenor_3s6s", seed)
        f = qu.facts
        swap, mkt = f["swap"], f["mkt"]
        annuity3 = sum((p.end - p.start).days / 360 * mkt.ois.df(p.pay) for p in swap.periods_3m)
        per_bp = swap.notional * 1e-4 * annuity3
        pos_part, pnl_part = qu.parts
        assert abs(f["basis_dv01"]) == pytest.approx(per_bp, rel=1e-3)
        assert (f["basis_dv01"] < 0) == f["long_basis"]
        # long the basis gains on widening: P&L sign = sign(move) for the long, opposite for the short
        assert (pnl_part.answer > 0) == ((f["move"] > 0) == f["long_basis"])
        assert pnl_part.answer == pytest.approx(per_bp * f["move"] * (1 if f["long_basis"] else -1), rel=0.03)


def test_client_trade_template_mechanics():
    for seed in SEEDS:
        qu = q("mm.client_trade_risk", seed)
        f = qu.facts
        quote, action, swap, hedge, mkt = f["quote"], f["action"], f["swap"], f["hedge"], f["mkt"]
        assert quote.bid < f["mid"] < quote.offer
        assert quote.mid == pytest.approx(f["mid"], abs=1e-9)
        pos, dv01_p, edge_p, hedge_p, unhedged_p, hedged_p = qu.parts
        pays = action is ClientAction.PAYS
        # client pays => trades at offer => dealer receives fixed => long duration => DV01 > 0
        assert swap.fixed_rate == (quote.offer if pays else quote.bid)
        assert (pos.correct == 0) == pays
        assert (dv01_p.answer > 0) == pays
        # edge = half-width x |DV01| (closed form, independent of the PV route used in the template)
        assert edge_p.answer == pytest.approx(f["w"] * abs(dv01_p.answer), rel=0.01)
        assert edge_p.answer > 0
        assert (hedge_p.answer < 0) == pays                     # long duration => pay fixed (negative signed notional)
        assert parallel_dv01(Portfolio([swap, hedge]), mkt) == pytest.approx(0, abs=1e-6 * abs(dv01_p.answer))
        assert unhedged_p.answer == pytest.approx(edge_p.answer - dv01_p.answer * f["m1"], rel=0.02, abs=0.02 * edge_p.answer)
        assert unhedged_p.approx == pytest.approx(f["total_approx"])
        assert hedged_p.answer == pytest.approx(-dv01_p.answer * f["m2"], rel=0.03)


def test_skew_template_answers_follow_the_model_and_are_unambiguous():
    for seed in SEEDS:
        qu = q("mm.skew_and_width", seed)
        ctx, b = qu.facts["ctx"], qu.facts["breakdown"]
        assert b == make_quote(ctx)
        dir_p, act_p, width_p = qu.parts
        assert dir_p.options[dir_p.correct].startswith({"higher": "Higher", "lower": "Lower", "neutral": "Symmetric"}[b.direction])
        # direction sanity from first principles: with no view, sign follows net inventory + expected flow
        net_risk = ctx.inventory_dv01 + 0.5 * ctx.expected_flow_dv01
        if ctx.conviction == 0 and net_risk > 0:
            assert b.direction == "higher"
        if ctx.conviction == 0 and net_risk < 0:
            assert b.direction == "lower"
        enc = b.encouraged_client_action
        assert (act_p.options[act_p.correct].startswith("Client RECEIVES")) == (enc is ClientAction.RECEIVES)
        assert b.quote.offer > b.quote.bid


# ---------- carry, roll-down, warehousing, attribution ----------

def test_swap_carry_roll_template_recomputed_independently():
    from rates_trainer.engine.dates import DayCount
    for seed in SEEDS:
        qu = q("carry.swap_carry_roll", seed)
        f = qu.facts
        mkt, swap, c, a1 = f["mkt"], f["swap"], f["c"], f["a1"]
        days = (a1 - mkt.anchor).days
        carry_p, roll_p, total_p, be_p, _ = qu.parts
        assert carry_p.answer + roll_p.answer + c.other == pytest.approx(total_p.answer)   # exact decomposition
        # independent accrual arithmetic, days x rates: the carry answer IS this number
        if f["kind"] == "IRS":
            p0 = swap.float_periods[0]
            short = mkt.projection("E6M").forward_rate(p0.start, p0.end)
            tau_fixed = DayCount.THIRTY_E_360.fraction(mkt.anchor, a1)
        else:
            short = (mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1) / (days / 360)
            tau_fixed = days / 360
        accrual = swap.side.sign * swap.notional * (swap.fixed_rate * tau_fixed - short * days / 360)
        assert carry_p.answer == pytest.approx(accrual, rel=1e-9)
        # ...and a student using the 3-decimal rate printed in the stem passes
        shown = swap.side.sign * swap.notional * (round(swap.fixed_rate, 5) * tau_fixed - round(short, 5) * days / 360)
        assert carry_p.tol.allows(shown, carry_p.answer)
        # signs follow position and curve: breakeven direction = sign of total / DV01
        assert (be_p.answer > 0) == (c.total_static / c.dv01 > 0)
        assert abs(c.total_forward) < 1e-3                                                  # par swap: forwards earn nothing
        assert be_p.answer == pytest.approx(c.total_static / c.dv01, abs=f["tb"] + 0.1)
        assert abs(c.other) <= 0.13 * f["gross"]


def test_warehousing_template_is_the_earning_side_and_cushion_is_consistent():
    for seed in SEEDS:
        qu = q("carry.warehousing", seed)
        f = qu.facts
        c, swap = f["c"], f["swap"]
        drift_p, total_p, _, sigma_p, cushion_p, reading_p = qu.parts
        assert c.total_static > 0.3 * abs(c.dv01)                                           # always the side that earns
        assert (swap.side is Side.RECEIVE) == (c.dv01 > 0)
        assert drift_p.answer == pytest.approx(f["drift"])
        assert total_p.approx == pytest.approx(c.dv01 * f["drift"])
        assert sigma_p.answer == pytest.approx(f["sigma_h"]) and f["n_bd"] in range(1, 70)
        assert cushion_p.answer == pytest.approx(abs(c.breakeven_bp) / f["sigma_h"] * 100)
        assert not 18.0 <= f["cushion"] <= 32.0                                              # no borderline readings
        assert (f["cushion"] < 25) == reading_p.options[reading_p.correct].startswith("The cushion is a small")
        assert abs(c.total_forward) < 1e-3                                                  # forwards realised: nothing


def test_curve_trade_carry_template_identity_and_breakeven():
    from rates_trainer.engine.carry import breakeven_move
    for seed in SEEDS:
        qu = q("carry.curve_trade", seed)
        f = qu.facts
        c, book, mkt = f["c"], f["book"], f["mkt"]
        long_leg, short_leg = f["long_leg"], f["short_leg"]
        assert parallel_dv01(book, mkt) == pytest.approx(0, abs=1e-6 * f["d_long"])         # DV01 neutral
        assert (long_leg.side is Side.PAY) == f["steepener"]
        drift_p, earn_p, total_p, be_p = qu.parts
        assert drift_p.answer == pytest.approx(f["drift"])
        assert (earn_p.options[earn_p.correct] == "It earns carry + roll-down") == (c.total_static > 0)
        # the identity: the book earns minus (position sign) x spread drift
        assert total_p.answer == pytest.approx(f["approx_total"], abs=f["tol_bp"] * f["d_long"])
        # breakeven by an independent full revaluation: shocking the spread by that amount zeroes the P&L
        static = mkt.rolled(f["a1"], "static")
        unit = CurveShock.points({float(f["short_t"]): 0.0, float(f["long_t"]): 1.0})
        shocked = static.shifted(CurveShock(tuple((t, b * be_p.answer) for t, b in unit.knots)))
        assert book.pv(shocked) - book.pv(mkt) == pytest.approx(0, abs=1.0)


def test_attribution_template_sums_and_dominance():
    for seed in SEEDS:
        qu = q("carry.attribution", seed)
        f = qu.facts
        att = f["att"]
        move_p, total_p, dom_p, resid_p = qu.parts
        assert att.time + att.delta + att.residual == pytest.approx(att.total)
        assert f["time_pnl"] == pytest.approx(att.time) and f["time_pnl"] + f["move_pnl"] == pytest.approx(att.total)
        gross = abs(f["d_s"] * f["a"]) + abs(f["d_l"] * f["b"])
        assert move_p.approx == pytest.approx(f["first"])
        # leg DV01 x the leg's own tenor move (the mental route) vs the engine's bucketed delta: they differ by
        # interpolation of the shock between buckets, a few percent of the gross leg P&L
        assert f["first"] == pytest.approx(att.delta, abs=0.07 * gross)
        assert move_p.answer == pytest.approx(f["move_pnl"])
        assert dom_p.options[dom_p.correct].startswith("The market move" if f["dominant"] == "market" else "Time")
        assert abs(att.residual) < 0.04 * (abs(f["d_s"] * f["a"]) + abs(f["d_l"] * f["b"]))
        assert (f["dominant"] == "market") == (abs(f["move_pnl"]) > abs(f["time_pnl"]))


def test_warehouse_carry_template_decision_logic():
    from rates_trainer.engine.dates import DayCount
    for seed in SEEDS:
        qu = q("mm.warehouse_carry", seed)
        f = qu.facts
        c, swap, quote, mkt, twin = f["c"], f["swap"], f["quote"], f["mkt"], f["twin"]
        carry_p, roll_p, sigma_p, cost_p, read_p = qu.parts
        assert swap.fixed_rate == (quote.offer if f["action"] is ClientAction.PAYS else quote.bid)
        # carry is the by-hand accrual at the rate the dealer DEALT at (the half-spread earns carry too)
        a1, days = f["a1"], (f["a1"] - mkt.anchor).days
        p0 = swap.float_periods[0]
        short = mkt.projection("E6M").forward_rate(p0.start, p0.end)
        by_hand = swap.side.sign * swap.notional * (swap.fixed_rate * DayCount.THIRTY_E_360.fraction(mkt.anchor, a1)
                                                    - short * days / 360)
        assert carry_p.answer == pytest.approx(by_hand, rel=1e-9)
        # roll-down is marked off the MID: it matches the at-market twin, not the off-market strike
        assert roll_p.approx == pytest.approx(f["est_roll"]) and roll_p.tol.allows(f["est_roll"], roll_p.answer)
        # the client edge is booked up front and EXCLUDED from carry + roll-down (a PV change, not a level)
        twin_c = carry_roll(twin, mkt, a1)
        assert c.total_static == pytest.approx(twin_c.total_static, abs=0.01 * abs(c.dv01))
        assert sigma_p.answer == pytest.approx(f["sigma_w"]) and cost_p.answer == pytest.approx(f["hedge_cost"])
        correct = read_p.options[read_p.correct]
        if c.total_static < 0:
            assert correct.startswith("Warehousing COSTS")
        elif f["r_cost"] < 0.7:
            assert "LESS than the cost of hedging" in correct
        else:
            assert "MORE than the cost of hedging" in correct
        assert not 0.7 <= f["r_cost"] <= 1.4


def test_a_lazy_answer_of_zero_never_passes_the_significant_parts():
    """Each scenario is drawn so its answer clearly exceeds the tolerance on it; otherwise 0 would be accepted."""
    for seed in SEEDS:
        for tid, idxs in (("carry.swap_carry_roll", (2, 3)), ("carry.warehousing", (1,)), ("carry.curve_trade", (2, 3))):
            parts = q(tid, seed).parts
            for i in idxs:
                p = parts[i]
                assert not p.tol.allows(0.0, p.answer), (tid, seed, i, p.answer, p.tol)
                assert not p.tol.allows(-p.answer, p.answer), (tid, seed, i)        # nor the wrong sign


# ---------- bonds vs swaps: ASW, hedging, repo, bond carry ----------

def test_asw_template_recomputed_by_hand():
    for seed in SEEDS:
        qu = q("rv.asw_package", seed)
        f = qu.facts
        mkt, bond = f["mkt"], f["bond"]
        asw_p, asw01_p, pnl_p, par_p = qu.parts
        # ASW by hand: (OIS-discounted bond cash flows - dirty price) / (ACT/360 annuity on the coupon dates)
        v = bond.coupon * sum(mkt.ois.df(p.pay) for p in bond.periods) + mkt.ois.df(bond.maturity)
        a = sum((p.end - p.start).days / 360 * mkt.ois.df(p.pay) for p in bond.periods)
        assert asw_p.answer == pytest.approx((v - f["price"] / 100) / a * 1e4, rel=1e-9)
        assert (asw_p.answer > 0) == (f["price"] / 100 < v)                      # cheap to the swap curve <=> positive ASW
        assert asw01_p.answer == pytest.approx(bond.notional * a * 1e-4, rel=1e-9)
        # package P&L: closed form N x A x (locked - new) = -move x ASW01, and tightening (move < 0) gains
        assert pnl_p.answer == pytest.approx(-f["move"] * asw01_p.answer, rel=1e-9)
        assert (pnl_p.answer > 0) == (f["move"] < 0)
        assert abs(f["par_pnl"]) < 1e-6 * bond.notional                         # no outright rate risk
        assert (par_p.options[par_p.correct]).startswith("About zero")


def test_bond_swap_hedge_template():
    for seed in SEEDS:
        qu = q("rv.bond_swap_hedge", seed)
        f = qu.facts
        mkt, bond, hedge = f["mkt"], f["bond"], f["hedge"]
        dv01_p, hedge_p, spread_p, rates_p = qu.parts
        assert parallel_dv01(f["book"], mkt) == pytest.approx(0, abs=1e-6 * abs(f["dv01"]))     # DV01-neutral
        assert (hedge.side is Side.PAY) == f["long"]                                              # long bond => pay fixed
        assert (dv01_p.answer > 0) == f["long"]
        # ASW P&L by hand: bond value is N(V - asw x A), so a move bp widening changes it by -N x A x move bp
        a = bond.spread_annuity(mkt)
        assert spread_p.answer == pytest.approx(-f["move"] * 1e-4 * bond.notional * a, rel=1e-9)
        assert (spread_p.answer < 0) == ((f["move"] > 0) == f["long"])
        assert abs(f["rates_pnl"]) < 0.12 * 10 * abs(f["dv01"])                 # outright rates mostly hedged out
        assert rates_p.options[rates_p.correct].startswith("Close to zero")


def test_repo_carry_template_arithmetic():
    from dataclasses import replace
    for seed in SEEDS:
        qu = q("bonds.repo_carry", seed)
        f = qu.facts
        mkt, bond, a1 = f["mkt"], f["bond"], f["a1"]
        carry_p, special_p, breakeven_p, short_p = qu.parts
        days, mv = f["days"], f["mv"]
        by_hand_accrual = bond.notional * bond.coupon * days / (bond.periods[0].end - bond.periods[0].start).days
        by_hand_fin = mv * (f["estr"] + bond.funding_spread) * days / 360
        assert carry_p.answer == pytest.approx(by_hand_accrual - by_hand_fin, rel=1e-3, abs=mv * 1e-5 * days / 360)
        assert special_p.answer == pytest.approx(mv * f["special_by"] * days / 360, rel=1e-3)
        # at the breakeven all-in repo rate the carry is zero
        zero = replace(bond, funding_spread=breakeven_p.answer / 100 - f["estr"])
        assert carry_roll(zero, mkt, a1).carry == pytest.approx(0, abs=0.002 * by_hand_accrual)
        assert breakeven_p.tol.allows(f["current_yield"] * 100, breakeven_p.answer)    # the quick 'current yield' form passes


def test_bond_carry_rolldown_template_identities():
    for seed in SEEDS:
        qu = q("bonds.carry_rolldown", seed)
        f = qu.facts
        mkt, bond, c, a1 = f["mkt"], f["bond"], f["c"], f["a1"]
        carry_p, pickup_p, roll_p, total_p, be_p = qu.parts
        assert c.other == pytest.approx(0, abs=1e-6)
        assert carry_p.answer + roll_p.answer + f["pull"] == pytest.approx(total_p.answer)      # carry + curve roll + pull = total
        assert pickup_p.answer == pytest.approx(c.carry + f["pull"])
        # exact: at an unchanged yield the dirty price grows by (1+y)^(days/period days)
        period_days = (bond.periods[0].end - bond.periods[0].start).days
        growth = f["mv"] * ((1 + f["y0"]) ** (f["days"] / period_days) - 1)
        assert pickup_p.answer == pytest.approx(growth - financing_cost(bond, mkt, a1), rel=1e-9)
        # forwards realised: only the funding spread survives
        assert c.total_forward == pytest.approx(-bond.funding_spread * f["mv"] * f["days"] / 360, abs=1e-6)
        # the answers clearly exceed their tolerances: lazy zero never passes the combined parts
        for p in (pickup_p, total_p):
            assert not p.tol.allows(0.0, p.answer)
        assert (be_p.answer > 0) == (total_p.answer / c.dv01 > 0)


# ---------- bond futures ----------

def _accrued_by_hand(bond, d):
    """ACT/ACT accrued per 100 on date d from the period containing d (independent of FixedBond.accrued)."""
    for p in bond.periods:
        if p.start <= d < p.end:
            return 100 * bond.coupon * (d - p.start).days / (p.end - p.start).days
    return 0.0


def _implied_repo_by_simulation(line, bond, anchor, delivery):
    """Solve for the repo at which: borrow dirty, receive any coupon (reinvested to delivery), pay loan back, receive invoice => 0."""
    dirty = line.clean + _accrued_by_hand(bond, anchor)
    days = (delivery - anchor).days
    paid = [p for p in bond.periods if anchor < p.pay <= delivery]
    cpn = 100 * bond.coupon if paid else 0.0
    cdays = (delivery - paid[0].pay).days if paid else 0
    invoice = line.futures_price * line.cf + _accrued_by_hand(bond, delivery)

    def net(r):
        return invoice + cpn * (1 + r * cdays / 360) - dirty * (1 + r * days / 360)
    lo, hi = -5.0, 5.0                                                 # net() is decreasing in r: bisect
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if net(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def test_conversion_factor_template_recomputed_by_hand():
    for seed in SEEDS:
        qu = q("futures.conversion_factor", seed)
        f = qu.facts
        case, i = f["case"], f["i"]
        b, l = case.fut.basket[i], case.lines[i]
        cf_p, invoice_p, gross_p, be_p = qu.parts
        m = f["months"]
        k = m % 12 or 12
        times = [(k + 12 * j) / 12 for j in range((m - k) // 12 + 1)]
        by_hand = sum(b.coupon / 1.06 ** t for t in times) + 1 / 1.06 ** (m / 12) - b.coupon * (12 - k) / 12
        assert cf_p.answer == pytest.approx(by_hand, abs=6e-7)
        assert cf_p.answer < 1 and abs(cf_p.approx - cf_p.answer) < 0.001
        assert invoice_p.answer == pytest.approx(1000 * (case.price * cf_p.answer + _accrued_by_hand(b, case.delivery)), rel=1e-6)
        assert gross_p.answer == pytest.approx(l.clean - case.price * cf_p.answer, abs=1e-6)
        assert be_p.answer == pytest.approx(l.clean / cf_p.answer, rel=1e-9)
        assert l.clean - be_p.answer * cf_p.answer == pytest.approx(0, abs=1e-9)                  # at the break-even price the gross basis is zero


def test_dv01_hedge_template_is_hedged_and_the_naive_hedge_is_wrong_in_the_right_direction():
    for seed in SEEDS:
        qu = q("futures.dv01_hedge", seed)
        f = qu.facts
        case, mkt = f["case"], f["case"].mkt
        dv01_p, hedge_p, naive_p, choice_p = qu.parts
        cf = case.lines[f["i"]].cf
        assert dv01_p.answer > 0
        assert dv01_p.answer == pytest.approx(f["fut_dv01"])
        assert (hedge_p.answer < 0) == f["long"]                                              # long bond => sell futures
        assert hedge_p.answer * dv01_p.answer + f["bond_dv01"] == pytest.approx(0, abs=1e-6 * abs(f["bond_dv01"]))
        assert hedge_p.approx == pytest.approx(-(1 if f["long"] else -1) * f["face"] * cf / 100_000)
        assert abs(f["n_naive"]) == pytest.approx(f["face"] / 100_000) and abs(f["n_naive"]) > abs(hedge_p.approx)     # face-for-face OVER-hedges
        # over-hedged: the naive book has the OPPOSITE sign of DV01 to the bond, so it gains when yields move against the bond
        net = f["bond_dv01"] + f["n_naive"] * f["fut_dv01"]
        assert net * f["bond_dv01"] < 0
        assert (naive_p.answer > 0) == (net * f["move"] < 0)
        assert choice_p.options[choice_p.correct].startswith("Rises")


def test_ctd_ranking_template_matches_an_independent_cash_flow_simulation():
    traps = 0
    for seed in SEEDS:
        qu = q("futures.ctd_ranking", seed)
        f = qu.facts
        case = f["case"]
        anchor, delivery = case.mkt.anchor, case.delivery
        implied = [_implied_repo_by_simulation(l, b, anchor, delivery) for l, b in zip(case.lines, case.fut.basket)]
        for l, r in zip(case.lines, implied):
            assert l.implied_repo == pytest.approx(r, abs=1e-9)
        # one repo rate for the whole basket: CTD = highest implied repo = lowest net basis
        assert len({round(x, 5) for x in case.repos}) == 1
        assert max(range(len(implied)), key=implied.__getitem__) == f["ci"] == min(range(len(case.lines)), key=lambda k: case.lines[k].net_basis)
        ctd_p, gross_p, net_p, ir_p, reading_p, *trap = qu.parts
        l = case.lines[f["ci"]]
        assert ctd_p.options[ctd_p.correct] == case.labels[f["ci"]]
        assert gross_p.answer == pytest.approx(l.clean - case.price * l.cf, abs=1e-9)
        assert net_p.answer == pytest.approx(l.gross_basis - l.carry, abs=1e-9) and net_p.answer > 0
        assert ir_p.answer / 100 < l.repo                                                       # the options make implied repo < repo
        # the trap part exists exactly when the lowest gross basis is not the CTD
        lowest_gross = min(range(len(case.lines)), key=lambda k: case.lines[k].gross_basis)
        assert bool(trap) == (lowest_gross != f["ci"]) == f["trap"]
        traps += bool(trap)
        # the mental route (no coupon reinvestment) names the same CTD
        mental = [x.gross_basis - (x.accrued_delivery - x.accrued0 + x.coupon_paid - x.dirty * x.repo * x.days / 360) for x in case.lines]
        assert min(range(len(mental)), key=mental.__getitem__) == f["ci"]
    assert 5 <= traps <= len(list(SEEDS)) - 5                                                   # both kinds of ranking occur


def test_ctd_switch_template_follows_the_model_and_the_future_never_beats_its_old_ctd():
    for seed in SEEDS:
        qu = q("futures.ctd_switch", seed)
        f = qu.facts
        case, x = f["case"], f["x"]
        fut, mkt = case.fut, case.mkt
        now, after, d_price_p, worse_p, pnl_p = qu.parts[0], qu.parts[1], qu.parts[2], qu.parts[3], qu.parts[4]
        f0 = fut.futures_equivalents(mkt)
        moved = mkt.shifted(CurveShock.parallel(x))
        f1 = fut.futures_equivalents(moved)
        assert now.options[now.correct] == case.labels[min(range(len(f0)), key=f0.__getitem__)]
        assert after.options[after.correct] == case.labels[min(range(len(f1)), key=f1.__getitem__)] != now.options[now.correct]
        assert d_price_p.answer == pytest.approx(min(f1) - fut.price_offset - (min(f0) - fut.price_offset), abs=1e-9)
        assert (d_price_p.answer < 0) == (x > 0)
        i0 = f["i0"]
        assert min(f1) < f1[i0] - 0.03                                                          # F strictly below the old CTD's price
        # the long basis: payoff minus premium, bounded below by minus the premium and consistent with the engine
        cf = case.lines[i0].cf
        assert f["nb0"] == pytest.approx(case.lines[i0].net_basis, abs=0.02)
        assert pnl_p.answer >= -f["nb0"] * f["face"] / 100 - 1e-6
        assert pnl_p.answer == pytest.approx(f["pnl_pts"] * f["face"] / 100)
        assert abs(pnl_p.answer) > pnl_p.tol.abs and abs(d_price_p.answer) > d_price_p.tol.abs


def test_basis_trade_template_decision_and_what_you_own():
    seen = set()
    for seed in SEEDS:
        qu = q("futures.basis_trade", seed)
        f = qu.facts
        case = f["case"]
        l = case.lines[f["ci"]]
        ctd_p, nb_p, decision_p, hedge_p, static_p, expected_p, risk_p = qu.parts
        assert ctd_p.options[ctd_p.correct] == case.labels[f["ci"]]
        assert nb_p.answer == pytest.approx(l.net_basis) and nb_p.answer > 0
        cheap = f["fair"] > l.net_basis
        assert cheap == f["cheap"]
        seen.add(cheap)
        assert decision_p.options[decision_p.correct].startswith("Buy the basis" if cheap else "Sell the basis")
        assert (hedge_p.answer < 0) == cheap                                                    # buy basis: long bond, SELL futures
        assert abs(hedge_p.approx) == pytest.approx(f["face"] * l.cf / 100_000)
        assert static_p.answer == pytest.approx((-1 if cheap else 1) * l.net_basis * f["face"] / 100)       # the premium is lost / kept
        assert expected_p.answer == pytest.approx(abs(f["fair"] - l.net_basis) * f["face"] / 100)
        assert expected_p.answer > 0 and abs(f["fair"] - l.net_basis) >= 0.04
        assert risk_p.options[risk_p.correct].startswith("Time decay" if cheap else "A big move")
    assert seen == {True, False}


def test_a_lazy_answer_of_zero_never_passes_the_futures_numerics():
    checks = {"futures.conversion_factor": (1, 2, 3), "futures.dv01_hedge": (0, 1, 2), "futures.ctd_ranking": (1, 2, 3),
              "futures.ctd_switch": (2, 4), "futures.basis_trade": (1, 3, 4, 5), "futures.stir_strip": (1, 2, 3)}
    for tid, idxs in checks.items():
        for seed in SEEDS:
            parts = q(tid, seed).parts
            for i in idxs:
                p = parts[i]
                assert not p.tol.allows(0.0, p.answer), (tid, seed, i, p.answer, p.tol)


def test_stir_strip_template_direction_sizes_and_prices():
    from rates_trainer.engine.dates import DayCount as DC
    from rates_trainer.engine.stir import imm_dates_after, third_wednesday
    for seed in SEEDS:
        qu = q("futures.stir_strip", seed)
        f = qu.facts
        mkt = f["mkt"]
        dir_p, total_p, price_p, strip_p, conv_p = qu.parts
        assert (total_p.answer < 0) == f["receive"]                                   # receiver is long duration: SELL the strip
        assert dir_p.options[dir_p.correct].startswith("SELL" if f["receive"] else "BUY")
        assert total_p.answer == pytest.approx(f["each"] * f["n"]) and total_p.approx == pytest.approx(-f["swap"].side.sign * abs(f["swap_dv01"]) / 25.0)
        # the strip alone and the swap alone offset (DV01-matched), and the strip pays EUR 25 x contracts x move (x ~0.965)
        assert strip_p.answer == pytest.approx(-f["unhedged"], rel=0.03)
        assert (strip_p.answer > 0) == (total_p.answer < 0)
        assert abs(f["residual"]) < 0.03 * abs(f["unhedged"])
        # price of the chosen contract by hand from the 3M curve
        dates = imm_dates_after(mkt.anchor, f["n"])
        a, b = dates[f["j"]], dates[f["j"] + 1]
        assert a == third_wednesday(a.year, a.month) and b.month in (3, 6, 9, 12)
        e3m = mkt.projection("E3M")
        fwd = (e3m.df(a) / e3m.df(b) - 1) / DC.ACT_360.fraction(a, b)
        assert price_p.answer == pytest.approx(100 - 100 * (fwd + f["ca_shown"] * 1e-4), abs=0.01)
        assert conv_p.options[conv_p.correct].startswith("Daily margining")
