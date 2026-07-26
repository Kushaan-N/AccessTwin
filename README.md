# Access-Twin

**Passing every ADA measurement and being reachable by a real body are different
properties. This measures the gap.**

Access-Twin generates a building, voxelises it, and drives four physically
constrained mobility profiles through it to find where geometry excludes bodies —
then localises each barrier, prices the repair, and scores itself against a
planted answer key it is never shown.

### ▶ Live: **https://access-twin.vercel.app**

The link opens on the **audit** — every issue, what fixes it, what that costs —
because that is the output. The two-minute walkthrough behind it is the evidence:
four bodies driven through the building, and everywhere one of them stopped.

| Entry point | Opens on |
|---|---|
| `access-twin.vercel.app` | the audit — 25 priced issues, free camera |
| `access-twin.vercel.app/#walkthrough` | the 2:00 film, from scene 1 |

No install, no sign-in, no backend. One self-contained 1.1 MB page.

---

## The hypothesis

> Geometric ADA compliance and actual traversability are different properties, and
> the gap between them is measurable automatically from spatial data.

### What the prototype demonstrates

1. **Regions exist that satisfy every clearance, slope and turning rule while being
   completely unreachable.** 215 m² is stranded from a wheelchair — the gallery
   (110.5 m²) and the community room (104.1 m²), both flawless inside. No
   clearance-based audit flags a room for being fine.
2. **The body width at which a space starts excluding people can be found by
   bisection, and it disagrees with a tape measure.** The route to the community
   room measures **47.2 in** of clear width and serves **27.6 in** once slope and
   level change are counted with it. The gallery also measures 47.2 in and admits
   **no body of any width**, because it was never a width problem.
3. **The best-scoring repair can be actively harmful.** The highest
   coverage-per-dollar candidate here — **3.27** points per $1k against the
   winner's **0.22**, fifteen times better — is rejected outright, because
   rebuilding the building that way takes floor from the wheelchair user it was
   meant to serve.

---

## Results (seed 7)

| Body | Floor reached | Destinations | Stranded |
|---|---|---|---|
| Walking adult | 100% | 5 / 5 | — |
| Wheelchair user | **63.2%** | 2 / 5 | 214.6 m² islanded |
| Cane user | 71.9% | 3 / 5 | 99.9 m² islanded |
| Delivery robot | 82.8% | 4 / 5 | 119.3 m² islanded |

The delivery robot passes through the 700 mm door that excludes the wheelchair.
The same building admits a machine and turns away a person.

**Detection: 13 of 13 planted defects recovered** by an analysis never told where
to look — alongside 99 emergent exclusions nobody planted, pinch points created by
where the furniture landed rather than by the architecture.

**Repair.** The optimiser's pick is **$4,512** (widen the 700 mm door), taking the
wheelchair from 63.2% to **73.9%** of the floor and the cane user from 71.9% to
**82.1%**, with no profile losing anything. Two candidates that scored better in
aggregate were rejected by the do-no-harm guard: one costs the wheelchair 0.9
points of floor, the other costs the walking adult a destination outright.

Across the whole worklist: **25 issues, $71,571**, of which **3 cost nothing** —
they are furniture, and moving them returns 102 m² of floor.

**58% of a sampled 200-person mobility population cannot reach every destination
in this building today.**

---

## How it works

The building is the source of truth and the analysis grid is *derived* from it:

```
typed solids (walls, ramps, stairs, furniture, soffits)
        │  voxelise, 5 cm
        ▼
floor height · free space · ceiling underside · surface finish
        │  erode by body radius, mask by climb / slope / headroom / finish
        ▼
per-profile navigable mask → connected components
```

That is the standard navmesh pipeline — the same heightfield Recast/Detour builds
from a Unity scene and habitat-sim builds from a scanned mesh. Point it at a
captured real building instead of a generated one and nothing downstream changes.

Two detectors run, and they are complementary rather than redundant.

**Geometric sweep.** Every ADA rule at every cell for every profile: clear width
along the circulation medial axis, running slope, level change, head clearance,
floor finish, turning space per room, and counter height. It catches what
*violates* — including defects that block nobody's route. 123 findings here.

