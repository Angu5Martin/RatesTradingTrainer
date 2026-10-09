"""Market making: how a quote should depend on the trader's state.

Graded on DIRECTION and relative width only. The numbers in the solution come from the
stylised model in marketmaking.quoting and are labelled illustrative.
"""

from __future__ import annotations

import random

from ...marketmaking.quoting import BP, ClientAction, Liquidity, QuotingContext, make_quote
from ..market import pct, random_market
from ..model import ChoicePart, QuestionBody
from ..registry import template

HALF_SPREAD = {5: 0.15, 10: 0.2, 30: 0.4}
VOL_TEXT = {0.8: "calm (realised vol low, nothing scheduled)", 1.0: "normal", 1.5: "elevated (big data week, markets jumpy)"}
LIQ_TEXT = {Liquidity.DEEP: "deep: the interdealer market is easy to hedge in size",
            Liquidity.NORMAL: "normal", Liquidity.THIN: "thin: hedging in size would move the market"}
ADV_TEXT = {0.0: "benign: mostly corporate and pension hedgers",
            0.3: "mixed: some real money, some funds",
            0.6: "toxic: fast-money accounts who have been right recently are active"}


def _conviction_text(c: float) -> str:
    return "moderate" if c <= 0.5 else "high"


def _sample(rng: random.Random):
    tenor = rng.choice(list(HALF_SPREAD))
    hs = HALF_SPREAD[tenor]
    limit = rng.choice([300e3, 500e3, 750e3])
    inventory = round(rng.choice([-0.9, -0.7, -0.5, -0.3, 0, 0, 0.3, 0.5, 0.7, 0.9]) * limit / 5e3) * 5e3
    flow = round(rng.choice([-0.3, 0, 0, 0.3]) * limit / 5e3) * 5e3
    vol = rng.choice(list(VOL_TEXT))
    liq = rng.choice(list(Liquidity))
    adv = rng.choice(list(ADV_TEXT))
    if rng.random() < 0.5:
        view_bp, conviction = 0.0, 0.0
    else:
        view_bp, conviction = rng.choice([-4, -3, -2, 2, 3, 4]), rng.choice([0.5, 0.8])
    return tenor, QuotingContext(
        fair_value=0.0,  # filled in by caller
        base_half_spread_bp=hs, inventory_dv01=inventory, dv01_limit=limit, vol_multiplier=vol,
        liquidity=liq, adverse_selection=adv, expected_flow_dv01=flow, view_bp=view_bp, conviction=conviction,
    )


def _crisp(b, ctx) -> bool:
    """Reject ambiguous draws: tiny net skew, drivers in near-balance conflict, borderline widths."""
    net = b.net_shift_bp
    if not (abs(net) >= 0.06 or abs(net) < 0.01):
        return False
    risk = b.inventory_skew_bp + b.flow_skew_bp
    view = b.view_skew_bp
    if risk * view < 0 and not (abs(risk) >= 2 * abs(view) or abs(view) >= 2 * abs(risk)):
        return False
    r = (b.bid_half_width_bp + b.offer_half_width_bp) / 2 / ctx.base_half_spread_bp
    return r >= 1.2 or r <= 0.9 or 0.95 <= r <= 1.05


