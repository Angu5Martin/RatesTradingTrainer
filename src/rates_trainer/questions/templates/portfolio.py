"""Portfolio templates: a book as a set of risk factors (bucket DV01, curve shape, swap-OIS spread), scenario P&L, and realised versus unrealised P&L.

The book's risk comes from the engine's key-rate DV01s (bump one par quote, re-bootstrap, reprice), collapsed to four reporting buckets (2Y, 5Y, 10Y,
30Y) and split by curve (the 6M Euribor swap curve and the ESTR OIS curve). Scenario P&L is full revaluation; the trainee's route is the first-order
sum of bucket DV01 x move, which is exactly what a risk report is for.
"""

from __future__ import annotations

import random

from ...engine.curve import CurveShock
from ...engine.instruments import Side
from ...engine.pnl import key_rate_first_order_pnl, revalue_pnl
from ...engine.risk import Portfolio, key_rate_dv01, par_irs, par_ois, unit_dv01
from ..market import eur_m, pct, random_market
from ..model import NumericPart, QuestionBody, Tolerance, fmt_eur, shuffled_choice
from ..registry import template
from .risk_book import BUCKETS, bucketed, kfmt

# (kind, start years, tenor years) -> a human label; the forward-starts have their risk in two buckets
_MENU = (("IRS", 0, 2), ("IRS", 0, 5), ("IRS", 0, 10), ("IRS", 0, 30), ("IRS", 2, 3), ("IRS", 5, 5), ("IRS", 10, 20), ("OIS", 0, 5), ("OIS", 0, 10))


def _label(kind: str, start: int, tenor: int) -> str:
    base = f"{start}y{tenor}y forward-starting IRS" if start else f"{tenor}Y {'IRS' if kind == 'IRS' else 'ESTR OIS'}"
    return base


def _draw_trade(rng: random.Random, mkt, kinds=("IRS", "OIS")):
    kind, start, tenor = rng.choice([m for m in _MENU if m[0] in kinds])
    side = rng.choice(list(Side))
    size = rng.choice([50, 75, 100, 150, 200, 250]) * 1e6
    make = par_irs if kind == "IRS" else par_ois
    return (kind, start, tenor, side, size, make(side, size, tenor, mkt, start_years=float(start)))


def _book(rng: random.Random, mkt, n: int, kinds=("IRS", "OIS")):
    trades = []
    seen = set()
    while len(trades) < n:
        t = _draw_trade(rng, mkt, kinds)
        key = (t[0], t[1], t[2])
        if key in seen:
            continue
        seen.add(key)
        trades.append(t)
    return trades


def _desc(t) -> str:
    kind, start, tenor, side, size, _ = t
    return f"{'Receive' if side is Side.RECEIVE else 'Pay'} fixed on {eur_m(size)} {_label(kind, start, tenor)}"


# ------------------------------------------------------------------------------------------------------------------ aggregation

