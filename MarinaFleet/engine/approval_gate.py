"""
Human Operator Approval gate (HARD SAFETY RULE 4).

State machine, enforced in code and persisted in SQLite:

    PENDING_APPROVAL --approve()--> APPROVED --verify_and_consume(token)--> EXECUTED
           |
           +--------reject()-----> REJECTED   (terminal; can never execute)

* approve() returns a one-time random token; only its SHA-256 hash is stored.
* dispatch_fleet_or_charger_order() refuses any physical action unless
  verify_and_consume() accepts (request_id, token, action_type).
* A token works once, only for its own request and its own action type.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from pathlib import Path

from config import OPS_DB_PATH
from engine.audit import utc_now
from engine.guards import PHYSICAL_ACTIONS
from engine.ops_db import connect

PENDING, APPROVED, REJECTED, EXECUTED = "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTED"
ALLOWED_TRANSITIONS = {PENDING: {APPROVED, REJECTED}, APPROVED: {EXECUTED}, REJECTED: set(), EXECUTED: set()}


class InvalidTransition(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ApprovalGate:
    def __init__(self, ops_db: Path | str = OPS_DB_PATH):
        self.ops_db = Path(ops_db)

    # ------------------------------------------------------------------
    def request(self, action_type: str, payload: dict, justification: str, run_id: str = "") -> str:
        if action_type not in PHYSICAL_ACTIONS:
            raise ValueError(f"{action_type} is not a physical action; approval gate not applicable")
        request_id = f"APR-{uuid.uuid4().hex[:8].upper()}"
        with connect(self.ops_db) as con:
            con.execute("INSERT INTO approvals (request_id, run_id, action_type, payload_json, justification, "
                        "status, created_utc) VALUES (?,?,?,?,?,?,?)",
                        (request_id, run_id, action_type, json.dumps(payload, default=str), justification,
                         PENDING, utc_now()))
        return request_id

    def get(self, request_id: str) -> dict | None:
        with connect(self.ops_db) as con:
            row = con.execute("SELECT * FROM approvals WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
        d.pop("token_hash", None)  # never expose the hash
        return d

    def list(self, status: str | None = None, run_id: str | None = None) -> list[dict]:
        q, args = "SELECT request_id FROM approvals WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        if run_id:
            q += " AND run_id=?"
            args.append(run_id)
        with connect(self.ops_db) as con:
            ids = [r[0] for r in con.execute(q + " ORDER BY created_utc", args).fetchall()]
        return [self.get(i) for i in ids]

    # ------------------------------------------------------------------
    def _transition(self, con, request_id: str, new_status: str) -> dict:
        row = con.execute("SELECT * FROM approvals WHERE request_id=?", (request_id,)).fetchone()
        if not row:
            raise KeyError(f"Unknown approval request {request_id}")
        if new_status not in ALLOWED_TRANSITIONS[row["status"]]:
            raise InvalidTransition(f"{request_id}: {row['status']} -> {new_status} is not allowed")
        return dict(row)

    def approve(self, request_id: str, operator: str, note: str = "") -> str:
        """Human operator approves. Returns the one-time execution token."""
        if not operator:
            raise ValueError("operator name is required")
        token = secrets.token_urlsafe(24)
        with connect(self.ops_db) as con:
            con.execute("BEGIN IMMEDIATE")
            self._transition(con, request_id, APPROVED)
            con.execute("UPDATE approvals SET status=?, decided_utc=?, decided_by=?, decision_note=?, token_hash=? "
                        "WHERE request_id=?", (APPROVED, utc_now(), operator, note, _hash(token), request_id))
        return token

    def reject(self, request_id: str, operator: str, note: str = "") -> None:
        if not operator:
            raise ValueError("operator name is required")
        with connect(self.ops_db) as con:
            con.execute("BEGIN IMMEDIATE")
            self._transition(con, request_id, REJECTED)
            con.execute("UPDATE approvals SET status=?, decided_utc=?, decided_by=?, decision_note=? "
                        "WHERE request_id=?", (REJECTED, utc_now(), operator, note, request_id))

    def verify_and_consume(self, request_id: str | None, token: str | None, action_type: str) -> tuple[bool, str]:
        """Check the token; on success move APPROVED -> EXECUTED atomically (single use)."""
        if not request_id or not token:
            return False, "no approval token supplied"
        with connect(self.ops_db) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM approvals WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                return False, f"unknown approval request {request_id}"
            if row["action_type"] != action_type:
                return False, f"token is for {row['action_type']}, not {action_type}"
            if row["status"] != APPROVED:
                return False, f"request {request_id} is {row['status']}, not APPROVED"
            if not row["token_hash"] or not hmac.compare_digest(row["token_hash"], _hash(token)):
                return False, "invalid approval token"
            con.execute("UPDATE approvals SET status=?, executed_utc=? WHERE request_id=?",
                        (EXECUTED, utc_now(), request_id))
        return True, f"approved by {row['decided_by']}"
