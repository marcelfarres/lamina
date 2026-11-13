# Folded Panels — how it works, what the research says, how it is tested

## Problem
Take a closed triangle mesh (a head, an animal, anything) and cut it into flat panels that fold back into the shape.
Two sub-problems: **unfolding** (which edges become folds, which become seams — a spanning tree of the mesh's dual
graph, with the constraint that the flattened panel must not overlap itself) and **joining** (what goes on the seams).
The mesh does not have to be closed: panels are cut from the surface itself, so in folded mode `plan.py` never mends
it. A clothing pattern, a mask or a shell with a neck hole is panelled around its boundary — those edges are nobody's
seam and carry no joints — while every other technique, which needs a solid to section, is mended as before.
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

## Which face is up, and how thick a sheet can fold
The sheet's outer face lies on the model's surface and its thickness goes inwards, so the outside of the built model
is one surface and keeps the model's size. Every fold closes on one face: the inside of a mountain (convex) fold, the
outside of a valley (concave) fold.

`score side` picks the face that is up on the cutter, and so the face that carries the scores and the seam numbers.
`inside` (the default) mirrors the net: the scores and numbers are inside the model and the outside stays clean.
`outside` lays the net as seen from outside, for a paper model printed on its outer side. Mountain and valley are
read from the face that is up: seen from inside, a convex edge is a valley fold.

