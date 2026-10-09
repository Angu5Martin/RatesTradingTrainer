from datetime import date

import pytest

from rates_trainer.engine.marketdata import MarketCurves

TRADE_DATE = date(2026, 10, 8)   # a Thursday; spot is Monday 12 Oct 2026

OIS = {3: .0195, 6: .0197, 12: .0200, 24: .0210, 36: .0220, 48: .0232, 60: .0242, 84: .0260,
       120: .0278, 180: .0292, 240: .0290, 360: .0272}
E6M = {6: .0215, 12: .0212, 24: .0221, 36: .0231, 48: .0242, 60: .0252, 84: .0269,
       120: .02845, 180: .0297, 240: .0294, 360: .0277}
BASIS = {6: .0003, 12: .0004, 24: .0005, 36: .0006, 48: .0006, 60: .0006, 84: .0006,
         120: .0006, 180: .0005, 240: .0005, 360: .0004}


def make_market(trade_date: date = TRADE_DATE, basis: bool = True) -> MarketCurves:
    q = {"OIS": OIS, "E6M": E6M}
    if basis:
        q["BASIS_3S6S"] = BASIS
    return MarketCurves(trade_date, q)


@pytest.fixture(scope="session")
def mkt() -> MarketCurves:
    """A realistic EUR market: upward-sloping, IRS ~10-15bp over OIS, positive 3s6s basis."""
    return make_market()


@pytest.fixture(autouse=True)
def _private_data_home(tmp_path_factory, monkeypatch):
    """No test may read or write the real trainer data (~/.rates_trainer): every test gets its own empty home unless it sets one itself."""
    monkeypatch.setenv("RATES_TRAINER_HOME", str(tmp_path_factory.mktemp("trainer-home")))
