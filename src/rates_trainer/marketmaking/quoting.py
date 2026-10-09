"""Quote mechanics and a transparent, stylised skew model.

QUOTE CONVENTION (rate quotes, as the swap desk shows them)
    Bid   = the fixed rate at which the DEALER PAYS fixed  (the lower rate)
    Offer = the fixed rate at which the DEALER RECEIVES fixed (the higher rate)
    A client who "pays" trades at the offer  -> dealer RECEIVES fixed -> dealer is LONG duration.
    A client who "receives" trades at the bid -> dealer PAYS fixed    -> dealer is SHORT duration.

    Think of the swap rate as the price of "pay fixed": the dealer buys it at the bid and
    sells it at the offer. Being long duration means being SHORT that rate-price, so a long
    dealer wants to BUY it back: it quotes HIGHER (both sides up). That is the sign most
    people get backwards at first.

THE SKEW MODEL IS A TEACHING MODEL, NOT A PRICING MODEL
    It exists to make each driver's direction and rough size explicit and decomposable
    (inventory, expected flow, view, volatility, liquidity, adverse selection, limit
    pressure). Magnitudes are plausible for a liquid EUR 10Y swap (fractions of a bp)
    but there is no claim that they are optimal. Questions built on it should grade
    DIRECTION and RELATIVE size, with generous bands -- never a single "correct" number.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..engine.instruments import IRSwap, Side
from ..engine.marketdata import MarketCurves

BP = 1e-4


class ClientAction(Enum):
    PAYS = "pays"         # client pays fixed: trades at the offer, dealer receives fixed
    RECEIVES = "receives"  # client receives fixed: trades at the bid, dealer pays fixed

    @property
    def dealer_side(self) -> Side:
        return Side.RECEIVE if self is ClientAction.PAYS else Side.PAY

    @property
    def opposite(self) -> "ClientAction":
        return ClientAction.RECEIVES if self is ClientAction.PAYS else ClientAction.PAYS


@dataclass(frozen=True)
class Quote:
    bid: float    # rate at which dealer pays fixed
    offer: float  # rate at which dealer receives fixed

    def __post_init__(self) -> None:
        if self.offer < self.bid:
            raise ValueError("offer must be >= bid (crossed market)")

    @property
    def mid(self) -> float:
        return (self.bid + self.offer) / 2

    @property
    def width_bp(self) -> float:
        return (self.offer - self.bid) / BP

    def client_rate(self, action: ClientAction) -> float:
        """The rate the client gets: pays at the offer, receives at the bid."""
        return self.offer if action is ClientAction.PAYS else self.bid

    def dealer_swap(self, action: ClientAction, notional: float, mkt: MarketCurves, tenor_years: float,
                    start_years: float = 0.0) -> IRSwap:
        """The EUR IRS (vs 6M Euribor) the dealer is left holding after the client trades."""
        return IRSwap.new(action.dealer_side, notional, self.client_rate(action), mkt.spot,
                          round(tenor_years * 12), round(start_years * 12))


class Liquidity(Enum):
    DEEP = 0.8
    NORMAL = 1.0
    THIN = 1.5


@dataclass(frozen=True)
class QuotingContext:
    """The trader's current state. Inventory is in DV01 (EUR/bp), positive = long duration."""

    fair_value: float
    base_half_spread_bp: float = 0.2
    inventory_dv01: float = 0.0
    dv01_limit: float = 500_000.0
    vol_multiplier: float = 1.0           # 1.0 = normal, >1 elevated, <1 calm
    liquidity: Liquidity = Liquidity.NORMAL
    adverse_selection: float = 0.0        # 0 = benign flow ... 1 = very informed flow
    expected_flow_dv01: float = 0.0       # expected net client flow, in DV01 the dealer would acquire
    view_bp: float = 0.0                  # expected move in rates; + = rates expected to rise
    conviction: float = 0.0               # 0..1 weight on the view

    def __post_init__(self) -> None:
        if self.dv01_limit <= 0 or self.base_half_spread_bp <= 0:
            raise ValueError("limit and base half-spread must be positive")
        if not 0 <= self.conviction <= 1 or not 0 <= self.adverse_selection <= 1:
            raise ValueError("conviction and adverse_selection are in [0, 1]")

    @property
    def utilisation(self) -> float:
        """Signed inventory / limit. +1 = long duration at the limit."""
        return self.inventory_dv01 / self.dv01_limit


