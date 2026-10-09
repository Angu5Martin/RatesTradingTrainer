"""Bond futures: conversion factors, futures DV01 and hedging, the CTD as a ranking problem, and the cash-futures basis.

The chain these templates walk (see engine/futures.py):  bond -> conversion factor -> futures price -> futures DV01 -> CTD ->
implied repo -> cash-futures basis -> relative-value decision.

CONVENTIONS (docs/DESIGN.md)
  * Prices per 100 face; 1 futures point = EUR 1,000; a tick (0.01) = EUR 10; a contract delivers EUR 100,000 face of any deliverable.
  * Invoice (per 100 face) = F x CF + accrued at delivery. Gross basis = clean - F x CF. Net basis = gross basis - carry.
  * CTD = lowest net basis = highest implied repo (one repo for all bonds). The future trades BELOW the CTD's forward-implied price
    by the value of the delivery options, so the CTD's implied repo is normally below the repo rate.
  * Long the BASIS = long bond, short CF x N / 100k contracts. It is long the delivery option: it pays the net basis as premium.

MENTAL ROUTES (carried as `approx`)
  CF ~ 1 - (6% - coupon) x 6% annuity over the remaining life;   futures DV01 ~ CTD dirty price x modified duration x 1bp / CF x 1000;
  contracts to hedge a CTD ~ face x CF / 100,000;   carry ~ (accrued at delivery - accrued today + coupon) - dirty x repo x days / 360.
"""

from __future__ import annotations

import random
from dataclasses import replace

from ...engine.curve import CurveShock
from ...engine.futures import (
    BOBL, BUND, contracts_to_hedge, long_basis_pnl_at_delivery, ranked, remaining_months)
from ...engine.instruments import FixedBond, Side
from ...engine.stir import BP_VALUE as STIR_BP_VALUE, strip
from ...engine.pnl import revalue_pnl
from ...engine.risk import Portfolio, par_irs, parallel_dv01, unit_dv01
from ..market import FuturesCase, bond_label, eur_m, pct, random_futures, random_market
from ..model import ChoicePart, NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template

BP = 1e-4
FACE_M = (10, 20, 25, 50, 75, 100, 150, 200)
DV01_CONVENTION = "DV01 = P&L for a 1bp FALL in yields (positive if long)."


def _spec_line(case: FuturesCase) -> str:
    sp = case.spec
    return (f"{sp.name} future ({sp.code}): €100,000 notional, 6% notional coupon; deliverable bonds have {sp.min_months / 12:g}-"
            f"{sp.max_months / 12:g} years left at delivery. 1 point = €1,000, 1 tick (0.01) = €10. Delivery {case.delivery:%d %b %Y}, "
            f"{case.days} days from today.")


def _screen(case: FuturesCase, with_repo: bool = True) -> str:
    """The basket as a desk screen: what is observable, nothing derived except the CF (exchange-published) and accrued."""
    head = f"{'Bond':<14}{'Clean':>8}{'CF':>10}{'Acc. today':>12}{'Acc. deliv.':>13}{'Coupon paid':>13}" + (f"{'Repo':>9}" if with_repo else "")
    rows = [head]
    for b, l in zip(case.fut.basket, case.lines):
        paid = f"{l.coupon_paid:.2f}" if l.coupon_paid else "-"
        rows.append(f"{bond_label(b):<14}{l.clean:>8.2f}{l.cf:>10.6f}{l.accrued0:>12.3f}{l.accrued_delivery:>13.3f}{paid:>13}"
                    + (f"{l.repo * 100:>8.3f}%" if with_repo else ""))
    return "\n".join(rows)


def _mental_carry(l) -> float:
    """What a trader does in their head: accrual built up (plus any coupon) less dirty price x repo x days/360. No reinvestment."""
    return l.accrued_delivery - l.accrued0 + l.coupon_paid - l.dirty * l.repo * l.days / 360.0


def _mental_net_basis(l) -> float:
    return l.gross_basis - _mental_carry(l)


def _mental_implied_repo(l) -> float:
    return ((l.invoice + l.coupon_paid) / l.dirty - 1.0) * 360.0 / l.days


# =============================================================================================================

@template("futures.conversion_factor", skill="futures.conversion_factor", difficulty=2)
def conversion_factor_q(rng: random.Random) -> QuestionBody:
    mkt = random_market(rng)
    case = random_futures(rng, mkt, min_gap=0.0)
    i = rng.choice([k for k, x in enumerate(case.lines) if abs(x.gross_basis) >= 0.05])      # a zero gross basis would let 0 pass
    b, l = case.fut.basket[i], case.lines[i]
    months = remaining_months(case.delivery, b.maturity)
    years = months / 12.0
    annuity = (1 - 1.06 ** (-years)) / 0.06
    annuity_shown = round(annuity, 3)
    cf_est = 1 - (0.06 - b.coupon) * annuity_shown
    f, label = case.price, bond_label(b)
    invoice = 1000.0 * l.invoice
    breakeven_f = l.clean / l.cf
    stem = (
        f"{_spec_line(case)}\n"
        f"The future trades at {f:.2f}. Consider the {label} bond: clean price {l.clean:.2f}, accrued interest {l.accrued_delivery:.3f} at delivery. "
        f"At delivery it has {months} complete months ({years:.2f} years) left, and a 6% annuity over that life is worth {annuity_shown:.3f} years of coupon.\n"
        "The conversion factor (CF) is the price of the bond per unit of face if it yielded exactly 6%, the notional coupon, on the delivery date."
    )
    parts = [
        NumericPart("What is the bond's conversion factor?", l.cf, Tolerance(abs=0.001), "cf", approx=cf_est,
                    approx_label="1 - (6% - coupon) x annuity",
                    sign_hint="A bond with a coupon below 6% is worth LESS than par at a 6% yield: CF < 1.",
                    note="a number near 0.8, e.g. 0.7736"),
        NumericPart(f"You are short one contract and deliver €100,000 face of this bond (CF {l.cf:.6f}). What invoice amount do you receive?",
                    invoice, Tolerance(rel=0.001), "EUR",
                    note="1000 x (futures price x CF + accrued)"),
        NumericPart("What is the bond's gross basis (price points per 100 face)?", l.gross_basis, Tolerance(abs=0.01), "pts",
                    note="clean price - futures price x CF"),
        NumericPart("At what futures price would delivering this bond break even on price alone (gross basis zero)?", breakeven_f,
                    Tolerance(abs=0.05), "pts", approx=l.clean / cf_est, approx_label="clean price / approximate CF",
                    note="clean price / CF"),
    ]
    solution = [
        f"Remaining life rounded DOWN to whole months: {months} months. Coupon {b.coupon * 100:.2f}% is below the 6% notional coupon, so at a 6% yield "
        f"the bond is worth less than par: CF ≈ 1 - (6% - {b.coupon * 100:.2f}%) x {annuity_shown:.3f} = {cf_est:.4f} (exchange figure {l.cf:.6f}).",
        f"Invoice = 1000 x (F x CF + accrued) = 1000 x ({f:.2f} x {l.cf:.6f} + {l.accrued_delivery:.3f}) = {fmt_eur(invoice, False)}. "
        "Delivering a bond with CF below 1 earns LESS than the futures notional: the CF is how the exchange scales a bond of lower coupon down to the 6% contract.",
        f"Gross basis = clean - F x CF = {l.clean:.2f} - {f:.2f} x {l.cf:.6f} = {l.gross_basis:.3f}. It is what you pay to own the bond rather than be long the future "
        "(before carry), and it converges to the bond's net basis, then to zero if it is the CTD, by delivery.",
        f"Break-even futures price = clean / CF = {breakeven_f:.2f}: the price at which this bond would be exactly as good as the future. The lower a bond's "
        "clean/CF, the cheaper it is to deliver before carry; the CTD is the bond with the lowest clean/CF after carry (next question).",
        "Why it matters: the CF values every bond at 6% while the market yields about 2-3%. At those yields the CF-adjusted prices of different bonds drift apart, "
        "and the short keeps the option to deliver the cheapest.",
    ]
    return QuestionBody(stem, parts, solution, {
        "case": case, "i": i, "months": months, "annuity": annuity_shown, "cf": l.cf, "cf_est": cf_est, "invoice": invoice,
        "gross": l.gross_basis, "breakeven_f": breakeven_f})


