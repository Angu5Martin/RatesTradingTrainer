"""Level 5: evidence and the posterior, no inference shown to the trainee, view sizing, the release, the limit cut, the price decomposition,
and the 200-path distribution (a supplement to the same-path comparison)."""

import math
import random
import statistics

import pytest

from rates_trainer.engine.instruments import IRSwap, Side
from rates_trainer.engine.risk import unit_dv01
from rates_trainer.episodes.assess import DecisionContext, Info, VisibleClient, assess_hedge, assess_rfq, best_alternative
from rates_trainer.episodes.decisions import parse_position
from rates_trainer.episodes.episode import PATHS, Episode, path_pnls, reference_decision, run_policy
from rates_trainer.episodes.evidence import Evidence, posterior
from rates_trainer.episodes.state import Desk, HedgeDecision, Limits, Position, Rating, Regime
from rates_trainer.marketmaking.quoting import ClientAction, Liquidity

L5 = "mm.ep5_information_views"


# ------------------------------------------------------------------------------------------ the posterior

def test_posterior_moves_the_right_way():
    prior = 0.3
    e_for = Evidence("X", +1, +2.0, 1.8, 1.5)          # it paid, then rates rose: consistent with being informed
    e_against = Evidence("X", +1, -2.0, 1.8, 1.5)
    assert posterior(prior, []) == pytest.approx(prior)
    assert posterior(prior, [e_for]) > prior > posterior(prior, [e_against])
    assert posterior(prior, [e_for, e_for]) > posterior(prior, [e_for])
    assert posterior(prior, [Evidence("X", +1, 1.5, 1.8, 1.5, mu=1.5)]) < posterior(prior, [Evidence("X", +1, 1.5, 1.8, 1.5)])   # explained by the view


def test_posterior_is_calibrated_against_simulation():
    """Draw the truth from the prior and the moves from the model: among histories given P ~ p, about p of clients are informed."""
    rng = random.Random(7)
    prior, sd, drift = 0.3, 1.8, 1.5
    bins: dict[int, list[int]] = {}
    for _ in range(20000):
        informed = rng.random() < prior
        ev = []
        for _ in range(rng.choice([1, 2, 3])):
            sign = rng.choice([-1, 1])
            ev.append(Evidence("X", sign, rng.gauss(sign * drift if informed else 0.0, sd), sd, drift))
        p = posterior(prior, ev)
        bins.setdefault(min(9, int(p * 10)), []).append(informed)
    for b, xs in bins.items():
        if len(xs) > 400:
            assert statistics.mean(xs) == pytest.approx((b + 0.5) / 10, abs=0.07), b


def test_the_episode_records_evidence_only_from_observables():
    ep = run_policy(L5, 3, lambda e, o: reference_decision(e, o))
    for ev, rec in zip(ep.evidence, [r for r in ep.records if r.plan.pricing]):
        assert ev.move == pytest.approx(rec.moves["level"])          # the observed move, nothing else
        assert ev.name == rec.inquiry.name


# ------------------------------------------------------------------------------------------ no inference shown

def test_no_inference_about_informedness_is_ever_shown_before_commitment():
    for seed in range(4):
        ep = Episode(L5, seed)
        while not ep.done:
            obs = ep.observe()
            text = "\n".join(obs.lines).lower()
            assert "informed" not in text and "toxic" not in text and "posterior" not in text
            # no probability attached to any client (rates like 2.6878% are fine; '72%' next to a client would be an inference)
            import re
            client_lines = [l for l in obs.lines if any(c.name in l for c in ep.setup.clients) or "inquiry" in l.lower()]
            assert not any(re.search(r"(?<![\d.])\d{1,3}%", l) for l in client_lines), client_lines
            ep.submit(reference_decision(ep, obs))


# ------------------------------------------------------------------------------------------ assessment

def _ctx(mkt, dv01=0.0, info=None, client=None, limit=300e3):
    pos = ()
    if dv01:
        pos = (Position(IRSwap.new(Side.RECEIVE if dv01 > 0 else Side.PAY, abs(dv01) / unit_dv01(10, mkt) * 1e6, mkt.par_irs_rate(120),
                                   mkt.spot, 120), "initial", "x", -1),)
    reg = Regime(1.0, Liquidity.NORMAL, (("macro_fund", 1),), 0.5, 0.125, "t", 0.3 * limit / unit_dv01(10, mkt) * 1e6)
    return DecisionContext(mkt, pos, limit, reg, 10, client, desk=Desk((2, 5, 10, 30), Limits(limit, 0.5 * limit), multi_tenor=True),
                           info=info, home=10)


def _best_target(ctx):
    return ctx.after(best_alternative(ctx, "position"))[0]["level"]


def test_view_sizing_grows_with_stated_reliability_and_points_the_right_way(mkt):
    """Rates expected to RISE: the desk should run SHORT duration, more so the more reliable the call."""
    targets = []
    for r in (0.0, 0.3, 0.7, 1.0):
        ctx = _ctx(mkt, info=Info(signal_drift_bp=r * 1.5, view_bp=6.0, reliability=r))
        targets.append(_best_target(ctx))
    assert targets[0] == pytest.approx(0.0, abs=0.01 * 300e3)
    assert targets[1] <= targets[0] and targets[3] < targets[1] and targets[3] < 0
    assert all(abs(t) <= 0.95 * 300e3 + 1 for t in targets)


