"""
Rider booking service (rider portal).

A rider booking is just one more ride request, so it goes through exactly the
same deterministic code as fleet dispatch:
  quote_ride()      Python picks the fastest idle vehicle that passes the 15 % reserve
                    guard (pickup + trip + leg to the nearest VERIFIED charger), and
                    computes ETA, pickup estimate, fare and a walk-to-quieter-gate tip.
  confirm_booking() executes through dispatch_fleet_or_charger_order(RIDE_DISPATCH),
                    which re-validates everything before writing the order.
No LLM is involved in booking.
"""
from __future__ import annotations

import math
import uuid
from pathlib import Path

from config import OPS_DB_PATH
from engine import battery_math as bm
from engine import guards
from engine.audit import utc_now
from engine.ops_db import connect
from services.dispatch import dispatch_fleet_or_charger_order
from services.snapshot import Snapshot

PORTAL_RUN_ID = "RIDER-PORTAL"
# Illustrative demo tariff (not a real price list): flag fall + per-km
FARE_BASE_AED, FARE_PER_KM_AED, FARE_MIN_AED = 12.0, 2.1, 20.0
WALK_SPEED_KMH = 4.5
TIP_MIN_SAVING = 5.0  # suggest another gate only if it saves at least this many minutes
GATE_RING = [f"G{i}" for i in range(1, 7)]


def destinations(snapshot: Snapshot) -> list[tuple[str, str]]:
    return sorted(((n, d["name"]) for n, d in snapshot.nodes.items() if d["kind"] == "district"), key=lambda x: x[1])


def unavailable_vehicle_ids(ops_db: Path | str = OPS_DB_PATH) -> set[str]:
    """Vehicles already committed: rider-portal bookings + rides dispatched by the latest agent run."""
    with connect(ops_db) as con:
        last = con.execute("SELECT run_id FROM orders WHERE run_id LIKE 'RUN-%' ORDER BY ts_utc DESC LIMIT 1").fetchone()
        runs = [PORTAL_RUN_ID] + ([last[0]] if last else [])
        rows = con.execute(f"SELECT target_id FROM orders WHERE order_type='RIDE_DISPATCH' AND status='EXECUTED' "
                           f"AND run_id IN ({','.join('?' * len(runs))})", runs).fetchall()
    return {r[0] for r in rows}


def _nearest_verified_charger(snapshot: Snapshot, node: str) -> tuple[str | None, float]:
    best = (None, math.inf)
    for c in snapshot.chargers:
        if guards.charger_freshness_guard(c, snapshot.snapshot_time, snapshot.stale_minutes).passed:
            d = snapshot.distance(node, c["node_id"])
            if d < best[1]:
                best = (c["charger_id"], d)
    return best


def _fare(trip_km: float) -> float:
    return round(max(FARE_MIN_AED, FARE_BASE_AED + FARE_PER_KM_AED * trip_km), 2)


def quote_ride(snapshot: Snapshot, gate_id: str, dest_node: str, party_size: int,
               exclude: set[str] | None = None, with_tip: bool = True) -> dict:
    gate = snapshot.gate(gate_id)
    if gate is None or dest_node not in snapshot.node_index:
        raise ValueError("Unknown pickup gate or destination.")
    if not 1 <= int(party_size) <= 6:
        raise ValueError("Party size must be between 1 and 6.")
    exclude = exclude or set()
    sf = bm.weather_profile(snapshot.weather)["speed_factor"]
    pz = gate["pickup_zone_node"]
    trip_km = snapshot.distance(pz, dest_node)
    charger_id, charger_km = _nearest_verified_charger(snapshot, dest_node)
    best, skipped_battery = None, 0
    for v in snapshot.vehicles:
        if v["status"] != "idle" or v["vehicle_id"] in exclude or v["capacity_seats"] < party_size:
            continue
        pk = snapshot.distance(v["node_id"], pz)
        plan = bm.plan_trip(v, pk, trip_km, charger_km, snapshot.weather)
        eta = bm.travel_minutes(pk, sf, gate["approach_delay_min"])
        if not guards.battery_reserve_guard(plan).passed:
            if best is None or eta < best["vehicle_eta_min"]:
                skipped_battery += 1  # a closer car that the 15 % guard ruled out
            continue
        if best is None or eta < best["vehicle_eta_min"]:
            best = {"vehicle_id": v["vehicle_id"], "model": v["model"], "seats": v["capacity_seats"],
                    "start_soc_pct": round(v["soc_pct"], 1), "pickup_km": round(pk, 2),
                    "vehicle_eta_min": round(eta, 1), "soc_at_charger_pct": round(plan.soc_at_charger_pct, 1)}
    q = {"gate_id": gate_id, "gate_name": gate["name"], "pickup_node": pz, "dest_node": dest_node,
         "dest_name": snapshot.nodes[dest_node]["name"], "party_size": int(party_size), "trip_km": round(trip_km, 2),
         "trip_min": round(bm.travel_minutes(trip_km, sf), 1), "gate_queue_min": gate["est_pickup_wait_min"],
         "gate_status": gate["status"], "safety_charger": charger_id, "fare_aed": _fare(trip_km),
         "weather": snapshot.weather, "closer_cars_skipped_by_battery_guard": skipped_battery}
    if best:
        # the rider is picked up when BOTH the car has arrived and their place in the curb queue comes up
        q.update(best, available=True, est_pickup_min=round(max(best["vehicle_eta_min"], gate["est_pickup_wait_min"]), 1))
    else:
        q.update(available=False, est_pickup_min=None,
                 alternative="No battery-safe robotaxi is free right now. Please use the feeder buses or the metro "
                             "(follow the green signs).")
    if with_tip:
        q["tip"] = _walk_tip(snapshot, q, exclude)
    return q


