# Changelog

What changed in each release. The GitHub release for a version is this section, pasted.

## 0.2.2

### Model

- **Square it up.** A boxy model that sits a few degrees off its axes (a rotate slider left at 85 instead of 90, a
  CAD export that came out tilted) cuts every straight edge as a staircase. The Model tab now says how far off it
  is, "sits 5° off square", with a **square it up** button right under the rotate controls. Nothing turns by
  itself: leave it if the tilt is on purpose.

### Fixed

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
