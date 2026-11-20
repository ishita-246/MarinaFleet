<p align="center"><img src="../assets/logo.svg" alt="MarinaFleet" height="56"></p>

# MarinaFleet brand guide

**Clear the stadium. Protect every battery.**

MarinaFleet is an operator command center for event-night mobility in Dubai. The brand idea is
*Intelligence that moves a city.* The feel is calm, precise, trustworthy and a little futuristic: air-traffic
control meets premium EV. Nothing on screen should shout, and every colour should mean something.

**Single source of truth:** `ui/theme.py` holds every colour, font, size, radius, space, shadow and duration as
a constant. It generates CSS variables (`--mf-*`) that `ui/styles.css` consumes. Python HTML and SVG read the same
constants. `tests/test_ui_design.py` fails the build if a hex colour, a raw font size or font family, a raw
radius or an inline `style=` appears anywhere outside `theme.py`. Structural dimensions such as border widths,
control heights and grid column counts stay in the CSS on purpose; they are layout, not brand.

---

## 1. Logo

![MarinaFleet logo](../assets/logo.svg)

| File | Use |
|---|---|
| `assets/logo.svg` | Full lockup: mark + wordmark. Header, login, README, slides. |
| `assets/logo-mark.svg` | Mark only. Loader, approval panel, avatars, small spaces. |
| `assets/favicon.svg`, `assets/favicon.png` | Browser tab. Generated, no emoji. |

**The mark** is a rounded battery cell with a gradient outline. Inside it, a bolt (energy) sits over a single
wave (the route and the Marina waterfront). **The wordmark** sets "Marina" in Space Grotesk Light and "Fleet" in
Bold, in the brand gradient.

- Clear space: at least half the mark's height on every side.
- Minimum height: 20 px for the lockup, 16 px for the mark alone.
- Use on `#0B1220` or `#121B2E` only. Do not place it on bright fills, recolour it, stretch it, or add effects.
- Regenerate all assets with `python -m ui.brand` (the test suite checks the files match the generator).

## 2. Palette

Dark theme only. Values below are the constants in `ui/theme.py`. Ratios are WCAG contrast measured with
`theme.contrast_ratio()`.

**Surfaces and text**

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `BG_BASE` | `#0B1220` | Page background | `TEXT` on it: 16.1:1 |
| `SURFACE` | `#121B2E` | Cards, panels | `TEXT`: 14.8:1 |
| `SURFACE_RAISED` | `#18233B` | Hover, nested blocks, inputs | `TEXT`: 13.4:1 |
| `BORDER` | `#24324F` | Hairlines, grid lines | decorative |
| `TEXT` | `#E8EEF9` | Primary text | see above |
| `TEXT_2` | `#9FB0CC` | Secondary text | 7.8:1 on surface |
| `TEXT_MUTED` | `#8091B0` | Captions, units, tertiary | 5.4:1 on surface, 4.9:1 on raised |

**Brand and meaning**

| Token | Hex | Used for |
|---|---|---|
| `BRAND` | `#19D3C5` | Primary teal. Primary actions, MarinaFleet data, **AGENT** badge. |
| `BRAND_BLUE` | `#4DA3FF` | Second end of the brand gradient. Also the Info tone. |
| `ACCENT` | `#F2B544` | Sand-gold. **CODE** badge, operator approval, premium moments. |
| `OK` | `#2ECC8F` | Safe, healthy, approved |
| `WARN` | `#F5A524` | Caution, stale, low battery |
| `DANGER` | `#FF5C6C` | Blocked, offline, Gate 4 surge, rejected |
| `INFO` | `#4DA3FF` | Neutral information |
| `GRADIENT` | `#19D3C5` to `#4DA3FF`, 135° | Logo, primary button, one key heading. Sparingly. |

Text on a bright fill uses `INK` (= `BG_BASE`): 9.9:1 on teal, 10.2:1 on gold, 6.2:1 on danger red.
Tinted tones (pills, callouts) are computed by `theme.mix()` as 14% of the colour over `SURFACE`, so each
tone's text/background pair is a solid, testable pair (4.8:1 to 7.1:1; all pass AA).

**Deviation from the brief:** the specified muted text `#6B7C9A` measures only 4.07:1 on `SURFACE`, below the
WCAG AA 4.5:1 minimum for body text. `TEXT_MUTED` is therefore lightened to `#8091B0`. This is the only palette
value changed.

**Colour is never the only signal.** Every status pill, badge, banner and chart mark also carries an icon, a text
label or a pattern.

## 3. Typography

| Role | Font | Fallback |
|---|---|---|
| Headings, big numbers | Space Grotesk (Sora as alternate) | system-ui |
| Body | Inter | system-ui, Segoe UI, Roboto |
| Data (IDs, SoC, timestamps) | JetBrains Mono | ui-monospace, Menlo, Consolas |

Fonts load by one Google Fonts `@import` at the top of the injected stylesheet. If the network blocks it, the system
fallbacks are used and the layout still holds.

