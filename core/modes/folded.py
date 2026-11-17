"""Folded Panels: unfold the (simplified) surface into flat panels with fold lines; join the seams with tabs,
holes (rivet / laced), connecting strips, or slotted angle ribs. Paper, card, cardboard, sheet metal.

Joint sizes adapt to the triangle they sit in (a hole or slot never crosses a fold or the outline); what had to
shrink is reported per panel. Tabs are shown in the 3D view folded onto the panel they glue to."""
from __future__ import annotations
import math
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, LineString
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.strtree import STRtree
from dataclasses import dataclass, field
from typing import NamedTuple
from . import Mode, Param, register
from ..model import Issue, Slice
from ..geometry import as_multi, circle, min_dims, rect_along, frame_xy, poly_coords
from ..labels import mark_box, mark_rot
from ..mesh import simplify, merge_small
from ..unfold import unfold, closing_shortfall

JOINTS = ["seam", "tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle", "snap", "click", "rivet", "laced", "loops", "strip", "rib"]
# The thickest sheet of each material that folds along a score line (mm); 0 = it does not fold at all, it cracks or
# splits along the line (wood, MDF, acrylic, foam board, printed plastic). Sheet metal bends on a brake.
# ponytail: rules of thumb, not measurements, and a material not listed is not checked; add it here when it matters.
FOLDS = {"paper": 1, "card": 1.5, "cardboard": 7, "greyboard": 2, "polypropylene": 2, "fabric": 10, "leather": 6,
         "EVA foam": 10, "steel": 3, "stainless steel": 3, "aluminium": 3, "brass": 3, "copper": 3,
         "plywood": 0, "mdf": 0, "acrylic": 0, "basswood": 0, "balsa": 0, "foam board": 0, "PLA": 0, "PETG": 0}
# How far one panel's edge can press into the next at a seam, as a share of the sheet's thickness: paper, card and
# foam crush or give, metal, wood and hard plastic do not. A material not listed is not checked.
# ponytail: rules of thumb like FOLDS, to be corrected by what gets built.
SQUISH = {"paper": 1, "card": 1, "fabric": 1, "cardboard": 1, "EVA foam": 0.7, "leather": 0.5, "greyboard": 0.3, "foam board": 0.3,
          "polypropylene": 0.1, "balsa": 0.1, "steel": 0, "stainless steel": 0, "aluminium": 0, "brass": 0, "copper": 0,
          "plywood": 0, "mdf": 0, "acrylic": 0, "basswood": 0, "PLA": 0, "PETG": 0}
BACK_ON_ITSELF = 0.1                  # 1 + cos(angle between two faces' normals) under this: they fold back on each other
SCORE = ("solid", "dashed")           # a mountain and a valley line that is scored, never perforated (a tab's base)


def notch_width(bend, depth, land=0.0, stop=0.0):
    """What a fold by `bend` (rad, a number or an array) takes off the closing face on each side of its line, in a
    sheet `depth` deep above its skin: depth·tan(bend / 2), the half opening of the V whose walls meet at that bend
    (they turn about the skin, each by atan(half the opening / the depth)). `stop` moves the bend it closes at;
    `land`, a printed groove's flat bottom, lies inside the opening and is its least width. None under FLAT."""
    bend = np.asarray(bend, float)
    return np.where(bend > FLAT, np.maximum(land / 2, depth * np.tan(np.clip(bend + stop, 0, math.pi * 0.999) / 2)), 0.0)


def closes_at(wide, depth):
    """The bend (rad) at which the walls of a groove `wide` to each side and `depth` deep meet."""
    return 2 * math.atan(wide / depth)


THIN_TABS = ("tab", "multitab", "diamond", "ticked", "gear")   # glue tabs a printed panel carries as thin flaps of its skin
FOLDED_JOINTS = ("tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle", "strip")   # a flap or bridge that bends
# The snap joint (printed panels): a wall on the inside face of each panel along the seam, and a clip over the two.
SNAP_WALL = 1.2                       # mm: a wall's thickness (three 0.4 mm lines)
SNAP_LEDGE, SNAP_GROOVE = 2.7, 0.4    # the groove in a wall's back the clip hooks into: how high its ledge is, how deep it is
SNAP_LEG, SNAP_BITE = 1.0, 0.3        # a clip's leg: its thickness, and how far its hook reaches into the groove
SNAP_CLIP, SNAP_LONG = 5.0, 8.0       # a clip's width along the seam, and the length of wall it sits on
SNAP_LEAN = math.radians(50)          # a wall leans by half the seam's bend: past this it does not print without support
# The click joint (printed panels): a tooth on one panel's wall and a bar on the other's, bridged between two posts.
# Printed flat, a part that stands on a panel is weak where it is pulled or bent across its layers, so: the one part
# that bends is the bar, a bridge, which bends along its lines; everything else is a block on a wide foot.
CLICK_DEEP = 2.0                      # the bar across the seam (five 0.4 mm lines): what holds when the seam is pulled
CLICK_THICK = (1.6, 1.4, 1.2, 1.0, 0.8)   # the bar the way it bends, up the wall: the thickest its span allows (see CLICK_STRAIN)
CLICK_SPAN, CLICK_POST = (14.0, 20.0), 3.0   # the bar's free length between its posts, least and most; a post's length along the seam
CLICK_STRAIN = 0.03                   # the most the bar is stretched letting the tooth past: PETG yields at about 0.05
CLICK_NOSE, CLICK_BITE = 8.0, 0.4     # the tooth's width along the seam, and how far its ridge stands up behind the bar
CLICK_WALL, CLICK_NECK = 2.4, 1.6     # the thickness of the wall the tooth stands on, and of the tooth where it goes under the bar
CLICK_FOOT = 4.0                      # the ramp behind every upright: how far it runs into the panel at most
CLICK_LONG = CLICK_SPAN[0] + 2 * CLICK_POST   # the least length of seam one click takes

FLAT = math.radians(1)                # two faces closer to one plane than this are one flat piece: no score between them
MAX_HOLES = 60                       # holes along one seam (rivet / laced / strip)
MAX_FACES = 4000                      # triangles this can unfold and lay out in a usable time
MAX_PANELS = 400                      # …and parts, when `separate` makes every triangle one (see build)
JOINT_HELP = ("seam = plain edge (glue / sew) · tab = one glue tab · multitab = several small tabs · diamond = triangular ticks · "
              "ticked = dense small ticks along the seam · "
              "gear = rectangular teeth · tongue = tab into a slot on the other panel · puzzle = round-head tab into a matching hole · "
              "snap = printed panels only: a short wall on the inside of each panel at the seam and a printed clip pushed over the two, nothing to see from outside, no glue · "
              "click = printed panels only: a tooth on the inside of one panel and a small bridge on the inside of the other; press the seam shut and it clicks, no loose parts, no glue · "
              "rivet = one hole per spacing on both panels · laced = ≥2 holes per edge on both panels (lace / zip-tie) · "
              "loops = alternating eyelet loops on both edges that interleave like hinge knuckles; one lace through all (cloth, leather, masks) · "
              "strip = holes + a separate rounded strip with matching holes bridging the two panels · "
              "rib = slots + a separate angle rib cut at the fold angle, slotted in from the back (sheet metal)")


def target_faces(mesh, facet):
    """Triangle count for an average edge length `facet` (mm): area / area of an equilateral triangle of that edge."""
    if not facet:
        return 0
    return max(12, int(mesh.area / (0.433 * facet * facet)))


def edge_geom(tri, ia, ib):
    """Edge A→B of a 2D triangle and the unit normal pointing into the triangle."""
    A, B = tri[ia], tri[ib]; C = tri[3 - ia - ib]
    d = B - A; d = d / np.linalg.norm(d)
    n = np.array([-d[1], d[0]])
    if np.dot(C - A, n) < 0:
        n = -n
    return A, B, d, n


class Groove(NamedTuple):
    """A V groove a printed folded panel gets along a fold or a seam edge, in the panel's flat net (mm)."""
    a: tuple        # the line's two ends
    b: tuple
    land: float     # width of the flat bottom
    skin: float     # what is left under the bottom: the hinge
    wide: float     # half the opening at the face it is cut from
    top: bool       # cut from the face up on the bed (else from the bed side)

    def json(self):
        return {"a": [round(float(x), 4) for x in self.a], "b": [round(float(x), 4) for x in self.b],
                "land": round(float(self.land), 4), "skin": round(float(self.skin), 4), "wide": round(float(self.wide), 4), "top": bool(self.top)}


class Click(NamedTuple):
    """The cross-sections of one click joint, each [(u, z)] as a Rail takes it (see Folded.click_parts)."""
    wall: list            # the wall the tooth stands on, on its ramp
    teeth: list           # the tooth along the seam, [(0, to, cross-section)] each way from its middle: its ridge is crowned
    post: list            # a post of the bar, on its ramp
    bar: list             # the bar
    guide: list           # the block under the bar each side of the tooth
    reach: float          # how far a foot goes into its panel
    thick: float          # the bar's thickness, the way it bends
    strain: float         # how far the bar is stretched letting the tooth past


class Rail(NamedTuple):
    """A wall standing on a printed panel along a line of its flat net: `profile` is its cross-section, [(u, z)] with
    u from the line into the panel along `into` and z up from the bed, the same from a to b."""
    a: tuple
    b: tuple
    into: tuple
    profile: list

    def foot(self):
        """The room the wall takes in the net, seen from above: where it stands and what it hangs over."""
        a, b, n = (np.asarray(v, float) for v in (self.a, self.b, self.into)); us = [u for u, _ in self.profile]
        return Polygon([a + n * min(us), b + n * min(us), b + n * max(us), a + n * max(us)])

    def json(self):
        r = lambda v: [round(float(x), 4) for x in v]         # noqa: E731
        return {"a": r(self.a), "b": r(self.b), "into": r(self.into), "profile": [r(q) for q in self.profile]}


