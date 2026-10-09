from datetime import date

import pytest

from rates_trainer.engine.dates import (
    BDC, TARGET, DayCount, add_months, easter_sunday, make_schedule, spot_date,
)


@pytest.mark.parametrize("year,expected", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                           (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))])
def test_easter(year, expected):
    assert easter_sunday(year) == expected


def test_target_holidays_2026():
    closed = [date(2026, 1, 1), date(2026, 4, 3), date(2026, 4, 6), date(2026, 5, 1), date(2026, 12, 25)]
    assert not any(TARGET.is_business_day(d) for d in closed)
    assert TARGET.is_business_day(date(2026, 4, 7)) and TARGET.is_business_day(date(2026, 12, 24))
    assert not TARGET.is_business_day(date(2026, 10, 10))   # Saturday
    # 14 Jul, 15 Aug, 1 Nov are NOT TARGET holidays
    assert all(TARGET.is_business_day(d) for d in (date(2026, 7, 14), date(2026, 8, 14), date(2026, 11, 2)))


def test_adjustment_conventions():
    sat_end_of_may = date(2026, 5, 30)   # Saturday
    assert TARGET.adjust(sat_end_of_may, BDC.FOLLOWING) == date(2026, 6, 1)
    assert TARGET.adjust(sat_end_of_may, BDC.MODIFIED_FOLLOWING) == date(2026, 5, 29)   # would cross month end
    assert TARGET.adjust(sat_end_of_may, BDC.PRECEDING) == date(2026, 5, 29)
    assert TARGET.adjust(date(2026, 10, 12)) == date(2026, 10, 12)


def test_spot_is_t_plus_2_business_days():
    assert spot_date(date(2026, 10, 8)) == date(2026, 10, 12)     # Thu -> Mon
    assert spot_date(date(2026, 4, 1)) == date(2026, 4, 7)        # Good Friday + Easter Monday
    assert spot_date(date(2026, 12, 23)) == date(2026, 12, 28)    # Xmas + weekend


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert add_months(date(2026, 10, 12), 120) == date(2036, 10, 12)


def test_day_counts():
    assert DayCount.ACT_360.fraction(date(2026, 10, 12), date(2027, 10, 12)) == pytest.approx(365 / 360)
    assert DayCount.ACT_365F.fraction(date(2026, 10, 12), date(2027, 10, 12)) == pytest.approx(1.0)
    assert DayCount.THIRTY_E_360.fraction(date(2026, 1, 31), date(2026, 7, 31)) == pytest.approx(0.5)
    assert DayCount.THIRTY_E_360.fraction(date(2026, 10, 12), date(2027, 10, 12)) == pytest.approx(1.0)
    assert DayCount.THIRTY_E_360.fraction(date(2026, 2, 28), date(2026, 3, 31)) == pytest.approx((30 + 2) / 360)


def test_schedule_structure():
    spot = date(2026, 10, 12)
    s = make_schedule(spot, 0, 120, 12)
    assert len(s) == 10 and s[0].start == spot
    assert all(a.end == b.start for a, b in zip(s, s[1:]))                       # contiguous
    assert all(TARGET.is_business_day(p.end) and p.pay == p.end for p in s)
    assert s[-1].end == date(2036, 10, 13)   # 12 Oct 2036 is a Sunday: Modified Following moves it to Monday
    assert len(make_schedule(spot, 0, 120, 6)) == 20 and len(make_schedule(spot, 0, 12, 3)) == 4


def test_forward_start_and_short_tenor_schedules():
    spot = date(2026, 10, 12)
    f = make_schedule(spot, 60, 60, 12)
    assert f[0].start == TARGET.adjust(add_months(spot, 60)) and len(f) == 5
    single = make_schedule(spot, 0, 3, 12)            # tenor shorter than frequency => one period
    assert len(single) == 1 and single[0].end == add_months(spot, 3)
    with pytest.raises(ValueError):
        make_schedule(spot, 0, 15, 12)                # would need a stub
    with pytest.raises(ValueError):
        make_schedule(spot, 0, 0, 12)
