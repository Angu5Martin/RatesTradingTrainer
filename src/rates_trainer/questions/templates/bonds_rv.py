"""Bonds versus swaps: asset swaps, hedging cash with swaps, repo carry and bond carry / roll-down.

CONVENTIONS (see docs/DESIGN.md)
  * ASW = par-par asset-swap spread over the OIS curve. CHEAP bond => POSITIVE ASW. Buying the package (long bond, pay the
    bond's coupons in a swap, receive ESTR + ASW) gains when the ASW TIGHTENS (the bond richens against swaps).
  * Swap spread in the Bund-style quote (swap rate minus bond yield) is the NEGATIVE of ASW, roughly.
  * Repo/funding spread = repo rate minus ESTR; NEGATIVE = on special.

MENTAL ROUTES (carried as `approx`)
  ASW ~ bond yield - OIS par yield (bond basis); ASW01 ~ a swap DV01 of the same notional and maturity;
  yield pickup over repo ~ MV x (yield x days/365 - repo x days/360); curve roll-down ~ DV01 x (yield - yield for remaining maturity).
"""

from __future__ import annotations

import random
from dataclasses import replace

from ...engine.carry import breakeven_move, carry_roll, financing_cost
from ...engine.curve import CurveShock
from ...engine.instruments import AssetSwapPackage, FixedBond, Side
from ...engine.pnl import first_order_pnl, revalue_pnl
from ...engine.risk import Portfolio, dv01_hedge_swap, par_irs, parallel_dv01, unit_dv01
from ..market import eur_m, pct, random_bond, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template

BP = 1e-4
FACE_M = (10, 25, 50, 75, 100, 150, 200)
DV01_CONVENTION = "DV01 = P&L for a 1bp FALL in rates/yields (positive if long)."


def _bond_line(bond: FixedBond, label: str, price: float, y: float) -> str:
    n = len(bond.periods)
    return f"{label} bond, {bond.coupon * 100:.2f}% annual coupon, {n}Y to maturity: dirty price {price:.2f}, yield {pct(y)}"


# =============================================================================================================

