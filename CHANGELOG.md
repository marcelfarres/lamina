# Changelog

What changed in each release. The GitHub release for a version is this section, pasted.

## 0.3.1

The Export tab says how much sheet to buy, and the SVG can be written one group per colour again for software that
prefers it. The installable package is up to date again.

### Added

- **How much stock to buy.** The Export tab now gives the sheet area beside the weight: m², or ft² when the units are
  inches, counted on whole sheets with their offcuts. It is the figure to compare with a shop's price per square
  metre or the size of a pack. Beneath it, the area that ends up in the parts and the share of the stock that is
  used, and a job that mixes thicknesses gets the sheet count and area on each stock line too. Thanks to @Schnema1.
- **The SVG can keep the colours apart again.** A switch under Export, *group parts*, on by default: off, the sheet
  is written one group per colour for the whole file, with the border, arrows and labels together in the label
  colour — the layout for software that wants the colours kept apart and never moves a part on its own. The command
  line has the same switch. Thanks to @Schnema1.

### Fixed

- **Stacked slices with many dowels stopped with an error.** A pair of layers joined by more than 24 dowels or
  pegs, a large model with several islands per layer, failed to slice. Past z the names now double up: Z-1aa, Z-1bb.
- **`uv tool install lamina3d` and `pip install lamina3d` gave 0.2.5.** 0.3.0 never reached PyPI; this version does.
- **A project file could name a folder outside the job.** The revision went into the cut files' names as written, so a
  project file someone else made, with a path in its revision, had a download written beside the job instead of in it.
  The revision is now cleaned like the project name: letters, digits, dots and dashes, nothing else.

## 0.3.0

The release for the laser: every label in a single-stroke font, dowels named after their slices and numbered beside their holes, labels that keep clear of parts and of each other, orientation arrows, a four-letter short name, and non-uniform spacing drawn as a curve in every technique, with a graph to draw it; a stack can be shifted to land a slice on a feature. Thin tips and slivers are found and can be trimmed off, small parts go into the hollows of big ones, and the first sheet is filled before the second. Folded nets got seam numbers that can be read and hinge lines for their tabs, the SVG keeps each part with its labels, and the assembly video names each part as it goes in.

### Added

- **Non-uniform spacing, drawn as a curve.** Stacked, interlocked, radial and curve each have a *vary the spacing*
  switch, and with it a graph under the 3D view: the distance between neighbouring slices against the position
  along the way — for radial the angle between the fan's planes against the angle round the axis, periodic, so the
  fan closes on itself; for interlocked one graph per family, each along its own axis. Drag the points (double-click
  adds one, alt-click removes one) and the model re-slices: dense where the shape changes fast, sparse where it does
  not. The curve between the points never overshoots them. *Keep* decides what is fixed: the count, with the drawn
  spacings scaled to span the model (the graph says by how much), or the spacings as drawn, with the count following.
  The ticks under the graph are where the slices went. Four new examples open with a curve: `vase` (stacked, dense
  at the foot, shoulder and lip), `ripple` (interlocked, one family following a ripple that tightens), `berry`
  (radial, the planes crowding the bumpy side) and `hook` (curve, ribs close round the bend). Slices a curve puts
  closer than the material are an error, with the pair named.
- **Stacked: shift the stack.** A new `shift` parameter moves every slice plane along the axis by the same amount,
  so one slice lands on a feature of the model — a rim, a shoulder, the middle of a hole — instead of wherever the
  even spacing put the nearest one. Laid by distance, the stack is laid again from the shifted start, one slice after
  another over the model; by count or along a spacing curve the slices keep their spacing, and one moved past an end of
  the model is left out, with a note, and two that a thick slice among them makes overlap are an error that names
  the pair.
- **Thin spots found, and trimmed on request.** A part with a tip or a sliver too thin for too long — the point of a
  radial slice where it meets the surface at a grazing angle, the wall left between a slot and the edge — is
  warned about, with what would break off and how long it is; the cylinder's 0.7 mm walls beside its end slots and
  the cone's points passed every check before. A new `trim thin spots` switch (`trim_thin`, among the fixes the
  warning offers) cuts them off: the part ends blunt there, a little short of the model, and the plan says how
  many spots went. The cone, blob and cylinder examples open with it on.
