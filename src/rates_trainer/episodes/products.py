"""Markets with a spread overlay, and positions in products whose value depends on it (level 4).

The engine prices a bond off the OIS curve and ITS asset-swap spread, and a bond future off its basket. To move "swap spreads" and
"the futures basis" as market factors without touching the engine, the episode market carries an overlay:

    spreads["asw"]        common change in every bond's ASW (decimal; + = bonds cheapen against swaps)
    spreads["fut"]        common change in every future's price offset (price points; + = futures cheapen against their CTD)

`SpreadMarket` wraps an engine `MarketCurves` and behaves like it everywhere (any method returning a MarketCurves returns a
SpreadMarket with the same overlay), so engine risk and carry functions work on it unchanged. Positions re-bind themselves to the
overlay when priced (`materialise`). A plain MarketCurves is a market with a zero overlay.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from ..engine.futures import BondFuture
from ..engine.instruments import FixedBond
from ..engine.marketdata import MarketCurves


def spread_of(m, key: str) -> float:
    return getattr(m, "spreads", {}).get(key, 0.0)


class SpreadMarket:
    def __init__(self, curves: MarketCurves, spreads: Mapping[str, float] | None = None):
        if isinstance(curves, SpreadMarket):
            curves = curves.curves
        self.curves = curves
        self.spreads = dict(spreads or {})

    def __getattr__(self, name):
        attr = getattr(self.curves, name)
        if callable(attr):
            def wrapped(*args, **kwargs):
                out = attr(*args, **kwargs)
                return SpreadMarket(out, self.spreads) if isinstance(out, MarketCurves) else out
            return wrapped
        return attr

    def with_spread(self, key: str, delta: float) -> "SpreadMarket":
        s = dict(self.spreads)
        s[key] = s.get(key, 0.0) + delta
        return SpreadMarket(self.curves, s)


@dataclass(frozen=True)
class BondPosition:
    """EUR `face` (signed) of a bond; its ASW is the bond's own plus the market's common ASW change."""

    bond: FixedBond          # per-100 bond carrying its base ASW and funding spread
    face: float
    code: str = "CTD"

    def materialise(self, m) -> FixedBond:
        b = self.bond
        return FixedBond(self.face, b.coupon, b.periods, b.asw + spread_of(m, "asw"), b.funding_spread)

    def pv(self, m) -> float:
        return self.materialise(m).pv(m)


@dataclass(frozen=True)
class FuturePosition:
    """`contracts` (signed) of a bond future. The basket's ASWs move with the market's ASW change (so a swap-spread move moves the
    future through its CTD), and the price offset with the futures-basis change."""

    fut: BondFuture
    contracts: float
    code: str
    entry: float = 0.0       # the price it was traded at: a margined position is worth contracts x EUR 1,000 x (price - entry)

    def materialise(self, m) -> BondFuture:
        dasw = spread_of(m, "asw")
        basket = tuple(b.with_asw(b.asw + dasw) for b in self.fut.basket) if dasw else self.fut.basket
        return replace(self.fut, basket=basket, price_offset=self.fut.price_offset + spread_of(m, "fut"), contracts=self.contracts)

    def pv(self, m) -> float:
        fut = self.materialise(m)
        return fut.pv(m) - self.contracts * fut.spec.point_value * self.entry

    def price(self, m) -> float:
        return self.materialise(m).price(m)