@template("rv.asw_package", skill="rv.asw", difficulty=2)
def asw_package(rng: random.Random) -> QuestionBody:
    for _ in range(400):
        mkt = random_market(rng)
        face = rng.choice(FACE_M) * 1e6
        bond, label = random_bond(rng, mkt, face, max_abs_asw=0.0100, price_range=(92.0, 108.0))
        if abs(bond.asw) >= 12 * BP:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a bond with a meaningful ASW")
    years = len(bond.periods)
    price = bond.price(mkt)
    y = bond.yield_from_dirty(mkt.anchor, price)
    swap_rate = mkt.bond_basis_swap_rate(years)
    asw = bond.asw
    a = bond.spread_annuity(mkt)
    asw01 = face * a * BP
    swap_dv01_per_m = unit_dv01(years, mkt)
    move = rng.choice([-10, -8, -5, -3, 3, 5, 8, 10])                    # ASW change in bp (+ = widens, bond cheapens)
    pkg = AssetSwapPackage(bond, locked_spread=asw)
    pnl = AssetSwapPackage(bond.with_asw(asw + move * BP), asw).pv(mkt) - pkg.pv(mkt)
    approx_pnl = -move * asw01
    par_pnl = pkg.pv(mkt.shifted(CurveShock.parallel(25))) - pkg.pv(mkt)
    cheap = asw > 0

    stem = (
        f"{_bond_line(bond, label.capitalize(), price, y)}.\n"
        f"The OIS swap curve's par yield at {years}Y, on the same annual bond basis, is {pct(swap_rate)}. "
        f"A €1m {years}Y swap has a DV01 of about €{swap_dv01_per_m:,.0f}.\n"
        f"You buy the asset-swap package on {eur_m(face)} face: you buy the bond and pay its coupons in a swap, receiving ESTR plus the "
        f"asset-swap spread, for a total outlay of par. Convention: a CHEAP bond has a POSITIVE ASW."
    )
    parts = [
        NumericPart("What is the asset-swap spread (bp)?", asw * 1e4, Tolerance(rel=0.12, abs=3.0), "bp",
                    approx=(y - swap_rate) * 1e4, approx_label="bond yield - swap par yield",
                    sign_hint="A bond yielding more than the swap curve is cheap to it: positive ASW.",
                    note="about the bond yield minus the swap rate"),
        NumericPart("What is the package's P&L for a 1bp move in the ASW spread (EUR per bp, sign: + for a 1bp TIGHTENING)?",
                    asw01, Tolerance(rel=0.06), "EUR", approx=face / 1e6 * swap_dv01_per_m,
                    approx_label="swap DV01 of the same notional and maturity",
                    note="notional x annuity x 1bp: about a swap DV01"),
        NumericPart(f"The bond's ASW then {'widens' if move > 0 else 'tightens'} by {abs(move)}bp (the bond "
                    f"{'cheapens' if move > 0 else 'richens'} against swaps). What is the package's P&L?",
                    pnl, Tolerance(rel=0.04), "EUR", approx=approx_pnl,
                    sign_hint="You are long the bond against swaps: you gain when it richens (ASW tightens), lose when it cheapens.",
                    note="-(ASW change) x ASW01"),
        shuffled_choice(
            rng, "Instead rates rise 25bp in parallel and the ASW is unchanged. The package's P&L is:",
            ["About zero: an at-market par-par package is a spread position, with almost no outright rate risk",
             f"A loss of roughly {fmt_eur(25 * asw01, False)}: you are long a bond",
             f"A gain of roughly {fmt_eur(25 * asw01, False)}: you pay fixed in the swap",
             "Positive only if the ASW is negative"],
            f"The bond's rate risk is offset by the fixed payments in the swap, and the upfront exchange is at par, so the package is "
            f"worth par whatever the curve does (exact P&L {fmt_eur(par_pnl)}). What is left is the spread: that is why traders quote "
            "and risk ASW packages in ASW01."),
    ]
    refine = (y - swap_rate) * (price * bond.modified_duration(mkt.anchor, y) / 100) / a * 1e4
    solution = [
        f"ASW = (swap-curve value of the bond - dirty price) / spread annuity = {asw * 1e4:+.1f}bp "
        f"({'cheap' if cheap else 'rich'} to swaps: the bond yields {'more' if cheap else 'less'} than the swap curve).",
        f"Quick rule: yield - swap rate = {(y - swap_rate) * 1e4:+.1f}bp. It is a little off because the bond's dollar duration "
        f"({price / 100 * bond.modified_duration(mkt.anchor, y):.2f}) is not the spread annuity ({a:.2f}); scaling by their ratio gives {refine:+.1f}bp. "
        "The further the bond is from par, the bigger the gap.",
        f"ASW01 = N x annuity x 1bp = {eur_m(face)} x {a:.2f} x 0.0001 = {fmt_eur(asw01, False)} (a swap of the same size has DV01 "
        f"{fmt_eur(face / 1e6 * swap_dv01_per_m, False)}).",
        f"ASW {'widens' if move > 0 else 'tightens'} {abs(move)}bp => {'-' if move > 0 else '+'}{abs(move)} x ASW01 = {fmt_eur(approx_pnl)}; "
        f"full revaluation {fmt_eur(pnl)}.",
        "Contrast: the 'swap spread' quoted for Bund-style bonds is swap rate MINUS bond yield, i.e. about the negative of ASW. "
        "Buying the package is long the bond against swaps: it gains when the swap spread (swap - bond) WIDENS = ASW TIGHTENS.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "bond": bond, "price": price, "y": y, "swap_rate": swap_rate, "asw01": asw01, "a": a, "pkg": pkg,
        "move": move, "pnl": pnl, "approx_pnl": approx_pnl, "par_pnl": par_pnl, "swap_dv01_per_m": swap_dv01_per_m})


