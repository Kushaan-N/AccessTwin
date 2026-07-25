# Access-Twin

**Passing every ADA measurement and being reachable by a real body are different
properties. This measures the gap.**

Access-Twin generates a building, voxelises it, and runs four physically
constrained mobility profiles through it to find where geometry excludes bodies —
then localises each barrier, prices the repairs, and scores itself against a
planted answer key it is never shown.

**Live demo:** https://claude.ai/code/artifact/131f14af-2e9c-4bf4-99b3-79452a60593a
It starts automatically, loops, and needs no input.

---

## The hypothesis

> Geometric ADA compliance and actual traversability are different properties, and
> the gap between them is measurable automatically from spatial data.

### What the prototype proves

1. **Regions exist that satisfy every clearance, slope and turning rule while being
   completely unreachable.** 215 m² is stranded from a wheelchair — a community
   room and a gallery, both flawless inside.
2. **The exact body width at which a space begins excluding people can be found by
   bisection**, and it disagrees with what a tape measure reports. The route to the
   community room measures **47 inches** of clear width and serves **27.6** once
   slope and level change are counted too; the route to the gallery measures 47
   inches and admits *no body of any width*, because it was never a width problem.
3. **The best-scoring remediation can be actively harmful.** The repair with the
   highest coverage-per-dollar here — 3.3 points per $1k against the winner's 0.2,
   fifteen times better — is rejected outright, because rebuilding the building
   that way takes floor away from the wheelchair user it was meant to serve.

---

## Results (seed 7)

| Body | Floor reached | Destinations |
|---|---|---|
| Walking adult | 100% | 5 / 5 |
| Wheelchair user | **63.2%** | 2 / 5 |
| Cane user | 71.9% | 3 / 5 |
| Delivery robot | 82.8% | 4 / 5 |

The delivery robot passes through the 700 mm door that excludes the wheelchair.
The same building admits a machine and turns away a person.

**Detection: 13 of 13 planted defects recovered**, by an analysis that is never told
where to look, plus dozens of emergent exclusions nobody planted — pinch points created by
where the furniture landed rather than by the architecture.

**Repair:** with a $6,000 budget the optimum is $4,512 (widen the 700 mm door),
returning the wheelchair from 66.3% to **77.0%** of the floor and the cane user
from 71.9% to **82.1%**, with no profile losing anything. Two cheaper repairs
that scored better in aggregate were rejected: one costs the wheelchair 0.9
points of floor, the other costs the walking adult a destination outright.

---

## Setup

```bash
pip install numpy scipy          # matplotlib optional
python3 core/world3d.py          # build + voxelise the building
python3 viz/scene3d.py --seed 7  # full analysis -> out/scene.json
python3 viz/build3d.py           # bundle -> out/index.html
open out/index.html
```

Python 3.10+. No GPU, no engine, no dataset, no network. The full analysis runs in
a few seconds on a laptop; a single profile rebake is about 2 ms.

### Controls

The demo runs 2 min 52 s and loops. Drag to orbit, scroll to zoom, `Space`
restarts, `←`/`→` step scenes, `P` pauses, `Esc` closes a panel. Two scenes are
interactive: drag the body-width slider in *Where does it close?*, and click any
marker in *Every blockage, priced*.

It is also usable without the 3D view: there is a skip link to a text version of
every finding, each scene is announced to a live region, and
`prefers-reduced-motion` is honoured.

Note: the walkthrough is driven by `requestAnimationFrame`, which browsers
suspend entirely in a background tab. Keep the window foreground while
presenting.

---

## How it works

The building is the source of truth and the analysis grid is *derived* from it:

```
typed solids (walls, ramps, stairs, furniture, soffits)
        │  voxelise, 5 cm
        ▼
floor height · free space · ceiling underside
        │  erode by body radius, mask by climb / slope / headroom
        ▼
per-profile navigable mask → connected components
```

That is the standard navmesh pipeline — the same heightfield Recast/Detour builds
from a Unity scene and habitat-sim builds from a scanned mesh. Point it at a real
captured building instead of a generated one and nothing downstream changes.

Two detectors run, and they are complementary rather than redundant.

**Geometric sweep.** Every ADA rule at every cell for every profile: clear width
along the circulation medial axis, running slope, level change, head clearance,
floor finish, turning space per room, and counter height against the model. It
catches what violates, including defects that block nobody's route.

**Embodied reachability.** Where a constrained profile's reachable set fails to
cover ground the baseline reaches, that is an exclusion. *The erosion is the
check.* It catches what excludes, and localises the barrier responsible — but it
reports only the cheapest barrier per route, so a second defect behind the first
is masked.

A planted defect counts as detected if either recovers it. Neither is ever told
where to look.

> A third layer — hesitation-weighted behavioural telemetry — exists in
> `legacy/telemetry.py` with the consensus auditor that combines all three. It is
> **not** on the path the shipped walkthrough runs, and the numbers above do not
> depend on it.

### Barrier localisation

