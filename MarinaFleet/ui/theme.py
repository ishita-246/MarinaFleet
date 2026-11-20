"""
MarinaFleet design tokens: the single source of truth for every colour, size, font and chart style.

Nothing in this module imports Streamlit, so it can be used by the CSS builder, the SVG chart helpers,
the brand-asset generator and the tests. Every other UI file (components, charts, pages, styles.css) must read
these constants instead of writing its own hex codes or pixel sizes; tests/test_ui_design.py enforces that.

Brand idea: "Intelligence that moves a city."  Water, light and motion.
Tagline:    "Clear the stadium. Protect every battery."
"""
from __future__ import annotations

from pathlib import Path

PRODUCT = "MarinaFleet"
TAGLINE = "Clear the stadium. Protect every battery."
BRAND_IDEA = "Intelligence that moves a city."
UI_DIR = Path(__file__).resolve().parent
ROOT_DIR = UI_DIR.parent
CSS_PATH = UI_DIR / "styles.css"

# ----------------------------------------------------------------------------------------------- colour
BG_BASE = "#0B1220"          # app background (deep navy)
SURFACE = "#121B2E"          # cards
SURFACE_RAISED = "#18233B"   # raised cards, inputs, hover
BORDER = "#24324F"           # 1px hairlines

BRAND = "#19D3C5"            # electric teal: fleet, "go", agent-safe actions
BRAND_BLUE = "#4DA3FF"       # second end of the brand gradient (also the Info colour)
ACCENT = "#F2B544"           # sand gold: Dubai warmth, code badge, the operator-approval gate

TEXT = "#E8EEF9"             # primary text
TEXT_2 = "#9FB0CC"           # secondary text
# Spec value was #6B7C9A (3.7:1 on raised cards: fails WCAG AA). Lightened to meet 4.5:1 on every surface.
TEXT_MUTED = "#8091B0"
INK = BG_BASE                # dark text that sits ON bright brand fills (buttons, badges)

OK = "#2ECC8F"               # safe / verified
WARN = "#F5A524"             # warning / stale
DANGER = "#FF5C6C"           # blocked / refused / offline
INFO = BRAND_BLUE

GRADIENT = f"linear-gradient(135deg, {BRAND} 0%, {BRAND_BLUE} 100%)"   # logo, primary buttons, key headings only


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(fg: str, bg: str, alpha: float) -> str:
    """Solid colour = `fg` at `alpha` opacity over `bg` (solid hex so contrast stays testable)."""
    f, b = _rgb(fg), _rgb(bg)
    return "#" + "".join(f"{round(f[i] * alpha + b[i] * (1 - alpha)):02X}" for i in range(3))


def _lin(c: int) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio between two hex colours."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# Semantic tones: text colour, tinted fill (solid, over SURFACE), border.
TONE_FG = {"ok": OK, "warn": WARN, "danger": DANGER, "info": INFO, "brand": BRAND, "accent": ACCENT, "neutral": TEXT_2}
TONES = {name: {"fg": fg, "bg": mix(fg, SURFACE, 0.14), "border": mix(fg, SURFACE, 0.42)} for name, fg in TONE_FG.items()}

# Glass panels (hero, approval gate) are translucent over the page background.
GLASS_BG = "rgba(24, 35, 59, 0.72)"
GLASS_BG_ACCENT = "rgba(242, 181, 68, 0.07)"
OVERLAY_SHADOW = "rgba(2, 6, 14, 0.55)"

# ------------------------------------------------------------------------------------------- typography
FONT_DISPLAY = "'Space Grotesk', 'Sora', system-ui, -apple-system, 'Segoe UI', sans-serif"
FONT_BODY = "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
FONT_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
FONT_IMPORT = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600"
               "&family=Space+Grotesk:wght@300;400;500;600;700&display=swap")

# Type scale in px: display / h1 / h2 / body / caption
FS_DISPLAY, FS_H1, FS_H2, FS_BODY, FS_CAPTION = 32, 24, 18, 14, 12
FS_HERO = 56                 # one oversized number per screen (rider pickup ETA)

# ---------------------------------------------------------------------------------------- space & shape
SPACE = 8                    # 8px grid
S1, S2, S3, S4, S5 = (SPACE * n for n in (1, 2, 3, 4, 5))
R_CARD = 16
R_CONTROL = 12
R_PILL = 999
SHADOW_1 = "0 1px 0 rgba(255,255,255,.03) inset, 0 1px 2px rgba(2,6,14,.45), 0 8px 24px rgba(2,6,14,.28)"
SHADOW_2 = "0 1px 0 rgba(255,255,255,.05) inset, 0 2px 4px rgba(2,6,14,.5), 0 16px 40px rgba(2,6,14,.45)"
GLOW_BRAND = "0 0 0 1px rgba(25,211,197,.35), 0 0 28px rgba(25,211,197,.18)"
GLOW_ACCENT = "0 0 0 1px rgba(242,181,68,.40), 0 0 36px rgba(242,181,68,.16)"

