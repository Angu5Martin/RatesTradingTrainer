"""Level 4: the spread overlay, product hedges and their residual risk, the overnight (carry, roll-down, funding), sessions and switching."""

from dataclasses import replace

import pytest

from rates_trainer.engine.carry import financing_cost
from rates_trainer.engine.instruments import IRSwap, Side
from rates_trainer.engine.risk import unit_dv01
from rates_trainer.episodes.assess import DecisionContext, Info, _held_products, _switch_decision, assess_hedge
from rates_trainer.episodes.decisions import parse_hedge
from rates_trainer.episodes.episode import Episode, reference_decision, run_policy
from rates_trainer.episodes.factors import apply_moves
from rates_trainer.episodes.products import BondPosition, FuturePosition, SpreadMarket
from rates_trainer.episodes.state import FuturesTrade, HedgeDecision, Position, Rating, book

L4 = "mm.ep4_products_overnight"


@pytest.fixture(scope="module")
def setup():
    return Episode(L4, 3, render=False).setup


def _ctx(setup, positions, regime=None, info=None):
    return DecisionContext(setup.mkt, positions, setup.limit, regime or setup.regime, setup.tenor, desk=setup.desk, info=info,
                           home=setup.tenor)


def _client(setup, dv01):
    m = setup.mkt
    t = setup.tenor
    return (Position(IRSwap.new(Side.RECEIVE if dv01 > 0 else Side.PAY, abs(dv01) / unit_dv01(t, m.curves) * 1e6, m.par_irs_rate(12 * t),
                                m.spot, 12 * t), "client", "c", -1),)


def test_spread_market_behaves_like_the_curves_and_keeps_its_overlay(setup):
    m = setup.mkt.with_spread("asw", 0.0003)
    assert isinstance(m, SpreadMarket) and m.spreads["asw"] == pytest.approx(0.0003)
    assert m.quotes == setup.mkt.quotes and m.anchor == setup.mkt.anchor
    moved = apply_moves(m, {"level": 2.0, "swap_spread": 1.0})
    assert isinstance(moved, SpreadMarket) and moved.spreads["asw"] == pytest.approx(0.0004)
    rolled = m.rolled(m.horizon_date(days=1), "static")
    assert isinstance(rolled, SpreadMarket) and rolled.spreads == m.spreads


def test_bond_and_future_positions_reprice_with_the_overlay(setup):
    bond = setup.desk.product("CTD").obj
    pos = BondPosition(bond, 10e6)
    m = setup.mkt
    base = pos.pv(m)
    assert base == pytest.approx(bond.pv(m) / 100 * 10e6, rel=1e-12)                       # zero overlay = the printed bond
    wider = pos.pv(m.with_spread("asw", 1e-4))
    assert wider < base and base - wider == pytest.approx(10e6 * bond.spread_annuity(m) * 1e-4, rel=1e-9)   # cheapens by A x 1bp
    fut = FuturePosition(setup.desk.product("FGBL").obj, 100, "FGBL")
    assert fut.price(m.with_spread("asw", 1e-4)) < fut.price(m)                             # bonds cheapen -> the future falls
    assert fut.price(m.with_spread("fut", 0.01)) == pytest.approx(fut.price(m) - 0.01)      # +1 tick of basis = 1 tick cheaper


def test_a_futures_hedge_removes_the_level_and_leaves_exactly_swap_spread_risk(setup):
    ctx = _ctx(setup, _client(setup, 0.5 * setup.limit))
    code = next(p.code for p in setup.desk.products if p.kind == "future")
    d = HedgeDecision((ctx.product_trade_for(1.0, code),))
    x, _ = ctx.after(d)
    assert abs(x["level"]) < 0.01 * ctx.limit
    assert x["swap_spread"] < -0.5 * abs(ctx.dv01)                     # short futures against a receiver: loses if bonds richen
    a = assess_hedge(ctx, d)
    assert any("swap-spread risk" in r for r in a.reasons)
    # with a swap hedge instead there is no spread risk at all
    xs, _ = ctx.after(HedgeDecision((ctx.hedge_trade_for(1.0, setup.tenor),)))
    assert abs(xs["swap_spread"]) < 1.0


def test_wrong_way_futures_hedge_is_an_error(setup):
    ctx = _ctx(setup, _client(setup, 0.5 * setup.limit))
    code = next(p.code for p in setup.desk.products if p.kind == "future")
    good = ctx.product_trade_for(1.0, code)
    bad = HedgeDecision((FuturesTrade(code, -good.contracts),))
    assert good.contracts < 0 and assess_hedge(ctx, bad).rating is Rating.ERROR


