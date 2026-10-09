"""Bond duration / convexity templates."""

from __future__ import annotations

import random

from ...engine.instruments import bond_convexity, bond_modified_duration, bond_price
from ..market import eur_m
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur
from ..registry import template


@template("bonds.duration_convexity_pnl", skill="bonds.duration_convexity", difficulty=2)
def bond_duration_convexity(rng: random.Random) -> QuestionBody:
    maturity = rng.choice([5, 7, 10, 15, 20, 30])
    coupon = rng.choice([0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04])
    y = round(rng.uniform(0.015, 0.040), 4)
    face = rng.choice([10, 20, 25, 50, 75, 100]) * 1e6
    short = rng.random() < 0.3
    move = rng.choice([-100, -75, -50, 50, 75, 100])

    price = bond_price(coupon, maturity, y)
    d_mod = bond_modified_duration(coupon, maturity, y)
    conv = bond_convexity(coupon, maturity, y)
    mv = (-1 if short else 1) * face * price / 100.0          # signed market value
    dv01 = mv * d_mod * 1e-4
    dy = move * 1e-4
    duration_pnl = -dv01 * move                                 # first order
    convexity_pnl = 0.5 * conv * dy**2 * mv                     # second-order correction
    exact = mv * (bond_price(coupon, maturity, y + dy) / price - 1.0)   # full repricing
    direction = "short" if short else "long"

    stem = (
        f"You are {direction} {eur_m(face)} face of a {maturity}Y EUR government bond, annual {coupon * 100:.2f}% coupon, "
        f"yield {y * 100:.3f}%, price {price:.3f}.\n"
        f"Modified duration {d_mod:.2f}, convexity {conv:.1f} (years^2). Positions are valued on a coupon date (no accrued).\n"
        "DV01 = P&L for a 1bp FALL in yield (positive if long)."
    )
    parts = [
        NumericPart("What is the DV01 of the position?", dv01, Tolerance(rel=0.03), "EUR",
                    sign_hint="Long bond: positive. Short bond: negative.", note="market value x duration x 1bp"),
        NumericPart(f"Yields move {move:+d}bp. What P&L does DV01 alone (duration only) predict?", duration_pnl,
                    Tolerance(rel=0.03), "EUR", sign_hint="Long bonds lose when yields rise."),
        NumericPart("What convexity adjustment (EUR) should be added to that estimate?", convexity_pnl,
                    Tolerance(rel=0.08), "EUR",
                    sign_hint="Long bonds are long convexity: the adjustment is positive. Short bonds: negative.",
                    note="0.5 x convexity x (move)^2 x market value"),
        NumericPart("Reprice the bond at the new yield: what is the actual P&L?", exact, Tolerance(rel=0.04), "EUR",
                    approx=duration_pnl + convexity_pnl, approx_label="duration + convexity estimate",
                    sign_hint="Long bonds lose when yields rise, short bonds gain."),
    ]
    solution = [
        f"Market value = {eur_m(face)} x {price:.3f}/100 = {fmt_eur(mv, False)} ({direction}).",
        f"DV01 = MV x modified duration x 1bp = {fmt_eur(abs(mv), False)} x {d_mod:.2f} x 0.0001 = {fmt_eur(dv01)}.",
        f"First order (duration only) = -DV01 x move = {fmt_eur(duration_pnl)}.",
        f"Convexity adjustment = 0.5 x C x dy^2 x MV = 0.5 x {conv:.1f} x ({dy:.4f})^2 x {fmt_eur(abs(mv), False)} "
        f"{'x (-1) ' if short else ''}= {fmt_eur(convexity_pnl)}.",
        f"Duration-only {fmt_eur(duration_pnl)}; with convexity {fmt_eur(duration_pnl + convexity_pnl)}; exact repricing {fmt_eur(exact)}. "
        f"Duration alone is off by {fmt_eur(exact - duration_pnl)} ({abs(exact - duration_pnl) / abs(exact) * 100:.0f}% of the true P&L). "
        f"The adjustment is always {'against' if short else 'in favour of'} the {direction} regardless of direction: "
        f"{'short' if short else 'long'} convexity.",
    ]
    return QuestionBody(stem, parts, solution, {"face": face, "coupon": coupon, "maturity": maturity, "y": y,
                                                 "move": move, "short": short, "exact_pnl": exact,
                                                 "second_order": duration_pnl + convexity_pnl})
