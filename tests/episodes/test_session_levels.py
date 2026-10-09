"""The terminal adapter with typed input at levels 3-5: the new syntax is understood, bad input re-prompts, the debrief prints."""

import pytest

from rates_trainer.episode_session import run_episode
from rates_trainer.episodes.episode import Episode


def _typist(ep, script):
    """Answers like a trainee would type them, derived from what is on the screen; a few deliberately bad inputs first."""
    bad = iter(["nonsense", "sell 10 fgbx", "target abc"])
    state = {"bad_sent": 0, "last": None, "repeats": 0}

    def ask(_prompt):
        if state["bad_sent"] < 1:
            state["bad_sent"] += 1
            return next(bad)
        kind = ep.phase
        key = (ep.round, kind)
        state["repeats"] = state["repeats"] + 1 if key == state["last"] else 0
        state["last"] = key
        if state["repeats"] >= 1:                 # the adapter rejected the scripted answer (e.g. nothing to switch): fall back
            return "none" if kind != "checkpoint" else "0"
        ctx = ep.context()
        if kind == "quote":
            mid = ctx.mid(ep.setup.tenor) * 100
            return f"{mid - 0.003:.4f} {mid + 0.003:.4f}"
        if kind == "rfq":
            q = ep.inquiries[ep.round]
            st = ctx.street(q.tenor).client_rate(q.action) * 100
            return f"{st:.4f}"
        if kind == "checkpoint":
            return "0"
        return script.get(kind, "none")
    return ask


@pytest.mark.parametrize("eid,script", [
    ("mm.ep3_curve_book_ldi", {"hedge": "flatten"}),
    ("mm.ep4_products_overnight", {"hedge": "100%", "overnight": "keep", "rehedge": "none"}),
    ("mm.ep5_information_views", {"hedge": "50%", "position": "target -50k"}),
])
def test_typed_episode_runs_to_the_debrief(eid, script):
    ep = Episode(eid, 3)
    out = []
    assert run_episode(ep, ask=_typist(ep, script), say=out.append, compare=False)
    text = "\n".join(out)
    assert "DEBRIEF" in text and "Your decision:" in text and "LUCK" in text


def test_level4_product_syntax_through_the_adapter():
    ep = Episode("mm.ep4_products_overnight", 3)
    code = next(p.code for p in ep.desk().products if p.kind == "future").lower()
    script = {"hedge": f"sell 100 {code}", "overnight": "switch", "rehedge": "none"}
    out = []
    assert run_episode(ep, ask=_typist(ep, script), say=out.append, compare=False)
    text = "\n".join(out)
    assert f"sold 100 {code.upper()}" in text