- **Dowels named after their slices, and marked beside their holes.** A connector is named after the lower of the
  two slices it joins and a letter: `Z-3a` is dowel *a* between `Z-3` and `Z-4`, and `3a` is engraved beside its
  hole on both slices. Read a slice's holes by their numbers: one below the slice's own takes the rod from below, its
  own number the rod going up — with random placement, where every pair of layers has its own holes, nothing on the
  part used to say which was which. A straight rod through several slices keeps the name of the slice it starts
  from; with tab connectors the peg or spacer is the connector and carries the name as its part label (they were
  `P-1`, `P-2` … in cut order). The assembly key lists every rod with its ends and its length. Marks — these and the
  seam numbers of folded panels — now turn with their part on the sheet, so a mark placed beside a hole stays beside
  it however the part was nested, and a hole is never cut through a mark engraved before it.
- **Orientation arrows.** A new sheet option (`orient_mark`) engraves two small arrows at the middle of every part,
  with the labels: a long one up the part's frame and a short one to its right, the same two directions on every
  part of the model, so a part turned on the sheet or laid face down is seen at once — the engraved face is the front.
  Labels keep clear of them, and the assembly key says what they mean.

### Changed

- **Each part is one group in the SVG**: its cuts, fold and guide lines, dowel numbers, arrows, label and leader line
  sit in one `<g class="piece">` (with a sub-group per layer), so a part dragged elsewhere in Inkscape or Illustrator
  takes its labels with it instead of leaving them behind. The border and title are the sheet's own group. Each
  layer group keeps its colour, which is what laser software sorts by, so cut settings by colour work as before.
- **Two stacked examples open with tab connectors**: the `tube` with pegs and the `wavy_torus` with spacers across
  its 5 mm gaps, beside the dowelled ones, so both kinds of connector are on show.
- **The model's name on each label is now a short code.** A label used to start with the whole project or model
  name — `horse_statue Y-12-2` is nineteen characters, most of them the name — which is what made the labels of a
  scanned model with a hundred small parts impossible to place. It now starts with up to four letters: the initials
  of the name's words (`HS Y-12-2`, `MFC Z-1`), or the first four letters of a one-word name (`BUNN Z-3`); a new
  `short_name` field sets it, and the assembly key says which name it stands for.
- **Labels on the parts where they fit, in free space where they do not.** A label used to go beside its part at
  one of thirty spots round its bounding box, and when none was free — on a full sheet of a scanned model, most of
  them — it was dropped on the part with no check at all, over neighbours, other labels and the sheet edge. It now
  goes on the part itself wherever the whole label fits on the material, inside the next layer's outline where there
  is one, upright or turned along the part, clear of holes and marks; otherwise beside the part at the nearest free
  spot searched outward from its outline, inside the margin, touching no part or label, with a leader line that
  crosses no other part and starts at the label's edge rather than through its letters. `labels on the parts`
  (`label_inside`) became `labels go` (`label_place`): *part*, the new default, *beside* for nothing engraved on the
  parts, *on* for always on the part; a project saved with the tickbox keeps what it had. A part with no free spot
  anywhere is tried smaller first — four fifths, two thirds, half the font — on the part and beside it, before it is
  put on the part anyway and counted in the notes. The sheet title is engraved inside the top margin at a size that
  fits it, where it used to run into the parts, and the one-file-per-part export engraves the label exactly where
  the sheet does.
- **Labels in a single-stroke font.** Every engraved text in the cut files — part labels, seam numbers, the sheet
  title — is now drawn in a stroke font (Hershey Simplex): each letter is a few open lines the laser engraves in one
  pass, the same lines in SVG, DXF, PDF and EPS. Text used to be left as text, which the laser's software filled with
  whatever font it had and traced as the two edges of every letter, or dropped when the font was missing. The `font`
  parameter is now the height of a capital letter in mm, so a 4 mm label has 4 mm capitals (it used to be a 4 mm
  font size, with capitals under 3 mm); the labels take a little more room beside the parts for it.
- **The support link says what it is.** The README shows the Ko-fi button, with its logo, under the badges and again
  in the Support section instead of a small badge at the top and a sentence at the very end. In the app the header
  link reads "support Lamina on Ko-fi" rather than just "Ko-fi", and the note at the foot of the Model tab says you
  can buy me a coffee there. Nothing else changes: Lamina stays free, with no account and no paid tier.
- **The header fits on a laptop.** On a window narrower than about 1700 px the header ran past the right edge, so
  Discord, "report a problem" and the support link were off-screen on most laptops. It now wraps onto a second row
  when there is not enough room, and stays one row on wide screens.

### Fixed

