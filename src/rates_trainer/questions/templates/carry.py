"""Carry, roll-down, warehousing and P&L attribution.

Engine numbers are exact (full revaluation). The MENTAL routes a trader would use are carried as `approx`:

    carry      =  N x (K x time - short rate x days/360)   exact: it IS the cash accrual (fixed 1/12 per month, float ACT/360)
    roll-down  ~  DV01 x (K - curve rate for the remaining maturity)   (off by the annuity ratio, ~ months/12/tenor)
    total      ~  carry + roll-down  ~  DV01 x (forward rate - spot rate, both for the remaining maturity)
    breakeven  ~  total / DV01

Tolerances are sized from measured error (see docs/DESIGN.md). Roll-down's error is the annuity ratio, so its
tolerance scales as horizon/tenor. The total also contains `other` (time value of accrued coupons, ~2% of gross accrual,
plus the floating leg's reset effect, which grows as tenor shrinks), so it carries an absolute tolerance in bp of DV01
that is larger for shorter tenors. These numeric questions therefore use tenors of 5Y and longer.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from ...engine.carry import (
    accrual_estimate, attribute, breakeven_move, carry_roll, rolled_rates,
)
from ...engine.curve import CurveShock
from ...engine.dates import TARGET
from ...engine.instruments import Side
from ...engine.risk import Portfolio, dv01_hedge_swap, par_irs, par_ois, parallel_dv01
from ...marketmaking.quoting import BP, ClientAction, Quote
from ..market import curve_line, eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template
from .mm_client_trade import HALF_WIDTHS
from .swaps import DV01_CONVENTION, NOTIONALS_M

CARRY_TENORS = (5, 7, 10, 15, 20, 30)
CURVE_PAIRS = ((5, 10), (5, 30), (10, 30), (7, 15), (10, 20), (5, 15), (7, 20))


# A scenario is only used if its answer is at least this many times the tolerance on it: otherwise a lazy answer
# (zero, or the wrong sign) would pass, and the question would teach nothing.
SIGNIFICANCE = 2.5


def _horizon_scale(days: int) -> float:
    """How the measured error of the carry + roll-down estimate grows with the horizon, relative to 3 months
    (measured 0.48-0.50 for a week, 0.85-0.9 for a month): the floating-reset and discounting effects saturate."""
    return 0.5 if days <= 10 else (0.9 if days <= 35 else 1.0)


# Worst measured error of "carry + roll-down" as an estimate of the total, in bp of DV01, over 3 months, on 100 random
# markets (IRS is the binding case; OIS is smaller), plus a ~35% margin. It falls roughly as 1/tenor.
_TOT_BP_3M = {5: 0.90, 7: 0.65, 10: 0.50, 15: 0.33, 20: 0.26, 30: 0.19}


def _tot_bp(tenor: int, days: int) -> float:
    """Absolute tolerance on carry + roll-down estimates of the TOTAL, in bp of DV01."""
    return _TOT_BP_3M[tenor] * _horizon_scale(days)


def _curve_tol_bp(days: int) -> float:
    """Same for a DV01-neutral curve trade, in bp of one leg's DV01: measured worst 0.39bp (leg errors largely cancel), +50%."""
    return 0.58 * _horizon_scale(days)


def _roll_rel(tenor: int, days: int) -> float:
    """Relative tolerance on the roll-down estimate: its error is the annuity ratio, about horizon / tenor."""
    return 0.02 + days / 365 / tenor


def _business_days(a0, a1) -> int:
    return sum(TARGET.is_business_day(a0 + timedelta(days=i)) for i in range(1, (a1 - a0).days + 1))


def _horizon_label(months: int | None, days: int) -> str:
    if months is None:
        return "1 week" if days == 7 else f"{days} days"
    return "1 month" if months == 1 else f"{months} months"


def _remaining_label(tenor: int, months: int) -> str:
    rem = tenor * 12 - months
    return f"{rem // 12}Y{rem % 12}M" if rem % 12 else f"{rem // 12}Y"


def _short_rate(kind: str, mkt, swap, a1) -> tuple[float, str]:
    if kind == "IRS":
        p = swap.float_periods[0]
        return mkt.projection("E6M").forward_rate(p.start, p.end), "6M Euribor fixing"
    days = (a1 - mkt.anchor).days
    return (mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1.0) / (days / 360.0), "ESTR (compounded over the period)"


def _mental(swap, mkt, a1, s_rem):
    est_carry = accrual_estimate(swap, mkt, a1)
    dv01 = parallel_dv01(swap, mkt)
    est_roll = dv01 * (swap.fixed_rate - s_rem) * 1e4
    return est_carry, est_roll


# =============================================================================================================