def test_late_session_size_makes_futures_competitive_and_the_morning_does_not(setup):
    """Late: swap cost x2 and impact over a shallow depth. A large hedge is cheaper in futures; in the deep morning swaps win back."""
    late = replace(setup.regime, swap_cost_mult=2.0, swap_depth_dv01=0.25 * setup.limit)
    morning = replace(setup.regime, swap_cost_mult=1.0, swap_depth_dv01=None)
    code = next(p.code for p in setup.desk.products if p.kind == "future")
    for regime, futures_cheaper in ((late, True), (morning, False)):
        ctx = _ctx(setup, _client(setup, 0.6 * setup.limit), regime)
        _, c_swap = ctx.after(HedgeDecision((ctx.hedge_trade_for(1.0, setup.tenor),)))
        _, c_fut = ctx.after(HedgeDecision((ctx.product_trade_for(1.0, code),)))
        assert (c_fut < c_swap) == futures_cheaper


def test_switch_closes_products_and_restores_a_pure_swap_hedge(setup):
    ctx0 = _ctx(setup, _client(setup, 0.5 * setup.limit))
    code = next(p.code for p in setup.desk.products if p.kind == "future")
    tr = ctx0.product_trade_for(1.0, code)
    held = _client(setup, 0.5 * setup.limit) + (Position(ctx0.product_position(code, tr.contracts), "hedge", "h", 0),)
    ctx = _ctx(setup, held)
    assert _held_products(ctx) == {code: pytest.approx(tr.contracts)}
    x, _ = ctx.after(_switch_decision(ctx, _held_products(ctx)))
    assert abs(x["swap_spread"]) < 1.0 and abs(x["fut_basis"]) < 1.0 and abs(x["level"]) < 0.01 * ctx.limit
    assert parse_hedge("switch", ctx).label.startswith("Switch")


def test_overnight_time_includes_repo_and_specialness_matters(setup):
    bond = setup.desk.product("CTD").obj
    m = setup.mkt
    nxt = m.horizon_date(days=1)
    info = Info(dt=0.5, overnight_to=nxt)
    for face in (50e6, -50e6):
        gc = BondPosition(replace(bond, funding_spread=0.0), face)
        sp = BondPosition(replace(bond, funding_spread=-0.004), face)
        ctx = _ctx(setup, (Position(gc, "hedge", "b", 0),), info=info)
        t_gc = ctx.time_pnl()
        ctx_sp = _ctx(setup, (Position(sp, "hedge", "b", 0),), info=info)
        t_sp = ctx_sp.time_pnl()
        fund = financing_cost(gc.materialise(m), m, nxt)
        assert (fund > 0) == (face > 0)                                  # a long pays repo, a short earns it
        # special repo: cheaper to own (long better off), and the short earns less on its cash (worse off)
        assert (t_sp > t_gc) == (face > 0)


def test_the_overnight_round_books_carry_and_the_screen_shows_it_first():
    ep = Episode(L4, 2)
    seen_report = False
    while not ep.done:
        obs = ep.observe()
        if obs.kind == "overnight":
            assert "carry report" in "\n".join(obs.lines)
            seen_report = True
        ep.submit(reference_decision(ep, obs))
    assert seen_report
    causes = {e.cause for e in ep.ledger if e.round == 2}
    assert any(c.startswith("time:") for c in causes)
    assert ep.mkt.anchor > ep.setup.mkt.anchor                            # a business day later


def test_futures_contracts_checkpoint(setup):
    ep = Episode(L4, 3)
    ep.submit(reference_decision(ep, ep.observe()))                       # the request
    obs = ep.observe()
    assert obs.kind == "checkpoint"
    per = obs.ctx.unit_product(next(p.code for p in ep.desk().products if p.kind == "future"))["level"]
    assert obs.part.answer == pytest.approx(-obs.ctx.dv01 / per)


def test_parsing_products(setup):
    ctx = _ctx(setup, _client(setup, 0.5 * setup.limit))
    assert parse_hedge("sell 300 fgbl", ctx).trades == (FuturesTrade("FGBL", -300.0),)
    b = parse_hedge("buy 50m ctd", ctx).trades[0]
    assert b.face == 50e6
    two = parse_hedge("sell 200 fgbm + pay 100m 10y", ctx).trades
    assert len(two) == 2
    for bad in ("sell 300 fgbx", "switch"):
        with pytest.raises((ValueError, KeyError)):
            parse_hedge(bad, ctx)


def test_keeping_a_futures_hedge_carries_spread_pnl_that_a_swap_hedge_does_not():
    pols = Episode(L4, 0, render=False).policies()
    spread_kept = spread_swaps = 0.0
    for seed in range(4):
        kept = run_policy(L4, seed, pols["futures, kept"])
        swaps = run_policy(L4, seed, pols["swaps only (pay the late-day spread)"])
        spread_kept += sum(abs(e.amount) for e in kept.ledger if e.cause == "market: swap_spread")
        spread_swaps += sum(abs(e.amount) for e in swaps.ledger if e.cause == "market: swap_spread")
    assert spread_kept > 10 * max(1.0, spread_swaps)
