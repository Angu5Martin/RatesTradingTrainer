"""Basis templates: IRS vs OIS (Euribor-ESTR) and 3M vs 6M tenor basis."""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import first_order_pnl, revalue_pnl
from ...engine.risk import Portfolio, dv01_hedge_swap, key_rate_dv01, par_basis, par_irs, parallel_dv01
from ..market import curve_line, eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template
from .swaps import NOTIONALS_M, TENORS


@template("basis.irs_vs_ois", skill="swaps.ois_vs_ibor", difficulty=2)
def irs_vs_ois(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    tenor = rng.choice(TENORS)
    notional = rng.choice(NOTIONALS_M) * 1e6
    irs_side = rng.choice(list(Side))
    move = rng.choice([-3, -2, -1.5, 1.5, 2, 3])
    irs = par_irs(irs_side, notional, tenor, mkt)
    irs_dv01 = parallel_dv01(irs, mkt)
    ois = dv01_hedge_swap(irs_dv01, tenor, mkt, kind="OIS")       # opposite direction, DV01-neutral
    book = Portfolio([irs, ois])
    spread_bp = (irs.fixed_rate - ois.fixed_rate) * 1e4

    pnl_widen = revalue_pnl(book, mkt, CurveShock.parallel(move), curves=("E6M",))   # IRS rate moves, OIS does not
    approx = first_order_pnl(irs_dv01, move)
    parallel_pnl = revalue_pnl(book, mkt, CurveShock.parallel(5))
    irs_verb, ois_verb = (("receive", "pay") if irs_side is Side.RECEIVE else ("pay", "receive"))
    short_spread = irs_side is Side.RECEIVE      # receive IRS / pay OIS profits when IRS rates FALL vs OIS

    stem = (
        f"EUR curves, {tenor}Y: IRS (6M Euribor) {pct(irs.fixed_rate)}, ESTR OIS {pct(ois.fixed_rate)} "
        f"(IRS - OIS = {spread_bp:+.1f}bp; part of this is accrual convention: OIS is ACT/360, the IRS fixed leg 30E/360).\n"
        f"You {irs_verb} fixed on {eur_m(notional)} {tenor}Y IRS and {ois_verb} fixed on {eur_m(ois.notional)} {tenor}Y OIS, "
        f"sized to be DV01-neutral. 'The IRS-OIS spread' means IRS rate minus OIS rate."
    )
    parts = [
        shuffled_choice(
            rng, "Which describes the position?",
            [f"{'Short' if short_spread else 'Long'} the IRS-OIS spread: it gains if the spread {'narrows' if short_spread else 'widens'}",
             f"{'Long' if short_spread else 'Short'} the IRS-OIS spread: it gains if the spread {'widens' if short_spread else 'narrows'}",
             "Flat risk: it is DV01-neutral so no market move matters",
             "Directional: it gains if rates fall regardless of the spread"],
            "Paying fixed in the IRS (and receiving OIS) gains when the IRS rate rises against OIS: long the spread. "
            "Receiving the IRS and paying OIS is the opposite: short the spread."),
        NumericPart(f"The IRS rate moves {move:+g}bp but the OIS rate does not (spread {'widens' if move > 0 else 'narrows'}). "
                    "What is your P&L?", pnl_widen, Tolerance(rel=0.04), "EUR", approx=approx,
                    sign_hint="Only the IRS leg moves; the OIS leg has no move."),
        shuffled_choice(rng, "Instead both curves rise 5bp together. What is your P&L?",
                        ["About zero: DV01-neutral and the spread is unchanged",
                         "Positive if you are long the spread", "Negative if you are short the spread",
                         f"About {fmt_eur(5 * abs(irs_dv01), False)}"],
                        f"A parallel move is hedged out; what is left is spread risk. Exact: {fmt_eur(parallel_pnl)}."),
    ]
    solution = [
        f"The IRS DV01 is {fmt_eur(irs_dv01)}/bp; the OIS leg ({eur_m(ois.notional)}, {fmt_eur(parallel_dv01(ois, mkt))}/bp) offsets it.",
        f"A move of the IRS rate alone is a move in the spread: first-order {fmt_eur(approx)} (= -({move:+g}) x {fmt_eur(irs_dv01)}); "
        f"full revaluation {fmt_eur(pnl_widen)}.",
        "IRS-OIS is the Euribor-ESTR basis. It widens when term/credit premium in Euribor rises vs overnight funding.",
        "Because the OIS notional differs slightly from the IRS notional for the same DV01, 'equal notional' is NOT quite DV01-neutral "
        "(ACT/360 vs 30E/360 accrual).",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "irs": irs, "ois": ois, "book": book, "move": move,
                                                 "approx": approx, "irs_dv01": irs_dv01})


