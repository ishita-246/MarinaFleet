"""
Audit logger: every agent decision, code execution, guard result and human
decision is written to SQLite (audit_log table) AND mirrored to a JSONL file.

Fields: timestamp, tool, inputs, outputs, guard results, rationale, actor and
execution mode (autonomous vs human-approved vs blocked / pending).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config import AUDIT_JSONL_PATH, OPS_DB_PATH
from engine.ops_db import connect

ACTORS = {"AGENT_LLM", "CODE_PYTHON", "HUMAN_OPERATOR"}
MAX_FIELD_CHARS = 6000  # keep audit rows readable


def _dump(obj) -> str:
    s = json.dumps(obj, default=str, ensure_ascii=False)
    return s if len(s) <= MAX_FIELD_CHARS else s[:MAX_FIELD_CHARS] + '..."<truncated>"'


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class AuditLogger:
    def __init__(self, run_id: str, ops_db: Path | str = OPS_DB_PATH, jsonl_path: Path | str | None = AUDIT_JSONL_PATH):
        self.run_id = run_id
        self.ops_db = Path(ops_db)
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None

    def log(self, actor: str, tool: str, inputs=None, outputs=None, guard_results=None,
            rationale: str = "", execution_mode: str = "N/A", step: int | None = None) -> dict:
        if actor not in ACTORS:
            raise ValueError(f"actor must be one of {ACTORS}")
        row = dict(ts_utc=utc_now(), run_id=self.run_id, step=step, actor=actor, tool=tool,
                   inputs=inputs, outputs=outputs, guard_results=guard_results or [],
                   rationale=rationale, execution_mode=execution_mode)
        with connect(self.ops_db) as con:
            con.execute(
                "INSERT INTO audit_log (ts_utc, run_id, step, actor, tool, inputs_json, outputs_json, "
                "guard_results_json, rationale, execution_mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (row["ts_utc"], self.run_id, step, actor, tool, _dump(inputs), _dump(outputs),
                 _dump(guard_results or []), rationale, execution_mode))
        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(_dump(row) if len(_dump(row)) < 4 * MAX_FIELD_CHARS else json.dumps(
                    {k: row[k] for k in ("ts_utc", "run_id", "actor", "tool", "execution_mode")}))
                f.write("\n")
        return row


def fetch_audit(ops_db: Path | str = OPS_DB_PATH, run_id: str | None = None) -> list[dict]:
    with connect(ops_db) as con:
        if run_id:
            rows = con.execute("SELECT * FROM audit_log WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    return [dict(r) for r in rows]