# =============================================================================================================

def _ctd_hedge_data(case: FuturesCase, rng: random.Random):
    mkt = case.mkt
    i = case.ctd_index()
    b, l = case.fut.basket[i], case.lines[i]
    fwd_dirty = l.forward_clean + l.accrued_delivery
    y_f = b.yield_from_dirty(case.delivery, fwd_dirty)
    d_f = b.modified_duration(case.delivery, y_f)
    return i, b, l, fwd_dirty, d_f


@template("futures.dv01_hedge", skill="futures.dv01", difficulty=3)
def dv01_hedge(rng: random.Random) -> QuestionBody:
    for _ in range(50):
        mkt = random_market(rng)
        case = random_futures(rng, mkt, spec=rng.choice([BUND, BUND, BOBL]), min_gap=0.15)
        i, b, l, fwd_dirty, d_f = _ctd_hedge_data(case, rng)
        if 1 / l.cf - 1 >= 0.12:                  # the face-for-face hedge must be visibly wrong
            break
    one = case.fut.with_contracts(1)
    fut_dv01 = parallel_dv01(one, mkt)
    fut_dv01_mental = fwd_dirty * d_f * BP / l.cf * 1000.0
    face = rng.choice(FACE_M) * 1e6
    long_ = rng.random() < 0.6
    sgn = 1 if long_ else -1
    position = FixedBond.from_maturity(sgn * face, b.coupon, b.maturity, mkt.anchor, asw=b.asw)
    bond_dv01 = parallel_dv01(position, mkt)
    n_exact = -bond_dv01 / fut_dv01
    n_cf = contracts_to_hedge(sgn * face, l.cf, case.spec)
    n_naive = -sgn * face / case.spec.notional
    naive_hedge = case.fut.with_contracts(n_naive)
    book = Portfolio([position, naive_hedge])
    move = rng.choice([8, 10, 15, -10, -15])
    naive_pnl = revalue_pnl(book, mkt, CurveShock.parallel(move))
    net_dv01_mental = bond_dv01 + n_naive * fut_dv01
    naive_approx = -net_dv01_mental * move
    years, days = len(b.periods), case.days
    asw_bp = abs(b.asw * 1e4)
    tol_dv01 = Tolerance(rel=0.06)
    # n_cf ignores that the bond's DV01 today exceeds its DV01 at delivery by about days/365/D, plus the constant-ASW effect.
    tol_cf = Tolerance(rel=0.03 + days / 365.0 / d_f + asw_bp * (0.00015 + 0.00007 * years))
    verb, hedge_verb = ("long", "sell") if long_ else ("short", "buy")
    stem = (
        f"{_spec_line(case)}\n"
        f"The future trades at {case.price:.2f}. Its cheapest-to-deliver bond is the {bond_label(b)} (CF {l.cf:.6f}). At delivery that bond will have a dirty price "
        f"of {fwd_dirty:.3f} and a modified duration of {d_f:.2f}.\n"
        f"You are {verb} {eur_m(face)} face of that bond. {DV01_CONVENTION}"
    )
    parts = [
        NumericPart("What is the DV01 of ONE futures contract (EUR per bp)? Long = positive.", fut_dv01, tol_dv01, "EUR",
                    approx=fut_dv01_mental, approx_label="CTD dirty price x duration x 1bp / CF x 1000",
                    note="the DV01 of the CTD per 100 face, divided by the CF, times €1,000 per point"),
        NumericPart(f"How many contracts hedge the bond's DV01? ({hedge_verb.capitalize()} = {'negative' if long_ else 'positive'})", n_exact, tol_cf, "contracts",
                    approx=n_cf, approx_label="face x CF / 100,000",
                    sign_hint="Hedge a LONG bond by SELLING futures (negative); a short bond by buying.",
                    note="e.g. -770"),
        NumericPart(f"Suppose you hedged by {hedge_verb}ing the SAME FACE amount instead ({abs(n_naive):,.0f} contracts: face / 100,000). Yields then move "
                    f"{'up' if move > 0 else 'down'} {abs(move)}bp. What is the P&L of bond plus futures?", naive_pnl, Tolerance(rel=0.10, abs=0.01 * abs(bond_dv01) * abs(move)),
                    "EUR", approx=naive_approx, approx_label="-(net DV01) x move",
                    sign_hint="The face-for-face hedge is too BIG by 1/CF, so you end up with the opposite exposure to the bond.",
                    note="net DV01 is the bond's less the over-sized hedge"),
        shuffled_choice(
            rng, "Rates rise sharply and a bond with LONGER duration becomes the cheapest to deliver. The DV01 of one contract:",
            ["Rises: the future now behaves like a longer-duration bond, so a CF-weighted hedge sized today is too small",
             "Falls: a longer-duration bond is worth less when yields are higher",
             "Is unchanged: the DV01 is set by the contract, which is always a 6% bond",
             "Falls, because the CF of the new CTD is lower"],
            "The future's price is (CTD forward price) / CF, so its DV01 is the CTD's DV01 divided by the CF. A longer-duration, lower-coupon "
            "CTD has a larger DV01 AND a smaller CF, so both effects raise the DV01 per contract. This is why a futures hedge needs to be re-sized "
            "when the CTD changes, and why the future is not a fixed-duration instrument."),
    ]
    solution = [
        f"Futures DV01 ≈ CTD DV01 / CF: {fwd_dirty:.3f} x {d_f:.2f} x 0.0001 = {fwd_dirty * d_f * BP:.4f} per 100 face; / {l.cf:.6f} = {fwd_dirty * d_f * BP / l.cf:.4f} "
        f"per point; x €1,000 = {fmt_eur(fut_dv01_mental, False)} per contract (engine: {fmt_eur(fut_dv01, False)}, from repricing the whole basket).",
        f"The CTD's DV01 per 100 face is divided by the CF because the future moves 1/CF points for each point the CTD moves (price = CTD / CF). "
        f"Bond DV01 on {eur_m(face)} = {fmt_eur(bond_dv01)}; contracts = {fmt_eur(abs(bond_dv01), False)} / {fmt_eur(fut_dv01, False)} = {abs(n_exact):,.0f}.",
        f"Rule of thumb: contracts = face x CF / 100,000 = {abs(n_cf):,.0f}. Not face / 100,000 = {abs(n_naive):,.0f}: that over-hedges by 1/CF - 1 = {(1 / l.cf - 1) * 100:.0f}%.",
        f"The face-for-face hedge leaves net DV01 ≈ {fmt_eur(net_dv01_mental)}, so a {abs(move)}bp {'rise' if move > 0 else 'fall'} gives {fmt_eur(naive_pnl)} "
        f"(first order {fmt_eur(naive_approx)}).",
        "The CF-weighted hedge is exact only for the CTD. A bond that is not the CTD hedges with its own DV01 ratio, and the hedge leaves a basis position.",
    ]
    return QuestionBody(stem, parts, solution, {
        "case": case, "i": i, "fut_dv01": fut_dv01, "fut_dv01_mental": fut_dv01_mental, "bond_dv01": bond_dv01, "n_exact": n_exact,
        "n_cf": n_cf, "n_naive": n_naive, "naive_pnl": naive_pnl, "naive_approx": naive_approx, "face": face, "long": long_,
        "fwd_dirty": fwd_dirty, "d_f": d_f, "tol_cf": tol_cf, "move": move})


