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
   It is also refused when it would lie edge to edge (within 0.01 mm, for over 1 mm, away from a shared corner)
   against a face that is not its neighbour on the model: the outline would join the two along that line.
   With a joint that puts a glue flap out from the edge (tab, multitab, diamond, ticked, gear, tongue, puzzle),
   every free edge of the panel keeps the room of its flap (the trapezoid the tab is drawn as, `tab_h` high, at most
   0.6 of the edge): the face is refused when it would lie in that room, or when its own free edges would have
   none. Without it the cow example had 40 of its 217 seams with no room for a tab on either side.
4. Repeat until nothing can be attached; start the next panel.
5. `auto` runs flat, strip, area and two randomised flat orders, and keeps the fewest panels / most compact result.

`separate=True` skips step 3: every triangle is a panel. That is always feasible for any closed mesh —
cavities, undercuts and handles just become more seams — which is why it is the safe default for complex organic
shapes and for rib / laced joints. `max_faces` caps panel size.

Every mesh edge is exactly one of: fold (inside a panel, exported on the SCORE layer, mountain solid / valley
dashed, dotted when `perforate`) or seam (numbered; the number is engraved beside the joint on **both** panels so
the mating edges can be found on the cut sheet). A fold between two faces in one plane (less than 1° apart: the
diagonal of a rectangle, the spokes of a hexagon cap) is not scored: the SCORE layer holds only the edges to bend.
An edge whose two faces already lie side by side in a panel is a fold, never a seam, unless the user chose a seam
there.

### Seams the user chooses
`seams` is a list of edges, each kept by its two end points in model coordinates. `edges_at` finds the mesh edge
for each (both ends within 0.05 mm of a vertex). The unfolder leaves these edges out of the graph it grows panels
over, so no panel grows across one, and the last step above does not make one a fold again. Everything after the
unfolding reads the same list of seams, so a chosen seam gets its joint, its number and its edge fit like any other.

A closed surface in *n* panels has a fixed number of seams (edges − faces + *n*). A chosen seam therefore takes the
place of one the unfolder would have put somewhere else; it does not add work, unless it splits off a new panel.

An edge is kept by its place, not by its index, because the indices belong to one simplified mesh. Another facet
size, model size or `smallest face` gives other edges. A chosen seam that is on no edge of the new mesh is left out
and the first panel carries a warning that says how many.

For the page, the plan lists every edge that is a seam or a bent fold (`edges3d`: index, `fold` / `seam` / `chosen`,
the two ends, the direction out of the model), and every folded piece lists where its edges lie on the sheet
(`edges`: index, x0, y0, x1, y1). The page draws them on the model with three line styles (thin, dashed, thick),
lights the edge under the pointer in both views, and adds or removes a seam on a click. The joins inside one flat
face are not listed: there is nothing to fold there.

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
face to face, with room for glue. Only outward seams are mitred: at an inward seam the sheets move apart. The glue
tab joints (tab, multitab, diamond, ticked, gear) print their tabs as flaps of the skin alone (`thin` per piece):
a tab as thick as the sheet would fold into the panel it glues to. The flap folds round the mitred edge onto the
outside of the next panel. Tongue, puzzle and strip are not printed this way and keep the material error.

### The snap joint: walls inside, a clip over them
A printed model can be closed without glue and with nothing on its outside. The `snap` joint puts a wall
(`Folded.snap_wall`) on the inside face of each panel along a seam, 2 mm thick and 9 mm long, one pair for every
`spacing` of seam. His first print had walls 1.2 mm thick and clips with 1.0 mm legs: they broke every time. A
longer wall grows into a neighbour seam's at a corner of the box. The front of a wall is the plane the two panels meet on: an outward seam turns about the top of its skin, so
that plane goes through the top of the skin at half the bend, which is also the plane of the mitre. The two walls
of a shut seam therefore lie face to face, at any bend, and one clip shape (`Folded.snap_clip`) fits every seam.

Why a separate clip: the two walls move apart sideways when a seam opens, so what holds them must reach round the
back of the other wall. A part printed flat, without support, cannot grow a hook that goes over a wall and comes
down behind it. The clip is a U, 9 mm across and 7 mm long, closed at one end by a plate 1.2 mm thick (`SNAP_PLATE`)
that fills the space between its legs. Its legs are 2.4 mm thick and its top 3 mm, and each leg ends in a hook
0.5 mm into a groove 0.7 mm deep in the back of its wall. The groove is 3.6 mm up the wall, so that a leg clears the
other panel beside a 2 mm wall on a seam bent 100°. The plate ties the legs, so the clip cannot open: it slides on
along the seam, its hooks running in the grooves, until the plate meets the end of the walls. It prints standing on
that plate. His second clip test (legs 1.6 mm, an open U standing on 34 mm² of the bed): "too small, too thin, they
pop out of the bed and too fragile", and the clip opened. The plate is 90 mm² at the default `snap wall`; under
`CLIP_AREA` (60 mm²) the plan warns and names the `snap wall` that gives a clip that size.

