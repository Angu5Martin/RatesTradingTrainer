"""Market-making judgement that can be assessed without the stateful episode engine.

These are the transferable parts of the Live Desk skills: reading a client request, re-quoting after a fill, a stale quote, hedge cost against edge,
a proposed quote, the economics of adverse selection, hedging a swap with futures, and risk around a scheduled event. Everything with a model behind it uses the
engine (swaps, futures) or the teaching quote model in marketmaking.quoting, which is graded on DIRECTION and relative size only. Nothing here reproduces
the episodes' hidden-information mechanics: no informed-flow indicator is shown, and no answer depends on knowing the true value.
"""

from __future__ import annotations

import random
from dataclasses import replace

from ...engine.curve import CurveShock
from ...engine.futures import BOBL, BUND, SCHATZ
from ...engine.instruments import Side
from ...engine.pnl import revalue_pnl
from ...engine.risk import Portfolio, dv01_hedge_swap, par_irs, parallel_dv01, unit_dv01
from ...marketmaking.quoting import BP, ClientAction, Liquidity, Quote, QuotingContext, make_quote
from ..market import eur_m, pct, random_futures, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template
from .mm_client_trade import ALL_TENORS, HALF_WIDTHS
from .mm_skew import ADV_TEXT, HALF_SPREAD, LIQ_TEXT, VOL_TEXT, _crisp, _sample


def _quote(mid: float, w: float) -> Quote:
    """A market on the 0.1bp grid (three decimals of a percent) around mid, `w` bp each side (a multiple of 0.1bp), so the numbers on the screen are exact."""
    m = round(mid, 5)
    return Quote(round(m - w * BP, 5), round(m + w * BP, 5))


# ------------------------------------------------------------------------------------------------------------------ bid / offer drill

