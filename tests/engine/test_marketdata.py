import pytest

from rates_trainer.engine.curve import CurveShock
from rates_trainer.engine.dates import DayCount
from rates_trainer.engine.instruments import BasisSwap, IRSwap, OISSwap, Side
from rates_trainer.engine.marketdata import IBOR_PILLARS, OIS_PILLARS, MarketCurves, _View

from ..conftest import BASIS, E6M, OIS, TRADE_DATE, make_market


def test_bootstrap_reprices_every_input_quote(mkt):
    for m, q in OIS.items():
        assert OISSwap.new(Side.RECEIVE, 1.0, q, mkt.spot, m).pv(mkt) == pytest.approx(0, abs=1e-12)
    for m, q in E6M.items():
        assert IRSwap.new(Side.RECEIVE, 1.0, q, mkt.spot, m).pv(mkt) == pytest.approx(0, abs=1e-12)
    for m, q in BASIS.items():
        assert BasisSwap.new(Side.RECEIVE, 1.0, q, mkt.spot, m).pv(mkt) == pytest.approx(0, abs=1e-12)


def test_ois_par_rate_matches_hand_written_formula(mkt):
    """Independent of OISSwap: S = (1 - DF(T)) / sum(ACT/360 x DF(pay)) for a spot-start OIS."""
    swap = OISSwap.new(Side.RECEIVE, 1.0, 0.0, mkt.spot, 120)
    disc = mkt.ois
    annuity = sum((p.end - p.start).days / 360 * disc.df(p.end) for p in swap.periods)
    assert (1 - disc.df(swap.periods[-1].end)) / annuity == pytest.approx(OIS[120], abs=1e-12)


def test_irs_par_rate_matches_hand_written_formula(mkt):
    """Independent of IRSwap: fixed 30E/360 annual vs 6M ACT/360 float projected on E6M, discounted on OIS."""
    swap = IRSwap.new(Side.RECEIVE, 1.0, 0.0, mkt.spot, 60)
    disc, proj = mkt.ois, mkt.projection("E6M")
    fixed = sum(DayCount.THIRTY_E_360.fraction(p.start, p.end) * disc.df(p.pay) for p in swap.fixed_periods)
    flt = 0.0
    for p in swap.float_periods:
        tau = (p.end - p.start).days / 360
        fwd = (proj.df(p.start) / proj.df(p.end) - 1) / tau
        flt += tau * fwd * disc.df(p.pay)
    assert flt / fixed == pytest.approx(E6M[60], abs=1e-12)


def test_float_leg_telescopes_when_projection_equals_discount(mkt):
    """With a single curve the float leg of a spot-start swap is exactly DF(0) - DF(T)."""
    swap = IRSwap.new(Side.RECEIVE, 1.0, 0.0, mkt.spot, 84)
    single = _View(mkt.ois, {"E6M": mkt.ois})
    assert swap.float_leg_pv(single) == pytest.approx(1 - mkt.ois.df(swap.maturity), abs=1e-13)


def test_multicurve_effects(mkt):
    assert mkt.par_irs_rate(120) > mkt.par_ois_rate(120)             # Euribor swaps pay over ESTR
    end = mkt.ois.dates[-1]
    assert mkt.projection("E6M").df(end) != pytest.approx(mkt.ois.df(end), rel=1e-3)


def test_zero_basis_gives_nearly_identical_3m_and_6m_curves_but_not_exactly():
    """Zero spread does NOT mean P3 = P6: two compounded 3M simple forwards differ slightly from one 6M simple
    forward. The gap is a compounding effect of a few ppm of discount factor, not a bug."""
    flat = MarketCurves(TRADE_DATE, {"OIS": OIS, "E6M": E6M, "BASIS_3S6S": {k: 0.0 for k in BASIS}})
    e3, e6 = flat.projection("E3M"), flat.projection("E6M")
    diffs = [abs(e3.df(d) / e6.df(d) - 1) for d in e6.dates]
    assert max(diffs) < 5e-4 and max(diffs) > 1e-9
    for m, q in flat.quotes["BASIS_3S6S"].items():     # ...and the zero-spread basis swaps still reprice exactly
        assert BasisSwap.new(Side.RECEIVE, 1.0, q, flat.spot, m).pv(flat) == pytest.approx(0, abs=1e-12)


