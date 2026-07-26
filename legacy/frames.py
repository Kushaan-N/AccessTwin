"""Build the self-running demo page.

Precomputes everything the browser needs -- masks, geodesic flood
fields, routes, barriers, statistics -- packs it into one JSON blob and
inlines it into a single self-contained HTML file. No network requests,
no build step, no server: opening the file IS the demo.

The flood animation is not decoration. Each profile ships a geodesic
distance field from the spawn point, so the reveal front advancing
across the floor is literally that profile walking outward at constant
speed. Where the front stops is where the body stops.

Run:  python3 viz/frames.py --seed 7
Then: open out/demo.html
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))

from schema import ALL_PROFILES, BASELINE, IN_PER_M
from worldgen import build
from navgrid import NavGrid
from pathing import GeoField
import analysis as A

DS = 2                      # plan-view downsample; 600x400 -> 300x200
HEIGHT_DS = 4

# Validated categorical palette (see dataviz validator: lightness band,
# chroma floor, CVD separation, normal-vision floor and contrast all
# PASS against both surfaces). Profiles are ALWAYS direct-labelled as
# well, so identity never rests on colour alone.
PROFILE_COLORS = {
    "baseline_walking":        {"dark": "#29A090", "light": "#00897B"},
    "wheelchair":              {"dark": "#6285D6", "light": "#3B62B8"},
    "vision_impaired_cane":    {"dark": "#D05C8C", "light": "#B03368"},
    "sidewalk_delivery_robot": {"dark": "#BE8A30", "light": "#8A6410"},
}
PROFILE_LABELS = {
    "baseline_walking": "Walking adult",
    "wheelchair": "Wheelchair",
    "vision_impaired_cane": "Cane user",
    "sidewalk_delivery_robot": "Delivery robot",
}


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(a.tobytes()).decode("ascii")


def _bits(mask: np.ndarray) -> str:
    """Bit-pack a boolean plan into base64. ~7.5 kB per 300x200 layer."""
    return _b64(np.packbits(mask.astype(np.uint8).ravel()))


def _down_and(m, k=DS):
    """Downsample a boolean plan, obstruction wins.

    Walls are 4 cells thick at 5 cm; a naive stride would drop them to 2
    and a majority filter would erase the thin ones entirely.
    """
    out = m[::k, ::k].copy()
    for i in range(k):
        for j in range(k):
            out &= m[i::k, j::k][:out.shape[0], :out.shape[1]]
    return out


def _down_or(m, k=DS):
    out = m[::k, ::k].copy()
    for i in range(k):
        for j in range(k):
            out |= m[i::k, j::k][:out.shape[0], :out.shape[1]]
    return out


def _down_min(m, k=DS):
    """Downsample a distance field keeping the nearest arrival.

    Minimum, not stride: 255 marks 'never reached', so any block
    containing a reachable cell must stay reachable.
    """
    out = m[::k, ::k].copy()
    for i in range(k):
        for j in range(k):
            out = np.minimum(out, m[i::k, j::k][:out.shape[0], :out.shape[1]])
    return out


def flood_field(grid: NavGrid, p, spawn) -> tuple[np.ndarray, float]:
    """Geodesic distance from spawn, quantised to 0..254. 255 = never."""
    nav = grid.navigable(p)
    gf = GeoField(nav, grid.cell)
    sp = NavGrid.snap(nav, spawn)
    d = gf.field(sp)
    finite = np.isfinite(d)
    dmax = float(d[finite].max()) if finite.any() else 1.0
    q = np.full(d.shape, 255, dtype=np.uint8)
    if finite.any():
        q[finite] = np.clip(d[finite] / max(dmax, 1e-9) * 254, 0, 254
                            ).astype(np.uint8)
    return q, dmax


def routes_for(grid: NavGrid, p, spawn, goals) -> dict:
    nav = grid.navigable(p)
    gf = GeoField(nav, grid.cell)
    sp = NavGrid.snap(nav, spawn)
    fld = gf.field(sp)
    out = {}
    for name, goal in goals.items():
        r = gf.route(fld, goal)
        if not r:
            continue
        step = max(1, len(r) // 90)
        out[name] = [[int(c[0] // DS), int(c[1] // DS)] for c in r[::step]]
    return out


def build_payload(seed: int, analysis: dict) -> dict:
    free, height, cell, spawn, goals, gt = build(seed)
    grid = NavGrid(free, height, cell)
    furn = A.furniture_mask(seed)

    d_free = _down_and(free)
    d_furn = _down_or(furn)
    # nx runs along the 30 m width, ny along the 20 m depth. The canvas
    # draws nx horizontally, so the plan reads the same way up as the
    # numbers in the audit.
    nx, ny = d_free.shape

    hq = height[::HEIGHT_DS, ::HEIGHT_DS]
    hmax = float(max(height.max(), 1e-6))
    hq = np.clip(hq / hmax * 255, 0, 255).astype(np.uint8)

    # After-remediation world, for the before/after toggle.
    opt = analysis["remediation"]
    wz = np.load(os.path.join(ROOT, "out", "world.npz"))
    fixed_free, fixed_height = wz["fixed_free"], wz["fixed_height"]
    after_grid = NavGrid(fixed_free, fixed_height, cell)

    profiles = []
    for p in ALL_PROFILES:
        q, dmax = flood_field(grid, p, spawn)
        st = grid.analyse(p, spawn)
        after = after_grid.analyse(p, spawn)
        base_m2 = grid.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
        after_base = after_grid.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
        profiles.append({
            "name": p.name,
            "label": PROFILE_LABELS[p.name],
            "color": PROFILE_COLORS[p.name],
            "width_in": p.required_clearance_in,
            "max_slope": round(p.max_slope_ratio, 4),
            "max_step_in": p.max_step_in,
            "flood": _b64(_down_min(q)),
            "reachable": _bits(_down_or(st["reachable"])),
            "after_reachable": _bits(_down_or(after["reachable"])),
            "reach_m2": st["reachable_m2"],
            "pct": round(100 * st["reachable_m2"] / base_m2, 1),
            "after_pct": round(100 * after["reachable_m2"] / after_base, 1),
            "islands": [{"area_m2": i["area_m2"],
                         "centroid": [i["centroid"][0] // DS,
                                      i["centroid"][1] // DS]}
                        for i in st["islands"]],
            "island_m2": st["island_m2"],
            "goals": {k: bool(grid.reaches(p, spawn, g))
                      for k, g in goals.items()},
            "routes": routes_for(grid, p, spawn, goals),
        })

    barr = []
    for pname, per_goal in analysis["barriers"].items():
        for gname, rec in per_goal.items():
            for b in rec["barriers"]:
                barr.append({
                    "profile": pname, "goal": gname, "kind": b["kind"],
                    "cell": [b["cell"][0] // DS, b["cell"][1] // DS],
                    "pos": b["pos"], "aperture_in": b["aperture_in"],
                    "step_in": b["step_in"], "severity": b["severity"],
                })

    fixes = []
    for c in analysis["remediation"]["candidate_menu"]:
        fixes.append({**c, "cell": [c["cell"][0] // DS, c["cell"][1] // DS],
                      "chosen": any(x["id"] == c["id"]
                                    for x in analysis["remediation"]["chosen"])})

    return {
        "meta": {
            "seed": seed, "cell_m": cell * DS, "nx": nx, "ny": ny,
            "world_m": [round(free.shape[0] * cell, 1),
                        round(free.shape[1] * cell, 1)],
            "spawn": [spawn[0] // DS, spawn[1] // DS],
            "goals": {k: [v[0] // DS, v[1] // DS] for k, v in goals.items()},
            "hnx": hq.shape[0], "hny": hq.shape[1],
            "runtime_s": analysis["runtime_s"],
        },
        "free": _bits(d_free),
        "furniture": _bits(d_furn),
        "height": _b64(hq),
        "profiles": profiles,
        "barriers": barr,
        "fixes": fixes,
        "ground_truth": [
            {**d, "cell": [int(round(d["pos"][0] / (cell * DS))),
                           int(round(d["pos"][1] / (cell * DS)))]}
            for d in gt],
        "island": analysis["headline_island"],
        "recall": analysis["audit"]["recall"],
        "breaking_point": analysis["breaking_point"],
        "population": analysis["population"],
        "elasticity": analysis["elasticity"],
        "counterfactual": analysis["counterfactual"],
        "remediation": {k: v for k, v in analysis["remediation"].items()
                        if k != "candidate_menu"},
        "detour": analysis["detour"],
        "headlines": analysis["headlines"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    apath = os.path.join(ROOT, "out", "analysis_output.json")
    if not os.path.exists(apath):
        sys.exit("run core/run_analysis.py first")
    analysis = json.load(open(apath))

    payload = build_payload(args.seed, analysis)
    blob = json.dumps(payload, separators=(",", ":"))

    tpl = open(os.path.join(ROOT, "viz", "template.html")).read()
    body = tpl.replace("/*__DATA__*/null", blob)

    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    art = os.path.join(ROOT, "out", "artifact.html")
    with open(art, "w") as fh:
        fh.write(body)

    standalone = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width,"
        "initial-scale=1\">\n"
        "<title>Access-Twin — who can actually get through</title>\n"
        "</head>\n<body>\n" + body + "\n</body>\n</html>\n")
    demo = os.path.join(ROOT, "out", "demo.html")
    with open(demo, "w") as fh:
        fh.write(standalone)

    kb = len(standalone) / 1024
    print(f"payload {len(blob)/1024:.0f} kB   page {kb:.0f} kB")
    print(f"wrote {demo}")
    print(f"wrote {art}  (body-only, for publishing)")


if __name__ == "__main__":
    main()
