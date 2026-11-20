"""
MarinaFleet brand assets, generated from the tokens in ui/theme.py (so logo colours can never drift from the UI).

    python -m ui.brand        # rewrites assets/logo.svg, assets/logo-mark.svg, assets/favicon.svg, assets/favicon.png

The mark: a rounded cell (battery) holding a lightning bolt, with a flowing wave line beneath it (the Marina
waterfront and a fleet route). The wordmark pairs a light "Marina" with a bold "Fleet" in the brand gradient.
"""
from __future__ import annotations

from pathlib import Path

from ui import theme as T

ASSETS = T.ROOT_DIR / "assets"


def _defs(uid: str) -> str:
    return (f'<defs><linearGradient id="mfg-{uid}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{T.BRAND}"/><stop offset="1" stop-color="{T.BRAND_BLUE}"/></linearGradient></defs>')


def _mark_body(uid: str) -> str:
    g = f"url(#mfg-{uid})"
    return (f'<rect x="3" y="3" width="42" height="42" rx="13" fill="{T.SURFACE}" stroke="{g}" stroke-width="2.4"/>'
            f'<path d="M26.6 8.5 15.2 25.2h7.4l-1.9 10.3 11.5-16.6h-7.4z" fill="{g}"/>'
            f'<path d="M8.4 37.6c2.6-3.4 5.2-3.4 7.8 0s5.2 3.4 7.8 0 5.2-3.4 7.8 0 3.2 2.2 4.6.6" fill="none" stroke="{g}" '
            f'stroke-width="2.2" stroke-linecap="round"/>')


def logo_mark(size: int = 40, uid: str = "m") -> str:
    """The symbol alone (favicon, sidebar, loading state)."""
    return (f'<svg class="mf-logo-mark" width="{size}" height="{size}" viewBox="0 0 48 48" role="img" aria-label="{T.PRODUCT}">'
            f'{_defs(uid)}{_mark_body(uid)}</svg>')


def logo_svg(height: int = 40, uid: str = "l", plate: bool = False) -> str:
    """Full lockup: mark + 'Marina' (light) + 'Fleet' (bold) in the brand gradient. `plate` adds a navy background
    so the logo stays legible on any page (README, slides)."""
    w = round(height * 4.5)
    g = f"url(#mfg-{uid})"
    bg = f'<rect width="216" height="48" rx="12" fill="{T.BG_BASE}"/>' if plate else ""
    off = 8 if plate else 0
    return (f'<svg class="mf-logo" width="{w}" height="{height}" viewBox="0 0 216 48" role="img" aria-label="{T.PRODUCT}" '
            f'xmlns="http://www.w3.org/2000/svg">{_defs(uid)}{bg}<g transform="translate({off} 0)">{_mark_body(uid)}</g>'
            f'<text x="{58 + off}" y="32" fill="{g}" font-family="{T.FONT_DISPLAY}" font-size="25" letter-spacing="-0.4">'
            f'<tspan font-weight="300">Marina</tspan><tspan font-weight="700">Fleet</tspan></text></svg>')


def favicon_svg() -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 48 48">{_defs("f")}'
            f'{_mark_body("f")}</svg>')


def standalone(svg: str) -> str:
    """Add the xmlns that a stand-alone .svg file needs."""
    return svg if "xmlns=" in svg else svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)


def build_assets(png: bool = True) -> list[Path]:
    ASSETS.mkdir(exist_ok=True)
    out = {
        "logo.svg": logo_svg(48, "a", plate=True),
        "logo-mark.svg": standalone(logo_mark(64, "b")),
        "favicon.svg": favicon_svg(),
    }
    paths = []
    for name, svg in out.items():
        p = ASSETS / name
        p.write_text(svg + "\n", encoding="utf-8")
        paths.append(p)
    if png:
        try:  # PNG favicon for st.set_page_config(page_icon=...); needs Playwright, skipped if unavailable
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                pg = b.new_page(viewport={"width": 64, "height": 64}, device_scale_factor=2)
                pg.set_content(f'<style>body{{margin:0}}</style>{favicon_svg()}')
                pg.screenshot(path=str(ASSETS / "favicon.png"), omit_background=True)
                b.close()
            paths.append(ASSETS / "favicon.png")
        except Exception as exc:  # pragma: no cover
            print("favicon.png not rebuilt:", exc)
    return paths


def page_icon() -> str:
    """Path for st.set_page_config(page_icon=...); falls back to a Material symbol (never an emoji)."""
    p = ASSETS / "favicon.png"
    return str(p) if p.exists() else ":material/bolt:"


if __name__ == "__main__":
    for path in build_assets():
        print("wrote", path)
