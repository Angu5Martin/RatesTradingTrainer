"""The frontend boundary (api.Session, views, render, codec) and the four pre-UI fixes.

    public views are plain data and carry nothing hidden; text is rendered from them; typed text parses through one entry point;
    decisions encode exactly and replay is deterministic across processes; results and debriefs are structured;
    zero-size hedge legs are not traded; the research view shown is the one the grader uses; the risk card states the training assumptions;
    the two "expected" figures in the debrief are separate, labelled quantities.
"""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from rates_trainer.episode_session import run_episode
from rates_trainer.episodes.api import REPLAY_FORMAT, Session, catalogue, episode_for_level
from rates_trainer.episodes.decisions import parse, parse_hedge, parse_quote, parse_rfq
from rates_trainer.episodes.episode import PATHS, Episode, all_episodes, path_pnls, reference_decision, run_policy
from rates_trainer.episodes.factors import FACTORS
from rates_trainer.episodes.render import debrief_lines, observation_lines, result_lines
from rates_trainer.episodes.serial import decode_decision, encode_decision, plain
from rates_trainer.episodes.state import (BondTrade, CheckpointAnswer, FuturesTrade, HedgeDecision, HedgeTrade, QuoteDecision, RFQDecision, Side)

EIDS = [e.id for e in all_episodes()]
L1, L3, L4, L5 = "mm.ep1_single_trade", "mm.ep3_curve_book_ldi", "mm.ep4_products_overnight", "mm.ep5_information_views"
SRC = str(Path(__file__).resolve().parents[2] / "src")

HIDDEN_KEYS = {"informed", "p_informed", "posterior", "signal_right", "truth", "z", "uniform", "uniforms", "seed", "market_seed", "answer",
               "ctx", "lean", "leans", "toxicity", "evidence_vs_truth", "view_truth"}


