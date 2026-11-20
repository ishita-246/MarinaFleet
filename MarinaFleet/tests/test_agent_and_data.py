"""End-to-end agent loop (Mock LLM), LLM client parsing / fallback, and dataset shape."""
import json
import sqlite3

import pytest

import config
from agent import llm_client
from agent.agent_loop import AGENT, CODE, resolve_approval, run_event_night, try_execute_without_approval
from agent.llm_client import LLMConfigError, get_llm_client, parse_action


def run(tmp_path, **kw):
    return run_event_night(backend=kw.pop("backend", "mock"), ops_db=tmp_path / "ops.sqlite",
                           jsonl_path=tmp_path / "audit.jsonl", **kw)


# ------------------------------------------------------------------ dataset
def test_dataset_shape():
    con = sqlite3.connect(config.DATA_DB_PATH)
    q = lambda s: con.execute(s).fetchone()[0]
    assert q("SELECT COUNT(*) FROM robotaxis") == 800
    assert q("SELECT COUNT(*) FROM buses") == 40
    assert q("SELECT COUNT(*) FROM metro_stations") == 2
    assert q("SELECT COUNT(*) FROM chargers WHERE status='OFFLINE'") >= 1
    assert q("SELECT fans_queued FROM gates WHERE gate_id='G4'") > 2 * q("SELECT AVG(fans_queued) FROM gates WHERE gate_id!='G4'")
    assert q("SELECT COUNT(*) FROM robotaxis WHERE consumption_kwh_per_km <= 0 OR soc_pct < 0 OR soc_pct > 100") == 0
    con.close()


def test_dataset_is_reproducible(tmp_path):
    from data.generate_data import generate
    generate(tmp_path / "a.sqlite", tmp_path / "a")
    generate(tmp_path / "b.sqlite", tmp_path / "b")
    assert (tmp_path / "a" / "robotaxis.csv").read_text() == (tmp_path / "b" / "robotaxis.csv").read_text()


# ------------------------------------------------------------------ agent loop
def test_end_to_end_workflow(tmp_path):
    r = run(tmp_path)
    assert r.finished and r.backend_used == "mock"
    tools = [t["action"] for t in r.trace if t["actor"] == AGENT]
    assert tools[0] == "Chose tool: get_egress_and_fleet_snapshot"
    assert tools[1] == "Chose tool: run_ev_dispatch_optimizer"
    for ot in ("RIDE_DISPATCH", "CHARGER_RESERVATION", "REBALANCE", "BUS_DEPLOYMENT", "METRO_ANNOUNCEMENT", "RIDER_GUIDANCE"):
        assert r.dispatch_results[ot]["status"] == "EXECUTED"
    # agent detected the Gate 4 surge and prioritised it
    assert r.plan["priority_gates"] == ["G4"]
    assert "G4" in r.report and "CH_JBR" in r.report and "CH_MEDIA" in r.report
    # lane change requested but NOT executed
    assert len(r.pending_approvals) == 1
    lane = r.dispatch_results["PICKUP_ZONE_LANE_REALLOCATION:G4"]
    assert lane["status"] == "PENDING_APPROVAL" and lane["executed"] is False


def test_trace_labels_agent_and_code(tmp_path):
    r = run(tmp_path)
    actors = {t["actor"] for t in r.trace}
    assert {AGENT, CODE} <= actors
    assert all(t["actor"] == CODE for t in r.trace if t["action"].startswith("Executed"))


def test_audit_log_written(tmp_path):
    r = run(tmp_path)
    rows = r.audit_rows()
    assert {"AGENT_LLM", "CODE_PYTHON"} <= {x["actor"] for x in rows}
    assert any(x["execution_mode"] == "AUTONOMOUS" for x in rows)
    assert any(x["execution_mode"] == "PENDING_APPROVAL" for x in rows)
    assert all(x["ts_utc"] and x["tool"] for x in rows)
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == len(rows) and json.loads(lines[0])["run_id"] == r.run_id


