"""Swap valuation and mechanics: marking an off-market swap, cash-flow conventions, and FRA settlement.

The engine prices these (IRSwap.pv, FRA.pv, make_schedule); the questions give the trainee the printed numbers a desk screen shows and ask for
the arithmetic that sits behind them, then check that arithmetic against the engine in tests.
"""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.dates import DayCount
from ...engine.instruments import FRA, IRSwap, Side
from ...engine.risk import par_irs, parallel_dv01
from ..market import eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template
from .swaps import NOTIONALS_M

# --------------------------------------------------------------------------------------------------------------------- MTM

@template("swaps.mtm_off_market", skill="swaps.dv01", difficulty=2, kind="calculation")
def mtm_off_market(rng: random.Random) -> QuestionBody:
    """A seasoned swap struck away from the market: value = PV01 x (rate difference), and what a rate move and an unwind do to it."""
    for _ in range(300):
        mkt = random_market(rng)
        tenor = rng.choice([3, 5, 7, 10, 15, 20])
        side = rng.choice(list(Side))
        notional = rng.choice(NOTIONALS_M) * 1e6
        par = round(mkt.par_irs_rate(tenor * 12), 5)
        offset = rng.choice([-1, 1]) * rng.choice([30, 45, 60, 80, 100, 130]) * 1e-4
        strike = round(par + offset, 5)
        if strike <= 0.002:
            continue
        swap = IRSwap.new(side, notional, strike, mkt.spot, tenor * 12)
        move = rng.choice([-30, -25, -20, 20, 25, 30])
        pv_moved = swap.pv(mkt.shifted(CurveShock.parallel(move)))
        dv01 = parallel_dv01(swap, mkt)
        if abs(pv_moved) > 1.5 * max(0.04 * abs(pv_moved), 0.04 * abs(dv01 * move)):          # the new mark must clear its tolerance
            break
    pv = swap.pv(mkt)
    pv01 = swap.annuity(mkt) * notional * 1e-4                # fixed-leg PV01: EUR per bp of fixed rate, always positive
    diff_bp = (strike - par) * 1e4                            # strike minus market
    mental = side.sign * pv01 * diff_bp
    half = rng.choice([0.15, 0.25, 0.4, 0.5])
    unwind = pv - pv01 * half
    asset = pv > 0
    recv = side is Side.RECEIVE
    verb = "receive" if recv else "pay"

    stem = (
        f"You {verb} fixed at {pct(strike, 3)} on a {eur_m(notional)} EUR IRS (vs 6M Euribor) with {tenor} years left, valued on a payment date "
        f"(no accrued interest). The market rate for a {tenor}Y swap is {pct(par, 3)}.\n"
        f"The swap's fixed-leg PV01 (annuity x notional x 1bp) is {fmt_eur(pv01, False)} per bp."
    )
    asset_txt = {(True, True): "An asset: the fixed leg you receive is worth more than the floating leg you pay",
                 (True, False): "An asset: the floating leg you receive is worth more than the fixed leg you pay",
                 (False, True): "A liability: the floating leg you pay is worth more than the fixed leg you receive",
                 (False, False): "A liability: the fixed leg you pay is worth more than the floating leg you receive"}
    parts = [
        NumericPart("What is the mark-to-market value of the swap to you (EUR, positive = an asset)?", pv, Tolerance(rel=0.02), "EUR",
                    approx=mental, approx_label="PV01 x rate difference", sign_hint="Receiving fixed above the market is worth money; paying above the market costs money.",
                    note="PV01 x (strike - market rate in bp), signed by your side"),
        NumericPart(f"All swap rates then move {move:+d}bp in parallel. What is the new mark-to-market (EUR)?", pv_moved, Tolerance(rel=0.04, abs=0.04 * abs(dv01) * abs(move)),
                    "EUR", approx=pv - dv01 * move, approx_label="old value - DV01 x move",
                    sign_hint="Rates up helps a payer and hurts a receiver, on top of where you started.",
                    note=f"your DV01 is {fmt_eur(dv01)} per bp"),
        NumericPart(f"A dealer will take the other side at {half:g}bp either side of the market rate. What do you receive (+) or pay (-) to close the swap now (EUR)?",
                    unwind, Tolerance(rel=0.02, abs=pv01 * 0.12), "EUR", note="the mark, less the cost of crossing the bid/offer on the PV01",
                    sign_hint="Closing always costs you the half-spread on top of the mark."),
        shuffled_choice(rng, "Is this swap an asset or a liability to you, and which leg is worth more?",
                        [asset_txt[(asset, recv)], *(v for k2, v in asset_txt.items() if k2 != (asset, recv))],
                        "A swap is worth the difference between the two legs from your side. Anyone receiving a fixed rate above the market, or paying one "
                        "below it, is owed money; the other side posts that value as collateral (variation margin)."),
    ]
    solution = [
        f"Value = side x PV01 x (strike - market) = {'+' if recv else '-'}{fmt_eur(pv01, False)} x ({strike * 1e4:.1f} - {par * 1e4:.1f}) bp "
        f"= {fmt_eur(mental)}; the engine, discounting every cash flow, gives {fmt_eur(pv)}.",
        f"Your DV01 is {fmt_eur(dv01)} per bp, so a {move:+d}bp move changes the value by about {fmt_eur(-dv01 * move)}: new mark {fmt_eur(pv - dv01 * move)} "
        f"(full revaluation {fmt_eur(pv_moved)}). An off-market swap has a different DV01 from a par swap of the same size: its value moves the annuity too.",
        f"Closing: {fmt_eur(pv)} less the half-spread cost {half:g}bp x {fmt_eur(pv01, False)} = {fmt_eur(unwind)}.",
        "Economically, an off-market swap is a par swap plus a stream of annual cash flows of (strike - market) on the notional: a long-dated "
        "annuity, which is why its value is PV01 x the rate difference.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "swap": swap, "pv": pv, "pv01": pv01, "mental": mental, "par": par, "strike": strike,
                                                 "pv_moved": pv_moved, "dv01": dv01, "move": move, "unwind": unwind, "half": half})


