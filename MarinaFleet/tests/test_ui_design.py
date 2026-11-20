"""
Design-system tests. These keep the UI honest without a browser:
  * one source of truth for colours and sizes (no stray hex codes, inline styles or raw pixel font sizes),
  * WCAG AA contrast for every text/background pair the CSS uses,
  * native Streamlit theme (.streamlit/config.toml) and brand assets in sync with ui/theme.py,
  * components never rely on colour alone, battery bar draws the 15% floor, guard items carry the code-generated reason,
  * map layout and KPI view-model read the Python results correctly.
"""
import re
from pathlib import Path

import pytest

from ui import brand, charts, icons, theme as T, viewmodel
from ui import components as C

ROOT = Path(__file__).resolve().parents[1]
UI_FILES = [p for p in (ROOT / "ui").glob("*.py") if p.name != "theme.py"] + [ROOT / "app.py"]
HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


# ------------------------------------------------------------------------------------ single source of truth
@pytest.mark.parametrize("path", UI_FILES + [ROOT / "ui" / "styles.css"], ids=lambda p: p.name)
def test_no_hardcoded_colours_outside_theme(path):
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"href='#[a-z-]+'", "", src)   # in-page anchor, not a colour
    assert not HEX.findall(src), f"{path.name} has literal hex colours; use ui/theme.py tokens"
    assert "rgba(" not in src and "rgb(" not in src, f"{path.name} has literal rgb colours"


def test_css_uses_tokens_for_sizes_and_has_no_inline_styles():
    css = (ROOT / "ui" / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r"font-size:\s*[0-9]", css), "font sizes must be var(--mf-fs-*)"
    assert not re.search(r"font-family:\s*['\"]", css), "fonts must be var(--mf-font-*)"
    assert not re.search(r"border-radius:\s*[0-9]+px", css), "radii must be var(--mf-r-*)"
    for p in UI_FILES:
        assert 'style="' not in p.read_text(encoding="utf-8"), f"{p.name}: use classes, not inline style attributes"


def test_stylesheet_has_motion_focus_and_hover_rules():
    css = T.stylesheet()
    assert css.startswith("@import url('https://fonts.googleapis.com")
    assert ":root{--mf-bg:#0B1220" in css and "--mf-brand:#19D3C5" in css and "--mf-accent:#F2B544" in css
    assert "prefers-reduced-motion: reduce" in css and ":focus-visible" in css
    for sel in (".stButton > button:hover", ".stTabs [data-baseweb=\"tab\"]:hover", ".mf-kpi:hover", "table.mf-table tbody tr:hover"):
        assert sel in css, f"missing hover state: {sel}"
    for fallback in ("system-ui", "monospace"):
        assert fallback in css  # fonts still look right fully offline


def test_type_scale_and_grid():
    assert (T.FS_DISPLAY, T.FS_H1, T.FS_H2, T.FS_BODY, T.FS_CAPTION) == (32, 24, 18, 14, 12)
    assert (T.S1, T.S2, T.S3) == (8, 16, 24) and T.R_CARD == 16 and T.R_PILL == 999


# --------------------------------------------------------------------------------------------- accessibility
def test_text_contrast_meets_wcag_aa_on_every_surface():
    for bg in (T.BG_BASE, T.SURFACE, T.SURFACE_RAISED):
        for fg in (T.TEXT, T.TEXT_2, T.TEXT_MUTED, T.BRAND, T.ACCENT, T.OK, T.WARN, T.DANGER, T.INFO):
            assert T.contrast_ratio(fg, bg) >= 4.5, (fg, bg, T.contrast_ratio(fg, bg))


def test_status_pills_and_dark_ink_on_bright_fills_meet_aa():
    for name, tone in T.TONES.items():
        assert T.contrast_ratio(tone["fg"], tone["bg"]) >= 4.5, name
    for fill in (T.BRAND, T.BRAND_BLUE, T.ACCENT, T.DANGER, T.INFO):
        assert T.contrast_ratio(T.INK, fill) >= 4.5, fill   # buttons, AGENT / CODE / GUARD badges use dark ink


def test_chart_series_are_visible_on_the_card_surface():
    for key, col in T.CHART["series"].items():
        assert T.contrast_ratio(col, T.SURFACE) >= 3.0, key   # non-text graphics need 3:1


