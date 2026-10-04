# Changelog

What changed in each release. The GitHub release for a version is this section, pasted.

## 0.2.2

What your model weighs, eleven more materials, PLA and PETG printed plate by plate at full size, a check that the
material folds before a folded job is cut, curve ribs that branch down each leg, dowels that hold a big layer from
near its edge, the model's name on every part, a button that squares up a tilted model, radial lobes side by side or
at right angles, a desktop version that keeps itself up to date, an auto-fix that never deletes a piece of your model,
and fixes for stacks that came out short, parts off their sheet, layers whose pieces were nested as one, folded holes
too near the edge, and the browser version's one intermittent failure.

### Printing

- **A printed job is plates, not sheets.** Picking PLA or PETG ticks **3D printed** on the Sheet & fit tab: the sheet
  size is the printer's bed, the page counts plates, and the Export tab offers the print plates (one 3MF per bed,
  at full size, with the job's own slot offset) instead of cut files nothing would cut. Untick it to get the cut
  files anyway.

### Checks

- **Folded panels check that the material folds.** Fold lines, and tabs that fold over a seam, in 3 mm plywood (or
  MDF, acrylic, balsa, foam board, printed PLA or PETG, or card and metal past the thickness they fold at) are an
  error now: the sheet would crack along the score. One click cuts every face as its own panel, joined by ribs that
  need no fold, at a facet size that keeps the part count workable. A material of your own is checked as the one
  it was made from.

### Weight

- **The Export tab weighs the job.** The parts as cut (holes and slots taken out, each at its own thickness), the
  whole sheets you buy and lift onto the machine, and the dowels, with a total for the assembled model. A job that
  mixes thicknesses gets a line per stock. It follows the units switch: grams and kilograms, or ounces and pounds.
- **Every material has a density** you can correct on the Sheet & fit tab. The figures are typical ones, checked
  against suppliers and wood and material references; weigh an offcut of your own stock for an exact number.
- **Materials of your own**: + beside the material keeps the one in use under a name, with its thickness and
  density, and − deletes it.

### Model

- **Square it up.** A boxy model that sits a few degrees off its axes (a rotate slider left at 85 instead of 90, a
  CAD export that came out tilted) cuts every straight edge as a staircase. The Model tab now says how far off it
  is, "sits 5° off square", with a **square it up** button right under the rotate controls. Nothing turns by
  itself: leave it if the tilt is on purpose.
- **Radial lobes side by side or at right angles.** Three balls on a neck, an axis through each, used to cut the
  spine into loose pieces, because a middle lobe's rings reached it through a neighbour's cap; their rings now go
  down the neck, and only a lobe no ring can join says so. Two axes at right angles work when they share a plane:
  the dumbbell now opens that way, across the lower ball and up the upper one.

### Curve

- **Curve (ribs) takes branches**: one line per leg, arm or tail, each with its own ribs square to it and a spine
  that reaches up into the body and slots into its ribs. A horse's legs are held instead of cut across by body ribs:
  with a branch down each leg it comes out in 55 parts and no errors, where the same job without them has two
  parts that fail. Shift+alt-click a hoof to add a branch (its joint lands inside the leg, even on a leg splayed
  out to the side), drag its ends, alt-click it to remove it. A branch that starts past the body's ribs is an error
  that says where to move it, not a loose leg.
- **Body ribs turn further**, because the legs no longer count toward how far the material reaches.
- **The curve's points are a table in the form.** Typing in the old box sent a number and the slice failed.

### Examples

- **The horse opens in Curve**, with its curve from tail to muzzle and a branch down each leg: 55 parts, no errors.
- **A new horse for stacked slices**: `horse_statue`, a porcelain horse rearing on a round base (CC0, from Poly
  Haven). It opens as side profiles across its width with a 4 mm gap on 2 mm square dowels: 39 parts, no errors,
  no warnings. Layered up its height, the body over its slanted hind legs would rest on nothing.
- **A new example, the wavy torus:** a ring rising and falling in three waves with a channel along it for an LED
  tube, stacked in PETG for a 3D printer. The page now opens on the blob.

### Technique

