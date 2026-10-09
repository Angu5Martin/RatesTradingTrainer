"""Money-market and bond-pricing mechanics: bills, day counts, compounded ESTR, clean and dirty bond prices.

All of it is closed-form arithmetic a desk does mentally, so the answers are exact formulas; where the engine has the same quantity (bond
accrued and yield-price, in engine.instruments) the engine produces the answer and the tests recompute it independently.
"""

from __future__ import annotations

import math
import random
from datetime import date

from ...engine.instruments import FixedBond
from ..market import eur_m, random_trade_date
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template

# --------------------------------------------------------------------------------------------------------------------- bills

BILLS = (("1M", 28), ("2M", 56), ("3M", 91), ("4M", 119), ("6M", 182), ("9M", 273), ("12M", 364))


@template("bonds.bill_price_yield", skill="bonds.money_market", difficulty=2, kind="calculation")
def bill_price_yield(rng: random.Random) -> QuestionBody:
    """A zero-coupon bill quoted as a money-market yield: price, cash, DV01, a yield move, and bills against OIS."""
    label, days = rng.choice(BILLS)
    y = round(rng.uniform(0.012, 0.036), 4)
    face = rng.choice([10, 25, 50, 100, 250]) * 1e6
    move = rng.choice([-15, -10, -8, -5, 5, 8, 10, 15])
    tau = days / 360.0
    price = 100.0 / (1.0 + y * tau)
    cash = face * price / 100.0
    mod_dur = tau / (1.0 + y * tau)
    dv01 = cash * mod_dur * 1e-4
    price2 = 100.0 / (1.0 + (y + move * 1e-4) * tau)
    exact = face * (price2 - price) / 100.0
    spread = rng.choice([-1, 1]) * rng.choice([4, 6, 8, 10, 12, 15]) * 1e-4
    ois = round(y + spread, 4)
    rich = ois > y

    stem = (
        f"A {label} EUR government bill ({days} days to maturity) quoted at a money-market yield of {y * 100:.3f}% "
        "(simple interest, ACT/360). Bills are zero-coupon: they pay 100 at maturity and nothing before.\n"
        f"You BUY {eur_m(face)} face. DV01 = P&L for a 1bp FALL in yield (positive when long)."
    )
    parts = [
        NumericPart("What is the price per 100 face?", price, Tolerance(rel=0, abs=0.004), "pts", note="100 / (1 + y x days/360)"),
        NumericPart("How much cash do you pay for the position (EUR)?", cash, Tolerance(rel=0.0005), "EUR"),
        NumericPart("What is the DV01 of the position?", dv01, Tolerance(rel=0.045), "EUR", approx=cash * tau * 1e-4,
                    approx_label="cash x years to maturity x 1bp", sign_hint="You are long the bill: DV01 is positive.",
                    note="cash x modified duration x 1bp; a bill's duration is just under its maturity in years"),
        NumericPart(f"The bill yield moves {move:+d}bp. What is your P&L?", exact, Tolerance(rel=0.04), "EUR", approx=-dv01 * move,
                    sign_hint="Long a bill: you gain when its yield falls and lose when it rises."),
        shuffled_choice(
            rng, f"The {label} ESTR OIS rate is {ois * 100:.3f}% (also ACT/360). Against OIS, the bill is:",
            [f"{'Rich' if rich else 'Cheap'}: its yield is {abs(spread) * 1e4:.0f}bp {'below' if rich else 'above'} OIS, so you accept "
             f"{'less' if rich else 'more'} than the overnight-compounded alternative",
             f"{'Cheap' if rich else 'Rich'}: its yield is {abs(spread) * 1e4:.0f}bp {'below' if rich else 'above'} OIS",
             "Fair: bills and OIS must have the same yield",
             "Not comparable: bills and OIS use different day counts"],
            "Both are ACT/360 simple rates, so the yields compare directly. A bill yielding less than OIS is rich: investors pay up for the "
            "collateral value and safety of the paper. A bill above OIS is cheap, which is a carry pickup if you can fund it at ESTR."),
    ]
    solution = [
        f"Price = 100 / (1 + {y:.4f} x {days}/360) = {price:.4f}; cash = {eur_m(face)} x {price:.4f}/100 = {fmt_eur(cash, False)}.",
        f"Modified duration = tau / (1 + y x tau) = {tau:.4f} / {1 + y * tau:.4f} = {mod_dur:.4f} years. DV01 = {fmt_eur(cash, False)} x "
        f"{mod_dur:.4f} x 0.0001 = {fmt_eur(dv01, False)}. In your head: cash x years x 1bp = {fmt_eur(cash * tau * 1e-4, False)}.",
        f"P&L for {move:+d}bp: first order {fmt_eur(-dv01 * move)}; repricing at {(y + move * 1e-4) * 100:.3f}% gives price {price2:.4f} and "
        f"{fmt_eur(exact)}. A bill has almost no convexity, so the two agree to a few euros.",
        f"Bills are low-DV01: {label} per €100m face is about {fmt_eur(dv01 / face * 1e8, False)}, against roughly €45,000 for a 5Y swap. "
        "They are funding and collateral instruments first, rate-risk instruments second.",
        f"Against OIS: {y * 100:.3f}% vs {ois * 100:.3f}% = {abs(spread) * 1e4:.0f}bp {'rich' if rich else 'cheap'}.",
    ]
    return QuestionBody(stem, parts, solution, {"days": days, "y": y, "face": face, "price": price, "cash": cash, "dv01": dv01,
                                                 "move": move, "exact": exact, "ois": ois, "rich": rich})


