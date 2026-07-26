# Submission — prefilled

Paste-ready answers for https://forms.gle/AgyhxvcXJGFNj9PC8

Every figure below is read from `out/scene.json` at seed 7. If you regenerate,
re-check them — `README.md` carries the same numbers.

---

**Project title**
Access-Twin

**Track**
Track 3 — Free Track

**Engine**
Custom Python simulation (numpy/scipy) with a three.js renderer. No game engine.

**Judge-accessible build link**
https://access-twin.vercel.app

Opens on the audit — every issue, priced. Append `#walkthrough` for the
two-minute film. No install, no sign-in, one self-contained page.

---

**One-sentence pitch**

Access-Twin generates a building and runs four physically constrained mobility
profiles through it to prove that passing every ADA measurement doesn't mean a
real body can get through — locating exactly where, for whom, and what the
cheapest fix is.

**Hypothesis**

Geometric ADA compliance and actual traversability are different properties, and
the gap between them is measurable automatically from spatial data.

**What it proves**

Regions exist that satisfy every clearance, slope and turning rule while being
completely unreachable — **215 m² of this building is stranded from a
wheelchair**, in two rooms that are flawless inside: the gallery (110.5 m²) and
the community room (104.1 m²). No clearance-based audit flags a room for being
fine.

The body width at which a space begins excluding people can be found by
bisection, and it disagrees with what a tape measure reports. The route to the
community room measures **47.2 inches** of clear width and serves **27.6** once
slope and level change are counted with it; the route to the gallery measures the
same 47.2 inches and admits **no body of any width**, because it was never a
width problem — it is a 1:6.7 ramp and a four-riser stair.

And the highest-value remediation is frequently not the obvious one. The
candidate with the best coverage-per-dollar here — **3.27** points per $1,000
against the winner's **0.22**, fifteen times better — is rejected outright,
because rebuilding the building that way takes 0.9 points of reachable floor away
from the wheelchair user it was meant to serve. A second candidate is rejected
for costing the walking adult a destination it has today.

Because we generate the space, we report detection recall against planted ground
truth: **13 of 13 defects recovered** by an analysis never told where to look,
plus **99 emergent exclusions** nobody planted, created by where the furniture
landed rather than by the architecture.

**Why does this matter? (Q&A one-liner)**

Every accessibility audit today is a clipboard and a tape measure checking rules
one at a time. This checks whether a body can actually get through — and it works
for delivery robots and mobility bases too, not just wheelchairs.

---

**Setup / controls / expected outcome**

Open the link. It lands on the audit; one button starts the two-minute
walkthrough, which loops. No input required.

Drag to orbit, scroll to zoom. `Space` pauses and resumes, `R` restarts, `←`/`→`
step scenes, `1`–`9` jump, `I` toggles the audit, `Esc` closes a panel.

Expected outcome: four mobility profiles walk the same generated civic building
toward five destinations. The walking adult reaches all five; the wheelchair user
reaches two and is stranded from 215 m²; the cane user reaches three, stopped by
a 1950 mm bulkhead at the accessible WC; the delivery robot reaches four, passing
through the 700 mm door that excluded the wheelchair.

Three scenes are interactive. Drag the body-width slider to watch rooms close one
at a time. Press the button in *Fix it, and walk it again* — the optimiser's
repair is applied to the building, the same body walks the route again through
the rebuilt world, and the reach figures move from 63.2% to 73.9%. Click any
marker in *Every blockage, priced* to see its verdict and cost. In the audit,
any issue can be issued as a work order carrying its location, ADA clause, scope,
cost and who it excludes.

Fully reproducible from a seed:
`python3 viz/scene3d.py --seed 7 && python3 viz/build3d.py`

**Device requirements**

Any laptop. Python 3.10+ with numpy and scipy to regenerate; a WebGL browser to
view. No GPU. Full analysis runs in a few seconds.

---

**External assets, datasets and AI tools used**

