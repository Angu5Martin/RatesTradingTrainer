"""Episodes: determinism and replay, decision-independent market and clients, no hindsight in the assessment, P&L conservation,
assessment sanity (errors, consistency, several sound choices), and the terminal adapter."""

import math
import statistics
from dataclasses import replace

import pytest

from rates_trainer.engine.instruments import IRSwap, Side
from rates_trainer.engine.risk import unit_dv01
from rates_trainer.episodes.assess import DecisionContext, VisibleClient, assess_hedge, assess_quote, assess_rfq
from rates_trainer.episodes.decisions import parse_hedge, parse_quote, parse_rfq
from rates_trainer.episodes.episode import POLICIES, Episode, all_episodes, run_policy
from rates_trainer.episodes.factors import CURVE_FACTORS, step_vol
from rates_trainer.episodes.state import (INFORMED_DRIFT_BP, ExpectedFlow, HedgeDecision, HedgeTrade, Position, Rating, Regime,
                                          book)
from rates_trainer.marketmaking.quoting import BP, ClientAction, Liquidity, Quote

L1, L2 = "mm.ep1_single_trade", "mm.ep2_inventory_loop"
REF, FULL, NONE = list(POLICIES.values())
SEEDS = range(6)


def _ratings(ep):
    return [(r.round, k, a.rating) for r in ep.records for k, _, a in r.decisions if a]


def _assessments(ep, rnd):
    return [(k, a.rating, round(a.expected_pnl, 6), round(a.variance, 3), tuple(a.reasons))
            for r in ep.records if r.round == rnd for k, _, a in r.decisions if a]


# ------------------------------------------------------------------------------------------ registry and structure

def test_five_levels_are_registered_with_known_skills():
    from rates_trainer.curriculum.skills import SKILLS
    eps = all_episodes()
    assert [e.level for e in eps] == [1, 2, 3, 3, 4, 5]
    assert all(e.skill in SKILLS and not SKILLS[e.skill].planned for e in eps)


# ------------------------------------------------------------------------------------------ determinism and fairness

@pytest.mark.parametrize("eid", [L1, L2])
def test_replay_is_exact(eid):
    for seed in (1, 7):
        a, b = run_policy(eid, seed, REF), run_policy(eid, seed, REF)
        assert [e.amount for e in a.ledger] == [e.amount for e in b.ledger]
        assert _ratings(a) == _ratings(b)
        assert a.debrief(compare=False) == b.debrief(compare=False)


@pytest.mark.parametrize("eid", [L1, L2])
def test_clients_and_market_path_do_not_depend_on_decisions(eid):
    for seed in SEEDS:
        runs = [run_policy(eid, seed, p) for p in (REF, FULL, NONE)]
        first = runs[0]
        for other in runs[1:]:
            assert other.inquiries == first.inquiries
            assert other.uniforms == first.uniforms
            assert [r.moves for r in other.records] == [r.moves for r in first.records]
            assert other.mkt.quotes == first.mkt.quotes                     # the same curve at the end, whatever was traded


@pytest.mark.parametrize("eid", [L1, L2])
def test_a_fill_is_the_fixed_uniform_against_the_decision_dependent_probability(eid):
    for seed in SEEDS:
        ep = run_policy(eid, seed, REF)
        for r in ep.records:
            if r.p_fill > 0:
                assert r.filled == (ep.uniforms[r.round] < r.p_fill)


# ------------------------------------------------------------------------------------------ no hindsight

@pytest.mark.parametrize("eid", [L1, L2])
def test_assessment_does_not_see_the_market_path(eid):
    """Everything decided before the first move is assessed identically whatever the market then does."""
    for seed in SEEDS:
        a = run_policy(eid, seed, REF, market_seed=seed)
        b = run_policy(eid, seed, REF, market_seed=seed + 1000)
        assert [r.moves for r in a.records] != [r.moves for r in b.records]
        assert _assessments(a, 0) == _assessments(b, 0)


