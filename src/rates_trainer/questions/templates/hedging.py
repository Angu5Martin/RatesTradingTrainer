"""Hedge-ratio templates."""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import first_order_pnl, revalue_pnl
from ...engine.risk import Portfolio, dv01_hedge_swap, par_irs, parallel_dv01, unit_dv01
from ..market import curve_line, eur_m, pct, random_market
from ..model import ChoicePart, NumericPart, QuestionBody, Tolerance, fmt_eur
from ..registry import template
from .swaps import NOTIONALS_M, TENORS


@template("hedging.swap_swap", skill="risk.hedge_ratio", difficulty=2)
def swap_swap_hedge(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    trade_t, hedge_t = rng.sample(TENORS, 2)
    side = rng.choice(list(Side))
    notional = rng.choice(NOTIONALS_M) * 1e6
    trade = par_irs(side, notional, trade_t, mkt)
    dv01 = parallel_dv01(trade, mkt)
    hedge = dv01_hedge_swap(dv01, hedge_t, mkt)
    book = Portfolio([trade, hedge])
    move = rng.choice([-5, -4, -3, -2, 2, 3, 4, 5])
    shock = CurveShock.points({float(hedge_t): 0.0, float(trade_t): float(move)})
    pnl = revalue_pnl(book, mkt, shock)
    approx = first_order_pnl(dv01, move)          # only the trade's tenor moved; the hedge leg has no move
    verb = "receive" if side is Side.RECEIVE else "pay"
    hedge_verb = "pay" if hedge.side is Side.PAY else "receive"
    per_million = unit_dv01(hedge_t, mkt)

    stem = (
        f"EUR IRS curve: {curve_line(mkt, sorted({2, 5, 10, 30, trade_t, hedge_t}))}\n"
        f"You {verb} fixed on {eur_m(notional)} {trade_t}Y IRS (struck at the market, {pct(trade.fixed_rate)}). "
        f"You want to hedge the parallel DV01 with an at-market {hedge_t}Y IRS."
    )
    parts = [
        ChoicePart(f"In the {hedge_t}Y hedge, do you pay or receive fixed?", ["Pay fixed", "Receive fixed"],
                   0 if hedge.side is Side.PAY else 1,
                   f"Your position is {'long' if dv01 > 0 else 'short'} duration; the hedge must be "
                   f"{'short' if dv01 > 0 else 'long'} duration."),
        NumericPart(f"What {hedge_t}Y notional makes the book DV01-neutral?", hedge.notional,
                    Tolerance(rel=0.04), "EUR", note="e.g. 480m"),
        NumericPart(f"Hedged. Now the {trade_t}Y swap rate moves {move:+d}bp while the {hedge_t}Y rate is unchanged. "
                    "What is the P&L of the two-leg book?", pnl, Tolerance(rel=0.05), "EUR", approx=approx,
                    sign_hint="Only your trade's leg has moved, the hedge leg has not."),
    ]
    solution = [
        f"Trade DV01 = {fmt_eur(dv01)}/bp. Hedge DV01 per €1m {hedge_t}Y = {fmt_eur(per_million, False)}.",
        f"Hedge notional = |trade DV01| / DV01 per €1m = {eur_m(hedge.notional)} (to {hedge_verb} fixed).",
        f"Notional is {'larger' if hedge.notional > notional else 'smaller'} than {eur_m(notional)} because a {hedge_t}Y swap has "
        f"{'less' if hedge.notional > notional else 'more'} DV01 per euro than a {trade_t}Y.",
        f"DV01-neutral is not risk-free: the book is flat to PARALLEL moves but carries {min(trade_t, hedge_t)}s{max(trade_t, hedge_t)}s curve risk. "
        f"Each at-market swap's P&L depends only on its own swap rate, so the book makes about {fmt_eur(approx)} "
        f"(= -({move:+d}) x {fmt_eur(dv01)}); full revaluation {fmt_eur(pnl)}.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "trade": trade, "hedge": hedge, "move": move,
                                                 "dv01": dv01, "approx": approx})