# --------------------------------------------------------------------------------------------------------------------- day counts

@template("bonds.mm_day_count", skill="bonds.money_market", difficulty=2, kind="calculation")
def mm_day_count(rng: random.Random) -> QuestionBody:
    """Two deposits quoted on different day counts: interest in cash, conversion, and the annual-equivalent yield."""
    while True:
        days = rng.choice([91, 92, 182, 183])
        ra = round(rng.uniform(0.014, 0.034), 4)
        if abs((1.0 + ra * days / 360.0) ** (365.0 / days) - 1.0 - ra * 365 / 360) > 0.00015:     # compounding must matter at this precision
            break
    gap = rng.choice([-1, 1]) * rng.choice([1.5, 2.5, 3.5, 5.0]) * 1e-4
    rb = round(ra * 365 / 360 + gap, 5)              # bank B quotes ACT/365: a flat rate there is ~1.4% higher than the same ACT/360 rate
    notional = rng.choice([25, 50, 100, 200]) * 1e6
    cash_a = notional * ra * days / 360.0
    cash_b = notional * rb * days / 365.0
    rb360 = rb * 360 / 365
    eff = (1.0 + ra * days / 360.0) ** (365.0 / days) - 1.0
    b_pays_more = cash_b > cash_a

    stem = (
        f"Two banks quote a {days}-day EUR deposit, both simple interest:\n"
        f"  Bank A: {ra * 100:.3f}%  ACT/360 (the euro convention)\n"
        f"  Bank B: {rb * 100:.3f}%  ACT/365\n"
        f"You place {eur_m(notional)}."
    )
    parts = [
        NumericPart("How much interest does Bank A pay at maturity (EUR)?", cash_a, Tolerance(rel=0.005), "EUR", note="notional x rate x days/360"),
        NumericPart("Bank B's rate expressed on ACT/360 (in %):", rb360 * 100, Tolerance(rel=0, abs=0.002), "%",
                    approx=rb * 100, approx_label="Bank B's rate with no day-count adjustment", accept_approx=False,
                    note="same interest in cash, a different year length"),
        shuffled_choice(
            rng, "Which bank pays more interest?",
            [("Bank B" if b_pays_more else "Bank A") + f", by about {fmt_eur(abs(cash_b - cash_a), False)}",
             ("Bank A" if b_pays_more else "Bank B") + f", by about {fmt_eur(abs(cash_b - cash_a), False)}",
             "They pay the same: the stated rates differ only by convention"],
            "A rate quoted on a 365-day year must be about 1.4% (365/360) higher than an ACT/360 rate to pay the same cash. Comparing the headline "
            f"numbers ({rb * 100:.3f}% vs {ra * 100:.3f}%) misleads by about {abs(rb - ra) * 1e4:.1f}bp; the like-for-like gap is "
            f"{abs(rb360 - ra) * 1e4:.1f}bp."),
        NumericPart("Rolling Bank A's deposit at the same rate for a full year, what is the effective annual yield (in %, ACT/365)?",
                    eff * 100, Tolerance(rel=0, abs=0.005), "%", approx=ra * 365 / 360 * 100,
                    approx_label="simple conversion to ACT/365 (no compounding)", accept_approx=False,
                    note="(1 + r x days/360)^(365/days) - 1"),
    ]
    solution = [
        f"Bank A: {eur_m(notional)} x {ra:.5f} x {days}/360 = {fmt_eur(cash_a, False)}.",
        f"Bank B: {eur_m(notional)} x {rb:.5f} x {days}/365 = {fmt_eur(cash_b, False)}. On ACT/360 it is {rb360 * 100:.3f}%.",
        f"A 360-day rate converts to a 365-day rate by x 365/360 (about +1.4%): {ra * 100:.3f}% ACT/360 = {ra * 365 / 360 * 100:.3f}% ACT/365.",
        f"Compounding every {days} days over a year gives (1 + {ra:.4f} x {days}/360)^(365/{days}) - 1 = {eff * 100:.3f}%, "
        f"{(eff - ra * 365 / 360) * 1e4:.1f}bp above the simple ACT/365 equivalent.",
        "Always put quotes on the same basis (day count, compounding) before comparing them: much of a 'spread' between markets "
        "can be convention.",
    ]
    return QuestionBody(stem, parts, solution, {"days": days, "ra": ra, "rb": rb, "cash_a": cash_a, "cash_b": cash_b, "rb360": rb360, "eff": eff})


