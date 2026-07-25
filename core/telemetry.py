"""Layer 2 -- synthetic behavioural telemetry.

Each profile walks its actual geodesic route and reports a per-sample
hesitation score derived from how much margin it has left against its
own physics envelope. Where a goal is unreachable the agent does what a
real person does: routes as close as it can get, dwells at the
obstruction, then backtracks. That produces a hesitation hotspot
sitting exactly on the feature that excluded it.

The point of this layer is not the trajectory, it is the raster: a
smoothed 2D hesitation field the auditor samples to decide whether a
geometric finding is behaviourally corroborated. The schema
(TelemetryPoint) is shaped to accept real dwell/backtrack signal from
captured sessions -- swapping synthetic for recorded changes nothing
downstream.
"""
from __future__ import annotations
import numpy as np
from scipy import ndimage

from schema import TelemetryPoint, MobilityAgentProfile
from navgrid import NavGrid
from pathing import GeoField

BASE_SPEED_MPS = 1.2


def _margins(grid: NavGrid, p: MobilityAgentProfile, yx):
    """How close this profile is to its own limits at one cell, 0..1 each.

    1.0 == exactly at the limit. Values are clipped, so a cell the agent
    cannot occupy at all saturates rather than exploding.
    """
    y, x = yx
    clear = grid.clearance[y, x] / max(p.radius_m, 1e-6)
    slope = grid.slope[y, x] / max(p.max_slope_ratio, 1e-6)
    step = grid.step[y, x] / max(p.max_step_m, 1e-6)
    # Clearance stress rises as available room approaches the body radius.
    stress_clear = float(np.clip(2.0 - clear, 0.0, 1.0))
    return (stress_clear, float(np.clip(slope, 0.0, 1.0)),
            float(np.clip(step, 0.0, 1.0)))


def simulate(grid: NavGrid, p: MobilityAgentProfile, spawn, goals: dict,
             seed: int = 7) -> list[TelemetryPoint]:
    """Walk every goal, returning one trajectory list for this profile."""
    rng = np.random.default_rng(seed + abs(hash(p.name)) % 10_000)
    nav = grid.navigable(p)
    gf = GeoField(nav, grid.cell)
    sp = NavGrid.snap(nav, spawn)
    dist = gf.field(sp)

    pts: list[TelemetryPoint] = []
    t = 0.0
    for gname, goal in goals.items():
        reached = bool(np.isfinite(dist[goal]))
        if reached:
            target = goal
        else:
            # Closest cell to the goal this profile can actually stand on.
            # This is the approach point: where the person gives up.
            finite = np.isfinite(dist)
            if not finite.any():
                continue
            ys, xs = np.nonzero(finite)
            d2 = (ys - goal[0]) ** 2 + (xs - goal[1]) ** 2
            k = int(np.argmin(d2))
            target = (int(ys[k]), int(xs[k]))

        route = gf.route(dist, target)
        if len(route) < 2:
            continue

        # Subsample: one telemetry sample every ~25cm of travel.
        stride = max(1, int(round(0.25 / grid.cell)))
        samples = route[::stride]
        if samples[-1] != route[-1]:
            samples.append(route[-1])

        for i, yx in enumerate(samples):
            sc, ss, st = _margins(grid, p, yx)
            hes = float(np.clip(
                0.55 * sc + 0.3 * ss + 0.5 * st + rng.normal(0, 0.02),
                0.0, 1.0))
            if i + 1 < len(samples):
                dy = samples[i + 1][0] - yx[0]
                dx = samples[i + 1][1] - yx[1]
                heading = float(np.degrees(np.arctan2(dy, dx)) % 360)
            else:
                heading = pts[-1].heading_deg if pts else 0.0
            vel = float(BASE_SPEED_MPS * (1.0 - 0.8 * hes))
            pts.append(TelemetryPoint(
                t=round(t, 2), x=round(yx[0] * grid.cell, 3),
                y=round(yx[1] * grid.cell, 3),
                z=round(float(grid.height[yx]), 3),
                heading_deg=round(heading, 1),
                velocity_mps=round(vel, 3),
                hesitation_score=round(hes, 3)))
            t += 0.25 / max(vel, 0.05)

        if not reached:
            # Dwell-and-backtrack at the obstruction. This is the signal a
            # real capture would show: velocity collapses, the agent holds
            # position, then reverses along its own path.
            end = samples[-1]
            for k in range(6):
                hes = float(np.clip(0.82 + 0.03 * k + rng.normal(0, 0.02),
                                    0.0, 1.0))
                pts.append(TelemetryPoint(
                    t=round(t, 2), x=round(end[0] * grid.cell, 3),
                    y=round(end[1] * grid.cell, 3),
                    z=round(float(grid.height[end]), 3),
                    heading_deg=pts[-1].heading_deg if pts else 0.0,
                    velocity_mps=0.0, hesitation_score=round(hes, 3),
                    interaction_trigger="dwell_blocked" if k < 5 else "backtrack"))
                t += 0.6
            for yx in samples[-6:][::-1]:
                pts.append(TelemetryPoint(
                    t=round(t, 2), x=round(yx[0] * grid.cell, 3),
                    y=round(yx[1] * grid.cell, 3),
                    z=round(float(grid.height[yx]), 3),
                    heading_deg=(pts[-1].heading_deg + 180) % 360,
                    velocity_mps=0.45, hesitation_score=0.6,
                    interaction_trigger="backtrack"))
                t += 0.55
    return pts


def raster(grid: NavGrid, tracks: dict, sigma_m: float = 0.35) -> np.ndarray:
    """Accumulate all trajectories into one smoothed hesitation field.

    This is what the auditor samples. Smoothing matters: a violation is
    corroborated if hesitation is elevated NEAR it, not exactly on the
    one cell an agent happened to occupy.
    """
    acc = np.zeros(grid.free.shape, dtype=np.float32)
    for pts in tracks.values():
        for pt in pts:
            iy = int(round(pt.x / grid.cell))
            ix = int(round(pt.y / grid.cell))
            if 0 <= iy < acc.shape[0] and 0 <= ix < acc.shape[1]:
                acc[iy, ix] = max(acc[iy, ix], pt.hesitation_score)
    sm = ndimage.gaussian_filter(acc, sigma=sigma_m / grid.cell)
    peak = float(sm.max())
    return sm / peak if peak > 0 else sm


if __name__ == "__main__":
    from worldgen import build
    from schema import ALL_PROFILES
    f, h, cell, sp, goals, gt = build(7)
    g = NavGrid(f, h, cell)
    tracks = {p.name: simulate(g, p, sp, goals) for p in ALL_PROFILES}
    for k, v in tracks.items():
        blocked = sum(1 for q in v if q.interaction_trigger)
        print(f"{k:26s} {len(v):5d} samples  "
              f"peak_hesitation={max(q.hesitation_score for q in v):.2f}  "
              f"blocked_events={blocked}")
    r = raster(g, tracks)
    print("hesitation raster", r.shape, "max", round(float(r.max()), 3))
