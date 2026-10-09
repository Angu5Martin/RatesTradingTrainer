"""Bond futures (the Euro-Bund family): conversion factors, the delivery basket, cheapest-to-deliver, basis, implied repo.

THE CHAIN this module makes executable (every link is a function, every function is tested against an independent route):

    bond --> conversion factor --> futures-equivalent price --> CTD --> futures price/DV01 --> implied repo --> basis --> trade

WHAT THE CONTRACT IS (stylised Eurex FGBL / FGBM / FGBS, the simplifications stated)
  * A notional bond of 6% coupon and EUR 100,000 face. Price is quoted per 100, so 1 point = EUR 1,000 and a tick (0.01) = EUR 10.
  * The short chooses WHICH bond to deliver from a basket (remaining life 8.5-10.5y for the Bund, 4.5-5.5y Bobl, 1.75-2.25y Schatz,
    measured at the delivery date) and WHEN within the delivery month. We model delivery on one date, the 10th of Mar/Jun/Sep/Dec
    (TARGET Following), and ignore the end-game and wildcard timing options. The quality (which-bond) option is the one that matters.
  * The invoice the long pays for a delivered bond, per 100 face:   F x CF + accrued interest at delivery.
  * The CONVERSION FACTOR CF is the price per unit face at which the bond yields exactly the 6% notional coupon on the delivery date,
    with the remaining life rounded DOWN to complete months and accrued removed (so a 6% coupon bond has CF near 1, and a low-coupon bond
    has CF well below 1). It exists to make bonds of different coupon and maturity roughly interchangeable. It cannot do so exactly, because
    it prices every bond off ONE flat 6% yield while markets sit at 2-3%. That error is the whole reason there is a CTD.

THE BASIS (all per 100 face of the bond, price points)
  gross basis    = clean price - F x CF                          the cost of owning the bond against being short the future
  carry          = coupon income to delivery (accrued, plus any coupon paid) - financing cost (dirty price x repo x days/360)
  net basis      = gross basis - carry = forward clean price - F x CF = CF x (F_i - F)
  F_i            = forward clean price / CF: the futures price at which delivering bond i is exactly break-even ("futures-equivalent price")
  implied repo   = the return from buying the bond, selling the future and delivering: the repo rate that makes the cash flows balance
  CTD            = the bond with the LOWEST F_i (= lowest net basis; = HIGHEST implied repo if all bonds finance at one repo). It sets the price:
                   fair F = min_i F_i, and the market trades below that by the value of the other delivery options (the net basis of the CTD).

Everything above takes only quoted prices, so it needs no curve (`basis_line`). `BondFuture` is the curve-consistent model: it prices every
deliverable from the OIS curve and its ASW, so it gives futures DV01, hedge ratios, CTD switches and scenario P&L.

Day counts: repo is simple ACT/360 from today to delivery; a coupon paid inside the window is reinvested at the same repo to delivery.
Bond coupon dates are unadjusted anniversaries of maturity (see FixedBond.from_maturity).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Sequence

from .curve import CurveShock
from .dates import TARGET, BDC, add_months
from .instruments import FixedBond, Market

NOTIONAL_COUPON = 0.06


@dataclass(frozen=True)
class FuturesSpec:
    name: str
    code: str
    min_months: int           # shortest deliverable remaining life at delivery, in months
    max_months: int
    notional: float = 100_000.0
    notional_coupon: float = NOTIONAL_COUPON

    @property
    def point_value(self) -> float:
        """EUR per 1.00 of price (per contract)."""
        return self.notional / 100.0

    @property
    def tick_value(self) -> float:
        return self.point_value * 0.01


BUND = FuturesSpec("Euro-Bund", "FGBL", 102, 126)       # 8.5 - 10.5 years
BOBL = FuturesSpec("Euro-Bobl", "FGBM", 54, 66)         # 4.5 - 5.5 years
SCHATZ = FuturesSpec("Euro-Schatz", "FGBS", 21, 27)     # 1.75 - 2.25 years
SPECS = {s.code: s for s in (BUND, BOBL, SCHATZ)}


# ----------------------------------------------------------------------------------------- dates and conversion factors

def delivery_date(year: int, month: int) -> date:
    """The 10th of the delivery month, moved to the next TARGET business day."""
    if month not in (3, 6, 9, 12):
        raise ValueError("delivery months are March, June, September, December")
    return TARGET.adjust(date(year, month, 10), BDC.FOLLOWING)


def next_delivery(anchor: date, min_days: int = 20) -> date:
    """The first quarterly delivery date at least `min_days` after `anchor`."""
    y = anchor.year
    for year in (y, y + 1):
        for month in (3, 6, 9, 12):
            d = delivery_date(year, month)
            if (d - anchor).days >= min_days:
                return d
    raise AssertionError("unreachable")


def remaining_months(delivery: date, maturity: date) -> int:
    """Complete months from delivery to maturity (rounded DOWN), the Eurex convention for the CF."""
    months = (maturity.year - delivery.year) * 12 + (maturity.month - delivery.month)
    return months - (1 if maturity.day < delivery.day else 0)


def is_deliverable(maturity: date, delivery: date, spec: FuturesSpec) -> bool:
    return add_months(delivery, spec.min_months) <= maturity <= add_months(delivery, spec.max_months)


def conversion_factor(coupon: float, maturity: date, delivery: date, notional_coupon: float = NOTIONAL_COUPON) -> float:
    """Price per unit face at the notional-coupon yield on the delivery date, minus accrued, rounded to 6 dp.

    m complete months remain; the next coupon is k = m mod 12 months away (12 if m is a whole number of years), the coupons are
    k, k+12, ... , m months out, and accrued is the (12-k)/12 of a coupon that has already built up (months, not days: exchange rule)."""
    m = remaining_months(delivery, maturity)
    if m < 1:
        raise ValueError("bond matures before delivery")
    k = m % 12 or 12
    v = 1.0 / (1.0 + notional_coupon)
    dirty = sum(coupon * v ** ((k + 12 * j) / 12.0) for j in range((m - k) // 12 + 1)) + v ** (m / 12.0)
    return round(dirty - coupon * (12 - k) / 12.0, 6)


# ----------------------------------------------------------------------------------------- basis analytics (quoted prices only)

@dataclass(frozen=True)
class BasisLine:
    """One deliverable bond's row on the basis screen. Prices are per 100 face; rates are decimals (ACT/360 simple repo)."""

    bond: FixedBond                 # a per-100 bond (notional 100)
    clean: float
    repo: float
    days: int                       # settlement (today) to delivery
    cf: float
    accrued0: float
    accrued_delivery: float
    coupon_paid: float              # coupon paid inside the window (0 if none)
    coupon_days: int                # days from that payment to delivery
    financing: float
    carry: float
    forward_clean: float            # clean - carry: the repo-implied forward clean price
    futures_price: float
    futures_equiv: float            # F_i = forward clean / CF
    gross_basis: float
    net_basis: float
    implied_repo: float

    @property
    def dirty(self) -> float:
        return self.clean + self.accrued0

    @property
    def invoice(self) -> float:
        """Cash received on delivery per 100 face: F x CF + accrued."""
        return self.futures_price * self.cf + self.accrued_delivery

    @property
    def net_basis_in_futures_points(self) -> float:
        """Net basis expressed as a futures price: F_i - F. Times EUR 1,000 = EUR per contract."""
        return self.futures_equiv - self.futures_price


