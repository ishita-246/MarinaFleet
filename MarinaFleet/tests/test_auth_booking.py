"""Accounts (hashing, roles, lock-out) and rider bookings (same 15 % guard as fleet dispatch)."""
import copy

import pytest

from engine import auth
from engine.ops_db import connect
from services import booking
from services.snapshot import get_egress_and_fleet_snapshot


@pytest.fixture()
def snap():
    return copy.deepcopy(get_egress_and_fleet_snapshot())


def test_passwords_are_hashed(ops_db):
    auth.ensure_demo_users(ops_db)
    with connect(ops_db) as con:
        rows = con.execute("SELECT * FROM users").fetchall()
    assert len(rows) == 2
    assert all(auth.DEMO_RIDER[2] not in r["pw_hash"] and len(r["pw_hash"]) == 64 for r in rows)


def test_roles_enforced(ops_db):
    auth.ensure_demo_users(ops_db)
    assert auth.authenticate("admin", auth.demo_admin_password(), "admin", ops_db)[0]["role"] == "admin"
    assert auth.authenticate("admin", auth.demo_admin_password(), "rider", ops_db)[0] is None
    assert auth.authenticate(auth.DEMO_RIDER[0], auth.DEMO_RIDER[2], "admin", ops_db)[0] is None
    with pytest.raises(PermissionError):
        auth.require_role({"role": "rider"}, "admin")


def test_register_validation_and_duplicates(ops_db):
    u = auth.register_rider("New.Rider@Example.com", "longpassword", "New Rider", ops_db)
    assert u["username"] == "new.rider@example.com"
    assert auth.authenticate("new.rider@example.com", "longpassword", "rider", ops_db)[0]
    for email, pw in [("new.rider@example.com", "longpassword"), ("not-an-email", "longpassword"), ("a@b.co", "short")]:
        with pytest.raises(ValueError):
            auth.register_rider(email, pw, "x", ops_db)


def test_lockout_after_failed_attempts(ops_db):
    auth.ensure_demo_users(ops_db)
    for _ in range(auth.MAX_FAILED):
        assert auth.authenticate(auth.DEMO_RIDER[0], "wrong", "rider", ops_db)[0] is None
    user, msg = auth.authenticate(auth.DEMO_RIDER[0], auth.DEMO_RIDER[2], "rider", ops_db)
    assert user is None and "locked" in msg.lower()


def test_quote_is_battery_safe_and_picks_fastest(snap):
    q = booking.quote_ride(snap, "G4", "AIRPORT", 2)
    assert q["available"] and q["soc_at_charger_pct"] >= 15
    assert q["est_pickup_min"] >= q["gate_queue_min"] and q["fare_aed"] >= booking.FARE_MIN_AED
    assert q["tip"] and q["tip"]["gate_id"] in ("G3", "G5") and q["tip"]["saving_min"] >= booking.TIP_MIN_SAVING


def test_confirm_goes_through_dispatch_and_reserves_vehicle(snap, ops_db):
    q = booking.quote_ride(snap, "G2", "MARINA", 3)
    b = booking.confirm_booking(snap, q, "r@x.ae", ops_db)
    assert b["status"] == "CONFIRMED"
    assert q["vehicle_id"] in booking.unavailable_vehicle_ids(ops_db)
    q2 = booking.quote_ride(snap, "G2", "MARINA", 3, booking.unavailable_vehicle_ids(ops_db))
    assert q2["vehicle_id"] != q["vehicle_id"]
    assert booking.cancel_booking(b["booking_id"], "r@x.ae", ops_db)
    assert q["vehicle_id"] not in booking.unavailable_vehicle_ids(ops_db)
    assert not booking.cancel_booking(b["booking_id"], "someone-else@x.ae", ops_db)


def test_tampered_quote_blocked_at_dispatch(snap, ops_db):
    q = booking.quote_ride(snap, "G1", "AIRPORT", 1)
    low = min((v for v in snap.vehicles if v["status"] == "idle"), key=lambda v: v["soc_pct"])
    q.update(vehicle_id=low["vehicle_id"], soc_at_charger_pct=99)  # forged numbers are ignored
    b = booking.confirm_booking(snap, q, "r@x.ae", ops_db)
    assert b["status"] == "REJECTED_BY_GUARD" and "BLOCKED" in b["message"]


def test_no_safe_vehicle_redirects_to_transit(snap, ops_db):
    for v in snap.vehicles:
        v["soc_pct"] = 10.0
    q = booking.quote_ride(snap, "G4", "AIRPORT", 2)
    assert not q["available"]
    assert booking.confirm_booking(snap, q, "r@x.ae", ops_db)["status"] == "REDIRECTED"


def test_bad_inputs(snap):
    with pytest.raises(ValueError):
        booking.quote_ride(snap, "G9", "MARINA", 1)
    with pytest.raises(ValueError):
        booking.quote_ride(snap, "G1", "MARINA", 9)