@template("portfolio.bucket_book", skill="portfolio.aggregation", difficulty=3, kind="calculation")
def bucket_book(rng: random.Random) -> QuestionBody:
    """Add the per-trade bucket DV01s into the book's exposure, read the curve shape, and hedge the biggest bucket."""
    steep = CurveShock.points({2.0: -5.0, 5.0: -3.9, 10.0: -2.1, 30.0: 5.0})           # a 2s30s steepening of 10bp (the buckets move as shown)
    for _ in range(100):
        mkt = random_market(rng)
        trades = _book(rng, mkt, rng.choice([3, 4]), kinds=("IRS",))
        rows = []
        for t in trades:
            kr = key_rate_dv01(t[5], mkt, curves=("E6M",))
            rows.append(bucketed(kr)["E6M"])
        net = {b: sum(r[b] for r in rows) for b in BUCKETS}
        total = sum(net.values())
        gross = sum(abs(v) for v in net.values())
        book = Portfolio([t[5] for t in trades])
        kr_all = key_rate_dv01(book, mkt, curves=("E6M",))
        slope_pnl = key_rate_first_order_pnl(kr_all, steep, curves=("E6M",))
        slope_full = revalue_pnl(book, mkt, steep, curves=("E6M",))
        big = max(BUCKETS, key=lambda b: abs(net[b]))
        if gross > 100e3 and abs(slope_full) > 2.5 * max(0.05 * abs(slope_full), 0.03 * sum(abs(net[b]) * abs(steep.bp_at(b)) for b in BUCKETS)) and abs(net[big]) > 60e3 and abs(total) > 20e3:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a book")
    lines = []
    for t, r in zip(trades, rows):
        lines.append(f"  {_desc(t):<62} " + "  ".join(f"{b}Y {kfmt(r[b]):>8}" for b in BUCKETS))
    hedge = -net[big] / unit_dv01(big, mkt) * 1e6
    stem = (
        "Your book, with the risk system's bucketed DV01 for each trade (EUR per 1bp FALL in the 6M Euribor swap curve in that bucket; positive = long duration). "
        "A forward-starting swap has risk in two buckets.\n" + "\n".join(lines)
    )
    parts = [
        NumericPart(f"What is the book's net DV01 in the {big}Y bucket (EUR per bp)?", net[big], Tolerance(rel=0.02, abs=800), "EUR",
                    sign_hint="Add the column with signs.", note="sum the column"),
        NumericPart("What is the book's total DV01 to a parallel move (EUR per bp)?", total, Tolerance(rel=0.03, abs=1500), "EUR",
                    sign_hint="Add every bucket of every trade."),
        NumericPart("The curve steepens 2s30s by 10bp: the 2Y rate falls 5bp, the 5Y 3.9bp, the 10Y 2.1bp and the 30Y rises 5bp. What is the book's P&L (EUR)?",
                    slope_full, Tolerance(rel=0.05, abs=0.03 * sum(abs(net[b]) * abs(steep.bp_at(b)) for b in BUCKETS)), "EUR", approx=slope_pnl,
                    approx_label="-sum(net bucket DV01 x move)", sign_hint="Rates down in a bucket helps long duration there; rates up hurts it.",
                    note="net bucket DV01 x that bucket's move, summed, with the sign flipped"),
        NumericPart(f"You want the {big}Y bucket flat. What at-market {big}Y swap notional does that need? (+ = receive fixed, - = pay fixed)", hedge,
                    Tolerance(rel=0.04), "EUR", sign_hint="Hedge net long duration by paying fixed.", note="bucket DV01 / DV01 per EUR 1m"),
    ]
    solution = [
        "Net by bucket: " + ", ".join(f"{b}Y {fmt_eur(net[b])}" for b in BUCKETS) + f". Total = {fmt_eur(total)}.",
        "P&L = -[" + " + ".join(f"({kfmt(net[b])} x {steep.bp_at(b):+.1f})" for b in BUCKETS) + f"] = {fmt_eur(slope_pnl)} first order; revalued {fmt_eur(slope_full)}.",
        f"Flattening the {big}Y bucket: {fmt_eur(abs(net[big]), False)} / ({fmt_eur(unit_dv01(big, mkt), False)} per EUR 1m) = {eur_m(abs(hedge))}, {'receive' if hedge > 0 else 'pay'} fixed. "
        "That cleans one bucket; the other buckets (and any curve exposure between them) are untouched.",
        "A book is a vector of risk factors, not a single number: two books with the same total DV01 can be opposite curve trades.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "trades": trades, "net": net, "total": total, "big": big, "hedge": hedge, "slope_pnl": slope_pnl, "slope_full": slope_full})


# ------------------------------------------------------------------------------------------------------------------ scenarios

@template("portfolio.scenario_pnl", skill="portfolio.scenarios", difficulty=3, kind="calculation")
def scenario_pnl(rng: random.Random) -> QuestionBody:
    """P&L under three different factor scenarios from the same risk report: parallel, bear steepening, and a swap-vs-OIS spread move."""
    for _ in range(100):
        mkt = random_market(rng)
        trades = _book(rng, mkt, 4)
        if not any(t[0] == "OIS" for t in trades) or not any(t[0] == "IRS" for t in trades):
            continue
        book = Portfolio([t[5] for t in trades])
        kr = key_rate_dv01(book, mkt)
        bk = bucketed(kr)
        pa = rng.choice([15, 20, 25])
        sa = CurveShock.parallel(pa)
        sb = CurveShock.points({2.0: 0.0, 5.0: 5.0, 10.0: 12.0, 30.0: 18.0})
        spread = rng.choice([3, 4, 5])
        scen = [("A", f"All swap rates rise {pa}bp in parallel (6M Euribor swaps and ESTR OIS together)", sa, ("E6M", "OIS")),
                ("B", "Bear steepening of both curves: 2Y unchanged, 5Y +5bp, 10Y +12bp, 30Y +18bp (linear between)", sb, ("E6M", "OIS")),
                ("C", f"The Euribor swap rates rise {spread}bp relative to ESTR OIS (swap curve +{spread}bp in parallel, OIS unchanged)", CurveShock.parallel(spread), ("E6M",))]
        res = []
        for _, _, shock, curves in scen:
            full = revalue_pnl(book, mkt, shock, curves=curves)
            first = -sum(d * shock.bp_at(m / 12.0) for (name, m), d in kr.items() if name in curves)
            scale = sum(abs(d) * abs(shock.bp_at(m / 12.0)) for (name, m), d in kr.items() if name in curves)
            res.append((full, first, 0.03 * scale))
        if all(abs(f) > 2.5 * max(0.05 * abs(f), a) for f, _, a in res) and len({round(f / 1e4) for f, _, _ in res}) == 3:
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a scenario book")
    rows = "\n".join(f"  {b:>2}Y   {kfmt(bk['E6M'][b]):>9}   {kfmt(bk['OIS'][b]):>9}" for b in BUCKETS)
    tot_e, tot_o = sum(bk["E6M"].values()), sum(bk["OIS"].values())
    worst = min(range(3), key=lambda i: res[i][0])
    stem = (
        "Your book's key-rate DV01 by bucket (EUR per 1bp FALL in rates in that bucket; positive = long duration), split by curve:\n"
        f"  Bucket   Euribor swaps   ESTR OIS\n{rows}\n"
        f"  Total    {kfmt(tot_e):>9}   {kfmt(tot_o):>9}\n"
        "Three scenarios, each applied to the risk factors named:\n" + "\n".join(f"  {k}: {d}" for k, d, _, _ in scen)
    )
    parts = [
        NumericPart(f"Scenario {k}: what is the P&L (EUR)?", full, Tolerance(rel=0.05, abs=a), "EUR", approx=first,
                    approx_label="-sum(bucket DV01 x move)", sign_hint="Rates up: long-duration buckets lose.",
                    note={"A": "use both columns", "B": "use both columns, bucket by bucket",
                          "C": "only the Euribor swap column moves"}[k])
        for (k, _, _, _), (full, first, a) in zip(scen, res)
    ] + [
        shuffled_choice(rng, "Which scenario hurts the book most (or helps it least)?",
                        [f"Scenario {'ABC'[worst]}", *[f"Scenario {'ABC'[i]}" for i in range(3) if i != worst], "They are equal: the book is DV01-neutral"],
                        "Compare the three P&Ls: the same book is a different position in each risk factor, which is why a single DV01 number is not a risk limit."),
    ]
    solution = [
        "Scenario A: " + " + ".join(f"({kfmt(bk['E6M'][b])} + {kfmt(bk['OIS'][b])}) x {pa}" for b in BUCKETS) + f" = -[...] = {fmt_eur(res[0][1])} (revalued {fmt_eur(res[0][0])}).",
        f"Scenario B: bucket moves 2Y 0, 5Y +5, 10Y +12, 30Y +18: first-order {fmt_eur(res[1][1])}, revalued {fmt_eur(res[1][0])}.",
        f"Scenario C: only the Euribor column ({kfmt(tot_e)} in total) moves, by {spread}bp: {fmt_eur(res[2][1])}, revalued {fmt_eur(res[2][0])}. "
        "The ESTR OIS positions do not respond to a swap-vs-OIS move.",
        "One book, three factors: outright level, curve shape and the swap-OIS spread are independent exposures, and each needs its own hedge.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "trades": trades, "bk": bk, "res": res, "worst": worst, "spread": spread, "pa": pa})


# ------------------------------------------------------------------------------------------------------------------ realised / unrealised

@template("pnl.realised_unrealised", skill="pnl.attribution", difficulty=2, kind="calculation")
def realised_unrealised(rng: random.Random) -> QuestionBody:
    """A trading day in one swap: lots opened, part closed (FIFO), the rest marked. Where the money is realised and what is still at risk."""
    mkt = random_market(rng)
    tenor = rng.choice([5, 10, 30])
    pv01_100 = unit_dv01(tenor, mkt) * 100                                   # EUR per bp on EUR 100m, treated as constant through the day
    r1 = round(mkt.par_irs_rate(tenor * 12), 5)
    n1, n2 = rng.choice([100, 150, 200]) * 1e6, rng.choice([50, 100]) * 1e6
    for _ in range(100):
        r2 = round(r1 + rng.choice([-1, 1]) * rng.choice([2, 3, 4, 5]) * 1e-4, 5)
        r3 = round(r1 + rng.choice([-1, 1]) * rng.choice([3, 4, 6, 8]) * 1e-4, 5)
        r_end = round(r3 + rng.choice([-1, 1]) * rng.choice([1, 2, 3, 4]) * 1e-4, 5)
        n3 = rng.choice([0.4, 0.6, 0.8, 1.1, 1.3]) * n1
        n3 = round(n3 / 25e6) * 25e6
        if 0 < n3 < n1 + n2 and len({r1, r2, r3, r_end}) == 4:
            break
    lots = [[n1, r1], [n2, r2]]                                             # FIFO: oldest first
    remaining, realised = n3, 0.0
    for lot in lots:
        take = min(lot[0], remaining)
        realised += take / 1e8 * pv01_100 * (lot[1] - r3) * 1e4              # received lot[1], paid r3 to close
        lot[0] -= take
        remaining -= take
    open_n = sum(l[0] for l in lots)
    avg = sum(l[0] * l[1] for l in lots) / open_n
    unreal = sum(l[0] / 1e8 * pv01_100 * (l[1] - r_end) * 1e4 for l in lots)
    open_dv01 = open_n / 1e8 * pv01_100

    stem = (
        f"Today you trade the {tenor}Y EUR swap as a market maker. PV01 of EUR 100m is {fmt_eur(pv01_100, False)} per bp; treat it as constant through the day.\n"
        f"  Trade 1: client pays, so you RECEIVE fixed on {eur_m(n1)} at {pct(r1, 3)}\n"
        f"  Trade 2: you RECEIVE fixed on {eur_m(n2)} at {pct(r2, 3)}\n"
        f"  Trade 3: you PAY fixed on {eur_m(n3)} at {pct(r3, 3)} to reduce the position (matched against your oldest open lot first, FIFO)\n"
        f"The {tenor}Y swap rate closes the day at {pct(r_end, 3)}. Ignore bid/offer on the marks."
    )
    parts = [
        NumericPart("What is the REALISED P&L on the closed part (EUR)?", realised, Tolerance(rel=0.03, abs=1000), "EUR",
                    sign_hint="You received a fixed rate and paid another to close: compare the two rates.", note="closed notional x PV01 x (rate received - rate paid)"),
        NumericPart("What notional do you have open at the close (EUR, receive fixed)?", open_n, Tolerance(rel=0.001), "EUR"),
        NumericPart("What is the average fixed rate on the open position (%)?", avg * 100, Tolerance(rel=0, abs=0.0015), "%", note="notional-weighted, over the remaining lots"),
        NumericPart("What is the UNREALISED P&L on the open position at the closing mark (EUR)?", unreal, Tolerance(rel=0.03, abs=1000), "EUR",
                    sign_hint="Receiving above the closing rate is in the money.", note="open notional x PV01 x (average rate - closing rate)"),
        NumericPart("What is the DV01 of the open position (EUR per bp)? Tomorrow's P&L moves with this.", open_dv01, Tolerance(rel=0.03), "EUR",
                    sign_hint="Receive fixed = long duration (+)."),
    ]
    solution = [
        f"FIFO: the {eur_m(min(n3, n1))} closed first comes from trade 1 (received {pct(r1, 3)}, paid {pct(r3, 3)})"
        + (f", then {eur_m(n3 - n1)} from trade 2" if n3 > n1 else "") + f". Realised = {fmt_eur(realised)}.",
        f"Open: {eur_m(open_n)}, average rate {pct(avg, 4)}. Unrealised vs the {pct(r_end, 3)} close = {fmt_eur(unreal)}. Day P&L = {fmt_eur(realised + unreal)}.",
        f"Open DV01 = {eur_m(open_n)} / 100m x {fmt_eur(pv01_100, False)} = {fmt_eur(open_dv01)} per bp: the unrealised P&L is still exposed to the market, the realised is not.",
        "Realised P&L is locked in by the offsetting trade (it still arrives as cash over the life of the swaps, but no market move changes it). "
        "Average-cost accounting would give a different split between realised and unrealised although the total is the same: the total is what matters.",
    ]
    return QuestionBody(stem, parts, solution, {"mkt": mkt, "tenor": tenor, "lots": [(n1, r1), (n2, r2)], "r3": r3, "n3": n3, "r_end": r_end, "realised": realised,
                                                 "unreal": unreal, "open_n": open_n, "avg": avg, "open_dv01": open_dv01, "pv01_100": pv01_100})