@pytest.mark.parametrize("decision,final", [("APPROVE", "EXECUTED"), ("REJECT", "REJECTED")])
def test_operator_decisions(tmp_path, decision, final):
    r = run(tmp_path)
    rid = r.pending_approvals[0]
    assert try_execute_without_approval(rid, r.run_id, r.ops_db)["status"] == "REFUSED"
    out = resolve_approval(rid, decision, "pytest-operator", r.run_id, r.ops_db, tmp_path / "audit.jsonl")
    assert out["request"]["status"] == final
    assert out["dispatch_result"]["status"] == ("EXECUTED" if decision == "APPROVE" else "REJECTED")
    human = [x for x in r.audit_rows() if x["actor"] == "HUMAN_OPERATOR"]
    assert len(human) == 1
    if decision == "APPROVE":
        assert any(x["execution_mode"] == "HUMAN_APPROVED" and x["actor"] == "CODE_PYTHON" for x in r.audit_rows())


def test_weather_flows_through_agent(tmp_path):
    r = run(tmp_path, weather="rain")
    assert r.snapshot.weather == "rain" and r.plan["weather"] == "rain"


def test_missing_api_key_falls_back_to_mock(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = run(tmp_path, backend="gemini")
    assert r.backend_used == "mock" and "GEMINI_API_KEY" in r.fallback_reason and r.finished


def test_backend_call_failure_falls_back_mid_run(tmp_path, monkeypatch):
    class Broken(llm_client.LLMClient):
        name = "broken"
        def complete(self, system, messages):
            raise llm_client.LLMCallError("simulated outage")
    monkeypatch.setattr("agent.agent_loop.get_llm_client", lambda b, m: Broken("x"))
    r = run(tmp_path, backend="ollama")
    assert r.finished and r.backend_used == "broken->mock" and "simulated outage" in r.fallback_reason


def test_malformed_llm_reply_is_rejected_by_code(tmp_path, monkeypatch):
    real = llm_client.MockLLMClient()
    calls = {"n": 0}
    class Flaky(llm_client.LLMClient):
        name = "flaky"
        def complete(self, system, messages):
            calls["n"] += 1
            return "I think we should dispatch everything!!" if calls["n"] == 1 else real.complete(
                system, [m for m in messages if not m["content"].startswith(("ERROR", "I think"))])
    monkeypatch.setattr("agent.agent_loop.get_llm_client", lambda b, m: Flaky("x"))
    r = run(tmp_path, backend="groq")
    assert r.finished and any(t["action"] == "Rejected malformed LLM reply" for t in r.trace)


def test_llm_cannot_execute_physical_action_directly(tmp_path, monkeypatch):
    """A 'rogue' model that immediately orders a lane reversal gets a pending approval, not an execution."""
    script = iter([
        '{"tool": "dispatch_fleet_or_charger_order", "arguments": {"order_type": "LANE_REVERSAL", "gate_id": "G4"}, "rationale": "go"}',
        '{"tool": "finish", "arguments": {"report": "done"}, "rationale": "x"}',
    ])
    class Rogue(llm_client.LLMClient):
        name = "rogue"
        def complete(self, system, messages):
            return next(script)
    monkeypatch.setattr("agent.agent_loop.get_llm_client", lambda b, m: Rogue("x"))
    r = run(tmp_path, backend="groq")
    res = r.dispatch_results["LANE_REVERSAL:G4"]
    assert res["executed"] is False and res["status"] == "PENDING_APPROVAL"


# ------------------------------------------------------------------ parsing / factory
def test_parse_action_variants():
    assert parse_action('{"tool": "finish", "arguments": {"report": "x"}}')["tool"] == "finish"
    assert parse_action('<think>hmm {"a":1}</think>```json\n{"tool":"finish","arguments":{}}\n```')["tool"] == "finish"
    assert parse_action('Sure! {"tool": "x", "arguments": {"s": "brace } inside"}} thanks')["arguments"]["s"] == "brace } inside"
    for bad in ["", "no json here", '{"arguments": {}}', '{"tool": "x", "arguments": [1]}']:
        with pytest.raises(ValueError):
            parse_action(bad)


def test_factory(monkeypatch):
    assert get_llm_client("mock").name == "mock"
    assert get_llm_client("ollama").name == "ollama"  # constructing does not need a server
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMConfigError):
        get_llm_client("groq")
    with pytest.raises(LLMConfigError):
        get_llm_client("gpt-17")
    monkeypatch.setenv("GROQ_API_KEY", "dummy")
    assert get_llm_client("groq").name == "groq"
