"""Rates mathematics templates."""

from __future__ import annotations

import random
from datetime import timedelta

from ...engine.curve import Curve
from ..market import random_market
from ..model import ChoicePart, NumericPart, QuestionBody, Tolerance
from ..registry import template


@template("math.forward_1y", skill="math.forward_rates", difficulty=1)
def forward_1y(rng: random.Random) -> QuestionBody:
    """Implied 1Y forward starting in s years from two annually-compounded zero rates."""
    mkt = random_market(rng)
    s = rng.choice([1, 2, 3, 4, 5, 7])
    d_a = mkt.anchor + timedelta(days=365 * s)            # ACT/365F: exactly s and s+1 years
    d_b = mkt.anchor + timedelta(days=365 * (s + 1))
    za, zb = round(mkt.ois.zero_rate(d_a), 5), round(mkt.ois.zero_rate(d_b), 5)   # as displayed, 0.001%
    shown = Curve(mkt.anchor, (d_a, d_b), ((1 + za) ** -s, (1 + zb) ** -(s + 1)))
    fwd = shown.annual_forward(d_a, d_b)
    shortcut = ((s + 1) * zb - s * za)

    stem = (
        f"Annually-compounded zero rates from a EUR curve:\n"
        f"  {s}Y: {za * 100:.3f}%     {s + 1}Y: {zb * 100:.3f}%\n"
        f"What 1-year rate does the market imply for the year starting in {s} year(s) (the {s}y1y forward)?"
    )
    part1 = NumericPart(f"{s}y1y forward rate (in %):", fwd * 100, Tolerance(rel=0, abs=0.03), unit="%",
                        note="e.g. 2.85", approx=shortcut * 100, approx_label="shortcut ((n+1) z(n+1) - n z(n))")
    above = fwd > zb
    part2 = ChoicePart(
        f"Is the {s}y1y forward above or below the {s + 1}Y zero rate?",
        ["Above", "Below"], 0 if above else 1,
        "Zero rates are averages of forwards. A rising zero curve means the newest forward must be above the longer zero."
        if above else "Zero rates are averages of forwards. A falling zero curve means the newest forward must be below the longer zero.",
    )
    solution = [
        f"(1 + z{s + 1})^{s + 1} = (1 + z{s})^{s} x (1 + f)  =>  f = (1 + {zb:.5f})^{s + 1} / (1 + {za:.5f})^{s} - 1 = {fwd * 100:.3f}%",
        f"Shortcut: f ~ {s + 1} x z{s + 1} - {s} x z{s} = {shortcut * 100:.3f}% (error is a fraction of a bp).",
        "The forward is the breakeven: hold the longer zero vs roll the shorter one and the reinvestment rate that equalises them.",
    ]
    return QuestionBody(stem, [part1, part2], solution, {"s": s, "za": za, "zb": zb})