def test_an_event_in_the_horizon_shrinks_the_position_taken(mkt):
    calm = _ctx(mkt, info=Info(signal_drift_bp=0.6, view_bp=4, reliability=0.6))
    release = _ctx(mkt, info=Info(signal_drift_bp=0.6, view_bp=4, reliability=0.6, vol_mult=3.0))
    assert abs(_best_target(release)) < abs(_best_target(calm))


def test_oversizing_a_weak_view_into_the_release_is_rated_poorly(mkt):
    ctx = _ctx(mkt, info=Info(signal_drift_bp=0.3 * 0.75, view_bp=3, reliability=0.3, vol_mult=3.0))
    allin = parse_position("target -280k", ctx)
    assert assess_hedge(ctx, allin, "position").rating in (Rating.POOR, Rating.DEFENSIBLE)
    assert assess_hedge(ctx, parse_position("flat", ctx), "position").rating is Rating.SOUND


def test_the_price_decomposition_separates_inventory_information_and_view(mkt):
    n = 0.2 * 300e3 / unit_dv01(10, mkt) * 1e6
    client = VisibleClient("macro_fund", ClientAction.PAYS, n, 10, "Halden Capital")
    low = assess_rfq(_ctx(mkt, dv01=100e3, info=Info(posterior=0.05, view_bp=4, reliability=0.7), client=client), None)
    high = assess_rfq(_ctx(mkt, dv01=100e3, info=Info(posterior=0.9, view_bp=4, reliability=0.7), client=client), None)
    for a in (low, high):
        parts = a.metrics["decomposition"]
        assert parts["inventory"] + parts["information"] + parts["view"] == pytest.approx(a.metrics["ref_charge"], abs=1e-9)
        assert parts["view"] > 0              # the client pays (you receive); rates expected to rise: lean higher = charge more
    assert high.metrics["decomposition"]["information"] > low.metrics["decomposition"]["information"]
    assert high.metrics["decomposition"]["inventory"] == pytest.approx(low.metrics["decomposition"]["inventory"])


def test_ignoring_strong_evidence_is_not_rated_sound(mkt):
    n = 0.2 * 300e3 / unit_dv01(10, mkt) * 1e6
    ctx = _ctx(mkt, info=Info(posterior=0.85), client=VisibleClient("macro_fund", ClientAction.PAYS, n, 10, "Halden Capital"))
    a0 = assess_rfq(ctx, None)
    tight = ctx.mid(10) + (a0.metrics["decomposition"]["inventory"] - 0.1) * 1e-4      # no widening at all for the evidence
    assert assess_rfq(ctx, tight).rating is not Rating.SOUND


def test_after_the_limit_cut_keeping_too_much_risk_is_an_error():
    ep = Episode(L5, 2, render=False)
    while ep.round < 3:
        ep.submit(reference_decision(ep, ep.observe()))
    ep.submit(reference_decision(ep, ep.observe()))           # the last request
    obs = ep.observe()
    assert ep.limits.dv01 < ep.setup.limit
    ctx = obs.ctx
    over = parse_position(f"target {1.2 * ep.limits.dv01:.0f}", ctx)
    assert assess_hedge(ctx, over).rating is Rating.ERROR


# ------------------------------------------------------------------------------------------ the 200 paths

def test_many_path_distribution_is_deterministic_and_only_at_level_5():
    ep = run_policy(L5, 1, lambda e, o: reference_decision(e, o))
    a, b = path_pnls(ep), path_pnls(ep)
    assert len(a) == PATHS and a == b
    text = "\n".join(ep.debrief())
    assert "200 OTHER MARKET PATHS" in text and text.index("SAME CLIENTS, SAME MARKET PATH") < text.index("200 OTHER MARKET PATHS")
    l4 = run_policy("mm.ep4_products_overnight", 1, lambda e, o: reference_decision(e, o))
    assert "OTHER MARKET PATHS" not in "\n".join(l4.debrief())


def test_many_path_mean_matches_a_direct_expectation():
    """With decisions held fixed the path mean is the fixed P&L plus exposure x expected drift: check it against that sum."""
    ep = run_policy(L5, 4, lambda e, o: reference_decision(e, o))
    s = ep.setup
    from rates_trainer.episodes.state import INFORMED_DRIFT_BP
    from rates_trainer.marketmaking.flow import CLIENT_TYPES
    expected = sum(r.fixed for r in ep.records)
    for rec in ep.records:
        reg = rec.plan.regime or s.regime
        drift = s.signal.reliability * s.signal.view_bp / s.rounds
        q = rec.inquiry
        if rec.plan.pricing:
            drift += (1 if q.action is ClientAction.PAYS else -1) * CLIENT_TYPES[q.ctype].p_informed * INFORMED_DRIFT_BP * reg.vol
        expected += -rec.x_after["level"] * drift
    paths = path_pnls(ep, n=4000)
    sd = statistics.pstdev(paths) / math.sqrt(len(paths))
    assert statistics.mean(paths) == pytest.approx(expected, abs=4 * sd + 1.0)


def test_the_view_can_be_right_or_noise_and_policies_feel_it():
    pols = Episode(L5, 0, render=False).policies()
    seen = set()
    for seed in range(8):
        ep = Episode(L5, seed, render=False)
        seen.add(ep.signal_right)
    assert seen == {True, False}
    follow = pols["follow the view fully into the release"]
    ignore = pols["ignore the research view"]
    diffs = [run_policy(L5, seed, follow).pnl_total() - run_policy(L5, seed, ignore).pnl_total() for seed in range(4)]
    assert any(abs(d) > 1000 for d in diffs)
