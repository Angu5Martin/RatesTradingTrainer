"""Plain-text rendering of the public views (views.py) for the terminal.

Every function takes the plain dicts a frontend receives (so `render(json.loads(json.dumps(view)))` is identical) and returns text. This is the
ONLY place the terminal's wording lives; a graphical frontend renders the same dicts its own way. Nothing here reads the engine.
"""

from __future__ import annotations

from ..questions.market import eur_m, pct
from ..questions.model import fmt_eur


# ------------------------------------------------------------------------------------------------- observation

def head_lines(v: dict) -> list[str]:
    h = v["header"]
    title = f"── {h['title']} ── round {h['round'] + 1}/{h['rounds']}" + (f" ── {h['round_title']}" if h["round_title"] else "") \
        if h["rounds"] > 1 else f"── {h['title']}"
    out = [title]
    if h["briefing"]:
        out.append(h["briefing"])
    out += h["notes"]
    if h["show_risk_card"]:
        out += risk_card_lines(v["risk_card"])
    return out


def risk_card_lines(c: dict) -> list[str]:
    vols = ", ".join(f"{f['name'].replace('_', ' ')} {f['normal_daily_vol']:g}{f['vol_unit']}" for f in c["factors"])
    return [f"Training assumptions (a simplified model for this exercise, not estimates of true market volatility): typical daily move at "
            f"normal volatility: {vols}. Today's volatility is x{c['regime_vol']:g} of normal, and a step's move scales with the square root of "
            "its length in days."]


def market_lines(m: dict) -> list[str]:
    if m["mode"] == "single":
        f = m["focus"]
        return [f"Curve (6M-Euribor swaps): " + " | ".join(f"{r['tenor']}Y {pct(r['mid'])}" for r in m["curve"]),
                f"{f['tenor']}Y EUR IRS: mid {pct(f['mid'], 4)}   street {pct(f['bid'], 4)} / {pct(f['offer'], 4)}   "
                f"(a €1m {f['tenor']}Y swap has DV01 €{f['dv01_per_m']:,.0f})"]
    out = ["Swaps:  tenor    mid        street bid / offer     DV01 per €1m   cost to hedge (half the interdealer spread)"]
    for r in m["ladder"]:
        out.append(f"        {r['tenor']:>3}Y   {pct(r['mid'], 4)}   {pct(r['bid'], 4)} / {pct(r['offer'], 4)}   "
                   f"€{r['dv01_per_m']:>6,.0f}        {r['cost_bp']:.2f}bp")
    for p in m["products"]:
        if p["kind"] == "future":
            out.append(f"{p['label']}: price {p['price']:.2f}; DV01 €{p['dv01_per_unit']:,.0f} per contract; crossing costs "
                       f"{p['half_spread_ticks']:.1f} tick (€{p['cost_per_unit']:,.0f} a contract). {p['info']}")
        else:
            out.append(f"{p['label']}: clean {p['clean']:.2f}, yield {pct(p['yield'], 3)}, ASW {p['asw_bp']:+.1f}bp; DV01 "
                       f"€{p['dv01_per_unit']:,.0f} per €1m face; crossing costs {p['half_spread']:.3f} "
                       f"(€{p['cost_per_unit']:,.0f} per €1m). {p['info']}")
    return out


