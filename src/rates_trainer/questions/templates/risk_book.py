"""Key-rate risk, convexity and curve-shape templates.

Everything comes from the engine: bucket DV01s from `key_rate_dv01` (bump one par quote, re-bootstrap, reprice), hedges from `solve_key_rate_hedge`
and `dv01_hedge_swap`, P&L from full revaluation (`revalue_pnl`). The trainee's mental route is the first-order sum of bucket DV01 x move, shown as `approx`.
"""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import key_rate_first_order_pnl, revalue_pnl
from ...engine.risk import (Portfolio, dv01_hedge_swap, key_rate_dv01, par_irs, parallel_dv01, solve_key_rate_hedge, unit_dv01)
from ..market import eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template

BUCKETS = (2, 5, 10, 30)


def bucket_of(months: int) -> int:
    """The reporting bucket (years) a risk key belongs to: <=2Y, 3-7Y, 8-15Y, longer."""
    return 2 if months <= 24 else 5 if months <= 84 else 10 if months <= 180 else 30


def bucketed(kr: dict) -> dict[str, dict[int, float]]:
    """{curve: {bucket_years: DV01}} from a key-rate dictionary {(curve, months): DV01}."""
    out: dict[str, dict[int, float]] = {"E6M": {b: 0.0 for b in BUCKETS}, "OIS": {b: 0.0 for b in BUCKETS}}
    for (name, m), d in kr.items():
        if name in out:
            out[name][bucket_of(m)] += d
    return out


def kfmt(x: float) -> str:
    return "0.0k" if abs(x) < 50 else f"{x / 1e3:+,.1f}k"


def _notional_for(dv01: float, tenor: int, mkt, start: float = 0.0) -> float:
    """Whole-euro-million notional giving roughly the wanted DV01 (positive number) for an at-market swap of this tenor."""
    unit = unit_dv01(tenor, mkt)                   # per EUR 1m
    return max(1.0, round(abs(dv01) / unit)) * 1e6


def _swap(sign: int, notional: float, tenor: int, mkt, start: float = 0.0):
    return par_irs(Side.RECEIVE if sign > 0 else Side.PAY, notional, tenor, mkt, start_years=start)


def _name(tenor: int) -> str:
    return f"{tenor}Y"


def _first_correct(rng, prompt: str, right: str, options: list[str], why: str):
    """A multiple choice with the correct option stated separately (the others are the rest of `options`), shuffled by rng."""
    return shuffled_choice(rng, prompt, [right, *[o for o in options if o != right]], why)


# ------------------------------------------------------------------------------------------------------------------ key-rate report

_MODE_LABEL = {
    "outright_long": "Outright long duration: gains if rates fall across the curve",
    "outright_short": "Outright short duration: gains if rates rise across the curve",
    "steepener": "A curve steepener: long short-end duration, short long-end duration, gains if the curve steepens",
    "flattener": "A curve flattener: short short-end duration, long long-end duration, gains if the curve flattens",
    "fly_long": "A butterfly long the belly: gains if the middle richens relative to the wings",
    "fly_short": "A butterfly short the belly: gains if the middle cheapens relative to the wings",
}


