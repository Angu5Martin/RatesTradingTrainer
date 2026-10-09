"""Skill graph.

A Skill is one thing you should be able to DO on a rates desk. Question templates and
curated questions declare which skill they exercise. `prereqs` give the teaching order
(a UI or scheduler can use them later); `planned` skills mark the roadmap so that
coverage gaps are visible in code and checked by a test, not kept in someone's head.

Track ordering follows the CLAUDE.md loops:
    Trade -> Position -> Risk -> Hedge -> Market Move -> P&L
    Fair Value -> Quote -> Client Trade -> Position -> Risk -> Skew/Hedge -> Move -> P&L -> Re-quote
"""

from __future__ import annotations

from dataclasses import dataclass

TRACKS: dict[str, str] = {
    "math": "Rates mathematics",
    "swaps": "Swaps, OIS and FRAs",
    "bonds": "Bonds, money markets and repo",
    "futures": "Interest-rate futures",
    "risk": "Risk and hedging",
    "curve": "Curve trades",
    "rv": "Relative value and basis",
    "pnl": "P&L and attribution",
    "mm": "Market making and quoting",
    "portfolio": "Portfolio risk",
}


@dataclass(frozen=True)
class Skill:
    id: str
    track: str
    title: str
    prereqs: tuple[str, ...] = ()
    planned: bool = False


def _s(id: str, title: str, prereqs: tuple[str, ...] = (), planned: bool = False) -> Skill:
    return Skill(id, id.split(".")[0], title, prereqs, planned)


