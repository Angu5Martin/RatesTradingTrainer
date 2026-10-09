"""Short-term-interest-rate (STIR) futures: 3M Euribor futures and strips.

CONTRACT (stylised ICE 3M Euribor future)
  * Reference rate: the 3M Euribor fixing for the period from the IMM date (third Wednesday of Mar/Jun/Sep/Dec) to the next IMM date,
    ACT/360. Price = 100 - 100 x futures rate. Notional EUR 1m; EUR 25 per bp (EUR 2,500 per price point); a tick of 0.005 is EUR 12.50.
  * The contract is cash-settled and MARGINED daily. LONG the future gains when rates FALL (the price rises): it is a long-duration
    position, like receiving fixed in a FRA, and its DV01 is positive.
  * The futures rate is the forward rate from the 3M curve PLUS a convexity adjustment: daily margining means a long future gains cash
    when rates fall (and reinvests it cheaply) and pays cash when rates rise (and funds it dearly), which makes it worth LESS than a
    FRA to the long, so its price is lower and its rate HIGHER than the forward. The adjustment grows with the square of the time to
    the contract (Ho-Lee: 1/2 sigma^2 T1 T2, sigma the normal vol). It is a stylised input here, small for the first years.

The contract's EUR 25/bp is fixed, but a real 3M period is 90-92 days, so a FRA on EUR 1m has a DV01 of EUR 25.0-25.6: a strip is slightly
different from the FRAs and the swap it hedges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .instruments import Market

NOTIONAL = 1_000_000.0
POINT_VALUE = 2_500.0         # EUR per 1.00 of price = 100bp x EUR 25
BP_VALUE = 25.0


def third_wednesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(2 - first.weekday()) % 7 + 14)


def imm_dates_after(anchor: date, n: int) -> list[date]:
    """The first n quarterly IMM dates strictly after `anchor`, plus one more (the end of the last reference period)."""
    out: list[date] = []
    y, m = anchor.year, 3
    while len(out) < n + 1:
        d = third_wednesday(y, m)
        if d > anchor:
            out.append(d)
        m += 3
        if m > 12:
            y, m = y + 1, 3
    return out


def convexity_adjustment(years_to_start: float, years_to_end: float, sigma: float = 0.0070) -> float:
    """Ho-Lee futures-minus-forward rate (decimal): 1/2 sigma^2 T1 T2."""
    return 0.5 * sigma ** 2 * years_to_start * years_to_end


@dataclass(frozen=True)
class STIRFuture:
    contracts: float            # signed: + long (long duration)
    start: date
    end: date
    convexity: float = 0.0      # futures rate minus forward rate, decimal; held fixed when the curve moves
    index: str = "E3M"

    def forward(self, m: Market) -> float:
        return m.projection(self.index).forward_rate(self.start, self.end)

    def rate(self, m: Market) -> float:
        return self.forward(m) + self.convexity

    def price(self, m: Market) -> float:
        return 100.0 - 100.0 * self.rate(m)

    def pv(self, m: Market) -> float:
        """Notional value: contracts x EUR 2,500 x price. Only differences mean anything (variation margin)."""
        return self.contracts * POINT_VALUE * self.price(m)


def strip(anchor: date, n: int, contracts_each: float = 1.0, sigma: float = 0.0070) -> list[STIRFuture]:
    """The first n quarterly contracts after `anchor`, each with its Ho-Lee convexity adjustment."""
    imm = imm_dates_after(anchor, n)
    out = []
    for a, b in zip(imm, imm[1:]):
        t1, t2 = (a - anchor).days / 365.0, (b - anchor).days / 365.0
        out.append(STIRFuture(contracts_each, a, b, convexity_adjustment(t1, t2, sigma)))
    return out