@template("risk.key_rate_read", skill="risk.key_rate", difficulty=2, kind="calculation")
def key_rate_read(rng: random.Random) -> QuestionBody:
    """Reading a bucketed risk report: what kind of position it is, what a non-parallel move does, and which hedges remove it."""
    for _ in range(100):
        mkt = random_market(rng)
        mode = rng.choice(["outright_long", "outright_short", "steepener", "flattener", "fly_long", "fly_short"])
        mags = [50e3, 75e3, 100e3, 150e3, 200e3, 250e3, 300e3]
        legs: list[tuple[int, int, float]] = []                     # (tenor, sign, target DV01)
        if mode.startswith("outright"):
            tenors = sorted(rng.sample(BUCKETS, rng.choice([2, 3])))
            sgn = 1 if mode.endswith("long") else -1
            legs = [(t, sgn, rng.choice(mags)) for t in tenors]
        elif mode in ("steepener", "flattener"):
            a, b = sorted(rng.sample(BUCKETS, 2))
            da = rng.choice(mags)
            db = round(da * rng.uniform(0.9, 1.1) / 5e3) * 5e3
            s = 1 if mode == "steepener" else -1
            legs = [(a, s, da), (b, -s, db)]
        else:
            a, b, c = rng.choice([(2, 5, 10), (2, 10, 30), (5, 10, 30)])
            db = rng.choice([100e3, 150e3, 200e3, 300e3])
            s = 1 if mode == "fly_long" else -1
            legs = [(a, -s, round(db / 2 * rng.uniform(0.9, 1.1) / 5e3) * 5e3), (b, s, db), (c, -s, round(db / 2 * rng.uniform(0.9, 1.1) / 5e3) * 5e3)]
        trades = [_swap(sg, _notional_for(d, t, mkt), t, mkt) for t, sg, d in legs]
        book = Portfolio(trades)
        kr = key_rate_dv01(book, mkt, curves=("E6M",))
        bk = bucketed(kr)["E6M"]
        net = sum(bk.values())
        gross = sum(abs(v) for v in bk.values())
        move = {b: float(rng.choice([-8, -6, -4, -2, 0, 2, 4, 6, 8, 10])) for b in BUCKETS}
        shock = CurveShock.points(move)
        first = key_rate_first_order_pnl(kr, shock, curves=("E6M",))
        full = revalue_pnl(book, mkt, shock, curves=("E6M",))
        tol_abs = 0.012 * sum(abs(bk[b]) * abs(move[b]) for b in BUCKETS)
        ok_net = (abs(net) > 0.7 * gross) if mode.startswith("outright") else (abs(net) < 0.25 * gross)
        if ok_net and abs(full) > 2.5 * max(0.05 * abs(full), tol_abs) and len(set(move.values())) > 2:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a key-rate book")

    live = [b for b in BUCKETS if abs(bk[b]) > 1.0]
    big = max(live, key=lambda b: abs(bk[b]))
    hedge_to_flat = -bk[big] / unit_dv01(big, mkt) * 1e6                 # signed: + = receive
    rows = "\n".join(f"  {b:>2}Y bucket: {kfmt(bk[b])} per bp" for b in BUCKETS)
    others = [m for m in _MODE_LABEL if m != mode]
    opts = [_MODE_LABEL[mode], *[_MODE_LABEL[m] for m in rng.sample(others, 3)]]
    small = min(live, key=lambda t: abs(bk[t]))
    names = ", ".join(_name(t) for t in live)
    hedge_opts = [f"Swaps in the {names} buckets, each sized to its own bucket's DV01",
                  f"One {_name(max(live))} swap sized to the book's total DV01 ({fmt_eur(abs(net), False)})",
                  f"Swaps in the {', '.join(_name(t) for t in live if t != small)} {'buckets' if len(live) > 2 else 'bucket'} only, each sized to its own DV01",
                  f"Swaps in the {names} buckets, each sized to the same notional"]

    stem = (
        f"EUR IRS curve: 2Y {pct(mkt.quotes['E6M'][24])} | 5Y {pct(mkt.quotes['E6M'][60])} | 10Y {pct(mkt.quotes['E6M'][120])} | 30Y {pct(mkt.quotes['E6M'][360])}\n"
        "Your risk system reports the book's key-rate DV01 by bucket (EUR per 1bp FALL in the swap rates in that bucket; positive = long duration):\n"
        f"{rows}"
    )
    mv = ", ".join(f"{b}Y {move[b]:+.0f}bp" for b in BUCKETS)
    parts = [
        NumericPart("What is the book's DV01 to a parallel move (EUR per bp)?", net, Tolerance(rel=0.02, abs=1500.0), "EUR",
                    sign_hint="Add the buckets with their signs.", note="the sum of the buckets"),
        shuffled_choice(rng, "Which description best fits this position?", opts,
                        "Read the signs and sizes: one sign across buckets is an outright position; opposite signs of similar size are a curve trade "
                        "(long duration at the short end, short at the long end, profits if the curve steepens); a belly against two opposite wings is a butterfly."),
        NumericPart(f"The swap curve moves as follows: {mv} (linear in between). What is your P&L (EUR)?", full, Tolerance(rel=0.05, abs=tol_abs), "EUR",
                    approx=first, approx_label="sum of -(bucket DV01 x move)", sign_hint="Rates up hurts long-duration buckets; rates down helps them.",
                    note="multiply each bucket by its own move"),
        NumericPart(f"You want to flatten the largest bucket ({big}Y) with one at-market {big}Y swap. What notional? (+ = receive fixed, - = pay fixed)",
                    hedge_to_flat, Tolerance(rel=0.04), "EUR", sign_hint="Hedge long duration by paying fixed.", note="bucket DV01 / DV01 per EUR 1m"),
        shuffled_choice(rng, "Which hedge set removes ALL the exposure shown (to first order)?", hedge_opts,
                        "Each bucket with a non-zero DV01 needs its own hedge: a single swap sized to the total DV01 removes the parallel risk but leaves the curve "
                        "shape (the opposite-signed buckets) in place, and a missing bucket leaves its risk unhedged."),
    ]
    solution = [
        f"Total = sum of buckets = {fmt_eur(net)} per bp ({'close to the gross of ' + fmt_eur(gross, False) if abs(net) > 0.7 * gross else 'much smaller than the gross of ' + fmt_eur(gross, False) + ': the position is mostly curve shape, not direction'}).",
        f"Shape: {_MODE_LABEL[mode]}.",
        f"P&L (first order) = - sum(bucket DV01 x move) = {fmt_eur(first)}; full revaluation {fmt_eur(full)}. Moves are linear in tenor between the stated buckets, "
        "and each bucket's risk is sensitive to its own rate: that is why a book with a small net DV01 can still make or lose real money.",
        f"{big}Y hedge: {fmt_eur(abs(bk[big]), False)} / ({fmt_eur(unit_dv01(big, mkt), False)} per EUR 1m) = {eur_m(abs(hedge_to_flat))}, "
        f"{'receive' if hedge_to_flat > 0 else 'pay'} fixed.",
        "Hedging the parallel DV01 alone (one swap) is the mistake this report prevents: the buckets that are not offset become the curve exposure.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "mode": mode, "buckets": bk, "net": net, "full": full, "first": first, "move": move,
                                                 "big": big, "hedge_to_flat": hedge_to_flat, "book": book})


# ------------------------------------------------------------------------------------------------------------------ forward-start hedge

_FWD_PAIRS = ((2, 5), (2, 10), (5, 10), (5, 15), (3, 10), (5, 30), (10, 20), (10, 30))