@pytest.mark.parametrize("eid", [L1, L2])
def test_assessment_does_not_know_whether_a_client_is_informed(eid):
    for seed in SEEDS:
        a = Episode(eid, seed)
        b = Episode(eid, seed)
        b.inquiries = [replace(q, informed=not q.informed) for q in b.inquiries]
        for ep in (a, b):
            while not ep.done and ep.round == 0:
                ep.submit(REF(ep, ep.observe()))
        assert _assessments(a, 0) == _assessments(b, 0)


def test_informed_clients_move_the_market_their_way_by_the_stated_drift():
    seen = 0
    for seed in range(15):
        ep = run_policy(L2, seed, NONE)
        reg = ep.setup.regime
        for r in ep.records:
            base = ep.z[r.round]["level"] * step_vol("level", reg.vol, reg.dt)
            drift = r.moves["level"] - base
            if r.inquiry.informed:
                seen += 1
                sign = 1 if r.inquiry.action is ClientAction.PAYS else -1          # a payer profits when rates rise
                assert drift == pytest.approx(sign * INFORMED_DRIFT_BP * reg.vol)
            else:
                assert drift == pytest.approx(0.0, abs=1e-12)
    assert seen > 0


# ------------------------------------------------------------------------------------------ P&L

@pytest.mark.parametrize("eid", [L1, L2])
def test_ledger_equals_full_revaluation_of_the_book(eid):
    for seed in SEEDS:
        for pol in (REF, NONE):
            ep = run_policy(eid, seed, pol)
            change = book(ep.positions).pv(ep.mkt) - ep.pv0
            assert sum(e.amount for e in ep.ledger) == pytest.approx(change, abs=1e-6 * max(1.0, abs(change)))
            # the convexity/cross term is second order: small next to the first-order market P&L
            first = sum(abs(e.amount) for e in ep.ledger if e.cause.startswith("market"))
            resid = sum(abs(e.amount) for e in ep.ledger if e.cause == "convexity/cross")
            assert resid <= 0.05 * first + 1.0


def test_edge_and_hedge_cost_signs():
    for seed in SEEDS:
        ep = run_policy(L2, seed, FULL)
        assert all(e.amount > 0 for e in ep.ledger if e.cause == "edge")          # the reference quotes are never through mid on a fill...
        assert all(e.amount < 0 for e in ep.ledger if e.cause == "hedge cost")    # ...and crossing the street always costs


def test_luck_is_centred_on_zero_across_many_paths():
    """Expected P&L is an unbiased forecast in the model: luck averages out (it is not a hidden bias)."""
    zs = []
    for seed in range(60):
        ep = run_policy(L1, seed, REF)
        sigma = math.sqrt(sum(r.variance for r in ep.records))
        if sigma > 0:
            zs.append((ep.pnl_total() - sum(r.expected for r in ep.records)) / sigma)
    assert abs(statistics.mean(zs)) < 0.5 and 0.3 < statistics.pstdev(zs) < 2.5


# ------------------------------------------------------------------------------------------ assessment sanity

@pytest.mark.parametrize("eid", [L1, L2])
def test_the_reference_policy_is_never_poor_and_mostly_sound(eid):
    ratings = [rt for seed in range(15 if eid == L2 else 30) for _, _, rt in _ratings(run_policy(eid, seed, REF))]
    assert all(rt in (Rating.SOUND, Rating.DEFENSIBLE) for rt in ratings)
    assert sum(rt is Rating.SOUND for rt in ratings) >= 0.85 * len(ratings)


def _greedy(ep, obs):
    """Never passes, never hedges: walks into limit breaches."""
    from rates_trainer.episodes.state import RFQDecision
    if obs.kind == "rfq":
        return RFQDecision(assess_rfq(obs.ctx, None).metrics["ref_level"])
    return NONE(ep, obs)


