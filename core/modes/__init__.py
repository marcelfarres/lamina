"""Construction-technique plug-ins.

To add a mode: create core/modes/<name>.py with a subclass of Mode, decorate it with @register.
It declares its parameters (rendered automatically by the CLI and the web UI) and returns Slice objects
with frames + cuts (or a ready-made profile for synthetic parts such as pegs, spacers, strips, ribs, panels).
Everything downstream (sections, checks, splitting, packing, export, 3D data) is shared.
"""
from __future__ import annotations
import importlib, pkgutil
from dataclasses import dataclass, field
import numpy as np
from ..geometry import frame, rot_about

REGISTRY: dict[str, Mode] = {}
MAX_SLICES = 500                      # the count slider's ceiling, and the ceiling for by-distance slicing too

# Param.type → what the UI renders
#   number | int | choice | bool | text
#   file          a file picked in the form, kept as its text (an SVG or DXF outline)   value: the file's text
#   vec2 / vec3   two / three number boxes                      value: [x, y(, z)]
#   points        table of 2D points (+ alt-click in the 3D view) value: [[x, y], …]
#   lines3        table of 3D lines start→end                   value: [[[x,y,z],[x,y,z]], …]
#   map           per-slice numbers (edited from the 3D view)   value: {label: number}
#   labels        list of slice labels (chips)                  value: [label, …]
#   chips         list of numbers or labels                   value: [v, …]
#   curve         the spacing curve, drawn in the graph under the 3D view   value: [[t, s], …] t 0..1, s mm or deg
LIST_TYPES = ("vec2", "vec3", "points", "lines3", "map", "labels", "chips", "curve")


@dataclass
class Param:
    name: str
    type: str
    default: object
    help: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list = field(default_factory=list)
    advanced: bool = False
    group: str = "technique"  # UI tab: model | technique | sheet | fit | checks | slices
    unit: str = ""            # "mm" → converted to the UI unit (cm / in); "deg"
    show_if: tuple | None = None   # (other param name, value or list of values) → field only shown when it matches
    label: str = ""           # what the form calls it; "" = the name with spaces
    section: str = ""         # a heading within its group, "Title — the line under it": shown where the section changes
    choice_labels: dict = field(default_factory=dict)   # choice value → what the list shows; the value itself is what is stored

    def coerce(self, v):
        if v is None or v == "":
            return self.default
        if self.type in ("number", "int"):
            v = float(v)
            if self.min is not None and self.max is not None:     # the slider's range holds for the API too: no million-slice request
                v = min(max(v, self.min), self.max)
            return int(v) if self.type == "int" else v
        if self.type == "bool": return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
        if self.type in LIST_TYPES:
            if isinstance(v, (list, tuple, dict)): return v
            import json; return json.loads(v)
        return v


def P(name, type, default, help="", min=None, max=None, step=None, **kw):
    return Param(name, type, default, help, min, max, step, **kw)


def spacing_params(what, curves, lo, hi, unit="mm", count="count"):
    """The parameters of a drawn spacing curve, for a technique whose slices are spread along an axis: the switch, the
    curve(s) — (name, label, default points) each, drawn in the graph under the 3D view — the range the graph shows,
    and whether the count or the curve is what is kept. `what`: what is spread (slices, ribs, planes)."""
    u = "°" if unit == "deg" else "mm"
    out = [P("spacing_vary", "bool", False, f"Vary the spacing of the {what} along the way: draw the distance between neighbours against the "
             "position in the graph under the 3D view — dense where the shape changes fast, sparse where it does not. The curve between "
             "the points never overshoots them. Off = evenly spread", label="vary the spacing")]
    for name, label, default in curves:
        out.append(P(name, "curve", default, f"The spacing of the {label}: control points (position 0…1 along the way, spacing in {u}), "
                     "drawn in the graph under the 3D view", show_if=("spacing_vary", True), label=label))
    out += [P("spacing_fix", "choice", "count", f"count = `{count}` is kept and the drawn spacings are scaled to span the model, so what is drawn "
              f"is their proportion; curve = the spacings are cut as drawn and the number of {what} follows", choices=["count", "curve"],
              show_if=("spacing_vary", True), label="keep", choice_labels={"count": f"the count ({count})", "curve": "the spacings as drawn"}),
            P("spacing_min", "number", lo, f"The least spacing the curve can draw ({u}): the graph's bottom", 0.1, 10000, 0.5, unit=unit, show_if=("spacing_vary", True), label="spacing from"),
            P("spacing_max", "number", hi, f"The most spacing the curve can draw ({u}): the graph's top", 0.2, 10000, 0.5, unit=unit, show_if=("spacing_vary", True), label="spacing to")]
    return out


