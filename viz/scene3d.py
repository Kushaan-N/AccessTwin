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
from world3d import build3d, SURFACE_ORDER
from navgrid import NavGrid
from pathing import GeoField
from sweep import sweep, group
from scipy import ndimage
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
    "auditorium": "Auditorium",
    "reading_room": "Reading Room",
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
    free, floor_z, ceil_z, surf = w.rasterize()
    cell = w.cell
    grid = NavGrid(free, floor_z, cell, ceiling=ceil_z,
                   surface=surf, surface_order=SURFACE_ORDER)
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
                     seed=args.seed, pop_n=args.pop, ceiling=ceil_z,
                     surface=surf, surface_order=SURFACE_ORDER)
    fixed_free, fixed_height = opt.pop("_final_world")
    fixed_free = np.asarray(fixed_free)
    after = NavGrid(fixed_free, fixed_height, cell, ceiling=ceil_z,
                    surface=surf, surface_order=SURFACE_ORDER)
    after_base = after.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
    for pr in profiles:
        p = next(q for q in ALL_PROFILES if q.name == pr["name"])
        a = after.analyse(p, spawn)
        # The route through the remediated building. Without this the
        # viewer can show a fix landing but not the journey it creates,
        # which is the only part that proves anything.
        pr["after_journeys"] = {
            g: walk(after, p, spawn, c, fixed_height, cell)
            for g, c in goals.items()}
        pr["after_pct"] = round(100 * a["reachable_m2"] / after_base, 1)
        pr["after_reach_grid"] = encode_mask(a["reachable"])
        pr["after_goals"] = {g: bool(after.reaches(p, spawn, c))
                             for g, c in goals.items()}

    cf = counterfactual(args.seed, spawn, cell)
    chokes = chokepoints(w, grid, spawn, cell, profiles, opt,
                         seed=args.seed)
    sweepw = width_sweep(w, grid, spawn, cell)
    recall = score_recall(w, grid, profiles, free, cell)

    scene = w.to_scene()
    scene.update({
        "seed": args.seed,
        "grid": {"nx": free.shape[0], "ny": free.shape[1], "cell": cell,
                 "mask_nx": free[::2, ::2].shape[0],
                 "mask_ny": free[::2, ::2].shape[1]},
        "goal_labels": GOAL_LABELS,
        "profiles": profiles,
        "breaking_point": bp,
        "population": pop,
        "elasticity": A.elasticity(pop["width_curve"]),
        "detour": det,
        "remediation": opt,
        "recall": recall,
        "width_sweep": sweepw,
        "counterfactual": cf,
        "surface_grid": encode_surface(surf),
        "chokepoints": chokes,
        "issues": audit_issues(w, grid, free, cell, chokes, profiles,
                               opt, seed=args.seed),
    })

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    path = os.path.join(ROOT, "out", "scene.json")
    with open(path, "w") as fh:
        json.dump(scene, fh, separators=(",", ":"), default=float)
    print(f"\nwrote {path}  ({os.path.getsize(path)/1024:.0f} kB)")
    print(f"population full access: {pop['pct_full_access']}% -> "
          f"{opt['after']['pct_full_access']}% after ${opt['spent_usd']:,}")
    print(f"recall: {recall['detected']}/{recall['planted']}")


def counterfactual(seed, spawn, cell):
    """Regenerate the same building with its contents removed.

    Exact, not inferred: same walls, same ramp, same doors, furniture
    omitted. Whatever the difference is, the furniture caused it -- and
    that half of the problem is fixable by somebody with a trolley.
    """
    a = build3d(seed)
    b = build3d(seed, with_contents=False)
    fa, za, ca, sa = a.rasterize()
    fb, zb, cb, sb = b.rasterize()
    ga = NavGrid(fa, za, cell, ceiling=ca, surface=sa,
                 surface_order=SURFACE_ORDER)
    gb = NavGrid(fb, zb, cell, ceiling=cb, surface=sb,
                 surface_order=SURFACE_ORDER)
    # Both worlds are measured against the SAME denominator -- the floor
    # a walking adult reaches once the contents are out of the way.
    # Normalising each world to its own baseline made the walking adult
    # read 100% -> 100% and hid the fact that it gains floor too.
    base = gb.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
    base_a = base_b = base
    out = {"furniture_m2": round(float((fb & ~fa).sum()) * cell ** 2, 1),
           "profiles": {}}
    for p in ALL_PROFILES:
        ra = ga.analyse(p, spawn)
        rb = gb.analyse(p, spawn)
        pa = 100 * ra["reachable_m2"] / base_a
        pb = 100 * rb["reachable_m2"] / base_b
        opened = [g for g, c in a.goals.items()
                  if gb.reaches(p, spawn, c) and not ga.reaches(p, spawn, c)]
        out["profiles"][p.name] = {
            "as_built_pct": round(pa, 1),
            "contents_removed_pct": round(pb, 1),
            "recovered_pct": round(pb - pa, 1),
            "rooms_unlocked": opened,
        }
    out["note"] = ("Floor recovered by moving contents costs nothing to "
                   "fix. Rooms that stay shut are shut by the building.")
    return out


