"""Client flow: who asks, whether they trade with you, and how informed they might be.

A STYLISED TRAINING MODEL, like quoting.py. It exists so that a quote has consequences that follow from it in a transparent way:

  * A client compares your price on ITS side with the street's (the best competitor price) and deals with you with probability
        P(fill) = logistic(logit(p_at_street) + improvement_bp / sensitivity_bp)
    improvement = how much better your price is than the street's for the client (in bp of rate). A price-sensitive client
    (small sensitivity) punishes a bad price hard; an informed client is less sensitive, because it needs to trade.
  * Every client type has a probability of being INFORMED: its trade predicts the next market move in its own favour. The trainee
    sees the type and its description, never the flag. A macro fund is not always informed and a corporate hedger occasionally is.

Signs follow quoting.py: a client who PAYS fixed trades on your OFFER (it wants it LOW); a client who RECEIVES trades on your BID (it wants it HIGH).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .quoting import BP, ClientAction, Liquidity, Quote, QuotingContext, make_quote


@dataclass(frozen=True)
class ClientType:
    name: str
    description: str          # what the trainee is told
    p_informed: float         # probability that a given trade predicts the next move
    sensitivity_bp: float     # price sensitivity of the fill probability (bp of rate per unit of log-odds)
    p_at_street: float        # probability of dealing with you if you match the street


CLIENT_TYPES: dict[str, ClientType] = {c.name: c for c in (
    ClientType("corporate", "Corporate treasurer hedging a new bond issue; trades a few times a year", 0.02, 0.15, 0.35),
    ClientType("pension", "Pension fund (LDI) extending hedges on a schedule", 0.05, 0.12, 0.35),
    ClientType("asset_manager", "Real-money asset manager adjusting duration", 0.15, 0.10, 0.35),
    ClientType("bank_treasury", "Bank treasury managing its balance-sheet hedge", 0.10, 0.10, 0.35),
    ClientType("macro_fund", "Macro hedge fund; trades around data and central-bank meetings", 0.45, 0.30, 0.45),
    ClientType("fast_money", "Fast-money account that has been on the right side of the last few moves", 0.60, 0.35, 0.50),
)}


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def improvement_bp(action: ClientAction, your: Quote, street: Quote) -> float:
    """How much better your price is than the street's, for this client (bp, + = you are better)."""
    if action is ClientAction.PAYS:
        return (street.offer - your.offer) / BP
    return (your.bid - street.bid) / BP


def fill_probability(ctype: ClientType, improvement: float) -> float:
    a = math.log(ctype.p_at_street / (1.0 - ctype.p_at_street))
    return logistic(a + improvement / ctype.sensitivity_bp)


def street_quote(mid: float, base_half_spread_bp: float, vol: float, liquidity: Liquidity, adverse: float) -> Quote:
    """The competitors' market: symmetric around mid (competitor inventories net out), width from the same quote model."""
    return make_quote(QuotingContext(fair_value=mid, base_half_spread_bp=base_half_spread_bp, vol_multiplier=vol,
                                     liquidity=liquidity, adverse_selection=adverse)).quote


def interdealer_half_spread_bp(base_half_spread_bp: float, vol: float, liquidity: Liquidity) -> float:
    """Half the interdealer bid/offer you cross to hedge: tighter than the client market, scaled by vol and liquidity."""
    return 0.5 * base_half_spread_bp * vol * liquidity.value
