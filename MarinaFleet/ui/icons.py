"""
One icon set for the whole product: 24x24 outline icons (1.75 stroke, round caps), drawn inline as SVG.
Never mix with emoji. Icons inherit the surrounding text colour (stroke="currentColor").
"""
from __future__ import annotations

_P = {
    "bolt": '<path d="M13 2.5 5 13.5h6.2L10 21.5l8-11h-6.2z"/>',
    "battery": '<rect x="2.5" y="7" width="16" height="10" rx="2.2"/><path d="M21.5 10.5v3"/><path d="M6 10.5v3M9.5 10.5v3M13 10.5v3"/>',
    "battery-low": '<rect x="2.5" y="7" width="16" height="10" rx="2.2"/><path d="M21.5 10.5v3"/><path d="M6 10.5v3"/>',
    "spark": '<path d="M11 3.5 12.9 9l5.6 1.9-5.6 1.9L11 18.4l-1.9-5.6L3.5 10.9 9.1 9z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
    "terminal": '<path d="M4.5 7.5 9.5 12l-5 4.5"/><path d="M12.5 17h7"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6"/>',
    "user": '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c0-4 3.3-6.2 7.5-6.2s7.5 2.2 7.5 6.2"/>',
    "users": '<circle cx="9" cy="8.2" r="3.3"/><path d="M2.8 19.5c0-3.5 2.7-5.6 6.2-5.6s6.2 2.1 6.2 5.6"/><path d="M15.6 5a3.3 3.3 0 0 1 0 6.4M18 14.2c2 .7 3.2 2.5 3.2 5.3"/>',
    "shield": '<path d="M12 3 4.5 6v5.6c0 4.5 3.1 7.9 7.5 9.4 4.4-1.5 7.5-4.9 7.5-9.4V6z"/>',
    "shield-check": '<path d="M12 3 4.5 6v5.6c0 4.5 3.1 7.9 7.5 9.4 4.4-1.5 7.5-4.9 7.5-9.4V6z"/><path d="m8.6 12 2.4 2.4 4.4-4.6"/>',
    "shield-x": '<path d="M12 3 4.5 6v5.6c0 4.5 3.1 7.9 7.5 9.4 4.4-1.5 7.5-4.9 7.5-9.4V6z"/><path d="m9.4 9.6 5.2 5.2M14.6 9.6l-5.2 5.2"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2.4"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/><path d="M12 14.5v2.2"/>',
    "unlock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2.4"/><path d="M8 10.5V8a4 4 0 0 1 7.6-1.7"/>',
    "check": '<path d="m5 12.6 4.4 4.4L19 7.4"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.4 2.7 2.7L16 9.6"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "x-circle": '<circle cx="12" cy="12" r="9"/><path d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6"/>',
    "alert": '<path d="M12 3.6 21.4 20H2.6z"/><path d="M12 10v4.4"/><path d="M12 17.4v.1"/>',
    "alert-circle": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5"/><path d="M12 16v.1"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.2"/><path d="M12 7.7v.1"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 1.8"/>',
    "car": '<path d="M5 17v-4.6l1.7-4.5A2.2 2.2 0 0 1 8.8 6.4h6.4a2.2 2.2 0 0 1 2.1 1.5L19 12.4V17"/><path d="M3.8 12.4h16.4"/><path d="M4.5 17h15v2.1h-3.2V17M7.7 17v2.1H4.5"/><path d="M7.8 14.9h.1M16.1 14.9h.1"/>',
    "bus": '<rect x="4.5" y="3.8" width="15" height="13.4" rx="2.6"/><path d="M4.5 11h15"/><path d="M7.5 17.2v2.3M16.5 17.2v2.3"/><path d="M8 14.2h.1M16 14.2h.1"/>',
    "train": '<rect x="5" y="3.2" width="14" height="14" rx="3.2"/><path d="M5 10.8h14"/><path d="M9 20.8 7.2 22.5M15 20.8l1.8 1.7M8.6 14.2h.1M15.4 14.2h.1"/>',
    "plug": '<path d="M9 3v4.5M15 3v4.5"/><path d="M6 7.5h12v3.2a6 6 0 0 1-12 0z"/><path d="M12 16.7V21"/>',
    "wifi-off": '<path d="M3 3l18 18"/><path d="M8.6 8.9A12 12 0 0 0 2.5 12.2M5.8 15.6a8 8 0 0 1 4.1-2M15.3 9.2a12 12 0 0 1 6.2 3M17.3 13.5a8 8 0 0 0-1.9-1.2"/><path d="M12 19.2v.1"/>',
    "pin": '<path d="M12 21s-6.8-5.9-6.8-11.1A6.8 6.8 0 0 1 12 3a6.8 6.8 0 0 1 6.8 6.9C18.8 15.1 12 21 12 21z"/><circle cx="12" cy="9.8" r="2.4"/>',
    "route": '<circle cx="6" cy="18.5" r="2.4"/><circle cx="18" cy="5.5" r="2.4"/><path d="M8.4 18.5H15a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h6.6"/>',
    "activity": '<path d="M3 12h3.6l2.6-7 5 14 2.6-7H21"/>',
    "gauge": '<path d="M4.2 17.5a8.6 8.6 0 1 1 15.6 0"/><path d="m12 13.5 3.6-4.6"/><path d="M12 13.5h.1"/>',
    "sun": '<circle cx="12" cy="12" r="3.8"/><path d="M12 2.8v2M12 19.2v2M2.8 12h2M19.2 12h2M5.5 5.5l1.4 1.4M17.1 17.1l1.4 1.4M18.5 5.5l-1.4 1.4M6.9 17.1l-1.4 1.4"/>',
    "cloud-rain": '<path d="M7 15.5a4.2 4.2 0 0 1-.5-8.3A5.6 5.6 0 0 1 17.2 8a3.8 3.8 0 0 1-.2 7.5z"/><path d="M8.5 18.5l-.8 2M12.5 18.5l-.8 2M16.5 18.5l-.8 2"/>',
    "cloud-fog": '<path d="M7 13.5a4.2 4.2 0 0 1-.5-8.3A5.6 5.6 0 0 1 17.2 6a3.8 3.8 0 0 1-.2 7.5z"/><path d="M4 17h16M7 20.5h10"/>',
    "log-out": '<path d="M9.5 4.5h-4A1.5 1.5 0 0 0 4 6v12a1.5 1.5 0 0 0 1.5 1.5h4"/><path d="M15 8l4 4-4 4M19 12H9.5"/>',
    "play": '<path d="M7.5 4.8v14.4L19 12z"/>',
    "key": '<circle cx="8" cy="14.5" r="3.6"/><path d="m10.6 12 8-8M15.8 6.8l2.4 2.4M13.5 9.1l1.8 1.8"/>',
    "file": '<path d="M6.5 3h7.8l4.2 4.2V19a2 2 0 0 1-2 2h-10a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M14 3v4.5h4.5M8.5 12.5h7M8.5 16h5"/>',
    "trend-down": '<path d="m3.5 7.5 6 6 4-4 7 7"/><path d="M15.5 16.5h5v-5"/>',
    "trend-up": '<path d="m3.5 16.5 6-6 4 4 7-7"/><path d="M15.5 7.5h5v5"/>',
    "minus": '<path d="M6 12h12"/>',
    "wave": '<path d="M2.5 9c2.4-3 4.8-3 7.2 0s4.8 3 7.2 0 3.4-2 4.6-.7"/><path d="M2.5 16c2.4-3 4.8-3 7.2 0s4.8 3 7.2 0 3.4-2 4.6-.7"/>',
    "lane": '<path d="M7 3 4.5 21M17 3l2.5 18"/><path d="M12 4v3M12 10.5v3M12 17v3"/>',
    "signal": '<rect x="9" y="3" width="6" height="18" rx="3"/><path d="M12 7.2v.1M12 12v.1M12 16.8v.1"/>',
    "database": '<ellipse cx="12" cy="6" rx="7.5" ry="3"/><path d="M4.5 6v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6M4.5 12v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/>',
    "download": '<path d="M12 4v11M7.5 10.8 12 15.3l4.5-4.5M4.5 19.5h15"/>',
    "list": '<path d="M8.5 6.5H20M8.5 12H20M8.5 17.5H20M4 6.5h.1M4 12h.1M4 17.5h.1"/>',
    "refresh": '<path d="M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3"/><path d="M18.5 3v4h-4M5.5 21v-4h4"/>',
    "ticket": '<path d="M4 8.2A2 2 0 0 0 4 12v0a2 2 0 0 1 0 3.8V18a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2.2a2 2 0 0 1 0-3.8v0a2 2 0 0 0 0-3.8V6a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1z"/><path d="M14 5v14" stroke-dasharray="2 2.4"/>',
    "walk": '<circle cx="13" cy="4.6" r="1.8"/><path d="m10 21 1.7-6.2-2.4-2.4 1.2-5 3.3 2 2.7.7M9.3 12.4 7 14.2M12.2 14.8 14.5 21"/>',
    "megaphone": '<path d="M4 10v4h3l7 4V6L7 10z"/><path d="M17.5 9.5a4 4 0 0 1 0 5"/>',
    "stadium": '<ellipse cx="12" cy="12" rx="9" ry="6"/><ellipse cx="12" cy="12" rx="4.6" ry="2.6"/>',
    "inbox": '<path d="M4 13.5 6.4 5.5h11.2l2.4 8"/><path d="M4 13.5V18a1.5 1.5 0 0 0 1.5 1.5h13A1.5 1.5 0 0 0 20 18v-4.5h-4.6a3.4 3.4 0 0 1-6.8 0z"/>',
}


def icon(name: str, size: int = 16, cls: str = "") -> str:
    """Inline SVG icon. `size` is the rendered px size; decorative (aria-hidden)."""
    body = _P[name]
    c = f' class="mf-ico {cls}"' if cls else ' class="mf-ico"'
    return (f'<svg{c} width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')


ICON_NAMES = tuple(_P)


def symbol(name: str, x: float, y: float, size: float, color: str, width: float = 1.75) -> str:
    """Icon as a <g> for use *inside* another SVG (the operations map): top-left at (x, y), square `size`, stroke `color`."""
    return (f'<g transform="translate({x:.1f} {y:.1f}) scale({size / 24:.3f})" fill="none" stroke="{color}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_P[name]}</g>')
