"""Road graph -> all-pairs shortest-path distance matrix (SciPy Dijkstra)."""
from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra


def build_distance_matrix(node_ids: list[str], edges: list[tuple[str, str, float]]) -> tuple[dict, np.ndarray]:
    """Return ({node_id: index}, D) where D[i, j] is the shortest road distance in km."""
    idx = {n: i for i, n in enumerate(node_ids)}
    best: dict[tuple[int, int], float] = {}
    for a, b, d in edges:  # de-duplicate: csr_matrix would SUM duplicate entries
        key = tuple(sorted((idx[a], idx[b])))
        best[key] = min(d, best.get(key, float("inf")))
    rows, cols, w = [], [], []
    for (i, j), d in best.items():
        rows += [i, j]
        cols += [j, i]
        w += [d, d]
    n = len(node_ids)
    D = dijkstra(csr_matrix((w, (rows, cols)), shape=(n, n)), directed=False)
    return idx, D