# =============================================================================================================

@template("futures.ctd_ranking", skill="futures.ctd", difficulty=3)
def ctd_ranking(rng: random.Random) -> QuestionBody:
    """CTD as a decision: net basis (gross basis less carry) over a basket, with the gross-basis trap."""
    want_trap = rng.random() < 0.5
    for _ in range(300):
        mkt = random_market(rng)
        try:
            case = random_futures(rng, mkt, contest=True, wide_coupons=want_trap, trap=want_trap or None, min_gap=0.05,
                                  repo_gap=(0.0020, 0.0060))
        except RuntimeError:
            continue
        lines = case.lines
        ci = case.ctd_index()
        l = lines[ci]
        # The mental route ignores interest on a coupon received before delivery; the allowance is exactly that, in price points.
        reinvest = l.coupon_paid * l.repo * l.coupon_days / 360.0
        tol_gross = Tolerance(abs=0.005)
        tol_nb = Tolerance(abs=0.008 + 1.3 * reinvest)
        tol_ir = Tolerance(abs=0.03 + 1.3 * 100.0 * reinvest / l.dirty * 360.0 / l.days)       # in %
        mental_rank = sorted(range(len(lines)), key=lambda k: _mental_net_basis(lines[k]))
        gap = sorted(_mental_net_basis(x) for x in lines)
        # the mental route must name the same CTD with room to spare, and no part may be answerable with 0
        if (mental_rank[0] == ci and gap[1] - gap[0] >= 0.03 and abs(l.gross_basis) >= 0.02
                and abs(l.net_basis) >= 1.6 * tol_nb.abs):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an unambiguous CTD ranking")
    l = lines[ci]
    b = case.fut.basket[ci]
    gross_idx = min(range(len(lines)), key=lambda k: lines[k].gross_basis)
    labels = case.labels
    repo_note = ("Repo is the term rate to delivery (ACT/360)." if len({round(x, 5) for x in case.repos}) == 1 else
                 "Repo is the term rate to delivery (ACT/360) for each bond; a bond on special repos below the others.")
    stem = (
        f"{_spec_line(case)}\nThe future trades at {case.price:.2f}. {repo_note} Coupon paid is any coupon received before delivery.\n\n"
        f"{_screen(case)}\n\nCarry to delivery = accrued built up (plus any coupon) minus financing: dirty price x repo x days / 360."
    )
    opts_order = list(range(len(lines)))
    order = opts_order[:]
    rng.shuffle(order)
    ctd_part = ChoicePart("Which bond is the cheapest to deliver (lowest net basis)?", [labels[k] for k in order], order.index(ci),
                          "Net basis = gross basis - carry. The CTD is the bond the short is happiest to deliver: lowest net basis, i.e. highest implied repo.")
    carry = l.carry
    parts = [
        ctd_part,
        NumericPart(f"What is the gross basis of the {labels[ci]} (price points per 100 face)?", l.gross_basis, tol_gross, "pts",
                    note="clean price - futures price x CF"),
        NumericPart(f"What is the net basis of the {labels[ci]} (gross basis less carry)?", l.net_basis, tol_nb, "pts",
                    approx=_mental_net_basis(l), approx_label="gross basis - (accrual + coupon - dirty x repo x days/360)",
                    note="a small positive number: the price of the delivery options"),
        NumericPart(f"What is the implied repo rate of the {labels[ci]} (%)?", l.implied_repo * 100, tol_ir, "%",
                    approx=_mental_implied_repo(l) * 100,
                    approx_label="(invoice + coupon) / dirty price - 1, annualised ACT/360",
                    note="(invoice + coupon paid) / dirty price - 1, x 360 / days"),
        shuffled_choice(
            rng, f"The CTD's implied repo ({l.implied_repo * 100:.2f}%) is BELOW its repo rate ({l.repo * 100:.2f}%). The best reading is:",
            ["No arbitrage: cash-and-carry would LOSE money, and the shortfall is the value of the short's delivery options (its net basis)",
             "The future is rich: sell the future and buy the bond to earn the difference",
             "The bond is on special, so the implied repo is meaningless",
             "The repo rate is wrong: implied repo must equal actual repo"],
            "Buy the CTD, repo it, sell the future and deliver: you earn the implied repo, and you pay the actual repo. Implied repo BELOW actual repo "
            "is a loss-making carry trade. The future is not rich: the short owns the choice of bond (and timing), which is worth money, and a future "
            "trading a little CHEAP to the CTD's forward price is the market pricing that option. The net basis is that price."),
    ]
    if gross_idx != ci:
        gl = lines[gross_idx]
        parts.append(shuffled_choice(
            rng, f"The {labels[gross_idx]} has the LOWEST gross basis ({gl.gross_basis:.3f}) but is not the CTD. Why?",
            [f"Its carry is lower than the CTD's ({_mental_carry(gl):.3f} vs {_mental_carry(l):.3f}): holding it to delivery is worth less, so its NET basis is higher",
             "Gross basis is only valid for bonds with coupons above 6%",
             "Its conversion factor is wrong",
             "A lower gross basis means a bond is more expensive to deliver"],
            "The gross basis ignores that the cash-and-carry also earns coupon accrual and pays financing. Net basis (gross basis less carry) is the full cost. "
            "Screening on gross basis alone is the standard trap: a high-coupon bond has a bigger carry, so it can look expensive on gross basis but be cheapest "
            "once carry is counted."))
    order_lines = ranked(lines)
    table = ["Bond           Gross   Carry     Net   Implied repo"]
    for x in order_lines:
        table.append(f"{bond_label(x.bond):<14}{x.gross_basis:>6.3f}{x.carry:>8.3f}{x.net_basis:>8.3f}{x.implied_repo * 100:>10.3f}%")
    solution = [
        "Net-basis screen, best first:\n    " + "\n    ".join(table),
        f"The CTD is the {labels[ci]}: lowest net basis {l.net_basis:.3f}, highest implied repo {l.implied_repo * 100:.3f}%. It leads the runner-up by "
        f"{sorted(x.net_basis for x in lines)[1] - l.net_basis:.3f} of price (net basis, per 100 face).",
        f"Its carry is {_mental_carry(l):.3f} quick ({carry:.3f} exact, which also earns repo on any coupon received): "
        f"{l.accrued_delivery - l.accrued0 + l.coupon_paid:.3f} of coupon income less {l.dirty * l.repo * l.days / 360:.3f} of financing.",
        f"Net basis = gross {l.gross_basis:.3f} - carry {carry:.3f} = {l.net_basis:.3f}. In futures-price terms that is {l.net_basis_in_futures_points:.3f} points (about "
        f"{l.net_basis_in_futures_points * 100:.0f} ticks, €{l.net_basis_in_futures_points * 1000:,.0f} per contract): the amount the future trades below the CTD's break-even price.",
        f"Implied repo: ({l.invoice:.3f}{' + ' + format(l.coupon_paid, '.2f') if l.coupon_paid else ''}) / {l.dirty:.3f} - 1 = "
        f"{_mental_implied_repo(l) * l.days / 360 * 100:.3f}% over {l.days} days = {_mental_implied_repo(l) * 100:.3f}% annualised "
        f"({l.implied_repo * 100:.3f}% with the coupon reinvested). The gap to the {l.repo * 100:.3f}% repo is the delivery-option premium.",
        ("The lowest GROSS basis was a different bond: always rank on net basis." if gross_idx != ci else
         "Here the lowest gross basis and the lowest net basis agree, but they need not: carry differs with coupon."),
    ]
    return QuestionBody(stem, parts, solution, {
        "case": case, "ci": ci, "gross_idx": gross_idx, "net": l.net_basis, "implied": l.implied_repo, "carry": carry,
        "gap": case.gap(), "mental_net": _mental_net_basis(l), "mental_implied": _mental_implied_repo(l), "trap": gross_idx != ci})