MOVABLE = {"cafe_table", "cafe_chair", "stool", "planter", "lobby_seat",
           "low_table", "reading_table", "bench"}
FIXED_COST = {"seat": 5200, "stage": 3800, "reception": 2400,
              "cafe_counter": 3100, "bookshelf": 900,
              "display_panel": 700, "display_case": 700}


def furniture_blockages(seed, spawn, cell, min_m2=1.2, top=8):
    """Where the contents, specifically, are what stops somebody.

    Ground truth rather than inference: difference each profile's
    reachable set between the building as built and the same building
    with its furniture omitted. Whatever it gains is furniture-caused,
    and every one of those is fixable by somebody with a trolley.
    """
    a = build3d(seed)
    b = build3d(seed, with_contents=False)
    fa, za, ca, sa = a.rasterize()
    fb, zb, cb, sb = b.rasterize()
    ga = NavGrid(fa, za, cell, ceiling=ca, surface=sa,
                 surface_order=SURFACE_ORDER)
    gb = NavGrid(fb, zb, cell, ceiling=cb, surface=sb,
                 surface_order=SURFACE_ORDER)

    gained = np.zeros(fa.shape, dtype=bool)
    per = {}
    for p in ALL_PROFILES:
        # Restricted to floor that is open in BOTH worlds. Without that
        # this measures the footprint of the furniture -- the floor under
        # a table becomes walkable once you remove the table -- rather
        # than the floor the furniture cuts you off from. The giveaway
        # was the walking adult appearing in every blockage while
        # recovering 0.0% overall.
        d = (gb.analyse(p, spawn)["reachable"]
             & ~ga.analyse(p, spawn)["reachable"] & fa)
        per[p.name] = d
        gained |= d
    if not gained.any():
        return []

    # Name each blockage after the nearest thing that is actually in the
    # way, so the popup says "relocate the cafe seating" rather than
    # quoting a coordinate.
    furn = [s for s in a.solids if s.kind == "furniture"]
    lab, n = ndimage.label(gained, structure=np.ones((3, 3)))
    out = []
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) * cell ** 2
        if area < min_m2:
            continue
        ys, xs = np.nonzero(m)
        cx, cy = float(ys.mean()) * cell, float(xs.mean()) * cell
        who = sorted(nm for nm, d in per.items() if (d & m).any())
        near, best = None, 1e9
        for f in furn:
            fx = max(f.x0, min(cx, f.x1))
            fy = max(f.y0, min(cy, f.y1))
            dd = (fx - cx) ** 2 + (fy - cy) ** 2
            if dd < best:
                best, near = dd, f
        tag = near.tag if near else "contents"
        label = tag.replace("_", " ")
        movable = tag in MOVABLE
        cost = 0 if movable else FIXED_COST.get(tag, 1500)
        out.append({
            "id": f"{'move' if movable else 'reconfig'}@{cx:.1f},{cy:.1f}",
            "kind": "declutter" if movable else "reconfigure",
            "verdict": "move" if movable else "reconfigure",
            "pos": [round(cx, 2), round(cy, 2)],
            "detail": (f"relocate the {label} — returns {area:.0f} m\u00b2 "
                       f"of floor" if movable else
                       f"re-lay the fixed {label} — returns {area:.0f} m\u00b2 "
                       f"of floor"),
            "cost": cost, "excludes": who, "goals_blocked": [],
            "opens_alone": [], "gain_pct": 0.0, "chosen": False,
            "area_m2": round(area, 1), "movable": movable,
        })
    out.sort(key=lambda d: -d["area_m2"])
    return out[:top]


