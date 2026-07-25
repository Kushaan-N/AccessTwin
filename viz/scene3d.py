"""Export the 3D scene plus everything the viewer needs to animate it.

Produces out/scene.json: the building geometry, and for every mobility
profile the route it actually takes, where it stops, what stopped it,
and which regions it can never reach.

Routes are real: each one is a geodesic path through that profile's own
eroded navigable set, with its z sampled from the voxelised floor, so an
agent walking a route climbs the ramp and steps up the stair because the
floor does. Blocked agents walk to the closest cell they can legally
occupy and halt at the barrier the analysis identified -- they are not
scripted to stop there.

Run:  python3 viz/scene3d.py --seed 7
"""
from __future__ import annotations
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from schema import ALL_PROFILES, BASELINE, WHEELCHAIR, IN_PER_M
from world3d import build3d
from navgrid import NavGrid
from pathing import GeoField
from sweep import sweep, group
import analysis as A

# Same validated categorical palette as the plan view, so a profile is
# the same colour wherever it appears.
COLORS = {
    "baseline_walking":        {"dark": "#29A090", "light": "#00897B"},
    "wheelchair":              {"dark": "#6285D6", "light": "#3B62B8"},
    "vision_impaired_cane":    {"dark": "#D05C8C", "light": "#B03368"},
    "sidewalk_delivery_robot": {"dark": "#BE8A30", "light": "#8A6410"},
}
LABELS = {
    "baseline_walking": "Walking adult",
    "wheelchair": "Wheelchair user",
    "vision_impaired_cane": "Cane user",
    "sidewalk_delivery_robot": "Delivery robot",
}
BODY = {
    "baseline_walking": "walker",
    "wheelchair": "wheelchair",
    "vision_impaired_cane": "cane",
    "sidewalk_delivery_robot": "robot",
}
GOAL_LABELS = {
    "community_room": "Community Room",
    "gallery": "Gallery",
    "restroom": "Accessible WC",
    "east_end": "East end of corridor",
}


def simplify(pts, tol_cells=1.2):
    """Douglas-Peucker. A 5 cm route is thousands of points; the viewer
    needs a walkable spline, not a voxel trail."""
    if len(pts) < 3:
        return list(pts)
    pts = np.asarray(pts, dtype=float)

    def rec(a, b):
        if b <= a + 1:
            return []
        p0, p1 = pts[a], pts[b]
        d = p1 - p0
        n = np.hypot(*d)
        seg = pts[a + 1:b]
        if n < 1e-9:
            dist = np.hypot(*(seg - p0).T)
        else:
            dist = np.abs(np.cross(np.broadcast_to(d, seg.shape),
                                   seg - p0)) / n
        k = int(np.argmax(dist))
        if dist[k] <= tol_cells:
            return []
        m = a + 1 + k
        return rec(a, m) + [m] + rec(m, b)

    keep = [0] + rec(0, len(pts) - 1) + [len(pts) - 1]
    return [pts[i].tolist() for i in sorted(set(keep))]


def route3d(cells, floor_z, cell):
    """Grid cells -> metric polyline with the floor height baked in."""
    out = []
    for (ix, iy) in cells:
        ix = int(np.clip(ix, 0, floor_z.shape[0] - 1))
        iy = int(np.clip(iy, 0, floor_z.shape[1] - 1))
        out.append([round(ix * cell, 3), round(iy * cell, 3),
                    round(float(floor_z[ix, iy]), 3)])
    return out


