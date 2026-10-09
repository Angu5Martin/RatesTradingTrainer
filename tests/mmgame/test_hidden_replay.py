"""Hidden information stays hidden until it is safe; and a game is exactly reproducible from its seed and the player's actions."""

import json
import random
import re

import pytest

from rates_trainer.mmgame import debrief
from rates_trainer.mmgame.game import Game
from rates_trainer.mmgame.generator import build
from tests.mmgame.helpers import add_dice, add_world, empty_game, shock
from rates_trainer.mmgame.probability import RestrictFaces, RevealClass


def walk(g: Game, rng: random.Random, view_log=None):
    """Play a game with arbitrary quotes (so trades, shocks and resolutions all happen), logging every view it would have sent."""
    while not g.done:
        for m in g.markets:
            if not m.is_open(g.round) or rng.random() < 0.3:
                continue
            f, sd = m.public(g.exps)
            t = float(m.tick)
            b = max(float(m.price_lo), round((float(f) - sd) / t) * t)
            try:
                g.set_quote(m.id, round(b, 6), round(b + t * rng.randint(1, 6), 6), rng.randint(1, g.lv.size_max))
            except Exception:
                pass
        g.advance()
        if view_log is not None:
            view_log.append(json.dumps(g.view()))
    return g


FORBIDDEN_KEYS = {"seed", "tape", "fair", "informed", "answer", "plan", "shock_plan", "shift", "fair_hist", "final_fair"}


