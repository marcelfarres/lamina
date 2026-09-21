# Changelog

What changed in each release. The GitHub release for a version is this section, pasted.

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