@template("risk.key_rate_hedge", skill="risk.key_rate", difficulty=3, kind="calculation")
def key_rate_hedge(rng: random.Random) -> QuestionBody:
    """A forward-starting swap is risk in two buckets, not one: hedge it bucket by bucket, then see what a single parallel hedge leaves behind."""
    for _ in range(100):
        mkt = random_market(rng)
        a, b = rng.choice(_FWD_PAIRS)
        side = rng.choice(list(Side))
        notional = rng.choice([50, 100, 150, 200, 250, 300]) * 1e6
        fwd = par_irs(side, notional, b - a, mkt, start_years=a)
        kr = key_rate_dv01(fwd, mkt, curves=("E6M",))
        ka, kb = kr[("E6M", a * 12)], kr[("E6M", b * 12)]
        hedges = solve_key_rate_hedge({k: v for k, v in kr.items()}, [("IRS", a), ("IRS", b)], mkt)
        signed = {}
        for h in hedges:
            tenor = round((h.fixed_periods[-1].end - mkt.spot).days / 365.25)
            signed[tenor] = h.notional if h.side is Side.RECEIVE else -h.notional
        na, nb = signed.get(a, 0.0), signed.get(b, 0.0)
        tot = sum(kr.values())                                           # E6M buckets only: the 'swap curve' this question is about
        one = dv01_hedge_swap(tot, b, mkt)                              # the lazy hedge: DV01-neutral in the b-year swap alone
        book = Portfolio([fwd, one])
        m = rng.choice([-6, -5, -4, 4, 5, 6])
        shock = CurveShock.points({float(a): float(m), float(b): 0.0})
        resid = revalue_pnl(book, mkt, shock, curves=("E6M",))
        first = -(ka * m)
        if na and nb and abs(resid) > 1500 and abs(na) > 0.5 * notional:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a forward-start hedge")
    verb = "receive" if side is Side.RECEIVE else "pay"
    one_signed = one.notional if one.side is Side.RECEIVE else -one.notional
    stem = (
        f"EUR IRS curve: {a}Y {pct(mkt.quotes['E6M'][a * 12])} | {b}Y {pct(mkt.quotes['E6M'][b * 12])} (6M Euribor swaps).\n"
        f"You {verb} fixed on a {eur_m(notional)} {a}y{b - a}y forward-starting swap (it starts in {a} years and runs {b - a} years, to year {b}), struck at the forward rate.\n"
        f"Its key-rate DV01s (EUR per bp fall): {a}Y bucket {kfmt(ka)}, {b}Y bucket {kfmt(kb)}; total {kfmt(tot)}."
    )
    parts = [
        NumericPart(f"Using at-market {b}Y and {a}Y swaps, what {b}Y notional neutralises the {b}Y bucket? (+ = receive fixed, - = pay fixed)", nb,
                    Tolerance(rel=0.04), "EUR", approx=-notional if side is Side.RECEIVE else notional,
                    approx_label="the forward swap's own notional, opposite direction", sign_hint="Offset the sign of the bucket.",
                    note=f"DV01 of the {b}Y bucket / DV01 per EUR 1m of a {b}Y swap"),
        NumericPart(f"What {a}Y notional neutralises the {a}Y bucket? (+ = receive fixed, - = pay fixed)", na, Tolerance(rel=0.04), "EUR",
                    approx=notional if side is Side.RECEIVE else -notional, approx_label="the forward swap's own notional, opposite direction",
                    sign_hint="The forward swap is long one bucket and short the other: the two hedges are opposite.", note="same method"),
        NumericPart(f"Instead you hedge only the total DV01 with a single at-market {b}Y swap ({eur_m(one.notional)}, {'receive' if one.side is Side.RECEIVE else 'pay'} fixed). "
                    f"The {a}Y rate then moves {m:+d}bp while the {b}Y rate does not. What is the P&L of forward swap plus hedge (EUR)?", resid, Tolerance(rel=0.06, abs=1500),
                    "EUR", approx=first, approx_label=f"-(the {a}Y bucket DV01 x move)", sign_hint=f"Only the {a}Y bucket is left unhedged: what is its sign?"),
        shuffled_choice(rng, "What does the single-swap hedge leave you with?",
                        [f"A {a}s{b}s curve position: parallel moves cancel, but the {a}Y and {b}Y buckets now carry equal and opposite exposures",
                         "Nothing: a DV01-neutral hedge removes all interest-rate risk",
                         f"A pure {b}Y outright exposure",
                         f"A basis position between Euribor and ESTR"],
                        "A forward-starting swap is a position in the spread between two points on the curve. Hedging only its total DV01 makes it parallel-neutral, but the "
                        "buckets are not cancelled: they now offset each other, which is a curve trade."),
    ]
    solution = [
        f"A {a}y{b - a}y forward swap is, in par-rate risk, the {b}Y swap minus the {a}Y swap at the SAME notional: forward rate = (S{b} x A{b} - S{a} x A{a}) / (A{b} - A{a}), "
        f"and its annuity is A{b} - A{a}, so its sensitivity to S{b} is N x A{b}, exactly that of a {eur_m(notional)} {b}Y swap.",
        f"Hedges from the engine: {b}Y {fmt_eur(nb)}, {a}Y {fmt_eur(na)} (equal notionals, opposite to the forward swap). The DV01 per euro differs by tenor, "
        f"but the notionals are the same: the two buckets' DV01s ({kfmt(ka)} and {kfmt(kb)}) are NOT equal and opposite.",
        f"Single {b}Y DV01 hedge: total {fmt_eur(tot)} / ({fmt_eur(unit_dv01(b, mkt), False)} per EUR 1m) = {eur_m(one.notional)}, a notional "
        f"{'smaller' if one.notional < notional else 'larger'} than the forward swap's. The {a}Y bucket ({kfmt(ka)}) is untouched and the {b}Y bucket is now {kfmt(-ka)}: "
        f"the total is zero but the two buckets offset each other. A {m:+d}bp move in the {a}Y alone is {fmt_eur(first)} first order, {fmt_eur(resid)} by revaluation.",
        "Equivalent portfolios, one view: 5y5y = 5Y + 10Y with opposite signs at equal notional. Reading forward-starting risk as two spot swaps is the quickest way to hedge it.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "fwd": fwd, "a": a, "b": b, "na": na, "nb": nb, "ka": ka, "kb": kb, "tot": tot, "one": one,
                                                 "resid": resid, "first": first, "m": m, "notional": notional})


# ------------------------------------------------------------------------------------------------------------------ convexity

