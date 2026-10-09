"""Contract specifications at work: ticks, tick value, a P&L in euros, and the yield move it stands for."""

from __future__ import annotations

import random

from ...engine.futures import BOBL, BUND
from ...engine.risk import parallel_dv01
from ..market import FuturesCase, random_futures, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template


@template("futures.contract_specs_pnl", skill="futures.dv01", difficulty=1, kind="calculation")
def contract_specs_pnl(rng: random.Random) -> QuestionBody:
    """Ticks, tick value and the daily P&L of a futures position, then the yield move that price change represents."""
    mkt = random_market(rng)
    case: FuturesCase = random_futures(rng, mkt, spec=rng.choice([BUND, BUND, BOBL]), min_gap=0.15)
    sp = case.spec
    fut_dv01 = parallel_dv01(case.fut.with_contracts(1), mkt)
    n = rng.choice([100, 250, 400, 500, 800, 1000])
    long_ = rng.random() < 0.5
    ticks = rng.choice([-1, 1]) * rng.choice([8, 12, 17, 25, 33, 48])
    entry = case.price
    exit_ = round(entry + ticks * 0.01, 2)
    pnl = (1 if long_ else -1) * n * ticks * sp.tick_value
    per_contract_pnl = ticks * sp.tick_value
    yield_move = -per_contract_pnl / fut_dv01
    cash_move = "pay" if pnl < 0 else "receive"
    stem = (
        f"{sp.name} future ({sp.code}): €{sp.notional:,.0f} notional, price quoted per 100, 1 point = {fmt_eur(sp.point_value, False)}, 1 tick (0.01) = {fmt_eur(sp.tick_value, False)}.\n"
        f"You {'buy' if long_ else 'sell'} {n:,} contracts at {entry:.2f}. At the close the price is {exit_:.2f}. "
        f"A long contract has a DV01 of {fmt_eur(fut_dv01, False)} (EUR per bp fall in the yield of its cheapest-to-deliver bond)."
    )
    parts = [
        NumericPart("By how many ticks did the price move (signed)?", ticks, Tolerance(rel=0, abs=0.5), "ticks", note="price change / 0.01"),
        NumericPart("What is your P&L on the position (EUR)?", pnl, Tolerance(rel=0.005), "EUR", sign_hint="A long position gains when the price rises; a short when it falls.",
                    note="contracts x ticks x tick value, signed by your side"),
        NumericPart("What change in the CTD's yield (bp, + = yields up) does that price move represent?", yield_move, Tolerance(rel=0.05, abs=0.1), "bp",
                    sign_hint="Futures prices and yields move in opposite directions.", note="P&L per contract / DV01 per contract, with the sign flipped"),
        shuffled_choice(
            rng, f"Futures are margined daily. What happens to your cash on this day?",
            [f"You {cash_move} {fmt_eur(abs(pnl), False)} of variation margin today: the P&L is settled in cash, not carried until you close",
             "Nothing: the gain or loss is realised only when you close the position",
             "The margin is paid at delivery",
             "You pay the margin only if you are long"],
            "Exchange-traded futures settle every day, so each day's profit or loss is paid or received in cash. The cash flow is a funding item: it is the source of the convexity "
            "adjustment in short-term interest-rate futures."),
    ]
    solution = [
        f"Ticks = ({exit_:.2f} - {entry:.2f}) / 0.01 = {ticks:+d}. P&L = {'+' if long_ else '-'}{n:,} x {ticks:+d} x {fmt_eur(sp.tick_value, False)} = {fmt_eur(pnl)}.",
        f"Per contract the move is worth {fmt_eur(per_contract_pnl)}; at {fmt_eur(fut_dv01, False)} per bp the CTD yield moved {yield_move:+.2f}bp. "
        f"A 1-tick move is about {sp.tick_value / fut_dv01:.2f}bp of yield.",
        "The tick value and the DV01 per contract are the two numbers that turn a price screen into risk: ticks give euros, DV01 gives basis points.",
    ]
    return QuestionBody(stem, parts, solution, {"case": case, "n": n, "long": long_, "ticks": ticks, "pnl": pnl, "yield_move": yield_move, "fut_dv01": fut_dv01})
