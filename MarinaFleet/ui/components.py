"""
Reusable MarinaFleet UI components. Pages (login, rider, admin) are built ONLY from these helpers and the tokens in
ui/theme.py, so every screen shares one look.

Almost every helper returns an HTML string (pure functions, easy to test); `show()` writes it to the page.
Colours never appear here as literals: SVG fills come from theme tokens, HTML styling comes from ui/styles.css classes.
"""
from __future__ import annotations

import html

from ui import brand, charts, icons, viewmodel
from ui import theme as T
from ui.icons import icon


class Raw(str):
    """Marks a string as trusted HTML so table cells and helpers do not escape it."""


def e(x) -> str:
    return html.escape(str(x))


def h(s: str) -> str:
    """One line of HTML: Streamlit's markdown parser turns blank lines / 4-space indents into code blocks."""
    return "".join(line.strip() for line in s.splitlines())


def cell(x) -> str:
    return x if isinstance(x, Raw) else e(x)


# ------------------------------------------------------------------------------------------ streamlit glue
def full_width() -> dict:
    """Full-width widget kwargs across Streamlit versions: `width="stretch"` (>=1.49) vs `use_container_width`."""
    import streamlit as st
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
    except Exception:  # stub / unknown version
        return {"width": "stretch"}
    return {"width": "stretch"} if (major, minor) >= (1, 49) else {"use_container_width": True}


def show(markup: str) -> None:
    import streamlit as st
    st.markdown(h(markup), unsafe_allow_html=True)


def inject_styles(hide_sidebar: bool = False) -> None:
    """Inject fonts + tokens + component CSS once per run (called from app.py only)."""
    import streamlit as st
    extra = ("[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],[data-testid='collapsedControl']{display:none}"
             if hide_sidebar else "")
    st.markdown(f"<style>{T.stylesheet()}{extra}</style>", unsafe_allow_html=True)


def panel_marker(kind: str = "panel", state: str = "") -> str:
    """Hidden marker inside st.container(border=True): styles.css turns the bordered box into a branded panel via :has()."""
    return f'<div class="mf-marker-{kind} {state}"></div>'


# --------------------------------------------------------------------------------------------- pills + badges
_STATUS = {
    # status -> (tone, icon, label)
    "EXECUTED": ("ok", "check-circle", "Executed"), "CONFIRMED": ("ok", "check-circle", "Confirmed"), "OK": ("ok", "check-circle", "OK"),
    "PASS": ("ok", "check-circle", "Pass"), "VERIFIED": ("ok", "shield-check", "Verified"), "NORMAL": ("ok", "check-circle", "Normal"),
    "DONE": ("ok", "check-circle", "Done"), "APPROVED": ("ok", "check-circle", "Approved"), "AUTONOMOUS": ("brand", "spark", "Autonomous"),
    "HUMAN_APPROVED": ("ok", "user", "Human approved"), "ONLINE": ("ok", "check-circle", "Online"), "DECIDED": ("brand", "spark", "Decided"),
    "PENDING_APPROVAL": ("accent", "lock", "Awaiting approval"), "ELEVATED": ("warn", "alert", "Elevated"), "WARN": ("warn", "alert", "Warning"),
    "PARTIAL": ("warn", "alert", "Partial"), "REDIRECTED": ("warn", "route", "Redirected"), "STALE": ("warn", "clock", "Stale"),
    "REFUSED": ("danger", "shield-x", "Refused"), "BLOCKED": ("danger", "shield-x", "Blocked"), "REJECTED": ("danger", "x-circle", "Rejected"),
    "SURGE": ("danger", "alert", "Surge"), "OFFLINE": ("danger", "wifi-off", "Offline"), "ERROR": ("danger", "alert-circle", "Error"),
    "REJECTED_BY_GUARD": ("danger", "shield-x", "Blocked by guard"), "CANCELLED": ("neutral", "x-circle", "Cancelled"),
    "NO_SLOTS": ("warn", "plug", "No free slots"), "CLOCK_SKEW": ("warn", "clock", "Clock skew"),
}


def pill(text: str, tone: str = "neutral", icon_name: str | None = None, live: bool = False, mono: bool = False, title: str = "") -> str:
    ic = icon(icon_name, 14) if icon_name else ""
    tt = f' title="{e(title)}"' if title else ""
    dot = '<span class="dot"></span>' if live else ""
    cls = f"mf-pill t-{tone}{' live' if live else ''}{' mf-mono-pill' if mono else ''}"
    return f'<span class="{cls}"{tt}>{dot}{ic}{e(text)}</span>'


