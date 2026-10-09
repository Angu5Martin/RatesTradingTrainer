"""Episode specifications: level 1 (one client, one trade) and level 2 (an inventory loop of client requests).

Each spec builds its starting state from the `setup` stream and draws each client from the `arrivals` stream. Levels 3-5 (curve book,
cross-product hedges, information and regime) are designed in docs/EPISODES.md and not built yet.
"""

from __future__ import annotations

import random

from ..engine.instruments import IRSwap, Side
from ..engine.risk import unit_dv01
from ..marketmaking.flow import CLIENT_TYPES
from ..marketmaking.quoting import BP, ClientAction, Liquidity
from ..questions.market import random_market
from .episode import EpisodeSpec, Setup, register_episode
from .state import ExpectedFlow, Inquiry, Position, Regime

STEP = 25e6


def _round_notional(x: float) -> float:
    return max(STEP, round(x / STEP) * STEP)


def _initial_inventory(rng: random.Random, mkt, tenor: int, limit: float, frac: float) -> tuple[Position, ...]:
    if frac == 0:
        return ()
    notional = _round_notional(abs(frac) * limit / unit_dv01(tenor, mkt) * 1e6)
    rate = mkt.par_irs_rate(12 * tenor) + rng.uniform(-3.0, 3.0) * BP          # dealt earlier today, a little off today's mid
    side = Side.RECEIVE if frac > 0 else Side.PAY
    return (Position(IRSwap.new(side, notional, round(rate, 6), mkt.spot, 12 * tenor), "initial", "earlier today", -1),)


def _draw_inquiry(rng: random.Random, s: Setup, size_range: tuple[float, float]) -> Inquiry:
    types, weights = zip(*s.regime.client_mix)
    ctype = rng.choices(types, weights)[0]
    action = ClientAction.PAYS if rng.random() < s.regime.p_pays else ClientAction.RECEIVES
    notional = _round_notional(rng.uniform(*size_range) * s.limit / unit_dv01(s.tenor, s.mkt) * 1e6)
    informed = rng.random() < CLIENT_TYPES[ctype].p_informed
    return Inquiry(ctype, action, notional, informed)


# ============================================================================================ level 1

def _build_l1(rng: random.Random) -> Setup:
    mkt = random_market(rng)
    tenor = rng.choices([5, 10, 30], [3, 5, 2])[0]
    limit = rng.choice([200e3, 300e3, 500e3])
    vol = rng.choice([0.6, 1.0, 1.0, 1.8])
    liq = rng.choice(list(Liquidity))
    dv_pm = unit_dv01(tenor, mkt)
    frac = rng.choice([-0.5, -0.3, 0.0, 0.3, 0.5])
    expected = None
    if rng.random() < 0.5:
        action = rng.choice(list(ClientAction))
        n = _round_notional(rng.uniform(0.3, 0.7) * limit / dv_pm * 1e6)
        p = rng.choice([0.5, 0.7, 0.8])
        who = rng.choice(["a pension fund", "a corporate", "an insurer's ALM desk"])
        expected = ExpectedFlow(action, n, p, f"sales expects {who} to {action.value.rstrip('s')} fixed on about €{n / 1e6:,.0f}m "
                                              f"{tenor}Y later today ({p:.0%} likely).")
    regime = Regime(vol, liq, (("corporate", 3), ("pension", 3), ("asset_manager", 2), ("bank_treasury", 2), ("macro_fund", 1)),
                    0.5, 0.25, "two-way: recent inquiries show no clear direction.", 0.5 * limit / dv_pm * 1e6, expected)
    return Setup("Level 1: one client, one trade",
                 "Make a two-way market, see whether the client deals, decide how much risk to keep, then watch the market move.",
                 mkt, tenor, limit, _initial_inventory(rng, mkt, tenor, limit, frac), regime, 1, "twoway", checkpoint=True)


register_episode(EpisodeSpec("mm.ep1_single_trade", 1, "mm.hedge_vs_inventory", "One client, one trade: quote, fill, hedge or warehouse",
                             _build_l1, lambda rng, s: _draw_inquiry(rng, s, (0.3, 0.7))))


# ============================================================================================ level 2

