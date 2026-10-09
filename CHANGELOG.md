# Changelog

What changed in each release. The GitHub release for a version is this section, pasted.

## 0.2.4

Quicker to work with in the browser: a change you make while a model is slicing now stops that slice and starts
yours, instead of waiting behind it, and renaming a project no longer prepares the model all over again.

### Changed

- **Rounding, thickening and hollowing are quicker.** Preparing a model this way, or remeshing one that does not
  close, takes up to a third less time: the bunny's rounding went from 1.4 s to 0.9 s.
- **Share your build with #lamina3d.** The note that invites you to share a photo of your build now names #lamina3d,
  the one name Lamina uses everywhere (it said #applamina).

### Fixed

- **A model with a hole in it slices.** A mesh open somewhere, as scans often are at their base, could fail to slice
  with "need at least one array to concatenate". It is now filled into the solid it encloses, the hole closed straight
  across, as was always meant.
- **A new change stops the slice before it.** In the browser version, moving a slider or changing a value while a
  slice was running queued a whole slice for every step, and the result for the value you ended on came last: four
  quick moves on the horse took almost two minutes to show the last one, and now take under one. Picking another
  example mid-slice also showed the old model's preview for a while, as if the new one had not loaded; it now goes
  straight to the new one. The local version already stopped the old slice, and still does.
- **Renaming the project no longer re-prepares the model.** A new name, sheet, thickness or anything else that does not
  change the model's shape reuses the model and its 3D preview as already prepared, so the remesh, the smoothing and
  the preview are not done again. On the head example in the browser a new name takes 9.5 s instead of 20 s, and a
  second or two less on your own computer.

## 0.2.3

A fix for 0.2.2, found the day it came out. If you have 0.2.2, update to this one.

### Changed

- **What's new covers everything you missed.** The notes that open by themselves after an update now show every
  version since the one you last used, not only the newest. Coming from 0.2.1, you see 0.2.2's notes as well as these.

### Fixed

- **The ticked joint keeps its ticks.** On some computers, Linux and the Docker version among them, a folded net with
  the ticked joint came out with every little tick as a loose piece of its own, flagged as too small to cut. The ticks
  are part of the net again, on every computer, and so are the tabs of every other joint.

## 0.2.2

What your model weighs, eleven more materials, PLA and PETG printed plate by plate at full size, a check that the
material can fold before a folded job is cut, curve ribs that branch down legs and arms, dowels that hold big layers
near their edge, the design's name on every part and every file, a button that squares up a tilted model, a desktop
version that keeps itself up to date, and an auto-fix that never deletes part of your model. And many fixes: stacks
that came out short, parts placed off their sheet, pieces of one layer nested as one, and the browser version's
occasional failure.

### Printing

- **A printed job is plates, not sheets.** Picking PLA or PETG ticks **3D printed** on the Sheet & fit tab: the sheet
  is the printer's bed, the page counts plates, and the Export tab offers one 3MF per plate, at full size and with the
  clearance set for printing, instead of cut files. Untick it to get the cut files anyway.

### Checks

- **Folded panels check that the material can fold.** Fold lines, and tabs that fold over a seam, in 3 mm plywood
  (or MDF, acrylic, balsa, foam board, printed PLA or PETG, or card and metal past the thickness they fold at) are an
  error now: the sheet would crack along the fold. One click cuts every face as its own panel, joined by ribs that
  need no fold, with triangles big enough to keep the number of parts reasonable. A material of your own is checked
  as the one it was based on.

### Weight

- **The Export tab weighs the job**: the parts as cut (holes and slots taken out), the whole sheets you buy and lift
  onto the machine, and the dowels, with a total for the assembled model. A job that mixes thicknesses gets a line
  per stock. It follows the units switch: grams and kilograms, or ounces and pounds. It matters most for big pieces
  and metal, and for anything that has to hang.
- **Every material has a density** you can correct on the Sheet & fit tab. The figures are typical ones; weigh an
  offcut of your own stock for an exact number.
- **Materials of your own**: + beside the material keeps the one in use under a name, with its thickness and
  density, and − deletes it.

### Model

- **Square it up.** A boxy model sitting a few degrees off square (a rotate slider left at 85 instead of 90, a CAD
  export that came out tilted) cuts every straight edge as a staircase. The Model tab now says how far off it is,
  "sits 5° off square", with a **square it up** button under the rotate controls. Nothing turns by itself: leave it
  if the tilt is on purpose.
- **Radial models with lobes side by side or at right angles.** Three balls on a neck, each with its own axis, no
  longer have their spine cut into loose pieces. Two axes at right angles work when they lie in one plane: the
  dumbbell now opens that way, across the lower ball and up the upper one.

### Curve

- **Curve (ribs) takes branches**: one line per leg, arm or tail, each with its own ribs square to it and a spine
  that reaches into the body and slots into its ribs. A horse's legs are held instead of cut across by the body's
  ribs: with a branch down each leg it comes out in 55 parts and no errors. Shift+alt-click a hoof to add a branch,
  drag its ends to move it, alt-click it to remove it. A branch that starts past the body's ribs is an error that
  says where to move it, instead of a loose leg.
- **The body's ribs can follow a tighter curve**, now that the legs no longer get in the way.
- **The curve's points are a table you can edit.** Typing in the old box broke the slice.

### Examples

- **The horse opens in Curve**, with its curve from tail to muzzle and a branch down each leg: 55 parts, no errors.
- **A new horse for stacked slices**: `horse_statue`, a porcelain horse rearing on a round base (CC0, from Poly
  Haven). It opens as side profiles with a 4 mm gap on 2 mm square dowels: 39 parts, no errors, no warnings.
- **The wavy torus**: a ring rising and falling in three waves, with a channel along it for an LED tube, stacked in
  PETG for a 3D printer.
- **The page now opens on the blob.**

### Stacked dowels

- **Dowels hold a big layer near its edge.** On a round model the widest layers used to hang on two dowels close
  together in the middle, free to wobble at the rim. Such a layer now gets dowels of its own out toward its edge,
  and three or more go round the layer instead of along a line. Where a layer is still held by dowels too close
  together, the Checks tab says so and offers a button that adds the dowel that would hold it. Where the wall is too
  thin for a dowel farther out (a hollowed model), it says how thick the wall is and what the dowel needs.
- **A dowel you add comes on top of the automatic ones.** One you alt-clicked or typed in used to count as one of
  the dowels per layer you had asked for, so the layer could end up held no better. Now it is added to them.

### Materials

- **Nine new ones to cut**: stainless steel, brass, copper, greyboard, polypropylene, foam board, EVA foam, basswood
  and balsa, each with the thicknesses it is sold in, its sheet sizes, a 3D look, and only the machines that can cut
  it.
- **Stainless has its own gauge table.** 14 gauge stainless is 1.984 mm where carbon steel's is 1.897 mm, so
  picking "steel" for it cut every slot too tight. Copper is listed by ounces per square foot and chipboard by
  points, the way they are sold.
- **Foam board is cut by hand only**: its polystyrene core melts and can catch fire under a laser.
- **PLA and PETG, to 3D-print the parts at full size.** Their thicknesses are whole print layers (0.8 to 6 mm),
  their "sheets" are print beds, and a 3D printer gives every slot 0.2 mm of clearance. Six printers are listed with
  their beds: Bambu Lab H2C, X1 / P1 / A1 and A1 mini, Prusa MK4S and CORE One, Creality Ender-3 V3.

### Labels and cut files

- **Every part carries the design's name**: `bunny Z-3`, so parts of two models cut together are never mixed up,
  even though both have a Z-3. It is the project's name when you have given one, otherwise the model's file name.
  **label model** on the Sheet & fit tab turns it off.
- **Every file is named after its design too.** Each file in a download starts with the same name as the zip: the
  project's or the model's, with its revision, as in `egg_v1.0 sheet1 plywood.svg`, `egg_v1.0 Z-1 plywood x4.svg`
  and `egg_v1.0 cut-list.txt`. Two designs unzipped into one folder no longer overwrite or mix with each other.
- **The cut list gives each part's size**, width × height as it lies in its file, in your units.
- **A material of several words is one word** in a file name: `egg_v1.0 Z-1 stainless-steel x4.svg`. The spaces
  always separate design, part, material, thickness and quantity.

### 3D view

- **The controls under the view are one short line**: orbit, zoom and pan. **all controls** opens the rest, grouped
  by what they work on. The handles of a selected part are explained in the panel that opens with it.

### On your computer

- **Updates come by themselves.** The double-click starter installs the newest release each time it starts, and
  starts the one you have when there is no internet. A starter downloaded before this version never updates:
  download the ZIP once more and use the new one; your jobs stay in the old folder's `working-files`.
- **From a terminal it is one install:** `uv tool install lamina3d`, then `lamina3d` opens it, and
  `uv tool upgrade lamina3d` updates it.

### Docker

- **The image runs on Debian 13**, as the Debian 12 base it was built on is no longer updated. Nothing changes in how
  you run it.
- **Dependencies are kept up to date**: the Python packages, the Docker base image and the build tools are checked
  every week, a new release is only taken once it is a week old, and every image is built and tested before an
  update is merged.

### Gallery

- **Show what you made.** The landing page has a gallery of things cut with Lamina, and a **send me a photo** link
  under the downloads on the Export tab opens a prefilled email (no account needed) or a GitHub issue form you drag
  the photos into. With your OK it goes up, credited the way you ask. Or post it on Instagram or X with
  **#applamina**.

### Auto-fix

- **Auto-fix never deletes a piece of your model.** It used to add crossing slices and then remove whatever still
  floated: on a tube that was most of the model, and on the horse the whole top layer with its ears. Now a piece
  nothing can hold stays, with its error and the fixes to click, deleting among them if that is what you want. The
  only things left out, and the report says so, are slivers too thin to cut: shavings a slot cuts off its own part,
  and specks where a slice only grazes the surface.
- **Interlocked slices are added where they actually hold.** A crossing slice through the middle of a loose piece
  was often just as loose there. Auto-fix now places it where it connects the piece to the rest of the model: the
  tube and the torus are held whole.
- **The remove choice of auto-fix is gone**: **add** holds what it can, **off** only reports. A project saved with
  remove opens with off.

### Usage counting

- **The box at the foot of the published app's Model tab now starts ticked.** While it is ticked it sends the
  technique you pick, whether the model came from the examples or your computer, and which formats you export:
  never the model, a file name, your measurements, an account or a cookie. Untick it and it stays off in that
  browser. The copy you run yourself or in Docker counts nothing at all.

### Fixed

- **The browser version no longer fails now and then while nesting.** The bunny example hit it about one time in
  three; it came from the geometry library the browser version runs.
- **Stacked slices run the full height of the model.** A 100 mm cube in 4 mm card came out 23 layers tall, with the
  missing 8 mm all at the top. It is 25 layers now, centred.
- **A stack never loses layers to the automatic fixes.** With a space between layers and dowels along lines, a
  layer no line crossed yet was removed: 11 of the horse's 20. It stays now, and the Checks tab says what would
  hold it.
- **Only the handles move a selected part.** Dragging anywhere on a selected layer used to slide it, which is also
  how you turn the view, so layers moved by accident. A plain drag now always turns the view; the arrow and rings
  (or shift- and ctrl-drag) still move, tilt and roll it.
- **Random dowels spread across each layer** instead of sometimes bunching at one end.
- **Dowel lines work from the first click.** The **+ line** button added an empty line that placed nothing; it now
  draws one up through the stack, and alt-click draws one through the point you click.
- **Folded panels keep a proper wall around their holes.** Rivet, laced and strip joints put their holes too close
  to the edge, and the one-click fix changed a setting folded panels do not use. The holes keep the full wall now,
  and the fix, when it is needed, changes the hole size.
- **Your own model starts from its own shape.** Uploading after an example kept that example's size, rounding and
  thickening, so Julia's square 100 mm cube came out 308 mm across with rounded corners and its small hole closed.
  An upload now starts with every Model setting at zero, the note after a remesh says how much it rounds the
  corners, and a model under 5 mm across (an STL saved in metres) gets a note asking for its real size.
- **Stacked slices no longer get stuck at "placing slices and slots"** on a model with flat walls, like a box with a
  hole: it never finished, and now takes about 18 s. Thanks to Colin for the report and the project file.
- **A tall slanted part is measured at its real size.** It could read as 0 mm wide, and was reported "too thin"
  instead of being split to fit the sheet.
- **Report a problem works while the page is stuck.** In the browser version, the report waited for a slice that
  would never finish, so it could only be sent after reloading, which lost what it was about.
- **Picking the same file again loads it.** After switching to an example, choosing the file you had uploaded
  before did nothing.
- **The local and Docker versions no longer finish slices nobody is waiting for.** Dragging a slider through a few
  values computed every one of them to the end, side by side, and made each slice several times slower.
- **A problem report says how you got there.** Besides the settings and the checks, it now carries the Lamina
  version and every step since you loaded the model (each setting changed, undo, fix clicked, slice and error), and,
  if a slice is still running, how long it has taken. **See what is sent** in the report dialog shows all of it
  before you send. Saving a project is unchanged: it holds the design, not the steps.
- **A dowel in the 3D view has the shape of its hole.** Square, hexagonal, cross and slot dowels were all drawn
  round, so changing the shape seemed to change nothing. Their weight uses the real shape too.
- **Every piece of a layer is its own part.** A layer that falls apart into separate shapes, like the lobes at the
  ends of the wavy torus, was one part: its pieces were nested together with the empty space between them, and only
  one had a label. Each piece is now a part of its own, labelled `Z-1-1`, `Z-1-2` …: the wavy torus goes from 14
  sheets to 8.
- **Aligned tab spacers hold every layer.** Every second pair of layers could end up with no spacer at all, and
  spacers that did fit could cut into each other. Each spacer is now placed where its slot really fits both layers,
  with a full wall around it.
- **A new example starts every technique fresh.** Switching the horse to stacked after the statue brought back the
  statue's 2 mm square dowels on its side axis, so every tab spacer came out too thin to cut. An example now opens
  every technique on its defaults and its own preset; your own model keeps the settings you gave it.
- **A spacer too thin to cut says why, and how to fix it.** Tab spacers and pegs are as wide as the connector, but
  their error told you to thicken or round the model, which never reaches them. It now names the connector size, and
  one click sets one that works.
- **Turning the view while a model loads turns the view.** On the Model tab, a drag across the view while a new model
  was slicing could catch a turn ring and stand the model on its head. While a slice runs, a drag only turns the view.
- **Every part lands on its sheet.** A part that filled a sheet almost exactly, like a big folded panel, could be
  placed far off the sheet, big jobs could run a part into the sheet margin, and now and then two parts were nested on
  top of each other. Every part is placed inside the margin and clear of the others now.
- **Interlocked slices added by auto-fix keep a full wall from each other.** One could land so close to another that
  barely 1 mm of material was left between their slots.

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
