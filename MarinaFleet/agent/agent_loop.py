"""
MarinaFleet agent loop (structured-JSON tool calling).

    while not finished and steps < max:
        reply  = LLM(system prompt, conversation)          <- AGENT (LLM) decides
        action = parse_action(reply)                       <- CODE validates format
        result = toolbox.execute(action)                   <- CODE runs math / guards / orders
        conversation += [reply, OBSERVATION(result)]
        audit both steps

The LLM only ever chooses a tool, a strategy, priority gates and order types.
Plan items (vehicle ids, charger ids, ...) are taken from the optimizer's output
by code; numbers are never accepted from the model.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config
from agent.llm_client import (LLMCallError, LLMConfigError, MockLLMClient, get_llm_client,
                              observation_message, parse_action)
from agent.prompts import SYSTEM_PROMPT, TASK_PROMPT
from engine import battery_math, guards
from engine.approval_gate import ApprovalGate
from engine.audit import AuditLogger, fetch_audit
from services.dispatch import dispatch_fleet_or_charger_order
from services.optimizer import STRATEGIES, run_ev_dispatch_optimizer
from services.snapshot import get_egress_and_fleet_snapshot

AGENT, CODE, HUMAN = "AGENT (LLM)", "CODE (Python)", "HUMAN OPERATOR"
TOOL_NAMES = {"get_egress_and_fleet_snapshot", "run_ev_dispatch_optimizer", "dispatch_fleet_or_charger_order", "finish"}


@dataclass
class RunResult:
    run_id: str
    backend_requested: str
    backend_used: str
    model: str
    fallback_reason: str | None
    weather: str
    stale_minutes: float
    trace: list = field(default_factory=list)
    report: str = ""
    code_appendix: str = ""
    snapshot: object = None
    plan: dict | None = None
    dispatch_results: dict = field(default_factory=dict)
    pending_approvals: list = field(default_factory=list)
    finished: bool = False
    steps_used: int = 0
    ops_db: str = ""
    jsonl_path: str | None = None

    def audit_rows(self) -> list[dict]:
        return fetch_audit(self.ops_db, self.run_id)


# =============================================================================
class Toolbox:
    """Executes validated agent actions. Holds the snapshot and plan for this run."""

    def __init__(self, result: RunResult, audit: AuditLogger, data_db=None):
        self.r, self.audit, self.data_db = result, audit, data_db

    # ------------------------------------------------------------------
    def execute(self, tool: str, args: dict, rationale: str, step: int) -> tuple[dict, str, str]:
        """Return (observation for the LLM, short human summary, status label)."""
        if tool not in TOOL_NAMES:
            return {"error": f"unknown tool '{tool}'. Valid: {sorted(TOOL_NAMES)}"}, f"Rejected unknown tool {tool}", "ERROR"
        if tool == "get_egress_and_fleet_snapshot":
            return self._snapshot(args, rationale, step)
        if tool == "run_ev_dispatch_optimizer":
            return self._optimizer(args, rationale, step)
        if tool == "dispatch_fleet_or_charger_order":
            return self._dispatch(args, rationale, step)
        return {"ok": True}, "Agent finished", "DONE"

    def _snapshot(self, args, rationale, step):
        weather = args.get("weather", self.r.weather)
        if weather not in battery_math.WEATHER_PROFILES:
            weather = self.r.weather
        if weather != self.r.weather:  # the operator's weather setting wins over the model's guess
            weather = self.r.weather
        snap = get_egress_and_fleet_snapshot(self.data_db, weather=weather, stale_minutes=self.r.stale_minutes)
        self.r.snapshot = snap
        obs = snap.to_llm_summary()
        surge = [a["gate_id"] for a in snap.alerts if a["type"] == "CROWD_SURGE"]
        bad = [a["charger_id"] for a in snap.alerts if a["type"].startswith("CHARGER_")]
        self.audit.log("CODE_PYTHON", "get_egress_and_fleet_snapshot", {"weather": weather}, obs,
                       [{"guard": "charger_freshness", "chargers_refused": bad}], rationale, "N/A", step)
        return obs, f"Snapshot loaded ({weather}). Surge flags: {surge or 'none'}. Untrusted chargers: {bad or 'none'}", "OK"

    def _optimizer(self, args, rationale, step):
        if self.r.snapshot is None:
            return {"error": "call get_egress_and_fleet_snapshot first"}, "Refused: no snapshot yet", "ERROR"
        strategy = args.get("strategy") if args.get("strategy") in STRATEGIES else "surge_first_battery_safe"
        pg = args.get("priority_gates") or []
        pg = [str(g).upper() for g in (pg if isinstance(pg, list) else [pg])]
        plan = run_ev_dispatch_optimizer(self.r.snapshot, priority_gates=pg, strategy=strategy)
        self.r.plan = plan
        obs = optimizer_observation(plan)
        gs = plan["guard_summary"]
        self.audit.log("CODE_PYTHON", "run_ev_dispatch_optimizer", {"strategy": strategy, "priority_gates": plan["priority_gates"]},
                       obs, [{"guard": "battery_reserve_15pct", "validated": gs["assignments_validated"],
                              "blocked": gs["dispatches_blocked_by_15pct_guard"], "validation_failures": gs["validation_failures"]},
                             {"guard": "charger_freshness", "refused": gs["chargers_refused"]}],
                       rationale, "N/A", step)
        c = obs["counts"]
        return obs, (f"Optimizer ({strategy}, priority {plan['priority_gates']}): {c['ride_assignments']} safe rides, "
                     f"{c['blocked_dispatches']} unsafe dispatches blocked, {c['charger_orders']} charger orders, "
                     f"{c['charger_refusals']} stale/offline routings refused"), "OK"

    def _dispatch(self, args, rationale, step):
        ot = str(args.get("order_type", "")).upper()
        just = str(args.get("justification", rationale))[:600]
        kind = guards.classify_order(ot, {})
        if kind == "AUTONOMOUS" and self.r.plan is None:
            return {"error": "run_ev_dispatch_optimizer first; there is no plan to execute"}, "Refused: no plan yet", "ERROR"
        if kind == "AUTONOMOUS" and ot in self.r.dispatch_results:
            return {"order_type": ot, "status": "NOOP", "note": "already executed this cycle"}, f"{ot} already done", "NOOP"

        payload = self._payload_for(ot, args)
        res = dispatch_fleet_or_charger_order(ot, payload, self.r.snapshot, justification=just,
                                              run_id=self.r.run_id, ops_db=self.r.ops_db)
        self.r.dispatch_results[ot if kind != "PHYSICAL" else f"{ot}:{payload.get('gate_id')}"] = res
        mode = res.get("execution_mode", "BLOCKED")
        self.audit.log("CODE_PYTHON", "dispatch_fleet_or_charger_order", {"order_type": ot, "items": _count_items(payload),
                       "gate_id": payload.get("gate_id")},
                       {k: res.get(k) for k in ("status", "accepted", "rejected", "approval_request_id", "reasons")},
                       res.get("guard_results"), just, mode, step)
        obs = {"order_type": ot, "status": res["status"], "execution_mode": mode,
               "accepted": res.get("accepted"), "rejected": res.get("rejected"),
               "approval_request_id": res.get("approval_request_id"), "reasons": (res.get("reasons") or [])[:3]}
        if res["status"] == "PENDING_APPROVAL":
            self.r.pending_approvals.append(res["approval_request_id"])
            summary = f"{ot} NOT executed: routed to Human Operator Approval gate ({res['approval_request_id']})"
        elif kind == "PHYSICAL":
            summary = f"{ot} refused: {obs['reasons'][0] if obs['reasons'] else ''}"
        else:
            summary = f"{ot}: {res['status']} - {res.get('accepted', 0)} executed, {res.get('rejected', 0)} blocked by guards"
        return obs, summary, res["status"]

    def _payload_for(self, ot: str, args: dict) -> dict:
        """Build the order payload from the CODE plan (ids only; numbers recomputed by dispatch)."""
        p = self.r.plan or {}
        if ot == "RIDE_DISPATCH":
            return {"assignments": [{"vehicle_id": a["vehicle_id"], "request_id": a["request_id"]} for a in p["ride_assignments"]]}
        if ot == "CHARGER_RESERVATION":
            return {"orders": [{"vehicle_id": o["vehicle_id"], "charger_id": o["charger_id"]} for o in p["charger_orders"]]}
        if ot == "REBALANCE":
            return {"orders": [{"vehicle_id": o["vehicle_id"], "to_node": o["to_node"], "gate_id": o["gate_id"]}
                               for o in p["rebalance_orders"]]}
        if ot == "BUS_DEPLOYMENT":
            return {"orders": p["multimodal"]["bus_orders"]}
        if ot == "METRO_ANNOUNCEMENT":
            return {"orders": p["multimodal"]["metro_announcements"]}
        if ot == "RIDER_GUIDANCE":
            return {"orders": p["rider_guidance"]}
        if ot == "MOBILE_CHARGER_REQUEST":
            return {"orders": p["mobile_charger_requests"]}
        if ot in guards.PHYSICAL_ACTIONS:
            gid = str(args.get("gate_id", "")).upper()
            prop = next((x for x in p.get("lane_proposals", []) if x["gate_id"] == gid), None)
            return dict(prop) if prop else {"gate_id": gid, "action_type": ot}
        return {}


def _count_items(payload: dict) -> int:
    return len(payload.get("assignments", payload.get("orders", []))) if payload else 0


def optimizer_observation(plan: dict) -> dict:
    """Compact code-produced summary of the plan for the LLM (no raw lists of hundreds of items)."""
    refusal_summary = {}
    for x in plan["charger_refusals"]:
        s = refusal_summary.setdefault(x["refused_charger"], {"vehicles_refused": 0, "code": x["refused_code"], "reason": x["reason"]})
        s["vehicles_refused"] += 1
    return {
        "strategy": plan["strategy"], "priority_gates": plan["priority_gates"], "weather": plan["weather"],
        "counts": {
            "ride_assignments": len(plan["ride_assignments"]), "blocked_dispatches": len(plan["blocked_dispatches"]),
            "battery_locked_vehicles": plan["guard_summary"]["battery_locked_vehicles"],
            "unserved_requests": len(plan["unserved_requests"]), "charger_orders": len(plan["charger_orders"]),
            "charger_refusals": len(plan["charger_refusals"]),
            "charger_refusals_rerouted": sum(1 for x in plan["charger_refusals"] if x["rerouted_to"]),
            "charger_waitlist": len(plan["charger_waitlist"]),
            "mobile_charger_requests": len(plan["mobile_charger_requests"]),
            "rebalance_orders": len(plan["rebalance_orders"]), "bus_orders": len(plan["multimodal"]["bus_orders"]),
            "metro_announcements": len(plan["multimodal"]["metro_announcements"]),
        },
        "kpis": plan["kpis"],
        "sample_assignments": plan["ride_assignments"][:3],
        "sample_blocked_dispatches": plan["blocked_dispatches"][:3],
        "charger_refusal_summary": refusal_summary,
        "rider_guidance": [g["message"] for g in plan["rider_guidance"]],
        "lane_proposals": plan["lane_proposals"],
    }


def code_kpi_appendix(plan: dict | None) -> str:
    """KPI table generated by Python (not by the LLM) appended to every report."""
    if not plan:
        return "No optimizer plan was produced in this run."
    o, b, g = plan["kpis"]["optimized"], plan["kpis"]["baseline"], plan["kpis"]["battery_aware_greedy"]
    rows = [("Mean rider pickup wait (min)", b["mean_wait_min"], g["mean_wait_min"], o["mean_wait_min"]),
            ("P90 rider pickup wait (min)", b["p90_wait_min"], g["p90_wait_min"], o["p90_wait_min"]),
            ("Pickup deadhead (km)", b["pickup_deadhead_km"], g["pickup_deadhead_km"], o["pickup_deadhead_km"]),
            ("Wasted km to dead/stale hubs", b["wasted_km"], "-", o["wasted_km"]),
            ("Stranded vehicles", b["stranded_vehicles"], 0, o["stranded_vehicles"]),
            ("Dispatches below 15% reserve", b["reserve_violations"], 0, o["reserve_violations"]),
            ("Failed charger attempts", b["failed_charger_attempts"], "-", o["failed_charger_attempts"]),
            ("Peak gate pickup-queue wait (min)", b["gate4_style_peak_queue_wait_min"], "-", o["gate4_style_peak_queue_wait_min"])]
    out = ["KPI APPENDIX (computed by Python, not the LLM)",
           f"{'Metric':<36}{'Naive':>10}{'Greedy+15%':>12}{'MarinaFleet':>13}"]
    out += [f"{r[0]:<36}{str(r[1]):>10}{str(r[2]):>12}{str(r[3]):>13}" for r in rows]
    out.append(f"If the lane reallocation is approved, peak queue wait -> {o['peak_queue_wait_if_lane_approved_min']} min.")
    return "\n".join(out)


# =============================================================================
def run_event_night(backend: str | None = None, model: str | None = None, weather: str = "clear",
                    stale_minutes: float | None = None, data_db: Path | str | None = None,
                    ops_db: Path | str | None = None, jsonl_path: Path | str | None = "default",
                    max_steps: int | None = None) -> RunResult:
    """Run the full event-night orchestration loop once and return everything the UI needs."""
    backend = (backend or config.LLM_BACKEND).lower()
    stale_minutes = config.STALE_TELEMETRY_MINUTES if stale_minutes is None else float(stale_minutes)
    battery_math.weather_profile(weather)  # validate early
    ops_db = str(ops_db or config.OPS_DB_PATH)
    jsonl = config.AUDIT_JSONL_PATH if jsonl_path == "default" else jsonl_path
    run_id = f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    audit = AuditLogger(run_id, ops_db, jsonl)

    fallback_reason = None
    try:
        llm = get_llm_client(backend, model)
    except LLMConfigError as exc:
        if not config.LLM_FALLBACK_TO_MOCK:
            raise
        fallback_reason = f"{backend} unavailable ({exc}); using deterministic Mock LLM"
        llm = MockLLMClient()

    result = RunResult(run_id=run_id, backend_requested=backend, backend_used=llm.name, model=str(llm.model),
                       fallback_reason=fallback_reason, weather=weather, stale_minutes=stale_minutes,
                       ops_db=ops_db, jsonl_path=str(jsonl) if jsonl else None)
    tools = Toolbox(result, audit, data_db)
    audit.log("CODE_PYTHON", "run_start", {"backend": backend, "weather": weather, "stale_minutes": stale_minutes},
              {"backend_used": llm.name, "fallback_reason": fallback_reason}, rationale="event-night run started")
    if fallback_reason:
        result.trace.append(_t(0, CODE, "Backend fallback", fallback_reason, "WARN"))

    messages = [{"role": "user", "content": TASK_PROMPT.format(weather=weather, stale=stale_minutes)}]
    max_steps = max_steps or config.AGENT_MAX_STEPS
    for step in range(1, max_steps + 1):
        result.steps_used = step
        # ---------------- AGENT decides ----------------
        try:
            reply = llm.complete(SYSTEM_PROMPT, messages)
        except (LLMCallError, LLMConfigError) as exc:
            if not config.LLM_FALLBACK_TO_MOCK or isinstance(llm, MockLLMClient):
                raise
            result.fallback_reason = f"{llm.name} call failed ({exc}); switched to Mock LLM mid-run"
            result.trace.append(_t(step, CODE, "Backend fallback", result.fallback_reason, "WARN"))
            llm = MockLLMClient()
            result.backend_used = f"{result.backend_used}->mock"
            result.model = f"{result.model}->{llm.model}"
            reply = llm.complete(SYSTEM_PROMPT, messages)
        try:
            action = parse_action(reply)
        except ValueError as exc:
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"ERROR: {exc}. Reply with ONE JSON object as specified."}]
            result.trace.append(_t(step, CODE, "Rejected malformed LLM reply", str(exc), "ERROR"))
            audit.log("CODE_PYTHON", "parse_action", {"reply": reply[:500]}, {"error": str(exc)}, step=step,
                      execution_mode="BLOCKED")
            continue
        tool, args, rationale = action["tool"], action.get("arguments", {}), str(action.get("rationale", ""))
        result.trace.append(_t(step, AGENT, f"Chose tool: {tool}", f"{_fmt_args(args)}  |  rationale: {rationale}", "DECIDED"))
        audit.log("AGENT_LLM", "llm_decision", {"tool": tool, "arguments": _short_args(args)},
                  {"thought": str(action.get("thought", ""))[:500]}, rationale=rationale, step=step)

        # ---------------- CODE executes ----------------
        if tool == "finish":
            result.report = str(args.get("report", "")).strip() or "(agent returned an empty report)"
            result.finished = True
            result.trace.append(_t(step, AGENT, "Wrote operator situation report", result.report[:200] + "...", "DONE"))
            break
        obs, summary, status = tools.execute(tool, args, rationale, step)
        result.trace.append(_t(step, CODE, f"Executed {tool}", summary, status))
        messages += [{"role": "assistant", "content": reply}, observation_message(tool, obs)]

    if not result.finished:
        result.report = ("Agent did not call finish within the step limit. Code-generated status follows; "
                         "check the trace for the last completed step.")
        result.trace.append(_t(result.steps_used, CODE, "Step limit reached", "fallback report generated", "WARN"))
    result.code_appendix = code_kpi_appendix(result.plan)
    audit.log("AGENT_LLM", "operator_report", None, {"report": result.report}, rationale="final situation report",
              step=result.steps_used)
    audit.log("CODE_PYTHON", "run_end", None, {"pending_approvals": result.pending_approvals,
                                                "orders": {k: v.get("status") for k, v in result.dispatch_results.items()}})
    return result


# =============================================================================
def resolve_approval(request_id: str, decision: str, operator: str, run_id: str,
                     ops_db: Path | str | None = None, jsonl_path: Path | str | None = "default", note: str = "") -> dict:
    """HUMAN step: Approve -> token -> dispatch executes with token. Reject -> terminal, nothing physical changes."""
    ops_db = str(ops_db or config.OPS_DB_PATH)
    jsonl = config.AUDIT_JSONL_PATH if jsonl_path == "default" else jsonl_path
    gate, audit = ApprovalGate(ops_db), AuditLogger(run_id, ops_db, jsonl)
    req = gate.get(request_id)
    if req is None:
        raise KeyError(request_id)
    decision = decision.upper()
    if decision == "APPROVE":
        token = gate.approve(request_id, operator, note)
        audit.log("HUMAN_OPERATOR", "approval_decision", {"request_id": request_id}, {"decision": "APPROVED"},
                  rationale=note or "operator approved", execution_mode="HUMAN_APPROVED")
        res = dispatch_fleet_or_charger_order(req["action_type"], req["payload"], approval_request_id=request_id,
                                              approval_token=token, run_id=run_id, ops_db=ops_db)
        audit.log("CODE_PYTHON", "dispatch_fleet_or_charger_order", {"order_type": req["action_type"], "request_id": request_id},
                  {"status": res["status"]}, res["guard_results"], "executed with operator token", res["execution_mode"])
        msg = (f"APPROVED by {operator}. Code verified the one-time token and EXECUTED {req['action_type']} "
               f"at {req['payload'].get('pickup_zone', req['payload'].get('gate_id'))}.")
    elif decision == "REJECT":
        gate.reject(request_id, operator, note)
        audit.log("HUMAN_OPERATOR", "approval_decision", {"request_id": request_id}, {"decision": "REJECTED"},
                  rationale=note or "operator rejected", execution_mode="REJECTED")
        res = {"status": "REJECTED", "executed": False}
        msg = (f"REJECTED by {operator}. Lanes and signals stay unchanged. The autonomous mitigations already "
               f"executed (rider walking guidance, feeder buses, metro announcements) remain the plan.")
    else:
        raise ValueError("decision must be APPROVE or REJECT")
    return {"request_id": request_id, "decision": decision, "message": msg, "dispatch_result": res,
            "request": gate.get(request_id)}


def try_execute_without_approval(request_id: str, run_id: str, ops_db: Path | str | None = None) -> dict:
    """Demo helper: attempt to execute a pending physical action with no token -> must be refused."""
    ops_db = str(ops_db or config.OPS_DB_PATH)
    req = ApprovalGate(ops_db).get(request_id)
    return dispatch_fleet_or_charger_order(req["action_type"], req["payload"], approval_request_id=request_id,
                                           approval_token=None, run_id=run_id, ops_db=ops_db)


# ----------------------------------------------------------------------------- helpers
def _t(step, actor, action, detail, status):
    return {"step": step, "actor": actor, "action": action, "detail": detail, "status": status}


def _short_args(args: dict) -> dict:
    return {k: (v[:300] + "..." if isinstance(v, str) and len(v) > 300 else v) for k, v in args.items()}


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v if not isinstance(v, str) or len(v) < 80 else v[:80] + '...'}" for k, v in args.items())