def book_lines(b: dict) -> list[str]:
    out = []
    for r in b["swaps"]:
        out.append(f"  {r['label']}: {r['side']} fixed {eur_m(r['notional'])} {r['tenor']}Y at {pct(r['rate'], 4)}")
    for h in b["hedges"]:
        q = h["quantity"]
        if h["code"] == "CTD":
            out.append(f"  hedges: {'long' if q > 0 else 'short'} {eur_m(abs(q))} face of the CTD bond")
        else:
            out.append(f"  hedges: {'long' if q > 0 else 'short'} {abs(q):,.0f} {h['code']}")
    if not out:
        out.append("  flat")
    dv, lim = b["dv01"], b["limit_dv01"]
    out.append(f"Book DV01 {fmt_eur(dv)}/bp ({'long' if dv > 0 else 'short'} duration), {abs(dv) / lim:.0%} of your {lim / 1e3:,.0f}k limit."
               if abs(dv) > 1 else f"Book DV01 ~0, limit {lim / 1e3:,.0f}k.")
    if b["buckets"] is not None:
        if b["buckets"]:
            out.append("DV01 by bucket: " + "  ".join(f"{r['tenor']}Y {fmt_eur(r['dv01'])}" for r in b["buckets"]))
        s = b["slope"]
        lim_s = f", {abs(s['exposure']) / s['limit']:.0%} of your {s['limit'] / 1e3:,.0f}k curve limit" if s["limit"] else ""
        out.append(f"Slope exposure {fmt_eur(s['exposure'])}{lim_s}. (Slope exposure = P&L for a 1bp FLATTENING of the slope factor, a 2s30s twist "
                   "about the 10Y: per bp of flattening the 2Y rises 1bp, the 5Y 0.625bp, the 10Y is unchanged, the 30Y falls 1bp. Same sign "
                   "convention as DV01.)")
        out.append(f"Curvature exposure {fmt_eur(b['curvature'])} (P&L for a 1bp fall of the belly against the wings: per unit the 5Y "
                   "falls 1bp and the 10Y 0.25bp, while the 2Y rises 0.125bp and the 30Y 0.5bp). No limit, but it is risk.")
    elif b["curve_position"] is not None:
        out.append(f"Curve position: {fmt_eur(b['curve_position'])} per bp of slope beyond your outright {b['focus_tenor']}Y risk "
                   "(slope = 2s30s steepening, pivoting on the 10Y).")
    if b["spreads"] is not None:
        out.append(f"Swap-spread exposure {fmt_eur(b['spreads']['swap_spread'])} per bp of ASW tightening; futures-basis exposure "
                   f"{fmt_eur(b['spreads']['fut_basis'])} per tick of futures richening.")
    out.append(f"P&L so far: {fmt_eur(b['pnl_so_far'])}")
    return out


def research_lines(r: dict) -> list[str]:
    way = "RISE" if r["remaining_bp"] > 0 else "FALL"
    return [f"Research: {r['text']}",
            f"  What is left of that view (the part your pricing and risk are judged against): about {abs(r['remaining_bp']):.1f}bp {way} over "
            f"the {r['steps_left']} step{'s' if r['steps_left'] != 1 else ''} still to come ({r['steps_total']} in the session, the view spread evenly), "
            f"about {abs(r['per_step_bp']):.1f}bp a step, and at {r['reliability']:.0%} stated reliability the desk should expect about "
            f"{abs(r['expected_per_step_bp']):.2f}bp of it in the next step."]


def conditions_lines(c: dict) -> list[str]:
    out = [f"Volatility: {c['volatility']}.  Liquidity: {c['liquidity']}.", f"Flow: {c['flow']}"]
    sc = c["swap_cost"]
    if sc:
        out.append(f"Swaps cost about {sc['multiplier']:g}x their usual spread to trade now"
                   + (f", and size moves the market: a swap hedge of D DV01 costs (1 + D / {sc['depth_dv01'] / 1e3:,.0f}k) times that."
                      if sc["depth_dv01"] else "."))
    if c["desk_expectation"]:
        out.append(f"Desk expectation: {c['desk_expectation']}")
    if c["research"]:
        out += research_lines(c["research"])
    if c["named_clients"]:
        out.append("Today's named clients and what the market did after each of their requests (the level of rates over the next step):")
        for cl in c["named_clients"]:
            out.append(f"  {cl['name']} ({cl['description']}): " + "; ".join(
                f"{o['side']}, then rates {o['move_bp']:+.1f}bp" for o in cl["observations"]))
    if c["calendar"]:
        out.append(f"Calendar: the data release lands in the next step (expect moves about {c['calendar']['vol_mult']:g}x normal).")
    return out + list(c["extra_lines"])


def _who(i: dict) -> str:
    return f"{i['name']} ({i['short']})" if i["name"] else i["description"]


