"""One market at the table: its question, my quote, my position and cash, and every trade. Pure data and bookkeeping; the game decides when things happen.

Accounting convention (the same everywhere, including the debrief):
    a lot is a fixed quantity; each market has a point value pv (credits per lot per 1.0 of price), chosen so that one standard deviation of the question's initial uncertainty
    is worth about 100 credits per lot.
    a trade of q lots at price p: I BUY q (a bot SELLS to me: it hits my bid)  -> position +q, cash -= q*p*pv
                                  I SELL q (a bot BUYS from me: it lifts my offer) -> position -q, cash += q*p*pv
    settlement at S:  cash += position * S * pv, position -> 0.    P&L = cash after settlement.    Before settlement, 'open P&L' marks the position at MY mid (not at any hidden fair value).
Prices are held as integer multiples of the tick, so a quote can never be off the grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from .probability import (DeckExperiment, DiceExperiment, Target, card_pred_text, event_text, face_pred_text, mean, variance)
from .world import WorldItem, WorldModel, fmt_num


def nice_pv(sd: float) -> Fraction:
    """Credits per lot per price point so that one standard deviation is worth ~100: the nearest of 1, 2, 5 times a power of ten."""
    target = 100.0 / max(sd, 1e-9)
    best, best_err = None, 1e18
    for e in range(-4, 5):
        for m in (1, 2, 5):
            v = m * 10.0 ** e
            err = abs(math.log(v / target))
            if err < best_err:
                best, best_err = v, err
    return Fraction(str(best)).limit_denominator(10000)


def decimals(tick: Fraction) -> int:
    d = 0
    while (tick * 10 ** d).denominator != 1 and d < 8:
        d += 1
    return d


@dataclass
class Quote:
    bid: int                                    # in ticks
    offer: int
    size: int
    set_round: int                              # the number of rounds completed when it was set


@dataclass
class Trade:
    n: int
    round: int                                  # the round in which it happened (1-based)
    phase: str                                  # A = normal flow, B = fast reaction after a shock
    market: str
    bot: str                                    # counterparty code
    me: str                                     # buy | sell: what *I* did
    qty: int
    price: Fraction
    fair: Fraction                              # public fair value at that moment (HIDDEN until the market has resolved)
    bid: Fraction                               # my market at that moment
    offer: Fraction
    stale: bool                                 # my quote was set before the latest shock on this market
    informed: bool                              # the bot had private information (HIDDEN until the end)
    pos_after: int


@dataclass
class Market:
    id: str
    title: str
    kind: str                                   # probability | world
    category: str
    unit: str
    tick: Fraction
    pv: Fraction
    price_lo: Fraction
    price_hi: Fraction
    opens_at: int
    resolves_at: int
    limit: int
    exp_id: str | None = None                   # the (possibly shared) experiment, for probability markets
    target: Target | None = None
    world: WorldModel | None = None
    sd0: float = 1.0                            # the initial public standard deviation (sizes the lot value)
    # state
    status_flags: dict = field(default_factory=lambda: {"shocked": False, "paused": False, "resolved": False})
    quote: Quote | None = None
    pos: int = 0
    cash: Fraction = Fraction(0)
    trades: list[Trade] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)      # public log of shocks / information that hit this market
    settle: Fraction | None = None
    fair_hist: list[Fraction] = field(default_factory=list)   # public fair at the start (index 0) and after each round
    final_fair: Fraction | None = None
    settled_pos: int = 0
    resolved_round: int = 0
    last_shock_round: int = 0
    quote_log: list[dict] = field(default_factory=list)
    shock_audit: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------ status
    @property
    def resolved(self) -> bool:
        return self.status_flags["resolved"]

    def status(self, rnd: int) -> str:
        if self.resolved:
            return "resolved"
        if rnd < self.opens_at:
            return "upcoming"
        if self.status_flags["paused"]:
            return "paused"
        if self.status_flags["shocked"]:
            return "shocked"
        return "active"

    def is_open(self, rnd: int) -> bool:
        return not self.resolved and rnd >= self.opens_at

    # ------------------------------------------------------------ what is public (and the hidden)
    def public(self, exps: dict) -> tuple[Fraction, float]:
        """Fair value and standard deviation of the answer given everything that is public now."""
        if self.world:
            m, sd = self.world.belief()
            return m, sd
        p = exps[self.exp_id].pmf(self.target)
        return mean(p), math.sqrt(float(variance(p)))

    def support(self, exps: dict) -> tuple[Fraction, Fraction]:
        if self.world:
            return self.world.support()
        a, b = exps[self.exp_id].support(self.target)
        return Fraction(a), Fraction(b)

    def truth(self, exps: dict) -> Fraction:
        """The answer under the rules in force now. HIDDEN: used only by insiders and at resolution."""
        if self.world:
            return self.world.realise()
        return Fraction(exps[self.exp_id].realise(self.target))

    # ------------------------------------------------------------ text
    def question(self, exps: dict) -> str:
        if self.world:
            return self.world.item.question
        e, t = exps[self.exp_id], self.target
        if isinstance(e, DeckExperiment):
            base = f"How many {card_pred_text(t.pred)} are among the {e.draws} cards drawn?" if t.agg == "count" else ""
            if t.binary:
                return f"Will the number of {card_pred_text(t.pred)} among the {e.draws} cards drawn be such that it {event_text(t.event)}?"
            return base
        n = len(e.trials)
        noun = {"die": "dice", "coin": "coin flips", "integer": "random integers"}[e.noun] if n != 1 else {"die": "die", "coin": "coin flip", "integer": "random integer"}[e.noun]
        if t.agg == "sum":
            what = f"the sum of the {n} {noun}" if n != 1 else f"the {noun}"
        elif t.agg == "top2":
            what = f"the sum of the highest two of the {n} {noun}"
        elif t.agg == "max":
            what = f"the highest of the {n} {noun}"
        elif t.agg == "min":
            what = f"the lowest of the {n} {noun}"
        else:
            if e.noun == "coin":
                what = f"the number of heads in {n} {noun}"
            else:
                what = f"the number of the {n} {noun} that show a result that is {face_pred_text(t.pred)}"
        if t.binary:
            return f"Will {what} be a number that {event_text(t.event)}?"
        return what[0].upper() + what[1:]

    def rules(self, exps: dict) -> list[str]:
        if self.world:
            return self.world.describe()
        return exps[self.exp_id].describe()

    def resolution_text(self, exps: dict) -> str:
        if self.world:
            return f"Settles at the true answer, in {self.unit or 'the units of the question'}. The answer and the reference source are shown when the market resolves."
        pay = "Pays 100 if the statement is true and 0 if it is false, so the price is the probability in %." if self.target.binary else f"Settles at the value of the answer ({self.unit})."
        return pay + " Any trial not yet rolled is rolled by the game at resolution, under the rules in force then. Nothing about the outcome is decided in advance of that moment from what you can see."

    # ------------------------------------------------------------ money
    def px(self, ticks: int) -> Fraction:
        return ticks * self.tick

    def avg_price(self) -> Fraction | None:
        """Moving-average entry price of the position now open (None when flat): adding to a position averages in, reducing leaves the average, crossing zero restarts it."""
        pos, avg = 0, Fraction(0)
        for t in self.trades:
            d = t.qty if t.me == "buy" else -t.qty
            if pos == 0 or (pos > 0) == (d > 0):
                avg = (avg * abs(pos) + t.price * abs(d)) / (abs(pos) + abs(d))
                pos += d
            else:
                pos += d
                if pos == 0:
                    avg = Fraction(0)
                elif (pos > 0) != (pos - d > 0):
                    avg = t.price
        return avg if pos else None

    def mid(self) -> Fraction | None:
        return None if self.quote is None else self.px(self.quote.bid + self.quote.offer) / 2

    def open_pnl(self) -> Fraction:
        """Cash so far plus the position marked at MY mid (zero position -> just the cash). After resolution: the final P&L."""
        if self.resolved:
            return self.cash
        m = self.mid()
        return self.cash + (self.pos * m * self.pv if m is not None else 0)
