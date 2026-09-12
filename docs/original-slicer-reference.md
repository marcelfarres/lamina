# Autodesk Slicer for Fusion 360 (formerly 123D Make) — Exhaustive UI/Option Reference

Compiled from public documentation, archived help text, university makerspace guides, and
community wikis. Autodesk's own hosted help pages for Slicer are gone (product is deprecated/EOL,
no longer maintained since ~2020); the best surviving primary source is an archived copy of the
in-app Help text on archive.org (see Sources). Where a value could not be confirmed from any
source, it is explicitly marked **unconfirmed**.

Status: Slicer for Fusion 360 is a **standalone desktop app** (not inside the Fusion 360 UI
itself) that imports a mesh, lets you choose a "construction technique" that slices/segments it
into flat, laser/CNC-cuttable 2D parts sized to a sheet material, previews assembly, and exports
cut plans (PDF/EPS/DXF).

---

## 1. Import

- **Supported input formats:** `.stl`, `.obj`, and Slicer's own `.3dmk` project format (3DMK
  from the 123D Make lineage). Loaded via an **Import** / **Open** button.
- **Fusion Team integration:** files can also be opened directly from Fusion Team (Autodesk's
  cloud storage) in 3DMK/STL/OBJ. A new Fusion Team account had to be registered to an A360 hub
  before cloud open/save/export worked.
- **No live link from Fusion 360 itself:** per the archived help text, "any mesh cannot be sent
  from Fusion 360 to Slicer application" — i.e. there is no direct "send to Slicer" design-link
  the way there is for some other Fusion workflows; you export a mesh from Fusion 360 (or any
  other tool) and then **Import** it into the separate Slicer app.
- **Up-axis correction on import:** a dialog lets you change which axis (X/Y/Z) is "up" for the
  imported mesh, needed when the source app used a different up-axis convention (e.g. Y-up vs
  Z-up). The model does not auto-rotate — you must set this manually if the import looks sideways.
- **Format quality note (community guidance, unconfirmed as official):** STL import reported to
  give more reliable results than OBJ in some workflows.
- Claims of `.3mf`/`.f3d` import or `.svg` export found in one low-reliability secondary source
  are **unconfirmed** and not corroborated by the archived official help text or other sources —
  treat as likely incorrect.

---

## 2. Manufacturing Settings (wrench/gear icon)

A named, savable **preset** system. Presets can be created (**+**), duplicated for variation
(**\***, "duplicate and tweak"), and deleted (**–**); a saved preset appears in the Manufacturing
Settings dropdown for reuse across projects.

- **Units:** dropdown for the measurement system used by all size fields in the preset (in/ft/mm/cm
  typically — exact list of unit choices **unconfirmed** for this panel specifically, though the
  DXF export panel is confirmed to offer inches, feet, cm, and mm).
- **Sheet / stock size:**
  - **Length**, **Width**, **Thickness** — numeric fields defining the raw material sheet.
  - **Standard presets** for common sheet stock (e.g. common cardboard/plywood sheet sizes) that
    auto-populate length/width/thickness; you can also enter fully **custom** dimensions.
- **Slot Offset (kerf compensation):** adjusts the width of generated notches/slots to compensate
  for material removed by the cutting tool (laser kerf or router bit).
  - `0` → notch width equals exact material thickness (a mathematically perfect fit).
  - **Negative/decreased** values → tighter notches, forcing a snugger, friction-fit assembly.
  - **Positive/increased** values → looser notches, more clearance for material-thickness
    variance or a looser assembly.
  - Community-reported example presets: ~0.25 mm slot offset for laser-cut cardboard/plywood
    (**unconfirmed** as an in-app default; observed as a user-chosen value in tutorials).
- **Tool Diameter:** used specifically to size **Dog Bone** relief notches for CNC routing (a
  circular relief cut at each interior notch corner sized to the router bit radius, since a round
  bit cannot cut a perfectly square interior corner). A value of `0` disables/prevents Dog Bone
  relief generation. For laser cutting, tool diameter is typically set to `0` or a near-zero value
  (e.g. `0.0001"`) since the laser kerf is handled by Slot Offset instead.

