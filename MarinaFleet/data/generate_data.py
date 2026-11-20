"""
Synthetic, seeded dataset generator for the MarinaFleet event-night scenario.

Run:  python data/generate_data.py

Produces:
  data/marina_stadium_egress.sqlite   (all tables)
  data/csv/<table>.csv                (one CSV export per table)

Everything is driven by a fixed random seed, so the same files are produced
on every machine. Coordinates are in kilometres on a flat local grid centred
on the stadium (x = east, y = north). No real map data is used.
"""
from __future__ import annotations

import csv
import math
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

SEED = 42
DATA_DIR = Path(__file__).resolve().parent
DB_PATH = DATA_DIR / "marina_stadium_egress.sqlite"
CSV_DIR = DATA_DIR / "csv"

# Snapshot clock: 21:48 Dubai time (UTC+4) = 17:48 UTC, 18 min into egress.
SNAPSHOT_TIME = datetime(2026, 11, 20, 17, 48, 0, tzinfo=timezone.utc)
EGRESS_START = datetime(2026, 11, 20, 17, 30, 0, tzinfo=timezone.utc)

ROAD_CIRCUITY = 1.3  # road distance = straight-line distance x 1.3
GATE_RING_RADIUS_KM = 0.20  # gates ~200 m apart around the bowl
PZ_RING_RADIUS_KM = 0.55  # pickup zones on the outer ring road

N_ROBOTAXIS = 800
N_BUSES = 40


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Road network
# --------------------------------------------------------------------------
DISTRICTS = [
    ("MARINA", "Dubai Marina", 2.5, 1.5),
    ("JBR", "JBR Walk", 3.5, 3.0),
    ("JLT", "Jumeirah Lakes Towers", 1.0, -2.5),
    ("MEDIA", "Media City", -1.5, 3.5),
    ("BARSHA", "Al Barsha", -3.5, -1.0),
    ("TECOM", "TECOM", -4.0, 2.5),
    ("PALM", "Palm Jumeirah", 4.5, 6.0),
    ("INTERNET", "Internet City", -0.5, 5.0),
    ("SPORTS", "Sports City", 2.0, -6.5),
    ("ALQUOZ", "Al Quoz", -7.0, 0.5),
    ("BBAY", "Business Bay", -10.0, 4.5),
    ("DOWNTOWN", "Downtown", -11.5, 6.0),
    ("JVC", "Jumeirah Village", -2.5, -5.5),
    ("DIP", "Investments Park", 3.5, -10.0),
    ("DEIRA", "Deira", -18.0, 10.0),
    ("AIRPORT", "DXB Airport", -20.0, 12.0),
]
# Gate 4 sits on the south side; Gates 3 and 5 are its ~200 m neighbours.
GATE_ANGLES = {1: 90, 2: 30, 3: -30, 4: -90, 5: -150, 6: 150}


def build_nodes():
    nodes = []  # (node_id, name, kind, x, y)
    for g, ang in GATE_ANGLES.items():
        a = math.radians(ang)
        nodes.append((f"G{g}", f"Gate {g}", "gate", round(GATE_RING_RADIUS_KM * math.cos(a), 4),
                      round(GATE_RING_RADIUS_KM * math.sin(a), 4)))
    for g, ang in GATE_ANGLES.items():
        a = math.radians(ang)
        nodes.append((f"PZ{g}", f"Pickup Zone {g}", "pickup_zone", round(PZ_RING_RADIUS_KM * math.cos(a), 4),
                      round(PZ_RING_RADIUS_KM * math.sin(a), 4)))
    nodes += [
        ("STAGE_E", "East Robotaxi Staging (venue charging hub)", "staging", 1.2, -0.3),
        ("STAGE_W", "West Robotaxi Staging", "staging", -1.2, 0.3),
        ("METRO_N", "Marina City North Metro", "metro", 0.9, 0.9),
        ("METRO_S", "Stadium South Metro", "metro", -0.8, -0.9),
        ("DEPOT_BUS", "Feeder Bus Depot", "depot", -1.5, -2.0),
    ]
    for nid, name, x, y in DISTRICTS:
        nodes.append((nid, name, "district", x, y))
    return nodes


