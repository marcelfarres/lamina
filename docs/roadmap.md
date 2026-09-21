# Parity with Slicer for Fusion 360 + extras — status

Legend: ✅ done · 🟡 partial · ⬜ not started. Reference of the original: `original-slicer-reference.md`
(§numbers below refer to it).

## §1 Import / model
| Original | Status | Notes |
|---|---|---|
| STL / OBJ import | ✅ | anything trimesh loads (STL, OBJ, 3MF, PLY, OFF, GLB); broken meshes are auto-shrinkwrapped |
| `.3dmk` project files | ✅ | own format: **project save / open** (`.slicer.json`: technique, every parameter, and the uploaded model embedded) |
| Fusion Team cloud open / save | — | not applicable (local tool) |
| Up-axis correction | ✅ | `up_axis` |
| CAD import (extra) | ✅ | STEP / BREP through CadQuery (`uv sync --extra cad`); IGES not supported (export STEP) |

## §2 Manufacturing settings
| Original | Status | Notes |
|---|---|---|
| Named presets: create (+), duplicate, delete (−) | ✅ | Sheet & fit tab → saved presets (material + sheet + fit), stored in the browser; pick to apply, + to save as, − to delete |
| Units | ✅ | mm / cm / in in the UI (all length fields) and for DXF; SVG/PDF/EPS carry physical size |
| Sheet length/width/thickness, standard presets, custom | ✅ | `sheet`, `thickness`; material + sheet presets |
| Slot Offset (fit) | ✅ | `slot_offset` |
| Tool Diameter → Dog Bone | ✅ | `tool_d`, `relief` = square / dogbone / tbone_h / tbone_v; applies to interlocked, curve and radial core slots |
| Object Size: Original Size button | ✅ | Model tab → original size |
| Object Size: uniform / per-axis | ✅ | `scale`, `size=[x,y,z]` (one value = uniform fit) |
| Modify Form: Hollow / Thicken / Shrinkwrap | ✅ | one voxel pass: `shrinkwrap` (pitch), `hollow` (wall), `thicken` (dilate); plus `round` (opening + closing) and `smooth` (Taubin). The grid follows the feature you ask for rather than the size of the model, and the steps a grid always leaves are smoothed off, so a smooth model comes back smooth (measured: `round 2` on the egg went from 13 % of edges over 45° to 0 %) |
| Kerf compensation (extra) | ✅ | `kerf` |

