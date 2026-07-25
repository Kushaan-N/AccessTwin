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

from schema import SURFACES, DEFAULT_SURFACE

# Fixed order so the uint8 raster and the viewer legend agree.
SURFACE_ORDER = list(SURFACES.keys())

CELL = 0.05                  # 5 cm voxel, same as a Recast cell size
W, H = 44.0, 36.0            # envelope, metres (incl. courtyard)
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
    surface: str = ""            # floor finish, walkable solids only

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
        # Floor finish per cell, as an index into SURFACE_ORDER. Written
        # in the same pass as floor height, so whichever walkable solid
        # wins the height also owns the finish -- a ramp laid over a
        # carpeted floor is a ramp, not carpet.
        surf = np.zeros((nx, ny), dtype=np.uint8)

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
            wins = top >= blk
            floor_z[i0:i1, j0:j1] = np.maximum(blk, top)
            if s.surface:
                sid = SURFACE_ORDER.index(s.surface)
                sub = surf[i0:i1, j0:j1]
                surf[i0:i1, j0:j1] = np.where(wins, sid, sub)

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
        return free, floor_z, ceiling_z, surf

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
            "surfaces": [{"name": n, **{k: v for k, v in
                          SURFACES[n].__dict__.items() if k != "name"}}
                         for n in SURFACE_ORDER],
            "rooms": self.rooms,
            "spawn": list(self.spawn_m),
            "goals": {k: list(v) for k, v in self.goals_m.items()},
            "ground_truth": self.gt,
        }


# ======================================================================
# the building
# ======================================================================