def _walk_keys(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, path
            yield from _walk_keys(v, f"{path}/{k}")
    elif isinstance(x, list):
        for v in x:
            yield from _walk_keys(v, path)


def _is_plain(x) -> bool:
    if x is None or isinstance(x, (str, bool, int, float)):
        return True
    if isinstance(x, list):
        return all(_is_plain(v) for v in x)
    if isinstance(x, dict):
        return all(isinstance(k, str) and _is_plain(v) for k, v in x.items())
    return False


def _play(eid, seed, market_seed=None, policy="ref", steps=None):
    """Play through the public Session with the reference policy; returns (session, [observation views], [step result views])."""
    s = Session.start(eid, seed, market_seed)
    obs, res = [], []
    while not s.done and (steps is None or len(obs) < steps):
        obs.append(s.observe())
        res.append(s.submit(reference_decision(s._ep, s._current(), policy)))
    return s, obs, res


# ------------------------------------------------------------------------------------------------- 1. public views

@pytest.mark.parametrize("eid", EIDS)
def test_views_are_plain_json_and_render_identically_from_json(eid):
    ep = Episode(eid, 1)
    while not ep.done:
        o = ep.observe()
        assert _is_plain(o.view) and json.loads(json.dumps(o.view)) == o.view
        assert observation_lines(json.loads(json.dumps(o.view))) == o.lines          # one source of truth for the terminal text
        r = ep.submit(reference_decision(ep, o))
        assert result_lines(plain(r.events)) == r.lines


@pytest.mark.parametrize("eid", EIDS)
def test_no_hidden_key_in_any_observation_or_step_result(eid):
    s, obs, res = _play(eid, 2)
    for v in obs:
        assert not ({k for k, _ in _walk_keys(v)} & HIDDEN_KEYS)
    for r in res:
        keys = {(k, p) for k, p in _walk_keys({k: v for k, v in r.items() if k != "assessment"})}
        assert not ({k for k, _ in keys} & HIDDEN_KEYS)
        if r["assessment"]:                  # revealed AFTER commitment by design: ratings, the table, metrics (incl. the evidence-based P(informed))
            assert "informed" not in r["assessment"] and "signal_right" not in r["assessment"]


def test_checkpoint_view_never_contains_the_answer():
    for eid, seed in ((L1, 1), (L3, 3), (L4, 3)):
        ep = Episode(eid, seed)
        seen = 0
        while not ep.done:
            o = ep.observe()
            if o.kind == "checkpoint":
                assert set(o.view["checkpoint"]) == {"intro", "with_screen", "inquiry", "prompt", "note"}
                assert "answer" not in json.dumps(o.view)
                seen += 1
            ep.submit(reference_decision(ep, o))
        assert seen


@pytest.mark.parametrize("eid", EIDS)
def test_public_views_do_not_change_with_the_hidden_truth(eid):
    """Flip every informed flag and the research view's outcome and change the market path: every observation up to the first market move is
    identical, and the research view shown depends only on the round, not on whether the call is right, at ANY round."""
    for seed in (0, 1):
        a = Episode(eid, seed, render=True)
        b = Episode(eid, seed, market_seed=seed + 999, render=True)
        b.inquiries = [replace(q, informed=not q.informed) for q in b.inquiries]
        b.signal_right = not b.signal_right
        while not a.done and a.round == 0:
            oa, ob = a.observe(), b.observe()
            assert json.dumps(oa.view, sort_keys=True) == json.dumps(ob.view, sort_keys=True)
            a.submit(reference_decision(a, oa))
            b.submit(reference_decision(b, ob))


def test_evidence_in_the_view_is_only_what_the_trainee_saw():
    ep = Episode(L5, 3)
    while not ep.done:
        o = ep.observe()
        for cl in (o.view["conditions"] or {}).get("named_clients", []):
            assert set(cl) == {"name", "description", "observations"}
            assert all(set(ob) == {"side", "move_bp"} for ob in cl["observations"])
        ep.submit(reference_decision(ep, o))


def test_frontend_does_not_need_to_parse_lines():
    s, obs, _ = _play(L4, 3)
    needed = ("kind", "header", "market", "book", "conditions", "prompt", "input", "risk_card")
    assert all(k in obs[0] for k in needed) and "lines" not in obs[0]
    v = obs[0]
    assert v["market"]["ladder"] and v["market"]["products"] and v["book"]["swaps"] and v["book"]["limit_dv01"] > 0
    assert {"tenor", "mid", "bid", "offer", "dv01_per_m", "cost_bp"} <= set(v["market"]["ladder"][0])
    assert v["input"]["type"] == "rfq"
    hedge = next(o for o in obs if o["kind"] == "hedge")
    assert sorted(hedge["input"]["products"]) == ["CTD", "FGBL", "FGBM"] and hedge["input"]["swap_tenors"] == [2, 5, 10, 30]
    assert hedge["book"]["buckets"] is not None and hedge["book"]["slope"]["limit"] > 0


# ------------------------------------------------------------------------------------------------- 2. decision codec and replay

def test_one_parse_entry_point_matches_the_individual_parsers():
    ep = Episode(L1, 1)
    o = ep.observe()
    assert o.kind == "quote" and parse(o, " 3.30 3.32 ") == parse_quote("3.30 3.32")
    ep3 = _l3_at_hedge()
    o = ep3.observe()
    assert o.kind == "hedge"
    assert parse(o, "100% 10y") == parse_hedge("100% 10y", o.ctx) and parse(o, "none").trades == ()
    assert parse(o, "flatten") == parse_hedge("flatten", o.ctx)
    ep3 = Episode(L3, 3)
    o = ep3.observe()
    assert o.kind == "rfq" and parse(o, "pass") == parse_rfq("pass") == RFQDecision(None)
    while ep3.round < 1:
        ep3.submit(reference_decision(ep3, ep3.observe()))
    o = ep3.observe()                                          # the slope checkpoint: any text becomes a CheckpointAnswer
    assert o.kind == "checkpoint" and parse(o, " 12k ") == CheckpointAnswer("12k")


def test_parse_errors_are_readable_and_leave_the_session_untouched():
    s = Session.start(L1, 1)
    before = json.dumps(s.observe(), sort_keys=True)
    for bad in ("", "3.30", "3.32 3.30", "abc def", "99 100"):
        with pytest.raises(ValueError):
            s.parse(bad)
    assert json.dumps(s.observe(), sort_keys=True) == before and s.record()["decisions"] == []


def test_wrong_kind_of_decision_is_rejected():
    s = Session.start(L1, 1)
    with pytest.raises(ValueError):
        s.submit(HedgeDecision((), "none"))
    with pytest.raises(ValueError):
        s.submit({"type": "rfq", "level": None})
    assert s.record()["decisions"] == []


DECISIONS = [QuoteDecision(0.0308, 0.0312), RFQDecision(0.0291), RFQDecision(None), CheckpointAnswer("-11.6k"), HedgeDecision((), "none"),
             HedgeDecision((HedgeTrade(10, Side.PAY, 150e6), HedgeTrade(2, Side.RECEIVE, 60.5e6)), "two legs"),
             HedgeDecision((FuturesTrade("FGBL", -1347.68), BondTrade("CTD", 5e7)), "products")]


@pytest.mark.parametrize("d", DECISIONS)
def test_decision_codec_round_trips_exactly_through_json(d):
    enc = encode_decision(d)
    assert _is_plain(enc) and decode_decision(json.loads(json.dumps(enc))) == d


def test_replay_reproduces_the_episode_in_process():
    s, _, _ = _play(L5, 4)
    rec = json.loads(json.dumps(s.record()))
    assert rec["format"] == REPLAY_FORMAT and rec["version"] == 1 and rec["complete"] is True
    assert set(rec) == {"format", "version", "episode", "seed", "market_seed", "decisions", "complete"}
    r = Session.replay(rec)
    assert r.done and r._ep.pnl_total() == s._ep.pnl_total() and [e.amount for e in r._ep.ledger] == [e.amount for e in s._ep.ledger]
    assert r.debrief(compare=False) == s.debrief(compare=False)
    part = Session.replay(rec, upto=3)                        # a partial replay resumes at the same prompt
    assert not part.done and part.observe() == _play(L5, 4, steps=4)[1][3]


def test_replay_is_deterministic_across_processes_and_hash_seeds(tmp_path):
    s, _, _ = _play(L4, 5, market_seed=77)
    rec_path = tmp_path / "rec.json"
    rec_path.write_text(json.dumps(s.record()))
    code = ("import json, sys; from rates_trainer.episodes.api import Session; "
            f"s = Session.replay(json.load(open({str(rec_path)!r}))); "
            "print(repr([e.amount for e in s._ep.ledger]), s._ep.pnl_total())")
    outs = []
    for hs in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hs, "PYTHONPATH": SRC}
        outs.append(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True).stdout.strip())
    assert outs[0] == outs[1] == f"{[e.amount for e in s._ep.ledger]!r} {s._ep.pnl_total()}"