# =============================================================================================================

@template("rv.bond_swap_hedge", skill="rv.cash_vs_swaps", difficulty=3)
def bond_swap_hedge(rng: random.Random) -> QuestionBody:
    """Hedge a bond's outright rate risk with a swap, and see what is left: the cash-vs-swaps (ASW) spread."""
    for _ in range(400):
        mkt = random_market(rng)
        face = rng.choice(FACE_M) * 1e6
        bond, label = random_bond(rng, mkt, face * rng.choice([1, 1, -1]), max_abs_asw=0.0060, price_range=(90.0, 112.0))
        if len(bond.periods) >= 5:
            break
    years = len(bond.periods)
    long_ = bond.notional > 0
    price = bond.price(mkt)
    y = bond.yield_from_dirty(mkt.anchor, price)
    d_mod = bond.modified_duration(mkt.anchor, y)
    mv = bond.pv(mkt)
    dv01 = parallel_dv01(bond, mkt)
    dv01_mental = mv * d_mod * BP
    hedge = dv01_hedge_swap(dv01, years, mkt)
    hedge_signed = hedge.notional if hedge.side is Side.RECEIVE else -hedge.notional
    per_m = unit_dv01(years, mkt)
    book = Portfolio([bond, hedge])
    move = rng.choice([-8, -5, -3, 3, 5, 8])                              # ASW change in bp (+ = bond cheapens)
    cheapened = bond.with_asw(bond.asw + move * BP)
    spread_pnl = Portfolio([cheapened, hedge]).pv(mkt) - book.pv(mkt)
    asw01 = abs(bond.notional) * bond.spread_annuity(mkt) * BP
    rates_pnl = revalue_pnl(book, mkt, CurveShock.parallel(10))
    verb = "long" if long_ else "short"
    # The yield-DV01 (market value x duration) and the engine's constant-ASW DV01 differ by a convexity effect that grows with
    # ASW and with maturity (measured: a 2-3% baseline plus gap/ASW of about 0.00015 + 0.00007 x years per bp, worst case plus margin).
    dv01_tol = 0.03 + abs(bond.asw * 1e4) * (0.00015 + 0.00007 * years)

    stem = (
        f"You are {verb} {eur_m(abs(bond.notional))} face of a {label} bond, {bond.coupon * 100:.2f}% coupon, {years}Y: dirty price {price:.2f}, "
        f"yield {pct(y)}, modified duration {d_mod:.2f}. Market value {fmt_eur(mv, False)}.\n"
        f"You hedge the outright rate risk with an at-market {years}Y EUR IRS. A €1m {years}Y swap has a DV01 of €{per_m:,.0f}.\n"
        f"{DV01_CONVENTION}"
    )
    parts = [
        NumericPart("What is the DV01 of the bond position?", dv01, Tolerance(rel=dv01_tol), "EUR", approx=dv01_mental,
                    approx_label="market value x modified duration x 1bp",
                    sign_hint="Long bond: positive. Short bond: negative.", note="market value x modified duration x 1bp"),
        NumericPart(f"What {years}Y swap notional DV01-hedges it? (+ = receive fixed, - = pay fixed)", hedge_signed,
                    Tolerance(rel=dv01_tol), "EUR", approx=(-dv01_mental / per_m * 1e6),
                    approx_label="bond DV01 (market value x duration) / swap DV01 per €1m",
                    sign_hint="Hedge a LONG bond by PAYING fixed (negative); a short bond by receiving (positive).",
                    note="e.g. -85m"),
        NumericPart(f"Hedged. The bond now cheapens {abs(move)}bp against swaps (ASW {'widens' if move > 0 else 'tightens'} "
                    f"{abs(move)}bp, swap rates unchanged). What is the P&L of the hedged book?", spread_pnl,
                    Tolerance(rel=0.05), "EUR", approx=-(1 if long_ else -1) * move * abs(bond.notional) / 1e6 * per_m,
                    approx_label="-(position) x ASW change x swap DV01 of the same notional",
                    sign_hint="A long bond loses when it cheapens against swaps; a short bond gains.",
                    note="a bp of ASW on €X face is worth a swap DV01 on €X"),
        shuffled_choice(
            rng, "Instead all rates rise 10bp together and the bond's ASW is unchanged. The hedged book's P&L is:",
            ["Close to zero: the DV01 hedge removes the outright rate risk, leaving only a small convexity residual",
             "Large: the hedge only works for changes in the ASW",
             f"Roughly {fmt_eur(10 * abs(dv01), False)} in your favour",
             f"Roughly {fmt_eur(10 * abs(dv01), False)} against you"],
            f"The book is DV01-neutral, so a parallel move nets to about nothing (exact {fmt_eur(rates_pnl)}). What it does NOT hedge is "
            f"the cash-versus-swaps spread: each bp of ASW is worth {fmt_eur(asw01, False)} to this position."),
    ]
    solution = [
        f"Bond DV01 = MV x modified duration x 1bp = {fmt_eur(abs(mv), False)} x {d_mod:.2f} x 0.0001 = {fmt_eur(dv01_mental)} "
        f"(engine, shifting the swap curve with ASW fixed: {fmt_eur(dv01)}).",
        f"Hedge notional = |DV01| / swap DV01 per €1m = {fmt_eur(abs(dv01), False)} / €{per_m:,.0f} per €1m = {eur_m(hedge.notional)}, "
        f"{'pay' if hedge.side is Side.PAY else 'receive'} fixed. It is {'larger' if hedge.notional > abs(bond.notional) else 'smaller'} than the bond's "
        f"face because the swap's DV01 per euro of notional is {'smaller' if hedge.notional > abs(bond.notional) else 'larger'} than the bond's "
        f"(price {price:.1f} and duration {d_mod:.1f} vs a par swap).",
        f"What is left is the spread: ASW01 = {fmt_eur(asw01, False)} per bp (about the DV01 of a swap on the same notional). A {abs(move)}bp "
        f"{'widening' if move > 0 else 'tightening'} is {fmt_eur(spread_pnl)} for this book.",
        "A subtlety: the engine holds the bond's ASW constant when rates move, and the spread annuity shrinks when rates rise, so the bond's DV01 "
        f"is a touch SMALLER than market value x duration (here {fmt_eur(dv01)} vs {fmt_eur(dv01_mental)}); the gap grows with the ASW.",
        "This is cash-versus-swaps: a bond hedged with swaps is a bet on the ASW, nothing else. If you want to hedge the ASW too you need another cash bond or a "
        "futures/repo structure; that is the next part of the curriculum.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "bond": bond, "hedge": hedge, "book": book, "dv01": dv01, "dv01_mental": dv01_mental, "per_m": per_m,
        "spread_pnl": spread_pnl, "asw01": asw01, "move": move, "rates_pnl": rates_pnl, "long": long_, "d_mod": d_mod})