- **What goes on a part, and in what order.** The orientation arrows, the dowel and seam numbers and the label used
  to be placed without regard for each other. Now the numbers go first, the arrows take the widest spot they leave,
  and the label goes on the part only where it fits with room to spare — otherwise beside it, searched outward over
  the whole sheet, and as a last resort with its line running across whatever lies between. A label is never put
  where it overruns its part again. The rectangle packing is tried beside the polygon nest and kept when it needs
  fewer sheets. A part too small for its label at any size carries its name without the short name in front, which
  the assembly key allows for, before the label goes far away on a line. A part that cannot carry even that is
  nested with the room for its name reserved beside it, so the label sits next to the part on a packed sheet
  instead of wherever a gap was left: the wavy torus's 68 spacers had their labels up to 35 cm away, now within
  10 mm. The last resort may use the sheet's margin band, where the title already is.
- **Small parts go into the holes of big ones.** A hollow model's slices are rings with a wide empty middle, and the
  nester left those middles empty: each dowel hole counted as a notch when the outline was cut into convex pieces
  for the no-fit polygons, a slice with thirty of them blew past the cap and was treated as its hull, which
  covered the middle. Holes too small for any part to go in are filled before that cut, so the bunny's small
  parts now sit inside its big slices.
- **A peg's name on the peg.** A part too narrow for its label at the font or a little under went beside with a
  leader line, and a column of fourteen pegs on the tube's sheet had fourteen lines crossing each other to
  names turned every which way. The label now goes on the part down to two thirds of the font, the size the
  nester already reserved room for, so a peg carries its own name along its length.
- **The first sheet is filled before the second.** When the polygon nest and the plain rectangle packing need the
  same number of sheets, the one that leaves less for the last sheet is kept: the tube's seven 3 mm rings went
  five, two (the second row dropped into the valleys of the first and lost a column), now six and one.
- **A split never leaves loose pieces.** A part too big for the sheet is cut into strips, and the cut used to be
  free to fall exactly where the other family's slots end — the tall bar's lower half came apart into three pieces,
  one a 13 × 73 mm triangle held by nothing. Each cut now slides sideways until the piece on either side of it is
  whole, and when no position manages that the slice says so as an error.
- **Orientation arrows keep well inside a small part**, at most six tenths of its clearance, and a part too small
  for a legible pair gets none.
- **Folded nets you can build.** Seam numbers were dropped at every seam's middle with no check, hundreds of them
  over each other and across the fold lines of a scanned model's net. Each now reads along its own edge, on the tab
  where the seam has one (as Pepakura prints them) or just inside the edge, only where the panel has room, and the
  panel's warnings count the ones left off. A tab that would land on its own panel is put on the other side of the
  seam instead of being dropped, which gave the cow example 49 more tabs. The hinge of a tab is scored across its
  base only, where it used to run the whole seam under the cut line. The legend explains folds, cuts and how to read
  the numbers.
- **The browser build tries a slice once more when its geometry engine fails.** The browser's GEOS now and then
  reports "orientationIndex encountered NaN/Inf" on a model that slices the next time, more so with the fuller
  cut sheets of this release: the worker now collects its garbage and runs the request again before reporting
  an error, and every new per-part computation falls back to a safe default when the engine fails inside it.
- **The assembly video names each part.** While the steps slider is short of the end, the 3D view carries the step
  number and the name of the part going in at the top centre, drawn into the canvas, so the recorded video shows it.

## 0.2.5

The first version with changes from outside Lamina: @Schnema1 sent three. A stacked slice can carry the outline of
the layer above as an engraved line to glue by, labels can go on the parts themselves where the next layer hides
them, and the steps slider is wide enough to land on one layer at a time. Round, thicken, hollow and shrinkwrap
keep a curved model smooth instead of faceting it. The one-file-per-part export now keeps a panel's fold lines, and
there is a Discord.

### Added

- **Stacked: the next layer's outline, engraved on the slice below.** A new option for stacked models engraves on
  each slice the outline of the layer that goes on top of it, as a light line: a GUIDE layer of its own in the cut
  files (orange), so the laser engraves it and cuts nothing. Line the stack up by it as you glue. An offset moves the
  line a little inward, so the layer above hides it even when the glue-up is a hair off. The line is drawn only where
  there is material under it, never over a slot or a dowel hole, and slices that are the same part with the same line
  are still cut once with a quantity. Thanks to @Schnema1.