def status_pill(status: str, label: str | None = None) -> str:
    tone, ic, default = _STATUS.get(str(status).upper(), ("neutral", "info", str(status).replace("_", " ").title()))
    return pill(label or default, tone, ic)


def status_tone(status: str) -> str:
    return _STATUS.get(str(status).upper(), ("neutral",))[0]


def badge(kind: str) -> str:
    """AGENT (teal, spark) / CODE (gold, terminal) / BLOCKED BY GUARD (red, shield) / HUMAN (blue, user)."""
    name, ic, label = {"agent": ("b-agent", "spark", "Agent"), "code": ("b-code", "terminal", "Code"),
                       "guard": ("b-guard", "shield-x", "Blocked by guard"), "human": ("b-human", "user", "Human")}[kind]
    return f'<span class="mf-badge {name}">{icon(ic, 14)}{label}</span>'


# ------------------------------------------------------------------------------------------------- header
def event_clock(c: dict) -> str:
    return (f'<span class="mf-clock" title="{e(c["event"])}: {c["local"]} Dubai time, minutes since the final whistle">{icon("clock", 16)}<b>T+{c["t_plus"]}</b>'
            f'<span class="sub">of {c["total"]} min</span><span class="sub">· {e(c["local"])}</span></span>')


def brand_header(right_html: str = "", tagline: bool = True) -> str:
    """Top bar shared by every screen: logo + tagline on the left, live status chips on the right."""
    tag = f'<span class="mf-tagline">{e(T.TAGLINE)}</span>' if tagline else ""
    return (f'<header class="mf-topbar"><div class="mf-brandlock">{brand.logo_svg(40, "hd")}{tag}</div>'
            f'<div class="mf-topbar-right">{right_html}</div></header>')


def side_title(text: str, icon_name: str) -> str:
    return f'<div class="mf-side-title">{icon(icon_name, 14)}{e(text)}</div>'


def user_chip(name: str, role: str) -> str:
    ini = (name.strip()[:1] or "?").upper()
    return f'<div class="mf-user"><div class="av">{e(ini)}</div><div><div class="nm">{e(name)}</div><div class="rl">{e(role)}</div></div></div>'


# ------------------------------------------------------------------------------------- titles + callouts
def section_title(title: str, icon_name: str | None = None, hint: str = "", first: bool = False) -> str:
    ic = icon(icon_name, 20) if icon_name else ""
    hint_html = f'<span class="hint">{hint}</span>' if hint else ""
    return f'<div class="mf-section{" first" if first else ""}"><h2>{ic}{e(title)}</h2>{hint_html}</div>'


def callout(body_html: str, tone: str = "info", icon_name: str | None = None, title: str | None = None) -> str:
    """Message block: icon + optional bold title + one plain sentence (body_html may contain <b>/<span class='mf-mono'>)."""
    ic_name = icon_name or {"ok": "check-circle", "warn": "alert", "danger": "alert-circle", "info": "info", "brand": "spark", "accent": "lock"}.get(tone, "info")
    ttl = f'<span class="ttl">{e(title)}</span>' if title else ""
    return f'<div class="mf-callout t-{tone}" role="status">{icon(ic_name, 20)}<div>{ttl}{body_html}</div></div>'


def empty_state(title: str, body: str, icon_name: str = "inbox") -> str:
    return f'<div class="mf-empty">{icon(icon_name, 32)}<b>{e(title)}</b>{e(body)}</div>'


# -------------------------------------------------------------------------------------------------- KPIs
def kpi_card(label: str, icon_name: str, tone: str = "brand", value: str = "", unit: str = "", sub: str = "",
             delta: dict | None = None, split: list | None = None, pending: bool = False) -> str:
    if split is not None:  # chargers: three coloured counts separated by dots
        parts = [f'<span class="n-{t}">{n}</span>' for n, t in split]
        val = '<span class="sep">·</span>'.join(parts)
        unit_html = ""
    else:
        val, unit_html = e(value), (f'<span class="u">{e(unit)}</span>' if unit else "")
    dl = ""
    if delta:
        good = delta.get("good")
        dl = (f'<div class="mf-delta {"good" if good else "bad"}">{icon("trend-down" if good else "trend-up", 14)}{e(delta["text"])}</div>'
              if good is not None else f'<div class="mf-delta flat">{icon("minus", 14)}{e(delta["text"])}</div>')
    return (f'<div class="mf-kpi t-{tone}{" pending" if pending else ""}"><span class="mf-kpi-ico">{icon(icon_name, 18)}</span><div class="mf-kpi-label">{e(label)}</div>'
            f'<div class="mf-kpi-value">{val}{unit_html}</div><div class="mf-kpi-sub">{e(sub)}</div>{dl}</div>')