def _forward_clean_and_carry(bond: FixedBond, clean: float, repo: float, anchor: date, delivery: date):
    days = (delivery - anchor).days
    if days <= 0:
        raise ValueError("delivery must be after the settlement date")
    a0, ad = bond.accrued(anchor), bond.accrued(delivery)
    paid = [p for p in bond.periods if anchor < p.pay <= delivery]
    c = 100.0 * bond.coupon if paid else 0.0
    cdays = (delivery - paid[0].pay).days if paid else 0
    dirty = clean + a0
    financing = dirty * repo * days / 360.0
    income = ad - a0 + c * (1.0 + repo * cdays / 360.0)
    return days, a0, ad, c, cdays, financing, income - financing


def forward_clean(bond: FixedBond, clean: float, repo: float, anchor: date, delivery: date) -> float:
    """Repo-implied forward clean price at delivery: buy today, finance at repo, receive coupon income."""
    *_, carry = _forward_clean_and_carry(bond, clean, repo, anchor, delivery)
    return clean - carry


def basis_line(bond: FixedBond, clean: float, repo: float, anchor: date, delivery: date, futures_price: float,
               notional_coupon: float = NOTIONAL_COUPON) -> BasisLine:
    """Gross basis, carry, net basis and implied repo for one deliverable bond from QUOTED prices. `bond` has notional 100."""
    days, a0, ad, c, cdays, financing, carry = _forward_clean_and_carry(bond, clean, repo, anchor, delivery)
    cf = conversion_factor(bond.coupon, bond.maturity, delivery, notional_coupon)
    fwd = clean - carry
    dirty = clean + a0
    invoice = futures_price * cf + ad
    # D0 (1 + r d/360) - c (1 + r d2/360) = invoice  is linear in r
    implied = (invoice - dirty + c) * 360.0 / (dirty * days - c * cdays)
    return BasisLine(bond, clean, repo, days, cf, a0, ad, c, cdays, financing, carry, fwd, futures_price, fwd / cf,
                     clean - futures_price * cf, fwd - futures_price * cf, implied)