Scale: **32** display, **24** page title, **18** section, **14** body (minimum), **12** caption.
One oversized `FS_HERO` (56) is reserved for the rider's pickup ETA. Numbers use tabular figures so columns line up.

## 4. Shape, space, depth, motion

- **Grid:** 8 px. Spacing tokens `S1`..`S5`.
- **Radius:** 16 px cards, 12 px controls, pill 999.
- **Depth:** `SHADOW_1` on cards, `SHADOW_2` on raised and modal-like panels. Glass (translucent surface + blur) only on
  the top bar, the login hero, the loader and the operator-approval panel.
- **Icons:** one set only: 24 px, 1.75 stroke, round caps (`ui/icons.py`, 52 icons). No emoji anywhere in the UI.
- **Motion:** timeline items fade and slide in, live indicators pulse softly, the surge ring pings, the loader
  breathes. Durations are tokens (`150 / 260 / 600 ms`). Under `prefers-reduced-motion` all animation stops and the
  static ring stays visible.

## 5. Components

All live in `ui/components.py` and return an HTML string (or render it with `show()`). Pages in `app.py` and
`ui/*.py` use nothing else.

| Component | Purpose | Example |
|---|---|---|
| `brand_header(right_html)` | Top bar: logo and tagline left, clock and status right | `brand_header(event_clock(c) + status_pill("ONLINE"))` |
| `kpi_card(label, icon_name, tone, value, unit, sub, delta)` | One metric with a small delta | `kpi_card("Avg pickup wait", "clock", "brand", "13.8", "min", delta=...)` |
| `status_pill(status)` / `pill(text, tone, icon_name)` | State, always icon + label | `status_pill("STALE")` |
| `section_title(title, icon_name, hint)` | Section header with a one-line "why" | `section_title("Charger network", "plug", "Only verified hubs receive cars.")` |
| `callout(body, tone, icon_name, title)` | Inline message in a semantic tone | `callout("Routing blocked by code, not by the LLM.", "danger", "shield-x")` |
| `timeline_item(kind, title, detail, status)` | Trace row: `agent` / `code` / `guard` / `human` | `timeline_item("guard", "Dispatch blocked", "Would reach 8.7%")` |
| `battery_bar(soc)` | SoC bar with a visible 15% floor line | red below 15, amber 15 to 30, green from 30 |
| `charger_card(c, stale_minutes)` | Hub status with telemetry age against the threshold | stale/offline hubs show the refusal line |
| `approval_panel(req, gate, decision)` | Gold premium panel for physical changes | lock icon, action, rationale, risk, state |
| `gate_map(model)` | Schematic operations map, gates 1 to 6 | Gate 4 pulses red when surging |

**Charts** (`ui/charts.py`) are inline SVG, not Plotly or Matplotlib: `grouped_bars`, `single_bars`, `hbar`. They share
one template (`theme.CHART`). Series colours belong to the *entity*, never to its rank:

| Entity | Colour |
|---|---|
| Naive baseline | `#8A9BBF` (muted grey-blue) |
| Greedy + 15% | `#F2B544` (gold) |
| MarinaFleet | `#19D3C5` (teal) |

Every chart has a legend for two or more series, value labels on the bars, hover tooltips, a hatch pattern on
hypothetical bars and a "View as table" fallback.

**Chart palette validation (honest result).** Run with the dataviz validator against the `#121B2E` surface: colour-blind
separation passes (worst adjacent pair ΔE 15.1 under protanopia), normal-vision separation passes (22.5) and every mark
clears 3:1 contrast. Two checks **fail** by design: the *lightness band* (teal and gold are brighter than the validator's
preferred range, and the grey-blue is slightly dimmer) and the *chroma floor* (the baseline is deliberately a muted
grey-blue, which the validator reads as grey). These follow the specified palette, where the baseline must recede.
The mitigation is the legend, value labels, tooltips, hatching and the table view, so no reading depends on hue alone.

## 6. Voice

- Short, calm, factual. No exclamation marks, no emoji, no jargon without a reason.
- Every block says **why** in one sentence and then gives the **technical value**.
  *"Only verified hubs receive cars. JBR telemetry is 23.0 min old against a 5 min limit."*
- Fixed terms: **Robotaxi**, **Feeder bus**, **Charger hub**, **Operator approval**. Do not mix in "cab", "EV taxi",
  "station" or "sign-off".
- Buttons are verbs: *Run event-night scenario*, *Approve change*, *Reject change*, *Confirm booking*.
- Authority is explicit. Say who acted: **AGENT** (LLM decided), **CODE** (Python computed or enforced),
  **BLOCKED BY GUARD** (code refused), **OPERATOR** (human decided).
- The line to keep: **"Routing blocked by code, not by the LLM."**

## 7. Accessibility checklist

- WCAG AA contrast on all text (tested in `tests/test_ui_design.py`).
- Body text 14 px or larger. KPI values and the map are readable at projector distance.
- Status is always icon + text, never colour alone.
- Visible focus ring on every control; hover states on cards, tabs and buttons.
- `prefers-reduced-motion` disables animation.
- Layout checked at 1366 x 768 in the offline preview (see README, "Verification").
