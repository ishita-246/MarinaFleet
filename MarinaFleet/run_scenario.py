"""
Headless event-night run (no UI). Useful for testing and for the viva.

    python run_scenario.py                       # mock LLM, clear weather, leave lane request pending
    python run_scenario.py --decision approve    # operator approves the lane reallocation
    python run_scenario.py --decision reject --weather rain
    python run_scenario.py --backend ollama      # needs `ollama serve` + `ollama pull qwen3:8b`
"""
from __future__ import annotations

import argparse
import sys

import config
from agent.agent_loop import resolve_approval, run_event_night, try_execute_without_approval


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MarinaFleet headless event-night scenario")
    ap.add_argument("--backend", default=config.LLM_BACKEND, choices=["mock", "ollama", "gemini", "groq"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--weather", default="clear", choices=["clear", "rain", "fog"])
    ap.add_argument("--stale-minutes", type=float, default=config.STALE_TELEMETRY_MINUTES)
    ap.add_argument("--decision", default="pending", choices=["pending", "approve", "reject"])
    a = ap.parse_args(argv)

    r = run_event_night(backend=a.backend, model=a.model, weather=a.weather, stale_minutes=a.stale_minutes)
    print(f"\n=== MarinaFleet run {r.run_id} | backend {r.backend_used} ({r.model}) | weather {r.weather} ===")
    if r.fallback_reason:
        print(f"NOTE: {r.fallback_reason}")
    print("\n--- AGENT vs CODE TRACE ---")
    for t in r.trace:
        print(f"[{t['step']:>2}] {t['actor']:<14} {t['action']:<45} {t['status']:<16} {t['detail'][:150]}")

    if r.plan:
        refusals = r.plan["charger_refusals"]
        if refusals:
            print("\n--- CHARGER REFUSALS (code-generated reasons, one example per refused hub) ---")
            examples = {}
            for x in refusals:  # prefer an example that was rerouted to a verified hub
                if x["refused_charger"] not in examples or (x["rerouted_to"] and not examples[x["refused_charger"]]["rerouted_to"]):
                    examples[x["refused_charger"]] = x
            print(f"  {len(refusals)} refusals, {sum(1 for x in refusals if x['rerouted_to'])} rerouted to verified hubs")
            for x in examples.values():
                print(f"  {x['vehicle_id']} ({x['soc_pct']}%): {x['reason']} -> rerouted to {x['rerouted_to']}")

    for req_id in r.pending_approvals:
        print(f"\n--- APPROVAL GATE: {req_id} is PENDING_APPROVAL ---")
        blocked = try_execute_without_approval(req_id, r.run_id, r.ops_db)
        print(f"  Attempt to execute WITHOUT token -> {blocked['status']}: {blocked['reasons'][0]}")
        if a.decision != "pending":
            out = resolve_approval(req_id, a.decision.upper(), "duty-operator-cli", r.run_id, r.ops_db, r.jsonl_path)
            print(f"  Operator decision -> {out['request']['status']}: {out['message']}")

    print("\n--- OPERATOR SITUATION REPORT ---")
    print(r.report)
    print("\n" + r.code_appendix)
    print(f"\nAudit rows written for this run: {len(r.audit_rows())} (ops DB: {r.ops_db}; JSONL: {r.jsonl_path})")
    return 0 if r.finished else 1


if __name__ == "__main__":
    sys.exit(main())
