#!/usr/bin/env python3
"""Measure simple quoting policies over whole MARKET MAKING GAME games: the source of the "Measured" numbers in docs/MARKET_MAKING_GAME/OVERVIEW.md.

Each policy quotes every open market every round around the EXACT public fair value (an oracle no player has for world questions), with a half-spread of h
standard deviations, and plays the game to the end through the real engine. Nothing is written anywhere: games are built in memory and never saved.

    .venv/bin/python scripts/measure_game_policies.py [games per level, default 40]

About 0.4 s a game; the default run takes roughly ten minutes. Seeds 0..N-1, default table size and mix, so the output is reproducible.
"""
import statistics as st
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rates_trainer.mmgame import debrief  # noqa: E402
from rates_trainer.mmgame.game import Game, GameError  # noqa: E402


def play(level: int, seed: int, h: float = .5, off: float = 0.0, requote: bool = True, size: int = 1, skew: float = 0.0) -> dict:
    """One game. off: the mid sits this many sd away from fair. skew: the mid moves against the position by skew sd x position/limit."""
    g = Game(level, seed)
    while not g.done:
        for m in g.markets:
            if not m.is_open(g.round) or (not requote and m.quote is not None):
                continue
            fair, sd = m.public(g.exps)
            sd = float(sd) or 1.0
            centre = float(fair) + off * sd - skew * sd * m.pos / max(1, m.limit)
            half = max(float(m.tick), h * sd)
            bid = max(round(Fraction(centre - half).limit_denominator(10**6) / m.tick) * m.tick, m.price_lo)
            offer = min(round(Fraction(centre + half).limit_denominator(10**6) / m.tick) * m.tick, m.price_hi)
            if offer <= bid:
                offer = bid + m.tick
            try:
                g.set_quote(m.id, float(bid), float(offer), min(size, g.lv.size_max))
            except GameError:
                pass
        g.advance()
    return debrief.build(g)["totals"]


POLICIES = [("half-spread 0.1 sd", dict(h=.1)), ("half-spread 0.2 sd", dict(h=.2)), ("half-spread 0.3 sd", dict(h=.3)), ("half-spread 0.5 sd", dict(h=.5)),
            ("half-spread 0.8 sd", dict(h=.8)), ("half-spread 1.2 sd", dict(h=1.2)), ("0.5 sd, maximum size", dict(h=.5, size=4)),
            ("0.5 sd, skew 0.6 sd x pos/limit", dict(h=.5, skew=.6)), ("0.5 sd, mid 0.5 sd off fair", dict(h=.5, off=.5)), ("0.5 sd, never re-quote", dict(h=.5, requote=False))]

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    for level in (1, 2, 3):
        print(f"LEVEL {level}  ({n} games each; credits per game)")
        for name, kw in POLICIES:
            t = [play(level, seed, **kw) for seed in range(n)]
            pnl = [x["pnl"] for x in t]
            print(f"  {name:34s} P&L mean {st.mean(pnl):7.0f}  sd {st.pstdev(pnl):6.0f}  decision result {st.mean(x['decision_result'] for x in t):7.0f}"
                  f"  adverse selection {st.mean(x['adverse_selection'] for x in t):7.0f}  luck {st.mean(x['luck'] for x in t):6.0f}", flush=True)