@template("risk.convexity_barbell", skill="risk.convexity", difficulty=3, kind="calculation")
def convexity_barbell(rng: random.Random) -> QuestionBody:
    """A DV01-neutral barbell against a bullet: neutral for small moves, positive convexity P&L for big moves in either direction."""
    for _ in range(100):
        mkt = random_market(rng)
        a, b, c = rng.choice([(2, 10, 30), (2, 5, 10), (5, 10, 30), (2, 7, 30)])
        n_belly = rng.choice([50, 100, 150, 200]) * 1e6
        belly = par_irs(Side.PAY, n_belly, b, mkt)
        d_belly = abs(parallel_dv01(belly, mkt))
        wa = dv01_hedge_swap(-d_belly / 2, a, mkt)
        wc = dv01_hedge_swap(-d_belly / 2, c, mkt)
        book = Portfolio([wa, wc, belly])
        m = rng.choice([50, 75, 100])
        down, up = mkt.shifted(CurveShock.parallel(-m)), mkt.shifted(CurveShock.parallel(m))
        dv_now = parallel_dv01(book, mkt)
        dv_down = parallel_dv01(book, down)
        pnl_down = revalue_pnl(book, mkt, CurveShock.parallel(-m))
        pnl_up = revalue_pnl(book, mkt, CurveShock.parallel(m))
        legs_down = [parallel_dv01(x, down) for x in (wa, wc, belly)]
        legs_up = [parallel_dv01(x, up) for x in (wa, wc, belly)]
        dv_up = sum(legs_up)
        if pnl_down > 4000 and pnl_up > 4000 and dv_down > 1500 and dv_up < -1500 and abs(dv_now) < 0.01 * d_belly:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a barbell")
    est = 0.5 * dv_down * m
    est_up = -0.5 * dv_up * m
    stem = (
        f"EUR IRS curve: {a}Y {pct(mkt.quotes['E6M'][a * 12])} | {b}Y {pct(mkt.quotes['E6M'][b * 12])} | {c}Y {pct(mkt.quotes['E6M'][c * 12])}.\n"
        f"You RECEIVE fixed in the {a}Y ({eur_m(wa.notional)}) and the {c}Y ({eur_m(wc.notional)}) and PAY fixed in the {b}Y ({eur_m(n_belly)}). "
        f"The {a}Y and {c}Y legs each carry half the {b}Y leg's DV01, so the book's parallel DV01 is {fmt_eur(dv_now)}: neutral.\n"
        f"After a {m}bp FALL in all swap rates the legs' DV01s (EUR per bp) would be: {a}Y {kfmt(legs_down[0])}, {c}Y {kfmt(legs_down[1])}, {b}Y {kfmt(legs_down[2])}.\n"
        f"After a {m}bp RISE they would be: {a}Y {kfmt(legs_up[0])}, {c}Y {kfmt(legs_up[1])}, {b}Y {kfmt(legs_up[2])}."
    )
    parts = [
        NumericPart(f"What would the book's net DV01 be after a {m}bp rally (EUR per bp)?", dv_down, Tolerance(rel=0.02, abs=400), "EUR",
                    sign_hint="Add the three legs; the sign of the pay leg is negative.", note="the sum of the three DV01s shown"),
        NumericPart(f"All rates fall {m}bp. What is the P&L of the book (EUR)?", pnl_down, Tolerance(rel=0.15), "EUR", approx=est,
                    approx_label="half the change in DV01 x the move", sign_hint="A barbell against a bullet is long convexity.",
                    note="the DV01 changed linearly from zero to the figure above: use its average"),
        NumericPart(f"Instead all rates RISE {m}bp. What is the P&L (EUR)?", pnl_up, Tolerance(rel=0.15), "EUR", approx=est_up,
                    approx_label="half the (negative) net DV01 after the rise x the move, with its sign flipped",
                    sign_hint="Long convexity pays in both directions.", note="the same method with the rise figures"),
        shuffled_choice(
            rng, "If convexity pays in both directions, what stops this from being free money?",
            [f"The market charges for it: the barbell's yield (carry and roll-down) is lower than the bullet's, so you pay a steady cost that the convexity must beat",
             "Nothing: DV01-neutral long-convexity positions are arbitrage",
             "The convexity P&L only appears when rates rise",
             "The barbell is not really DV01-neutral, so it loses money on parallel moves"],
            "Convexity is a priced characteristic. You earn it only on large moves, and you fund it through lower carry and roll-down; the trade pays "
            "when realised moves are bigger than the market's pricing of them."),
    ]
    solution = [
        f"Net DV01 after the {m}bp rally = {kfmt(legs_down[0])} + {kfmt(legs_down[1])} + {kfmt(legs_down[2])} = {fmt_eur(dv_down)} per bp: the book turns LONG duration as rates fall "
        f"and SHORT duration as they rise ({fmt_eur(dv_up)} after the sell-off). That is long convexity: it buys duration as the market rallies and sells it as it sells off.",
        f"Convexity P&L ~ 1/2 x (change in DV01) x (move) = 0.5 x {fmt_eur(dv_down)} x {m} = {fmt_eur(est)}. Full revaluation for the rally: {fmt_eur(pnl_down)}. "
        f"For the sell-off the net DV01 turns to {fmt_eur(dv_up)}: P&L ~ {fmt_eur(est_up)}; revalued {fmt_eur(pnl_up)}.",
        "For a small move the P&L is nearly zero (the book is DV01-neutral); it scales with the SQUARE of the move: the rally and the sell-off earn about the same, and doubling the move quadruples the P&L.",
        "Who pays for it? The bullet holder is short convexity and is paid carry or roll for that: a barbell is a bet that realised volatility exceeds what its financing costs imply.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "book": book, "m": m, "dv_down": dv_down, "pnl_down": pnl_down, "pnl_up": pnl_up, "est": est,
                                                 "legs_down": legs_down, "est_up": est_up, "dv_up": dv_up})


# ------------------------------------------------------------------------------------------------------------------ butterfly

_FLIES = ((2, 5, 10), (3, 5, 7), (5, 7, 10), (5, 10, 30), (2, 10, 30), (10, 15, 20), (7, 10, 15))