def kpi_strip(cards: list[dict], cols: int = 6) -> str:
    return f'<div class="mf-kpis c{cols}">' + "".join(kpi_card(**c) for c in cards) + "</div>"


# ---------------------------------------------------------------------------------- surge alert banner
def surge_alert(b: dict) -> str:
    after = (f'<div class="mf-countdown after"><span class="lbl">Extra lane alone</span><span class="big">{b["after"]:.1f} min</span></div>'
             if b.get("after") else "")
    plan = ""
    if b.get("managed") is not None and b.get("managed_lane") is not None:
        plan = (f' With rider guidance and feeder buses the plan brings it to {b["managed"]:.1f} min, '
                f'or {b["managed_lane"]:.1f} min once the lane is approved.')
    return (f'<div class="mf-alert-surge" role="alert"><div class="top"><span class="pulse"></span>'
            f'<div class="msg"><b>{e(b["gate"])} surge: {b["fans"]:,} fans queued, {b["ratio"]}x expected</b>'
            f'<span>The pickup queue clears in {b["wait"]:.1f} min at the current {b["throughput"]:.0f} vehicles/min curb rate. Target: under 20 min.{plan}</span></div></div>'
            f'<div class="counts"><div class="mf-countdown"><span class="lbl">Queue clears in</span><span class="big">{b["wait"]:.1f} min</span></div>{after}</div></div>')


def panel(title: str, icon_name: str, body: str, right: str = "", foot: str = "") -> str:
    """Titled card used for the operations map and similar large blocks."""
    return (f'<section class="mf-mapcard"><div class="mf-mapcard-head"><h2>{icon(icon_name, 20)}{e(title)}</h2>{right}</div>{body}{foot}</section>')


def card(body: str, raised: bool = False) -> str:
    return f'<div class="mf-card{" raised" if raised else ""}">{body}</div>'


def actor_badge(actor: str) -> Raw:
    key = "agent" if actor.startswith("AGENT") else "code" if actor.startswith("CODE") else "human"
    return Raw(badge(key))


# ------------------------------------------------------------------------------------ battery bar (15%)
def battery_bar(soc: float, width: int = 120, tag: str | None = None) -> str:
    """Fill (green / amber / red) with a visible line at the hard 15% reserve floor. The number is always printed."""
    soc = max(0.0, min(100.0, float(soc)))
    if soc >= T.BATTERY_OK_FROM:
        col, ic, word = T.OK, "check", "above 30%"
    elif soc >= T.BATTERY_FLOOR:
        col, ic, word = T.WARN, "alert", "15 to 30%"
    else:
        col, ic, word = T.DANGER, "x", "below 15% floor"
    fx = width * T.BATTERY_FLOOR / 100
    svg = (f'<svg width="{width}" height="14" viewBox="0 0 {width} 14" role="img" aria-label="{soc:.1f}% battery, {word}">'
           f'<title>{soc:.1f}% ({word}); line = {T.BATTERY_FLOOR:.0f}% reserve floor</title>'
           f'<rect y="2" width="{width}" height="10" rx="5" fill="{T.SURFACE_RAISED}" stroke="{T.BORDER}"/>'
           f'<rect y="2" width="{width * soc / 100:.1f}" height="10" rx="5" fill="{col}"/>'
           f'<line x1="{fx:.1f}" x2="{fx:.1f}" y1="0" y2="14" stroke="{T.TEXT}" stroke-width="2"/></svg>')
    t = f'<span class="tag">{e(tag)}</span>' if tag else ""
    return Raw(f'<span class="mf-bat">{svg}<span class="pct">{soc:.1f}%</span>{icon(ic, 14)}{t}</span>')


# ------------------------------------------------------------------------------------------------ tables
def table(headers: list[str], rows: list[list], num: tuple = (), ident: tuple = (), reason: tuple = ()) -> str:
    """Branded HTML table. `num` / `ident` / `reason` are column indexes styled mono-right / mono-teal / muted-wrap."""
    th = "".join(f'<th class="{"num" if i in num else ""}">{e(c)}</th>' for i, c in enumerate(headers))
    body = ""
    for r in rows:
        tds = ""
        for i, c in enumerate(r):
            cls = "num" if i in num else ("id" if i in ident else ("reason" if i in reason else ""))
            tds += f'<td class="{cls}">{cell(c)}</td>'
        body += f"<tr>{tds}</tr>"
    if not rows:
        body = f'<tr><td colspan="{len(headers)}">{e("No rows")}</td></tr>'
    return f'<div class="mf-tablewrap"><table class="mf-table"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


