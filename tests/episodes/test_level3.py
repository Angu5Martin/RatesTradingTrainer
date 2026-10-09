"""Level 3, the curve book: whole-book pricing, curve limit, bucket risk, hedging the curve, and the deferred slope check."""

import pytest

from rates_trainer.engine.instruments import IRSwap, Side
from rates_trainer.engine.risk import parallel_dv01, unit_dv01
from rates_trainer.episodes.assess import DecisionContext, VisibleClient, assess_hedge, assess_rfq
from rates_trainer.episodes.episode import Episode, bucket_dv01, reference_decision, run_policy
from rates_trainer.episodes.state import Desk, HedgeDecision, HedgeTrade, Limits, Position, Rating, Regime, book
from rates_trainer.marketmaking.quoting import ClientAction, Liquidity

L3 = ("mm.ep3_curve_book_ldi", "mm.ep3_curve_book_corporate")
DESK = Desk((2, 5, 10, 30), Limits(500e3, 250e3), multi_tenor=True)


def _ctx(mkt, legs, client=None, slope_limit=250e3):
    pos = tuple(Position(IRSwap.new(Side.RECEIVE if d > 0 else Side.PAY, abs(d) / unit_dv01(t, mkt) * 1e6, mkt.par_irs_rate(12 * t), mkt.spot, 12 * t),
                         "initial", f"{t}Y", -1) for t, d in legs)
    reg = Regime(1.0, Liquidity.NORMAL, (("asset_manager", 1),), 0.5, 0.125, "test", 0.3 * 500e3 / unit_dv01(10, mkt) * 1e6)
    desk = Desk((2, 5, 10, 30), Limits(500e3, slope_limit), multi_tenor=True)
    t = client.tenor if client else 10
    return DecisionContext(mkt, pos, 500e3, reg, t, client, desk=desk, home=10)


def test_risk_equivalent_inventory_sees_through_the_curve(mkt):
    """A long-30Y / short-2Y book has almost no DV01 but behaves like a large 30Y receiver for a 30Y request: the reference price must
    lean against a client who would make it longer at 30Y, and welcome one who would take 30Y off it."""
    ctx = _ctx(mkt, [(30, 150e3), (2, -150e3)])
    assert abs(ctx.dv01) < 0.05 * 500e3
    # Cov(book, 30Y) / Var(30Y): a 30Y swap is mostly level, the book is all slope, so the equivalent is positive but well below the
    # 150k leg; in the 2Y the same book looks SHORT. The single DV01 number (~0) sees neither.
    assert ctx.risk_equivalent(30) > 0.05 * 500e3 and ctx.risk_equivalent(2) < -0.05 * 500e3
    # a trade about the size of the risk-equivalent takes risk off; a much bigger one in the same direction would ADD level risk
    n = ctx.risk_equivalent(30) / unit_dv01(30, mkt) * 1e6
    takes_off = _ctx(mkt, [(30, 150e3), (2, -150e3)], VisibleClient("asset_manager", ClientAction.RECEIVES, n, 30))   # you would pay 30Y
    adds = _ctx(mkt, [(30, 150e3), (2, -150e3)], VisibleClient("asset_manager", ClientAction.PAYS, n, 30))           # you would receive 30Y
    a_off, a_add = assess_rfq(takes_off, None), assess_rfq(adds, None)
    assert a_off.metrics["reduces"] and not a_add.metrics["reduces"]
    assert a_off.metrics["ref_charge"] < a_add.metrics["ref_charge"]      # aggressive for the axe, wide for the risk-adder
    # passing on the axe is poor even though the DV01 was flat
    assert a_off.rating is Rating.POOR


def test_a_trade_that_cuts_dv01_can_add_risk_and_the_assessment_says_so(mkt):
    ctx = _ctx(mkt, [(10, 200e3)], VisibleClient("asset_manager", ClientAction.RECEIVES, 0.4 * 500e3 / unit_dv01(2, mkt) * 1e6, 2))
    a = assess_rfq(ctx, assess_rfq(ctx, None).metrics["ref_level"])
    assert a.metrics["dv01_after"] < ctx.dv01                            # DV01 falls...
    assert any("curve" in r for r in a.reasons) or a.metrics["reduces"]


