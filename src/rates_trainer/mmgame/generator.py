"""Builds a game from (level, seed, number of markets, mix): the markets, their experiments, the opening and resolution schedule and the hidden shock plan.

Everything is drawn from named streams of the seed, so the same arguments always give the same game. The shock plan is built by simulating the effects in time order on
working copies, so every shock is valid when it lands (it leaves something to roll, changes the answer and is not a repeat), and its size is known (how far it moves the
fair value, in standard deviations) for the debrief. The plan is NEVER sent to the player before a shock lands.

Market templates (probability): sum of dice, count of results meeting a condition, highest or lowest of several dice, heads in coin flips, sum of the highest two (hard),
cards of a kind in a hand, and the *events* built on each of these (priced as a probability in %). Linked markets (level 3) are different readings of the same dice.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from fractions import Fraction

from .levels import LEVELS, Level
from .markets import Market, nice_pv
from .probability import (ALL_CARDS, AddJokers, AddTrials, ChangeDraws, DeckExperiment, DiceExperiment, Effect, LoadFace, RemoveCards, RemoveTrials, RestrictFaces, RevealCards,
                          RevealClass, RevealTrials, SetAgg, SetPred, SetSides, SetSpecial, SetThreshold, Target, build_deck, build_dice, mean, try_apply, variance)
from .rng import Stream
from .world import AltResolution, Clue, WorldItem, WorldModel, bank_items


@dataclass
class Shock:
    id: str
    round: int
    scope: str                                  # experiment | market
    ref: str                                    # experiment id or market id
    effect: Effect
    shift: float = 0.0                          # |change in fair value| / initial standard deviation, known at planning time (HIDDEN until the debrief)


@dataclass
class Spec:
    markets: list[Market]
    exps: dict
    shocks: list[Shock]


# ---------------------------------------------------------------- probability markets

def _tape(seed: int, key: str) -> list[int]:
    s = Stream(seed, "tape", key)
    return [s.u53() for _ in range(16)]


def _tick_for(sd: float) -> Fraction:
    return Fraction(1, 10) if sd < 4 else Fraction(1, 2)


def _moments(exp, target: Target) -> tuple[float, float]:
    p = exp.pmf(target)
    return float(mean(p)), math.sqrt(float(variance(p)))


def _noun_plural(noun: str) -> str:
    return {"die": "dice", "coin": "coin flips", "integer": "random integers"}[noun]


def _price_range(exp, target: Target) -> tuple[Fraction, Fraction]:
    if target.binary:
        return Fraction(0), Fraction(100)
    lo, hi = exp.support(target)
    if isinstance(exp, DeckExperiment):
        return Fraction(0), Fraction(exp.draws * 2)
    sides = max(max(t.weights) for t in exp.trials)
    n = len(exp.trials)
    top = {"sum": n * sides, "top2": 2 * sides, "count": n, "max": sides, "min": sides}[target.agg]
    return Fraction(0), Fraction(math.ceil(top * 2))


def short_pred(p: dict) -> str:
    k, v = p["kind"], p.get("v")
    return {"odd": "odd", "even": "even", "prime": "prime", "ge": f"≥{v}", "le": f"≤{v}", "eq": f"={v}", "ne": f"≠{v}", "mult": f"×{v}"}[k]


def _title(exp, target: Target) -> str:
    if isinstance(exp, DeckExperiment):
        what = card_phrase(target.pred)
        return f"P(≥{target.event['t']} {what} in {exp.draws} cards)" if target.binary else f"{what[0].upper() + what[1:]} in {exp.draws} cards"
    n = len(exp.trials)
    sides = max(max(t.weights) for t in exp.trials)
    d = f"{n}d{sides}" if exp.noun == "die" else (f"{n} coins" if exp.noun == "coin" else f"{n} ints 1–{sides}")
    if target.agg == "count":
        core = f"Heads in {n} flips" if exp.noun == "coin" else f"# {short_pred(target.pred)} in {d}"
    else:
        core = {"sum": f"Sum of {d}", "top2": f"Top-2 sum of {d}", "max": f"Highest of {d}", "min": f"Lowest of {d}"}[target.agg]
    if target.binary:
        t = target.event
        return f"P({core} {'≥' if t['op'] == 'ge' else '≤' if t['op'] == 'le' else '='} {t['t']})"
    return core


def card_phrase(pred: dict) -> str:
    from .probability import card_pred_text
    return card_pred_text(pred)


def _make_dice_market(level: Level, st: Stream, seed: int, key: str, n_dice: int | None = None, sides: int | None = None):
    L = level.n
    kinds = {1: ["sum", "count", "coin", "max", "event_sum"], 2: ["sum", "count", "coin", "max", "min", "event_sum", "event_count", "count"],
             3: ["sum", "count", "coin", "max", "min", "top2", "event_sum", "event_count", "event_max", "count", "sum"]}[L]
    kind = st.choice(kinds)
    noun = "coin" if kind == "coin" else ("integer" if st.chance(0.15 if L > 1 else 0.0) else "die")
    sides = sides or (6 if L == 1 else st.choice([6, 6, 8, 10]) if L == 2 else st.choice([6, 8, 10, 12]))
    if noun == "integer":
        sides = st.choice([6, 8, 10])
    if noun == "coin":
        n = n_dice or st.randint(4, {1: 8, 2: 12, 3: 16}[L])
    elif kind in ("top2",):
        n = n_dice or st.randint(3, 5)
    else:
        n = n_dice or {1: st.randint(1, 3), 2: st.randint(2, 4), 3: st.randint(3, 6)}[L]
        if kind in ("count", "event_count") and not n_dice:
            n = max(n, 3)
        if kind in ("max", "min", "event_max") and not n_dice:
            n = max(n, 2)
    weights = None
    if noun == "coin" and L == 3 and st.chance(0.35):
        weights = {0: 1, 1: 2}
    exp = build_dice(noun, sides, n, _tape(seed, key), weights)
    if kind == "coin":
        target = Target("count", {"kind": "eq", "v": 1})
    elif kind == "count" or kind == "event_count":
        pool = [{"kind": "odd"}, {"kind": "even"}, {"kind": "ge", "v": max(2, math.ceil(sides * 0.6) + 0)}] if L == 1 else \
               [{"kind": "odd"}, {"kind": "even"}, {"kind": "ge", "v": math.ceil(sides * 0.6) + 1}, {"kind": "le", "v": max(2, sides // 3)},
                {"kind": "prime"}, {"kind": "mult", "v": 3}]
        pred = st.choice(pool)
        target = Target("count", pred)
    elif kind in ("sum", "event_sum"):
        target = Target("sum")
    elif kind in ("max", "event_max"):
        target = Target("max")
    elif kind == "min":
        target = Target("min")
    else:
        target = Target("top2")
    if kind.startswith("event"):
        p = exp.pmf(target)
        med = _median(p)
        t = med + st.choice([0, 0, 1, -1]) if target.agg != "count" else max(1, int(round(float(mean(p)))) + st.choice([0, 1]))
        op = "ge" if st.chance(0.7) else "le"
        if kind == "event_max":
            op, t = "ge", max(2, sides - st.choice([0, 1]))
        target = Target(target.agg, target.pred, {"op": op, "t": t})
        pe = exp.pmf(target)
        if len(pe) < 2 or not (0.1 <= float(pe.get(100, 0)) <= 0.9):          # reject trivial events
            return None
    if len(exp.pmf(target)) < 2:
        return None
    return exp, target, kind


def _median(p) -> int:
    acc = Fraction(0)
    for k in sorted(p):
        acc += p[k]
        if acc >= Fraction(1, 2):
            return k
    return max(p)


def _make_deck_market(level: Level, st: Stream, seed: int, key: str):
    L = level.n
    draws = st.randint(3, 5) if L == 1 else st.randint(4, 7) if L == 2 else st.randint(5, 9)
    order = st.shuffle(ALL_CARDS)
    pred = st.choice([{"kind": "suit", "v": st.choice("SHDC")}, {"kind": "color", "v": st.choice(["red", "black"])}] if L == 1 else
                     [{"kind": "suit", "v": st.choice("SHDC")}, {"kind": "color", "v": st.choice(["red", "black"])}, {"kind": "face"}, {"kind": "ace"}, {"kind": "high"}])
    if pred["kind"] == "ace":
        draws = max(draws, 6)
    exp = build_deck(draws, order)
    target = Target("count", pred)
    if st.chance(0.35 if L > 1 else 0.0):
        p = exp.pmf(target)
        t = max(1, int(round(float(mean(p)))))
        target = Target("count", pred, {"op": "ge", "t": t})
        pe = exp.pmf(target)
        if len(pe) < 2 or not (0.1 <= float(pe.get(100, 0)) <= 0.9):
            return None
    return exp, target, "deck"


def _unit_for(target: Target, exp) -> str:
    if target.binary:
        return "% (pays 100)"
    if isinstance(exp, DeckExperiment):
        return "cards"
    if target.agg == "count":
        return "heads" if exp.noun == "coin" else "results"
    return "points"


# ---------------------------------------------------------------- the whole game

def _schedule(level: Level, st: Stream, n: int, linked_groups: list[list[int]]) -> list[tuple[int, int]]:
    """(opens_at, resolves_at) per market; linked markets share both. At least one market resolves in the last round, so the game ends on its schedule."""
    R = level.rounds
    out: list[tuple[int, int] | None] = [None] * n
    leader = {i: g[0] for g in linked_groups for i in g}
    members = lambda i: [k for k in range(n) if leader.get(k, k) == leader.get(i, i)]
    late = set(st.sample(list(range(n)), min(level.later_markets, max(0, n - 2)))) if level.later_markets else set()
    for i in range(n):
        if out[i] is not None:
            continue
        o = st.randint(1, max(1, R // 3)) if (i in late and i not in leader) else 0
        r = st.randint(min(o + (3 if level.n == 1 else 4), R), R)
        for j in members(i):
            out[j] = (o, r)
    if not any(r == R for _, r in out):
        i = st.randint(0, n - 1)
        for j in members(i):
            out[j] = (out[j][0], R)
    return out


def _pick_world(level: Level, st: Stream, used: set[str], used_cats: set[str], items: tuple[WorldItem, ...]) -> WorldItem:
    bank = [i for i in items if i.difficulty <= level.world_max_difficulty and i.id not in used]
    w = []
    for i in bank:
        base = 1.0 + (i.difficulty - 1) * (0.6 if level.n == 3 else 0.0)
        if i.category in used_cats:
            base *= 0.4
        if level.n >= 2 and i.alt:
            base *= 1.5                           # items that can take a resolution change are more useful at higher levels
        w.append(base)
    return st.weighted(bank, w)


def build(level_n: int, seed: int, n_markets: int | None = None, mix: str = "mixed", bank: int | None = None) -> Spec:
    level = LEVELS[level_n]
    items = bank_items(bank)
    lo, default, hi = level.markets
    n = default if n_markets is None else max(lo, min(hi, int(n_markets)))
    st = Stream(seed, "gen")
    # how many markets of each kind
    n_world = 0 if mix == "probability" else n if mix == "world" else max(1 if n > 1 else 0, round(n * level.world_share))
    if mix == "world":
        n_world = n
    n_prob = n - n_world
    linked_pairs = min(level.linked, n_prob // 2) if mix != "world" else 0
    kinds = ["prob"] * (n_prob - 2 * linked_pairs) + ["world"] * n_world
    kinds = st.shuffle(kinds)
    plan: list[tuple[str, int]] = [(k, -1) for k in kinds]
    groups: list[list[int]] = []
    for g in range(linked_pairs):
        a = len(plan)
        plan += [("linked", g), ("linked", g)]
        groups.append([a, a + 1])
    # keep linked groups adjacent at the end of the plan; shuffle display order later is unnecessary
    sched = _schedule(level, st, len(plan), groups)

    markets: list[Market] = []
    exps: dict = {}
    used_items: set[str] = set()
    used_cats: set[str] = set()
    idx = 0
    gi = 0
    i = 0
    while i < len(plan):
        kind, g = plan[i]
        o, r = sched[i]
        if kind == "world":
            it = _pick_world(level, st, used_items, used_cats, items)
            used_items.add(it.id)
            used_cats.add(it.category)
            ms = Stream(seed, "world", it.id)
            z = max(-2.0, min(2.0, ms.gauss()))
            za = max(-2.0, min(2.0, ms.gauss()))
            wm = WorldModel(it, z, za)
            m = Market(f"M{i + 1}", it.question, "world", it.category, it.unit, it.tick, nice_pv(it.spread), it.lo, it.hi, o, r, level.limit, world=wm, sd0=it.spread)
            m.fair_hist = []
            markets.append(m)
            i += 1
            continue
        if kind == "linked":
            key = f"E{i + 1}"
            ms = Stream(seed, "linked", g)
            for attempt in range(40):
                sub = Stream(seed, "linked", g, attempt)
                made = _make_dice_market(level, sub, seed, key, n_dice=sub.randint(3, 5), sides=6 if sub.chance(.6) else 8)
                if made and not made[2].startswith("event") and made[2] not in ("coin", "top2"):
                    break
            exp = made[0]
            exps[key] = exp
            t1 = Target("sum") if made[1].agg != "sum" else Target("count", {"kind": "odd"})
            t2 = Target("max") if t1.agg == "sum" else Target("sum")
            targets = [t1, t2]
            for j, tg in enumerate(targets):
                mi = i + j
                sd = _moments(exp, tg)[1]
                lo_, hi_ = _price_range(exp, tg)
                m = Market(f"M{mi + 1}", _title(exp, tg), "probability", "dice", _unit_for(tg, exp), _tick_for(sd), nice_pv(sd), lo_, hi_, sched[mi][0], sched[mi][1], level.limit,
                           exp_id=key, target=tg, sd0=sd)
                markets.append(m)
            i += 2
            continue
        # a free-standing probability market (retry until the draw is non-trivial)
        key = f"E{i + 1}"
        made = None
        for attempt in range(60):
            sub = Stream(seed, "prob", i, attempt)
            made = _make_deck_market(level, sub, seed, key) if (level.n >= 1 and sub.chance(0.22 if level.n > 1 else 0.12)) else _make_dice_market(level, sub, seed, key)
            if made:
                break
        exp, tg, _ = made
        exps[key] = exp
        sd = _moments(exp, tg)[1]
        lo_, hi_ = _price_range(exp, tg)
        cat = "cards" if isinstance(exp, DeckExperiment) else ("coins" if exp.noun == "coin" else "dice")
        markets.append(Market(f"M{i + 1}", _title(exp, tg), "probability", cat, _unit_for(tg, exp), Fraction(1) if tg.binary else _tick_for(sd), nice_pv(sd), lo_, hi_, o, r, level.limit,
                              exp_id=key, target=tg, sd0=sd))
        i += 1
    for m in markets:
        if m.opens_at == 0:
            m.fair_hist = [m.public(exps)[0]]
    shocks = plan_shocks(level, seed, Stream(seed, "shocks"), markets, exps)
    return Spec(markets, exps, shocks)


# ---------------------------------------------------------------- shock planning

def _candidates(exp, target: Target, world: WorldModel | None, category: str, st: Stream) -> list[Effect]:
    out: list[Effect] = []
    if world is not None:
        if category == "information":
            a, b = world.bounds()
            sp = world.item.spread
            tick = world.item.tick
            for k in (-0.6, 0.0, 0.6):
                t = Fraction(world.mu + sp * k).limit_denominator(1000)
                t = round(t / tick) * tick
                if not (world.item.lo < t < world.item.hi):
                    continue
                out.append(Clue("ge" if world.answer >= t else "lt", str(t)))
        elif category == "resolution" and world.item.alt and not world.alt_used:
            out.append(AltResolution())
        return out
    if isinstance(exp, DiceExperiment):
        sides = max(max(t.weights) for t in exp.trials)
        if category == "experiment":
            if exp.noun != "coin":
                out += [RestrictFaces({"kind": "even"}), RestrictFaces({"kind": "odd"}), RestrictFaces({"kind": "ge", "v": max(2, sides // 2 + 1)}),
                        RestrictFaces({"kind": "le", "v": max(2, sides // 2 + 1)}), RestrictFaces({"kind": "ge", "v": sides - 1})]
                out += [SetSides(s) for s in (4, 6, 8, 10, 12) if s != sides]
                out += [LoadFace(st.randint(1, sides), st.choice([2, 3]))]
            else:
                out += [LoadFace(1, st.choice([2, 3])), LoadFace(0, 2)]
            out += [AddTrials(1), AddTrials(2), RemoveTrials(1)]
        elif category == "information":
            out += [RevealTrials(1), RevealTrials(2), RevealClass("parity"), RevealClass("half")]
        else:
            ev = target.event
            if ev:
                out += [SetThreshold(ev["t"] + d) for d in (-2, -1, 1, 2)]
            elif target.pred and target.pred["kind"] in ("ge", "le"):
                out += [SetThreshold(target.pred["v"] + d) for d in (-1, 1)]
            if target.agg == "count" and exp.noun != "coin":
                out += [SetPred(p) for p in ({"kind": "odd"}, {"kind": "even"}, {"kind": "prime"}, {"kind": "ge", "v": max(2, sides // 2 + 1)}, {"kind": "le", "v": max(2, sides // 3)})]
            if target.agg == "sum":
                out += [SetAgg("top2")]
    else:
        if category == "experiment":
            out += [RemoveCards({"kind": "suit", "v": s}) for s in "SHDC"] + [RemoveCards({"kind": "color", "v": c}) for c in ("red", "black")] + [RemoveCards({"kind": "face"})]
            out += [AddJokers(1), AddJokers(2), ChangeDraws(1), ChangeDraws(-1), ChangeDraws(2)]
        elif category == "information":
            out += [RevealCards(1), RevealCards(2)]
        else:
            ev = target.event
            if ev:
                out += [SetThreshold(ev["t"] + d) for d in (-1, 1)]
            out += [SetSpecial(p) for p in ({"kind": "suit", "v": "S"}, {"kind": "suit", "v": "H"}, {"kind": "color", "v": "red"}, {"kind": "face"}, {"kind": "ace"}, {"kind": "high"})]
    return out


def plan_shocks(level: Level, seed: int, st: Stream, markets: list[Market], exps: dict) -> list[Shock]:
    lo, hi = level.shocks
    count = st.randint(lo, hi) if hi else 0
    if count == 0:
        return []
    work_exps = copy.deepcopy(exps)
    work_world = {m.id: copy.deepcopy(m.world) for m in markets if m.world}
    work_target = {m.id: m.target for m in markets}
    cats = list(level.shock_categories)
    weights = {"information": 0.34, "experiment": 0.4, "resolution": 0.26} if level.n > 1 else {"information": 0.6, "experiment": 0.4}
    # the rounds: each shock needs a market that is open that round and still has a round left after it
    rounds_ok: list[tuple[int, str]] = []
    for r in range(1, level.rounds):
        for m in markets:
            if m.opens_at + 1 <= r <= m.resolves_at - 1:
                rounds_ok.append((r, m.id))
    shocks: list[Shock] = []
    chosen = st.sample(rounds_ok, min(count * 3, len(rounds_ok)))
    chosen.sort(key=lambda x: (x[0], x[1]))
    seen_rounds_markets: set[tuple[int, str]] = set()
    n_id = 0
    for r, mid in chosen:
        if len(shocks) >= count:
            break
        if (r, mid) in seen_rounds_markets:
            continue
        m = next(x for x in markets if x.id == mid)
        sub = Stream(seed, "shock-pick", r, mid)
        cat_pool = [c for c in cats]
        cat = sub.weighted(cat_pool, [weights.get(c, 0.3) for c in cat_pool])
        cands = _candidates(work_exps.get(m.exp_id), work_target[m.id], work_world.get(m.id), cat, sub)
        cands = sub.shuffle(cands)
        best = None
        for eff in cands:
            if m.world:
                w2 = copy.deepcopy(work_world[m.id])
                before = w2.belief()
                try:
                    w2.apply(eff)
                except Exception:
                    continue
                after = w2.belief()
                shift = abs(float(after[0] - before[0])) / max(m.sd0, 1e-9)
                res = (w2, shift)
            else:
                exp0 = work_exps[m.exp_id]
                before_p = exp0.pmf(work_target[m.id])
                out = try_apply(exp0, work_target[m.id], eff)
                if out is None:
                    continue
                e2, t2 = out
                shift = abs(float(mean(e2.pmf(t2)) - mean(before_p))) / max(m.sd0, 1e-9)
                res = (e2, t2, shift)
            need = level.min_shift if cat != "information" else 0.0
            if shift >= need:
                best = (eff, res, shift)
                break
            if best is None or shift > best[2]:
                best = (eff, res, shift)
        if best is None:
            continue
        eff, res, shift = best
        if m.world:
            work_world[m.id] = res[0]
            ref, scope = m.id, "market"
        else:
            if eff.scope == "experiment":
                work_exps[m.exp_id] = res[0]
                ref, scope = m.exp_id, "experiment"
            else:
                work_exps[m.exp_id] = res[0]
                work_target[m.id] = res[1]
                ref, scope = m.id, "market"
        n_id += 1
        shocks.append(Shock(f"S{n_id}", r, scope, ref, eff, shift))
        seen_rounds_markets.add((r, mid))
    shocks.sort(key=lambda s: (s.round, s.id))
    for i, s in enumerate(shocks):
        s.id = f"S{i + 1}"
    return shocks