@template("curves.butterfly", skill="curve.butterfly", difficulty=3, kind="calculation")
def butterfly(rng: random.Random) -> QuestionBody:
    """A DV01-weighted butterfly: wing sizes, P&L from a non-parallel move, and which move it profits from."""
    for _ in range(300):
        mkt = random_market(rng)
        a, b, c = rng.choice(_FLIES)
        long_belly = rng.random() < 0.5                         # receive the belly, pay the wings
        belly_side = Side.RECEIVE if long_belly else Side.PAY
        n_belly = rng.choice([50, 75, 100, 150, 200]) * 1e6
        belly = par_irs(belly_side, n_belly, b, mkt)
        d_b = parallel_dv01(belly, mkt)
        wa, wc = dv01_hedge_swap(d_b / 2, a, mkt), dv01_hedge_swap(d_b / 2, c, mkt)       # opposite direction, half the belly DV01 each
        book = Portfolio([wa, belly, wc])
        ma, mb, mc = (float(rng.choice([-6, -4, -3, -2, 0, 2, 3, 4, 6])) for _ in range(3))
        shock = CurveShock.points({float(a): ma, float(b): mb, float(c): mc})
        pnl = revalue_pnl(book, mkt, shock)
        approx = -(parallel_dv01(wa, mkt) * ma + d_b * mb + parallel_dv01(wc, mkt) * mc)
        fly_move = 2 * mb - ma - mc
        # the scenario ranking for the last part
        scen = {
            "parallel +10bp": (10.0, 10.0, 10.0),
            f"{b}Y outperforms by 4bp ({b}Y -4bp, wings unchanged)": (0.0, -4.0, 0.0),
            f"the wings outperform by 4bp ({a}Y and {c}Y -4bp, {b}Y unchanged)": (-4.0, 0.0, -4.0),
            f"a pure steepening around the belly ({a}Y -4bp, {b}Y unchanged, {c}Y +4bp)": (-4.0, 0.0, 4.0),
        }
        res = {k: revalue_pnl(book, mkt, CurveShock.points({float(a): v[0], float(b): v[1], float(c): v[2]})) for k, v in scen.items()}
        best = max(res, key=lambda k: res[k])
        tol_abs = 0.012 * (abs(d_b) * (abs(mb) + (abs(ma) + abs(mc)) / 2))
        if abs(pnl) > 2.5 * max(0.05 * abs(pnl), tol_abs) and abs(fly_move) >= 2:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a butterfly")
    pa, pb, pc = (round(unit_dv01(t, mkt)) for t in (a, b, c))
    ranked = sorted(res, key=lambda k: -res[k])
    right = ranked[0]
    names = list(res)
    others = [k for k in names if k != right]
    verb = "RECEIVE" if long_belly else "PAY"
    opp = "PAY" if long_belly else "RECEIVE"
    stem = (
        f"EUR IRS curve: {a}Y {pct(mkt.quotes['E6M'][a * 12])} | {b}Y {pct(mkt.quotes['E6M'][b * 12])} | {c}Y {pct(mkt.quotes['E6M'][c * 12])}.\n"
        f"DV01 per EUR 1m of an at-market swap: {a}Y EUR {pa}, {b}Y EUR {pb}, {c}Y EUR {pc}.\n"
        f"You trade a DV01-weighted {a}s{b}s{c}s butterfly: you {verb} fixed on {eur_m(n_belly)} {b}Y (the belly) and {opp} fixed in the {a}Y and {c}Y wings, "
        "each wing carrying half the belly's DV01. The fly spread is 2 x belly - wing - wing, in bp."
    )
    parts = [
        NumericPart(f"What {a}Y wing notional does half the belly's DV01 require?", abs(wa.notional), Tolerance(rel=0.04), "EUR", note="half the belly DV01 / DV01 per EUR 1m"),
        NumericPart(f"What {c}Y wing notional?", abs(wc.notional), Tolerance(rel=0.04), "EUR"),
        NumericPart(f"The swap curve moves {a}Y {ma:+.0f}bp, {b}Y {mb:+.0f}bp, {c}Y {mc:+.0f}bp. What is the P&L of the fly (EUR)?", pnl,
                    Tolerance(rel=0.05, abs=tol_abs), "EUR", approx=approx, approx_label="-sum(leg DV01 x move)",
                    sign_hint=f"You {verb.lower()} the belly: you gain when the {b}Y rate falls relative to the wings.",
                    note="belly move against the average of the wing moves"),
        shuffled_choice(rng, f"Which of these moves makes the most money for your fly ({verb.lower()} the belly)?", [right, *others],
                        f"Being {'long' if long_belly else 'short'} the belly means you profit when the belly {'richens (rates fall)' if long_belly else 'cheapens (rates rise)'} relative to the average of the wings. "
                        "A parallel move or a steepening that leaves the belly at the average of the wings does nothing, because the legs' DV01s are balanced."),
    ]
    solution = [
        f"Belly DV01 = {fmt_eur(d_b)}; each wing carries {fmt_eur(d_b / 2)}: {a}Y {eur_m(abs(wa.notional))}, {c}Y {eur_m(abs(wc.notional))}. "
        "Wings are not equal notionals: the longer wing has more DV01 per euro.",
        f"P&L = -[{ma:+.0f} x {fmt_eur(parallel_dv01(wa, mkt))} + {mb:+.0f} x {fmt_eur(d_b)} + {mc:+.0f} x {fmt_eur(parallel_dv01(wc, mkt))}] = {fmt_eur(approx)} first order; "
        f"revalued {fmt_eur(pnl)}. Equivalently -(DV01 belly/2) x (fly change {fly_move:+.0f}bp) = {fmt_eur(-d_b / 2 * fly_move)}.",
        "Scenario P&Ls (full revaluation): " + "; ".join(f"{k}: {fmt_eur(v)}" for k, v in res.items()) + ".",
        "A 50:50 DV01 fly is neutral to level and to a slope move that leaves the belly at the wings' average: it isolates curvature. "
        "Equal NOTIONALS would not be neutral to either, because DV01 per euro rises with tenor.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "a": a, "b": b, "c": c, "long_belly": long_belly, "wa": wa, "wc": wc, "belly": belly, "pnl": pnl,
                                                 "approx": approx, "moves": (ma, mb, mc), "scenarios": res, "right": right, "d_b": d_b})


# ------------------------------------------------------------------------------------------------------------------ curve moves

_PAIRS = ((2, 10), (2, 5), (5, 10), (5, 30), (10, 30), (2, 30))
_MOVE_NAMES = {("down", "steeper"): "bull steepening", ("down", "flatter"): "bull flattening",
               ("up", "steeper"): "bear steepening", ("up", "flatter"): "bear flattening"}