def test_replay_rejects_other_formats():
    with pytest.raises(ValueError):
        Session.replay({"format": "something else", "version": 1})
    with pytest.raises(ValueError):
        Session.replay({"format": REPLAY_FORMAT, "version": 2})


def test_catalogue_and_level_selection():
    assert [c["level"] for c in catalogue()] == [1, 2, 3, 3, 4, 5]
    assert {episode_for_level(3, 0), episode_for_level(3, 1)} == {"mm.ep3_curve_book_corporate", "mm.ep3_curve_book_ldi"}
    with pytest.raises(ValueError):
        episode_for_level(9, 0)


# ------------------------------------------------------------------------------------------------- 3. serialisable results

@pytest.mark.parametrize("eid", EIDS)
def test_step_results_and_assessments_are_plain_data(eid):
    s, _, res = _play(eid, 3)
    assert any(r["assessment"] for r in res)
    for r in res:
        assert _is_plain(r) and json.loads(json.dumps(r)) == r
        a = r["assessment"]
        if a:
            assert set(a) == {"kind", "rating", "reasons", "expected_pnl", "variance", "table", "metrics"}
            assert all(set(t) == {"label", "expected", "sigma", "rating"} for t in a["table"])
            assert _is_plain(a["metrics"])


def test_quote_metrics_are_plain_not_engine_objects():
    ep = Episode(L5, 1)
    r = ep.submit(reference_decision(ep, ep.observe()))
    m = r.assessment.metrics
    assert type(m["ref"]) is dict and type(m["street"]) is dict and {"bid", "offer"} <= set(m["street"])
    assert {"inventory_skew_bp", "view_skew_bp", "fair_value"} <= set(m["ref"])