### Object Size panel
- **Original Size** button: reverts the model's dimensions back to its as-imported/native STL
  size (undoing any scaling), reinterpreted in the currently selected units.
- **Uniform Scale toggle:** when **on**, changing one of height/width/length scales all three
  dimensions together (proportional/locked-ratio scaling); when **off**, each axis (height,
  width, length) can be scaled independently/non-uniformly.
- Increasing object size increases slice count and geometry complexity, which increases
  processing/render time (noted in sources as a performance consideration, not a hard limit).
- A **"lock ratio"** control is described in some secondary sources as functionally identical to
  the Uniform Scale toggle above; treat these as the same control under possibly different naming
  — exact on-screen label **unconfirmed** beyond "Uniform Scale."

### Modify Form (global mesh pre-processing, applied to the whole model before slicing)
Three toggleable operations, applied before construction-technique slicing (not per-slice):
- **Hollow:** removes interior material, converting a solid model into a shell of a given wall
  thickness, to reduce material use / weight while preserving outward shape. Has a wall-thickness
  control; exact slider range/default **unconfirmed**.
- **Thicken:** grows/widens thin geometry (thin walls, fine points) so they survive cutting/
  printing without breaking; described as slightly altering the model's original shape as a
  trade-off. Has a thickness control; exact slider range/default **unconfirmed**.
- **Shrinkwrap:** wraps a smooth/simplified surface around the model, rounding off small sharp
  details (help text's example: "sharp T-rex teeth" get rounded and softened) and closing up
  holes/gaps to produce a watertight, more reliably-sliceable mesh. Has a
  resolution/aggressiveness control; exact slider range/default **unconfirmed**.
- (Community note: reducing sheet **Thickness** to a very small value, e.g. ~0.005in, in
  Manufacturing Settings was suggested as a way to preview Folded Panels perforation lines more
  clearly, since at normal thickness perforation marks can look like solid cut holes at first
  glance.)

---

## 3. Construction Technique

A single dropdown/list selects one of six mutually exclusive slicing methods. Switching
techniques re-slices the model from scratch using that method's own parameter set. All
slice-based techniques (Stacked, Interlocked, Radial, Curve, 3D Slices) share a common
**Slice Direction** manipulator: a draggable handle/gizmo (cone or arrow) on the model that sets
the slicing axis; dragging snaps to **5° increments** via visible guide rings, snapping can be
disabled by dragging away from the rings, and a **Reset** button restores the default direction.
The Slice Direction manipulator is **not available for Folded Panels** (which slices by mesh
faces, not a linear axis).

### 3.1 Stacked Slices
Cuts the model into parallel horizontal-style cross-section slices along the slice-direction
axis; each slice is a flat outline meant to be cut, stacked, and glued (classic LOM/laminated
object manufacturing).
- **Slice Direction / axis:** shared manipulator described above — sets the plane-normal axis
  along which parallel slices are cut.
- **Slice Distribution:** method for how many/where slices fall — **by Count** (fixed number of
  evenly spaced slices) or **by Distance** (slices spaced at a fixed interval, count follows from
  model size ÷ interval). Numeric count/distance field accompanies the chosen mode; exact default
  values **unconfirmed**.
- **Dowels** (optional alignment pins added on top of the stacked-slice output):
  - **Diameter** field: sets dowel width, in the model's working units.
  - **Shape** dropdown: **Square, Pencil, Round, Cross, Horizontal Slot, Vertical Slot** (six
    options).
  - **Placement:** manual, by clicking in the (light-blue-highlighted) 3D viewport — a dashed
    guide line previews where the dowel hole will be cut through the stack; click an existing
    dowel's circular marker to drag/move it; delete a dowel via the **Delete** key or
    **Ctrl+click**.
  - **Automatic** button: auto-places a set of dowels across the model without manual clicking.
  - Exact default dowel count/size **unconfirmed** (no fixed default is stated in the surviving
    text; placement is user- or auto-driven rather than a fixed count parameter).

### 3.2 Interlocked Slices
"Cuts your 3D model into two stacks of slotted slices. Lock them together in a grid, like when
building a 3D puzzle." Produces two perpendicular families of slotted slices (1st axis and 2nd
axis) that slot together egg-crate style.
- **1st Axis slice count/distribution** and **2nd Axis slice count/distribution:** each axis has
  its own **Slice Distribution** control (by Count or by Distance, as above), independently
  setting how many slices are generated along that axis. Increasing either axis's value produces
  more, thinner slices in that direction and more total parts.