@template("mm.bid_offer_drill", skill="mm.bid_offer", difficulty=1, kind="calculation")
def bid_offer_drill(rng: random.Random) -> QuestionBody:
    """Which side of your market does a client request hit, what do you hold afterwards, and which client do you now want?"""
    mkt = random_market(rng)
    tenor = rng.choice(list(HALF_WIDTHS))
    w = rng.choice(HALF_WIDTHS[tenor])
    mid = mkt.quotes["E6M"][tenor * 12]
    q = _quote(mid, w)
    action = rng.choice(list(ClientAction))
    notional = rng.choice([25, 50, 100, 150, 200, 300]) * 1e6
    swap = q.dealer_swap(action, notional, mkt, tenor)
    dv01 = parallel_dv01(swap, mkt)
    per100 = unit_dv01(tenor, mkt) * 100
    while True:
        inv0 = rng.choice([-1, 1]) * rng.choice([100e3, 150e3, 250e3, 350e3]) * rng.choice([0.5, 1.0])
        inv1 = inv0 + dv01
        if abs(inv1) > 25e3:
            break
    wording = rng.choice(["client", "ask"])
    if wording == "client":
        request = f"A client {action.value} fixed on {eur_m(notional)} {tenor}Y."
    else:
        asked = "PAY" if action is ClientAction.RECEIVES else "RECEIVE"
        request = f"A client asks you to {asked} fixed on {eur_m(notional)} {tenor}Y."
    held = "Receive fixed (long duration)" if swap.side is Side.RECEIVE else "Pay fixed (short duration)"
    want = ClientAction.RECEIVES if inv1 > 0 else ClientAction.PAYS               # long duration: you want to PAY fixed, so a client who RECEIVES
    stem = (
        f"EUR {tenor}Y swap, your market {pct(q.bid, 3)} / {pct(q.offer, 3)} (bid / offer). Convention: you PAY fixed at your bid and RECEIVE fixed at your offer. "
        f"DV01 per EUR 100m of this swap is {fmt_eur(per100, False)}; positive DV01 = long duration.\n"
        f"Before this request you are {'long' if inv0 > 0 else 'short'} {abs(inv0) / 1e3:,.0f}k of DV01.\n{request}"
    )
    parts = [
        NumericPart("At what rate (in %) does the trade execute?", (q.client_rate(action)) * 100, Tolerance(rel=0, abs=0.0004), "%",
                    note="your bid or your offer, whichever the client deals on"),
        shuffled_choice(rng, "What do you now hold from this trade?",
                        [held, "Pay fixed (short duration)" if swap.side is Side.RECEIVE else "Receive fixed (long duration)"],
                        f"The client {action.value} fixed, so they deal on your {'offer' if action is ClientAction.PAYS else 'bid'}, and you "
                        f"{'receive' if swap.side is Side.RECEIVE else 'pay'} fixed."),
        NumericPart("What is your total DV01 after the trade (EUR per bp, + = long duration)?", inv1, Tolerance(rel=0.02, abs=4000), "EUR",
                    sign_hint="Add the trade's DV01 to what you had; receiving fixed is positive.", note="before + the trade, with signs"),
        shuffled_choice(rng, "Given what you now hold, which client trade would you most like to see next?",
                        [f"A client who {want.value} fixed: it reduces your {'long' if inv1 > 0 else 'short'} duration position",
                         f"A client who {want.opposite.value} fixed: it adds to your position",
                         "Either: only the spread matters, not the direction"],
                        "Long duration (you have received fixed) is reduced by PAYING fixed, which happens when a client receives on your bid. "
                        "So a long dealer wants clients to receive and shades the bid up to attract them; a short dealer wants clients to pay."),
    ]
    solution = [
        f"Client {action.value} fixed => dealt on your {'offer' if action is ClientAction.PAYS else 'bid'}: {pct(q.client_rate(action), 3)}. You {'receive' if swap.side is Side.RECEIVE else 'pay'} fixed: {held}.",
        f"Trade DV01 = {eur_m(notional)} / 100m x {fmt_eur(per100, False)} = {fmt_eur(dv01)}. Total = {fmt_eur(inv0)} + ({fmt_eur(dv01)}) = {fmt_eur(inv1)}.",
        f"After the trade you are {'long' if inv1 > 0 else 'short'} duration; the useful next client is the one who {want.value} fixed. "
        "The quote logic follows: shade the market towards that client and away from the one who would add to your risk.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "quote": q, "action": action, "swap": swap, "dv01": dv01, "inv0": inv0, "inv1": inv1, "want": want})


# ------------------------------------------------------------------------------------------------------------------ re-quote after a fill

def _rq_context(rng: random.Random):
    """A benign two-way flow context, so the only thing that changes between quotes is the inventory."""
    tenor = rng.choice([5, 10, 30])
    limit = rng.choice([200e3, 300e3, 400e3, 500e3])
    inv0 = round(rng.choice([-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6]) * limit / 5e3) * 5e3
    adv = rng.choice([0.0, 0.3])
    vol = rng.choice([1.0, 1.0, 1.5])
    return tenor, limit, inv0, adv, vol


@template("mm.requote_sequence", skill="mm.requote_loop", difficulty=3, kind="calculation")
def requote_sequence(rng: random.Random) -> QuestionBody:
    """Quote, get hit, new inventory, re-quote: direction of the move, whether the skew grew, shrank or flipped, and whether the limit now bites."""
    for _ in range(500):
        mkt = random_market(rng)
        tenor, limit, inv0, adv, vol = _rq_context(rng)
        mid = mkt.quotes["E6M"][tenor * 12]
        hs = HALF_SPREAD[tenor]
        unit = unit_dv01(tenor, mkt)
        action = rng.choice(list(ClientAction))
        size = rng.choice([25, 50, 75, 100, 150, 200, 250, 300, 400]) * 1e6
        if not 0.2 <= size / 1e6 * unit / limit <= 0.8:
            continue
        dv = (1 if action is ClientAction.PAYS else -1) * size / 1e6 * unit
        inv1 = inv0 + dv
        ctx0 = QuotingContext(fair_value=mid, base_half_spread_bp=hs, inventory_dv01=inv0, dv01_limit=limit, vol_multiplier=vol,
                              liquidity=Liquidity.NORMAL, adverse_selection=adv)
        ctx1 = replace(ctx0, inventory_dv01=inv1)
        b0, b1 = make_quote(ctx0), make_quote(ctx1)
        shift = b1.net_shift_bp - b0.net_shift_bp
        s0, s1 = b0.net_shift_bp, b1.net_shift_bp
        u1 = abs(inv1) / limit
        if abs(shift) < 0.12 or not (u1 > 1.05 or u1 < 0.55):
            continue
        if abs(inv1) < 20e3:
            continue
        if abs(s0) < 0.02:
            kind = "from flat"
        elif s0 * s1 < 0 and abs(s1) > 0.03:
            kind = "flips"
        elif abs(s1) > abs(s0) + 0.03:
            kind = "larger"
        elif abs(s1) < abs(s0) - 0.03:
            kind = "smaller"
        else:
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a re-quote case")
    held = "Receive fixed (long duration)" if dv > 0 else "Pay fixed (short duration)"
    q0, q1 = b0.quote, b1.quote
    breach = u1 > 1.05
    excess = (abs(inv1) - limit)
    stem = (
        f"EUR {tenor}Y swap, fair value {pct(mid, 3)}. DV01 per EUR 1m is {fmt_eur(unit, False)}. Your DV01 limit is {limit / 1e3:,.0f}k. Conditions: "
        f"volatility {VOL_TEXT[vol]}, flow quality {ADV_TEXT[adv].split(':')[0]}, liquidity normal, two-way flow expected, no view.\n"
        f"Your inventory is {'LONG' if inv0 > 0 else 'SHORT' if inv0 < 0 else 'FLAT'}{'' if inv0 == 0 else f' {abs(inv0) / 1e3:,.0f}k DV01 ({abs(inv0) / limit * 100:.0f}% of the limit)'} "
        f"and you are quoting {pct(q0.bid, 3)} / {pct(q0.offer, 3)}.\n"
        f"A client {action.value} fixed on {eur_m(size)}. You do the trade."
    )
    kind_text = {"from flat": "It was symmetric before; now it should lean",
                 "larger": "Larger, in the same direction: the position has grown the pressure",
                 "smaller": "Smaller, in the same direction: the trade reduced the pressure",
                 "flips": "It reverses: you went from one side of flat to the other"}
    parts = [
        shuffled_choice(rng, "What do you now hold from this trade?", [held, "Pay fixed (short duration)" if dv > 0 else "Receive fixed (long duration)"],
                        f"A client who {action.value} fixed deals on your {'offer' if dv > 0 else 'bid'}; you {'receive' if dv > 0 else 'pay'} fixed."),
        NumericPart("What is your new total DV01 (EUR per bp, + = long duration)?", inv1, Tolerance(rel=0.02, abs=4000), "EUR",
                    sign_hint="Add the trade's DV01 to what you had; receiving fixed is positive.", note="before + the trade"),
        shuffled_choice(rng, "Compared with your last market, where should the CENTRE of the new market move?",
                        ["Higher in rate (both bid and offer up): your position is now longer, you want to pay fixed" if shift > 0 else
                         "Lower in rate (both bid and offer down): your position is now shorter, you want to receive fixed",
                         "Lower in rate (both bid and offer down): your position is now shorter, you want to receive fixed" if shift > 0 else
                         "Higher in rate (both bid and offer up): your position is now longer, you want to pay fixed",
                         "Unchanged: a filled client trade is already in the price"],
                        "A long-duration dealer pays fixed to get flat, so it shades both prices UP in rate (the bid becomes more attractive to a client who receives); "
                        "a short dealer shades DOWN. The move is relative to the last market, which already reflected the old inventory."),
        shuffled_choice(rng, "How does the skew compare with before the trade?", [kind_text[kind], *[v for k, v in kind_text.items() if k != kind]],
                        f"Skew follows inventory: from {s0:+.2f}bp to {s1:+.2f}bp in the teaching model. A trade in the direction of your existing inventory grows "
                        "the lean; one against it shrinks it, and a trade big enough to cross zero reverses it."),
        shuffled_choice(rng, "What should you do about the position?",
                        [(f"Hedge at least the excess over the limit now (about {excess / 1e3:,.0f}k DV01): you are past it, and skew alone is too slow"
                          if breach else "Keep working it: skew and wait for the next flow rather than pay to hedge a position this size"),
                         ("Do nothing: skewing will bring the flow back" if breach else "Hedge the whole position at once to stay flat every time"),
                         "Widen the market on both sides and keep the position as it is",
                         ("Quote symmetrically again to avoid scaring clients" if breach else "Raise the limit so the position fits")],
                        f"Utilisation after the trade is {u1 * 100:.0f}%. " + (
                            "A limit is a constraint, not a preference: past it, you must reduce, and the only quick way is to hedge." if breach else
                            "Well inside the limit the skew does the work, and every hedge crosses a spread that gives back the edge you just earned.")),
    ]
    solution = [
        f"The client {action.value} fixed => you {'receive' if dv > 0 else 'pay'} fixed: {fmt_eur(dv)} of DV01 ({eur_m(size)} x {fmt_eur(unit, False)} per EUR 1m). "
        f"Total {fmt_eur(inv0)} -> {fmt_eur(inv1)} ({u1 * 100:.0f}% of the limit).",
        f"Teaching-model skew: {s0:+.2f}bp before, {s1:+.2f}bp after (a move of {shift:+.2f}bp); illustrative market now {pct(q1.bid, 4)} / {pct(q1.offer, 4)} against "
        f"{pct(q0.bid, 4)} / {pct(q0.offer, 4)} before. The direction and the change of size are the lesson, not the decimals.",
        "The loop: fair value -> quote -> fill -> inventory -> re-quote. The quote after a fill is not the quote before it, and a fill on the encouraged side "
        "buys you a smaller skew, while one on the wrong side asks for a bigger one.",
        "Hedge or keep working it is a trade-off between cost and risk: the nearer the limit, the less choice you have.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "ctx0": ctx0, "ctx1": ctx1, "b0": b0, "b1": b1, "dv": dv, "inv0": inv0, "inv1": inv1, "shift": shift,
                                                 "kind": kind, "u1": u1, "breach": breach, "action": action})


