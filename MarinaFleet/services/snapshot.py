"""
Mock service 1: get_egress_and_fleet_snapshot()

Reads the event-night telemetry from SQLite and returns a Snapshot object.
All derived metrics (gate queue waits, surge flags, charger freshness verdicts)
are computed HERE in Python, so the LLM only ever reads facts, never derives them.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from config import DATA_DB_PATH, STALE_TELEMETRY_MINUTES
from engine import battery_math, guards
from engine.road_network import build_distance_matrix

SURGE_RATIO = 1.8          # queued fans vs expected baseline at this point of egress
SURGE_WAIT_MIN = 25.0      # or estimated pickup wait above this -> SURGE
ELEVATED_RATIO, ELEVATED_WAIT_MIN = 1.2, 15.0
APPROACH_DELAY_MIN = {"SURGE": 6.0, "ELEVATED": 3.5, "NORMAL": 2.0}  # vehicle approach delay near gate


@dataclass
class Snapshot:
    snapshot_time: datetime
    weather: str
    stale_minutes: float
    meta: dict
    nodes: dict
    node_index: dict
    dist: np.ndarray
    gates: list
    surge_events: list
    vehicles: list
    buses: list
    metro: list
    chargers: list
    charger_notices: list
    requests: list
    alerts: list = field(default_factory=list)

    # -------------------------------------------------------------- helpers
    def distance(self, a: str, b: str) -> float:
        return float(self.dist[self.node_index[a], self.node_index[b]])

    def vehicle(self, vehicle_id: str) -> dict | None:
        return self._vmap().get(vehicle_id)

    def _vmap(self) -> dict:
        if not hasattr(self, "_vehicle_map"):
            self._vehicle_map = {v["vehicle_id"]: v for v in self.vehicles}
        return self._vehicle_map

    def gate(self, gate_id: str) -> dict | None:
        return next((g for g in self.gates if g["gate_id"] == gate_id), None)

    def fleet_summary(self) -> dict:
        st = Counter(v["status"] for v in self.vehicles)
        idle = [v for v in self.vehicles if v["status"] == "idle"]
        return {
            "robotaxis_total": len(self.vehicles), "by_status": dict(st),
            "idle_below_15pct": sum(v["soc_pct"] < 15 for v in idle),
            "idle_15_to_30pct": sum(15 <= v["soc_pct"] < 30 for v in idle),
            "idle_above_30pct": sum(v["soc_pct"] >= 30 for v in idle),
            "buses_available": sum(b["status"] == "available" for b in self.buses),
            "buses_total": len(self.buses), "pending_ride_requests": len(self.requests),
        }

    def to_llm_summary(self) -> dict:
        """Compact, code-computed facts for the LLM (no raw 800-vehicle list)."""
        return {
            "snapshot_time_utc": self.meta["snapshot_time_utc"], "weather": self.weather,
            "weather_profile": battery_math.weather_profile(self.weather)["label"],
            "fans_remaining": int(self.meta["fans_remaining"]),
            "target_clear_minutes": int(self.meta["target_clear_minutes"]),
            "gates": [{k: g[k] for k in ("gate_id", "fans_queued", "surge_ratio", "ridehail_parties_queued",
                                         "est_pickup_wait_min", "status")} for g in self.gates],
            "alerts": self.alerts,
            "fleet": self.fleet_summary(),
            "chargers": [{k: c[k] for k in ("charger_id", "status", "available_slots", "telemetry_age_min",
                                            "verdict", "verdict_reason")} for c in self.chargers],
            "charger_notices": self.charger_notices,
            "recent_crowd_events": self.surge_events,
            "metro": [{k: m[k] for k in ("station_id", "headway_min", "current_load_pct")} for m in self.metro],
        }


def _rows(con, table: str) -> list[dict]:
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(f"SELECT * FROM {table}").fetchall()]


def get_egress_and_fleet_snapshot(data_db: Path | str | None = None, weather: str = "clear",
                                  stale_minutes: float | None = None, now: datetime | None = None) -> Snapshot:
    """
    Load the telemetry snapshot. `now` defaults to the scenario's snapshot clock so
    freshness checks are reproducible; pass a real datetime in production.
    """
    data_db = Path(data_db or DATA_DB_PATH)
    if not data_db.exists():
        raise FileNotFoundError(f"{data_db} not found. Run: python data/generate_data.py")
    stale_minutes = STALE_TELEMETRY_MINUTES if stale_minutes is None else float(stale_minutes)
    wx = battery_math.weather_profile(weather)

    con = sqlite3.connect(data_db)
    try:
        meta = {r["key"]: r["value"] for r in _rows(con, "scenario_meta")}
        nodes = {r["node_id"]: r for r in _rows(con, "road_nodes")}
        edges = [(e["from_node"], e["to_node"], e["distance_km"]) for e in _rows(con, "road_edges")]
        gates, events = _rows(con, "gates"), _rows(con, "crowd_surge_events")
        vehicles, buses, metro = _rows(con, "robotaxis"), _rows(con, "buses"), _rows(con, "metro_stations")
        chargers, notices, requests = _rows(con, "chargers"), _rows(con, "charger_notices"), _rows(con, "trip_requests")
    finally:
        con.close()

    node_index, D = build_distance_matrix(list(nodes), edges)
    now = now or guards.parse_ts(meta["snapshot_time_utc"])

    # ---- gate congestion metrics (queue model, computed in code) -------------
    alerts = []
    for g in gates:
        parties = round(g["fans_queued"] * g["ridehail_share"] / g["avg_party_size"])
        throughput = g["curb_throughput_vpm"] * wx["speed_factor"]  # weather slows curb turnover
        wait = parties / throughput
        ratio = g["fans_queued"] / g["baseline_expected_fans"]
        status = ("SURGE" if ratio >= SURGE_RATIO or wait >= SURGE_WAIT_MIN else
                  "ELEVATED" if ratio >= ELEVATED_RATIO or wait >= ELEVATED_WAIT_MIN else "NORMAL")
        g.update(ridehail_parties_queued=parties, effective_throughput_vpm=round(throughput, 2),
                 est_pickup_wait_min=round(wait, 1), surge_ratio=round(ratio, 2), status=status,
                 approach_delay_min=round(APPROACH_DELAY_MIN[status] / wx["speed_factor"], 2))
        if status == "SURGE":
            alerts.append({"type": "CROWD_SURGE", "gate_id": g["gate_id"],
                           "message": f"{g['name']}: {g['fans_queued']} fans queued ({ratio:.1f}x expected), "
                                      f"est. pickup wait {wait:.0f} min"})

    # ---- charger freshness verdicts (Rule 3, computed in code) ---------------
    charging_counts = Counter(v["node_id"] for v in vehicles if v["status"] == "charging")
    for c in chargers:
        gr = guards.charger_freshness_guard(c, now, stale_minutes)
        c.update(telemetry_age_min=gr.details["telemetry_age_min"], verdict=gr.details["code"],
                 verdict_reason=gr.reason, fleet_vehicles_charging_here=charging_counts.get(c["node_id"], 0))
        if not gr.passed and gr.details["code"] in ("STALE", "OFFLINE"):
            alerts.append({"type": f"CHARGER_{gr.details['code']}", "charger_id": c["charger_id"], "message": gr.reason})

    return Snapshot(snapshot_time=now, weather=weather, stale_minutes=stale_minutes, meta=meta, nodes=nodes,
                    node_index=node_index, dist=D, gates=gates, surge_events=events, vehicles=vehicles,
                    buses=buses, metro=metro, chargers=chargers, charger_notices=notices,
                    requests=requests, alerts=alerts)