@template("carry.swap_carry_roll", skill="curve.carry_rolldown", difficulty=2)
def swap_carry_roll(rng: random.Random) -> QuestionBody:
    for _ in range(400):
        mkt = random_market(rng)
        kind = rng.choice(["IRS", "IRS", "OIS"])
        make, curve_name, label = ((par_irs, "E6M", "EUR IRS (vs 6M Euribor)") if kind == "IRS"
                                   else (par_ois, "OIS", "EUR ESTR OIS"))
        tenor = rng.choice(CARRY_TENORS)
        side = rng.choice(list(Side))
        notional = rng.choice(NOTIONALS_M) * 1e6
        months = rng.choice([1, 3])
        swap = make(side, notional, tenor, mkt)
        a1 = mkt.horizon_date(months=months)
        c = carry_roll(swap, mkt, a1)
        # the answer must be clearly bigger than the tolerance on it, or a lazy answer of zero would pass
        if abs(c.total_static) >= SIGNIFICANCE * _tot_bp(tenor, (a1 - mkt.anchor).days) * abs(c.dv01):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a scenario whose answer clearly exceeds its tolerance")
    days = (a1 - mkt.anchor).days
    s_rem, s_fwd = rolled_rates(swap, mkt, a1)
    short, short_name = _short_rate(kind, mkt, swap, a1)
    est_carry, est_roll = _mental(swap, mkt, a1, s_rem)
    gross = notional * swap.fixed_rate * days / 360
    rem = _remaining_label(tenor, months)
    verb = "receive" if side is Side.RECEIVE else "pay"
    ahead = _horizon_label(months, days)
    tb = _tot_bp(tenor, days)

    stem = (
        f"{label} curve: {curve_line(mkt, (1, 2, 5, 7, 10, 15, 20, 30), curve_name)}\n"
        f"You {verb} fixed on a {eur_m(notional)} {tenor}Y {label.split(' (')[0]}, struck at the market rate ({pct(swap.fixed_rate)}). "
        f"DV01 {fmt_eur(c.dv01)}/bp.\n"
        f"Short rate over the period: {pct(short)} ({short_name}). After {ahead} ({days} days) the swap has {rem} left; "
        f"today's curve gives {pct(s_rem, 3)} for {rem}.\n"
        f"Assume the curve does not move: every swap rate by tenor stays where it is. {DV01_CONVENTION}"
    )
    parts = [
        NumericPart(f"Carry: net coupon accrual over the {ahead} (fixed accrued minus floating accrued)?", c.carry,
                    Tolerance(rel=0.03, abs=notional * 1e-5 * days / 360), "EUR",
                    sign_hint="A receiver earns carry when the fixed rate is above the short rate; a payer the reverse.",
                    note="IRS: fixed accrues 1/12 per month, floating ACT/360. OIS: both ACT/360"),
        NumericPart(f"Roll-down: P&L from the swap's remaining maturity ({rem}) being priced off the unchanged curve?",
                    c.roll_down, Tolerance(rel=_roll_rel(tenor, days), abs=0.06 * abs(c.dv01)), "EUR", approx=est_roll,
                    approx_label="DV01 x (K - rate for the remaining maturity)",
                    sign_hint="A receiver gains when the remaining-maturity rate is BELOW the rate it holds.",
                    note="DV01 x (K - the rate for the remaining maturity)"),
        NumericPart("Total P&L over the period if the curve does not move?", c.total_static,
                    Tolerance(rel=0.06, abs=tb * abs(c.dv01)), "EUR", approx=est_carry + est_roll,
                    approx_label="carry + roll-down estimates"),
        NumericPart("By how many bp can the whole curve move (+ = rates up) before that total is wiped out?",
                    c.breakeven_bp, Tolerance(rel=0.10, abs=tb + 0.1), "bp", approx=(est_carry + est_roll) / c.dv01,
                    approx_label="total / DV01",
                    sign_hint="Rates must rise to hurt a receiver (+); fall to hurt a payer (-).",
                    note="total / DV01"),
        shuffled_choice(
            rng, "Instead the curve rolls to what today's FORWARDS imply. Your total P&L over the period is:",
            ["About zero: the mark-to-market falls by about the carry you earn",
             "The same as with an unchanged curve: carry plus roll-down",
             "Only the carry: roll-down needs the curve not to move",
             "Positive if you hold a receiver, negative if you hold a payer"],
            f"Forwards are the market's expected path. If they are realised, carry is offset by the forced "
            f"mark-to-market drift: carry {fmt_eur(c.carry)}, everything else {fmt_eur(c.mtm_forward)}, total {fmt_eur(c.total_forward)}. "
            "Carry is not free money: it pays you for the drift the market already expects."),
    ]
    solution = [
        f"Carry. {'Fixed accrues K x months/12 (30E/360); floating accrues the short rate on ACT/360.' if kind == 'IRS' else 'Both legs accrue ACT/360.'} "
        f"Net = N x (K x τ_fixed - {pct(short, 3)} x {days}/360) = {fmt_eur(c.carry)}. This is cash accrual: exact arithmetic.",
        f"Roll-down = DV01 x (K - rate for {rem}) = {fmt_eur(c.dv01)} x ({swap.fixed_rate * 1e4:.1f} - {s_rem * 1e4:.1f})bp = {fmt_eur(est_roll)}; "
        f"the engine's clean repricing gives {fmt_eur(c.roll_down)} (it uses the shorter swap's smaller annuity, ~{months / 12 / tenor * 100:.0f}% less than today's DV01).",
        f"Total = {fmt_eur(c.total_static)} = carry {fmt_eur(c.carry)} + roll-down {fmt_eur(c.roll_down)} + other {fmt_eur(c.other)}. "
        f"'Other' is small: the time value of the accrued coupons (paid later, so worth a touch less than their face accrual) and, on an IRS, "
        f"the floating leg's in-progress coupon having been fixed at the old rate. "
        f"Breakeven = total / DV01 = {c.breakeven_bp:+.2f}bp: the parallel move that erases it (estimate {(est_carry + est_roll) / c.dv01:+.2f}bp).",
        f"Forward drift: the {rem} rate is {s_rem * 1e4:.1f}bp today and {s_fwd * 1e4:.1f}bp {ahead} forward, an implied move of "
        f"{(s_fwd - s_rem) * 1e4:+.1f}bp. For a par swap that gap IS the breakeven (approximately): you are paid to hold only as long as "
        "rates move by less than the forwards imply.",
        "Warehousing intuition: carry + roll-down is what you earn for waiting if nothing happens. It is the premium for taking the other side of "
        "the market's expected drift, not an arbitrage.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "swap": swap, "c": c, "a1": a1, "kind": kind, "tenor": tenor, "months": months, "s_rem": s_rem,
        "est_carry": est_carry, "est_roll": est_roll, "gross": gross, "tb": tb})