# -------------------------------------------------------------------------------------------- motion
DUR_FAST, DUR_BASE, DUR_SLOW = "150ms", "260ms", "600ms"
EASE = "cubic-bezier(.2,.7,.2,1)"

# ------------------------------------------------------------------------------------------- charts
# Entity colours are fixed everywhere: an approach never changes colour between charts.
# Baseline = muted grey-blue, Greedy+15% = sand gold, MarinaFleet = brand teal.
SERIES_NAIVE = "#8A9BBF"
SERIES_GREEDY = ACCENT
SERIES_MARINA = BRAND
CHART = {
    "surface": SURFACE,
    "font_family": FONT_BODY,
    "font_mono": FONT_MONO,
    "font_size": FS_BODY,
    "label_size": FS_BODY,
    "title_size": FS_BODY,
    "text": TEXT_2,
    "text_strong": TEXT,
    "grid": BORDER,
    "axis": BORDER,
    "bar_radius": 4,         # rounded data end, anchored flat to the baseline
    "bar_gap": 2,            # surface-coloured gap between adjacent fills
    "line_width": 2,
    "series": {"naive": SERIES_NAIVE, "greedy": SERIES_GREEDY, "marina": SERIES_MARINA},
    "series_label": {"naive": "Naive baseline", "greedy": "Greedy + 15%", "marina": "MarinaFleet"},
    "bad": DANGER,
    "ok": OK,
}

# Battery bar: green / amber / red fill with a visible line at the hard 15% floor.
BATTERY_OK_FROM = 30.0
BATTERY_FLOOR = 15.0

# Layout
CONTENT_MAX_WIDTH = 1480
SIDEBAR_WIDTH = 300


def css_variables() -> str:
    """The :root block that styles.css reads. Every value comes from the constants above."""
    v = {
        "bg": BG_BASE, "surface": SURFACE, "raised": SURFACE_RAISED, "border": BORDER,
        "brand": BRAND, "blue": BRAND_BLUE, "accent": ACCENT, "ink": INK,
        "text": TEXT, "text-2": TEXT_2, "muted": TEXT_MUTED,
        "ok": OK, "warn": WARN, "danger": DANGER, "info": INFO,
        "gradient": GRADIENT, "glass": GLASS_BG, "glass-accent": GLASS_BG_ACCENT, "overlay-shadow": OVERLAY_SHADOW,
        "font-display": FONT_DISPLAY, "font-body": FONT_BODY, "font-mono": FONT_MONO,
        "fs-hero": f"{FS_HERO}px", "fs-display": f"{FS_DISPLAY}px", "fs-h1": f"{FS_H1}px", "fs-h2": f"{FS_H2}px",
        "fs-body": f"{FS_BODY}px", "fs-caption": f"{FS_CAPTION}px",
        "s1": f"{S1}px", "s2": f"{S2}px", "s3": f"{S3}px", "s4": f"{S4}px", "s5": f"{S5}px",
        "r-card": f"{R_CARD}px", "r-control": f"{R_CONTROL}px", "r-pill": f"{R_PILL}px",
        "shadow-1": SHADOW_1, "shadow-2": SHADOW_2, "glow-brand": GLOW_BRAND, "glow-accent": GLOW_ACCENT,
        "dur-fast": DUR_FAST, "dur": DUR_BASE, "dur-slow": DUR_SLOW, "ease": EASE,
        "content-max": f"{CONTENT_MAX_WIDTH}px", "sidebar-w": f"{SIDEBAR_WIDTH}px",
        "series-naive": SERIES_NAIVE, "series-greedy": SERIES_GREEDY, "series-marina": SERIES_MARINA,
    }
    for name, t in TONES.items():
        v[f"{name}-fg"], v[f"{name}-bg"], v[f"{name}-bd"] = t["fg"], t["bg"], t["border"]
    return ":root{" + ";".join(f"--mf-{k}:{val}" for k, val in v.items()) + "}"


def stylesheet() -> str:
    """@import first (CSS requires it), then tokens, then the component rules in styles.css."""
    return f"@import url('{FONT_IMPORT}');\n{css_variables()}\n{CSS_PATH.read_text(encoding='utf-8')}"