# =============================================================================================================

def _sensitivities(case: FuturesCase) -> list[float]:
    """Each bond's futures-equivalent price change per 1bp FALL in yields (price points), by central difference on the whole model."""
    m = case.mkt
    up = case.fut.futures_equivalents(m.shifted(CurveShock.parallel(+0.5)))
    dn = case.fut.futures_equivalents(m.shifted(CurveShock.parallel(-0.5)))
    return [d - u for u, d in zip(up, dn)]


@template("futures.ctd_switch", skill="futures.ctd", difficulty=3)
def ctd_switch(rng: random.Random) -> QuestionBody:
    """When does the cheapest bond change, what does the future do when it does, and what is a long-basis position worth then."""
    moves = [25, 30, 40, 50, 60, 75, 100]
    for _ in range(400):
        mkt = random_market(rng)
        try:
            case = random_futures(rng, mkt, contest=True, min_gap=0.05, max_gap=0.30)
        except RuntimeError:
            continue
        fut = case.fut
        f0 = fut.futures_equivalents(mkt)
        i0 = min(range(len(f0)), key=f0.__getitem__)
        sens = _sensitivities(case)
        tabled = [round(x, 3) for x in f0]
        dv01 = [round(s * 1000.0, 1) for s in sens]                        # EUR per contract per bp, as the screen shows it
        candidates = []
        for mag in moves:
            for x in (mag, -mag):
                fo = [a - x * d / 1000.0 for a, d in zip(tabled, dv01)]       # the mental route: only the printed table
                io = min(range(len(fo)), key=fo.__getitem__)
                g2 = sorted(fo)
                if io == i0 or g2[1] - g2[0] < 0.04:                          # screen cheaply first: the exact repricing is the slow step
                    continue
                f1 = fut.futures_equivalents(mkt.shifted(CurveShock.parallel(x)))
                i1 = min(range(len(f1)), key=f1.__getitem__)
                g1 = sorted(f1)
                if i1 == io and g1[1] - g1[0] >= 0.04 and f1[i0] - f1[i1] >= 0.04:
                    candidates.append((x, f1, i1, fo))
        if not candidates:
            continue
        # Take the mildest move that changes the CTD and leaves every answer well clear of its tolerance: the first-order table is most reliable there.
        d_i = [abs(sv) * 1e4 / f for sv, f in zip(sens, f0)]                  # modified duration of each futures-equivalent price
        d_max, d_min = max(d_i), min(d_i)
        face = rng.choice([10, 25, 50, 100]) * 1e6
        lines = case.lines
        labels = case.labels
        cf = lines[i0].cf
        nb0 = cf * (tabled[i0] - case.price)
        chosen = None
        for x, f1, i1, fo in sorted(candidates, key=lambda c: (abs(c[0]), rng.random())):
            price0 = fut.price(mkt)
            price1 = fut.price(mkt.shifted(CurveShock.parallel(x)))
            d_price, d_price_mental = price1 - price0, min(fo) - tabled[i0]
            # first-order error: convexity (about D^2/2 x F x move^2) plus the rounding of the printed table; the P&L is a DIFFERENCE of
            # two prices so only the convexity SPREAD between the bonds matters
            rounding = 0.001 + 0.0001 * abs(x)
            tol_move = Tolerance(rel=0.02, abs=1.6 * 0.5 * f0[i0] * d_max ** 2 * (x * BP) ** 2 + rounding)
            tol_pnl_pts = 1.6 * 0.5 * f0[i0] * (d_max ** 2 - d_min ** 2) * (x * BP) ** 2 * cf + 2 * rounding * cf + 0.01
            if abs(d_price) < 2.5 * tol_move.abs or abs(-nb0 + cf * (fo[i0] - min(fo))) < 1.8 * tol_pnl_pts:     # cheap screen first
                continue
            pnl_pts = long_basis_pnl_at_delivery(fut, mkt, i0, CurveShock.parallel(x))
            if abs(pnl_pts) >= 1.6 * tol_pnl_pts:
                chosen = True
                break
        if chosen:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a CTD-switch scenario with answers clear of their tolerances")
    pnl = pnl_pts * face / 100.0
    pnl_mental = (-nb0 + cf * (fo[i0] - min(fo))) * face / 100.0
    tol_pnl = Tolerance(rel=0.05, abs=tol_pnl_pts * face / 100.0)
    selloff = x > 0
    dirn = "rise" if selloff else "fall"

    table = [f"{'Bond':<14}{'CF':>10}{'Futures-equiv. price':>22}{'DV01 (€/contract/bp)':>22}"]
    for k, lab in enumerate(labels):
        table.append(f"{lab:<14}{lines[k].cf:>10.6f}{tabled[k]:>22.3f}{dv01[k]:>22,.1f}")
    order = list(range(len(labels)))
    rng.shuffle(order)

    def pick(prompt, idx, why):
        return ChoicePart(prompt, [labels[k] for k in order], order.index(idx), why)

    stem = (
        f"{_spec_line(case)}\nThe future trades at {case.price:.2f}. The screen shows each deliverable's FUTURES-EQUIVALENT price (its forward clean price / CF: "
        "the futures price at which delivering that bond breaks even after carry) and the DV01 of that price per contract. "
        "DV01 is the change in the price for a 1bp FALL in yields.\n\n" + "\n".join(table)
    )
    parts = [
        pick("Which bond is the cheapest to deliver today?", i0,
             "The CTD has the lowest futures-equivalent price: the future is priced off it (the market trades a little BELOW that price, the value of the other options)."),
        pick(f"Yields {dirn} {abs(x)}bp in parallel. Which bond is the CTD afterwards?", i1,
             "Move each futures-equivalent price by -(yield change) x DV01 and re-rank. Bonds with different durations move by different amounts, so their prices cross: "
             "in a selloff the HIGHER-duration bond falls fastest and becomes cheapest; in a rally the lower-duration one does (when yields are below 6%)."
             if selloff else
             "Move each futures-equivalent price by -(yield change) x DV01 and re-rank. A rally lifts higher-duration bonds most, so cheapness migrates to the lower-duration "
             "ones (when yields are below 6%)."),
        NumericPart(f"By how much does the FUTURES price change (points, signed)?", d_price, tol_move, "pts", approx=d_price_mental,
                    approx_label="new lowest futures-equivalent price - old CTD's price",
                    sign_hint="Rates up, futures down.", note="new CTD's re-priced futures-equivalent less the old CTD's"),
        shuffled_choice(
            rng, f"Compare the future's price change with that of the OLD CTD's futures-equivalent price. The future did:",
            [f"WORSE: it {'fell more' if selloff else 'rose less'}, because the short can switch to a cheaper bond",
             f"Better: it {'fell less' if selloff else 'rose more'}, because the switch makes the CTD longer-dated",
             "The same: the future always tracks its CTD one for one",
             "Better, because the long gets the switching option"],
            f"The future is priced off the CHEAPEST bond: F = min of the futures-equivalent prices. The old CTD's price is one of them, so F can never be above it, "
            f"and the gap opens as soon as another bond becomes cheaper (here {f1[i0] - f1[i1]:.3f} points). The short owns that choice; the long is short the option. "
            "That is why a bond future has less convexity than its CTD and underperforms it in big moves."),
        NumericPart(f"You are long the basis in the old CTD, {labels[i0]}: you own {eur_m(face)} face and are short CF x face / 100,000 contracts "
                    f"({face * cf / 100_000:,.0f}). Yields {dirn} {abs(x)}bp in parallel and everything is held to delivery. What is your P&L?",
                    pnl, tol_pnl, "EUR", approx=pnl_mental,
                    approx_label="-(net basis) + CF x (old CTD's new price - lowest new price)",
                    sign_hint="Long basis can lose at most the net basis it paid; here the option has been exercised in your favour.",
                    note="the option payoff minus the premium (the net basis)"),
    ]
    solution = [
        "Futures-equivalent prices after the move, first order (price - DV01/1000 x move): " + ", ".join(
            f"{lab} {v:.3f}" for lab, v in zip(labels, fo)) + f". Lowest: {labels[min(range(len(fo)), key=fo.__getitem__)]}: the CTD is now the {labels[i1]}.",
        f"The old CTD was {labels[i0]} at {tabled[i0]:.3f}; the new one is cheaper by {f1[i0] - f1[i1]:.3f} points on the exact repricing. The yield move changed the ranking "
        "because the bonds do not have the same duration: their prices move by different amounts per bp, and the CF (a fixed number, set at a 6% yield) cannot compensate.",
        f"The future moves from {price0:.2f} to {price1:.2f} ({d_price:+.3f} points); first order from the table: {d_price_mental:+.3f}. "
        f"The old CTD alone would have given {f1[i0] - f0[i0]:+.3f}: the future did worse by {f1[i0] - f1[i1]:.3f} because it follows the cheapest bond.",
        f"Long basis: you paid a net basis of CF x (F_i - F) = {cf:.4f} x ({tabled[i0]:.3f} - {case.price:.2f}) = {nb0:.3f} points per 100 face. "
        f"If nothing had happened by delivery you would lose exactly that. Instead the old CTD is now {cf * (f1[i0] - f1[i1]):.3f} points (per 100 face) dearer than the cheapest, which is "
        f"what the future converges to: P&L = -{nb0:.3f} + {cf * (f1[i0] - f1[i1]):.3f} = {pnl_pts:+.3f} per 100 face = {fmt_eur(pnl)} on {eur_m(face)}.",
        "The position is DV01-hedged, so it does not care which way yields go, only whether they move ENOUGH to change the CTD. It is long the delivery option (and short time: "
        "the net basis decays to zero by delivery); the holder of the future's short side owns the same option from the other side.",
    ]
    return QuestionBody(stem, parts, solution, {
        "case": case, "i0": i0, "i1": i1, "x": x, "f1": f1, "fo": fo, "tabled": tabled, "dv01": dv01, "d_price": d_price,
        "d_price_mental": d_price_mental, "tol_move": tol_move, "pnl": pnl, "pnl_mental": pnl_mental, "face": face, "nb0": nb0,
        "pnl_pts": pnl_pts, "d_max": d_max})