def _build_l2(rng: random.Random) -> Setup:
    mkt = random_market(rng)
    tenor = rng.choices([5, 10, 30], [3, 5, 2])[0]
    limit = rng.choice([200e3, 300e3, 500e3])
    vol = rng.choice([0.6, 1.0, 1.0, 1.8])
    liq = rng.choice(list(Liquidity))
    dv_pm = unit_dv01(tenor, mkt)
    frac = rng.choice([-0.6, -0.4, -0.2, 0.2, 0.4, 0.6])
    p_pays = rng.choice([0.5, 0.3, 0.7, 0.25, 0.75])
    mix = rng.choice([
        (("corporate", 2), ("pension", 3), ("asset_manager", 3), ("bank_treasury", 2), ("macro_fund", 1)),
        (("pension", 2), ("asset_manager", 3), ("macro_fund", 2), ("fast_money", 1)),
        (("asset_manager", 2), ("macro_fund", 3), ("fast_money", 2), ("bank_treasury", 1)),
    ])
    typical = 0.35 * limit / dv_pm * 1e6
    if p_pays == 0.5:
        flow_text, expected = "two-way: no clear direction in this morning's inquiries.", None
    else:
        majority = ClientAction.PAYS if p_pays > 0.5 else ClientAction.RECEIVES
        share = max(p_pays, 1 - p_pays)
        flow_text = (f"one-way: about {share:.0%} of this morning's inquiries were clients who "
                     f"{majority.value.rstrip('s')} fixed.")
        expected = ExpectedFlow(majority, typical, 2 * share - 1,
                                f"if that continues, the next few inquiries lean towards clients who {majority.value.rstrip('s')} fixed.")
    regime = Regime(vol, liq, mix, p_pays, 0.125, flow_text, typical, expected)
    return Setup("Level 2: working an inventory",
                 "Five client requests in a row. Price each one (or pass), then hedge or keep the risk before the market moves. "
                 "Your inventory and P&L carry from one request to the next.",
                 mkt, tenor, limit, _initial_inventory(rng, mkt, tenor, limit, frac), regime, 5, "rfq")


register_episode(EpisodeSpec("mm.ep2_inventory_loop", 2, "mm.requote_loop", "Working an inventory: five requests, re-pricing as the book changes",
                             _build_l2, lambda rng, s: _draw_inquiry(rng, s, (0.2, 0.5))))


# ============================================================================================ level 3: the curve book

from dataclasses import replace as _replace  # noqa: E402

from ..episodes.state import Desk, Limits, RoundPlan  # noqa: E402

CURVE_TENORS = (2, 5, 10, 30)
# Where each client type tends to trade (training assumption, for variety and structure; not market statistics)
TENOR_PREFS = {
    "pension": {30: 0.6, 10: 0.3, 5: 0.1},
    "corporate": {5: 0.5, 10: 0.4, 2: 0.1},
    "asset_manager": {5: 0.35, 10: 0.35, 30: 0.3},
    "bank_treasury": {2: 0.5, 5: 0.4, 10: 0.1},
    "macro_fund": {2: 0.25, 5: 0.25, 10: 0.25, 30: 0.25},
    "fast_money": {2: 0.25, 5: 0.25, 10: 0.25, 30: 0.25},
}
L3_VARIANTS = {
    "ldi": ("an LDI morning: pension funds have been receiving the long end all morning; real money is two-way in the belly.",
            {"pension": 0.25}, (("pension", 4), ("asset_manager", 3), ("bank_treasury", 1), ("macro_fund", 1))),
    "corporate": ("corporate hedging season: corporates are paying 5-10Y to fix floating-rate debt; bank treasuries are two-way at the front.",
                  {"corporate": 0.75}, (("corporate", 4), ("bank_treasury", 3), ("asset_manager", 2), ("macro_fund", 1))),
}


def _swap_at(mkt, tenor: int, dv01: float, rng: random.Random, label: str) -> Position:
    notional = _round_notional(abs(dv01) / unit_dv01(tenor, mkt) * 1e6)
    rate = mkt.par_irs_rate(12 * tenor) + rng.uniform(-2.0, 2.0) * BP
    return Position(IRSwap.new(Side.RECEIVE if dv01 > 0 else Side.PAY, notional, round(rate, 6), mkt.spot, 12 * tenor), "initial", label, -1)


