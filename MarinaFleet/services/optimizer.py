"""
Mock service 2: run_ev_dispatch_optimizer()

Deterministic optimisation runtime. Given a Snapshot it produces a complete,
battery-safe plan. No LLM involvement: the agent only chooses the high-level
`strategy` and `priority_gates` arguments.

Pipeline
  1. Charger verification      - only ONLINE + fresh + free-slot hubs are usable (Rule 3)
  2. Ride assignment           - Hungarian algorithm (scipy linear_sum_assignment) on a
                                 vehicle x request cost matrix; battery-infeasible pairs
                                 are forbidden, and every chosen pair is re-validated with
                                 the scalar guard (Rule 2)
  3. Charger routing           - unassigned low-SoC vehicles -> nearest VERIFIED hub with a slot;
                                 refusals of stale/offline hubs are recorded with reasons
  4. Fleet rebalancing         - healthy idle vehicles -> pickup zones of priority gates
  5. Multi-modal balancer      - overflow demand -> feeder buses + metro announcements  (stretch B)
  6. Rider guidance            - nudge fans ~200 m to less congested gates               (stretch C)
  7. Lane-change proposal      - physical action, flagged requires_human_approval        (Rule 4)
  8. Naive baseline + ROI KPIs - nearest-vehicle, no battery awareness                   (stretch A)
Weather (stretch D) flows through battery_math speed / consumption factors.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from scipy.optimize import linear_sum_assignment

from config import BATTERY_RESERVE_PCT, CHARGE_THRESHOLD_PCT, CHARGER_ARRIVAL_FLOOR_PCT
from engine import battery_math as bm
from engine import guards
from services.snapshot import Snapshot

BIG = 1e6                       # forbidden-pair cost
PRIORITY_BONUS_MIN = 6.0        # cost bonus for requests at agent-chosen priority gates
WAIT_BONUS_PER_MIN = 0.25       # requests that waited longer are preferred
WAIT_FAIRNESS = 0.05            # quadratic term: penalises very long individual pickups (lowers p90)
REBALANCE_MAX = 60              # max vehicles moved toward priority gates per cycle
FORECAST_WINDOW_MIN = 30        # multi-modal planning horizon
RETURN_SHARE = 0.35             # share of busy vehicles expected back within the window
BUS_SHARE_OF_OVERFLOW = 0.60    # rest of overflow goes to metro
WALK_SPEED_KMH = 4.5
STRANDED_REDISPATCH_WAIT_MIN = 35.0   # baseline: rider stuck in a dead car waits like historic peak
STRATEGIES = {"surge_first_battery_safe", "min_deadhead"}


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def run_ev_dispatch_optimizer(snapshot: Snapshot, priority_gates: list[str] | None = None,
                              strategy: str = "surge_first_battery_safe",
                              charge_threshold_pct: float = CHARGE_THRESHOLD_PCT) -> dict:
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {sorted(STRATEGIES)}")
    valid_gates = {g["gate_id"] for g in snapshot.gates}
    priority_gates = [g for g in (priority_gates or []) if g in valid_gates]
    if strategy == "min_deadhead":
        priority_gates_for_cost = []
    else:
        priority_gates_for_cost = priority_gates

    wx = bm.weather_profile(snapshot.weather)
    cf, sf = wx["consumption_factor"], wx["speed_factor"]
    D, ix = snapshot.dist, snapshot.node_index
    gate_by_id = {g["gate_id"]: g for g in snapshot.gates}

    # ------------------------------------------------ 1. charger verification
    verified, refused = [], []
    for c in snapshot.chargers:
        gr = guards.charger_freshness_guard(c, snapshot.snapshot_time, snapshot.stale_minutes)
        (verified if gr.passed else refused).append({"charger": c, "guard": gr})
    v_nodes = np.array([ix[x["charger"]["node_id"]] for x in verified], dtype=int)
    if len(v_nodes):
        near_ch_km = D[:, v_nodes].min(axis=1)
        near_ch_id = [verified[i]["charger"]["charger_id"] for i in D[:, v_nodes].argmin(axis=1)]
    else:  # no trustworthy charger at all -> every dispatch is infeasible (fail safe)
        near_ch_km = np.full(D.shape[0], np.inf)
        near_ch_id = [None] * D.shape[0]

    # ------------------------------------------------ 2. ride assignment
    idle = [v for v in snapshot.vehicles if v["status"] == "idle"]
    reqs = snapshot.requests
    v_node = np.array([ix[v["node_id"]] for v in idle])
    soc = np.array([v["soc_pct"] for v in idle], dtype=float)
    batt = np.array([v["battery_kwh"] for v in idle], dtype=float)
    cons = np.array([v["consumption_kwh_per_km"] for v in idle], dtype=float)
    seats = np.array([v["capacity_seats"] for v in idle])
    r_pick = np.array([ix[r["pickup_node"]] for r in reqs])
    r_dest = np.array([ix[r["dest_node"]] for r in reqs])
    party = np.array([r["party_size"] for r in reqs])
    waited = np.array([r["waited_min"] for r in reqs], dtype=float)
    delay = np.array([gate_by_id[r["gate_id"]]["approach_delay_min"] for r in reqs])

    pickup_km = D[np.ix_(v_node, r_pick)]
    trip_km = D[r_pick, r_dest]
    charger_km = near_ch_km[r_dest]
    final_soc = bm.final_soc_matrix(soc, batt, cons, pickup_km, trip_km, charger_km, cf)
    battery_ok = final_soc >= BATTERY_RESERVE_PCT - bm.EPS
    feasible = battery_ok & (seats[:, None] >= party[None, :]) & np.isfinite(final_soc)

    eta = pickup_km / (bm.BASE_SPEED_KMH * sf) * 60.0 + delay[None, :]
    bonus = WAIT_BONUS_PER_MIN * waited + np.array(
        [PRIORITY_BONUS_MIN if r["gate_id"] in priority_gates_for_cost else 0.0 for r in reqs])
    cost = np.where(feasible, eta + WAIT_FAIRNESS * eta ** 2 - bonus[None, :], BIG)
    rows, cols = linear_sum_assignment(cost)

    assignments, assigned_v, served_r = [], set(), set()
    validation_failures = 0
    for vi, ri in zip(rows, cols):
        if cost[vi, ri] >= BIG:
            continue
        v, r = idle[vi], reqs[ri]
        # authoritative scalar re-check (defence in depth)
        plan = bm.plan_trip(v, float(pickup_km[vi, ri]), float(trip_km[ri]), float(charger_km[ri]), snapshot.weather)
        g_batt = guards.battery_reserve_guard(plan)
        g_seat = guards.seat_capacity_guard(v["capacity_seats"], r["party_size"])
        if not (g_batt.passed and g_seat.passed):
            validation_failures += 1
            continue
        assigned_v.add(vi)
        served_r.add(ri)
        assignments.append({
            "vehicle_id": v["vehicle_id"], "request_id": r["request_id"], "gate_id": r["gate_id"],
            "from_node": v["node_id"], "pickup_node": r["pickup_node"], "dest_node": r["dest_node"],
            "party_size": r["party_size"], "start_soc_pct": _r(v["soc_pct"], 1),
            "pickup_km": _r(plan.pickup_km), "trip_km": _r(plan.trip_km), "charger_leg_km": _r(plan.charger_km),
            "soc_after_trip_pct": _r(plan.soc_after_trip_pct, 1), "soc_at_charger_pct": _r(plan.soc_at_charger_pct, 1),
            "safety_charger": near_ch_id[r_dest[ri]], "pickup_eta_min": _r(eta[vi, ri], 1),
            "guard": "PASS", "guard_reason": g_batt.reason,
        })

    # dispatches the 15 % guard blocked: the naive "nearest car" for each request, if it fails the guard
    blocked, seen = [], set()
    nearest_vi = pickup_km.argmin(axis=0)
    for ri, vi in enumerate(nearest_vi):
        if battery_ok[vi, ri] or vi in seen:
            continue
        seen.add(vi)
        v, r = idle[vi], reqs[ri]
        plan = bm.plan_trip(v, float(pickup_km[vi, ri]), float(trip_km[ri]), float(charger_km[ri]), snapshot.weather)
        gr = guards.battery_reserve_guard(plan)
        blocked.append({"vehicle_id": v["vehicle_id"], "request_id": r["request_id"], "gate_id": r["gate_id"],
                        "start_soc_pct": _r(v["soc_pct"], 1), "projected_soc_pct": _r(plan.soc_at_charger_pct, 1),
                        "reason": gr.reason})
    battery_locked = int((~battery_ok).all(axis=1).sum())  # vehicles infeasible for every request

    # ------------------------------------------------ 3. charger routing
    slots = {x["charger"]["charger_id"]: int(x["charger"]["available_slots"]) for x in verified}
    all_ch = snapshot.chargers
    refused_by_id = {x["charger"]["charger_id"]: x["guard"] for x in refused}
    low = sorted((vi for vi in range(len(idle)) if vi not in assigned_v and soc[vi] < charge_threshold_pct),
                 key=lambda vi: soc[vi])
    charger_orders, charger_refusals, waitlist, mobile_requests = [], [], [], []
    for vi in low:
        v = idle[vi]
        ranked_all = sorted(all_ch, key=lambda c: D[v_node[vi], ix[c["node_id"]]])
        nearest_any = ranked_all[0]
        chosen = None
        reachable_but_full = False
        for c in ranked_all:
            if c["charger_id"] not in slots:
                continue  # not verified -> never a candidate
            km = float(D[v_node[vi], ix[c["node_id"]]])
            arrival = v["soc_pct"] - bm.soc_drop_pct(km, v["consumption_kwh_per_km"], v["battery_kwh"], cf)
            if not guards.charger_reachability_guard(v["vehicle_id"], arrival).passed:
                continue
            if slots[c["charger_id"]] <= 0:
                reachable_but_full = True
                continue
            chosen = (c, km, arrival)
            break
        if nearest_any["charger_id"] in refused_by_id:
            charger_refusals.append({
                "vehicle_id": v["vehicle_id"], "soc_pct": _r(v["soc_pct"], 1),
                "refused_charger": nearest_any["charger_id"],
                "refused_code": refused_by_id[nearest_any["charger_id"]].details["code"],
                "reason": refused_by_id[nearest_any["charger_id"]].reason,
                "rerouted_to": chosen[0]["charger_id"] if chosen else None,
            })
        if chosen:
            c, km, arrival = chosen
            slots[c["charger_id"]] -= 1
            charger_orders.append({"vehicle_id": v["vehicle_id"], "charger_id": c["charger_id"],
                                   "from_node": v["node_id"], "distance_km": _r(km), "start_soc_pct": _r(v["soc_pct"], 1),
                                   "arrival_soc_pct": _r(arrival, 1),
                                   "eta_min": _r(bm.travel_minutes(km, sf), 1)})
        elif reachable_but_full:
            waitlist.append({"vehicle_id": v["vehicle_id"], "soc_pct": _r(v["soc_pct"], 1),
                             "action": "HOLD_AND_WAITLIST", "reason": "all reachable verified hubs full"})
        else:
            mobile_requests.append({"vehicle_id": v["vehicle_id"], "node_id": v["node_id"], "soc_pct": _r(v["soc_pct"], 1),
                                    "reason": "no verified hub reachable above arrival floor; do not move vehicle"})

    # ------------------------------------------------ 4. rebalancing
    rebalance_orders = []
    if strategy == "min_deadhead":
        targets = []  # minimise empty km: no proactive repositioning
    else:
        targets = priority_gates or [g["gate_id"] for g in snapshot.gates if g["status"] != "NORMAL"]
    unmet_by_gate = defaultdict(int)
    for ri, r in enumerate(reqs):
        if ri not in served_r:
            unmet_by_gate[r["gate_id"]] += 1
    if targets:
        cands = [vi for vi in range(len(idle)) if vi not in assigned_v and soc[vi] >= charge_threshold_pct]
        weights = {g: gate_by_id[g]["ridehail_parties_queued"] for g in targets}
        total_w = sum(weights.values()) or 1
        quota = {g: max(1, round(REBALANCE_MAX * w / total_w)) for g, w in weights.items()}
        used = set()
        for g in targets:
            pz = gate_by_id[g]["pickup_zone_node"]
            ranked = sorted((vi for vi in cands if vi not in used), key=lambda vi: D[v_node[vi], ix[pz]])
            for vi in ranked:
                if quota[g] <= 0:
                    break
                v = idle[vi]
                km = float(D[v_node[vi], ix[pz]])
                if km < 0.3:  # already at the pickup zone
                    continue
                plan = bm.plan_trip(v, km, 0.0, float(near_ch_km[ix[pz]]), snapshot.weather)
                if not guards.battery_reserve_guard(plan).passed:
                    continue
                used.add(vi)
                quota[g] -= 1
                rebalance_orders.append({"vehicle_id": v["vehicle_id"], "from_node": v["node_id"], "to_node": pz,
                                         "gate_id": g, "distance_km": _r(km), "start_soc_pct": _r(v["soc_pct"], 1),
                                         "soc_at_charger_pct": _r(plan.soc_at_charger_pct, 1),
                                         "eta_min": _r(bm.travel_minutes(km, sf), 1)})

    # ------------------------------------------------ 5. multi-modal balancer
    multimodal = _multimodal_plan(snapshot, assignments, rebalance_orders, sf)

    # ------------------------------------------------ 6. rider guidance + 7. lane proposal
    guidance = _rider_guidance(snapshot)
    lane_proposals = _lane_proposals(snapshot, guidance)

    # ------------------------------------------------ 8. KPIs vs naive baseline
    alt_wait = multimodal["alt_wait_min_by_gate"]
    opt_waits = [a["pickup_eta_min"] for a in assignments] + \
                [alt_wait.get(r["gate_id"], STRANDED_REDISPATCH_WAIT_MIN) for ri, r in enumerate(reqs) if ri not in served_r]
    pickup_dh = sum(a["pickup_km"] for a in assignments)
    charging_km = sum(o["distance_km"] for o in charger_orders)
    rebalance_km = sum(o["distance_km"] for o in rebalance_orders)
    peak_after = _peak_queue_wait_after(snapshot, guidance, lane_approved=False)
    optimized_kpis = {
        "requests": len(reqs), "served_by_robotaxi": len(assignments),
        "redirected_multimodal": len(reqs) - len(assignments),
        "mean_wait_min": _r(np.mean(opt_waits), 1), "p90_wait_min": _r(np.percentile(opt_waits, 90), 1),
        "pickup_deadhead_km": _r(pickup_dh, 1),
        "deadhead_km_per_ride": _r(pickup_dh / max(1, len(assignments)), 2),
        "charging_km": _r(charging_km, 1), "wasted_km": 0.0, "rebalance_km": _r(rebalance_km, 1),
        "total_empty_km": _r(pickup_dh + charging_km + rebalance_km, 1),
        "stranded_vehicles": len([a for a in assignments if a["soc_after_trip_pct"] <= 0]),
        "riders_stranded": 0,
        "reserve_violations": len([a for a in assignments if a["soc_at_charger_pct"] < BATTERY_RESERVE_PCT - bm.EPS]),
        "failed_charger_attempts": 0, "charger_orders": len(charger_orders),
        "gate4_style_peak_queue_wait_min": peak_after,
        "peak_queue_wait_if_lane_approved_min": _peak_queue_wait_after(snapshot, guidance, lane_approved=True),
    }
    baseline_kpis = naive_baseline(snapshot)
    # same battery rules, but greedy nearest-vehicle instead of global optimisation
    greedy_kpis = _battery_aware_greedy(reqs, feasible, pickup_km, eta)

    guard_summary = {
        "assignments_validated": len(assignments), "validation_failures": validation_failures,
        "dispatches_blocked_by_15pct_guard": len(blocked), "battery_locked_vehicles": battery_locked,
        "chargers_verified": [x["charger"]["charger_id"] for x in verified],
        "chargers_refused": {x["charger"]["charger_id"]: x["guard"].reason for x in refused},
        "charger_refusal_events": len(charger_refusals),
    }

    return {
        "strategy": strategy, "priority_gates": priority_gates, "weather": snapshot.weather,
        "ride_assignments": assignments, "blocked_dispatches": blocked,
        "unserved_requests": [reqs[ri]["request_id"] for ri in range(len(reqs)) if ri not in served_r],
        "charger_orders": charger_orders, "charger_refusals": charger_refusals,
        "charger_waitlist": waitlist, "mobile_charger_requests": mobile_requests,
        "rebalance_orders": rebalance_orders, "multimodal": multimodal,
        "rider_guidance": guidance, "lane_proposals": lane_proposals,
        "kpis": {"optimized": optimized_kpis, "baseline": baseline_kpis, "battery_aware_greedy": greedy_kpis},
        "guard_summary": guard_summary,
    }


# =============================================================================
# Stretch B: multi-modal load balancer
# =============================================================================
def _multimodal_plan(snapshot: Snapshot, assignments: list, rebalance: list, sf: float) -> dict:
    D, ix = snapshot.dist, snapshot.node_index
    busy = sum(v["status"] in ("occupied", "en_route") for v in snapshot.vehicles)
    total_parties = sum(g["ridehail_parties_queued"] for g in snapshot.gates) or 1
    assigned_by_gate, rebal_by_gate = defaultdict(int), defaultdict(int)
    for a in assignments:
        assigned_by_gate[a["gate_id"]] += 1
    for o in rebalance:
        rebal_by_gate[o["gate_id"]] += 1

    gate_rows, overflow_fans = [], {}
    for g in snapshot.gates:
        returning = busy * RETURN_SHARE * g["ridehail_parties_queued"] / total_parties
        capacity = assigned_by_gate[g["gate_id"]] + rebal_by_gate[g["gate_id"]] + returning
        overflow_parties = max(0.0, g["ridehail_parties_queued"] - capacity)
        overflow_fans[g["gate_id"]] = int(round(overflow_parties * g["avg_party_size"]))
        gate_rows.append({"gate_id": g["gate_id"], "ridehail_parties": g["ridehail_parties_queued"],
                          "robotaxi_capacity_30min": _r(capacity, 0), "overflow_parties": _r(overflow_parties, 0),
                          "overflow_fans": overflow_fans[g["gate_id"]]})

    buses = sorted([b for b in snapshot.buses if b["status"] == "available"], key=lambda b: b["bus_id"])
    bus_orders, alt_wait = [], {}
    for gid in sorted(overflow_fans, key=lambda k: -overflow_fans[k]):
        need = overflow_fans[gid] * BUS_SHARE_OF_OVERFLOW
        if need <= 0:
            continue
        pz = snapshot.gate(gid)["pickup_zone_node"]
        buses.sort(key=lambda b: D[ix[b["node_id"]], ix[pz]])
        seats = 0
        while buses and seats < need:
            b = buses.pop(0)
            km = float(D[ix[b["node_id"]], ix[pz]])
            eta = bm.travel_minutes(km, sf, congestion_delay_min=2.0)
            seats += b["capacity"]
            bus_orders.append({"bus_id": b["bus_id"], "gate_id": gid, "to_node": pz, "capacity": b["capacity"],
                               "distance_km": _r(km), "eta_min": _r(eta, 1)})
            alt_wait[gid] = max(alt_wait.get(gid, 0.0), _r(eta, 1))

    announcements, metro_spare = [], {}
    for m in snapshot.metro:
        metro_spare[m["station_id"]] = m["capacity_per_hour"] * (1 - m["current_load_pct"] / 100) * FORECAST_WINDOW_MIN / 60
    for g in snapshot.gates:
        bus_seats = sum(o["capacity"] for o in bus_orders if o["gate_id"] == g["gate_id"])
        rest = max(0, overflow_fans[g["gate_id"]] - bus_seats)
        if rest <= 0:
            continue
        ranked = sorted(snapshot.metro, key=lambda m: math.hypot(g["x_km"] - snapshot.nodes[m["node_id"]]["x_km"],
                                                                 g["y_km"] - snapshot.nodes[m["node_id"]]["y_km"]))
        m = next((m for m in ranked if metro_spare[m["station_id"]] >= rest), ranked[0])
        walk_km = math.hypot(g["x_km"] - snapshot.nodes[m["node_id"]]["x_km"], g["y_km"] - snapshot.nodes[m["node_id"]]["y_km"]) * 1.2
        walk_min = walk_km / WALK_SPEED_KMH * 60
        metro_spare[m["station_id"]] -= rest
        metro_wait = walk_min + m["headway_min"] / 2
        if g["gate_id"] not in alt_wait:
            alt_wait[g["gate_id"]] = _r(metro_wait, 1)
        announcements.append({
            "gate_id": g["gate_id"], "station_id": m["station_id"], "fans": rest, "walk_min": _r(walk_min, 1),
            "message": f"{g['name']}: ride-hail queue is long. {m['name']} metro is a {walk_min:.0f}-minute walk, "
                       f"trains every {m['headway_min']:g} min. Follow the green signs.",
        })
    for g in snapshot.gates:  # gates with no overflow: alternative = metro walk
        if g["gate_id"] not in alt_wait:
            m = snapshot.metro[0]
            walk_km = math.hypot(g["x_km"] - snapshot.nodes[m["node_id"]]["x_km"], g["y_km"] - snapshot.nodes[m["node_id"]]["y_km"]) * 1.2
            alt_wait[g["gate_id"]] = _r(walk_km / WALK_SPEED_KMH * 60 + m["headway_min"] / 2, 1)
    return {"gates": gate_rows, "bus_orders": bus_orders, "metro_announcements": announcements,
            "metro_spare_after_30min": {k: int(v) for k, v in metro_spare.items()}, "alt_wait_min_by_gate": alt_wait}


# =============================================================================
# Stretch C: rider ETA + pickup-zone guidance (walk ~200 m to a quieter gate)
# =============================================================================
def _rider_guidance(snapshot: Snapshot) -> list[dict]:
    gates = {g["gate_id"]: g for g in snapshot.gates}
    order = [f"G{i}" for i in range(1, 7)]
    out = []
    for gid, g in gates.items():
        if g["status"] != "SURGE":
            continue
        i = order.index(gid)
        neigh = [gates[order[(i - 1) % 6]], gates[order[(i + 1) % 6]]]
        group = [g] + neigh
        total_parties = sum(x["ridehail_parties_queued"] for x in group)
        total_thr = sum(x["effective_throughput_vpm"] for x in group)
        target_wait = total_parties / total_thr  # balanced wait across the three gates
        shift_total = max(0.0, g["ridehail_parties_queued"] - target_wait * g["effective_throughput_vpm"])
        for n in neigh:
            room = max(0.0, target_wait * n["effective_throughput_vpm"] - n["ridehail_parties_queued"])
            walk_km = math.hypot(g["x_km"] - n["x_km"], g["y_km"] - n["y_km"])
            walk_min = walk_km / WALK_SPEED_KMH * 60
            parties = min(room, shift_total)
            out.append({
                "from_gate": gid, "to_gate": n["gate_id"], "walk_m": int(round(walk_km * 1000)),
                "walk_min": _r(walk_min, 1), "parties_to_shift": int(round(parties)),
                "fans_to_shift": int(round(parties * g["avg_party_size"])),
                "wait_before_min": g["est_pickup_wait_min"], "wait_at_target_now_min": n["est_pickup_wait_min"],
                "wait_after_balancing_min": _r(target_wait, 1),
                "message": f"Shorter ride-hail wait at {n['name']}: walk ~{walk_km * 1000:.0f} m "
                           f"({walk_min:.0f} min). Est. pickup in {target_wait:.0f} min vs {g['est_pickup_wait_min']:.0f} min here.",
            })
    return out


def _peak_queue_wait_after(snapshot: Snapshot, guidance: list[dict], lane_approved: bool) -> float:
    """Highest gate pickup-queue wait after applying rider guidance (and optionally the extra curb lane)."""
    parties = {g["gate_id"]: float(g["ridehail_parties_queued"]) for g in snapshot.gates}
    thr = {g["gate_id"]: float(g["effective_throughput_vpm"]) for g in snapshot.gates}
    for x in guidance:
        parties[x["from_gate"]] -= x["parties_to_shift"]
        parties[x["to_gate"]] += x["parties_to_shift"]
    if lane_approved:
        for g in snapshot.gates:
            if g["status"] == "SURGE":
                thr[g["gate_id"]] *= (g["curb_lanes"] + 1) / g["curb_lanes"]
                # with more curb capacity, fewer fans need to walk: rebalance the surge group again
                order = [f"G{i}" for i in range(1, 7)]
                i = order.index(g["gate_id"])
                grp = [g["gate_id"], order[(i - 1) % 6], order[(i + 1) % 6]]
                target = sum(parties[k] for k in grp) / sum(thr[k] for k in grp)
                for k in grp:
                    parties[k] = target * thr[k]
    return _r(max(parties[k] / thr[k] for k in parties), 1)


def _lane_proposals(snapshot: Snapshot, guidance: list[dict]) -> list[dict]:
    """Physical change proposals. Computed here; can ONLY be executed with operator approval."""
    props = []
    for g in snapshot.gates:
        if g["status"] != "SURGE":
            continue
        thr_after = g["effective_throughput_vpm"] * (g["curb_lanes"] + 1) / g["curb_lanes"]
        wait_after = g["ridehail_parties_queued"] / thr_after
        props.append({
            "action_type": "PICKUP_ZONE_LANE_REALLOCATION", "gate_id": g["gate_id"],
            "pickup_zone": g["pickup_zone_node"],
            "description": f"Reallocate 1 general-traffic lane on the stadium ring road at {g['pickup_zone_node']} "
                           f"to robotaxi pickup ({g['curb_lanes']} -> {g['curb_lanes'] + 1} curb lanes) "
                           f"and give pickup-exit signals priority for 30 min.",
            "throughput_before_vpm": g["effective_throughput_vpm"], "throughput_after_vpm": _r(thr_after, 1),
            "wait_before_min": g["est_pickup_wait_min"], "wait_after_min": _r(wait_after, 1),
            "requires_human_approval": True,
        })
    return props


def _battery_aware_greedy(reqs, feasible, pickup_km, eta) -> dict:
    """Comparator isolating the optimiser's value: greedy FIFO but with the same 15 % feasibility mask."""
    avail = set(range(feasible.shape[0]))
    waits, km, served = [], 0.0, 0
    for ri in sorted(range(len(reqs)), key=lambda i: -reqs[i]["waited_min"]):
        cand = [vi for vi in avail if feasible[vi, ri]]
        if not cand:
            waits.append(STRANDED_REDISPATCH_WAIT_MIN)
            continue
        vi = min(cand, key=lambda vi: pickup_km[vi, ri])
        avail.discard(vi)
        served += 1
        waits.append(float(eta[vi, ri]))
        km += float(pickup_km[vi, ri])
    return {"requests": len(reqs), "served_by_robotaxi": served, "mean_wait_min": _r(np.mean(waits), 1),
            "p90_wait_min": _r(np.percentile(waits, 90), 1), "pickup_deadhead_km": _r(km, 1),
            "deadhead_km_per_ride": _r(km / max(1, served), 2), "stranded_vehicles": 0, "reserve_violations": 0}


