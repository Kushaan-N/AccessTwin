"""Access-Twin procedural world generator.

Seeded. Produces a cluttered hall plus a side room whose interior is
geometrically flawless but whose only two entrances each fail for a
different reason -- the reachability-island headline finding.
Returns a ground-truth manifest of every planted defect so detection
recall can be scored.
"""
from __future__ import annotations
import numpy as np

CELL = 0.05
W, H = 30.0, 20.0


def build(seed: int = 7):
    """The world as built: shell, planted defects, and contents."""
    return _build(seed, with_clutter=True)


def build_empty(seed: int = 7):
    """The identical building with the free-standing contents omitted.

    Used for the architecture-vs-contents counterfactual. Because it
    replays the same construction, differencing the two free masks
    gives the exact furniture footprint -- no guessing which
    obstructions are walls. The clutter loop is the only consumer of
    the RNG and nothing after it draws, so skipping it leaves every
    other feature bit-identical.
    """
    return _build(seed, with_clutter=False)


def _build(seed: int = 7, with_clutter: bool = True):
    rng = np.random.default_rng(seed)
    nx, ny = int(W / CELL), int(H / CELL)
    free = np.ones((nx, ny), dtype=bool)
    height = np.zeros((nx, ny), dtype=np.float32)
    gt = []

    def c(v):
        return int(round(v / CELL))

    def block(x0, y0, x1, y1):
        free[c(x0):c(x1), c(y0):c(y1)] = False

    def open_(x0, y0, x1, y1):
        free[c(x0):c(x1), c(y0):c(y1)] = True

    def ramp(x0, y0, x1, y1, rise):
        xs = np.linspace(0, rise, c(x1) - c(x0))
        height[c(x0):c(x1), c(y0):c(y1)] = xs[:, None]
        height[c(x1):, c(y0):c(y1)] = rise

    def curb(x0, y0, x1, y1, h):
        height[c(x0):c(x1), c(y0):c(y1)] = h

    # ---- shell
    block(0, 0, W, 0.2); block(0, H - 0.2, W, H)
    block(0, 0, 0.2, H); block(W - 0.2, 0, W, H)

    # ---- clutter FIRST so planted defects are never overwritten
    placed = 0
    while placed < 55 and with_clutter:
        cx = rng.uniform(2.0, 18.0); cy = rng.uniform(2.0, H - 2.0)
        r = rng.uniform(0.20, 0.45)
        # Keep clutter off walls so it never seals a pocket for the
        # baseline profile. A baseline island means the GENERATOR is
        # wrong, not the analyser.
        if cx - r < 1.4 or cx + r > 18.6 or cy - r < 1.4 or cy + r > H - 1.4:
            continue
        block(cx - r, cy - r, cx + r, cy + r)
        placed += 1

    # ---- partition, 0.86m squeeze (34in): blocks cane only
    block(8.0, 0.2, 8.4, 9.0)
    block(8.0, 9.86, 8.4, H - 0.2)
    open_(7.6, 9.0, 8.8, 9.86)
    gt.append(dict(id="squeeze_34in", type="clearance_width", pos=[8.2, 9.43],
                   measured_in=34.0, blocks=["vision_impaired_cane"]))

    # ---- ramp at 15% grade: blocks wheelchair + robot
    open_(12.0, 2.0, 16.0, 5.0)
    ramp(12.0, 2.0, 16.0, 5.0, 0.60)
    gt.append(dict(id="ramp_15pct", type="slope_gradient", pos=[14.0, 3.5],
                   measured=0.15,
                   blocks=["wheelchair", "sidewalk_delivery_robot"]))

    # ---- curb 0.20m: blocks wheelchair + robot
    open_(12.0, 14.0, 16.0, 17.0)
    curb(13.9, 14.0, 16.0, 17.0, 0.20)
    gt.append(dict(id="curb_8in", type="step_height", pos=[13.9, 15.5],
                   measured_in=7.9,
                   blocks=["wheelchair", "sidewalk_delivery_robot"]))

    # ---- side room: flawless interior, both entrances fail differently
    block(20.0, 4.0, 20.3, 16.0)
    block(20.0, 4.0, W - 0.2, 4.3)
    block(20.0, 15.7, W - 0.2, 16.0)
    open_(20.3, 4.3, W - 0.2, 15.7)             # scrub interior clean
    height[c(20.3):, c(4.3):c(15.7)] = 0.0

    # entrance A: 0.71m pinch (28in)
    open_(20.0, 9.6, 20.3, 10.31)
    gt.append(dict(id="door_28in", type="clearance_width", pos=[20.15, 9.95],
                   measured_in=28.0,
                   blocks=["wheelchair", "vision_impaired_cane"]))
    # entrance B: wide, but a 0.20m threshold step
    open_(20.0, 12.5, 20.3, 13.7)
    curb(20.0, 12.5, 20.35, 13.7, 0.20)
    gt.append(dict(id="thresh_step_8in", type="step_height", pos=[20.15, 13.1],
                   measured_in=7.9,
                   blocks=["wheelchair", "sidewalk_delivery_robot"]))

    spawn = (c(2.0), c(2.0))
    goals = {"side_room": (c(26.0), c(10.0)), "far_hall": (c(18.0), c(18.0))}
    return free, height, CELL, spawn, goals, gt


if __name__ == "__main__":
    f, h, cell, sp, g, gt = build()
    print("grid", f.shape, "free frac", round(f.mean(), 3), "defects", len(gt))
