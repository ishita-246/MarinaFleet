"""
Brand charts as inline SVG (no Plotly / Matplotlib, so there is no default chart look and no extra dependency).

Every colour and size comes from the shared chart template `theme.CHART`. Chart rules followed (see docs/BRAND_GUIDE.md):
  * one colour per approach, the same in every chart (Naive = grey-blue, Greedy+15% = gold, MarinaFleet = teal);
  * thin bars, 4 px rounded data end anchored flat on the baseline, 2 px surface gap between neighbouring fills;
  * a legend whenever there are two or more series, value labels on the bars, hover tooltips (<title>) per bar;
  * a texture (diagonal hatch) is available as a second, non-colour cue, and every chart has a "View as table" fallback;
  * text always wears text colours, never the series colour.
"""
from __future__ import annotations

import html
import math
import zlib

from ui import theme as T

C = T.CHART
_FONT = f'font-family="{html.escape(C["font_family"], quote=True)}"'


def _e(x) -> str:
    return html.escape(str(x))


def _nice_max(v: float) -> float:
    """Axis maximum = 4 x a round tick step, so the four gridlines land on tidy whole numbers."""
    if v <= 0:
        return 4.0
    exp = math.floor(math.log10(v / 4))
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10):
        if 4 * step * 10 ** exp >= v:
            return 4 * step * 10 ** exp
    return 40 * 10 ** exp


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.1f}"


def _bar_path(x: float, y: float, w: float, h: float, r: float) -> str:
    r = max(0.0, min(r, h, w / 2))
    if h <= 0:
        return ""
    return (f"M{x:.1f},{y + h:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}"
            f"Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y + h:.1f}Z")


def _outline(it: dict, col: str) -> str:
    return f' stroke="{col}" stroke-width="1.5"' if it.get("hatch") else ""


def _hatch_defs(uid: str, color: str) -> str:
    return (f'<defs><pattern id="mfh-{uid}" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">'
            f'<rect width="7" height="7" fill="{C["surface"]}"/><line x1="0" y1="0" x2="0" y2="7" stroke="{color}" stroke-width="3.5"/></pattern></defs>')


def _swatch(color: str) -> str:
    return f'<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect width="12" height="12" rx="3" fill="{color}"/></svg>'


def _legend(series: list[dict]) -> str:
    items = "".join(f'<span>{_swatch(C["series"][s["key"]])}{_e(s.get("label") or C["series_label"][s["key"]])}</span>'
                    for s in series)
    return f'<div class="mf-chart-legend">{items}</div>'


def _table(categories: list[str], series: list[dict], unit: str) -> str:
    head = "".join(f'<th>{_e(s.get("label") or C["series_label"][s["key"]])}</th>' for s in series)
    rows = "".join("<tr><td>" + _e(c.replace("\n", " ")) + "</td>" + "".join(f'<td>{_fmt(s["values"][i])}</td>' for s in series) + "</tr>"
                   for i, c in enumerate(categories))
    return (f'<details><summary>View as table</summary><table><thead><tr><th>{_e(unit)}</th>{head}</tr></thead>'
            f"<tbody>{rows}</tbody></table></details>")