def ctd_line(lines: Sequence[BasisLine]) -> BasisLine:
    """The cheapest to deliver: the LOWEST NET BASIS (= lowest futures-equivalent price F_i), with each bond financed at its own repo.

    When every bond finances at the same repo rate this is also the bond with the highest implied repo, which is how the screen
    is usually read. They differ only if repo differs by bond: a bond on special has cheaper financing, so a lower net basis, and
    is likelier to be the CTD even where its implied repo looks no higher."""
    return min(lines, key=lambda l: l.net_basis)


def ranked(lines: Sequence[BasisLine]) -> list[BasisLine]:
    """Best (CTD) first, by net basis."""
    return sorted(lines, key=lambda l: l.net_basis)


def ranked_by_implied_repo(lines: Sequence[BasisLine]) -> list[BasisLine]:
    return sorted(lines, key=lambda l: -l.implied_repo)


# ----------------------------------------------------------------------------------------- the curve-consistent contract

def term_repo(bond: FixedBond, m: Market, delivery: date) -> float:
    """Simple ACT/360 repo from the market's anchor to delivery: the forward ESTR path implied by the OIS curve plus the bond's funding spread."""
    days = (delivery - m.anchor).days
    growth = m.ois.df(m.anchor) / m.ois.df(delivery) - 1.0
    return growth * 360.0 / days + bond.funding_spread


def clean_price(bond: FixedBond, m: Market) -> float:
    """Clean price per 100 from the curve (bond has notional 100): swap-curve value less ASW x annuity, less accrued."""
    return bond.pv(m) - bond.accrued(m.anchor)


@dataclass(frozen=True)
class BondFuture:
    """A bond future priced from the curve: contracts (signed; + long) of a futures contract on a basket of per-100 bonds.

        F_i(market)  = forward clean price of bond i / CF_i      (bond price from the OIS curve and its ASW, financing at its repo)
        fair F       = min_i F_i                                  the CTD sets the price
        traded F     = fair F - price_offset                      the market trades below fair by the delivery-option value (>= 0 usually)

    price_offset is held FIXED when the curve moves: it is the premium for the switch options, and the net basis of the CTD is
    CF x price_offset. pv() is the notional value of the position (contracts x EUR 1,000 x F); only differences of pv mean anything,
    exactly like daily variation margin.
    """

    spec: FuturesSpec
    delivery: date
    basket: tuple[FixedBond, ...]         # per-100 bonds; funding_spread = repo minus ESTR
    price_offset: float = 0.0
    contracts: float = 1.0

    def __post_init__(self) -> None:
        if not self.basket:
            raise ValueError("empty basket")
        for b in self.basket:
            if not is_deliverable(b.maturity, self.delivery, self.spec):
                raise ValueError(f"bond maturing {b.maturity} is not deliverable into {self.spec.name} on {self.delivery}")

    def conversion_factors(self) -> list[float]:
        return [conversion_factor(b.coupon, b.maturity, self.delivery, self.spec.notional_coupon) for b in self.basket]

    def futures_equivalents(self, m: Market) -> list[float]:
        """F_i for each bond on this market."""
        return [forward_clean(b, clean_price(b, m), term_repo(b, m, self.delivery), m.anchor, self.delivery) / cf
                for b, cf in zip(self.basket, self.conversion_factors())]

    def ctd_index(self, m: Market) -> int:
        f = self.futures_equivalents(m)
        return min(range(len(f)), key=f.__getitem__)

    def ctd(self, m: Market) -> FixedBond:
        return self.basket[self.ctd_index(m)]

    def fair_price(self, m: Market) -> float:
        return min(self.futures_equivalents(m))

    def price(self, m: Market) -> float:
        return self.fair_price(m) - self.price_offset

    def pv(self, m: Market) -> float:
        return self.contracts * self.spec.point_value * self.price(m)

    def lines(self, m: Market, futures_price: float | None = None) -> list[BasisLine]:
        """The basis screen on this market, at the model's own traded price unless one is given."""
        f = self.price(m) if futures_price is None else futures_price
        return [basis_line(b, clean_price(b, m), term_repo(b, m, self.delivery), m.anchor, self.delivery, f, self.spec.notional_coupon)
                for b in self.basket]

    def with_contracts(self, n: float) -> "BondFuture":
        return replace(self, contracts=n)


