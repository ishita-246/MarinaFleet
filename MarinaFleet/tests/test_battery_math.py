"""Battery-math engine and the 15 % reserve guard (incl. the exact boundary)."""
import numpy as np
import pytest

from engine import battery_math as bm
from engine.guards import battery_reserve_guard

CAR = {"vehicle_id": "T-1", "battery_kwh": 60.0, "consumption_kwh_per_km": 0.2, "soc_pct": 20.0}


def test_energy_and_soc_drop():
    assert bm.energy_kwh(10, 0.2) == pytest.approx(2.0)
    assert bm.soc_drop_pct(10, 0.2, 60) == pytest.approx(2.0 / 60 * 100)


def test_plan_trip_legs_add_up():
    p = bm.plan_trip(CAR, pickup_km=3, trip_km=9, charger_km=3)
    assert p.total_km == pytest.approx(15)
    assert p.soc_after_pickup_pct == pytest.approx(19.0)
    assert p.soc_after_trip_pct == pytest.approx(16.0)
    assert p.soc_at_charger_pct == pytest.approx(15.0)


def test_reserve_boundary_exactly_15_passes():
    # 20 % start, 15 km x 0.2 kWh/km = 3 kWh = 5 % of 60 kWh -> exactly 15.0 %
    p = bm.plan_trip(CAR, 3, 9, 3)
    assert battery_reserve_guard(p).passed


def test_reserve_just_below_15_blocked():
    p = bm.plan_trip(CAR, 3, 9, 3.05)  # a few metres more -> 14.98 %
    g = battery_reserve_guard(p)
    assert p.soc_at_charger_pct < 15
    assert not g.passed and "BLOCKED" in g.reason


def test_charger_leg_is_counted():
    # trip alone would end at 16 %, but the drive to a charger pushes it below 15 %
    p = bm.plan_trip(CAR, 3, 9, 6)
    assert p.soc_after_trip_pct >= 15 and not battery_reserve_guard(p).passed


def test_weather_increases_consumption_and_time():
    clear = bm.plan_trip(CAR, 3, 9, 3, "clear")
    rain = bm.plan_trip(CAR, 3, 9, 3, "rain")
    assert rain.soc_at_charger_pct < clear.soc_at_charger_pct
    assert bm.travel_minutes(10, bm.WEATHER_PROFILES["fog"]["speed_factor"]) > bm.travel_minutes(10)


def test_unknown_weather_rejected():
    with pytest.raises(ValueError):
        bm.weather_profile("tornado")


def test_vectorised_matches_scalar():
    rng = np.random.default_rng(0)
    soc, batt, cons = rng.uniform(5, 90, 20), rng.choice([60, 72, 82], 20).astype(float), rng.uniform(0.15, 0.21, 20)
    pk, tk, ck = rng.uniform(0, 15, (20, 7)), rng.uniform(1, 30, 7), rng.uniform(0, 10, 7)
    M = bm.final_soc_matrix(soc, batt, cons, pk, tk, ck, 1.08)
    for i in range(20):
        for j in range(7):
            v = {"vehicle_id": "x", "soc_pct": soc[i], "battery_kwh": batt[i], "consumption_kwh_per_km": cons[i]}
            assert M[i, j] == pytest.approx(bm.plan_trip(v, pk[i, j], tk[j], ck[j], "rain").soc_at_charger_pct)