- **Slice Direction:** a control to rotate the overall interlocking grid's orientation (e.g.
  rotate the horizontal-layer orientation by increments, community sources mention a 90° rotate
  option).
- **Notch Factor:** "flares the mouth of the slot by a specific amount, relative to the width of
  the slot" — widens the entrance of each interlocking notch to make assembly easier (a chamfer/
  flare at the slot opening, proportional to slot width). Exact numeric range/default
  **unconfirmed**.
- **Notch Angle:** the angle (relative to the slot's direction) at which the notch-mouth flare is
  cut. Default **45°**, explicitly stated as chosen to "aid with easy assembly."
- **Relief / Notch type** dropdown — controls the shape of the interior corner of each notch:
  - **Square** (default) — a plain square notch corner.
  - **Horizontal** and **Vertical** — relief cut oriented along one axis at the notch corner.
  - **Dog Bone** — adds a small circular relief cut (sized from Manufacturing Settings' **Tool
    Diameter**) at the interior notch corner so slices can fully penetrate one another with no
    rounded-corner interference; needed because a round cutting tool (router bit) can't produce a
    sharp interior corner.
- **Interactive slice manipulation:** individual slices can be click-dragged in the 3D preview to
  reposition them; spacing/notches recompute automatically.

### 3.3 Curve
"Cuts slices perpendicular to a curve, resembling ribs." Intended for organic, rib-like forms
(e.g. boat-hull or fuselage-style construction) — each slice is cut perpendicular to a
user-drawn curve rather than along a single straight axis.
- **Curve drawing/editing:** the curve is represented on-screen as a line (an orange line, per
  one community source) with draggable control points (blue dots); dragging a control point
  reshapes the curve and correspondingly changes the angle/position of the ribs (slices) along
  it. The curve exists on a single plane; changing "slice direction" affects/reshapes the curve.
- **Slice Distribution:** by Count or by Distance, same as other techniques, sets how many rib
  slices are produced along the curve's length.
- **Notch Factor:** same flare-the-slot-mouth control as Interlocked Slices, applied to how ribs
  notch into any cross-members. Exact range/default **unconfirmed**.
- (Full notch-type/relief options for Curve beyond Notch Factor are **unconfirmed** — sources
  describe it as sharing the interlocking-notch machinery conceptually but don't enumerate a
  separate relief dropdown specifically for Curve.)

### 3.4 Radial Slices
"Cuts your 3D model into radiating slices from a central point. Use this for a round symmetrical
object, such as a vase." Produces slices that fan out radially around a central axis, like spokes.
- **Axis:** sets the central axis the radial slices fan around (uses the shared Slice Direction
  manipulator).
- **Radial (Count):** the number of radiating slices/spokes generated around the central axis.
- **1st Axis** density control: an additional distribution setting affecting slice density along
  the central/vertical axis independent of the radial count (per community tutorial description).
- **Notch Factor:** same slot-flare control as Interlocked Slices, for how radial slices notch
  into a central spine/hub piece if present. Exact range/default **unconfirmed**.

### 3.5 Folded Panels
"Separates your 3D model into 2D segments of triangular meshes. These segments (panels) are
folded multiple times, then attached using one of ten different joint types." This is the
Pepakura-style papercraft technique: the mesh is unfolded into flat panels connected by fold
lines, joined at their edges by tabs/seams rather than by full-depth slot-and-tab slices.

- **Simplify Form:** a control (described as adjusting vertex/face — i.e. triangle — count) that
  reduces the mesh's polygon count before unfolding, to reduce the number of resulting panels and
  simplify assembly. Reducing triangle count ("decimation") is noted to sometimes produce
  interesting/stylized low-poly results as a side effect. Exact slider range/default
  **unconfirmed**; likely a percentage or target-triangle-count slider.
- **Optimize Panels:** reduces panel vertex count (simplifies panel boundary shapes) independent
  of Simplify Form's mesh-wide decimation.
  - **Perforate** option: adds perforated (dashed) fold lines matching the material thickness,
    instead of a plain scored line, to make folding along thick material easier. (Perforation
    lines can visually resemble solid cut holes in the 3D preview until sheet Thickness is
    reduced to check them, per community tip.)
  - **Split Panels:** an option that creates a separate panel for every individual mesh face
    (maximum fragmentation — most material-efficient nesting but most assembly joints).
- **Add/Remove Seams:** manual editing — click a mesh edge in the 3D view to add a seam (splits
  one large panel into two smaller ones along that edge) or remove a seam (merges two adjacent
  panels back into one larger panel), giving manual control over panel size vs. joint count.
- **Joint Type:** dropdown of **ten joint types**, each connecting adjacent panel edges after
  unfolding, each with its own parameter set:

  | Joint Type | Description | Parameters |
  |---|---|---|
  | **Diamond** | Fold-and-affix using small triangular tabs/ticks | Tick Radius |
  | **Gear** | Fold-and-affix using rectangular tabs with gear-like cutouts | Tooth Radius (distance from edge), Tick Spacing, Tooth Scale |
  | **Laced** | Panels laced together through holes (like a shoelace/rivet) | Hole Radius, Joint Space, Tick Radius |
  | **Multitab** | Multiple small tabs fix panels together | Tick Radius, Tab Fraction (tab width as a fraction of edge length) |
  | **Puzzle** | Interlocking jigsaw-puzzle-shaped edge tabs | Tick Radius |
  | **Rivet** | Panels riveted together through holes | Hole Radius, Joint Space, Tick Radius |
  | **Seam** | A plain sewn/glued seam, no tabs | Seam Radius (border width) |
  | **Tab** | Tabs insert into cut slots on the adjoining panel | Tick Radius |
  | **Ticked** | Small ticks connect panels continuously along the seam | Tick Space, Seam Radius, Tick Radius |
  | **Tongue** | Tongue-and-groove-style edge joint (listed in the dropdown; parameter detail **unconfirmed**) | Tick Radius (assumed, **unconfirmed**) |

  (Note: one secondary source calls this "Tab"/"Tongue" pairing "similar" joints; treat Tongue's
  exact behavior/parameters as **unconfirmed** beyond its name and presumed Tick Radius control.)

- **Fold angle / score vs. cut differentiation:** fold lines are exported as **score** lines
  (not cut through), shown as **yellow** guides in the Cut Layout preview (see §4), distinct from
  blue (outer silhouette) and green (interior cut) outlines. A discrete numeric "fold angle"
  parameter/slider (e.g. constraining folds to specific angles) is **unconfirmed** — Folded
  Panels appears to derive fold angles from the actual dihedral angle between adjacent mesh faces
  rather than exposing it as a user-set slider.
- **Dowels/tabs for Folded Panels specifically** beyond the ten Joint Types above are
  **unconfirmed** — Dowels as a distinct feature are documented under Stacked Slices, not Folded
  Panels; the Folded Panels joint system (tabs/ticks) serves the equivalent role.

### 3.6 3D Slices
"Cross sections your 3D model, similar to Stacked Slices. Rather than a stepped section for each
slice, the section conforms to the surface of the 3D model." I.e., unlike Stacked Slices (whose
edges are always flat polygon outlines stacked in flat layers), 3D Slices' cut profile follows
the model's actual curved surface on each slice, producing an interlocking "3D jigsaw puzzle"
look often used for topographic/terrain models.
- Shares the common **Slice Distribution** (Count/Distance) and **Slice Direction** controls.
- Described by one secondary community source as a "3D Jigsaw Puzzle" technique with
  interlocking tab/slot connections between slices, similar in spirit to Interlocked Slices but
  contour-following; exact tab/slot depth parameters, and whether it exposes a separate Notch
  Factor/Relief type control like Interlocked Slices, are **unconfirmed** from primary sources.