@pytest.mark.parametrize("eid", EIDS)
def test_debrief_is_structured_and_renders_to_the_same_text(eid):
    ep = run_policy(eid, 2, lambda e, o: reference_decision(e, o))
    d = ep.debrief_view(compare=True)
    assert _is_plain(d) and json.loads(json.dumps(d)) == d
    assert {"decisions", "calculation_checks", "outcome", "luck", "clients", "counterfactuals"} <= set(d)
    assert set(d["luck"]) == {"label", "expected_pnl", "realised_pnl", "luck", "sigma_units"}       # decision quality / outcome / luck / same-path
    assert d["counterfactuals"]["policies"] and d["outcome"]["by_cause"]
    assert debrief_lines(json.loads(json.dumps(d))) == ep.debrief(compare=True)
    assert (d["market_paths"] is not None) == (eid == L5)


def test_debrief_keeps_decision_quality_separate_from_outcome():
    ep = run_policy(L4, 1, lambda e, o: reference_decision(e, o))
    d = ep.debrief_view(compare=False)
    assert all(r["rating"] in ("sound", "defensible", "poor", "error") for r in d["decisions"])
    assert d["luck"]["luck"] == pytest.approx(d["luck"]["realised_pnl"] - d["luck"]["expected_pnl"])
    assert d["outcome"]["total"] == pytest.approx(ep.pnl_total()) and d["counterfactuals"] is None


# ------------------------------------------------------------------------------------------------- 4A. zero-size legs

def _l3_at_hedge(seed=3):
    ep = Episode(L3, seed, render=False)
    while ep.phase != "hedge":
        ep.submit(reference_decision(ep, ep.observe()))
    return ep


def test_a_dust_leg_is_not_traded_but_the_real_leg_is():
    ep = _l3_at_hedge()
    ctx = ep.observe().ctx
    big = ctx.hedge_trade_for(1.0, 10)
    n_before = len(ep.positions)
    r = ep.submit(HedgeDecision((big, HedgeTrade(2, Side.PAY, 0.1e6)), "big plus dust"))
    kinds = [e["type"] for e in r.events]
    assert kinds.count("hedge_trade") == 1 and kinds.count("skipped_trade") == 1 and len(ep.positions) == n_before + 1
    assert "€0m" not in "\n".join(r.lines) and "Not traded" in "\n".join(r.lines)
    hedges = [d for k, d, _ in ep.records[-2].decisions if k == "hedge"]
    assert len(hedges[0].trades) == 1                                   # the decision that was assessed is the one that was traded


def test_an_all_dust_decision_is_no_trade_and_dust_products_are_dropped_too():
    ep = _l3_at_hedge()
    n = len(ep.positions)
    r = ep.submit(HedgeDecision((HedgeTrade(10, Side.PAY, 0.05e6), HedgeTrade(2, Side.RECEIVE, 0.2e6)), "dust"))
    kinds = [e["type"] for e in r.events]
    assert kinds[:3] == ["skipped_trade", "skipped_trade", "no_trade"] and len(ep.positions) == n and "hedge_trade" not in kinds
    ep4 = Episode(L4, 3, render=False)
    while ep4.phase != "hedge":
        ep4.submit(reference_decision(ep4, ep4.observe()))
    r = ep4.submit(HedgeDecision((FuturesTrade("FGBL", 1.0),), "one contract"))
    assert [e["type"] for e in r.events][0] == "skipped_trade"


@pytest.mark.parametrize("eid", ["mm.ep3_curve_book_ldi", "mm.ep3_curve_book_corporate", L4, L5])
def test_no_executed_hedge_leg_is_ever_dust(eid):
    for seed in range(4):
        ep = Episode(eid, seed, render=False)
        while not ep.done:
            o = ep.observe()
            ctx = o.ctx
            r = ep.submit(reference_decision(ep, o))
            for e in r.events:
                if e["type"] != "hedge_trade":
                    continue
                if e["kind"] == "swap":
                    dv = e["notional"] / 1e6 * ctx.dv01_per_m(e["tenor"])
                elif e["kind"] == "future":
                    dv = e["contracts"] * ctx.unit_product(e["code"])["level"]
                else:
                    dv = e["face"] / 1e6 * ctx.unit_product(e["code"])["level"]
                assert abs(dv) >= 0.002 * ctx.limit


# ------------------------------------------------------------------------------------------------- 4B. the research view