def observation_lines(v: dict) -> list[str]:
    kind = v["kind"]
    if kind == "checkpoint":
        cp = v["checkpoint"]
        if not cp["with_screen"]:
            return [cp["intro"]]
        i = cp["inquiry"]
        return head_lines(v) + market_lines(v["market"]) + ["Your book:"] + book_lines(v["book"]) + [
            cp["intro"], f"A client asks to {i['action'].rstrip('s')} fixed on {eur_m(i['notional'])} {i['tenor']}Y."]
    out = head_lines(v) + market_lines(v["market"])
    if kind == "quote":
        return out + ["Your book:"] + book_lines(v["book"]) + conditions_lines(v["conditions"]) + [
            "Clients today: " + ", ".join(v["clients_today"]) + "."]
    if kind == "rfq":
        i = v["inquiry"]
        you = "RECEIVE" if i["action"] == "pays" else "PAY"
        out += ["Your book:"] + book_lines(v["book"])
        if v["conditions"] is not None:
            out += conditions_lines(v["conditions"])
        return out + [f"Inquiry: {_who(i)}.",
                      f"It asks for a price to {i['action'].upper().rstrip('S')} fixed on {eur_m(i['notional'])} {i['tenor']}Y: if it deals, "
                      f"you {you} fixed (DV01 {fmt_eur(i['dv01'])})."]
    # risk decisions
    li = v["last_inquiry"]
    if li:
        out.append(f"Last inquiry: {li['short']} wanted to {li['action'].rstrip('s')} fixed on {eur_m(li['notional'])} {li['tenor']}Y; "
                   f"{li['outcome']}.")
    out += ["Your book now:"] + book_lines(v["book"]) + conditions_lines(v["conditions"])
    hm = v["hedge_menu"]
    if hm:
        out.append("Hedge in the interdealer market at mid plus half its bid/offer.  " + ";  ".join(
            f"{r['tenor']}Y: DV01 €{r['dv01_per_m']:,.0f} per €1m, costs {r['cost_bp']:.2f}bp to cross" for r in hm) + ".")
    if v["overnight"]:
        out.append(f"Overnight on an unchanged curve your book would make {fmt_eur(v['overnight']['time_pnl'])} from carry, roll-down and funding "
                   "(the desk's carry report).")
        out.append("The market is closing: the next move is overnight, and it carries more risk than an hour of trading.")
    else:
        out.append(f"The next market move comes before your next decision ({_step_text(v['next_step']['trading_hours'])}).")
    return out


def _step_text(hours: float) -> str:
    if hours < 0.9:
        return f"about {hours * 60:.0f} minutes of trading"
    return f"about {hours:.0f} hour{'s' if hours >= 1.5 else ''} of trading"


# ------------------------------------------------------------------------------------------------- step results

