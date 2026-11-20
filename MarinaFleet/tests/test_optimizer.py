"""The optimiser never produces an unsafe assignment (checked independently), plus stretch-goal outputs."""
import copy
import random

import pytest

from config import BATTERY_RESERVE_PCT
from engine import battery_math as bm
from engine import guards
from services.dispatch import dispatch_fleet_or_charger_order
from services.optimizer import run_ev_dispatch_optimizer
from services.snapshot import get_egress_and_fleet_snapshot


def independent_check(snapshot, plan):
    """Recompute every assignment from raw snapshot data, without using optimiser numbers."""
    verified = [c for c in snapshot.chargers
                if guards.charger_freshness_guard(c, snapshot.snapshot_time, snapshot.stale_minutes).passed]
    reqs = {r["request_id"]: r for r in snapshot.requests}
    used_v, used_r = set(), set()
    for a in plan["ride_assignments"]:
        v, r = snapshot.vehicle(a["vehicle_id"]), reqs[a["request_id"]]
        assert v["status"] == "idle"
        assert a["vehicle_id"] not in used_v and a["request_id"] not in used_r  # no double booking
        used_v.add(a["vehicle_id"])
        used_r.add(a["request_id"])
        ck = min(snapshot.distance(r["dest_node"], c["node_id"]) for c in verified)
        p = bm.plan_trip(v, snapshot.distance(v["node_id"], r["pickup_node"]),
                         snapshot.distance(r["pickup_node"], r["dest_node"]), ck, snapshot.weather)
        assert p.soc_at_charger_pct >= BATTERY_RESERVE_PCT - bm.EPS, a
        assert v["capacity_seats"] >= r["party_size"]


def test_optimizer_never_unsafe(snapshot, plan):
    assert len(plan["ride_assignments"]) > 0
    independent_check(snapshot, plan)
    assert plan["guard_summary"]["validation_failures"] == 0
    assert plan["kpis"]["optimized"]["reserve_violations"] == 0


@pytest.mark.parametrize("weather", ["rain", "fog"])
def test_optimizer_safe_in_bad_weather(weather):
    s = get_egress_and_fleet_snapshot(weather=weather)
    independent_check(s, run_ev_dispatch_optimizer(s, ["G4"]))


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_optimizer_safe_on_randomised_fleets(seed):
    """Property-style test: scramble SoC and locations; the plan must still be safe."""
    s = copy.deepcopy(get_egress_and_fleet_snapshot())
    rng = random.Random(seed)
    nodes = [n for n, d in s.nodes.items() if d["kind"] != "gate"]
    for v in s.vehicles:
        v["soc_pct"] = round(rng.uniform(2, 60), 1)
        v["node_id"] = rng.choice(nodes)
    s._vehicle_map = {v["vehicle_id"]: v for v in s.vehicles}
    plan = run_ev_dispatch_optimizer(s, ["G4"])
    independent_check(s, plan)


def test_no_charger_orders_to_stale_or_offline(plan):
    assert plan["charger_orders"]
    assert not {o["charger_id"] for o in plan["charger_orders"]} & {"CH_JBR", "CH_MEDIA"}
    assert all(o["arrival_soc_pct"] >= 5 for o in plan["charger_orders"])
    refused = {x["refused_charger"] for x in plan["charger_refusals"]}
    assert refused == {"CH_JBR", "CH_MEDIA"}
    assert all(("STALE" in x["reason"]) or ("OFFLINE" in x["reason"]) for x in plan["charger_refusals"])


def test_charger_slots_not_exceeded(snapshot, plan):
    slots = {c["charger_id"]: c["available_slots"] for c in snapshot.chargers}
    from collections import Counter
    for cid, n in Counter(o["charger_id"] for o in plan["charger_orders"]).items():
        assert n <= slots[cid]