# --------------------------------------------------------------------------------------------------------------------- ESTR compounding

@template("swaps.estr_compounding", skill="swaps.ois_vs_ibor", difficulty=2, kind="calculation")
def estr_compounding(rng: random.Random) -> QuestionBody:
    """One week of ESTR compounded in arrears: why the Friday fixing counts three times, and why OIS and Euribor legs differ in timing."""
    for _ in range(200):
        base = round(rng.uniform(0.016, 0.034), 4)
        step = rng.choice([-0.0050, -0.0025, -0.0025, 0.0025, 0.0025, 0.0050])
        k = rng.choice([1, 2, 3, 4])                     # first fixing (0 = Monday) at the new level: the ECB decision takes effect
        fixes = [round(base + rng.uniform(-0.00008, 0.00008), 5) + (step if i >= k else 0.0) for i in range(5)]
        weights = [1, 1, 1, 1, 3]
        growth = math.prod(1.0 + r * d / 360.0 for r, d in zip(fixes, weights))
        comp = (growth - 1.0) * 360.0 / 7.0
        naive = sum(fixes) / 5.0
        if abs(comp - naive) > 0.00012:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a compounding case")
    notional = rng.choice([100, 250, 500, 1000]) * 1e6
    interest = notional * (growth - 1.0)
    weighted = sum(r * d for r, d in zip(fixes, weights)) / 7.0
    names = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    rows = "  ".join(f"{n} {r * 100:.3f}%" for n, r in zip(names, fixes))
    stem = (
        "A one-week stub of a EUR OIS floating leg: ESTR compounded daily in arrears from Monday to the following Monday (7 calendar days, ACT/360). "
        "Each business-day fixing applies until the next business day, so Friday's fixing applies for 3 days (Fri, Sat, Sun).\n"
        f"Fixings: {rows}   (the ECB's decision took effect on {names[k]})\n"
        f"Notional {eur_m(notional)}."
    )
    parts = [
        NumericPart("What is the compounded ESTR rate for the week (in %, ACT/360)?", comp * 100, Tolerance(rel=0, abs=0.004), "%",
                    approx=naive * 100, approx_label="the plain average of the five fixings", accept_approx=False,
                    note="product of (1 + fixing x days/360), minus 1, annualised over 7 days"),
        NumericPart("How much floating interest accrues for the week (EUR)?", interest, Tolerance(rel=0.01), "EUR",
                    note="notional x (compounded growth - 1)"),
        shuffled_choice(
            rng, "Compared with a 6M Euribor floating leg, when is the rate of this ESTR leg known?",
            ["Only at the end: ESTR is compounded in arrears, so each day's fixing is published after the day; Euribor is set at the start of its period",
             "At the start of the period, like Euribor, because ESTR is an overnight rate",
             "ESTR leg rates are known a month ahead; Euribor is set in arrears",
             "Both are set in arrears; the difference is only in the day count"],
            "A 6M Euribor payment is fixed at the start of the period (known, then paid at the end); compounded ESTR is only known as the days pass. "
            "That is why an OIS floating leg has almost no reset risk once the period starts, and why a central-bank move shows up in it day by day."),
    ]
    solution = [
        f"Weights: {', '.join(f'{n} x{d}' for n, d in zip(names, weights))}. Growth = product of (1 + fixing x d/360) = {growth:.8f}.",
        f"Compounded rate = ({growth:.8f} - 1) x 360/7 = {comp * 100:.4f}%. Day-weighted average without compounding: {weighted * 100:.4f}%. "
        f"Over a week the compounding itself is worth only {abs(comp - weighted) * 1e4:.2f}bp; the real lesson is the weighting: the plain average of the fixings, "
        f"{naive * 100:.4f}%, is {abs(naive - comp) * 1e4:.1f}bp off because it ignores that Friday counts three times.",
        f"Interest = {eur_m(notional)} x ({growth:.8f} - 1) = {fmt_eur(interest, False)}.",
        "An OIS floating leg is therefore a compounding of realised overnight rates: a receiver of fixed is long the policy path, not a "
        "forecast of one fixing.",
    ]
    return QuestionBody(stem, parts, solution, {"fixes": fixes, "growth": growth, "comp": comp, "naive": naive, "interest": interest, "k": k, "notional": notional})