def calibrated(spec: FuturesSpec, delivery: date, basket: Sequence[FixedBond], m: Market, traded_price: float,
               contracts: float = 1.0) -> BondFuture:
    """A BondFuture whose price on market `m` is exactly `traded_price` (the offset is solved, not assumed)."""
    fut = BondFuture(spec, delivery, tuple(basket), 0.0, contracts)
    return replace(fut, price_offset=fut.fair_price(m) - traded_price)


# ----------------------------------------------------------------------------------------- hedging and basis trades

def contracts_to_hedge(bond_face: float, cf: float, spec: FuturesSpec) -> float:
    """The CF-weighted hedge of a position in the CTD: contracts to SELL per long face (signed: positive face -> negative contracts).

    F moves about 1/CF of the bond's price per 100, so a face of N needs N x CF / notional contracts."""
    return -bond_face * cf / spec.notional


def delivery_scenario_prices(fut: BondFuture, m: Market, shock, curves=("OIS", "E6M")) -> tuple[list[float], float]:
    """Clean price of each deliverable AT DELIVERY if forwards are realised and then the curve moves by `shock`, and the futures
    price that results (the lowest F_i at delivery: no financing left, so F_i = clean / CF).

    The shock enters as a CHANGE in the bond's price on the delivery-date market, added to the repo-implied forward clean price,
    so the forward drift is exactly the financing arithmetic (no model mismatch when a coupon is paid inside the window)."""
    # The reference is the forward market REBUILT from its own par quotes, so that a zero shock is exactly zero: the rolled
    # curve and a re-bootstrap of its quotes differ slightly between pillars (interpolation), and that is not a market move.
    base = m.rolled(fut.delivery, "forward").shifted(CurveShock.parallel(0.0), curves)
    moved = base.shifted(shock, curves)
    out = []
    for b in fut.basket:
        fwd = forward_clean(b, clean_price(b, m), term_repo(b, m, fut.delivery), m.anchor, fut.delivery)
        out.append(fwd + (clean_price(b, moved) - clean_price(b, base)))
    final = min(p / cf for p, cf in zip(out, fut.conversion_factors()))
    return out, final


def long_basis_pnl_at_delivery(fut: BondFuture, m: Market, bond_index: int, shock, curves=("OIS", "E6M")) -> float:
    """P&L per 100 face of: buy bond i today, finance in repo, short CF_i futures-units (per 100), hold to delivery and deliver.

        P&L = -net basis_i + CF_i x (F_i' - min_j F_j')

    the option payoff (the amount by which bond i has stopped being the cheapest) minus the premium (the net basis you paid).
    Computed here by cash flows, not by that formula."""
    cf = fut.conversion_factors()[bond_index]
    prices, f_final = delivery_scenario_prices(fut, m, shock, curves)
    b = fut.basket[bond_index]
    fwd = forward_clean(b, clean_price(b, m), term_repo(b, m, fut.delivery), m.anchor, fut.delivery)
    f0 = fut.price(m)
    return (prices[bond_index] - fwd) + cf * (f0 - f_final)