def grouped_bars(title: str, subtitle: str, categories: list[str], series: list[dict], unit: str,
                 height: int = 250, y_max: float | None = None) -> str:
    """series = [{"key": "naive"|"greedy"|"marina", "values": [...], "label": optional, "hatch": optional bool}]"""
    uid = f"{zlib.crc32(title.encode()):08x}"
    W, H = 500, height
    ml, mr, mt, mb = 44, 8, 26, 42
    pw, ph = W - ml - mr, H - mt - mb
    vmax = _nice_max(y_max if y_max is not None else max([v for s in series for v in s["values"]] + [0.0]))
    n, k = len(categories), len(series)
    gw = pw / n
    bw = min(46.0, (gw * 0.72 - C["bar_gap"] * (k - 1)) / k)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(title)}" {_FONT}>']
    for s in series:
        if s.get("hatch"):
            out.append(_hatch_defs(f"{uid}{s['key']}", C["series"][s["key"]]))
    for t in range(5):  # recessive grid
        v = vmax * t / 4
        y = mt + ph - ph * t / 4
        out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{C["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{ml - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="{C["label_size"]}" fill="{C["text"]}">{_fmt(v)}</text>')
    for ci, cat in enumerate(categories):
        gx = ml + ci * gw + (gw - (bw * k + C["bar_gap"] * (k - 1))) / 2
        for si, s in enumerate(series):
            v = float(s["values"][ci])
            h = max(ph * v / vmax, 0.0)
            x = gx + si * (bw + C["bar_gap"])
            y = mt + ph - h
            col = C["series"][s["key"]]
            fill = f"url(#mfh-{uid}{s['key']})" if s.get("hatch") else col
            name = s.get("label") or C["series_label"][s["key"]]
            tip = f"{name}: {_fmt(v)} {unit}  ({cat.replace(chr(10), ' ')})"
            if h < 1:  # a true zero still gets a visible 2 px baseline stub
                out.append(f'<g class="bar"><title>{_e(tip)}</title><rect x="{x:.1f}" y="{mt + ph - 2:.1f}" width="{bw:.1f}" height="2" rx="1" fill="{col}"/></g>')
            else:
                out.append(f'<g class="bar"><title>{_e(tip)}</title><path class="bar-grow" d="{_bar_path(x, y, bw, h, C["bar_radius"])}" fill="{fill}"'
                           f'{_outline(s, col)}/></g>')
            out.append(f'<text x="{x + bw / 2:.1f}" y="{(y if h >= 1 else mt + ph - 2) - 6:.1f}" text-anchor="middle" font-size="{C["label_size"]}" '
                       f'font-weight="600" fill="{C["text_strong"]}" font-family="{html.escape(C["font_mono"], quote=True)}">{_fmt(v)}</text>')
        for li, line in enumerate(cat.split("\n")):
            out.append(f'<text x="{ml + ci * gw + gw / 2:.1f}" y="{H - mb + 18 + li * 14}" text-anchor="middle" font-size="{C["label_size"]}" fill="{C["text"]}">{_e(line)}</text>')
    out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{mt + ph}" y2="{mt + ph}" stroke="{C["axis"]}" stroke-width="1.5"/>')
    out.append(f'<text x="{ml - 8}" y="{mt - 10}" text-anchor="end" font-size="{C["label_size"]}" fill="{C["text"]}">{_e(unit)}</text></svg>')
    body = '<div class="mf-chart">' + "".join(out) + "</div>"
    return _card(title, subtitle, body, _legend(series) if len(series) > 1 else "", _table(categories, series, unit))


def single_bars(title: str, subtitle: str, items: list[dict], unit: str, height: int = 250) -> str:
    """One bar per approach, coloured by entity. items = [{"label", "value", "key", "hatch": optional}]"""
    cats = [i["label"] for i in items]
    uid = f"{zlib.crc32(title.encode()):08x}"
    W, H = 500, height
    ml, mr, mt, mb = 44, 8, 26, 42
    pw, ph = W - ml - mr, H - mt - mb
    vmax = _nice_max(max([i["value"] for i in items] + [0.0]))
    n = len(items)
    gw = pw / n
    bw = min(64.0, gw * 0.5)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(title)}" {_FONT}>']
    for i in items:
        if i.get("hatch"):
            out.append(_hatch_defs(f"{uid}{i['key']}", C["series"][i["key"]]))
    for t in range(5):
        y = mt + ph - ph * t / 4
        out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{C["grid"]}" stroke-width="1"/>')
        out.append(f'<text x="{ml - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="{C["label_size"]}" fill="{C["text"]}">{_fmt(vmax * t / 4)}</text>')
    for idx, it in enumerate(items):
        h = max(ph * it["value"] / vmax, 0.0)
        x = ml + idx * gw + (gw - bw) / 2
        y = mt + ph - h
        col = C["series"][it["key"]]
        fill = f"url(#mfh-{uid}{it['key']})" if it.get("hatch") else col
        shape = (f'<path class="bar-grow" d="{_bar_path(x, y, bw, h, C["bar_radius"])}" fill="{fill}"{_outline(it, col)}/>' if h >= 1 else
                 f'<rect x="{x:.1f}" y="{mt + ph - 2:.1f}" width="{bw:.1f}" height="2" rx="1" fill="{col}"/>')
        out.append(f'<g class="bar"><title>{_e(it["label"].replace(chr(10), " "))}: {_fmt(it["value"])} {_e(unit)}</title>{shape}</g>')
        y = min(y, mt + ph - 2)
        out.append(f'<text x="{x + bw / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" font-size="{C["label_size"]}" font-weight="600" '
                   f'fill="{C["text_strong"]}" font-family="{html.escape(C["font_mono"], quote=True)}">{_fmt(it["value"])}</text>')
        for li, line in enumerate(it["label"].split("\n")):
            out.append(f'<text x="{ml + idx * gw + gw / 2:.1f}" y="{H - mb + 18 + li * 14}" text-anchor="middle" font-size="{C["label_size"]}" fill="{C["text"]}">{_e(line)}</text>')
    out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{mt + ph}" y2="{mt + ph}" stroke="{C["axis"]}" stroke-width="1.5"/>')
    out.append(f'<text x="{ml - 8}" y="{mt - 10}" text-anchor="end" font-size="{C["label_size"]}" fill="{C["text"]}">{_e(unit)}</text></svg>')
    seen, legend_series = set(), []
    for i in items:
        if i["key"] not in seen:
            seen.add(i["key"])
            legend_series.append({"key": i["key"], "values": []})
    rows = "".join(f"<tr><td>{_e(c.replace(chr(10), ' '))}</td><td>{_fmt(i['value'])}</td></tr>" for c, i in zip(cats, items))
    tbl = f"<details><summary>View as table</summary><table><thead><tr><th>Approach</th><th>{_e(unit)}</th></tr></thead><tbody>{rows}</tbody></table></details>"
    return _card(title, subtitle, '<div class="mf-chart">' + "".join(out) + "</div>", _legend(legend_series) if len(legend_series) > 1 else "", tbl)


def hbar(value: float, vmax: float, tone_color: str, width: int = 220, height: int = 12, floor_marker: float | None = None) -> str:
    """Thin horizontal bar used in the gate-queue list. `floor_marker` draws a tick (e.g. the 20-minute target)."""
    w = max(0.0, min(width, width * value / vmax)) if vmax else 0.0
    mk = ""
    if floor_marker is not None and vmax:
        mx = width * floor_marker / vmax
        mk = f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="-3" y2="{height + 3}" stroke="{C["text"]}" stroke-width="1.5" stroke-dasharray="2 2"/>'
    return (f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-hidden="true">'
            f'<rect width="{width}" height="{height}" rx="{height / 2}" fill="{T.SURFACE_RAISED}"/>'
            f'<rect class="hbar-grow" width="{w:.1f}" height="{height}" rx="{height / 2}" fill="{tone_color}"/>{mk}</svg>')


def _card(title: str, subtitle: str, body: str, legend: str, table: str) -> str:
    sub = f'<p class="sub">{_e(subtitle)}</p>' if subtitle else ""
    return f'<div class="mf-chartcard"><h3>{_e(title)}</h3>{sub}{body}{legend}{table}</div>'