# parameters shared by every mode
VOXELS = (". Remeshes the model on a grid no finer than its size allows (the note after slicing gives it): curves stay "
          "curves and the value acts exactly, but detail finer than the grid is lost. All four at 0 keeps the model "
          "exactly as drawn")
COMMON: list[Param] = [
    # -- model
    P("up_axis", "choice", "z", "Which axis of the imported file points up (Y-up files from Blender/Maya: pick y)", choices=["z", "y", "x"], group="model"),
    P("rotate", "vec3", [0, 0, 0], "Rotate the whole model about x, y, z (deg) before slicing — re-align it or slice at an angle", -180, 180, 5, group="model", unit="deg"),
    P("scale", "number", 1.0, "Uniform scale factor, applied on top of `size` when one is set (size 30 in at scale 0.8 = 24 in)", 0.001, 1000, 0.01, group="model"),
    P("size", "vec3", [0, 0, 0], "Target size x, y, z (mm); 0 = keep the original; one value = uniform fit to that size. `scale` multiplies it", 0, 10000, 1, group="model", unit="mm"),
    P("shrinkwrap", "number", 0.0, "Modify form: remesh the model at this resolution (mm); rounds off small details and closes holes. 0 = off (auto-on for broken meshes)" + VOXELS, 0, 50, 0.1, group="model", unit="mm"),
    P("hollow", "number", 0.0, "Modify form: keep only a wall of this thickness (mm) — saves material. 0 = solid" + VOXELS, 0, 100, 0.5, group="model", unit="mm"),
    P("thicken", "number", 0.0, "Modify form: grow the model outward by this much (mm) so thin features survive cutting. 0 = off" + VOXELS, 0, 50, 0.5, group="model", unit="mm"),
    P("round", "number", 0.0, "Modify form: remove features thinner than this (mm), bridge gaps narrower than it and round the corners off (morphological opening + closing with a ball of this diameter). 0 = off" + VOXELS, 0, 50, 0.5, group="model", unit="mm"),
    P("smooth", "int", 0, "Modify form: smoothing passes (Taubin, volume-preserving) that soften pointy vertices and noise. 0 = off, 5–20 typical", 0, 100, 1, group="model"),
    # -- sheet / material
    P("units", "choice", "mm", "Units for the DXF export and for the numbers in this form", choices=["mm", "cm", "in"], group="sheet"),
    P("thickness", "number", 1.5, "Material thickness (mm). Paper 0.3 mm, card 1 mm, cardboard 3 mm, steel 1–2 mm, plywood 3–6 mm", 0.05, 100, 0.05, group="sheet", unit="mm"),
    P("sheet", "vec2", [600, 400], "Sheet size width, height (mm)", 10, 5000, 1, group="sheet", unit="mm"),
    P("printed", "bool", False, "3D printed, not cut: each sheet is one build plate (the sheet size is the printer's bed), "
      "and the print set on the Export tab comes out as one 3MF per plate at full size instead of cut files. Picking PLA "
      "or PETG ticks it", group="sheet"),
    P("sheet_margin", "number", 5, "Keep-out from the sheet edge (mm)", 0, 100, 0.5, group="sheet", unit="mm"),
    P("gap", "number", 3, "Gap between parts on the sheet (mm)", 0, 50, 0.5, group="sheet", unit="mm"),
    P("grain", "bool", False, "Keep the grain: every part is laid on the sheet as it stands in its own frame, or upside down, "
      "never turned sideways, so the wood grain runs the same way through all of them. Lay the stock with its grain along "
      "the sheet's width (the first sheet size). Parts pack less tightly; one that only fits turned is split, or flagged",
      group="sheet", label="keep the grain"),
    P("labels", "bool", True, "Engrave part labels (LABEL layer): beside each part with a leader line, or on the part itself — see `labels on the parts`", group="sheet"),
    P("font", "number", 4.0, "Height of a capital letter in the engraved labels (mm). Single-stroke lettering: the laser draws each letter as one line, not the two edges of a filled one", 1, 30, 0.5, group="sheet", unit="mm"),
    P("short_name", "text", "", "The short name engraved before each label, up to 4 letters or digits (HS Y-12). Blank = the initials of the "
      "project's or the model's name, or the first four letters of a one-word name (bunny → BUNN). The assembly key says what it stands for",
      group="sheet", show_if=("label_model", True), label="short name"),
    P("label_model", "bool", True, "Engrave the model's short name before each label (BUNN Z-3): two models have the same part names, "
      "and parts cut together would otherwise get mixed up. The project name when it has one. Off for a longer label's room "
      "beside small parts", group="sheet", show_if=("labels", True)),
    P("label_style", "choice", "position", "What the engraved label says. position = where the part belongs (Z-3, R-2a, P-7) · "
      "code = a short code that gives nothing away, for a puzzle: the app, the Parts list and the 3D view still show the real "
      "labels, and assembly-key.txt in the export maps code → part. Leave that file out of the zip and the puzzle stays a puzzle",
      choices=["position", "code"], group="sheet", show_if=("labels", True)),
    P("orient_mark", "bool", False, "Engrave two small arrows at the middle of every part (LABEL layer, with the labels): a long one up the "
      "part's frame and a short one to its right, the same two directions on every part of the model, so a part turned on the sheet "
      "or laid face down is seen at once — the engraved face is the front. Labels keep clear of them", group="sheet", label="orientation arrows"),
    P("label_place", "choice", "part", "Where each label is engraved. part = on the part itself where the whole label fits on "
      "its material (inside the outline of the next layer where the technique marks one, so the layer glued on top hides it), "
      "beside it with a line pointing at it where it does not · beside = always beside the part, on the waste, so nothing is "
      "engraved on the parts · on = always on the part, on its widest spot, past its outline when it must: trim those in your "
      "laser software. However placed, no part comes out without its label", choices=["part", "beside", "on"], group="sheet",
      show_if=("labels", True), label="labels go"),
    # -- fit: three things that are easy to take for one. Only the kerf is switched by `compensate`; the slot fit and the
    # corners always apply, and the form says so in each section's line (reported: "if compensate is off, it feels like
    # none of the parameters below apply")
    P("compensate", "bool", False, "Off (the default): the files are drawn at the parts' exact size. Right when your laser or "
      "CAM software applies its own kerf offset (LightBurn's kerf offset, a CAM tool path's offset), and for a knife or a "
      "printer, which have none. On: Lamina grows every outline and shrinks every hole and slot by half the kerf below, so "
      "the parts come out true from a machine that cuts on the line. Never both, or the parts shrink twice. Only the kerf "
      "depends on this: slot offset and corner relief always apply", group="fit", label="compensate kerf",
      section="Kerf — the width the beam or bit burns away. Only the kerf is switched on and off here: slot fit and corners always apply"),
    P("kerf", "number", 0.0, "How wide the cut is (mm): what the beam, plasma or bit removes. Measure it: cut a 20 mm square, "
      "measure it, kerf = 20 − what you measured. Typical: CO2 laser 0.1–0.2, diode 0.1–0.15, fiber 0.2, plasma 1–2, a CNC "
      "router about its bit's diameter. Each edge moves by half of it", 0, 5, 0.01, group="fit", unit="mm",
      show_if=("compensate", True), label="kerf"),
    P("slot_offset", "number", 0.0, "How much wider than the material every slot, hole and socket is cut (mm): + looser, − "
      "tighter, a press fit. Sheet is rarely its nominal thickness (3 mm plywood is often 2.7–3.2), so cut the fit test "
      "first (Export tab, step 1) and set the offset of the joint that slides together snug. It is the one number that "
      "decides whether the model holds (Slicer for Fusion 360: Slot Offset)", -2, 2, 0.01, group="fit", unit="mm",
      label="slot offset (fit)", section="Slot fit — how snug the joints are. Always applied"),
    P("notch_ratio", "number", 0.5, "Where two crossing slices meet: each gets a slot to that point. 0.5 = each cut half way, "
      "the usual; 0.7 = the first family's slot goes 70 % of the way and the other's 30 %. Move it when one family's slots "
      "leave a part too thin", 0.05, 0.95, 0.05, group="fit", label="slot depth split"),
    P("notch_factor", "number", 0.0, "Open each slot's mouth into a funnel, so parts find their slot as you push them together: "
      "the extra width at the opening, as a fraction of the slot's width. 0 = straight slots, the cleanest look; 0.2–0.5 "
      "helps with stiff material and many crossings", 0, 2, 0.05, group="fit", label="slot mouth flare"),
    P("notch_angle", "number", 45, "How steep that funnel is (deg), when the mouth is flared", 10, 80, 5, group="fit", unit="deg",
      advanced=True, label="flare angle"),
    P("relief", "choice", "square", "A round bit cannot cut a sharp inside corner: it leaves a curve the size of the bit, and "
      "the part that slots in stops short of the bottom. A relief cuts a little more at each inside corner so it seats. "
      "None suits lasers, knives and printers, whose corners are sharp. Dogbone notches into the corner diagonally, the "
      "usual one; T-bone along or across puts the notch along the slot or across it, hidden from one side. Needs the "
      "tool diameter", choices=["square", "dogbone", "tbone_h", "tbone_v"], group="fit", label="inside-corner relief",
      choice_labels={"square": "none (laser, knife, printer)", "dogbone": "dogbone", "tbone_h": "T-bone along the slot",
                     "tbone_v": "T-bone across the slot"},
      section="Inside corners — for a CNC router or plasma. Always applied"),
    P("tool_d", "number", 0.0, "The bit's diameter (mm), for the relief above: each notch is this wide. 0 = no relief, "
      "whatever is picked above", 0, 20, 0.1, group="fit", unit="mm", label="bit diameter"),
    P("margin", "number", 0, "Stacked / by-distance: keep the stack this far inside the model's end faces (mm), 0 = the stack is as tall as the model · Curve: keep the rib's ends this far in, 0 = one thickness", 0, 50, 0.1, group="technique", unit="mm", advanced=True, label="end margin"),
    # -- slicing frame + per-slice edits (also driven by the 3D view)
    P("center", "vec3", [0, 0, 0], "Move the slicing centre / axis (mm) away from the model's bounding-box centre", -5000, 5000, 1, group="technique", unit="mm"),
    P("skip", "labels", [], "Deleted slices (3D view: select → delete). Crossing slices get no slot for them", group="slices"),
    P("offset", "map", {}, "Move a slice along its normal (mm)", group="slices", unit="mm"),
    P("tilt", "map", {}, "Rotate a slice about its in-plane x axis (deg)", group="slices", unit="deg"),
    P("roll", "map", {}, "Rotate a slice about its in-plane y axis (deg)", group="slices", unit="deg"),
    P("thick", "map", {}, "Per-slice thickness override (mm), for mixing materials", group="slices", unit="mm"),
    P("grow", "map", {}, "Grow a slice's outline by this much (mm) — the bridge-thinner fix: thin necks get 2× this wider, the rest is a hair bigger than the model", group="slices", unit="mm"),
    # Placed by the 3D view, never typed: the world point a tilted / rolled slice turns about — its own middle, which
    # only the drawn part knows. Absent, a slice turns about its frame origin, as it always did.
    P("pivot", "map", {}, "Where a tilted slice turns: the part's own middle, set when you drag its rings", group="hidden"),
    P("project", "text", "", "Project name (printed on every sheet)", group="hidden"),
    # The form's own stock picker fills this; the planner only carries it so the cut files say what they are cut from.
    P("material", "text", "", "What the sheet is (cardboard, plywood, steel …) — named in every cut file", group="hidden"),
    P("material_kind", "text", "", "The built-in material a material of your own was made from (its name for a built-in one): "
      "what the physical checks go by, such as whether it folds", group="hidden"),
    P("model_name", "text", "", "The model's file name as it was uploaded (set by the server), engraved before every label", group="hidden"),
    P("rev", "text", "1.0", "Revision major.minor (printed on every sheet)", group="hidden"),
    # -- sheet fitting + checks
    P("split", "bool", True, "Split parts that do not fit the sheet, joining them with puzzle tabs", group="sheet"),
    P("scale_check", "bool", True, "Add a calibration bar to every export — 10 cm, or 4 in when the units are inches — to cut first and measure before committing to the whole set", group="sheet"),
    P("one_sheet", "bool", False, "Ignore the sheet height: every part goes on one sheet as wide as the sheet and as long as it needs to be, to be cut apart at the machine", group="sheet"),
    P("mirror_ok", "bool", False, "Count a part and its mirror image as the same part: it is cut once and the copies are turned over, which merges left/right pairs into one file. Only for stock that is the same both sides and either way up — no print, laminate, brushed grain or one-sided film — and the engraved label reads backwards on a turned-over part. The cut list and the Parts table name the ones to turn over", group="sheet"),
    P("tab", "number", 8, "Puzzle-tab width for splits (mm)", 2, 50, 0.5, group="sheet", unit="mm", advanced=True),
    P("autofix", "choice", "add", "add = hold what nothing holds the way this technique holds things (crossing slices, rings, spines; up to 2 rounds); off = report only. Nothing of the model is ever taken away: what still cannot work stays, with its error and the fixes to click, deleting among them. Everything done is listed in the report", choices=["add", "off"], group="checks"),
    P("min_feature", "number", 2.0, "Check: minimum wall / feature width (mm)", 0.1, 50, 0.1, group="checks", unit="mm"),
    P("min_part", "number", 6.0, "Check: parts smaller than this (mm) in both directions are flagged", 0.5, 100, 0.5, group="checks", unit="mm"),
    P("trim_thin", "bool", False, "Cut off what is too thin for too long to survive the cutter or the hand — thinner than min_feature for twice that length, or a spike under 1.5 × min_feature for four times it: the sharp point of a slice that meets the surface at a grazing angle, the wall left between a slot and the edge. The part ends blunt there, a little short of the model; off, each such spot is a warning on its part", group="checks", label="trim thin spots"),
]