@dataclass(frozen=True)
class QuoteBreakdown:
    """The quote and the contribution of each driver, all in bp of rate."""

    quote: Quote
    fair_value: float
    inventory_skew_bp: float
    flow_skew_bp: float
    view_skew_bp: float
    bid_half_width_bp: float
    offer_half_width_bp: float
    core_half_spread_bp: float
    limit_widening_bp: float

    @property
    def net_shift_bp(self) -> float:
        """Shift of the centre of the market vs fair value. + = quoted higher in rate."""
        return self.inventory_skew_bp + self.flow_skew_bp + self.view_skew_bp

    @property
    def direction(self) -> str:
        """'higher' / 'lower' / 'neutral' relative to a symmetric market around fair value."""
        if abs(self.net_shift_bp) < 0.02:
            return "neutral"
        return "higher" if self.net_shift_bp > 0 else "lower"

    @property
    def encouraged_client_action(self) -> ClientAction | None:
        """Which client trade the skew makes more attractive (None if neutral).

        Quoted higher -> bid is better for a client who RECEIVES -> dealer pays fixed
        -> reduces a long-duration inventory.
        """
        d = self.direction
        if d == "neutral":
            return None
        return ClientAction.RECEIVES if d == "higher" else ClientAction.PAYS


def _skew_curve(util: float) -> float:
    """Inventory-skew shape in half-spreads: linear for small inventory, convex near the limit."""
    return 0.8 * util + 0.6 * util * abs(util)


FLOW_WEIGHT = 0.5      # expected flow counts as half-inventory when skewing
VIEW_WEIGHT = 0.05     # fraction of (conviction-weighted) expected move leaned into the mid
LIMIT_PRESSURE_START = 0.8
LIMIT_PRESSURE_SLOPE = 4.0  # extra half-spreads of width on the risk-adding side per unit util above start


def make_quote(ctx: QuotingContext) -> QuoteBreakdown:
    """Reference quote for a context. See module docstring for what this is and is not."""
    hs = ctx.base_half_spread_bp
    core = hs * ctx.vol_multiplier * ctx.liquidity.value * (1.0 + ctx.adverse_selection)

    # Skew scales with the cost of carrying risk, which rises with volatility.
    scale = hs * ctx.vol_multiplier
    u = ctx.utilisation
    u_flow = FLOW_WEIGHT * ctx.expected_flow_dv01 / ctx.dv01_limit
    inv_skew = scale * _skew_curve(u)
    flow_skew = scale * (_skew_curve(u + u_flow) - _skew_curve(u))
    view_skew = VIEW_WEIGHT * ctx.conviction * ctx.view_bp

    # Near the limit, widen the side that would ADD risk (long -> offer, short -> bid).
    pressure = max(0.0, abs(u + u_flow) - LIMIT_PRESSURE_START) * LIMIT_PRESSURE_SLOPE * hs
    bid_hw, offer_hw = core, core
    if u + u_flow > 0:
        offer_hw += pressure
    elif u + u_flow < 0:
        bid_hw += pressure

    shift = inv_skew + flow_skew + view_skew
    quote = Quote(
        bid=ctx.fair_value + (shift - bid_hw) * BP,
        offer=ctx.fair_value + (shift + offer_hw) * BP,
    )
    return QuoteBreakdown(
        quote=quote,
        fair_value=ctx.fair_value,
        inventory_skew_bp=inv_skew,
        flow_skew_bp=flow_skew,
        view_skew_bp=view_skew,
        bid_half_width_bp=bid_hw,
        offer_half_width_bp=offer_hw,
        core_half_spread_bp=core,
        limit_widening_bp=pressure,
    )