A wall leans over its own panel by half the bend, so it prints without support up to a bend of 100° (`SNAP_LEAN`);
a sharper seam is left plain with a warning, like a seam shorter than a wall and its margins or a window frame
narrower than the wall's foot. At an inward seam the panels meet outside the edge: the wall starts on the panel's
edge, leans out to that plane at 45° and follows it. A shallow seam's mitre is wider than its bend needs (it is as
wide as the groove's flat bottom): the wall starts at the mitre and leans out to the plane in the same way.

Bend limits, for both joints that stand walls on the panels (`Folded.past_bend`, bug 063). Outward, a wall leans by
half the bend: up to 100° (`SNAP_LEAN`). Inward, the two walls start where the panels meet, out over the edge, at
t / (1 - tan(bend / 2)) - t: up to `SNAP_REACH` (5 mm) out, which is 71° on a 2 mm sheet; at 90° they never meet.
The click joint's tooth also needs walls taller than `snap wall` on an inward seam past 40° at the default 10.5 mm
(up to about 70° at 20 mm): that seam is said with the wall height it needs. A seam past a limit is left plain, and
the plan names it with its bend and the cure: glue it. The limits are in the help of the joint setting.

The walls travel in the plan with each piece (`rails`, a `Rail` each: its line in the net, the direction into the
panel, its cross-section) and `core.solid.rail` fuses them onto the panel. The 3D view draws each as a facet of its
face. A clip is a part of its own (`K-n`, group J, 7 mm thick, `springy`: the thin-part checks pass it). The joint
needs a printed material, a hinge and `score side` inside, because the walls stand on the face that is up on the bed.

### The click joint: a tooth under a bridged bar, no part of its own
The `click` joint closes a printed seam with nothing loose. It uses the same plane as the snap joint: one panel
gets a wall with a tooth (`CLICK_NOSE` wide) that goes through the plane, the other gets a bar beside the plane,
bridged between two posts `CLICK_SPAN` apart. Pressed shut, the tooth goes under the bar and
stands `tooth height` up behind it. `Folded.click_parts` makes the five cross-sections; all of them are walls in the
plan (`rails`), so `core.solid` needs nothing new.

Why a bridge: a part that grows up from a flat panel is weak where it is bent or pulled across its layers. A bar
between two posts is printed as a bridge and bends along its lines. It is the only part that bends; the tooth is
rigid.

How the bar is sized: lifted by the tooth's height in its middle, a beam held at both ends is stretched by
12 · lift · thickness / length², where the length is the part of the bar free to bend: its span less the ridge,
the fillets and the support. The bar is never stretched past `CLICK_STRAIN` (6 % for PETG, 3 % for PLA). In his
eighth print the bars stretched 6.4 % held, and one broke where they reached 8.6 and 12 %. Its span is as long as
the seam allows, 16 to 24 mm. The bar is as thick as `bar thickness` asks (1.2 mm, never under `CLICK_THIN`: a bar
of 0.8 mm broke in the hand). Where even a bar with nothing under it would stretch too far, the tooth is made lower,
a layer (0.2 mm) at a time, down to `CLICK_LOW` (0.6 mm), and only then the bar thinner; the plan names the seams
whose tooth is lower. With a tooth 1 mm high in PETG, a 24 mm bar keeps the full tooth and a 16 mm bar gets a
0.6 mm one. A free bar is also no thicker than a hand can press shut: the force to lift a beam held at both ends is
192 · E · I · lift / length³, under `CLICK_PRESS` (80 N, about 8 kg). Across the seam the bar is `bar depth` deep
(2.4 mm). The depth, not the thickness, keeps the bar straight when the seam is pulled: a 2.0 mm deep bar broke in
the eighth print. The ridge of the tooth is `CLICK_RIDGE` long, in the middle: a ridge as wide as the tooth would
hold the bar flat over that width and bend the rest of it far too much.