# =============================================================================================================

@template("bonds.repo_carry", skill="bonds.repo", difficulty=2)
def repo_carry(rng: random.Random) -> QuestionBody:
    """Exact repo arithmetic: coupon accrual vs financing, what specialness is worth, and the breakeven repo rate."""
    mkt = random_market(rng)
    face = rng.choice(FACE_M) * 1e6
    gc_spread = rng.choice([0.0, -0.0005, -0.0010, -0.0015])
    special_by = rng.choice([0.0010, 0.0020, 0.0030, 0.0050])
    bond, label = random_bond(rng, mkt, face, funding_spread=gc_spread)
    months = rng.choice([1, 3])
    a1 = mkt.horizon_date(months=months)
    days = (a1 - mkt.anchor).days
    special = replace(bond, funding_spread=gc_spread - special_by)
    cg, cs = carry_roll(bond, mkt, a1), carry_roll(special, mkt, a1)
    price = bond.price(mkt)
    mv = bond.pv(mkt)
    estr = (mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1) * 360 / days
    period_days = (bond.periods[0].end - bond.periods[0].start).days
    accrual = face * bond.coupon * days / period_days
    financing_gc = financing_cost(bond, mkt, a1)
    improvement = cs.carry - cg.carry
    breakeven_repo = accrual * 360 / (mv * days)                          # all-in repo rate at which carry is zero
    current_yield = bond.coupon / (price / 100)
    years = len(bond.periods)

    stem = (
        f"You buy {eur_m(face)} face of a {label} bond, {bond.coupon * 100:.2f}% annual coupon, {years}Y, at a dirty price of {price:.2f} "
        f"(market value {fmt_eur(mv, False)}), funded in repo for {months} month{'s' if months > 1 else ''} ({days} days).\n"
        f"ESTR averages {pct(estr, 3)} over the period. General-collateral (GC) repo is ESTR {gc_spread * 1e4:+.0f}bp. Repo accrues ACT/360; the coupon "
        f"accrues over its {period_days}-day period.\n"
        f"The bond is currently on special: it repos {special_by * 1e4:.0f}bp BELOW GC."
    )
    parts = [
        NumericPart("Carry funded at GC: coupon accrued minus repo financing over the period?", cg.carry,
                    Tolerance(rel=0.03, abs=mv * 1e-5 * days / 360), "EUR",
                    sign_hint="Carry is positive when the coupon accrues faster than the cash costs to borrow.",
                    note="face x coupon x days/period - market value x repo x days/360"),
        NumericPart("How much better is your carry because the bond is on special (EUR)?", improvement,
                    Tolerance(rel=0.03), "EUR", sign_hint="Cheaper financing is better carry for a long: positive.",
                    note="market value x specialness x days/360"),
        NumericPart("What all-in repo rate makes the carry exactly zero? (%)", breakeven_repo * 100,
                    Tolerance(rel=0.03, abs=0.01), "%", approx=current_yield * 100, approx_label="current yield: coupon / dirty price",
                    note="about the coupon divided by the dirty price"),
        shuffled_choice(
            rng, "You are instead SHORT the same special bond (you borrow it in a reverse repo). Compared with a short in a bond that is not special, your carry is:",
            [f"Worse: you lend your sale proceeds at the special rate, {special_by * 1e4:.0f}bp below GC, so you earn less interest",
             "Better: the bond is special, so borrowing it pays you",
             "Unchanged: specialness only matters to owners of the bond",
             "Better, because the coupon you owe is smaller"],
            "Specialness is a premium that the owner of the bond earns by lending it out (or by not paying for cash). The short must borrow the "
            "bond and gives up that premium: shorting a special bond costs its specialness every day, on top of the coupon he pays the lender."),
    ]
    solution = [
        f"Coupon accrued = {eur_m(face)} x {bond.coupon * 100:.2f}% x {days}/{period_days} = {fmt_eur(accrual, False)}.",
        f"Financing at GC = market value {fmt_eur(mv, False)} x ({pct(estr, 3)} {gc_spread * 1e4:+.0f}bp) x {days}/360 = {fmt_eur(financing_gc, False)}.",
        f"Carry = {fmt_eur(accrual, False)} - {fmt_eur(financing_gc, False)} = {fmt_eur(cg.carry)}.",
        f"On special the repo rate is {special_by * 1e4:.0f}bp lower, saving {fmt_eur(mv, False)} x {special_by * 1e4:.0f}bp x {days}/360 = {fmt_eur(improvement)}.",
        f"Breakeven repo = coupon accrual / (MV x days/360) = {breakeven_repo * 100:.3f}% (quick form: coupon / dirty price = {current_yield * 100:.3f}%, "
        "a little higher because the coupon accrues on 365 days and repo on 360). Carry is positive whenever repo is below the current yield "
        "on the dirty price.",
        "Mind the price: a bond far from par has a current yield very different from its coupon, so low-coupon bonds are negative carry at almost any repo rate.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "bond": bond, "special": special, "cg": cg, "cs": cs, "a1": a1, "accrual": accrual,
        "financing_gc": financing_gc, "improvement": improvement, "breakeven_repo": breakeven_repo,
        "current_yield": current_yield, "estr": estr, "special_by": special_by, "days": days, "mv": mv})