def result_lines(events: list[dict]) -> list[str]:
    out: list[str] = []
    for e in events:
        t = e["type"]
        if t == "client_arrives":
            who = f"{e['name']} ({e['short']})" if e["name"] else e["description"]
            out.append(f"A client arrives: {who}. It wants to {e['action'].rstrip('s')} fixed on {eur_m(e['notional'])} "
                       f"(your {'offer' if e['action'] == 'pays' else 'bid'} {pct(e['your_rate'], 4)} vs street {pct(e['street_rate'], 4)}).")
        elif t == "passed":
            out.append("You passed. The client dealt elsewhere.")
        elif t == "fill":
            if not e["filled"]:
                out.append(f"The client dealt elsewhere (your chance of winning it was {e['p_win']:.0%}).")
            else:
                out.append(f"DONE: the client {e['action']} fixed on {eur_m(e['notional'])} {e['tenor']}Y at {pct(e['rate'], 4)} with you "
                           f"(chance was {e['p_win']:.0%}). You {e['dealer_side']} fixed. Edge against mid: {fmt_eur(e['edge'])}.")
        elif t == "checkpoint_recorded":
            out.append("Answer recorded: it is checked after you price the request.")
        elif t == "checkpoint_grade":
            line = ("✓ " if e["correct"] else "✗ ") + e["feedback"] + ("" if e["correct"] else f" It is {e['expected']}.")
            out.append((e["label"] + ": " if e["label"] else "") + line)
        elif t == "flat_book":
            out.append("Your book is flat: nothing to hedge.")
        elif t == "hedge_trade":
            if e["kind"] == "swap":
                out.append(f"Hedged: you {e['side']} fixed {eur_m(e['notional'])} {e['tenor']}Y at {pct(e['rate'], 4)} (cost {fmt_eur(e['cost'])}).")
            else:
                if e["kind"] == "future":
                    qty, what = e["contracts"], f"{abs(e['contracts']):,.0f} {e['code']}"
                else:
                    qty, what = e["face"], f"{eur_m(abs(e['face']))} face of the {e['code']} bond"
                out.append(f"Done: you {'bought' if qty > 0 else 'sold'} {what} (cost {fmt_eur(e['cost'])}).")
        elif t == "skipped_trade":
            out.append(f"Not traded: {e['description']} is too small to matter (under {e['threshold_pct']:g}% of your DV01 limit).")
        elif t == "no_trade":
            out.append("No trade: you keep the book as it is.")
        elif t == "overnight":
            out.append("Overnight (curve unchanged): " + ", ".join(f"{c['name'].replace('time: ', '')} {fmt_eur(c['amount'])}"
                                                                    for c in e["causes"]) + ".")
        elif t == "market":
            desc = ", ".join(f"{m['name'].replace('_', ' ')} {m['value']:+.1f}" for m in e["factor_moves"])
            out.append(f"Market{' (the release)' if e['release'] else ''}: the {e['focus_tenor']}Y moves {e['move_bp']:+.1f}bp ({desc}).")
            detail = ", ".join(f"{m['name'].replace('_', ' ')} {fmt_eur(m['pnl'])}" for m in e["first_order"] if abs(m["pnl"]) >= 0.5)
            out.append(f"Market P&L: first order {fmt_eur(e['first_total'])} ({detail or 'nothing'}); full revaluation "
                       f"{fmt_eur(e['full_revaluation'])} (convexity/cross {fmt_eur(e['convexity_cross'])}).")
        elif t == "round_pnl":
            out.append(f"Round P&L {fmt_eur(e['round_pnl'])}; total {fmt_eur(e['total_pnl'])}.")
        else:
            raise ValueError(f"unknown event {t!r}")
    return out


def assessment_lines(a: dict) -> list[tuple[str, str]]:
    """(role, text) pairs: roles are headline, reason, note, row, after. The terminal styles them; a frontend may do what it likes."""
    out = [("headline", f"Your decision: {a['rating'].upper()}  (judged on what you knew when you committed)")]
    out += [("reason", "• " + r) for r in a["reasons"]]
    if a["table"]:
        out.append(("note", "Revealed now that you have committed: the benchmark alternatives. E = expected P&L to the next mark "
                            "(hedge cost now, the cost of exiting what you keep later net of expected client flow, and any drift "
                            "expected after this client's trade); sigma = risk over the next step."))
        for r in a["table"]:
            out.append(("row", f"  {r['label']:<38} E €{r['expected']:>10,.0f}   sigma €{r['sigma']:>10,.0f}   {r['rating']}"))
    out.append(("after", "What happened next:"))
    return out


# ------------------------------------------------------------------------------------------------- debrief