def _build_l3(variant: str):
    text, _, mix = L3_VARIANTS[variant]

    def build(rng: random.Random) -> Setup:
        from ..engine.risk import Portfolio
        from .factors import FactorRisk
        for _ in range(100):
            mkt = random_market(rng)
            limit = rng.choice([300e3, 500e3])
            slope_limit = 0.5 * limit
            # a starting book with a real curve profile: two or three legs in different tenors
            legs = rng.sample(CURVE_TENORS, rng.choice([2, 3]))
            positions = tuple(_swap_at(mkt, t, rng.choice([-1, 1]) * rng.uniform(0.15, 0.4) * limit, rng, f"earlier today ({t}Y)")
                              for t in legs)
            x = FactorRisk(mkt).exposures(Portfolio([p.inst for p in positions]))
            if abs(x["level"]) <= 0.5 * limit and 0.25 * slope_limit <= abs(x["slope"]) <= 0.7 * slope_limit:
                break
        vol = rng.choice([0.6, 1.0, 1.0, 1.8])
        liq = rng.choice(list(Liquidity))
        typical = 0.3 * limit / unit_dv01(10, mkt) * 1e6
        regime = Regime(vol, liq, mix, 0.5, 0.125, text, typical)
        desk = Desk(CURVE_TENORS, Limits(limit, slope_limit), multi_tenor=True)
        plans = tuple(RoundPlan("rfq", checkpoint="slope_if_dealt" if r == 1 else None) for r in range(5))
        return Setup("Level 3: the curve book",
                     "Clients ask in the 2Y, 5Y, 10Y and 30Y. Your risk is a curve, not a number: price each request by what it does to the "
                     "WHOLE book, then decide where (and whether) to hedge. Limits: total DV01, and slope exposure.",
                     mkt, 10, limit, positions, regime, 5, "rfq", desk=desk, plans=plans)
    return build


def _draw_l3(variant: str):
    _, side_bias, _ = L3_VARIANTS[variant]

    def draw(rng: random.Random, s: Setup) -> Inquiry:
        types, weights = zip(*s.regime.client_mix)
        ctype = rng.choices(types, weights)[0]
        prefs = TENOR_PREFS[ctype]
        tenor = rng.choices(list(prefs), list(prefs.values()))[0]
        action = ClientAction.PAYS if rng.random() < side_bias.get(ctype, 0.5) else ClientAction.RECEIVES
        notional = _round_notional(rng.uniform(0.15, 0.45) * s.limit / unit_dv01(tenor, s.mkt) * 1e6)
        informed = rng.random() < CLIENT_TYPES[ctype].p_informed
        return Inquiry(ctype, action, notional, informed, tenor=tenor)
    return draw


def _l3_policies():
    from .episode import reference_decision
    from .state import HedgeDecision

    def level_10y(ep, obs):
        if obs.kind in ("hedge", "position", "overnight", "rehedge"):
            tr = obs.ctx.hedge_trade_for(1.0, 10)
            return HedgeDecision((tr,) if tr else (), "Hedge the level in the 10Y")
        return reference_decision(ep, obs)

    def flatten(ep, obs):
        if obs.kind in ("hedge", "position", "overnight", "rehedge"):
            return obs.ctx.flatten_curve_hedge() or HedgeDecision((), "flat")
        return reference_decision(ep, obs)

    def never(ep, obs):
        return reference_decision(ep, obs, "none")

    return {"reference desk (model prices, mid-appetite hedge)": lambda ep, obs: reference_decision(ep, obs),
            "model prices, hedge the level in the 10Y only": level_10y,
            "model prices, flatten level and curve every round": flatten,
            "model prices, never hedge": never}


for _v in ("ldi", "corporate"):
    register_episode(EpisodeSpec(f"mm.ep3_curve_book_{_v}", 3, "risk.key_rate",
                                 f"The curve book ({_v}): price by whole-book risk, hedge where it matters", _build_l3(_v), _draw_l3(_v),
                                 policies=_l3_policies()))


# ============================================================================================ level 4: products and the overnight

from ..engine.futures import BOBL, BUND, calibrated, conversion_factor  # noqa: E402
from ..questions.market import bond_label, random_futures  # noqa: E402
from .factors import CURVE_FACTORS, SPREAD_FACTORS  # noqa: E402
from .products import SpreadMarket  # noqa: E402
from .state import Product  # noqa: E402

FUT_HALF_TICK = 0.005       # half the futures bid/offer, price points (the Bund trades a tick wide)
LATE_SWAP_COST = 2.0        # late in the day swaps cost about 2x their usual spread to trade (training assumption)
LATE_DEPTH = 0.25           # ... and the late swap market absorbs about a quarter of your limit in DV01 before impact doubles the cost
BOND_HALF = 0.01            # half the CTD's bid/offer, price points per 100 face


