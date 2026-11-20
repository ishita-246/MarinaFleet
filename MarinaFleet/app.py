"""
MarinaFleet web app (Streamlit).

    streamlit run app.py

Clear the stadium. Protect every battery.

Routing:
  not signed in -> ui/login.py   (rider sign-in / sign-up, operator sign-in)
  role "rider"  -> ui/rider.py   (book a battery-checked robotaxi)
  role "admin"  -> ui/admin.py   (operator command center: agent run, approvals, ROI, audit)

The UI does no maths and defines no colours: it reads Python outputs, and every colour, size and font comes from
ui/theme.py (shared by ui/styles.css, ui/components.py and ui/charts.py).
"""
from __future__ import annotations

import streamlit as st

from ui import brand

st.set_page_config(page_title="MarinaFleet | Operator command center", page_icon=brand.page_icon(), layout="wide",
                   initial_sidebar_state="expanded")

from ui import admin, components, login, rider  # noqa: E402  (set_page_config must come first)

user = st.session_state.get("user")
components.inject_styles(hide_sidebar=user is None)   # fonts + tokens + component CSS, injected once per run
if user is None:
    login.render()
elif user["role"] == "admin":
    admin.render(user)
else:
    rider.render(user)
