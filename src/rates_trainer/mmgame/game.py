"""The game: a table of simultaneous markets, a round loop and the ledger. UI-agnostic and independent of the rates engine, the TRAIN catalogue and the Live Desk.

A round is one decision cycle, played by advance():
    1. Normal flow (phase A): each bot may look at each open, quoted, unpaused market and trade against my CURRENT bid or offer.
    2. Shocks scheduled for this round land. Affected markets are flagged SHOCKED and their public information, rules or resolution rule change.
    3. Fast reaction (phase B): fast bots (the sniper, insiders) trade in the shocked markets against the quote I still have there, which is now stale.
    4. Markets whose resolution round it is are settled on the verified outcome.
Then I see what happened, may re-quote, pause or resume any market, and advance again. Nothing runs on a clock.

Hidden until it is safe: the seed, the outcome tape, any unrolled result, the shock plan, the fair value at each trade, which counterparties were informed. The views built here
contain only what a participant could know; see Game.view().

Replay: a game is (level, seed, markets, mix, coach) plus the list of actions the player took. Game.replay(record) re-executes them and reaches the identical state.
"""

from __future__ import annotations

import secrets
import time
from fractions import Fraction

from .bots import Look, PERSONALITIES, consider, make_bots
from .generator import Shock, build
from .levels import LEVELS
from .markets import Market, Quote, Trade, decimals
from .rng import Stream
from .world import fmt_num, latest_bank

VERSION = 1
HEADLINE = {"experiment": "RULE CHANGE", "information": "NEW INFORMATION", "resolution": "RESOLUTION CHANGE"}


class GameError(ValueError):
    """A request the game refuses (bad quote, closed market, finished game). Nothing has changed when this is raised."""


def fl(x) -> float:
    return float(x)


