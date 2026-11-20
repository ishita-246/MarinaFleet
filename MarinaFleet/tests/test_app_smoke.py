"""
Smoke tests for the Streamlit app using a stub Streamlit module (the real one needs a browser).
They run app.py top to bottom through: login page, admin sign-in, agent run, approve / reject /
bypass, rider sign-in, quote, walk-tip switch, confirm booking, and role separation.
"""
import runpy
import sys
from pathlib import Path

import pytest

from engine.auth import DEMO_RIDER, demo_admin_password
from tests.streamlit_stub import StreamlitStub, _RerunException, _StopException

APP = str(Path(__file__).resolve().parents[1] / "app.py")
ADMIN_IN = {"admin_user": "admin", "admin_pw": demo_admin_password()}
RIDER_IN = {"rider_email": DEMO_RIDER[0], "rider_pw": DEMO_RIDER[2]}


def render(monkeypatch, press=(), state=None, inputs=None):
    st = StreamlitStub(press, inputs)
    if state is not None:
        st.session_state = state
    monkeypatch.setitem(sys.modules, "streamlit", st)
    for m in [m for m in sys.modules if m == "ui" or m.startswith("ui.")]:
        monkeypatch.delitem(sys.modules, m)  # re-import ui modules against this stub
    try:
        runpy.run_path(APP, run_name="__main__")
    except (_RerunException, _StopException):
        pass
    return st


def texts(st):
    return " ".join(str(c[1]) for c in st.calls)


def test_login_page_renders(monkeypatch):
    st = render(monkeypatch)
    assert "user" not in st.session_state
    t = texts(st)
    assert "Intelligence that moves a city" in t and "Clear the stadium. Protect every battery." in t
    assert "MarinaFleet" in t and "--mf-brand" in t  # brand header + design tokens injected


def test_admin_idle_state_shows_live_telemetry(monkeypatch):
    st = render(monkeypatch, ("Sign in to operations console",), inputs=ADMIN_IN)
    st = render(monkeypatch, (), st.session_state)  # signed in, no agent run yet
    t = texts(st)
    assert "Fans remaining" in t and "Agent idle" in t and "Gate 4 surge" in t and "Operations view" in t
    assert "Approve change" not in t  # nothing to approve before a run


def test_wrong_password_rejected(monkeypatch):
    st = render(monkeypatch, ("Sign in to operations console",), inputs={"admin_user": "admin", "admin_pw": "nope"})
    assert "user" not in st.session_state
    assert "Sign-in failed" in texts(st)  # branded error callout


def test_rider_account_cannot_open_admin(monkeypatch):
    st = render(monkeypatch, ("Sign in to operations console",),
                inputs={"admin_user": DEMO_RIDER[0], "admin_pw": DEMO_RIDER[2]})
    assert "user" not in st.session_state


@pytest.mark.parametrize("button,final", [("Approve", "EXECUTED"), ("Reject", "REJECTED")])
def test_admin_flow(monkeypatch, button, final):
    st = render(monkeypatch, ("Sign in to operations console",), inputs=ADMIN_IN)
    assert st.session_state["user"]["role"] == "admin"
    st = render(monkeypatch, ("Run event-night scenario",), st.session_state)
    r = st.session_state["result"]
    assert r is not None and r.finished and r.pending_approvals
    st = render(monkeypatch, (), st.session_state)  # after st.rerun()
    t = texts(st)
    for needle in ("Fans remaining", "Avg pickup wait", "Operator approval required", "Agent vs Code", "Blocked by guard",
                   "Routing blocked by code, not by the LLM", "MarinaFleet vs baselines", "Charger network", "Battery-safe assignments"):
        assert needle in t, needle
    st = render(monkeypatch, ("without approval",), st.session_state)
    assert next(iter(st.session_state["blocked_attempts"].values()))["status"] == "REFUSED"
    st = render(monkeypatch, (button,), st.session_state)
    rid = r.pending_approvals[0]
    d = st.session_state["decisions"][rid]
    assert d["request"]["status"] == final and "Duty Operator" in d["message"]


def test_rider_flow_quote_switch_confirm(monkeypatch):
    st = render(monkeypatch, ("Sign in as rider",), inputs=RIDER_IN)
    assert st.session_state["user"]["role"] == "rider"
    inputs = {"bk_gate": "G4", "bk_dest": "MARINA", "bk_party": 2}
    st = render(monkeypatch, ("Get quote",), st.session_state, inputs)
    q = st.session_state["quote"]
    assert q["available"] and q["soc_at_charger_pct"] >= 15 and q["tip"]["gate_id"] in ("G3", "G5")
    st = render(monkeypatch, ("Switch to",), st.session_state, inputs)
    assert st.session_state["quote"]["gate_id"] == q["tip"]["gate_id"]
    st = render(monkeypatch, ("Confirm booking",), st.session_state, inputs)
    b = st.session_state["last_booking"]
    assert b["status"] == "CONFIRMED"
    st = render(monkeypatch, (), st.session_state, inputs)
    assert "My trips" in texts(st) and b["booking_id"] in texts(st)  # trips table lists the new booking


def test_rider_sees_no_admin_console(monkeypatch):
    st = render(monkeypatch, ("Sign in as rider",), inputs=RIDER_IN)
    st = render(monkeypatch, ("Run event-night scenario",), st.session_state)
    assert "result" not in st.session_state  # the run button only exists in the admin console