def _walk_tip(snapshot: Snapshot, q: dict, exclude: set[str]) -> dict | None:
    """If a neighbouring gate (~200 m walk) gives a clearly earlier pickup, suggest it."""
    g = snapshot.gate(q["gate_id"])
    i = GATE_RING.index(q["gate_id"])
    best = None
    for nid in (GATE_RING[(i - 1) % 6], GATE_RING[(i + 1) % 6]):
        n = snapshot.gate(nid)
        alt = quote_ride(snapshot, nid, q["dest_node"], q["party_size"], exclude, with_tip=False)
        if not alt["available"]:
            continue
        walk_km = math.hypot(g["x_km"] - n["x_km"], g["y_km"] - n["y_km"])
        walk_min = walk_km / WALK_SPEED_KMH * 60
        total = max(alt["est_pickup_min"], walk_min)
        current = q["est_pickup_min"] if q["available"] else math.inf
        if current - total >= TIP_MIN_SAVING and (best is None or total < best["est_pickup_min"]):
            best = {"gate_id": nid, "gate_name": n["name"], "walk_m": int(round(walk_km * 1000)),
                    "walk_min": round(walk_min, 1), "est_pickup_min": round(total, 1),
                    "saving_min": round(current - total, 1) if current != math.inf else None}
    return best


def confirm_booking(snapshot: Snapshot, quote: dict, username: str, ops_db: Path | str = OPS_DB_PATH) -> dict:
    """Execute the booking via the guarded dispatch service and record it."""
    booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
    if not quote.get("available"):
        _save(ops_db, booking_id, username, quote, "REDIRECTED", None, quote.get("alternative", ""))
        return {"booking_id": booking_id, "status": "REDIRECTED", "message": quote.get("alternative")}
    request = {"request_id": booking_id, "gate_id": quote["gate_id"], "pickup_node": quote["pickup_node"],
               "dest_node": quote["dest_node"], "party_size": quote["party_size"], "waited_min": 0.0}
    snapshot.requests.append(request)  # make the request known to the dispatcher's re-validation
    res = dispatch_fleet_or_charger_order("RIDE_DISPATCH", {"assignments": [{"vehicle_id": quote["vehicle_id"],
                                          "request_id": booking_id}]}, snapshot, run_id=PORTAL_RUN_ID, ops_db=ops_db)
    if res["accepted"] == 1:
        item = res["accepted_items"][0]
        _save(ops_db, booking_id, username, quote, "CONFIRMED", item["order_id"], "battery guard passed at dispatch")
        return {"booking_id": booking_id, "status": "CONFIRMED", "order_id": item["order_id"],
                "message": f"{quote['vehicle_id']} is on its way to {quote['gate_name']} pickup zone."}
    reason = res["reasons"][0] if res["reasons"] else "vehicle no longer available"
    _save(ops_db, booking_id, username, quote, "REJECTED_BY_GUARD", None, reason)
    return {"booking_id": booking_id, "status": "REJECTED_BY_GUARD", "message": reason}


def _save(ops_db, booking_id, username, q, status, order_id, note):
    with connect(ops_db) as con:
        con.execute("INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (booking_id, username, utc_now(), q["gate_id"], q["pickup_node"], q["dest_node"], q["party_size"],
                     q.get("vehicle_id"), q.get("vehicle_eta_min"), q.get("est_pickup_min"), q.get("soc_at_charger_pct"),
                     q["trip_km"], q["fare_aed"], status, order_id, note))


def list_bookings(ops_db: Path | str = OPS_DB_PATH, username: str | None = None) -> list[dict]:
    with connect(ops_db) as con:
        if username:
            rows = con.execute("SELECT * FROM bookings WHERE username=? ORDER BY ts_utc DESC", (username,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM bookings ORDER BY ts_utc DESC").fetchall()
    return [dict(r) for r in rows]


def cancel_booking(booking_id: str, username: str, ops_db: Path | str = OPS_DB_PATH) -> bool:
    with connect(ops_db) as con:
        cur = con.execute("UPDATE bookings SET status='CANCELLED' WHERE booking_id=? AND username=? AND status='CONFIRMED'",
                          (booking_id, username))
        if cur.rowcount:
            con.execute("UPDATE orders SET status='CANCELLED' WHERE order_type='RIDE_DISPATCH' AND run_id=? AND "
                        "payload_json LIKE ?", (PORTAL_RUN_ID, f'%"{booking_id}"%'))
        return cur.rowcount == 1
