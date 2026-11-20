"""Rule 4: physical lane / signal changes can never execute without a human approval token."""
import pytest

from engine.approval_gate import ApprovalGate, InvalidTransition
from engine.ops_db import connect
from services.dispatch import dispatch_fleet_or_charger_order

LANE = "PICKUP_ZONE_LANE_REALLOCATION"


def executed_physical(ops_db):
    with connect(ops_db) as con:
        return con.execute("SELECT COUNT(*) FROM orders WHERE order_type IN "
                           "('PICKUP_ZONE_LANE_REALLOCATION','LANE_REVERSAL','SIGNAL_PRIORITY_OVERRIDE') "
                           "AND status='EXECUTED'").fetchone()[0]


@pytest.mark.parametrize("action", [LANE, "LANE_REVERSAL", "SIGNAL_PRIORITY_OVERRIDE"])
def test_lane_change_without_approval_is_refused(ops_db, action):
    res = dispatch_fleet_or_charger_order(action, {"gate_id": "G4"}, run_id="t", ops_db=ops_db)
    assert res["executed"] is False and res["status"] == "PENDING_APPROVAL"
    assert ApprovalGate(ops_db).get(res["approval_request_id"])["status"] == "PENDING_APPROVAL"
    assert executed_physical(ops_db) == 0


def test_pending_request_without_token_still_refused(ops_db):
    rid = dispatch_fleet_or_charger_order(LANE, {"gate_id": "G4"}, ops_db=ops_db)["approval_request_id"]
    res = dispatch_fleet_or_charger_order(LANE, {"gate_id": "G4"}, approval_request_id=rid, ops_db=ops_db)
    assert res["status"] == "REFUSED" and executed_physical(ops_db) == 0


def test_wrong_token_refused_valid_token_executes_once(ops_db):
    gate = ApprovalGate(ops_db)
    rid = dispatch_fleet_or_charger_order(LANE, {"gate_id": "G4"}, ops_db=ops_db)["approval_request_id"]
    token = gate.approve(rid, "op")
    assert dispatch_fleet_or_charger_order(LANE, {"gate_id": "G4"}, approval_request_id=rid,
                                           approval_token="forged", ops_db=ops_db)["status"] == "REFUSED"
    ok = dispatch_fleet_or_charger_order(LANE, {"gate_id": "G4"}, approval_request_id=rid, approval_token=token, ops_db=ops_db)
    assert ok["status"] == "EXECUTED" and ok["execution_mode"] == "HUMAN_APPROVED"
    replay = dispatch_fleet_or_charger_order(LANE, {"gate_id": "G4"}, approval_request_id=rid, approval_token=token, ops_db=ops_db)
    assert replay["status"] == "REFUSED"  # single use
    assert executed_physical(ops_db) == 1


def test_token_bound_to_action_type(ops_db):
    gate = ApprovalGate(ops_db)
    rid = gate.request(LANE, {"gate_id": "G4"}, "test")
    token = gate.approve(rid, "op")
    res = dispatch_fleet_or_charger_order("SIGNAL_PRIORITY_OVERRIDE", {"gate_id": "G4"}, approval_request_id=rid,
                                          approval_token=token, ops_db=ops_db)
    assert res["status"] == "REFUSED"


def test_rejected_request_can_never_execute(ops_db):
    gate = ApprovalGate(ops_db)
    rid = gate.request(LANE, {"gate_id": "G4"}, "test")
    gate.reject(rid, "op", "not safe tonight")
    with pytest.raises(InvalidTransition):
        gate.approve(rid, "op")
    assert gate.verify_and_consume(rid, "anything", LANE)[0] is False
    assert gate.get(rid)["status"] == "REJECTED"


def test_invalid_transitions_and_non_physical_request(ops_db):
    gate = ApprovalGate(ops_db)
    rid = gate.request(LANE, {}, "x")
    gate.approve(rid, "op")
    with pytest.raises(InvalidTransition):
        gate.reject(rid, "op")
    with pytest.raises(ValueError):
        gate.request("REBALANCE", {}, "not physical")
    with pytest.raises(ValueError):
        gate.approve(gate.request(LANE, {}, "x"), "")  # operator identity required


def test_disguised_physical_payload_goes_to_gate(ops_db, snapshot):
    res = dispatch_fleet_or_charger_order("REBALANCE", {"orders": [], "lane_id": "RING-S-2"}, snapshot, ops_db=ops_db)
    assert res["status"] == "PENDING_APPROVAL" and res["executed"] is False
