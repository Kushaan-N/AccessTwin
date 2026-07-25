"""Access-Twin 3D world: a generated civic building, and its voxelisation.

This module is the source of truth for the whole project. Everything
downstream -- the navigability grid, the barrier finder, the optimiser,
the 3D viewer -- consumes what is built here.

The building is described as typed solids in metres. Nothing is a
sprite or a tile: a wall is a box, a ramp is a box with a sloped top, a
stair is four boxes. That matters because the analysis does NOT read
the solids. It reads a voxelisation of them:

    solids  ->  floor_z (walkable surface height)
                free    (is the body band clear here)
                ceiling_z (underside of anything overhead)

which is the same heightfield Recast/Detour builds from a Unity scene,
and the same one habitat-sim builds from a scanned mesh. Feed this
pipeline a real captured building instead of a generated one and
nothing downstream changes.

Because we author the building, we also emit a ground-truth manifest of
every access defect planted in it, so detection can be scored against a
known answer.

Run:  python3 core/world3d.py
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

CELL = 0.05                  # 5 cm voxel, same as a Recast cell size
W, H = 32.0, 22.0            # building envelope, metres
WALL_H = 2.9
CEIL_Z = 3.0

# A body occupies this band above the floor it stands on. Anything
# intruding into it is an obstruction; anything above it is overhead.
BODY_BAND = (0.05, 1.20)

# ---- ADA-derived reference dimensions used when planting defects ----
IN = 0.0254
CLEAR_DOOR_MIN = 32 * IN     # 0.813 m
TURN_CIRCLE = 60 * IN        # 1.524 m
HEAD_MIN = 80 * IN           # 2.032 m


@dataclass
class Solid:
    """One box in the building. Ramps carry a sloped top."""
    kind: str                     # wall|slab|ramp|stair|curb|furniture|fixture|
                                  # soffit|glazing|rail|door_header
    x0: float; y0: float; x1: float; y1: float
    z0: float; z1: float
    tag: str = ""
    material: str = ""
    # ramp: top rises from rz0 to rz1 along `axis` ("x" or "y")
    axis: Optional[str] = None
    rz0: float = 0.0
    rz1: float = 0.0

    @property
    def walkable(self) -> bool:
        return self.kind in ("slab", "ramp", "stair", "curb")

    @property
    def overhead(self) -> bool:
        return self.kind in ("soffit", "door_header")

    @property
    def obstruction(self) -> bool:
        return self.kind in ("wall", "furniture", "fixture", "glazing", "rail")


@dataclass
class World:
    solids: list = field(default_factory=list)
    spawn_m: tuple = (2.0, 11.0)
    goals_m: dict = field(default_factory=dict)
    gt: list = field(default_factory=list)
    rooms: list = field(default_factory=list)
    cell: float = CELL
    size: tuple = (W, H)
    seed: int = 7

    # ---------- voxelisation ----------

    def rasterize(self):
        """Solids -> (free, floor_z, ceiling_z) on a 5 cm lattice.

        Two passes are required and the order is load-bearing. Walkable
        surfaces must be resolved first, because whether a solid blocks
        a body depends on the height of the floor that body is standing
        on -- a 0.5 m parapet on a slab raised 0.6 m is not an
        obstruction to someone down on the ground floor beside it.
        """
        nx, ny = int(round(W / CELL)), int(round(H / CELL))
        floor_z = np.zeros((nx, ny), dtype=np.float32)
        free = np.ones((nx, ny), dtype=bool)
        ceiling_z = np.full((nx, ny), CEIL_Z, dtype=np.float32)

        xs = (np.arange(nx) + 0.5) * CELL
        ys = (np.arange(ny) + 0.5) * CELL

        def span(s):
            i0 = max(0, int(np.floor(s.x0 / CELL)))
            i1 = min(nx, int(np.ceil(s.x1 / CELL)))
            j0 = max(0, int(np.floor(s.y0 / CELL)))
            j1 = min(ny, int(np.ceil(s.y1 / CELL)))
            return i0, i1, j0, j1

        # pass 1 -- walkable surfaces
        for s in self.solids:
            if not s.walkable:
                continue
            i0, i1, j0, j1 = span(s)
            if i0 >= i1 or j0 >= j1:
                continue
            if s.kind == "ramp" and s.axis:
                if s.axis == "x":
                    t = (xs[i0:i1] - s.x0) / max(s.x1 - s.x0, 1e-9)
                    top = (s.rz0 + (s.rz1 - s.rz0) * np.clip(t, 0, 1))[:, None]
                    top = np.broadcast_to(top, (i1 - i0, j1 - j0))
                else:
                    t = (ys[j0:j1] - s.y0) / max(s.y1 - s.y0, 1e-9)
                    top = (s.rz0 + (s.rz1 - s.rz0) * np.clip(t, 0, 1))[None, :]
                    top = np.broadcast_to(top, (i1 - i0, j1 - j0))
            else:
                top = np.full((i1 - i0, j1 - j0), s.z1, dtype=np.float32)
            blk = floor_z[i0:i1, j0:j1]
            floor_z[i0:i1, j0:j1] = np.maximum(blk, top)

        # pass 2 -- obstructions and overheads, relative to the local floor
        lo, hi = BODY_BAND
        for s in self.solids:
            i0, i1, j0, j1 = span(s)
            if i0 >= i1 or j0 >= j1:
                continue
            fz = floor_z[i0:i1, j0:j1]
            if s.obstruction:
                hits = (s.z1 > fz + lo) & (s.z0 < fz + hi)
                sub = free[i0:i1, j0:j1]
                free[i0:i1, j0:j1] = sub & ~hits
            elif s.overhead:
                low = s.z0 >= fz + hi
                cz = ceiling_z[i0:i1, j0:j1]
                ceiling_z[i0:i1, j0:j1] = np.where(
                    low, np.minimum(cz, s.z0), cz)

        # Outside the envelope is not floor.
        free[:, :] &= True
        return free, floor_z, ceiling_z

    # ---------- exports ----------

    def cell_of(self, p):
        return (int(round(p[0] / CELL)), int(round(p[1] / CELL)))

    @property
    def spawn(self):
        return self.cell_of(self.spawn_m)

    @property
    def goals(self):
        return {k: self.cell_of(v) for k, v in self.goals_m.items()}

    def to_scene(self) -> dict:
        return {
            "size": [W, H, CEIL_Z],
            "cell": CELL,
            "solids": [asdict(s) for s in self.solids],
            "rooms": self.rooms,
            "spawn": list(self.spawn_m),
            "goals": {k: list(v) for k, v in self.goals_m.items()},
            "ground_truth": self.gt,
        }


# ======================================================================
# the building
# ======================================================================

def build3d(seed: int = 7) -> World:
    """A civic centre: lobby, cafe, spine corridor, community room,
    accessible WC, and a raised gallery.

    Every planted defect is a condition that occurs constantly in real
    buildings and passes a plan-check: a door that measures fine until
    you account for the leaf, a ramp built to the wrong grade, a
    threshold nobody thought about, a WC that has all its fixtures but
    no room to turn, a bulkhead dropped under a duct run.
    """
    rng = np.random.default_rng(seed)
    S: list[Solid] = []
    gt: list = []
    rooms: list = []

    def add(kind, x0, y0, x1, y1, z0=0.0, z1=WALL_H, **kw):
        S.append(Solid(kind, x0, y0, x1, y1, z0, z1, **kw))

    def wall(x0, y0, x1, y1, tag="", z0=0.0, z1=WALL_H, mat="wall"):
        add("wall", x0, y0, x1, y1, z0, z1, tag=tag, material=mat)

    def wall_x(x, y0, y1, t=0.2, **kw):
        """Wall running along y at abscissa x."""
        wall(x, y0, x + t, y1, **kw)

    def wall_y(y, x0, x1, t=0.2, **kw):
        wall(x0, y, x1, y + t, **kw)

    def header(x0, y0, x1, y1, z0=2.10):
        """Structure over a door opening. Above the body band, so it is
        overhead rather than an obstruction -- which is exactly the
        distinction that makes the low bulkhead below a real finding."""
        add("door_header", x0, y0, x1, y1, z0, WALL_H, material="header")

    # ---------------- ground slab + envelope ----------------
    add("slab", 0.0, 0.0, W, H, -0.2, 0.0, tag="ground", material="floor")
    wall(0.0, 0.0, W, 0.2, tag="envelope")
    wall(0.0, H - 0.2, W, H, tag="envelope")
    wall(0.0, 0.0, 0.2, H, tag="envelope")
    wall(W - 0.2, 0.0, W, H, tag="envelope")

    # entrance opening in the west wall (glazed doors, always passable)
    S[:] = [s for s in S]
    add("glazing", 0.0, 8.6, 0.2, 9.4, 0.0, WALL_H, material="glass")
    add("glazing", 0.0, 12.6, 0.2, 13.4, 0.0, WALL_H, material="glass")
    # the doorway itself: cut by simply not walling y 9.4..12.6
    for (a, b) in [(0.2, 8.6), (13.4, H - 0.2)]:
        pass  # west wall already continuous; carve below

    # carve the entrance: replace the west envelope wall with two pieces
    S[:] = [s for s in S if not (s.kind == "wall" and s.tag == "envelope"
                                 and s.x0 == 0.0 and s.x1 == 0.2)]
    wall(0.0, 0.0, 0.2, 9.4, tag="envelope")
    wall(0.0, 12.6, 0.2, H, tag="envelope")
    header(0.0, 9.4, 0.2, 12.6)

    rooms.append({"name": "Entrance", "x0": 0.2, "y0": 8.5, "x1": 4.0,
                  "y1": 13.5, "z": 0.0})

    # ---------------- lobby ----------------
    rooms.append({"name": "Lobby", "x0": 0.2, "y0": 0.2, "x1": 13.8,
                  "y1": 21.8, "z": 0.0})

    # ---------------- cross wall at x = 13.8, with three openings -------
    # openings: community room door A (0.70 m), door B (1.20 m w/ threshold),
    # and the 3.0 m corridor mouth.
    XW = 13.8
    segs = [(0.2, 3.0), (4.2, 5.6), (6.3, 10.0), (13.0, 17.2), (18.6, 21.8)]
    for (a, b) in segs:
        wall_x(XW, a, b, tag="cross")
    header(XW, 3.0, XW + 0.2, 4.2)
    header(XW, 5.6, XW + 0.2, 6.3)
    header(XW, 10.0, XW + 0.2, 13.0, z0=2.30)
    header(XW, 17.2, XW + 0.2, 18.6)   # 1.4 m double leaf

    # Meeting Room B is the control: a 900 mm door, level threshold,
    # generous turning space. Not every room here is broken, and the
    # analysis has to be able to say so.
    rooms.append({"name": "Meeting Room B", "x0": XW + 0.2, "y0": 14.85,
                  "x1": 18.9, "y1": 21.8, "z": 0.0})

    # --- DEFECT 1: community room door A, 0.70 m clear (27.6 in) -------
    gt.append(dict(id="door_a_700mm", type="clearance_width",
                   pos=[XW + 0.1, 5.95], measured_in=round(0.70 / IN, 1),
                   blocks=["wheelchair", "vision_impaired_cane"],
                   note="Leaf-to-stop clear width 700 mm; ADA requires 815 mm."))

    # --- DEFECT 2: door B is wide, but sits on a 200 mm threshold ------
    add("curb", XW - 0.15, 3.0, XW + 0.35, 4.2, 0.0, 0.20,
        tag="threshold", material="concrete")
    gt.append(dict(id="door_b_threshold_200mm", type="step_height",
                   pos=[XW + 0.1, 3.6], measured_in=round(0.20 / IN, 1),
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="1200 mm opening, unusable: 200 mm upstand at the sill."))

    # ---------------- community room: the island ----------------
    # Interior deliberately impeccable -- this is the finding.
    wall_y(9.0, XW, 22.2, tag="community")
    wall(22.0, 0.2, 22.2, 9.2, tag="community")
    rooms.append({"name": "Community Room", "x0": XW + 0.2, "y0": 0.2,
                  "x1": 22.0, "y1": 9.0, "z": 0.0})

    # ---------------- spine corridor ----------------
    # south wall of corridor is the community-room wall above;
    # north wall carries the WC entrance.
    rooms.append({"name": "Corridor", "x0": XW + 0.2, "y0": 9.2, "x1": 31.8,
                  "y1": 13.0, "z": 0.0})
    for (a, b) in [(XW, 15.9), (16.9, 19.0)]:
        wall_y(13.0, a, b, tag="corridor_n")
    header(16.0, 13.0, 16.9, 13.2)

    # ---------------- accessible WC ----------------
    # A 2.1 x 1.45 m compartment. It is signed accessible, has a 1.0 m
    # door and a grab rail, and every fixture is correctly mounted --
    # and there is still nowhere to turn a wheelchair around. This is
    # the single most common real failure and it never shows up on a
    # door-width checklist.
    wall(15.0, 13.0, 15.2, 14.85, tag="wc")
    wall(17.3, 13.0, 17.5, 14.85, tag="wc")
    wall(15.0, 14.65, 17.5, 14.85, tag="wc")
    rooms.append({"name": "Accessible WC", "x0": 15.2, "y0": 13.2,
                  "x1": 17.3, "y1": 14.65, "z": 0.0})

    # fixtures eat the clear floor space
    add("fixture", 16.55, 13.95, 17.30, 14.65, 0.0, 0.42,
        tag="wc_pan", material="porcelain")
    add("fixture", 15.20, 14.20, 15.80, 14.65, 0.0, 0.85,
        tag="wc_basin", material="porcelain")
    add("rail", 17.20, 13.30, 17.30, 14.00, 0.75, 0.85,
        tag="grab_rail", material="steel")

    # --- DEFECT 3: WC has fixtures but no turning circle ---------------
    gt.append(dict(id="wc_turning_1300mm", type="turning_radius",
                   pos=[16.2, 13.85], measured_in=round(1.30 / IN, 1),
                   blocks=["wheelchair"],
                   note="Largest clear circle ~1300 mm; ADA 304.3.1 needs 1525 mm."))

    # --- DEFECT 4: bulkhead dropped over the WC door -------------------
    add("soffit", 15.0, 12.9, 17.5, 13.9, 1.95, 2.45,
        tag="wc_bulkhead", material="soffit")
    gt.append(dict(id="soffit_1950mm", type="head_clearance",
                   pos=[16.25, 13.4], measured_in=round(1.95 / IN, 1),
                   blocks=["vision_impaired_cane"],
                   note="Duct bulkhead at 1950 mm; ADA 307.4 requires 2032 mm."))

    # ---------------- raised gallery, +0.60 m ----------------
    # The slab is authored as five pieces rather than one rectangle so
    # the ramp and the stair occupy real pockets in it. A single slab
    # laid over the whole footprint would sit ON TOP of both, erasing
    # the only two ways up and turning the entire gallery edge into an
    # unbroken 600 mm cliff.
    GZ = 0.60
    RAMP_X = (19.5, 21.9)          # 2.4 m wide
    RAMP_Y = (13.0, 17.0)          # 4.0 m run -> 600/4000 = 1:6.7
    STAIR_X = (23.0, 24.5)
    STAIR_Y = (13.0, 14.2)

    for (a, b, c, d) in [
        (19.0, 13.2, RAMP_X[0], 21.8),          # west of the ramp
        (RAMP_X[0], RAMP_Y[1], RAMP_X[1], 21.8),  # north of the ramp
        (RAMP_X[1], 13.2, STAIR_X[0], 21.8),    # between ramp and stair
        (STAIR_X[0], STAIR_Y[1], STAIR_X[1], 21.8),  # north of the stair
        (STAIR_X[1], 13.2, 31.8, 21.8),         # east
    ]:
        add("slab", a, b, c, d, 0.0, GZ, tag="gallery", material="gallery")

    rooms.append({"name": "Gallery", "x0": 19.0, "y0": 13.2, "x1": 31.8,
                  "y1": 21.8, "z": GZ})
    for (a, b) in [(13.2, 21.8)]:
        add("wall", 18.9, a, 19.0, b, GZ, GZ + 1.0, tag="gallery_edge",
            material="parapet")

    # --- DEFECT 5: the ramp is built at 1:6.7 --------------------------
    add("ramp", RAMP_X[0], RAMP_Y[0], RAMP_X[1], RAMP_Y[1], 0.0, GZ,
        tag="gallery_ramp", material="ramp", axis="y", rz0=0.0, rz1=GZ)
    add("rail", RAMP_X[0] - 0.08, RAMP_Y[0], RAMP_X[0], RAMP_Y[1],
        0.85, 0.95, tag="ramp_rail", material="steel")
    add("rail", RAMP_X[1], RAMP_Y[0], RAMP_X[1] + 0.08, RAMP_Y[1],
        0.85, 0.95, tag="ramp_rail", material="steel")
    gt.append(dict(id="ramp_15pct", type="slope_gradient",
                   pos=[(RAMP_X[0] + RAMP_X[1]) / 2,
                        (RAMP_Y[0] + RAMP_Y[1]) / 2],
                   measured=round(GZ / (RAMP_Y[1] - RAMP_Y[0]), 3),
                   blocks=["wheelchair", "sidewalk_delivery_robot",
                           "vision_impaired_cane"],
                   note="600 mm rise over 4.0 m run = 1:6.7; ADA 405.2 max 1:12."))

    # --- DEFECT 6: the stair is the only other way up ------------------
    for i in range(4):
        add("stair", STAIR_X[0], STAIR_Y[0] + i * 0.30,
            STAIR_X[1], STAIR_Y[0] + (i + 1) * 0.30,
            0.0, (i + 1) * 0.15, tag=f"stair_{i}", material="concrete")
    gt.append(dict(id="stair_4riser_150mm", type="step_height",
                   pos=[(STAIR_X[0] + STAIR_X[1]) / 2, 13.6],
                   measured_in=round(0.15 / IN, 1),
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="4 risers at 150 mm. Passable on foot or with a cane; "
                        "not on wheels."))

    # --- DEFECT 7: unprotected 600 mm drop along the gallery's south edge
    gt.append(dict(id="gallery_curb_600mm", type="step_height",
                   pos=[28.0, 13.25], measured_in=round(GZ / IN, 1),
                   blocks=["wheelchair", "sidewalk_delivery_robot",
                           "vision_impaired_cane"],
                   note="Slab edge with no upstand or ramp for 8.9 m."))

    # ---------------- cafe: seeded contents ----------------
    def table(cx, cy, r=0.40):
        add("furniture", cx - r, cy - r, cx + r, cy + r, 0.0, 0.74,
            tag="cafe_table", material="timber")

    def chair(cx, cy, r=0.22):
        add("furniture", cx - r, cy - r, cx + r, cy + r, 0.0, 0.86,
            tag="cafe_chair", material="timber")

    placed = 0
    while placed < 9:
        cx = float(rng.uniform(1.6, 12.6))
        cy = float(rng.uniform(1.4, 7.6))
        if any(abs(cx - t[0]) < 2.0 and abs(cy - t[1]) < 2.0
               for t in [(s.x0 + 0.40, s.y0 + 0.40) for s in S
                         if s.tag == "cafe_table"]):
            continue
        table(cx, cy)
        for (dx, dy) in [(-0.78, 0), (0.78, 0), (0, -0.78), (0, 0.78)]:
            if rng.random() < 0.72:
                chair(cx + dx, cy + dy)
        placed += 1

    # --- DEFECT 8: two furniture runs leave an 860 mm gap --------------
    # Planted last so the random tables cannot overwrite it.
    add("furniture", 7.2, 9.4, 9.6, 10.2, 0.0, 0.75, tag="bench",
        material="timber")
    add("furniture", 7.2, 11.06, 9.6, 11.86, 0.0, 0.75, tag="bench",
        material="timber")
    gt.append(dict(id="cafe_pinch_860mm", type="clearance_width",
                   pos=[8.4, 10.63], measured_in=round(0.86 / IN, 1),
                   blocks=["vision_impaired_cane"],
                   note="860 mm between two benches. Architecture is fine; "
                        "the furniture is not."))

    # reception desk + lobby seating
    add("furniture", 11.4, 15.2, 13.4, 16.4, 0.0, 1.05, tag="reception",
        material="timber")
    for k in range(4):
        add("furniture", 9.4 + k * 0.95, 18.4, 10.0 + k * 0.95, 19.4,
            0.0, 0.86, tag="lobby_seat", material="fabric")

    # ---------------- planters, columns (structure, not clutter) -------
    for cx in (9.0, 18.0, 26.0):
        add("wall", cx - 0.22, 6.4, cx + 0.22, 6.84, 0.0, WALL_H,
            tag="column", material="concrete")

    goals = {
        "community_room": (18.0, 5.2),
        "gallery": (27.0, 18.0),
        "restroom": (16.2, 13.6),
        "east_end": (30.0, 11.0),
    }

    return World(solids=S, spawn_m=(1.8, 11.0), goals_m=goals, gt=gt,
                 rooms=rooms, seed=seed)


if __name__ == "__main__":
    w = build3d(7)
    free, fz, cz = w.rasterize()
    print(f"solids        : {len(w.solids)}")
    print(f"grid          : {free.shape}  ({CELL*100:.0f} cm cells)")
    print(f"free fraction : {free.mean():.3f}")
    print(f"floor_z range : {fz.min():.2f} .. {fz.max():.2f} m")
    print(f"ceiling min   : {cz.min():.2f} m")
    print(f"defects       : {len(w.gt)}")
    for d in w.gt:
        print(f"   {d['id']:26s} {d['type']:16s} {d['note']}")
