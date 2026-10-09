"""Invariants every episode level must satisfy. Parametrised over every registered episode, so new levels inherit them.

    replay is exact; clients, fill draws and the market path never depend on decisions; nothing decided before the first move is graded
    differently when the market path, the informed flags or the research view's outcome change (no hindsight); the ledger reconciles to
    full revaluation plus cash; no assessment content appears before the trainee commits; the reference policy is never poor or an error.
"""

from dataclasses import replace

import pytest

from rates_trainer.episodes.episode import Episode, all_episodes, reference_decision, run_policy
from rates_trainer.episodes.state import Rating, book

EIDS = [e.id for e in all_episodes()]
SEEDS = (0, 1, 2)


def REF(ep, obs):
    return reference_decision(ep, obs)


def NEVER(ep, obs):
    return reference_decision(ep, obs, "none")


def _assessments(ep, rnd):
    return [(k, a.rating, round(a.expected_pnl, 4), round(a.variance, 1), tuple(a.reasons))
            for r in ep.records if r.round == rnd for k, _, a in r.decisions if a]


@pytest.mark.parametrize("eid", EIDS)
def test_replay_is_exact(eid):
    a, b = run_policy(eid, 4, REF), run_policy(eid, 4, REF)
    assert [e.amount for e in a.ledger] == [e.amount for e in b.ledger]
    assert a.debrief(compare=False) == b.debrief(compare=False)


@pytest.mark.parametrize("eid", EIDS)
def test_clients_fills_and_market_do_not_depend_on_decisions(eid):
    for seed in SEEDS:
        a, b = run_policy(eid, seed, REF), run_policy(eid, seed, NEVER)
        assert a.inquiries == b.inquiries and a.uniforms == b.uniforms and a.signal_right == b.signal_right
        assert [r.moves.keys() for r in a.records] == [r.moves.keys() for r in b.records]
        assert a.z == b.z
        assert a.mkt.quotes == b.mkt.quotes                          # the same curve at the end whatever was traded
        # the evidence each saw differs only through which moves happened (identical) and who asked (identical)
        assert [(e.name, e.sign, round(e.move, 12)) for e in a.evidence] == [(e.name, e.sign, round(e.move, 12)) for e in b.evidence]


@pytest.mark.parametrize("eid", EIDS)
def test_no_hindsight_market_path(eid):
    for seed in SEEDS:
        a = run_policy(eid, seed, REF, market_seed=seed)
        b = run_policy(eid, seed, REF, market_seed=seed + 999)
        assert a.z != b.z
        assert _assessments(a, 0) == _assessments(b, 0)


@pytest.mark.parametrize("eid", EIDS)
def test_no_hindsight_hidden_flags(eid):
    """Flip every informed flag and the research view's outcome: nothing decided before the first move may be graded differently."""
    for seed in SEEDS:
        eps = []
        for flip in (False, True):
            ep = Episode(eid, seed, render=False)
            if flip:
                ep.inquiries = [replace(q, informed=not q.informed) for q in ep.inquiries]
                ep.signal_right = not ep.signal_right
            while not ep.done and ep.round == 0:
                ep.submit(REF(ep, ep.observe()))
            eps.append(ep)
        assert _assessments(eps[0], 0) == _assessments(eps[1], 0)


@pytest.mark.parametrize("eid", EIDS)
def test_ledger_reconciles_to_full_revaluation_plus_cash(eid):
    for seed in SEEDS:
        for pol in (REF, NEVER):
            ep = run_policy(eid, seed, pol)
            change = book(ep.positions).pv(ep.mkt) - ep.pv0 + ep.cash
            assert sum(e.amount for e in ep.ledger) == pytest.approx(change, abs=1e-6 * max(1.0, abs(change)))


@pytest.mark.parametrize("eid", EIDS)
def test_nothing_from_the_assessment_is_shown_before_commitment(eid):
    leaks = ("sound", "defensible", "poor", "sigma", "benchmark", "best balance", "p(informed", "posterior", "toxic", "behaves like")
    ep = Episode(eid, 1)
    while not ep.done:
        obs = ep.observe()
        text = "\n".join(obs.lines + [obs.prompt, obs.input_hint]).lower()
        for leak in leaks:
            assert leak not in text, (eid, obs.kind, leak)
        ep.submit(REF(ep, obs))


@pytest.mark.parametrize("eid", EIDS)
def test_reference_policy_is_never_poor_or_an_error(eid):
    ratings = [a.rating for seed in range(6) for r in run_policy(eid, seed, REF).records for _, _, a in r.decisions if a]
    assert ratings and all(rt in (Rating.SOUND, Rating.DEFENSIBLE) for rt in ratings), eid
    assert sum(rt is Rating.SOUND for rt in ratings) >= 0.75 * len(ratings)


@pytest.mark.parametrize("eid", EIDS)
def test_debrief_has_the_four_parts(eid):
    ep = run_policy(eid, 2, REF)
    text = "\n".join(ep.debrief())
    for section in ("DECISIONS", "OUTCOME", "LUCK", "SAME CLIENTS, SAME MARKET PATH"):
        assert section in text