# --------------------------------------------------------------------------------------------------------------------- conventions

@template("swaps.cashflow_conventions", skill="swaps.ois_vs_ibor", difficulty=2, kind="calculation")
def cashflow_conventions(rng: random.Random) -> QuestionBody:
    """The first cash flows of a EUR swap: ACT/360 floating accrual, 30E/360 fixed accrual, and who pays what on the first floating date."""
    mkt = random_market(rng)
    tenor = rng.choice([2, 3, 5, 7, 10])
    side = rng.choice(list(Side))
    notional = rng.choice(NOTIONALS_M) * 1e6
    strike = round(mkt.par_irs_rate(tenor * 12), 5)
    swap = IRSwap.new(side, notional, strike, mkt.spot, tenor * 12)
    f1, fx1 = swap.float_periods[0], swap.fixed_periods[0]
    days = (f1.end - f1.start).days
    fixing = round(mkt.projection("E6M").forward_rate(f1.start, f1.end) + rng.choice([-1, 1]) * rng.uniform(0.0002, 0.0012), 5)
    float_amt = notional * fixing * days / 360.0
    frac = DayCount.THIRTY_E_360.fraction(fx1.start, fx1.end)
    fixed_amt = notional * strike * frac
    naive_fixed = notional * strike
    recv = side is Side.RECEIVE
    # 30E/360 counts every month as 30 days, so a rolled year can be 360, 361 or 362 'days': say what the dates give
    d360 = round(frac * 360)

    stem = (
        f"You {'receive' if recv else 'pay'} fixed at {pct(strike, 3)} on a {eur_m(notional)} {tenor}Y EUR IRS vs 6M Euribor, trade date {mkt.trade_date:%d-%b-%Y}, "
        f"effective (spot, T+2 TARGET) {mkt.spot:%d-%b-%Y}.\n"
        "Fixed leg: annual, 30E/360. Floating leg: 6M Euribor, semi-annual, ACT/360. Payment dates follow modified-following on TARGET.\n"
        f"  First floating period: {f1.start:%d-%b-%Y} to {f1.end:%d-%b-%Y}; 6M Euribor for it fixes at {fixing * 100:.3f}%.\n"
        f"  First fixed period:    {fx1.start:%d-%b-%Y} to {fx1.end:%d-%b-%Y}."
    )
    parts = [
        NumericPart("How many days does the first floating period accrue (ACT/360 numerator)?", days, Tolerance(rel=0, abs=0.5), "days", note="actual days between the dates"),
        NumericPart("What is the first floating payment (EUR)?", float_amt, Tolerance(rel=0.0005), "EUR", note="notional x fixing x days/360"),
        NumericPart("What is the first annual fixed payment (EUR)?", fixed_amt, Tolerance(rel=0.0005), "EUR",
                    note=f"30E/360: months count as 30 days (the dates give {d360}/360)"),
        shuffled_choice(
            rng, "On the first floating payment date, 6 months in, what cash moves?",
            [f"Only the floating leg pays: you {'pay' if recv else 'receive'} {fmt_eur(float_amt, False)}; the fixed leg is annual, so there is nothing to net yet",
             f"A net payment of fixed less floating: you {'receive' if recv else 'pay'} the difference",
             "Nothing: both legs pay together at the end of the year",
             f"Both legs pay in full, {fmt_eur(float_amt, False)} and a half-year of fixed, with no netting"],
            "With a semi-annual floating leg against an annual fixed leg, the floating leg pays alone at 6M. Payments are netted only on dates when both legs pay "
            "(every 12 months), which is why a swap's cash flows and its funding needs are not smooth."),
    ]
    solution = [
        f"Floating: {days} actual days between {f1.start:%d-%b-%Y} and {f1.end:%d-%b-%Y}. Payment = {eur_m(notional)} x {fixing:.5f} x {days}/360 = {fmt_eur(float_amt, False)}.",
        f"Fixed: 30E/360 = {d360}/360 = {frac:.5f} of a year (every month counts 30 days; the end day is capped at 30). "
        f"Payment = {eur_m(notional)} x {strike:.5f} x {frac:.5f} = {fmt_eur(fixed_amt, False)}, versus {fmt_eur(naive_fixed, False)} for a clean year.",
        "ACT/360 counts the real days over a 360-day year, which is why a floating leg pays slightly more than 'half a year' of the same rate; 30E/360 "
        "treats every month as equal, so a regular fixed coupon is the same each year apart from date adjustments.",
        "The dates here are the adjusted business days: a period that starts or ends on a weekend or holiday is moved, and the accrual follows the moved dates.",
    ]
    return QuestionBody(stem, parts, solution, {"swap": swap, "days": days, "float_amt": float_amt, "fixed_amt": fixed_amt, "frac": frac, "fixing": fixing, "mkt": mkt})


