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
#   vec2 / vec3   two / three number boxes                      value: [x, y(, z)]
#   points        table of 2D points (+ alt-click in the 3D view) value: [[x, y], …]
#   lines3        table of 3D lines start→end                   value: [[[x,y,z],[x,y,z]], …]
#   map           per-slice numbers (edited from the 3D view)   value: {label: number}
#   labels        list of slice labels (chips)                  value: [label, …]
#   chips         list of numbers or labels                   value: [v, …]
LIST_TYPES = ("vec2", "vec3", "points", "lines3", "map", "labels", "chips", "list")


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


# parameters shared by every mode
COMMON: list[Param] = [
    # -- model
    P("up_axis", "choice", "z", "Which axis of the imported file points up (Y-up files from Blender/Maya: pick y)", choices=["z", "y", "x"], group="model"),
    P("rotate", "vec3", [0, 0, 0], "Rotate the whole model about x, y, z (deg) before slicing — re-align it or slice at an angle", -180, 180, 5, group="model", unit="deg"),
    P("scale", "number", 1.0, "Uniform scale factor, applied on top of `size` when one is set (size 30 in at scale 0.8 = 24 in)", 0.001, 1000, 0.01, group="model"),
    P("size", "vec3", [0, 0, 0], "Target size x, y, z (mm); 0 = keep the original; one value = uniform fit to that size. `scale` multiplies it", 0, 10000, 1, group="model", unit="mm"),
    P("shrinkwrap", "number", 0.0, "Modify form: voxel-remesh the model at this resolution (mm); rounds off small details and closes holes. 0 = off (auto-on for broken meshes)", 0, 50, 0.1, group="model", unit="mm"),
    P("hollow", "number", 0.0, "Modify form: keep only a wall of this thickness (mm) — saves material. 0 = solid", 0, 100, 0.5, group="model", unit="mm"),
    P("thicken", "number", 0.0, "Modify form: grow the model outward by this much (mm) so thin features survive cutting. 0 = off", 0, 50, 0.5, group="model", unit="mm"),
    P("round", "number", 0.0, "Modify form: remove features thinner than this (mm) and round every corner to that radius (morphological opening + closing). 0 = off", 0, 50, 0.5, group="model", unit="mm"),
    P("smooth", "int", 0, "Modify form: smoothing passes (Taubin, volume-preserving) that soften pointy vertices and noise. 0 = off, 5–20 typical", 0, 100, 1, group="model"),
    # -- sheet / material
    P("units", "choice", "mm", "Units for the DXF export and for the numbers in this form", choices=["mm", "cm", "in"], group="sheet"),
    P("thickness", "number", 1.5, "Material thickness (mm). Paper 0.3, card 1, cardboard 3, steel 1–2, plywood 3–6", 0.05, 100, 0.05, group="sheet", unit="mm"),
    P("sheet", "vec2", [600, 400], "Sheet size width, height (mm)", 10, 5000, 1, group="sheet", unit="mm"),
    P("sheet_margin", "number", 5, "Keep-out from the sheet edge (mm)", 0, 100, 0.5, group="sheet", unit="mm"),
    P("gap", "number", 3, "Gap between parts on the sheet (mm)", 0, 50, 0.5, group="sheet", unit="mm"),
    P("labels", "bool", True, "Engrave part labels beside each part, with a leader line to the part (LABEL layer)", group="sheet"),
    P("font", "number", 4.0, "Label text height (mm)", 1, 30, 0.5, group="sheet", unit="mm"),
    P("compensate", "bool", False, "Apply the kerf compensation below to the cut files. Leave it off when the machine's own software compensates for its kerf, or the parts come out compensated twice", group="fit"),
    P("kerf", "number", 0.0, "Cut compensation: beam/plasma kerf width (mm). Outer edges grow, holes and slots shrink by kerf/2", 0, 5, 0.01, group="fit", unit="mm", show_if=("compensate", True)),
    # -- fit
    P("slot_offset", "number", 0.0, "Added to every slot width (mm): + looser, − press fit (Slicer: Slot Offset)", -2, 2, 0.01, group="fit", unit="mm"),
    P("notch_ratio", "number", 0.5, "Where the two slot families meet along a crossing: 0.5 = half/half, 0.7 = first family takes 70 %", 0.05, 0.95, 0.05, group="fit"),
    P("notch_factor", "number", 0.0, "Flare the slot mouth: extra width at the opening as a fraction of the slot width (0 = none)", 0, 2, 0.05, group="fit"),
    P("notch_angle", "number", 45, "Flare angle (deg)", 10, 80, 5, group="fit", unit="deg", advanced=True),
    P("relief", "choice", "square", "Inner-corner relief for routed/plasma cuts (a round tool cannot cut a sharp inside corner)", choices=["square", "dogbone", "tbone_h", "tbone_v"], group="fit"),
    P("tool_d", "number", 0.0, "Tool diameter for the relief (mm); 0 = none", 0, 20, 0.1, group="fit", unit="mm"),
    P("margin", "number", 0, "Stacked / by-distance: keep slices this far from the model's extreme faces (mm); 0 = auto (one thickness)", 0, 50, 0.1, group="fit", unit="mm", advanced=True),
    # -- slicing frame + per-slice edits (also driven by the 3D view)
    P("center", "vec3", [0, 0, 0], "Move the slicing centre / axis (mm) away from the model's bounding-box centre", -5000, 5000, 1, group="technique", unit="mm"),
    P("skip", "labels", [], "Deleted slices (3D view: select → delete). Crossing slices get no slot for them", group="slices"),
    P("offset", "map", {}, "Move a slice along its normal (mm)", group="slices", unit="mm"),
    P("tilt", "map", {}, "Rotate a slice about its in-plane x axis (deg)", group="slices", unit="deg"),
    P("roll", "map", {}, "Rotate a slice about its in-plane y axis (deg)", group="slices", unit="deg"),
    P("thick", "map", {}, "Per-slice thickness override (mm), for mixing materials", group="slices", unit="mm"),
    P("grow", "map", {}, "Grow a slice's outline by this much (mm) — the bridge-thinner fix: thin necks get 2× this wider, the rest is a hair bigger than the model", group="slices", unit="mm"),
    P("project", "text", "", "Project name (printed on every sheet)", group="hidden"),
    P("rev", "text", "1.0", "Revision major.minor (printed on every sheet)", group="hidden"),
    # -- sheet fitting + checks
    P("split", "bool", True, "Split parts that do not fit the sheet, joining them with puzzle tabs", group="sheet"),
    P("scale_check", "bool", True, "Add a calibration bar to every export — 10 cm, or 4 in when the units are inches — to cut first and measure before committing to the whole set", group="sheet"),
    P("one_sheet", "bool", False, "Ignore the sheet height: every part goes on one sheet as wide as the sheet and as long as it needs to be, to be cut apart at the machine", group="sheet"),
    P("mirror_ok", "bool", False, "Count a part and its mirror image as the same part: it is cut once and the copies are turned over, which merges left/right pairs into one file. Only for stock that is the same both sides and either way up — no print, laminate, brushed grain or one-sided film — and the engraved label reads backwards on a turned-over part. The cut list and the Parts table name the ones to turn over", group="sheet"),
    P("tab", "number", 8, "Puzzle-tab width for splits (mm)", 2, 50, 0.5, group="sheet", unit="mm", advanced=True),
    P("autofix", "choice", "add", "add = first add crossing slices through regions nothing holds (up to 2 rounds), then remove what still cannot work; remove = only remove; off = report only. Everything done is listed in the report", choices=["add", "remove", "off"], group="checks"),
    P("min_feature", "number", 2.0, "Check: minimum wall / feature width (mm)", 0.1, 50, 0.1, group="checks", unit="mm"),
    P("min_part", "number", 6.0, "Check: parts smaller than this (mm) in both directions are flagged", 0.5, 100, 0.5, group="checks", unit="mm"),
]


