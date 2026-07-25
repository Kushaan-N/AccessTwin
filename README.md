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
   completely unreachable.** In the generated building, 142 m² is stranded from a
   wheelchair — a community room and a gallery, both flawless inside.
2. **The exact body width at which a space begins excluding people can be found by
   bisection**, and it disagrees with what a tape measure reports. The route to the
   gallery measures 94 inches of clear width and admits *no body of any width*,
   because it is a slope-and-step problem, not a width problem.
3. **The highest-value remediation is frequently not the obvious one — and the
   best-scoring one can be actively harmful.** The repair with the best coverage
   per dollar is rejected here, because rebuilding the building that way costs the
   wheelchair a destination it has today.

---

## Results (seed 7)

| Body | Floor reached | Destinations | Stranded |
|---|---|---|---|
| Walking adult | 567.7 m² (100%) | 4 / 4 | — |
| Wheelchair user | 370.4 m² (65.2%) | 2 / 4 | **141.8 m²** |
| Cane user | 430.5 m² (75.8%) | 2 / 4 | 52.8 m² |
| Delivery robot | 451.9 m² (79.6%) | 3 / 4 | 88.4 m² |

The delivery robot passes through the 700 mm door that excludes the wheelchair.
The same building admits a machine and turns away a person.

**Detection: 8 of 8 planted defects recovered**, by an analysis that is never told
where to look, plus 9 emergent exclusions nobody planted — pinch points created by
where the furniture landed rather than by the architecture.

**Repair:** with a $6,000 budget the optimum is $4,512 (widen the 700 mm door),
returning the wheelchair from 65.2% to 75.2% of the floor and the cane user from
75.8% to 85.1%. A $4,204 repair scored 1.1 points per $1k against 0.2 and was
still rejected — rebuilt that way, the wheelchair loses a destination.

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

The demo self-runs and loops. Drag to orbit, scroll to zoom, `Space` restarts,
`←`/`→` step scenes, `P` pauses.

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

**Layer 1 — geometric.** Every ADA rule at every cell for every profile: clear
width along the circulation medial axis, running slope, level change, head
clearance, and turning space per room.

**Layer 2 — behavioural.** Hesitation-weighted telemetry. Where a goal is
unreachable an agent routes as close as it can, dwells, and backtracks, producing
a hesitation hotspot on the feature that excluded it.

**Layer 3 — embodied.** Where a constrained profile's reachable set fails to cover
ground the baseline reaches, that is an exclusion. *The erosion is the check.*

A finding confirmed by more than one layer is high-confidence. Disagreement is
reported, not hidden — an embodied exclusion with no geometric violation is the
interesting case.

### Barrier localisation

Asked *what is in the way*, the model routes a body along a least-resistance path
over its own violation surface, where each constraint is normalised to its own
limit. Where free passage exists the path crosses nothing; where none exists it
crosses the single cheapest barrier — and names it. **The candidate repairs the
optimiser considers are discovered this way, never hand-listed.**

---

## The building

A generated civic centre, 32 × 22 m: entrance, lobby, café, spine corridor,
community room, accessible WC, and a gallery raised 600 mm. Eight defects are
planted, every one a condition that occurs constantly in practice and passes a
plan check.

| Defect | Type | Excludes |
|---|---|---|
| 700 mm community room door | clear width | wheelchair, cane |
| 1200 mm door on a 200 mm threshold | level change | wheelchair, robot |
| Gallery ramp at 1:6.7 | running slope | wheelchair, robot, cane |
| Four-riser stair, 150 mm | level change | wheelchair, robot |
| Unprotected 600 mm slab edge, 8.9 m | level change | all wheeled |
| WC with every fixture correct, 1300 mm circle | turning space | wheelchair |
| Duct bulkhead at 1950 mm | head clearance | cane |
| 860 mm gap between two benches | clear width | cane |

Meeting Room B is the control: 1.4 m doors, level threshold, generous turning
space, reachable by all four. Not every room here is broken, and the analysis has
to be able to say so.

Because the building is authored, an answer key exists — which is what makes the
recall figure possible and is the one thing no dataset-based approach can offer.

---

## Layout

```
core/
  schema.py      profiles + result contract (single source of truth)
  world3d.py     3D building, and its voxelisation
  navgrid.py     navmesh pipeline: erode, mask, label
  pathing.py     geodesic routing; least-resistance barrier routing
  sweep.py       blind geometric sweep of every rule, everywhere
  analysis.py    breaking point, barriers, population, remediation
  telemetry.py   Layer 2 behavioural signal
  auditor.py     three-layer consensus audit
viz/
  scene3d.py     exports out/scene.json
  detail3d.js    procedural surfaces, furnishing, figures
  app3d.js       3D walkthrough + choreography
  build3d.py     bundles everything into one self-contained file
```

`out/` is generated and gitignored.

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