class Mode:
    name: str = ""
    title: str = ""
    description: str = ""
    legend: str = ""                   # what this mode's part labels mean — shown in the Export tab, written into
    params: list[Param] = []           # assembly-key.txt beside the cut files, and the only key in puzzle mode
    hidden_common: tuple = ()          # common params that make no sense for this mode

    def build(self, ctx) -> list:
        raise NotImplementedError

    def crossing_fix(self, ctx, sl, point):
        """Optional: how to add a slice that would hold `point` (world) in slice `sl` → fix dict or None."""
        return None

    def hold(self, slices, ctx):
        """Optional: auto-fix's parameter changes that hold every loose group at once, seeing the whole plan → list of
        sets, or None to add crossing_fix's slice through each loose region instead."""
        return None

    def guide_outlines(self, ctx, slices):
        """Optional: lines the technique engraves once the outlines are final — grown, slivers shed, slots and holes
        taken out of `profile` — such as stacked's next-layer guide. `slices` are the kept ones, in order."""
        return None

    @classmethod
    def all_params(cls) -> list[Param]:
        return COMMON + cls.params

    @classmethod
    def schema(cls):
        return {"name": cls.name, "title": cls.title, "description": cls.description, "legend": cls.legend,
                "params": [p.__dict__ for p in cls.params],
                "common": [p.__dict__ for p in COMMON if p.name not in cls.hidden_common]}


