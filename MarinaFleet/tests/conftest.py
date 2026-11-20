"""Shared pytest fixtures. Every test gets its own temporary ops DB and audit file."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402

if not config.DATA_DB_PATH.exists():  # generate the dataset once if missing
    from data.generate_data import generate

    generate()


@pytest.fixture()
def ops_db(tmp_path):
    return tmp_path / "ops.sqlite"


@pytest.fixture(scope="session")
def snapshot():
    from services.snapshot import get_egress_and_fleet_snapshot

    return get_egress_and_fleet_snapshot()


@pytest.fixture(scope="session")
def plan(snapshot):
    from services.optimizer import run_ev_dispatch_optimizer

    return run_ev_dispatch_optimizer(snapshot, priority_gates=["G4"])


@pytest.fixture(autouse=True)
def _isolate_runtime(tmp_path, monkeypatch):
    """Keep tests from writing into runtime/ (defaults point at tmp)."""
    monkeypatch.setattr(config, "OPS_DB_PATH", tmp_path / "default_ops.sqlite")
    monkeypatch.setattr(config, "AUDIT_JSONL_PATH", tmp_path / "default_audit.jsonl")
    monkeypatch.setattr(config, "LLM_BACKEND", "mock")
