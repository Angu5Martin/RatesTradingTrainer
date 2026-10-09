"""Swap spreads in numbers: the spread, how it moves when the bond and the swap move differently, and the P&L of the DV01-matched package."""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side, bond_modified_duration, bond_price
from ...engine.pnl import revalue_pnl
from ...engine.risk import dv01_hedge_swap
from ..market import eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template


@template("rv.swap_spread_pnl", skill="rv.swap_spread", difficulty=2, kind="calculation")
def swap_spread_pnl(rng: random.Random) -> QuestionBody:
    """Swap spread = swap rate minus bond yield. Long the bond and pay a DV01-matched swap is long the spread: it earns the change in it."""
    for _ in range(300):
        mkt = random_market(rng)
        years = rng.choice([5, 10, 30])
        swap_rate = round(mkt.quotes["E6M"][years * 12], 5)
        s0 = rng.choice([-1, 1, 1]) * rng.choice([8, 12, 18, 25, 32, 40])                 # bp: swap rate minus bond yield
        y_b = round(swap_rate - s0 * 1e-4, 5)
        coupon = max(0.0, round(y_b / 0.0025) * 0.0025)
        dy_b = float(rng.choice([-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]))
        dy_s = float(rng.choice([-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]))
        change = dy_s - dy_b
        if abs(change) >= 3 and y_b > 0.002:
            break
    face = rng.choice([25, 50, 100, 200]) * 1e6
    price = bond_price(coupon, years, y_b)
    md = bond_modified_duration(coupon, years, y_b)
    bond_dv01 = face * price / 100.0 * md * 1e-4
    swap = dv01_hedge_swap(bond_dv01, years, mkt)                                         # long bond (positive DV01) -> pay fixed
    assert swap.side is Side.PAY
    book_swap_pnl = revalue_pnl(swap, mkt, CurveShock.parallel(dy_s))
    bond_pnl = face * (bond_price(coupon, years, y_b + dy_b * 1e-4) - price) / 100.0
    pnl = bond_pnl + book_swap_pnl
    s1 = s0 + change
    approx = bond_dv01 * change
    stem = (
        f"Swap spread = {years}Y swap rate minus {years}Y government bond yield (both annual).\n"
        f"The swap rate is {pct(swap_rate, 3)} and the bond yields {pct(y_b, 3)} (price {price:.3f}, modified duration {md:.2f}). You own {eur_m(face)} face of the bond, DV01 {fmt_eur(bond_dv01, False)} per bp, "
        f"and pay fixed on a {years}Y swap sized to the same DV01 (notional {eur_m(swap.notional)}).\n"
        f"Then the bond yield moves {dy_b:+g}bp and the swap rate {dy_s:+g}bp."
    )
    parts = [
        NumericPart("What is the swap spread now (bp, swap rate minus bond yield)?", s0, Tolerance(rel=0.02, abs=0.2), "bp", sign_hint="Swap rate minus bond yield: a bond that yields MORE than the swap gives a negative spread."),
        NumericPart("What is the swap spread after the moves (bp)?", s1, Tolerance(rel=0.02, abs=0.2), "bp", note="old spread + swap move - bond move"),
        NumericPart("What is the P&L of the package, bond plus swap (EUR)?", pnl, Tolerance(rel=0.06, abs=0.03 * bond_dv01 * max(abs(dy_b), abs(dy_s), 1)), "EUR",
                    approx=approx, approx_label="DV01 x change in the swap spread", sign_hint="You gain when the swap rate rises relative to the bond yield.",
                    note="the legs' directions cancel: what is left is the change in the spread"),
        shuffled_choice(rng, "What is this package?",
                        ["Long the swap spread: it gains if the swap rate rises against the bond yield (the spread widens)",
                         "Short the swap spread: it gains if the spread widens, because it pays fixed",
                         "Long duration: it gains if all yields fall together",
                         "A pure bond position: the swap only adds financing"],
                        "Long the bond is long duration, paying fixed is short duration; at equal DV01 the rate level cancels. You are left owning the bond's yield against paying the swap rate: "
                        "you gain when the bond yield falls relative to the swap rate, i.e. when the spread widens. The view that spreads will tighten is the opposite package: short the bond and receive fixed."),
    ]
    solution = [
        f"Spread now = {pct(swap_rate, 3)} - {pct(y_b, 3)} = {s0:+.1f}bp. After the moves: {s0:+.1f} + ({dy_s:+g}) - ({dy_b:+g}) = {s1:+.1f}bp, a change of {change:+.1f}bp.",
        f"Bond P&L {fmt_eur(bond_pnl)} ({-dy_b:+g}bp of yield x {fmt_eur(bond_dv01, False)}); swap P&L {fmt_eur(book_swap_pnl)}; package {fmt_eur(pnl)} = about DV01 x spread change = "
        f"{fmt_eur(approx)}. Any parallel move in yields cancels; only the difference between the bond's move and the swap's move pays.",
        "This is the structure of an asset-swap package without the funding: swap spreads are driven by supply of government bonds, safe-haven demand, repo and balance-sheet costs, "
        "none of which show up in the level of rates.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "years": years, "swap_rate": swap_rate, "y_b": y_b, "s0": s0, "s1": s1, "dy_b": dy_b, "dy_s": dy_s, "pnl": pnl,
                                                 "approx": approx, "face": face, "coupon": coupon, "bond_dv01": bond_dv01, "bond_pnl": bond_pnl, "swap_pnl": book_swap_pnl, "swap": swap})