def register(cls):
    REGISTRY[cls.name] = cls()
    return cls


def load_all():
    for m in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{m.name}")
    return REGISTRY


class Ctx:
    """What a mode gets: the centred mesh, the slicing frame (world axes, centre shifted by `center`), extents,
    coerced params and small helpers. Modes use ctx.ax[i] as axes and ctx.mid + ctx.ax[i]*s as origins."""
    def __init__(self, mesh, params):
        self.mesh = mesh
        self.ax = [e for e in np.eye(3)]
        self.mid = np.asarray(params.get("center") or [0, 0, 0], float)
        self.ext = mesh.extents
        self.sized = np.asarray(mesh.metadata.get("sized_extents", self.ext), float)   # before modify form grew it
        self.span = float(np.linalg.norm(self.ext)) * 2
        self.p = params
        self.errors = []          # mode-level errors (bad parameter combinations)
        self.fixes = []           # … and their one-click fixes
        self.notes_extra = ""     # what the technique wants said in the plan's notes
        self.cover_r = None       # how far across its plane a part counts as covering the surface (plan.coverage); None = a default
        # what the technique hands the 3D view: dowel rods, a curve and its points, fan axes / branches, the planes between lobes
        self.rods, self.curve3d, self.curve_pts, self.axes3d, self.bounds3d = [], None, None, None, []
        self.core_d_min = None    # radial: the smallest core the half-slices allow
        self.spacing = []         # the drawn spacing curves' outcome, for the graph: [{param, positions, length, unit, scale}]
        self.stack, self.common_pts = [], None   # stacked: the layers in order, and the dowel points they all share (cached)
        self.covered = None       # plaque: the model in front of the plate, which is what the slices are asked to cover
        self.clip = None          # plaque: [point, normal] of the plate's front face — the 3D view shows the model in front of it only
        self.joins = {}           # plaque: lower slice's label → the overlaps where a floating piece hangs from its neighbour

    def override(self, key, label, default=0.0):
        return float(dict(self.p[key]).get(label, default))

    def keep(self, slices):
        """Drop slices the user deleted (`skip`), before slots are computed against them."""
        return [s for s in slices if s.label not in set(self.p["skip"])]

    def thickness_of(self, label):
        return self.override("thick", label, self.p["thickness"])

    def spaced(self, param, length, count, periodic=False, unit="mm"):
        """Positions from the drawn spacing curve `param` along `length` (0 at the start), or None when the spacing is
        even: `count` of them with `spacing_fix` = count, else as many as the curve gives (up to MAX_SLICES). What
        it gave goes to the plan, for the graph's ticks and the note about the scale."""
        from ..spacing import spaced
        p = self.p
        if not p.get("spacing_vary"):
            return None
        pos, k = spaced(p[param] or [], length, p["spacing_min"], max(p["spacing_max"], p["spacing_min"] + 1e-6),
                        count if p["spacing_fix"] == "count" else None, periodic, MAX_SLICES)
        self.spacing.append({"param": param, "positions": [round(float(q), 3) for q in pos], "length": float(length), "unit": unit, "scale": round(float(k), 4)})
        if p["spacing_fix"] != "count" and len(pos) >= MAX_SLICES:   # the walk hit the cap with model left over: stop, as count_by_thickness does
            self.errors.append(f"the spacing curve lays {MAX_SLICES} slices along {length:.0f} mm of model and does not reach its end — more "
                               f"than can be cut. A model this big is usually a units slip (lifesize, or saved in centimetres): set `size` to "
                               f"the real size, or raise the curve's spacing")
            return []
        if abs(k - 1) > 0.5 and p["spacing_fix"] == "count":
            self.notes_extra = " · ".join(x for x in [self.notes_extra, f"spacing curve ({param}): the count and the drawn spacings disagree — "
                                                      f"the curve is scaled {k:.2f}× to fit {len(pos)}; change the count or the curve"] if x)
        return pos

    def frame(self, label, origin, normal, up_hint=(0, 0, 1)):
        """Slice frame with the user's per-slice edits applied: offset along the normal, tilt/roll about the in-plane
        axes. A plane turns about `pivot` when the 3D view has said where the part's own middle is — without one it
        turns about its frame origin, which for a radial half-slice sits out on the fan axis and swings the part
        across the model instead of tilting it where it stands."""
        M = frame(origin, normal, up_hint)
        M[:3, 3] += M[:3, 2] * self.override("offset", label)
        tilt, roll = self.override("tilt", label), self.override("roll", label)
        if tilt or roll:
            R = rot_about(M[:3, 1], roll) @ rot_about(M[:3, 0], tilt)
            M[:3, :3] = R @ M[:3, :3]
            c = dict(self.p.get("pivot") or {}).get(label)
            if c is not None:
                c = np.asarray(c, float)
                M[:3, 3] = c + R @ (M[:3, 3] - c)
        return M

    def positions(self, length, thicknesses):
        """N slice centres over `length` (centred on 0): one per equal bin, like Slicer's "by count", so the end
        slices sit a half-spacing inside the model where there is still material to cross."""
        n = len(thicknesses)
        return [-length / 2 + length * (i + 0.5) / n for i in range(n)]

    def stacked_positions(self, length, thicknesses, gap=0.0):
        """Centre of each slice = cumulative thickness (+ gap between slices), the stack centred on the model so the
        part of a layer that does not fit is shared by both ends instead of all missing from the top."""
        room = length - 2 * self.p["margin"]; z = 0.0; out = []
        for t in thicknesses:
            if z + t > room + 1e-6:
                break
            out.append(z + t / 2); z += t + gap
        lo = -room / 2 + (room - max(0.0, z - gap)) / 2
        return [lo + c for c in out]

    def count_by_thickness(self, length, t, gap=0.0, axis=None):
        """Slices that fit along `length` one thickness (+ gap) apart — never more than the count slider allows: a
        metre of paper slices is a wrong setting, and every slice is a section, checks and a part to nest."""
        room = length - 2 * self.p["margin"]
        n = max(1, int((room + gap) // (t + gap)))
        if n > MAX_SLICES:
            # Not capped and carried on: a lifesize model (3.5 m of bear at 3 mm) was cut into the 500 and split over
            # hundreds of sheets, a quarter of an hour before the error could be read (034). Stopped here instead,
            # before a single section is taken, with the scale that holds the cap: a scale, not a size, so it is the
            # same whichever way the model is turned, and measured on the length before thicken / round grew it,
            # which they add again after the scale.
            grown = float(self.ext[axis] - self.sized[axis]) if axis is not None else 0.0
            want = MAX_SLICES * (t + gap) - gap - 0.01 + 2 * self.p["margin"]        # the length that holds MAX_SLICES layers
            f = (want - grown) / (length - grown)
            e = (f"{n} slices of {t:g} mm along {room:.0f} mm of model — more than the {MAX_SLICES} that can be cut. A model "
                 f"this big is usually a units slip (lifesize, or saved in centimetres): set `size` to the real size, "
                 f"or use thicker material, more space, or `count`")
            self.errors.append(e)
            self.fixes.append({"error": e, "options": [{"title": f"scale the model to {f:.0%} ({want:.0f} mm along the stack: {MAX_SLICES} layers)",
                                                        "set": {"scale": round(self.p["scale"] * f, 4)}}]})
            return 0
        return n
