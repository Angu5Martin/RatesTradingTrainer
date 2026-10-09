"""Hand-made tables for tests: a Game whose markets, experiments and shock plan are exactly what the test says."""

from __future__ import annotations

from fractions import Fraction

from rates_trainer.mmgame.game import Game
from rates_trainer.mmgame.generator import Shock, _tape
from rates_trainer.mmgame.markets import Market, nice_pv
from rates_trainer.mmgame.probability import Target, build_deck, build_dice, ALL_CARDS, mean
from rates_trainer.mmgame.rng import Stream
from rates_trainer.mmgame.world import WorldModel, bank_by_id


def empty_game(level: int = 2, seed: int = 1, **kw) -> Game:
    g = Game(level, seed, **kw)
    g.markets, g.exps, g._plan = [], {}, []
    return g


def add_dice(g: Game, mid: str, n=2, sides=6, target=None, opens_at=0, resolves_at=6, noun="die", key=None, weights=None, tick=Fraction(1, 10)) -> Market:
    key = key or f"E_{mid}"
    target = target or Target("sum")
    exp = g.exps.get(key) or build_dice(noun, sides, n, _tape(g.seed, key), weights)
    g.exps[key] = exp
    p = exp.pmf(target)
    sd = float(sum((k - mean(p)) ** 2 * v for k, v in p.items())) ** 0.5
    m = Market(mid, mid, "probability", "dice", "points", Fraction(1) if target.binary else tick, nice_pv(sd), Fraction(0), Fraction(100 if target.binary else 100),
               opens_at, resolves_at, g.lv.limit, exp_id=key, target=target, sd0=sd)
    m.fair_hist = [m.public(g.exps)[0]] if opens_at == 0 else []
    g.markets.append(m)
    return m


def add_deck(g: Game, mid: str, draws=5, pred=None, opens_at=0, resolves_at=6, event=None) -> Market:
    key = f"E_{mid}"
    exp = build_deck(draws, Stream(g.seed, "deck", mid).shuffle(ALL_CARDS))
    g.exps[key] = exp
    target = Target("count", pred or {"kind": "suit", "v": "H"}, event)
    p = exp.pmf(target)
    sd = float(sum((k - mean(p)) ** 2 * v for k, v in p.items())) ** 0.5
    m = Market(mid, mid, "probability", "cards", "cards", Fraction(1, 10), nice_pv(sd), Fraction(0), Fraction(20), opens_at, resolves_at, g.lv.limit, exp_id=key, target=target, sd0=sd)
    m.fair_hist = [m.public(g.exps)[0]]
    g.markets.append(m)
    return m


def add_world(g: Game, mid: str, item_id: str, z=0.0, z_alt=0.0, opens_at=0, resolves_at=6) -> Market:
    it = bank_by_id()[item_id]
    m = Market(mid, it.question, "world", it.category, it.unit, it.tick, nice_pv(it.spread), it.lo, it.hi, opens_at, resolves_at, g.lv.limit, world=WorldModel(it, z, z_alt), sd0=it.spread)
    m.fair_hist = [m.public(g.exps)[0]] if opens_at == 0 else []
    g.markets.append(m)
    return m


def shock(g: Game, rnd: int, effect, ref: str, scope: str) -> Shock:
    s = Shock(f"S{len(g._plan) + 1}", rnd, scope, ref, effect)
    g._plan.append(s)
    return s


def trade(g: Game, m: Market, bot_id: str, bot_side: str, qty: int) -> None:
    """Execute a bot trade against my current quote, as the round loop would (round 1, normal flow)."""
    bot = next(b for b in g.bots if b.id == bot_id)
    g._execute(m, bot, bot_side, qty, g.round + 1, "A", [])