def test_ending_over_the_limit_is_an_error():
    found = 0
    for seed in range(20):
        ep = run_policy(L2, seed, _greedy)
        for r in ep.records:
            for k, _, a in r.decisions:
                if k == "hedge" and abs(a.metrics["dv01_after"]) > ep.setup.limit:
                    found += 1
                    assert a.rating is Rating.ERROR
    assert found > 0


def _ctx(mkt, tenor=10, inv_frac=0.5, limit=300e3, vol=1.0, liq=Liquidity.NORMAL, expected=None, client=None, p_pays=0.5,
         mix=(("pension", 1),)):
    dv = unit_dv01(tenor, mkt)
    pos = ()
    if inv_frac:
        n = abs(inv_frac) * limit / dv * 1e6
        pos = (Position(IRSwap.new(Side.RECEIVE if inv_frac > 0 else Side.PAY, n, mkt.par_irs_rate(12 * tenor), mkt.spot, 12 * tenor),
                        "initial", "x", -1),)
    reg = Regime(vol, liq, mix, p_pays, 0.25, "test", 0.4 * limit / dv * 1e6, expected)
    return DecisionContext(mkt, pos, limit, reg, tenor, client)


def test_a_hedge_that_adds_risk_is_an_error(mkt):
    ctx = _ctx(mkt, inv_frac=0.5)
    wrong = HedgeDecision((HedgeTrade(10, Side.RECEIVE, 50e6),), "receive more")
    assert assess_hedge(ctx, wrong).rating is Rating.ERROR
    right = HedgeDecision((ctx.hedge_trade_for(1.0, 10),), "full")
    assert right.trades[0].side is Side.PAY and assess_hedge(ctx, right).rating is Rating.SOUND


def test_warehousing_is_sound_for_a_small_calm_position_and_poor_for_a_large_stressed_one(mkt):
    small = _ctx(mkt, inv_frac=0.1, vol=0.6)
    big = _ctx(mkt, inv_frac=0.9, vol=1.8, liq=Liquidity.THIN)
    keep = HedgeDecision((), "warehouse")
    assert assess_hedge(small, keep).rating is Rating.SOUND
    assert assess_hedge(big, keep).rating is Rating.POOR
    # and with the small position, hedging fully is ALSO sound: several choices are reasonable
    assert assess_hedge(small, HedgeDecision((small.hedge_trade_for(1.0, 10),))).rating is Rating.SOUND


def test_two_way_flow_nets_small_positions_more_than_large_ones(mkt):
    small, large = _ctx(mkt, inv_frac=0.1), _ctx(mkt, inv_frac=0.9)
    assert small.absorbed(small.dv01) / abs(small.dv01) > large.absorbed(large.dv01) / abs(large.dv01)
    assert 0 < large.absorbed(large.dv01) < abs(large.dv01)


def test_expected_offsetting_flow_makes_warehousing_more_attractive(mkt):
    keep = HedgeDecision((), "warehouse")
    none = _ctx(mkt, inv_frac=0.4)
    offset = _ctx(mkt, inv_frac=0.4, expected=ExpectedFlow(ClientAction.RECEIVES, 150e6, 0.8, "a client receives later"))
    adds = _ctx(mkt, inv_frac=0.4, expected=ExpectedFlow(ClientAction.PAYS, 150e6, 0.8, "a client pays later"))
    e_none, e_off, e_add = (c.hedge_value(keep)[0] for c in (none, offset, adds))
    assert e_off > e_none
    assert e_add <= e_none + 1e-9                                  # flow on the SAME side does not take risk off you (it adds a skew)
    assert offset.absorbed(offset.dv01) > none.absorbed(none.dv01) >= adds.absorbed(adds.dv01)


def test_a_neighbouring_tenor_hedge_leaves_a_curve_position_that_the_assessment_names(mkt):
    ctx = _ctx(mkt, tenor=10, inv_frac=0.6, limit=500e3)
    a = assess_hedge(ctx, HedgeDecision((ctx.hedge_trade_for(1.0, 30),)))
    assert abs(a.metrics["dv01_after"]) < 0.01 * ctx.limit
    assert abs(a.metrics["curve_after"]) > 0.3 * ctx.limit
    assert any("curve position" in r for r in a.reasons)
    # a level-and-curve hedge removes both
    lc = ctx.level_and_slope_hedge(30)
    x, _ = ctx.after(lc)
    assert abs(x["level"]) < 1.0 and abs(x["slope"]) < 1.0


