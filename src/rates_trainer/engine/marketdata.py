"""MarketCurves: par quotes in, calibrated ESTR-OIS / 6M Euribor / 3M Euribor curves out.

Quote sets (rates as decimals, pillars in MONTHS):
    "OIS"        par ESTR OIS rates                      -> discount curve
    "E6M"        par IRS rates vs 6M Euribor             -> 6M projection curve (discounted on OIS)
    "BASIS_3S6S" par 3M+spread vs 6M spreads (optional)  -> 3M projection curve

Calibration reuses the real instruments: each pillar solves "instrument struck at its quote has PV 0"
by sequential 1-D root finds, so pricing and bootstrapping can never disagree. A bump of one quote
re-bootstraps everything downstream of it, exactly like a desk risk system.

Curves are built lazily (a OIS-only question never pays for the Euribor curves).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Callable, Mapping

from .curve import BP, Curve, CurveShock
from .dates import TARGET, Period, spot_date
from .instruments import BasisSwap, IRSwap, Instrument, OISSwap, Side
from .numerics import find_root

OIS_PILLARS = (3, 6, 12, 24, 36, 48, 60, 84, 120, 180, 240, 360)
IBOR_PILLARS = (6, 12, 24, 36, 48, 60, 84, 120, 180, 240, 360)
PILLARS = {"OIS": OIS_PILLARS, "E6M": IBOR_PILLARS, "BASIS_3S6S": IBOR_PILLARS}
DEFAULT_SHOCK_CURVES = ("OIS", "E6M")   # a "rates move" shifts both; basis spreads stay put


class _View:
    """What an instrument sees while a curve is being solved."""

    def __init__(self, ois: Curve, projections: dict[str, Curve]):
        self.ois = ois
        self.anchor = ois.anchor
        self._p = projections

    def fixing(self, index: str, period: Period) -> float:
        raise ValueError("calibration instruments start at the anchor: no fixings needed")

    def ois_growth(self, start: date) -> float:
        raise ValueError("calibration instruments start at the anchor: no realised compounding needed")

    def projection(self, index: str) -> Curve:
        return self._p[index]


def _bootstrap(anchor: date, pillars: tuple[int, ...], make_inst: Callable[[int], Instrument],
               view: Callable[[Curve], _View]) -> Curve:
    dates: list[date] = []
    values: list[float] = []
    for m in pillars:
        inst = make_inst(m)
        node = inst.maturity
        t_prev = (dates[-1] - anchor).days if dates else 0
        base = values[-1] if values else 1.0
        guess = base * math.exp(-0.03 * ((node - anchor).days - t_prev) / 365.0)

        def f(x: float, _node=node) -> float:
            return inst.pv(view(Curve(anchor, (*dates, _node), (*values, x))))

        lo, hi = guess * 0.9, guess * 1.1
        for _ in range(60):
            if f(lo) * f(hi) <= 0:
                break
            lo, hi = lo * 0.9, hi * 1.1
        else:
            raise ValueError(f"could not bracket a solution at {m}M: quotes inconsistent")
        x = find_root(f, lo, hi, tol=1e-15)
        dates.append(node)
        values.append(x)
    return Curve(anchor, tuple(dates), tuple(values))


class MarketCurves:
    def __init__(self, trade_date: date, quotes: Mapping[str, Mapping[int, float]], *,
                 _built: dict[str, Curve] | None = None, history: "MarketCurves | None" = None,
                 fixings: Mapping[str, Mapping[date, float]] | None = None):
        self.trade_date = trade_date
        self.history = history          # the market this one was rolled from: source of past fixings
        self.fixings = {k: dict(v) for k, v in (fixings or {}).items()}   # explicit: {index: {period start: rate}}
        self.spot = spot_date(trade_date)
        self.anchor = self.spot   # all PVs are as at spot; the T+2 gap is ignored
        self.quotes: dict[str, dict[int, float]] = {}
        for name, q in quotes.items():
            if name not in PILLARS:
                raise ValueError(f"unknown quote set {name!r}")
            if tuple(sorted(q)) != PILLARS[name]:
                raise ValueError(f"{name} needs pillars {PILLARS[name]} (months), got {tuple(sorted(q))}")
            lo, hi = (-0.005, 0.01) if name == "BASIS_3S6S" else (-0.02, 0.15)
            if any(not lo < r < hi for r in q.values()):
                raise ValueError(f"implausible {name} quote(s): {dict(q)}")
            self.quotes[name] = {m: float(q[m]) for m in sorted(q)}
        if "OIS" not in self.quotes or "E6M" not in self.quotes:
            raise ValueError("OIS and E6M quotes are required")
        self._built: dict[str, Curve] = dict(_built or {})

    # ----- curves (lazy) -----
    @property
    def ois(self) -> Curve:
        if "OIS" not in self._built:
            q = self.quotes["OIS"]
            self._built["OIS"] = _bootstrap(
                self.anchor, OIS_PILLARS,
                lambda m: OISSwap.new(Side.RECEIVE, 1.0, q[m], self.spot, m),
                lambda trial: _View(trial, {}))
        return self._built["OIS"]

    def projection(self, index: str) -> Curve:
        if index in self._built:
            return self._built[index]
        if index == "E6M":
            q, ois = self.quotes["E6M"], self.ois
            self._built[index] = _bootstrap(
                self.anchor, IBOR_PILLARS,
                lambda m: IRSwap.new(Side.RECEIVE, 1.0, q[m], self.spot, m),
                lambda trial: _View(ois, {"E6M": trial}))
        elif index == "E3M":
            if "BASIS_3S6S" not in self.quotes:
                raise KeyError("no BASIS_3S6S quotes: this market has no 3M curve")
            q, ois, e6m = self.quotes["BASIS_3S6S"], self.ois, self.projection("E6M")
            self._built[index] = _bootstrap(
                self.anchor, IBOR_PILLARS,
                lambda m: BasisSwap.new(Side.RECEIVE, 1.0, q[m], self.spot, m),
                lambda trial: _View(ois, {"E6M": e6m, "E3M": trial}))
        else:
            raise KeyError(f"unknown index {index!r}")
        return self._built[index]

    # ----- scenarios -----
    def bumped(self, curve: str, pillar_months: int, bp: float) -> "MarketCurves":
        """Move ONE quote by bp, re-bootstrapping only what depends on it."""
        quotes = {n: dict(q) for n, q in self.quotes.items()}
        quotes[curve][pillar_months] += bp * BP
        reuse = {"OIS": (), "E6M": ("OIS",), "BASIS_3S6S": ("OIS", "E6M")}[curve]
        return MarketCurves(self.trade_date, quotes, history=self.history, fixings=self.fixings,
                            _built={k: v for k, v in self._built.items() if k in reuse})

    def shifted(self, shock: CurveShock, curves: tuple[str, ...] = DEFAULT_SHOCK_CURVES) -> "MarketCurves":
        quotes = {n: dict(q) for n, q in self.quotes.items()}
        for name in curves:
            if name in quotes:
                for m in quotes[name]:
                    quotes[name][m] += shock.bp_at(m / 12.0) * BP
        return MarketCurves(self.trade_date, quotes, history=self.history, fixings=self.fixings)

    # ----- time -----
    def horizon_date(self, *, days: int = 0, months: int = 0) -> date:
        """The business day that is `days` calendar days / `months` months after spot."""
        from datetime import timedelta
        from .dates import add_months
        return TARGET.adjust(add_months(self.anchor, months) + timedelta(days=days))

    def rolled(self, new_anchor: date, mode: str) -> "MarketCurves":
        """This market seen from a later spot date.

        mode="static":  every par quote BY TENOR is unchanged (the curve does not move, so the position
                        rolls down it). Forwards change.
        mode="forward": the forward curve is unchanged (forwards are realised). Quotes are the implied par rates.
        Past fixings and realised ESTR compounding are looked up in `self` via `history`.
        """
        if new_anchor <= self.anchor:
            raise ValueError("can only roll forward in time")
        if not TARGET.is_business_day(new_anchor):
            raise ValueError("the new anchor must be a TARGET business day")
        trade_date = TARGET.add_business_days(new_anchor, -2)
        if mode == "static":
            out = MarketCurves(trade_date, self.quotes, history=self, fixings=self.fixings)
        elif mode == "forward":
            built = {"OIS": self.ois.reanchored(new_anchor), "E6M": self.projection("E6M").reanchored(new_anchor)}
            if "BASIS_3S6S" in self.quotes:
                built["E3M"] = self.projection("E3M").reanchored(new_anchor)
            tmp = MarketCurves(trade_date, self.quotes, _built=built, history=self, fixings=self.fixings)
            implied = {
                "OIS": {m: tmp.par_ois_rate(m) for m in OIS_PILLARS},
                "E6M": {m: tmp.par_irs_rate(m) for m in IBOR_PILLARS},
            }
            if "BASIS_3S6S" in self.quotes:
                implied["BASIS_3S6S"] = {m: BasisSwap.new(Side.RECEIVE, 1.0, 0.0, tmp.spot, m).par_spread(tmp)
                                         for m in IBOR_PILLARS}
            out = MarketCurves(trade_date, implied, _built=built, history=self, fixings=self.fixings)
        else:
            raise ValueError("mode must be 'static' or 'forward'")
        assert out.anchor == new_anchor
        return out

    def fixing(self, index: str, period: Period) -> float:
        """The rate set at the START of a period that began before this market's anchor."""
        explicit = self.fixings.get(index, {}).get(period.start)
        if explicit is not None:
            return explicit
        if self.history is None:
            raise ValueError(f"{index} period starting {period.start} began before the valuation date "
                             "and no fixing is available")
        h = self.history
        if period.start >= h.anchor:
            return h.projection(index).forward_rate(period.start, period.end)
        return h.fixing(index, period)

    def ois_growth(self, start: date) -> float:
        """Compounded ESTR growth realised from `start` to this market's anchor (forwards-realised assumption)."""
        if self.history is None:
            raise ValueError("no history: cannot know realised ESTR compounding")
        h = self.history
        if start >= h.anchor:
            return h.ois.df(start) / h.ois.df(self.anchor)
        return h.ois_growth(start) / h.ois.df(self.anchor)

    # ----- par rates -----
    def par_irs_rate(self, tenor_months: int, start_months: int = 0) -> float:
        return IRSwap.new(Side.RECEIVE, 1.0, 0.0, self.spot, tenor_months, start_months).par_rate(self)

    def par_ois_rate(self, tenor_months: int, start_months: int = 0) -> float:
        return OISSwap.new(Side.RECEIVE, 1.0, 0.0, self.spot, tenor_months, start_months).par_rate(self)

    def bond_basis_swap_rate(self, maturity_years: int) -> float:
        """The OIS curve's par yield on a bond basis: the annual rate K (accrual 1.0, as a government coupon) that makes
        a bond paying K and par at maturity worth par on the OIS curve. This is the rate to compare a bond YIELD with
        (OIS quotes are ACT/360, which sits ~1.4% lower in rate terms than an annual ACT/ACT yield)."""
        from .dates import make_schedule
        periods = make_schedule(self.spot, 0, 12 * maturity_years, 12)
        return (1.0 - self.ois.df(periods[-1].end)) / sum(self.ois.df(p.pay) for p in periods)

    def risk_keys(self, curves: tuple[str, ...] | None = None) -> list[tuple[str, int]]:
        return [(n, m) for n in (curves or tuple(self.quotes)) if n in self.quotes for m in self.quotes[n]]