@template("mm.skew_and_width", skill="mm.skew", difficulty=2)
def skew_and_width(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    for _ in range(500):
        tenor, ctx0 = _sample(rng)
        ctx = QuotingContext(**{**ctx0.__dict__, "fair_value": mkt.quotes["E6M"][tenor * 12]})
        b = make_quote(ctx)
        if _crisp(b, ctx):
            break
    else:  # pragma: no cover - guards against a future change making sampling infeasible
        raise RuntimeError("could not draw an unambiguous quoting context")

    hs = ctx.base_half_spread_bp
    inv = ctx.inventory_dv01
    inv_text = ("flat" if inv == 0 else
                f"{'LONG' if inv > 0 else 'SHORT'} {abs(inv) / 1e3:,.0f}k DV01 of {tenor}Y duration "
                f"({abs(ctx.utilisation) * 100:.0f}% of your {ctx.dv01_limit / 1e3:,.0f}k limit)")
    flow = ctx.expected_flow_dv01
    flow_text = ("two-way, no obvious bias" if flow == 0 else
                 f"you expect more clients to {'PAY' if flow > 0 else 'RECEIVE'} fixed "
                 f"(~{abs(flow) / 1e3:,.0f}k DV01 of {'receiving' if flow > 0 else 'paying'} for you)")
    view_text = ("no view" if ctx.conviction == 0 else
                 f"you think the {tenor}Y swap rate will {'RISE' if ctx.view_bp > 0 else 'FALL'} about {abs(ctx.view_bp):.0f}bp "
                 f"over the next few days ({_conviction_text(ctx.conviction)} conviction)")
    stem = (
        f"EUR {tenor}Y swap. Fair value {pct(ctx.fair_value)}. On a normal day you make "
        f"{pct(ctx.fair_value - hs * BP)} / {pct(ctx.fair_value + hs * BP)}.\n"
        f"  Inventory:   {inv_text}\n"
        f"  Volatility:  {VOL_TEXT[ctx.vol_multiplier]}\n"
        f"  Liquidity:   {LIQ_TEXT[ctx.liquidity]}\n"
        f"  Client flow: {flow_text}\n"
        f"  Flow quality: {ADV_TEXT[ctx.adverse_selection]}\n"
        f"  Your view:   {view_text}\n"
        "Reminder: you pay fixed at your bid and receive fixed at your offer; long duration = receiving fixed."
    )

    direction_opts = ["Higher in rate (both bid and offer up)", "Lower in rate (both bid and offer down)",
                      "Symmetric around fair value (no skew)"]
    d_idx = {"higher": 0, "lower": 1, "neutral": 2}[b.direction]
    enc = b.encouraged_client_action
    action_opts = ["Client RECEIVES fixed (you pay)", "Client PAYS fixed (you receive)", "Neither: stay neutral"]
    a_idx = 2 if enc is None else (0 if enc is ClientAction.RECEIVES else 1)
    ratio = (b.bid_half_width_bp + b.offer_half_width_bp) / 2 / hs
    w_idx = 0 if ratio >= 1.2 else (2 if ratio <= 0.9 else 1)

    why_dir = (f"Net shift {b.net_shift_bp:+.2f}bp = inventory {b.inventory_skew_bp:+.2f} + expected flow {b.flow_skew_bp:+.2f} "
               f"+ view {b.view_skew_bp:+.2f}. Long duration (or an expected build-up of it, or a bearish-rates view) pushes quotes "
               f"UP in rate; short pushes them DOWN.")
    parts = [
        ChoicePart("Relative to a market symmetric around fair value, where should your market sit?", direction_opts, d_idx, why_dir),
        ChoicePart("Which client trade should the skew make most attractive?", action_opts, a_idx,
                   "Quote higher: your bid becomes more attractive to clients who receive fixed (you pay fixed, reducing a long). "
                   "Quote lower: your offer becomes more attractive to clients who pay (you receive fixed, reducing a short)."),
        ChoicePart("Compared with a normal day, how wide should your market be?", ["Wider", "About the same", "Narrower"], w_idx,
                   f"Width ≈ base x vol x liquidity x (1 + adverse selection) = {b.core_half_spread_bp:.2f}bp half-spread "
                   f"(vs {hs:.2f} normally)" + (f", plus {b.limit_widening_bp:.2f}bp extra on the risk-adding side near the limit."
                                                if b.limit_widening_bp > 0 else ".")),
    ]
    solution = [
        why_dir,
        f"Width: base {hs:.2f}bp half-spread x vol {ctx.vol_multiplier:g} x liquidity {ctx.liquidity.value:g} x "
        f"(1 + {ctx.adverse_selection:g}) = {b.core_half_spread_bp:.2f}bp"
        + (f"; near the limit the risk-adding side is widened by a further {b.limit_widening_bp:.2f}bp." if b.limit_widening_bp > 0 else "."),
        f"Illustrative market from the teaching model: {pct(b.quote.bid, 4)} / {pct(b.quote.offer, 4)} "
        f"(vs symmetric {pct(ctx.fair_value - hs * BP, 4)} / {pct(ctx.fair_value + hs * BP, 4)}). Direction and relative size matter; "
        "the exact numbers are a model, not a rule.",
        "Skew manages INVENTORY; width protects against INFORMATION and volatility. They are different tools.",
        "Trade-off: every bp you skew away from mid costs you flow on the side you are discouraging; every bp you widen "
        "costs you flow on both sides. You pay for protection with volume.",
    ]
    if b.view_skew_bp * (b.inventory_skew_bp + b.flow_skew_bp) < 0:
        solution.append("Here your view and your risk point opposite ways. The risk position wins: a limit is a constraint, "
                        "a view is an opinion.")
    return QuestionBody(stem, parts, solution, {"ctx": ctx, "breakdown": b})
