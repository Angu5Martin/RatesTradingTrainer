"""The post-game debrief: what happened, why, and how much of it was decision and how much was luck. Built only when the game is over (it names the hidden things).

P&L attribution convention, per trade of q lots at price p when the public fair value was F (the expectation of the answer given everything announced so far, computed
exactly for probability markets; the crowd's belief for world markets) and the market finally settled at S, with F_end the fair value just before settlement:

    edge             = q·(F - p) if I bought, q·(p - F) if I sold            what the trade was worth against fair value when it was done   (a DECISION result)
      of which       spread capture  = q · half-spread of my market at that moment
                     mispricing      = edge - spread capture = q·(mid - F) on a sale, q·(F - mid) on a purchase     (negative when my mid sat on the wrong side of fair)
    news drift       = signed q · (F_end - F)                                    how the fair value moved after the trade (shocks, clues)
    settlement luck  = signed q · (S - F_end)                                    how the answer fell against its expectation
      Against an UNINFORMED counterparty these two are LUCK: zero on average. Against an INFORMED one (who knew more than the public fair value) they are not luck: the
      counterparty traded because it knew which way they would go, so on those trades news drift + settlement luck is reported as ADVERSE SELECTION, the cost of trading with
      someone who knew more, which the spread you charged is there to pay for.

    total P&L = edge + adverse selection + news drift + settlement luck, exactly, in every market (all in fractions). Multiply by the lot value to get credits.
Decision result = edge + adverse selection: what your quotes achieved given who traded with you. Luck is what the world added on top, and averages to zero.
"""

from __future__ import annotations

from fractions import Fraction

from .bots import PERSONALITIES
from .world import fmt_num

DESCRIBE = {
    "retail": "Retail flow: uninformed, trades often and small, mostly cares about the spread.",
    "value": "Value fund: a good estimate of the public fair value; takes quotes that are clearly off it.",
    "anchor": "Slow money: priced off the fair value of two rounds ago, so it trades stale prices after a shock.",
    "sniper": "Fast money: reacts to a shock in the same round, before you can re-quote, with size.",
    "insider": "Informed: knew (nearly) the answer under the rules of the moment, traded only where the edge was large and rationed its size.",
}


CONVENTION = "\n".join([
    "Fair value F: the exact expectation of the answer given everything announced so far (world questions: the crowd's belief). S: the settlement. F_end: fair value just before settlement.",
    "Per trade of q lots at price p:",
    "  edge = q·(F − p) if I bought, q·(p − F) if I sold: what the trade was worth against fair value when it happened (a decision result).",
    "    spread capture = q · half my quoted spread;  mispricing = edge − spread capture (negative when my mid sat on the wrong side of fair).",
    "  news drift = signed q · (F_end − F);  settlement luck = signed q · (S − F_end).",
    "Against an uninformed counterparty those two are luck (zero on average). Against an informed one they are ADVERSE SELECTION: the cost of trading with someone who knew more,",
    "which the spread is there to pay for.",
    "Total P&L = edge + adverse selection + news drift + settlement luck, exactly, in every market. Credits = price units × lots × the lot value.",
    "Decision result = edge + adverse selection. Luck = news drift + settlement luck (informed trades excluded).",
])


def fl(x) -> float:
    return float(x)


def _classify(t, S, F_end, pv, half_sd: float, sd: float) -> dict:
    s = t.qty if t.me == "buy" else -t.qty
    edge = (t.fair - t.price) * t.qty if t.me == "buy" else (t.price - t.fair) * t.qty
    result = s * (S - t.price)
    half = (t.offer - t.bid) / 2
    mid = (t.offer + t.bid) / 2
    mis = edge - t.qty * half
    out = {"edge": edge, "result": result, "spread_capture": t.qty * half, "mispricing": mis, "drift": s * (F_end - t.fair), "settlement": s * (S - F_end)}
    if result < 0 and edge < 0:
        cause = "stale" if t.stale else "informed" if t.informed else "mispriced"
        out["verdict"] = {"stale": "Lost, and the price was already worse than fair: the quote was stale after a shock.",
                          "informed": "Lost, and the price was worse than fair against a counterparty who knew more: adverse selection you could have priced.",
                          "mispriced": "Lost, and the price was worse than fair: the quote was off fair value."}[cause]
        out["cause"] = cause
    elif result < 0:
        out["cause"] = "informed-priced" if t.informed else "luck"
        out["verdict"] = ("Lost, but the price was at or better than fair, and the counterparty knew more: the spread you charged was the protection."
                          if t.informed else "Lost, but the price was at or better than fair: unlucky, not a mistake.")
    elif edge < 0:
        out["cause"] = "lucky"
        out["verdict"] = "Won, but you traded at a price worse than fair: luck rescued a poor price."
    else:
        out["cause"] = "good"
        out["verdict"] = "Won, and the price was at or better than fair: edge and outcome agreed."
    return out