Asked *what is in the way*, the model routes a body along a least-resistance path
over its own violation surface, where each constraint is normalised to its own
limit. Where free passage exists the path crosses nothing; where none exists it
crosses the single cheapest barrier — and names it. **The candidate repairs the
optimiser considers are discovered this way, never hand-listed.**

---

## The building

A generated civic centre, 44 × 30 m, 250 solids across nine rooms: an open atrium
with a café in it, a spine corridor, community room, auditorium, accessible WC,
lift, reading room, and a gallery raised 600 mm. The plan is deliberately open —
a corridor-and-cells building hides its access failures behind doors, whereas an
atrium fails in public, in the middle of the floor.

Twelve defects are planted, every one a condition that occurs constantly in
practice and passes a plan check.

| Defect | Type | Excludes |
|---|---|---|
| 700 mm community room door | clear width | wheelchair, cane |
| 1200 mm door on a 200 mm threshold | level change | wheelchair, robot |
| Gallery ramp at 1:6.7 | running slope | wheelchair, robot, cane |
| Four-riser stair, 150 mm | level change | wheelchair, robot |
| Unprotected 600 mm slab edge | level change | all wheeled |
| WC with every fixture correct, 1300 mm circle | turning space | wheelchair |
| Lift car sized by capacity, 1600 × 1400 mm | turning space | wheelchair |
| Auditorium: 850 mm aisle, no designated space | clear width | cane, wheelchair |
| Duct bulkhead at 1950 mm | head clearance | cane |
| Screen hung at 1550 mm, projecting 350 mm | head clearance | cane |
| Café counter at 1050 mm, no lowered section | counter height | wheelchair |
| 860 mm gap between two benches | clear width | cane |
| **22 mm deep-pile carpet in the auditorium** | **floor surface** | **wheelchair only** |

The reading room is the control: 1.4 m doors, level threshold, generous turning
space, reachable by all four. Not every room here is broken, and the analysis has
to be able to say so.

### The floor itself

ADA 302 governs the material, not the geometry, and nothing in a
clearance-and-slope analysis can see it. Surfaces carry firmness, pile
height, opening width and rolling resistance; profiles carry tolerances
against those, so blocking is *derived* rather than enumerated.

The auditorium is carpeted at 22 mm where ADA 302.2 allows 13. It is level,
wide, generous, and compliant on every dimension a tape measure reaches — and
it stops a wheelchair and nothing else. The cane user walks across it; the
delivery robot rides over it on larger wheels; only the 100 mm front castors
of a manual chair dig in.

### Where it closes

Sweeping body width across the population range, holding a real wheelchair's
slope and step tolerance fixed:

| Body width | Rooms closed |
|---|---|
| 18–26 in | Gallery only — and never for a width reason |
| **28 in** | **+ Community Room, Accessible WC** |
| **32 in** | **+ Lift** — a standard powered wheelchair |
| 48 in | + Auditorium |

The gallery is closed at every width in the sweep, because it was never a width
problem: it is a 1:6.7 ramp and a four-riser stair.

Because the building is authored, an answer key exists — which is what makes the
recall figure possible and is the one thing no dataset-based approach can offer.

---

## Layout

```
core/
  schema.py      profiles, floor surfaces, result contract
  world3d.py     3D building, and its voxelisation
  navgrid.py     navmesh pipeline: erode, mask, label
  pathing.py     geodesic routing; least-resistance barrier routing
  sweep.py       blind geometric sweep of every rule, everywhere
  analysis.py    breaking point, barriers, population, remediation
viz/
  scene3d.py     exports out/scene.json
  detail3d.js    procedural surfaces, furnishing, figures
  app3d.js       3D walkthrough + choreography
  build3d.py     bundles everything into one self-contained file
```

`out/` is generated and gitignored. `legacy/` holds the earlier 2.5D build and
its three-layer auditor; nothing in the shipped pipeline imports it.

---

## Honest limits

- **Costs are illustrative** order-of-magnitude figures for demonstration, not
  quotes. They are labelled as such wherever they surface.
- **The population is a synthetic mixture**, not a survey dataset. It shows the
  *shape* of the exclusion curve, not a real population statistic.
- **Layer 2 telemetry is synthetic.** The schema accepts real dwell/backtrack
  signal from captured sessions; swapping it changes nothing downstream.
- **Turning space is evaluated per room** from the model's room schedule — the same
  list a BIM file carries. The defect manifest is never consulted.
- The cane profile is modelled at its full 42-inch sweep arc, which is
  conservative; a real cane user narrows their sweep through a doorway.

## Attribution

No external 3D assets, scene datasets, captured spaces, or game engine. All
geometry procedurally generated from seeded RNG; all textures painted procedurally
at load. Libraries: numpy, scipy. Rendering: three.js r161 (MIT), vendored.
Thresholds from the ADA 2010 Standards for Accessible Design, cited per violation.
Claude (Anthropic) used for code generation. No personal, identifiable, or
captured real-world data of any kind.
