"""Access-Twin consensus auditor.

Three independent layers look at the same space:

  Layer 1  geometric   -- ADA clearance / slope / step / turning-space
                          rules, evaluated on the circulation network.
  Layer 2  behavioural -- hesitation-weighted telemetry.
  Layer 3  embodied    -- per-profile navigable mask + connected
                          components. If a constrained profile's
                          reachable set fails to cover ground the
                          baseline reaches, that is an exclusion. The
                          erosion IS the check.

A finding confirmed by more than one layer is high-confidence.
Disagreement is not hidden -- a geometric violation with no embodied
confirmation is a rule that fires without excluding anybody, and an
embodied exclusion with no geometric violation is the interesting
case: a space that passes every check and still locks people out.

Run:  python3 core/auditor.py --seed 7
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schema import (ALL_PROFILES, BASELINE, ADA_CITATIONS, AuditResult,
                    MobilityAgentProfile, Severity, ViolationNode,
                    ViolationType, IN_PER_M)
from navgrid import NavGrid
from worldgen import build
from pathing import GeoField
import telemetry as tele

# A finding must occupy at least this much of the circulation network
# before it is reported. Below this it is quantisation noise on the
# 5cm lattice, not a feature of the building.
MIN_RIDGE_CELLS = 3
MIN_AREA_CELLS = 60
# Radius within which a geometric finding counts as co-located with an
# actual exclusion boundary or a hesitation hotspot.
CONFIRM_RADIUS_M = 0.75
HESITATION_CONFIRM = 0.35


def _quant_id(prefix: str, y: int, x: int, cell: float) -> str:
    """Location-derived segment id, quantised to 0.5m.

    Deliberately NOT a counter: the same doorway must produce the same
    segment_id for every profile that fails at it, otherwise consensus
    and ground-truth matching cannot see that they are one defect.
    """
    return f"{prefix}_{int(y * cell * 2)}_{int(x * cell * 2)}"


def _severity(overshoot: float, hesitation: float) -> Severity:
    """Severity scales with how far past the limit the geometry is.

    Behavioural signal can escalate but never de-escalate: a rule
    breach nobody was observed struggling at is still a rule breach.
    """
    if overshoot < 0.10:
        s = Severity.LOW
    elif overshoot < 0.30:
        s = Severity.MEDIUM
    elif overshoot < 0.60:
        s = Severity.HIGH
    else:
        s = Severity.CRITICAL
    if hesitation > 0.6:
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH,
                 Severity.CRITICAL]
        s = order[min(order.index(s) + 1, 3)]
    return s


class Auditor:
    def __init__(self, seed: int = 7, world=None):
        self.seed = seed
        f, h, cell, spawn, goals, gt = world if world else build(seed)
        self.free, self.height, self.cell = f, h, cell
        self.spawn, self.goals, self.gt = spawn, goals, gt
        self.grid = NavGrid(f, h, cell)

        self.base = self.grid.analyse(BASELINE, spawn)
        self.base_reach = self.base["reachable"]

        # The circulation network: ridge of the clearance field inside
        # the walkable area. clearance*2 along this ridge is the local
        # corridor width -- the number a tape measure would give you.
        cl = self.grid.clearance
        self.ridge = (cl >= ndimage.maximum_filter(cl, size=3) - 1e-9) & \
                     self.base_reach
        _, self.n_segments = ndimage.label(self.ridge, structure=np.ones((3, 3)))

        self.tracks = {p.name: tele.simulate(self.grid, p, spawn, goals, seed)
                       for p in ALL_PROFILES}
        self.hes = tele.raster(self.grid, self.tracks)

        self._per_profile = {}

    # ---------- per-profile embodied state ----------

    def profile_state(self, p: MobilityAgentProfile) -> dict:
        if p.name in self._per_profile:
            return self._per_profile[p.name]
        st = self.grid.analyse(p, self.spawn)
        # Ground the baseline reaches but this profile does not. This is
        # the exclusion set, and it is the ground truth for Layer 3.
        st["excluded"] = self.base_reach & ~st["reachable"]
        st["excl_dist"] = ndimage.distance_transform_edt(
            ~st["excluded"], sampling=self.cell) if st["excluded"].any() \
            else np.full(self.free.shape, np.inf)
        self._per_profile[p.name] = st
        return st

    # ---------- layer plumbing ----------

    def _confirm(self, p, yx) -> tuple[list[str], float]:
        """Which layers corroborate a finding at this cell."""
        st = self.profile_state(p)
        layers = ["geometric"]
        hes = float(self.hes[yx])
        if hes >= HESITATION_CONFIRM:
            layers.append("behavioral")
        if float(st["excl_dist"][yx]) <= CONFIRM_RADIUS_M:
            layers.append("embodied")
        return layers, hes

    def _node(self, prefix, vtype, p, yx, measured, threshold, overshoot):
        layers, hes = self._confirm(p, yx)
        return ViolationNode(
            segment_id=_quant_id(prefix, yx[0], yx[1], self.cell),
            position=(round(yx[0] * self.cell, 2), round(yx[1] * self.cell, 2),
                      round(float(self.height[yx]), 2)),
            violation_type=vtype, agent=p.name,
            measured_value=measured, threshold=threshold,
            severity=_severity(overshoot, hes),
            hesitation_context=hes, confirmed_by=layers,
            ada_citation=ADA_CITATIONS[vtype])

    # ---------- Layer 1: geometric ----------

    def _clearance(self, p) -> list[ViolationNode]:
        need_m = p.required_clearance_in / IN_PER_M
        width = self.grid.clearance * 2.0            # corridor width, metres
        bad = self.ridge & (width < need_m)
        lab, n = ndimage.label(bad, structure=np.ones((3, 3)))
        out = []
        for i in range(1, n + 1):
            m = lab == i
            if int(m.sum()) < MIN_RIDGE_CELLS:
                continue
            w = np.where(m, width, np.inf)
            yx = np.unravel_index(int(np.argmin(w)), w.shape)
            meas_in = float(width[yx] * IN_PER_M)
            out.append(self._node(
                "clr", ViolationType.CLEARANCE, p, yx, meas_in,
                p.required_clearance_in,
                (p.required_clearance_in - meas_in) / p.required_clearance_in))
        return out

    def _slope(self, p) -> list[ViolationNode]:
        bad = self.free & (self.grid.slope > p.max_slope_ratio) & \
            (self.grid.step <= p.max_step_m)
        lab, n = ndimage.label(bad)
        out = []
        for i in range(1, n + 1):
            m = lab == i
            if int(m.sum()) < MIN_AREA_CELLS:
                continue
            vals = self.grid.slope[m]
            # Report the RUNNING slope, not the worst cell. A ramp's max
            # gradient sits on its side lip, which would both overstate
            # the grade and locate the finding in a corner instead of on
            # the ramp. Median over the region is the number a surveyor's
            # level would read, and the centroid is where they'd stand.
            meas = float(np.median(vals))
            ys, xs = np.nonzero(m)
            cy, cx = ys.mean(), xs.mean()
            k = int(np.argmin((ys - cy) ** 2 + (xs - cx) ** 2))
            yx = (int(ys[k]), int(xs[k]))
            out.append(self._node(
                "slp", ViolationType.SLOPE, p, yx, meas, p.max_slope_ratio,
                (meas - p.max_slope_ratio) / p.max_slope_ratio))
        return out

    def _step(self, p) -> list[ViolationNode]:
        bad = self.free & (self.grid.step > p.max_step_m)
        lab, n = ndimage.label(bad)
        out = []
        for i in range(1, n + 1):
            m = lab == i
            if int(m.sum()) < MIN_AREA_CELLS // 2:
                continue
            s = np.where(m, self.grid.step, -np.inf)
            yx = np.unravel_index(int(np.argmax(s)), s.shape)
            meas_in = float(self.grid.step[yx] * IN_PER_M)
            out.append(self._node(
                "stp", ViolationType.STEP_HEIGHT, p, yx, meas_in, p.max_step_in,
                (meas_in - p.max_step_in) / max(p.max_step_in, 1e-6)))
        return out

    def _turning(self, p) -> list[ViolationNode]:
        """ADA 304.3.1: a turn needs a 60in-diameter clear circle.

        Only meaningful where the route actually turns, so we test the
        profile's own geodesic route rather than the whole floor.
        """
        st = self.profile_state(p)
        nav = st["nav_mask"]
        gf = GeoField(nav, self.cell)
        sp = NavGrid.snap(nav, self.spawn)
        dist = gf.field(sp)
        need_m = (p.turning_radius_in / 2.0) / IN_PER_M   # radius of circle
        out, seen = [], set()
        for goal in self.goals.values():
            route = gf.route(dist, goal)
            if len(route) < 3:
                continue
            step = max(1, int(round(0.5 / self.cell)))
            pts = route[::step]
            for i in range(1, len(pts) - 1):
                a = np.array(pts[i]) - np.array(pts[i - 1])
                b = np.array(pts[i + 1]) - np.array(pts[i])
                na, nb = np.linalg.norm(a), np.linalg.norm(b)
                if na == 0 or nb == 0:
                    continue
                ang = np.degrees(np.arccos(
                    np.clip(float(a @ b) / (na * nb), -1, 1)))
                if ang < 45.0:
                    continue
                yx = pts[i]
                have = float(self.grid.clearance[yx])
                if have >= need_m:
                    continue
                key = _quant_id("trn", yx[0], yx[1], self.cell)
                if key in seen:
                    continue
                seen.add(key)
                out.append(self._node(
                    "trn", ViolationType.TURNING_RADIUS, p, yx,
                    have * 2 * IN_PER_M, p.turning_radius_in,
                    (need_m - have) / need_m))
        return out

    # ---------- Layer 3: embodied ----------

    def _unreachable(self, p) -> list[ViolationNode]:
        st = self.profile_state(p)
        out = []
        for isl in st["islands"]:
            yx = (int(isl["centroid"][0]), int(isl["centroid"][1]))
            hes = float(self.hes[yx])
            layers = ["embodied"]
            if hes >= HESITATION_CONFIRM:
                layers.append("behavioral")
            # Does any Layer-1 rule fire INSIDE this island? If not, the
            # region is geometrically flawless and still unreachable --
            # the headline finding.
            area = isl["area_m2"]
            sev = Severity.CRITICAL if area >= 20 else Severity.HIGH
            out.append(ViolationNode(
                segment_id=_quant_id("unr", yx[0], yx[1], self.cell),
                position=(round(yx[0] * self.cell, 2),
                          round(yx[1] * self.cell, 2),
                          round(float(self.height[yx]), 2)),
                violation_type=ViolationType.UNREACHABLE, agent=p.name,
                measured_value=area, threshold=0.0, severity=sev,
                hesitation_context=hes, confirmed_by=layers,
                ada_citation=ADA_CITATIONS[ViolationType.UNREACHABLE]))
        return out

    # ---------- recall against planted ground truth ----------

    def score_recall(self, violations) -> dict:
        """Because we generated the space, we know the answer.

        No dataset-based auditor can report this number.
        """
        tol = 1.6  # metres
        geo = [v for v in violations
               if v.violation_type != ViolationType.UNREACHABLE]
        matched, per_defect = set(), []
        for d in self.gt:
            gx, gy = d["pos"]
            hits = [v for v in geo
                    if v.violation_type.value == d["type"]
                    and abs(v.position[0] - gx) <= tol
                    and abs(v.position[1] - gy) <= tol]
            for v in hits:
                matched.add(id(v))
            per_defect.append({
                "id": d["id"], "type": d["type"], "pos": d["pos"],
                "detected": bool(hits),
                "detected_for": sorted({v.agent for v in hits}),
                "expected_to_block": d.get("blocks", []),
            })
        emergent = [v for v in geo if id(v) not in matched]
        # Emergent findings are grouped by location: one pinch found for
        # three profiles is one emergent feature, not three.
        emergent_segs = {}
        for v in emergent:
            emergent_segs.setdefault(v.segment_id, {
                "segment_id": v.segment_id, "type": v.violation_type.value,
                "position": v.position, "measured": round(v.measured_value, 1),
                "agents": []})
            emergent_segs[v.segment_id]["agents"].append(v.agent)
        found = sum(1 for d in per_defect if d["detected"])
        return {
            "planted": len(self.gt), "detected": found,
            "recall": round(found / max(len(self.gt), 1), 3),
            "geometric_findings": len(geo),
            "matched_to_ground_truth": len(matched),
            "precision_vs_planted": round(len(matched) / max(len(geo), 1), 3),
            "emergent_features": len(emergent_segs),
            "emergent": sorted(emergent_segs.values(),
                               key=lambda d: -len(d["agents"]))[:12],
            "per_defect": per_defect,
        }

    # ---------- top level ----------

    def run(self) -> AuditResult:
        res = AuditResult(seed=self.seed)
        res.segments_checked = int(self.n_segments)
        res.agents_evaluated = [p.name for p in ALL_PROFILES]
        for p in ALL_PROFILES:
            for fn in (self._clearance, self._slope, self._step,
                       self._turning, self._unreachable):
                res.violations.extend(fn(p))

        base_area = self.base["reachable_m2"]
        for p in ALL_PROFILES:
            st = self.profile_state(p)
            res.coverage[p.name] = {
                "reachable_m2": st["reachable_m2"],
                "pct_of_baseline": round(
                    100.0 * st["reachable_m2"] / max(base_area, 1e-9), 1),
                "excluded_m2": round(
                    float(st["excluded"].sum()) * self.cell ** 2, 1),
                "goals": {k: bool(self.grid.reaches(p, self.spawn, g))
                          for k, g in self.goals.items()},
            }
            res.islands[p.name] = st["islands"]

        res.ground_truth = {"defects": self.gt}
        res.recall = self.score_recall(res.violations)

        order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2,
                 Severity.LOW: 3}
        res.violations.sort(key=lambda v: (order[v.severity], -v.consensus,
                                           v.agent))
        return res


def main():
    ap = argparse.ArgumentParser(description="Access-Twin consensus auditor")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    t0 = time.time()
    a = Auditor(seed=args.seed)
    res = a.run()
    dt = time.time() - t0
    js = res.to_json()
    js["runtime_s"] = round(dt, 3)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = args.out or os.path.join(root, "out", "audit_output.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(js, fh, indent=2)

    print(f"\nAccess-Twin audit  seed={args.seed}  {dt:.2f}s")
    print(f"circulation segments checked : {js['segments_checked']}")
    print(f"violations                   : {js['violation_count']}")
    print("\nprofile                     reach_m2   %base  excl_m2  goals")
    for k, v in js["coverage"].items():
        g = ",".join(n for n, ok in v["goals"].items() if ok) or "-none-"
        print(f"{k:26s}{v['reachable_m2']:10.1f}{v['pct_of_baseline']:8.1f}"
              f"{v['excluded_m2']:9.1f}  {g}")

    r = js["recall"]
    print(f"\nground truth: planted {r['planted']}, detected {r['detected']} "
          f"(recall {r['recall']:.0%}), "
          f"{r['emergent_features']} emergent features not planted")
    for d in r["per_defect"]:
        mark = "OK " if d["detected"] else "MISS"
        print(f"  [{mark}] {d['id']:18s} {d['type']:16s} "
              f"-> {', '.join(d['detected_for']) or '-'}")

    print("\ntop findings by severity + consensus")
    for v in js["violations"][:10]:
        print(f"  {v['severity']:8s} c{v['consensus']} {v['agent']:24s} "
              f"{v['type']:18s} @{v['position'][0]:5.1f},{v['position'][1]:5.1f} "
              f"meas={v['measured']:6.1f} thr={v['threshold']:6.1f}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