Folded by an angle θ, a sheet of thickness t gives up t·tan(θ/2) of the closing face on each side of the fold. A
triangle keeps some of that face while Σ dᵢ·Lᵢ ≤ 2·area over its fold edges (dᵢ is what edge i gives up, Lᵢ its
length; a point's distance to edge i is 2·area·λᵢ/Lᵢ in barycentric coordinates). Past that, the folds around the
face meet and it cannot be folded to the model's shape: on a curve this happens when the sheet is thicker than the
curve's radius, a little sooner where the faces are narrow. Each panel says how many of its folds cannot close. The
check runs only when the material folds at all (the material check comes first).

## Printed panels: a groove at every fold
A printed material (PLA, PETG) does not fold along a score. Printed, the panel can be thick and still fold: with
`hinge` above 0 every fold gets a V groove on the face that closes, cut down to a skin `hinge` thick (the living
hinge) with a flat bottom `hinge w` wide. The walls turn about the skin and meet when each has turned
atan(half the opening / the depth), so the groove opens 2 · (t − hinge) · tan(bend / 2) wide at the face (never
narrower than its flat bottom) and the fold stops at the model's angle. The flat bottom lies inside that opening:
added to it, as the first version did, a 90° fold in 2 mm closed at 97° and a 45° fold at 57°. `fold stop` moves
the stop a few degrees past or short of the model's angle, to tune a printer. With
the plain `seam` joint each seam edge gets the half of that groove on its own panel (a mitre): the panels meet
face to face, with room for glue. Mountain folds are grooved from the face up on the bed, valley folds from the
bed side. Edges between faces in one plane get no groove. The grooves travel in the plan with each piece (`vees`)
and `core/solid.py` cuts them from the printed part; the browser build has no boolean engine and prints plain parts.
The example `fold_test` (48 × 48 × 32 mm, 2 mm PETG) carries 45°, 76°, 80°, 90° and 104° folds and a valley edge.

## Stiff sheet: seams meet at the inside edges
Two square-cut panels that both reach the model's edge occupy the same corner on every outward (convex) seam: a
t × t square at 90°. Paper gives; metal, wood and acrylic do not, and the part cannot close. With `edge fit` =
inner (the default) each outward seam edge is cut back by t · tan(bend / 2), so the inside edges of the two
panels meet and the gap is on the outside. Holes, slots and seam numbers are measured from the new edge. Inward
seams need nothing: their material moves apart. Joints with a tab or loop on the edge are not cut back, and
printed panels are mitred instead (above). `outer` keeps the edges on the model's edge. A flat face of several
triangles is cut back as one: the triangles that touch the edge only at its ends lose their corner tip too.

`through` cuts only one panel of each outward seam, the one with more room, until it clears the other's inside
face: t · sin(bend) up to a right angle, t · tan(bend / 2) past it. The other runs to the model's edge, so the
outside closes (fully at 90°) and one sheet shows its edge. Seam, rivet and laced joints; strip and rib use inner.

Faces that share only a corner point are handled after the edges (`corners`): each pair's solids are intersected
(manifold3d) and what they share is cut from the bigger face, seen along its normal. On a saddle the tip of one
face otherwise lies inside the sheet of another. Without manifold3d (the browser build) the tips stay.

What is left presses into the next panel: t · tan(bend / 2) less the cut-back (capped at 0.4 of the face's height,
so a sliver keeps its middle; nothing with a tab joint). `SQUISH` in `core/modes/folded.py` gives the share of the
thickness each material can crush at an edge (paper, card, cardboard 1; foam and leather less; metal, wood and
hard plastic 0). Past it the panel warns, with the depth. A material not in the table is not checked.
Measured on the examples in 3 mm steel, every face its own panel, by intersecting the panels' solids
(working-files, 2026-11-13): cube, pyramid, wedge and fold_test go from 18–77 colliding pairs to 0; fold_lamp 204
to 1 (1 mm³); egg 530 to 1; torus 359 to 54 (99 mm³ in all); cow 340 to 70; bowl 378 to 41. What remains is at
saddle vertices, where panels that share only a corner meet, and on slivers the cap protects. Not yet handled.

## Windows
`window` opens every face with a hole of its own shape, for a lamp shade or a lantern. The frame left around it is
what the share asks for and never less than 1.25 × the minimum feature width, plus what the face's grooves or
cut-back edges take, plus the reach of the joint's holes or slots. A face too small for that stays whole.
The example `fold_lamp` uses it: a twisted, swelling tube of 72 triangles, printed in 2 mm PETG on one plate.

## The fold slider
Each panel face remembers the face it was unfolded from (`Panel.parent`). The plan gives every facet a `hinge`:
its parent facet, the fold line on the model (a point and a direction) and the turn that lays it flat beside the
parent. The 3D view's `fold` slider turns every face about its fold line by the share left, parents first: 0 % is
the flat panel in the plane of its first face, 100 % the model. The recorded assembly video ends with it.
A printed panel's facets carry their grooved edges (`bevel`); the view draws each face in six layers, each set in
by what the V takes at that height, so grooves and mitres show as they are exported.

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

## Tests (tests/test_unfold.py)
For cube, egg, torus, bowl (cavity), igea head (separate faces), Spot the cow (legs = undercuts), homer:
- **refold**: every layout triangle is congruent to its 3D face and both faces of every fold share the edge in the
  layout (max deviation < 1e-3 mm) — the unfolding is rigid.
- panel area == mesh area; union area == sum of triangle areas (no self-overlap).
- folds + seams == all interior edges; faces == panels' faces; the cube net is 1 panel / 7 seams with every strategy.
- one joint part per seam for strip/rib, angle label 0–360; rib on a cube edge is 90°.
- separate faces on a cube: ≥ 2 holes per seam side; on a 150-face egg with default sizes: > 100 ribs.
- no two holes overlap on a 400-face head in separate mode; folded tabs add facets for the 3D view.
- nothing "does not fit the sheet".

In tests/test_modes.py: the built cube is exactly the model's size (the sheet lies inside the surface), its
convex folds are valley lines with `score side` inside and mountain lines with outside, and a 5 mm sphere warns that
its folds cannot close in an 8 mm sheet but not in a 1.5 mm one.

Run: `uv run python tests/test_unfold.py`.

## Roadmap for this technique
1. Simulated annealing / tabu search over the spanning tree when `auto` still leaves many panels (Korpitsch, Zawallich).
2. Shape relaxation until a single patch unfolds (Bhargava 2024) — for paper models where fidelity can give a little.
3. Click-to-add / remove seams in the 3D view (Pepakura-style manual control).
4. Tab placement by stability, not on every seam (Korpitsch 2020).
