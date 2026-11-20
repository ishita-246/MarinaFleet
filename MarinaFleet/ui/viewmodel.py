"""
View-model: turns the Python results (snapshot, optimiser plan, agent trace, approvals) into plain display data.

No safety or battery logic lives here. This module only picks fields, counts things for display, formats text, and lays
out the schematic gate map. Every number shown to the operator is read from the Python outputs; the few differences
(e.g. "deadhead km saved vs Greedy+15%") are display subtraction of two Python-computed KPIs.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone

import config
from agent.agent_loop import AGENT, CODE, HUMAN

# ------------------------------------------------------------------------------------------------- clock
def event_clock(snap) -> dict:
    """'T+18 min of 90' computed from the scenario metadata (egress start, snapshot time, target clear time)."""
    m = snap.meta
    start = datetime.fromisoformat(m["egress_start_utc"].replace("Z", "+00:00"))
    t_plus = int(round((snap.snapshot_time - start).total_seconds() / 60))
    try:
        from zoneinfo import ZoneInfo
        local = snap.snapshot_time.astimezone(ZoneInfo(m.get("timezone", "Asia/Dubai")))
    except Exception:  # tzdata missing: Dubai is a fixed UTC+4
        local = snap.snapshot_time.astimezone(timezone(timedelta(hours=4)))
    return {"t_plus": t_plus, "total": int(m["target_clear_minutes"]), "local": local.strftime("%H:%M"),
            "event": m.get("event_name", "")}


# ------------------------------------------------------------------------------------------ system status
def system_status(snap, plan, pending: int) -> dict:
    """One pill for the top bar: what should the operator worry about first?"""
    untrusted = [c for c in snap.chargers if c["verdict"] in ("STALE", "OFFLINE")]
    surge = [g for g in snap.gates if g["status"] == "SURGE"]
    if pending:
        return {"tone": "accent", "icon_name": "lock", "label": f"{pending} approval pending"}
    if surge or untrusted:
        bits = []
        if surge:
            bits.append(f"{len(surge)} surge")
        if untrusted:
            bits.append(f"{len(untrusted)} hub{'s' if len(untrusted) > 1 else ''} untrusted")
        return {"tone": "warn", "icon_name": "alert", "label": "Guards active", "detail": ", ".join(bits)}
    return {"tone": "ok", "icon_name": "check-circle", "label": "All systems nominal"}


# ------------------------------------------------------------------------------------------------- KPIs
def charger_counts(snap) -> dict:
    c = Counter(x["verdict"] for x in snap.chargers)
    return {"healthy": c.get("VERIFIED", 0), "stale": c.get("STALE", 0), "offline": c.get("OFFLINE", 0),
            "other": sum(v for k, v in c.items() if k not in ("VERIFIED", "STALE", "OFFLINE"))}


def kpis(snap, plan) -> list[dict]:
    """Six KPI cards. Agent-derived ones are `pending` until the scenario has been run."""
    meta = snap.meta
    total, remaining = int(meta["total_fans"]), int(meta["fans_remaining"])
    fs = snap.fleet_summary()
    active = fs["by_status"].get("en_route", 0) + fs["by_status"].get("occupied", 0)
    low = fs["idle_below_15pct"] + fs["idle_15_to_30pct"]
    ch = charger_counts(snap)
    out = [
        {"label": "Fans remaining", "icon_name": "users", "tone": "info", "value": f"{remaining:,}", "unit": "",
         "sub": f"{remaining / total:.0%} of {total:,} still on site"},
        {"label": "Avg pickup wait", "icon_name": "clock", "tone": "brand", "pending": plan is None},
        {"label": "Robotaxis active", "icon_name": "car", "tone": "brand", "value": f"{active}", "unit": f"of {fs['robotaxis_total']}",
         "sub": f"{fs['by_status'].get('occupied', 0)} on trip · {fs['by_status'].get('en_route', 0)} en route"
                + (f" · +{len(plan['ride_assignments'])} dispatched" if plan else "")},
        {"label": "Low battery", "icon_name": "battery-low", "tone": "warn" if low else "ok", "value": f"{low}", "unit": "idle",
         "sub": f"{fs['idle_below_15pct']} below the 15% reserve (locked)"},
        {"label": "Charger hubs", "icon_name": "plug", "tone": "danger" if ch["offline"] else ("warn" if ch["stale"] else "ok"),
         "split": [(ch["healthy"], "ok"), (ch["stale"], "warn"), (ch["offline"], "danger")],
         "sub": "healthy · stale · offline"},
        {"label": "Deadhead saved", "icon_name": "route", "tone": "brand", "pending": plan is None},
    ]
    if plan:
        o, g = plan["kpis"]["optimized"], plan["kpis"]["battery_aware_greedy"]
        d_wait = o["mean_wait_min"] - g["mean_wait_min"]
        out[1].update(value=f"{o['mean_wait_min']:.1f}", unit="min", sub=f"P90 {o['p90_wait_min']:.1f} min · vs Greedy+15%",
                      delta={"text": f"{d_wait:+.1f} min", "good": d_wait <= 0})
        saved = g["pickup_deadhead_km"] - o["pickup_deadhead_km"]
        pct = saved / g["pickup_deadhead_km"] if g["pickup_deadhead_km"] else 0.0
        out[5].update(value=f"{saved:,.0f}", unit="km", sub="empty pickup km vs Greedy+15%",
                      delta={"text": f"{pct:.1%} less", "good": saved >= 0})
    else:
        out[1].update(value="--", unit="min", sub="Run the scenario to compute")
        out[5].update(value="--", unit="km", sub="Run the scenario to compute")
    return out


# ------------------------------------------------------------------------------------------ surge banner
def surge_banner(snap, plan) -> dict | None:
    surge = [g for g in snap.gates if g["status"] == "SURGE"]
    if not surge:
        return None
    g = max(surge, key=lambda x: x["surge_ratio"])
    lane = (plan or {}).get("lane_proposals") or []
    after = next((p["wait_after_min"] for p in lane if p["gate_id"] == g["gate_id"]), None)
    return {"gate": g["name"], "gate_id": g["gate_id"], "fans": g["fans_queued"], "ratio": g["surge_ratio"],
            "wait": g["est_pickup_wait_min"], "throughput": g["effective_throughput_vpm"], "after": after,
            "managed": (plan or {}).get("kpis", {}).get("optimized", {}).get("gate4_style_peak_queue_wait_min"),
            "managed_lane": (plan or {}).get("kpis", {}).get("optimized", {}).get("peak_queue_wait_if_lane_approved_min")}


# ----------------------------------------------------------------------------------------- trace timeline
def _split_detail(detail: str) -> tuple[str, str]:
    if "  |  rationale: " in detail:
        args, why = detail.split("  |  rationale: ", 1)
        return args, why
    return "", detail


def _guard_items(snap, plan) -> list[dict]:
    items: list[dict] = []
    stale_min = snap.stale_minutes
    for b in (plan.get("blocked_dispatches") or [])[:2]:
        items.append({
            "kind": "guard", "title": f"Dispatch {b['vehicle_id']} blocked: 15% battery reserve",
            "reason": f"Projected SoC {b['projected_soc_pct']:.1f}% < {config.BATTERY_RESERVE_PCT:.0f}% reserve",
            "detail": b["reason"], "foot": "Blocked by code, not by the LLM.", "status": "BLOCKED", "step": None})
    extra = len(plan.get("blocked_dispatches") or []) - 2
    if extra > 0:
        items[-1]["foot"] += f" {extra} more unsafe dispatch(es) blocked this cycle."
    refusals = plan.get("charger_refusals") or []
    for c in snap.chargers:
        if c["verdict"] not in ("STALE", "OFFLINE"):
            continue
        mine = [r for r in refusals if r["refused_charger"] == c["charger_id"]]
        rer = sum(1 for r in mine if r["rerouted_to"])
        if c["verdict"] == "STALE":
            reason = f"Telemetry {c['telemetry_age_min']:.0f} min old > {stale_min:.0f} min threshold"
        else:
            reason = f"Node OFFLINE, last telemetry {c['telemetry_age_min']:.0f} min ago"
        items.append({"kind": "guard", "title": f"Charger hub {c['charger_id'].replace('CH_', '')} refused ({c['verdict'].lower()})",
                      "reason": reason, "detail": c["verdict_reason"],
                      "foot": f"Routing blocked by code, not by the LLM. {len(mine)} routing(s) refused, {rer} rerouted to verified hubs.",
                      "status": "REFUSED", "step": None})
    return items


def trace_items(result, decisions: dict, blocked_attempts: dict) -> list[dict]:
    """Ordered timeline: AGENT / CODE / BLOCKED-BY-GUARD / HUMAN items, each carrying the code-generated reason."""
    items: list[dict] = []
    plan, snap = result.plan or {}, result.snapshot
    for t in result.trace:
        if t["actor"] == AGENT:
            args, why = _split_detail(t["detail"])
            items.append({"kind": "agent", "title": t["action"], "detail": why, "args": args, "status": t["status"], "step": t["step"]})
        elif t["actor"] == CODE:
            items.append({"kind": "code", "title": t["action"], "detail": t["detail"], "status": t["status"], "step": t["step"]})
            if "run_ev_dispatch_optimizer" in t["action"] and plan:
                items.extend(_guard_items(snap, plan))
        else:
            items.append({"kind": "human", "title": t["action"], "detail": t["detail"], "status": t["status"], "step": t["step"]})
    for rid, att in blocked_attempts.items():
        items.append({"kind": "guard", "title": f"Execution without approval refused ({rid})",
                      "reason": att["reasons"][0], "detail": "", "foot": "Blocked by code, not by the LLM.", "status": "REFUSED", "step": None})
    for rid, d in decisions.items():
        verb = "approved" if d["decision"] == "APPROVE" else "rejected"
        items.append({"kind": "human", "title": f"Operator {verb} {rid}",
                      "detail": d["message"], "status": d["request"]["status"], "step": None})
    return items


def trace_counts(items: list[dict]) -> dict:
    c = Counter(i["kind"] for i in items)
    return {"agent": c.get("agent", 0), "code": c.get("code", 0) + c.get("guard", 0), "human": c.get("human", 0), "guards": c.get("guard", 0)}


# --------------------------------------------------------------------------------------------- ROI data
def roi(plan: dict) -> dict:
    k = plan["kpis"]
    return {"naive": k["baseline"], "greedy": k["battery_aware_greedy"], "marina": k["optimized"]}


# ----------------------------------------------------------------------------------------- operations map
W, H = 600.0, 570.0
CX, CY = 300.0, 290.0          # schematic centre in SVG units
R_GATE, R_PZ, R_NODE = 66.0, 156.0, 222.0     # gate ring, pickup-zone chips, staging + metro nodes
HUB_RX, HUB_RY = 262.0, 214.0                 # charger hubs sit on an ellipse so labels never leave the canvas
MIN_BEARING_GAP = 26.0         # degrees between outer charger markers so labels never collide
ANCHOR_CLEARANCE = 18.0        # degrees a hub keeps away from a staging / metro node


def _bearing(x: float, y: float) -> float:
    return math.degrees(math.atan2(y, x))


def _polar(r: float, deg: float, ry: float | None = None) -> tuple[float, float]:
    a = math.radians(deg)
    return CX + r * math.cos(a), CY - (ry if ry is not None else r) * math.sin(a)


def _angdiff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _relax(bearings: dict[str, float], gap: float, anchors: list[float]) -> dict[str, float]:
    """Give every hub a free slot on the outer ellipse: as close to its true compass bearing as possible, at least `gap`
    degrees from its neighbours and `ANCHOR_CLEARANCE` degrees from the staging / metro nodes, so labels never collide."""
    slots = [d for d in range(-180, 180, 4) if all(_angdiff(d, a) >= ANCHOR_CLEARANCE for a in anchors)]
    placed: dict[str, float] = {}
    for key in sorted(bearings, key=lambda k: bearings[k]):
        want = bearings[key]
        ok = [d for d in slots if all(_angdiff(d, v) >= gap for v in placed.values())]
        placed[key] = min(ok, key=lambda d: _angdiff(d, want)) if ok else want
    return placed


def map_model(snap, plan) -> dict:
    """Schematic (not to scale) stadium-precinct layout: gates on the ring, pickup zones outside, hubs by compass bearing."""
    inbound = Counter(a["gate_id"] for a in (plan or {}).get("ride_assignments", []))
    gates = []
    for g in snap.gates:
        n = snap.nodes[g["gate_id"]]
        deg = _bearing(n["x_km"], n["y_km"])
        gx, gy = _polar(R_GATE, deg)
        px, py = _polar(R_PZ, deg)
        gates.append({"id": g["gate_id"], "name": g["name"], "x": gx, "y": gy, "pz": g["pickup_zone_node"], "px": px, "py": py,
                      "deg": deg, "status": g["status"], "ratio": g["surge_ratio"], "queue": g["est_pickup_wait_min"],
                      "fans": g["fans_queued"], "inbound": inbound.get(g["gate_id"], 0)})
    precinct, anchors = [], []
    for nid in ("STAGE_E", "STAGE_W", "METRO_N", "METRO_S"):
        n = snap.nodes[nid]
        deg = _bearing(n["x_km"], n["y_km"])
        anchors.append(deg)
        x, y = _polar(R_NODE, deg)
        entry = {"id": nid, "kind": "metro" if nid.startswith("METRO") else "staging", "x": x, "y": y, "name": n["name"], "deg": deg}
        if nid.startswith("METRO"):
            entry["load"] = next(m for m in snap.metro if m["station_id"] == nid)["current_load_pct"]
        precinct.append(entry)
    outer = {}
    for c in snap.chargers:
        if not c["node_id"].startswith("STAGE"):
            n = snap.nodes[c["node_id"]]
            outer[c["charger_id"]] = _bearing(n["x_km"], n["y_km"])
    placed = _relax(outer, MIN_BEARING_GAP, anchors)
    hubs = []
    for c in snap.chargers:
        if c["charger_id"] in placed:
            x, y = _polar(HUB_RX, placed[c["charger_id"]], HUB_RY)
            n = snap.nodes[c["node_id"]]
            dist = math.hypot(n["x_km"], n["y_km"])
        else:  # the venue hub sits at the east staging node
            ref = next(p for p in precinct if p["id"] == c["node_id"])
            x, y, dist = ref["x"], ref["y"], 0.0
        hubs.append({"id": c["charger_id"], "short": c["charger_id"].replace("CH_", ""), "x": x, "y": y, "verdict": c["verdict"],
                     "age": c["telemetry_age_min"], "slots": c["available_slots"], "total": c["total_slots"], "dist": dist,
                     "venue": c["charger_id"] not in placed, "charging": c.get("fleet_vehicles_charging_here", 0)})
    return {"center": (CX, CY), "size": (W, H), "gates": gates, "precinct": precinct, "hubs": hubs, "stale_minutes": snap.stale_minutes,
            "lane_gate": next((p["gate_id"] for p in (plan or {}).get("lane_proposals", [])), None)}