def _no_coupon_soon(bond, anchor, days: int = 6) -> bool:
    from datetime import timedelta
    return not any(anchor < p.pay <= anchor + timedelta(days=days) for p in bond.periods)


def _build_l4(rng: random.Random) -> Setup:
    for _ in range(200):
        mkt0 = random_market(rng)
        try:
            bund = random_futures(rng, mkt0, spec=BUND, min_gap=0.08)
            bobl = random_futures(rng, mkt0, spec=BOBL, min_gap=0.08)
        except RuntimeError:
            continue
        ci = bund.ctd_index()
        ctd = bund.fut.basket[ci]
        if all(_no_coupon_soon(b, mkt0.anchor) for c in (bund, bobl) for b in c.fut.basket):
            break
    else:  # pragma: no cover
        raise RuntimeError("could not draw a futures market without coupons over the overnight")
    special = rng.random() < 0.4
    if special:                                      # the CTD goes special: cheaper to own, dearer to short
        sp = rng.choice([0.0020, 0.0030, 0.0040])
        new_ctd = _replace(ctd, funding_spread=ctd.funding_spread - sp)
        basket = tuple(new_ctd if k == ci else b for k, b in enumerate(bund.fut.basket))
        fgbl = calibrated(BUND, bund.delivery, basket, mkt0, bund.price)
        ctd = new_ctd
    else:
        fgbl = bund.fut
    fgbm = bobl.fut
    mkt = SpreadMarket(mkt0)
    tenor = rng.choices([10, 5, 30], [5, 3, 2])[0]
    limit = rng.choice([300e3, 500e3])
    gc_bp = ctd.funding_spread * 1e4
    repo_text = (f"Repo SPECIAL at ESTR {gc_bp:+.0f}bp: cheap to own, expensive to be short" if special
                 else f"Repo at general collateral, ESTR {gc_bp:+.0f}bp")
    cf = conversion_factor(ctd.coupon, ctd.maturity, bund.delivery)
    products = (
        Product("FGBL", "future", "Bund future (FGBL)", fgbl, FUT_HALF_TICK, f"CTD {bond_label(ctd)}, CF {cf:.4f}."),
        Product("FGBM", "future", "Bobl future (FGBM)", fgbm, FUT_HALF_TICK, f"CTD {bond_label(bobl.fut.basket[bobl.ctd_index()])}."),
        Product("CTD", "bond", f"the {bond_label(ctd)} Bund (Bund CTD)", ctd, BOND_HALF, repo_text + "."),
    )
    if tenor == 5:                                   # the matching future first: it is the natural hedge (and the checkpoint's contract)
        products = (products[1], products[0], products[2])
    desk = Desk(CURVE_TENORS, Limits(limit, limit), products, CURVE_FACTORS + SPREAD_FACTORS, multi_tenor=True)
    dv_pm = unit_dv01(tenor, mkt0)
    frac = rng.choice([-0.6, -0.45, 0.45, 0.6])
    n = _round_notional(abs(frac) * limit / dv_pm * 1e6)
    rate = mkt0.par_irs_rate(12 * tenor) + rng.uniform(-1.0, 1.0) * BP
    positions = (Position(IRSwap.new(Side.RECEIVE if frac > 0 else Side.PAY, n, round(rate, 6), mkt0.spot, 12 * tenor),
                          "client", "client at 15:30", -1),)
    mix = (("pension", 2), ("asset_manager", 3), ("bank_treasury", 2), ("macro_fund", 1))
    typical = 0.3 * limit / dv_pm * 1e6
    vol = rng.choice([0.6, 1.0, 1.0, 1.8])
    late = Regime(vol, Liquidity.NORMAL, mix, 0.5, 0.0625, "late afternoon: swap liquidity is thin, futures still trade tight.", typical,
                  swap_cost_mult=LATE_SWAP_COST, swap_depth_dv01=LATE_DEPTH * limit)
    morning = Regime(vol, Liquidity.DEEP, mix, 0.5, 0.125, "morning: the swap market is deep again.", typical)
    plans = (
        RoundPlan("rfq", "hedge", "intraday", "Day 1, 16:00", regime=late, checkpoint="futures_contracts"),
        RoundPlan("rfq", "hedge", "intraday", "Day 1, 16:30"),
        RoundPlan(None, "overnight", "overnight", "Day 1, close",
                  notes=("The close. Decide what you carry overnight: the next move is the overnight one, and carry, roll-down and funding accrue.",)),
        RoundPlan(None, "rehedge", "intraday", "Day 2, 08:30", regime=morning,
                  notes=("Morning: swap liquidity is back. Review the hedges you carried.",)),
        RoundPlan("rfq", "hedge", "intraday", "Day 2, 09:30"),
    )
    return Setup("Level 4: hedging with other products, and holding risk overnight",
                 f"It is late afternoon and you are carrying a {tenor}Y client position. Swaps are expensive to trade this late; futures are not. "
                 "A hedge is a trade: choose the product by its cost, the risk it leaves (swap spread, futures basis), what it carries overnight "
                 "and how long you will hold it.",
                 mkt, tenor, limit, positions, late, 5, "rfq", desk=desk, plans=plans)