@template("curves.move_decomposition", skill="curve.direction", difficulty=2, kind="calculation")
def move_decomposition(rng: random.Random) -> QuestionBody:
    """Name a curve move, split it into level and slope, and see what it does to a DV01-neutral steepener."""
    for _ in range(300):
        mkt = random_market(rng)
        s, l = rng.choice(_PAIRS)
        ms = float(rng.choice([-9, -7, -6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 7, 9]))
        ml = float(rng.choice([-9, -7, -6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 7, 9]))
        if ms == ml or abs(ms + ml) < 3 or abs(ml - ms) < 3:
            continue
        steepener = rng.random() < 0.5
        n_long = rng.choice([50, 100, 150, 200]) * 1e6
        long_leg = par_irs(Side.PAY if steepener else Side.RECEIVE, n_long, l, mkt)
        d_l = parallel_dv01(long_leg, mkt)
        short_leg = dv01_hedge_swap(d_l, s, mkt)
        book = Portfolio([short_leg, long_leg])
        pnl = revalue_pnl(book, mkt, CurveShock.points({float(s): ms, float(l): ml}))
        slope = ml - ms
        level = (ml + ms) / 2
        if abs(pnl) > 2500:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a curve move")
    direction = "up" if level > 0 else "down"
    shape = "steeper" if slope > 0 else "flatter"
    name = _MOVE_NAMES[(direction, shape)]
    approx = (slope if steepener else -slope) * abs(d_l)
    options = list(_MOVE_NAMES.values())
    stem = (
        f"The {s}Y swap rate moves {ms:+.0f}bp and the {l}Y swap rate moves {ml:+.0f}bp.\n"
        f"You hold a DV01-neutral {s}s{l}s {'steepener' if steepener else 'flattener'} built from the {eur_m(n_long)} {l}Y leg "
        f"({'pay' if steepener else 'receive'} fixed) and a {s}Y leg in the opposite direction. The {l}Y leg's DV01 is {fmt_eur(d_l)} per bp."
    )
    parts = [
        _first_correct(rng, "Which description fits the move?", name, options,
                    "Bull = rates fall, bear = rates rise (named for the bond price); steepening = the long end moves up relative to the short end, flattening the reverse. "
                    f"The level moved {level:+.1f}bp (average) and the slope ({l}Y minus {s}Y) {slope:+.0f}bp."),
        NumericPart("By how much did the LEVEL of the curve move (the average of the two rates, bp)?", level, Tolerance(rel=0.05, abs=0.3), "bp", sign_hint="Average, signed."),
        NumericPart(f"By how much did the {s}s{l}s SLOPE ({l}Y minus {s}Y, bp) change?", slope, Tolerance(rel=0.05, abs=0.3), "bp",
                    sign_hint=f"Positive = {l}Y moved up more than the {s}Y: steepening."),
        NumericPart("What is the P&L of your curve position (EUR)?", pnl, Tolerance(rel=0.05, abs=0.015 * abs(d_l) * max(abs(ms), abs(ml))), "EUR", approx=approx,
                    approx_label=f"{'+' if steepener else '-'}(slope change) x leg DV01",
                    sign_hint=f"A {'steepener' if steepener else 'flattener'} gains when the curve {'steepens' if steepener else 'flattens'}, whatever the level does.",
                    note="slope change x the leg DV01, signed by your trade"),
    ]
    solution = [
        f"Level = ({ms:+.0f} + {ml:+.0f}) / 2 = {level:+.1f}bp ({'rates up: bear' if level > 0 else 'rates down: bull'}). Slope = {ml:+.0f} - ({ms:+.0f}) = {slope:+.0f}bp "
        f"({'steeper' if slope > 0 else 'flatter'}). Together: {name}.",
        f"A DV01-neutral curve trade ignores level: P&L = {'+' if steepener else '-'}slope change x DV01 = {'+' if steepener else '-'}({slope:+.0f}) x {fmt_eur(abs(d_l), False)} = {fmt_eur(approx)}; "
        f"revalued {fmt_eur(pnl)}.",
        "Direction and curve shape are separate: a 'bull steepener' and a 'bear flattener' can both lose money for an outright position, but a DV01-neutral trade only sees the slope.",
        "In practice the shape of a move says where the repricing is happening: bear flattening is the front end repricing to tighter policy; bull steepening is the front end repricing to cuts.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "s": s, "l": l, "ms": ms, "ml": ml, "level": level, "slope": slope, "name": name, "steepener": steepener,
                                                 "pnl": pnl, "approx": approx, "d_l": d_l})


# ------------------------------------------------------------------------------------------------------------------ level / slope / curvature

LOADINGS = {"level": (1.0, 1.0, 1.0, 1.0), "slope": (-1.5, -0.5, 0.5, 1.5), "curvature": (1.0, -1.0, -1.0, 1.0)}
FACTOR_VOL = {"level": 5.0, "slope": 2.0, "curvature": 1.0}          # stylised daily vols of one unit of each factor, bp