@dataclass
class FoldedSlice(Slice):
    """A folded panel: the shared Slice plus what unfolding and joining it keeps while it is built."""
    pn: object = None                   # the Panel this slice is cut from
    rails: list = field(default_factory=list)       # printed: a Rail per wall standing on the panel (the snap joint)
    additions: list = field(default_factory=list)   # tabs added to the panel's outline
    skipped: dict = field(default_factory=dict)     # what → seams whose joint found no room
    room: MultiPolygon | None = None    # the panel with its tabs so far, a hair in, where a seam number may go (cached)
    room_tabs: int = -1                 # … and how many tabs it had when that was last worked out
    mark_boxes: list = field(default_factory=list)  # the room each of `marks` takes, boxed once (cached)
    reduced: int = 0                    # joints made smaller than asked
    grooves: list = field(default_factory=list)     # printed: a Groove per fold and per mitred seam edge
    hinges: list | None = None                      # per facet, [parent facet, point xyz, axis xyz, unfold angle] or None: how the 3D view folds it
    bevels: list | None = None                      # printed: per facet, [[x0, y0, x1, y1, width, closing face (1 inside, -1 outside)]] its grooved edges
    pressed: list = field(default_factory=list)     # how far (mm) each seam edge of this panel still presses into its neighbour
    taken: object = None                            # the panel and the tabs it has so far (cached), what a new tab may not touch
    taken_tabs: int = -1
    thin: list = field(default_factory=list)        # printed: the glue tabs, printed only as thick as the hinge skin
    thin_t: float = 0.0                             # … and that thickness
    tab_t: list = field(default_factory=list)       # the thickness of each of `tab_facets` when it is not the sheet's (a thin printed tab)
    facet_t: list | None = None                     # per facet, that thickness or None
    tab_of: list = field(default_factory=list)      # the face each of `tab_facets` lies on
    tab_facets: list = field(default_factory=list)  # the tabs as the 3D view shows them, folded onto their panel

    def piece_extra(self):
        """What a printed folded panel carries beyond its outline, for core.solid to cut: a groove per fold and mitred seam
        edge, and its glue tabs with the thickness they keep. (A folded net is one piece.)"""
        return {**({"grooves": [g.json() for g in self.grooves]} if self.grooves else {}), **({"rails": [r.json() for r in self.rails]} if self.rails else {}),
                **({"thin": [r for g in self.thin for r in poly_coords(as_multi(g))], "thin_t": self.thin_t} if self.thin else {})}

    def facet_extra(self, i):
        """hinge: how a folded panel's face unfolds, bevel: its grooved edges, t: its thickness when it is not the sheet's."""
        h, b, ft = (xs[i] if xs else None for xs in (self.hinges, self.bevels, self.facet_t))
        return {**({"hinge": h} if h else {}), **({"bevel": b} if b else {}), **({"t": ft} if ft else {})}

    def mirror(self):
        """The slice seen from its other face: everything it holds in flat-net coordinates turned over (x → −x), and
        what was worked out from them forgotten. Folded panels cut with their inside face up are built seen from
        outside and mirrored once, here. (Their strips and ribs are parts of their own and lie either way up.)"""
        flip = lambda g: affinity.scale(g, -1, 1, origin=(0, 0))   # noqa: E731
        self.raw = flip(self.raw); self.cuts = [flip(c) for c in self.cuts]; self.thin = [flip(g) for g in self.thin]
        self.lines = [(style, flip(ln)) for style, ln in self.lines]
        self.marks = [(-m[0], m[1], m[2], -(m[3] if len(m) > 3 else 0.0)) for m in self.marks]
        self.grooves = [g._replace(a=(-g.a[0], g.a[1]), b=(-g.b[0], g.b[1])) for g in self.grooves]
        self.rails = [r._replace(a=(-r.a[0], r.a[1]), b=(-r.b[0], r.b[1]), into=(-r.into[0], r.into[1])) for r in self.rails]
        self.mark_boxes = []; self.room = None; self.taken = None

@dataclass(eq=False)
class Side:
    """One face's side of a seam: the edge A→B of face f in panel-layout coords, and the same edge in the face's own frame
    (for the 3D parts). `back` is set later, when the seam edge is cut back."""
    sl: FoldedSlice       # the panel the face is in
    f: int                # the face
    A: np.ndarray         # edge start, layout
    B: np.ndarray         # edge end, layout
    d: np.ndarray         # unit direction A→B, layout
    n: np.ndarray         # unit normal pointing into the triangle, layout
    L: float              # edge length
    tri: Polygon          # the face's triangle, layout
    h: float              # height of the triangle over this edge
    lmid: np.ndarray      # edge midpoint in the face's own frame
    ld: np.ndarray        # unit direction in the face's own frame
    ln: np.ndarray        # unit inward normal in the face's own frame
    back: float = 0.0     # how far the seam edge was cut back: holes, slots and numbers are measured from the new edge