def _draw_l4(rng: random.Random, s: Setup) -> Inquiry:
    types, weights = zip(*s.regime.client_mix)
    ctype = rng.choices(types, weights)[0]
    action = ClientAction.PAYS if rng.random() < 0.5 else ClientAction.RECEIVES
    notional = _round_notional(rng.uniform(0.15, 0.4) * s.limit / unit_dv01(s.tenor, s.mkt) * 1e6)
    return Inquiry(ctype, action, notional, rng.random() < CLIENT_TYPES[ctype].p_informed, tenor=s.tenor)


def _l4_policies():
    from .assess import _held_products, _switch_decision
    from .episode import reference_decision
    from .state import HedgeDecision

    def fut_code(ep):
        return next(p.code for p in ep.desk().products if p.kind == "future")

    def swaps_only(ep, obs):
        if obs.kind in ("hedge", "overnight", "rehedge"):
            tr = obs.ctx.hedge_trade_for(1.0, ep.setup.tenor)
            return HedgeDecision((tr,) if tr else (), "swaps")
        return reference_decision(ep, obs)

    def futures(keep: bool):
        def pol(ep, obs):
            if obs.kind == "rehedge" and not keep:
                held = _held_products(obs.ctx)
                if held:
                    return _switch_decision(obs.ctx, held)
            if obs.kind in ("hedge", "overnight", "rehedge"):
                tr = obs.ctx.product_trade_for(1.0, fut_code(ep))
                return HedgeDecision((tr,) if tr else (), "futures")
            return reference_decision(ep, obs)
        return pol

    return {"reference desk (model prices, mid-appetite hedge)": lambda ep, obs: reference_decision(ep, obs),
            "swaps only (pay the late-day spread)": swaps_only,
            "futures, switched into swaps next morning": futures(keep=False),
            "futures, kept": futures(keep=True),
            "never hedge": lambda ep, obs: reference_decision(ep, obs, "none")}


register_episode(EpisodeSpec("mm.ep4_products_overnight", 4, "mm.cross_product_hedging",
                             "Hedging with futures and bonds, and holding risk overnight", _build_l4, _draw_l4, policies=_l4_policies()))


# ============================================================================================ level 5: information, views and conditions

from .state import NamedClient, Signal  # noqa: E402

L5_NAMES = ("Halden Capital", "Orsay Partners", "Brennmoor AM", "Kestrel Fund", "Nordlicht Pensions")
L5_TYPES = ("macro_fund", "fast_money", "asset_manager", "macro_fund", "pension")