# ------------------------------------------------------------------------------------ Agent vs Code trace
def timeline_item(kind: str, title: str, detail: str = "", status: str | None = None, step: int | None = None,
                  reason: str = "", foot: str = "", args: str = "", index: int = 0) -> str:
    """One step in the live trace. kind: agent | code | guard | human. Guard items carry the code-generated reason."""
    ic = {"agent": "spark", "code": "terminal", "guard": "shield-x", "human": "user"}[kind]
    st = status_pill(status) if status and kind != "guard" else ""
    step_html = f'<span class="mf-tl-step">step {step}</span>' if step else ""
    reason_html = f'<div class="mf-tl-reason">{e(reason)}</div>' if reason else ""
    foot_html = f'<div class="mf-tl-foot">{e(foot)}</div>' if foot else ""
    detail_html = ""
    if detail:
        if len(detail) > 150:
            detail_html = (f'<div class="mf-tl-detail">{e(detail[:150].rsplit(" ", 1)[0])}...</div>'
                           f'<details><summary>Show full text</summary><div class="mf-tl-detail">{e(detail)}</div></details>')
        else:
            detail_html = f'<div class="mf-tl-detail">{e(detail)}</div>'
    args_html = f'<div class="mf-tl-detail mf-mono">{e(args)}</div>' if args else ""
    return (f'<li class="mf-tl-item k-{kind}"><span class="mf-tl-dot">{icon(ic, 16)}</span>'
            f'<div class="mf-tl-card"><div class="mf-tl-head">{badge(kind)}{st}{step_html}</div>'
            f'<div class="mf-tl-title">{e(title)}</div>{reason_html}{detail_html}{args_html}{foot_html}</div></li>')


def trace_panel(items: list[dict], counts: dict | None = None) -> str:
    """Right-hand Agent vs Code panel: the hero of the demo."""
    legend = (f'<div class="mf-trace-legend"><span class="item">{badge("agent")}<span class="mf-small">decides</span></span>'
              f'<span class="item">{badge("code")}<span class="mf-small">computes and enforces</span></span>'
              f'<span class="item">{badge("guard")}<span class="mf-small">refuses</span></span></div>')
    c = counts or {"agent": 0, "code": 0, "human": 0}
    count_html = (f'<div class="mf-trace-count"><div class="c-agent"><b>{c["agent"]}</b><span>Agent</span></div>'
                  f'<div class="c-code"><b>{c["code"]}</b><span>Code</span></div>'
                  f'<div class="c-human"><b>{c["human"]}</b><span>Human</span></div></div>')
    if not items:
        body = (f'<div class="mf-trace-empty">{icon("spark", 32)}<div><b>Agent idle</b></div>'
                f'<div>Run the event-night scenario to watch the agent choose tools while Python computes, checks and executes.</div></div>')
    else:
        body = '<ol class="mf-tl">' + "".join(timeline_item(index=i, **it) for i, it in enumerate(items)) + "</ol>"
    return (f'<section class="mf-trace" aria-label="Agent versus code trace"><div class="mf-trace-head"><h2>{icon("activity", 20)}Agent vs Code: live trace</h2>'
            f'{legend}{count_html}</div><div class="mf-trace-body">{body}</div></section>')


# ----------------------------------------------------------------------------------------- operations map
_GATE_TONE = {"NORMAL": T.OK, "ELEVATED": T.WARN, "SURGE": T.DANGER}
_HUB_TONE = {"VERIFIED": (T.OK, "plug"), "STALE": (T.WARN, "clock"), "OFFLINE": (T.DANGER, "wifi-off")}