## §3 Construction techniques
| Original | Status | Notes |
|---|---|---|
| Slice Direction gizmo (any angle, reset) | ✅ | `rotate` (three angles) turns the whole model, `center` moves the slicing axis / grid; per-slice `tilt` / `roll`, `rotate_grid` on top; "original size" resets |
| Stacked Slices: direction, by count / by distance | ✅ | `axis`, `distribution`, `count`; plus `space` (empty space between slices) |
| Stacked: dowels (diameter, 6 shapes) | ✅ | `connect=dowel`, 6 hole shapes; `connect=tab` = flat pegs, or tabbed spacers when `space` > 0 |
| Stacked: dowel placement by clicking in 3D, Automatic, delete | ✅ | alt-click a part = add a point there, alt-click a point = remove; `placement` aligned / random per pair / along your 3D `lines` |
| Interlocked Slices: 2 families, counts, direction, rotate | ✅ | `nx`, `ny`, `up`, `rotate`, `distribution` |
| Interlocked: Notch Factor + Notch Angle + relief | ✅ | `notch_factor`, `notch_angle`, `relief` |
| Interlocked: drag individual slices | ✅ | click a part in the 3D view: its own handles sit on it — a yellow arrow along its normal, a green ring to tilt and a blue one to roll, both turning about the part's own middle (`pivot`) — or type `offset` / `tilt` / `roll`. Shift-drag and ctrl-drag still do the two rotations |
| Delete a slice (troubleshooting advice) | ✅ | select → delete (`skip`); crossing slices get no slot for it |
| Radial Slices: axis, count, 1st-axis density, notch factor | ✅ | half-slices around a movable axis (`center`, fan turned with `angle`) + horizontal ring slices (`ring_count` / `ring_spacing`, each movable with offset) with radial slots; `axes` gives a fan per lobe (one line each: where the axis sits, which way it points, the stretch its rings spread along); neighbouring lobes are parted by a flat plane between their axes (`B-1-2`: through the middle of the axes' closest points, facing centre to centre — the mitre between a snowman's balls, the plane across a dumbbell's neck; side-by-side axes face straight across so shortening one does not tilt it), a translucent part in the 3D view that the per-slice offset / tilt / roll move and turn; and the spine — the full plane through every axis, cut whole and slotted into every ring — is automatic from how the axes lie: on one line any number, on one plane exactly one (every fan turned to start on it), on no plane an error naming the fix. A ring slides onto the spine from its own side of the model. Every axis is drawn in the 3D view where it passes through the model and dragged whole or by either end — on the plane the other axes share while that plane faces the camera, freely when it is seen edge-on (the view you take to leave it on purpose); axes that end up on no plane get the error with a one-click fix that puts every end on the plane nearest to all of them. Alt-click the model adds a parallel axis there, `+` splits one in two, alt-click an axis removes it, and the single default axis is draggable before `axes` has ever been filled in. Spine ↔ ring slots are one slot for the whole crossing line (through-cut across a grazing chord, half-lapped where the closed end lies), reaching the sheet's own edge |
| Curve: draggable control points, distribution, notch factor | ✅ | drag a control point in the curve's plane (the mouse ray meets the plane, from any view); alt-click on the model adds one, alt-click a point removes it; the curve follows the body's centre across the plane and the ribs turn with it; the curve and its points are drawn on top in 3D; `spines` interlock the ribs |
| Folded: Simplify Form | ✅ | `facet` (target average triangle edge, mm) |
| Folded: Optimize Panels (reduce panel vertices) | ⬜ | panel outlines keep every triangle vertex; harmless for laser cutting |
| Folded: Perforate | ✅ | `perforate` (dotted score lines) |
| Folded: Split Panels | ✅ | `separate` (every triangle cut alone) |
| Folded: unfolding quality | ✅ | strategies flat / strip / area / auto (best of several runs), joints sized to their triangles, tabs shown folded in 3D — see docs/folded-panels.md for the papers |
| Folded: Add / Remove seams by clicking an edge | ⬜ | seams are chosen automatically (flattest-edge unfolding); `max_faces` limits panel size |
| Folded: 10 joint types | ✅ | seam, tab, multitab, diamond, ticked, gear, tongue, puzzle, rivet, laced (+ loops, strip, rib) |
| Folded: score vs cut, yellow fold lines | ✅ | SCORE layer: solid mountain, dashed valley, dotted perforate |
| 3D Slices | ✅ | stacked with `surface=outer` (outline follows the surface through the slice) + pegs |
| Assembly Steps: play / scrub | ✅ | `steps` slider in the 3D view; `explode` slider |
| Assembly Steps: material look (cardboard, plywood, plastic) | ✅ | `look` select in the 3D view: by family, cardboard, paper, plywood, steel, plastic |
| Reference sheets beside the 3D view, zoom | ✅ | cut sheets live under the 3D view; click one to open it full size |

## Extras (not in the original)
| Feature | Status | Notes |
|---|---|---|
| Per-slice thickness / position / angle | ✅ | `thick`, `offset`, `tilt`, `roll` (3D view or JSON) |
| Asymmetric notch meeting point | ✅ | `notch_ratio` |
| Auto-split oversize parts + joint | ✅ | puzzle tabs along the cut; `tab` width |
| Physical checks | ✅ | see README |
| Cloth mode (every triangle separate, ≥ 2 holes per edge) | ✅ | folded `separate=true`, joint `laced` |
| Folded panels from an open surface | ✅ | a clothing pattern, a mask, a shell with a neck hole: in folded mode the mesh is never mended first (it is cut from the surface, so an open edge is the input and not a defect) — boundary edges stay open and carry no joints, and a hole in the surface stays a hole |
| Connecting strips | ✅ | joint `strip`: rounded strips with mirrored holes, fold angle on the label |
| Sheet-metal ribs | ✅ | joint `rib`: slots + angle ribs cut at the dihedral angle |
| Assembly collision simulation | ✅ | every slotted part is slid along its crossing line out through the slot's mouth; material of the slotted part left in that path (a hollow section crossed twice, a concave outline) is an error with fixes |
| Live update, dark UI, tooltips, tabs | ✅ | |
| Material / machine / stock-sheet presets | ✅ | thickness by gauge or fraction with mm and inch, sheet sizes per material, kerf / slot / relief per machine (CO2 laser, fiber laser, plasma, router, knife) |
| One-sheet strip | ✅ | `one_sheet`: everything on one sheet as wide as the stock and as long as it needs |
| View cube | ✅ | click a face of the cube in the 3D view for a flat view |
| Session kept by the server | ✅ | refresh, a new tab or another browser resumes the last slice |
| Identical pieces counted once | ✅ | the plan decides which pieces are the same part (same outline, any quarter turn, same stock): the Parts table lists each once with a quantity and its twins, the per-piece export writes one file with the quantity (`Z-1_x4`) plus `cut-list.txt` |
| Mirror images counted once | ✅ | `mirror_ok` (off by default): a part and its mirror image share one file, cut twice and one turned over — only for stock that is the same both sides; the cut list and the table (⇄) name the ones to turn over |
| Undo / redo | ✅ | Ctrl+Z / Ctrl+Y (or the ↶ ↷ buttons): one step per change that reaches the slicer, technique included; the model itself is not on the stack |
| Scale-check bar | ✅ | 10 cm or 4 in bar on the first sheet with room and as its own piece file, to cut and measure first |
| Kerf compensation toggle | ✅ | `compensate`, off by default: machines that compensate their own kerf must not be compensated twice |
| Solid output (STL of assembled model / single part) | ✅ | pure trimesh |
| Test set | ✅ | 17 synthetic shapes (the dumbbell — two spheres on a neck — is the case for an axis per lobe) + 5 scanned (a head, three animals, the bunny); regression matrix; unfold and pipeline tests |

## §4 Get Plans / export
| Original | Status |
|---|---|
| Summary stats (sheets, slices, parts) | ✅ plus sheet usage % and material area |
| Cut sheets view, click to magnify | ✅ |
| Part labels `Axis-Slice-Part` | ✅ engraved beside the part with a leader line |
| Automatic nesting | ✅ no-fit-polygon nesting on the part outlines after [Deepnest](https://github.com/Jack000/Deepnest) (min-rect angle plus quarter turns, lowest-left free point, parts slide into cavities and holes); a bounding-rectangle packer takes over above 150 parts, for speed |
| Colour coding blue / green / yellow / red | ✅ OUTER / INNER / SCORE layers; parts with errors are drawn red in the UI (3D and sheet) |
| Prototyping (extra) | ✅ scaled 3D-print set: one flat STL per part + plate, labels engraved (groove) or cut (hole) at a minimum letter height in printed mm, placed where the part is widest and off the slots, printable minimum thickness; a print slot offset in printed mm (a clearance is not a ratio); fit tests (the job's joints on a small stand-in at five slot offsets, marked) as cut files at 1:1 for the real material and as a print for the print; every zip carries the project file that reopens the job |
| PDF | ✅ multi-page (one sheet per page) |
| EPS | ✅ one per sheet, zipped |
| DXF with unit choice | ✅ |
| SVG (extra) | ✅ |
| Assembly key (extra) | ✅ `assembly-key.txt` beside the cut files: what this technique's labels mean, then every part with its centre, what it slots onto and the order the 3D view builds them in; a tickbox leaves it out of the zip |
| Puzzle mode (extra) | ✅ `label_style=code`: parts are engraved with a two-letter code that says nothing about where they go and the per-piece files are named after it, so the key is the only way back — seeded by the job, so a re-slice engraves the same codes |
| Assembly video (extra) | ✅ the steps slider played and recorded off the 3D canvas (`MediaRecorder`, the browser's own) as .webm — made in the page, nothing uploaded and nothing rendered twice |

## §5 Troubleshooting checks of the original
| Original | Status |
|---|---|
| Unconnected / floating pieces | ✅ region-level assembly connectivity (slots, connectors, glued contact): floating regions and separate groups are errors; `autofix=add` adds crossing slices first, then removes what still floats; one-click fixes add a slice, move, delete the group, round the model |
| Part too small / too narrow | ✅ `min_part`, `min_feature`, thin-neck erosion |
| Notches split a part | ✅ error: slots cut the part into loose regions |
| Parts exceed the sheet | ✅ error (rotation considered) or auto-split with puzzle tabs, placed only where a whole tab fits (never clipped by a hole or the outline). A part over the sheet in *both* directions is cut the long way and then across; whatever still does not fit is named with the size that would, and keeps its sheet to itself instead of being nested over |
| Multiple / overlapping notches | ✅ warning: two slots overlap each other |
| Notch intersects a cavity | ✅ handled (one slot per in-material segment) |
| Puzzle / gear / rivet joints fail to fit | ✅ tabs that would overlap the panel are dropped with a warning; holes / slots that cross a fold are skipped and listed by seam |

## Next steps, in order

What makes more models buildable comes first; polish and speed after.

1. **Through-slots** where a crossing line meets the model twice (a leg and the body, the two walls of a hollow shape,
   the ears over a skull): each part half-laps only its deepest segment and is cut through on the others, the owner
   of each through-cut chosen so that no part is severed. Today the insertion check reports these crossings as
   unassemblable and the maker has to move or delete a slice; it is the one thing that stops interlocked and radial
   on most scanned animals and heads. Done for one pair so far: spine ↔ ring in radial (`cut_slots(…, through=True)`,
   one slot for the whole line, each part cut through on its own side of the closed end) — the general version is
   the same rule plus the severing check that decides which side takes the through-cut.
2. **Click-to-add / remove seams** in the folded 3D view (edge picking), and **Optimize Panels** (merge collinear
   panel edges, fewer vertices per outline).
3. **Folded panels**: simulated annealing / tabu search over the spanning tree, shape relaxation for single-patch
   unfolding (docs/folded-panels.md).
4. **Nesting, the quadratic half**: the no-fit polygons (after Deepnest, 2026-09-12) take the placed parts as convex
   pieces but the part on its way in as its hull, so it slides into a placed cavity or hole but does not wrap its own
   cavity around a placed bulge (a crescent in a crescent). The pieces-against-pieces version is one argument away in
   `core/nest.py` (`turned[r]` for `hull[r]`), at pieces × pieces rings per no-fit polygon; Deepnest's genetic
   search over the part order, and its merging of shared cut lines, were left out. Measured 2026-09-12 against the
   corner search it replaced: one sheet fewer on the snowman, the bowl and the folded pear (38 → 51 %, 25 → 33 %,
   14 → 21 % usage), the same sheets elsewhere; nesting time within 1.5× on every case (bunny 2.5 → 3.3 s, cow 3.4 →
   5.6 s) once parts with more than 16 pieces are nested by their hull.
5. **Speed**: the browser now runs within about 2× of the local version (README → How long a slice takes) and shows
   its progress per stage. Next: cache the section polygons of a slice frame between parameter changes that do not
   move the slices (slot width, notch ratio, sheet), so a fit tweak on a scan answers in a second.
6. **Touch**: the 3D view's drag / shift-drag / ctrl-drag editing has no touch equivalent; a tablet at the laser is
   a common place to use it.

Left out of the four features above, deliberately: the instructions are a text file (`assembly-key.txt`) with the
build order as a column, not a numbered page per step; the 3D-printed prototype still engraves real labels in puzzle
mode (that path is `core/solid.py`, not the cut files); every fan of a multi-axis radial job shares one `count`,
which is what makes neighbouring fans meet plane for plane; and axes on no single plane get no spine, because no
flat sheet passes through all of them (the job says so and names the fix). A known limit of parallel axes side by
side: a lobe *between* two others cannot be assembled, because its rings would have to slide along the spine through
the neighbours' part of it — the insertion check reports it. Lobes one after the other on a line have no such limit.

Tests to add next (what the coverage report shows untested, 88 % of core + web at the time of writing): the
`lines` connector placement of stacked, the fix options of the assembly checks (`core/checks.py` 300–320), the
CadQuery import (needs the `cad` extra in CI), the EPS writer's label path.

