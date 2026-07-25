"""Access-Twin full study: audit + every higher-order analysis.

Writes out/analysis_output.json, which is the single artefact the
visualisation and the demo read. Deterministic for a given seed.

Run:  python3 core/run_analysis.py --seed 7 --budget 5000
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schema import ALL_PROFILES, BASELINE, IN_PER_M
from worldgen import build
from navgrid import NavGrid
from auditor import Auditor
import analysis as A


def _headlines(js: dict) -> list[str]:
    """The three or four sentences the demo actually says out loud."""
    out = []
    r = js["audit"]["recall"]
    out.append(
        f"Planted {r['planted']} defects, detected {r['detected']} "
        f"({r['recall']:.0%} recall), plus {r['emergent_features']} emergent "
        f"exclusions created by furniture rather than architecture.")

    isl = js["headline_island"]
    if isl and isl.get("passes_all_interior_checks"):
        out.append(
            f"A {isl['area_m2']:.0f} m2 region passes every geometric check "
            f"inside it -- {isl['min_clearance_in']:.0f}in minimum corridor, "
            f"a {isl['largest_inscribed_circle_in']:.0f}in turning circle, "
            f"dead flat, no level change -- and is completely unreachable "
            f"for {isl['profile']}. No clearance-based audit would flag it.")
    elif isl:
        out.append(
            f"The largest unreachable region is {isl['area_m2']:.0f} m2 "
            f"for {isl['profile']}.")

    bp = js["breaking_point"].get("side_room")
    if bp and bp["width_only_in"] - bp["full_envelope_in"] > 1.0:
        out.append(
            f"Measured with a tape, this route serves bodies up to "
            f"{bp['width_only_in']:.0f}in. Run an actual body through it and "
            f"it is {bp['full_envelope_in']:.0f}in -- the wide way in has a "
            f"threshold, so you are forced through the narrow door.")

    o = js["remediation"]
    if o["chosen"]:
        best = o["chosen"][0]
        worse = [d for d in o["rejected"] if d["cost"] > best["cost"]]
        line = (f"With ${o['budget_usd']:,.0f}, the optimal spend is "
                f"${o['spent_usd']:,} on {len(o['chosen'])} fix(es), taking "
                f"population access from {o['before']['pct_full_access']}% to "
                f"{o['after']['pct_full_access']}%.")
        if worse:
            w = max(worse, key=lambda d: d["cost"])
            ratio = w["cost"] / max(best["cost"], 1)
            line += (f" The obvious fix -- {w['detail']} at ${w['cost']:,} -- "
                     f"was measured and rejected: it buys "
                     f"{w['gain_pct']:.0f} points for {ratio:.1f}x the price "
                     f"({w['pct_per_1k_usd']:.1f} vs "
                     f"{best['pct_per_1k_usd']:.1f} points per $1k).")
        out.append(line)
    return out


def _island_stats(aud: Auditor, p, isl) -> dict:
    """Run the Layer-1 geometric rules INSIDE one unreachable region."""
    from scipy import ndimage
    g = aud.grid
    lab, _ = ndimage.label(aud.profile_state(p)["nav_mask"])
    cy, cx = int(isl["centroid"][0]), int(isl["centroid"][1])
    if lab[cy, cx] == 0:
        return {}
    interior = (lab == lab[cy, cx]) & aud.free
    if not interior.any():
        return {}
    # Measure clearance on the region's medial axis, not its edge cells:
    # every region touches a wall at its boundary, so an edge-cell
    # minimum would report ~0 for even a ballroom.
    ridge = interior & aud.ridge
    src = ridge if ridge.any() else interior
    min_clear_in = float(g.clearance[src].min() * 2 * IN_PER_M)
    max_slope = float(g.slope[interior].max())
    max_step_in = float(g.step[interior].max() * IN_PER_M)
    biggest_circle_in = float(g.clearance[interior].max() * 2 * IN_PER_M)
    return {
        "profile": p.name,
        "area_m2": isl["area_m2"],
        "centroid": [round(cy * g.cell, 1), round(cx * g.cell, 1)],
        "min_clearance_in": round(min_clear_in, 1),
        "max_slope": round(max_slope, 4),
        "max_step_in": round(max_step_in, 2),
        "largest_inscribed_circle_in": round(biggest_circle_in, 1),
        "turning_circle_fits": bool(biggest_circle_in >= 60.0),
        # The ADA thresholds a surveyor standing inside would apply.
        "passes_all_interior_checks": bool(
            min_clear_in >= 36.0 and max_slope <= 1 / 12
            and max_step_in <= 0.5 and biggest_circle_in >= 60.0),
    }


def headline_island(aud: Auditor) -> dict:
    """The largest unreachable region whose interior is geometrically clean.

    The finding only lands if the region really does pass every rule
    inside it, so we verify that rather than assuming it: score every
    island, keep the ones that pass, take the biggest. If none pass we
    return the largest anyway, flagged, and the demo says something
    weaker instead of something false.
    """
    scored = []
    for p in ALL_PROFILES:
        for isl in aud.profile_state(p)["islands"]:
            s = _island_stats(aud, p, isl)
            if s:
                scored.append(s)
    if not scored:
        return {}
    clean = [s for s in scored if s["passes_all_interior_checks"]]
    pool = clean or scored
    return max(pool, key=lambda d: d["area_m2"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--budget", type=float, default=5000.0)
    ap.add_argument("--pop", type=int, default=240)
    ap.add_argument("--opt-pop", type=int, default=90)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    t0 = time.time()
    free, height, cell, spawn, goals, gt = build(args.seed)
    grid = NavGrid(free, height, cell)
    furn = A.furniture_mask(args.seed)

    stage = {}

    def timed(name, fn):
        t = time.time()
        v = fn()
        stage[name] = round(time.time() - t, 2)
        print(f"  {name:22s} {stage[name]:6.2f}s")
        return v

    print(f"Access-Twin full study  seed={args.seed}")
    aud = timed("audit", lambda: Auditor(seed=args.seed,
                                         world=(free, height, cell, spawn,
                                                goals, gt)))
    audit = timed("audit.run", aud.run).to_json()
    island = timed("headline_island", lambda: headline_island(aud))
    bp = timed("breaking_point", lambda: A.breaking_point(grid, spawn, goals))
    barr = timed("barriers", lambda: A.barrier_report(grid, spawn, goals))
    det = timed("detour", lambda: A.detour(grid, spawn, goals))
    pop = timed("population",
                lambda: A.population_coverage(grid, spawn, goals,
                                              pop=A.sample_population(
                                                  args.pop, args.seed)))
    cf = timed("counterfactual",
               lambda: A.counterfactual_furniture(args.seed, spawn, goals))
    opt = timed("remediation",
                lambda: A.optimise(free, height, cell, spawn, goals,
                                   budget=args.budget, seed=args.seed,
                                   pop_n=args.opt_pop, furniture=furn))

    fixed_free, fixed_height = opt.pop("_final_world")
    after_grid = NavGrid(fixed_free, fixed_height, cell)
    after_cov = {p.name: after_grid.analyse(p, spawn)["reachable_m2"]
                 for p in ALL_PROFILES}

    js = {
        "seed": args.seed,
        "world": {"width_m": free.shape[0] * cell,
                  "depth_m": free.shape[1] * cell, "cell_m": cell,
                  "grid": list(free.shape),
                  "spawn": list(spawn),
                  "goals": {k: list(v) for k, v in goals.items()}},
        "audit": audit,
        "headline_island": island,
        "breaking_point": bp,
        "barriers": barr,
        "detour": det,
        "population": pop,
        "elasticity": A.elasticity(pop["width_curve"]),
        "counterfactual": cf,
        "remediation": opt,
        "coverage_after_remediation_m2": after_cov,
        "stage_times_s": stage,
        "runtime_s": round(time.time() - t0, 2),
    }
    js["headlines"] = _headlines(js)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = args.out or os.path.join(root, "out", "analysis_output.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(js, fh, indent=2, default=float)
    np.savez_compressed(
        os.path.join(root, "out", "world.npz"),
        free=free, height=height, cell=cell, spawn=np.array(spawn),
        fixed_free=fixed_free, fixed_height=fixed_height, furniture=furn)

    print(f"\ntotal {js['runtime_s']}s -> {out}")
    print("\n" + "=" * 72)
    for i, line in enumerate(js["headlines"], 1):
        print(f"\n[{i}] {line}")
    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
