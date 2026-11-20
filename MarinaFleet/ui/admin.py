"""
Operator command center (admin): KPI strip, operations map, Agent-vs-Code live trace, approval gate, and the detail tabs.
Built only from ui/components.py + ui/charts.py + ui/viewmodel.py. No colours or sizes are defined in this file.
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

import config
from agent.agent_loop import resolve_approval, run_event_night, try_execute_without_approval
from engine.approval_gate import ApprovalGate
from engine.auth import require_role
from engine.battery_math import WEATHER_PROFILES
from services import booking
from services.snapshot import get_egress_and_fleet_snapshot
from ui import charts, viewmodel
from ui import components as C
from ui.components import Raw, e, full_width, pill, show, status_pill

BACKENDS = {"Mock (offline, deterministic)": "mock", "Ollama (local qwen3)": "ollama",
            "Gemini Flash (free tier)": "gemini", "Groq (free tier)": "groq"}
DEFAULT_MODEL = {"mock": "mock-deterministic-v1", "ollama": config.OLLAMA_MODEL,
                 "gemini": config.GEMINI_MODEL, "groq": config.GROQ_MODEL}
FULL = full_width()


@st.cache_resource(show_spinner=False)
def _live_snapshot(weather: str, stale: float):
    """Telemetry snapshot for the idle state (no agent, no LLM): the same Python service the agent calls."""
    return get_egress_and_fleet_snapshot(weather=weather, stale_minutes=stale)


def _df(rows, cols=None, rename=None):
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    return df.rename(columns=rename or {})


# =============================================================================================== sidebar
def _sidebar(user: dict, ss) -> tuple[str, str, str, float, bool]:
    with st.sidebar:
        show(C.user_chip(user["display_name"], f"Operator · {user['username']}"))
        show(C.side_title("Scenario", "stadium"))
        weather = st.selectbox("Weather", list(WEATHER_PROFILES), key="adm_weather", format_func=lambda w: WEATHER_PROFILES[w]["label"])
        show(C.side_title("Agent", "spark"))
        label = st.selectbox("LLM backend", list(BACKENDS), index=0, key="adm_backend")
        backend = BACKENDS[label]
        model = st.text_input("Model", value=DEFAULT_MODEL[backend], key=f"adm_model_{backend}")
        if backend in ("gemini", "groq"):
            var = f"{backend.upper()}_API_KEY"
            st.caption(f"{var}: " + ("set" if os.getenv(var) else "not set, Mock fallback will be used"))
        elif backend == "ollama":
            st.caption(f"{config.OLLAMA_HOST} (Mock fallback if unreachable)")
        show(C.side_title("Safety limits", "shield-check"))
        stale = st.slider("Charger data is stale after (min)", 1, 30, int(config.STALE_TELEMETRY_MINUTES), key="adm_stale")
        st.caption(f"Battery reserve {config.BATTERY_RESERVE_PCT:.0f}%: a hard rule in code, not adjustable here.")
        st.divider()
        run = st.button("Run event-night scenario", type="primary", **FULL, key="run_sidebar")
        if st.button("Sign out", **FULL, key="adm_signout"):
            for k in ("user", "result", "decisions", "blocked_attempts"):
                ss.pop(k, None)
            st.rerun()
    return weather, backend, model, float(stale), run


# ========================================================================================= approval panels
def _approvals(r, gate: ApprovalGate, user: dict, ss) -> None:
    for rid in r.pending_approvals:
        req = gate.get(rid)
        gate_name = next((g["name"] for g in r.snapshot.gates if g["gate_id"] == req["payload"].get("gate_id")), req["payload"].get("gate_id", ""))
        decision = ss.decisions.get(rid)
        state = "" if decision is None else ("is-approved" if decision["decision"] == "APPROVE" else "is-rejected")
        with st.container(border=True):
            show(C.panel_marker("approval", state))
            show(C.approval_panel(req, gate_name, decision, ss.blocked_attempts.get(rid)))
            if req["status"] == "PENDING_APPROVAL":
                b = st.columns([1, 1, 1.3], gap="small")
                if b[0].button("Approve change", key=f"approve_{rid}", type="primary", **FULL):
                    require_role(user, "admin")
                    ss.decisions[rid] = resolve_approval(rid, "APPROVE", user["display_name"], r.run_id, r.ops_db, r.jsonl_path)
                    st.rerun()
                if b[1].button("Reject change", key=f"reject_{rid}", **FULL):
                    require_role(user, "admin")
                    ss.decisions[rid] = resolve_approval(rid, "REJECT", user["display_name"], r.run_id, r.ops_db, r.jsonl_path)
                    st.rerun()
                if b[2].button("Try to execute without approval", key=f"bypass_{rid}", **FULL):
                    ss.blocked_attempts[rid] = try_execute_without_approval(rid, r.run_id, r.ops_db)
                    st.rerun()


# ================================================================================================== tabs
def _tab_dispatch(plan, snap, surge_ids) -> None:
    show(C.section_title("Battery-safe assignments", "route", f"{len(plan['ride_assignments'])} rides validated by code", first=True))
    only = st.toggle("Surge gates only", value=True, key="adm_only_surge")
    rows = [a for a in plan["ride_assignments"] if not only or a["gate_id"] in surge_ids]
    top = sorted(rows, key=lambda a: a["soc_at_charger_pct"])[:10]
    show(C.table(["Vehicle", "Request", "Gate", "Battery at pickup", "Projected at charger", "Pickup ETA", "Safety charger"],
                 [[a["vehicle_id"], a["request_id"], a["gate_id"], C.battery_bar(a["start_soc_pct"], 96), C.battery_bar(a["soc_at_charger_pct"], 96),
                   f"{a['pickup_eta_min']:.1f} min", a["safety_charger"].replace("CH_", "")] for a in top], num=(5,), ident=(0, 1)))
    low = min(a["soc_at_charger_pct"] for a in plan["ride_assignments"])
    st.caption(f"Showing the 10 tightest battery margins of {len(rows)} rides. Lowest projected battery in any assignment: "
               f"{low:.1f}% (reserve {config.BATTERY_RESERVE_PCT:.0f}%).")
    with st.expander(f"All {len(rows)} assignments (sortable table)"):
        st.dataframe(_df(rows, ["vehicle_id", "request_id", "gate_id", "from_node", "dest_node", "start_soc_pct", "pickup_km", "trip_km",
                                "charger_leg_km", "soc_at_charger_pct", "safety_charger", "pickup_eta_min"]), hide_index=True, **FULL, height=320)
    show(C.section_title("Blocked by the 15% battery guard", "shield-x", f"{len(plan['blocked_dispatches'])} unsafe nearest-car dispatches refused"))
    show(C.table(["Vehicle", "Gate", "Battery at pickup", "Projected at charger", "Why (generated by code)"],
                 [[b["vehicle_id"], b["gate_id"], C.battery_bar(b["start_soc_pct"], 96), C.battery_bar(b["projected_soc_pct"], 96),
                   f"Projected SoC {b['projected_soc_pct']:.1f}% < {config.BATTERY_RESERVE_PCT:.0f}% reserve. {b['reason']}"]
                  for b in plan["blocked_dispatches"]], ident=(0,), reason=(4,)))
    show(C.section_title("Fleet rebalancing", "refresh", f"{len(plan['rebalance_orders'])} robotaxis moved toward surge gates (autonomous)"))
    with st.expander("Rebalancing orders"):
        st.dataframe(_df(plan["rebalance_orders"], ["vehicle_id", "from_node", "to_node", "distance_km", "eta_min"]), hide_index=True, **FULL, height=260)


def _tab_chargers(plan, snap) -> None:
    show(C.section_title("Charger network", "plug", f"telemetry must be newer than {snap.stale_minutes:.0f} min to be trusted", first=True))
    show('<div class="mf-chargers">' + "".join(C.charger_card(c, snap.stale_minutes) for c in snap.chargers) + "</div>")
    if plan:
        refs = plan["charger_refusals"]
        rer = sum(1 for x in refs if x["rerouted_to"])
        show(C.section_title("Refused routings", "shield-x", f"{len(refs)} vehicles, {rer} rerouted to verified hubs"))
        shown, seen = [], set()
        for x in sorted(refs, key=lambda x: (x["rerouted_to"] is None)):  # one example per hub and outcome, rerouted first
            k = (x["refused_charger"], bool(x["rerouted_to"]))
            if k not in seen:
                seen.add(k)
                shown.append(x)
        show(C.table(["Vehicle", "Battery", "Refused hub", "Result", "Why (generated by code)"],
                     [[x["vehicle_id"], C.battery_bar(x["soc_pct"], 96), x["refused_charger"].replace("CH_", ""),
                       Raw(status_pill("REDIRECTED", f"Rerouted to {x['rerouted_to'].replace('CH_', '')}") if x["rerouted_to"] else status_pill("BLOCKED", "No safe hub")),
                       x["reason"]] for x in shown], ident=(0,), reason=(4,)))
        with st.expander(f"All {len(refs)} refused routings"):
            st.dataframe(_df(refs, ["vehicle_id", "soc_pct", "refused_charger", "refused_code", "rerouted_to", "reason"]), hide_index=True, **FULL, height=260)
        show(C.section_title("Verified reservations", "check-circle",
                             f"{len(plan['charger_orders'])} reserved · {len(plan['charger_waitlist'])} waitlisted · {len(plan['mobile_charger_requests'])} mobile-charger requests"))
        with st.expander("Reservation orders"):
            st.dataframe(_df(plan["charger_orders"]), hide_index=True, **FULL, height=240)


def _tab_approvals(r, gate: ApprovalGate, ss) -> None:
    show(C.section_title("Approval queue", "lock", "PENDING_APPROVAL, then APPROVED and EXECUTED, or REJECTED", first=True))
    show(C.callout("The dispatch service refuses any physical lane, pickup-zone or signal change without a one-time approval token. "
                   "Approve or reject in the gold panel above the map.", "accent", "lock", "Human operator approval gate"))
    if not r.pending_approvals:
        show(C.empty_state("No physical change requested", "The agent did not ask to change any lane, pickup zone or signal in this run.", "shield-check"))
        return
    rows = []
    for rid in r.pending_approvals:
        q = gate.get(rid)
        rows.append([rid, q["action_type"].replace("_", " ").title(), q["payload"].get("pickup_zone", ""), Raw(status_pill(q["status"])),
                     q["decided_by"] or "waiting for operator", q["decision_note"] or ""])
    show(C.table(["Request", "Action", "Zone", "State", "Decided by", "Note"], rows, ident=(0,), reason=(5,)))


def _tab_audit(r) -> None:
    adf = pd.DataFrame(r.audit_rows())
    show(C.section_title("Audit log", "file", f"{len(adf)} entries · timestamp, tool, inputs, outputs, guard results, rationale", first=True))
    if adf.empty:
        show(C.empty_state("No audit entries yet", "Run the scenario to create the first entries."))
        return
    recent = adf.tail(8).iloc[::-1]
    show(C.table(["#", "Time (UTC)", "Actor", "Tool", "Mode", "Rationale"],
                 [[int(x["id"]), x["ts_utc"][11:19], C.actor_badge(x["actor"]), x["tool"], x["execution_mode"], (x["rationale"] or "")[:140]]
                  for _, x in recent.iterrows()], num=(0,), ident=(3,), reason=(5,)))
    with st.expander(f"Full audit log ({len(adf)} rows)"):
        st.dataframe(adf[["id", "ts_utc", "step", "actor", "tool", "execution_mode", "rationale"]], hide_index=True, **FULL, height=420)
    st.download_button("Download audit log (CSV)", adf.to_csv(index=False), file_name=f"{r.run_id}_audit.csv", key="adm_dl_audit")
    st.caption(f"SQLite: {r.ops_db} · JSONL: {r.jsonl_path}")


def _tab_roi(plan, r) -> None:
    d = viewmodel.roi(plan)
    n, g, m = d["naive"], d["greedy"], d["marina"]
    show(C.section_title("MarinaFleet vs baselines", "trend-down", "same seeded event night, all numbers computed by Python", first=True))
    cards = [
        {"label": "Peak gate queue", "icon_name": "clock", "tone": "brand", "value": f"{m['gate4_style_peak_queue_wait_min']}", "unit": "min",
         "sub": f"{m['peak_queue_wait_if_lane_approved_min']} min if the lane change is approved",
         "delta": {"text": f"{m['gate4_style_peak_queue_wait_min'] - n['gate4_style_peak_queue_wait_min']:+.1f} min vs naive", "good": True}},
        {"label": "Stranded vehicles", "icon_name": "battery-low", "tone": "ok", "value": f"{m['stranded_vehicles']}", "unit": "",
         "sub": f"naive baseline strands {n['stranded_vehicles']}", "delta": {"text": f"{m['stranded_vehicles'] - n['stranded_vehicles']:+d} vs naive", "good": True}},
        {"label": "Wasted km (dead hubs)", "icon_name": "wifi-off", "tone": "ok", "value": f"{m['wasted_km']:.0f}", "unit": "km",
         "sub": f"naive wastes {n['wasted_km']:.0f} km on stale or offline hubs", "delta": {"text": f"{m['wasted_km'] - n['wasted_km']:+.0f} km vs naive", "good": True}},
        {"label": "Pickup deadhead", "icon_name": "route", "tone": "brand", "value": f"{m['pickup_deadhead_km']:,.0f}", "unit": "km",
         "sub": "empty km to riders, same 15% rule", "delta": {"text": f"{m['pickup_deadhead_km'] - g['pickup_deadhead_km']:+.0f} km vs Greedy+15%", "good": m["pickup_deadhead_km"] <= g["pickup_deadhead_km"]}},
    ]
    show(C.kpi_strip(cards, cols=4))
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        show(charts.grouped_bars("Rider pickup wait", "Mean and 90th percentile, lower is better", ["Mean wait", "P90 wait"],
                                 [{"key": "naive", "values": [n["mean_wait_min"], n["p90_wait_min"]]}, {"key": "greedy", "values": [g["mean_wait_min"], g["p90_wait_min"]]},
                                  {"key": "marina", "values": [m["mean_wait_min"], m["p90_wait_min"]]}], "min"))
        show(charts.grouped_bars("Safety events", "Count over the night, lower is better. Greedy+15% uses the same guard and is not scored on charger trips.",
                                 ["Stranded\nvehicles", "Below 15%\nreserve", "Failed charger\ntrips"],
                                 [{"key": k, "values": [d[k]["stranded_vehicles"], d[k]["reserve_violations"], d[k]["failed_charger_attempts"]]} for k in ("naive", "marina")], "events"))
    with c2:
        show(charts.single_bars("Peak gate pickup-queue wait", "Gate 4 surge, lower is better",
                                [{"label": "Naive\nbaseline", "value": n["gate4_style_peak_queue_wait_min"], "key": "naive"},
                                 {"label": "MarinaFleet", "value": m["gate4_style_peak_queue_wait_min"], "key": "marina"},
                                 {"label": "MarinaFleet\n+ lane approved", "value": m["peak_queue_wait_if_lane_approved_min"], "key": "marina", "hatch": True}], "min"))
        show(charts.single_bars("Pickup deadhead", "Empty km driven to riders", [{"label": "Naive\nbaseline", "value": n["pickup_deadhead_km"], "key": "naive"},
                                 {"label": "Greedy\n+ 15%", "value": g["pickup_deadhead_km"], "key": "greedy"}, {"label": "MarinaFleet", "value": m["pickup_deadhead_km"], "key": "marina"}], "km"))
    show(C.callout("The naive baseline looks slightly faster on mean pickup because it sends nearby low-battery cars that later strand. "
                   "Under the same 15% rule, MarinaFleet beats greedy dispatch on wait and deadhead.", "info", "info", "Honest trade-off"))
    with st.expander("KPI table (computed by Python)"):
        st.code(r.code_appendix)


def _tab_multimodal(plan) -> None:
    mm = plan["multimodal"]
    c1, c2 = st.columns([1.2, 1], gap="large")
    with c1:
        show(C.section_title("Feeder buses", "bus", f"{len(mm['bus_orders'])} deployed (autonomous)", first=True))
        show(C.table(["Bus", "Gate", "To", "Seats", "Distance", "ETA"], [[b["bus_id"], b["gate_id"], b["to_node"], b["capacity"], f"{b['distance_km']:.1f} km", f"{b['eta_min']:.1f} min"]
                                                                       for b in mm["bus_orders"][:12]], num=(3, 4, 5), ident=(0,)))
        with st.expander(f"All {len(mm['bus_orders'])} bus orders"):
            st.dataframe(_df(mm["bus_orders"]), hide_index=True, **FULL, height=260)
        show(C.section_title("30-minute overflow forecast", "gauge"))
        show(C.table(["Gate", "Ride-hail parties", "Robotaxi capacity (30 min)", "Overflow parties", "Overflow fans"],
                     [[x["gate_id"], x["ridehail_parties"], f"{x['robotaxi_capacity_30min']:.0f}", f"{x['overflow_parties']:.0f}", x["overflow_fans"]] for x in mm["gates"]], num=(1, 2, 3, 4), ident=(0,)))
    with c2:
        show(C.section_title("Rider guidance pushed", "walk", first=True))
        for gd in plan["rider_guidance"]:
            show(C.callout(f"{e(gd['message'])}<br><span class='mf-small'>About {gd['fans_to_shift']} fans, {e(gd['from_gate'])} to {e(gd['to_gate'])}</span>", "brand", "walk"))
        show(C.section_title("Metro announcements", "megaphone"))
        for a in mm["metro_announcements"]:
            show(C.callout(f"{e(a['message'])} <span class='mf-small'>(about {a['fans']} fans)</span>", "info", "train"))


def _tab_bookings() -> None:
    rows = booking.list_bookings(config.OPS_DB_PATH)
    show(C.section_title("Rider portal bookings", "ticket", f"{len(rows)} bookings, each checked by the same 15% battery guard", first=True))
    if not rows:
        show(C.empty_state("No rider bookings yet", "Riders book from the rider portal; their trips appear here.", "ticket"))
        return
    show(C.table(["Booking", "Rider", "Gate", "To", "Pax", "Vehicle", "Pickup", "Battery at charger", "Fare", "Status"],
                 [[b["booking_id"], b["username"], b["gate_id"], b["dest_node"], b["party_size"], b["vehicle_id"], f"{b['est_pickup_min']:.0f} min",
                   C.battery_bar(b["soc_at_charger_pct"], 80), f"AED {b['fare_aed']:.2f}", Raw(status_pill(b["status"]))] for b in rows],
                 num=(4, 6, 8), ident=(0, 5)))


# =========================================================================================== entry point
def render(user: dict) -> None:
    require_role(user, "admin")
    ss = st.session_state
    ss.setdefault("result", None)
    ss.setdefault("decisions", {})
    ss.setdefault("blocked_attempts", {})
    weather, backend, model, stale, run_side = _sidebar(user, ss)

    r = ss.result
    snap = r.snapshot if r else _live_snapshot(weather, stale)
    plan = (r.plan or None) if r else None
    gate = ApprovalGate(r.ops_db) if r else None
    pending = [rid for rid in (r.pending_approvals if r else []) if (gate.get(rid) or {}).get("status") == "PENDING_APPROVAL"]

    # ---- top bar: logo + tagline | event clock, system status, LLM backend
    stat = viewmodel.system_status(snap, plan, len(pending))
    right = C.event_clock(viewmodel.event_clock(snap)) + pill(stat["label"], stat["tone"], stat["icon_name"], live=True, title=stat.get("detail", ""))
    right += pill(f"LLM: {r.backend_used}" if r else f"LLM: {backend}", "brand", "spark", mono=True)
    show(C.brand_header(right))

    run_main = False
    if r is None:
        _, mid, _ = st.columns([1, 1.2, 1])
        run_main = mid.button("Run event-night scenario", type="primary", **FULL, key="run_main")
    if run_main or run_side:
        slot = st.empty()
        slot.markdown(C.h(C.loader("Agent cycle running")), unsafe_allow_html=True)
        ss.result = run_event_night(backend=backend, model=model or None, weather=weather, stale_minutes=stale)
        ss.decisions, ss.blocked_attempts = {}, {}
        slot.empty()
        st.rerun()

    if r and r.fallback_reason:
        show(C.callout(e(r.fallback_reason), "warn", "alert", "LLM backend note"))

    # ---- zone 1: KPI strip
    show(C.kpi_strip(viewmodel.kpis(snap, plan)))

    if pending:
        show(C.callout("A physical road change is waiting for your decision. <a href='#operator-approval'>Review and decide below the map</a>. "
                       "Nothing runs until you approve.", "accent", "lock", f"{len(pending)} operator approval pending"))

    # ---- zones 2 and 3: operations map | Agent-vs-Code live trace
    left, right_col = st.columns([1.5, 1], gap="medium")
    with left:
        banner = viewmodel.surge_banner(snap, plan)
        if banner:
            show(C.surge_alert(banner))
        mm = viewmodel.map_model(snap, plan)
        show(C.panel("Operations view", "stadium", C.gate_map(mm) + C.gate_queue_rows(snap.gates),
                     right=pill(WEATHER_PROFILES[snap.weather]["label"], "neutral", "sun"), foot=C.map_legend()))
    with right_col:
        items = viewmodel.trace_items(r, ss.decisions, ss.blocked_attempts) if r else []
        show(C.trace_panel(items, viewmodel.trace_counts(items) if r else None))

    # ---- human approval gate (gold panel) directly under the map and trace
    if r and r.pending_approvals:
        show('<div id="operator-approval"></div>' + C.section_title("Operator approval", "lock", "physical road changes never run without you"))
        _approvals(r, gate, user, ss)

    if r is None:
        show(C.callout("Gate 4 is already in surge and two charger hubs are untrusted in the live telemetry above. "
                       "Press <b>Run event-night scenario</b>: the agent will decide what to do, Python will do the maths and enforce every safety rule.",
                       "brand", "spark", "Ready"))
        _tab_bookings_only()
        return

    # ---- tabs
    surge_ids = {g["gate_id"] for g in snap.gates if g["status"] == "SURGE"}
    tabs = st.tabs(["Dispatch Decisions", "Charger Network", f"Approval Queue ({len(pending)})", "Audit Log", "ROI vs Baseline",
                    "Feeder & Metro", "Bookings", "Report"])
    with tabs[0]:
        _tab_dispatch(plan, snap, surge_ids)
    with tabs[1]:
        _tab_chargers(plan, snap)
    with tabs[2]:
        _tab_approvals(r, gate, ss)
    with tabs[3]:
        _tab_audit(r)
    with tabs[4]:
        _tab_roi(plan, r)
    with tabs[5]:
        _tab_multimodal(plan)
    with tabs[6]:
        _tab_bookings()
    with tabs[7]:
        show(C.section_title("Operator situation report", "file", "written by the agent; every figure quoted from Python tool outputs", first=True))
        st.code(r.report, language=None)
        with st.expander("Code-computed KPI appendix"):
            st.code(r.code_appendix)


def _tab_bookings_only() -> None:
    _tab_bookings()