# =============================================================================================================

@template("carry.warehousing", skill="pnl.warehousing", difficulty=3)
def warehousing(rng: random.Random) -> QuestionBody:
    """Carry versus risk: how big a cushion does carry + roll-down really give a position you warehouse?"""
    for _ in range(400):
        mkt = random_market(rng)
        kind = rng.choice(["IRS", "OIS"])
        make, label = (par_irs, "EUR IRS") if kind == "IRS" else (par_ois, "EUR OIS")
        tenor = rng.choice(CARRY_TENORS)
        months = rng.choice([1, 3])
        notional = rng.choice(NOTIONALS_M) * 1e6
        a1 = mkt.horizon_date(months=months)
        sigma_d = rng.choice([2.5, 3.0, 3.5, 4.0, 4.5, 5.0])
        probe = make(Side.RECEIVE, notional, tenor, mkt)
        c0 = carry_roll(probe, mkt, a1)
        side = Side.RECEIVE if c0.total_static > 0 else Side.PAY          # always the side that earns carry
        swap = probe if side is Side.RECEIVE else make(Side.PAY, notional, tenor, mkt)
        c = c0 if side is Side.RECEIVE else carry_roll(swap, mkt, a1)
        n_bd = _business_days(mkt.anchor, a1)
        sigma_h = sigma_d * math.sqrt(n_bd)
        be = abs(c.breakeven_bp)
        cushion = be / sigma_h * 100.0
        if (c.total_static >= SIGNIFICANCE * (_tot_bp(tenor, (a1 - mkt.anchor).days) + 0.1) * abs(c.dv01)
                and not 18.0 <= cushion <= 32.0):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an unambiguous warehousing scenario")

    days = (a1 - mkt.anchor).days
    s_rem, s_fwd = rolled_rates(swap, mkt, a1)
    est_carry, est_roll = _mental(swap, mkt, a1, s_rem)
    drift = (s_fwd - s_rem) * 1e4
    rem = _remaining_label(tenor, months)
    ahead = _horizon_label(months, days)
    verb = "receive" if side is Side.RECEIVE else "pay"
    gross = notional * swap.fixed_rate * days / 360
    cushion_reading = ("The cushion is a small fraction of one standard deviation: this is a directional position that "
                       "happens to pay carry" if cushion < 25.0 else
                       "The cushion is a meaningful fraction of one standard deviation, though still not a guarantee")
    tot_abs = (_tot_bp(tenor, days) + 0.1) * abs(c.dv01)

    stem = (
        f"You are thinking of warehousing a {label} position: {verb} fixed on {eur_m(notional)} {tenor}Y at the market rate "
        f"({pct(swap.fixed_rate)}), DV01 {fmt_eur(c.dv01)}/bp, for {ahead} ({days} days, {n_bd} business days).\n"
        f"Today's curve: the {rem} rate (what your swap rolls to) is {pct(s_rem, 3)}; "
        f"the same {rem} rate {ahead} FORWARD is {pct(s_fwd, 3)}.\n"
        f"The {tenor}Y rate has been moving about {sigma_d:g}bp a day. Treat daily moves as independent."
    )
    parts = [
        NumericPart(f"What move in the {rem} rate over the {ahead} do the forwards imply (bp)?", drift,
                    Tolerance(rel=0.02, abs=0.03), "bp", note="forward rate minus today's rate for that maturity"),
        NumericPart("If the curve simply does not move, what do you earn over the period (carry + roll-down)?",
                    c.total_static, Tolerance(rel=0.10, abs=tot_abs), "EUR", approx=c.dv01 * drift,
                    approx_label="DV01 x forward-implied drift",
                    sign_hint="You chose the side that earns carry: the answer is positive.",
                    note="for a par swap this is DV01 x the forward drift"),
        shuffled_choice(
            rng, "Instead the curve rolls exactly to its forwards. Your total P&L over the period is:",
            ["About zero: the carry is paid for by the mark-to-market drift the forwards impose",
             "The carry you computed, in full", "Negative: you are short convexity", "Larger than with an unchanged curve"],
            f"Forwards realised ⇒ total {fmt_eur(c.total_forward)} (carry {fmt_eur(c.carry)} offset by mark-to-market {fmt_eur(c.mtm_forward)}). "
            "The static-curve P&L is a bet that rates move LESS than the forwards imply."),
        NumericPart(f"What is a one-standard-deviation move in the {tenor}Y rate over the {ahead} (bp)?", sigma_h,
                    Tolerance(rel=0.04), "bp", note="daily vol x sqrt(number of business days)"),
        NumericPart("The rate can move how many bp against you before the carry + roll-down is gone, as a % of one "
                    "standard deviation?", cushion, Tolerance(rel=0.15, abs=3.0), "%",
                    note="(total / DV01) / (one-sigma move) x 100",
                    approx=abs(c.breakeven_approx_bp) / sigma_h * 100.0, approx_label="(total/DV01) / sigma"),
        shuffled_choice(
            rng, "A colleague says 'I'm in this trade for the carry.' Given these numbers:",
            [cushion_reading,
             "Carry makes the position low-risk: a loss would need a many-sigma move",
             "The position is hedged, since carry offsets DV01",
             "Carry only matters for payers"],
            f"Breakeven {be:.1f}bp against a one-sigma move of {sigma_h:.1f}bp: the cushion is {cushion:.0f}% of one sigma. "
            "Carry pays you to wait, but it does not shrink the risk: a normal move dwarfs it, so size the position for the risk, "
            "and treat the carry as a tie-breaker between otherwise similar views."),
    ]
    solution = [
        f"Forward drift = {pct(s_fwd, 3)} - {pct(s_rem, 3)} = {drift:+.2f}bp. For a par swap, total ≈ DV01 x drift = {fmt_eur(c.dv01 * drift)} "
        f"(engine {fmt_eur(c.total_static)}: carry {fmt_eur(c.carry)} + roll-down {fmt_eur(c.roll_down)} + other {fmt_eur(c.other)}).",
        f"Forwards realised ⇒ total ≈ 0 ({fmt_eur(c.total_forward)}). Carry is the market's expected drift being paid to you.",
        f"One sigma over {n_bd} business days = {sigma_d:g} x √{n_bd} = {sigma_h:.1f}bp; "
        f"your breakeven is {be:.1f}bp, so {cushion:.0f}% of one sigma. Probability the market moves further against you than that is large "
        f"(~{100 * (1 - 0.5 * (1 + math.erf(cushion / 100 / math.sqrt(2)))):.0f}% for a one-sided normal).",
        "How a trader should think: carry and roll-down are the price of waiting. They justify choosing the side that pays you "
        "when you have a view that is otherwise neutral; they do not justify ignoring the risk.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "swap": swap, "c": c, "a1": a1, "drift": drift, "sigma_h": sigma_h, "cushion": cushion, "n_bd": n_bd,
        "side": side, "tot_abs": tot_abs, "tenor": tenor, "months": months})