@template("risk.factor_exposure", skill="risk.key_rate", difficulty=3, kind="calculation")
def factor_exposure(rng: random.Random) -> QuestionBody:
    """Re-express bucket DV01s as level, slope and curvature exposures, then ask which one the book is really about and what a mixed move does."""
    for _ in range(300):
        mkt = random_market(rng)
        tenors = sorted(rng.sample(BUCKETS, 3))
        legs = [(t, rng.choice([-1, 1]), rng.choice([50e3, 100e3, 150e3, 200e3, 250e3])) for t in tenors]
        book = Portfolio([_swap(sg, _notional_for(d, t, mkt), t, mkt) for t, sg, d in legs])
        kr = key_rate_dv01(book, mkt, curves=("E6M",))
        bk = bucketed(kr)["E6M"]
        d = [bk[b] for b in BUCKETS]
        fdv = {f: sum(x * l for x, l in zip(d, load)) for f, load in LOADINGS.items()}
        risk = {f: abs(fdv[f]) * FACTOR_VOL[f] for f in LOADINGS}
        order = sorted(risk, key=lambda f: -risk[f])
        if risk[order[0]] < 1.4 * risk[order[1]]:
            continue
        move = {"level": rng.choice([-8.0, -4.0, 0.0, 4.0, 8.0]), "slope": rng.choice([-4.0, -2.0, 0.0, 2.0, 4.0]), "curvature": rng.choice([-3.0, -1.5, 0.0, 1.5, 3.0])}
        if sum(v != 0 for v in move.values()) < 2:
            continue
        bucket_move = {float(b): sum(move[f] * LOADINGS[f][i] for f in LOADINGS) for i, b in enumerate(BUCKETS)}
        full = revalue_pnl(book, mkt, CurveShock.points(bucket_move), curves=("E6M",))
        first = -sum(fdv[f] * move[f] for f in LOADINGS)
        tol_abs = 0.012 * sum(abs(x) * abs(bucket_move[float(b)]) for x, b in zip(d, BUCKETS))
        if abs(full) > 2.5 * max(0.05 * abs(full), tol_abs) and all(abs(fdv[f]) > 8e3 for f in LOADINGS):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a factor-exposure book")
    names = {"level": "Level", "slope": "Slope", "curvature": "Curvature"}
    rows = "\n".join(f"  {b:>2}Y bucket: {kfmt(bk[b])} per bp" for b in BUCKETS)
    stem = (
        "Your risk report (EUR per 1bp FALL in the swap rate in each bucket; positive = long duration):\n" + rows + "\n"
        "Describe curve moves with three factors; one UNIT of each moves the buckets (2Y, 5Y, 10Y, 30Y) by:\n"
        "  Level:     +1, +1, +1, +1 bp\n  Slope:     -1.5, -0.5, +0.5, +1.5 bp   (positive = steepening)\n  Curvature: +1, -1, -1, +1 bp   (positive = the wings up against the belly)\n"
        "A factor DV01 is the P&L for a 1-unit FALL in the factor, so it is the sum of bucket DV01 x loading. "
        f"Typical daily moves: level {FACTOR_VOL['level']:g} units, slope {FACTOR_VOL['slope']:g}, curvature {FACTOR_VOL['curvature']:g}."
    )
    mv = ", ".join(f"{names[f].lower()} {move[f]:+g}" for f in LOADINGS if move[f] != 0)
    parts = [
        NumericPart("What is the book's level DV01 (EUR per unit)?", fdv["level"], Tolerance(rel=0.02, abs=1500), "EUR", sign_hint="Sum the buckets with signs."),
        NumericPart("What is the book's slope DV01 (EUR per unit of slope fall)?", fdv["slope"], Tolerance(rel=0.03, abs=1500), "EUR",
                    sign_hint="Weight each bucket by its slope loading, with its sign.", note="sum of bucket DV01 x slope loading"),
        NumericPart("What is the book's curvature DV01 (EUR per unit)?", fdv["curvature"], Tolerance(rel=0.03, abs=1500), "EUR", note="wings minus belly"),
        NumericPart(f"The curve moves by: {mv} (units). What is your P&L (EUR)?", full, Tolerance(rel=0.05, abs=tol_abs), "EUR", approx=first,
                    approx_label="-sum(factor DV01 x move)", sign_hint="P&L = -(factor DV01 x factor move) for each factor, added up."),
        shuffled_choice(rng, "Weighting each factor DV01 by its typical daily move, which factor drives the book's day-to-day risk?",
                        [f"{names[order[0]]}: {fmt_eur(abs(fdv[order[0]]) * FACTOR_VOL[order[0]], False)} of one-sigma P&L from that factor",
                         *[f"{names[f]}" for f in order[1:]], "None: the factors cancel each other"],
                        "Exposure alone does not rank risks: a small curvature exposure is dwarfed by the same exposure to level, because level moves are bigger. Multiply each factor "
                        "exposure by its typical move to see where the risk actually lives."),
    ]
    solution = [
        "Factor DV01s: " + "; ".join(f"{names[f].lower()} = {fmt_eur(fdv[f])}" for f in LOADINGS) + ".",
        f"Scenario ({mv}): P&L = -[" + " + ".join(f"({fmt_eur(fdv[f])}) x ({move[f]:+g})" for f in LOADINGS if move[f] != 0) + f"] = {fmt_eur(first)}; revalued {fmt_eur(full)}.",
        "One-sigma P&L by factor: " + "; ".join(f"{names[f].lower()} {fmt_eur(risk[f], False)}" for f in LOADINGS) + f". The book is mainly a {order[0]} position.",
        "Level, slope and curvature are one way to organise the bucket risks; the same book can be read in buckets (where to hedge) or in factors (what to worry about). "
        "A principal-components analysis of historical curve moves produces such factors from data, with level typically explaining most of the variance.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "book": book, "buckets": bk, "fdv": fdv, "move": move, "full": full, "first": first, "order": order, "risk": risk})


# ------------------------------------------------------------------------------------------------------------------ equal notional is not neutral

@template("curves.equal_notional_trap", skill="curve.steepener", difficulty=2, kind="calculation")
def equal_notional_trap(rng: random.Random) -> QuestionBody:
    """A curve trade struck at equal notionals is a duration position in disguise: find its DV01, its P&L in a parallel move, and the neutral size."""
    for _ in range(100):
        mkt = random_market(rng)
        s, l = rng.choice([(2, 10), (2, 5), (5, 10), (5, 30), (10, 30), (2, 30)])
        steepener = rng.random() < 0.5
        n = rng.choice([50, 100, 150, 200]) * 1e6
        long_leg = par_irs(Side.PAY if steepener else Side.RECEIVE, n, l, mkt)
        short_leg = par_irs(Side.RECEIVE if steepener else Side.PAY, n, s, mkt)
        book = Portfolio([short_leg, long_leg])
        d_l, d_s = parallel_dv01(long_leg, mkt), parallel_dv01(short_leg, mkt)
        net = d_l + d_s
        neutral = dv01_hedge_swap(d_l, s, mkt)
        move = rng.choice([8, 10, 12, -8, -10, -12])
        pnl = revalue_pnl(book, mkt, CurveShock.parallel(move))
        pnl_neutral = revalue_pnl(Portfolio([neutral, long_leg]), mkt, CurveShock.parallel(move))
        if abs(net) > 0.4 * abs(d_l) and abs(pnl) > 6 * abs(pnl_neutral):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw an equal-notional trap")
    dir_word = "short" if net < 0 else "long"
    name = f"{s}s{l}s {'steepener' if steepener else 'flattener'}"
    stem = (
        f"A colleague builds a {name} with EQUAL notionals of {eur_m(n)}: {'pay' if steepener else 'receive'} fixed on the {l}Y and "
        f"{'receive' if steepener else 'pay'} fixed on the {s}Y, both at the market.\n"
        f"The {l}Y leg's DV01 is {fmt_eur(d_l)} per bp (positive = long duration)."
    )
    parts = [
        NumericPart("What is the DV01 of the whole package (EUR per bp)?", net, Tolerance(rel=0.05, abs=1500), "EUR",
                    sign_hint="Add the two legs: the larger-DV01 leg wins.", note=f"the {s}Y leg's DV01 is about {fmt_eur(abs(d_s), False)}"),
        NumericPart(f"All rates {'rise' if move > 0 else 'fall'} {abs(move)}bp in parallel. What is the P&L of the package (EUR)?", pnl, Tolerance(rel=0.06, abs=0.03 * abs(d_l) * abs(move)),
                    "EUR", approx=-net * move, approx_label="-(package DV01) x move"),
        NumericPart(f"What {s}Y notional would make the package DV01-neutral (EUR)?", neutral.notional, Tolerance(rel=0.04), "EUR",
                    note=f"{l}Y DV01 / DV01 per EUR 1m of the {s}Y"),
        shuffled_choice(
            rng, "What does the equal-notional package really express?",
            [f"A {name} PLUS an unintended {dir_word}-duration position of about {fmt_eur(abs(net), False)} per bp (the {l}Y leg is the bigger DV01)",
             f"A pure {name}: equal notionals are what make a curve trade neutral",
             "A pure outright position in the long end",
             "No position at all: the two legs cancel"],
            f"DV01 per euro rises with maturity, so equal notionals leave the {l}Y leg with more risk than the {s}Y leg. The package responds to the level of rates as well as to the "
            "slope, which is not what a curve trader meant to put on."),
    ]
    solution = [
        f"{l}Y leg {fmt_eur(d_l)}, {s}Y leg {fmt_eur(d_s)}: package DV01 = {fmt_eur(net)}.",
        f"Parallel {move:+d}bp: -({fmt_eur(net)}) x ({move:+d}) = {fmt_eur(-net * move)}; revalued {fmt_eur(pnl)}. A DV01-neutral version, with a {s}Y notional of {eur_m(neutral.notional)}, makes "
        f"{fmt_eur(pnl_neutral)} on the same move: it is flat to level.",
        f"The neutral {s}Y notional is {neutral.notional / n:.1f}x the {l}Y's because the {s}Y has only about {abs(d_s) / abs(d_l) * 100:.0f}% of the {l}Y's DV01 per euro at equal notional.",
        "Always size curve trades in DV01 (or against a risk target), then convert to notional. A curve trade that makes money when rates fall is not a curve trade.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "book": book, "net": net, "d_l": d_l, "d_s": d_s, "pnl": pnl, "neutral": neutral, "pnl_neutral": pnl_neutral,
                                                 "steepener": steepener, "s": s, "l": l, "move": move})