# =============================================================================
# Stretch A: naive baseline (nearest vehicle, no battery awareness, cached charger data)
# =============================================================================
def naive_baseline(snapshot: Snapshot) -> dict:
    wx = bm.weather_profile(snapshot.weather)
    cf, sf = wx["consumption_factor"], wx["speed_factor"]
    D, ix = snapshot.dist, snapshot.node_index
    gate_by_id = {g["gate_id"]: g for g in snapshot.gates}
    idle = [v for v in snapshot.vehicles if v["status"] == "idle"]
    available = set(range(len(idle)))
    # baseline trusts every charger's reported data (including stale / offline nodes)
    any_ch_nodes = [ix[c["node_id"]] for c in snapshot.chargers]
    valid_nodes = [ix[c["node_id"]] for c in snapshot.chargers
                   if guards.charger_freshness_guard(c, snapshot.snapshot_time, snapshot.stale_minutes).passed]
    invalid_nodes = set(any_ch_nodes) - set(valid_nodes)

    waits, stranded, reserve_viol, served, failed_charge, riders_stranded = [], 0, 0, 0, 0, 0
    pickup_km_total, charger_km_total, wasted_km = 0.0, 0.0, 0.0
    used_vehicles = set()
    for r in sorted(snapshot.requests, key=lambda r: -r["waited_min"]):  # FIFO by waiting time
        cand = [vi for vi in available if idle[vi]["capacity_seats"] >= r["party_size"]]
        if not cand:
            waits.append(STRANDED_REDISPATCH_WAIT_MIN)
            continue
        vi = min(cand, key=lambda vi: D[ix[idle[vi]["node_id"]], ix[r["pickup_node"]]])
        available.discard(vi)
        used_vehicles.add(vi)
        v = idle[vi]
        pk = float(D[ix[v["node_id"]], ix[r["pickup_node"]]])
        tk = float(D[ix[r["pickup_node"]], ix[r["dest_node"]]])
        pickup_km_total += pk
        after_pickup = v["soc_pct"] - bm.soc_drop_pct(pk, v["consumption_kwh_per_km"], v["battery_kwh"], cf)
        after_trip = after_pickup - bm.soc_drop_pct(tk, v["consumption_kwh_per_km"], v["battery_kwh"], cf)
        eta = bm.travel_minutes(pk, sf, gate_by_id[r["gate_id"]]["approach_delay_min"])
        if after_pickup <= 0:
            stranded += 1  # dies before reaching the rider
            waits.append(STRANDED_REDISPATCH_WAIT_MIN + eta)
            continue
        if after_trip <= 0:
            stranded += 1  # dies mid-trip with riders on board -> riders need a rescue car
            riders_stranded += 1
            waits.append(eta + STRANDED_REDISPATCH_WAIT_MIN)
            continue
        served += 1
        waits.append(eta)
        if after_trip < BATTERY_RESERVE_PCT:
            reserve_viol += 1
            # tries nearest charger by (possibly stale) reported data
            d_node = ix[r["dest_node"]]
            ch = min(any_ch_nodes, key=lambda n: D[d_node, n])
            km = float(D[d_node, ch])
            if ch in invalid_nodes:
                failed_charge += 1
                wasted_km += km  # drove to a dead / full hub
                km += float(min(D[ch, n] for n in valid_nodes)) if valid_nodes else 0.0
            charger_km_total += km
            if after_trip - bm.soc_drop_pct(km, v["consumption_kwh_per_km"], v["battery_kwh"], cf) <= 0:
                stranded += 1
    # low unused vehicles head to nearest reported charger (no freshness check)
    for vi in available:
        v = idle[vi]
        if v["soc_pct"] >= CHARGE_THRESHOLD_PCT:
            continue
        n0 = ix[v["node_id"]]
        ch = min(any_ch_nodes, key=lambda n: D[n0, n])
        km = float(D[n0, ch])
        if ch in invalid_nodes:
            failed_charge += 1
            wasted_km += km
            km += float(min(D[ch, n] for n in valid_nodes)) if valid_nodes else 0.0
        charger_km_total += km
        if v["soc_pct"] - bm.soc_drop_pct(km, v["consumption_kwh_per_km"], v["battery_kwh"], cf) <= 0:
            stranded += 1

    return {
        "requests": len(snapshot.requests), "served_by_robotaxi": served,
        "redirected_multimodal": 0,
        "mean_wait_min": _r(np.mean(waits), 1), "p90_wait_min": _r(np.percentile(waits, 90), 1),
        "pickup_deadhead_km": _r(pickup_km_total, 1),
        "deadhead_km_per_ride": _r(pickup_km_total / max(1, len(used_vehicles)), 2),
        "charging_km": _r(charger_km_total, 1), "wasted_km": _r(wasted_km, 1), "rebalance_km": 0.0,
        "total_empty_km": _r(pickup_km_total + charger_km_total, 1),
        "stranded_vehicles": stranded, "riders_stranded": riders_stranded,
        "reserve_violations": reserve_viol, "failed_charger_attempts": failed_charge,
        "gate4_style_peak_queue_wait_min": max(g["est_pickup_wait_min"] for g in snapshot.gates),
    }