def build(g) -> dict:
    if not g.done:
        raise ValueError("the debrief opens after the last market has resolved")
    markets, tot = [], {k: Fraction(0) for k in ("edge", "spread_capture", "mispricing", "drift", "settlement", "adverse", "pnl")}
    causes: dict[str, int] = {}
    cp: dict[str, dict] = {b.id: {"id": b.id, "personality": b.key, "label": PERSONALITIES[b.key].label, "description": DESCRIBE[b.key], "trades": 0, "lots": 0,
                                  "my_result": Fraction(0), "edge_given": Fraction(0)} for b in g.bots}
    decisions: list[dict] = []
    for m in g.markets:
        S, Fend, pv = m.settle, m.final_fair, m.pv
        rows, agg = [], {k: Fraction(0) for k in ("edge", "spread_capture", "mispricing", "drift", "settlement", "adverse")}
        for t in m.trades:
            sd = max(next((q["sd"] for q in m.quote_log if q["round"] <= t.round), 1.0), 1e-9)
            c = _classify(t, S, Fend, pv, 0.0, sd)
            for k in ("edge", "spread_capture", "mispricing"):
                agg[k] += c[k] * pv
            late = (c["drift"] + c["settlement"]) * pv
            if t.informed:
                agg["adverse"] += late
            else:
                agg["drift"] += c["drift"] * pv
                agg["settlement"] += c["settlement"] * pv
            causes[c["cause"]] = causes.get(c["cause"], 0) + 1
            cp[t.bot]["trades"] += 1
            cp[t.bot]["lots"] += t.qty
            cp[t.bot]["my_result"] += c["result"] * pv
            cp[t.bot]["edge_given"] += c["edge"] * pv
            rows.append({"n": t.n, "round": t.round, "phase": t.phase, "bot": t.bot, "informed": t.informed, "me": t.me, "qty": t.qty, "price": fl(t.price), "fair": fl(t.fair),
                         "bid": fl(t.bid), "offer": fl(t.offer), "stale": t.stale, "edge": fl(c["edge"] * pv), "result": fl(c["result"] * pv), "cause": c["cause"], "verdict": c["verdict"],
                         "position_after": t.pos_after})
        pnl = m.cash
        assert pnl == agg["edge"] + agg["adverse"] + agg["drift"] + agg["settlement"], (m.id, pnl, agg)          # exact: all fractions
        assert agg["edge"] == agg["spread_capture"] + agg["mispricing"], (m.id, agg)
        for k in agg:
            tot[k] += agg[k]
        tot["pnl"] += pnl
        quotes = []
        for q in m.quote_log:
            mid = (q["bid"] + q["offer"]) / 2
            sd = max(q["sd"], 1e-9)
            err = fl(mid - q["fair"]) / sd
            half = fl((q["offer"] - q["bid"]) / 2) / sd
            lean = -1 if q["pos"] > 0 and mid < q["fair"] else 1 if q["pos"] < 0 and mid > q["fair"] else 0
            lean_with = (q["pos"] > 0 and mid > q["fair"] and abs(err) > 0.3) or (q["pos"] < 0 and mid < q["fair"] and abs(err) > 0.3)
            if abs(err) <= 0.3:
                v = "centred on fair value"
            elif lean and abs(err) <= 0.9:
                v = "skewed to reduce inventory (sensible)"
            elif lean_with:
                v = "skewed the same way as inventory (adds risk)"
            else:
                v = "off fair value"
            quotes.append({"round": q["round"], "bid": fl(q["bid"]), "offer": fl(q["offer"]), "size": q["size"], "fair": fl(q["fair"]), "error_sd": round(err, 2),
                           "half_spread_sd": round(half, 2), "position": q["pos"], "verdict": v,
                           "spread": "tight" if half < 0.12 else "wide" if half > 1.3 else "reasonable"})
        shocks = []
        for a in m.shock_audit:
            requoted = next((q for q in m.quote_log if q["round"] == a["round"] + 1), None)
            sd = max(a["sd_after"], 1e-9)
            mid_before = None if a["bid"] is None else (a["bid"] + a["offer"]) / 2
            err_before = None if mid_before is None else fl(mid_before - a["fair_after"]) / sd
            shocks.append({"id": a["id"], "round": a["round"], "headline": a["headline"], "text": a["text"], "position": a["position"],
                           "fair_before": fl(a["fair_before"]), "fair_after": fl(a["fair_after"]), "fair_moved_sd": round(abs(fl(a["fair_after"] - a["fair_before"])) / max(m.sd0, 1e-9), 2),
                           "mark_impact": fl(a["position"] * (a["fair_after"] - a["fair_before"]) * pv), "quote_was_off_by_sd": None if err_before is None else round(err_before, 2),
                           "requoted_at_once": requoted is not None,
                           "requote_mid_error_sd": None if requoted is None else round(fl(((requoted["bid"] + requoted["offer"]) / 2) - requoted["fair"]) / max(requoted["sd"], 1e-9), 2)})
            if requoted is None and err_before is not None and abs(err_before) > 0.5 and a["round"] < m.resolved_round:
                decisions.append({"market": m.id, "round": a["round"], "kind": "stale", "text": f"{m.id} after {a['headline'].lower()} in round {a['round']}: your quote was {abs(err_before):.1f}σ from the new fair value and was not re-quoted straight away."})
        item = m.world.item if m.world else None
        markets.append({
            "id": m.id, "title": m.title, "kind": m.kind, "category": m.category, "unit": m.unit, "lot_value": fl(pv), "question": m.question(g.exps),
            "resolution_rule": (m.world.rule if m.world else m.resolution_text(g.exps)), "rules_at_resolution": m.rules(g.exps), "source": item.source if item else None,
            "as_of": m.world.as_of if m.world else None, "settle": fl(S), "settle_text": fmt_num(S), "opens_at": m.opens_at, "resolved_round": m.resolved_round, "position_at_settlement": m.settled_pos,
            "final_fair": fl(Fend), "trades": rows, "quotes": quotes, "shocks": shocks,
            "pnl": {"total": fl(pnl), "spread_capture": fl(agg["spread_capture"]), "mispricing": fl(agg["mispricing"]), "edge": fl(agg["edge"]), "adverse_selection": fl(agg["adverse"]),
                    "news_drift": fl(agg["drift"]), "settlement_luck": fl(agg["settlement"])},
        })
    stale = sorted((d for d in decisions if d["kind"] == "stale"), key=lambda d: -float(d["text"].split("was ")[1].split("σ")[0]))
    decisions = stale[:4] + [d for d in decisions if d["kind"] != "stale"]
    worst = sorted((r for mk in markets for r in mk["trades"] if r["cause"] in ("stale", "informed", "mispriced")), key=lambda r: r["result"])[:3]
    for r in worst:
        decisions.append({"market": next(mk["id"] for mk in markets if r in mk["trades"]), "round": r["round"], "kind": r["cause"], "text": r["verdict"] + f" ({r['me']} {r['qty']} at {fmt_num(Fraction(str(r['price'])))}, result {r['result']:+.0f})"})
    best = max((r for mk in markets for r in mk["trades"]), key=lambda r: r["edge"], default=None)
    if best and best["edge"] > 0:
        decisions.append({"market": next(mk["id"] for mk in markets if best in mk["trades"]), "round": best["round"], "kind": "good", "text": f"Best trade by edge: {best['me']} {best['qty']} at {fmt_num(Fraction(str(best['price'])))} when fair value was {best['fair']:.2f} (+{best['edge']:.0f} credits of edge)."})
    for c in cp.values():
        c["my_result"], c["edge_given"] = fl(c["my_result"]), fl(c["edge_given"])
    decision_part = tot["edge"]
    return {
        "game": g.summary(), "seed": g.seed, "level": g.level, "mix": g.mix,
        "totals": {"pnl": fl(tot["pnl"]), "spread_capture": fl(tot["spread_capture"]), "mispricing": fl(tot["mispricing"]), "decision_edge": fl(decision_part),
                   "adverse_selection": fl(tot["adverse"]), "decision_result": fl(decision_part + tot["adverse"]),
                   "news_drift": fl(tot["drift"]), "settlement_luck": fl(tot["settlement"]), "luck": fl(tot["drift"] + tot["settlement"])},
        "trade_causes": causes,
        "markets": markets,
        "shocks": [{**s} for s in g.shock_log],
        "shock_plan": [{"id": s.id, "round": s.round, "kind": s.effect.kind, "category": s.effect.category, "shift_sd": round(s.shift, 2)} for s in g._plan],
        "counterparties": list(cp.values()),
        "decisions": decisions,
        "convention": CONVENTION,
    }