def gate_map(m: dict) -> str:
    """Stylised stadium-precinct SVG: gates (heat-coloured, Gate 4 pulsing), pickup zones, staging, metro, charger hubs."""
    cx, cy = m["center"]
    s = [f'<svg viewBox="0 0 {int(m["size"][0])} {int(m["size"][1])}" role="img" aria-label="Stadium gate map: surge gates, pickup zones and charger hub states">',
         f'<defs><radialGradient id="mfmapglow" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="{T.BRAND}" stop-opacity=".10"/>'
         f'<stop offset="1" stop-color="{T.BRAND}" stop-opacity="0"/></radialGradient></defs>',
         f'<ellipse cx="{cx}" cy="{cy}" rx="300" ry="270" fill="url(#mfmapglow)"/>']
    for r in (viewmodel.R_GATE, viewmodel.R_PZ, viewmodel.R_NODE):  # schematic range rings
        s.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{T.BORDER}" stroke-width="1" stroke-dasharray="3 6"/>')
    s.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{viewmodel.HUB_RX}" ry="{viewmodel.HUB_RY}" fill="none" stroke="{T.BORDER}" stroke-width="1" stroke-dasharray="3 6"/>')
    s.append(f'<ellipse cx="{cx}" cy="{cy}" rx="46" ry="30" fill="{T.SURFACE_RAISED}" stroke="{T.BORDER}" stroke-width="2"/>'
             f'<ellipse cx="{cx}" cy="{cy}" rx="26" ry="15" fill="none" stroke="{T.BRAND}" stroke-opacity=".55" stroke-width="1.5"/>'
             f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" font-size="{T.FS_CAPTION}" font-weight="600" letter-spacing="1.4" fill="{T.TEXT_2}">STADIUM</text>')
    # outer charger hubs (behind the precinct)
    for hb in m["hubs"]:
        if hb["venue"]:
            continue
        col, ic = _HUB_TONE.get(hb["verdict"], (T.TEXT_2, "plug"))
        blocked = hb["verdict"] in ("STALE", "OFFLINE")
        s.append(f'<line x1="{cx}" y1="{cy}" x2="{hb["x"]:.1f}" y2="{hb["y"]:.1f}" stroke="{col}" stroke-opacity="{.55 if blocked else .18}" '
                 f'stroke-width="{1.6 if blocked else 1}" stroke-dasharray="{"5 5" if blocked else "2 6"}"/>')
    for g in m["gates"]:
        s.append(f'<line class="{"flow" if g["inbound"] else ""}" x1="{g["x"]:.1f}" y1="{g["y"]:.1f}" x2="{g["px"]:.1f}" y2="{g["py"]:.1f}" '
                 f'stroke="{T.BRAND if g["inbound"] else T.BORDER}" stroke-width="2"/>')
    for g in m["gates"]:
        col = _GATE_TONE.get(g["status"], T.OK)
        surge = g["status"] == "SURGE"
        halo = 22 + 9 * g["ratio"]
        tip = f'{g["name"]}: {g["fans"]:,} fans queued, {g["ratio"]}x expected, pickup queue {g["queue"]:.1f} min ({g["status"]})'
        s.append(f'<g class="gate-hit"><title>{e(tip)}</title>'
                 f'<circle cx="{g["x"]:.1f}" cy="{g["y"]:.1f}" r="{halo:.1f}" fill="{col}" fill-opacity="{.26 if surge else .13}"/>')
        if surge:
            for k, d in enumerate(("", " d2", " d3")):
                s.append(f'<circle class="ping{d}" cx="{g["x"]:.1f}" cy="{g["y"]:.1f}" r="22" fill="none" stroke="{col}" stroke-width="2.5"/>')
        s.append(f'<circle class="gate-core" cx="{g["x"]:.1f}" cy="{g["y"]:.1f}" r="19" fill="{T.SURFACE}" stroke="{col}" stroke-width="3.5"/>'
                 f'<text x="{g["x"]:.1f}" y="{g["y"] + 5:.1f}" text-anchor="middle" font-size="{T.FS_BODY}" font-weight="700" fill="{T.TEXT}" '
                 f'font-family="{e(T.FONT_DISPLAY)}">{e(g["id"])}</text></g>')
        # pickup-zone chip with queue + inbound robotaxis
        w, hh = 120, 42
        x0, y0 = g["px"] - w / 2, g["py"] - hh / 2
        word = {"SURGE": "SURGE", "ELEVATED": "ELEVATED", "NORMAL": "OK"}.get(g["status"], g["status"])
        s.append(f'<g><title>{e(g["pz"])}: {g["inbound"]} robotaxis assigned inbound; queue {g["queue"]:.1f} min</title>'
                 f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w}" height="{hh}" rx="12" fill="{T.SURFACE_RAISED}" stroke="{col if g["status"] != "NORMAL" else (T.BRAND if g["inbound"] else T.BORDER)}" stroke-width="{2 if g["status"] != "NORMAL" else 1.5}"/>'
                 f'<text x="{x0 + 9:.1f}" y="{y0 + 17:.1f}" font-size="{T.FS_BODY}" font-weight="700" fill="{T.TEXT}">{e(g["pz"])}</text>'
                 f'<text x="{x0 + w - 9:.1f}" y="{y0 + 17:.1f}" text-anchor="end" font-size="{T.FS_CAPTION}" font-weight="600" fill="{T.TEXT_2}">{word}</text>'
                 f'<text x="{x0 + 9:.1f}" y="{y0 + 35:.1f}" font-size="{T.FS_BODY}" font-weight="600" fill="{T.TEXT}" font-family="{e(T.FONT_MONO)}">{g["queue"]:.1f} min</text>'
                 f'<text x="{x0 + w - 9:.1f}" y="{y0 + 35:.1f}" text-anchor="end" font-size="{T.FS_CAPTION}" fill="{T.TEXT_2}">{g["inbound"]} in</text>')
        if m.get("lane_gate") == g["id"]:
            s.append(f'<title>Lane reallocation proposed: needs operator approval</title>'
                     f'<circle cx="{x0 + w - 4:.1f}" cy="{y0 - 2:.1f}" r="11" fill="{T.SURFACE}" stroke="{T.ACCENT}" stroke-width="2"/>'
                     + icons.symbol("lock", x0 + w - 10, y0 - 8, 12, T.ACCENT, 2.2))
        s.append("</g>")
    for p in m["precinct"]:
        if p["kind"] == "metro":
            s.append(f'<g><title>{e(p["name"])}: {p["load"]:.0f}% load</title><circle cx="{p["x"]:.1f}" cy="{p["y"]:.1f}" r="15" fill="{T.SURFACE}" stroke="{T.INFO}" stroke-width="2"/>'
                     + icons.symbol("train", p["x"] - 8, p["y"] - 8, 16, T.TEXT)
                     + f'<text x="{p["x"]:.1f}" y="{p["y"] + 32:.1f}" text-anchor="middle" font-size="{T.FS_CAPTION}" fill="{T.TEXT_2}">Metro {p["id"][-1]} {p["load"]:.0f}%</text></g>')
        elif not any(hb["venue"] and abs(hb["x"] - p["x"]) < 1 for hb in m["hubs"]):
            s.append(f'<g><title>{e(p["name"])}</title><circle cx="{p["x"]:.1f}" cy="{p["y"]:.1f}" r="15" fill="{T.SURFACE}" stroke="{T.BRAND}" stroke-width="2"/>'
                     + icons.symbol("car", p["x"] - 8, p["y"] - 8, 16, T.TEXT)
                     + f'<text x="{p["x"]:.1f}" y="{p["y"] + 32:.1f}" text-anchor="middle" font-size="{T.FS_CAPTION}" fill="{T.TEXT_2}">{"West" if p["id"].endswith("W") else "East"} staging</text></g>')
    for hb in m["hubs"]:
        col, ic = _HUB_TONE.get(hb["verdict"], (T.TEXT_2, "plug"))
        blocked = hb["verdict"] in ("STALE", "OFFLINE")
        up = hb["y"] < cy or hb["venue"]
        state = {"VERIFIED": f'{hb["slots"]}/{hb["total"]} slots', "STALE": f'STALE {hb["age"]:.0f} min', "OFFLINE": f'OFFLINE {hb["age"]:.0f} min'}.get(hb["verdict"], hb["verdict"])
        name = "Venue hub" if hb["venue"] else (hb["short"] if len(hb["short"]) <= 3 else hb["short"].title())  # keep acronyms (JBR)
        ty = hb["y"] - 25 if up else hb["y"] + 31
        tip = (f'{name}: {hb["verdict"]}; telemetry {hb["age"]:.1f} min old (threshold {m["stale_minutes"]:.0f} min)'
               + ("; routing blocked by code" if blocked else ""))
        dash = ' stroke-dasharray="4 3"' if blocked else ""
        s.append(f'<g><title>{e(tip)}</title><circle cx="{hb["x"]:.1f}" cy="{hb["y"]:.1f}" r="16" fill="{T.SURFACE}" stroke="{col}" stroke-width="3"'
                 f'{dash}/>' + icons.symbol(ic, hb["x"] - 8, hb["y"] - 8, 16, T.TEXT)
                 + f'<text x="{hb["x"]:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="{T.FS_BODY}" font-weight="700" fill="{T.TEXT}" stroke="{T.SURFACE}" stroke-width="4" paint-order="stroke">{e(name)}</text>'
                 f'<text x="{hb["x"]:.1f}" y="{ty + (14 if not up else 14):.1f}" text-anchor="middle" font-size="{T.FS_CAPTION}" font-weight="{600 if blocked else 500}" fill="{T.TEXT_2}" stroke="{T.SURFACE}" stroke-width="4" paint-order="stroke">{e(state)}</text></g>')
    s.append("</svg>")
    return '<div class="mf-map">' + "".join(s) + "</div>"