# --------------------------------------------------------------------------------------------------------------------- FRA settlement

_FRA_WINDOWS = ((3, 6), (6, 9), (9, 12), (3, 9), (6, 12), (12, 18), (12, 15))


@template("swaps.fra_settlement", skill="swaps.fra", difficulty=2, kind="calculation")
def fra_settlement(rng: random.Random) -> QuestionBody:
    """FRA mechanics: cash settles at the START of the period, discounted; value before the fixing; who gains."""
    for _ in range(300):
        mkt = random_market(rng)
        start, end = rng.choice(_FRA_WINDOWS)
        side = rng.choice(list(Side))
        notional = rng.choice([50, 100, 250, 500, 1000]) * 1e6
        template_fra = FRA.new(side, notional, 0.0, mkt.spot, start, end)
        fwd = template_fra.par_rate(mkt)
        k = round(fwd + rng.choice([-1, 1]) * rng.choice([10, 15, 20, 30]) * 1e-4, 5)
        fix = round(k + rng.choice([-1, 1]) * rng.choice([10, 15, 20, 25, 35]) * 1e-4, 5)
        if k > 0.002 and fix > 0.002:
            break
    fra = FRA.new(side, notional, k, mkt.spot, start, end)
    p = fra.period
    days = (p.end - p.start).days
    tau = days / 360.0
    settle = side.sign * notional * tau * (k - fix) / (1.0 + fix * tau)          # + = you receive
    undiscounted = side.sign * notional * tau * (k - fix)
    f_now = round(fra.forward(mkt), 5)
    df_start = round(mkt.ois.df(p.start), 5)
    value_now = side.sign * notional * tau * (k - f_now) / (1.0 + f_now * tau) * df_start
    payer = side is Side.PAY
    receives = settle > 0
    tenor = "3M" if end - start == 3 else "6M"

    stem = (
        f"You {'pay' if payer else 'receive'} the fixed rate {pct(k, 3)} on a {eur_m(notional)} {start}x{end} FRA on {tenor} Euribor. "
        f"The accrual period runs {p.start:%d-%b-%Y} to {p.end:%d-%b-%Y} ({days} days, ACT/360).\n"
        f"Today the market forward rate for the period is {pct(f_now, 3)}, and the discount factor to {p.start:%d-%b-%Y} is {df_start:.5f}."
    )
    parts = [
        NumericPart(f"{tenor} Euribor then fixes at {pct(fix, 3)} on {p.start:%d-%b-%Y}. What is your settlement (EUR, + = you receive)?",
                    settle, Tolerance(rel=0.025), "EUR", approx=undiscounted, approx_label="notional x days/360 x (rate difference), undiscounted",
                    sign_hint="A FRA payer gains when the fixing is above the FRA rate; the receiver when it is below.",
                    note="notional x tau x (fixing - K) / (1 + fixing x tau), from the payer's side"),
        shuffled_choice(
            rng, "When is the FRA settled, and why is the amount divided by (1 + fixing x tau)?",
            ["At the START of the period, when the fixing is known; the interest difference would normally be paid at the end, so it is discounted back at the fixing rate",
             "At the END of the period, when the interest is paid; the divisor adjusts for compounding",
             "At the start, and the amount is not discounted because the fixing is already known",
             "Daily, as the forward rate changes; the divisor is a margin factor"],
            "A FRA settles in cash on the fixing date (start of the loan period). The interest difference accrues over the period, but is paid up front, so the "
            "payment is the present value, at the fixing rate, of (fixing - K) x tau x N."),
        NumericPart("Before the fixing, what is the FRA worth to you today (EUR)?", value_now, Tolerance(rel=0.03, abs=notional * tau * 0.4e-4),
                    "EUR", note="discounted settlement at today's forward, then discounted to today",
                    sign_hint="Compare the FRA rate you locked with today's forward: which side is in the money?"),
    ]
    solution = [
        f"tau = {days}/360 = {tau:.5f}. Settlement = {'+' if payer else '-'}{eur_m(notional)} x {tau:.5f} x ({fix:.5f} - {k:.5f}) / (1 + {fix:.5f} x {tau:.5f}) = {fmt_eur(settle)}: "
        f"{'you receive' if receives else 'you pay'} {fmt_eur(abs(settle), False)} on {p.start:%d-%b-%Y}. "
        f"Without the discounting divisor it would be {fmt_eur(undiscounted)} ({(undiscounted / settle - 1) * 100:+.1f}% off).",
        f"Today the market forward {pct(f_now, 3)} is {'above' if f_now > k else 'below'} your FRA rate {pct(k, 3)}, so as {'payer' if payer else 'receiver'} you are "
        f"{'ahead' if value_now > 0 else 'behind'}: value = {'+' if payer else '-'}N x tau x ({f_now:.5f} - {k:.5f}) / (1 + {f_now:.5f} x {tau:.5f}) x {df_start:.5f} = {fmt_eur(value_now)} "
        f"(engine: {fmt_eur(fra.pv(mkt))}).",
        "A FRA is a one-period forward-starting swap: its whole risk is the single forward rate, which is why a FRA DV01 is only about N x tau x 1bp.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "fra": fra, "settle": settle, "undiscounted": undiscounted, "value_now": value_now, "fix": fix,
                                                 "f_now": f_now, "df_start": df_start, "k": k, "tau": tau})