_SKILLS = [
    # --- maths ---
    _s("math.forward_rates", "Forward rates from zero rates / discount factors"),
    _s("math.bootstrapping", "Bootstrapping a curve from par swap rates", ("math.forward_rates",), True),
    _s("math.interpolation", "Interpolation and what it does to forwards and risk", ("math.bootstrapping",), True),
    # --- swaps ---
    _s("swaps.dv01", "Swap DV01 and P&L for a rate move", ("math.forward_rates",)),
    _s("swaps.forward_start", "Forward-starting swaps and forward par rates", ("swaps.dv01",)),
    _s("swaps.ois_vs_ibor", "OIS vs Euribor swaps, discounting and tenor basis", ("swaps.dv01",)),
    _s("swaps.fra", "FRAs: pricing, DV01, hedging with swaps and futures", ("swaps.dv01",)),
    _s("swaps.basis", "Basis swaps (3s6s, ESTR-Euribor) direction and risk", ("swaps.ois_vs_ibor",)),
    # --- bonds / money markets ---
    _s("bonds.duration_convexity", "Bond DV01, duration and convexity P&L", ("swaps.dv01",)),
    _s("bonds.money_market", "Bills, zero-coupon instruments, money-market yields", (), True),
    _s("bonds.carry", "Bond carry and roll-down against repo: yield pickup, pull-to-par, curve roll, breakeven",
       ("bonds.repo", "curve.carry_rolldown", "bonds.duration_convexity")),
    _s("bonds.repo", "Repo, financing, specialness", ("bonds.duration_convexity",)),
    # --- futures ---
    _s("futures.conversion_factor", "Conversion factors, invoice price and gross basis", ("bonds.duration_convexity",)),
    _s("futures.dv01", "Bund/Bobl/Schatz futures DV01 and CF-weighted hedges", ("futures.conversion_factor",)),
    _s("futures.ctd", "Cheapest-to-deliver: net basis ranking, implied repo, why it switches",
       ("futures.conversion_factor", "bonds.repo")),
    _s("futures.stir", "3M Euribor futures and strips: price, DV01, direction, hedging a swap, convexity adjustment", ("swaps.fra",)),
    # --- risk ---
    _s("risk.hedge_ratio", "DV01-neutral hedge ratios across tenors", ("swaps.dv01",)),
    _s("risk.key_rate", "Key-rate exposure and what a hedge leaves behind", ("risk.hedge_ratio",)),
    _s("risk.convexity", "Convexity: who is long/short and what it costs", ("bonds.duration_convexity",), True),
    # --- curve ---
    _s("curve.steepener", "Curve trade direction, DV01-neutral sizing and P&L", ("risk.hedge_ratio",)),
    _s("curve.direction", "Bull/bear steepening and flattening", ("swaps.dv01",)),
    _s("curve.butterfly", "Butterflies: weights, direction, P&L", ("curve.steepener",), True),
    _s("curve.carry_rolldown", "Carry and roll-down of a position: accrual, curve rate for the remaining maturity, breakeven",
       ("swaps.dv01", "math.forward_rates")),
    _s("curve.carry_curve", "Carry and roll-down of curve trades: the forward-implied spread drift",
       ("curve.carry_rolldown", "curve.steepener")),
    # --- relative value ---
    _s("rv.swap_spread", "Swap spreads and asset swaps: direction and packages", ("bonds.duration_convexity",)),
    _s("rv.asw", "Asset-swap packages: sizing and P&L", ("rv.swap_spread",)),
    _s("rv.futures_basis", "Cash-futures basis: net basis vs delivery-option value, buy/sell the basis, what the position owns",
       ("futures.ctd", "futures.dv01")),
    _s("rv.cash_vs_swaps", "Cash vs swaps relative value", ("rv.asw",)),
    # --- P&L ---
    _s("pnl.convexity", "Convexity in P&L: asymmetry for large moves", ("bonds.duration_convexity",)),
    _s("pnl.warehousing", "Warehousing: carry as the market's expected drift, breakeven versus volatility",
       ("curve.carry_rolldown",)),
    _s("pnl.attribution", "Attribution: carry, roll, delta, curve, convexity", ("pnl.convexity", "curve.carry_rolldown")),
    # --- market making ---
    _s("mm.bid_offer", "Bid/offer sides: what each client action leaves you with"),
    _s("mm.client_trade", "Client trade -> position -> DV01 -> edge -> hedge -> P&L",
       ("mm.bid_offer", "swaps.dv01", "risk.hedge_ratio")),
    _s("mm.skew", "Quote skew and width: inventory, flow, view, vol, liquidity", ("mm.bid_offer",)),
    _s("mm.hedge_vs_inventory", "Hedge now vs manage through flow", ("mm.skew", "mm.client_trade")),
    _s("mm.adverse_selection", "Adverse selection and protecting the market", ("mm.skew",)),
    _s("mm.requote_loop", "Multi-step: quote, trade, new inventory, re-quote", ("mm.skew", "mm.client_trade")),
    _s("mm.cross_product_hedging", "Hedging swaps with futures and bonds: cost, spread and basis risk, carry, overnight",
       ("futures.dv01", "rv.cash_vs_swaps", "bonds.repo")),
    _s("mm.views_and_events", "Views, events and changing conditions: sizing risk by conviction and vol",
       ("mm.skew", "mm.adverse_selection")),
    # --- portfolio ---
    _s("portfolio.aggregation", "Aggregate DV01, key-rate and curve exposure", ("risk.key_rate",), True),
    _s("portfolio.scenarios", "P&L under multi-factor scenarios", ("portfolio.aggregation",), True),
]

SKILLS: dict[str, Skill] = {s.id: s for s in _SKILLS}


def validate() -> list[str]:
    """Return a list of structural problems in the graph (empty = fine)."""
    problems = []
    for s in SKILLS.values():
        if s.track not in TRACKS:
            problems.append(f"{s.id}: unknown track {s.track}")
        for p in s.prereqs:
            if p not in SKILLS:
                problems.append(f"{s.id}: unknown prerequisite {p}")
    # cycle check
    state: dict[str, int] = {}

    def visit(sid: str) -> None:
        if state.get(sid) == 1:
            problems.append(f"cycle through {sid}")
            return
        if state.get(sid) == 2:
            return
        state[sid] = 1
        for p in SKILLS[sid].prereqs:
            if p in SKILLS:
                visit(p)
        state[sid] = 2

    for sid in SKILLS:
        visit(sid)
    return problems