What the bar can still stretch goes first to a fillet at each end (`CLICK_FILLET`, 0.9 mm): three blocks under the
bar, 0.2 mm deeper each nearer its support, fused to it. The bar thickens from 1.2 to 1.8 mm into its support
instead of meeting it at a sharp step, which is where the bar broke. Each step reaches 0.3 mm further along the
seam than the one below, about 55° from upright, so it prints as a ledge on the post. What is left goes to `bar
support` (0.5 at most): the two posts grow in under the bar, which makes it stronger and stiffer. On a 24 mm bar that
is 2.6 mm a side; a 16 mm bar gets 0.4 mm. The plan still warns when a click takes more than `CLICK_HARD` to press
shut, with the kilos.

`click size` scales the whole joint: every size in this section is for size 1. A small model takes 0.7, so that
its short seams have room for a click. A big model takes 1.5 or 2: its seams carry more and have the room.
`post size` scales the two posts alone: their length along the seam beyond the bar, and their ramp.

What a 0.4 mm nozzle and 0.2 mm layers can print set the tooth. The first print had a ridge 0.4 mm high, measured
up a wall that leans by half the bend: on a 94° seam that is 0.27 mm above the bed, one layer, on a top 0.5 mm
wide. It lined the seam up and held nothing. The ridge is now 1 mm high (`tooth height`, in steps of one layer) and
its flat top is `CLICK_LAND` wide, three lines. Its back face is square to the pull, so a pull does not lift the bar.

A click also stands clear of the faces that fold or close over its panel. Shut, such a face is the panel's mirror
image in the plane that halves the edge's angle. A corner of a post, bar or wall whose mirror image lies in the
sheet under that face is in its way: the fold would stop short. The click then slides along its seam or takes the
shortest bar, and is left out with a warning when neither helps. The check looks at the faces next to the panel,
not at the walls that stand on them.

Which seams get a click when not all can: the seams between two panels come first, since they are all that holds a
piece to the rest; then `Folded.far` puts the others in order, farthest from a fold of their flat face first. A lid hangs on one fold. The seam opposite that fold holds it shut, so it finds its place before the
seams beside the fold, which the fold holds already.

A seam a click does not fit, a frame too narrow beside a window or a seam too short, tries a smaller click before it
is left plain: 85 % and then 70 % of `click size` (`CLICK_SMALLER`); the plan names those seams. A piece with a seam
but no click on any of them gets a warning, since nothing would hold it. His v9 lamp had such a piece: a loose
triangle whose two seams missed their click, one by 0.07 mm of frame, the other to a click placed first next door.

One click at a time: several clicks that must go in at the same moment are hard to press shut. `Folded.closing`
finds the seams that close in one motion and gives only one of them a click; the others get a locator, the tooth
without its ridge, which keeps the edges level and goes in with no force. It assumes an order of folding: out from
the biggest flat part of the biggest panel; a flap (a part on one fold with nothing beyond it, like a lid) after
the parts that carry others; of two flaps, the one with more seams on its edges; a panel of its own after the bigger
ones. A seam closes when the later of its two parts moves. Two parts equally late, such as two walls on one bottom,
close their seam one after the other, so both keep their clicks. The box's lid closes five seams as it folds down:
it gets one click, opposite its fold, and locators where there is room. The fold holds the lid on one side, and the
click opposite it stops the lid turning about it with the longest lever. A piece on no fold (a panel of its own)
gets two clicks, or it could swing out about the one. A model folded in another order can still close two clicks at
once, as the last wall of a ring does. `one click at a time` (`click_together`) turns the rule off: every seam its
own click.