**Embodied reachability.** Where a constrained profile's reachable set fails to
cover ground the baseline reaches, that is an exclusion. *The erosion is the
check.* It catches what *excludes*, and localises the barrier responsible — but it
reports only the cheapest barrier per route, so a second defect behind the first
is masked.

A planted defect counts as detected if either recovers it. Neither is ever shown
the answer key.

### Barrier localisation

Asked *what is in the way*, the model routes a body along a least-resistance path
over its own violation surface, each constraint normalised to its own limit. Where
free passage exists the path crosses nothing; where none exists it crosses the
single cheapest barrier — and names it. **The candidate repairs the optimiser
considers are discovered this way, never hand-listed.**

### Costing and verification

Repairs are selected by 0/1 knapsack over measured per-repair value, then the
selected set is **applied to the building and re-measured**, so the reported gain
is what rebuilding actually delivers rather than the sum of individual estimates.
The interaction gap between the two is reported. Any repair that costs a profile
a destination, or more than 0.25 points of floor, is rejected with a named reason.

---

## The building

A generated civic centre, 44 × 30 m, **257 solids across nine rooms**: an open
atrium with a café in it, a spine corridor, community room, auditorium, accessible
WC, lift, reading room, and a gallery raised 600 mm. The plan is deliberately open
— a corridor-and-cells building hides its access failures behind doors, whereas an
atrium fails in public, in the middle of the floor.

**Thirteen defects are planted**, every one a condition that occurs constantly in
practice and passes a plan check. The *Excludes* column is measured, not asserted.

| Defect | Type | Excludes |
|---|---|---|
| 700 mm community room door | clear width | wheelchair |
| 1200 mm door on a 200 mm threshold | level change | wheelchair, cane, robot |
| Gallery ramp at 1:6.7 | running slope | wheelchair, cane, robot |
| Four-riser stair, 150 mm | level change | all four |
| Unprotected 600 mm slab edge | level change | all four |
| WC with every fixture correct, 1300 mm circle | turning space | wheelchair |
| Lift car sized by capacity, 1600 × 1400 mm | turning space | wheelchair |
| Auditorium: 850 mm aisle, no designated space | clear width | wheelchair, cane |
| Duct bulkhead at 1950 mm | head clearance | cane |
| Screen hung at 1550 mm, projecting 350 mm | head clearance | cane |
| Café counter at 1050 mm, no lowered section | counter height | wheelchair |
| 860 mm gap between two benches | clear width | wheelchair, cane, robot |
| **22 mm deep-pile carpet in the auditorium** | **floor surface** | **wheelchair only** |

The reading room is the control: 1.4 m doors, level threshold, generous turning
space, reachable by all four. Not every room here is broken, and the analysis has
to be able to say so.

### The floor itself

ADA 302 governs the material, not the geometry, and nothing in a
clearance-and-slope analysis can see it. Surfaces carry firmness, pile height,
opening width and rolling resistance; profiles carry tolerances against those, so
blocking is *derived* rather than enumerated.

The auditorium is carpeted at 22 mm where ADA 302.2 allows 13. It is level, wide,
generous, and compliant on every dimension a tape measure reaches — and it stops a
wheelchair and nothing else. The cane user walks across it; the delivery robot
rides over it on larger wheels; only the 100 mm front castors of a manual chair
dig in.

### Where it closes

Sweeping body width across the population range, holding a real wheelchair's slope
and step tolerance fixed:

| Body width | Rooms closed |
|---|---|
| 18–26 in | Gallery only — and never for a width reason |
| **28 in** | **+ Community Room, Accessible WC** |
| **32 in** | **+ Lift** — a standard powered wheelchair |
| 48 in | + Auditorium |

The gallery is closed at every width in the sweep because it was never a width
problem: it is a 1:6.7 ramp and a four-riser stair.

Because the building is authored, an answer key exists — which is what makes the
recall figure possible, and is the one thing no dataset-based approach can offer.

---

## Run it

```bash
pip install numpy scipy

python3 core/world3d.py          # build the model, print the defect manifest
python3 viz/scene3d.py --seed 7  # full analysis    -> out/scene.json
python3 viz/build3d.py           # bundle one page  -> out/index.html
open out/index.html
```