- **Labels on the parts themselves.** A new sheet option engraves each part's label on the part instead of beside it
  with a leader line. On a stacked model with the next layer's outline engraved, the label goes inside that outline,
  so the layer glued on top hides it; otherwise it sits where the part is widest. A label too big for a small part is
  still placed, running past the edge if it must, for you to trim in your laser software: no part comes out without
  its name. The one-file-per-part export grows its drawing so such a label is not cut off. Thanks to @Schnema1.

### Changed

- **Round, thicken, hollow and shrinkwrap keep a curved model smooth.** Any of them used to send the model through a
  grid of cubes, and a smooth curve came back faceted and bumpy, both in the 3D view and on the cut parts, with the
  whole surface sitting a little outside where it was. The remesh now measures the real distance to the surface
  and puts it back exactly where it belongs: on a smooth blob the result is as smooth as the model itself, within a
  few hundredths of a millimetre, and the 3D preview stays smooth too. The values act exactly as well: thicken 1
  grows the model by 1 mm, not by a whole cube, and the note that said "acted as" is gone. The price is time: a
  model with round set takes a few seconds longer to prepare than before (the examples, 3 to 6 s where it was
  under 1), and several times that in the version that runs in the browser; the progress bar shows the step.
  Detail finer than the grid (the note after slicing gives its size) is still lost, and
  a sharp edge or corner is softened by up to half a grid step. Parts that overlap in the file (a leg pushed into
  a body) are one solid, a closed inner surface is filled, and a shell that is open somewhere (the bunny example
  is one, with a 7 mm wall) stays a shell, as it is with every value at 0; the old grid thickened its wall shut.
  The bunny, head and horse statue examples' settings were re-tuned for the exact remesh: the bunny is thickened
  2 mm, the head lets the grid pick its own size (it no longer needs a fine one to look smooth, and opens in a
  third of the time), the statue stacks without a gap.
- **The 3D view shades curved surfaces smoothly.** The translucent model used to be drawn with a flat shade on every
  triangle, so even a model that was never remeshed looked faceted; it is now shaded across the triangles, with
  edges sharper than 30° kept sharp.
- **The steps slider is easier to use.** The slider that plays the build order over the 3D view is almost three times
  as wide, so a drag lands on one layer at a time, and a counter beside it reads the step you are on, live as you
  drag and while the assembly video records. Thanks to @Schnema1.
- **Share your build with #lamina3dapp.** The note that invites you to share a photo of your build now names
  #lamina3dapp: #lamina3d is already full of posts about other things, so a build posted there was easy to miss.