def test_the_research_view_shown_is_the_one_the_grader_uses():
    for seed in range(4):
        ep = Episode(L5, seed)
        last = None
        while not ep.done:
            o = ep.observe()
            rs = (o.view["conditions"] or {}).get("research")
            if rs:
                info = o.ctx.info
                assert rs["remaining_bp"] == pytest.approx(info.view_bp) and rs["reliability"] == pytest.approx(info.reliability)
                if o.kind in ("hedge", "position"):
                    assert rs["expected_per_step_bp"] == pytest.approx(info.signal_drift_bp)       # what the position assessment expects next step
                assert rs["steps_left"] == ep.setup.rounds - ep.round and rs["remaining_bp"] == pytest.approx(rs["per_step_bp"] * rs["steps_left"])
                if last is not None:
                    assert abs(rs["remaining_bp"]) <= abs(last) + 1e-12                              # it only runs down
                last = rs["remaining_bp"]
                assert "still to come" in "\n".join(o.lines)
            ep.submit(reference_decision(ep, o))
        assert last is not None


def test_the_research_text_states_exactly_the_numbers_in_the_view():
    ep = Episode(L5, 1)
    while not ep.done:
        o = ep.observe()
        rs = (o.view["conditions"] or {}).get("research")
        if rs:
            line = next(l for l in o.lines if "still to come" in l)
            assert f"about {abs(rs['remaining_bp']):.1f}bp" in line and f"about {abs(rs['per_step_bp']):.1f}bp a step" in line
            assert f"{abs(rs['expected_per_step_bp']):.2f}bp of it" in line and f"{rs['reliability']:.0%} stated reliability" in line
            assert f"over the {rs['steps_left']} step" in line
        ep.submit(reference_decision(ep, o))


def test_book_text_loadings_match_the_risk_card():
    v = Episode(L3, 0).observe()
    slope = next(f for f in v.view["risk_card"]["factors"] if f["name"] == "slope")["loadings"]
    curv = next(f for f in v.view["risk_card"]["factors"] if f["name"] == "curvature")["loadings"]
    text = "\n".join(v.lines)
    assert f"the 5Y {abs(slope[1]['bp_per_unit']):g}bp" in text and f"the 2Y rises {abs(curv[0]['bp_per_unit']):g}bp" in text


def test_research_is_absent_where_there_is_no_view():
    for eid in (L1, L3, L4):
        assert (Episode(eid, 1).observe().view["conditions"] or {}).get("research") is None


def test_the_research_line_is_the_same_whether_or_not_the_call_is_right():
    a, b = Episode(L5, 2), Episode(L5, 2)
    b.signal_right = not a.signal_right
    seen = 0
    while not a.done:
        oa, ob = a.observe(), b.observe()
        assert oa.view["conditions"]["research"] == ob.view["conditions"]["research"]
        assert [l for l in oa.lines if "Research" in l or "still to come" in l] == [l for l in ob.lines if "Research" in l or "still to come" in l]
        seen += 1
        a.submit(reference_decision(a, oa))
        b.submit(reference_decision(b, ob))
    assert seen >= 8


# ------------------------------------------------------------------------------------------------- 4C. the risk card

@pytest.mark.parametrize("eid", EIDS)
def test_risk_card_states_the_training_assumptions_once_and_in_the_data(eid):
    ep = Episode(eid, 1)
    first = ep.observe()
    card = first.view["risk_card"]
    names = [f["name"] for f in card["factors"]]
    assert names == list(ep.factors)
    for f in card["factors"]:
        assert f["normal_daily_vol"] == FACTORS[f["name"]].vol_bp_day
    assert card["regime_vol"] == ep.regime.vol and first.view["header"]["show_risk_card"]
    text = "\n".join(first.lines)
    assert "not estimates of true market volatility" in text
    for f in card["factors"]:
        assert f"{f['name'].replace('_', ' ')} {f['normal_daily_vol']:g}" in text
    ep.submit(reference_decision(ep, first))
    while not ep.done and ep.round == 0:
        o = ep.observe()
        assert not o.view["header"]["show_risk_card"] and "Training assumptions" not in "\n".join(o.lines)
        ep.submit(reference_decision(ep, o))


def test_spread_factors_appear_only_where_they_exist():
    assert [f["name"] for f in Episode(L4, 0).observe().view["risk_card"]["factors"]] == ["level", "slope", "curvature", "swap_spread", "fut_basis"]
    assert [f["name"] for f in Episode(L5, 0).observe().view["risk_card"]["factors"]] == ["level", "slope", "curvature"]
    loads = Episode(L3, 0).observe().view["risk_card"]["factors"][1]["loadings"]
    assert [(r["tenor"], r["bp_per_unit"]) for r in loads] == [(2, -1.0), (5, -0.625), (10, 0.0), (30, 1.0)]