### Assembly Steps (post-slicing preview, applies to whichever technique is active)
- A **preview/play** control that animates the model being assembled slice-by-slice / panel-by-
  panel in the 3D viewport, intended to be used as physical assembly instructions.
- **Material** selector for the preview render (visual only): **Cardboard, Plywood, Plastic**
  (at least these three; exact full list **unconfirmed**).
- **Scrubber/slider** and **arrow keys** to step forward/backward through the assembly animation
  one slice/panel at a time.
- **Reference sheets** are shown alongside the 3D preview; you can click to **zoom in**, **fit to
  view**, or return to the full model view.

---

## 4. Get Plans (2D output / export)

Reached via a **Get Plans** button/icon once a construction technique is configured. Shows a
**Cut Layout** preview before exporting.

### Cut Layout preview
- **Summary stats:** total sheet count, total slice count, total part count for the current
  design.
- **Cut Sheets view:** shows how parts are laid out across each material sheet; click a sheet to
  magnify/inspect it.
- **Part labels:** hyphenated ID scheme, e.g. `Z-6-2` = axis (`Z`) – slice number (`6`) – part
  number within that slice (`2`). Labels are printed directly on/near each part in the exported
  plan so parts can be matched back to their position in the model during assembly.
- **Arrangement/nesting:** parts on a sheet are **not placed in any particular logical order** —
  "elements on a sheet are not in any order. Parts are automatically fitted to use as much of the
  sheet as possible" (i.e. an automatic bin-packing/nesting algorithm optimizes for material
  usage, not for readability or grouping). Multiple community sources describe the resulting
  nesting efficiency as mediocre ("nesting efficiency is bad but easily fixed back in CAD" —
  meaning users commonly re-import the DXF into a CAD/nesting tool to manually tighten the
  layout).