def test_never_colour_alone():
    for status in ("EXECUTED", "STALE", "OFFLINE", "REFUSED", "PENDING_APPROVAL", "SURGE", "VERIFIED"):
        h = C.status_pill(status)
        assert "<svg" in h and re.search(r">[A-Za-z ]{3,}</span>$", h), status       # icon AND text label
    for kind, label in (("agent", "Agent"), ("code", "Code"), ("guard", "Blocked by guard"), ("human", "Human")):
        assert "<svg" in C.badge(kind) and label in C.badge(kind)
    for tone in ("ok", "warn", "danger", "info"):
        assert "<svg" in C.callout("x", tone)


def test_all_status_icons_exist():
    for _, (tone, ic, label) in C._STATUS.items():
        assert ic in icons.ICON_NAMES and tone in T.TONES


# ------------------------------------------------------------------------------------- native theme + assets
def test_streamlit_config_matches_tokens():
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    cfg = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
    assert cfg["base"] == "dark"
    assert cfg["primaryColor"].upper() == T.BRAND and cfg["backgroundColor"].upper() == T.BG_BASE
    assert cfg["secondaryBackgroundColor"].upper() == T.SURFACE and cfg["textColor"].upper() == T.TEXT


def test_brand_assets_in_sync_with_tokens():
    assert (ROOT / "assets" / "logo.svg").read_text() == brand.logo_svg(48, "a", plate=True) + "\n"
    assert (ROOT / "assets" / "favicon.svg").read_text() == brand.favicon_svg() + "\n"
    assert (ROOT / "assets" / "favicon.png").stat().st_size > 200
    logo = brand.logo_svg(40)
    assert "Marina" in logo and "Fleet" in logo and T.BRAND in logo and T.BRAND_BLUE in logo


def test_tagline_is_consistent():
    assert T.TAGLINE == "Clear the stadium. Protect every battery."
    for doc in ("README.md", "docs/slide_summary.md", "docs/BRAND_GUIDE.md"):
        assert T.TAGLINE in (ROOT / doc).read_text(encoding="utf-8"), doc
    assert T.TAGLINE in C.brand_header("")


# ------------------------------------------------------------------------------------------------ components
def test_battery_bar_draws_the_15_percent_floor_and_tone():
    for soc, word in ((12.0, "below 15% floor"), (15.0, "15 to 30%"), (29.9, "15 to 30%"), (30.0, "above 30%"), (80.0, "above 30%")):
        h = C.battery_bar(soc, width=100)
        assert word in h and f"{soc:.1f}%" in h
        assert 'x1="15.0" x2="15.0"' in h   # visible line at the reserve floor (15% of the bar width)


def test_guard_timeline_item_shows_code_generated_reason():
    h = C.timeline_item("guard", "Dispatch RT-0089 blocked: 15% battery reserve", reason="Projected SoC 11.4% < 15% reserve",
                        foot="Blocked by code, not by the LLM.")
    assert "Blocked by guard" in h and "Projected SoC 11.4% &lt; 15% reserve" in h and "not by the LLM" in h
    assert "k-guard" in h


def test_html_is_escaped():
    h = C.timeline_item("agent", "<script>alert(1)</script>", detail="<img src=x>")
    assert "<script>" not in h and "<img" not in h


def test_surge_alert_has_countdown_and_after_value():
    h = C.surge_alert({"gate": "Gate 4", "fans": 9800, "ratio": 2.8, "wait": 35.5, "throughput": 24.0, "after": 23.7})
    assert "9,800 fans" in h and "35.5 min" in h and "23.7 min" in h and 'role="alert"' in h


def test_surge_banner_never_mixes_lane_only_and_full_plan_figures(snapshot, plan):
    """The lane-alone tile and the full-plan sentence are labelled separately, and match the ROI KPIs."""
    b = viewmodel.surge_banner(snapshot, plan)
    h = C.surge_alert(b)
    k = plan["kpis"]["optimized"]
    assert "Extra lane alone" in h and "If lane change approved" not in h
    assert f'{k["gate4_style_peak_queue_wait_min"]:.1f} min' in h
    assert f'{k["peak_queue_wait_if_lane_approved_min"]:.1f} min once the lane is approved' in h


def test_map_keeps_acronym_hub_names(snapshot, plan):
    svg = C.gate_map(viewmodel.map_model(snapshot, plan))
    assert ">JBR<" in svg and "Jbr" not in svg


