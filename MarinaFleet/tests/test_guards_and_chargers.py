"""Telemetry freshness (stale / offline rejection) and order classification."""
from datetime import datetime, timedelta, timezone

from engine.guards import charger_freshness_guard, classify_order
from services.dispatch import dispatch_fleet_or_charger_order

NOW = datetime(2026, 11, 20, 17, 48, tzinfo=timezone.utc)


def ch(age_min, status="ONLINE", slots=5):
    ts = (NOW - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"charger_id": "CH_T", "status": status, "available_slots": slots, "last_telemetry_utc": ts}


def test_fresh_charger_verified():
    assert charger_freshness_guard(ch(1), NOW, 5).passed


def test_stale_charger_rejected():
    g = charger_freshness_guard(ch(23), NOW, 5)
    assert not g.passed and g.details["code"] == "STALE" and "STALE" in g.reason


def test_offline_charger_rejected_even_if_fresh():
    g = charger_freshness_guard(ch(0.5, status="OFFLINE"), NOW, 5)
    assert not g.passed and g.details["code"] == "OFFLINE"


def test_threshold_is_configurable():
    assert not charger_freshness_guard(ch(7), NOW, 5).passed
    assert charger_freshness_guard(ch(7), NOW, 10).passed


def test_no_slots_and_future_timestamp_rejected():
    assert charger_freshness_guard(ch(1, slots=0), NOW, 5).details["code"] == "NO_SLOTS"
    assert charger_freshness_guard(ch(-10), NOW, 5).details["code"] == "CLOCK_SKEW"


def test_dataset_has_stale_and_offline_nodes(snapshot):
    verdicts = {c["charger_id"]: c["verdict"] for c in snapshot.chargers}
    assert verdicts["CH_JBR"] == "STALE" and verdicts["CH_MEDIA"] == "OFFLINE"


def test_dispatch_refuses_reservation_at_stale_or_offline(snapshot, ops_db):
    low = next(v for v in snapshot.vehicles if v["status"] == "idle" and 10 < v["soc_pct"] < 20)
    for cid in ("CH_JBR", "CH_MEDIA"):
        res = dispatch_fleet_or_charger_order("CHARGER_RESERVATION", {"orders": [{"vehicle_id": low["vehicle_id"],
                                              "charger_id": cid}]}, snapshot, run_id="t", ops_db=ops_db)
        assert res["accepted"] == 0 and res["rejected"] == 1
        assert "REFUSED" in res["reasons"][0]


def test_charger_overbooking_refused(snapshot, ops_db):
    lows = [v for v in snapshot.vehicles if v["status"] == "idle" and 15 < v["soc_pct"] < 40]
    c = next(c for c in snapshot.chargers if c["charger_id"] == "CH_MARINA")
    orders = [{"vehicle_id": v["vehicle_id"], "charger_id": "CH_MARINA"} for v in lows[: c["available_slots"] + 3]]
    res = dispatch_fleet_or_charger_order("CHARGER_RESERVATION", {"orders": orders}, snapshot, run_id="t", ops_db=ops_db)
    assert res["accepted"] <= c["available_slots"]


def test_classify_orders():
    assert classify_order("REBALANCE") == "AUTONOMOUS"
    assert classify_order("PICKUP_ZONE_LANE_REALLOCATION") == "PHYSICAL"
    assert classify_order("REBALANCE", {"lane_id": "L2"}) == "PHYSICAL"  # disguised physical change
    assert classify_order("DROP_TABLES") == "UNKNOWN"