def test_rebalance_orders_are_safe_and_go_to_priority_gate(snapshot, plan):
    assert plan["rebalance_orders"]
    assert {o["gate_id"] for o in plan["rebalance_orders"]} == {"G4"}
    assert all(o["soc_at_charger_pct"] >= BATTERY_RESERVE_PCT for o in plan["rebalance_orders"])


def test_blocked_dispatches_are_really_unsafe(plan):
    assert all(b["projected_soc_pct"] < BATTERY_RESERVE_PCT for b in plan["blocked_dispatches"])


def test_no_verified_chargers_means_no_dispatch():
    s = copy.deepcopy(get_egress_and_fleet_snapshot())
    for c in s.chargers:
        c["status"] = "OFFLINE"
    plan = run_ev_dispatch_optimizer(s, ["G4"])
    assert plan["ride_assignments"] == [] and plan["charger_orders"] == []  # fail safe


def test_dispatch_revalidates_and_blocks_tampered_assignment(snapshot, ops_db):
    low = min((v for v in snapshot.vehicles if v["status"] == "idle"), key=lambda v: v["soc_pct"])
    far = next(r for r in snapshot.requests if r["dest_node"] == "AIRPORT")
    res = dispatch_fleet_or_charger_order("RIDE_DISPATCH", {"assignments": [{"vehicle_id": low["vehicle_id"],
                                          "request_id": far["request_id"], "soc_at_charger_pct": 99}]},
                                          snapshot, run_id="t", ops_db=ops_db)
    assert res["accepted"] == 0 and "BLOCKED" in res["reasons"][0]


def test_roi_kpis_vs_baseline(plan):
    o, b, g = plan["kpis"]["optimized"], plan["kpis"]["baseline"], plan["kpis"]["battery_aware_greedy"]
    assert b["stranded_vehicles"] > 0 and o["stranded_vehicles"] == 0
    assert b["failed_charger_attempts"] > 0 and o["failed_charger_attempts"] == 0
    assert o["wasted_km"] == 0 < b["wasted_km"]
    # optimiser beats greedy under the same 15 % rule
    assert o["mean_wait_min"] <= g["mean_wait_min"] and o["pickup_deadhead_km"] <= g["pickup_deadhead_km"]
    assert o["gate4_style_peak_queue_wait_min"] < b["gate4_style_peak_queue_wait_min"]
    assert o["peak_queue_wait_if_lane_approved_min"] < o["gate4_style_peak_queue_wait_min"]


def test_multimodal_and_guidance(snapshot, plan):
    mm = plan["multimodal"]
    assert mm["bus_orders"] and len({b["bus_id"] for b in mm["bus_orders"]}) == len(mm["bus_orders"])
    assert all(b["status"] == "available" for b in snapshot.buses if b["bus_id"] in {x["bus_id"] for x in mm["bus_orders"]})
    g = plan["rider_guidance"]
    assert {x["to_gate"] for x in g} == {"G3", "G5"}
    assert all(150 <= x["walk_m"] <= 300 for x in g)
    assert all(x["wait_after_balancing_min"] < x["wait_before_min"] for x in g)
    assert plan["lane_proposals"][0]["requires_human_approval"] is True


def test_weather_recalculates_etas():
    clear = run_ev_dispatch_optimizer(get_egress_and_fleet_snapshot(weather="clear"), ["G4"])
    fog = run_ev_dispatch_optimizer(get_egress_and_fleet_snapshot(weather="fog"), ["G4"])
    assert fog["kpis"]["optimized"]["mean_wait_min"] > clear["kpis"]["optimized"]["mean_wait_min"]
    assert fog["kpis"]["optimized"]["gate4_style_peak_queue_wait_min"] > clear["kpis"]["optimized"]["gate4_style_peak_queue_wait_min"]


def test_bad_strategy_rejected(snapshot):
    with pytest.raises(ValueError):
        run_ev_dispatch_optimizer(snapshot, ["G4"], strategy="yolo")