# --------------------------------------------------------------------------------------------------------------------- forward swaps, the other way round

@template("swaps.forward_start_inverse", skill="swaps.forward_start", difficulty=2, kind="calculation")
def forward_start_inverse(rng: random.Random) -> QuestionBody:
    """Given the spot a-year swap and the a-by-b forward, recover the spot b-year swap, and read a forward swap as two spot swaps."""
    from .swaps import _FORWARD_PAIRS
    for _ in range(300):
        mkt = random_market(rng)
        a, b = rng.choice(_FORWARD_PAIRS)
        sa, sb = par_irs(Side.RECEIVE, 1.0, a, mkt), par_irs(Side.RECEIVE, 1.0, b, mkt)
        fwd = par_irs(Side.RECEIVE, 1.0, b - a, mkt, start_years=a)
        aa, ab = round(sa.annuity(mkt), 2), round(sb.annuity(mkt), 2)
        ra, f = round(sa.par_rate(mkt), 5), round(fwd.par_rate(mkt), 5)
        exact = (ra * aa + f * (ab - aa)) / ab              # S_b A_b = S_a A_a + F (A_b - A_a), solved for S_b
        naive = (a * ra + (b - a) * f) / b
        if abs(naive - exact) > 0.0002:                     # the year-weighted shortcut must be visibly wrong
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a forward-start case")
    bump = rng.choice([3, 4, 5, 6])
    d_sb = bump * (ab - aa) / ab
    name = f"{a}y{b - a}y"
    stem = (
        f"EUR IRS (6M Euribor) data, with annuities (PV of 1 per year of fixed payments):\n"
        f"  Spot {a}Y par rate: {pct(ra, 3)}   annuity {aa:.2f}\n"
        f"  The {name} forward swap rate (starts in {a} years, runs {b - a} years): {pct(f, 3)}\n"
        f"  Spot {b}Y annuity: {ab:.2f}"
    )
    steeper = f > exact
    parts = [
        NumericPart(f"What spot {b}Y par rate is consistent with these numbers (in %)?", exact * 100, Tolerance(rel=0, abs=0.008), "%",
                    approx=naive * 100, approx_label=f"year-weighted average of {a}Y and the {name}", accept_approx=False,
                    note="the annuities are the weights: S_b x A_b = S_a x A_a + F x (A_b - A_a)"),
        NumericPart(f"The {name} forward rate rises {bump}bp with the spot {a}Y rate unchanged. By how much does the spot {b}Y rate rise (bp)?", d_sb,
                    Tolerance(rel=0.04, abs=0.05), "bp",
                    note="the forward is only the share (A_b - A_a)/A_b of the longer swap"),
        shuffled_choice(
            rng, f"A €100m {name} forward-starting receiver has the same par-rate risk as which pair of spot swaps?",
            [f"Receive €100m {b}Y and pay €100m {a}Y (equal notionals)",
             f"Receive €100m {b}Y and pay a {a}Y swap with the same DV01",
             f"Receive €100m {a}Y and pay €100m {b}Y",
             f"Receive €100m {b - a}Y spot"],
            f"A forward swap's value is the longer swap minus the shorter swap with the same fixed rate and notional: its annuity is A{b} - A{a}, and the rate that "
            "makes it fair is the annuity-weighted difference. So it carries risk to both par rates, long the longer swap and short the shorter at equal NOTIONAL."),
        shuffled_choice(
            rng, f"Is the {name} forward rate above or below the spot {b}Y rate here?",
            ["Above: the later years are priced higher than the average" if steeper else "Below: the later years are priced lower than the average",
             "Below: the later years are priced lower than the average" if steeper else "Above: the later years are priced higher than the average",
             "Equal: forward-starting swaps always match the spot rate"],
            "A spot swap is a blend of the early and later years, so the forward (later years only) is above the spot rate on a rising curve and below it on a falling one."),
    ]
    solution = [
        f"The {b}Y swap is the {a}Y swap followed by the {name}: S{b} x A{b} = S{a} x A{a} + F x (A{b} - A{a}), so "
        f"S{b} = ({pct(ra, 3)} x {aa:.2f} + {pct(f, 3)} x {ab - aa:.2f}) / {ab:.2f} = {exact * 100:.3f}%.",
        f"Year-weighting would give {naive * 100:.3f}%: wrong because the earlier years carry more annuity (they are discounted less).",
        f"A move of {bump}bp in the forward moves S{b} by {bump} x {ab - aa:.2f}/{ab:.2f} = {d_sb:.2f}bp, not by {bump * (b - a) / b:.2f}bp.",
        "The same weights give the hedge: a forward swap is long the longer spot swap and short the shorter one at equal notional, not equal DV01.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "a": a, "b": b, "ra": ra, "f": f, "aa": aa, "ab": ab, "exact": exact, "naive": naive, "d_sb": d_sb, "bump": bump})


# --------------------------------------------------------------------------------------------------------------------- 3M and 6M projection curves

@template("basis.tenor_compounding", skill="swaps.basis", difficulty=2, kind="calculation")
def tenor_compounding(rng: random.Random) -> QuestionBody:
    """Two 3M Euribor periods compound to less than one 6M Euribor period: the gap is the tenor premium the basis swap trades."""
    from ...engine.dates import TARGET, add_months
    for _ in range(300):
        mkt = random_market(rng)
        start = rng.choice([0, 3, 6, 12])
        d0, d1, d2 = (TARGET.adjust(add_months(mkt.spot, start + k)) for k in (0, 3, 6))
        p3, p6 = mkt.projection("E3M"), mkt.projection("E6M")
        f1, f2, f6 = round(p3.forward_rate(d0, d1), 5), round(p3.forward_rate(d1, d2), 5), round(p6.forward_rate(d0, d2), 5)
        t1, t2, t6 = (d1 - d0).days / 360, (d2 - d1).days / 360, (d2 - d0).days / 360
        comp = ((1 + f1 * t1) * (1 + f2 * t2) - 1) / t6
        prem = (f6 - comp) * 1e4
        if prem > 1.2 and abs(comp - (f1 + f2) / 2) > 0.00008:
            break
    window = "the 6 months from now" if start == 0 else f"the 6M period starting in {start} months"
    stem = (
        f"For {window} ({d0:%d-%b-%Y} to {d2:%d-%b-%Y}) the curves give these forward rates (simple, ACT/360):\n"
        f"  3M Euribor, first quarter: {f1 * 100:.3f}%   3M Euribor, second quarter: {f2 * 100:.3f}%\n"
        f"  6M Euribor for the whole period: {f6 * 100:.3f}%\n"
        f"The two quarters are {(d1 - d0).days} and {(d2 - d1).days} days."
    )
    parts = [
        NumericPart("Rolling the 3M twice, what 6M simple rate (ACT/360, in %) do you earn over the whole period?", comp * 100, Tolerance(rel=0, abs=0.004), "%",
                    approx=(f1 + f2) / 2 * 100, approx_label="the plain average of the two 3M rates", accept_approx=False,
                    note="(1 + f1 x t1)(1 + f2 x t2) - 1, divided by the 6M year fraction"),
        NumericPart("How many bp does the 6M rate exceed the rolled 3M (bp)?", prem, Tolerance(rel=0.15, abs=0.35), "bp", sign_hint="The 6M rate is the higher one.",
                    note="6M forward less the compounded 3M rate"),
        shuffled_choice(
            rng, "What does that gap represent, and who gains if it widens?",
            ["The tenor premium (credit and liquidity) that 6M lending demands over rolling 3M; a payer of the 3M+spread leg against 6M gains if it widens",
             "A convexity adjustment, which is paid to the holder of the 3M leg",
             "A mistake in the curves: two 3M periods must compound exactly to the 6M rate",
             "The central bank's expected rate path, which shifts the 6M rate over the 3M"],
            "A 6M Euribor loan is riskier and less liquid than two consecutive 3M loans, so 6M fixings embed a premium; a 3M+spread vs 6M basis swap trades that premium. "
            "Paying the 3M+spread leg (receiving 6M) is long the basis in this project's convention: it gains when the spread widens."),
    ]
    solution = [
        f"Compounded 3M: (1 + {f1:.5f} x {t1:.4f})(1 + {f2:.5f} x {t2:.4f}) - 1 = {((1 + f1 * t1) * (1 + f2 * t2) - 1) * 100:.4f}% over the period; / {t6:.4f} = {comp * 100:.3f}% as a 6M simple rate. "
        f"The plain average of the two quarters would give {(f1 + f2) / 2 * 100:.3f}%, ignoring that the first quarter's interest earns interest in the second.",
        f"The 6M forward is {f6 * 100:.3f}%, {prem:.1f}bp above. That is the tenor premium, close to the quoted 3s6s basis for a swap over the same dates.",
        "Because one fixing is for six months and the other two are for three, a 3M leg needs a positive spread to match a 6M leg, and the basis widens when credit or liquidity stress raises the premium for lending longer.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "f1": f1, "f2": f2, "f6": f6, "comp": comp, "prem": prem, "t1": t1, "t2": t2, "t6": t6, "start": start})
