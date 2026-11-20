"""
User accounts for the operator console and the rider booking portal.

* Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes (never in plain text).
* Two roles: "rider" (book taxis) and "admin" (operator console, approval gate).
* 5 failed sign-ins lock the account for 5 minutes.
* Demo accounts are created on first use; the admin password can be set with
  MARINA_ADMIN_PASSWORD. Change both before any real deployment.

This is demo-grade authentication for a hackathon prototype (no sessions server,
no MFA, no password reset).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import OPS_DB_PATH
from engine.audit import utc_now
from engine.ops_db import connect

ROLES = ("rider", "admin")
ITERATIONS = 200_000
MAX_FAILED = 5
LOCK_MINUTES = 5
DEMO_ADMIN = ("admin", "Duty Operator")
DEMO_RIDER = ("rider@demo.ae", "Demo Rider", "RideDemo!2026")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def demo_admin_password() -> str:
    return os.getenv("MARINA_ADMIN_PASSWORD", "MarinaOps!2026")


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def create_user(username: str, password: str, role: str, display_name: str = "",
                ops_db: Path | str = OPS_DB_PATH) -> None:
    username = username.strip().lower()
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if role == "rider" and not EMAIL_RE.match(username):
        raise ValueError("Please enter a valid e-mail address.")
    salt = secrets.token_hex(16)
    with connect(ops_db) as con:
        if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("An account with this name already exists.")
        con.execute("INSERT INTO users (username, display_name, role, salt, pw_hash, created_utc) VALUES (?,?,?,?,?,?)",
                    (username, display_name or username, role, salt, _hash(password, salt), utc_now()))


def ensure_demo_users(ops_db: Path | str = OPS_DB_PATH) -> None:
    """Create the demo admin and demo rider if they do not exist yet."""
    with connect(ops_db) as con:
        existing = {r[0] for r in con.execute("SELECT username FROM users").fetchall()}
    if DEMO_ADMIN[0] not in existing:
        create_user(DEMO_ADMIN[0], demo_admin_password(), "admin", DEMO_ADMIN[1], ops_db)
    if DEMO_RIDER[0] not in existing:
        create_user(DEMO_RIDER[0], DEMO_RIDER[2], "rider", DEMO_RIDER[1], ops_db)


def register_rider(email: str, password: str, display_name: str, ops_db: Path | str = OPS_DB_PATH) -> dict:
    create_user(email, password, "rider", display_name.strip() or email, ops_db)
    return {"username": email.strip().lower(), "display_name": display_name.strip() or email, "role": "rider"}


def authenticate(username: str, password: str, role: str, ops_db: Path | str = OPS_DB_PATH) -> tuple[dict | None, str]:
    """Return (user, "") on success or (None, reason). A rider account cannot open the admin console and vice versa."""
    username = (username or "").strip().lower()
    now = datetime.now(timezone.utc)
    with connect(ops_db) as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            return None, "Unknown account or wrong password."
        if row["locked_until_utc"] and datetime.fromisoformat(row["locked_until_utc"]) > now:
            return None, f"Account locked after {MAX_FAILED} failed attempts. Try again in a few minutes."
        if not hmac.compare_digest(row["pw_hash"], _hash(password or "", row["salt"])):
            fails = (row["failed_attempts"] or 0) + 1
            lock = (now + timedelta(minutes=LOCK_MINUTES)).isoformat() if fails >= MAX_FAILED else None
            con.execute("UPDATE users SET failed_attempts=?, locked_until_utc=? WHERE username=?",
                        (0 if lock else fails, lock, username))
            return None, "Unknown account or wrong password."
        if row["role"] != role:
            return None, ("This is an operator account. Use the Operator sign-in." if row["role"] == "admin"
                          else "This account cannot open the operator console.")
        con.execute("UPDATE users SET failed_attempts=0, locked_until_utc=NULL WHERE username=?", (username,))
    return {"username": row["username"], "display_name": row["display_name"], "role": row["role"]}, ""


def require_role(user: dict | None, role: str) -> None:
    """Server-side role check used before privileged actions (e.g. approval decisions)."""
    if not user or user.get("role") != role:
        raise PermissionError(f"This action requires the '{role}' role.")