def test_quote_skewed_the_wrong_way_is_poor_and_crossing_the_street_is_an_error(mkt):
    ctx = _ctx(mkt, inv_frac=0.8)                                  # long: should quote HIGHER
    ref = ctx.reference()
    assert ref.net_shift_bp > 0.05
    mid, hw = ctx.mid(10), (ref.bid_half_width_bp + ref.offer_half_width_bp) / 2 * BP
    assert assess_quote(ctx, ref.quote).rating is Rating.SOUND
    lower = Quote(mid - 0.2 * BP - hw, mid - 0.2 * BP + hw)
    assert assess_quote(ctx, lower).rating is Rating.POOR
    centred = Quote(mid - hw, mid + hw)
    assert assess_quote(ctx, centred).rating is Rating.DEFENSIBLE
    st = ctx.street()
    crossing = Quote(st.offer + 0.1 * BP, st.offer + 0.5 * BP)
    assert assess_quote(ctx, crossing).rating is Rating.ERROR


def test_quote_consequences_skewing_up_attracts_receivers(mkt):
    ctx = _ctx(mkt, inv_frac=0.0)
    mid = ctx.mid(10)
    up, down = Quote(mid - 0.1 * BP, mid + 0.4 * BP), Quote(mid - 0.4 * BP, mid + 0.1 * BP)
    au, ad = assess_quote(ctx, up), assess_quote(ctx, down)
    assert au.metrics["p_fill_receives"] > ad.metrics["p_fill_receives"]
    assert au.metrics["p_fill_pays"] < ad.metrics["p_fill_pays"]


def test_rfq_rules_axe_breach_and_through_mid(mkt):
    dv = unit_dv01(10, mkt)
    # long book; a client wants to RECEIVE (you would pay: reduces risk) -> passing is poor
    axe = _ctx(mkt, inv_frac=0.6, client=VisibleClient("pension", ClientAction.RECEIVES, 0.3 * 300e3 / dv * 1e6))
    assert assess_rfq(axe, None).rating is Rating.POOR
    assert assess_rfq(axe, assess_rfq(axe, None).metrics["ref_level"]).rating is Rating.SOUND
    # long book near the limit; a client wants to PAY a size that would breach -> passing is sound
    breach = _ctx(mkt, inv_frac=0.8, client=VisibleClient("pension", ClientAction.PAYS, 0.4 * 300e3 / dv * 1e6))
    assert assess_rfq(breach, None).rating is Rating.SOUND
    # flat book, risk-adding trade priced THROUGH mid -> poor
    flat = _ctx(mkt, inv_frac=0.0, client=VisibleClient("asset_manager", ClientAction.PAYS, 0.3 * 300e3 / dv * 1e6))
    mid = flat.mid(10)
    assert assess_rfq(flat, mid - 0.3 * BP).rating is Rating.POOR       # client pays: you receive BELOW mid
    assert assess_rfq(flat, assess_rfq(flat, None).metrics["ref_level"]).rating is Rating.SOUND


def test_a_client_that_looks_informed_gets_a_wider_reference_price(mkt):
    dv = unit_dv01(10, mkt)
    n = 0.3 * 300e3 / dv * 1e6
    pension = _ctx(mkt, inv_frac=0.0, client=VisibleClient("pension", ClientAction.PAYS, n))
    fund = _ctx(mkt, inv_frac=0.0, client=VisibleClient("fast_money", ClientAction.PAYS, n))
    assert assess_rfq(fund, None).metrics["ref_charge"] > assess_rfq(pension, None).metrics["ref_charge"]