# ------------------------------------------------------------------------------------------------------------------ convexity of a single swap

@template("pnl.convexity_asymmetry", skill="pnl.convexity", difficulty=2, kind="calculation")
def convexity_asymmetry(rng: random.Random) -> QuestionBody:
    """A single swap in a big move: the DV01-only estimate misses an asymmetry that favours the receiver and costs the payer."""
    for _ in range(100):
        mkt = random_market(rng)
        tenor = rng.choice([10, 20, 30])
        side = rng.choice(list(Side))
        notional = rng.choice([50, 100, 150, 250]) * 1e6
        m = rng.choice([75, 100, 125])
        swap = par_irs(side, notional, tenor, mkt)
        dv01 = parallel_dv01(swap, mkt)
        dv_after = parallel_dv01(swap, mkt.shifted(CurveShock.parallel(-m)))
        dv_after_up = parallel_dv01(swap, mkt.shifted(CurveShock.parallel(m)))
        p_dn = revalue_pnl(swap, mkt, CurveShock.parallel(-m))
        p_up = revalue_pnl(swap, mkt, CurveShock.parallel(m))
        first = abs(dv01) * m
        mid = (p_dn + p_up) / 2
        if abs(mid) > 0.08 * first:
            break
    est = (dv_after - dv_after_up) * m / 4                  # the trader's route: gamma = (DV01 after a fall - DV01 after a rise) / (2 x move); convexity P&L = 1/2 gamma m^2
    verb = "receive" if side is Side.RECEIVE else "pay"
    long_cx = side is Side.RECEIVE
    stem = (
        f"You {verb} fixed on a {eur_m(notional)} {tenor}Y EUR swap struck at the market. DV01 is {fmt_eur(dv01)} per bp today; after a {m}bp FALL in rates it would be {fmt_eur(dv_after)}, and after a {m}bp RISE {fmt_eur(dv_after_up)}.\n"
        "All swap rates move in parallel."
    )
    parts = [
        NumericPart(f"What is the P&L if rates FALL {m}bp (full revaluation, EUR)?", p_dn, Tolerance(rel=0.04), "EUR", approx=dv01 * m, approx_label="DV01 x move (first order)", accept_approx=False,
                    sign_hint=f"A {verb}er of fixed {'gains' if long_cx else 'loses'} when rates fall.", note="the DV01 changes along the way: use the average of today's and the final one"),
        NumericPart(f"What is the P&L if rates RISE {m}bp (full revaluation, EUR)?", p_up, Tolerance(rel=0.04), "EUR", approx=-dv01 * m, approx_label="-DV01 x move (first order)",
                    accept_approx=False, sign_hint=f"A {verb}er of fixed {'loses' if long_cx else 'gains'} when rates rise."),
        NumericPart("What is the convexity P&L: the average of the two P&Ls (EUR)? A positive number is a gain from convexity.", mid, Tolerance(rel=0.12, abs=0.01 * first), "EUR",
                    approx=est, approx_label="(DV01 after the fall - DV01 after the rise) x move / 4",
                    note="the first-order parts cancel in the average, what is left is convexity"),
        shuffled_choice(rng, f"Compared with the DV01-only estimate, what does convexity do to this {verb}er of fixed?",
                        [("It helps: the gain from a fall is larger than the loss from an equal rise" if long_cx else "It hurts: the loss from a fall is larger than the gain from an equal rise"),
                         ("It hurts: the loss from a rise is larger than the gain from an equal fall" if long_cx else "It helps: the gain from a rise is larger than the loss from an equal fall"),
                         "It makes no difference: a swap is linear in rates",
                         "It only matters for options, not for swaps and bonds"],
                        "A receiver behaves like a bond: its DV01 grows when rates fall and shrinks when they rise, so it gains more than the linear estimate in a rally and loses less in a sell-off. "
                        "A payer is the mirror image. The effect scales with the square of the move and with the maturity."),
    ]
    solution = [
        f"First order: DV01 x move = {fmt_eur(abs(dv01) * m, False)} either way. Full revaluation: fall {fmt_eur(p_dn)}, rise {fmt_eur(p_up)}.",
        f"Their average, {fmt_eur(mid)}, is the convexity P&L. The trader's route: gamma = (DV01 after the fall - DV01 after the rise) / (2 x {m}); convexity P&L = 1/2 x gamma x move^2 = "
        f"({fmt_eur(dv_after)} - ({fmt_eur(dv_after_up)})) x {m} / 4 = {fmt_eur(est)}.",
        f"The DV01-only estimate misses {fmt_eur(p_dn - dv01 * m)} on the fall and {fmt_eur(p_up + dv01 * m)} on the rise: convexity is a gain for a receiver and a cost for a payer, "
        "and it grows with the square of the move.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "swap": swap, "m": m, "dv01": dv01, "dv_after": dv_after, "dv_after_up": dv_after_up, "p_dn": p_dn, "p_up": p_up, "mid": mid, "est": est, "first": first})