# =============================================================================================================

@template("bonds.carry_rolldown", skill="bonds.carry", difficulty=3)
def bond_carry_rolldown(rng: random.Random) -> QuestionBody:
    """Warehouse a funded bond: yield pickup over repo, curve roll-down, total and breakeven."""
    for _ in range(600):
        mkt = random_market(rng)
        face = rng.choice(FACE_M) * 1e6
        bond, label = random_bond(rng, mkt, face, funding_spread=rng.choice([0.0, -0.0005, -0.0010, -0.0020]),
                                  max_abs_asw=0.0100, price_range=(88.0, 114.0))
        years = len(bond.periods)
        if years < 5:
            continue
        months = rng.choice([1, 3])
        a1 = mkt.horizon_date(months=months)
        days = (a1 - mkt.anchor).days
        c = carry_roll(bond, mkt, a1)
        price = bond.price(mkt)
        y0 = bond.yield_from_dirty(mkt.anchor, price)
        d_mod = bond.modified_duration(mkt.anchor, y0)
        mv = bond.pv(mkt)
        dv01_m = mv * d_mod * BP
        static = mkt.rolled(a1, "static")
        y_h = bond.yield_from_dirty(a1, bond.pv(static) / bond.notional * 100)
        pull = bond.notional / 100 * bond.dirty_from_yield(a1, y0) - bond.accrued(a1) - bond.pv(mkt)
        repo = financing_cost(bond, mkt, a1) / mv * 360 / days
        pickup = c.carry + pull
        y0_shown, yh_shown, repo_shown = round(y0, 6), round(y_h, 6), round(repo, 5)       # 4dp in %: what the stem prints
        pickup_est = mv * (y0_shown * days / 365 - repo_shown * days / 360)
        roll_est = dv01_m * (y0_shown - yh_shown) * 1e4
        # The pickup formula ignores compounding: its error is MV x (y - ln(1+y)) x time ~ MV x y^2/2 x time. Rounding of the
        # printed yields adds ~0.01bp each. These ARE the tolerances: nothing is fitted.
        compounding = mv * y0 ** 2 / 2 * days / 365
        tol_pickup = Tolerance(rel=0.03, abs=1.6 * compounding + 0.04 * dv01_m)
        tol_roll = Tolerance(rel=0.07, abs=0.04 * dv01_m)
        tol_total = Tolerance(rel=0.05, abs=1.3 * (tol_pickup.abs + tol_roll.abs))
        if (abs(c.total_static) >= 2.5 * tol_total.abs and abs(c.roll_down - pull) >= 0.15 * dv01_m
                and abs(pickup) >= 2.0 * tol_pickup.abs):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an unambiguous bond carry scenario")

    estr = (mkt.ois.df(mkt.anchor) / mkt.ois.df(a1) - 1) * 360 / days
    fs = bond.funding_spread
    period_days = (bond.periods[0].end - bond.periods[0].start).days
    accrual = bond.notional * bond.coupon * days / period_days
    ahead = f"{months} month{'s' if months > 1 else ''} ({days} days)"

    stem = (
        f"You are long {eur_m(face)} face of a {label} bond, {bond.coupon * 100:.2f}% annual coupon, {years}Y, dirty price {price:.2f}, "
        f"yield {pct(y0, 4)}, modified duration {d_mod:.2f}. Market value {fmt_eur(mv, False)}.\n"
        f"You fund it in repo at ESTR {fs * 1e4:+.0f}bp for {ahead}; ESTR averages {pct(estr, 4)} over the period. The coupon accrued is "
        f"{fmt_eur(accrual, False)} (ACT/ACT, {days}/{period_days} of a year's coupon).\n"
        f"Assume the curve does not move: swap rates by tenor and the bond's spread to swaps stay put. The bond's yield for its REMAINING "
        f"maturity is then {pct(y_h, 4)} ({pct(y0, 4)} today).\n{DV01_CONVENTION}"
    )
    parts = [
        NumericPart("Cash carry: coupon accrued minus repo financing over the period?", c.carry,
                    Tolerance(rel=0.03, abs=mv * 1e-5 * days / 360), "EUR",
                    sign_hint="The coupon accrues to you; the repo cost goes out.",
                    note="coupon accrued - market value x repo x days/360"),
        NumericPart("Yield pickup over repo: what does holding earn at an UNCHANGED yield (carry plus pull-to-par)?", pickup,
                    tol_pickup, "EUR", approx=pickup_est,
                    approx_label="MV x (yield x days/365 - repo x days/360)", note="market value x (yield - repo) x time"),
        NumericPart("Curve roll-down: P&L from the yield falling to its remaining-maturity level?", c.roll_down - pull,
                    tol_roll, "EUR", approx=roll_est, approx_label="DV01 x (yield - yield for remaining maturity)",
                    sign_hint="A long bond gains when its yield falls.", note="DV01 x change in yield"),
        NumericPart("Total P&L over the period, curve unchanged (after funding)?", c.total_static,
                    tol_total, "EUR", approx=pickup_est + roll_est,
                    approx_label="yield pickup + curve roll-down"),
        NumericPart("By how many bp can yields rise before that total is wiped out?", c.breakeven_bp,
                    Tolerance(rel=0.10, abs=tol_total.abs / abs(c.dv01) + 0.1), "bp",
                    approx=(pickup_est + roll_est) / c.dv01, approx_label="total / DV01", note="total / DV01"),
    ]
    solution = [
        f"Cash carry = coupon accrued {fmt_eur(accrual, False)} - financing {fmt_eur(financing_cost(bond, mkt, a1), False)} = {fmt_eur(c.carry)}.",
        f"Pull-to-par ({'up' if pull > 0 else 'down'}): at an unchanged yield a {'discount' if price < 100 else 'premium'} bond's clean price drifts toward par: "
        f"{fmt_eur(pull)}. Carry + pull-to-par = {fmt_eur(pickup)} ≈ MV x (yield - repo) x time = {fmt_eur(pickup_est)}: "
        "holding a bond funded in repo earns the yield pickup over repo. (The quick formula ignores compounding, so it runs a little high; the gap is about MV x y²/2 x time.)",
        f"Curve roll-down = DV01 x (yield - remaining-maturity yield) = {fmt_eur(dv01_m)} x ({y0 * 1e4:.1f} - {y_h * 1e4:.1f})bp = {fmt_eur(roll_est)} "
        f"(engine {fmt_eur(c.roll_down - pull)}). Total roll-down (clean price change) = pull-to-par + curve roll = {fmt_eur(c.roll_down)}.",
        f"Total = {fmt_eur(c.total_static)}; breakeven {c.breakeven_bp:+.2f}bp of yield. If forwards were realised instead, a bond funded at ESTR flat "
        f"would earn exactly zero: the carry is paid for by the forward drift. Your funding spread of {fs * 1e4:+.0f}bp is the only edge that survives "
        f"({fmt_eur(c.total_forward)}).",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "bond": bond, "c": c, "a1": a1, "pull": pull, "pickup": pickup, "pickup_est": pickup_est, "roll_est": roll_est,
        "dv01_m": dv01_m, "y0": y0, "y_h": y_h, "mv": mv, "days": days, "accrual": accrual, "estr": estr, "tol_roll": tol_roll,
        "tol_pickup": tol_pickup, "tol_total": tol_total})
