"""Rider portal: book a battery-checked robotaxi, see the fastest gate, manage trips. Built from shared components only."""
from __future__ import annotations

import copy

import streamlit as st

import config
from services import booking
from services.snapshot import get_egress_and_fleet_snapshot
from ui import components as C
from ui import viewmodel
from ui.components import Raw, e, full_width, pill, show, status_pill

FULL = full_width()


@st.cache_resource(show_spinner=False)
def _base_snapshot(weather: str):
    return get_egress_and_fleet_snapshot(weather=weather)


def _quote_card(q: dict) -> str:
    eta = (f'<div class="mf-quote-hero"><div><div class="mf-eyebrow">Estimated pickup</div><div class="eta mf-gradient-text">{q["est_pickup_min"]:.0f} min</div>'
           f'<div class="mf-small">at {e(q["gate_name"])} pickup zone {e(q["pickup_node"])}</div></div>'
           f'<div><div class="mf-eyebrow">Fare estimate</div><div class="mf-display">AED {q["fare_aed"]:.2f}</div></div></div>')
    kv = "".join(f'<div><div class="k">{e(k)}</div><div class="v">{e(v)}</div></div>' for k, v in
                 [("Vehicle", f"{q['vehicle_id']} · {q['model']}"), ("Car arrives in", f"{q['vehicle_eta_min']:.0f} min"),
                  ("Curb queue", f"{q['gate_queue_min']:.0f} min"), ("Trip", f"{q['trip_km']:.1f} km · {q['trip_min']:.0f} min")])
    safe = (f'<hr class="mf-hr"><div class="mf-bat-row">{pill("Battery check passed", "ok", "shield-check")} '
            f'<span class="mf-small">Projected after your trip and the drive to charger {e(q["safety_charger"])} (minimum {config.BATTERY_RESERVE_PCT:.0f}%):</span> '
            f'{C.battery_bar(q["soc_at_charger_pct"], 140)}</div>')
    skipped = (f'<p class="mf-small">{q["closer_cars_skipped_by_battery_guard"]} closer robotaxi(s) were skipped because they could not finish your trip safely.</p>'
               if q["closer_cars_skipped_by_battery_guard"] else "")
    return C.card(f'<h3>{e(q["gate_name"])} to {e(q["dest_name"])} · {q["party_size"]} passenger(s)</h3>{eta}<div class="mf-kv">{kv}</div>{safe}{skipped}')


def render(user: dict) -> None:
    ss = st.session_state
    ops_db = config.OPS_DB_PATH
    if "rider_snap" not in ss:
        ss.rider_snap = copy.deepcopy(_base_snapshot("clear"))
    snap = ss.rider_snap
    ss.setdefault("quote", None)
    ss.setdefault("last_booking", None)

    with st.sidebar:
        show(C.user_chip(user["display_name"], f"Rider · {user['username']}"))
        show(C.side_title("Tonight", "stadium"))
        st.caption(f"{snap.meta['event_name']}. Egress in progress; pickup zones PZ1 to PZ6 on the stadium ring road.")
        st.divider()
        if st.button("Sign out", **FULL, key="rider_signout"):
            for k in ("user", "quote", "last_booking", "rider_snap"):
                ss.pop(k, None)
            st.rerun()

    surge = [g for g in snap.gates if g["status"] == "SURGE"]
    status = "".join(pill(f"{g['name']}: {g['est_pickup_wait_min']:.0f} min queue", "danger", "alert") for g in surge) or pill("All gates normal", "ok", "check-circle")
    show(C.brand_header(C.event_clock(viewmodel.event_clock(snap)) + status))
    show(C.section_title("Book your ride home", "car", "Every robotaxi is battery-checked before it is sent.", first=True))

    left, right = st.columns([1, 1.25], gap="large")
    gates = snap.gates
    dests = booking.destinations(snap)
    with left:
        with st.form("booking_form"):
            gate_id = st.selectbox("Pickup gate", [g["gate_id"] for g in gates], index=3, key="bk_gate",
                                   format_func=lambda gid: next(f"{g['name']} · queue about {g['est_pickup_wait_min']:.0f} min" + (" · busy" if g["status"] == "SURGE" else "")
                                                                for g in gates if g["gate_id"] == gid))
            dest = st.selectbox("Destination", [d[0] for d in dests], key="bk_dest", format_func=lambda n: dict(dests)[n])
            party = st.number_input("Passengers", min_value=1, max_value=6, value=2, step=1, key="bk_party")
            if st.form_submit_button("Get quote", type="primary", **FULL):
                ss.quote = booking.quote_ride(snap, gate_id, dest, int(party), booking.unavailable_vehicle_ids(ops_db))
                ss.last_booking = None
        show('<p class="mf-fine">Fares use an illustrative demo tariff (AED 12 + 2.10 per km, minimum AED 20).</p>')

    with right:
        q = ss.quote
        if ss.last_booking:
            b = ss.last_booking
            show(C.callout(f"{e(b['message'])}", "ok" if b["status"] == "CONFIRMED" else "warn",
                           "check-circle" if b["status"] == "CONFIRMED" else "alert", f"Booking {b['booking_id']}"))
        if q is None:
            show(C.card(C.empty_state("Your quote will appear here", "Choose a pickup gate and destination, then press Get quote.", "ticket")))
        elif not q["available"]:
            show(C.callout(e(q["alternative"]), "warn", "alert", "No robotaxi available right now"))
        else:
            show(_quote_card(q))
            tip = q.get("tip")
            if tip:
                show(C.callout(f"Walk about {tip['walk_m']} m ({tip['walk_min']:.0f} min) to <b>{e(tip['gate_name'])}</b> and be picked up in about "
                               f"<b>{tip['est_pickup_min']:.0f} min</b>, saving about {tip['saving_min']:.0f} min.", "brand", "walk", "Faster option"))
            c1, c2 = st.columns(2)
            if c1.button("Confirm booking", type="primary", **FULL, key="bk_confirm"):
                ss.last_booking = booking.confirm_booking(snap, q, user["username"], ops_db)
                ss.quote = None
                st.rerun()
            if tip and c2.button(f"Switch to {tip['gate_name']}", **FULL, key="bk_switch"):
                ss.quote = booking.quote_ride(snap, tip["gate_id"], q["dest_node"], q["party_size"], booking.unavailable_vehicle_ids(ops_db))
                st.rerun()

    show(C.section_title("My trips", "ticket"))
    trips = booking.list_bookings(ops_db, user["username"])
    if not trips:
        show(C.empty_state("No bookings yet", "Your confirmed trips will be listed here.", "ticket"))
    else:
        show(C.table(["Booking", "Booked (UTC)", "Gate", "To", "Pax", "Vehicle", "Pickup", "Fare", "Status"],
                     [[t["booking_id"], t["ts_utc"][:16].replace("T", " "), t["gate_id"], t["dest_node"], t["party_size"], t["vehicle_id"],
                       f"{t['est_pickup_min']:.0f} min", f"AED {t['fare_aed']:.2f}", Raw(status_pill(t["status"]))] for t in trips], num=(4, 6, 7), ident=(0, 5)))
        active = [t["booking_id"] for t in trips if t["status"] == "CONFIRMED"]
        if active:
            c1, c2 = st.columns([2, 1])
            which = c1.selectbox("Cancel a booking", active, key="bk_cancel_sel", label_visibility="collapsed")
            if c2.button("Cancel booking", **FULL, key="bk_cancel"):
                booking.cancel_booking(which, user["username"], ops_db)
                st.rerun()