def map_legend() -> str:
    def sw(c, dash=False):
        d = ' stroke-dasharray="3 2"' if dash else ""
        return (f'<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" fill="{T.SURFACE}" stroke="{c}" stroke-width="3"{d}/></svg>')
    return (f'<div class="mf-legend"><span>{sw(T.OK)}Normal gate or verified hub</span><span>{sw(T.WARN)}Elevated / stale hub</span>'
            f'<span>{sw(T.DANGER)}Surge gate / offline hub</span><span>{sw(T.TEXT_2, True)}Dashed ring: routing blocked by code</span>'
            f'<span>{icon("route", 16)}Animated line: robotaxis inbound</span><span class="mf-small">Schematic, not to scale. Hubs sit at their compass bearing.</span></div>')


def gate_queue_rows(gates: list[dict], target_min: float = 20.0) -> str:
    vmax = max([g["est_pickup_wait_min"] for g in gates] + [target_min * 1.2])
    rows = ""
    for g in gates:
        col = _GATE_TONE.get(g["status"], T.OK)
        word = {"SURGE": "surge", "ELEVATED": "elevated"}.get(g["status"], "")
        ic = {"SURGE": "alert", "ELEVATED": "alert"}.get(g["status"], "check")
        rows += (f'<div class="mf-gq-row"><span class="nm">{e(g["name"])}</span>{charts.hbar(g["est_pickup_wait_min"], vmax, col, floor_marker=target_min)}'
                 f'<span class="val">{icon(ic, 14)} {g["est_pickup_wait_min"]:.1f} min {e(word)}</span></div>')
    return f'<div class="mf-gq" aria-label="Pickup queue by gate; dashed tick marks the {target_min:.0f} minute target">{rows}</div>'