def test_several_alternatives_are_often_sound_and_warehousing_sometimes_is():
    multi = total = warehouse_sound = 0
    for seed in range(15):
        ep = run_policy(L2, seed, NONE)
        for r in ep.records:
            for k, _, a in r.decisions:
                if k == "hedge":
                    total += 1
                    sound = [l for l, _, _, rt in a.table if rt is Rating.SOUND]
                    multi += len(sound) >= 2
                    warehouse_sound += "Warehouse (no hedge)" in sound
    assert multi >= 0.3 * total and warehouse_sound >= 0.05 * total


# ------------------------------------------------------------------------------------------ input parsing and the adapter

def test_parsing(mkt):
    assert parse_quote("2.843 2.847").bid == pytest.approx(0.02843) and parse_quote("2.843/2.847").offer == pytest.approx(0.02847)
    for bad in ("2.847 2.843", "2.84", "abc def"):
        with pytest.raises(ValueError):
            parse_quote(bad)
    assert parse_rfq("pass").level is None and parse_rfq("2.8465").level == pytest.approx(0.028465)
    ctx = _ctx(mkt, inv_frac=0.5)
    assert parse_hedge("none", ctx).trades == ()
    half = parse_hedge("50%", ctx).trades[0]
    assert half.side is Side.PAY and half.tenor == 10
    assert parse_hedge("100% 5y", ctx).trades[0].tenor == 5
    two = parse_hedge("pay 100m 10y + receive 40m 30y", ctx).trades
    assert [(t.side, t.notional, t.tenor) for t in two] == [(Side.PAY, 100e6, 10), (Side.RECEIVE, 40e6, 30)]
    for bad in ("50", "pay 10y", "100% 7y", "sell 10m"):
        with pytest.raises(ValueError):
            parse_hedge(bad, ctx)


@pytest.mark.parametrize("eid", [L1, L2])
def test_nothing_from_the_assessment_is_shown_before_the_trainee_commits(eid):
    """Observations carry only state; benchmarks, ratings and expected values exist only in the result of submit()."""
    import dataclasses
    from rates_trainer.episodes.episode import Observation
    assert not any("assess" in f.name or "rating" in f.name for f in dataclasses.fields(Observation))
    for seed in range(3):
        ep = Episode(eid, seed)
        while not ep.done:
            obs = ep.observe()
            text = "\n".join(obs.lines + [obs.prompt, obs.input_hint]).lower()
            for leaked in ("sound", "defensible", "poor", "sigma", "benchmark", "warehouse (no hedge)", "best balance"):
                assert leaked not in text, (eid, seed, obs.kind, leaked)
            if obs.kind == "hedge":
                assert "volatility" in text and "last inquiry" in text and "street" in text     # what IS known is shown
            res = ep.submit(REF(ep, obs))
            if obs.kind == "hedge":
                assert res.assessment.table                                                       # ... and the reveal comes after


def test_terminal_adapter_plays_an_episode_and_reprompts_bad_input():
    from rates_trainer.episode_session import run_episode
    ep = Episode(L1, 3)
    mid = ep.observe().ctx.mid(ep.setup.tenor) * 100
    answers = iter(["nonsense", f"{mid - 0.003:.4f} {mid + 0.003:.4f}", "500k", "frobnicate", "100%"])
    out = []
    assert run_episode(ep, ask=lambda _: next(answers), say=out.append, compare=False)
    text = "\n".join(out)
    assert "DEBRIEF" in text and "Your decision:" in text and "LUCK" in text
    # the reveal follows the commitment: the hedge input comes before the benchmark table in the transcript
    assert text.index("Hedge, partly hedge, or warehouse?") < text.index("Revealed now that you have committed")
    assert run_episode(Episode(L2, 1), ask=lambda _: "q", say=lambda s: None) is False


def test_cli_episode_command(monkeypatch, capsys):
    from rates_trainer.cli import main
    answers = iter(["q"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(["episode", "-L", "2", "--seed", "4"]) == 0
    assert "mm.ep2_inventory_loop#4" in capsys.readouterr().out
