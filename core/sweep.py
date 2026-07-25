"""Layer 1 -- blind geometric sweep of the whole floor.

The barrier finder answers "what stopped this body on this route", which
is the right question for the walkthrough but a poor detector: it
reports only the cheapest barrier per route, so a second defect behind
the first never surfaces, and a defect that blocks nobody's route is
invisible to it.

This sweep is the complement. It evaluates every ADA rule at every cell
of the voxel grid, for every profile, and clusters the failures into
findings. It is told nothing about where defects were planted.

Together the two give the recall figure: barriers find what excludes,
the sweep finds what violates, and a planted defect counts as detected
if either recovers it.
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage

from schema import ALL_PROFILES, BASELINE, IN_PER_M
from navgrid import NavGrid

TURN_CIRCLE_IN = 60.0
HEAD_MIN_IN = 80.0
MIN_RIDGE = 3
MIN_AREA = 40


def _clusters(mask, min_cells):
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    for i in range(1, n + 1):
        m = lab == i
        if int(m.sum()) >= min_cells:
            yield m


def _bbox(m, cell):
    """Metric extent of a finding.

    A representative point is misleading for anything linear: an 8.9 m
    unprotected slab edge is one finding, and which cell along it happens
    to be the deepest is arbitrary. Callers match against the extent.
    """
    ys, xs = np.nonzero(m)
    return [round(float(ys.min()) * cell, 2), round(float(xs.min()) * cell, 2),
            round(float(ys.max()) * cell, 2), round(float(xs.max()) * cell, 2)]


def sweep(grid: NavGrid, free, cell, rooms=None, spawn=None) -> list:
    """Every rule, everywhere. Returns a flat list of findings."""
    out = []
    base_nav = grid.navigable(BASELINE)
    if spawn is not None:
        base_reach = grid.analyse(BASELINE, spawn)["reachable"]
    else:
        base_reach = base_nav

    # The circulation network: ridge of the clearance field. clearance*2
    # along it is the corridor width a tape measure would report.
    cl = grid.clearance
    ridge = (cl >= ndimage.maximum_filter(cl, size=3) - 1e-9) & base_reach
    width = cl * 2.0

    for p in ALL_PROFILES:
        need_m = p.required_clearance_in / IN_PER_M

        # -- clear width along circulation
        for m in _clusters(ridge & (width < need_m), MIN_RIDGE):
            w = np.where(m, width, np.inf)
            yx = np.unravel_index(int(np.argmin(w)), w.shape)
            out.append(dict(type="clearance_width", agent=p.name,
                            pos=[round(yx[0] * cell, 2), round(yx[1] * cell, 2)],
                            bbox=_bbox(m, cell),
                            measured_in=round(float(width[yx] * IN_PER_M), 1),
                            threshold_in=p.required_clearance_in))

        # -- running slope (median over the run, positioned at its centroid,
        #    so a ramp reports its grade and not the lip at its edge)
        bad = free & (grid.slope > p.max_slope_ratio) & \
            (grid.step <= p.max_step_m)
        for m in _clusters(bad, MIN_AREA * 3):
            ys, xs = np.nonzero(m)
            cy, cx = ys.mean(), xs.mean()
            k = int(np.argmin((ys - cy) ** 2 + (xs - cx) ** 2))
            out.append(dict(type="slope_gradient", agent=p.name,
                            pos=[round(float(ys[k]) * cell, 2),
                                 round(float(xs[k]) * cell, 2)],
                            bbox=_bbox(m, cell),
                            measured=round(float(np.median(grid.slope[m])), 3),
                            threshold=round(p.max_slope_ratio, 3)))

        # -- level change
        for m in _clusters(free & (grid.step > p.max_step_m), MIN_AREA):
            s = np.where(m, grid.step, -np.inf)
            yx = np.unravel_index(int(np.argmax(s)), s.shape)
            out.append(dict(type="step_height", agent=p.name,
                            pos=[round(yx[0] * cell, 2), round(yx[1] * cell, 2)],
                            bbox=_bbox(m, cell),
                            measured_in=round(float(grid.step[yx] * IN_PER_M), 1),
                            threshold_in=p.max_step_in))

        # -- head clearance
        if grid.headroom is not None and p.head_clearance_in:
            need = p.head_clearance_in / IN_PER_M
            for m in _clusters(free & (grid.headroom < need), MIN_AREA):
                h = np.where(m, grid.headroom, np.inf)
                yx = np.unravel_index(int(np.argmin(h)), h.shape)
                out.append(dict(type="head_clearance", agent=p.name,
                                pos=[round(yx[0] * cell, 2),
                                     round(yx[1] * cell, 2)],
                                bbox=_bbox(m, cell),
                                measured_in=round(
                                    float(grid.headroom[yx] * IN_PER_M), 1),
                                threshold_in=p.head_clearance_in))

    # -- turning space, per room.
    # ADA 304.3.1 is about maneuvering inside a space, so it is evaluated
    # per room from the model's room schedule -- the same list a BIM file
    # carries. The defect manifest is never consulted.
    if rooms:
        for r in rooms:
            i0, i1 = int(r["x0"] / cell), int(r["x1"] / cell)
            j0, j1 = int(r["y0"] / cell), int(r["y1"] / cell)
            sub = free[i0:i1, j0:j1]
            if sub.size == 0 or not sub.any():
                continue
            circle_in = float(grid.clearance[i0:i1, j0:j1][sub].max()
                              * 2 * IN_PER_M)
            if circle_in < TURN_CIRCLE_IN:
                c = grid.clearance[i0:i1, j0:j1]
                yx = np.unravel_index(int(np.argmax(np.where(sub, c, -1))),
                                      c.shape)
                out.append(dict(type="turning_radius", agent="wheelchair",
                                room=r["name"],
                                pos=[round((i0 + yx[0]) * cell, 2),
                                     round((j0 + yx[1]) * cell, 2)],
                                measured_in=round(circle_in, 1),
                                threshold_in=TURN_CIRCLE_IN))
    return out


def group(findings, cell=0.5):
    """Collapse per-profile duplicates of one physical defect."""
    seen = {}
    for f in findings:
        key = (f["type"], round(f["pos"][0] / cell), round(f["pos"][1] / cell))
        d = seen.setdefault(key, {**f, "agents": []})
        d["agents"].append(f["agent"])
    return sorted(seen.values(), key=lambda d: -len(d["agents"]))


if __name__ == "__main__":
    from world3d import build3d
    w = build3d(7)
    free, fz, cz = w.rasterize()
    g = NavGrid(free, fz, w.cell, ceiling=cz)
    f = sweep(g, free, w.cell, rooms=w.rooms, spawn=w.spawn)
    gr = group(f)
    print(f"{len(f)} raw findings -> {len(gr)} distinct features")
    for d in gr[:20]:
        print(f"  {d['type']:16s} @{d['pos'][0]:5.1f},{d['pos'][1]:5.1f}  "
              f"{len(d['agents'])} profiles")
