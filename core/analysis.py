"""Access-Twin higher-order analysis.

Everything here consumes the same NavGrid the auditor uses, so no
finding can disagree with the audit.

  breaking_point     -- bisect body width until the space stops working
  chokepoints        -- WHERE it stops working. Found by widest-path
                        analysis, not from a hand-written candidate list.
  detour             -- geodesic route length vs the baseline route
  population         -- Monte Carlo over a synthetic mobility population
  counterfactual     -- re-audit with the furniture deleted, to split
                        exclusions into architecture vs contents
  remediation        -- greedy budget-constrained fix selection, scored
                        by recomputed population coverage

Cost figures are ILLUSTRATIVE order-of-magnitude estimates for demo
purposes, not quotes. They are labelled as such everywhere they surface.
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage

from schema import (ALL_PROFILES, BASELINE, WHEELCHAIR, MobilityAgentProfile,
                    IN_PER_M)
from navgrid import NavGrid
from pathing import GeoField, PenaltyField

# ---- illustrative unit costs (USD) -----------------------------------
COST_WIDEN_BASE = 1200.0      # structural opening, per aperture
COST_WIDEN_PER_IN = 180.0
COST_REGRADE_BASE = 900.0     # level change / threshold
COST_REGRADE_PER_IN = 140.0
COST_RAMP_PER_M2 = 220.0
COST_DECLUTTER = 150.0        # relocate a furniture obstruction

# ADA 405.2 caps ramps at 1:12. Building to exactly the cap is a trap:
# discretised on a 5 cm grid the running slope lands a hair over, and the
# wheelchair the ramp exists for is excluded by its own remediation. Real
# practice leaves margin, so remediation targets 1:14.
RAMP_RUN_RATIO = 14.0


# ======================================================================
# breaking point + chokepoint localisation
# ======================================================================

def probe(width_in: float, slope_tol: float, step_tol: float):
    """A throwaway profile used to sweep one axis of the envelope."""
    return MobilityAgentProfile(
        name="probe", width_in=width_in, turning_radius_in=1.0,
        max_slope_ratio=slope_tol, max_step_in=step_tol)


def breaking_point(grid: NavGrid, spawn, goals: dict,
                   ref: MobilityAgentProfile = WHEELCHAIR,
                   iters: int = 22) -> dict:
    """At what body width does this route stop working -- and why.

    Two numbers, deliberately. The width-only figure asks "if width
    were the only thing that mattered"; that is what a tape-measure
    audit effectively computes. The full-envelope figure holds a real
    wheelchair's slope and step tolerance fixed and bisects width
    against ALL constraints at once.

    Where the two disagree, the route has a barrier that no amount of
    being narrow will get you past -- and we name it, by relaxing each
    constraint in turn and seeing which one unlocks the route.
    """
    out = {}
    for name, goal in goals.items():
        sp = NavGrid.snap(grid.clearance >= 0.05, spawn)
        width_only = grid.breaking_point_m(sp, goal) * 2 * IN_PER_M

        def ok(w):
            return grid.reaches(probe(w, ref.max_slope_ratio, ref.max_step_in),
                                spawn, goal)

        if not ok(1.0):
            full, binding = 0.0, []
            # Nothing fits at any width: relax one constraint at a time
            # and see which relaxation restores the route.
            if grid.reaches(probe(1.0, 9.9, ref.max_step_in), spawn, goal):
                binding.append("slope_gradient")
            if grid.reaches(probe(1.0, ref.max_slope_ratio, 99.0), spawn, goal):
                binding.append("step_height")
            if not binding:
                binding = ["slope_gradient", "step_height"]
        else:
            lo, hi, binding = 1.0, 60.0, []
            for _ in range(iters):
                mid = (lo + hi) / 2
                if ok(mid):
                    lo = mid
                else:
                    hi = mid
            full = lo
            if width_only - full > 1.0:
                binding = ["clearance_width"]

        out[name] = {
            "width_only_in": round(width_only, 1),
            "full_envelope_in": round(full, 1),
            "binding_constraint": binding,
            "blocked_at_any_width": full <= 1.0,
            "excludes": sorted(p.name for p in ALL_PROFILES
                               if p.required_clearance_in > full),
            "reference_envelope": {
                "profile": ref.name, "max_slope_ratio": round(
                    ref.max_slope_ratio, 4), "max_step_in": ref.max_step_in},
        }
    return out


# ----------------------------------------------------------------------
# barrier localisation -- the system finds its own fix candidates
# ----------------------------------------------------------------------

def penalty_surface(grid: NavGrid, p: MobilityAgentProfile) -> np.ndarray:
    """Per-cell 0..1 measure of how badly one cell violates one envelope.

    Zero wherever the profile can stand. Solid material saturates at 1
    because its clearance is zero. Normalising each constraint to its
    own limit puts width, slope and step on one comparable scale, which
    is what lets a single search weigh "widen this door" against "ramp
    this threshold" without us telling it how.
    """
    eps = 1e-9
    c = np.clip((p.radius_m - grid.clearance) / max(p.radius_m, eps), 0, 1)
    s = np.clip((grid.slope - p.max_slope_ratio) /
                np.maximum(grid.slope, eps), 0, 1)
    t = np.clip((grid.step - p.max_step_m) /
                np.maximum(grid.step, eps), 0, 1)
    return np.maximum(np.maximum(c, s), t).astype(np.float64)


def barriers(grid: NavGrid, p: MobilityAgentProfile, spawn, goal,
             max_points: int = 6) -> list:
    """What stands between this body and that goal, in order.

    Routes the profile along the least-resistance path over its own
    penalty surface. Where free passage exists the path costs nothing
    and crosses nothing; where it does not, the path crosses the
    single cheapest set of barriers. Each contiguous violating stretch
    is one barrier, classified by which constraint dominated it.

    This is the piece that makes the remediation optimiser autonomous:
    candidate fixes are discovered here, never hand-listed.
    """
    pen = penalty_surface(grid, p)
    pf = PenaltyField(pen, grid.cell)
    sp = NavGrid.snap(grid.navigable(p), spawn)
    route = pf.route(pf.field(sp), goal)
    if len(route) < 2:
        return []

    ys = np.array([c[0] for c in route])
    xs = np.array([c[1] for c in route])
    pv = pen[ys, xs]
    hot = pv > 1e-6

    # Which constraint is responsible, per cell, for classification.
    eps = 1e-9
    cdef = np.clip((p.radius_m - grid.clearance[ys, xs]) /
                   max(p.radius_m, eps), 0, 1)
    sdef = np.clip((grid.slope[ys, xs] - p.max_slope_ratio) /
                   np.maximum(grid.slope[ys, xs], eps), 0, 1)
    tdef = np.clip((grid.step[ys, xs] - p.max_step_m) /
                   np.maximum(grid.step[ys, xs], eps), 0, 1)

    out, i, n = [], 0, len(route)
    while i < n:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and hot[j + 1]:
            j += 1
        seg = slice(i, j + 1)
        k = int(np.argmax(pv[seg])) + i
        kind = ["clearance_width", "slope_gradient", "step_height"][
            int(np.argmax([cdef[seg].max(), sdef[seg].max(), tdef[seg].max()]))]
        yx = (int(ys[k]), int(xs[k]))
        out.append({
            "cell": [yx[0], yx[1]],
            "pos": [round(yx[0] * grid.cell, 2), round(yx[1] * grid.cell, 2)],
            "kind": kind,
            "severity": round(float(pv[seg].max()), 3),
            "thickness_m": round(float(j - i + 1) * grid.cell, 2),
            "aperture_in": round(float(grid.clearance[yx] * 2 * IN_PER_M), 1),
            "step_in": round(float(grid.step[yx] * IN_PER_M), 1),
            "slope": round(float(grid.slope[yx]), 3),
            "route_frac": round(k / max(n - 1, 1), 3),
        })
        i = j + 1

    # One physical aperture can be crossed twice; keep the worst instance.
    merged = []
    for b in sorted(out, key=lambda d: -d["severity"]):
        if all((b["cell"][0] - q["cell"][0]) ** 2 +
               (b["cell"][1] - q["cell"][1]) ** 2 > (0.8 / grid.cell) ** 2
               for q in merged):
            merged.append(b)
    return merged[:max_points]


def barrier_report(grid: NavGrid, spawn, goals: dict) -> dict:
    """Every barrier standing between every profile and every goal."""
    rep = {}
    for p in ALL_PROFILES:
        per_goal = {}
        for gname, goal in goals.items():
            if grid.reaches(p, spawn, goal):
                per_goal[gname] = {"reachable": True, "barriers": []}
            else:
                per_goal[gname] = {"reachable": False,
                                   "barriers": barriers(grid, p, spawn, goal)}
        rep[p.name] = per_goal
    return rep


# ======================================================================
# detour factor
# ======================================================================

def detour(grid: NavGrid, spawn, goals: dict) -> dict:
    """Route length per profile as a multiple of the baseline route.

    A space can be fully compliant and still cost a wheelchair user
    three times the distance. That never appears on a checklist.
    """
    base_nav = grid.navigable(BASELINE)
    bgf = GeoField(base_nav, grid.cell)
    bsp = NavGrid.snap(base_nav, spawn)
    bfield = bgf.field(bsp)
    base_len = {k: bgf.length_m(bgf.route(bfield, g)) for k, g in goals.items()}

    out = {}
    for p in ALL_PROFILES:
        nav = grid.navigable(p)
        gf = GeoField(nav, grid.cell)
        sp = NavGrid.snap(nav, spawn)
        fld = gf.field(sp)
        rec = {}
        for k, g in goals.items():
            L = gf.length_m(gf.route(fld, g))
            b = base_len.get(k, 0.0)
            rec[k] = {
                "length_m": round(L, 2),
                "baseline_m": round(b, 2),
                "detour_factor": round(L / b, 2) if (L > 0 and b > 0) else None,
                "reachable": L > 0,
            }
        out[p.name] = rec
    return out


# ======================================================================
# population Monte Carlo
# ======================================================================

# Illustrative mobility-population mixture. Widths in inches, drawn to
# span ambulatory through bariatric power chairs. NOT a survey dataset --
# a plausible spread used to show the shape of the coverage curve.
_POP_MIX = [
    # (weight, label, width mean/sd, slope tol mean/sd, step tol mean/sd)
    (0.42, "ambulatory",        20.0, 2.0, 0.200, 0.040, 10.0, 3.0),
    (0.14, "cane_or_walker",    27.0, 3.0, 0.110, 0.020, 5.0, 1.5),
    (0.16, "manual_wheelchair", 27.0, 2.5, 0.095, 0.015, 1.0, 0.4),
    (0.16, "power_wheelchair",  33.0, 3.5, 0.085, 0.012, 0.6, 0.2),
    (0.07, "scooter",           31.0, 3.0, 0.100, 0.015, 1.2, 0.4),
    (0.05, "bariatric_chair",   39.0, 3.0, 0.080, 0.010, 0.5, 0.2),
]


def sample_population(n: int = 240, seed: int = 7) -> list:
    rng = np.random.default_rng(seed)
    w = np.array([m[0] for m in _POP_MIX], dtype=float)
    w /= w.sum()
    picks = rng.choice(len(_POP_MIX), size=n, p=w)
    pop = []
    for i, k in enumerate(picks):
        _, label, wm, ws, sm, ss, tm, ts = _POP_MIX[k]
        width = float(np.clip(rng.normal(wm, ws), 16.0, 48.0))
        pop.append((MobilityAgentProfile(
            name=f"{label}_{i}", width_in=width,
            turning_radius_in=float(np.clip(width * 1.85, 30.0, 72.0)),
            max_slope_ratio=float(np.clip(rng.normal(sm, ss), 0.03, 0.30)),
            max_step_in=float(np.clip(rng.normal(tm, ts), 0.2, 18.0))), label))
    return pop


def population_coverage(grid: NavGrid, spawn, goals: dict, pop=None,
                        seed: int = 7) -> dict:
    """What fraction of a mobility population can actually use the space."""
    pop = pop if pop is not None else sample_population(seed=seed)
    base = grid.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
    rows = []
    for p, label in pop:
        st = grid.analyse(p, spawn, min_island_cells=10 ** 9)
        hits = {k: bool(grid.reaches(p, spawn, g)) for k, g in goals.items()}
        rows.append({
            "label": label, "width_in": p.width_in,
            "frac": st["reachable_m2"] / base,
            "all_goals": all(hits.values()),
            "goals": hits,
        })
    n = len(rows)
    by_label = {}
    for r in rows:
        d = by_label.setdefault(r["label"], {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += int(r["all_goals"])
    for d in by_label.values():
        d["pct_full_access"] = round(100.0 * d["ok"] / max(d["n"], 1), 1)

    # Coverage as a function of body width -- where the cliff is.
    widths = np.array([r["width_in"] for r in rows])
    ok = np.array([r["all_goals"] for r in rows], dtype=float)
    frac = np.array([r["frac"] for r in rows], dtype=float)
    edges = np.arange(16, 50, 2.0)
    curve = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (widths >= a) & (widths < b)
        if m.sum() == 0:
            continue
        curve.append({
            "width_in": round(float((a + b) / 2), 1), "n": int(m.sum()),
            "pct_full_access": round(100.0 * float(ok[m].mean()), 1),
            "mean_area_frac": round(float(frac[m].mean()), 3),
        })
    return {
        "n_sampled": n,
        "pct_full_access": round(100.0 * float(ok.mean()), 1),
        "mean_area_fraction": round(float(frac.mean()), 3),
        "by_group": by_label,
        "width_curve": curve,
        "note": "Illustrative synthetic population mixture, not a survey "
                "dataset. Used to show the shape of the exclusion curve.",
    }


def elasticity(curve: list) -> dict:
    """Steepest drop in access per inch of body width -- the cliff edge."""
    if len(curve) < 2:
        return {}
    worst, wi = 0.0, None
    for a, b in zip(curve[:-1], curve[1:]):
        dw = b["width_in"] - a["width_in"]
        if dw <= 0:
            continue
        d = (a["pct_full_access"] - b["pct_full_access"]) / dw
        if d > worst:
            worst, wi = d, (a["width_in"], b["width_in"])
    return {"max_drop_pct_per_inch": round(worst, 1),
            "between_widths_in": list(wi) if wi else []}


# ======================================================================
# counterfactual: architecture vs contents
# ======================================================================

# The architecture-vs-contents counterfactual used to live here and
# depended on the 2.5D generator. The 3D pipeline computes it directly in
# viz/scene3d.py by regenerating the building with its furniture omitted,
# which is exact rather than inferred, so both functions were removed
# along with this module's last dependency on worldgen.


def _disk(shape, yx, r_cells):
    ys, xs = np.ogrid[:shape[0], :shape[1]]
    return (ys - yx[0]) ** 2 + (xs - yx[1]) ** 2 <= r_cells ** 2


def propose_fixes(grid: NavGrid, free, height, cell, spawn, goals,
                  target: MobilityAgentProfile = WHEELCHAIR,
                  furniture: np.ndarray | None = None) -> list:
    """Generate candidate remediations automatically.

    Three sources, none of them a hard-coded location:
      1. chokepoints from widest-path analysis -> widen the aperture
      2. step blobs on the exclusion boundary  -> level / ramp the change
      3. slope blobs on the exclusion boundary -> regrade the run
    """
    widest = max(p.required_clearance_in for p in ALL_PROFILES)
    furn = (furniture if furniture is not None
            else np.zeros(free.shape, dtype=bool))

    raw = []
    # -- barriers actually standing between a profile and a goal.
    for p in ALL_PROFILES:
        for goal in goals.values():
            if grid.reaches(p, spawn, goal):
                continue
            raw.extend(barriers(grid, p, spawn, goal))

    # -- over-steep runs anywhere on the floor, whether or not they
    #    currently disconnect anything: a 1:6.7 ramp is a finding even
    #    when a longer way round exists.
    slopebad = free & (grid.slope > target.max_slope_ratio) & \
        (grid.step <= target.max_step_m)
    lab, n = ndimage.label(slopebad)
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) * cell ** 2
        if area < 2.0:
            continue
        ys, xs = np.nonzero(m)
        raw.append({"cell": [int(round(ys.mean())), int(round(xs.mean()))],
                    "pos": [round(float(ys.mean()) * cell, 2),
                            round(float(xs.mean()) * cell, 2)],
                    "kind": "slope_gradient", "severity": 0.5,
                    "area_m2": area,
                    "slope": float(np.median(grid.slope[m])),
                    "aperture_in": 0.0, "step_in": 0.0})

    cands, seen = [], []
    for b in sorted(raw, key=lambda d: -d["severity"]):
        yx = tuple(b["cell"])
        if any((yx[0] - s[0]) ** 2 + (yx[1] - s[1]) ** 2 < (1.2 / cell) ** 2
               for s in seen):
            continue
        seen.append(yx)
        pos = b["pos"]

        if b["kind"] == "clearance_width":
            add_in = max(widest - b["aperture_in"], 0.0) + 4.0
            r_cells = int(round((widest / 2 + 3) / IN_PER_M / cell))
            # Widening a gap between two free-standing objects is moving
            # furniture, not construction. Same geometric fix, two orders
            # of magnitude apart in cost -- so it must be priced apart.
            near = _disk(free.shape, yx, int(round(0.8 / cell)))
            is_furniture = bool(furn[near].any()) and not bool(
                (~free & ~furn)[near].any())
            cands.append({
                "id": f"{'declutter' if is_furniture else 'widen'}"
                      f"@{pos[0]:.1f},{pos[1]:.1f}",
                "kind": "declutter" if is_furniture else "widen_aperture",
                "cell": list(yx), "pos": pos,
                "detail": (f"relocate contents to open {b['aperture_in']:.0f}in "
                           f"gap to {widest + 4:.0f}in" if is_furniture else
                           f"widen {b['aperture_in']:.0f}in aperture to "
                           f"{b['aperture_in'] + add_in:.0f}in"),
                "cost": round(COST_DECLUTTER if is_furniture else
                              COST_WIDEN_BASE + COST_WIDEN_PER_IN * add_in),
                "_apply": ("free_disk", yx, r_cells),
            })

        elif b["kind"] == "step_height":
            step_in = max(b["step_in"], 0.5)
            run_m = (step_in / IN_PER_M) * RAMP_RUN_RATIO
            cands.append({
                "id": f"level@{pos[0]:.1f},{pos[1]:.1f}",
                "kind": "level_change", "cell": list(yx), "pos": pos,
                "detail": f"ramp {step_in:.1f}in level change at "
                          f"1:{RAMP_RUN_RATIO:.0f} ({run_m:.1f}m run)",
                "cost": round(COST_REGRADE_BASE +
                              COST_REGRADE_PER_IN * step_in),
                "_apply": ("regrade", yx, int(round(run_m / cell))),
            })

        else:
            area = b.get("area_m2", 6.0)
            grade = max(b.get("slope", target.max_slope_ratio * 2), 1e-3)
            cands.append({
                "id": f"regrade@{pos[0]:.1f},{pos[1]:.1f}",
                "kind": "regrade_ramp", "cell": list(yx), "pos": pos,
                "detail": f"regrade {area:.0f}m2 run from 1:{1/grade:.0f} "
                          f"to 1:{RAMP_RUN_RATIO:.0f}",
                "cost": round(COST_RAMP_PER_M2 * area),
                "_apply": ("regrade", yx,
                           int(round(grade * np.sqrt(area) * RAMP_RUN_RATIO / cell))),
            })
    return cands


def apply_fix(free, height, cell, fix):
    """Return a new (free, height) with one remediation applied."""
    f2, h2 = free.copy(), height.copy()
    kind, yx, r = fix["_apply"]
    if kind == "free_disk":
        f2[_disk(free.shape, yx, r)] = True
    elif kind == "regrade":
        # Build an actual ramp, not a blur.
        #
        # Smoothing the height field was a tempting shortcut and a wrong
        # one: at the run lengths a 600 mm rise needs (7.2 m at 1:12) the
        # kernel smears the raised slab across everything near it,
        # destroying floor area elsewhere. The optimiser then scored that
        # destruction as an improvement, because more of the population
        # could reach the goal even though the building had been wrecked.
        #
        # A regrade lays a linear surface from the low level to the high
        # level along the local direction of ascent, over exactly the run
        # the code requires -- which is what a builder would pour.
        run_cells = max(int(r), 4)
        run_m = run_cells * cell
        region = _disk(free.shape, yx, int(run_cells / 2) + int(1.5 / cell))
        if not region.any():
            return f2, h2
        vals = h2[region]
        zlo, zhi = float(np.percentile(vals, 4)), float(np.percentile(vals, 96))
        if zhi - zlo < 0.02:
            return f2, h2

        # Direction of steepest ascent, from a smoothed copy so a single
        # noisy cell cannot set the ramp's orientation.
        sm = ndimage.gaussian_filter(h2, sigma=max(3.0, 0.25 / cell))
        gy, gx = np.gradient(sm, cell)
        uy, ux = float(gy[yx]), float(gx[yx])
        n = float(np.hypot(uy, ux))
        if n < 1e-6:
            return f2, h2
        uy, ux = uy / n, ux / n

        ys, xs = np.nonzero(region)
        # Distance along the ascent direction, in metres, centred on the
        # discontinuity so the ramp straddles it.
        t = ((ys - yx[0]) * uy + (xs - yx[1]) * ux) * cell
        z = zlo + np.clip((t + run_m / 2) / run_m, 0.0, 1.0) * (zhi - zlo)
        h2[ys, xs] = z.astype(h2.dtype)
    return f2, h2


def _score(free, height, cell, spawn, goals, pop, ceiling=None,
           surface=None, surface_order=None) -> dict:
    g = NavGrid(free, height, cell, ceiling=ceiling, surface=surface,
                surface_order=surface_order)
    base = g.analyse(BASELINE, spawn)["reachable_m2"] or 1.0
    ok, frac = 0, 0.0
    for p, _label in pop:
        st = g.analyse(p, spawn, min_island_cells=10 ** 9)
        frac += st["reachable_m2"] / base
        if all(g.reaches(p, spawn, gl) for gl in goals.values()):
            ok += 1
    n = max(len(pop), 1)
    named = {}
    for p in ALL_PROFILES:
        st = g.analyse(p, spawn, min_island_cells=10 ** 9)
        named[p.name] = {
            "pct": round(100.0 * st["reachable_m2"] / base, 1),
            "goals": sum(1 for gl in goals.values()
                         if g.reaches(p, spawn, gl))}
    return {"pct_full_access": round(100.0 * ok / n, 1),
            "mean_area_fraction": round(frac / n, 3),
            "by_profile": named}


def optimise(free, height, cell, spawn, goals, budget: float = 5000.0,
             seed: int = 7, pop_n: int = 90,
             furniture: np.ndarray | None = None,
             ceiling: np.ndarray | None = None,
             surface: np.ndarray | None = None,
             surface_order: list | None = None) -> dict:
    """Greedy budget-constrained remediation.

    Every candidate is scored by REBUILDING the world with that fix
    applied and re-running the population, so the reported coverage
    gain is measured, never estimated. Greedy re-scores after each
    pick, which captures interaction between fixes (two doors on the
    same route are not additive).
    """
    pop = sample_population(n=pop_n, seed=seed)
    grid = NavGrid(free, height, cell, ceiling=ceiling,
                   surface=surface, surface_order=surface_order)
    cands = propose_fixes(grid, free, height, cell, spawn, goals,
                          furniture=furniture)
    start = _score(free, height, cell, spawn, goals, pop, ceiling,
                   surface, surface_order)

    cur_f, cur_h = free.copy(), height.copy()
    cur = dict(start)
    chosen, spent, log = [], 0.0, []
    remaining = list(cands)
    standalone = None      # every candidate measured against the as-built
    harmed = {}            # id -> who this fix would cost, if anyone
    skipped_cost = []

    while remaining:
        scored = []
        for fx in remaining:
            if spent + fx["cost"] > budget:
                skipped_cost.append(fx["id"])
                continue
            f2, h2 = apply_fix(cur_f, cur_h, cell, fx)
            s = _score(f2, h2, cell, spawn, goals, pop, ceiling,
                       surface, surface_order)
            gain = s["pct_full_access"] - cur["pct_full_access"]
            area_gain = s["mean_area_fraction"] - cur["mean_area_fraction"]
            scored.append({"gain": gain, "area_gain": area_gain, "fx": fx,
                           "s": s, "f2": f2, "h2": h2})
        if standalone is None:
            # First pass is measured against the untouched building, so it
            # is the honest head-to-head between fixes -- including the
            # obvious one the optimiser ends up rejecting.
            standalone = sorted(
                [{"id": t["fx"]["id"], "kind": t["fx"]["kind"],
                  "detail": t["fx"]["detail"], "cost": t["fx"]["cost"],
                  "pos": t["fx"]["pos"],
                  "gain_pct": round(t["gain"], 1),
                  "area_gain": round(t["area_gain"], 3),
                  "pct_per_1k_usd": round(
                      t["gain"] / max(t["fx"]["cost"], 1) * 1000, 2)}
                 for t in scored], key=lambda d: -d["pct_per_1k_usd"])
            # Keep each candidate's measured per-profile outcome so a
            # caller can tell "this fix opens a room on its own" from
            # "this fix buys nothing unless others happen too".
            for d, t in zip(standalone, sorted(
                    scored, key=lambda q: -(q["gain"] /
                                            max(q["fx"]["cost"], 1) * 1000))):
                d["by_profile"] = t["s"].get("by_profile", {})
        # Keep only fixes that actually move the needle, then rank by
        # population unlocked per dollar. Area gain breaks ties so a fix
        # that opens floor without flipping a goal still counts.
        # Reject anything that costs an existing profile reachable floor
        # or a goal it already had. An aggregate score can be improved by
        # a change that strands somebody; that is not a fix.
        def harm(t):
            """Name what this fix would cost somebody, or None."""
            a, b = cur.get("by_profile", {}), t["s"].get("by_profile", {})
            for name, before in a.items():
                after = b.get(name, before)
                lost = before["goals"] - after["goals"]
                who = name.replace("_", " ")
                if lost > 0:
                    return (f"the {who} loses a destination it has today"
                            if lost == 1 else
                            f"the {who} loses {lost} destinations it has today")
                if after["pct"] < before["pct"] - 0.25:
                    return (f"the {who} loses "
                            f"{before['pct'] - after['pct']:.1f} points of "
                            f"reachable floor")
            return None

        for t in scored:
            h = harm(t)
            if h:
                harmed.setdefault(t["fx"]["id"], h)

        useful = [t for t in scored
                  if (t["gain"] > 0 or t["area_gain"] > 0.002) and not harm(t)]
        if not useful:
            break
        useful.sort(key=lambda t: -((t["gain"] + 12.0 * t["area_gain"]) /
                                    max(t["fx"]["cost"], 1)))
        t = useful[0]
        fx, s = t["fx"], t["s"]
        cur_f, cur_h, cur = t["f2"], t["h2"], s
        spent += fx["cost"]
        chosen.append(fx["id"])
        log.append({
            "id": fx["id"], "kind": fx["kind"], "pos": fx["pos"],
            "detail": fx["detail"], "cost": fx["cost"],
            "access_pct_after": s["pct_full_access"],
            "gain_pct": round(t["gain"], 1),
            "pct_per_1k_usd": round(t["gain"] / max(fx["cost"], 1) * 1000, 2),
        })
        remaining = [r for r in remaining if r["id"] != fx["id"]]

    rejected = [dict(d, harm=harmed.get(d["id"]))
                for d in (standalone or []) if d["id"] not in chosen]
    return {
        "budget_usd": budget,
        "spent_usd": round(spent),
        "unspent_usd": round(budget - spent),
        "before": start, "after": cur,
        "baseline_by_profile": start.get("by_profile", {}),
        "coverage_gain_pct": round(cur["pct_full_access"] -
                                   start["pct_full_access"], 1),
        "candidates_considered": len(cands),
        "candidate_menu": [{k: v for k, v in c.items() if not k.startswith("_")}
                           for c in cands],
        "standalone_scores": standalone or [],
        "rejected": rejected,
        "chosen": log,
        "population_n": pop_n,
        "note": "Costs are illustrative order-of-magnitude figures for demo "
                "purposes, not quotes. Coverage gains are MEASURED by "
                "re-running the full population audit with each fix "
                "applied, never estimated.",
        "_final_world": (cur_f, cur_h),
    }
