"""
Regenerate docs/roi_chart.png from a real optimizer run, using the SAME brand chart module as the app (ui/charts.py).

    python docs/make_charts.py        # needs Playwright + Chromium (dev tool only)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.optimizer import run_ev_dispatch_optimizer  # noqa: E402
from services.snapshot import get_egress_and_fleet_snapshot  # noqa: E402
from ui import charts, theme as T  # noqa: E402


def main() -> Path:
    plan = run_ev_dispatch_optimizer(get_egress_and_fleet_snapshot(), ["G4"])
    n, g, m = plan["kpis"]["baseline"], plan["kpis"]["battery_aware_greedy"], plan["kpis"]["optimized"]
    a = charts.single_bars("Peak gate pickup-queue wait", "Gate 4 surge, lower is better",
                           [{"label": "Naive\nbaseline", "value": n["gate4_style_peak_queue_wait_min"], "key": "naive"},
                            {"label": "MarinaFleet", "value": m["gate4_style_peak_queue_wait_min"], "key": "marina"},
                            {"label": "MarinaFleet\n+ lane approved", "value": m["peak_queue_wait_if_lane_approved_min"], "key": "marina", "hatch": True}], "min")
    b = charts.grouped_bars("Safety events", "Count over the night, lower is better", ["Stranded\nvehicles", "Below 15%\nreserve", "Failed charger\ntrips"],
                            [{"key": k, "values": [d["stranded_vehicles"], d["reserve_violations"], d["failed_charger_attempts"]]}
                             for k, d in (("naive", n), ("marina", m))], "events")
    c = charts.grouped_bars("Rider pickup wait", "Mean and 90th percentile, lower is better", ["Mean wait", "P90 wait"],
                            [{"key": "naive", "values": [n["mean_wait_min"], n["p90_wait_min"]]}, {"key": "greedy", "values": [g["mean_wait_min"], g["p90_wait_min"]]},
                            {"key": "marina", "values": [m["mean_wait_min"], m["p90_wait_min"]]}], "min")
    html = (f"<style>{T.stylesheet()}body{{background:{T.BG_BASE};margin:0;padding:24px;width:1500px}}"
            f".row{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}</style><div class='row'>{a}{b}{c}</div>")
    out = ROOT / "docs" / "roi_chart.png"
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 1548, "height": 600}, device_scale_factor=2)
        pg.set_content(html)
        pg.wait_for_timeout(900)
        pg.locator(".row").screenshot(path=str(out))
        br.close()
    return out


if __name__ == "__main__":
    print("wrote", main())