def _build_l5(rng: random.Random) -> Setup:
    mkt = random_market(rng)
    tenor = 10                                                    # the slope factor pivots on the 10Y: a 10Y view is a pure level view
    limit = rng.choice([300e3, 500e3])
    idx = rng.sample(range(len(L5_NAMES)), 3)                    # three named clients for four requests: at least one comes back
    clients = []
    for i in idx:
        ctype = L5_TYPES[i]
        clients.append(NamedClient(L5_NAMES[i], ctype, rng.random() < CLIENT_TYPES[ctype].p_informed))
    leans = {c.name: rng.choice(list(ClientAction)) for c in clients}  # each client has a direction today (it tends to repeat it)
    view = rng.choice([-4.0, -3.0, -2.0, 2.0, 3.0, 4.0])
    rel = rng.choice([0.3, 0.5, 0.7])
    signal = Signal(view, rel, f"we expect the {tenor}Y to {'RISE' if view > 0 else 'FALL'} about {abs(view):.0f}bp over the session. "
                               f"About {rel:.0%} of this desk's calls have carried real information (the rest were noise).")
    vol = rng.choice([0.6, 1.0, 1.0])
    mix = tuple((c.ctype, 1) for c in clients)
    typical = 0.3 * limit / unit_dv01(tenor, mkt) * 1e6
    regime = Regime(vol, Liquidity.NORMAL, mix, 0.5, 0.125, "named accounts are active; some will come back.", typical)
    thin = _replace(regime, liquidity=Liquidity.THIN, flow_text="late: liquidity is draining.")
    cut = Limits(round(limit * 2 / 3, -4), round(0.5 * limit * 2 / 3, -4))
    plans = (
        RoundPlan("quote", "hedge", "intraday", "Morning"),
        RoundPlan("rfq", "position", "event", "Before the release", vol_mult=3.0,
                  notes=("The data release lands in the next step. Decide what risk you want to run through it.",)),
        RoundPlan("rfq", "hedge", "intraday", "After the release"),
        RoundPlan("rfq", "hedge", "intraday", "Late: the risk manager cuts your limits", regime=thin, limits=cut,
                  notes=(f"Risk management cuts your limits to {cut.dv01 / 1e3:,.0f}k DV01 and {cut.slope / 1e3:,.0f}k slope for the rest of the day. "
                         "Liquidity is draining.",)),
    )
    positions = _initial_inventory(rng, mkt, tenor, limit, rng.choice([-0.3, -0.15, 0.15, 0.3]))
    desk = Desk(CURVE_TENORS, Limits(limit, 0.5 * limit), multi_tenor=True)
    s = Setup("Level 5: information, views and changing conditions",
              "Three reasons move your price: your inventory, what a client may know, and your view. Keep them apart. You will see named "
              "clients come back, a research view with a stated track record, a data release, and a limit cut.",
              mkt, tenor, limit, positions, regime, 4, "rfq", desk=desk, plans=plans, signal=signal, clients=tuple(clients), many_paths=True,
              _leans=leans)
    return s


def _draw_l5(rng: random.Random, s: Setup) -> Inquiry:
    c = rng.choice(s.clients)
    lean = s._leans[c.name]
    action = lean if rng.random() < 0.8 else lean.opposite
    notional = _round_notional(rng.uniform(0.15, 0.4) * s.limit / unit_dv01(s.tenor, s.mkt) * 1e6)
    return Inquiry(c.ctype, action, notional, c.informed, tenor=s.tenor, name=c.name)


def _l5_policies():
    from .assess import DecisionContext, best_alternative
    from .episode import reference_decision
    from .state import HedgeDecision, HedgeTrade

    def ctx_with(ep, obs, **changes):
        i = _replace(obs.ctx.info, **changes)
        return DecisionContext(ep.mkt, ep.positions, ep.limits.dv01, ep.regime, ep.inquiry_tenor(), obs.ctx.client, desk=ep.desk(),
                               info=i, home=ep.setup.tenor)

    def ignore_view(ep, obs):
        return reference_decision(ep, obs, ctx=ctx_with(ep, obs, view_bp=0.0, reliability=0.0, signal_drift_bp=0.0))

    def ignore_evidence(ep, obs):
        return reference_decision(ep, obs, ctx=ctx_with(ep, obs, posterior=None))

    def follow_view(ep, obs):
        if obs.kind == "position":
            ctx = obs.ctx
            target = (-0.9 if ep.setup.signal.view_bp > 0 else 0.9) * ctx.limit       # view: rates up -> be short duration
            change = target - ctx.dv01
            return HedgeDecision((HedgeTrade(ctx.tenor, Side.RECEIVE if change > 0 else Side.PAY, abs(change) / ctx.dv01_per_m(ctx.tenor) * 1e6),),
                                 "follow the view")
        return reference_decision(ep, obs)

    def never(ep, obs):
        if obs.kind in ("hedge", "position"):
            limit_fix = abs(obs.ctx.dv01) > obs.ctx.limit
            return best_alternative(obs.ctx) if limit_fix else HedgeDecision((), "keep")
        return reference_decision(ep, obs)

    return {"reference desk (all three drivers, mid-appetite)": lambda ep, obs: reference_decision(ep, obs),
            "ignore the research view": ignore_view,
            "follow the view fully into the release": follow_view,
            "ignore the evidence on clients (type priors only)": ignore_evidence,
            "never hedge unless over a limit": never}


register_episode(EpisodeSpec("mm.ep5_information_views", 5, "mm.views_and_events",
                             "Information, views and changing conditions: inventory, information and conviction kept apart",
                             _build_l5, _draw_l5, policies=_l5_policies()))