- **A Discord for Lamina.** Ask a question, share an idea or show what you made at
  [discord.gg/N66bCQxmt3](https://discord.gg/N66bCQxmt3), linked from the app's header, the landing page and the
  README. Bugs are still best sent with **report a problem**, which brings the model and settings along.
- **The Docker image runs on Python 3.14**, the same Python the starters install, with the current uv.

### Fixed

- **A turned interlocked grid reaches the corners.** With the grid rotated (`rotate_grid`), the slices were spread
  over the model's box, which is shorter than the model is across the turned directions, so the corners got no slice.
  They are spread over the model's real reach along each family now.
- **A slice auto-fix adds no longer renumbers the ones after it.** An extra interlocked slice used to take the next
  number in line, so every slice after it moved up one and a per-slice setting (an offset, a tilt, a deleted slice)
  landed on the wrong slice. Added slices are numbered after the family's own, and the assembly key says so.
- **Two parts with a hole in a different place are two parts.** Identical parts are cut once with a quantity; the test
  for "identical" allowed a difference of a thousandth of the area, which on a big layer let a dowel hole a millimetre
  off pass, and the copy was cut with its hole in the wrong place. Outlines now have to lie within a tenth of a
  millimetre of each other everywhere, and what is engraved on them (a guide line, a seam number) has to match too.
- **One file per part carries the seam numbers.** Folded panels and strips engrave a number beside each seam on the
  sheet; the one-file-per-part export left them off. They are in those files now.
- **The guide is the layer as it is cut.** The next layer's outline, engraved on the layer below, is drawn from the
  layer as it comes out of the cut: a sliver too thin to cut is left off it, and a dowel hole is not drawn as a ring.
- **One file per part: the label goes where the sheet puts it.** With labels on the parts, the one-file-per-part
  export placed a part's label at its widest spot even when the sheet had put it under the next layer's outline, so
  the two disagreed and the file's label could show on the finished model. Both now use the same rule. In the same
  export, turning labels off was ignored for every part but the scale-check bar; the files are plain again when asked.
- **A part cut into strips keeps its guide.** A stacked slice too big for the sheet, split into strips, lost the next
  layer's outline on every strip. Each strip now carries the part of the line that lies on it.
- **The guide closes where the layers share an edge.** Where the layer above sat exactly on an edge of the layer
  below, that side of its outline could be lost to rounding, so the engraved ring stayed open and the label could not
  find its way under it. The whole ring is kept.
- **The browser version's downloads do what the server's do.** In the version that runs in the browser, leaving the
  assembly key out of a puzzle export had no effect, the fit test downloads (print and cut) answered "not found", and
  the prototype's font size, minimum thickness and slot offset reached the wrong settings. All four behave as they do
  with the local version.
- **A model named in another script exports.** A model or project named with an umlaut or in Chinese made every
  download fail after a good slice, and the EPS export failed on its own. The files are named in plain letters, the
  label is engraved as typed where the format allows, and the EPS writes a ? for a letter it cannot carry.
- **One long sheet is as long as its labels.** With `one_sheet`, the topmost part's label sat past the end of the
  sheet, where the cut file cut it off. The sheet's length now includes the labels.
- **What a technique says about a slice is shown.** A dowel typed outside every layer, a folded seam with no room for
  its joint, a joint made smaller to fit: these messages were written on the slice and then wiped before the checks
  ran, so they never reached the Checks tab. They show now.
- **Installing Lamina on a fresh computer works again.** A brand-new Python came out this week that three of
  Lamina's libraries have no builds for yet, and the installer picked it, so the start script stopped with a
  compiler error. The starters now ask for the Python Lamina is tested on, and an install on the newest Python
  leaves those three libraries out until they catch up (engraved labels on prototypes need one of them, and say so).
  A copy already installed was never affected.
- **One file per part keeps the lines.** The one-file-per-part export left every fold line off a folded panel, and
  would have left off the new guide line; both are in those files now, exactly as on the sheet.

## 0.2.4

Clearer and quicker. Machine & cut compensation and the Export tab now explain themselves, step by step. A change you
make while a model is slicing stops that slice instead of waiting behind it, and nesting, remeshing and renaming all
take less time. Two fixes matter for the parts themselves: your machine's kerf and slot offset no longer drop to 0
when an example loads, and a model with a hole in it slices.

### Changed

- **On a phone, Lamina says it is made for a computer.** The first time it opens on a phone, a short note says that
  editing in the 3D view wants a mouse and a wide screen, and suggests a computer. It runs on anyway, with the panel
  above the 3D view so the page fits the screen.
- **The machine settings explain themselves.** Machine & cut compensation now comes in three parts, kerf, slot fit and
  inside corners, each with a line saying what it does and whether it always applies: only the kerf is switched on and
  off by "compensate kerf", while the slot offset and the corner relief always apply. Every setting has a plain name
  and says when to change it, with typical values and how to measure them, and the corner relief choices say what they
  are for.
- **The Export tab goes step by step.** First the fit test (cut it first, and how to read it), then the parts, then
  building it. Every download now says what it is for: which laser software or CAM opens it, or what else to use it for.
- **Nesting is faster on your own computer.** Laying the parts out on the sheets now tries each part's four turns side
  by side, about twice as fast on a big model (the bowl's nesting went from 5.0 s to 2.1 s); the layout is exactly the
  same. The browser version lays them out as before.
- **Rounding, thickening and hollowing are quicker.** Preparing a model this way, or remeshing one that does not
  close, takes up to a third less time: the bunny's rounding went from 1.4 s to 0.9 s.
- **Share your build with #lamina3d.** The note that invites you to share a photo of your build now names #lamina3d,
  the one name Lamina uses everywhere (it said #applamina).

### Fixed

- **Zooming with the wheel behaves.** With the browser zoomed below 100 %, one turn of the wheel put the view right on
  the model's centre and it could not zoom back out; a fast spin or a touchpad flick dived straight into the model. Each
  notch now zooms by the same small step on any screen, toward what is under the pointer, and the view stops short of
  the model's surface and never loses the model zooming out.
- **What's new keeps its lists.** On a copy of Lamina cloned on Windows, these notes ran a whole version together as
  one paragraph, every point inline. Each point is on its own line again.
- **Your machine's kerf and slot offset stay put.** Opening the app, or picking another example, set the kerf and the
  slot offset to 0 while the machine list still named your machine, so the parts were cut with no fit allowance at all.
  They now keep your machine's values, or the ones you set after a fit test, until you pick another machine. An example
  that comes with its own machine brings that machine's values.
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
