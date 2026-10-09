import random

from rates_trainer.questions.market import random_market


def test_random_markets_are_valid_and_realistic():
    for seed in range(120):
        m = random_market(random.Random(seed))
        assert all(0.01 < r < 0.045 for r in m.quotes["OIS"].values())
        assert all(0.0001 < m.quotes["E6M"][k] - m.par_ois_rate(k) < 0.0030 for k in (12, 60, 120))   # IRS over OIS
        assert all(0.0001 < b < 0.0012 for b in m.quotes["BASIS_3S6S"].values())
        for name, q in m.quotes.items():
            if name == "OIS":
                for k, r in q.items():
                    assert abs(m.par_ois_rate(k) - r) < 1e-10
        for k, r in m.quotes["E6M"].items():
            assert abs(m.par_irs_rate(k) - r) < 1e-10
        ois = m.ois
        assert all(0 < ois.df(d) < 1 for d in ois.dates)