Everything else is a plain block. The tooth is one block 10 mm wide on a 2.4 mm wall, with the one ridge. Every
upright (the tooth's wall, the posts, the blocks under the bar) is a wedge (`Folded.braced`, `CLICK_FOOT`): its
front, a flat top, and one slope down into the panel, so a pull on the seam does not bend a thin wall at its foot
across its layers. A window frame too narrow for the slope gets a shorter one, down to the bare wall. A click
slides along its seam to stand clear of the walls of the seams round the corner (`Rail.foot`), takes the shortest
bar when that is not enough, and is left out, with a warning, when it still finds no room: two walls grown into one
would not fold.

The underside of the tooth rises as steeply as prints without support and stays 0.3 mm over the other panel's
inside face. It is a short overhang, so it may lean 55° from upright (`CLICK_LEAN`), where a tall wall may lean 50°.
How far the tooth reaches past the plane sets the joint's height: on a sharp seam because the other panel stands up
there, on a shallow one because the underside rises all the way. So every part of the reach is short: the bar's
depth, the ridge's top, and a lead-in ramp of `CLICK_LEAD` with a tip `CLICK_TIP` thick. His sixth print found the
joint too tall to assemble; these cut 0.5 to 1.1 mm. `bar depth` 2.0 cuts about 0.3 mm more.

The fronts of the tooth's wall, the posts, the bar and the blocks stand `CLICK_BACK` (0.15 mm) back from the plane.
Shut, only the panel edges meet there. A printed face a little proud, or the steps of its layers, would otherwise
hold the seam open by that much.

A seam whose tooth needs walls higher than `snap wall` is left plain with a warning, like a seam bent over 100°, a
seam too short for the shortest bar and its posts (about 22 mm at `click size` 1), or a window frame narrower than a
wall's foot. A block each side of the tooth, from it to the post and
1 mm under the bar, stops the seam from sliding along its length.

Across the thickness of the sheet the tooth sits between the bar and the other panel's inside face, so the two
edges stay level: the panel stops it one way, the bar's spring the other.
Mountain folds are grooved from the face up on the bed, valley folds from the
bed side. Edges between faces in one plane get no groove. The grooves travel in the plan with each piece (`grooves`, a `Groove` each: its line, flat bottom, skin, half opening and face)
and `core/solid.py` cuts them from the printed part; the browser build has no boolean engine and exports plain parts,
and the first panel carries a warning that says so.
The example `fold_test` (48 × 48 × 32 mm, 2 mm PETG) carries 45°, 76°, 80°, 90° and 104° folds and a valley edge.

## Stiff sheet: seams meet at the inside edges
Two square-cut panels that both reach the model's edge occupy the same corner on every outward (convex) seam: a
t × t square at 90°. Paper gives; metal, wood and acrylic do not, and the part cannot close. With `how seams meet` =
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

Only what the sheet cannot take up itself is cut: the cut-back is t · tan(bend / 2) less the material's crush
(`SQUISH` × t). Paper, card, cardboard and fabric crush through their whole thickness and are never cut back, nor
is a material that is not listed; cut back like steel, the small panels of a laced cow in 1 mm card fell under
the minimum part size. A rib too small to cut and handle (under `min_part` both ways) is left out and reported. The cut-back is never what
makes a panel too small: a panel it would take under `min_part` or `min_feature` keeps its edges and carries the
press warning.

What is left presses into the next panel: t · tan(bend / 2) less the cut-back (capped at 0.4 of the face's height,
so a sliver keeps its middle; nothing with a tab joint). `SQUISH` in `core/modes/folded.py` gives the share of the
thickness each material can crush at an edge (paper, card, cardboard 1; foam and leather less; metal, wood and
hard plastic 0). Past it the panel warns, with the depth. A material not in the table is not checked.
Measured on the examples in 3 mm steel, every face its own panel, by intersecting the panels' solids
(working-files, 2026-11-13): cube, pyramid, wedge and fold_test go from 18–77 colliding pairs to 0; fold_lamp 204
to 1 (1 mm³); egg 530 to 1; torus 359 to 54 (99 mm³ in all); cow 340 to 70; bowl 378 to 41. What remains is at
saddle vertices, where panels that share only a corner meet, and on slivers the cap protects. Not yet handled.

## Faces too small for the sheet
The cut-back takes at most 0.4 of a face's height, so a face lower than about 2.5 sheets (more at a sharp seam)
cannot be cut back all the way and carries the press warning. The warning offers two fixes. *Bigger triangles*
raises `facet` and makes the whole model coarser. *Merge the faces under 4 × the sheet* sets `min_face`
(`merge_small` in `core/mesh.py`): after the model is simplified, each face whose least height is under `min_face`
has its shortest edge closed up to its middle, the smallest faces first, until no such face is left. The other
faces do not move, except those that share a corner with a merged face.

Measured on the cow in 1 mm steel, laced, facet 15, `min_face` 4 (2026-11-14): 408 faces become 282, the 66 faces
under 4 mm become 0, the press warnings go from 6 to 0, all warnings from 84 to 62, errors stay 0. The model is
1.2 mm shorter. On the bowl 2012 faces become 1994 and on the torus 1092 become 1036; both stay closed.
Limits: the shortest edge is closed whatever it is, so a flat wide triangle with no short edge is pulled out of
shape and not removed, and an edge on the rim of an open surface moves that rim.

## A model thinner than two sheets
The sheet lies inside the surface, one thickness deep. Where the model itself is thinner than two sheets (a fin, an
ear, a thin shell), the sheet under one side runs into the sheet under the other. `check_walls` sends one ray from
the middle of each face straight into the model; a face that meets the far side within two thicknesses puts a
warning on its panel, with the least depth found. One ray per face: a wall that thins only near an edge is missed.
It needs the ray engine's rtree, which the browser build has not.

## Windows
`window` opens every face with a hole of its own shape, for a lamp shade or a lantern. The frame left around it is
what the share asks for and never less than 1.35 × the minimum feature width, plus what the face's grooves or
cut-back edges take, plus the reach of the joint's holes or slots. A face too small for that stays whole.
The example `fold_lamp` uses it: a twisted, swelling tube of 30 triangles (about 58 × 29 mm each, 12 seams to close), printed in 2 mm PETG on one
plate. It had 72 triangles of 38 × 19 mm and 32 seams at first: too many and too small to put together by hand.
The lantern keeps the 72: at 420 mm they are big enough.

## Removed faces
`removed` holds the faces the user took off the surface, to keep only a part of the model (a mask from a head). They
go after the model is simplified and before it is unfolded. What is left is an open surface: the rim round the
removed faces is a boundary like any other, a plain cut edge with no seam and no joint.

A removed face is kept by its place, not by its number: its triangle, in the coordinates of the model file. The plan
gives the 4 × 4 matrix from the file's coordinates to the plan's millimetres (`frame`; `core/mesh.py` builds it from
every scale, turn and move it applies). So the same places are removed after a change of facet size, of the model's
size or of its rotation. After a change of facet size the rim moves by one triangle at most.

`faces_at` (`core/unfold.py`) finds the faces at those places. A face is removed when the line through its middle,
along its own normal, meets a stored triangle that faces the same way, no further off than half that triangle's
longest edge. The stored triangles of a region lie edge to edge, so a line through the region meets one of them; a
flat projection onto each triangle leaves a gap along every ridge between two. The far side of a thin wall faces
the other way and stays.

- A seam the user chose that is now on the rim, or among the removed faces, is left out and nothing is said. The
  page takes it off the list when the face is removed; undo brings back the face and the seam.
- A piece of the surface that the removed faces cut off from the rest is cut as panels of its own. A warning names
  the panels. It is not deleted.
- When every face is removed, the plan has an error and no parts.
- Coverage is measured on the model without the points at the removed places.

Measured on `head_igea` in 0.5 mm card (2026-11-17): the back of the head picked at facet 20 mm, 246 faces, leaves
451 cm² of 944 cm². At facet 12 mm with the same list, 703 faces are removed and 456 cm² is left.
Not done: a smooth rim along a drawn line. The rim follows the edges of the triangles.
Limit: where the surface folds over itself within half an edge length and both layers face the same way (the
curls of a carved mane), a face under a removed one can be at the same place and go with it. On the lion head
at face size 25 mm, one selection of 617 faces removed 618.

On the page (`web/static/js/faces.js`) the `select faces` tool of the 3D view makes the list. The plan gives the
faces that are left (`faces3d`: the corners, the faces, and the two faces across each edge, numbered as `edges3d`).
A click or a drag selects faces. `grow` adds the faces across an edge of the selection, `connected` goes on until
nothing is added; both stop at a seam the user chose, and so at a removed face and at the rim, where there is no
face across the edge. `remove` adds the selected triangles to `removed`, carried to the file's coordinates with the
inverse of `frame`. A removed face is drawn as a dashed outline while the tool is on; a click on one takes its
triangle out of the list. Selected faces are hatched: the three looks (hatched, dashed outline, thick seam line)
do not depend on colour. In the seam tool and in this one, a drag with the left button paints, so the right button
turns the view and the middle one moves it.

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

In tests/test_seams.py: a chosen seam is never a fold and the net still folds back; a chosen seam across a flat face
stays a seam; the plan marks every fold once and every seam twice on the sheets, a fold on its score line and a seam
on the cut outline, with the net mirrored and not; a seam on no edge is reported and left out. In tests/ui/test_edit3d.py:
a seam is chosen on the model, another on a sheet, one is given back, and both views mark the same edges.

Run: `uv run python tests/test_unfold.py`.

## Roadmap for this technique
1. Simulated annealing / tabu search over the spanning tree when `auto` still leaves many panels (Korpitsch, Zawallich).
2. Shape relaxation until a single patch unfolds (Bhargava 2024) — for paper models where fidelity can give a little.
3. Edges the user wants kept as folds ("keep this area in one piece"): possible only as a preference, because an
   overlap or the sheet size can still force a seam there.
4. Tab placement by stability, not on every seam (Korpitsch 2020).