def chokepoints(w, grid, spawn, cell, profiles, opt, seed=7):
    """Every blockage, with a verdict: move it, build it, or neither.

    Sources are already computed and merely joined here -- the fix
    candidates carry kind and cost, the barrier finder carries which
    body was stopped where, and the optimiser has MEASURED what each
    fix returns by rebuilding the building with it applied.

    The third verdict is the important one. A barrier whose repair opens
    nothing on its own is not cheap-and-easy, it is one of several that
    must all happen -- and a marker that only ever says move-or-build
    cannot express that.
    """
    stand = {d["id"]: d for d in opt.get("standalone_scores", [])}
    chosen_ids = {c["id"] for c in opt.get("chosen", [])}
    base_goals = {k: v["goals"]
                  for k, v in (opt.get("baseline_by_profile") or {}).items()}

    # who is stopped where
    blocked = []
    for pr in profiles:
        for gname, j in pr["journeys"].items():
            for b in j.get("barriers", []):
                blocked.append((b["pos"][0], b["pos"][1], pr["name"],
                                gname, b))

    out = []
    for c in opt.get("candidate_menu", []):
        px, py = c["pos"][0], c["pos"][1]
        near = [t for t in blocked
                if abs(t[0] - px) <= 1.8 and abs(t[1] - py) <= 1.8]
        who = sorted({t[2] for t in near})
        goals_hit = sorted({t[3] for t in near})

        sc = stand.get(c["id"], {})
        after = sc.get("by_profile", {})
        opens = []
        for name, aft in after.items():
            if name in base_goals and aft["goals"] > base_goals[name]:
                opens.append(name)

        furniture = c["kind"] == "declutter"
        if furniture:
            verdict = "move"
        elif opens:
            verdict = "build"
        else:
            verdict = "combined"

        out.append({
            "id": c["id"],
            "kind": c["kind"],
            "verdict": verdict,
            "pos": [px, py],
            "detail": c["detail"],
            "cost": 0 if furniture else c["cost"],
            "excludes": who,
            "goals_blocked": goals_hit,
            "opens_alone": opens,
            "gain_pct": sc.get("gain_pct", 0.0),
            "chosen": c["id"] in chosen_ids,
        })
    out.extend(furniture_blockages(seed, spawn, cell))
    out.sort(key=lambda d: (d["verdict"] != "move", d["cost"]))
    return out


# Illustrative remedies for findings the route-based optimiser never
# nominates, because they exclude somebody without disconnecting a goal.
REMEDY = {
    "floor_surface": ("Replace with a hard finish or low-pile carpet",
                      "area", 65.0),
    "counter_height": ("Drop a 865 mm section into the counter run",
                       "flat", 1400.0),
    "head_clearance": ("Raise the obstruction clear of 2032 mm",
                       "flat", 2200.0),
    "turning_radius": ("Enlarge the compartment to take a 1525 mm circle",
                       "flat", 8500.0),
    "clearance_width": ("Widen the opening", "flat", 3200.0),
    "step_height": ("Ramp the level change at 1:14", "flat", 2400.0),
    "slope_gradient": ("Regrade the run to 1:14", "flat", 2600.0),
}


