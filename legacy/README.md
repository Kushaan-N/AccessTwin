# Legacy — the 2.5D plan-view build

These modules were the first working version: a seeded 2.5D world, a
three-layer consensus auditor (geometric rules, behavioural telemetry,
embodied reachability) and an animated plan-view demo.

They are **not** on the path the shipped 3D walkthrough runs. That
pipeline is:

    world3d -> navgrid -> pathing -> sweep -> analysis -> scene3d -> build3d

They are kept because two of them contain work the live build does not
carry, and it would be dishonest to describe the project as having
capabilities that only live here:

- `telemetry.py` — Layer 2. Hesitation-weighted synthetic trajectories,
  and the raster the auditor samples to decide whether a geometric
  finding is behaviourally corroborated. The shipped build runs the
  geometric sweep and embodied reachability, not this.
- `auditor.py` — the consensus logic that combines all three layers and
  reports disagreement rather than hiding it.
- `worldgen.py`, `run_analysis.py`, `frames.py`, `template.html` — the
  2.5D world and its plan-view renderer, superseded by `world3d.py` and
  the three.js walkthrough.

To run the old build:

    cd legacy && python3 run_analysis.py --seed 7 && python3 frames.py