- **Dowels hold a big layer from near its edge.** Aligned dowels were placed in the part every layer shares, so on
  a round model the widest layers in the middle hung on two dowels close together at the centre, free to swing a
  little at the rim. A layer those shared dowels do not hold now gets its own, out toward its edge; with three or
  more they go round the layer instead of along a line, and asking for more dowels never leaves a layer worse
  held. Where a layer is still held by dowels bunched together, the Checks tab says so — its size, how much its
  far edge can shift — and names the one more dowel that would hold it, with a button to add it. Where no dowel
  fits farther out because the wall is too thin (a hollowed model's ring), it says how thick the wall is and how
  much the dowel needs. Small pieces, where two dowels this size cannot sit any farther apart, are left in peace.
- **A dowel you add comes on top of the automatic ones.** One alt-clicked or typed under dowels used to stand in for
  one of the `n_points` per layer, so the layer could end up held no better. Now it is added to them.

### Materials

- **Nine new ones to cut**: stainless steel, brass, copper, greyboard, polypropylene, foam board, EVA foam, basswood
  and balsa, each with the thicknesses it is sold in, the sheet sizes, a 3D look and only the machines that can cut it.
- **Stainless has its own gauge table.** 14 ga stainless is 1.984 mm where carbon steel's is 1.897 mm, so picking
  "steel" for it cut every slot too tight. Copper is listed by ounces per square foot and chipboard by points, the
  way they are sold.
- **Foam board is cut by hand only**, because its polystyrene core melts and can catch fire under a laser.
- **PLA and PETG, to 3D-print the parts at full size.** Their thicknesses are whole layers (0.8 to 6 mm), their
  "sheets" are print beds so the parts nest plate by plate, and a 3D printer machine gives every slot 0.2 mm of
  clearance. Six printers are listed by name with their beds: Bambu Lab H2C, X1 / P1 / A1 and A1 mini, Prusa MK4S
  and CORE One, Creality Ender-3 V3. Picking PLA or PETG sets the Export tab's print set to full size.

### Labels and cut files

- **Every part carries the model's name**: `bunny Z-3`, so parts of two models cut together are never mixed up,
  even though both have a Z-3. It is the project's name when you have given one, otherwise the model's file name.
  The room for it is kept when the parts are nested; **label model** on the Sheet & fit tab turns it off.
- **The cut list gives each part's size**, width × height as it lies in its file, in your units.
- **A material of several words is one word** in a file name: `Z-1 stainless-steel x4.svg`. The spaces always
  separate part, material, thickness and quantity.

### 3D view

- **The controls under the view are one short line.** It shows orbit, zoom and pan; **all controls** opens the rest,
  grouped by view, model, alt-click, curve and radial. The handles on a selected part are explained in its own
  panel, so they are no longer repeated there.

### On your computer

- **Updates come by themselves.** The double-click starter installs the newest release each time it starts, and
  starts the one you have when there is no internet. A starter downloaded before this version never updates:
  download the ZIP once more and use the new one; your jobs stay in the old folder's `working-files`.
- **From a terminal it is one install:** `uv tool install lamina3d`, then `lamina3d` opens it, and
  `uv tool upgrade lamina3d` updates it.

### Docker

- **The Docker image runs on Debian 13** with uv 0.12.23. The Debian 12 base it was built on is no longer updated.
  Nothing changes in how you run it, and it slices the bunny exactly as the desktop version does.
- **Dependencies are kept up to date.** The Python packages, the Docker base image and the GitHub Actions are
  checked every week, a new release is only taken once it is a week old, and every image is built before an update
  can be merged.

### Gallery

- **Show what you made.** The landing page has a gallery of things cut with Lamina, and a **send me a photo** link
  under the downloads on the Export tab opens the same dialog as a bug report: a prefilled email (no account
  needed) or a GitHub issue form you drag the photos into. With your OK it goes up, credited the way you ask. Or
  post it on Instagram or X with **#applamina**.

### Auto-fix

- **Auto-fix never deletes a piece of your model.** It used to add crossing slices and then remove whatever still
  floated: on a tube sliced 6 × 5 that was 71 % of the model, and on the horse the whole top layer with its ear tips.
  Now what nothing can hold stays on the plan with its error and the fixes to click, deleting among them if that is
  what you want. The only things left out, and the report says so, are slivers thinner than the minimum wall
  everywhere: shavings a slot cuts off its own part, and specks where a slice only grazes the surface.
- **Interlocked slices are held where it counts.** A crossing slice through the middle of a loose piece used to be just
  as loose there. Auto-fix now places it where its own cut reaches the rest of the model: the tube and the torus are
  held whole, and on thirteen hard cases the errors left went from 281 to 92 (all of them now kept and shown, where
  before they were deleted).
- The **remove** choice of auto-fix is gone: **add** holds what it can, **off** only reports. A project saved with
  remove opens with off.

### Usage counting

- **The box at the foot of the published app's Model tab now starts ticked.** While it is ticked it sends the
  technique you pick, whether the model came from the examples or your computer, and which formats you export:
  never the model, a file name, your measurements, an account or a cookie. Untick it and it stays off on that
  browser. The copy you run yourself or in Docker has no counting at all.

### Fixed

- **The browser version no longer fails now and then while nesting** with `GEOSException … NaN/Inf`. The bunny
  example hit it about one time in three. It came from the geometry library the browser version runs, and nesting
  now avoids the function that caused it.
- **Stacked slices run the full height of the model.** A layer's thickness was always left off each end, and the
  stack was built up from the bottom, so a 100 mm cube in 4 mm card came out 23 layers tall with the missing 8 mm
  all at the top. It is 25 layers now, centred.
- **A stack never loses layers to the automatic fixes.** With a space between layers and dowels placed along lines,
  a layer that no line crossed yet was removed as "held by nothing" — 11 of the horse's 20 layers. It stays now,
  and the Checks tab says what would hold it.
- **Only the handles move a selected part.** Dragging anywhere on a selected layer used to slide it, which is also
  how you turn the view, so layers moved by accident. A plain drag now always turns the view; the arrow and rings
  (or shift- and ctrl-drag) still move, tilt and roll it.
- **Random dowels spread across each layer** instead of sometimes bunching at one end: on the horse, the farthest
  point of a layer from any dowel went from 0.91 of its width to 0.57.
- **Dowel lines work from the first click.** `+ line` added a line from 0,0,0 to 0,0,0, which placed nothing; it now
  draws one up through as many layers as it can, alt-click draws one through the point you click, and the help
  explains aligned, random and lines.
- **Folded panels keep a proper wall around their holes.** Rivet, laced and strip joints placed their holes half the
  minimum wall from the edge, so the checks warned "a hole sits closer than 2 mm to the outline", and the one-click
  fix changed the dowel size, which folded panels do not use. The holes keep the full wall now, strip ends are
  long enough for their end holes, and the fix, when it is needed, changes the hole size.
- **Your own model starts from its own shape.** Uploading after an example (the horse, which the page opened on)
  kept that example's size, rounding and thickening, so Julia's square 100 mm cube came out 308 mm across with
  14 mm round corners and its 15 mm hole closed to 3.5 mm. An upload now starts with every Model setting at zero.
  The note after a remesh gives the voxel size and how much rounding and narrowing to expect, and the help for
  shrinkwrap, hollow, thicken and round now says that all four at 0 keep the model exactly as drawn. A model under
  5 mm across (Blender saves STL in metres, so a 100 mm cube arrives as 0.1 mm) gets a note asking for its real size.
- **Stacked slices no longer stop at "placing slices and slots"** on a model with flat walls. Each layer's outline
  carried stray points along its straight edges, a different set on every layer, and lining up the dowels through
  the whole stack piled them all up: a 300 mm cube with a hole reached nearly 400,000 points by its 15th layer and
  never finished. Its 100 layers now take about 18 s from start to cut sheets. Thanks to Colin for the report and
  the project file.
- **A tall slanted part is measured at its real size.** A 120 × 660 mm part with slots along a slanted side could
  read as 0 mm wide, so it was reported "too thin" and taken away instead of being split to fit the sheet.
- **Report a problem works while the page is stuck.** In the browser version, "gathering the report…" waited for
  a slice that would never finish, so the report could only be sent after reloading, which lost what it was
  about. It now has the model straight away.
- **Picking the same file again loads it.** After switching to an example, choosing the file you had uploaded
  before did nothing: the upload box still held it, so the browser saw no change and the page stayed on the example.
  Picking an example or opening a project now clears the box.
- **The local and Docker versions no longer finish slices nobody is waiting for.** Every change sends a new slice
  and the page shows only the newest, but the server used to compute every earlier one to the end as well, side by
  side, so dragging a slider through a few values made each slice several times slower. A newer slice now stops the
  older ones.
- **A problem report says how you got there.** Besides the settings and the checks, it now carries the Lamina
  version, every step since you loaded the model (each setting changed, undo, fix clicked, slice and error, with its
  time), and, if a slice is still running, how long and at which step. **See what is sent** in the report dialog
  shows all of it before you send. Saving a project is unchanged: it holds the design, not the steps.
- **A dowel in the 3D view has the shape of its hole.** Square, hexagonal, cross and slot dowels were all drawn as
  round rods, so changing the dowel shape seemed to change nothing; the weight of the dowels now uses their real
  section too.
- **Every piece of a layer is its own part.** A layer that falls apart into separate shapes, like the lobes at the
  ends of the wavy torus, was one part: its pieces were nested as one group with the empty space between them, and
  only one carried a label. Each piece is now a part of its own, labelled `Z-1-1`, `Z-1-2` …, and nested on its own:
  the wavy torus goes from 14 sheets to 8.
- **Aligned tab spacers hold every layer.** With tab connectors and aligned placement, every second pair of layers
  could end up with no spacer at all: the automatic fixes then removed the pieces nothing held, and spacers that did
  fit could cut into each other ("two slots / holes overlap"). Each spacer is now placed where its slot really fits
  both layers, with a full wall from every other cut, and a piece the regular points miss gets spacers of its own.
  On ten example shapes the errors went from 319 to 6, all at the tip of a cone too small for a 6 mm connector.
- **A new example starts every technique fresh.** Switching the horse to stacked after the statue brought back the
  statue's 2 mm square dowels on its side axis, so every tab spacer came out too thin to cut. An example now opens
  every technique on its defaults and its own preset; your own model keeps the settings you gave it.
- **A spacer too thin to cut says why, and how to fix it.** Tab spacers and pegs are drawn at the connector's
  size, but their error told you to thicken or round the model, which never reaches them. It now names the connector,
  and one click sets a size whose spacers keep the minimum wall.
- **Every part lands on its sheet.** A part that filled a sheet almost exactly, like a big folded panel, could be
  placed hundreds of millimetres off the sheet, and jobs of more than 150 parts let the last part along the edges
  run a millimetre or two into the sheet margin, and now and then two parts were nested on top of each other. Every
  part is placed inside the margin and clear of the others now.
- **Interlocked slices added by the automatic fixes keep a full wall from the others.** A slice added to hold a loose
  piece could land 4.5 mm from another of its family in 3 mm material, leaving 1.3 mm between their slots in every
  slice they cross. Each one now keeps the material's thickness, the slot offset and the minimum wall away.

Verified by 634 tests, plus 27 driving the app in a real browser and one slicing the published build end to end.

## 0.2.1

Units and file names, both reported after 0.2.0.

### Units

- **The units switch now changes every length on the page.** Before, some places stayed in mm: the panel of the part
  you had selected, the parts table, the Export tab's boxes, the messages and fix buttons, and the help. Now they all
  follow the switch, straight away, without slicing again.
- **Nothing is rounded when you change units.** Lengths are kept exactly as you typed them, and the units only
  change how they are shown. 1/16 in is 1.5875 mm, where editing a single part used to store 1.59 mm. Switching back
  and forth any number of times leaves every value where it was.
- **The boxes step in round numbers of your unit.** In inches the thickness box used to step by 0.0019685 and mark
  0.25 as invalid. It now steps by 0.002. An exact inch fraction reads as one, as in `1/16 in stock`.
- **Cut files come out in the units on screen**, even if you changed them after the last slice.

### File names

- **Per-piece files say what they are**: part, material, thickness, then quantity, separated by spaces. For example,
  `R-1a cardboard x2.svg`. Every file ends in its quantity, `x1` included. Sheet files carry the material too:
  `sheet1 cardboard.svg`.

Verified by 579 tests, plus 16 driving the app in a real browser (one of them for units) and one slicing the
published build end to end.

Known issue, also in 0.2.0: in the browser version, the bunny example now and then fails to slice with a geometry
error (`GEOSException … NaN/Inf`). It shows up in about one run in three of the end-to-end test and is being looked at.

## 0.2.0

Most of this came from people who wrote in after trying 0.1.0. Thank you — keep them coming.

### Install and run

- **Double-click to start**, on Windows, macOS and Linux. No terminal, no commands.
- **No upload limit on your own machine.** The 30 MB cap was a public-server measure applied to everybody.
- **A model that fails to load says so in a dialog**, and lets go of the file box.

### Model preparation

- **`round`, `shrinkwrap`, `hollow` and `thicken` keep a smooth model smooth.** All four go through one voxel grid,
  which left a staircase and then a bumpy edge. Both are gone: on the egg at `round 2`, edges over 45° went
  **13 % → 0 %** and the cut outline's wobble **0.285 mm → 0.092 mm**. You no longer need `smooth` to undo the tool.
- **A model that is not watertight is mended first** — merged, de-duplicated, holes filled — instead of going
  through the remesh that put steps on every slice.

### Stacking

- **Layers get alignment dowels by default**, two per piece, so a stack glued with no gap cannot go together
  crooked. Each piece of a layer that falls into two gets its own pair.
- **Dowel holes keep a wall of material between them.** They used to merge into one ragged opening — 6 mm holes
  0.6 mm apart on a hollowed model, 3.4 mm on a cone.
- **A dowel runs straight through as many layers as it fits.** Holes used to creep inward on anything tapered until
  they collided and were dropped; the scanned head went from 20 dowels to 38.
- **Where none fits, it says so** and any size it suggests is one that works.

### Cutting

- **Parts bigger than your sheet** are cut the long way and then across; whatever still cannot fit keeps a sheet to
  itself instead of being nested on top of. The report names the size that would fit.
- **`one sheet` with many parts is 550× faster** — 2552 s → 4.6 s on 400 panels.

### On screen

- **Your model appears seconds in**, while the slices are still being cut, and the overlay lists the stages
  (`step 5 of 9 · sectioning · 12 of 34 · 46 %`) instead of a bar that restarts.
- **The sheet preview is readable without colour vision** — the Okabe–Ito set, drawn thicker. Exported files keep
  the machine colours.
- **A selected part has handles on the part**: an arrow along its normal, two rings to turn it about its own middle.
  Radial half-slices and the planes between lobes used to swing across the model when dragged.
- **Curve points follow your pointer from any view**, instead of plunging along an axis you cannot see.
- **Nothing follows you from one model to the next**: axes, curve points, dowels and per-slice edits are cleared.
- **What changed shows itself once** after an update, and the **what's new** button in the header has every version,
  newest first — these notes, so they cannot drift from the release.

### Checks, machines, finding your way

- **A layer of a stack is never offered for deletion** — take it out and the model has a gap through it. A floating
  island *of* a layer still is.
- **16 machines by name** (Glowforge, xTool, OMTech, K40, Epilog, Thunder, Trotec, Shapeoko, Cricut, Cameo and more),
  each marked `*`: published bed sizes and an educated guess at kerf, not measured on your material. Plus metric
  thicknesses, and a button to share a machine or material so it ships with Lamina.
- **`? help`** in the header: the tabs in the order you use them, the 3D mouse, every shortcut.
- **Undo is labelled**, and holding Ctrl+Z slices once at the end instead of once per step.
- **The size boxes** show the model's real dimensions: type one and the other two follow.

### Also

Radial slicing with several axes (a snowman, a dumbbell) tied by a spine · `assembly-key.txt` in the export ·
puzzle mode · the assembly as a video · folded panels from an open surface · fit tests at print and cut scale ·
a report button that writes the bug report for you.

Verified by 579 tests, plus 15 driving the app in a real browser and one slicing the published build end to end.
Not tested here: the macOS and Linux starters (Windows only), and the starred machine figures.

## 0.1.0

First public release: five construction techniques (stacked, interlocked, radial, curve, folded), the physical
checks with one-click fixes, nesting, SVG / DXF / PDF / EPS export, the 3D-printable prototype set, and the browser
build that needs no install.