# ------------------------------------------------------------------------------------------------------------------ stale quote

@template("mm.stale_quote", skill="mm.requote_loop", difficulty=2, kind="calculation")
def stale_quote(rng: random.Random) -> QuestionBody:
    """The market moves and your quote has not: who trades, what it costs, and where the new market belongs."""
    for _ in range(200):
        mkt = random_market(rng)
        tenor = rng.choice([2, 5, 10, 30])
        w = rng.choice([0.1, 0.2, 0.3])
        move = rng.choice([-1, 1]) * rng.choice([1.0, 1.5, 2.0, 3.0])
        q = _quote(mkt.quotes["E6M"][tenor * 12], w)
        mid = q.mid
        up = move > 0
        action = ClientAction.PAYS if up else ClientAction.RECEIVES       # rates up: a client wants to pay your too-low offer? No: pay at the stale (low) offer
        notional = rng.choice([50, 100, 200, 300]) * 1e6
        swap = q.dealer_swap(action, notional, mkt, tenor)
        loss = swap.pv(mkt.shifted(CurveShock.parallel(move)))
        dv01 = parallel_dv01(swap, mkt)
        edge = swap.pv(mkt)
        if loss < 0 and abs(loss) > 0.4 * abs(dv01) and abs(edge) > 1000:
            break
    new_mid = mid + move * BP
    new_offer, new_bid = new_mid + w * BP, new_mid - w * BP
    hit = "offer" if up else "bid"
    stem = (
        f"EUR {tenor}Y swap, your market {pct(q.bid, 3)} / {pct(q.offer, 3)} (mid {pct(mid, 3)}). A data release moves the whole {tenor}Y swap rate "
        f"{move:+g}bp, so the fair value is now {pct(new_mid, 3)}. You have not yet updated your quote.\n"
        f"A client immediately {action.value} fixed on {eur_m(notional)}, trading on your old {hit}."
    )
    approx_pnl = dv01 * (-move) + (abs(dv01) * w)           # first order: half-spread captured vs the move, signed through the dealer's DV01
    parts = [
        shuffled_choice(rng, "Which side of your old market is now the dangerous one?",
                        [("The OFFER: rates rose, so receiving fixed at your old offer is now below fair value" if up else
                          "The BID: rates fell, so paying fixed at your old bid is now above fair value"),
                         ("The BID: rates rose, so paying fixed at your old bid is now above fair value" if up else
                          "The OFFER: rates fell, so receiving fixed at your old offer is now below fair value"),
                         "Neither: the spread protects you from any move",
                         "Both equally, because a move in either direction hurts a market maker"],
                        "After a move up, a client can pay fixed (hit your offer) at a rate below the new fair value: you receive less than the market now pays. "
                        "After a move down, the bid is the stale price. The side to cancel or move first is the one that has become cheap."),
        NumericPart(f"What is your mark-to-market P&L (EUR) on that trade, marking at the NEW mid ({pct(new_mid, 3)})?", loss, Tolerance(rel=0.05, abs=0.08 * abs(dv01)), "EUR",
                    approx=approx_pnl, approx_label="DV01 x (half-spread less the move)", sign_hint="Compare the half-spread you collected with the move you missed.",
                    note=f"your DV01 is {fmt_eur(dv01)} per bp"),
        NumericPart(f"You now re-quote with the same {w:g}bp each side. What is your new {'offer' if up else 'bid'} (in %)?", (new_offer if up else new_bid) * 100,
                    Tolerance(rel=0, abs=0.0004), "%", note="new mid +/- the same half-width"),
        shuffled_choice(rng, "What does this teach about when to change a quote?",
                        ["Update when fair value moves, before waiting to be traded: the spread is for noise and for fills, not for a moved market",
                         "Leave the quote alone: a market maker earns the spread whatever the market does",
                         "Widen the spread in advance of every release and never update after it",
                         "Only change quotes when inventory changes"],
                        "A quote is a standing offer: when the market moves through it, informed or fast clients take it. The half-spread is the cushion for being wrong by "
                        f"less than {w:g}bp; a {abs(move):g}bp move is {'bigger' if abs(move) > w else 'smaller'} than that."),
    ]
    solution = [
        f"The client {action.value} fixed, so you {'receive' if action is ClientAction.PAYS else 'pay'} fixed at {pct(q.client_rate(action), 3)}; the market is now {pct(new_mid, 3)}. "
        f"Your DV01 is {fmt_eur(dv01)}.",
        f"Marked at the new mid: -DV01 x move + the half-spread = {fmt_eur(-dv01 * move)} + {fmt_eur(abs(dv01) * w, False)} = {fmt_eur(approx_pnl)} first order, {fmt_eur(loss)} revalued. "
        f"Before the move the same trade was worth {fmt_eur(edge)}.",
        f"New market with the same width: {pct(new_bid, 4)} / {pct(new_offer, 4)}.",
        "Moves bigger than your half-spread turn a quote into a free option for whoever sees the move first. Fast updating, a lower size on stale quotes, "
        "and wider markets around scheduled events are all versions of the same protection.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "quote": q, "move": move, "loss": loss, "dv01": dv01, "edge": edge, "approx": approx_pnl, "w": w,
                                                 "up": up, "new_mid": new_mid})


