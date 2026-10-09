"""Episode state: regime, client inquiries, positions, the P&L ledger and the decision types.

State that changes through an episode (market, positions, ledger) is held in immutable records; the Episode runner (episode.py) moves
from one to the next. Nothing here prices anything: the engine does.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..engine.instruments import Side
from ..engine.risk import Portfolio
from ..marketmaking.flow import CLIENT_TYPES
from ..marketmaking.quoting import ClientAction, Liquidity, Quote

# Client-market half-spreads by tenor (bp) on a normal day, and the hedge tenors offered next to each focus tenor.
BASE_HALF_SPREAD_BP = {2: 0.10, 5: 0.15, 10: 0.20, 30: 0.40}
NEIGHBOURS = {2: (5,), 5: (2, 10), 10: (5, 30), 30: (10,)}
INFORMED_DRIFT_BP = 1.5        # an informed client's trade predicts a level move of this size (x regime vol) in its favour


@dataclass(frozen=True)
class ExpectedFlow:
    """What the desk expects clients to do later (information for the trainee, and the assessment's working assumption)."""

    action: ClientAction
    notional: float
    probability: float
    text: str


@dataclass(frozen=True)
class Regime:
    vol: float                                  # 0.6 calm / 1.0 normal / 1.8 stressed
    liquidity: Liquidity
    client_mix: tuple[tuple[str, float], ...]   # (client type, weight)
    p_pays: float                               # probability an inquiring client wants to PAY fixed
    dt: float                                   # length of one market step, in days
    flow_text: str                              # how the flow looks to the desk
    typical_notional: float                     # average inquiry size (EUR), for expected-value calculations
    expected_flow: ExpectedFlow | None = None
    swap_cost_mult: float = 1.0                 # session effect on the cost of hedging in swaps NOW (late day > 1); exits later are at normal cost
    swap_depth_dv01: float | None = None        # late-session depth: a swap hedge of |DV01| d costs (1 + d / depth) x the spread (impact)

    @property
    def informed_share(self) -> float:
        w = sum(x for _, x in self.client_mix)
        return sum(CLIENT_TYPES[t].p_informed * x for t, x in self.client_mix) / w

    def facts(self) -> dict:
        """The conditions as plain data (labels, not sentences): what the screen reports about the market."""
        vol = {0.6: "calm", 1.0: "normal", 1.8: "stressed (data-heavy, jumpy)"}.get(self.vol, f"x{self.vol:g}")
        liq = {Liquidity.DEEP: "deep (easy to hedge in size)", Liquidity.NORMAL: "normal",
               Liquidity.THIN: "thin (hedging in size costs more)"}[self.liquidity]
        return {"volatility": vol, "liquidity": liq, "flow": self.flow_text,
                "swap_cost": ({"multiplier": self.swap_cost_mult, "depth_dv01": self.swap_depth_dv01} if self.swap_cost_mult > 1 else None),
                "desk_expectation": self.expected_flow.text if self.expected_flow else None}

    def describe(self) -> list[str]:
        from .render import conditions_lines
        return conditions_lines({**self.facts(), "research": None, "named_clients": [], "calendar": None, "extra_lines": []})


@dataclass(frozen=True)
class Inquiry:
    """A client, drawn from the arrivals stream before the episode starts: independent of every decision."""

    ctype: str
    action: ClientAction
    notional: float
    informed: bool          # never shown to the trainee before the debrief
    tenor: int | None = None    # None: the episode's focus tenor (levels 1-2)
    name: str | None = None     # a persistent named client (level 5)


@dataclass(frozen=True)
class Position:
    inst: object            # anything with pv(market): IRSwap, or a BondPosition / FuturePosition (products.py)
    origin: str             # "initial" | "client" | "hedge"
    label: str
    round: int


def book(positions: tuple[Position, ...]) -> Portfolio:
    return Portfolio([p.inst for p in positions])


@dataclass(frozen=True)
class LedgerEntry:
    round: int
    cause: str              # "edge" | "hedge cost" | "market: level" | ... | "convexity/cross"
    amount: float


# ------------------------------------------------------------------------------------------------- decisions

@dataclass(frozen=True)
class QuoteDecision:
    bid: float              # rates, decimal
    offer: float

    def __post_init__(self) -> None:
        if not self.offer > self.bid:
            raise ValueError("the offer must be above the bid")

    @property
    def quote(self) -> Quote:
        return Quote(self.bid, self.offer)


@dataclass(frozen=True)
class RFQDecision:
    level: float | None     # the rate you show for the client's side; None = pass


@dataclass(frozen=True)
class HedgeTrade:
    tenor: int
    side: Side              # the side YOU take in the interdealer market
    notional: float


@dataclass(frozen=True)
class FuturesTrade:
    code: str               # "FGBL" | "FGBM"
    contracts: float        # signed: + buy


@dataclass(frozen=True)
class BondTrade:
    code: str               # the bond on the menu ("CTD")
    face: float             # signed EUR face: + buy


@dataclass(frozen=True)
class HedgeDecision:
    trades: tuple = ()      # HedgeTrade (swaps), FuturesTrade, BondTrade
    label: str = ""


# ------------------------------------------------------------------------------------------------- the desk and the plan

@dataclass(frozen=True)
class Limits:
    dv01: float
    slope: float | None = None          # |slope exposure| limit, EUR per bp of the slope factor (level 3+)


@dataclass(frozen=True)
class Product:
    """A hedge instrument other than a swap (level 4): one futures contract or EUR 1m face of a bond, priced by products.py."""

    code: str
    kind: str               # "future" | "bond"
    label: str
    obj: object             # BondFuture (contracts=1) or a per-100 FixedBond
    half_spread: float      # price points crossed per side (per 100 face for a bond; futures price points for a future)
    info: str = ""          # what the screen shows about it


@dataclass(frozen=True)
class Desk:
    hedge_tenors: tuple[int, ...]       # swap tenors you can hedge in
    limits: Limits
    products: tuple[Product, ...] = ()
    factors: tuple[str, ...] = ("level", "slope", "curvature")
    multi_tenor: bool = False           # level 3+: clients ask in several tenors; price off the risk-equivalent inventory

    def product(self, code: str) -> Product:
        for p in self.products:
            if p.code == code:
                return p
        raise KeyError(f"no product {code!r} on this desk")


@dataclass(frozen=True)
class RoundPlan:
    """One round: an optional pricing decision, one risk decision, then a market move."""

    pricing: str | None = "rfq"         # "quote" | "rfq" | None
    decision: str = "hedge"             # "hedge" | "position" | "overnight" | "rehedge"
    move: str = "intraday"              # "intraday" | "overnight" | "event"
    title: str = ""
    notes: tuple[str, ...] = ()         # announcements at the start of the round (a limit cut, a session change)
    regime: Regime | None = None        # conditions from this round on
    limits: Limits | None = None        # limits from this round on
    checkpoint: str | None = None       # "dv01_after_fill" | "slope_if_dealt" | "futures_contracts"
    vol_mult: float = 1.0               # the move's vol multiplier (an event)


@dataclass(frozen=True)
class Signal:
    """A research view (level 5): direction and size over the session, with an honest stated reliability."""

    view_bp: float                      # + = rates expected to rise
    reliability: float                  # probability that the call carries information
    text: str


@dataclass(frozen=True)
class NamedClient:
    name: str
    ctype: str
    informed: bool                      # latent for the whole session; revealed only in the debrief


@dataclass(frozen=True)
class CheckpointAnswer:
    raw: str


class Rating(Enum):
    SOUND = "sound"
    DEFENSIBLE = "defensible"
    POOR = "poor"
    ERROR = "error"

    @property
    def rank(self) -> int:
        return {"sound": 0, "defensible": 1, "poor": 2, "error": 3}[self.value]


def worst(*ratings: Rating) -> Rating:
    return max(ratings, key=lambda r: r.rank)
