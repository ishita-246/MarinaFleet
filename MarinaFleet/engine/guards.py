"""
Deterministic safety guards. These are the HARD SAFETY RULES of the brief,
enforced in Python. The LLM can ask for anything; these functions decide.

Every guard returns a GuardResult so the reason is machine-generated text that
can be shown to operators and written to the audit log.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from config import BATTERY_RESERVE_PCT, CHARGER_ARRIVAL_FLOOR_PCT, STALE_TELEMETRY_MINUTES
from engine.battery_math import EPS, TripEnergyPlan

# Rule 4: physical-infrastructure actions -> always need a human approval token.
PHYSICAL_ACTIONS = {"LANE_REVERSAL", "PICKUP_ZONE_LANE_REALLOCATION", "SIGNAL_PRIORITY_OVERRIDE"}
# Rule 5: digital / fleet actions that may run autonomously (after their own guards).
AUTONOMOUS_ACTIONS = {"RIDE_DISPATCH", "REBALANCE", "CHARGER_RESERVATION", "BUS_DEPLOYMENT",
                      "METRO_ANNOUNCEMENT", "RIDER_GUIDANCE", "MOBILE_CHARGER_REQUEST"}
# Payload keys that indicate a physical change even if the order type claims otherwise.
PHYSICAL_PAYLOAD_KEYS = {"lane_id", "lane", "lane_direction", "signal_id", "signal_priority", "signal_plan"}


@dataclass
class GuardResult:
    guard: str
    passed: bool
    reason: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------- Rule 2
def battery_reserve_guard(plan: TripEnergyPlan, reserve_pct: float = BATTERY_RESERVE_PCT) -> GuardResult:
    """Block if SoC after pickup + trip + charger leg would fall below the reserve."""
    lowest = plan.soc_at_charger_pct
    ok = lowest >= reserve_pct - EPS
    if ok:
        reason = (f"{plan.vehicle_id}: projected {lowest:.1f}% at nearest verified charger "
                  f">= {reserve_pct:.0f}% reserve")
    else:
        reason = (f"BLOCKED {plan.vehicle_id}: starts {plan.start_soc_pct:.1f}%, would reach "
                  f"{lowest:.1f}% after pickup {plan.pickup_km:.1f} km + trip {plan.trip_km:.1f} km + "
                  f"charger leg {plan.charger_km:.1f} km (< {reserve_pct:.0f}% reserve)")
    return GuardResult("battery_reserve_15pct", ok, reason, {"projected_min_soc_pct": round(lowest, 2),
                                                             "reserve_pct": reserve_pct})


def seat_capacity_guard(capacity_seats: int, party_size: int) -> GuardResult:
    ok = capacity_seats >= party_size
    return GuardResult("seat_capacity", ok,
                       "seats ok" if ok else f"party of {party_size} exceeds {capacity_seats} seats")


# ------------------------------------------------------------- Rule 3
def parse_ts(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp ('Z' allowed) into an aware UTC datetime."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def telemetry_age_minutes(ts: str, now: datetime) -> float:
    return (now - parse_ts(ts)).total_seconds() / 60.0


def charger_freshness_guard(charger: dict, now: datetime,
                            max_age_minutes: float = STALE_TELEMETRY_MINUTES) -> GuardResult:
    """A charger may only be used if ONLINE, telemetry is fresh, and it reports a free slot."""
    cid = charger["charger_id"]
    age = telemetry_age_minutes(charger["last_telemetry_utc"], now)
    details = {"telemetry_age_min": round(age, 1), "max_age_min": max_age_minutes,
               "status": charger["status"], "reported_slots": charger["available_slots"]}
    if str(charger["status"]).upper() == "OFFLINE":
        return GuardResult("charger_freshness", False,
                           f"REFUSED {cid}: node is OFFLINE (last telemetry {age:.0f} min ago)", details | {"code": "OFFLINE"})
    if age > max_age_minutes:
        return GuardResult("charger_freshness", False,
                           f"REFUSED {cid}: telemetry is STALE ({age:.0f} min old > {max_age_minutes:g} min limit); "
                           f"reported {charger['available_slots']} free slots are cached and unverified",
                           details | {"code": "STALE"})
    if age < -1.0:  # timestamp from the future -> clock problem, do not trust
        return GuardResult("charger_freshness", False, f"REFUSED {cid}: telemetry timestamp is in the future",
                           details | {"code": "CLOCK_SKEW"})
    if int(charger["available_slots"]) <= 0:
        return GuardResult("charger_freshness", False, f"REFUSED {cid}: no free slots reported",
                           details | {"code": "NO_SLOTS"})
    return GuardResult("charger_freshness", True,
                       f"{cid} verified: ONLINE, telemetry {age:.1f} min old, {charger['available_slots']} free slots",
                       details | {"code": "VERIFIED"})


def charger_reachability_guard(vehicle_id: str, soc_on_arrival_pct: float,
                               floor_pct: float = CHARGER_ARRIVAL_FLOOR_PCT) -> GuardResult:
    ok = soc_on_arrival_pct >= floor_pct - EPS
    return GuardResult("charger_reachability", ok,
                       f"{vehicle_id} arrives with {soc_on_arrival_pct:.1f}%" + ("" if ok else
                       f" (< {floor_pct:g}% floor) -> do not move, request mobile charger"))


# ------------------------------------------------------------- Rule 4 / 5
def classify_order(order_type: str, payload: dict | None = None) -> str:
    """Return 'PHYSICAL', 'AUTONOMOUS' or 'UNKNOWN'. Payload keys can escalate to PHYSICAL."""
    order_type = (order_type or "").upper()
    if order_type in PHYSICAL_ACTIONS:
        return "PHYSICAL"
    if order_type in AUTONOMOUS_ACTIONS:
        if payload and PHYSICAL_PAYLOAD_KEYS & set(map(str.lower, payload.keys())):
            return "PHYSICAL"
        return "AUTONOMOUS"
    return "UNKNOWN"


def human_approval_guard(order_type: str, token_valid: bool, token_reason: str) -> GuardResult:
    if token_valid:
        return GuardResult("human_approval", True, f"{order_type}: valid operator approval token ({token_reason})")
    return GuardResult("human_approval", False,
                       f"REFUSED {order_type}: physical traffic change requires a Human Operator approval token "
                       f"({token_reason})")