# --------------------------------------------------------------------------------------------------------------------- clean / dirty

@template("bonds.clean_dirty_accrued", skill="bonds.duration_convexity", difficulty=2, kind="calculation")
def clean_dirty_accrued(rng: random.Random) -> QuestionBody:
    """A government bond settling between coupon dates: accrued, dirty price, cash, and the price effect of a yield move."""
    for _ in range(300):
        anchor = random_trade_date(rng)
        mat = date(anchor.year + rng.randint(3, 11), rng.randint(1, 12), rng.choice([4, 15]))
        coupon = rng.choice([0.0, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035])
        bond = FixedBond.from_maturity(100.0, coupon, mat, anchor)
        per = next((p for p in bond.periods if p.start < anchor < p.end), None)
        if per is None:
            continue
        since, length = (anchor - per.start).days, (per.end - per.start).days
        if not 25 <= since <= length - 25 or coupon == 0.0:
            continue
        y0 = round(rng.uniform(0.015, 0.038), 4)
        accrued = bond.accrued(anchor)
        clean = round(bond.dirty_from_yield(anchor, y0) - accrued, 2)
        dirty = clean + accrued
        y = bond.yield_from_dirty(anchor, dirty)
        break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a bond")
    face = rng.choice([10, 25, 50, 100]) * 1e6
    move = rng.choice([-25, -20, -15, -10, 10, 15, 20, 25])
    md = bond.modified_duration(anchor, y)
    clean2 = bond.dirty_from_yield(anchor, y + move * 1e-4) - accrued
    d_clean = clean2 - clean
    approx = -md * dirty * move * 1e-4
    premium = clean > 100.0

    stem = (
        f"A EUR government bond: {coupon * 100:.3f}% annual coupon, maturing {mat:%d-%b-%Y}. It settles on {anchor:%d-%b-%Y}.\n"
        f"  Last coupon {per.start:%d-%b-%Y}, next coupon {per.end:%d-%b-%Y}: {since} days have elapsed in a coupon period of {length} days "
        "(ACT/ACT: accrued interest builds pro rata).\n"
        f"  Quoted CLEAN price {clean:.2f}, yield {y * 100:.3f}%, modified duration {md:.2f}. You buy {eur_m(face)} face."
    )
    parts = [
        NumericPart("What accrued interest is owed per 100 face?", accrued, Tolerance(rel=0, abs=0.006), "pts",
                    note="coupon x days elapsed / days in the period"),
        NumericPart("What is the dirty (full) price per 100 face?", dirty, Tolerance(rel=0, abs=0.01), "pts", note="clean + accrued"),
        NumericPart("How much cash settles on the purchase (EUR)?", face * dirty / 100.0, Tolerance(rel=0.0004), "EUR"),
        NumericPart(f"Yields {'rise' if move > 0 else 'fall'} {abs(move)}bp before settlement and accrued interest is unchanged. By how many price points does the CLEAN price change (signed)?",
                    d_clean, Tolerance(rel=0.03, abs=0.03), "pts", approx=approx, approx_label="-modified duration x dirty price x yield change",
                    sign_hint="Prices and yields move in opposite directions.", note="modified duration applies to the dirty price"),
        shuffled_choice(
            rng, "At this clean price, and with yields unchanged, what happens to the CLEAN price as the bond approaches maturity?",
            [f"It {'falls' if premium else 'rises'} towards 100 (pull to par): the bond trades at a {'premium' if premium else 'discount'}"
             f" because its coupon is {'above' if premium else 'below'} the yield",
             f"It {'rises' if premium else 'falls'} towards 100",
             "It stays constant: only the yield matters",
             "It rises by exactly the accrued interest each day"],
            f"A bond whose yield is {'below' if premium else 'above'} its coupon trades at a {'premium' if premium else 'discount'} and must converge to 100 at maturity, so its clean price drifts "
            f"{'down' if premium else 'up'}. The drift is part of carry: coupon income and pull-to-par together, against funding."),
    ]
    solution = [
        f"Accrued = {coupon * 100:.3f} x {since}/{length} = {accrued:.4f} per 100.",
        f"Dirty = clean + accrued = {clean:.2f} + {accrued:.4f} = {dirty:.4f}; cash = {eur_m(face)} x {dirty:.4f}/100 = {fmt_eur(face * dirty / 100, False)}. "
        "You pay the seller for the coupon earned since the last coupon date, and receive the full coupon back on the next one.",
        f"Price change for {move:+d}bp: duration estimate -{md:.2f} x {dirty:.3f} x {move * 1e-4:+.4f} = {approx:+.3f} points; repricing from the yield gives "
        f"{d_clean:+.3f}. Duration applies to the dirty price, not the clean one: they differ by the accrued, which is a few percent of the price.",
        "Quotes are clean so that the price does not saw-tooth by the coupon every year; settlement cash is dirty.",
    ]
    return QuestionBody(stem, parts, solution, {"bond": bond, "anchor": anchor, "accrued": accrued, "clean": clean, "dirty": dirty, "y": y, "md": md,
                                                 "since": since, "length": length, "d_clean": d_clean, "approx": approx, "face": face})