def debrief_lines(d: dict) -> list[str]:
    out = ["DECISIONS (judged on what you knew at the time):"]
    for r in d["decisions"]:
        out.append(f"  round {r['round'] + 1} {r['kind']:<9} {r['rating'].upper():<10} {r['headline']}")
    for g in d["calculation_checks"]:
        out.append(f"  calculation check: {'correct' if g['correct'] else 'missed'} ({g['expected']})")
    o = d["outcome"]
    out.append("OUTCOME (what this market path did):")
    out.append("  " + "; ".join(f"{c['cause']} {fmt_eur(c['amount'])}" for c in o["by_cause"]) + f"  =>  total {fmt_eur(o['total'])}")
    if o["exposures_by_round"] is not None:
        out.append("  Your exposures through the move each round (level DV01 / slope):  "
                   + "  ".join(f"R{r['round'] + 1} {fmt_eur(r['level'])}/{fmt_eur(r['slope'])}" for r in o["exposures_by_round"]))
    if o["spread_note"] is not None:
        out.append(f"  Your hedges carried spread risk: swap spread {fmt_eur(o['spread_note']['swap_spread'])}, futures basis "
                   f"{fmt_eur(o['spread_note']['fut_basis'])}. That is what a cheaper product hedge costs when bonds or futures move against swaps.")
    out.append(f"  Risk left: DV01 {fmt_eur(o['risk_left']['dv01'])}; flattening it would cost about {fmt_eur(o['risk_left']['flatten_cost'], False)}.")
    lk = d["luck"]
    out.append("LUCK (realised minus what your decisions were expected to make):")
    out.append(f"  expected {fmt_eur(lk['expected_pnl'])}, realised {fmt_eur(lk['realised_pnl'])}: luck {fmt_eur(lk['luck'])}"
               + (f" ({lk['sigma_units']:+.1f} sigma of the uncertainty your decisions left: fills and market)." if lk["sigma_units"] is not None else "."))
    out.append("  'Expected' here is the EXPECTED P&L FROM EXECUTION UNCERTAINTY: what your decisions were priced to make when you took them, with "
               "each client counted at its probability of dealing with you, plus hedge and exit costs and any drift expected after a client's trade. "
               "Who actually dealt with you, and where the market went, is what the luck figure measures.")
    out.append("  A good decision can lose money and a poor one can make it: judge the decisions above, not this line.")
    out.append("CLIENTS (now revealed):")
    for c in d["clients"]:
        out.append(f"  round {c['round'] + 1}: {c['name'] + ', ' if c['name'] else ''}{c['ctype'].replace('_', ' ')} {c['action']} {eur_m(c['notional'])}"
                   f"{' ' + str(c['tenor']) + 'Y' if c['tenor'] else ''}; {'INFORMED (the market drifted its way)' if c['informed'] else 'not informed'}; "
                   f"{'traded with you' if c['traded'] else 'did not trade with you'}.")
    if d["evidence_vs_truth"] is not None:
        out.append("  What the evidence said before each request (P(informed) from the trades and moves you had seen) against the truth:")
        for r in d["evidence_vs_truth"]:
            out.append(f"    {r['name']}: " + ", ".join(f"{p:.0%}" for p in r["posteriors"]) + f"  -> truth: {'informed' if r['informed'] else 'not informed'}")
    if d["view_truth"] is not None:
        v = d["view_truth"]
        out.append(f"  The research view was {'RIGHT (it carried information)' if v['right'] else 'NOISE this time'}; "
                   f"its stated reliability was {v['reliability']:.0%}.")
    cf = d["counterfactuals"]
    if cf is not None:
        out.append("SAME CLIENTS, SAME MARKET PATH, OTHER POLICIES:")
        for r in cf["policies"]:
            out.append(f"  {r['name']:<44} P&L {fmt_eur(r['pnl']):>10}   decisions: " + ", ".join(r["ratings"]))
        out.append(f"  {'you':<44} P&L {fmt_eur(cf['you']):>10}")
    mp = d["market_paths"]
    if mp is not None:
        y = mp["yours"]
        out.append(f"{mp['n']} OTHER MARKET PATHS (supplements the same-path comparison above; decisions and clients held fixed, first-order P&L):")
        out.append(f"  your decisions:      mean {fmt_eur(y['mean'])}, 5%-95% {fmt_eur(y['p05'])} to {fmt_eur(y['p95'])}; "
                   f"your realised P&L sits at the {mp['rank']:.0%} point.")
        if mp["reference"] is not None:
            r = mp["reference"]
            out.append(f"  reference desk:      mean {fmt_eur(r['mean'])}, 5%-95% {fmt_eur(r['p05'])} to {fmt_eur(r['p95'])}.")
        out.append("  A wide band means the result was mostly luck; compare the means to judge the decisions.")
        out.append("  This is a different quantity from the 'expected' figure in the LUCK section: it is the MARKET-PATH P&L DISTRIBUTION conditional on "
                   "these decisions AND the fills you actually got (the edge those fills paid is counted as it happened, not at its probability), "
                   "re-drawing only the market, the research view and who was informed. The two means are not meant to match.")
    return out