def keys_of(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, path
            yield from keys_of(v, path + "/" + k)
    elif isinstance(x, list):
        for v in x:
            yield from keys_of(v, path)


@pytest.mark.parametrize("level", [1, 2, 3])
def test_views_never_carry_hidden_fields_for_open_markets(level):
    g = Game(level, 41 + level)
    rng = random.Random(level)
    log = []
    walk(g, rng, log)
    g2 = Game(level, 41 + level)
    seen_open = 0
    while not g2.done:
        for m in g2.markets:
            if m.is_open(g2.round):
                try:
                    g2.set_quote(m.id, float(m.price_lo + m.tick), float(m.price_lo + 3 * m.tick), 1)
                except Exception:
                    pass
        g2.advance()
        v = g2.view()
        for mv in v["markets"]:
            if mv["status"] in ("active", "shocked", "paused", "upcoming"):
                seen_open += 1
                bad = {k for k, _ in keys_of(mv)} & (FORBIDDEN_KEYS | {"settle", "pnl", "source", "position_at_settlement"})
                assert not bad, (mv["id"], bad)
                for t in mv.get("trades", []):
                    assert "fair" not in t and "stale" not in t and "informed" not in t
                    assert ("edge" in t) == (g2.coach and mv["kind"] == "probability"), "the edge shows only for the coach, on probability markets"
        top = {k for k, p in keys_of({k: v[k] for k in v if k != "markets"}) if p == ""}
        assert not (top & {"seed", "plan", "shock_plan", "tape"})
    assert seen_open


def test_resolved_markets_reveal_settlement_fair_value_and_edge_but_not_who_was_informed():
    g = walk(Game(3, 8), random.Random(2))
    assert g.done
    for mv in g.view()["markets"]:
        assert mv["status"] == "resolved" and "settle" in mv and mv["settle"] == float(g.m(mv["id"]).settle)
        for t in mv["trades"]:
            assert "fair" in t and "edge" in t and "informed" not in t
    assert all(c["type"] is None for c in g.view()["counterparties"])           # level 3 shows no counterparty types, even at the end of the game


def test_the_seed_the_tape_and_future_outcomes_are_in_no_payload_during_play():
    g = Game(2, 123456789)
    log = []
    walk(g, random.Random(5), log)
    blob = "\n".join(log)
    assert "123456789" not in blob
    tape_values = [str(x) for e in g.exps.values() for x in getattr(e, "tape", ())]
    assert tape_values and not any(tv in blob for tv in tape_values)


def test_world_answer_and_source_are_hidden_until_resolution():
    g = empty_game(2, 4)
    m = add_world(g, "M1", "gold_z", resolves_at=3)
    blob = json.dumps(g.view())
    mv = g.view()["markets"][0]
    assert "source" not in mv and "settle" not in mv and "as_of" not in mv and '"settle"' not in blob and "protons" in blob
    g.advance(); g.advance(); g.advance()
    mv = g.view()["markets"][0]
    assert mv["settle"] == 79 and "IUPAC" in mv["source"]


def test_unrolled_dice_are_not_revealed_by_information_shocks_beyond_what_is_announced():
    g = empty_game(2, 4)
    m = add_dice(g, "M1", n=4, resolves_at=6)
    shock(g, 1, RevealClass("parity"), "E_M1", "experiment")
    g.set_quote("M1", 8, 12)
    g.advance()
    blob = json.dumps(g.view())
    hidden = g.exps["E_M1"].trials[0].value                         # the real value of the partly-revealed die
    assert hidden is not None and "tape" not in blob and f"shows {hidden}" not in blob and "exact value is not shown" in blob


def test_debrief_is_refused_until_the_game_is_over():
    g = Game(1, 3)
    with pytest.raises(ValueError):
        debrief.build(g)
    walk(g, random.Random(1))
    assert debrief.build(g)["seed"] == 3


def test_generator_is_deterministic_and_seeds_differ():
    def sig(sp):
        return [(m.id, m.title, m.opens_at, m.resolves_at, str(m.tick), str(m.pv)) for m in sp.markets], [(s.round, s.ref, s.effect.kind, repr(s.effect.__dict__)) for s in sp.shocks]
    for level in (1, 2, 3):
        assert sig(build(level, 77)) == sig(build(level, 77))
        assert sig(build(level, 77)) != sig(build(level, 78))


def _digest(bank):
    import hashlib
    h = hashlib.sha256()
    for level in (1, 2, 3):
        for seed in (1, 2, 3, 4, 5):
            sp = build(level, seed, bank=bank)
            h.update(repr([(m.id, m.title, m.opens_at, m.resolves_at, str(m.tick), str(m.pv), str(m.price_hi)) for m in sp.markets]).encode())
            h.update(repr([(s.round, s.ref, s.effect.kind, sorted(s.effect.__dict__.items(), key=str)) for s in sp.shocks]).encode())
    return h.hexdigest()


# Saved games are replayed from (seed, actions, bank version): if the generator changes, old games would silently become different games. If either fails on purpose, bump VERSION.
SNAPSHOT_BANK1 = "7c6c7bf1d6a9906e00eb779bfa4e015a1cbe5830a62683bd6bdd4347c86e125c"      # the table every seed dealt before the bank grew: must never change
SNAPSHOT_BANK2 = "d1885901fcf67369998c05f208eb975962ff7a1265e8166a8f4d3f412af99a51"


def test_generator_snapshots_guard_replay_of_saved_games():
    assert _digest(1) == SNAPSHOT_BANK1, "a game dealt from bank 1 is no longer the same game: saved games would not replay"
    assert _digest(2) == SNAPSHOT_BANK2


def test_a_record_saved_before_banks_were_versioned_replays_from_bank_1():
    g = walk(Game(2, 77, bank=1), random.Random(1))
    rec = json.loads(json.dumps(g.record()))
    assert rec["bank"] == 1
    del rec["bank"]                                                   # the shape of a record written before the field existed
    again = Game.replay(rec)
    assert again.bank == 1 and json.dumps(again.view(), sort_keys=True) == json.dumps(g.view(), sort_keys=True)


def test_new_games_use_the_latest_bank_and_it_is_what_the_record_remembers():
    from rates_trainer.mmgame.world import latest_bank, bank_items
    g = Game(3, 5)
    assert g.bank == latest_bank() >= 2 and g.record()["bank"] == g.bank
    assert len(bank_items(2)) > len(bank_items(1)) == 92 and bank_items(1) == bank_items(2)[:92]
    done = walk(Game(2, 5), random.Random(2))
    assert Game.replay(json.loads(json.dumps(done.record()))).bank == done.bank


def test_a_bank_1_game_never_contains_a_later_item():
    from rates_trainer.mmgame.world import bank_items
    ids1 = {i.id for i in bank_items(1)}
    for seed in range(30):
        for lv in (1, 2, 3):
            for m in build(lv, seed, mix="world", bank=1).markets:
                assert m.world.item.id in ids1


@pytest.mark.parametrize("level", [1, 2, 3])
def test_replay_from_the_record_reproduces_the_game_exactly(level):
    g = walk(Game(level, 2024 + level), random.Random(level))
    again = Game.replay(json.loads(json.dumps(g.record())))
    assert json.dumps(again.view(), sort_keys=True) == json.dumps(g.view(), sort_keys=True)
    assert json.dumps(debrief.build(again), sort_keys=True) == json.dumps(debrief.build(g), sort_keys=True)
    assert [t.n for m in again.markets for t in m.trades] == [t.n for m in g.markets for t in m.trades]


def test_replay_of_an_unfinished_game_resumes_in_the_same_place():
    g = Game(2, 31)
    rng = random.Random(3)
    for _ in range(4):
        for m in g.markets:
            if m.is_open(g.round):
                f = float(m.public(g.exps)[0]); t = float(m.tick)
                lo = max(float(m.price_lo), round(f / t) * t - t)
                g.set_quote(m.id, round(lo, 6), round(lo + 2 * t, 6), 1)
        g.advance()
    r = Game.replay(g.record())
    assert not r.done and r.round == 4 and json.dumps(r.view(), sort_keys=True) == json.dumps(g.view(), sort_keys=True)
    r.advance(); g.advance()
    assert json.dumps(r.view(), sort_keys=True) == json.dumps(g.view(), sort_keys=True)


def test_bot_randomness_does_not_depend_on_what_the_player_did():
    """Arrival and noise are fixed by (seed, round, market, bot): a different quote changes decisions, not the stream."""
    from rates_trainer.mmgame.rng import Stream
    assert Stream(5, "bot", 3, "A", "M1", "CP-1").u() == Stream(5, "bot", 3, "A", "M1", "CP-1").u()
    a, b = Game(2, 9), Game(2, 9)
    assert [[x.id for x in g.markets] for g in (a, b)][0] == [x.id for x in b.markets]
    a.set_quote(a.markets[0].id, float(a.markets[0].price_lo), float(a.markets[0].price_lo + a.markets[0].tick), 1)
    assert a.markets[0].trades == [] and a.round == b.round == 0
