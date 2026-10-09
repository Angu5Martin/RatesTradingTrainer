import math
from datetime import date, timedelta

import pytest

from rates_trainer.engine.curve import Curve, CurveShock

A = date(2026, 10, 12)


def test_df_nodes_interpolation_extrapolation():
    n1, n2 = A + timedelta(days=365), A + timedelta(days=730)
    c = Curve(A, (n1, n2), (0.98, 0.95))
    assert c.df(A) == 1.0
    assert c.df(n1) == pytest.approx(0.98) and c.df(n2) == pytest.approx(0.95)
    mid = A + timedelta(days=365 + 182)           # 182 of 365 days into the second segment
    assert c.df(mid) == pytest.approx(math.exp(math.log(0.98) + (math.log(0.95) - math.log(0.98)) * 182 / 365))
    n3 = A + timedelta(days=1095)                  # extrapolation continues the last forward
    assert c.df(n3) == pytest.approx(0.95 * 0.95 / 0.98)
    # before the first node: constant zero rate from the anchor
    assert c.df(A + timedelta(days=182)) == pytest.approx(math.exp(math.log(0.98) * 182 / 365))
    with pytest.raises(ValueError):
        c.df(A - timedelta(days=1))


def test_forward_and_zero():
    n1, n2 = A + timedelta(days=360), A + timedelta(days=720)
    c = Curve(A, (n1, n2), (0.98, 0.95))
    assert c.forward_rate(n1, n2) == pytest.approx((0.98 / 0.95 - 1) / 1.0)      # 360 days = 1.0 ACT/360
    assert (1 + c.zero_rate(n2)) ** (720 / 365) == pytest.approx(1 / 0.95)


def test_reanchoring_preserves_forwards_exactly():
    nodes = tuple(A + timedelta(days=d) for d in (91, 365, 1000, 3650))
    c = Curve(A, nodes, (0.995, 0.98, 0.93, 0.74))
    new = A + timedelta(days=200)
    r = c.reanchored(new)
    a, b = A + timedelta(days=500), A + timedelta(days=900)
    assert r.forward_rate(a, b) == pytest.approx(c.forward_rate(a, b), rel=1e-12)
    assert r.df(b) == pytest.approx(c.df(b) / c.df(new), rel=1e-12)
    assert r.df(new) == 1.0


def test_validation():
    with pytest.raises(ValueError):
        Curve(A, (A,), (1.0,))
    with pytest.raises(ValueError):
        Curve(A, (A + timedelta(days=5), A + timedelta(days=3)), (0.9, 0.8))
    with pytest.raises(ValueError):
        Curve(A, (A + timedelta(days=5),), (-0.9,))


def test_shock_interpolation():
    s = CurveShock.points({2: -5, 10: 3})
    assert s.bp_at(1) == -5 and s.bp_at(2) == -5
    assert s.bp_at(6) == pytest.approx(-1.0)
    assert s.bp_at(30) == 3
    p = CurveShock.parallel(4)
    assert p.bp_at(0.25) == 4 == p.bp_at(30)