# =============================================================================================================

def _curve_book(rng, mkt, steepener, short_t, long_t, n_long):
    long_side = Side.PAY if steepener else Side.RECEIVE
    long_leg = par_irs(long_side, n_long, long_t, mkt)
    short_leg = dv01_hedge_swap(parallel_dv01(long_leg, mkt), short_t, mkt)
    return long_leg, short_leg


@template("carry.curve_trade", skill="curve.carry_curve", difficulty=3)
def curve_trade_carry(rng: random.Random) -> QuestionBody:
    """A DV01-neutral curve trade is a bet on the spread: its carry + roll-down is minus the spread drift the forwards imply."""
    for _ in range(400):
        mkt = random_market(rng)
        short_t, long_t = rng.choice(CURVE_PAIRS)
        steepener = rng.random() < 0.5
        n_long = rng.choice([25, 50, 75, 100, 150, 200]) * 1e6
        months = rng.choice([1, 3])
        long_leg, short_leg = _curve_book(rng, mkt, steepener, short_t, long_t, n_long)
        book = Portfolio([long_leg, short_leg])
        a1 = mkt.horizon_date(months=months)
        c = carry_roll(book, mkt, a1)
        d_long = abs(parallel_dv01(long_leg, mkt))
        if abs(c.total_static) >= SIGNIFICANCE * _curve_tol_bp((a1 - mkt.anchor).days) * d_long:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an unambiguous curve-trade carry scenario")

    days = (a1 - mkt.anchor).days
    ahead = _horizon_label(months, days)
    name = f"{short_t}s{long_t}s {'steepener' if steepener else 'flattener'}"
    rs_stat, rs_fwd = rolled_rates(short_leg, mkt, a1)
    rl_stat, rl_fwd = rolled_rates(long_leg, mkt, a1)
    spread_stat, spread_fwd = (rl_stat - rs_stat) * 1e4, (rl_fwd - rs_fwd) * 1e4
    drift = spread_fwd - spread_stat
    sgn = 1.0 if steepener else -1.0                        # steepener is long the spread
    approx_total = -sgn * d_long * drift
    unit = CurveShock.points({float(short_t): 0.0, float(long_t): 1.0})
    be_spread = breakeven_move(book, mkt, a1, unit)
    approx_be = -approx_total / (sgn * d_long) if d_long else 0.0
    rem_s, rem_l = _remaining_label(short_t, months), _remaining_label(long_t, months)
    earns = c.total_static > 0
    tol_bp = _curve_tol_bp(days)
    tot_abs = tol_bp * d_long

    stem = (
        f"You hold a DV01-neutral {name}: {long_leg.side.value} fixed {eur_m(long_leg.notional)} {long_t}Y IRS and "
        f"{short_leg.side.value} fixed {eur_m(short_leg.notional)} {short_t}Y IRS (each leg DV01 about {fmt_eur(d_long, False)}/bp). "
        f"Horizon {ahead}.\n"
        f"Curve rates for the REMAINING maturities, if the curve does not move: {rem_s} {pct(rs_stat, 3)}, {rem_l} {pct(rl_stat, 3)} "
        f"=> spread {spread_stat:.1f}bp.\n"
        f"The same tenors {ahead} FORWARD: {rem_s} {pct(rs_fwd, 3)}, {rem_l} {pct(rl_fwd, 3)} => spread {spread_fwd:.1f}bp.\n"
        "A steepener profits when the long-end rate minus the short-end rate widens; a flattener when it narrows."
    )
    parts = [
        NumericPart(f"By how much do the forwards imply the {short_t}s{long_t}s spread will change over the {ahead} (bp, + = steeper)?",
                    drift, Tolerance(rel=0.03, abs=0.08), "bp", note="forward spread minus today's spread"),
        shuffled_choice(
            rng, f"If the curve does not move, does your {name} earn or pay carry + roll-down?",
            ["It earns carry + roll-down" if earns else "It pays carry + roll-down",
             "It pays carry + roll-down" if earns else "It earns carry + roll-down"],
            f"The forwards imply the spread {'steepens' if drift > 0 else 'flattens'} by {abs(drift):.1f}bp. "
            f"A {name} is {'long' if steepener else 'short'} the spread, so it is positioned {'WITH' if not earns else 'AGAINST'} that move. "
            "A trade positioned AGAINST the forward-implied move earns carry + roll-down if the curve sits still (it is paid to wait "
            "for a move the market already expects but that has not come); one positioned WITH it pays."),
        NumericPart("Total P&L over the period if the curve does not move?", c.total_static,
                    Tolerance(rel=0.10, abs=tot_abs), "EUR", approx=approx_total,
                    approx_label=f"{'-' if steepener else '+'}|DV01| x forward spread drift",
                    sign_hint="Compare the sign of the forward-implied spread change with the direction your trade wants.",
                    note=f"{'-' if steepener else '+'}|DV01| x (forward spread drift)"),
        NumericPart("By how much must the spread change (bp, + = widen) for the total P&L over the period to be zero?",
                    be_spread, Tolerance(rel=0.15, abs=tol_bp), "bp", approx=approx_be, approx_label="-total / (|DV01| x position sign)",
                    sign_hint="A trade that earns carry needs the spread to move AGAINST it to break even.",
                    note="the spread move that cancels the total"),
    ]
    solution = [
        f"Forward spread drift = {spread_fwd:.1f} - {spread_stat:.1f} = {drift:+.1f}bp. A {name} is {'long' if steepener else 'short'} the spread, "
        f"so with the curve unchanged: total ≈ {'-' if steepener else '+'}|DV01| x drift = {fmt_eur(approx_total)} (engine {fmt_eur(c.total_static)}).",
        "Leg by leg (all per leg, same DV01): each leg earns DV01 x (forward rate - spot rate of the rolled tenor); the two legs subtract, "
        "leaving the difference of the two drifts, i.e. the SPREAD drift.",
        f"Breakeven: the spread must change by {be_spread:+.1f}bp over the period to erase it ({approx_be:+.1f}bp by the quick formula).",
        "Rule of thumb: steepeners pay for waiting when the forwards imply a steeper curve; flatteners are paid for waiting. "
        "Whether that is a lot is measured against how much the spread normally moves.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "book": book, "long_leg": long_leg, "short_leg": short_leg, "c": c, "a1": a1, "steepener": steepener,
        "drift": drift, "approx_total": approx_total, "be_spread": be_spread, "approx_be": approx_be, "d_long": d_long,
        "tol_bp": tol_bp, "short_t": short_t, "long_t": long_t, "earns": earns})