# ------------------------------------------------------------------------------------- charger network
def charger_card(c: dict, stale_minutes: float) -> str:
    tone = {"VERIFIED": "ok", "STALE": "warn", "OFFLINE": "danger"}.get(c["verdict"], "neutral")
    age = f'{c["telemetry_age_min"]:.0f} min ago' if c["telemetry_age_min"] >= 10 else f'{c["telemetry_age_min"]:.1f} min ago'
    slots = (f'{c["available_slots"]} of {c["total_slots"]} free' if c["verdict"] == "VERIFIED"
             else f'{c["available_slots"]} reported (unverified)' if c["verdict"] == "STALE" else "unavailable")
    note = ""
    if c["verdict"] in ("STALE", "OFFLINE"):
        what = ("Last update " + age + f", threshold {stale_minutes:.0f} min." if c["verdict"] == "STALE"
                else f"Node offline, last update {age}.")
        note = (f'<div class="block-note">{icon("shield-x", 18)}<div><b>{what}</b><br>Routing blocked by code, not by the LLM. '
                f'Low-battery vehicles are sent to verified hubs instead.</div></div>')
    return (f'<div class="mf-charger t-{tone}"><div class="mf-charger-head"><h3>{e(c["name"])}<span class="id">{e(c["charger_id"])}</span></h3>'
            f'{status_pill(c["verdict"])}</div><dl><dt>Slots</dt><dd>{e(slots)}</dd><dt>Telemetry</dt><dd>{e(age)}</dd>'
            f'<dt>Power</dt><dd>{c["power_kw"]} kW</dd><dt>Charging here</dt><dd>{c.get("fleet_vehicles_charging_here", 0)} robotaxis</dd></dl>{note}</div>')


# ------------------------------------------------------------------------- human operator approval gate
_ACTION = {"LANE_REVERSAL": "Reverse a lane", "PICKUP_ZONE_LANE_REALLOCATION": "Reallocate a lane to robotaxi pickup",
           "SIGNAL_PRIORITY_OVERRIDE": "Override signal priority"}