# ------------------------------------------------------------------------------------------------------------------ edge against hedge cost

@template("mm.client_net_edge", skill="mm.client_trade", difficulty=3, kind="calculation")
def client_net_edge(rng: random.Random) -> QuestionBody:
    """The edge in a client trade is not what you quoted: it is what is left after you hedge, and what a mismatch in the hedge can take away."""
    for _ in range(200):
        mkt = random_market(rng)
        tenor = rng.choice([5, 7, 10, 15, 20, 30])
        i = ALL_TENORS.index(tenor)
        hedge_t = rng.choice([h for j, h in enumerate(ALL_TENORS) if h != tenor and abs(j - i) <= 2])
        w = rng.choice(HALF_WIDTHS[tenor])
        h = rng.choice([0.05, 0.1, 0.15, 0.2])
        action = rng.choice(list(ClientAction))
        notional = rng.choice([50, 100, 150, 250]) * 1e6
        mid = mkt.quotes["E6M"][tenor * 12]
        q = _quote(mid, w)
        swap = q.dealer_swap(action, notional, mkt, tenor)
        dv01 = parallel_dv01(swap, mkt)
        hedge = dv01_hedge_swap(dv01, hedge_t, mkt)
        gross = w * abs(dv01)                                    # by construction: the half-width against mid, on the DV01 the engine gives
        cost = h * abs(dv01)
        net = gross - cost
        if net > 0.25 * gross and cost > 0.2 * gross:
            break
    comp = round(h * rng.choice([0.5, 0.75, 1.5, 2.0, 3.0]), 3)
    match_ok = comp > h * 1.15
    hedge_dir = "pay" if hedge.side is Side.PAY else "receive"
    stem = (
        f"EUR {tenor}Y swap: your market {pct(q.bid, 3)} / {pct(q.offer, 3)} (mid {pct(mid, 3)}; half-width {w:g}bp). A client {action.value} fixed on {eur_m(notional)}.\n"
        f"You hedge immediately in the interdealer market with an at-market {hedge_t}Y swap ({hedge_dir} fixed, {eur_m(hedge.notional)}), DV01-neutral. "
        f"That market is {2 * h:g}bp wide around mid: you cross half of it. Your {tenor}Y trade's DV01 is {fmt_eur(dv01)}."
    )
    parts = [
        NumericPart("What spread did you capture against mid on the client trade (EUR)?", gross, Tolerance(rel=0.05), "EUR", note="half-width x |DV01|"),
        NumericPart(f"What does it cost to cross the {hedge_t}Y interdealer spread on the hedge (EUR)?", cost, Tolerance(rel=0.03), "EUR",
                    note="half the interdealer width x |hedge DV01|, which equals your DV01"),
        NumericPart("What is the edge after hedging (EUR)?", net, Tolerance(rel=0.06), "EUR", note="spread captured less hedge cost"),
        NumericPart(f"The hedge is in the {hedge_t}Y, not the {tenor}Y. How many bp can the {min(tenor, hedge_t)}s{max(tenor, hedge_t)}s spread move against you before the net edge is gone (bp)?",
                    net / abs(dv01), Tolerance(rel=0.08, abs=0.01), "bp", note="net edge / |DV01|"),
        shuffled_choice(rng, f"A competitor is showing the client {comp:g}bp each side around mid on the same trade. What does your hedged edge say?",
                        [(f"You can meet it: after paying {h:g}bp to hedge, a half-width of {comp:g}bp still leaves {comp - h:.3g}bp of edge per unit of DV01" if match_ok else
                          f"Not profitably if you hedge: after paying {h:g}bp on the hedge you would keep {comp - h:+.3g}bp per unit of DV01; match it only if you accept holding the risk"),
                         ("You cannot match it: any narrowing of the spread loses money" if match_ok else "You can match it: a tighter quote only affects your volume, not your P&L"),
                         "Match it and hedge later: the hedge cost does not depend on when you trade",
                         "The hedge cost is irrelevant to the quote: it is only a feature of the interdealer market"],
                        f"The price you can afford to show a client is your hedge cost plus the edge you need. Here the hedge costs {h:g}bp per DV01 against the {w:g}bp you quoted."),
    ]
    solution = [
        f"Captured: {w:g}bp x {fmt_eur(abs(dv01), False)} = {fmt_eur(gross)} (marking the swap at mid).",
        f"Hedge cost: {h:g}bp x {fmt_eur(abs(dv01), False)} = {fmt_eur(cost)}. Net edge = {fmt_eur(net)}: {net / gross * 100:.0f}% of what you quoted survives.",
        f"A {hedge_t}Y hedge leaves a {min(tenor, hedge_t)}s{max(tenor, hedge_t)}s mismatch. The net edge covers a spread move of {net / abs(dv01):.2f}bp; beyond that the hedged trade loses money.",
        "The quote is a function of your hedging costs: the tighter the competition, the less of your quoted half-width is profit, and some client flow is only worth "
        "taking if you are willing to warehouse the risk.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "quote": q, "swap": swap, "hedge": hedge, "dv01": dv01, "gross": gross, "cost": cost, "net": net, "h": h, "w": w,
                                                 "comp": comp, "match_ok": match_ok, "hedge_t": hedge_t})


# ------------------------------------------------------------------------------------------------------------------ quote review