class Mode:
    name: str = ""
    title: str = ""
    description: str = ""
    params: list[Param] = []
    hidden_common: tuple = ()          # common params that make no sense for this mode

    def build(self, ctx) -> list:
        raise NotImplementedError

    def crossing_fix(self, ctx, sl, point):
        """Optional: how to add a slice that would hold `point` (world) in slice `sl` → fix dict or None."""
        return None

    @classmethod
    def all_params(cls) -> list[Param]:
        return COMMON + cls.params

    @classmethod
    def schema(cls):
        return {"name": cls.name, "title": cls.title, "description": cls.description,
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
        self.span = float(np.linalg.norm(self.ext)) * 2
        self.p = params
        self.errors = []          # mode-level errors (bad parameter combinations)
        if not params.get("margin"):
            params["margin"] = params["thickness"]

    def override(self, key, label, default=0.0):
        return float(dict(self.p[key]).get(label, default))

    def keep(self, slices):
        """Drop slices the user deleted (`skip`), before slots are computed against them."""
        return [s for s in slices if s.label not in set(self.p["skip"])]

    def thickness_of(self, label):
        return self.override("thick", label, self.p["thickness"])

    def frame(self, label, origin, normal, up_hint=(0, 0, 1)):
        """Slice frame with the user's per-slice edits applied: offset along the normal, tilt/roll about the in-plane axes."""
        M = frame(origin, normal, up_hint)
        M[:3, 3] += M[:3, 2] * self.override("offset", label)
        tilt, roll = self.override("tilt", label), self.override("roll", label)
        if tilt or roll:
            M[:3, :3] = rot_about(M[:3, 1], roll) @ rot_about(M[:3, 0], tilt) @ M[:3, :3]
        return M

    def positions(self, length, thicknesses):
        """N slice centres over `length` (centred on 0): one per equal bin, like Slicer's "by count", so the end
        slices sit a half-spacing inside the model where there is still material to cross."""
        n = len(thicknesses)
        return [-length / 2 + length * (i + 0.5) / n for i in range(n)]

    def stacked_positions(self, length, thicknesses, gap=0.0):
        """Stack from the bottom: centre of each slice = cumulative thickness (+ gap between slices)."""
        z = -length / 2 + self.p["margin"]; out = []
        for t in thicknesses:
            if z + t > length / 2 - self.p["margin"] + 1e-6:
                break
            out.append(z + t / 2); z += t + gap
        return out

    def count_by_thickness(self, length, t, gap=0.0):
        """Slices that fit along `length` one thickness (+ gap) apart — never more than the count slider allows: a
        metre of paper slices is a wrong setting, and every slice is a section, checks and a part to nest."""
        n = max(1, int((length - 2 * self.p["margin"] + gap) // (t + gap)))
        if n > MAX_SLICES:
            self.errors.append(f"{n} slices at this thickness and spacing: capped at {MAX_SLICES} — use thicker material, more space, or `count`")
        return min(n, MAX_SLICES)
