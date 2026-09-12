# Folded Panels — how it works, what the research says, how it is tested

## Problem
Take a closed triangle mesh (a head, an animal, anything) and cut it into flat panels that fold back into the shape.
Two sub-problems: **unfolding** (which edges become folds, which become seams — a spanning tree of the mesh's dual
graph, with the constraint that the flattened panel must not overlap itself) and **joining** (what goes on the seams).
Finding an overlap-free single-patch unfolding is NP-complete in general [Haenselmann 2012] and does not always exist
(Dürer's problem); every practical tool therefore uses heuristics plus search, and cuts into several patches when it
has to.

## What the literature does (2004 → 2024) and what we took from it
| Paper | Idea | Used here |
|---|---|---|
| Mitani & Suzuki, *Making papercraft toys from meshes using strip-based approximate unfolding*, SIGGRAPH 2004 | approximate the mesh by triangle strips (no interior vertices) and unfold the strips; strips can be crafted by bending | `strategy=strip`: edges perpendicular to the model's main axis are attached first, which grows long bendable strips |
| Straub & Prautzsch, *Creating optimized cut-out sheets for paper models from meshes*, 2011 | initial folding tree → remove overlaps by adding cuts → glue tabs along all cuts → 2D bin packing | the same pipeline: greedy tree, overlap ⇒ new cut (seam), tabs on one side only, outline nesting |
| Takahashi et al., *Optimized topological surgery for unfolding 3D meshes*, CGF 2011 | genetic algorithm over spanning trees for a single patch, optimising sheet usage and patch balance | the objective: among candidate unfoldings keep the fewest panels, then the most compact (area / bounding rectangle) |
| Haenselmann et al., *Optimal strategies for creating paper models from 3D objects*, 2012 | cut-order strategies compared; avoid overlaps and very small angles; NP-complete | multi-start: several orderings (`auto`) instead of one |
| Korpitsch et al., *Simulated annealing to unfold 3D meshes and assign glue tabs*, WSCG 2020 | MST + simulated annealing for a single overlap-free patch; glue tabs not on every edge; fast under 400 faces | tabs on one side; the 300–400 face default; SA is the documented upgrade path |
| Zawallich, *Unfolding polyhedra via tabu search*, Visual Computer 2024; *Unfolding via progressive mesh approximation* 2024; *…via surface flows*, CGF 2024 | tabu search over the tree; let the mesh approximation change while unfolding | `simplify`, `round`, `smooth` as unfoldability aids (fewer, fatter triangles unfold better) |
| Bhargava et al., *Mesh simplification for unfolding*, CGF 2024 | modify the shape (vertex moves, edge collapses) until an overlap-free single patch exists | same idea, manual: the Modify-form controls; automatic shape relaxation is on the roadmap |
| Xi & Lien, *Learning to segment and unfold polyhedral mesh from failures*, C&G 2016 | couple segmentation with unfolding; segments learned from failed unfoldings | `max_faces` / `separate` as explicit segmentation; failure-driven segmentation is a roadmap item |
| Liu et al., *Optimal design of flat patterns for 3D folded structures by unfolding with topological validation*, CAD 2007 | enumerate spanning trees, topological overlap test, compactness ranking (sheet metal / packaging) | compactness ranking of candidates |
| O'Rourke, *Unfolding convex polyhedra via radially monotone cut trees*, 2016 | greedy radially-monotone cut trees rarely overlap on convex shapes | the greedy grows from the largest face outward — radially, in spirit |
| Sohrabi et al., *Simplification and unfolding of 3D mesh models: review of existing tools*, Procedia CIRP 2021 | Pepakura / Blender / SketchUp compared: simplification quality matters more than the unfolder | quadric decimation (`fast-simplification`) before unfolding |

## Unfolding (core/unfold.py)
Greedy spanning tree with a priority per edge:
1. Every face gets its own 2D frame (origin = vertex 0, z = outward normal), so its triangle is seen from outside.
2. Start a panel at the largest unvisited face. Keep a heap of its boundary edges ordered by the strategy's weight
   (`flat`: dihedral angle; `strip`: alignment with the model's main axis; `area`: neighbour size).
3. Pop the best edge; lay the neighbour flat across it (a 2D rigid transform that maps the shared edge onto its
   image). Accept it if the union's area equals the sum (no overlap — tested on the union, because GEOS' intersection
   misses fans that wrap past 360° at saddle vertices) and the panel still fits the sheet. Otherwise the edge becomes
   a seam.
4. Repeat until nothing can be attached; start the next panel.
5. `auto` runs flat, strip, area and two randomised flat orders, and keeps the fewest panels / most compact result.

`separate=True` skips step 3: every triangle is a panel. That is always feasible for any closed mesh —
cavities, undercuts and handles just become more seams — which is why it is the safe default for complex organic
shapes and for rib / laced joints. `max_faces` caps panel size.

Every mesh edge is exactly one of: fold (inside a panel, exported on the SCORE layer, mountain solid / valley
dashed, dotted when `perforate`) or seam (numbered; the number is engraved beside the joint on **both** panels so
the mating edges can be found on the cut sheet).

Complexity: O(faces × panel size) shapely unions per run; 300 faces ≈ 1 s per strategy.

## Joints (core/modes/folded.py)
| joint | panel A | panel B | extra part | use |
|---|---|---|---|---|
| seam | — | — | — | glue / sew (paper) |
| tab, multitab, diamond, ticked, gear | tab(s) unioned onto the edge, score at the base | — | — | glue tabs (paper, card) |
| tongue | tab with a second bend at `inset` | slot at `inset` | — | no glue |
| puzzle | round-head tab | matching keyhole | — | no glue |
| rivet | 1 hole per `spacing` at `inset` | same, aligned | — | rivets, screws |
| laced | ≥ 2 holes per edge | same, aligned | — | lacing, zip ties, wire, thread (separate faces) |
| strip | holes | holes | rounded strip with mirrored holes, score on its centreline, label carries the fold angle | cardboard / steel: the strip is bent to the angle and bolted through both panels |
| rib | slot ⊥ to the seam at `inset` | slot | flat angle rib: two arms at the interior dihedral angle, each with a tab through the slot; label carries the angle | sheet metal: ribs slot in from the back and fix the panels at the right angle |

Sizes adapt to the triangle: holes sit at ≤ 20 % of the triangle height from the seam and are ≤ 30 % of it wide;
rib slots start at ≤ 10 % and end at ≤ 32 %, so three ribs (one per edge of a separate triangle) never meet.
Every hole / slot is also checked against the cuts already in its face; what was shrunk or skipped is reported per
panel with seam numbers. Hole positions along an edge are parametrised from the same vertex on both sides, so they
line up when folded. Glue tabs, tongues and puzzle heads are shown in the 3D view folded flat against the inside of
the panel they attach to; strips and ribs are shown in place.

Ribs are built in a frame whose x is "into panel A along its surface", y is "into the model", z is the edge
direction, so the arm directions are read straight from the 3D normals — reflex (concave) edges get an outward
bracket automatically.

## Tests (tests/test_unfold.py, working-files/smoke4.py)
For cube, egg, torus, bowl (cavity), igea head (separate faces), Spot the cow (legs = undercuts), homer:
- **refold**: every layout triangle is congruent to its 3D face and both faces of every fold share the edge in the
  layout (max deviation < 1e-3 mm) — the unfolding is rigid.
- panel area == mesh area; union area == sum of triangle areas (no self-overlap).
- folds + seams == all interior edges; faces == panels' faces; the cube net is 1 panel / 7 seams with every strategy.
- one joint part per seam for strip/rib, angle label 0–360; rib on a cube edge is 90°.
- separate faces on a cube: ≥ 2 holes per seam side; on a 150-face egg with default sizes: > 100 ribs.
- no two holes overlap on a 400-face head in separate mode; folded tabs add facets for the 3D view.
- nothing "does not fit the sheet".

Run: `uv run python tests/test_unfold.py`, `uv run python working-files/smoke4.py`.

## Roadmap for this technique
1. Simulated annealing / tabu search over the spanning tree when `auto` still leaves many panels (Korpitsch, Zawallich).
2. Shape relaxation until a single patch unfolds (Bhargava 2024) — for paper models where fidelity can give a little.
3. Click-to-add / remove seams in the 3D view (Pepakura-style manual control).
4. Tab placement by stability, not on every seam (Korpitsch 2020).