# =============================================================================================================

@template("carry.attribution", skill="pnl.attribution", difficulty=3)
def attribution(rng: random.Random) -> QuestionBody:
    """Explain a month of P&L on a curve trade: time (carry + roll-down) versus the market move (delta, convexity)."""
    for _ in range(400):
        mkt = random_market(rng)
        short_t, long_t = rng.choice(CURVE_PAIRS)
        steepener = rng.random() < 0.5
        n_long = rng.choice([50, 100, 150, 200]) * 1e6
        long_leg, short_leg = _curve_book(rng, mkt, steepener, short_t, long_t, n_long)
        book = Portfolio([long_leg, short_leg])
        a1 = mkt.horizon_date(months=1)
        a = rng.choice([-12, -9, -6, -4, -2, 2, 4, 6, 9, 12])
        b = rng.choice([-12, -9, -6, -4, -2, 2, 4, 6, 9, 12])
        shock = CurveShock.points({float(short_t): float(a), float(long_t): float(b)})
        att = attribute(book, mkt, a1, shock)
        time_pnl, move_pnl = att.time, att.total - att.time
        big, small = max(abs(time_pnl), abs(move_pnl)), min(abs(time_pnl), abs(move_pnl))
        gross_move = abs(parallel_dv01(short_leg, mkt) * a) + abs(parallel_dv01(long_leg, mkt) * b)
        if small > 0 and big / small >= 1.6 and abs(att.delta) > 0.5 * abs(move_pnl) and abs(att.residual) < 0.04 * gross_move:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an unambiguous attribution scenario")

    static = mkt.rolled(a1, "static")
    d_s, d_l = parallel_dv01(short_leg, static), parallel_dv01(long_leg, static)
    days = (a1 - mkt.anchor).days
    name = f"{short_t}s{long_t}s {'steepener' if steepener else 'flattener'}"
    d_ref = abs(d_l)
    first = -(d_s * a + d_l * b)
    tol = Tolerance(rel=0.05, abs=d_ref * (0.07 + 0.028 * max(abs(a), abs(b))))   # leg DV01 x move vs bucketed reval
    dominant = "market" if abs(move_pnl) > abs(time_pnl) else "time"
    gross_move = abs(d_s * a) + abs(d_l * b)
    resid_small = abs(att.residual) < 0.04 * gross_move

    stem = (
        f"A month ago ({days} days) you put on a DV01-neutral {name}: {long_leg.side.value} fixed {eur_m(long_leg.notional)} "
        f"{long_t}Y and {short_leg.side.value} fixed {eur_m(short_leg.notional)} {short_t}Y.\n"
        f"Today the {short_t}Y rate has moved {a:+d}bp and the {long_t}Y rate {b:+d}bp. "
        f"Your risk now: {short_t}Y leg DV01 {fmt_eur(d_s)}/bp, {long_t}Y leg DV01 {fmt_eur(d_l)}/bp.\n"
        f"Your P&L system says carry + roll-down on an unchanged curve was {fmt_eur(time_pnl)} for the month. "
        "Explain the P&L."
    )
    parts = [
        NumericPart("P&L from the market move itself (the move in the two rates, using today's DV01s)?", move_pnl, tol, "EUR",
                    approx=first, approx_label="-sum(DV01 x move)",
                    sign_hint="Check each leg: sign of its DV01 times the direction of its rate.",
                    note="-(DV01_short x move_short + DV01_long x move_long)"),
        NumericPart("Total P&L over the month?", att.total, Tolerance(rel=0.05, abs=tol.abs), "EUR",
                    approx=time_pnl + first, approx_label="carry + roll-down + delta"),
        shuffled_choice(
            rng, "What explains most of the month's P&L?",
            ["The market move" if dominant == "market" else "Time: carry and roll-down",
             "Time: carry and roll-down" if dominant == "market" else "The market move",
             "Convexity", "Funding costs"],
            f"Carry + roll-down {fmt_eur(time_pnl)} vs market move {fmt_eur(move_pnl)}. "
            "On a position that is hedged to parallel moves the curve move still usually dominates a month of carry; "
            "carry is the steady part, the move is the noisy part."),
        shuffled_choice(
            rng, "How large is the convexity / cross-gamma residual that DV01 maths leaves out?",
            ["Small: a few percent of the legs' P&Ls at most",
             "Material: comparable to the P&L of either leg",
             "Larger than carry plus roll-down by an order of magnitude",
             "Exactly zero for a DV01-neutral book"],
            f"Residual {fmt_eur(att.residual)} against legs of {fmt_eur(d_s * a, False)} and {fmt_eur(d_l * b, False)} "
            f"({abs(att.residual) / gross_move * 100:.1f}% of their combined size). It is second order in the move: "
            "it grows with the square of the move and with the convexity difference between the legs. "
            "A DV01-neutral book is NOT convexity-neutral."),
    ]
    solution = [
        f"Market move (first order) = -[{fmt_eur(d_s)} x ({a:+d}) + {fmt_eur(d_l)} x ({b:+d})] = {fmt_eur(first)}; "
        f"full revaluation {fmt_eur(move_pnl)}.",
        f"Total = carry + roll-down + market move = {fmt_eur(time_pnl)} + {fmt_eur(move_pnl)} = {fmt_eur(att.total)}.",
        f"Explain: carry {fmt_eur(att.carry)}, roll-down {fmt_eur(att.roll_down)}, other time effects {fmt_eur(att.other_time)}, delta {fmt_eur(att.delta)}, "
        f"convexity/cross residual {fmt_eur(att.residual)}.",
        "Order of questions at the end of a day: how much was time, how much was the move, and is what is left (the residual) small enough "
        "to trust the risk numbers? A large residual means the book has real convexity or the DV01s are stale.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "book": book, "att": att, "time_pnl": time_pnl, "move_pnl": move_pnl, "first": first, "a": a, "b": b,
        "d_s": d_s, "d_l": d_l, "dominant": dominant, "short_t": short_t, "long_t": long_t, "tol": tol, "a1": a1})


