"""Rates-mathematics templates: bootstrapping, discount factors and forwards, interpolation, and the policy path implied by OIS.

Two kinds of curve appear here, and every stem says which:
  * a STYLISED annual curve (bootstrapping, interpolation): fixed payments once a year with accrual exactly 1.0, one curve for discounting
    and forwards, so the arithmetic can be done by hand. Whole years are 365 days, which makes engine.curve.Curve's ACT/365F zero and
    annual-forward rates exact. The answers come from that engine class, not from a second implementation of the formulas.
  * the engine's full EUR market (ACT/360 simple forwards between real TARGET dates).
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from ...engine.curve import Curve
from ...engine.dates import TARGET, add_months
from ..market import pct, random_market, random_trade_date
from ..model import NumericPart, QuestionBody, Tolerance, shuffled_choice
from ..registry import template

TOL_DF = 0.00005           # a hand calculation carried to 5 decimals of a discount factor


def bootstrap_annual(par: list[float]) -> list[float]:
    """Discount factors for 1..n years from annual par swap rates: DF_k = (1 - S_k x sum_{i<k} DF_i) / (1 + S_k)."""
    dfs: list[float] = []
    annuity = 0.0
    for s in par:
        df = (1.0 - s * annuity) / (1.0 + s)
        dfs.append(df)
        annuity += df
    return dfs


def par_rates_from(dfs: list[float]) -> list[float]:
    """The inverse: S_k = (1 - DF_k) / sum_{i<=k} DF_i."""
    out, annuity = [], 0.0
    for df in dfs:
        annuity += df
        out.append((1.0 - df) / annuity)
    return out


def annual_curve(anchor, dfs: list[float]) -> Curve:
    """Nodes at exactly 1, 2, ... years (365 days each), so ACT/365F year fractions are whole numbers."""
    return Curve(anchor, tuple(anchor + timedelta(days=365 * (i + 1)) for i in range(len(dfs))), tuple(dfs))


def _yr(anchor, k: int):
    return anchor + timedelta(days=365 * k)


# ---------------------------------------------------------------------------------------------------------------- bootstrapping

@template("math.bootstrap_par_curve", skill="math.bootstrapping", difficulty=2, kind="calculation")
def bootstrap_par_curve(rng: random.Random) -> QuestionBody:
    """Par rates to discount factors (the bootstrap), or the reverse: the same information read in either direction."""
    n = rng.choice([3, 4, 4])
    reverse = rng.random() < 0.4
    for _ in range(2000):
        front = rng.uniform(0.010, 0.036)
        a = rng.choice([-1, 1, 1]) * rng.uniform(0.005, 0.016)
        par = [round(front + a * (1 - math.exp(-k / 1.5)), 4) for k in range(n)]
        if min(par) < 0.004:
            continue
        dfs = bootstrap_annual(par)
        if reverse:
            dfs = [round(x, 5) for x in dfs]                                   # the factors as printed; the par rates are then derived from them
            par = par_rates_from(dfs)
        naive = (1 + par[-1]) ** -n
        zero_n = dfs[-1] ** (-1.0 / n) - 1.0
        if abs(naive - dfs[-1]) > 2.5 * TOL_DF and abs(zero_n - par[-1]) > 6e-5:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a bootstrap with a clear lesson")
    anchor = random_trade_date(rng)
    cv = annual_curve(anchor, dfs)
    zero = cv.zero_rate(_yr(anchor, n))
    fwd = cv.annual_forward(_yr(anchor, n - 1), _yr(anchor, n))
    higher_zero = zero > par[-1]
    kind = "fixed leg paid ANNUALLY, accrual exactly 1.0 per year; one curve for discounting and forwards; the floating leg is worth 1 - DF at maturity"
    if not reverse:
        rows = "\n".join(f"  {k + 1}Y: {pct(s, 2)}" for k, s in enumerate(par))
        stem = (f"Par swap rates from a stylised EUR curve ({kind})\n{rows}\n"
                "Bootstrap the discount factors one maturity at a time: a par swap has zero value, so fixed leg = floating leg.")
        lead = [
            NumericPart("What is the 2-year discount factor? (use the 1-year factor first)", dfs[1], Tolerance(rel=0, abs=TOL_DF), "df",
                        note="DF1 = 1/(1+S1); then S2 x (DF1 + DF2) = 1 - DF2"),
            NumericPart(f"What is the {n}-year discount factor?", dfs[-1], Tolerance(rel=0, abs=TOL_DF), "df", approx=naive,
                        approx_label=f"the tempting shortcut 1/(1+S{n})^{n}", accept_approx=False,
                        note="the annuity of the earlier years is already known"),
        ]
    else:
        rows = "\n".join(f"  {k + 1}Y: {df:.5f}" for k, df in enumerate(dfs))
        stem = (f"Discount factors from a stylised EUR curve ({kind})\n{rows}\n"
                "A par swap rate is the fixed rate that makes the fixed leg equal the floating leg.")
        lead = [
            NumericPart("What is the 2-year par swap rate (in %)?", par[1] * 100, Tolerance(rel=0, abs=0.005), "%", note="(1 - DF2) / (DF1 + DF2)"),
            NumericPart(f"What is the {n}-year par swap rate (in %)?", par[-1] * 100, Tolerance(rel=0, abs=0.005), "%",
                        approx=zero * 100, approx_label=f"the {n}-year zero rate", accept_approx=False,
                        note=f"(1 - DF{n}) divided by the sum of all {n} discount factors"),
        ]
    parts = lead + [
        NumericPart(f"What is the {n}-year zero rate (annually compounded, in %)?", zero * 100, Tolerance(rel=0, abs=0.004), "%",
                    approx=par[-1] * 100, approx_label=f"treating the {n}-year par rate as the zero rate", accept_approx=False,
                    note=f"DF{n}^(-1/{n}) - 1"),
        NumericPart(f"What 1-year rate does the curve imply for the year starting in {n - 1} years (the {n - 1}y1y forward, in %)?",
                    fwd * 100, Tolerance(rel=0, abs=0.02), "%", note=f"DF{n - 1} / DF{n} - 1"),
        shuffled_choice(
            rng, f"Which is higher on this curve, the {n}-year zero rate or the {n}-year par swap rate?",
            [f"The zero rate ({zero * 100:.3f}% vs {par[-1] * 100:.3f}%)" if higher_zero else f"The par rate ({par[-1] * 100:.3f}% vs {zero * 100:.3f}%)",
             f"The par rate ({par[-1] * 100:.3f}% vs {zero * 100:.3f}%)" if higher_zero else f"The zero rate ({zero * 100:.3f}% vs {par[-1] * 100:.3f}%)",
             "They are equal: a par swap rate IS the zero rate for its maturity"],
            "A par rate is a blend of the zero rates for every payment date, weighted by discount factors, so on a rising curve it sits "
            "below the longest zero rate (the early, lower zero rates pull it down) and on a falling curve above it."),
    ]
    steps = "; ".join(f"DF{k + 1} = {dfs[k]:.5f}" for k in range(n))
    if reverse:
        solution = [
            "The fixed leg is S x (DF1 + ... + DFn) and the floating leg is 1 - DFn, so S_n = (1 - DF_n) / (DF1 + ... + DF_n).",
            f"S2 = (1 - {dfs[1]:.5f}) / ({dfs[0]:.5f} + {dfs[1]:.5f}) = {par[1] * 100:.3f}%;  S{n} = (1 - {dfs[-1]:.5f}) / {sum(dfs):.5f} = {par[-1] * 100:.3f}%.",
        ]
    else:
        solution = [
            f"DF1 = 1 / (1 + {par[0]:.4f}) = {dfs[0]:.5f}.",
            f"DF2: {par[1]:.4f} x (DF1 + DF2) = 1 - DF2  =>  DF2 = (1 - {par[1]:.4f} x {dfs[0]:.5f}) / (1 + {par[1]:.4f}) = {dfs[1]:.5f}.",
            f"In general DF_k = (1 - S_k x sum of the earlier DFs) / (1 + S_k). Result: {steps}.",
            f"The shortcut 1/(1+S{n})^{n} = {naive:.5f} is wrong by {abs(naive - dfs[-1]):.5f}: it discounts every cash flow at the {n}-year par rate, "
            "but the early coupons are really discounted at the lower or higher short rates.",
        ]
    solution += [
        f"Zero rate = DF{n}^(-1/{n}) - 1 = {zero * 100:.3f}%; forward = DF{n - 1}/DF{n} - 1 = {fwd * 100:.3f}%. "
        "Par rates, zero rates and forwards carry the same information; each is a different average of the same one-year forwards.",
    ]
    return QuestionBody(stem, parts, solution, {"par": par, "dfs": dfs, "n": n, "zero": zero, "fwd": fwd, "naive": naive, "reverse": reverse})


# ---------------------------------------------------------------------------------------------------------------- DF <-> forward

_WINDOWS = ((3, 6), (6, 12), (3, 9), (6, 9), (9, 12), (12, 24), (6, 18))


@template("math.df_forward_solve", skill="math.forward_rates", difficulty=2, kind="calculation")
def df_forward_solve(rng: random.Random) -> QuestionBody:
    """Forward from two discount factors, then the discount factor from a forward: the same identity used in both directions."""
    for _ in range(500):
        mkt = random_market(rng)
        a, b = rng.choice(_WINDOWS)
        d_a, d_b = TARGET.adjust(add_months(mkt.spot, a)), TARGET.adjust(add_months(mkt.spot, b))
        dfa, dfb = round(mkt.ois.df(d_a), 5), round(mkt.ois.df(d_b), 5)
        shown = Curve(mkt.anchor, (d_a, d_b), (dfa, dfb))
        fwd = shown.forward_rate(d_a, d_b)
        delta = rng.choice([-1, 1]) * rng.uniform(0.0010, 0.0035)
        f2 = round(fwd + delta, 4)
        days = (d_b - d_a).days
        tau = days / 360.0
        dfb2 = dfa / (1.0 + f2 * tau)
        zb = (1.0 / dfb - 1.0) * 360.0 / (d_b - mkt.anchor).days
        if abs(dfb2 - dfb) > 1.5e-4 and abs(fwd - zb) > 0.0002 and f2 > 0:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a clear forward / discount-factor case")
    rising = fwd > zb
    stem = (
        "Discount factors from the valuation date on a EUR curve, with simple rates ACT/360:\n"
        f"  {d_a:%d-%b-%Y} ({(d_a - mkt.anchor).days} days): {dfa:.5f}\n"
        f"  {d_b:%d-%b-%Y} ({(d_b - mkt.anchor).days} days): {dfb:.5f}\n"
        f"The forward period between the two dates is {days} days."
    )
    parts = [
        NumericPart(f"What simple forward rate (ACT/360, in %) do these discount factors imply for the {days}-day period?", fwd * 100,
                    Tolerance(rel=0, abs=0.025), "%", note="(DF_a / DF_b - 1) / (days / 360)"),
        NumericPart(f"A dealer quotes the forward for that same period at {f2 * 100:.2f}%. Keeping the first discount factor, what second "
                    "discount factor does that quote imply?", dfb2, Tolerance(rel=0, abs=0.00006), "df", approx=dfb, approx_label="the curve's own discount factor", accept_approx=False,
                    note="DF_b = DF_a / (1 + F x days/360)"),
        NumericPart(f"What simple zero rate (ACT/360, in %) does the curve give from the valuation date to {d_b:%d-%b-%Y}?", zb * 100,
                    Tolerance(rel=0, abs=0.03), "%", note="(1 / DF - 1) / (days / 360)"),
        shuffled_choice(
            rng, "Is the forward for the period above or below that zero rate, and why?",
            ["Above: the zero rate averages in the lower earlier rates, so the later forward is higher" if rising
             else "Below: the zero rate averages in the higher earlier rates, so the later forward is lower",
             "Below: the zero rate averages in the lower earlier rates, so the later forward is higher" if rising
             else "Above: the zero rate averages in the higher earlier rates, so the later forward is lower",
             "Equal: a forward and a zero rate are the same thing over the same end date"],
            "A zero rate is an average of every forward from today to its end date; the forward is the marginal rate for the last stretch. "
            "When the curve slopes up the marginal rate is above the average, and when it slopes down it is below."),
    ]
    higher = dfb2 > dfb
    solution = [
        f"Forward = (DF_a / DF_b - 1) / (days/360) = ({dfa:.5f} / {dfb:.5f} - 1) / ({days}/360) = {fwd * 100:.3f}%.",
        f"Going the other way, DF_b = DF_a / (1 + F x days/360) = {dfa:.5f} / (1 + {f2:.4f} x {days}/360) = {dfb2:.5f}. "
        f"That is {'above' if higher else 'below'} the curve's {dfb:.5f}: a {'lower' if higher else 'higher'} forward means a "
        f"{'larger' if higher else 'smaller'} discount factor for the later date. Discount factors fall as forwards rise.",
        f"Zero rate to {d_b:%d-%b-%Y}: (1/{dfb:.5f} - 1) x 360/{(d_b - mkt.anchor).days} = {zb * 100:.3f}%.",
        "A discount factor curve is internally consistent only if the factors fall with maturity (positive forwards, for the EUR market here), "
        "and any forward you quote must be the ratio of two factors on the same curve.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "dfa": dfa, "dfb": dfb, "fwd": fwd, "f2": f2, "dfb2": dfb2, "zb": zb, "days": days})


# ---------------------------------------------------------------------------------------------------------------- interpolation

_NODE_SETS = ((2, 5, 10), (3, 7, 10), (5, 10, 30), (2, 7, 10), (5, 10, 20), (3, 6, 10), (1, 5, 10))


@template("math.interp_log_linear", skill="math.interpolation", difficulty=2, kind="calculation")
def interp_log_linear(rng: random.Random) -> QuestionBody:
    """Interpolating discount factors log-linearly (flat forwards between nodes) versus interpolating the zero rate."""
    anchor = random_trade_date(rng)
    for _ in range(500):
        a, b, c = rng.choice(_NODE_SETS)
        q = rng.randint(a + 1, b - 2) if b - a >= 3 else None
        if q is None:
            continue
        base = rng.uniform(0.016, 0.034)
        za = round(base, 4)
        zb = round(base + rng.choice([-1, 1, 1]) * rng.uniform(0.003, 0.010), 4)
        zc = round(zb + rng.choice([-1, 1]) * rng.uniform(0.002, 0.008), 4)
        if min(za, zb, zc) < 0.008:
            continue
        nodes = {t: (1 + z) ** -t for t, z in ((a, za), (b, zb), (c, zc))}
        cv = Curve(anchor, tuple(_yr(anchor, t) for t in (a, b, c)), tuple(nodes[t] for t in (a, b, c)))
        df_q = cv.df(_yr(anchor, q))
        z_lin = za + (zb - za) * (q - a) / (b - a)
        df_lin = (1 + z_lin) ** -q
        f1 = cv.annual_forward(_yr(anchor, q), _yr(anchor, q + 1))
        zq_lin1, zq_lin0 = za + (zb - za) * (q + 1 - a) / (b - a), z_lin
        f_lin = (1 + zq_lin1) ** (q + 1) / (1 + zq_lin0) ** q - 1
        r = rng.choice([q + 1, b])               # the comparison window: still inside the (a, b) interval, or the first year after node b
        if r == q + 1 and q + 2 > b:
            continue
        if r == b and b + 1 > c:
            continue
        f2 = cv.annual_forward(_yr(anchor, r), _yr(anchor, r + 1))
        inside = r == q + 1
        if abs(df_q - df_lin) > 0.0006 and abs(f1 - f_lin) > 0.0005 and (inside or abs(f2 - f1) > 0.0004):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an interpolation case")
    stem = (
        "Annually-compounded zero rates at three curve nodes (a stylised EUR curve; whole years):\n"
        f"  {a}Y: {za * 100:.2f}%     {b}Y: {zb * 100:.2f}%     {c}Y: {zc * 100:.2f}%\n"
        f"The curve is built by interpolating the LOGARITHM of the discount factor linearly in time between nodes (the standard choice, "
        "equivalent to flat forward rates between nodes)."
    )
    if inside:
        opts = ["Identical: forward rates are flat between two nodes", "Higher: forwards drift up with maturity",
                "Lower: forwards drift down with maturity", "It cannot be said without a fourth node"]
    else:
        right, wrong = ("Higher", "Lower") if f2 > f1 else ("Lower", "Higher")
        opts = [f"{right}: the forward steps to the next segment's level at the {b}Y node", "Identical: forward rates are flat between nodes",
                f"{wrong}: the forward steps the other way at the {b}Y node", "It cannot be said without a fourth node"]
    parts = [
        NumericPart(f"What is the {q}-year discount factor on this curve?", df_q, Tolerance(rel=0, abs=0.0003), "df",
                    approx=df_lin, approx_label=f"linear interpolation of the zero rate ({z_lin * 100:.3f}%)", accept_approx=False,
                    note=f"ln DF is linear in time between the {a}Y and {b}Y nodes"),
        NumericPart(f"What 1-year forward rate (in %) does the curve imply for the year starting in {q} years?", f1 * 100,
                    Tolerance(rel=0, abs=0.04), "%", approx=f_lin * 100, approx_label="the forward implied by linearly interpolated zero rates",
                    accept_approx=False, note=f"between {a}Y and {b}Y every year has the same forward"),
        shuffled_choice(
            rng, f"How does the 1-year forward starting in {r} years compare with the one starting in {q} years?",
            opts,
            "Log-linear discount factors mean one constant forward per segment between nodes: two forwards inside the same segment are "
            "identical, and the forward steps when you cross a node." if inside else
            "Between nodes the forward is flat; it moves only when you cross a node, to the level of the next segment."),
        shuffled_choice(
            rng, f"Only the {b}Y zero rate is bumped up. Between today and {c} years, which forward rates change?",
            [f"Those in the two segments either side of the {b}Y node ({a}Y-{b}Y and {b}Y-{c}Y); not those before {a}Y",
             f"Only the single forward at the {b}Y point",
             f"Every forward from today to {c} years",
             f"Only the forwards after {b}Y"],
            "Each node controls the forward rates in the segments next to it: a bump is local to those two segments, which is why a "
            "piecewise-flat curve gives clean, bucketed risk, and why the forward curve can show kinks at the nodes."),
    ]
    solution = [
        f"Discount factors at the nodes: DF{a} = {nodes[a]:.5f}, DF{b} = {nodes[b]:.5f}, DF{c} = {nodes[c]:.5f}.",
        f"Log-linear: ln DF{q} = ln DF{a} + (ln DF{b} - ln DF{a}) x ({q}-{a})/({b}-{a})  =>  DF{q} = {df_q:.5f}. "
        f"Interpolating the zero rate linearly ({z_lin * 100:.3f}%) would give {df_lin:.5f}, which is a different curve.",
        f"Forward {q}y1y = DF{q}/DF{q + 1} - 1 = {f1 * 100:.3f}%, the same for every year in the {a}Y-{b}Y segment: "
        f"(DF{a}/DF{b})^(1/{b - a}) - 1.",
        f"The year from {r}Y: {f2 * 100:.3f}%, {'the same segment so the same forward' if inside else f'across the {b}Y node, so the forward steps'}.",
        "Interpolation is a modelling choice that changes forwards, and so the risk of forward-starting trades; it is why two desks can price "
        "a 5y5y differently from identical par quotes.",
    ]
    return QuestionBody(stem, parts, solution, {"nodes": (a, b, c), "zeros": (za, zb, zc), "q": q, "r": r, "df_q": df_q, "f1": f1, "f2": f2, "df_lin": df_lin,
                                                 "f_lin": f_lin, "inside": inside})


# ---------------------------------------------------------------------------------------------------------------- policy path

@template("math.ois_policy_path", skill="math.forward_rates", difficulty=2, kind="calculation")
def ois_policy_path(rng: random.Random) -> QuestionBody:
    """What the short end of the ESTR OIS curve says about the central bank, and how to trade a different view."""
    for _ in range(500):
        mkt = random_market(rng)
        o3, o6, o12 = (mkt.quotes["OIS"][m] for m in (3, 6, 12))
        d0 = mkt.spot
        d3, d6, d12 = (TARGET.adjust(add_months(d0, m)) for m in (3, 6, 12))
        f03 = mkt.ois.forward_rate(d0, d3)
        f36 = mkt.ois.forward_rate(d3, d6)
        step_bp = (f36 - f03) * 1e4
        short = ((o6 * (d6 - d0).days - o3 * (d3 - d0).days) / (d6 - d3).days)       # the mental route: time-weighted average
        if abs(step_bp) >= 9 or abs(step_bp) <= 2.5:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a clear policy-path case")
    view_dovish = rng.random() < 0.5            # the trainee's view: MORE easing than priced (rates lower than the forwards)
    cuts = step_bp / 25.0
    if step_bp <= -9:
        priced = "cuts"
    elif step_bp >= 9:
        priced = "hikes"
    else:
        priced = "hold"
    stem = (
        "ESTR OIS par rates (single payment at maturity, compounded ESTR, ACT/360):\n"
        f"  3M: {pct(o3)}     6M: {pct(o6)}     12M: {pct(o12)}\n"
        "Treat ESTR as the policy rate (it sits a few bp below the ECB deposit rate). The ECB moves in 25bp steps."
    )
    parts = [
        NumericPart("What average ESTR (in %) does the curve imply for the 3-month window that starts in 3 months and ends in 6 months?",
                    f36 * 100, Tolerance(rel=0, abs=0.04), "%", approx=short * 100,
                    approx_label="time-weighted shortcut (6M x days6 - 3M x days3) / days(3x6)",
                    note="the 6M rate is the average of the first 3M rate and the 3x6 forward"),
        NumericPart("By how many bp is that forward above (+) or below (-) the average implied for the first 3 months?", step_bp,
                    Tolerance(rel=0.15, abs=4.0), "bp", approx=2 * (o6 - o3) * 1e4, approx_label="2 x (6M - 3M)",
                    sign_hint="Cuts priced means a negative number.", note="signed, in bp"),
        shuffled_choice(
            rng, "In terms of 25bp ECB moves, what is the market pricing between the first and the second quarter?",
            [{"cuts": f"About {abs(cuts):.1f} of a 25bp cut: easing is priced",
              "hikes": f"About {abs(cuts):.1f} of a 25bp hike: tightening is priced",
              "hold": "Essentially no change: the path is flat"}[priced],
             {"cuts": "Tightening is priced: the forward is above the first quarter's average",
              "hikes": "Easing is priced: the forward is below the first quarter's average",
              "hold": "A 25bp cut is fully priced"}[priced],
             {"cuts": "No change is priced: only term premium differs",
              "hikes": "No change is priced: only term premium differs",
              "hold": "A 25bp hike is fully priced"}[priced],
             "Nothing can be read from OIS about the policy path"],
            "An OIS forward is the market's expected average policy rate over the window (plus a small term premium). Its distance from the "
            "earlier window, in units of 25bp, reads as a probability-weighted number of moves; 0.8 of a cut can be an 80% chance of one move."),
        shuffled_choice(
            rng, f"You think policy rates will end up {'LOWER' if view_dovish else 'HIGHER'} than this 3x6 forward implies (the ECB more {'dovish' if view_dovish else 'hawkish'} than the curve), "
                 "and you want to trade only that window. Which position?",
            [f"{'Receive' if view_dovish else 'Pay'} fixed in the 3x6 forward window: {'receive' if view_dovish else 'pay'} 6M OIS, "
             f"{'pay' if view_dovish else 'receive'} 3M OIS, sized so the first 3 months cancel",
             f"{'Pay' if view_dovish else 'Receive'} fixed in the 3x6 forward window",
             f"{'Receive' if view_dovish else 'Pay'} 3M OIS only",
             f"{'Pay' if view_dovish else 'Receive'} 6M OIS outright"],
            f"If policy rates end up {'lower' if view_dovish else 'higher'} than the forward implies, the forward rate {'falls' if view_dovish else 'rises'}: you want to "
            f"{'receive' if view_dovish else 'pay'} it. The forward window is built from the 6M swap and the opposite 3M swap, so the first quarter, where you have no view, nets out."),
    ]
    solution = [
        f"3x6 forward ESTR = (DF3/DF6 - 1) x 360/days = {f36 * 100:.3f}%; the first 3 months average {f03 * 100:.3f}% (the 3M OIS rate).",
        f"Mental route: the 6M rate is the day-weighted average of the first quarter's rate and the 3x6 forward, so the forward is about "
        f"({pct(o6)} x 2 - {pct(o3)}) = {short * 100:.3f}%.",
        f"Step between the two quarters: {step_bp:+.1f}bp = {cuts:+.2f} of a 25bp move. ({'cuts priced' if priced == 'cuts' else 'hikes priced' if priced == 'hikes' else 'no clear move priced'}.)",
        f"{'Receiving' if view_dovish else 'Paying'} fixed in the window profits if realised policy rates come in {'below' if view_dovish else 'above'} the forward. A forward position "
        "isolates the meeting you have a view on; an outright 6M swap also carries the first quarter, where the path is better known.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "f36": f36, "f03": f03, "step_bp": step_bp, "view_dovish": view_dovish, "priced": priced})
