"""
Mock service 3: dispatch_fleet_or_charger_order()

The ONLY function that "executes" anything. It never trusts numbers from its
caller: every order is re-validated against the snapshot with the same guards
the optimiser used (defence in depth), then written to the orders table.

  Autonomous order types (Rule 5): RIDE_DISPATCH, REBALANCE, CHARGER_RESERVATION,
      BUS_DEPLOYMENT, METRO_ANNOUNCEMENT, RIDER_GUIDANCE, MOBILE_CHARGER_REQUEST
  Physical order types (Rule 4): LANE_REVERSAL, PICKUP_ZONE_LANE_REALLOCATION,
      SIGNAL_PRIORITY_OVERRIDE -> refused unless a valid one-time approval token
      is supplied; without a token the request is routed to the approval gate
      (status PENDING_APPROVAL) and nothing is executed.
"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path

from config import OPS_DB_PATH
from engine import battery_math as bm
from engine import guards
from engine.approval_gate import ApprovalGate
from engine.audit import utc_now
from engine.ops_db import connect


def _write_order(ops_db, run_id, order_type, target_id, payload, status, mode, reason) -> str:
    oid = f"ORD-{uuid.uuid4().hex[:10].upper()}"
    with connect(ops_db) as con:
        con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)",
                    (oid, run_id, utc_now(), order_type, target_id, json.dumps(payload, default=str),
                     status, mode, reason))
    return oid


def _nearest_verified_charger_km(snapshot, node_id) -> float:
    kms = [snapshot.distance(node_id, c["node_id"]) for c in snapshot.chargers
           if guards.charger_freshness_guard(c, snapshot.snapshot_time, snapshot.stale_minutes).passed]
    return min(kms) if kms else float("inf")


def dispatch_fleet_or_charger_order(order_type: str, payload: dict, snapshot=None, *,
                                    approval_request_id: str | None = None, approval_token: str | None = None,
                                    justification: str = "", run_id: str = "",
                                    ops_db: Path | str = OPS_DB_PATH) -> dict:
    """
    Execute (or refuse) one order. `payload` holds items, e.g.
      {"assignments": [{"vehicle_id": ..., "request_id": ...}, ...]}  for RIDE_DISPATCH
      {"orders": [{"vehicle_id": ..., "charger_id": ...}, ...]}       for CHARGER_RESERVATION
      {"gate_id": "G4", ...}                                          for physical actions
    Returns {"status", "executed", "accepted", "rejected", "reasons", "guard_results", ...}.
    """
    order_type = (order_type or "").upper()
    kind = guards.classify_order(order_type, payload)

    # ------------------------------------------------------------ physical: Rule 4
    if kind == "PHYSICAL":
        gate = ApprovalGate(ops_db)
        action = order_type if order_type in guards.PHYSICAL_ACTIONS else "PICKUP_ZONE_LANE_REALLOCATION"
        ok, why = gate.verify_and_consume(approval_request_id, approval_token, action)
        gr = guards.human_approval_guard(action, ok, why)
        if ok:
            oid = _write_order(ops_db, run_id, action, payload.get("gate_id"), payload, "EXECUTED",
                               "HUMAN_APPROVED", gr.reason)
            return {"status": "EXECUTED", "executed": True, "order_id": oid, "execution_mode": "HUMAN_APPROVED",
                    "approval_request_id": approval_request_id, "guard_results": [gr.to_dict()], "reasons": [gr.reason]}
        # no / invalid token -> refuse, and (only if there is no request yet) open one
        pending_id = approval_request_id
        if not approval_request_id:
            pending_id = gate.request(action, payload, justification or "requested by agent", run_id)
        _write_order(ops_db, run_id, action, payload.get("gate_id"), payload, "REFUSED", "PENDING_APPROVAL"
                     if not approval_request_id else "BLOCKED", gr.reason)
        return {"status": "PENDING_APPROVAL" if not approval_request_id else "REFUSED", "executed": False,
                "approval_request_id": pending_id, "execution_mode": "PENDING_APPROVAL" if not approval_request_id else "BLOCKED",
                "guard_results": [gr.to_dict()],
                "reasons": [gr.reason + (" -> routed to Human Operator Approval gate" if not approval_request_id else "")]}

    if kind == "UNKNOWN":
        reason = f"REFUSED: unknown order type '{order_type}'"
        _write_order(ops_db, run_id, order_type or "?", None, payload, "REFUSED", "BLOCKED", reason)
        return {"status": "REFUSED", "executed": False, "guard_results": [], "reasons": [reason]}

    # ------------------------------------------------------------ autonomous: Rule 5
    if snapshot is None and order_type in ("RIDE_DISPATCH", "REBALANCE", "CHARGER_RESERVATION"):
        raise ValueError(f"{order_type} needs the snapshot for re-validation")
    handler = {
        "RIDE_DISPATCH": _ride_dispatch, "REBALANCE": _rebalance, "CHARGER_RESERVATION": _charger_reservation,
    }.get(order_type, _simple_autonomous)
    accepted, rejected, guard_results = handler(order_type, payload, snapshot, run_id, ops_db)
    status = "EXECUTED" if accepted and not rejected else "PARTIAL" if accepted else "BLOCKED"
    if not accepted and not rejected:
        status = "NOOP"
    return {"status": status, "executed": bool(accepted), "execution_mode": "AUTONOMOUS",
            "accepted": len(accepted), "rejected": len(rejected), "accepted_items": accepted,
            "rejected_items": rejected, "guard_results": guard_results,
            "reasons": [r["reason"] for r in rejected][:10]}


# ----------------------------------------------------------------------------- handlers
def _ride_dispatch(order_type, payload, snap, run_id, ops_db):
    reqs = {r["request_id"]: r for r in snap.requests}
    accepted, rejected, guard_counts, used = [], [], Counter(), set()
    for item in payload.get("assignments", []):
        v, r = snap.vehicle(item.get("vehicle_id")), reqs.get(item.get("request_id"))
        if v is None or r is None or v["status"] != "idle" or v["vehicle_id"] in used:
            rejected.append({**item, "reason": "unknown/unavailable vehicle or request, or vehicle already used"})
            continue
        pk = snap.distance(v["node_id"], r["pickup_node"])
        tk = snap.distance(r["pickup_node"], r["dest_node"])
        ck = _nearest_verified_charger_km(snap, r["dest_node"])
        plan = bm.plan_trip(v, pk, tk, ck, snap.weather)
        gb = guards.battery_reserve_guard(plan)
        gs = guards.seat_capacity_guard(v["capacity_seats"], r["party_size"])
        guard_counts[f"battery_reserve:{'PASS' if gb.passed else 'FAIL'}"] += 1
        if gb.passed and gs.passed:
            used.add(v["vehicle_id"])
            oid = _write_order(ops_db, run_id, order_type, v["vehicle_id"], {**item, **plan.to_dict()},
                               "EXECUTED", "AUTONOMOUS", gb.reason)
            accepted.append({**item, "order_id": oid, "soc_at_charger_pct": round(plan.soc_at_charger_pct, 1)})
        else:
            reason = gb.reason if not gb.passed else gs.reason
            _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "BLOCKED", "BLOCKED", reason)
            rejected.append({**item, "reason": reason})
    return accepted, rejected, [{"guard": k, "count": n} for k, n in guard_counts.items()]


def _rebalance(order_type, payload, snap, run_id, ops_db):
    accepted, rejected, counts = [], [], Counter()
    for item in payload.get("orders", []):
        v = snap.vehicle(item.get("vehicle_id"))
        to = item.get("to_node")
        if v is None or to not in snap.node_index or v["status"] != "idle":
            rejected.append({**item, "reason": "unknown vehicle/node or vehicle not idle"})
            continue
        plan = bm.plan_trip(v, snap.distance(v["node_id"], to), 0.0, _nearest_verified_charger_km(snap, to), snap.weather)
        g = guards.battery_reserve_guard(plan)
        counts[f"battery_reserve:{'PASS' if g.passed else 'FAIL'}"] += 1
        if g.passed:
            oid = _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "EXECUTED", "AUTONOMOUS", g.reason)
            accepted.append({**item, "order_id": oid})
        else:
            _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "BLOCKED", "BLOCKED", g.reason)
            rejected.append({**item, "reason": g.reason})
    return accepted, rejected, [{"guard": k, "count": n} for k, n in counts.items()]


def _charger_reservation(order_type, payload, snap, run_id, ops_db):
    chargers = {c["charger_id"]: c for c in snap.chargers}
    # slots already reserved in THIS run (prevents over-booking across calls)
    with connect(ops_db) as con:
        booked = Counter(r[0] for r in con.execute(
            "SELECT target_id FROM orders WHERE run_id=? AND order_type='CHARGER_RESERVATION_SLOT' AND status='EXECUTED'",
            (run_id,)).fetchall())
    cf = bm.weather_profile(snap.weather)["consumption_factor"]
    accepted, rejected, counts = [], [], Counter()
    for item in payload.get("orders", []):
        v, c = snap.vehicle(item.get("vehicle_id")), chargers.get(item.get("charger_id"))
        if v is None or c is None:
            rejected.append({**item, "reason": "unknown vehicle or charger"})
            continue
        fresh = guards.charger_freshness_guard(c, snap.snapshot_time, snap.stale_minutes)
        counts[f"charger_freshness:{fresh.details['code']}"] += 1
        if not fresh.passed:
            _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "BLOCKED", "BLOCKED", fresh.reason)
            rejected.append({**item, "reason": fresh.reason})
            continue
        if booked[c["charger_id"]] >= int(c["available_slots"]):
            reason = f"REFUSED {c['charger_id']}: all {c['available_slots']} verified slots already reserved this cycle"
            _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "BLOCKED", "BLOCKED", reason)
            rejected.append({**item, "reason": reason})
            continue
        km = snap.distance(v["node_id"], c["node_id"])
        arrival = v["soc_pct"] - bm.soc_drop_pct(km, v["consumption_kwh_per_km"], v["battery_kwh"], cf)
        reach = guards.charger_reachability_guard(v["vehicle_id"], arrival)
        if not reach.passed:
            _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "BLOCKED", "BLOCKED", reach.reason)
            rejected.append({**item, "reason": reach.reason})
            continue
        booked[c["charger_id"]] += 1
        _write_order(ops_db, run_id, "CHARGER_RESERVATION_SLOT", c["charger_id"], {"vehicle_id": v["vehicle_id"]},
                     "EXECUTED", "AUTONOMOUS", "slot booked")
        oid = _write_order(ops_db, run_id, order_type, v["vehicle_id"], item, "EXECUTED", "AUTONOMOUS",
                           f"{fresh.reason}; {reach.reason}")
        accepted.append({**item, "order_id": oid, "arrival_soc_pct": round(arrival, 1)})
    return accepted, rejected, [{"guard": k, "count": n} for k, n in counts.items()]


def _simple_autonomous(order_type, payload, snap, run_id, ops_db):
    """Bus deployments, metro announcements, rider guidance, mobile charger requests (no physical change)."""
    accepted = []
    for item in payload.get("orders", []):
        target = item.get("bus_id") or item.get("gate_id") or item.get("vehicle_id") or item.get("station_id")
        oid = _write_order(ops_db, run_id, order_type, target, item, "EXECUTED", "AUTONOMOUS", "digital/fleet action")
        accepted.append({**item, "order_id": oid})
    return accepted, [], []
