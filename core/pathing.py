"""Geodesic routing on a per-profile navigability mask.

Detour factor needs true shortest-path length inside each profile's
eroded free space, not Euclidean distance. Grid A* in pure Python on a
600x400 lattice is ~1s per query; instead we build the 8-connected
grid graph once per mask and run scipy's Dijkstra over it, which is
compiled and vectorised. The full distance FIELD comes back for the
price of one query, so route tracing is a steepest-descent walk with
no extra search.

Everything here is deterministic: no RNG, and ties in the descent are
broken by a fixed neighbour ordering.
"""
from __future__ import annotations
import numpy as np
from scipy import sparse
from scipy.sparse import csgraph

# 8-connected neighbourhood with octile weights. Fixed order == fixed
# tie-breaking == reproducible routes.
_NBR = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, np.sqrt(2)), (-1, 1, np.sqrt(2)),
        (1, -1, np.sqrt(2)), (1, 1, np.sqrt(2))]


class GeoField:
    """Geodesic distance field over one navigability mask."""

    def __init__(self, mask: np.ndarray, cell: float):
        self.mask = mask
        self.cell = cell
        self.shape = mask.shape
        # Compact node numbering over navigable cells only. On a typical
        # world this drops ~40% of the lattice before we ever build edges.
        self.idx = np.full(mask.shape, -1, dtype=np.int32)
        ys, xs = np.nonzero(mask)
        self.idx[ys, xs] = np.arange(ys.size, dtype=np.int32)
        self.n = int(ys.size)
        self._pred = None
        self._src = None
        self._nodes = (ys, xs)
        self._graph = self._build() if self.n else None

    def _build(self):
        rows, cols, data = [], [], []
        idx = self.idx
        for dy, dx, w in _NBR:
            # Overlap the index grid with a shifted copy of itself; every
            # position where both are >= 0 is a legal edge.
            a = idx[max(0, -dy):idx.shape[0] - max(0, dy),
                    max(0, -dx):idx.shape[1] - max(0, dx)]
            b = idx[max(0, dy):idx.shape[0] - max(0, -dy),
                    max(0, dx):idx.shape[1] - max(0, -dx)]
            ok = (a >= 0) & (b >= 0)
            rows.append(a[ok]); cols.append(b[ok])
            data.append(np.full(int(ok.sum()), w * self.cell, dtype=np.float32))
        return sparse.csr_matrix(
            (np.concatenate(data),
             (np.concatenate(rows), np.concatenate(cols))),
            shape=(self.n, self.n))

    def field(self, src: tuple[int, int]) -> np.ndarray:
        """Geodesic distance in metres from src to every cell. inf off-mask.

        Stashes Dijkstra's predecessor array so route() can reconstruct
        the exact optimal path rather than descending a gradient --
        which matters once edge costs stop being uniform.
        """
        out = np.full(self.shape, np.inf, dtype=np.float64)
        self._pred, self._src = None, src
        if self._graph is None or self.idx[src] < 0:
            return out
        d, pred = csgraph.dijkstra(self._graph, indices=int(self.idx[src]),
                                   return_predecessors=True)
        ys, xs = np.nonzero(self.mask)
        out[ys, xs] = d[self.idx[ys, xs]]
        self._pred = pred
        self._nodes = (ys, xs)
        return out

    def route(self, dist: np.ndarray, goal: tuple[int, int]) -> list:
        """Exact optimal route src -> goal. Empty if unreachable."""
        if not np.isfinite(dist[goal]) or self._pred is None:
            return []
        ys, xs = self._nodes
        node = int(self.idx[goal])
        path = []
        for _ in range(self.n + 1):
            if node < 0:
                break
            path.append((int(ys[node]), int(xs[node])))
            if node == int(self.idx[self._src]):
                break
            node = int(self._pred[node])
        path.reverse()
        return path if path and path[0] == self._src else path

    def length_m(self, path: list) -> float:
        if len(path) < 2:
            return 0.0
        a = np.array(path, dtype=float)
        return float(np.hypot(*(np.diff(a, axis=0).T)).sum() * self.cell)


def route_between(mask, cell, src, goal):
    """Convenience: (path, length_m). Empty path if no route exists."""
    gf = GeoField(mask, cell)
    d = gf.field(src)
    p = gf.route(d, goal)
    return p, gf.length_m(p)


class PenaltyField(GeoField):
    """Least-resistance routing across a barrier-penalty surface.

    A GeoField answers "can this body get there". This answers the
    harder question: "if it cannot, what is the cheapest thing to
    change so that it can, and where."

    Every cell carries a penalty in 0..1 measuring how badly it
    violates one profile's envelope (too narrow, too steep, too tall a
    step; a solid cell saturates at 1). Edge cost is distance scaled by
    the penalty of the cell being entered, with LAMBDA large enough
    that any penalty-free route always wins. The optimal path is
    therefore free space wherever free space exists, and where none
    does it crosses the single cheapest barrier -- which is exactly the
    intervention worth paying for.

    Routes over the WHOLE lattice, walls included, because removing
    material is a legitimate remediation.
    """

    LAMBDA = 200.0

    def __init__(self, penalty: np.ndarray, cell: float):
        self.penalty = penalty
        super().__init__(np.ones(penalty.shape, dtype=bool), cell)

    def _build(self):
        rows, cols, data = [], [], []
        idx = self.idx
        pen = self.penalty
        for dy, dx, w in _NBR:
            sl_a = (slice(max(0, -dy), idx.shape[0] - max(0, dy)),
                    slice(max(0, -dx), idx.shape[1] - max(0, dx)))
            sl_b = (slice(max(0, dy), idx.shape[0] - max(0, -dy)),
                    slice(max(0, dx), idx.shape[1] - max(0, -dx)))
            a, b = idx[sl_a], idx[sl_b]
            ok = (a >= 0) & (b >= 0)
            # Cost of entering b. Directed edges, so the surface is
            # traversed correctly in both directions.
            cost = w * self.cell * (1.0 + self.LAMBDA * pen[sl_b][ok])
            rows.append(a[ok]); cols.append(b[ok])
            data.append(cost.astype(np.float64))
        return sparse.csr_matrix(
            (np.concatenate(data),
             (np.concatenate(rows), np.concatenate(cols))),
            shape=(self.n, self.n))