No external 3D assets, scene datasets, captured spaces, or game engine. All
building geometry is procedurally generated from seeded RNG; all surface textures
are painted procedurally into a canvas at load, and all furniture and figures are
assembled from primitives — the page is a single self-contained file with no
network requests.

Libraries: numpy, scipy (ndimage, sparse, csgraph). Rendering: three.js r161
(MIT), vendored unmodified into the repo.

The navigability analysis is a reimplementation of the standard Recast/Detour
navmesh pipeline (voxelise to a heightfield → erode by agent radius → mask by
climb, slope and headroom → connected components), operating on a voxelisation of
our own 3D building. Thresholds are from the ADA 2010 Standards for Accessible
Design, cited per violation (§404.2.3 clear width, §405.2 ramp slope, §303.2
level change, §304.3.1 turning space, §307.4 head clearance, §302.2 carpet pile,
§904.4.1 counter height).

Claude (Anthropic) used for code generation during the build window.

No personal, identifiable, or captured real-world data of any kind.

---

**Repo / notes**

Branch `access-twin`. `out/` is generated and gitignored; rebuild with the two
commands above. `./deploy.sh` rebuilds, checks, deploys and verifies the served
page.

Stated plainly, because a judge will ask:

- **Costs are illustrative** order-of-magnitude figures for demonstration, not
  quotations, and are labelled as such wherever they surface. The ranking and the
  ratios are the claim; the dollars are not.
- **The mobility population is a synthetic mixture**, used to show the shape of
  the exclusion curve rather than as a real population statistic.
- **One floor plan.** The seed varies café furniture and nothing else — all 210
  non-café solids and all 13 planted defects are identical between seeds. The
  detectors are generic and never see the answer key, but multi-building
  robustness has not been demonstrated.

---

## Three strongest screenshots

Pause with `Space` and capture:

1. **The finding** (scene 6) — the exclusion overlay with both stranded rooms
   called out: "110 m² stranded / Gallery" and "104 m² stranded / Community Room".
2. **Wheelchair · community room** (scene 3) — the wheelchair stopped at the door
   with the callout in frame: `28" clear — needs 32" — ADA 404.2.3`.
3. **The audit** — the priced worklist beside the plan, with a work order open on
   one issue showing its ADA clause, scope, cost and who it excludes.

## 60–90 s backup video — shot list

Record in one take from `access-twin.vercel.app/#walkthrough`; the film is 2:00,
so either let it run or cut as below.

| Time | Shot | Line |
|---|---|---|
| 0:00 | Establishing orbit | "A generated civic centre, drawn to code. Thirteen access defects are planted in it, and every one passes a plan check." |
| 0:10 | Walking adult | "Four bodies are about to walk it — only their dimensions differ. A walking adult reaches all five destinations. This is the building as its drawings describe it." |
| 0:22 | Wheelchair stops at the door | "Same route, 32-inch wheelchair. It stops at the door — 28 inches clear where 32 are required. The wider entrance beside it sits on a 7.9-inch threshold. Two ways in, neither usable." |
| 0:36 | Width slider | "Sweep the body width and the rooms switch off one at a time. At 32 inches — a standard powered wheelchair — the lift goes dark." |
| 0:46 | Islands reveal | "Those two regions are flawless inside — wide, flat, turning circles to spare — and completely unreachable. No clearance-based audit flags a room for being fine." |
| 0:58 | Carpet | "Twenty-two millimetre carpet. Level, wide, compliant on every dimension a tape measure reaches — and it stops a wheelchair and nothing else." |
| 1:08 | Delivery robot | "A 26-inch robot goes straight through the door that excluded the wheelchair. The building admits a machine and turns away a person." |
| 1:18 | Repair scene, press the button | "Every repair is scored by rebuilding the building and re-running the population. This one costs $4,512 and returns the wheelchair from 63 to 74 percent. The candidate that scored fifteen times better was rejected — it takes floor away from the person it was meant to help." |
| 1:32 | Recall | "Thirteen defects planted, thirteen recovered, by an analysis never told where to look." |