def test_positive_basis_pushes_3m_forwards_below_6m_curve_forwards(mkt):
    """3M + spread must equal 6M, so the 3M fixing is LOWER than the 6M one by about the spread."""
    e3, e6 = mkt.projection("E3M"), mkt.projection("E6M")
    a, b = mkt.spot, mkt.projection("E6M").dates[2]    # 0 -> 2Y window, forwards over 3M from E3M vs from E6M
    from rates_trainer.engine.dates import add_months
    s, e = add_months(mkt.spot, 24), add_months(mkt.spot, 27)
    f3, f6 = e3.forward_rate(s, e), e6.forward_rate(s, e)
    assert f3 < f6 and (f6 - f3) == pytest.approx(0.0005, abs=0.0004)


def test_forward_start_swaps_are_additive_with_spot_swaps(mkt):
    """S(0,10) A(0,10) = S(0,5) A(0,5) + S(5,10) A(5,10): fixed and float legs both add up."""
    def swap(t, s=0):
        return IRSwap.new(Side.RECEIVE, 1.0, 0.0, mkt.spot, t, s)
    s10, s5, s5y5y = swap(120), swap(60), swap(60, 60)
    lhs = s10.par_rate(mkt) * s10.annuity(mkt)
    rhs = s5.par_rate(mkt) * s5.annuity(mkt) + s5y5y.par_rate(mkt) * s5y5y.annuity(mkt)
    assert lhs == pytest.approx(rhs, rel=1e-12)
    assert s5y5y.par_rate(mkt) > s10.par_rate(mkt) > s5.par_rate(mkt)       # upward-sloping part of the curve


def test_calendar_dependence_is_small_but_real():
    a, b = make_market(TRADE_DATE), make_market(TRADE_DATE.replace(month=2, day=11))
    assert a.spot != b.spot
    assert a.par_irs_rate(120) == pytest.approx(b.par_irs_rate(120), abs=2e-5)    # < 0.2bp from schedule noise


def test_lazy_build_and_missing_basis():
    m = MarketCurves(TRADE_DATE, {"OIS": OIS, "E6M": E6M})
    assert m._built == {}
    m.par_ois_rate(12)
    assert set(m._built) == {"OIS"}
    with pytest.raises(KeyError):
        m.projection("E3M")


def test_bump_reuses_unaffected_curves(mkt):
    ois = mkt.ois
    b = mkt.bumped("E6M", 120, 1.0)
    assert b._built.get("OIS") is ois and "E6M" not in b._built
    assert mkt.bumped("OIS", 120, 1.0)._built == {}
    assert b.quotes["E6M"][120] == pytest.approx(E6M[120] + 1e-4)
    assert mkt.quotes["E6M"][120] == E6M[120]                         # original untouched


def test_shift_moves_both_rate_curves_but_not_basis(mkt):
    s = mkt.shifted(CurveShock.parallel(5))
    assert s.quotes["OIS"][120] == pytest.approx(OIS[120] + 5e-4)
    assert s.quotes["E6M"][120] == pytest.approx(E6M[120] + 5e-4)
    assert s.quotes["BASIS_3S6S"][120] == BASIS[120]
    only_e6m = mkt.shifted(CurveShock.parallel(5), ("E6M",))
    assert only_e6m.quotes["OIS"][120] == OIS[120]


def test_input_validation():
    with pytest.raises(ValueError):
        MarketCurves(TRADE_DATE, {"OIS": {12: 0.02}, "E6M": E6M})                 # wrong pillars
    with pytest.raises(ValueError):
        MarketCurves(TRADE_DATE, {"OIS": {**OIS, 120: 0.5}, "E6M": E6M})           # implausible
    with pytest.raises(ValueError):
        MarketCurves(TRADE_DATE, {"OIS": OIS})                                    # needs E6M
    with pytest.raises(ValueError):
        MarketCurves(TRADE_DATE, {"OIS": OIS, "E6M": E6M, "FOO": E6M})


def test_pillar_sets():
    assert OIS_PILLARS == tuple(sorted(OIS)) and IBOR_PILLARS == tuple(sorted(E6M))
