"""Swap DV01 / P&L, forward-start swaps and FRAs."""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import first_order_pnl, revalue_pnl
from ...engine.risk import par_fra, par_irs, par_ois, parallel_dv01
from ..market import curve_line, eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template

TENORS = (2, 3, 5, 7, 10, 15, 20, 30)           # years; all are quoted pillars
NOTIONALS_M = (25, 50, 75, 100, 150, 200, 250, 300, 500)
DV01_CONVENTION = "DV01 = P&L for a 1bp FALL in rates (positive if long duration, negative if short)."


@template("swaps.dv01_pnl", skill="swaps.dv01", difficulty=1)
def swap_dv01_pnl(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    kind = rng.choice(["IRS", "IRS", "OIS"])
    make, curve_name, label = ((par_irs, "E6M", "EUR IRS (vs 6M Euribor)") if kind == "IRS"
                               else (par_ois, "OIS", "EUR ESTR OIS"))
    side = rng.choice(list(Side))
    tenor = rng.choice(TENORS)
    notional = rng.choice(NOTIONALS_M) * 1e6
    move = rng.choice([-8, -6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 8])
    swap = make(side, notional, tenor, mkt)

    dv01 = parallel_dv01(swap, mkt)
    pnl = revalue_pnl(swap, mkt, CurveShock.parallel(move))
    approx = first_order_pnl(dv01, move)
    annuity = swap.annuity(mkt)
    verb = "receive" if side is Side.RECEIVE else "pay"

    stem = (
        f"{label} curve: {curve_line(mkt, curve=curve_name)}\n"
        f"You {verb} fixed on a {eur_m(notional)} {tenor}Y {label}, struck at the market rate ({pct(swap.fixed_rate)}).\n"
        f"{DV01_CONVENTION}"
    )
    parts = [
        NumericPart("What is the DV01 of the position?", dv01, Tolerance(rel=0.04), "EUR",
                    sign_hint="Receiving fixed is long duration (+); paying fixed is short duration (-).",
                    note="e.g. -215k"),
        NumericPart(f"The whole swap curve now moves {move:+d}bp in parallel. What is your P&L?", pnl,
                    Tolerance(rel=0.04), "EUR", approx=approx,
                    sign_hint="Does this position gain or lose when rates move this way?", note="e.g. 340k"),
    ]
    solution = [
        f"DV01 per unit = annuity x 1bp. The {tenor}Y annuity (PV of the fixed leg per 1 of rate) is about {annuity:.2f}.",
        f"|DV01| = {eur_m(notional)} x {annuity:.2f} x 0.0001 = {fmt_eur(abs(dv01), False)} (about €{abs(dv01) / notional * 1e6:,.0f} per €1m).",
        f"Sign: you {verb} fixed, so DV01 is {'positive (long duration)' if side is Side.RECEIVE else 'negative (short duration)'}: {fmt_eur(dv01)} per bp.",
        f"First-order P&L = -DV01 x move = -({fmt_eur(dv01)}) x ({move:+d}) = {fmt_eur(approx)}. "
        f"Full revaluation gives {fmt_eur(pnl)}; the difference ({fmt_eur(pnl - approx)}) is convexity.",
        "Habit to build (DV01 per €1m, rates 1.5-4%): 2Y ~ €190-200, 5Y ~ €450-480, 10Y ~ €820-920, 30Y ~ €1,750-2,400. "
        "OIS annuities are ~1.4% larger than IRS ones (ACT/360 vs 30E/360 accrual).",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "swap": swap, "move": move, "dv01": dv01, "approx": approx})


_FORWARD_PAIRS = ((2, 5), (3, 5), (5, 7), (5, 10), (7, 10), (5, 15), (10, 20), (10, 15), (3, 10), (2, 10))