@template("mm.quote_review", skill="mm.skew", difficulty=3, kind="conceptual")
def quote_review(rng: random.Random) -> QuestionBody:
    """Pick the sensible market out of four proposals: one is skewed the wrong way, one ignores the state, one is too tight for the conditions."""
    mkt = random_market(rng)
    for _ in range(500):
        tenor, ctx0 = _sample(rng)
        ctx = QuotingContext(**{**ctx0.__dict__, "fair_value": mkt.quotes["E6M"][tenor * 12]})
        b = make_quote(ctx)
        ratio = (b.bid_half_width_bp + b.offer_half_width_bp) / 2 / ctx.base_half_spread_bp
        if _crisp(b, ctx) and abs(b.net_shift_bp) >= 0.12 and ratio >= 1.2:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a quoting context")
    fv, hs = ctx.fair_value, ctx.base_half_spread_bp
    shift = b.net_shift_bp
    bh, oh = b.bid_half_width_bp, b.offer_half_width_bp

    def mk(shift_bp: float, bid_w: float, off_w: float) -> str:
        return f"{pct(fv + (shift_bp - bid_w) * BP, 4)} / {pct(fv + (shift_bp + off_w) * BP, 4)}"

    right = mk(shift, bh, oh)
    mirrored = mk(-shift, bh, oh)
    symmetric = mk(0.0, hs, hs)
    tight = mk(shift, (bh + oh) / 4, (bh + oh) / 4)
    inv, flow, view = ctx.inventory_dv01, ctx.expected_flow_dv01, ctx.view_bp * (ctx.conviction > 0)
    inv_text = "flat" if inv == 0 else f"{'LONG' if inv > 0 else 'SHORT'} {abs(inv) / 1e3:,.0f}k DV01 ({abs(ctx.utilisation) * 100:.0f}% of your {ctx.dv01_limit / 1e3:,.0f}k limit)"
    flow_text = ("two-way, no obvious bias" if flow == 0 else f"you expect more clients to {'PAY' if flow > 0 else 'RECEIVE'} fixed")
    view_text = "no view" if ctx.conviction == 0 else f"you expect the {tenor}Y rate to {'RISE' if ctx.view_bp > 0 else 'FALL'} about {abs(ctx.view_bp):.0f}bp"
    stem = (
        f"EUR {tenor}Y swap. Fair value {pct(fv, 4)}; on a normal day you show {pct(fv - hs * BP, 4)} / {pct(fv + hs * BP, 4)}.\n"
        f"  Inventory: {inv_text}.   Volatility: {VOL_TEXT[ctx.vol_multiplier]}.   Liquidity: {LIQ_TEXT[ctx.liquidity]}.\n"
        f"  Flow: {flow_text}.   Quality of flow: {ADV_TEXT[ctx.adverse_selection]}.   View: {view_text}.\n"
        "Reminder: you pay fixed at your bid and receive fixed at your offer. Four colleagues propose a market (bid / offer):"
    )
    props = [right, mirrored, symmetric, tight]
    enc = b.encouraged_client_action
    parts = [
        shuffled_choice(rng, "Which proposal best fits the situation?", props,
                        f"The sensible market is skewed {b.direction} ({shift:+.2f}bp) and wider than normal (half-width about {(bh + oh) / 2:.2f}bp vs {hs:g}bp). "
                        "The mirror image skews the wrong way, the symmetric market ignores your state, and the tight one ignores volatility, liquidity and flow quality."),
        shuffled_choice(rng, f"What is wrong with {mirrored}?",
                        ["It skews the wrong way: it makes the side that ADDS to your risk more attractive and the side that reduces it less attractive",
                         "It is too wide for any client to trade on",
                         "Nothing: any skew is acceptable as long as the spread is positive",
                         "It is crossed (the bid is above the offer)"],
                        "Skew is a statement of what you want done: a market centred the wrong way pays clients to take you further from where you want to be."),
        shuffled_choice(rng, "Which client trade does the sensible market make most attractive?",
                        [("A client who RECEIVES fixed (you pay fixed): it reduces a long position" if enc is ClientAction.RECEIVES else
                          "A client who PAYS fixed (you receive fixed): it reduces a short position"),
                         ("A client who PAYS fixed (you receive fixed)" if enc is ClientAction.RECEIVES else "A client who RECEIVES fixed (you pay fixed)"),
                         "Both equally: the width does not favour a side",
                         "Neither: the market is too wide for any flow"],
                        "A market centred higher in rate pays more to a client who receives fixed (your bid is closer to the market); lower pays more to one who pays."),
    ]
    solution = [
        f"Net shift {shift:+.2f}bp = inventory {b.inventory_skew_bp:+.2f} + expected flow {b.flow_skew_bp:+.2f} + view {b.view_skew_bp:+.2f}; "
        f"half-width {bh:.2f}bp bid / {oh:.2f}bp offer (base {hs:g}bp).",
        f"Right: {right}. Mirror image: {mirrored}. Symmetric and ignoring the state: {symmetric}. Right direction, too tight: {tight}.",
        "Skew manages inventory; width protects against information and volatility. The common errors are the wrong sign (mixing up which side a long dealer wants), "
        "ignoring the state altogether, and keeping a normal-day spread in a difficult market.",
    ]
    return QuestionBody(stem, parts, solution, {"ctx": ctx, "breakdown": b, "proposals": props, "right": right})


# ------------------------------------------------------------------------------------------------------------------ adverse selection economics