def test_ending_over_the_curve_limit_is_an_error(mkt):
    ctx = _ctx(mkt, [(30, 100e3), (2, -100e3)], slope_limit=150e3)
    assert abs(ctx.slope) > 150e3                                      # starts over the curve limit
    keep = assess_hedge(ctx, HedgeDecision((), "keep"))
    assert keep.rating is Rating.ERROR and any("curve limit" in r for r in keep.reasons)
    level_only = assess_hedge(ctx, HedgeDecision((ctx.hedge_trade_for(1.0, 10),) if ctx.hedge_trade_for(1.0, 10) else ()))
    assert level_only.rating is Rating.ERROR                           # a level hedge does not fix a curve breach
    curve = assess_hedge(ctx, ctx.level_and_slope_hedge(30, 2))
    assert curve.rating is not Rating.ERROR and abs(curve.metrics["slope_after"]) < 1.0


def test_flatten_removes_level_slope_and_curvature(mkt):
    ctx = _ctx(mkt, [(5, 120e3), (30, -60e3), (2, 40e3)])
    x, cost = ctx.after(ctx.flatten_curve_hedge())
    assert all(abs(x[k]) < 1.0 for k in ("level", "slope", "curvature")) and cost > 0


def test_bucket_dv01_sums_to_parallel_dv01(mkt):
    ctx = _ctx(mkt, [(5, 120e3), (30, -60e3), (2, 40e3)])
    bk = bucket_dv01(book(ctx.positions), mkt)
    assert sum(bk.values()) == pytest.approx(parallel_dv01(book(ctx.positions), mkt), rel=1e-3)
    assert bk[5] > 0 > bk[30] and bk[2] > 0 and abs(bk[10]) < 0.05 * 120e3


def test_slope_checkpoint_is_correct_and_its_answer_is_withheld_until_after_pricing():
    for eid in L3:
        ep = Episode(eid, 3)
        while ep.round < 1:
            ep.submit(reference_decision(ep, ep.observe()))
        obs = ep.observe()
        assert obs.kind == "checkpoint" and ep.plan.checkpoint == "slope_if_dealt"
        q = ep.inquiries[1]
        expected = obs.ctx.slope + obs.ctx.trade_exposure(q.action, q.notional, q.tenor)["slope"]
        assert obs.part.answer == pytest.approx(expected)
        res = ep.submit(reference_decision(ep, obs))
        assert "checked after you price" in " ".join(res.lines) and "It is" not in " ".join(res.lines)
        res2 = ep.submit(reference_decision(ep, ep.observe()))
        assert "slope check" in res2.lines[0].lower()


def test_rfq_screen_shows_the_trades_own_dv01_but_not_its_effect_on_the_book():
    for eid in L3:
        ep = Episode(eid, 5)
        while not ep.done:
            obs = ep.observe()
            if obs.kind == "rfq":
                text = "\n".join(obs.lines).lower()
                assert "if it deals, you" in text                     # the request and its own DV01
                for leak in ("would become", "after the trade", "behaves like", "risk-equivalent", "equivalent"):
                    assert leak not in text
            ep.submit(reference_decision(ep, obs))


def test_hedging_only_the_level_runs_the_curve_and_is_rated_below_the_reference():
    worse = 0
    for eid in L3:
        for seed in range(4):
            ep = run_policy(eid, seed, list(Episode(eid, seed, render=False).policies().values())[1])   # "hedge the level in the 10Y only"
            ratings = [a.rating for r in ep.records for k, _, a in r.decisions if k == "hedge"]
            worse += sum(rt in (Rating.POOR, Rating.DEFENSIBLE, Rating.ERROR) for rt in ratings)
    assert worse > 0


def test_variants_differ_in_their_structural_flow():
    ldi = [q for s in range(10) for q in Episode(L3[0], s, render=False).inquiries]
    corp = [q for s in range(10) for q in Episode(L3[1], s, render=False).inquiries]
    assert sum(q.tenor == 30 for q in ldi) > sum(q.tenor == 30 for q in corp)
    assert sum(q.tenor in (2, 5) for q in corp) > sum(q.tenor in (2, 5) for q in ldi)


def test_whether_a_trade_reduces_risk_depends_on_its_size(mkt):
    """On a flat-DV01 curve book, paying a little 30Y reduces risk; paying a lot adds outright risk faster than it removes curve risk."""
    base = _ctx(mkt, [(30, 150e3), (2, -150e3)])
    small = base.risk_equivalent(30) / unit_dv01(30, mkt) * 1e6
    big = 4 * small
    r_small = assess_rfq(_ctx(mkt, [(30, 150e3), (2, -150e3)], VisibleClient("asset_manager", ClientAction.RECEIVES, small, 30)), None)
    r_big = assess_rfq(_ctx(mkt, [(30, 150e3), (2, -150e3)], VisibleClient("asset_manager", ClientAction.RECEIVES, big, 30)), None)
    assert r_small.metrics["reduces"] and not r_big.metrics["reduces"]
