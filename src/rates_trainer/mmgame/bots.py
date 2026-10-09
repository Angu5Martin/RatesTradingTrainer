"""The bots: deterministic counterparties with different estimates, uncertainty, aggressiveness and information.

A bot sees the market's PUBLIC state (fair value and standard deviation given everything announced), my quote, and, for the informed kinds, the hidden truth. It decides whether
to look at a market this round, forms an estimate, and trades against my actual bid or offer if my price is worse than its estimate by more than its threshold. It never trades
at a price other than my quote. Its randomness (arrival, estimate noise) is a function of (seed, round, market, bot) only, so the same game replays identically; only its *decision*
depends on what I quoted.

    retail    trades often, small, with a noisy view around fair value; cares about the spread, not about being right. Uninformed flow: the way to earn the spread.
    value     a careful fund: a good estimate of the public fair value; trades when a quote is clearly off it. Punishes mispriced quotes.
    anchor    slow to update: its estimate is the public fair value from two rounds ago. After a shock it trades at the old price: stale, but not harmful to the player.
    sniper    fast money: reacts in the SAME round as a shock, before the player can re-quote, with a sharp estimate and size. Punishes stale quotes.
    insider   knows (nearly) the answer under the current rules. Strategic: trades only where the edge is large, bigger the larger the edge, and only up to a limited amount a
              round across all markets, spread over the best opportunities. Its absence is information too.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from .rng import Stream


@dataclass(frozen=True)
class Personality:
    key: str
    label: str                                  # what is shown at the levels that show counterparty types
    coarse: str
    activity: float                             # chance of looking at a market in normal flow
    noise: float                                # std of its estimate error, in public standard deviations
    thr: float                                  # edge required, in public standard deviations (negative = will pay up)
    max_size: int
    size_gain: float
    fast: bool = False                          # also reacts within the round a shock lands
    informed: bool = False                      # estimate is built around the truth
    lag: int = 0                                # rounds behind in its view of fair value
    capacity: int | None = None                 # lots per round across all markets
    fast_activity: float = 0.0


PERSONALITIES: dict[str, Personality] = {p.key: p for p in (
    Personality("retail", "Retail flow", "Retail", .75, .8, -.05, 1, 0.0),
    Personality("value", "Value fund", "Fund", .5, .25, .2, 2, 1.5),
    Personality("anchor", "Slow money", "Fund", .55, .3, .15, 2, 1.0, lag=2),
    Personality("sniper", "Fast money", "Prop", .2, .08, .25, 4, 3.0, fast=True, fast_activity=1.0),
    Personality("insider", "Informed", "Prop", .55, .05, .35, 4, 4.0, fast=True, informed=True, capacity=5, fast_activity=.8),
)}


@dataclass(frozen=True)
class Bot:
    id: str                                     # CP-1 ...
    key: str

    @property
    def p(self) -> Personality:
        return PERSONALITIES[self.key]


def make_bots(keys: tuple[str, ...]) -> list[Bot]:
    return [Bot(f"CP-{i + 1}", k) for i, k in enumerate(keys)]


@dataclass
class Look:
    """What a bot can see of one market when it looks."""
    market: str
    fair: float
    sd: float
    lagged_fair: float
    truth: float
    bid: float
    offer: float
    tick: float
    avail_buy: int                              # lots I can still sell it (my size and my limit room on that side, after the risk budget)
    avail_sell: int


@dataclass
class Order:
    bot: str
    market: str
    bot_side: str                               # buy: the bot lifts my offer | sell: the bot hits my bid
    qty: int
    score: float                                # edge in standard deviations (used to allocate a limited capacity)


def consider(bot: Bot, look: Look, rs: Stream, phase: str) -> Order | None:
    """The bot's decision on one market. Draws a fixed set of random numbers first, so the stream is aligned whatever happens."""
    p = bot.p
    arrive, noise_z = rs.u(), rs.gauss()
    act = p.activity if phase == "A" else p.fast_activity
    if phase == "B" and not p.fast:
        return None
    if arrive >= act:
        return None
    s = max(look.sd, 2 * look.tick)
    base = look.truth if p.informed else (look.lagged_fair if p.lag else look.fair)
    est = base + p.noise * s * noise_z
    buy_edge, sell_edge = (est - look.offer) / s, (look.bid - est) / s
    if buy_edge >= p.thr and look.avail_buy > 0 and buy_edge >= sell_edge:
        side, edge, room = "buy", buy_edge, look.avail_buy
    elif sell_edge >= p.thr and look.avail_sell > 0:
        side, edge, room = "sell", sell_edge, look.avail_sell
    else:
        return None
    qty = max(1, min(p.max_size, room, 1 + int(p.size_gain * max(0.0, edge - max(p.thr, 0.0)))))
    return Order(bot.id, look.market, side, qty, edge)
