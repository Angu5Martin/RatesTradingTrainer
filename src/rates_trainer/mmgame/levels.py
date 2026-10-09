"""The three difficulty levels. Difficulty comes from how many markets run at once, which bots are in them, how often and how hard the shocks hit and how tight the
limits are: never from a clock. The game is turn-based; nothing happens until the player advances the round."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    n: int
    name: str
    blurb: str
    markets: tuple[int, int, int]               # min, default, max simultaneous markets
    rounds: int
    shocks: tuple[int, int]                     # min, max shocks over a whole game
    shock_categories: tuple[str, ...]
    min_shift: float                            # a major shock moves the fair value by at least this many standard deviations
    bots: tuple[str, ...]
    limit: int                                  # position limit per market, in lots
    size_max: int                               # most lots that can be quoted on a side
    risk_budget: int | None                     # cap on total 1σ risk across all markets (credits), None = no cap
    later_markets: int                          # how many markets open after the start
    linked: int                                 # pairs of markets that settle off the same dice
    world_max_difficulty: int
    world_share: float                          # share of world-knowledge markets when the mix is 'mixed'
    coach: bool                                 # show the edge of every trade as it happens (gentle feedback)
    types: str                                  # what the player sees of a counterparty: full | coarse | none


LEVELS: dict[int, Level] = {
    1: Level(1, "Beginner", "Few, simple markets. Gentle bots, no sharks. A shock now and then tells you something new; the coach shows how each trade went.",
             (2, 3, 4), 8, (0, 1), ("information", "experiment"), 0.0, ("retail", "retail", "value", "anchor"), 6, 3, None, 0, 0, 1, 0.34, True, "full"),
    2: Level(2, "Intermediate", "More markets, markets that open late, a fast trader who punishes stale quotes, and rule changes. Manage inventory across several tables.",
             (3, 5, 6), 12, (2, 4), ("information", "experiment", "resolution"), 0.35, ("retail", "retail", "value", "anchor", "sniper"), 5, 4, None, 2, 0, 2, 0.4, False, "coarse"),
    3: Level(3, "Advanced", "Many markets, linked ones that settle off the same dice, informed and strategic counterparties, major shocks and a firm-wide risk budget.",
             (4, 7, 8), 14, (5, 8), ("information", "experiment", "resolution"), 0.6, ("retail", "retail", "value", "anchor", "sniper", "insider", "insider"), 4, 4, 1100, 3, 1, 3, 0.4, False, "none"),
}

MIXES = ("mixed", "probability", "world")