# =============================================================================================================

@template("futures.basis_trade", skill="rv.futures_basis", difficulty=3)
def basis_trade(rng: random.Random) -> QuestionBody:
    """The capstone: screen the basket, find the CTD, price the basis against the option value, size the hedge, know what you own."""
    for _ in range(300):
        mkt = random_market(rng)
        try:
            case = random_futures(rng, mkt, spec=rng.choice([BUND, BUND, BOBL]), contest=rng.random() < 0.5, min_gap=0.05,
                                  repo_gap=(0.0020, 0.0060))
        except RuntimeError:
            continue
        lines = case.lines
        ci = case.ctd_index()
        l = lines[ci]
        reinvest = l.coupon_paid * l.repo * l.coupon_days / 360.0
        tol_nb = Tolerance(abs=0.008 + 1.3 * reinvest)
        mental_rank = sorted(range(len(lines)), key=lambda k: _mental_net_basis(lines[k]))
        gap = sorted(_mental_net_basis(x) for x in lines)
        if (mental_rank[0] != ci or gap[1] - gap[0] < 0.03 or 1 / l.cf - 1 < 0.12 or abs(l.net_basis) < 2.0 * tol_nb.abs
                or tol_nb.abs > 0.025):
            continue
        break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a basis-trade scenario")
    labels, b = case.labels, case.fut.basket[ci]
    mkt = case.mkt
    # The option desk's fair value for the CTD's net basis sits clearly above or below what the screen shows
    cheap = rng.random() < 0.5                                   # True: net basis BELOW fair value -> basis is cheap -> BUY it
    delta = rng.choice([0.05, 0.06, 0.08, 0.10, 0.12])
    fair = round(l.net_basis + (delta if cheap else -delta), 2)
    if fair < 0.02:
        fair, cheap = round(l.net_basis + delta, 2), True
    edge = fair - l.net_basis                                    # >0: basis cheap
    cheap = edge > 0
    face = rng.choice([25, 50, 75, 100, 150]) * 1e6
    sgn = 1 if cheap else -1                                     # +1: long the bond (buy basis); -1: short the bond (sell basis)
    # hedge sizing: engine DV01s (the long-bond DV01 against the future's), CF-weighted shortcut as the mental route
    one = case.fut.with_contracts(1)
    fut_dv01 = parallel_dv01(one, mkt)
    position = FixedBond.from_maturity(sgn * face, b.coupon, b.maturity, mkt.anchor, asw=b.asw)
    bond_dv01 = parallel_dv01(position, mkt)
    d_f = _ctd_hedge_data(case, rng)[4]
    n_exact = -bond_dv01 / fut_dv01
    n_cf = contracts_to_hedge(sgn * face, l.cf, case.spec)
    tol_cf = Tolerance(rel=0.03 + case.days / 365.0 / d_f + abs(b.asw * 1e4) * (0.00015 + 0.00007 * len(b.periods)))
    static = -sgn * l.net_basis * face / 100.0                   # long basis loses the net basis; short basis keeps it
    expected = abs(edge) * face / 100.0
    tol_static = Tolerance(rel=0.02, abs=tol_nb.abs * face / 100.0)
    tol_expected = Tolerance(rel=0.03, abs=1.3 * tol_nb.abs * face / 100.0)
    order = list(range(len(labels)))
    rng.shuffle(order)
    action = "BUY the basis (long the bond, short futures)" if cheap else "SELL the basis (short the bond, long futures)"
    stem = (
        f"{_spec_line(case)}\nThe future trades at {case.price:.2f}. Repo is the term rate to delivery (ACT/360); coupon paid is any coupon received before delivery.\n\n"
        f"{_screen(case)}\n\nCarry to delivery = accrued built up (plus any coupon) minus financing (dirty price x repo x days / 360). "
        f"The options desk values the delivery options of the CTD at {fair:.2f} points of NET basis (per 100 face): the premium a fair market would charge for "
        f"the short's choice of bond and timing. You may trade the basis in {eur_m(face)} face of the CTD, hedged with the future."
    )
    decision_opts = ["Buy the basis: long the CTD, short CF x face / 100,000 contracts",
                     "Sell the basis: short the CTD, long CF x face / 100,000 contracts",
                     "Do nothing: the net basis equals its fair value"]
    risk_buy = ("Time decay: if nothing happens the net basis you paid decays to zero by delivery, and you lose it all",
                "A big selloff: the long basis loses when yields rise")
    parts = [
        ChoicePart("Which bond is the cheapest to deliver?", [labels[k] for k in order], order.index(ci),
                   "Lowest net basis (gross basis less carry) = highest implied repo."),
        NumericPart(f"What is the net basis of the {labels[ci]} (price points per 100 face)?", l.net_basis, tol_nb, "pts",
                    approx=_mental_net_basis(l), approx_label="gross basis - (accrual + coupon - dirty x repo x days/360)",
                    note="clean - F x CF - carry"),
        shuffled_choice(
            rng, f"The net basis is {'below' if cheap else 'above'} the {fair:.2f} the options desk calls fair. What is the trade?",
            [decision_opts[0] if cheap else decision_opts[1], decision_opts[1] if cheap else decision_opts[0], decision_opts[2],
             "Buy the future outright: its price is below the CTD's forward price"],
            "The net basis is the PRICE of the short's delivery options. If the price on the screen is below fair value, the options are cheap: buy them by buying the "
            "basis (long the CTD, short the future in CF-weighted size). If it is above fair, sell the basis. The trade is DV01-neutral: the bet is only on the option "
            "(on how much yields move and whether the CTD changes) against the premium."),
        NumericPart(f"How many contracts do you {'sell' if cheap else 'buy'} to hedge {eur_m(face)} face of the CTD? ({'sell' if cheap else 'buy'} = {'negative' if cheap else 'positive'})",
                    n_exact, tol_cf, "contracts", approx=n_cf, approx_label="face x CF / 100,000",
                    sign_hint="The future must offset the bond: long bond, short futures; short bond, long futures.",
                    note="face x CF / 100,000"),
        NumericPart(f"If yields do not move and the CTD does not change, what is your P&L by delivery (EUR)?", static, tol_static, "EUR",
                    sign_hint=("The long basis pays the net basis as premium and it decays to nothing." if cheap else
                               "The short basis collects the net basis as premium and it decays to nothing."),
                    note="net basis x face / 100"),
        NumericPart("The options turn out to be worth exactly the desk's fair value. What is your expected profit (EUR)?", expected, tol_expected, "EUR",
                    note="the difference between fair value and the net basis, x face / 100"),
        shuffled_choice(
            rng, "What is the main risk of this position, given that it is DV01-neutral?",
            [risk_buy[0] if cheap else "A big move in yields that switches the CTD: the future underperforms the bond you are short, and you are short the option",
             "Outright rate risk: the CF-weighted hedge removes only half of it" if cheap else "Time decay: the premium you collected disappears",
             "Swap-spread risk: a futures hedge has none",
             "No risk: a basis trade is an arbitrage"],
            ("You paid the net basis for an option. If yields sit still, it expires worthless: you lose the premium exactly (the static P&L above). You make money only if "
             "moves are big enough to change the CTD and pay more than you paid." if cheap else
             "You sold the option and kept the premium. Quiet markets earn it for you; a violent move that makes another bond cheapest costs you more than the premium, "
             "and being DV01-hedged does not help, because that loss comes from the bond leg and the future moving by different amounts (the future follows the new CTD).")),
    ]
    solution = [
        f"CTD: {labels[ci]}, net basis {l.net_basis:.3f} (gross {l.gross_basis:.3f} less carry {l.carry:.3f}); implied repo {l.implied_repo * 100:.3f}% vs repo {l.repo * 100:.3f}%: "
        f"BELOW, because the short's options have value. The runner-up is {sorted(x.net_basis for x in lines)[1] - l.net_basis:.3f} points behind.",
        f"The desk values the options at {fair:.2f}; the screen charges {l.net_basis:.3f}. The basis is {'CHEAP' if cheap else 'RICH'} by {abs(edge):.3f} points per 100 face: {action}.",
        f"Hedge: face x CF / 100,000 = {eur_m(face)} x {l.cf:.6f} / 100,000 = {abs(n_cf):,.0f} contracts (DV01 ratio: {abs(n_exact):,.0f}; "
        f"{fmt_eur(bond_dv01)} of bond DV01 against {fmt_eur(fut_dv01, False)} per contract).",
        f"If nothing happens the future converges to the CTD's forward price, so the position earns/loses exactly the net basis: "
        f"{'-' if cheap else '+'}{l.net_basis:.3f} x {eur_m(face)} / 100 = {fmt_eur(static)}.",
        f"If the options are worth {fair:.2f}, the expected P&L is (fair - net basis) = {edge:+.3f} x {eur_m(face)} / 100 = "
        f"{fmt_eur(expected)} in your favour. That is an EXPECTED value: the realised result is the option payoff, which is zero most days and large when the CTD switches.",
        "In practice: the basis is a bet on realised switching against the premium. It is DV01-neutral but not risk-free.",
    ]
    return QuestionBody(stem, parts, solution, {
        "case": case, "ci": ci, "fair": fair, "cheap": cheap, "edge": edge, "face": face, "n_exact": n_exact, "n_cf": n_cf, "static": static,
        "expected": expected, "net": l.net_basis, "mental_net": _mental_net_basis(l), "tol_nb": tol_nb, "tol_cf": tol_cf,
        "bond_dv01": bond_dv01, "fut_dv01": fut_dv01})