- **Color-coded outlines** distinguish line types on each part:
  - **Blue** — the model's outer silhouette edge (the part's outer cut boundary).
  - **Green** — interior/hollow cuts within a part (cut-through lines).
  - **Yellow** — scored guide lines (e.g. fold lines for Folded Panels) — cut only partially or
    not at all, meant to guide bending/folding, not full separation.
  - **Red** — indicates an assembly/geometry **error** on that part (e.g. a notch that doesn't
    close correctly); a visual warning rather than an exported line color.

### Export formats
- **PDF:** a single multi-page file, one sheet per page (or per-part pages, depending on layout);
  positioned as the easiest option for users without dedicated vector/EPS software.
- **EPS:** exports as a **.zip archive containing one separate EPS file per sheet**; separates
  text (labels) and cut profiles onto different layers within each file, for import into laser-
  cutter software or vector editors.
- **DXF:** also separates text and profiles into layers. DXF's export dialog additionally offers
  a **unit** choice (inches, feet, cm, mm) independent of the app's working units. DXF cannot be
  opened directly back inside Fusion 360's normal Open dialog; the documented workaround is to
  export locally, upload the DXF to Fusion Team, then right-click its thumbnail and choose
  **"Open as Fusion Design."**
- Export **destination**: **My Computer** (direct local save) or **Fusion Team** (cloud) — saving
  to Fusion Team creates a **new folder every export** which must be named; such folders **cannot
  be deleted from within Slicer** itself (must be deleted from the Fusion Team / A360 website).