class Game:
    def __init__(self, level: int, seed: int, n_markets: int | None = None, mix: str = "mixed", coach: bool | None = None,
                 game_id: str | None = None, started: str | None = None, bank: int | None = None):
        if level not in LEVELS:
            raise GameError("level must be 1, 2 or 3")
        if mix not in ("mixed", "probability", "world"):
            raise GameError("mix must be mixed, probability or world")
        self.id = game_id or secrets.token_hex(8)
        self.level, self.seed, self.mix = level, int(seed), mix
        self.lv = LEVELS[level]
        self.bank = latest_bank() if bank is None else int(bank)          # which version of the question bank this game was dealt from
        spec = build(level, self.seed, n_markets, mix, self.bank)
        self.markets: list[Market] = spec.markets
        self.exps: dict = spec.exps
        self._plan: list[Shock] = spec.shocks
        self.n_markets = len(self.markets)
        self.coach = self.lv.coach if coach is None else bool(coach)
        self.bots = make_bots(self.lv.bots)
        self.started = started or time.strftime("%Y-%m-%dT%H:%M:%S")
        self.round = 0
        self.done = False
        self.actions: list[dict] = []
        self.shock_log: list[dict] = []
        self.reports: list[dict] = []
        self._tn = 0
        self._used: dict[tuple[str, int], int] = {}

    # ------------------------------------------------------------------ helpers
    def m(self, mid: str) -> Market:
        for x in self.markets:
            if x.id == mid:
                return x
        raise GameError(f"unknown market {mid!r}")

    def _live(self) -> None:
        if self.done:
            raise GameError("the game is over")

    def _open(self, mid: str) -> Market:
        self._live()
        m = self.m(mid)
        if m.resolved:
            raise GameError(f"{m.id} has already resolved")
        if self.round < m.opens_at:
            raise GameError(f"{m.id} is not open yet")
        return m

    @staticmethod
    def _ticks(m: Market, x, what: str) -> int:
        if isinstance(x, bool) or not isinstance(x, (int, float, str)):
            raise GameError(f"{what} must be a number")
        try:
            f = Fraction(str(x).strip())
        except (ValueError, ZeroDivisionError):
            raise GameError(f"{what} must be a number") from None
        t = f / m.tick
        if t.denominator != 1:
            raise GameError(f"{what} must be a multiple of the tick ({fmt_num(m.tick)})")
        return int(t)

    # ------------------------------------------------------------------ player actions
    def check_quote(self, mid: str, bid, offer, size=1) -> tuple[Market, Quote]:
        m = self._open(mid)
        b, o = self._ticks(m, bid, "bid"), self._ticks(m, offer, "offer")
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= self.lv.size_max:
            raise GameError(f"size must be a whole number of lots from 1 to {self.lv.size_max}")
        if m.px(b) < m.price_lo or m.px(o) > m.price_hi:
            raise GameError(f"prices must stay inside {fmt_num(m.price_lo)} to {fmt_num(m.price_hi)}")
        if o <= b:
            raise GameError("the offer must be above the bid")
        return m, Quote(b, o, size, self.round)

    def set_quote(self, mid: str, bid, offer, size=1) -> None:
        m, q = self.check_quote(mid, bid, offer, size)
        self._set(m, q)
        self.actions.append({"t": "quote", "market": mid, "bid": str(bid), "offer": str(offer), "size": size})

    def set_quotes(self, quotes: list[dict]) -> None:
        """All or nothing: every quote is checked before any is applied."""
        checked = [self.check_quote(q["market"], q["bid"], q["offer"], q.get("size", 1)) for q in quotes]
        if len({m.id for m, _ in checked}) != len(checked):
            raise GameError("a market appears twice")
        for (m, q), raw in zip(checked, quotes):
            self._set(m, q)
            self.actions.append({"t": "quote", "market": m.id, "bid": str(raw["bid"]), "offer": str(raw["offer"]), "size": raw.get("size", 1)})

    def _set(self, m: Market, q: Quote) -> None:
        m.quote = q
        m.status_flags["shocked"] = False
        m.status_flags["paused"] = False                  # quoting a paused market puts it back on
        fair, sd = m.public(self.exps)
        m.quote_log.append({"round": self.round + 1, "bid": m.px(q.bid), "offer": m.px(q.offer), "size": q.size, "fair": fair, "sd": sd, "pos": m.pos})   # fair and sd: debrief only

    def pause(self, mid: str, paused: bool = True) -> None:
        m = self._open(mid)
        m.status_flags["paused"] = bool(paused)
        self.actions.append({"t": "pause", "market": mid, "paused": bool(paused)})

    def acknowledge(self, mid: str) -> None:
        """I have seen the shock and am leaving the quote as it is: the SHOCKED flag clears, the quote does not change."""
        m = self._open(mid)
        m.status_flags["shocked"] = False
        self.actions.append({"t": "ack", "market": mid})

    # ------------------------------------------------------------------ risk and room
    def _risk(self, m: Market, pos: int) -> float:
        if m.resolved or pos == 0:
            return 0.0
        return abs(pos) * float(m.pv) * m.public(self.exps)[1]

    def risk_total(self) -> float:
        return sum(self._risk(m, m.pos) for m in self.markets if m.is_open(self.round))

    def _room(self, m: Market, i_do: str) -> int:
        """Most lots I can trade on this side now: my quoted size, the position limit, and the firm-wide risk budget."""
        if m.quote is None:
            return 0
        lim = (m.limit - m.pos) if i_do == "buy" else (m.pos + m.limit)
        room = min(m.quote.size, max(0, lim))
        budget = self.lv.risk_budget
        if budget and room:
            sign = 1 if i_do == "buy" else -1
            base = self.risk_total() - self._risk(m, m.pos)
            while room and abs(m.pos + sign * room) > abs(m.pos) and base + self._risk(m, m.pos + sign * room) > budget:
                room -= 1
        return room

    def closed_sides(self, m: Market) -> dict:
        return {"bid": m.quote is not None and self._room(m, "buy") == 0, "offer": m.quote is not None and self._room(m, "sell") == 0}

    # ------------------------------------------------------------------ the round
    def advance(self) -> dict:
        self._live()
        n = self.round + 1
        events: list[dict] = []
        live = [m for m in self.markets if m.is_open(self.round)]
        self._flow(n, "A", live, events)
        shocked: set[str] = set()
        for s in [s for s in self._plan if s.round == n]:
            shocked |= self._shock(s, n, events)
        if shocked:
            self._flow(n, "B", [m for m in live if m.id in shocked and not m.resolved], events)
        for m in live:
            if m.resolves_at == n:
                self._resolve(m, n, events)
        self.round = n
        for m in self.markets:
            if m.resolved:
                continue
            if m.opens_at == n:
                events.append({"type": "opened", "market": m.id, "title": m.title})
            if m.is_open(n):
                m.fair_hist.append(m.public(self.exps)[0])
        if all(m.resolved for m in self.markets):
            self.done = True
        report = {"round": n, "events": events}
        self.reports.append(report)
        self.actions.append({"t": "advance"})
        return report

    def _look(self, m: Market, bot, n: int) -> Look:
        fair, sd = m.public(self.exps)
        hist = m.fair_hist or [fair]
        lag = bot.p.lag
        lagged = hist[max(0, len(hist) - 1 - lag)]
        truth = m.truth(self.exps) if bot.p.informed else fair
        return Look(m.id, fl(fair), sd, fl(lagged), fl(truth), fl(m.px(m.quote.bid)), fl(m.px(m.quote.offer)), fl(m.tick), self._room(m, "sell"), self._room(m, "buy"))

    def _flow(self, n: int, phase: str, mkts: list[Market], events: list[dict]) -> None:
        for bot in Stream(self.seed, "order", n, phase).shuffle(self.bots):
            if phase == "B" and not bot.p.fast:
                continue
            orders = []
            for m in mkts:
                if m.resolved or m.status_flags["paused"] or m.quote is None:
                    continue
                o = consider(bot, self._look(m, bot, n), Stream(self.seed, "bot", n, phase, m.id, bot.id), phase)
                if o:
                    orders.append(o)
            cap = bot.p.capacity
            for o in sorted(orders, key=lambda o: -o.score):
                m = self.m(o.market)
                qty = min(o.qty, self._room(m, "sell" if o.bot_side == "buy" else "buy"))
                if cap is not None:
                    qty = min(qty, cap - self._used.get((bot.id, n), 0))
                if qty <= 0:
                    continue
                self._used[(bot.id, n)] = self._used.get((bot.id, n), 0) + qty
                self._execute(m, bot, o.bot_side, qty, n, phase, events)

    def _execute(self, m: Market, bot, bot_side: str, qty: int, n: int, phase: str, events: list[dict]) -> None:
        q = m.quote
        price = m.px(q.offer if bot_side == "buy" else q.bid)
        me = "sell" if bot_side == "buy" else "buy"
        fair = m.public(self.exps)[0]
        self._tn += 1
        signed = qty if me == "buy" else -qty
        m.pos += signed
        m.cash -= signed * price * m.pv
        t = Trade(self._tn, n, phase, m.id, bot.id, me, qty, price, fair, m.px(q.bid), m.px(q.offer), m.last_shock_round > q.set_round, bot.p.informed, m.pos)
        m.trades.append(t)
        events.append({"type": "trade", "market": m.id, "trade": self._trade_view(m, t)})

    def _shock(self, s: Shock, n: int, events: list[dict]) -> set[str]:
        e = s.effect
        if s.scope == "experiment":
            hit = [m for m in self.markets if m.exp_id == s.ref and m.is_open(self.round) and not m.resolved]
        else:
            hit = [self.m(s.ref)]
        audit = {m.id: (m.public(self.exps)[0], m.pos) for m in hit}                    # fair value and position BEFORE the effect (debrief only)
        if s.scope == "experiment":
            text = self.exps[s.ref].apply(e)
        else:
            m0 = hit[0]
            if m0.world:
                text = m0.world.apply(e)
            else:
                m0.target, text = e.apply_target(m0.target, self.exps[m0.exp_id])
        entry = {"id": s.id, "round": n, "category": e.category, "headline": HEADLINE[e.category], "text": text, "markets": [m.id for m in hit]}
        self.shock_log.append(entry)
        for m in hit:
            f0, pos0 = audit[m.id]
            f1, sd1 = m.public(self.exps)
            q = m.quote
            m.shock_audit.append({"id": s.id, "round": n, "category": e.category, "headline": HEADLINE[e.category], "text": text, "position": pos0, "fair_before": f0, "fair_after": f1,
                                  "sd_after": sd1, "bid": None if q is None else m.px(q.bid), "offer": None if q is None else m.px(q.offer), "shift": s.shift})
            m.status_flags["shocked"] = True
            m.last_shock_round = n
            m.notes.append({"round": n, "category": e.category, "headline": HEADLINE[e.category], "text": text, "id": s.id})
        events.append({"type": "shock", **entry})
        return {m.id for m in hit}

    def _resolve(self, m: Market, n: int, events: list[dict]) -> None:
        S = m.truth(self.exps)
        m.final_fair = m.public(self.exps)[0]
        m.settle = S
        m.settled_pos = m.pos
        m.cash += m.pos * S * m.pv
        m.pos = 0
        m.status_flags["resolved"] = True
        m.resolved_round = n
        events.append({"type": "resolved", "market": m.id, "title": m.title, "settle": fl(S), "pnl": fl(m.cash), "position": m.settled_pos})

    # ------------------------------------------------------------------ views (public information only)
    def _trade_view(self, m: Market, t: Trade) -> dict:
        v = {"n": t.n, "round": t.round, "phase": t.phase, "market": t.market, "bot": t.bot, "type": self._bot_type(t.bot), "me": t.me, "qty": t.qty, "price": fl(t.price),
             "position_after": t.pos_after, "bid": fl(t.bid), "offer": fl(t.offer)}
        if m.resolved or (self.coach and m.kind == "probability"):
            edge = (t.fair - t.price) if t.me == "buy" else (t.price - t.fair)
            v["edge"] = fl(edge)                                 # per lot, in price units: what the trade was worth against the public fair value at that moment
        if m.resolved:
            v["fair"] = fl(t.fair)
            v["stale"] = t.stale
        return v

    def _bot_type(self, bot_id: str) -> str | None:
        bot = next(b for b in self.bots if b.id == bot_id)
        return {"full": PERSONALITIES[bot.key].label, "coarse": PERSONALITIES[bot.key].coarse, "none": None}[self.lv.types]

    def market_view(self, m: Market) -> dict:
        rnd = self.round
        st = m.status(rnd)
        out = {"id": m.id, "title": m.title, "kind": m.kind, "category": m.category, "unit": m.unit, "tick": fl(m.tick), "decimals": decimals(m.tick), "lot_value": fl(m.pv),
               "range": [fl(m.price_lo), fl(m.price_hi)], "status": st, "opens_at": m.opens_at, "resolves_at": m.resolves_at, "limit": m.limit,
               "notes": list(m.notes)}
        if st == "upcoming":
            out["opens_in"] = m.opens_at - rnd
            return out                                            # nothing about an unopened market is shown but its schedule
        out["question"] = m.question(self.exps)
        out["rules"] = m.rules(self.exps)
        out["resolution_rule"] = m.resolution_text(self.exps)
        out["position"] = m.pos
        out["quote"] = None if m.quote is None else {"bid": fl(m.px(m.quote.bid)), "offer": fl(m.px(m.quote.offer)), "size": m.quote.size, "set_round": m.quote.set_round,
                                                       "stale": m.last_shock_round > m.quote.set_round}
        out["trades"] = [self._trade_view(m, t) for t in m.trades]
        out["cash"] = fl(m.cash) if not m.resolved else fl(m.cash)
        if m.resolved:
            item = m.world.item if m.world else None
            out.update({"remaining": 0, "resolved_round": m.resolved_round, "settle": fl(m.settle), "position_at_settlement": m.settled_pos, "pnl": fl(m.cash),
                        "source": (item.source if item else None), "as_of": (m.world.as_of if m.world else None),
                        "resolution_text": (f"Settled at {fmt_num(m.settle)} {m.unit}".strip())})
            return out
        a, b = m.support(self.exps)
        out["possible"] = [fl(a), fl(b)]
        out["remaining"] = m.resolves_at - rnd
        out["avg_price"] = None if m.avg_price() is None else fl(m.avg_price())
        out["open_pnl"] = fl(m.open_pnl())
        out["closed"] = self.closed_sides(m)
        out["risk"] = round(self._risk(m, m.pos), 2)
        return out

    def view(self) -> dict:
        ms = [self.market_view(m) for m in self.markets]
        settled = sum(m.cash for m in self.markets if m.resolved)
        open_ = sum(m.open_pnl() for m in self.markets if not m.resolved and m.is_open(self.round))
        used = self.risk_total()
        return {
            "id": self.id, "level": self.level, "level_name": self.lv.name, "round": self.round, "rounds": self.lv.rounds, "phase": "done" if self.done else "quoting",
            "started": self.started, "mix": self.mix, "coach": self.coach, "size_max": self.lv.size_max, "limit": self.lv.limit,
            "markets": ms,
            "portfolio": {"pnl_settled": fl(settled), "pnl_open": fl(open_), "pnl_total": fl(settled + open_),
                          "gross_lots": sum(abs(m.pos) for m in self.markets if not m.resolved), "net_lots": sum(m.pos for m in self.markets if not m.resolved),
                          "risk_used": round(used, 1), "risk_budget": self.lv.risk_budget, "trades": sum(len(m.trades) for m in self.markets),
                          "open_markets": sum(1 for m in self.markets if m.is_open(self.round)), "resolved_markets": sum(1 for m in self.markets if m.resolved)},
            "shocks": list(self.shock_log),
            "last_report": self.reports[-1] if self.reports else None,
            "counterparties": [{"id": b.id, "type": self._bot_type(b.id)} for b in self.bots],
            "convention": ("P&L in credits. Buying q lots at p: cash -= q·p·lot value. Selling: cash += q·p·lot value. At resolution: cash += position · settlement · lot value. "
                           "Open P&L marks positions at YOUR mid, not at any hidden fair value."),
        }

    # ------------------------------------------------------------------ record and replay
    def record(self) -> dict:
        return {"v": VERSION, "id": self.id, "seed": self.seed, "level": self.level, "n_markets": self.n_markets, "mix": self.mix, "coach": self.coach, "bank": self.bank,
                "started": self.started, "round": self.round, "done": self.done, "actions": list(self.actions)}

    @classmethod
    def replay(cls, rec: dict) -> "Game":
        g = cls(rec["level"], rec["seed"], rec["n_markets"], rec["mix"], rec["coach"], rec["id"], rec["started"], rec.get("bank", 1))   # games saved before banks were versioned used bank 1
        for a in rec["actions"]:
            t = a["t"]
            if t == "quote":
                g.set_quote(a["market"], a["bid"], a["offer"], a["size"])
            elif t == "pause":
                g.pause(a["market"], a["paused"])
            elif t == "ack":
                g.acknowledge(a["market"])
            elif t == "advance":
                g.advance()
        return g

    def summary(self) -> dict:
        return {"id": self.id, "level": self.level, "level_name": self.lv.name, "started": self.started, "round": self.round, "rounds": self.lv.rounds, "markets": self.n_markets,
                "done": self.done, "pnl": fl(sum(m.cash for m in self.markets if m.resolved)), "trades": sum(len(m.trades) for m in self.markets)}
