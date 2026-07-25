"""Access-Twin navigability grid.

2.5D reimplementation of the standard navmesh pipeline: build a
heightfield, erode the walkable area by agent radius, mask by max climb
and max slope, extract connected components. Same algorithm as
Recast/Detour; ~2ms per profile instead of ~10s per Unity bake.
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage
from schema import MobilityAgentProfile


class NavGrid:
    def __init__(self, free: np.ndarray, height: np.ndarray, cell: float,
                 ceiling: np.ndarray | None = None):
        """free: bool, True = unobstructed. height: metres. cell: m/cell.

        ceiling: underside of anything overhead, in metres. Optional --
        omit it and head clearance is simply not evaluated, which is the
        correct behaviour for a 2.5D world that has no overhead data.
        With a real 3D scene it lets a profile be excluded by a low
        bulkhead it would physically walk into, which is invisible to a
        plan-view analysis.
        """
        self.free = free
        self.height = height
        self.cell = cell
        self.ceiling = ceiling
        self.headroom = (None if ceiling is None
                         else (ceiling - height).astype(np.float32))

        # Distance from every free cell to the nearest obstruction.
        # clearance*2 == local corridor width. This IS the clearance
        # check, evaluated everywhere at once.
        self.clearance = ndimage.distance_transform_edt(free, sampling=cell)

        gy, gx = np.gradient(height, cell)
        self.slope = np.hypot(gx, gy)

        # Max height discontinuity to any 4-neighbour == local step height.
        h = height
        s = np.zeros_like(h)
        s[1:, :] = np.maximum(s[1:, :], np.abs(h[1:, :] - h[:-1, :]))
        s[:-1, :] = np.maximum(s[:-1, :], np.abs(h[:-1, :] - h[1:, :]))
        s[:, 1:] = np.maximum(s[:, 1:], np.abs(h[:, 1:] - h[:, :-1]))
        s[:, :-1] = np.maximum(s[:, :-1], np.abs(h[:, :-1] - h[:, 1:]))
        self.step = s

        # A vertical discontinuity is a STEP, not a slope. Without this a
        # 20cm curb reads as gradient 4.0 and isolates the platform even
        # for profiles that can trivially step onto it. Recast separates
        # these via spans + walkableClimb; on a heightfield we must do it
        # explicitly. discont = largest per-cell rise a real ramp could
        # produce at this resolution. THIS LINE IS LOad-BEARING.
        discont = 0.6 * cell
        self.slope = np.where(s > discont, 0.0, self.slope)

    def navigable(self, p: MobilityAgentProfile) -> np.ndarray:
        """Per-profile walkable mask: radius erosion + slope + step + headroom."""
        mask = (
            (self.clearance >= p.radius_m)
            & (self.slope <= p.max_slope_ratio)
            & (self.step <= p.max_step_m)
        )
        if self.headroom is not None and p.head_clearance_in:
            mask = mask & (self.headroom >= p.head_clearance_in / 39.3701)
        return mask

    @staticmethod
    def snap(mask: np.ndarray, pt: tuple[int, int]) -> tuple[int, int]:
        """Nearest navigable cell. habitat-sim calls this snap_point.
        WITHOUT THIS a spawn 30cm from a wall lands in no component and
        wide profiles report zero reachable area. The symptom looks like
        a logic bug in the analyser. Do not remove."""
        if mask[pt]:
            return pt
        if not mask.any():
            return pt
        idx = ndimage.distance_transform_edt(
            ~mask, return_distances=False, return_indices=True)
        return (int(idx[0][pt]), int(idx[1][pt]))

    def analyse(self, p: MobilityAgentProfile, spawn: tuple[int, int],
                min_island_cells: int = 400) -> dict:
        nav = self.navigable(p)
        sp = self.snap(nav, spawn)
        lab, n = ndimage.label(nav)
        home = int(lab[sp])
        reachable = (lab == home) if home > 0 else np.zeros_like(nav)
        islands = []
        for i in range(1, n + 1):
            if i == home:
                continue
            cells = int((lab == i).sum())
            if cells < min_island_cells:
                continue
            ys, xs = np.nonzero(lab == i)
            islands.append({
                "area_m2": round(cells * self.cell ** 2, 1),
                "centroid": [int(ys.mean()), int(xs.mean())],
            })
        islands.sort(key=lambda d: -d["area_m2"])
        return {
            "profile": p.name,
            "nav_mask": nav,
            "reachable": reachable,
            "labels": lab,
            "reachable_m2": round(float(reachable.sum()) * self.cell ** 2, 1),
            "component_count": n,
            "islands": islands,
            "island_m2": round(sum(d["area_m2"] for d in islands), 1),
            "spawn_snapped": sp,
        }

    def reaches(self, p: MobilityAgentProfile, spawn, goal) -> bool:
        nav = self.navigable(p)
        sp = self.snap(nav, spawn)
        lab, _ = ndimage.label(nav)
        return bool(lab[sp] > 0 and lab[sp] == lab[goal])

    def breaking_point_m(self, spawn, goal, lo=0.05, hi=1.2, iters=24) -> float:
        """Largest agent radius that still connects spawn to goal."""
        lab0, _ = ndimage.label(self.clearance >= lo)
        if not (lab0[spawn] > 0 and lab0[spawn] == lab0[goal]):
            return 0.0
        for _ in range(iters):
            mid = (lo + hi) / 2
            lab, _ = ndimage.label(self.clearance >= mid)
            sp = lab[spawn]
            if sp > 0 and sp == lab[goal]:
                lo = mid
            else:
                hi = mid
        return lo
