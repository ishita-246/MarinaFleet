"""
Operations database (runtime state): audit log, approval requests, executed orders.

Kept separate from the scenario dataset so the dataset stays reproducible and
read-only. Default location: runtime/marina_ops.sqlite (override MARINA_OPS_DB).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    run_id TEXT NOT NULL,
    step INTEGER,
    actor TEXT NOT NULL,            -- AGENT_LLM | CODE_PYTHON | HUMAN_OPERATOR
    tool TEXT NOT NULL,
    inputs_json TEXT,
    outputs_json TEXT,
    guard_results_json TEXT,
    rationale TEXT,
    execution_mode TEXT             -- AUTONOMOUS | HUMAN_APPROVED | PENDING_APPROVAL | BLOCKED | REJECTED | N/A
);
CREATE TABLE IF NOT EXISTS approvals (
    request_id TEXT PRIMARY KEY,
    run_id TEXT,
    action_type TEXT NOT NULL,
    payload_json TEXT,
    justification TEXT,
    status TEXT NOT NULL,           -- PENDING_APPROVAL | APPROVED | REJECTED | EXECUTED
    created_utc TEXT NOT NULL,
    decided_utc TEXT,
    decided_by TEXT,
    decision_note TEXT,
    token_hash TEXT,
    executed_utc TEXT
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,      -- rider e-mail or admin user name
    display_name TEXT,
    role TEXT NOT NULL,             -- rider | admin
    salt TEXT NOT NULL,
    pw_hash TEXT NOT NULL,          -- PBKDF2-HMAC-SHA256
    created_utc TEXT NOT NULL,
    failed_attempts INTEGER DEFAULT 0,
    locked_until_utc TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
    booking_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    gate_id TEXT, pickup_node TEXT, dest_node TEXT, party_size INTEGER,
    vehicle_id TEXT, vehicle_eta_min REAL, est_pickup_min REAL, soc_at_charger_pct REAL,
    trip_km REAL, fare_aed REAL,
    status TEXT NOT NULL,           -- CONFIRMED | REDIRECTED | CANCELLED
    order_id TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    run_id TEXT,
    ts_utc TEXT NOT NULL,
    order_type TEXT NOT NULL,
    target_id TEXT,
    payload_json TEXT,
    status TEXT NOT NULL,           -- EXECUTED | BLOCKED | REFUSED
    execution_mode TEXT,
    reason TEXT
);
"""


@contextmanager
def connect(ops_db: Path | str):
    """Open the ops DB, create tables if needed, commit on success, roll back on error, always close."""
    path = Path(ops_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