def test_the_card_exposes_no_hidden_client_information_or_outcomes():
    for eid in EIDS:
        text = json.dumps(Episode(eid, 0).observe().view["risk_card"]).lower()
        for word in ("informed", "posterior", "seed", "view_bp", "reliab"):
            assert word not in text


# ------------------------------------------------------------------------------------------------- 4D. two expected-P&L figures

def test_the_debrief_labels_and_explains_the_two_expectations():
    ep = run_policy(L5, 4, lambda e, o: reference_decision(e, o))
    d = ep.debrief_view()
    assert d["luck"]["label"] == "Expected P&L from execution uncertainty"
    assert d["market_paths"]["label"] == "Market-path P&L distribution conditional on these decisions and fills"
    text = "\n".join(debrief_lines(d))
    assert "EXPECTED P&L FROM EXECUTION UNCERTAINTY" in text and "MARKET-PATH P&L DISTRIBUTION" in text
    assert "The two means are not meant to match" in text
    assert text.index("LUCK") < text.index("EXPECTED P&L FROM EXECUTION") < text.index("OTHER MARKET PATHS") < text.index("MARKET-PATH P&L DISTRIBUTION")


def test_the_two_quantities_are_computed_from_different_things():
    """'Expected' prices each fill at its probability, so it does not change with who actually dealt; the market-path mean keeps the realised fills
    (their edge is in it), so it does. Force the first fill both ways on the same decisions and see which number moves."""
    out = {}
    for name, u in (("fill", 0.0), ("miss", 0.999)):
        ep = Episode(L5, 4, render=False)
        ep.uniforms[0] = u
        ep.submit(reference_decision(ep, ep.observe()))                  # round 1 quote (the same quote either way)
        rec0 = ep.records[0]
        out[name] = (rec0.expected, rec0.fixed, rec0.filled)
    assert out["fill"][2] and not out["miss"][2]
    assert out["fill"][0] == pytest.approx(out["miss"][0])               # expected: not a function of the realised fill
    assert out["fill"][1] != pytest.approx(out["miss"][1])               # the realised edge is, and it is what the path mean carries

    ep = run_policy(L5, 4, lambda e, o: reference_decision(e, o))
    d = ep.debrief_view()
    assert d["market_paths"]["yours"]["mean"] == pytest.approx(sum(path_pnls(ep)) / PATHS)
    assert d["luck"]["expected_pnl"] == pytest.approx(sum(r.expected for r in ep.records))
    assert d["luck"]["expected_pnl"] != pytest.approx(d["market_paths"]["yours"]["mean"])
    # the path mean is the realised fixed P&L plus exposure x expected drift, i.e. it contains the fills actually won
    assert sum(r.fixed for r in ep.records) != pytest.approx(d["luck"]["expected_pnl"])


def test_many_paths_only_at_level_5_and_after_the_same_path_comparison():
    for eid in EIDS:
        d = run_policy(eid, 1, lambda e, o: reference_decision(e, o)).debrief_view()
        assert (d["market_paths"] is not None) == (eid == L5)
        assert d["counterfactuals"] is not None


# ------------------------------------------------------------------------------------------------- the terminal adapter over the Session

def test_terminal_adapter_plays_a_level_through_the_session():
    s = Session.start(L1, 1)
    out, state = [], {"n": 0}

    def ask(_):
        state["n"] += 1
        v = s.observe()
        if v["kind"] == "quote":
            mid = v["market"]["focus"]["mid"] * 100
            return f"{mid - 0.03:.4f} {mid + 0.03:.4f}"
        return "0" if v["kind"] == "checkpoint" else "none"

    assert run_episode(s, ask=ask, say=out.append, compare=False) is True and s.done
    text = "\n".join(out)
    assert "Your decision:" in text and "DEBRIEF" in text and "Training assumptions" in text
    assert len(s.record()["decisions"]) in (2, 3)         # the DV01 check only follows a fill
    assert run_episode(Session.start(L1, 2), ask=lambda _: "q", say=lambda s: None) is False