# --------------------------------------------------------------------------------------------------------------------- solving for the yield move

@template("bonds.price_to_yield_move", skill="bonds.duration_convexity", difficulty=2, kind="calculation")
def price_to_yield_move(rng: random.Random) -> QuestionBody:
    """Work backwards: from a price move to the yield move that caused it, and from there to the P&L on a position and the hedge."""
    from ...engine.instruments import bond_modified_duration, bond_price
    maturity = rng.choice([5, 7, 10, 15, 20, 30])
    coupon = rng.choice([0.01, 0.015, 0.02, 0.025, 0.03, 0.035])
    y = round(rng.uniform(0.015, 0.040), 4)
    dy_bp = rng.choice([-1, 1]) * rng.choice([12, 18, 25, 35, 45, 60])
    face = rng.choice([20, 50, 100, 200]) * 1e6
    long_ = rng.random() < 0.6
    price = bond_price(coupon, maturity, y)
    price2 = bond_price(coupon, maturity, y + dy_bp * 1e-4)
    d_price = round(price2 - price, 2)
    md = bond_modified_duration(coupon, maturity, y)
    implied = -d_price / (md * price) * 1e4
    pnl = (1 if long_ else -1) * face * d_price / 100.0
    dv01_pos = (1 if long_ else -1) * face * price / 100.0 * md * 1e-4
    stem = (
        f"A {maturity}Y EUR government bond, annual {coupon * 100:.2f}% coupon, yields {y * 100:.3f}% and is priced at {price:.3f} (valued on a coupon date). Its modified duration is {md:.2f}.\n"
        f"You are {'long' if long_ else 'short'} {eur_m(face)} face. Today its price moves by {d_price:+.2f} points."
    )
    parts = [
        NumericPart("By how many bp did the yield move (signed, + = yields up)?", dy_bp, Tolerance(rel=0.12, abs=1.0), "bp", approx=implied,
                    approx_label="-price change / (modified duration x price)", sign_hint="Prices and yields move in opposite directions.",
                    note="price change / (price x modified duration), then flip the sign"),
        NumericPart("What is your P&L on the day (EUR)?", pnl, Tolerance(rel=0.01), "EUR", sign_hint="A short position makes money when the price falls."),
        NumericPart("What is the DV01 of the position (EUR per bp, positive = long)?", dv01_pos, Tolerance(rel=0.03), "EUR",
                    sign_hint="Long bonds have positive DV01; short, negative.", note="market value x modified duration x 1bp"),
        shuffled_choice(
            rng, "The same yield move hits a bond with a longer maturity and the same coupon and yield. Compared with this bond, its price change is:",
            ["Larger: it has a higher duration, so each bp of yield moves its price more",
             "Smaller: longer bonds are less sensitive because their cash flows are far away",
             "The same: price depends only on the yield change",
             "Opposite in sign"],
            "Price sensitivity to yield is duration. A longer bond has more of its value in distant cash flows, which are the most sensitive to the discount rate, so its price moves more for the same yield change."),
    ]
    solution = [
        f"Price {price:.3f} -> {price2:.3f}, a move of {d_price:+.2f}. Duration estimate of the yield move = -({d_price:+.2f}) / ({md:.2f} x {price:.3f}) x 10,000 = {implied:+.1f}bp "
        f"(repricing gives {dy_bp:+d}bp; the gap is convexity).",
        f"P&L = {eur_m(face)} x {d_price:+.2f}/100 x ({'+' if long_ else '-'}1) = {fmt_eur(pnl)}.",
        f"DV01 = {'+' if long_ else '-'}{eur_m(face)} x {price:.3f}/100 x {md:.2f} x 0.0001 = {fmt_eur(dv01_pos)}. The day's P&L divided by the DV01 gives the move: {-pnl / dv01_pos:+.1f}bp.",
        "Working backwards from the price move to the risk number is how a trader reads a P&L: how many bp of yield does it explain, and is that what the market did?",
    ]
    return QuestionBody(stem, parts, solution, {"coupon": coupon, "maturity": maturity, "y": y, "dy_bp": dy_bp, "price": price, "d_price": d_price, "md": md, "implied": implied,
                                                 "pnl": pnl, "dv01_pos": dv01_pos, "long": long_})