# =============================================================================================================

@template("futures.stir_strip", skill="futures.stir", difficulty=2)
def stir_strip(rng: random.Random) -> QuestionBody:
    """Hedge a short-dated swap with a strip of 3M Euribor futures: size, direction, price from the curve, what is left."""
    mkt = random_market(rng)
    years = rng.choice([2, 3])
    n = 4 * years
    receive = rng.random() < 0.5
    notional = rng.choice([50, 100, 150, 200, 250]) * 1e6
    swap = par_irs(Side.RECEIVE if receive else Side.PAY, notional, years, mkt)
    swap_dv01 = parallel_dv01(swap, mkt)
    per_m = unit_dv01(years, mkt)
    contracts = strip(mkt.anchor, n)
    strip_dv01 = sum(parallel_dv01(c, mkt) for c in contracts)
    each = -swap_dv01 / strip_dv01                                         # contracts in EACH quarter (signed: negative = sell)
    total = each * n
    total_mental = -swap_dv01 / STIR_BP_VALUE
    hedge = [replace(c, contracts=each) for c in contracts]
    book = Portfolio([swap, *hedge])
    move = rng.choice([8, 10, 12])
    residual = revalue_pnl(book, mkt, CurveShock.parallel(move))
    unhedged = revalue_pnl(swap, mkt, CurveShock.parallel(move))
    strip_pnl = revalue_pnl(Portfolio(hedge), mkt, CurveShock.parallel(move))
    j = n // 2
    c = contracts[j]
    fwd_shown, ca_shown = round(c.forward(mkt) * 100, 3), round(c.convexity * 1e4, 1)
    price = c.price(mkt)
    price_mental = 100.0 - fwd_shown - ca_shown / 100.0
    sell = each < 0
    verb = "receive" if receive else "pay"
    names = ", ".join(f"{c.start:%b-%y}" for c in contracts[:2]) + f" ... {contracts[-1].start:%b-%y}"
    stem = (
        f"You {verb} fixed on {eur_m(notional)} of a {years}Y EUR IRS at the market. A €1m {years}Y swap has a DV01 of €{per_m:,.0f}. "
        f"{DV01_CONVENTION.replace('yields', 'rates')}\n"
        f"You hedge with the same number of contracts in each of the first {n} quarterly 3M Euribor futures ({names}). One contract is €1m of notional: "
        "€25 per bp (a tick of 0.005 is €12.50), price = 100 - the futures rate, and a LONG position gains when the price rises."
    )
    parts = [
        shuffled_choice(
            rng, "What position in the futures hedges the swap?",
            [("SELL" if sell else "BUY") + " the strip: " + ("a receiver gains when rates fall and futures prices rise, so you offset by selling them"
                                                             if sell else "a payer gains when rates rise and futures prices fall, so you offset by buying them"),
             ("BUY" if sell else "SELL") + " the strip: futures behave like the fixed leg of the swap",
             "Sell the strip if rates are low and buy it if they are high",
             "No hedge is needed: futures settle daily"],
            "A long future gains when the price rises, which is when rates FALL, so it is long duration, like a receiver. A receiver is therefore hedged by SELLING the strip, "
            "a payer by BUYING it."),
        NumericPart(f"How many contracts in total (across all {n} quarters) hedge the swap's DV01? ({'sell' if sell else 'buy'} = {'negative' if sell else 'positive'})",
                    total, Tolerance(rel=0.06), "contracts", approx=total_mental, approx_label="swap DV01 / €25",
                    sign_hint="Opposite the swap: a receiver is hedged by SELLING futures (negative).",
                    note="swap DV01 / €25 per contract"),
        NumericPart(f"The {c.start:%b-%y} contract: the curve's 3M forward rate for its period is {fwd_shown:.3f}% and its convexity adjustment is {ca_shown:.1f}bp "
                    f"(futures rate = forward + adjustment). What is its price?", price, Tolerance(abs=0.003), "pts", approx=price_mental,
                    approx_label="100 - (forward + adjustment)", note="a price near 97.5, to 3 decimals"),
        NumericPart(f"Rates then rise {move}bp in parallel. What is the P&L on the FUTURES strip you hold (EUR)?", strip_pnl,
                    Tolerance(rel=0.06), "EUR", approx=-total * STIR_BP_VALUE * move, approx_label="-(contracts) x €25 x move",
                    sign_hint=("You are short futures: they fall when rates rise, so you GAIN." if sell else "You are long futures: they fall when rates rise, so you LOSE."),
                    note="contracts x €25 per bp x move"),
        shuffled_choice(
            rng, "The futures rate for a contract two years out is HIGHER than the forward rate from the curve (the FRA rate) for the same period. Why?",
            ["Daily margining: a long future gains cash when rates fall and loses it when they rise, so it is worth less than a FRA to the long, and its price is lower (rate higher)",
             "Futures are priced off the 6M curve and FRAs off the 3M curve",
             "The FRA includes the credit risk of the counterparty",
             "It is not higher: futures and FRA rates are identical"],
            "A FRA settles once, at the start of the period. A future settles every day, so profits and losses are paid and received as rates move. A long future pays margin when rates rise "
            "(funded dearly) and receives it when they fall (reinvested cheaply): the margining is a drag that grows with the volatility of rates and the time to the contract. "
            "Hence the futures rate exceeds the forward rate by the convexity adjustment, which is small near term and grows with the SQUARE of time (here "
            f"{ca_shown:.1f}bp {c.start.year - mkt.anchor.year}y out)."),
    ]
    solution = [
        f"Swap DV01 = {fmt_eur(swap_dv01)} ({eur_m(notional)} x €{per_m:,.0f} per €1m). Each contract is worth about €25 per bp, so {n} contracts across the strip are worth ≈ €{25 * n} per bp for ONE "
        f"contract in every quarter: you need {abs(total_mental):,.0f} contracts in total ({abs(total_mental) / n:,.0f} per quarter). Engine, with each contract's own DV01 "
        f"(€24-25, because a 1bp move in par swap rates moves a 3M forward by a little under 1bp): {abs(total):,.0f}.",
        f"Direction: {verb} fixed is {'long' if receive else 'short'} duration, so {'SELL' if sell else 'BUY'} the strip.",
        f"Price of the {c.start:%b-%y} contract = 100 - (forward {fwd_shown:.3f}% + {ca_shown:.1f}bp) = {price_mental:.3f} (engine {price:.4f}).",
        f"For +{move}bp the strip makes {fmt_eur(strip_pnl)} ({abs(total):,.0f} contracts x €25 x {move}bp = {fmt_eur(abs(total) * 25 * move, False)} quick) against {fmt_eur(unhedged)} on the swap: "
        f"together {fmt_eur(residual)}. A DV01-matched hedge removes the parallel move (what is left is convexity). "
        "Its weaknesses show up when the curve moves NON-parallel: the swap starts at spot but the strip at the first IMM date (a stub is unhedged), the swap's risk is not spread "
        "evenly over the quarters, a swap's annuity is discounted while a future's DV01 is not, and a 6M-Euribor swap is being hedged with 3M contracts.",
        "A strip hedges PARALLEL risk and the right size per quarter; it is a front-end tool. A key-rate hedge sizes each quarter separately: the quarters of a swap do not all carry the same risk.",
    ]
    return QuestionBody(stem, parts, solution, {
        "mkt": mkt, "swap": swap, "swap_dv01": swap_dv01, "strip_dv01": strip_dv01, "total": total, "each": each, "total_mental": total_mental,
        "n": n, "j": j, "price": price, "price_mental": price_mental, "residual": residual, "unhedged": unhedged, "strip_pnl": strip_pnl, "receive": receive,
        "move": move, "fwd_shown": fwd_shown, "ca_shown": ca_shown})
