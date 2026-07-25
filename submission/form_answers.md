# Submission — prefilled

Paste-ready answers for https://forms.gle/AgyhxvcXJGFNj9PC8

---

**Project title**
Access-Twin

**Track**
Track 3 — Free Track

**Engine**
Custom Python simulation (numpy/scipy) with a three.js renderer. No game engine.

**Judge-accessible build link**
https://claude.ai/code/artifact/131f14af-2e9c-4bf4-99b3-79452a60593a

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
completely unreachable — 142 m² of this building is stranded from a wheelchair,
in two rooms that are flawless inside. The body width at which a space begins
excluding people can be found by bisection, and it disagrees with what a tape
measure reports: the route to the gallery measures 94 inches of clear width and
admits no body of any width, because it is a slope-and-step problem rather than a
width problem. And the highest-value remediation is frequently not the obvious
one — here the repair with the best coverage-per-dollar is rejected outright,
because rebuilding the building that way costs the wheelchair a destination it
has today.

Because we generate the space, we report detection recall against planted ground
truth: 8 of 8 defects recovered by an analysis never told where to look, plus 9
emergent exclusions nobody planted, created by where the furniture landed rather
than by the architecture.

**Why does this matter? (Q&A one-liner)**

Every accessibility audit today is a clipboard and a tape measure checking rules
one at a time. This checks whether a body can actually get through — and it works
for delivery robots and mobility bases too, not just wheelchairs.

---

**Setup / controls / expected outcome**

Open the link; the demo starts automatically and loops, no input required. Drag
to orbit, scroll to zoom, SPACE restarts, arrow keys step scenes, P pauses.

Expected outcome: four mobility profiles walk the same generated civic building.
The walking adult reaches all four destinations; the wheelchair user reaches two
and is stranded from 142 m²; the cane user is stopped by a 1950 mm bulkhead at
the accessible WC; the delivery robot passes through the 700 mm door that
excluded the wheelchair. The walkthrough then reports which regions are
geometrically compliant yet unreachable, where each barrier is and what it
measures, which repair buys the most access per dollar, and how many of the
planted defects the analysis recovered unprompted.

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
level change, §304.3.1 turning space, §307.4 head clearance).

Claude (Anthropic) used for code generation during the build window.

No personal, identifiable, or captured real-world data of any kind.

---

**Repo / notes**

Branch `access-twin`. `out/` is generated and gitignored; rebuild with the two
commands above.

Illustrative figures are labelled as such: remediation costs are
order-of-magnitude estimates for demonstration, not quotes, and the mobility
population is a synthetic mixture used to show the shape of the exclusion curve
rather than a real population statistic.

---

## Three strongest screenshots

1. **The finding** — the exclusion overlay with the two stranded rooms called out
   ("85 m² stranded / Gallery", "56 m² stranded / Community Room").
2. **Wheelchair · community room** — the wheelchair stopped at the 700 mm door,
   route ribbon turning red at the point of failure.
3. **Exclusion map** — the whole floor coloured by how many of the four bodies can
   stand on each square metre.

## 60–90 s backup video — shot list

| Time | Shot | Line |
|---|---|---|
| 0:00 | Establishing orbit | "A generated civic centre, drawn to code. Eight access defects are planted in it, and every one passes a plan check." |
| 0:12 | Walls drop to section | "Four bodies are about to walk it. Only their dimensions differ." |
| 0:20 | Walking adult | "A walking adult reaches every room. This is the building as its drawings describe it." |
| 0:32 | Wheelchair stops at the door | "Same route, 32-inch wheelchair. It stops at the door — 28 inches clear where 32 are required. The wider entrance beside it sits on a 7.9-inch threshold. Two ways in, neither usable." |
| 0:46 | Islands reveal | "Those two regions are flawless inside — wide, flat, turning circles to spare — and completely unreachable. No clearance-based audit flags a room for being fine." |
| 0:58 | Cane user at the bulkhead | "A cane sweeps 42 inches. It meets a bulkhead at 1950. The accessible WC excludes two different people for two entirely different reasons." |
| 1:08 | Delivery robot through the door | "A 26-inch robot goes straight through the door that excluded the wheelchair. The building admits a machine and turns away a person." |
| 1:18 | Repair scene | "Every repair is scored by rebuilding the building and re-running the population. The best-scoring one is rejected — it costs the wheelchair a destination." |
| 1:28 | Recall | "Eight defects planted, eight recovered, by an analysis never told where to look." |