@template("mm.adverse_selection_edge", skill="mm.adverse_selection", difficulty=2, kind="calculation")
def adverse_selection_edge(rng: random.Random) -> QuestionBody:
    """The simplest model of adverse selection: the spread you need equals the informed share times how far the market moves against you."""
    for _ in range(100):
        p = rng.choice([0.1, 0.15, 0.2, 0.3, 0.4])
        mu = rng.choice([0.6, 0.8, 1.0, 1.2, 1.5, 2.0])
        w = rng.choice([0.15, 0.2, 0.25, 0.3, 0.4, 0.5])
        dv = rng.choice([20e3, 40e3, 60e3, 100e3])
        ev = dv * (w - p * mu)
        if abs(w - p * mu) >= 0.05:
            break
    p2 = min(0.6, round(p * 2 * 20) / 20)
    be = p * mu
    be2 = p2 * mu
    stem = (
        f"A stylised model of one client trade of {fmt_eur(dv, False)} DV01 around fair value, quoted with a half-spread of {w:g}bp.\n"
        f"  With probability {1 - p:.0%} the client is uninformed: the market does not move after the trade.\n"
        f"  With probability {p:.0%} the client is informed: right after the trade the market moves {mu:g}bp against you.\n"
        "You mark the trade at fair value after the move. This is an assumption for the exercise: in practice you cannot see which clients are informed."
    )
    parts = [
        NumericPart("What is your expected P&L per trade (EUR)?", ev, Tolerance(rel=0.05, abs=0.01 * dv),
                    "EUR", sign_hint="A negative expectation means the spread does not cover the information.",
                    note="DV01 x [half-spread - (informed share x move)]"),
        NumericPart("What half-spread (bp) makes the expected P&L zero?", be, Tolerance(rel=0.05, abs=0.02), "bp", note="informed share x move against you"),
        NumericPart(f"The informed share rises to {p2:.0%} with the same move. What half-spread breaks even now (bp)?", be2, Tolerance(rel=0.05, abs=0.02), "bp"),
        shuffled_choice(rng, "What is the right way to use this?",
                        ["Widen when you think the flow has become more informed, but remember the extra spread also costs you the uninformed clients who would have paid it",
                         "Always quote at the break-even spread: it is the fair price of every trade",
                         "Widen on every request: informed clients are impossible to avoid",
                         "Ignore it: the inventory skew already handles adverse selection"],
                        "The model gives the spread at which uninformed profit pays for informed loss. A wider spread protects you but also repels volume, and you do not "
                        "know the informed share in advance; skew (inventory) and width (information) are separate tools."),
    ]
    solution = [
        f"Expected P&L = DV01 x [(1 - p) x w + p x (w - mu)] = DV01 x (w - p x mu) = {fmt_eur(dv, False)} x ({w:g} - {p:g} x {mu:g}) = {fmt_eur(ev)}.",
        f"Break-even: w = p x mu = {p:g} x {mu:g} = {be:.2f}bp. At {p2:.0%}: {be2:.2f}bp. Informed flow is charged for by the whole spread, uninformed flow pays it.",
        f"{'Your quote earns' if w > be else 'Your quote loses'} {abs(w - be):.2f}bp per DV01 on average: {'wider than it needs to be' if w > be + 0.05 else 'too tight for this flow'}.",
        "Real markets add inventory costs, competition and the fact that the informed share varies by client, time and event; the exercise shows only the direction and the "
        "size of the effect.",
    ]
    return QuestionBody(stem, parts, solution, {"p": p, "mu": mu, "w": w, "dv": dv, "ev": ev, "be": be, "p2": p2, "be2": be2})


# ------------------------------------------------------------------------------------------------------------------ swap hedged with futures

_FUT_FOR = ((BUND, 10), (BOBL, 5), (SCHATZ, 2))


@template("mm.cross_product_hedge", skill="mm.cross_product_hedging", difficulty=3, kind="calculation")
def cross_product_hedge(rng: random.Random) -> QuestionBody:
    """A client swap hedged with bond futures: how many contracts, what each hedge costs, what basis risk it leaves, and what that does to the saving."""
    for _ in range(100):
        mkt = random_market(rng)
        spec, tenor = rng.choice(_FUT_FOR)
        case = random_futures(rng, mkt, spec=spec, min_gap=0.15)
        fut_dv01 = parallel_dv01(case.fut.with_contracts(1), mkt)
        w = rng.choice([0.2, 0.3, 0.4])
        action = rng.choice(list(ClientAction))
        notional = rng.choice([100, 150, 200, 300]) * 1e6
        q = _quote(mkt.quotes["E6M"][tenor * 12], w)
        swap = q.dealer_swap(action, notional, mkt, tenor)
        dv01 = parallel_dv01(swap, mkt)
        n = -dv01 / fut_dv01
        width = rng.choice([0.3, 0.4, 0.5, 0.6])
        swap_cost = width / 2 * abs(dv01)
        fut_cost = abs(n) * case.spec.tick_value / 2
        saving = swap_cost - fut_cost
        if saving > 0.2 * swap_cost and abs(n) > 100:
            break
    s = rng.choice([1.0, 1.5, 2.0, 3.0])                                      # the adverse swap-spread move, in bp
    adverse = 1.0 if dv01 > 0 else -1.0                                       # long-duration swap leg loses when the swap rate rises against bonds, short loses when it falls
    basis_pnl = revalue_pnl(swap, mkt, CurveShock.parallel(adverse * s))
    be = saving / abs(dv01)
    sigma = rng.choice([0.7, 0.9, 1.1, 1.3])
    verb = "sell" if dv01 > 0 else "buy"
    stem = (
        f"EUR {tenor}Y swap market {pct(q.bid, 3)} / {pct(q.offer, 3)}. A client {action.value} fixed on {eur_m(notional)}. Your DV01 is {fmt_eur(dv01)} per bp.\n"
        f"You can hedge with the {case.spec.name} future ({case.spec.code}): its DV01 is {fmt_eur(fut_dv01, False)} per contract (CTD-based, a long future is long duration). "
        f"One tick is {fmt_eur(case.spec.tick_value, False)}; the future is one tick wide.\n"
        f"Or you can hedge in the interdealer {tenor}Y swap market, which is {width:g}bp wide. Either way you cross half the spread. The swap spread (swap rate minus the bond yield) has a daily volatility of "
        f"about {sigma:g}bp."
    )
    parts = [
        NumericPart(f"How many {case.spec.code} contracts hedge the DV01? ({verb.capitalize()} = {'negative' if dv01 > 0 else 'positive'})", n, Tolerance(rel=0.03), "contracts",
                    sign_hint="Hedge long duration by selling the future.", note="your DV01 / DV01 per contract"),
        NumericPart("What does the swap hedge cost to execute (EUR)?", swap_cost, Tolerance(rel=0.03), "EUR", note="half the interdealer width x |DV01|"),
        NumericPart("What does the futures hedge cost to execute (EUR)?", fut_cost, Tolerance(rel=0.05), "EUR", note="contracts x half a tick"),
        NumericPart(f"After hedging with futures, the swap spread moves {s:g}bp against you (the swap rate {'rises' if dv01 > 0 else 'falls'} {s:g}bp with bond yields unchanged). "
                    "What is your P&L (EUR)?", basis_pnl, Tolerance(rel=0.05, abs=0.03 * abs(dv01) * s), "EUR", approx=-dv01 * adverse * s,
                    approx_label="-DV01 x swap-rate move", sign_hint="Futures do not move: only the swap leg reprices, and the move is against you."),
        NumericPart("How far can the swap spread move against you before the futures hedge's saving is gone (bp)?", be, Tolerance(rel=0.08, abs=0.01), "bp",
                    note="the saving / |DV01|"),
        shuffled_choice(rng, f"The spread's daily volatility is about {sigma:g}bp. What does that say about hedging with futures?",
                        ["The saving is a small fraction of one day's swap-spread risk: use futures for speed and liquidity, and expect to swap the hedge out or accept the basis",
                         "Futures are always the better hedge because they are cheaper",
                         "Futures should never be used for swaps because they have basis risk",
                         "The swap-spread risk is zero because the future is a hedge of the swap's DV01"],
                        f"A DV01 hedge removes the outright level risk but not the swap-vs-bond spread. The saving ({fmt_eur(saving, False)}) disappears after only {be:.2f}bp of spread move, "
                        f"a small fraction of a {sigma:g}bp daily move. Futures are the quick, liquid, cheap hedge; the basis is the price."),
    ]
    solution = [
        f"Contracts = {fmt_eur(abs(dv01), False)} / {fmt_eur(fut_dv01, False)} = {abs(n):,.0f} ({verb}).",
        f"Swap hedge: {width / 2:g}bp x {fmt_eur(abs(dv01), False)} = {fmt_eur(swap_cost)}. Futures: {abs(n):,.0f} x {fmt_eur(case.spec.tick_value / 2, False)} = {fmt_eur(fut_cost)}. Saving {fmt_eur(saving)}.",
        f"Swap rate {'+' if dv01 > 0 else '-'}{s:g}bp against unchanged bond yields: swap leg {fmt_eur(basis_pnl)} (first order {fmt_eur(-dv01 * adverse * s)}), futures unchanged. "
        f"Break-even spread move {be:.2f}bp.",
        "The trade-off: futures are cheaper and deeper but hedge the bond market, not the swap. A swap hedge costs more and removes the basis. A dealer often hedges "
        "quickly in futures and replaces it with swaps as offsetting client flow arrives.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "case": case, "swap": swap, "dv01": dv01, "fut_dv01": fut_dv01, "n": n, "swap_cost": swap_cost,
                                                 "fut_cost": fut_cost, "saving": saving, "basis_pnl": basis_pnl, "s": s, "be": be, "sigma": sigma})