- SVG export is claimed by one low-reliability secondary source only and is **unconfirmed** —
  not corroborated by the archived official help text (which lists only PDF/EPS/DXF).

---

## 5. Known Quirks, Limits, and Troubleshooting

Most of this section comes from the app's own in-product "common problems" guidance as preserved
in the archived help text, supplemented by community notes.

- **Unconnected / floating pieces (shown in blue in-app as an error indicator during modeling,
  distinct from the blue outline meaning in Cut Layout):** the model has parts of a slice that
  aren't physically connected to the rest of that slice. Suggested fixes: change the slicing
  angle, adjust slice count, switch to the **Stacked** technique, or manually delete the
  disconnected slice.
- **Part too small:** enlarge the model, adjust the slicing angle, drag the slice, or apply
  **Thicken**. No exact numeric "minimum part size" threshold is stated anywhere in the available
  sources — the app appears to flag this qualitatively/visually (e.g. red highlighting) rather
  than exposing a configurable minimum-size number. **Unconfirmed** whether any hard numeric
  minimum exists internally.
- **Notches split/break a part:** move the slice position or change the slicing angle.
- **Part too narrow:** apply Thicken, enlarge the model, or change the angle.
- **Parts exceed the sheet size:** reduce model size, increase sheet size in Manufacturing
  Settings, or change the slicing angle.
- **Multiple/overlapping notches on one part:** adjust angle, drag the slice, delete the affected
  slice, switch construction technique, or resize.
- **Notch intersects a hollow/interior cavity:** switch to Stacked Slices or change the angle.
- **Puzzle joint (Folded Panels) fails to fit:** reduce **Tick Radius**.
- **Gear joint teeth overlap:** reduce **Tooth Radius**.
- **Rivet/Laced holes intersect the panel boundary:** reduce **Hole Radius** or **Tick Radius**.
- **Notch depth computation** (how deep a notch/slot is cut relative to material thickness, and
  whether it always cuts to the exact midpoint of the intersecting part) is **not documented** in
  any available source — **unconfirmed**. The only confirmed geometric detail is that **Slot
  Offset** in Manufacturing Settings controls the notch's *width* tolerance (kerf compensation),
  not its depth; depth is presumably always the intersecting material's full thickness so slots
  seat flush, but no source states this explicitly.
- **Mesh/polygon count limits:** no documented hard limit was found in any available source
  (official or community). Community and forum evidence (an Autodesk Community thread titled
  "Fusion 360 slicer crashes when selecting actual size") suggests **large/high-poly meshes or
  large physical object sizes can cause slowdowns or crashes** in practice, consistent with the
  official help text's own note that larger objects generate more slices and require more
  processing — but no specific triangle-count ceiling is documented. **Unconfirmed** as a hard
  limit; treat as a soft performance degradation.
- **Unit handling:** the app's default working unit is commonly reported as **inches**, and this
  is described by one community source as not globally configurable outside of Manufacturing
  Settings/Object Size/DXF-export unit pickers (each of which has its own unit control) — i.e.
  there is no single global "always use metric" preference; you set units per-panel. Decimal
  input in numeric fields reportedly respects OS locale (e.g. a German-localized OS accepts commas
  as the decimal separator) — **unconfirmed** as officially documented, but plausible/consistent
  with standard OS-level numeric-locale behavior and reported by a community source.
  **Paste is disabled** in numeric fields in at least the localized version tested by that source;
  right-click context menu must be used instead of Ctrl+V — **unconfirmed** as universal behavior
  across all versions.
- **File naming:** files/folders saved to Fusion Team must be named using English/ASCII
  characters — non-English filenames were reported to cause the app to misbehave.
- **Add-in reinstall / cache clearing (troubleshooting a broken cloud-login state), Mac:** delete
  the cached script-info file at
  `/Users/<Account>/Library/Application Support/Autodesk/Autodesk Fusion 360/<A360AccountID>`
  (the relevant file is named similarly to `JSLoadedScriptsInfo`); the account ID is a 12- or
  15-digit numeric string.