def audit_issues(w, grid, free, cell, chokes, profiles, opt, seed=7,
                 cap=30):
    """One worklist: every finding, what fixes it, and what that costs.

    The walkthrough is a story and only needs the barriers that stop
    somebody mid-route. An auditor wants the other kind too -- the
    carpet, the counter, the turning circle -- which exclude people
    without disconnecting anything, so no route-based search ever
    nominates them.

    The hard part is not gathering findings, it is refusing to list
    them all. A raw sweep produces 80-odd clearance hits, nearly all
    of them gaps between a chair and a table, and a worklist with 83
    identical "widen the opening" rows is worse than no worklist.
    So: cluster at 2 m, drop clearance pinches that are made of
    furniture rather than building, name the room, and cap the list.
    """
    from sweep import sweep as run_sweep, group as group_sweep
    issues = []

    for c in chokes:
        issues.append({**c, "source": "route", "remedy": c["detail"],
                       "room": nearest_room(w, c["pos"][0], c["pos"][1]),
                       "title": ("Blocked by loose furniture"
                                 if c["verdict"] == "move" else
                                 "Blocked by fixed furniture"
                                 if c["verdict"] == "reconfigure" else
                                 "One of several barriers"
                                 if c["verdict"] == "combined" else
                                 "Blocked by the building")})

    # Furniture footprint, so a gap between two chairs is not billed as
    # a structural opening.
    fe = build3d(seed, with_contents=False).rasterize()[0]
    furn = fe & ~free
    fdist = ndimage.distance_transform_edt(~furn, sampling=cell) \
        if furn.any() else np.full(free.shape, np.inf)

    raw = run_sweep(grid, free, cell, rooms=w.rooms, spawn=w.spawn,
                    solids=w.solids)

    # Merge on extent, not on a representative point. A 6.8 m counter or
    # a 12 m ramp is reported once per profile and each profile's worst
    # cell lands at a different end, so point-distance merging leaves
    # three rows for one thing to fix.
    merged = []
    for g in group_sweep(raw, cell=2.0):
        bb = g.get("bbox")
        hit = None
        for m in merged:
            if m["type"] != g["type"]:
                continue
            mb = m.get("bbox")
            if bb and mb and not (bb[2] < mb[0] - 1.0 or bb[0] > mb[2] + 1.0
                                  or bb[3] < mb[1] - 1.0 or bb[1] > mb[3] + 1.0):
                hit = m
                break
            if not bb or not mb:
                if (abs(g["pos"][0] - m["pos"][0]) <= 2.0
                        and abs(g["pos"][1] - m["pos"][1]) <= 2.0):
                    hit = m
                    break
        if hit:
            hit["agents"] = sorted(set(hit.get("agents", []))
                                   | set(g.get("agents", [])))
            hit["area_m2"] = round(hit.get("area_m2", 0)
                                   + g.get("area_m2", 0), 1)
            if bb and hit.get("bbox"):
                hit["bbox"] = [min(bb[0], hit["bbox"][0]),
                               min(bb[1], hit["bbox"][1]),
                               max(bb[2], hit["bbox"][2]),
                               max(bb[3], hit["bbox"][3])]
        else:
            merged.append(dict(g))

    minor = 0
    for g in merged:
        px, py = g["pos"]
        kind = g["type"]
        # Same place is not the same problem: a relocatable bench and a
        # carpet that stops a castor can share a room, and folding one
        # into the other loses the finding entirely.
        if any(abs(px - c["pos"][0]) <= 2.0 and abs(py - c["pos"][1]) <= 2.0
               and c.get("kind") == kind for c in chokes):
            continue
        ix, iy = int(round(px / cell)), int(round(py / cell))
        if kind == "clearance_width":
            # Made of furniture, not building: already covered by the
            # relocate entries, and not a construction job.
            if fdist[min(ix, fdist.shape[0] - 1),
                     min(iy, fdist.shape[1] - 1)] < 0.9:
                minor += 1
                continue
        label, mode, unit = REMEDY.get(kind, ("Investigate on site",
                                              "flat", 0.0))
        area = g.get("area_m2", 0.0)
        cost = max(round(unit * area), 400) if mode == "area" else round(unit)
        room = nearest_room(w, px, py)
        meas = g.get("measured_in", 0) or 0
        if kind == "floor_surface":
            detail = (f"{label} — {area:.0f} m² of "
                      f"{g.get('surface_label', 'finish')}")
        elif kind == "counter_height":
            detail = f"{label} — the run is at {meas:.0f}in today"
        elif kind == "turning_radius":
            detail = f"{label} — {meas:.0f}in circle today, 60in required"
        elif kind == "head_clearance":
            detail = f"{label} — {meas:.0f}in today, 80in required"
        elif kind == "clearance_width":
            detail = f"{label} — {meas:.0f}in clear today"
        else:
            detail = label
        issues.append({
            "id": f"sweep:{kind}@{px:.1f},{py:.1f}",
            "kind": kind, "verdict": "build", "source": "sweep",
            "pos": [px, py], "detail": detail, "remedy": detail,
            "cost": cost, "room": room,
            "excludes": sorted(set(g.get("agents", []))),
            "goals_blocked": [], "opens_alone": [], "gain_pct": 0.0,
            "chosen": False, "area_m2": area,
            "title": "Excludes without disconnecting",
        })

    # Cost per square metre returned. A worklist sorted by price answers
    # "what is cheapest"; sorted by this it answers "what is worth
    # doing", which is a different and better question.
    stand = {d["id"]: d for d in (opt.get("standalone_scores") or [])}
    for it in issues:
        m2 = it.get("area_m2") or 0.0
        sc = stand.get(it["id"])
        if sc and sc.get("profile_m2"):
            m2 = max(m2, max(sc["profile_m2"].values()))
        it["recovered_m2"] = round(m2, 1)
        it["cost_per_m2"] = (round(it["cost"] / m2) if it["cost"] and m2 > 0.2
                             else (0 if not it["cost"] else None))

    order = {"move": 0, "reconfigure": 1, "combined": 2, "build": 3}
    issues.sort(key=lambda d: (order.get(d["verdict"], 9),
                               -len(d.get("excludes", [])), d["cost"]))
    # The cap only trims sweep extras. A route barrier is something a
    # body actually hit, and dropping one to fit a list length would be
    # hiding the finding that matters most.
    keep = [d for d in issues if d["source"] == "route"]
    extra = [d for d in issues if d["source"] != "route"]
    room = max(0, cap - len(keep))
    minor += max(0, len(extra) - room)
    issues = sorted(keep + extra[:room],
                    key=lambda d: (order.get(d["verdict"], 9), d["cost"]))
    for it in issues:
        it["minor_folded"] = minor
    return issues


