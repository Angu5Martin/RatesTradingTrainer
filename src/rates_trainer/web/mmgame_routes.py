"""HTTP API of the MARKET MAKING GAME (everything under /api/mmgame). Separate from TRAIN (/api/train) and the Live Desk (/api/desk): own game registry, own files.

    GET    /api/mmgame                       {levels, games}: the three levels' settings and the saved games (newest first)
    POST   /api/mmgame/start {level, markets?, mix?, seed?, coach?}   -> state
    GET    /api/mmgame/{id}                  -> state (a saved game is replayed from disk if the server was restarted)
    POST   /api/mmgame/{id}/quote {market, bid, offer, size?}         -> state     set or revise my market (clears PAUSED and SHOCKED on it)
    POST   /api/mmgame/{id}/quotes {quotes: [..]}                     -> state     several markets at once, all or nothing
    POST   /api/mmgame/{id}/pause {market, paused?}                   -> state     pull (or put back) a market's quote without losing it
    POST   /api/mmgame/{id}/ack {market}                              -> state     I have seen the shock and leave the quote as it is
    POST   /api/mmgame/{id}/advance                                   -> {report, state}   play one round
    GET    /api/mmgame/{id}/debrief                                   -> debrief   only after the last market has resolved (409 before)
    DELETE /api/mmgame/{id}                  abandon an unfinished game (409 if finished: finished games are kept)

state = Game.view(): public information only. It never contains the seed, the shock plan, a fair value before a market resolves, an unrolled result or which counterparty is informed.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..mmgame import debrief as debrief_mod
from ..mmgame import store as game_store
from ..mmgame.game import Game, GameError
from ..mmgame.levels import LEVELS, MIXES
from . import store as web_store

MAX_LIVE = 20


class StartBody(BaseModel):
    level: int
    markets: int | None = None
    mix: str = "mixed"
    seed: int | None = None
    coach: bool | None = None


class QuoteBody(BaseModel):
    market: str
    bid: float | str
    offer: float | str
    size: int = 1


class QuotesBody(BaseModel):
    quotes: list[QuoteBody]


class PauseBody(BaseModel):
    market: str
    paused: bool = True


class AckBody(BaseModel):
    market: str


@dataclass
class Live:
    game: Game
    lock: threading.Lock = field(default_factory=threading.Lock)


def level_info() -> list[dict]:
    return [{"level": lv.n, "name": lv.name, "blurb": lv.blurb, "markets": list(lv.markets), "rounds": lv.rounds, "limit": lv.limit, "size_max": lv.size_max,
             "risk_budget": lv.risk_budget, "shocks": list(lv.shocks), "coach": lv.coach, "late_markets": lv.later_markets, "linked": lv.linked} for lv in LEVELS.values()]


def make_router() -> APIRouter:
    r = APIRouter(prefix="/api/mmgame")
    live: dict[str, Live] = {}
    reg_lock = threading.Lock()

    def remember(g: Game) -> Live:
        with reg_lock:
            live[g.id] = Live(g)
            while len(live) > MAX_LIVE:
                live.pop(next(iter(live)))
            return live[g.id]

    def get(gid: str) -> Live:
        with reg_lock:
            hit = live.get(gid)
        if hit:
            return hit
        rec = game_store.load(web_store.home(), gid)
        if rec is None:
            raise HTTPException(404, "unknown game")
        try:
            return remember(Game.replay(rec))
        except Exception:
            raise HTTPException(409, "this saved game can no longer be replayed") from None

    def persist(g: Game) -> None:
        game_store.save(web_store.home(), g.record(), g.summary())

    def act(gid: str, fn):
        h = get(gid)
        with h.lock:
            try:
                out = fn(h.game)
            except GameError as e:
                raise HTTPException(400, str(e)) from None
            persist(h.game)
            return out

    @r.get("")
    def games():
        return {"levels": level_info(), "mixes": list(MIXES), "games": game_store.list_games(web_store.home())}

    @r.post("/start")
    def start(body: StartBody):
        try:
            seed = body.seed if body.seed is not None else secrets.randbelow(1_000_000_000)
            g = Game(body.level, seed, body.markets, body.mix, body.coach)
        except GameError as e:
            raise HTTPException(400, str(e)) from None
        h = remember(g)
        with h.lock:
            persist(g)
            return g.view()

    @r.get("/{gid}")
    def state(gid: str):
        h = get(gid)
        with h.lock:
            return h.game.view()

    @r.post("/{gid}/quote")
    def quote(gid: str, body: QuoteBody):
        return act(gid, lambda g: (g.set_quote(body.market, body.bid, body.offer, body.size), g.view())[1])

    @r.post("/{gid}/quotes")
    def quotes(gid: str, body: QuotesBody):
        return act(gid, lambda g: (g.set_quotes([q.model_dump() for q in body.quotes]), g.view())[1])

    @r.post("/{gid}/pause")
    def pause(gid: str, body: PauseBody):
        return act(gid, lambda g: (g.pause(body.market, body.paused), g.view())[1])

    @r.post("/{gid}/ack")
    def ack(gid: str, body: AckBody):
        return act(gid, lambda g: (g.acknowledge(body.market), g.view())[1])

    @r.post("/{gid}/advance")
    def advance(gid: str):
        return act(gid, lambda g: {"report": g.advance(), "state": g.view()})

    @r.get("/{gid}/debrief")
    def debrief(gid: str):
        h = get(gid)
        with h.lock:
            if not h.game.done:
                raise HTTPException(409, "the debrief opens after the last market has resolved")
            return debrief_mod.build(h.game)

    @r.delete("/{gid}")
    def abandon(gid: str):
        h = get(gid)
        with h.lock:
            if h.game.done:
                raise HTTPException(409, "this game is finished: it is kept")
            with reg_lock:
                live.pop(gid, None)
            game_store.delete(web_store.home(), gid)
        return {"deleted": gid}

    return r