- **Add-in reinstall, Windows:** via Fusion 360's Add-Ins panel, browse to
  `C:\ProgramData\Autodesk\ApplicationPlugins\SlicerforFusion360.bundle\Contents\SlicerforFusion360.py`
  and run/double-click it to reload the add-in/link.
- **Cloud account gating:** newer/Tinkercad-origin or 123D-origin accounts had to register to an
  A360 hub before any cloud open/save/export worked in Slicer; existing full Fusion 360 users were
  typically already registered.
- **Deprecation status:** Autodesk has stated the technology is deprecated and no longer
  maintained/supported; the last released build is distributed as a static downloadable zip from
  Autodesk's support/knowledge-base article rather than through ongoing updates.

---

## Sources

- [Full text of "Slicer For Fusion 360"](https://archive.org/stream/slicer-for-fusion-360/Slicer%20for%20Fusion%20360%20Help_djvu.txt) — archived copy of the official in-app/online Slicer for Fusion 360 Help documentation; primary source for most of §1–§4 and the troubleshooting list in §5.
- [Software: Slicer for Fusion 360 – Tampa Hackerspace wiki](https://wiki.tampahackerspace.com/Software:_Slicer_for_Fusion_360)
- [Slicer for Fusion 360 – Doing Papercraft (FH Potsdam)](https://fh-potsdam.github.io/doing-papercraft/slicer/)
- [Slicer for Autodesk Fusion 360 Tutorial: Slice your 3D model – Sculpteo](https://www.sculpteo.com/en/prepare-your-file-laser-cutting/slicer-fusion-360-tutorial-prepare-your-file-laser-cutting/slice-your-3d-model/)
- [Slicer for Fusion 360 – Complete Guide to Setup, Features, and Workflows – Autocad Everything](https://autocadeverything.com/slicer-for-fusion-360/) *(lower-reliability secondary source; used only for corroboration, some claims from it — e.g. `.3mf`/`.f3d` import, SVG export — were rejected as uncorroborated elsewhere)*
- [Using Slicer for Fusion 360 for model production – UQ Makerspace PDF](https://makerspace.uq.edu.au/files/1863/TU-031-A%20Using%20Slicer%20for%20Fusion%20360%20for%20model%20production.pdf)
- [Guide: Slicer for Fusion 360 06-08-2018 PDF – University of Auckland OML](https://oml.blogs.auckland.ac.nz/files/2018/10/Slicer_for_fusion_contours-vm350r.pdf)
- [Slicer for Fusion 360 – Product Design Online](https://productdesignonline.com/fusion-360-tutorials/slicer-for-fusion-360-laser-cutter-and-cnc-router-projects/)
- [SlicerImport (tapnair) – Fusion Slicer to Fusion 360 import utility, GitHub](https://github.com/tapnair/SlicerImport)
- [123Make will be replaced by Slicer for Fusion 360 · Issue #7 – FH-Potsdam/doing-papercraft GitHub](https://github.com/FH-Potsdam/doing-papercraft/issues/7)
- [Fusion 360 slicer crashes when selecting actual size — Autodesk Community forum thread](https://forums.autodesk.com/t5/fusion-design-validate-document/fusion-360-slicer-crashes-when-selecting-actual-size-of/td-p/8115010)
- [Solved: Slicer for Fusion 360 Manufacturing Settings — Autodesk Community forum thread](https://forums.autodesk.com/t5/fusion-support-forum/slicer-for-fusion-360-manufacturing-settings/td-p/7378910)
- [SLICER FOR FUSION 360 — CMU/OpenSculpture class notes PDF](http://islathemovie.com/CMUSIS/OpenSculptureF19/Slicer_notes.pdf) *(fetch blocked by TLS/robots restriction during research; listed for completeness, not used as a direct source of quoted content)*