def walk(grid, p, spawn, goal, floor_z, cell):
    """The journey this body actually makes toward one goal.

    Returns the route it can legally travel, whether it arrived, and if
    not, where it had to stop.
    """
    nav = grid.navigable(p)
    gf = GeoField(nav, cell)
    sp = NavGrid.snap(nav, spawn)
    dist = gf.field(sp)
    arrived = bool(np.isfinite(dist[goal]))

    if arrived:
        target = goal
    else:
        # Closest cell to the goal this body can stand on: where it gives up.
        finite = np.isfinite(dist)
        if not finite.any():
            return {"arrived": False, "path": [], "stop": None}
        ys, xs = np.nonzero(finite)
        k = int(np.argmin((ys - goal[0]) ** 2 + (xs - goal[1]) ** 2))
        target = (int(ys[k]), int(xs[k]))

    cells = gf.route(dist, target)
    if len(cells) < 2:
        return {"arrived": arrived, "path": [], "stop": None}
    simple = simplify([[c[0], c[1]] for c in cells])
    path = route3d([(c[0], c[1]) for c in simple], floor_z, cell)
    return {
        "arrived": arrived,
        "path": path,
        "length_m": round(gf.length_m(cells), 2),
        "stop": path[-1] if not arrived else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--budget", type=float, default=6000.0)
    ap.add_argument("--pop", type=int, default=200)
    args = ap.parse_args()

    w = build3d(args.seed)
    free, floor_z, ceil_z = w.rasterize()
    cell = w.cell
    grid = NavGrid(free, floor_z, cell, ceiling=ceil_z)
    spawn, goals = w.spawn, w.goals

    base = grid.analyse(BASELINE, spawn)
    base_m2 = base["reachable_m2"] or 1.0

    print(f"Access-Twin 3D  seed={args.seed}")

    profiles = []
    for p in ALL_PROFILES:
        st = grid.analyse(p, spawn)
        journeys = {}
        for gname, g in goals.items():
            journeys[gname] = walk(grid, p, spawn, g, floor_z, cell)
            if not journeys[gname]["arrived"]:
                bs = A.barriers(grid, p, spawn, g)
                journeys[gname]["barriers"] = [{
                    "kind": b["kind"],
                    "pos": [b["pos"][0], b["pos"][1],
                            round(float(floor_z[b["cell"][0], b["cell"][1]]), 3)],
                    "aperture_in": b["aperture_in"],
                    "step_in": b["step_in"],
                    "slope": b["slope"],
                    "severity": b["severity"],
                } for b in bs[:3]]
            else:
                journeys[gname]["barriers"] = []

        islands = []
        for isl in st["islands"]:
            cy, cx = int(isl["centroid"][0]), int(isl["centroid"][1])
            islands.append({
                "area_m2": isl["area_m2"],
                "pos": [round(cy * cell, 2), round(cx * cell, 2),
                        round(float(floor_z[cy, cx]), 2)],
                "room": nearest_room(w, cy * cell, cx * cell),
            })

        profiles.append({
            "name": p.name, "label": LABELS[p.name], "body": BODY[p.name],
            "color": COLORS[p.name],
            "width_in": p.required_clearance_in,
            "max_slope": round(p.max_slope_ratio, 4),
            "max_step_in": p.max_step_in,
            "head_in": p.head_clearance_in,
            "reach_m2": st["reachable_m2"],
            "pct": round(100 * st["reachable_m2"] / base_m2, 1),
            "island_m2": st["island_m2"],
            "islands": islands,
            "journeys": journeys,
            "reach_grid": encode_mask(st["reachable"]),
        })
        arrived = [g for g in goals if journeys[g]["arrived"]]
        print(f"  {p.name:24s} {st['reachable_m2']:7.1f} m2  "
              f"reaches {len(arrived)}/{len(goals)}")

    # ---- higher-order analysis -------------------------------------
    print("  analysing...")
    bp = A.breaking_point(grid, spawn, goals, ref=WHEELCHAIR)
    pop = A.population_coverage(grid, spawn, goals,
                                pop=A.sample_population(args.pop, args.seed))
    det = A.detour(grid, spawn, goals)
    opt = A.optimise(free, floor_z, cell, spawn, goals, budget=args.budget,
                     seed=args.seed, pop_n=70, ceiling=ceil_z)
    fixed_free, fixed_height = opt.pop("_final_world")
    after = NavGrid(fixed_free, fixed_height, cell, ceiling=ceil_z)
    after_base = after.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
    for pr in profiles:
        p = next(q for q in ALL_PROFILES if q.name == pr["name"])
        a = after.analyse(p, spawn)
        pr["after_pct"] = round(100 * a["reachable_m2"] / after_base, 1)
        pr["after_reach_grid"] = encode_mask(a["reachable"])
        pr["after_goals"] = {g: bool(after.reaches(p, spawn, c))
                             for g, c in goals.items()}

    recall = score_recall(w, grid, profiles, free, cell)

    scene = w.to_scene()
    scene.update({
        "seed": args.seed,
        "grid": {"nx": free.shape[0], "ny": free.shape[1], "cell": cell},
        "goal_labels": GOAL_LABELS,
        "profiles": profiles,
        "breaking_point": bp,
        "population": pop,
        "elasticity": A.elasticity(pop["width_curve"]),
        "detour": det,
        "remediation": opt,
        "recall": recall,
    })

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    path = os.path.join(ROOT, "out", "scene.json")
    with open(path, "w") as fh:
        json.dump(scene, fh, separators=(",", ":"), default=float)
    print(f"\nwrote {path}  ({os.path.getsize(path)/1024:.0f} kB)")
    print(f"population full access: {pop['pct_full_access']}% -> "
          f"{opt['after']['pct_full_access']}% after ${opt['spent_usd']:,}")
    print(f"recall: {recall['detected']}/{recall['planted']}")


def nearest_room(w, x, y):
    for r in w.rooms:
        if r["x0"] <= x <= r["x1"] and r["y0"] <= y <= r["y1"]:
            return r["name"]
    return ""


def encode_mask(m):
    import base64
    return base64.b64encode(np.packbits(m.astype(np.uint8).ravel())
                            ).decode("ascii")


def score_recall(w, grid, profiles, free, cell):
    """Which planted defects did the analysis rediscover, unprompted?

    Two independent detectors, neither told where to look:

      barriers -- what actually stopped a body on a route. Precise about
                  exclusion, but reports only the cheapest barrier per
                  route, so a second defect behind the first is masked,
                  and a defect blocking nobody's route is invisible.
      sweep    -- every ADA rule at every cell for every profile. Catches
                  what the routes miss.

    A defect counts as detected if either recovers it within 1.6 m.
    """
    found = []
    for pr in profiles:
        for _gname, j in pr["journeys"].items():
            for b in j.get("barriers", []):
                found.append((b["kind"], b["pos"][0], b["pos"][1],
                              "route:" + pr["name"], None))

    sweep_raw = sweep(grid, free, cell, rooms=w.rooms, spawn=w.spawn)
    for f in sweep_raw:
        found.append((f["type"], f["pos"][0], f["pos"][1],
                      "sweep:" + f["agent"], f.get("bbox")))

    per = []
    for d in w.gt:
        gx, gy = d["pos"]
        def near(f):
            if f[0] != d["type"]:
                return False
            if abs(f[1] - gx) <= 1.6 and abs(f[2] - gy) <= 1.6:
                return True
            # Linear features (a slab edge, a long pinch) are matched on
            # extent: which cell along them is deepest is arbitrary.
            bb = f[4] if len(f) > 4 else None
            return bool(bb and bb[0] - 1.0 <= gx <= bb[2] + 1.0
                        and bb[1] - 1.0 <= gy <= bb[3] + 1.0)

        hits = [f for f in found if near(f)]
        by = sorted({h[3].split(":")[0] for h in hits})
        per.append({"id": d["id"], "type": d["type"], "pos": d["pos"],
                    "note": d.get("note", ""), "detected": bool(hits),
                    "detected_by": by,
                    "detected_for": sorted({h[3].split(":")[1] for h in hits})})

    # Findings that match no planted defect are emergent, not false
    # positives: mostly pinch points created by where the furniture
    # landed rather than by the architecture.
    grouped = group(sweep_raw)
    def matches_planted(g):
        for d in w.gt:
            if g["type"] != d["type"]:
                continue
            gx, gy = d["pos"]
            if abs(g["pos"][0] - gx) <= 1.6 and abs(g["pos"][1] - gy) <= 1.6:
                return True
            bb = g.get("bbox")
            if bb and bb[0] - 1.0 <= gx <= bb[2] + 1.0 \
                    and bb[1] - 1.0 <= gy <= bb[3] + 1.0:
                return True
        return False

    emergent = [g for g in grouped if not matches_planted(g)]
    n = sum(1 for x in per if x["detected"])
    return {"planted": len(w.gt), "detected": n,
            "recall": round(n / max(len(w.gt), 1), 3),
            "sweep_findings": len(grouped),
            "emergent_features": len(emergent),
            "emergent": [{"type": e["type"], "pos": e["pos"],
                          "agents": e["agents"]} for e in emergent[:10]],
            "per_defect": per}


if __name__ == "__main__":
    main()