def test_charger_card_states_threshold_and_code_not_llm(snapshot):
    for c in snapshot.chargers:
        h = C.charger_card(c, snapshot.stale_minutes)
        if c["verdict"] in ("STALE", "OFFLINE"):
            assert "Routing blocked by code, not by the LLM" in h and "threshold" in h or c["verdict"] == "OFFLINE"
            assert f"{c['telemetry_age_min']:.0f} min ago" in h
        else:
            assert "Routing blocked" not in h


# ----------------------------------------------------------------------------------------------------- charts
def test_charts_use_fixed_entity_colours_and_have_table_fallback():
    h = charts.grouped_bars("Wait", "lower is better", ["Mean", "P90"],
                            [{"key": "naive", "values": [12.7, 17.4]}, {"key": "greedy", "values": [14.3, 20.7]}, {"key": "marina", "values": [13.8, 19.7]}], "min")
    for col in T.CHART["series"].values():
        assert col in h
    assert "View as table" in h and "<title>" in h and "MarinaFleet" in h   # legend + tooltips + table view
    assert "Plotly" not in h


def test_chart_axis_ticks_are_whole_and_zero_is_visible():
    assert charts._nice_max(20.7) == 24 and charts._nice_max(74) == 80 and charts._nice_max(0) == 4
    h = charts.single_bars("Zero", "", [{"label": "A", "value": 0, "key": "marina"}, {"label": "B", "value": 3, "key": "naive"}], "x")
    assert 'height="2"' in h   # a true zero still draws a baseline stub


# ------------------------------------------------------------------------------------------------ view-model
def test_kpis_pending_before_run_and_filled_after(snapshot, plan):
    before = viewmodel.kpis(snapshot, None)
    after = viewmodel.kpis(snapshot, plan)
    assert [k["label"] for k in after] == ["Fans remaining", "Avg pickup wait", "Robotaxis active", "Low battery", "Charger hubs", "Deadhead saved"]
    assert before[1]["pending"] and before[5]["pending"] and not after[1].get("pending")
    o, g = plan["kpis"]["optimized"], plan["kpis"]["battery_aware_greedy"]
    assert after[1]["value"] == f"{o['mean_wait_min']:.1f}"
    assert after[5]["value"] == f"{g['pickup_deadhead_km'] - o['pickup_deadhead_km']:,.0f}"
    assert after[4]["split"] == [(5, "ok"), (1, "warn"), (1, "danger")]
    assert after[0]["value"] == "25,000"


def test_event_clock_from_scenario_metadata(snapshot):
    c = viewmodel.event_clock(snapshot)
    assert (c["t_plus"], c["total"], c["local"]) == (18, 90, "21:48")


def test_trace_contains_agent_code_and_guard_items(plan):
    from agent.agent_loop import run_event_night
    r = run_event_night(backend="mock", weather="clear")
    items = viewmodel.trace_items(r, {}, {})
    kinds = {i["kind"] for i in items}
    assert {"agent", "code", "guard"} <= kinds
    guards = [i for i in items if i["kind"] == "guard"]
    assert any("< 15% reserve" in g["reason"] for g in guards)                    # battery guard, code-generated
    assert any("min old >" in g["reason"] or "OFFLINE" in g["reason"] for g in guards)   # stale / offline hub refusals
    assert all("not by the LLM" in g["foot"] for g in guards)
    counts = viewmodel.trace_counts(items)
    assert counts["agent"] >= 5 and counts["code"] >= 5 and counts["guards"] == len(guards)


def test_map_model_is_collision_free_and_inside_canvas(snapshot, plan):
    m = viewmodel.map_model(snapshot, plan)
    W, H = m["size"]
    pts = [(h["short"], h["x"], h["y"]) for h in m["hubs"] if not h["venue"]]
    for name, x, y in pts:
        assert 40 < x < W - 40 and 50 < y < H - 50, name
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert ((a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5 > 70, (a[0], b[0])
    assert {g["id"] for g in m["gates"]} == {f"G{i}" for i in range(1, 7)}
    g4 = next(g for g in m["gates"] if g["id"] == "G4")
    assert g4["status"] == "SURGE" and g4["inbound"] > 0
    svg = C.gate_map(m)
    assert svg.count('class="ping') == 3 and "STALE" in svg and "OFFLINE" in svg   # Gate 4 pulses, hubs show state
