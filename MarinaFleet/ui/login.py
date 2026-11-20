"""Sign-in page: brand hero on the left, rider and operator sign-in on the right."""
from __future__ import annotations

import streamlit as st

import config
from engine import auth
from ui import components as C
from ui.components import full_width, show

FULL = full_width()


def render() -> None:
    ops_db = config.OPS_DB_PATH
    auth.ensure_demo_users(ops_db)
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        show(C.login_hero())
    with right:
        show('<h2 class="mf-h1 mf-signin-title">Sign in</h2><p class="mf-muted">Choose how you are using MarinaFleet tonight.</p>')
        rider_tab, admin_tab = st.tabs(["Rider", "Operator / Admin"])
        with rider_tab:
            with st.form("rider_login"):
                email = st.text_input("E-mail", key="rider_email", placeholder="you@example.com")
                pw = st.text_input("Password", type="password", key="rider_pw")
                if st.form_submit_button("Sign in as rider", type="primary", **FULL):
                    user, msg = auth.authenticate(email, pw, "rider", ops_db)
                    if user:
                        st.session_state.user = user
                        st.rerun()
                    show(C.callout(C.e(msg), "danger", "alert-circle", "Sign-in failed"))
            with st.expander("New here? Create a rider account"):
                with st.form("rider_signup"):
                    name = st.text_input("Full name", key="su_name")
                    su_email = st.text_input("E-mail", key="su_email")
                    su_pw = st.text_input("Password (min. 8 characters)", type="password", key="su_pw")
                    if st.form_submit_button("Create account", **FULL):
                        try:
                            st.session_state.user = auth.register_rider(su_email, su_pw, name, ops_db)
                            st.rerun()
                        except ValueError as exc:
                            show(C.callout(C.e(exc), "danger", "alert-circle", "Could not create account"))
            show(C.callout(f"Demo rider: <span class='mf-mono'>{C.e(auth.DEMO_RIDER[0])}</span> / <span class='mf-mono'>{C.e(auth.DEMO_RIDER[2])}</span>",
                           "info", "key"))
        with admin_tab:
            with st.form("admin_login"):
                uname = st.text_input("Operator ID", key="admin_user", placeholder="admin")
                apw = st.text_input("Password", type="password", key="admin_pw")
                if st.form_submit_button("Sign in to operations console", type="primary", **FULL):
                    user, msg = auth.authenticate(uname, apw, "admin", ops_db)
                    if user:
                        st.session_state.user = user
                        st.rerun()
                    show(C.callout(C.e(msg), "danger", "alert-circle", "Sign-in failed"))
            show(C.callout("Demo operator: <span class='mf-mono'>admin</span> / <span class='mf-mono'>MarinaOps!2026</span> "
                           "(override with MARINA_ADMIN_PASSWORD).", "info", "key"))
        show('<p class="mf-fine">Prototype authentication: salted PBKDF2 password hashes, role checks, lock-out after 5 failed attempts.</p>')