# ------------------------------------------------------------------------------------------------------------------ events

@template("mm.event_sizing", skill="mm.views_and_events", difficulty=3, kind="calculation")
def event_sizing(rng: random.Random) -> QuestionBody:
    """Risk before a scheduled release: scale inventory to volatility, and count only the part of your view that is not already priced."""
    sigma = rng.choice([3.5, 4.0, 4.5, 5.0])
    k = rng.choice([1.6, 1.8, 2.0, 2.2, 2.5])
    limit = rng.choice([300e3, 400e3, 500e3])
    inv = rng.choice([0.7, 0.8, 0.9]) * limit
    long_ = rng.random() < 0.5
    d0 = inv if long_ else -inv
    view = (-1 if long_ else 1) * rng.choice([2.0, 3.0, 4.0])                       # your expected move on the print, bp: the view agrees with the position (rates down if you are long duration)
    priced = round(view * rng.choice([0.5, 0.6, 0.7, 0.8]), 1)                       # the part the market has already moved
    edge = view - priced
    ev = -d0 * edge                                                                  # P&L = -DV01 x move
    info = abs(edge) / (sigma * k)
    stem = (
        f"The 10Y EUR swap rate has a normal daily volatility of {sigma:g}bp. Tomorrow's flash inflation release is expected to make the day {k:g}x as volatile.\n"
        f"Your DV01 limit is {limit / 1e3:,.0f}k, set for normal days. You are {'long' if long_ else 'short'} {abs(d0) / 1e3:,.0f}k DV01.\n"
        f"Your research view is that the print will push the 10Y {'up' if view > 0 else 'down'} about {abs(view):g}bp. Since this morning the 10Y has already moved "
        f"{abs(priced):g}bp {'up' if priced > 0 else 'down'} (the market has taken part of that view on board)."
    )
    parts = [
        NumericPart("What is a one-standard-deviation daily P&L on your position on a NORMAL day (EUR)?", abs(d0) * sigma, Tolerance(rel=0.03), "EUR", note="|DV01| x daily vol"),
        NumericPart("And tomorrow, on the release day (EUR)?", abs(d0) * sigma * k, Tolerance(rel=0.03), "EUR", note="the same position, a larger move"),
        NumericPart("What DV01 would give tomorrow the SAME one-sigma P&L as a normal day with your current position (EUR per bp)?", abs(d0) / k, Tolerance(rel=0.03), "EUR",
                    note="keep |DV01| x vol constant"),
        NumericPart("What is the expected P&L of your view, counting only the part NOT yet priced (EUR, signed)?", ev, Tolerance(rel=0.05, abs=0.05 * abs(d0)), "EUR",
                    approx=-d0 * view, approx_label="the whole view, ignoring what has already moved", accept_approx=False,
                    sign_hint="Rates up hurts a long-duration position: P&L = -DV01 x move.", note="remaining move = view - already priced"),
        shuffled_choice(rng, f"The remaining expected move is {abs(edge):g}bp against a one-sigma move of {sigma * k:.1f}bp on the day ({info:.2f} sigma). What is sensible?",
                        ["Do not add risk on this view: the edge is small against the day's volatility, so cut towards the volatility-adjusted level unless you can justify more",
                         "Add to the position: the expected P&L is positive, so a larger position earns more",
                         "Hold the limit in DV01 terms: limits are in DV01, not volatility",
                         "Go to the limit: event days pay the biggest profits to those with conviction"],
                        "Positive expected value is not enough: the view's edge is small compared with the day's standard deviation, so the position is dominated by noise. "
                        "Inventory limits set for a normal day are too generous on an event day, and a view that is partly priced is worth less than it feels."),
    ]
    solution = [
        f"Normal-day 1 sigma = {fmt_eur(abs(d0), False)} x {sigma:g} = {fmt_eur(abs(d0) * sigma, False)}; release day = x {k:g} = {fmt_eur(abs(d0) * sigma * k, False)}.",
        f"To keep the same risk: DV01 = {fmt_eur(abs(d0), False)} / {k:g} = {fmt_eur(abs(d0) / k, False)} (your limit, scaled, is {fmt_eur(limit / k, False)}).",
        f"Edge = {view:+g} - ({priced:+g}) = {edge:+g}bp; expected P&L = -DV01 x edge = -({fmt_eur(d0)}) x ({edge:+g}) = {fmt_eur(ev)}. Counting the whole view would give {fmt_eur(-d0 * view)}.",
        f"Edge / sigma = {info:.2f}: the expected gain is a small fraction of one standard deviation. The observable fact is what the market has already done; the view is what "
        "is left, and it is uncertain.",
    ]
    return QuestionBody(stem, parts, solution, {"sigma": sigma, "k": k, "limit": limit, "d0": d0, "view": view, "priced": priced, "edge": edge, "ev": ev, "info": info})