@register
class Folded(Mode):
    name = "folded"
    surface = True
    title = "Folded Panels"
    description = ("Unfolds the surface into flat panels with fold (score) lines, joined at the seams by tabs, holes, "
                   "strips or ribs. Works on any closed shape (heads, animals): cavities and undercuts just become more seams.")
    legend = ("P-7 = the 7th panel · every seam has a number, engraved on the tab (or beside the edge) on one panel and beside "
              "the matching edge on the other: find the same number on two parts and those two edges go together, the number "
              "reading along its edge · a cut edge with no number is an outside edge or one whose number had no room (the other "
              "side of the seam still carries it) · S-n = the connecting strip for seam n, R-n = the angle rib for seam n · on "
              "the score layer a solid line is a mountain fold, a dashed line a valley fold, seen from the face that is up on "
              "the cutter (the inside of the model unless `score side` says outside); the short score across a tab's base is "
              "where the tab folds, the rest of the outline is cut")
    params = [
        Param("facet", "number", 15, "Detail: average triangle edge after simplification (mm). Bigger = fewer, simpler panels; joints need triangles a few times bigger than the joint. 0 = keep every triangle of the model", 0, 200, 1, unit="mm"),
        Param("min_face", "number", 0.0, "Merge the faces too small to work with into their neighbours: a face whose least height is "
              "under this (mm) is closed up along its shortest edge, and the rest of the model stays as it is. 0 = keep every "
              "face. For a model where a few small faces carry warnings and a bigger facet size would lose detail everywhere", 0, 100, 0.5, unit="mm", label="smallest face"),
        Param("separate", "bool", False, "Every face is its own panel (no folds): each triangle is cut alone and joined to its neighbours along every edge"),
        Param("strategy", "choice", "auto", "How panels grow: flat = flattest fold first; strip = long strips along the model's axis; area = big faces first; auto = try all and keep the fewest, most compact panels (≤ 800 faces)", choices=["auto", "flat", "strip", "area"], show_if=("separate", False)),
        Param("max_faces", "int", 0, "Max triangles per panel (0 = as many as fit the sheet without overlapping)", 0, 5000, 1, show_if=("separate", False)),
        Param("joint", "choice", "laced", JOINT_HELP, choices=JOINTS),
        Param("hole_d", "number", 2.5, "Hole diameter for rivet / laced / strip (mm); shrinks where the triangle is small", 0.5, 30, 0.1, unit="mm"),
        Param("inset", "number", 4.0, "Distance from the seam to the hole centres / slots / second bend (mm); shrinks where the triangle is small", 0.5, 100, 0.5, unit="mm"),
        Param("spacing", "number", 20.0, "Hole spacing along a seam (mm); laced makes ≥ 2 per edge, rivet ≥ 1", 2, 500, 1, unit="mm"),
        Param("tab_h", "number", 10.0, "Tab height for tab / multitab / diamond / gear / tongue / puzzle (mm)", 1, 100, 0.5, unit="mm"),
        Param("tab_angle", "number", 30, "Side angle of trapezoid tabs (deg)", 0, 80, 5, unit="deg"),
        Param("snap_h", "number", 7.5, "Snap and click joints: how high the walls stand on the inside of the panels (mm). Snap: higher walls give "
              "the clip longer legs, which go on more easily. Click: the most a wall may stand; a seam whose tooth needs more is left plain", 6, 20, 0.5,
              unit="mm", show_if=("joint", ["snap", "click"]), label="snap wall"),
        Param("snap_fit", "number", 0.1, "Snap joint: the room between a clip and the two walls it holds, on each side (mm). Click joint: the "
              "room between the tooth and the bar. Does not go on: more. Loose: less, down to 0. Print one seam first and set it for your "
              "printer and filament", 0, 1, 0.05, unit="mm", show_if=("joint", ["snap", "click"]), label="snap fit"),
        Param("rib_w", "number", 12.0, "Rib joint: arm width above the panel and tab width through the slot (mm); shrinks where the triangle is small", 2, 100, 0.5, unit="mm"),
        Param("rib_thick", "number", 0.0, "Rib material thickness (mm) when the ribs are cut from a different sheet; 0 = same as the panels. Slots in the panels follow it", 0, 20, 0.1, unit="mm", show_if=("joint", "rib")),
        Param("perforate", "bool", False, "Fold lines as dashed perforation instead of a continuous score (thick material)"),
        Param("score_side", "choice", "inside", "The face of the sheet that is up on the cutter, and so carries the scores and "
              "seam numbers: inside = the net is mirrored, they end up inside the model and the outside stays one clean "
              "surface; outside = they show on the outside, as on a printed paper model", choices=["inside", "outside"]),
        Param("hinge", "number", 0.4, "3D printed panels (PLA, PETG): the skin left at every fold (mm). The panel prints at its "
              "full thickness with a V groove along each fold, cut to that fold's own angle: it folds to the model's shape and "
              "stops there, and with the plain `seam` joint the seam edges are mitred the same way, so the panels meet face to "
              "face for glue. Two layers (0.4 mm) is a good start; PETG bends, PLA is brittle and folds once. 0 = no groove", 0, 5, 0.05, unit="mm", show_if=("printed", True)),
        Param("hinge_w", "number", 0.4, "3D printed panels: width of the flat strip of skin at the bottom of each fold's groove (mm), "
              "the length that bends. Wider folds more easily and stops less sharply", 0, 5, 0.05, unit="mm", label="hinge width", show_if=("printed", True)),
        Param("hinge_stop", "number", 0.0, "3D printed panels: where each fold stops, in degrees past (+) or short of (−) the "
              "model's angle. 0 = the groove walls meet at the model's angle. Folds that go too far on your printer: set it "
              "below 0 for a tighter groove; folds that stop short: above 0", -20, 20, 0.5, unit="deg", label="fold stop", show_if=("printed", True)),
        Param("edge_fit", "choice", "inner", "Where two panels meet at a seam. inner = at their inside edges: every outward seam "
              "edge is cut back by thickness × tan(bend / 2), so stiff sheet (metal, wood, acrylic) closes instead of its "
              "inside corners colliding, and an open V is left on the outside; through = one panel runs to the model's edge "
              "and only the other is cut back, to butt against its inside face: the outside closes (fully at 90°) and one "
              "sheet shows its edge (seam, rivet and laced joints; the others use inner); outer = both edges reach the "
              "model's edge (edges you bevel yourself). Joints with a tab or loop on the edge, and printed panels (mitred "
              "instead), are not cut back", choices=["inner", "through", "outer"]),
        Param("window", "number", 0.0, "Open every face with a window of its own shape, for light (lamp shades, lanterns): how "
              "much of the face it takes, 0 = none, 1 = as much as the frame allows. The frame left round it is never "
              "narrower than the minimum feature width plus the room its folds need; a face too small for that stays whole", 0, 1, 0.05),
        Param("edge_labels", "bool", True, "Engrave the seam number beside every joint on both panels, so mating edges can be found"),
    ]
    hidden_common = ("notch_ratio", "notch_factor", "notch_angle", "relief", "tool_d", "margin", "tab", "offset", "tilt", "roll", "thick", "center", "skip")

    def build(self, ctx):
        p = ctx.p; t = p["thickness"]; self.p = p; self.t = t; self.inside = p["score_side"] == "inside"
        self.hinged = bool(p["printed"]) and 0 < p["hinge"] < t        # printed with a living hinge at every fold
        if p["printed"] and p["hinge"] >= t:
            ctx.errors.append(f"hinge {p['hinge']:g} mm is not thinner than the {t:g} mm sheet: there is nothing to cut a groove "
                              f"in, so no fold is grooved. Set `hinge` below the sheet thickness")
        # the groove's skin, flat bottom and stop; all 0 for a sheet that is not grooved, where notch() is the plain t·tan(bend / 2)
        self.skin, self.land, self.stop = (p["hinge"], p["hinge_w"], math.radians(p["hinge_stop"])) if self.hinged else (0.0, 0.0, 0.0)
        self.styles = ("dashed", "dotted") if p["perforate"] else SCORE     # a mountain and a valley fold line
        # … and its glue tabs as flaps of the skin alone: a tab as thick as the sheet would fold into the panel it glues to
        self.thin_tabs = self.hinged and p["joint"] in THIN_TABS
        self.mitres = self.hinged and (p["joint"] in ("seam", "snap", "click") or self.thin_tabs)     # seam edges cut to half the bend, face to face
        if p["joint"] in ("snap", "click") and not (self.hinged and self.inside):
            ctx.errors.append(f"the {p['joint']} joint is for printed panels: it needs a printed material, a `hinge` above 0 and `score side` inside "
                              "(its walls stand on the face that is up on the bed). The seams are left plain")
        # Bound the face count itself, not the facet size. `facet` 0 means "keep every triangle", which made
        # target_faces return 0 and skipped this guard entirely — the one route into unfold() with no limit, so a
        # scanned mesh of 200 000 faces never came back and the server looked hung. Whichever way the count was
        # asked for, it is capped here and the preview degrades instead of stalling.
        # `separate` cuts every triangle as its own panel, so there the ceiling is a number of parts to cut and glue,
        # not a number of triangles to unfold: 4000 of them is not a job anyone would take on, and checking and
        # nesting them takes longer than anyone will wait.
        cap = MAX_PANELS if p["separate"] else MAX_FACES
        target = target_faces(ctx.mesh, p["facet"])
        want = target or len(ctx.mesh.faces)
        if want > cap:
            need = math.sqrt(ctx.mesh.area / (0.433 * cap))
            asked = f"facet {p['facet']:g} mm needs" if p["facet"] else "facet 0 keeps every triangle of this model —"
            limit = f"the {cap} separate faces this will cut" if p["separate"] else f"the {cap} this can unfold"
            ctx.errors.append(f"{asked} {want} triangles, more than {limit}: set the facet size to {need:.0f} mm or "
                              f"more{'' if p['separate'] else ', or use `separate` faces'}. Simplified to {cap} "
                              f"triangles so you can still see the result.")
            target = cap
        mesh = simplify(ctx.mesh, target)
        if p["min_face"]:
            mesh = merge_small(mesh, p["min_face"])
        self.mesh = mesh
        ctx.cover_r = t                                       # coverage: surface points within the sheet thickness of a panel
        frames, local, panels, seams = unfold(mesh, p["separate"], p["max_faces"], self.usable_sheet(p), p["strategy"])
        self.frames, self.local = frames, local
        convex = mesh.face_adjacency_convex
        slices, owner = [], {}
        self.face_cuts = {}                                   # face → cuts inside it (collision checks)
        self.grooved = {}                                     # face → its grooved edges in the face's own frame, for the 3D view
        for i, pn in enumerate(panels):
            sl = FoldedSlice(f"P-{i + 1}", "F", frames[pn.faces[0]], t)
            sl.pn = pn
            sl.raw = as_multi(pn.union.buffer(0))
            for k in self.creases(pn):
                fa = list(mesh.faces[mesh.face_adjacency[k][0]])
                va, vb = mesh.face_adjacency_edges[k]
                f = mesh.face_adjacency[k][0]
                sl.lines.append((self.fold_line(convex[k]), LineString([pn.tri[f][fa.index(va)], pn.tri[f][fa.index(vb)]])))
                self.groove(sl, pn.tri[f][fa.index(va)], pn.tri[f][fa.index(vb)], k)
            slices.append(sl)
            for f in pn.faces:
                owner[f] = sl
        # A stiff sheet has thickness at a seam: two panels that both reach the model's edge collide at their inside
        # corners on every outward seam, and nothing gives. Each is cut back so the inside edges meet instead.
        back = (p["edge_fit"] != "outer" and not self.hinged and p["joint"] not in FOLDED_JOINTS and p["joint"] != "loops")
        through = back and p["edge_fit"] == "through" and p["joint"] in ("seam", "rivet", "laced")
        self.back = np.zeros(len(mesh.faces)); self.face_trims = {}; all_sides = {}
        give = SQUISH.get(p.get("material_kind") or p.get("material"))
        mitred = self.mitres                                  # a printed seam edge is cut to half the bend: nothing left to collide
        for k in seams:
            fa, fb = (int(x) for x in mesh.face_adjacency[k])
            va, vb = mesh.face_adjacency_edges[k]
            all_sides[k] = [self.side(owner[f], f, va, vb) for f in (fa, fb)]
            bend = float(mesh.face_adjacency_angles[k])
            outward = convex[k] and bend > math.radians(1)
            need = t * math.tan(min(bend, math.radians(150)) / 2) if outward else 0
            if through and outward:
                # one face is cut back until it clears the other's inside face: t·sin(bend) up to a right angle (its
                # inside corner lands on that face), t·tan(bend / 2) past it; the other runs to the model's edge
                need = t * math.sin(bend) if bend <= math.pi / 2 else need
            # Only what the sheet cannot take up itself is cut. Paper, card and cardboard crush at a seam (SQUISH): cut
            # back like steel, a small panel in 1 mm card fell under the minimum part size, and a laced job that was
            # clean in 0.3.2 came back with errors. A material that crushes through its whole thickness is never cut
            # back, at any angle; nor is one that is not listed, which gives as it always did.
            over = 0.0 if give is None or give >= 1 else max(0.0, need - give * t)
            cut = dict.fromkeys((0, 1), min(over, *(0.4 * s.h for s in all_sides[k])) if back else 0)   # never most of a face: a sliver of a triangle keeps its middle
            if through and outward:                           # the face with more room is the one cut
                i = int(all_sides[k][1].h > all_sides[k][0].h)
                cut = {i: min(over, 0.4 * all_sides[k][i].h), 1 - i: 0}
            left = over - max(cut.values())
            if not mitred and left > 0.05:                    # what is left presses into the other panel
                for s in all_sides[k]:
                    s.sl.pressed.append(left)
            for i, s in enumerate(all_sides[k]):
                d = cut[i]
                if d:
                    far = s.d * (d * 4)                    # past both ends: the corner goes with the edge
                    whole = Polygon([s.A - far - s.n * 1e-3, s.B + far - s.n * 1e-3, s.B + far + s.n * d, s.A - far + s.n * d])
                    strip = whole.intersection(s.tri)
                    # a flat face of several triangles: the ones that touch this edge only at its ends lose their tip too
                    for g in {int(g) for v in (va, vb) for g in mesh.vertex_faces[v] if g >= 0} - {fa, fb}:
                        if mesh.face_normals[g] @ mesh.face_normals[s.f] > 0.9999:
                            tip = self.across(whole, owner[s.f].pn, s.f, owner[g].pn, g).intersection(Polygon(owner[g].pn.tri[g]))
                            if tip.area > 1e-6:
                                self.face_trims.setdefault(g, []).append(tip); self.back[g] = max(self.back[g], d)
                    self.face_trims.setdefault(s.f, []).append(strip); self.back[s.f] = max(self.back[s.f], d)
                    s.back = d                            # holes, slots and numbers are measured from the new edge
        self.corners(owner)

        def small(geom):                                      # as core.checks reads a part: any region too small or too thin
            return geom.is_empty or any(max(d) < p["min_part"] or min(d) < p["min_feature"] for d in map(min_dims, geom.geoms))
        for sl in slices:
            trims = [g for f in sl.pn.faces for g in self.face_trims.get(f, ())]
            if trims:
                was = sl.raw
                # opened by a hair: the tip of a sharp triangle between two cut-back edges is left as a thread of no width
                sl.raw = as_multi(sl.raw.difference(unary_union(trims)).buffer(-0.01, join_style="mitre").buffer(0.01, join_style="mitre"))
                # … and a corner cut against a neighbour can leave a crumb beside the panel: no part, it goes
                whole = [g for g in sl.raw.geoms if g.area >= 0.25 * p["min_feature"] ** 2]
                if whole and len(whole) < len(sl.raw.geoms):
                    sl.raw = as_multi(unary_union(whole))
                # The cut-back is never what makes a panel too small to cut: a panel it would take under the minimum
                # part or feature size keeps its edges, and says how far it then presses into its neighbours.
                if small(sl.raw) and not small(was):
                    sl.raw = was; sl.pressed.append(max(self.back[f] for f in sl.pn.faces))
                    for f in sl.pn.faces:
                        self.face_trims.pop(f, None); self.back[f] = 0
                    for k in seams:
                        for side in all_sides[k]:
                            if side.sl is sl:
                                side.back = 0.0
        self.windows(slices)
        extra = []
        for j, k in enumerate(seams, 1):
            sides = all_sides[k]
            phi = self.interior_angle(k)
            extra += self.joint(j, k, sides, phi, convex[k])
        # additions (tabs) → raw; facets for the 3D view: the profile of every face in its own frame (+ folded tabs)
        for sl in slices:
            for what, js in sl.skipped.items():
                ids = ", ".join(map(str, sorted(set(js))[:12])) + (" …" if len(set(js)) > 12 else "")
                if what == "seam number":
                    sl.warnings.append(f"{len(set(js))} seam number(s) left off — no room beside the edge for a legible one (seams {ids}): "
                                       f"the other side of each seam still carries it; a smaller font or a bigger facet size gives them room")
                    continue
                sl.warnings.append(Issue(f"{len(set(js))} seam(s) without a {what} — no room inside the triangle even after shrinking the joint (seams {ids}): "
                                         f"use fewer triangles (`simplify`), a bigger model, or smaller hole_d / inset / rib_w", "no-joint"))
            if sl.pressed:
                kind = p.get("material_kind") or p.get("material")
                sl.warnings.append(Issue(f"{len(sl.pressed)} seam edge(s) press up to {max(sl.pressed):.1f} mm into the next panel, beyond the "
                                         f"{give * t:.1f} mm that {t:g} mm {kind} gives: the panels will not close there. "
                                         + ("Use a joint with no tab on the edge (seam, rivet, laced, strip, rib) with `edge fit` inner, so the edge is cut back"
                                            if not back else "The faces there are too small to cut back that far: use a thinner sheet or a bigger facet size"),
                                         "press", cut_back=bool(back)))     # the facet-size fix is for faces too small to cut back
            if sl.reduced:
                sl.warnings.append(f"{sl.reduced} joint(s) made smaller than asked to fit their triangle — fine for paper, check strength for metal")
            if sl.additions:
                # a tab's base lies on the panel's edge only to rounding: a hair outside and it stays a piece of its own
                # (the ticked joint's ticks came off on Linux, not on Windows). Closing by 1 µm joins them, no edge moves
                sl.raw = as_multi(unary_union([sl.raw, *sl.additions]).buffer(1e-3, join_style="mitre").buffer(-1e-3, join_style="mitre"))
            tree = STRtree(sl.cuts) if sl.cuts else None
            sl.facets = []; sl.hinges = []; sl.bevels = []; at = {}           # at: face → its facet
            for f in sl.pn.faces:
                tri = Polygon(sl.pn.tri[f])
                near = [sl.cuts[i] for i in tree.query(tri)] if tree is not None else []
                near += self.face_trims.get(f, [])
                g = as_multi(sl.pn.to_local(f, tri.difference(unary_union(near)) if near else tri))
                if not g.is_empty:
                    at[f] = len(sl.facets); sl.facets.append((frames[f], g)); sl.hinges.append(self.hinge(sl.pn, f, at))
                    sl.bevels.append(self.grooved.get(f))
            sl.hinges += [[at[f], 0, 0, 0, 0, 0, 1, 0] if f in at else None for f in sl.tab_of]    # a tab rides on its face
            sl.bevels += [None] * len(sl.tab_of)
            sl.facet_t = [None] * len(sl.facets) + sl.tab_t
            sl.facets += sl.tab_facets
            if self.inside:                                   # the inside face up on the cutter: the net seen from inside
                sl.mirror()
        # the sheet's outer face lies on the model's surface and its thickness goes inwards, so the outside is one
        # surface; centred on the surface, every fold left a notch on the outside and the model grew by half a sheet
        for sl in slices + extra:
            if sl.facets:
                sl.facets = [(self.sunk(M), g) for M, g in sl.facets]
        if self.hinged and slices:
            try:                                              # core.solid cuts the grooves with it; the browser build has no wheel for it
                import manifold3d  # noqa: F401
            except ImportError:
                slices[0].warnings.append("this build cannot cut the fold grooves into the print files (it runs in the browser): the "
                                          "panels would export plain and not fold. Export the print plates from the installed app")
        n_panels = len(slices)
        if not p["separate"] and n_panels > 0.6 * len(mesh.faces):
            ctx.errors.append(f"unfolding gave {n_panels} panels for {len(mesh.faces)} faces — use a bigger facet size or enlarge the sheet")
        self.check_walls(slices)
        said = len(ctx.errors)
        self.check_folds(ctx, panels, seams)
        if len(ctx.errors) == said:                           # a sheet that does not fold at all has said so: how far it folds is moot
            self.check_closing(slices)
        ctx.notes_extra = f"unfolded {len(mesh.faces)} triangles into {n_panels} panel(s), {len(seams)} seams"
        return slices + extra

    def check_walls(self, slices):
        """The sheet lies inside the surface, one thickness deep. Where the model itself is thinner than two sheets (the
        wall of a bowl, a fin), the sheet under one side of it runs into the sheet under the other side, and the
        panels there cannot both be fitted. A ray from the middle of each face, straight into the model, finds how
        thick the model is there.
        ponytail: one ray per face, from its middle; a wall that thins only near a face's edge is missed. Needs the ray
        engine's rtree, which the browser build has not: no check there."""
        m, t = self.mesh, self.t
        try:
            start = m.triangles_center - m.face_normals * 1e-3
            hit, ray, _ = m.ray.intersects_location(start, -m.face_normals, multiple_hits=False)
        except Exception:                                     # no rtree (trimesh raises its own error types for it)
            return
        deep = np.full(len(m.faces), np.inf); deep[ray] = np.linalg.norm(hit - start[ray], axis=1)
        for sl in slices:
            thin = deep[sl.pn.faces]; n = int((thin < 2 * t).sum())
            if n:
                sl.warnings.append(f"{n} face(s) lie on a wall of the model thinner than two sheets (down to {thin.min():.1f} mm, the sheet "
                                   f"is {t:g} mm): the panel on the far side of that wall is in the way. Use a thinner sheet, or "
                                   f"make the wall thicker (Model tab: thicken)")

    def notch(self, bend):
        """What a fold by `bend` takes off the closing face on each side of its line (mm): half the opening of a printed
        groove, or, in a sheet that is not grooved, the t·tan(bend / 2) the fold itself needs. See notch_width."""
        return notch_width(bend, self.t - self.skin, self.land, self.stop)

    def check_closing(self, slices):
        """The folds that cannot close (unfold.closing_shortfall): a sheet thicker than the curve's radius, or faces too
        small for the sheet, cannot be folded to the model."""
        m = self.mesh
        L = np.linalg.norm(np.diff(m.vertices[m.face_adjacency_edges], axis=1)[:, 0], axis=1)
        folds = [np.asarray(sl.pn.folds, int) for sl in slices]
        if not sum(map(len, folds)):
            return
        stuck = closing_shortfall(m, self.notch(m.face_adjacency_angles) * L, np.concatenate(folds)); at = 0
        for sl, f in zip(slices, folds):
            n = int(stuck[at:at + len(f)].sum()); at += len(f)
            if n:
                sl.warnings.append(f"{n} fold(s) cannot close in {self.t:g} mm sheet: folding takes depth × tan(bend / 2) "
                                   f"off the inside of the bend on each side of a fold, and here the folds around a face need "
                                   f"more than the whole face. Use a thinner sheet or a bigger facet size, or round the model "
                                   f"less tightly: a curve needs a radius bigger than the sheet is thick")

    def windows(self, slices):
        """A window in every face (`window` > 0): the face set in by a frame, cut out. The frame is what the share asks
        for, and at least the minimum feature width plus what the widest groove on the face's edges takes."""
        share = self.p["window"]
        if not share:
            return
        m = self.mesh; room = self.back.copy()                # what a cut-back seam edge already took
        p = self.p                                            # and what the joint's holes or slots reach in from the edge
        holes = lambda h: min(p["inset"], 0.2 * h) + min(p["hole_d"], 0.3 * h) / 2      # noqa: E731
        slot = lambda h: min(p["inset"], 0.1 * h) + min(p["rib_w"], max(0.22 * h, 2 * self.t))   # noqa: E731
        if self.hinged:                                       # a groove on each of its edges
            for f in m.face_adjacency.T:
                np.maximum.at(room, f, self.notch(m.face_adjacency_angles))
        for sl in slices:
            for f in sl.pn.faces:
                tri = Polygon(sl.pn.tri[f]); r = 2 * tri.area / tri.length            # the inscribed circle's radius
                h = 2 * tri.area / max(np.linalg.norm(np.diff(np.vstack([sl.pn.tri[f], sl.pn.tri[f][:1]]), axis=0), axis=1))   # the least height
                joint = {"rivet": holes, "laced": holes, "strip": holes, "rib": slot}.get(self.p["joint"], lambda h: 0)(h)   # as fit_sizes shrinks them
                frame = max((1 - share) * r, 1.35 * self.p["min_feature"] + room[f] + joint)      # a third over: the thin-spot check measures to the hair (at 1.25 five frames of the lamp were flagged)
                hole = tri.buffer(-frame, join_style="mitre")
                if hole.is_empty or hole.geom_type != "Polygon" or 2 * hole.area / hole.length < self.p["min_feature"] / 2:
                    continue                                                        # no room for a window worth cutting
                sl.cuts.append(hole); self.face_cuts.setdefault(f, []).append(hole)

    def corners(self, owner):
        """Faces that share a corner point but no edge. Cutting seam edges back leaves each its tip, and where the
        surface is a saddle the tip of one lies inside the sheet of another. The two solids are intersected (each
        face as it is cut, one sheet deep under the surface) and what they share is cut from the face with more
        room, seen along its own normal.
        ponytail: needs manifold3d; without it (the browser build) the tips stay and the page shows them overlapping."""
        if not self.face_trims:
            return
        try:
            import manifold3d as m3
        except ImportError:
            return
        m, t = self.mesh, self.t
        edge_mates = {(int(a), int(b)) for a, b in m.face_adjacency} | {(int(b), int(a)) for a, b in m.face_adjacency}
        area = m.area_faces; solid = {}

        def cut(f):                                            # the face in its layout, less what was cut back so far
            tri = Polygon(owner[f].pn.tri[f]); trims = self.face_trims.get(f)
            return tri.difference(unary_union(trims)) if trims else tri

        def body(f):                                           # … as a solid on the model, one sheet deep
            if f not in solid:
                g = owner[f].pn.to_local(f, cut(f)); g = max(shapely.get_parts(g), key=lambda x: x.area, default=None) if not g.is_empty else None
                if g is None or g.geom_type != "Polygon" or g.area < 1e-6:
                    solid[f] = None
                else:
                    M = self.frames[f]
                    solid[f] = m3.Manifold.extrude(m3.CrossSection([np.asarray(shapely.geometry.polygon.orient(g, 1).exterior.coords)[:-1]]), t).translate([0, 0, -t]).transform(M[:3, :4])
            return solid[f]
        for v in range(len(m.vertices)):
            around = [int(f) for f in m.vertex_faces[v] if f >= 0 and f in owner]
            for i, f in enumerate(around):
                for g in around[i + 1:]:
                    if (f, g) in edge_mates or m.face_normals[f] @ m.face_normals[g] > 0.9999:
                        continue
                    a, b = body(f), body(g)
                    if a is None or b is None:
                        continue
                    both = a ^ b
                    if both.volume() < 0.01:
                        continue
                    lose = f if area[f] >= area[g] else g      # the bigger face gives up the tip
                    pts = np.asarray(both.to_mesh().vert_properties)[:, :3]
                    loc = (np.linalg.inv(self.frames[lose]) @ np.c_[pts, np.ones(len(pts))].T).T[:, :2]
                    pn = owner[lose].pn
                    tip = shapely.MultiPoint((pn.R[lose] @ loc.T).T + pn.t[lose]).convex_hull.buffer(0.02, join_style="mitre").intersection(Polygon(pn.tri[lose]))
                    if tip.area > 1e-6:
                        self.face_trims.setdefault(lose, []).append(tip); solid.pop(lose, None)

    def across(self, geom, pf, f, pg, g):
        """Layout geometry of face f (in panel pf) where it lies in the layout of face g (panel pg), the two being in
        one plane on the model: out of f's layout to its own frame, through the model, into g's frame and layout."""
        def h(R, t):
            M = np.eye(3); M[:2, :2] = R; M[:2, 2] = t
            return M
        W = (np.linalg.inv(self.frames[g]) @ self.frames[f])[np.ix_([0, 1, 3], [0, 1, 3])]
        M = h(pg.R[g], pg.t[g]) @ W @ np.linalg.inv(h(pf.R[f], pf.t[f]))
        return affinity.affine_transform(geom, [M[0, 0], M[0, 1], M[1, 0], M[1, 1], M[0, 2], M[1, 2]])

    def groove(self, sl, a, b, k, f=None):
        """The V groove a printed panel gets along edge a→b (a fold, or a seam edge to mitre: then `f` is the one face it
        lies on) of adjacency k: opened to the edge's bend (notch), on the face that closes (the inside of a convex
        edge), down to the skin. An edge between faces in one plane bends nothing and gets none."""
        m = self.mesh; wide = float(self.notch(m.face_adjacency_angles[k]))
        if not self.hinged or not wide:
            return
        top = bool(m.face_adjacency_convex[k]) == self.inside       # the closing face is the one up on the bed
        sl.grooves.append(Groove(tuple(map(float, a)), tuple(map(float, b)), self.land, self.skin, wide, top))
        for face in ([f] if f is not None else m.face_adjacency[k]):      # a fold grooves both of its faces
            fl = list(m.faces[face]); va, vb = m.face_adjacency_edges[k]
            la, lb = self.local[face][fl.index(va)], self.local[face][fl.index(vb)]
            self.grooved.setdefault(int(face), []).append([*(round(float(x), 4) for x in (*la, *lb)), round(wide, 4), 1 if m.face_adjacency_convex[k] else -1])

    def hinge(self, pn, f, at):
        """How the 3D view unfolds face f: the facet it hangs from, the fold line between them (a point and a direction,
        on the model) and the turn about it that lays f flat beside that facet. None for a panel's first face."""
        if f not in pn.parent or pn.parent[f][0] not in at:
            return None
        g, k = pn.parent[f]; m = self.mesh; va, vb = m.face_adjacency_edges[k]
        d = m.vertices[vb] - m.vertices[va]; d = d / np.linalg.norm(d)
        nf, ng, a = m.face_normals[f], m.face_normals[g], float(m.face_adjacency_angles[k])
        turned = lambda u: nf * math.cos(u) + np.cross(d, nf) * math.sin(u) + d * (d @ nf) * (1 - math.cos(u))   # noqa: E731
        u = a if turned(a) @ ng > turned(-a) @ ng else -a           # the way round that brings f's normal onto g's
        return [at[g], *(round(float(x), 4) for x in m.vertices[va]), *(round(float(x), 6) for x in d), round(u, 6)]

    def sunk(self, M):
        """Frame M moved half a sheet inwards: the centred extrusion then spans the surface to one thickness inside."""
        M = M.copy(); M[:3, 3] += self.mid(M[:3, 2])
        return M

    def mid(self, n):
        """From a point on the model's surface to the middle of the sheet under it, for a face with outward normal n."""
        return -n * self.t / 2

    def mid_edge(self, E, na, nb):
        """Where the mid-planes of two faces meet, for their shared edge at E on the surface: E moved by both faces'
        offsets, further the sharper the edge (not past BACK_ON_ITSELF, where the two fold back on each other)."""
        return E + (self.mid(na) + self.mid(nb)) / max(1 + na @ nb, BACK_ON_ITSELF)

    def mountain(self, convex):
        """Whether an edge folds as a mountain seen from the face up on the cutter: a convex edge does seen from outside,
        and is a valley seen from inside."""
        return bool(convex) != self.inside

    def fold_line(self, convex):
        """The line style of a panel's fold: scored, or perforated when asked."""
        return self.styles[0 if self.mountain(convex) else 1]

    def tab_line(self, convex):
        """The line style of a tab's base or its second bend: always a score."""
        return SCORE[0 if self.mountain(convex) else 1]

    def check_folds(self, ctx, panels, seams):
        """A fold line in a panel, or a joint whose tab or strip bends over the seam, needs a sheet that folds: 3 mm
        plywood cracks along the score where 3 mm cardboard folds. Every face its own panel, joined by ribs, folds
        nothing."""
        p = self.p; kind = p.get("material_kind") or p.get("material"); most = FOLDS.get(kind)
        # what has to fold as a sheet: a panel's folds unless they are grooved (then the skin folds), and a joint's tab or
        # strip over each seam unless it is a thin printed flap
        folds = (0 if self.hinged else sum(len(self.creases(pn)) for pn in panels)) + (len(seams) if p["joint"] in FOLDED_JOINTS and not self.thin_tabs else 0)
        if most is None or not folds or self.t <= most:
            return
        why = "it does not fold, it cracks along the line" if most == 0 else f"it folds along a score up to about {most:g} mm"
        msg = (f"{folds} fold(s) in {self.t:g} mm {kind}: {why}. Cut every face as its own panel (separate) and join them with "
               f"a joint that needs no fold (rib, rivet or laced), or use a thinner or foldable material")
        ctx.errors.append(msg)
        fix = {"separate": True, "joint": "rib"}
        if (target_faces(ctx.mesh, p["facet"]) or len(ctx.mesh.faces)) > MAX_PANELS:    # each face is a part now: as few as build cuts
            fix["facet"] = math.ceil(math.sqrt(ctx.mesh.area / (0.433 * MAX_PANELS)))
        ctx.fixes = [{"error": msg, "options": [{"title": "every face its own panel, joined by ribs", "set": fix,
                                                 "note": "rigid panels, each rib cut at its seam's angle and slotted in from the back"}]}]

    # ---------------------------------------------------------------- helpers
    def creases(self, pn):
        """The panel's edges that are bent. The triangles of one flat face (a rectangle's diagonal, a hexagon's
        spokes) are joined edges too, but there is nothing to fold there and so nothing to score."""
        return [k for k in pn.folds if self.mesh.face_adjacency_angles[k] >= FLAT]

    @staticmethod
    def usable_sheet(p):
        """Panel size limit for the unfolder: the sheet minus margins, minus room for glue tabs that grow the outline."""
        room = p["tab_h"] if p["joint"] in FOLDED_JOINTS and p["joint"] != "strip" else 0     # a strip is a part of its own: the outline gains nothing
        return (p["sheet"][0] - 2 * p["sheet_margin"] - 2 * room, p["sheet"][1] - 2 * p["sheet_margin"] - 2 * room)

    def side(self, sl, f, va, vb) -> Side:
        """Edge va→vb of face f in panel-layout coords and in the face's own frame (for the 3D parts)."""
        fl = list(self.mesh.faces[f]); ia, ib = fl.index(va), fl.index(vb)
        A, B, d, n = edge_geom(sl.pn.tri[f], ia, ib)
        la, lb, ld, ln = edge_geom(self.local[f], ia, ib)
        tri = Polygon(sl.pn.tri[f]); L = float(np.linalg.norm(B - A))
        return Side(sl, f, A, B, d, n, L, tri, 2 * tri.area / L, (la + lb) / 2, ld, ln)

    def interior_angle(self, k):
        """Angle between the two panels measured inside the model (deg): 90 for a cube edge, >180 for a concave edge."""
        return 180 - math.degrees(self.mesh.face_adjacency_angles[k]) if self.mesh.face_adjacency_convex[k] \
            else 180 + math.degrees(self.mesh.face_adjacency_angles[k])

    def mark(self, s, j, depth, on_tab=False):
        """The seam number beside edge A→B of side `s`, turned to read along the edge: on the tab itself where the
        side carries one (`on_tab`, as Pepakura prints them — the tab is glued out of sight and has no fold across
        it), else set `depth` in from the edge on the panel; at the first of a few spots (the middle of the edge
        first, then towards its ends, then deeper in) where the whole number lies on material clear of the cuts, the
        fold lines and the numbers already there. A seam with no such spot gets none, and the panel says how many:
        a number over a fold or another number reads as neither."""
        if not self.p["edge_labels"]:
            return
        p, sl = self.p, s.sl
        text = str(j); A, d, n, L = s.A, s.d, s.n, s.L
        rot = math.degrees(math.atan2(d[1], d[0])) % 180
        if rot > 90:
            rot -= 180                                                      # never upside down in the panel's frame
        if sl.room is None or len(sl.additions) != sl.room_tabs:            # the panel with the tabs it has so far, a hair in
            sl.room = unary_union([sl.raw, *sl.additions]).buffer(-0.3); sl.room_tabs = len(sl.additions)
        h = mark_box(0, 0, text, p["font"]).bounds[3] * 2
        # a panel collects hundreds of numbers and holes on a dense mesh: each number is boxed once, and a spot is
        # measured only against what lies within reach of it (one by one against all, it took minutes, bugs/028)
        sl.mark_boxes += [mark_box(*m[:3], p["font"], mark_rot(m)) for m in sl.marks[len(sl.mark_boxes):]]
        clear, taken = np.array([*sl.cuts, *(ln for _, ln in sl.lines)], dtype=object), np.array(sl.mark_boxes, dtype=object)
        near_clear, near_taken = STRtree(clear), STRtree(taken)

        def free(b):
            x0, y0, x1, y1 = b.bounds; reach = shapely.box(x0 - 0.3, y0 - 0.3, x1 + 0.3, y1 + 0.3)   # 0.3 mm off cuts and folds
            return ((shapely.distance(b, clear[near_clear.query(reach)]) >= 0.3).all()
                    and shapely.disjoint(b, taken[near_taken.query(b)]).all())
        deeps = ([-(h + 0.8)] if on_tab else []) + [depth, depth + p["font"] * 0.5, depth + p["font"]]   # on the tab: 0.8 mm past the hinge
        for deep in deeps:
            for along in (0.5, 0.35, 0.65, 0.22, 0.78):
                c = A + d * (along * L) + n * (deep + h / 2 + s.back)
                b = mark_box(float(c[0]), float(c[1]), text, p["font"], rot)
                if sl.room.covers(b) and free(b):
                    sl.marks.append((float(c[0]), float(c[1]), text, round(rot, 2)))
                    return
        sl.skipped.setdefault("seam number", []).append(j)

    def fit_sizes(self, sides):
        """Joint sizes that fit both triangles: holes at ≤ 20 % of the triangle height, ≤ 30 % wide; rib slots start at
        ≤ 10 % and reach ≤ 32 % so that three ribs (one per edge) never meet in the middle of a triangle."""
        p = self.p; h = min(s.h for s in sides)
        if p["joint"] == "rib":
            inset, hole, rib = min(p["inset"], 0.1 * h), p["hole_d"], min(p["rib_w"], max(0.22 * h, 2 * self.t))
        else:
            inset, hole, rib = min(p["inset"], 0.2 * h), min(p["hole_d"], 0.3 * h), p["rib_w"]
        if inset < p["inset"] - 1e-9 or hole < p["hole_d"] - 1e-9 or (p["joint"] == "rib" and rib < p["rib_w"] - 1e-9):
            for s in sides:
                s.sl.reduced += 1
        return inset, hole, rib

    def collides(self, s, geom):
        return any(geom.intersects(c) for c in self.face_cuts.get(s.f, ()))

    def add_cut(self, s, geom):
        s.sl.cuts.append(geom); self.face_cuts.setdefault(s.f, []).append(geom)

    def cut_if_fits(self, s, geom, j, what):
        if s.tri.buffer(-self.p["min_feature"]).contains(geom) and not self.collides(s, geom):
            self.add_cut(s, geom); return True
        s.sl.skipped.setdefault(what, []).append(j)
        return False

    def folded_tab(self, a, b, poly):
        """A tab drawn outside edge A→B of face a, shown in 3D folded flat against the inside of face b."""
        A, d, out, L = a.A, a.d, -a.n, a.L
        pts = [b.lmid + (float(np.dot(P - A, d)) / L - 0.5) * L * b.ld + float(np.dot(P - A, out)) * b.ln for P in np.asarray(poly.exterior.coords)]
        M = self.frames[b.f].copy(); h = self.skin
        if self.thin_tabs:                                    # a flap of the skin, folded round the edge onto the outside of the mating panel
            M[:3, 3] += M[:3, 2] * (h / 2 + self.t / 2)         # (every facet is then sunk half a sheet, see build)
        else:
            M[:3, 3] -= M[:3, 2] * self.t                      # just inside the mating panel
        b.sl.tab_facets.append((M, as_multi(Polygon(pts)))); b.sl.tab_of.append(b.f); b.sl.tab_t.append(h if self.thin_tabs else None)

    # ---------------------------------------------------------------- joints
    def joint(self, j, k, sides, phi, convex):
        p = self.p; jt = p["joint"]
        # a mitre: the half of a fold's groove that lies on each panel. Outward seams only: at an inward one the two
        # sheets move apart, and a mitre there would open a V on the outside and cut a glue tab off its panel
        if self.mitres and convex:
            for s in sides:
                self.groove(s.sl, s.A, s.B, k, s.f)
        if jt in ("rivet", "laced", "strip"):
            return self.holes(j, sides, phi, convex)
        if jt == "loops":
            return self.loops(j, sides)
        if jt == "rib":
            return self.rib(j, k, sides, phi)
        if jt == "snap":
            return self.snap(j, k, sides, convex)
        if jt == "click":
            return self.click(j, k, sides, convex)
        if jt != "seam":
            self.tabs(j, sides, jt, convex)
        else:
            for s in sides:
                self.mark(s, j, p["font"] * 0.5)
        return []

    def hole_range(self, s, inset, hole_d):
        """Parameter interval [q0, q1] along the seam where a hole centred `inset` inside stays clear of the triangle's
        other edges (hole radius + the min feature: the wall the hole check asks for, so a hole placed here passes it)."""
        r = hole_d / 2 + self.p["min_feature"]
        trims = self.face_trims.get(s.f)                   # the face as it is cut: less its cut-back seam edges
        tri_in = (s.tri.difference(unary_union(trims)) if trims else s.tri).buffer(-r)
        if tri_in.is_empty:
            return None
        line = LineString([s.A + s.n * inset, s.B + s.n * inset])
        hit = line.intersection(tri_in)
        segs = [g for g in shapely.get_parts(hit) if g.geom_type == "LineString" and not g.is_empty]
        if not segs:
            return None
        seg = max(segs, key=lambda g: g.length); c = np.asarray(seg.coords)
        return sorted(float(np.dot(c[i] - line.coords[0], s.d)) / s.L for i in (0, -1))

    def holes(self, j, sides, phi, convex):
        """Holes at the same parameters on both panels, spread over the interval that fits both triangles."""
        p = self.p; L = sides[0].L; want = 2 if p["joint"] != "rivet" else 1
        inset, hole_d, _ = self.fit_sizes(sides)
        ranges = [self.hole_range(s, inset + s.back, hole_d) for s in sides]
        ss = []
        if all(r is not None for r in ranges):
            q0, q1 = max(r[0] for r in ranges), min(r[1] for r in ranges)
            usable = (q1 - q0) * L
            if usable >= 0:
                # every hole is collision-checked against every cut on its panel, so the count per seam is capped:
                # past it the seam is metres long and the spacing, not the hole count, is the setting to change
                n = min(MAX_HOLES, max(want, int(usable // p["spacing"]) + 1), max(1, int(usable // (2 * hole_d)) + 1))
                ss = [(q0 + q1) / 2] if n == 1 else list(np.linspace(q0, q1, n))
        placed = []
        for q in ss:
            circles = [circle(s.A + (s.B - s.A) * q + s.n * (inset + s.back), hole_d) for s in sides]
            if any(self.collides(s, c) for s, c in zip(sides, circles)):
                continue
            for s, c in zip(sides, circles):
                self.add_cut(s, c)
            placed.append(q)
        if len(placed) < want:
            for s in sides:
                s.sl.skipped.setdefault("hole", []).append(j)
        for s in sides:
            self.mark(s, j, inset + hole_d / 2 + p["font"] * 0.45)
        if p["joint"] != "strip" or not placed:
            return []
        # connecting strip: rounded, folded along its centreline, holes mirrored on both halves
        wall = max(hole_d, p["min_feature"]); Wd = 2 * inset + hole_d + 2 * wall; Ls = L
        # the straight part reaches the outermost holes: one in a rounded end kept a fraction of the wall
        xs = [(q - 0.5) * L for q in placed]
        strip = LineString([(min(-Ls / 2 + Wd / 2, min(xs)), 0), (max(Ls / 2 - Wd / 2, max(xs)), 0)]).buffer(Wd / 2)
        holes = [circle(((q - 0.5) * L, sgn * inset), hole_d) for q in placed for sgn in (1, -1)]
        sl = Slice(f"S-{j}", "J", np.eye(4), self.t, note=f"{phi:.0f}°")
        sl.raw = as_multi(strip); sl.cuts = holes
        sl.lines.append(("solid" if convex else "dashed", LineString([(-Ls / 2 + Wd / 2, 0), (Ls / 2 - Wd / 2, 0)])))
        sl.marks.append((0.0, 0.0 - inset * 0.35, str(j)))
        prof = as_multi(strip.difference(unary_union(holes)))
        big = Ls + Wd
        sl.facets = []
        for s, sgn in zip(sides, (1, -1)):
            half = prof.intersection(Polygon([(-big, 0), (big, 0), (big, sgn * big), (-big, sgn * big)]))
            d, n, m = s.ld, s.ln, s.lmid
            g = affinity.affine_transform(half, [d[0], sgn * n[0], d[1], sgn * n[1], m[0], m[1]])
            M = self.frames[s.f].copy(); M[:3, 3] -= M[:3, 2] * self.t     # strips sit inside the panels
            sl.facets.append((M, as_multi(g)))
        return [sl]

    def loops(self, j, sides):
        """Eyelet loops alternating along the seam: side A gets the even positions, side B the odd ones, so the loops
        interleave like hinge knuckles and one lace runs through all of them. Loops stay in their panel's plane."""
        p = self.p; L = sides[0].L
        _, hole_d, _ = self.fit_sizes(sides)
        loop_d = 2 * hole_d + 2 * max(hole_d * 0.8, p["min_feature"])
        n = max(2, int(L // (loop_d * 1.15)))
        for i in range(n):
            q = (i + 0.5) / n; s = sides[i % 2]
            c = s.A + (s.B - s.A) * q - s.n * (loop_d * 0.5 - 0.6)      # centre just outside the edge
            loop = unary_union([circle(c, loop_d), Polygon([s.A + (s.B - s.A) * q - s.d * loop_d * 0.45, s.A + (s.B - s.A) * q + s.d * loop_d * 0.45,
                                                            c + s.d * loop_d * 0.45, c - s.d * loop_d * 0.45])])
            s.sl.additions.append(loop)
            hole = circle(c, hole_d)
            s.sl.cuts.append(hole)
            s.sl.tab_facets.append((self.frames[s.f], as_multi(s.sl.pn.to_local(s.f, loop.difference(hole))))); s.sl.tab_of.append(s.f); s.sl.tab_t.append(None)
        for s in sides:
            self.mark(s, j, p["font"] * 0.5)
        return []

    def rib(self, j, k, sides, phi):
        p = self.p; t = self.t; tr = p["rib_thick"] or t
        inset, _, w = self.fit_sizes(sides); tab = w; inset += sides[0].back
        # slots in both panels, perpendicular to the seam (never across a fold or into another cut)
        slots = [rect_along(s.A + (s.B - s.A) / 2 + s.n * inset, s.A + (s.B - s.A) / 2 + s.n * (inset + tab), tr + p["slot_offset"]) for s in sides]   # inset holds the cut-back: the same on both sides for a rib
        if not all(s.tri.buffer(-p["min_feature"] / 2).contains(sl_) and not self.collides(s, sl_) for s, sl_ in zip(sides, slots)):
            for s in sides:
                s.sl.skipped.setdefault("rib slot", []).append(j)
                self.mark(s, j, p["font"] * 0.5)
            return []
        # rib frame: origin = edge midpoint, x = into panel A along its surface, y = into the model (−normal A), z ∥ edge
        m = self.mesh; fa, fb = (int(x) for x in m.face_adjacency[k]); va, vb = m.face_adjacency_edges[k]
        E = m.vertices[[va, vb]].mean(0); e = m.vertices[vb] - m.vertices[va]; e /= np.linalg.norm(e)
        na, nb = m.face_normals[fa], m.face_normals[fb]

        def inward(f):
            c = m.triangles_center[f] - E; c -= np.dot(c, e) * e; return c / np.linalg.norm(c)
        dA, dB = inward(fa), inward(fb)
        M = frame_xy(self.mid_edge(E, na, nb), dA, -na)           # the rib is drawn about where the panels' mid-planes meet
        dB2 = np.array([dB @ dA, dB @ -na]); nB2 = np.array([-nb @ dA, nb @ na])
        L = inset + tab + t * 2

        def arm(d, n):
            body = Polygon([d * 0 + n * t / 2, d * L + n * t / 2, d * L + n * (t / 2 + w), n * (t / 2 + w)])
            tabp = Polygon([d * inset - n * (t / 2 + 0.5), d * (inset + tab) - n * (t / 2 + 0.5), d * (inset + tab) + n * (t / 2 + 0.1), d * inset + n * (t / 2 + 0.1)])
            return unary_union([body, tabp])
        nA2 = np.array([0.0, 1.0]); dA2 = np.array([1.0, 0.0])
        corner = Polygon([nA2 * t / 2, nA2 * (t / 2 + w), nB2 * (t / 2 + w), nB2 * t / 2])
        rib = unary_union([arm(dA2, nA2), arm(dB2, nB2), corner]).buffer(0)
        if max(min_dims(rib)) < p["min_part"]:               # on a small face the rib shrinks with it: too small to cut and handle, it is no joint
            for s in sides:
                s.sl.skipped.setdefault("rib big enough to handle", []).append(j)
                self.mark(s, j, p["font"] * 0.5)
            return []
        for s, sl_ in zip(sides, slots):
            self.add_cut(s, sl_); self.mark(s, j, inset - s.back + tab + p["font"] * 0.45)   # mark() adds the cut-back itself
        sl = Slice(f"R-{j}", "J", M, tr, note=f"{phi:.0f}°")
        sl.raw = as_multi(rib)
        sl.marks.append((float(L * 0.5), float(t / 2 + w * 0.5), str(j)))
        return [sl]

    def snap_wall(self, bend, convex, H=None, w=SNAP_WALL, groove=True):
        """The cross-section of a snap wall for a seam bent by `bend`, [(u, z)]: u from the seam edge into the panel, z
        up from the outer face. Its front is the seam's own plane, where the two panels meet (the mitre of an outward
        seam, carried on upwards), so the two walls of a seam lie face to face; its back has the groove the clip hooks
        into. Also the point its front starts at and the two directions it is drawn in: up the front, and into the wall.
        The click joint asks for walls of its own height `H` and thickness `w`, without the groove."""
        t = self.t; H = self.p["snap_h"] if H is None else H
        if convex:                                            # it leans over its own panel by half the bend
            # the panels turn about the top of the skin and meet on the plane through it at half the bend. The mitre
            # ends on that plane, or short of it (a shallow seam's mitre is as wide as the groove's flat bottom, a
            # fold stop opens it further): the wall then starts at the mitre and leans out to the plane first
            wide = float(self.notch(bend)); h = bend / 2; tan = math.tan(h)
            z1 = max(t, (wide + t + self.skin * tan) / (1 + tan))
            at = np.array([(z1 - self.skin) * tan, z1]); up = np.array([math.sin(h), math.cos(h)]); back = np.array([math.cos(h), -math.sin(h)])
            lead = [(wide, t - 0.05)] if z1 > t + 1e-9 else []; foot = max(0.05, (z1 - w * math.sin(h) - t + 0.05) / math.cos(h))
        else:                                                 # an inward seam: the panels meet outside the edge, the wall leans out to there
            h = bend / 2; z1 = t / (1 - math.tan(h))
            at = np.array([-z1 * math.tan(h), z1]); up = np.array([-math.sin(h), math.cos(h)]); back = np.array([math.cos(h), math.sin(h)])
            lead = [(0.0, t - 0.05)]; foot = (z1 + w * math.sin(h) - t + 0.05) / math.cos(h)
        q = lambda s, m: tuple(float(x) for x in at + up * s + back * m)   # noqa: E731
        g, l = SNAP_GROOVE, SNAP_LEDGE
        notch = [q(l, w), q(l, w - g), q(l - 0.5, w - g), q(l - 1.0, w)] if groove else []
        profile = lead + [q(0 if lead else -0.05, 0), q(H - 0.4, 0), q(H, 0.4), q(H, w - 0.4), q(H - 0.4, w), *notch, q(-foot, w)]
        return profile, at, up, back, h

    def click_parts(self, bend, convex, room=1e9, span=CLICK_SPAN[0]):
        """The cross-sections of a click joint for a seam bent by `bend`, each [(u, z)] like snap_wall → a Click; or a
        sentence, when the tooth does not fit.
        Drawn in the seam's own terms: s up the plane the panels meet on, m across it. The tooth goes through that
        plane, under the bar, and its ridge stands up behind it. Its underside rises as steeply as prints without
        support and stays clear of the other panel, so the sharper the seam, the higher the bar sits.
        The bar is a bridge between its two posts, `span` apart. Lifted `CLICK_BITE` in its middle it is stretched
        12 · lift · thickness / span² (a beam held at both ends), so its thickness is the most that keeps that under
        `CLICK_STRAIN`: a longer seam gets a longer and thicker bar. The ridge is crowned along the seam (full height
        in the middle 2 mm, lower beside it, none further out) to lift the bar there and nowhere else: a ridge as
        wide as the tooth would force the bar flat over its width and bend the short rest of it far too much.
        Every upright stands on a ramp (`braced`) as far as the panel has `room`."""
        t = self.t; fit = self.p["snap_fit"]; D = CLICK_DEEP; h = bend / 2
        wall, at, up, back, _ = self.snap_wall(bend, convex, 1.0, CLICK_WALL, False)
        q = lambda s, m: tuple(float(x) for x in at + up * s + back * m)   # noqa: E731
        slope = math.tan(math.pi / 2 - SNAP_LEAN - (h if convex else -h))     # the printable underside, seen from the plane
        # under the tooth, d past the plane: over the slope that prints, and 0.3 mm over the other panel's inside face
        clear = lambda d: (t + 0.3 - at[1] - back[1] * d) / up[1]   # noqa: E731
        low = lambda d: max(clear(d), max(0.0, clear(0)) + d * slope)   # noqa: E731
        d1 = D + fit; d2 = d1 + 1.2                         # the back of the bar, where the ridge stands up; the tooth's tip
        neck = max(low(0) + CLICK_NECK, low(d1) + CLICK_NECK, low(d2) + 1.2)   # the top of the tooth's neck
        sb = neck + fit + 0.05                              # the bar's underside
        most = CLICK_STRAIN * (span - 1) ** 2 / (12 * CLICK_BITE)       # the ridge's middle is 2 mm wide: the bar bends over a little less than its span
        tb = next((x for x in CLICK_THICK if x <= most + 1e-9 and sb + x <= self.p["snap_h"]), None)
        if tb is None:
            return f"the tooth needs walls {sb + CLICK_THICK[-1]:.1f} mm high: raise `snap wall`"
        top = sb + tb; under = [q(low(d), -d) for d in np.linspace(0, d2, 9)]

        def tooth(ridge):                                     # the wall with the tooth on it, its ridge this far up behind the bar
            head = [q(neck - 0.3, -d2), q(sb + ridge, -d1 - 0.5), q(sb + ridge, -d1), q(neck, -d1)] if ridge > 0 else [q(neck - 0.3, -d2), q(neck, -d2 + 0.6)]
            return [tuple(c) for c in orient(Polygon(wall).buffer(0).union(Polygon([q(low(0), 0.3), *under, *head, q(neck, 0.3)]))).exterior.coords[:-1]]
        lift = lambda x: (lambda r: 3 * r * r - 2 * r ** 3)(1 - 2 * x / span)   # noqa: E731  how far the bar is up, x from its middle, as a share of the lift there
        wall = self.braced(self.snap_wall(bend, convex, sb + CLICK_BITE, CLICK_WALL, False)[0], room)
        teeth = [(0.0, 1.0, tooth(CLICK_BITE)), (0.0, 2.5, tooth(round(0.8 * CLICK_BITE * lift(2.5), 2))), (0.0, CLICK_NOSE / 2, tooth(0))]     # each inside the next: one solid
        post = self.braced(self.snap_wall(bend, convex, top, D, False)[0], room)
        guide = self.braced(self.snap_wall(bend, convex, max(sb - 1.2, 0.6), D, False)[0], room)
        bar = [q(sb, 0), q(top, 0), q(top, D), q(sb, D)]
        reach = max(u for prof in (wall, post) for u, z in prof if z < t + 0.1)
        return Click(wall, teeth, post, bar, guide, reach, tb, 12 * CLICK_BITE * tb / (span - 1) ** 2)

    def braced(self, wall, room):
        """A wall (its cross-section as snap_wall draws it, without a groove) on a ramp: solid from the top of its back
        down to the panel, `CLICK_FOOT` into it and never nearer than 0.8 mm to the end of the `room`. A shut seam
        pulls on the wall and would bend a bare one across its layers at its foot: the ramp gives it a foot several
        times as deep. It also fills the space under a wall that leans over its panel."""
        front, top, foot = np.array(wall[-5]), np.array(wall[-2]), wall[-1]     # the top of its front and of its back, the foot of its back
        to = min(max(foot[0] + CLICK_FOOT, top[0] + 1.5), room - 0.8)       # a wall that leans far over its panel has its foot deep already
        if to < max(foot[0], top[0]) + 0.8:
            return wall
        ramp = Polygon([(foot[0] - 0.4, foot[1]), (to, foot[1]), (to, self.t + 1.0), tuple(float(x) for x in top + (front - top) * 0.3)])
        return [tuple(c) for c in orient(Polygon(wall).buffer(0).union(ramp)).exterior.coords[:-1]]

    def stand(self, s, va, e, c0, c1, profile):
        """A wall on side s of a seam, from c0 to c1 along it: a Rail in the plan, a facet in the 3D view."""
        m = self.mesh; E = m.vertices[va] + e * (c0 + c1) / 2
        s.sl.rails.append(Rail(tuple(s.A + s.d * c0), tuple(s.A + s.d * c1), tuple(s.n), profile))
        into = m.triangles_center[s.f] - E; into -= np.dot(into, e) * e; into /= np.linalg.norm(into)     # into the face, square to the seam
        M = frame_xy(E, into, -m.face_normals[s.f]); M[:3, 3] += M[:3, 2] * self.t / 2      # x into the panel, y into the model, z along the seam; the half sheet every facet is sunk by, taken back
        s.sl.tab_facets.append((M, as_multi(Polygon(profile).buffer(0)))); s.sl.tab_of.append(s.f); s.sl.tab_t.append(c1 - c0)

    def click(self, j, k, sides, convex):
        """Seam j as a click joint, once for every `spacing` of seam: on the first panel a wall with a tooth, on the
        second a bar bridged between two posts, with a block each side of where the tooth comes through. Pressed
        shut, the tooth goes under the bar and its ridge stands up behind it. No part of its own."""
        p = self.p; m = self.mesh
        for s in sides:
            self.mark(s, j, p["font"] * 0.5)
        if not (self.hinged and self.inside):
            return []
        bend = float(m.face_adjacency_angles[k]); L = sides[0].L; a, b = sides
        n = max(1, int(L // max(p["spacing"], 2 * (CLICK_SPAN[1] + 2 * CLICK_POST))))
        room = min(min((c.distance(LineString([s.A, s.B])) for c in self.face_cuts.get(s.f, ())), default=s.h) for s in sides)
        va, vb = m.face_adjacency_edges[k]; e = m.vertices[vb] - m.vertices[va]; e /= np.linalg.norm(e)
        # the walls that stand on the two pieces already (other seams, round the corner): a click slides along its
        # seam to stand clear of them, takes a shorter bar when that is not enough, and is left out when it still
        # finds no room. Two walls grown into one would not fold
        taken = {id(s.sl): unary_union([r.foot() for r in s.sl.rails]).buffer(0.4) for s in sides}
        free = lambda s, c0, c1, prof: not Rail(tuple(s.A + s.d * c0), tuple(s.A + s.d * c1), tuple(s.n), prof).foot().intersects(taken[id(s.sl)])   # noqa: E731
        longest = min(CLICK_SPAN[1], math.floor(L / n - 3 - 2 * CLICK_POST))     # the bar as long as the seam lets it be
        why = ("the seam bends more than 100°: the walls would lean too far to print" if bend / 2 > SNAP_LEAN else
               "the seam is too short" if longest < CLICK_SPAN[0] else "")
        placed = 0
        for span in ([] if why else sorted({longest, CLICK_SPAN[0]}, reverse=True)):
            parts = self.click_parts(bend, convex, room, span)
            why = parts if isinstance(parts, str) else "the frame beside the window is too narrow" if room < parts.reach + 0.8 else ""
            if why:
                break
            half, tooth, long = span / 2, CLICK_NOSE / 2, span + 2 * CLICK_POST

            def pieces(c, parts=parts, half=half, tooth=tooth):   # what a click centred c along the seam stands on each side
                out = [(a, c - tooth - 3, c + tooth + 3, parts.wall), (b, c - half - 0.5, c + half + 0.5, parts.bar)]   # the bar: half a millimetre into each post
                out += [(a, c - x1, c + x1, prof) for _, x1, prof in parts.teeth]
                for sign in (-1, 1):
                    out.append((b, *sorted((c + sign * half, c + sign * (half + CLICK_POST))), parts.post))
                    out.append((b, *sorted((c + sign * (tooth + 0.25), c + sign * (half + 0.5))), parts.guide))     # a block from the tooth to the post, under the bar
                return out
            for i in range(n):
                lo, hi = i / n * L + long / 2 + 1.5, (i + 1) / n * L - long / 2 - 1.5
                for c in sorted(np.arange(lo, hi + 1e-9, 1.0), key=lambda c, lo=lo, hi=hi: abs(c - (lo + hi) / 2)):
                    if all(free(*q) for q in pieces(c)):
                        for q in pieces(c):
                            self.stand(q[0], va, e, *q[1:])
                        placed += 1; break
            if placed:
                break
        if not placed:
            a.sl.skipped.setdefault(f"click joint ({why or 'no room beside the joints of the seams next to it'})", []).append(j)
        return []

    def snap_clip(self):
        """The clip's outline, x across the two walls (0 = where they meet) and y up them: a U whose two legs each end
        in a hook, `SNAP_BITE` into the groove of its wall. Printed flat, so its legs bend along the layers. One
        shape for every seam: the walls are the same at any bend."""
        p = self.p; a = SNAP_WALL + p["snap_fit"]; b = SNAP_BITE; l = SNAP_LEDGE; top = p["snap_h"] + 0.2; lo = l - 0.9; x1 = a + SNAP_LEG
        outer = Polygon([(-a, lo), (a, lo), (x1, lo + 1.5 * SNAP_LEG), (x1, top + 1.6), (-x1, top + 1.6), (-x1, lo + 1.5 * SNAP_LEG)])   # the legs' feet cut back: clear of the panels
        room = Polygon([(a, lo - 1), (a, lo), (a - b, l - 0.4), (a - b, l - 0.05), (a, l - 0.05), (a, top),
                        (-a, top), (-a, l - 0.05), (b - a, l - 0.05), (b - a, l - 0.4), (-a, lo), (-a, lo - 1)])
        return outer.difference(room).buffer(0.25).buffer(-0.25)       # the inside corners rounded: where a leg would crack

    def snap(self, j, k, sides, convex):
        """Seam j as a snap joint: a wall on the inside of each panel, face to face when the seam is shut, and a clip
        over the two for every `spacing` of seam. → the clips, parts of their own."""
        p = self.p; m = self.mesh
        for s in sides:
            self.mark(s, j, p["font"] * 0.5)
        if not (self.hinged and self.inside):
            return []
        bend = float(m.face_adjacency_angles[k]); L = sides[0].L
        profile, at, up, back, h = self.snap_wall(bend, convex)
        reach = profile[-1][0]                                # how far into the panel a wall's foot goes
        n = max(1, int(L // max(p["spacing"], 2 * SNAP_LONG)))
        room = min(min((c.distance(LineString([s.A, s.B])) for c in self.face_cuts.get(s.f, ())), default=s.h) for s in sides)
        why = ("the seam bends more than 100°: the walls would lean too far to print" if h > SNAP_LEAN else
               "the seam is too short" if L / n < SNAP_LONG + 6 else "the frame beside the window is too narrow" if room < reach + 0.8 else "")
        if why:
            sides[0].sl.skipped.setdefault(f"snap wall ({why})", []).append(j)
            return []
        fa, fb = (int(x) for x in m.face_adjacency[k]); va, vb = m.face_adjacency_edges[k]
        e = m.vertices[vb] - m.vertices[va]; e /= np.linalg.norm(e)
        clip = self.snap_clip(); clips = []
        for i in range(n):
            c = (i + 0.5) / n * L; E = m.vertices[va] + e * c
            for s in sides:
                self.stand(s, va, e, c - SNAP_LONG / 2, c + SNAP_LONG / 2, profile)
            a = sides[0]; into = m.triangles_center[a.f] - E; into -= np.dot(into, e) * e; into /= np.linalg.norm(into); inn = -m.face_normals[a.f]
            O = E + into * at[0] + inn * at[1]                # where the two walls' fronts start, on the model
            sl = Slice(f"K-{j}{'abcdefgh'[i] if n > 1 else ''}", "J", frame_xy(O, into * back[0] + inn * back[1], into * up[0] + inn * up[1]), SNAP_CLIP)
            sl.raw = as_multi(clip); sl.springy = True; clips.append(sl)
        return clips

    def tabs(self, j, sides, jt, convex, swapped=False):
        """Tabs on side a of seam j, glued to side b. A tab that would land on its own panel (a concave net) is tried
        from the other side first — the seam then has its tab on panel b, folded onto a — and only when neither
        side has room is the seam left plain, with a warning."""
        p = self.p; t = self.t; a, b = sides
        inset, _, _ = self.fit_sizes(sides)
        L = a.L; h = min(p["tab_h"], L * 0.6, b.h * 0.6); A, d, n = a.A, a.d, a.n
        out = -n                                        # tabs protrude away from the panel
        tan = math.tan(math.radians(p["tab_angle"]))

        hinges = []                                     # the base of each tab, where it folds: scored there and only there

        def trap(s0, s1, height, top_inset):
            x0, x1 = A + d * (s0 * L), A + d * (s1 * L)
            ti = min(top_inset, (s1 - s0) * L * 0.4)
            hinges.append(LineString([x0, x1]))
            return Polygon([x0, x1, x1 - d * ti + out * height, x0 + d * ti + out * height])
        polys, bends = [], []
        if jt in ("tab", "tongue"):
            height = h if jt == "tab" else inset + t + max(h * 0.5, 3)
            polys.append(trap(0.08, 0.92, height, height * tan))
            if jt == "tongue":
                bends.append(LineString([A + d * 0.08 * L + out * inset, A + d * 0.92 * L + out * inset]))
                width = 0.84 * L - 2 * inset * tan
                slot = rect_along(b.A + (b.B - b.A) / 2 + b.n * inset - b.d * width / 2,
                                  b.A + (b.B - b.A) / 2 + b.n * inset + b.d * width / 2, t + p["slot_offset"])
                self.cut_if_fits(b, slot, j, "tongue slot")
        elif jt == "puzzle":
            neck = h * 0.55; head = h * 0.9
            mid = A + d * L / 2
            body = Polygon([mid - d * neck / 2, mid + d * neck / 2, mid + d * neck / 2 + out * h * 0.5, mid - d * neck / 2 + out * h * 0.5])
            polys.append(unary_union([body, circle(mid + out * (h * 0.5 + head * 0.3), head)]))
            bm = b.A + (b.B - b.A) / 2 + b.n * inset
            hole = unary_union([circle(bm + b.n * head * 0.3, head + p["slot_offset"]),
                                rect_along(bm - b.n * inset * 0.2, bm + b.n * head * 0.3, neck + p["slot_offset"])])
            self.cut_if_fits(b, hole, j, "puzzle hole")
        else:
            if jt == "ticked":
                h = min(h * 0.5, L * 0.3)
            nt = max(2, int(L // (2 * h)))
            for i in range(nt):
                c = (i + 0.5) / nt; hw = min(h * 0.6, L / nt * 0.4) / L
                if jt == "multitab": polys.append(trap(c - hw, c + hw, h, h * tan))
                elif jt == "gear":   polys.append(trap(c - hw, c + hw, h, 0))
                else:                                 # diamond / ticked
                    polys.append(Polygon([A + d * (c - hw) * L, A + d * (c + hw) * L, A + d * c * L + out * h]))
                    hinges.append(LineString([A + d * (c - hw) * L, A + d * (c + hw) * L]))
        # a tab may not land on the panel itself (concave layouts), nor touch it or another tab anywhere but along its
        # own edge (the outline would join them and hold the tab on two sides): the other side gets it, else it is a plain seam
        sl = a.sl
        if sl.taken is None or sl.taken_tabs != len(sl.additions):          # the panel with the tabs it has so far
            sl.taken = unary_union([sl.raw, *sl.additions]); sl.taken_tabs = len(sl.additions)
        base = LineString([A, A + d * L]).buffer(0.6)
        for poly in polys:
            if poly.intersection(sl.raw).area > 0.02 * poly.area or poly.buffer(0.3).intersection(sl.taken).difference(base).area > 0.05:
                if not swapped:
                    return self.tabs(j, [b, a], jt, convex, swapped=True)
                a.sl.warnings.append(f"seam {j}: tab would overlap or touch the panel on either side — reduced to a plain seam (lower tab_h)")
                break
        else:
            a.sl.additions += polys
            if self.thin_tabs:
                a.sl.thin += polys; a.sl.thin_t = self.skin
            # the hinge is scored across each tab's base, not along the whole seam edge: the rest of that edge is a cut,
            # and a score under a cut is wasted on the laser and invisible on the part
            a.sl.lines += [(self.tab_line(convex), hl) for hl in hinges]
            a.sl.lines += [(self.tab_line(False), bl) for bl in bends]     # a tongue's second bend: a valley from outside
            for poly in polys:
                self.folded_tab(a, b, poly)
        self.mark(a, j, p["font"] * 0.5, on_tab=bool(polys) and polys[0] in a.sl.additions)
        self.mark(b, j, (inset + t + p["font"] * 0.6) if jt in ("tongue", "puzzle") else p["font"] * 0.5)
