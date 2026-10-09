"""Curve-trade templates (steepeners / flatteners)."""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import first_order_pnl, revalue_pnl
from ...engine.risk import Portfolio, dv01_hedge_swap, par_irs, parallel_dv01
from ..market import curve_line, eur_m, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template

PAIRS = ((2, 10), (5, 10), (2, 5), (5, 30), (10, 30), (2, 30), (3, 7), (7, 15))
LEG_NOTIONALS_M = (25, 50, 75, 100, 150, 200)


@template("curves.curve_trade", skill="curve.steepener", difficulty=3)
def curve_trade(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    short_t, long_t = rng.choice(PAIRS)
    steepener = rng.random() < 0.5
    n_long = rng.choice(LEG_NOTIONALS_M) * 1e6
    name = f"{short_t}s{long_t}s {'steepener' if steepener else 'flattener'}"

    # Steepener: profit if (long - short) widens => receive short end, pay long end.
    long_side = Side.PAY if steepener else Side.RECEIVE
    short_side = long_side.opposite
    long_leg = par_irs(long_side, n_long, long_t, mkt)
    long_dv01 = parallel_dv01(long_leg, mkt)
    short_leg = dv01_hedge_swap(long_dv01, short_t, mkt)
    assert short_leg.side is short_side
    short_dv01 = parallel_dv01(short_leg, mkt)
    book = Portfolio([long_leg, short_leg])

    a = rng.choice([-8, -6, -5, -4, -3, -2, 0, 2, 3, 4, 5, 6, 8])    # short-end move, bp
    b = rng.choice([-8, -6, -5, -4, -3, -2, 0, 2, 3, 4, 5, 6, 8])    # long-end move, bp
    while abs(b - a) < 2:
        b = rng.choice([-8, -6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 8])
    shock = CurveShock.points({float(short_t): float(a), float(long_t): float(b)})
    pnl = revalue_pnl(book, mkt, shock)
    approx = first_order_pnl(short_dv01, a) + first_order_pnl(long_dv01, b)
    par_pnl = revalue_pnl(book, mkt, CurveShock.parallel(10))
    leg_pnl_10 = abs(long_dv01) * 10

    def legs(s_side: Side, l_side: Side) -> str:
        w = {Side.PAY: "pay", Side.RECEIVE: "receive"}
        return f"{w[s_side].capitalize()} {short_t}Y / {w[l_side]} {long_t}Y"

    options = [legs(short_side, long_side), legs(short_side.opposite, long_side.opposite),
               legs(Side.RECEIVE, Side.RECEIVE), legs(Side.PAY, Side.PAY)]
    stem = (
        f"EUR IRS curve: {curve_line(mkt, sorted({2, 5, 10, 30, short_t, long_t}))}\n"
        f"You want a DV01-neutral {name}. A steepener profits when the {short_t}s{long_t}s spread "
        f"(long-end rate minus short-end rate) widens; a flattener when it narrows.\n"
        f"The {long_t}Y leg is {eur_m(n_long)}. Both legs are at-market IRS."
    )
    parts = [
        shuffled_choice(rng, f"Which legs make a {name}?", options,
                        "Steepener = long the spread: pay the long end (profits if it sells off) and receive the short end. "
                        "Flattener is the reverse."),
        NumericPart(f"What {short_t}Y notional makes the trade DV01-neutral?", short_leg.notional,
                    Tolerance(rel=0.04), "EUR", note="e.g. 420m"),
        NumericPart(f"The {short_t}Y rate moves {a:+d}bp and the {long_t}Y rate moves {b:+d}bp. What is the P&L?", pnl,
                    Tolerance(rel=0.05, abs=abs(long_dv01) * (0.03 + 0.01 * max(abs(a), abs(b)))), "EUR", approx=approx,
                    sign_hint="Check each leg separately: which direction does it gain?"),
        shuffled_choice(rng, "The whole curve instead rises 10bp in parallel. What is the P&L?",
                        ["About zero: DV01-neutral, only a small convexity residual",
                         "Positive: the trade benefits from higher rates",
                         "Negative: the trade loses from higher rates",
                         f"About {fmt_eur(leg_pnl_10, False)}: the long-end leg's P&L"],
                        f"A curve trade expresses a view on the SPREAD. The legs offset in a parallel move "
                        f"(exact residual: {fmt_eur(par_pnl)} vs ~{fmt_eur(leg_pnl_10, False)} on each leg)."),
    ]
    solution = [
        f"{name}: {legs(short_side, long_side)}.",
        f"{long_t}Y leg DV01 = {fmt_eur(long_dv01)}; {short_t}Y DV01 per €1m is "
        f"{fmt_eur(abs(short_dv01) / short_leg.notional * 1e6, False)} => notional {eur_m(short_leg.notional)}.",
        f"Each leg's P&L depends on its own rate: {long_t}Y leg {fmt_eur(first_order_pnl(long_dv01, b))}, "
        f"{short_t}Y leg {fmt_eur(first_order_pnl(short_dv01, a))} => first-order total {fmt_eur(approx)}; "
        f"full revaluation {fmt_eur(pnl)}.",
        f"Spread {'widened' if b - a > 0 else 'narrowed'} by {abs(b - a)}bp; "
        f"net P&L ~ {'' if steepener else '-'}(spread change {b - a:+d}bp) x |DV01| {fmt_eur(abs(long_dv01), False)}.",
        "Note that a steepener can lose money while the market is rallying hard, or make money in a sell-off: "
        "what matters is the spread move, not the direction of rates.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "long_leg": long_leg, "short_leg": short_leg, "a": a, "b": b,
                                                 "steepener": steepener, "short_t": short_t, "long_t": long_t,
                                                 "approx": approx})