def build_edges(nodes):
    """k-nearest-neighbour road graph + stadium ring roads, guaranteed connected."""
    road = [n for n in nodes if n[2] != "gate"]
    pos = {n[0]: (n[3], n[4]) for n in nodes}

    def dist(a, b):
        (x1, y1), (x2, y2) = pos[a], pos[b]
        return math.hypot(x1 - x2, y1 - y2) * ROAD_CIRCUITY

    edges = {}

    def add(a, b, cls):
        key = tuple(sorted((a, b)))
        if a != b and key not in edges:
            edges[key] = (key[0], key[1], round(dist(a, b), 3), cls)

    for n in road:  # 3 nearest road neighbours
        others = sorted((dist(n[0], m[0]), m[0]) for m in road if m[0] != n[0])
        for _, m in others[:3]:
            add(n[0], m, "arterial")
    for g in range(1, 7):  # outer ring road between pickup zones, and gate walkways
        add(f"PZ{g}", f"PZ{g % 6 + 1}", "stadium_ring")
        add(f"G{g}", f"PZ{g}", "walkway")

    # make sure the road graph is connected (join closest pair across components)
    ids = [n[0] for n in nodes]
    idx = {n: i for i, n in enumerate(ids)}
    while True:
        r, c, w = [], [], []
        for a, b, d, _ in edges.values():
            r += [idx[a], idx[b]]
            c += [idx[b], idx[a]]
            w += [d, d]
        ncomp, labels = connected_components(csr_matrix((w, (r, c)), shape=(len(ids), len(ids))), directed=False)
        if ncomp == 1:
            break
        best = None
        for a in road:
            for b in road:
                if labels[idx[a[0]]] != labels[idx[b[0]]]:
                    d = dist(a[0], b[0])
                    if best is None or d < best[0]:
                        best = (d, a[0], b[0])
        add(best[1], best[2], "connector")
    return list(edges.values())


