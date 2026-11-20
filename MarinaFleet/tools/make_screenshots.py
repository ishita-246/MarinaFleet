"""Render the main UI states to PNG through tools/preview_harness.py (see that file for what this does and does not prove)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import preview_harness as H  # noqa: E402
from engine.auth import DEMO_RIDER, demo_admin_password  # noqa: E402

ADMIN = {"admin_user": "admin", "admin_pw": demo_admin_password()}
RIDER = {"rider_email": DEMO_RIDER[0], "rider_pw": DEMO_RIDER[2]}
OUT = H.SHOTS
OUT.mkdir(parents=True, exist_ok=True)


def write(name: str, stub) -> Path:
    p = Path("/tmp") / f"mf_{name}.html"
    p.write_text(stub if isinstance(stub, str) else H.page_html(stub), encoding="utf-8")
    return p


def loader_page() -> str:
    """The branded loading state (the real loader markup and CSS, on the app background)."""
    from ui import components as C, theme as T
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{T.stylesheet()}\n{H.HARNESS_CSS}</style></head><body>'
            f'<div class="stApp" data-testid="stApp"><div class="h-main"><div class="block-container">{C.h(C.loader())}</div></div></div></body></html>')


def main(only: set[str] | None = None) -> None:
    from playwright.sync_api import sync_playwright
    states = {}
    states["login"] = H.run_app()
    states["loader"] = loader_page()
    admin = H.run_app(("Sign in to operations console",), ADMIN)
    st_admin = admin.session_state
    states["admin_idle"] = H.run_app((), None, st_admin)
    H.run_app(("Run event-night scenario",), None, st_admin)       # runs the agent (Mock backend), then rerun
    states["admin_run"] = H.run_app((), None, st_admin)
    for tab, name in ((0, "tab_dispatch"), (1, "tab_chargers"), (4, "tab_roi")):
        states[name] = H.run_app((), None, st_admin, tab)
    H.run_app(("Try to execute without approval",), None, st_admin)
    states["admin_bypass"] = H.run_app((), None, st_admin)
    H.run_app(("Approve change",), None, st_admin)
    states["admin_approved"] = H.run_app((), None, st_admin)
    rider = H.run_app(("Sign in as rider",), RIDER)
    inputs = {"bk_gate": "G4", "bk_dest": "MARINA", "bk_party": 2}
    H.run_app(("Get quote",), inputs, rider.session_state)
    states["rider_quote"] = H.run_app((), inputs, rider.session_state)

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name, stub in states.items():
            if only and name not in only:
                continue
            path = write(name, stub)
            pg = b.new_page(viewport={"width": 1366, "height": 768})
            pg.goto(f"file://{path}")
            pg.wait_for_timeout(1400)  # let entry animations finish
            pg.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            pg.screenshot(path=str(OUT / f"{name}_viewport.png"))
            pg.close()
        b.close()
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