@template("mm.event_repricing", skill="mm.views_and_events", difficulty=3, kind="calculation")
def event_repricing(rng: random.Random) -> QuestionBody:
    """Translate a data surprise into a curve move, a position's P&L, and the outcome you do not want going into the release."""
    for _ in range(200):
        mkt = random_market(rng)
        s = rng.choice([-0.3, -0.2, 0.2, 0.3])                                          # surprise vs consensus, percentage points
        b2, b10 = rng.choice([3.0, 4.0, 5.0]), rng.choice([1.0, 1.5, 2.0])               # bp of rate move per 0.1pp of surprise: the front end reprices more
        m2, m10 = b2 * s / 0.1, b10 * s / 0.1
        n2, n10 = rng.choice([100, 150, 200, 300]) * 1e6, rng.choice([30, 50, 75, 100]) * 1e6
        s2, s10 = rng.choice([Side.RECEIVE, Side.PAY]), rng.choice([Side.RECEIVE, Side.PAY])
        leg2, leg10 = par_irs(s2, n2, 2, mkt), par_irs(s10, n10, 10, mkt)
        book = Portfolio([leg2, leg10])
        shock = CurveShock.points({2.0: m2, 10.0: m10})
        pnl = revalue_pnl(book, mkt, shock)
        opp = revalue_pnl(book, mkt, CurveShock.points({2.0: -m2, 10.0: -m10}))
        d2, d10 = parallel_dv01(leg2, mkt), parallel_dv01(leg10, mkt)
        tol = max(0.06 * abs(pnl), 0.04 * (abs(d2) * abs(m2) + abs(d10) * abs(m10)))
        if abs(pnl) > 2.5 * tol and pnl * opp < 0 and s2 is not s10:
            break
    slope = m10 - m2
    hawkish = s > 0
    hot_pnl, soft_pnl = (pnl, opp) if hawkish else (opp, pnl)
    hurts_hot = hot_pnl < 0
    hot = "hotter" if hawkish else "softer"
    stem = (
        f"Flash euro-area inflation comes in {abs(s):.1f} percentage points {hot} than consensus. Historically each 0.1pp of surprise has moved the 2Y swap rate by about "
        f"{b2:g}bp and the 10Y by about {b10:g}bp, in the direction of the surprise (the front end reprices more).\n"
        f"Your book: {'receive' if s2 is Side.RECEIVE else 'pay'} fixed on {eur_m(n2)} 2Y (DV01 {fmt_eur(d2)}) and {'receive' if s10 is Side.RECEIVE else 'pay'} fixed on {eur_m(n10)} 10Y (DV01 {fmt_eur(d10)})."
    )
    parts = [
        NumericPart("By how much does the 2Y swap rate move on this surprise (bp, signed)?", m2, Tolerance(rel=0.02, abs=0.2), "bp", sign_hint="A hotter print raises rates.", note="beta x surprise / 0.1"),
        NumericPart("By how much does the 2s10s slope (10Y minus 2Y) change (bp, + = steeper)?", slope, Tolerance(rel=0.05, abs=0.3), "bp",
                    sign_hint="The front end moves more: is the curve flattening or steepening?", note="10Y move less 2Y move"),
        NumericPart("What is the P&L on your book (EUR)?", pnl, Tolerance(rel=0.06, abs=0.04 * (abs(d2) * abs(m2) + abs(d10) * abs(m10))), "EUR",
                    approx=-(d2 * m2 + d10 * m10), approx_label="-sum(DV01 x move)", sign_hint="Multiply each leg's DV01 by its own move."),
        shuffled_choice(rng, "Going into the release, which outcome is the risk to this book?",
                        [f"{'A hotter' if hurts_hot else 'A softer'}-than-expected print: the book loses about {fmt_eur(abs(min(hot_pnl, soft_pnl)), False)} on a surprise of this size",
                         f"{'A softer' if hurts_hot else 'A hotter'}-than-expected print: the book loses on this side",
                         "Neither: a surprise cannot hurt a position with offsetting legs",
                         "Both: a DV01-weighted book loses on any surprise"],
                        "The book is a position in the level and the slope of the curve. Work out the P&L for each direction of surprise: one side loses what the other earns, "
                        "to first order. Offsetting legs of different tenors are not offsetting unless the two rates move together."),
    ]
    solution = [
        f"Surprise {s:+.1f}pp = {s / 0.1:+.0f} units of 0.1pp. 2Y: {b2:g} x {s / 0.1:+.0f} = {m2:+.1f}bp. 10Y: {b10:g} x {s / 0.1:+.0f} = {m10:+.1f}bp. "
        f"Slope = {m10:+.1f} - ({m2:+.1f}) = {slope:+.1f}bp: {'bear flattening' if hawkish else 'bull steepening'} ({'rates up, front end most' if hawkish else 'rates down, front end most'}).",
        f"P&L = -[({fmt_eur(d2)} x {m2:+.1f}) + ({fmt_eur(d10)} x {m10:+.1f})] = {fmt_eur(-(d2 * m2 + d10 * m10))} first order; revalued {fmt_eur(pnl)}. "
        f"The opposite surprise gives {fmt_eur(opp)}.",
        "A scheduled release has known timing but unknown direction: you can size the risk (exposure to level and slope) in advance, and you can only hold an opinion on the direction. "
        "The market's reaction function (betas) turns a one-number surprise into a whole-curve move.",
        "Whatever the book looks like in DV01, ask what happens to level and to slope: a DV01-neutral book can still be a large slope position.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "s": s, "m2": m2, "m10": m10, "slope": slope, "pnl": pnl, "opp": opp, "d2": d2, "d10": d10, "book": book})