# --------------------------------------------------------------------------
# Main generator
# --------------------------------------------------------------------------
def generate(db_path: Path = DB_PATH, csv_dir: Path = CSV_DIR, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    nodes = build_nodes()
    edges = build_edges(nodes)
    node_ids = [n[0] for n in nodes]

    # ---------------- gates (crowd surge zones) -------------------------
    # fans_queued for Gate 4 includes the sudden surge (concourse closure).
    gate_rows = []
    queued = {1: 3200, 2: 2900, 3: 3400, 4: 9800, 5: 2600, 6: 3100}
    pos = {n[0]: (n[3], n[4]) for n in nodes}
    for g in range(1, 7):
        x, y = pos[f"G{g}"]
        gate_rows.append(dict(
            gate_id=f"G{g}", name=f"Gate {g}", x_km=x, y_km=y, pickup_zone_node=f"PZ{g}",
            fans_queued=queued[g], baseline_expected_fans=3500,
            ridehail_share=0.20, avg_party_size=2.3,
            curb_slots=20, curb_lanes=2, curb_throughput_vpm=24.0,  # vehicles loaded per minute
            walk_capacity_ppm=900,
        ))

    surge_events = [
        dict(event_id="EV-001", ts_utc=iso(EGRESS_START), gate_id="ALL", event_type="EGRESS_START",
             fans_delta=0, note="Final whistle. Phased egress begins on all six gates."),
        dict(event_id="EV-002", ts_utc=iso(SNAPSHOT_TIME - timedelta(minutes=7)), gate_id="G4",
             event_type="CROWD_SURGE", fans_delta=6300,
             note="Concourse C closed (spill). Sections 112-131 redirected to Gate 4."),
    ]

    # ---------------- chargers -----------------------------------------
    # status/available_slots are what each hub *reports*; telemetry timestamps
    # decide whether we may trust it. CH_JBR is STALE (cached), CH_MEDIA OFFLINE.
    chargers = [
        # id, name, node, total, power_kw, status, telemetry_age_min
        ("CH_STADIUM", "Venue Fast-Charge Hub", "STAGE_E", 40, 150, "ONLINE", 0.6),
        ("CH_MARINA", "Marina Mall Hub", "MARINA", 16, 120, "ONLINE", 1.2),
        ("CH_JLT", "JLT Cluster D Hub", "JLT", 20, 120, "ONLINE", 2.1),
        ("CH_BARSHA", "Al Barsha Hub", "BARSHA", 14, 100, "ONLINE", 1.7),
        ("CH_SPORTS", "Sports City Hub", "SPORTS", 16, 150, "ONLINE", 0.9),
        ("CH_JBR", "JBR Beach Fast-Charge Hub", "JBR", 16, 150, "ONLINE", 23.0),   # STALE cache
        ("CH_MEDIA", "Media City Hub", "MEDIA", 14, 120, "OFFLINE", 41.0),          # OFFLINE
    ]
    charging_here = {"CH_STADIUM": 4, "CH_MARINA": 9, "CH_JLT": 12, "CH_BARSHA": 8, "CH_SPORTS": 7, "CH_JBR": 9}

    charger_rows = []
    for cid, name, node, total, kw, status, age in chargers:
        if cid == "CH_JBR":
            reported = total  # cached feed still claims every slot free
        elif cid == "CH_MEDIA":
            reported = 8  # last value before the hub dropped off
        else:
            reported = total - charging_here.get(cid, 0)
        charger_rows.append(dict(
            charger_id=cid, name=name, node_id=node, total_slots=total, available_slots=reported,
            power_kw=kw, status=status, last_telemetry_utc=iso(SNAPSHOT_TIME - timedelta(minutes=age)),
        ))

    charger_notices = [
        dict(notice_id="CN-01", charger_id="CH_JBR", ts_utc=iso(SNAPSHOT_TIME - timedelta(minutes=22)),
             severity="WARNING", message="Telemetry gateway timeout; serving cached slot availability."),
        dict(notice_id="CN-02", charger_id="CH_MEDIA", ts_utc=iso(SNAPSHOT_TIME - timedelta(minutes=40)),
             severity="CRITICAL", message="Hub offline: grid feeder fault, all dispensers de-energised."),
    ]

    # ---------------- robotaxis ----------------------------------------
    models = [("Model-A", 60.0, 0.165), ("Model-B", 72.0, 0.180), ("Model-C", 82.0, 0.200)]
    stadium_nodes = [f"PZ{g}" for g in range(1, 7)] + ["STAGE_E", "STAGE_W", "METRO_N", "METRO_S"]
    district_ids = [d[0] for d in DISTRICTS if d[0] not in ("AIRPORT", "DEIRA")]
    low_nodes, low_w = ["JBR", "MEDIA", "INTERNET", "PALM", "MARINA"], [4, 4, 2, 2, 1]

    statuses = ["idle"] * 500 + ["occupied"] * 150 + ["en_route"] * 101
    charging_slots = [cid for cid, n in charging_here.items() for _ in range(n)]  # 49 vehicles
    statuses += ["charging"] * len(charging_slots)
    assert len(statuses) == N_ROBOTAXIS
    rng.shuffle(statuses)
    charger_node = {c[0]: c[2] for c in chargers}

    vehicles = []
    ch_iter = iter(charging_slots)
    for i, status in enumerate(statuses, start=1):
        model, batt, cons = rng.choice(models)
        cons = round(cons * rng.uniform(0.95, 1.05), 4)
        if status == "idle":
            u = rng.random()
            if u < 0.68:
                soc = rng.uniform(35, 95)
            elif u < 0.86:
                soc = rng.uniform(15, 35)
            elif u < 0.96:
                soc = rng.uniform(8, 15)
            else:
                soc = rng.uniform(3, 8)
        elif status == "charging":
            soc = rng.uniform(20, 70)
        else:
            soc = rng.uniform(25, 90)
        soc = round(soc, 1)

        if status == "charging":
            cid = next(ch_iter)
            node = charger_node[cid]
        elif status == "idle" and soc < 20:
            node = rng.choices(low_nodes, low_w)[0]  # low cars cluster near JBR/Media
        elif rng.random() < 0.30:
            node = rng.choice(stadium_nodes)
        else:
            node = rng.choice(district_ids)
        vehicles.append(dict(
            vehicle_id=f"RT-{i:04d}", model=model, battery_kwh=batt, consumption_kwh_per_km=cons,
            soc_pct=soc, node_id=node, status=status,
            capacity_seats=6 if rng.random() < 0.10 else 4,
            last_telemetry_utc=iso(SNAPSHOT_TIME - timedelta(seconds=rng.randint(2, 40))),
        ))

    # ---------------- feeder buses -------------------------------------
    buses = []
    for i in range(1, N_BUSES + 1):
        in_service = i > 30
        buses.append(dict(
            bus_id=f"BUS-{i:02d}", capacity=rng.choice([60, 80, 90]),
            node_id=rng.choice(district_ids) if in_service else rng.choice(["DEPOT_BUS", "DEPOT_BUS", "STAGE_W"]),
            status="in_service" if in_service else "available",
            cycle_time_min=rng.choice([25, 30, 35, 40]),
        ))

    # ---------------- metro --------------------------------------------
    metro = [
        dict(station_id="METRO_N", name="Marina City North", node_id="METRO_N",
             capacity_per_hour=24000, headway_min=2.5, current_load_pct=82.0),
        dict(station_id="METRO_S", name="Stadium South", node_id="METRO_S",
             capacity_per_hour=18000, headway_min=4.0, current_load_pct=61.0),
    ]

    # ---------------- pending ride-hail requests -----------------------
    per_gate = {1: 45, 2: 40, 3: 50, 4: 150, 5: 40, 6: 55}
    dest_w = {"MARINA": 10, "JBR": 9, "JLT": 9, "MEDIA": 6, "BARSHA": 8, "TECOM": 6, "PALM": 8,
              "INTERNET": 4, "SPORTS": 5, "ALQUOZ": 4, "BBAY": 7, "DOWNTOWN": 8, "JVC": 6, "DIP": 3,
              "AIRPORT": 5, "DEIRA": 4}
    requests = []
    rid = 1
    for g, n in per_gate.items():
        for _ in range(n):
            waited = rng.uniform(4, 16) if g == 4 else rng.uniform(0, 8)
            requests.append(dict(
                request_id=f"RQ-{rid:04d}", gate_id=f"G{g}", pickup_node=f"PZ{g}",
                dest_node=rng.choices(list(dest_w), list(dest_w.values()))[0],
                party_size=rng.choices([1, 2, 3, 4], [0.30, 0.35, 0.20, 0.15])[0],
                waited_min=round(waited, 1),
            ))
            rid += 1

    meta = dict(
        event_name="Marina City Derby - event night", venue="Marina City Stadium",
        snapshot_time_utc=iso(SNAPSHOT_TIME), egress_start_utc=iso(EGRESS_START),
        total_fans=60000, fans_remaining=sum(queued.values()), target_clear_minutes=90,
        historical_peak_wait_min=35, timezone="Asia/Dubai", seed=seed,
    )

    # ---------------- shortest-path distance matrix --------------------
    idx = {n: i for i, n in enumerate(node_ids)}
    r, c, w = [], [], []
    for a, b, d, _ in edges:
        r += [idx[a], idx[b]]
        c += [idx[b], idx[a]]
        w += [d, d]
    D = dijkstra(csr_matrix((w, (r, c)), shape=(len(node_ids), len(node_ids))), directed=False)
    dist_rows = [dict(from_node=a, to_node=b, distance_km=round(float(D[idx[a], idx[b]]), 3))
                 for a in node_ids for b in node_ids]

    tables = {
        "scenario_meta": [dict(key=k, value=str(v)) for k, v in meta.items()],
        "road_nodes": [dict(node_id=n[0], name=n[1], kind=n[2], x_km=n[3], y_km=n[4]) for n in nodes],
        "road_edges": [dict(from_node=a, to_node=b, distance_km=d, road_class=cls) for a, b, d, cls in edges],
        "distance_matrix": dist_rows,
        "gates": gate_rows,
        "crowd_surge_events": surge_events,
        "robotaxis": vehicles,
        "buses": buses,
        "metro_stations": metro,
        "chargers": charger_rows,
        "charger_notices": charger_notices,
        "trip_requests": requests,
    }
    _write_sqlite(db_path, tables)
    _write_csvs(csv_dir, tables)
    return {k: len(v) for k, v in tables.items()}


def _write_sqlite(db_path: Path, tables: dict) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    for name, rows in tables.items():
        cols = list(rows[0].keys())
        def sqltype(v):
            return "INTEGER" if isinstance(v, int) else "REAL" if isinstance(v, float) else "TEXT"
        con.execute(f"CREATE TABLE {name} ({', '.join(f'{c} {sqltype(rows[0][c])}' for c in cols)})")
        con.executemany(f"INSERT INTO {name} VALUES ({','.join('?' * len(cols))})",
                        [tuple(r[c] for c in cols) for r in rows])
    con.commit()
    con.close()


def _write_csvs(csv_dir: Path, tables: dict) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with open(csv_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)


if __name__ == "__main__":
    counts = generate()
    print(f"Wrote {DB_PATH.relative_to(DATA_DIR.parent)} and CSVs in {CSV_DIR.relative_to(DATA_DIR.parent)}/")
    for k, v in counts.items():
        print(f"  {k:<20} {v:>6} rows")
    sys.exit(0)
