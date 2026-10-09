"""Market making: a client trade becomes a position, a risk, an edge, a hedge and a P&L."""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import first_order_pnl, revalue_pnl
from ...engine.risk import Portfolio, dv01_hedge_swap, parallel_dv01
from ...marketmaking.quoting import BP, ClientAction, Quote
from ..market import curve_line, eur_m, pct, random_market
from ..model import ChoicePart, NumericPart, QuestionBody, Tolerance, fmt_eur
from ..registry import template

# Plausible bid/offer HALF-widths (bp) by tenor: wider further out the curve.
HALF_WIDTHS = {2: (0.1, 0.2), 5: (0.1, 0.2), 7: (0.2, 0.3), 10: (0.2, 0.3),
               15: (0.3, 0.4), 20: (0.3, 0.4), 30: (0.4, 0.5)}
ALL_TENORS = (2, 3, 5, 7, 10, 15, 20, 30)


@template("mm.client_trade_risk", skill="mm.client_trade", difficulty=3)
def client_trade_risk(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    tenor = rng.choice(list(HALF_WIDTHS))
    w = rng.choice(HALF_WIDTHS[tenor])
    mid = mkt.quotes["E6M"][tenor * 12]
    quote = Quote(round(mid - w * BP, 7), round(mid + w * BP, 7))
    action = rng.choice(list(ClientAction))
    notional = rng.choice([50, 100, 150, 200, 250, 300, 500]) * 1e6

    swap = quote.dealer_swap(action, notional, mkt, tenor)
    dv01 = parallel_dv01(swap, mkt)
    edge = swap.pv(mkt)  # PV at mid of a swap struck at the client's (worse) rate

    i = ALL_TENORS.index(tenor)
    hedge_t = rng.choice([h for j, h in enumerate(ALL_TENORS) if h != tenor and abs(j - i) <= 2])
    hedge = dv01_hedge_swap(dv01, hedge_t, mkt)
    hedge_signed = hedge.notional if hedge.side is Side.RECEIVE else -hedge.notional
    book = Portfolio([swap, hedge])

    m1 = rng.choice([-8, -6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 8])
    total_unhedged = swap.pv(mkt.shifted(CurveShock.parallel(m1)))
    total_approx = edge + first_order_pnl(dv01, m1)
    m2 = rng.choice([-5, -4, -3, -2, 2, 3, 4, 5])
    shock2 = CurveShock.points({float(hedge_t): 0.0, float(tenor): float(m2)})
    resid = revalue_pnl(book, mkt, shock2)
    resid_approx = first_order_pnl(dv01, m2)

    pays = action is ClientAction.PAYS
    held = "Receive fixed (long duration)" if swap.side is Side.RECEIVE else "Pay fixed (short duration)"
    stem = (
        f"EUR IRS curve: {curve_line(mkt, sorted({2, 5, 10, 30, tenor, hedge_t}))}\n"
        f"Your {tenor}Y market is {pct(quote.bid)} / {pct(quote.offer)} (bid / offer, mid {pct(mid)}).\n"
        f"Convention: you PAY fixed at your bid and RECEIVE fixed at your offer. DV01 is positive when long duration.\n"
        f"A client {action.value} fixed on {eur_m(notional)}."
    )
    parts = [
        ChoicePart("What position are you now holding?",
                   ["Receive fixed (long duration)", "Pay fixed (short duration)"],
                   0 if swap.side is Side.RECEIVE else 1,
                   f"The client {action.value} fixed, so they trade on your {'offer' if pays else 'bid'} "
                   f"({pct(quote.client_rate(action))}) and you {'receive' if pays else 'pay'} fixed."),
        NumericPart("What is the DV01 of the position?", dv01, Tolerance(rel=0.04), "EUR",
                    sign_hint="Receive fixed = long duration (+); pay fixed = short duration (-).", note="e.g. -265k"),
        NumericPart("Mark the trade to mid immediately. What is your P&L (the spread you captured)?", edge,
                    Tolerance(rel=0.05), "EUR", note="half-spread x DV01"),
        NumericPart(f"You hedge with an at-market {hedge_t}Y IRS at mid (ignore hedging costs). What notional? "
                    "(+ = receive fixed, - = pay fixed)", hedge_signed, Tolerance(rel=0.04), "EUR",
                    sign_hint="Hedge long duration by paying fixed (negative); hedge short duration by receiving (positive).",
                    note="e.g. -480m"),
        NumericPart(f"Instead you do NOT hedge and the whole curve moves {m1:+d}bp. What is your total P&L since the client trade "
                    "(including the spread captured)?", total_unhedged, Tolerance(rel=0.05), "EUR",
                    approx=total_approx, approx_label="spread captured + (-DV01 x move)",
                    sign_hint="Spread captured is always positive; the market move can be either sign."),
        NumericPart(f"You are hedged. The {tenor}Y rate then moves {m2:+d}bp while the {hedge_t}Y rate is unchanged. "
                    "What is the P&L from the move (excluding the spread already captured)?", resid,
                    Tolerance(rel=0.05), "EUR", approx=resid_approx,
                    sign_hint="Only the leg whose rate moved makes or loses money."),
    ]
    per_bp = abs(dv01)
    solution = [
        f"Client {action.value} fixed => trades at your {'offer' if pays else 'bid'} {pct(quote.client_rate(action))}; "
        f"you {'receive' if pays else 'pay'} fixed: {held}.",
        f"DV01 = {fmt_eur(dv01)}/bp (≈ notional x annuity x 1bp, annuity ≈ {swap.annuity(mkt):.2f}).",
        f"Edge = half-width {w:.1f}bp x |DV01| {fmt_eur(per_bp, False)} = {fmt_eur(edge)}. This is your whole cushion: a "
        f"{w:.1f}bp adverse move wipes it out.",
        f"Hedge DV01 {fmt_eur(-dv01)}: {eur_m(hedge.notional)} {hedge_t}Y, {'pay' if hedge.side is Side.PAY else 'receive'} fixed "
        f"({'larger' if hedge.notional > notional else 'smaller'} than the {eur_m(notional)} trade because the {hedge_t}Y has "
        f"{'less' if hedge.notional > notional else 'more'} DV01 per euro). Hedging at mid is optimistic: really you cross "
        f"half the {hedge_t}Y bid/offer, which eats into the edge.",
        f"Unhedged: edge {fmt_eur(edge)} + move {fmt_eur(first_order_pnl(dv01, m1))} ≈ {fmt_eur(total_approx)} first-order; "
        f"full revaluation {fmt_eur(total_unhedged)}.",
        f"Hedged but with a {min(tenor, hedge_t)}s{max(tenor, hedge_t)}s curve mismatch: only the {tenor}Y leg moves, "
        f"P&L ≈ -DV01 x move = -({fmt_eur(dv01)}) x ({m2:+d}) = {fmt_eur(resid_approx)}; full revaluation {fmt_eur(resid)}. "
        "A DV01 hedge is not a risk-free hedge.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "quote": quote, "action": action, "swap": swap, "hedge": hedge,
                                                 "m1": m1, "m2": m2, "w": w, "mid": mid, "edge": edge,
                                                 "total_approx": total_approx, "resid_approx": resid_approx})
