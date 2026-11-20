"""
Deterministic EV battery-math engine.

ALL energy, range, state-of-charge (SoC) and travel-time numbers in MarinaFleet
come from this module. The LLM never calculates any of them.

Model (kept deliberately simple so it can be explained in a viva):
    energy_kWh   = distance_km x consumption_kWh_per_km x weather_consumption_factor
    SoC drop (%) = energy_kWh / battery_kWh x 100
    travel_min   = distance_km / (BASE_SPEED_KMH x weather_speed_factor) x 60 + congestion delay

A passenger dispatch is evaluated over three legs:
    1. pickup leg   vehicle location -> pickup zone   (empty / "deadhead")
    2. trip leg     pickup zone      -> destination   (with riders)
    3. charger leg  destination      -> nearest VERIFIED charger (safety margin)
and the SoC at the END of leg 3 must stay >= the 15 % reserve (see guards.py).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

BASE_SPEED_KMH = 32.0  # average urban robotaxi speed in event traffic

# Stretch goal D: weather speed-restriction adapter.
WEATHER_PROFILES = {
    "clear": {"label": "Clear", "speed_factor": 1.00, "consumption_factor": 1.00},
    "rain": {"label": "Rain (speed limit -25 %)", "speed_factor": 0.75, "consumption_factor": 1.08},
    "fog": {"label": "Dense fog (speed limit -40 %)", "speed_factor": 0.60, "consumption_factor": 1.03},
}

EPS = 1e-9  # float tolerance so exactly 15.0 % counts as "at the reserve", not below it


def weather_profile(weather: str) -> dict:
    """Return the speed/consumption profile; unknown weather raises (never guess)."""
    try:
        return WEATHER_PROFILES[weather]
    except KeyError as exc:
        raise ValueError(f"Unknown weather '{weather}'. Use one of {list(WEATHER_PROFILES)}") from exc


def energy_kwh(distance_km: float, consumption_kwh_per_km: float, consumption_factor: float = 1.0) -> float:
    if distance_km < 0 or consumption_kwh_per_km <= 0:
        raise ValueError("distance must be >= 0 and consumption > 0")
    return distance_km * consumption_kwh_per_km * consumption_factor


def soc_drop_pct(distance_km: float, consumption_kwh_per_km: float, battery_kwh: float,
                 consumption_factor: float = 1.0) -> float:
    if battery_kwh <= 0:
        raise ValueError("battery_kwh must be > 0")
    return energy_kwh(distance_km, consumption_kwh_per_km, consumption_factor) / battery_kwh * 100.0


def range_km(soc_pct: float, battery_kwh: float, consumption_kwh_per_km: float,
             consumption_factor: float = 1.0, floor_pct: float = 0.0) -> float:
    """Distance the vehicle can drive before hitting floor_pct SoC."""
    usable_kwh = max(0.0, soc_pct - floor_pct) / 100.0 * battery_kwh
    return usable_kwh / (consumption_kwh_per_km * consumption_factor)


def travel_minutes(distance_km: float, speed_factor: float = 1.0, congestion_delay_min: float = 0.0) -> float:
    return distance_km / (BASE_SPEED_KMH * speed_factor) * 60.0 + congestion_delay_min


@dataclass
class TripEnergyPlan:
    """Result of evaluating one vehicle against one trip (all numbers from code)."""

    vehicle_id: str
    start_soc_pct: float
    pickup_km: float
    trip_km: float
    charger_km: float
    soc_after_pickup_pct: float
    soc_after_trip_pct: float
    soc_at_charger_pct: float  # lowest SoC along the plan (SoC only decreases)
    total_km: float
    energy_kwh: float

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def plan_trip(vehicle: dict, pickup_km: float, trip_km: float, charger_km: float,
              weather: str = "clear") -> TripEnergyPlan:
    """Scalar, authoritative evaluation of a dispatch. Used to validate every assignment."""
    cf = weather_profile(weather)["consumption_factor"]
    cons, batt, soc = vehicle["consumption_kwh_per_km"], vehicle["battery_kwh"], vehicle["soc_pct"]
    after_pickup = soc - soc_drop_pct(pickup_km, cons, batt, cf)
    after_trip = after_pickup - soc_drop_pct(trip_km, cons, batt, cf)
    at_charger = after_trip - soc_drop_pct(charger_km, cons, batt, cf)
    total = pickup_km + trip_km + charger_km
    return TripEnergyPlan(
        vehicle_id=vehicle["vehicle_id"], start_soc_pct=soc, pickup_km=pickup_km, trip_km=trip_km,
        charger_km=charger_km, soc_after_pickup_pct=after_pickup, soc_after_trip_pct=after_trip,
        soc_at_charger_pct=at_charger, total_km=total, energy_kwh=energy_kwh(total, cons, cf),
    )


def final_soc_matrix(soc: np.ndarray, battery_kwh: np.ndarray, consumption: np.ndarray,
                     pickup_km: np.ndarray, trip_km: np.ndarray, charger_km: np.ndarray,
                     consumption_factor: float = 1.0) -> np.ndarray:
    """
    Vectorised version of plan_trip(...).soc_at_charger_pct for a V x R matrix
    (V vehicles, R requests). Same formula; used only to build the optimiser's
    cost matrix quickly. Every chosen assignment is re-checked with plan_trip().
    """
    total_km = pickup_km + trip_km[None, :] + charger_km[None, :]
    drop = total_km * consumption[:, None] * consumption_factor / battery_kwh[:, None] * 100.0
    return soc[:, None] - drop
