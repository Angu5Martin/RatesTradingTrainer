"""Random but realistic EUR market states, and display helpers for question stems."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from ..engine.dates import TARGET, add_months
from ..engine.marketdata import IBOR_PILLARS, OIS_PILLARS, MarketCurves

_KNOTS = (12, 24, 60, 120, 360)            # months at which the OIS shape is drawn
_FIRST, _LAST = date(2026, 1, 5), date(2027, 12, 20)


def _interp(knots: dict[int, float], m: int) -> float:
    ks = sorted(knots)
    if m <= ks[0]:
        return knots[ks[0]]
    for a, b in zip(ks, ks[1:]):
        if a <= m <= b:
            return knots[a] + (knots[b] - knots[a]) * (m - a) / (b - a)
    return knots[ks[-1]]


def random_trade_date(rng: random.Random) -> date:
    d = _FIRST + timedelta(days=rng.randrange((_LAST - _FIRST).days))
    return TARGET.adjust(d)


def random_market(rng: random.Random, trade_date: date | None = None) -> MarketCurves:
    """A plausible EUR market: ESTR-OIS level 1.6-3.2%, mostly upward sloping, occasional inversion;
    6M-Euribor swaps over OIS by 3-20bp (wider at the front); 3s6s basis 2-8bp; monotone front end between 6M and
    2Y. Quotes rounded to 0.1bp."""
    o2 = rng.uniform(0.016, 0.032)
    o6 = o2 - rng.uniform(-0.0030, 0.0035)               # policy path: 6M above 2Y = cuts priced, below = hikes
    o1 = o6 + (o2 - o6) * rng.uniform(0.4, 0.6)          # 1Y sits between them: a smooth, monotone front end
    o5 = o2 + rng.uniform(-0.0015, 0.0045)
    o10 = o5 + rng.uniform(-0.0005, 0.0045)
    o30 = o10 + rng.uniform(-0.0030, 0.0030)
    shape = dict(zip(_KNOTS, (o1, o2, o5, o10, o30)))
    ois = {m: round(_interp(shape, m), 5) for m in OIS_PILLARS if m >= 12}
    ois[6] = round(o6, 5)
    ois[3] = round(o6 - 0.5 * (o1 - o6), 5)               # extend the front-end trend back to 3M
    ois = {m: ois[m] for m in OIS_PILLARS}

    s_front, s_back = rng.uniform(0.0008, 0.0020), rng.uniform(0.0003, 0.0012)
    base = {m: _interp({6: ois[6], **{k: ois[k] for k in OIS_PILLARS if k >= 12}}, m) for m in IBOR_PILLARS}
    e6m = {}
    for m in IBOR_PILLARS:
        w = min(1.0, math.log(max(m, 6) / 6) / math.log(120 / 6))       # 0 at 6M ... 1 at 10Y+
        e6m[m] = round(base[m] + s_front * (1 - w) + s_back * w, 5)
    b0 = rng.uniform(0.0002, 0.0008)
    basis = {m: round(b0 * (1.0 + 0.15 * math.log(max(m, 6) / 6) / math.log(60)), 5) for m in IBOR_PILLARS}
    return MarketCurves(trade_date or random_trade_date(rng), {"OIS": ois, "E6M": e6m, "BASIS_3S6S": basis})


def pct(rate: float, dp: int = 3) -> str:
    return f"{rate * 100:.{dp}f}%"


def curve_line(mkt: MarketCurves, tenors=(2, 5, 10, 30), curve: str = "E6M") -> str:
    """e.g. '2Y 2.210% | 5Y 2.520% | 10Y 2.845%' from the quoted pillars."""
    return " | ".join(f"{int(t)}Y {pct(mkt.quotes[curve][round(t * 12)])}" for t in tenors)


def eur_m(x: float) -> str:
    return f"€{x / 1e6:,.0f}m"


# Illustrative issuer styles: (label, ASW range in decimal). Core govvies trade rich to swaps (ASW around zero or
# negative), peripheral ones cheap. The ranges are for variety, not a claim about any specific market level.
ISSUER_STYLES = (("core", -0.0020, 0.0015), ("semi-core", 0.0010, 0.0060), ("periphery", 0.0060, 0.0140))
BOND_YEARS = (3, 5, 7, 10, 15, 20, 30)


def random_bond(rng: random.Random, mkt: MarketCurves, notional: float, funding_spread: float = 0.0,
                max_abs_asw: float = 0.0200, price_range: tuple[float, float] = (80.0, 125.0)):
    """A government bond valued on a coupon date: coupon near the swap par yield, ASW from an issuer style.

    The printed price is rounded to 0.01 and the bond's ASW is RECOMPUTED from that printed price, so price, yield and ASW
    shown to the student are mutually consistent. Draws are repeated until |ASW| <= max_abs_asw and the price lies in
    price_range (the ASW and DV01 rules of thumb only hold near par). Returns (bond, issuer_label).
    """
    from ..engine.instruments import FixedBond
    for _ in range(200):
        years = rng.choice(BOND_YEARS)
        label, lo, hi = rng.choice(ISSUER_STYLES)
        par = mkt.bond_basis_swap_rate(years)
        coupon = max(0.0, round((par + rng.uniform(-0.006, 0.006)) / 0.0025) * 0.0025)
        probe = FixedBond.new(notional, coupon, mkt.spot, years, asw=rng.uniform(lo, hi), funding_spread=funding_spread)
        price = round(probe.price(mkt), 2)
        bond = probe.with_asw(probe.asw_from_price(mkt, price))
        if abs(bond.asw) <= max_abs_asw and price_range[0] <= price <= price_range[1]:
            return bond, label
    raise RuntimeError("could not draw a bond within the requested ASW and price limits")


# --------------------------------------------------------------------------------------------- bond futures baskets

def bond_label(bond) -> str:
    """'2.50% Jun-35': how a desk names a bond."""
    return f"{bond.coupon * 100:.2f}% {bond.maturity:%b-%y}"


@dataclass
class FuturesCase:
    """A bond-futures market state as a student sees it: a basket with printed clean prices and repo rates and a printed futures price.

    `lines` is the basis screen computed ONLY from those printed numbers (what the question grades). `fut` is the curve-consistent
    model calibrated to the same prices (what DV01, hedging and scenario answers use); at the base market the two agree on prices."""

    spec: object
    mkt: MarketCurves
    fut: object                 # engine.futures.BondFuture
    delivery: date
    days: int
    price: float                # printed futures price
    cleans: list[float]
    repos: list[float]
    lines: list                 # list[engine.futures.BasisLine], printed-quote analytics

    @property
    def labels(self) -> list[str]:
        return [bond_label(b) for b in self.fut.basket]

    def ctd_index(self) -> int:
        from ..engine.futures import ctd_line
        return self.lines.index(ctd_line(self.lines))

    def gross_basis_misleads(self) -> bool:
        """True if the bond with the lowest GROSS basis is not the CTD (carry changes the answer)."""
        return min(range(len(self.lines)), key=lambda k: self.lines[k].gross_basis) != self.ctd_index()

    def gap(self) -> float:
        """Net-basis gap (price points per 100 face) between the CTD and the runner-up."""
        nb = sorted(l.net_basis for l in self.lines)
        return nb[1] - nb[0]


def random_futures(rng: random.Random, mkt: MarketCurves, spec=None, n: int | None = None,
                   repo_gap: tuple[float, float] = (0.0020, 0.0060), special: bool = False, contest: bool = False,
                   wide_coupons: bool = False, trap: bool | None = None, min_gap: float = 0.03,
                   max_gap: float | None = None) -> FuturesCase:
    """A plausible deliverable basket: coupons clustered around the current coupon, a few bp of ASW noise, GC repo near ESTR.

    With the curve well below the 6% notional coupon the SHORTEST-duration bond is the natural CTD; `contest` makes one longer bond
    cheap to swaps by 4-9bp and `special` puts one bond on special repo, both of which can steal the crown (the interesting cases).
    Prices are printed to 0.01 and each bond's ASW is recomputed from its printed price; the futures price is printed to 0.01 and the
    model's price offset recomputed from it. The future is set so that the CTD's implied repo sits `repo_gap` BELOW its repo (decimal; this
    is the delivery-option premium, normal and positive); a negative gap puts the future RICH to the CTD (implied repo above repo).
    Redrawn until the CTD leads the runner-up by at least min_gap."""
    from ..engine.futures import BOBL, BUND, SCHATZ, basis_line, calibrated, clean_price, next_delivery, term_repo
    from ..engine.instruments import FixedBond
    for _ in range(500):
        sp = spec or rng.choices([BUND, BOBL, SCHATZ], [5, 3.5, 1.5])[0]
        delivery = next_delivery(mkt.anchor, min_days=rng.randint(25, 40))
        n_bonds = n or {"FGBL": 5, "FGBM": 4, "FGBS": 3}[sp.code]
        offs = sorted(rng.sample(range(sp.min_months + 1, sp.max_months), n_bonds))
        years = round((sp.min_months + sp.max_months) / 24)
        par = mkt.bond_basis_swap_rate(years)
        lo, hi = (-0.0075, 0.0030) if sp.code != "FGBS" else (-0.005, 0.0025)
        if wide_coupons:
            lo, hi = 1.6 * lo, 1.3 * hi
        base_asw = rng.uniform(-0.0015, 0.0012)
        gc = rng.choice([0.0, -0.0005, -0.0010])
        special_idx = rng.randrange(n_bonds) if special else None
        cheap_idx = rng.randrange(1, n_bonds) if contest else None
        bonds, cleans = [], []
        for i, off in enumerate(offs):
            d0 = add_months(delivery, off)
            mat = date(d0.year, d0.month, rng.choice([4, 15]))
            coupon = max(0.0, round((par + rng.uniform(lo, hi)) / 0.0025) * 0.0025)
            fs = gc - (rng.choice([0.0020, 0.0030, 0.0040]) if i == special_idx else 0.0)
            asw = base_asw + rng.gauss(0, 0.0004) + (rng.uniform(0.0004, 0.0009) if i == cheap_idx else 0.0)
            probe = FixedBond.from_maturity(100.0, coupon, mat, mkt.anchor, asw=asw, funding_spread=fs)
            clean = round(clean_price(probe, mkt), 2)
            bonds.append(probe.with_asw(probe.asw_from_price(mkt, clean + probe.accrued(mkt.anchor))))
            cleans.append(clean)
        fut0 = calibrated(sp, delivery, bonds, mkt, 0.0)
        fair = fut0.fair_price(mkt)
        at_fair = fut0.lines(mkt, futures_price=fair)[fut0.ctd_index(mkt)]
        # net basis that opens the implied repo `gap` below the repo: gap x (dirty x days - coupon x coupon_days) / 360, as a futures price
        net_target = rng.uniform(*repo_gap) * (at_fair.dirty * at_fair.days - at_fair.coupon_paid * at_fair.coupon_days) / 360.0
        price = round(fair - net_target / at_fair.cf, 2)
        fut = calibrated(sp, delivery, bonds, mkt, price)
        repos = [round(term_repo(b, mkt, delivery), 5) for b in bonds]
        lines = [basis_line(b, c, r, mkt.anchor, delivery, price, sp.notional_coupon) for b, c, r in zip(bonds, cleans, repos)]
        case = FuturesCase(sp, mkt, fut, delivery, (delivery - mkt.anchor).days, price, cleans, repos, lines)
        if trap is not None and case.gross_basis_misleads() != trap:
            continue
        if case.gap() >= min_gap and (max_gap is None or case.gap() <= max_gap):
            return case
    raise RuntimeError("could not draw a futures basket with a clear cheapest-to-deliver")