@template("swaps.forward_start", skill="swaps.forward_start", difficulty=2)
def forward_start_rate(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    a, b = rng.choice(_FORWARD_PAIRS)
    sa, sb = par_irs(Side.RECEIVE, 1.0, a, mkt), par_irs(Side.RECEIVE, 1.0, b, mkt)
    fwd = par_irs(Side.RECEIVE, 1.0, b - a, mkt, start_years=a)
    # what a screen shows: PV01 (annuity) rounded to 2dp; the answer uses the same rounded numbers
    aa, ab = round(sa.annuity(mkt), 2), round(sb.annuity(mkt), 2)
    exact = (sb.par_rate(mkt) * ab - sa.par_rate(mkt) * aa) / (ab - aa)
    naive = (b * sb.par_rate(mkt) - a * sa.par_rate(mkt)) / (b - a)
    name = f"{a}y{b - a}y"

    stem = (
        f"EUR IRS (6M Euribor) par rates and annuities (PV of 1 per year of fixed payments):\n"
        f"  {a}Y: {pct(sa.par_rate(mkt))}  annuity {aa:.2f}\n"
        f"  {b}Y: {pct(sb.par_rate(mkt))}  annuity {ab:.2f}\n"
        f"A forward-starting swap {name} starts in {a} years and runs {b - a} years, so spot {a}Y + {name} = spot {b}Y."
    )
    parts = [
        NumericPart(f"What is the {name} forward swap rate (in %)?", fwd.par_rate(mkt) * 100,
                    Tolerance(rel=0, abs=0.03), "%", note="weight by annuities, not by years", approx=naive * 100,
                    approx_label=f"naive year-weighting ({b}xS{b} - {a}xS{a})/{b - a}", accept_approx=False),
    ]
    steeper = fwd.par_rate(mkt) > sb.par_rate(mkt)
    parts.append(shuffled_choice(
        rng, f"Is the {name} forward rate above or below the spot {b}Y rate?",
        ["Above" if steeper else "Below", "Below" if steeper else "Above"],
        "The forward covers only the later, higher-yielding part of the curve." if steeper
        else "The forward covers only the later part of an inverted/falling section of the curve."))
    solution = [
        f"Fixed and floating legs are both additive: S{b} x A{b} = S{a} x A{a} + F x A({a}y{b - a}y), where A({name}) = A{b} - A{a} = {ab - aa:.2f}.",
        f"F = ({pct(sb.par_rate(mkt), 4)} x {ab:.2f} - {pct(sa.par_rate(mkt), 4)} x {aa:.2f}) / {ab - aa:.2f} = {exact * 100:.3f}%  "
        f"(engine, full schedule: {fwd.par_rate(mkt) * 100:.3f}%).",
        f"Naive year-weighting gives {naive * 100:.3f}%: it is off by {(fwd.par_rate(mkt) - naive) * 1e4:+.1f}bp because later "
        f"payments are discounted, so the later swap carries less annuity than its years suggest.",
        "Forward rate above spot = the curve slopes up through that region; a long-dated forward is the market's price for the later years only.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "a": a, "b": b, "fwd": fwd, "exact": exact, "naive": naive,
                                                 "aa": aa, "ab": ab})


@template("swaps.fra_dv01_pnl", skill="swaps.fra", difficulty=2)
def fra_dv01_pnl(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    start, end = rng.choice([(3, 6), (6, 9), (6, 12), (3, 9), (9, 15), (12, 18)])
    side = rng.choice(list(Side))
    notional = rng.choice([100, 200, 250, 500, 1000]) * 1e6
    move = rng.choice([-10, -8, -5, -4, 4, 5, 8, 10])
    fra = par_fra(side, notional, start, end, mkt)
    dv01 = parallel_dv01(fra, mkt)
    pnl = revalue_pnl(fra, mkt, CurveShock.parallel(move))
    approx = first_order_pnl(dv01, move)
    tau = (fra.period.end - fra.period.start).days / 360
    verb = "receive" if side is Side.RECEIVE else "pay"
    idx = "3M" if end - start == 3 else "6M"

    stem = (
        f"You {verb} the fixed rate on a {eur_m(notional)} {start}x{end} FRA on {idx} Euribor, struck at the market "
        f"forward rate ({pct(fra.rate, 3)}). The accrual period is {end - start} months (about {tau:.3f} on ACT/360).\n"
        f"{DV01_CONVENTION}"
    )
    parts = [
        NumericPart("What is the DV01 of the FRA?", dv01, Tolerance(rel=0.10), "EUR",
                    sign_hint="Receiving the FRA rate is long duration (+); paying it is short (-).",
                    note="notional x accrual x 1bp, a few % less"),
        NumericPart(f"All rates move {move:+d}bp in parallel. What is your P&L?", pnl, Tolerance(rel=0.10), "EUR",
                    approx=approx, sign_hint="A FRA payer gains when rates rise; the receiver gains when they fall."),
    ]
    if (start, end) == (6, 12):
        parts.append(shuffled_choice(
            rng, f"Which pair of swaps, sized DV01-neutral, hedges the {verb}-fixed 6x12 FRA?",
            ["Pay fixed 12M / receive fixed 6M" if side is Side.RECEIVE else "Receive fixed 12M / pay fixed 6M",
             "Receive fixed 12M / pay fixed 6M" if side is Side.RECEIVE else "Pay fixed 12M / receive fixed 6M",
             "Receive fixed in both", "Pay fixed in both"],
            "A 6x12 FRA is exposure to the 6M rate 6 months forward = the 12M swap minus the 6M swap. To hedge it, "
            "take the opposite: the 12M swap and the 6M swap in opposite directions, so the first six months cancel."))
    solution = [
        f"Accrual τ ≈ {tau:.4f}. Naive DV01 = N x τ x 1bp = {fmt_eur(abs(notional * tau * 1e-4), False)}. The engine gives "
        f"{fmt_eur(abs(dv01), False)} ({abs(dv01) / (notional * tau * 1e-4) * 100:.0f}% of that) because (i) the payoff is discounted "
        f"and divided by (1 + Fτ), and (ii) a 1bp move in 30E/360 par swap rates is only ~0.986bp on an ACT/360 forward. "
        f"You {verb}, so the sign is {'+' if dv01 > 0 else '-'}.",
        f"First-order P&L = -DV01 x move = {fmt_eur(approx)}; full revaluation {fmt_eur(pnl)} (FRAs have almost no convexity).",
        "A FRA's DV01 is small relative to a swap of equal notional: it only has one accrual period of risk. "
        "FRA DV01 per €1m ≈ €50 for a 6M period, €25 for a 3M period.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "fra": fra, "move": move, "dv01": dv01, "approx": approx})