Python 3.10+. No GPU, no engine, no dataset, no network. The full analysis runs in
a few seconds on a laptop; a single profile rebake is about 2 ms.

`./deploy.sh` rebuilds, runs the sanity checks, deploys to Vercel and then
verifies the *served* page rather than the upload. `./deploy.sh --local` rebuilds
and serves on `:8899`; `--preview` deploys to a preview URL.

### Controls

The film runs **2:00** and loops.

| | |
|---|---|
| `Space` | pause / resume |
| `R` | restart |
| `←` `→` | step scenes |
| `1`–`9` | jump to a scene |
| `I` | toggle the audit |
| `Esc` | close a panel, or leave the audit |
| drag / scroll | orbit, zoom |

Two scenes are interactive: drag the body-width slider in *Where does it close?*,
and click any marker in *Every blockage, priced*. In *Fix it, and walk it again* a
button applies the optimiser's repair, and the same body walks the route again
through the rebuilt building.

**The audit** is where the page opens. Every finding at once, free camera, a
filterable list grouped by what it takes to action — *today at no cost*, *minor
works*, *capital works* — and a clickable marker on each. Selecting one flies the
camera to it and shows the remedy and the price. Any issue can be issued as a
work order carrying its location, ADA clause, scope, cost and who it excludes.
`Copy` exports the worklist as CSV.

It is usable without the 3D view: a skip link leads to a text version of every
finding, each scene is announced to a live region, `prefers-reduced-motion` is
honoured, and a WebGL failure falls back to the text findings rather than a black
rectangle.

> The walkthrough is driven by `requestAnimationFrame`, which browsers suspend in
> a background tab. Keep the window foreground while presenting.

---

## Layout

```
core/
  schema.py      profiles, floor surfaces, ADA citations, result contract
  world3d.py     3D building, and its voxelisation
  navgrid.py     navmesh pipeline: erode, mask, label
  pathing.py     geodesic routing; least-resistance barrier routing
  sweep.py       blind geometric sweep of every rule, everywhere
  analysis.py    breaking point, barriers, population, remediation, knapsack
viz/
  scene3d.py     runs the analysis, exports out/scene.json
  app3d.js       3D walkthrough, audit mode, choreography
  detail3d.js    procedural surfaces, furnishing, figures
  shell3d.html   page chrome, panels, work-order dialog
  build3d.py     bundles everything into one self-contained file
deploy.sh        rebuild -> check -> deploy -> verify the served page
```

`out/` is generated and gitignored. `legacy/` holds the earlier 2.5D build and a
three-layer consensus auditor including behavioural telemetry; **nothing in the
shipped pipeline imports it**, and none of the numbers above depend on it.

---

## Honest limits

- **One floor plan.** This is the weakest claim in the project. The seed varies
  café furniture and nothing else — verified: all 210 non-café solids and all 13
  planted defects are byte-identical between seed 7 and seed 42. The detectors are
  generic (ADA rules swept over a voxel grid, plus pathfinding) and are never shown
  the answer key, but **multi-building robustness has not been demonstrated.**
- **Costs are illustrative** order-of-magnitude figures for demonstration, not
  quotations. They are labelled as such wherever they surface. The ranking and the
  ratios are the claim; the dollars are not.
- **The population is a synthetic mixture**, not a survey dataset. It shows the
  *shape* of the exclusion curve, not a real population statistic.
- **Only two of the three detection layers ship.** The behavioural-telemetry layer
  and the consensus auditor live in `legacy/` and are not on the shipped path.
- **Turning space is evaluated per room** from the model's room schedule — the same
  list a BIM file carries. The defect manifest is never consulted.
- **The cane profile is modelled at its full 42-inch sweep arc**, which is
  conservative; a real cane user narrows their sweep through a doorway.
- **Barrier localisation reports one barrier per route.** A second defect behind
  the first is masked until the first is repaired.

## Attribution

No external 3D assets, scene datasets, captured spaces, or game engine. All
geometry procedurally generated from seeded RNG; all textures painted procedurally
at load. Libraries: numpy, scipy. Rendering: three.js r161 (MIT), vendored.
Thresholds from the ADA 2010 Standards for Accessible Design, cited per violation.
Claude (Anthropic) used for code generation. No personal, identifiable, or
captured real-world data of any kind.