@template("basis.tenor_3s6s", skill="swaps.basis", difficulty=2)
def tenor_basis_3s6s(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    tenor = rng.choice([2, 3, 5, 7, 10, 15, 20, 30])
    notional = rng.choice(NOTIONALS_M) * 1e6
    side = rng.choice(list(Side))
    move = rng.choice([-3, -2, -1, 1, 2, 3])
    swap = par_basis(side, notional, tenor, mkt)
    key = ("BASIS_3S6S", round(tenor * 12))
    basis_dv01 = key_rate_dv01(swap, mkt, curves=("BASIS_3S6S",))[key]     # per 1bp FALL in the spread
    pnl = swap.pv(mkt.bumped("BASIS_3S6S", key[1], move)) - swap.pv(mkt)
    approx = first_order_pnl(basis_dv01, move)
    long_basis = side is Side.PAY
    desc = "pay 3M Euribor + spread and receive 6M Euribor" if long_basis else "receive 3M Euribor + spread and pay 6M Euribor"
    rate_dv01 = parallel_dv01(swap, mkt)

    stem = (
        f"EUR {tenor}Y 3s6s basis swap: the market spread is {swap.spread * 1e4:.1f}bp (3M Euribor + spread vs 6M Euribor flat).\n"
        f"You {desc} on {eur_m(notional)} at the market spread. "
        "Convention: 'long the basis' = pay the spread leg, so you gain when the 3s6s spread widens."
    )
    parts = [
        shuffled_choice(
            rng, "What is your position?",
            [f"{'Long' if long_basis else 'Short'} the basis: gains if the spread {'widens' if long_basis else 'narrows'}",
             f"{'Short' if long_basis else 'Long'} the basis: gains if the spread {'narrows' if long_basis else 'widens'}",
             "Long duration: gains if rates fall", "Short duration: gains if rates rise"],
            "You pay a fixed spread: like paying a fixed rate, you gain when the market level of that spread rises above yours."
            if long_basis else
            "You receive a fixed spread: like receiving a fixed rate, you gain when the market level falls below yours."),
        NumericPart(f"The {tenor}Y 3s6s spread {'widens' if move > 0 else 'narrows'} by {abs(move)}bp (rates unchanged). "
                    "What is your P&L?", pnl, Tolerance(rel=0.04), "EUR", approx=approx,
                    sign_hint="Long the basis gains when the spread widens; short gains when it narrows.",
                    note="spread move x notional x 3M-leg annuity"),
    ]
    solution = [
        f"Spread sensitivity ≈ N x 1bp x annuity of the 3M leg: {fmt_eur(abs(basis_dv01), False)} per bp (about the size of a "
        f"{tenor}Y swap's DV01 for the same notional).",
        f"You are {'long' if long_basis else 'short'} the basis, so P&L ≈ {'+' if long_basis else '-'} (spread change) x {fmt_eur(abs(basis_dv01), False)} "
        f"= {fmt_eur(approx)}; full revaluation {fmt_eur(pnl)}.",
        f"Its exposure to outright rates is small: parallel DV01 only {fmt_eur(rate_dv01)} vs {fmt_eur(abs(basis_dv01), False)} per bp of spread. "
        "A basis swap is almost pure spread risk.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "swap": swap, "move": move, "pnl": pnl, "approx": approx,
                                                 "basis_dv01": basis_dv01, "long_basis": long_basis})