# =============================================================================================================

@template("mm.warehouse_carry", skill="mm.hedge_vs_inventory", difficulty=3)
def warehouse_carry(rng: random.Random) -> QuestionBody:
    """A client trade leaves you with inventory. Should carry change whether you warehouse it or hedge it?"""
    for _ in range(400):
        mkt = random_market(rng)
        tenor = rng.choice(CARRY_TENORS)
        w = rng.choice(HALF_WIDTHS[tenor])
        mid = mkt.quotes["E6M"][tenor * 12]
        quote = Quote(round(mid - w * BP, 7), round(mid + w * BP, 7))
        action = rng.choice(list(ClientAction))
        notional = rng.choice([100, 150, 200, 250, 300, 500]) * 1e6
        swap = quote.dealer_swap(action, notional, mkt, tenor)
        a1 = mkt.horizon_date(days=7)
        c = carry_roll(swap, mkt, a1)
        sigma_d = rng.choice([3.0, 3.5, 4.0, 4.5])
        hedge_hs = rng.choice([0.05, 0.1, 0.15, 0.2])
        n_bd = _business_days(mkt.anchor, a1)
        sigma_w = abs(c.dv01) * sigma_d * math.sqrt(n_bd)
        hedge_cost = hedge_hs * abs(c.dv01)
        r_cost = abs(c.total_static) / hedge_cost
        # the reading must not depend on whether you use the engine's total or the mental carry + roll-down estimate
        twin_mid = par_irs(swap.side, notional, tenor, mkt)
        s_mid, _ = rolled_rates(twin_mid, mkt, a1)
        e_carry, e_roll = _mental(twin_mid, mkt, a1, s_mid)
        r_est = abs(e_carry + e_roll) / hedge_cost
        same_side = (c.total_static > 0) == (e_carry + e_roll > 0)
        clear = lambda r: r < 0.7 or r > 1.4
        if (abs(c.total_static) > 0.1 * hedge_cost and abs(c.carry) > 0.04 * abs(c.dv01) and same_side
                and clear(r_cost) and clear(r_est) and (r_cost < 1) == (r_est < 1)):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an unambiguous warehousing-decision scenario")

    days = (a1 - mkt.anchor).days
    short_rate, _ = _short_rate("IRS", mkt, swap, a1)
    twin = par_irs(swap.side, notional, tenor, mkt)          # the same position at the mid: how a trader marks roll-down
    s_rem, _ = rolled_rates(twin, mkt, a1)
    est_carry, est_roll = _mental(twin, mkt, a1, s_rem)
    gross = notional * swap.fixed_rate * days / 360
    pays = action is ClientAction.PAYS
    held = "receive" if swap.side is Side.RECEIVE else "pay"
    positive = c.total_static > 0
    r_risk = abs(c.total_static) / sigma_w
    edge = swap.pv(mkt)
    if positive and r_cost < 0.7:
        correct = ("A week of carry and roll-down earns back LESS than the cost of hedging, and is small next to the week's risk: "
                   "warehousing needs another reason (flow expected to offset it, or room in the limit), not carry")
    elif positive:
        correct = ("A week of carry and roll-down earns back MORE than the cost of hedging, but is still small next to the week's risk: "
                   "it does not make an unhedged position safe")
    else:
        correct = ("Warehousing COSTS you carry and roll-down every day on top of the risk: if flow does not come to offset it, "
                   "the case for hedging or skewing harder gets stronger")
    wrong = [
        "Carry is guaranteed income: warehousing is always better than paying to hedge",
        "Carry removes the risk, so the position needs no limit or hedge",
        "Carry only matters over horizons of a year or more, so it can be ignored for any decision under a month",
    ]

    stem = (
        f"Your {tenor}Y market is {pct(quote.bid)} / {pct(quote.offer)} (mid {pct(mid)}). A client {action.value} fixed on "
        f"{eur_m(notional)}; you now {held} fixed (DV01 {fmt_eur(c.dv01)}/bp). You could hedge in the interdealer market at mid, "
        f"paying a half-spread of {hedge_hs:g}bp, or keep the position for a week ({days} days, {n_bd} business days).\n"
        f"Short rate over the week: {pct(short_rate, 3)}. The mid-market rate for the swap's remaining maturity is {pct(s_rem, 4)} on today's curve, "
        f"against a mid of {pct(mid, 4)} today. The {tenor}Y has been moving about "
        f"{sigma_d:g}bp a day. Assume the curve does not move for the carry calculation."
    )
    parts = [
        NumericPart("Carry over the week (net coupon accrual: fixed accrued minus floating accrued)?", c.carry,
                    Tolerance(rel=0.03, abs=notional * 1e-5 * days / 360), "EUR",
                    sign_hint="Receiving fixed earns carry when the fixed rate is above the short rate; paying fixed the reverse.",
                    note="N x (K x time - short rate x days/360); K is the rate you dealt at"),
        NumericPart("Roll-down over the week (curve unchanged), marking the swap at the MID rate?", c.roll_down,
                    Tolerance(rel=_roll_rel(tenor, days), abs=0.01 * abs(c.dv01)), "EUR", approx=est_roll,
                    approx_label="DV01 x (mid - rate for the remaining maturity)",
                    sign_hint="Positive when the remaining-maturity rate is below the mid you hold (for a receiver).",
                    note="exclude the edge you captured at the client trade: mark off the mid"),
        NumericPart("One standard deviation of the position's P&L over the week?", sigma_w, Tolerance(rel=0.04), "EUR",
                    note="|DV01| x daily vol x sqrt(business days)"),
        NumericPart("What does it cost to hedge now (half-spread crossed on the hedge)?", hedge_cost, Tolerance(rel=0.03), "EUR",
                    note="half-spread x |DV01|"),
        shuffled_choice(rng, "What do these numbers say about warehousing the position instead of hedging it?",
                        [correct, *wrong],
                        f"Carry + roll-down {fmt_eur(c.total_static)} over the week vs hedge cost {fmt_eur(hedge_cost)} "
                        f"({abs(c.total_static) / hedge_cost * 100:.0f}%) vs one-sigma P&L {fmt_eur(sigma_w)} "
                        f"({r_risk * 100:.1f}%). The spread you captured on the client trade is {fmt_eur(edge, False)}."),
    ]
    solution = [
        f"Carry + roll-down ≈ accrual {fmt_eur(est_carry)} + DV01 x (mid - {pct(s_rem, 3)}) {fmt_eur(est_roll)} = {fmt_eur(est_carry + est_roll)} "
        f"(engine {fmt_eur(c.total_static)}; mark roll-down off the MID, since the half-spread you captured is already booked as edge).",
        f"One sigma over {n_bd} business days = {sigma_d:g} x √{n_bd} = {sigma_d * math.sqrt(n_bd):.1f}bp x {fmt_eur(abs(c.dv01), False)} = {fmt_eur(sigma_w, False)}.",
        f"Hedging now costs {hedge_hs:g}bp x {fmt_eur(abs(c.dv01), False)} = {fmt_eur(hedge_cost, False)}; "
        f"a week's carry + roll-down is {abs(c.total_static) / hedge_cost * 100:.0f}% of that and {r_risk * 100:.1f}% of one sigma.",
        "Link to quoting: carry is a small second-order input to the skew. The first-order drivers remain the inventory against the limit, "
        "expected offsetting flow, volatility and the cost of hedging.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "quote": quote, "swap": swap, "c": c, "a1": a1, "sigma_w": sigma_w, "hedge_cost": hedge_cost,
        "est_roll": est_roll, "positive": positive, "r_cost": r_cost, "n_bd": n_bd, "action": action, "tenor": tenor,
        "twin": twin, "w": w})