def width_sweep(w, grid, spawn, cell, lo=18.0, hi=48.0, step=2.0):
    """Which rooms survive, as the body gets wider.

    Sweeps a probe body across the population's width range holding a
    real wheelchair's slope and step tolerance fixed, and records which
    rooms it can still reach. Reporting rooms rather than a pixel mask
    is both far smaller to ship and far more legible: on a projector you
    watch named rooms switch off one at a time, and the width at which
    each one goes dark is the number that matters.
    """
    from schema import WHEELCHAIR
    base = grid.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
    rows = []
    wi = lo
    while wi <= hi + 1e-9:
        p = A.probe(wi, WHEELCHAIR.max_slope_ratio, WHEELCHAIR.max_step_in)
        st = grid.analyse(p, spawn, min_island_cells=10 ** 9)
        reach = st["reachable"]
        rooms = {}
        for r in w.rooms:
            i0, i1 = int(r["x0"] / cell), int(r["x1"] / cell)
            j0, j1 = int(r["y0"] / cell), int(r["y1"] / cell)
            sub = reach[i0:i1, j0:j1]
            # Usable means a meaningful patch of the room is reachable,
            # not that the body can put one wheel over the sill. The
            # threshold scales with the room: a fixed 2 m2 would call a
            # 3 m2 WC closed at every width and hide the transition that
            # actually matters.
            area = max((i1 - i0) * (j1 - j0) * cell ** 2, 1e-6)
            got = float(sub.sum()) * cell ** 2
            rooms[r["name"]] = bool(got >= max(0.7, 0.14 * area))
        rows.append({
            "width_in": round(wi, 1),
            "reach_m2": st["reachable_m2"],
            "pct": round(100 * st["reachable_m2"] / base, 1),
            "rooms": rooms,
        })
        wi += step
    return rows


def nearest_room(w, x, y):
    for r in w.rooms:
        if r["x0"] <= x <= r["x1"] and r["y0"] <= y <= r["y1"]:
            return r["name"]
    return ""


def encode_surface(surf):
    """Quarter-resolution surface raster for the floor-material overlay.

    Full res would be 630 kB of base64 for something the eye reads as
    broad zones; at a 20 cm cell it is 40 kB and looks identical.
    """
    import base64
    q = surf[::4, ::4]
    return {"nx": int(q.shape[0]), "ny": int(q.shape[1]),
            "cell": 0.2,
            "data": base64.b64encode(q.tobytes()).decode("ascii")}


def encode_mask(m, step=2):
    """Half-resolution, OR-reduced. Eight of these at full 5 cm cost
    528 kB of the payload for an overlay the eye reads as broad regions;
    at 10 cm they are a quarter of that and look identical."""
    import base64
    a = m[::step, ::step].copy()
    for i in range(step):
        for j in range(step):
            a |= m[i::step, j::step][:a.shape[0], :a.shape[1]]
    return base64.b64encode(np.packbits(a.astype(np.uint8).ravel())
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

    sweep_raw = sweep(grid, free, cell, rooms=w.rooms, spawn=w.spawn,
                      solids=w.solids)
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