def build3d(seed: int = 7, with_contents: bool = True) -> World:
    """A civic centre: open atrium, cafe, reading room, auditorium,
    accessible WC, lift, and a gallery raised 600 mm.

    The plan is deliberately open. A corridor-and-cells building hides
    its access failures behind doors; an atrium with a cafe in it fails
    in public, in the middle of the floor, which is both more honest and
    far more legible in three dimensions.

    Every planted defect is a condition that occurs constantly in
    practice and passes a plan check: a door that measures fine until
    you account for the leaf, a ramp built to the wrong grade, a
    threshold nobody costed, a WC with every fixture correct and no room
    to turn, a lift car specified by capacity rather than footprint,
    seating laid out to a seat count, a counter at till height, and a
    screen hung at exactly the height a cane cannot find.
    """
    rng = np.random.default_rng(seed)
    S: list[Solid] = []
    gt: list = []
    rooms: list = []

    def add(kind, x0, y0, x1, y1, z0=0.0, z1=WALL_H, **kw):
        # with_contents=False regenerates the identical building with the
        # loose furniture omitted -- same walls, same ramp, same doors.
        # Differencing the two free masks is then exact ground truth for
        # which exclusions the building causes and which its contents do,
        # rather than a guess based on what looks free-standing.
        if not with_contents and kind == "furniture":
            return
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
        distinction that makes the low bulkhead and the hung screen
        below into real findings."""
        add("door_header", x0, y0, x1, y1, z0, WALL_H, material="header")

    def floor(x0, y0, x1, y1, surface, z=0.0):
        """A finish laid over an existing slab, 5 mm proud so it wins the
        height comparison and therefore owns the surface id."""
        add("slab", x0, y0, x1, y1, z - 0.005, z, tag="finish",
            material="floor", surface=surface)

    def room(name, x0, y0, x1, y1, z=0.0):
        rooms.append({"name": name, "x0": x0, "y0": y0,
                      "x1": x1, "y1": y1, "z": z})

    # ================= envelope =================
    add("slab", 0.0, 0.0, W, H, -0.2, 0.0, tag="ground",
        material="floor", surface="concrete")
    wall(0.0, 0.0, W, 0.2, tag="envelope")
    wall(0.0, H - 0.2, W, H, tag="envelope")
    # The old north elevation is now internal: beyond it is the courtyard.
    for (a, b) in [(0.0, 12.0), (13.4, W)]:
        wall(a, 29.8, b, 30.0, tag="envelope")
    header(12.0, 29.8, 13.4, 30.0)
    wall(0.0, 30.0, 0.2, H, tag="envelope")
    wall(W - 0.2, 30.0, W, H, tag="envelope")
    wall(W - 0.2, 0.0, W, H, tag="envelope")
    # west wall, split around the entrance
    wall(0.0, 0.0, 0.2, 13.0, tag="envelope")
    wall(0.0, 17.0, 0.2, H, tag="envelope")
    header(0.0, 13.0, 0.2, 17.0)
    add("glazing", 0.0, 13.0, 0.2, 14.0, 0.0, 2.10, material="glass")
    add("glazing", 0.0, 16.0, 0.2, 17.0, 0.0, 2.10, material="glass")

    # North elevation is glazed: an atrium wants daylight, and glass
    # reads as openness in a way a blank wall cannot.
    for gx in range(6, 21, 2):
        if gx >= 12 and gx < 14:
            continue
        add("glazing", float(gx), 29.8, float(gx) + 1.6, 30.0, 0.0, 2.6,
            material="glass")

    # ---------------- floor finishes ----------------
    # ADA 302 is a material rule, and it is the one axis on which a cane
    # user out-performs a wheelchair: feet cross gravel and deep pile,
    # castors do not.
    floor(0.2, 0.2, 21.8, 29.8, "concrete")
    floor(0.4, 0.4, 10.5, 9.5, "tile")                 # cafe
    floor(22.2, 0.4, 31.8, 12.8, "carpet_low")         # community room
    floor(22.2, 13.0, 43.8, 17.0, "concrete")          # corridor
    floor(22.2, 17.2, 24.4, 18.65, "tile")             # WC
    floor(22.2, 19.1, 30.5, 29.6, "carpet_low")        # reading room

    # ================= atrium =================
    # The whole west half is one volume. No cross walls, no cells.
    room("Atrium", 0.2, 0.2, 21.8, H - 0.2)

    # structural grid
    for cx in (7.0, 13.0, 19.0):
        for cy in (6.0, 12.0, 18.0, 24.0):
            add("wall", cx - 0.22, cy - 0.22, cx + 0.22, cy + 0.22,
                0.0, WALL_H, tag="column", material="concrete")

    # ---- cafe, open into the atrium -------------------------------
    room("Cafe", 0.4, 0.4, 10.5, 9.5)
    add("furniture", 8.6, 1.6, 9.6, 8.4, 0.0, 1.05,
        tag="cafe_counter", material="timber")
    # --- DEFECT: counter at till height with no lowered section ------
    gt.append(dict(id="counter_1050mm", type="counter_height",
                   pos=[9.1, 5.0], measured_in=round(1.05 / IN, 1),
                   blocks=["wheelchair"],
                   note="Service counter runs 6.8 m at 1050 mm with no "
                        "lowered section; ADA 904.4.1 requires 865 mm."))
    for k in range(6):
        add("furniture", 8.0, 2.2 + k * 1.1, 8.45, 2.65 + k * 1.1, 0.0, 0.78,
            tag="stool", material="timber")

    # Rejection sampling with a bounded attempt count. Asking for more
    # tables than the separation allows spins forever, so the loop is
    # capped and simply places fewer.
    placed, spots, tries = 0, [], 0
    while placed < 9 and tries < 400:
        tries += 1
        cx = float(rng.uniform(1.4, 7.4))
        cy = float(rng.uniform(1.4, 8.6))
        if any(abs(cx - a) < 1.75 and abs(cy - b) < 1.75 for a, b in spots):
            continue
        spots.append((cx, cy))
        add("furniture", cx - 0.40, cy - 0.40, cx + 0.40, cy + 0.40,
            0.0, 0.74, tag="cafe_table", material="timber")
        for (dx, dy) in [(-0.78, 0), (0.78, 0), (0, -0.78), (0, 0.78)]:
            if rng.random() < 0.7:
                add("furniture", cx + dx - 0.22, cy + dy - 0.22,
                    cx + dx + 0.22, cy + dy + 0.22, 0.0, 0.86,
                    tag="cafe_chair", material="timber")
        placed += 1

    # --- DEFECT: two benches leave an 860 mm gap ---------------------
    add("furniture", 11.6, 10.4, 14.0, 11.2, 0.0, 0.75, tag="bench",
        material="timber")
    add("furniture", 11.6, 12.06, 14.0, 12.86, 0.0, 0.75, tag="bench",
        material="timber")
    gt.append(dict(id="atrium_pinch_860mm", type="clearance_width",
                   pos=[12.8, 11.63], measured_in=round(0.86 / IN, 1),
                   blocks=["vision_impaired_cane"],
                   note="860 mm between two benches. The architecture is "
                        "fine; the furniture is not."))

    # ---- reception -------------------------------------------------
    add("furniture", 3.0, 14.0, 6.0, 15.4, 0.0, 1.05, tag="reception",
        material="timber")

    # ---- lounge seating --------------------------------------------
    for k in range(4):
        add("furniture", 14.6 + k * 1.5, 23.0, 15.6 + k * 1.5, 24.0,
            0.0, 0.86, tag="lobby_seat", material="fabric")
    for k in range(3):
        add("furniture", 15.4 + k * 1.5, 26.0, 16.4 + k * 1.5, 27.0,
            0.0, 0.86, tag="lobby_seat", material="fabric")
    add("furniture", 17.4, 24.6, 19.0, 25.6, 0.0, 0.42, tag="low_table",
        material="timber")

    # ---- planters ---------------------------------------------------
    for (px, py) in [(4.5, 20.0), (10.0, 20.0), (4.5, 26.0), (10.5, 26.5)]:
        add("furniture", px - 0.45, py - 0.45, px + 0.45, py + 0.45,
            0.0, 0.80, tag="planter", material="concrete")

    # --- DEFECT: information screen hung above cane sweep -----------
    # Sits clear of the body band, so the floor beneath it reads as
    # perfectly walkable, and low enough to strike a standing head. A
    # cane sweeps the ground and never finds it.
    add("soffit", 15.4, H - 0.55, 17.4, H - 0.2, 1.55, 1.95,
        tag="info_screen", material="soffit")
    gt.append(dict(id="screen_1550mm", type="head_clearance",
                   pos=[16.4, H - 0.38], measured_in=round(1.55 / IN, 1),
                   blocks=["vision_impaired_cane"],
                   note="Wall-hung screen projecting 350 mm with its "
                        "underside at 1550 mm; ADA 307.2 limits projection "
                        "to 100 mm between 685 and 2030 mm."))

    # ================= cross wall at x = 22 =================
    XW = 22.0
    for (a, b) in [(0.2, 3.0), (4.2, 5.6), (6.3, 13.0), (17.0, 21.0),
                   (22.4, 29.8)]:
        wall_x(XW, a, b, tag="cross")
    header(XW, 3.0, XW + 0.2, 4.2)
    header(XW, 5.6, XW + 0.2, 6.3)
    header(XW, 13.0, XW + 0.2, 17.0, z0=2.40)     # 4 m corridor mouth
    header(XW, 21.0, XW + 0.2, 22.4)              # 1.4 m reading room door

    # --- DEFECT: community room door A, 700 mm clear -----------------
    gt.append(dict(id="door_a_700mm", type="clearance_width",
                   pos=[XW + 0.1, 5.95], measured_in=round(0.70 / IN, 1),
                   blocks=["wheelchair", "vision_impaired_cane"],
                   note="Leaf-to-stop clear width 700 mm; ADA 404.2.3 "
                        "requires 815 mm."))
    # --- DEFECT: door B is wide, and sits on a 200 mm upstand --------
    add("curb", XW - 0.15, 3.0, XW + 0.35, 4.2, 0.0, 0.20,
        tag="threshold", material="concrete")
    gt.append(dict(id="door_b_threshold_200mm", type="step_height",
                   pos=[XW + 0.1, 3.6], measured_in=round(0.20 / IN, 1),
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="1200 mm opening, unusable: 200 mm upstand at the "
                        "sill."))

    # ================= spine corridor =================
    room("Corridor", XW + 0.2, 13.0, W - 0.2, 17.0)
    # South side: the community room deliberately gets NO corridor door.
    # Its only two ways in are the 700 mm leaf and the 200 mm threshold,
    # which is what makes it an island rather than merely awkward.
    wall_y(12.8, XW, 36.0, tag="corridor_s")
    wall_y(12.8, 37.4, W - 0.2, tag="corridor_s")
    header(36.0, 12.8, 37.4, 13.0)     # auditorium door, 1.4 m
    # North side: WC, lift and reading room doors, then open to the
    # gallery from x = 31.0 east.
    for (a, b) in [(XW, 22.9), (24.1, 25.9), (27.5, 28.0), (29.4, 31.0)]:
        wall_y(17.0, a, b, tag="corridor_n")
    header(22.9, 17.0, 24.1, 17.2)     # WC door
    header(25.9, 17.0, 27.5, 17.2)     # lift doors
    header(28.0, 17.0, 29.4, 17.2)     # reading room door, 1.4 m

    # ================= community room: the island =================
    room("Community Room", XW + 0.2, 0.4, 31.8, 12.8)
    wall_x(31.8, 0.2, 12.9, tag="community")

    # ================= auditorium =================
    room("Auditorium", 32.2, 0.4, W - 0.4, 12.8)
    # --- DEFECT: deep-pile carpet throughout the auditorium ----------
    floor(32.2, 0.4, W - 0.4, 12.8, "carpet_deep")
    gt.append(dict(id="auditorium_carpet_22mm", type="floor_surface",
                   pos=[38.0, 6.5], measured_in=round(0.022 / IN, 2),
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="22 mm deep-pile carpet throughout; ADA 302.2 caps "
                        "pile at 13 mm. Geometrically the room is fine."))
    # Fixed seating laid out to a seat count. Rows are generous, the
    # cross aisle is not, and nowhere in the room is there a clear space
    # for somebody who brings their own seat.
    # Stage at the far end, seating between it and the door, and a clear
    # circulation zone inside the entrance -- the way a room like this is
    # actually laid out. The failure is not that it is cramped; it is
    # that the layout was drawn to a seat count.
    add("furniture", 33.0, 0.6, 43.0, 2.2, 0.0, 0.45, tag="stage",
        material="timber")
    for r in range(6):
        yy = 3.4 + r * 1.30
        for c in range(7):
            xx = 32.7 + c * 0.62
            add("furniture", xx, yy, xx + 0.50, yy + 0.55, 0.0, 0.92,
                tag="seat", material="fabric")
        for c in range(7):
            xx = 37.77 + c * 0.62
            add("furniture", xx, yy, xx + 0.50, yy + 0.55, 0.0, 0.92,
                tag="seat", material="fabric")
    gt.append(dict(id="auditorium_aisle_850mm", type="clearance_width",
                   pos=[37.6, 6.0], measured_in=round(0.85 / IN, 1),
                   blocks=["vision_impaired_cane"],
                   note="850 mm cross aisle between seat blocks, and no "
                        "clear space anywhere for a wheelchair user; "
                        "ADA 221 requires designated spaces."))


    # ================= accessible WC =================
    room("Accessible WC", 22.2, 17.2, 24.4, 18.65)
    wall_x(22.0, 17.2, 18.85, tag="wc")
    wall_x(24.4, 17.0, 18.85, tag="wc")
    wall_y(18.65, 22.0, 24.6, tag="wc")
    add("fixture", 23.65, 17.95, 24.40, 18.65, 0.0, 0.42,
        tag="wc_pan", material="porcelain")
    add("fixture", 22.20, 18.20, 22.80, 18.65, 0.0, 0.85,
        tag="wc_basin", material="porcelain")
    add("rail", 24.30, 17.30, 24.40, 18.00, 0.75, 0.85,
        tag="grab_rail", material="steel")
    gt.append(dict(id="wc_turning_1300mm", type="turning_radius",
                   pos=[23.2, 17.8], measured_in=round(1.30 / IN, 1),
                   blocks=["wheelchair"],
                   note="Every fixture correctly mounted; largest clear "
                        "circle ~1300 mm where ADA 304.3.1 needs 1525 mm."))
    # --- DEFECT: duct bulkhead over the WC entrance ------------------
    add("soffit", 22.0, 16.9, 24.6, 17.9, 1.95, 2.45,
        tag="wc_bulkhead", material="soffit")
    gt.append(dict(id="soffit_1950mm", type="head_clearance",
                   pos=[23.2, 17.4], measured_in=round(1.95 / IN, 1),
                   blocks=["vision_impaired_cane"],
                   note="Duct bulkhead at 1950 mm; ADA 307.4 requires "
                        "2032 mm."))

    # ================= lift =================
    # Specified by capacity, not by footprint: the car takes eight
    # people standing and cannot turn one wheelchair.
    room("Lift", 25.9, 17.2, 27.5, 18.6)
    wall_x(25.7, 17.0, 18.8, tag="lift")
    wall_x(27.5, 17.0, 18.8, tag="lift")
    wall_y(18.6, 25.7, 27.7, tag="lift")
    add("wall", 25.7, 17.0, 25.9, 17.2, 0.0, WALL_H, tag="lift",
        material="wall")
    add("fixture", 27.35, 17.25, 27.50, 18.55, 0.90, 1.30,
        tag="lift_panel", material="steel")
    gt.append(dict(id="lift_car_1600x1400", type="turning_radius",
                   pos=[26.7, 17.9], measured_in=round(1.40 / IN, 1),
                   blocks=["wheelchair"],
                   note="Car 1600 x 1400 mm. Enough to enter, not enough "
                        "to turn; ADA 304.3.1 needs a 1525 mm circle."))

    # ================= reading room: the control =================
    # 1.4 m doors, level threshold, generous turning space. Not every
    # room here is broken and the analysis has to be able to say so.
    room("Reading Room", 22.2, 19.1, 30.5, 29.6)
    wall_x(30.5, 17.2, 29.8, tag="reading")
    for k in range(6):
        add("furniture", 22.4, 20.4 + k * 1.5, 22.9, 21.5 + k * 1.5,
            0.0, 1.80, tag="bookshelf", material="timber")
    for k in range(5):
        add("furniture", 29.9, 20.0 + k * 1.6, 30.4, 21.1 + k * 1.6,
            0.0, 1.80, tag="bookshelf", material="timber")
    for (tx, ty) in [(26.2, 22.4), (26.2, 26.2)]:
        add("furniture", tx - 0.9, ty - 0.55, tx + 0.9, ty + 0.55,
            0.0, 0.74, tag="reading_table", material="timber")
        for dx in (-0.55, 0.55):
            add("furniture", tx + dx - 0.22, ty - 1.02, tx + dx + 0.22,
                ty - 0.58, 0.0, 0.86, tag="cafe_chair", material="timber")
            add("furniture", tx + dx - 0.22, ty + 0.58, tx + dx + 0.22,
                ty + 1.02, 0.0, 0.86, tag="cafe_chair", material="timber")

    # ================= gallery, +0.60 m =================
    GZ = 0.60
    RAMP_X = (33.0, 35.4)
    RAMP_Y = (17.0, 21.0)          # 4.0 m run -> 1:6.7
    STAIR_X = (36.4, 37.9)
    STAIR_Y = (17.0, 18.2)

    room("Gallery", 31.0, 17.2, W - 0.4, 29.6, GZ)
    # Authored as pieces so the ramp and stair occupy real pockets. One
    # slab laid over the whole footprint would sit on top of both,
    # erasing the only two ways up.
    for (a, b, c, d) in [
        (31.0, 17.2, RAMP_X[0], 29.6),
        (RAMP_X[0], RAMP_Y[1], RAMP_X[1], 29.6),
        (RAMP_X[1], 17.2, STAIR_X[0], 29.6),
        (STAIR_X[0], STAIR_Y[1], STAIR_X[1], 29.6),
        (STAIR_X[1], 17.2, W - 0.4, 29.6),
    ]:
        add("slab", a, b, c, d, 0.0, GZ, tag="gallery",
            material="gallery", surface="timber")
    add("wall", 30.9, 17.2, 31.0, 29.6, GZ, GZ + 1.0, tag="gallery_edge",
        material="parapet")

    # --- DEFECT: ramp built at 1:6.7 ---------------------------------
    add("ramp", RAMP_X[0], RAMP_Y[0], RAMP_X[1], RAMP_Y[1], 0.0, GZ,
        tag="gallery_ramp", material="ramp", axis="y", rz0=0.0, rz1=GZ,
        surface="concrete")
    for rx in (RAMP_X[0] - 0.08, RAMP_X[1]):
        add("rail", rx, RAMP_Y[0], rx + 0.08, RAMP_Y[1], 0.85, 0.95,
            tag="ramp_rail", material="steel")
    gt.append(dict(id="ramp_15pct", type="slope_gradient",
                   pos=[(RAMP_X[0] + RAMP_X[1]) / 2,
                        (RAMP_Y[0] + RAMP_Y[1]) / 2],
                   measured=round(GZ / (RAMP_Y[1] - RAMP_Y[0]), 3),
                   blocks=["wheelchair", "sidewalk_delivery_robot",
                           "vision_impaired_cane"],
                   note="600 mm rise over 4.0 m = 1:6.7; ADA 405.2 caps "
                        "ramps at 1:12."))

    # --- DEFECT: four-riser stair is the only other way up -----------
    for i in range(4):
        add("stair", STAIR_X[0], STAIR_Y[0] + i * 0.30,
            STAIR_X[1], STAIR_Y[0] + (i + 1) * 0.30,
            0.0, (i + 1) * 0.15, tag=f"stair_{i}", material="concrete",
            surface="concrete")
    gt.append(dict(id="stair_4riser_150mm", type="step_height",
                   pos=[(STAIR_X[0] + STAIR_X[1]) / 2, 17.6],
                   measured_in=round(0.15 / IN, 1),
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="4 risers at 150 mm. Passable on foot or with a "
                        "cane; not on wheels."))

    # --- DEFECT: unprotected 600 mm drop along the gallery edge ------
    gt.append(dict(id="gallery_curb_600mm", type="step_height",
                   pos=[39.5, 17.25], measured_in=round(GZ / IN, 1),
                   blocks=["wheelchair", "sidewalk_delivery_robot",
                           "vision_impaired_cane"],
                   note="Slab edge with no upstand or ramp for 5.3 m."))

    # --- DEFECT: services grating across the gallery ----------------
    floor(31.0, 23.0, 43.6, 23.9, "grating", z=0.60)
    gt.append(dict(id="gallery_grating_22mm", type="floor_surface",
                   pos=[37.0, 23.45], measured_in=round(0.022 / IN, 2),
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="Services grating with 22 mm slots runs the full "
                        "width; ADA 302.3 caps openings at 13 mm. Castors "
                        "drop straight in."))
    # Good practice, deliberately included so the analysis can also say
    # when something is right: tactile warning surface at the stair.
    floor(STAIR_X[0] - 0.1, STAIR_Y[0] - 0.9, STAIR_X[1] + 0.1,
          STAIR_Y[0], "tactile")

    # gallery contents
    for k in range(4):
        add("furniture", 33.4 + k * 2.6, 27.6, 34.6 + k * 2.6, 28.0,
            GZ, GZ + 1.9, tag="display_panel", material="timber")
    for k in range(3):
        add("furniture", 40.4, 19.4 + k * 2.4, 42.4, 20.0 + k * 2.4,
            GZ, GZ + 0.95, tag="display_case", material="steel")

    # ================= courtyard =================
    # Outside, and paved in exactly the materials that read as "civic
    # quality" on a drawing and stop a wheelchair at the door.
    room("Courtyard", 0.2, 30.0, W - 0.2, H - 0.2)
    floor(0.2, 30.0, W - 0.2, H - 0.2, "gravel")
    # --- DEFECT: a cobbled path is the only route across ------------
    floor(11.4, 30.0, 14.0, H - 0.2, "cobble")
    gt.append(dict(id="courtyard_gravel", type="floor_surface",
                   pos=[8.0, 33.0], measured_in=0.0,
                   blocks=["wheelchair", "sidewalk_delivery_robot"],
                   note="Loose gravel with a cobbled path: neither is firm "
                        "and stable under a castor. ADA 302.1. A cane user "
                        "crosses both without difficulty."))
    for (px, py) in [(4.0, 32.0), (18.0, 32.0), (4.0, 34.5), (18.0, 34.5)]:
        add("furniture", px - 0.5, py - 0.5, px + 0.5, py + 0.5, 0.0, 0.85,
            tag="planter", material="concrete")
    for k in range(3):
        add("furniture", 16.0 + k * 3.2, 33.4, 17.8 + k * 3.2, 33.9,
            0.0, 0.45, tag="bench", material="timber")

    # Goals sit on open floor by construction. reaches() tests the goal
    # cell directly without snapping, so a destination parked 200 mm from
    # a display case would read as unreachable for everybody.
    goals = {
        "community_room": (27.0, 6.5),
        "gallery": (42.2, 27.0),
        "restroom": (23.1, 17.6),
        "auditorium": (37.4, 11.8),
        "reading_room": (26.2, 24.4),
        "courtyard": (8.0, 33.0),
    }

    return World(solids=S, spawn_m=(2.2, 15.0), goals_m=goals, gt=gt,
                 rooms=rooms, seed=seed)


if __name__ == "__main__":
    w = build3d(7)
    free, fz, cz, sf = w.rasterize()
    print(f"solids        : {len(w.solids)}")
    print(f"grid          : {free.shape}  ({CELL*100:.0f} cm cells)")
    print(f"free fraction : {free.mean():.3f}")
    print(f"floor_z range : {fz.min():.2f} .. {fz.max():.2f} m")
    print(f"ceiling min   : {cz.min():.2f} m")
    print(f"defects       : {len(w.gt)}")
    for d in w.gt:
        print(f"   {d['id']:26s} {d['type']:16s} {d['note']}")