def approval_panel(req: dict, gate_name: str, decision: dict | None = None, blocked: dict | None = None) -> str:
    """Premium gold-glass panel: the physical action, the agent's rationale, risk notes and (after the choice) the confirmation."""
    p = req["payload"]
    action = _ACTION.get(req["action_type"], req["action_type"].replace("_", " ").title())
    status = req["status"]
    delta = p.get("wait_after_min", 0) - p.get("wait_before_min", 0)
    stats = (f'<div class="mf-ap-stats"><div class="mf-ap-stat"><div class="k">Queue now</div><div class="v">{p.get("wait_before_min")} min</div></div>'
             f'<div class="mf-ap-stat"><div class="k">This lane alone</div><div class="v good">{p.get("wait_after_min")} min</div></div>'
             f'<div class="mf-ap-stat"><div class="k">Curb throughput</div><div class="v">{p.get("throughput_after_vpm")}'
             f'<span class="mf-small"> veh/min (now {p.get("throughput_before_vpm")})</span></div></div></div>') if "wait_before_min" in p else ""
    result = ""
    if decision:
        ok = decision["decision"] == "APPROVE"
        result = (f'<div class="mf-ap-result {"ok" if ok else "bad"}">{icon("check-circle" if ok else "x-circle", 24)}<div><b>'
                  f'{"Approved and executed" if ok else "Rejected"}.</b> {e(decision["message"])} Recorded in the audit log.</div></div>')
    # The agent's justification often opens by repeating the action description; show it once (display only, data unchanged).
    why = str(req["justification"])
    desc = str(p.get("description", ""))
    if desc and why.startswith(desc):
        why = why[len(desc):].strip() or why
    bypass = ""
    if blocked:
        bypass = callout(f'<span class="mf-mono">{e(blocked["reasons"][0])}</span><br>Blocked by code, not by the LLM.', "danger", "shield-x",
                         "Execution without approval refused")
    return (f'<div class="mf-ap-head"><span class="lock">{icon("lock", 22)}</span><div class="ttl"><span class="mf-eyebrow">Operator approval required</span>'
            f'<h2>{e(action)} at {e(gate_name)} pickup zone ({e(p.get("pickup_zone", ""))})</h2></div>'
            f'{brand.logo_mark(32, "ap")}{status_pill(status)}</div>'
            f'<div class="mf-ap-body">{stats}'
            f'<div class="mf-ap-block"><span class="k">Requested physical change</span>{e(p.get("description", ""))}</div>'
            f'<div class="mf-ap-block"><span class="k">Agent rationale</span>{e(why)}</div>'
            f'<div class="mf-ap-block"><span class="k">Risk and controls</span>Physical change on a public road: it can only run with a human decision. '
            f'The approval is a one-time token bound to this request. Both outcomes are written to the audit log.</div>'
            f'<div class="mf-ap-meta"><span>request {e(req.get("request_id") or req.get("id", ""))}</span><span>action {e(req["action_type"])}</span></div>'
            f'{result}{bypass}</div>')


# ------------------------------------------------------------------------------------ loading state
def loader(status: str = "Agent cycle running") -> str:
    stages = ("Reading snapshot", "Running optimizer", "Checking guards", "Dispatching", "Requesting approval", "Writing report")
    chips = "".join(f'<span class="stage">{e(s)}</span>' for s in stages)
    skels = '<div class="mf-skels">' + '<div class="mf-skel"></div>' * 6 + "</div>"
    return (f'<div class="mf-loader" role="status" aria-live="polite"><div class="logo">{brand.logo_mark(64, "ld")}</div>'
            f'<div class="status">{e(status)}...</div><div class="stages">{chips}</div>{skels}</div>')




# --------------------------------------------------------------------------------------------- sign-in hero
def login_hero() -> str:
    """Left panel of the sign-in page: brand idea, three promises, animated waterline."""
    pts = [("car", "Riders", "Book a robotaxi that is battery-checked before it is sent, and get the fastest pickup gate."),
           ("spark", "Operators", "Run the AI orchestration agent, see exactly what it decided, and approve lane changes."),
           ("shield-check", "Safety in code", "Every trip keeps a 15% battery reserve. Stale or offline chargers are never used.")]
    items = "".join(f'<li><span class="ic">{icon(i, 20)}</span><div><b>{t}</b>{e(d)}</div></li>' for i, t, d in pts)
    wave = ("M0 60 C 80 20 160 100 240 60 S 400 20 480 60 S 640 100 720 60 S 880 20 960 60 S 1120 100 1200 60 S 1360 20 1440 60 "
            "S 1600 100 1680 60 S 1840 20 1920 60")
    waves = (f'<svg class="waves" viewBox="0 0 960 120" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="mflw" x1="0" x2="1">'
             f'<stop offset="0" stop-color="{T.BRAND}"/><stop offset="1" stop-color="{T.BRAND_BLUE}"/></linearGradient></defs>'
             f'<g class="wave-a"><path d="{wave}" fill="none" stroke="url(#mflw)" stroke-width="2.2"/>'
             f'<path d="{wave}" transform="translate(0 22)" fill="none" stroke="url(#mflw)" stroke-width="1.6" stroke-opacity=".6"/>'
             f'<path d="{wave}" transform="translate(0 44)" fill="none" stroke="url(#mflw)" stroke-width="1.2" stroke-opacity=".35"/></g></svg>')
    return (f'<section class="mf-login-hero"><div>{brand.logo_svg(48, "lg")}'
            f'<p class="mf-eyebrow mf-spaced">Operator command center for event-night mobility</p>'
            f'<h1 class="mf-display"><span class="mf-gradient-text">{e(T.BRAND_IDEA)}</span></h1>'
            f'<p class="mf-muted mf-lead">{e(T.TAGLINE)} MarinaFleet clears 60,000 fans in 90 minutes with an AI agent that decides and Python code that verifies.</p></div>'
            f'<ul class="mf-points">{items}</ul>{waves}</section>')
