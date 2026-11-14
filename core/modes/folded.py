"""Folded Panels: unfold the (simplified) surface into flat panels with fold lines; join the seams with tabs,
holes (rivet / laced), connecting strips, or slotted angle ribs. Paper, card, cardboard, sheet metal.

Joint sizes adapt to the triangle they sit in (a hole or slot never crosses a fold or the outline); what had to
shrink is reported per panel. Tabs are shown in the 3D view folded onto the panel they glue to."""
from __future__ import annotations
import math
import numpy as np
import trimesh
import shapely
from shapely import affinity
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree
from . import Mode, Param, register
from ..model import Slice
from ..geometry import as_multi, circle, mark_box, mark_rot, rect_along, frame_xy
from ..unfold import unfold

JOINTS = ["seam", "tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle", "rivet", "laced", "loops", "strip", "rib"]
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
THIN_TABS = ("tab", "multitab", "diamond", "ticked", "gear")   # glue tabs a printed panel carries as thin flaps of its skin
FOLDED_JOINTS = ("tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle", "strip")   # a flap or bridge that bends
MAX_HOLES = 60                        # holes along one seam (rivet / laced / strip)
MAX_FACES = 4000                      # triangles this can unfold and lay out in a usable time
MAX_PANELS = 400                      # …and parts, when `separate` makes every triangle one (see build)
JOINT_HELP = ("seam = plain edge (glue / sew) · tab = one glue tab · multitab = several small tabs · diamond = triangular ticks · "
              "ticked = dense small ticks along the seam · "
              "gear = rectangular teeth · tongue = tab into a slot on the other panel · puzzle = round-head tab into a matching hole · "
              "rivet = one hole per spacing on both panels · laced = ≥2 holes per edge on both panels (lace / zip-tie) · "
              "loops = alternating eyelet loops on both edges that interleave like hinge knuckles; one lace through all (cloth, leather, masks) · "
              "strip = holes + a separate rounded strip with matching holes bridging the two panels · "
              "rib = slots + a separate angle rib cut at the fold angle, slotted in from the back (sheet metal)")


def target_faces(mesh, facet):
    """Triangle count for an average edge length `facet` (mm): area / area of an equilateral triangle of that edge."""
    if not facet:
        return 0
    return max(12, int(mesh.area / (0.433 * facet * facet)))


def cluster(m, cell):
    """Vertex clustering (Rossignac–Borrel): every vertex snaps to the mean of its grid cell and faces that fold flat
    go. Panels come out a little more angular than with quadric decimation, but it is plain numpy — the browser
    build, which has no fast-simplification wheel, decimates with this."""
    _, inv = np.unique(np.floor(m.vertices / cell).astype(np.int64), axis=0, return_inverse=True); inv = inv.ravel()
    v = np.zeros((inv.max() + 1, 3)); np.add.at(v, inv, m.vertices); v /= np.bincount(inv)[:, None]
    f = inv[m.faces]; f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    out = trimesh.Trimesh(v, f, process=True); out.update_faces(out.unique_faces())
    return out


def simplify(mesh, target):
    m = mesh.copy()
    if target and len(m.faces) > target:
        try:
            import fast_simplification
            pts, faces = fast_simplification.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int32), target_count=int(target))
            m = trimesh.Trimesh(pts, faces, process=True)
        except ImportError:
            m = cluster(m, math.sqrt(m.area / (0.433 * target)))   # a cell per target-sized equilateral triangle
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces()); m.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(m)
    return m


def edge_geom(tri, ia, ib):
    """Edge A→B of a 2D triangle and the unit normal pointing into the triangle."""
    A, B = tri[ia], tri[ib]; C = tri[3 - ia - ib]
    d = B - A; d = d / np.linalg.norm(d)
    n = np.array([-d[1], d[0]])
    if np.dot(C - A, n) < 0:
        n = -n
    return A, B, d, n


@register
class Folded(Mode):
    name = "folded"
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
        Param("separate", "bool", False, "Every face is its own panel (no folds): each triangle is cut alone and joined to its neighbours along every edge"),
        Param("strategy", "choice", "auto", "How panels grow: flat = flattest fold first; strip = long strips along the model's axis; area = big faces first; auto = try all and keep the fewest, most compact panels (≤ 800 faces)", choices=["auto", "flat", "strip", "area"], show_if=("separate", False)),
        Param("max_faces", "int", 0, "Max triangles per panel (0 = as many as fit the sheet without overlapping)", 0, 5000, 1, show_if=("separate", False)),
        Param("joint", "choice", "laced", JOINT_HELP, choices=JOINTS),
        Param("hole_d", "number", 2.5, "Hole diameter for rivet / laced / strip (mm); shrinks where the triangle is small", 0.5, 30, 0.1, unit="mm"),
        Param("inset", "number", 4.0, "Distance from the seam to the hole centres / slots / second bend (mm); shrinks where the triangle is small", 0.5, 100, 0.5, unit="mm"),
        Param("spacing", "number", 20.0, "Hole spacing along a seam (mm); laced makes ≥ 2 per edge, rivet ≥ 1", 2, 500, 1, unit="mm"),
        Param("tab_h", "number", 10.0, "Tab height for tab / multitab / diamond / gear / tongue / puzzle (mm)", 1, 100, 0.5, unit="mm"),
        Param("tab_angle", "number", 30, "Side angle of trapezoid tabs (deg)", 0, 80, 5, unit="deg"),
        Param("rib_w", "number", 12.0, "Rib joint: arm width above the panel and tab width through the slot (mm); shrinks where the triangle is small", 2, 100, 0.5, unit="mm"),
        Param("rib_thick", "number", 0.0, "Rib material thickness (mm) when the ribs are cut from a different sheet; 0 = same as the panels. Slots in the panels follow it", 0, 20, 0.1, unit="mm", show_if=("joint", "rib")),
        Param("perforate", "bool", False, "Fold lines as dashed perforation instead of a continuous score (thick material)"),
        Param("score_side", "choice", "inside", "The face of the sheet that is up on the cutter, and so carries the scores and "
              "seam numbers: inside = the net is mirrored, they end up inside the model and the outside stays one clean "
              "surface; outside = they show on the outside, as on a printed paper model", choices=["inside", "outside"]),
        Param("hinge", "number", 0.4, "3D printed panels (PLA, PETG): the skin left at every fold (mm). The panel prints at its "
              "full thickness with a V groove along each fold, cut to that fold's own angle: it folds to the model's shape and "
              "stops there, and with the plain `seam` joint the seam edges are mitred the same way, so the panels meet face to "
              "face for glue. Two layers (0.4 mm) is a good start; PETG bends, PLA is brittle and folds once. 0 = no groove", 0, 5, 0.05, unit="mm"),
        Param("hinge_w", "number", 0.4, "3D printed panels: width of the flat strip of skin at the bottom of each fold's groove (mm), "
              "the length that bends. Wider folds more easily and stops less sharply", 0, 5, 0.05, unit="mm", label="hinge width"),
        Param("hinge_stop", "number", 0.0, "3D printed panels: where each fold stops, in degrees past (+) or short of (−) the "
              "model's angle. 0 = the groove walls meet at the model's angle. Folds that go too far on your printer: set it "
              "below 0 for a tighter groove; folds that stop short: above 0", -20, 20, 0.5, unit="deg", label="fold stop"),
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
        # … and its glue tabs as flaps of the skin alone: a tab as thick as the sheet would fold into the panel it glues to
        self.thin_tabs = self.hinged and p["joint"] in THIN_TABS
        self.mitres = self.hinged and (p["joint"] == "seam" or self.thin_tabs)     # seam edges cut to half the bend, face to face
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
        self.mesh = mesh
        ctx.cover_r = t                                       # coverage: surface points within the sheet thickness of a panel
        frames, local, panels, seams = unfold(mesh, p["separate"], p["max_faces"], self.usable_sheet(p), p["strategy"])
        self.frames, self.local = frames, local
        convex = mesh.face_adjacency_convex
        styles = ("dashed", "dotted") if p["perforate"] else ("solid", "dashed")     # mountain, valley
        slices, owner = [], {}
        self.face_cuts = {}                                   # face → cuts inside it (collision checks)
        self.grooved = {}                                     # face → its grooved edges in the face's own frame, for the 3D view
        for i, pn in enumerate(panels):
            sl = Slice(f"P-{i + 1}", "F", frames[pn.faces[0]], t)
            sl.pn = pn
            sl.raw = as_multi(pn.union.buffer(0))
            for k in pn.folds:
                fa = list(mesh.faces[mesh.face_adjacency[k][0]])
                va, vb = mesh.face_adjacency_edges[k]
                f = mesh.face_adjacency[k][0]
                sl.lines.append((self.mv(convex[k], styles), LineString([pn.tri[f][fa.index(va)], pn.tri[f][fa.index(vb)]])))
                self.vee(sl, pn.tri[f][fa.index(va)], pn.tri[f][fa.index(vb)], k)
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
            cut = dict.fromkeys((0, 1), min(need, *(0.4 * s["h"] for s in all_sides[k])) if back else 0)   # never most of a face: a sliver of a triangle keeps its middle
            if through and outward:
                # the face with more room is cut back until it clears the other's inside face: t·sin(bend) up to a right
                # angle (its inside corner lands on that face), t·tan(bend / 2) past it; the other runs to the model's edge
                need = t * math.sin(bend) if bend <= math.pi / 2 else need
                i = int(all_sides[k][1]["h"] > all_sides[k][0]["h"])
                cut = {i: min(need, 0.4 * all_sides[k][i]["h"]), 1 - i: 0}
            left = need - max(cut.values())
            if give is not None and not mitred and left > give * t + 0.05:      # what is left presses into the other panel
                for s in all_sides[k]:
                    s["sl"].pressed.append(left)
            for i, s in enumerate(all_sides[k]):
                d = cut[i]
                if d:
                    far = s["d"] * (d * 4)                    # past both ends: the corner goes with the edge
                    whole = Polygon([s["A"] - far - s["n"] * 1e-3, s["B"] + far - s["n"] * 1e-3, s["B"] + far + s["n"] * d, s["A"] - far + s["n"] * d])
                    strip = whole.intersection(s["tri"])
                    # a flat face of several triangles: the ones that touch this edge only at its ends lose their tip too
                    for g in {int(g) for v in (va, vb) for g in mesh.vertex_faces[v] if g >= 0} - {fa, fb}:
                        if mesh.face_normals[g] @ mesh.face_normals[s["f"]] > 0.9999:
                            tip = self.across(whole, owner[s["f"]].pn, s["f"], owner[g].pn, g).intersection(Polygon(owner[g].pn.tri[g]))
                            if tip.area > 1e-6:
                                self.face_trims.setdefault(g, []).append(tip); self.back[g] = max(self.back[g], d)
                    self.face_trims.setdefault(s["f"], []).append(strip); self.back[s["f"]] = max(self.back[s["f"]], d)
                    s["back"] = d                            # holes, slots and numbers are measured from the new edge
        self.corners(owner)
        for sl in slices:
            trims = [g for f in sl.pn.faces for g in self.face_trims.get(f, ())]
            if trims:
                # opened by a hair: the tip of a sharp triangle between two cut-back edges is left as a thread of no width
                sl.raw = as_multi(sl.raw.difference(unary_union(trims)).buffer(-0.01, join_style="mitre").buffer(0.01, join_style="mitre"))
        self.windows(slices)
        extra = []
        for j, k in enumerate(seams, 1):
            sides = all_sides[k]
            phi = self.interior_angle(k)
            # a mitre: the half of a fold's groove that lies on each panel. Outward seams only: at an inward one the two
            # sheets move apart, and a mitre there would open a V on the outside and cut a glue tab off its panel
            if self.mitres and convex[k]:
                for s in sides:
                    self.vee(s["sl"], s["A"], s["B"], k, s["f"])
            extra += self.joint(j, k, sides, phi, convex[k])
        # additions (tabs) → raw; facets for the 3D view: the profile of every face in its own frame (+ folded tabs)
        for sl in slices:
            for what, js in sl.skipped.items():
                ids = ", ".join(map(str, sorted(set(js))[:12])) + (" …" if len(set(js)) > 12 else "")
                if what == "seam number":
                    sl.warnings.append(f"{len(set(js))} seam number(s) left off — no room beside the edge for a legible one (seams {ids}): "
                                       f"the other side of each seam still carries it; a smaller font or a bigger facet size gives them room")
                    continue
                sl.warnings.append(f"{len(set(js))} seam(s) without a {what} — no room inside the triangle even after shrinking the joint (seams {ids}): "
                                   f"use fewer triangles (`simplify`), a bigger model, or smaller hole_d / inset / rib_w")
            if sl.pressed:
                kind = p.get("material_kind") or p.get("material")
                sl.warnings.append(f"{len(sl.pressed)} seam edge(s) press up to {max(sl.pressed):.1f} mm into the next panel, and {t:g} mm {kind} "
                                   f"gives {give * t:.1f} mm: the panels will not close there. "
                                   + ("Use a joint with no tab on the edge (seam, rivet, laced, strip, rib) with `edge fit` inner, so the edge is cut back"
                                      if not back else "The faces there are too small to cut back that far: use a thinner sheet or a bigger facet size"))
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
                flip = lambda g: affinity.scale(g, -1, 1, origin=(0, 0))
                sl.raw = as_multi(flip(sl.raw)); sl.cuts = [flip(c) for c in sl.cuts]
                sl.lines = [(s, flip(ln)) for s, ln in sl.lines]
                sl.marks = [(-m[0], m[1], m[2], -mark_rot(m)) for m in sl.marks]
                sl.vees = [[-v[0], v[1], -v[2], *v[3:]] for v in sl.vees]
                sl.thin = [flip(g) for g in sl.thin]
        # the sheet's outer face lies on the model's surface and its thickness goes inwards, so the outside is one
        # surface; centred on the surface, every fold left a notch on the outside and the model grew by half a sheet
        for sl in slices + extra:
            if sl.facets:
                sl.facets = [(self.sunk(M), g) for M, g in sl.facets]
        n_panels = len(slices)
        if not p["separate"] and n_panels > 0.6 * len(mesh.faces):
            ctx.errors.append(f"unfolding gave {n_panels} panels for {len(mesh.faces)} faces — use a bigger facet size or enlarge the sheet")
        if not self.check_folds(ctx, panels, seams):
            self.check_closing(slices)
        ctx.notes_extra = f"unfolded {len(mesh.faces)} triangles into {n_panels} panel(s), {len(seams)} seams"
        return slices + extra

    def check_closing(self, slices):
        """A sheet of thickness t folded by θ gives up t·tan(θ/2) of its closing face on each side of the fold (the inside
        of a mountain fold, the outside of a valley fold). A triangle keeps material on that face while Σ dᵢ·Lᵢ ≤ 2·area
        over its fold edges (a point's distance to edge i is 2·area·λᵢ/Lᵢ). Past that the folds around a face meet: a
        sheet thicker than the curve's radius, or faces too small for the sheet, cannot be folded to the model."""
        m, t = self.mesh, self.t
        L = np.linalg.norm(np.diff(m.vertices[m.face_adjacency_edges], axis=1)[:, 0], axis=1)
        bend = np.minimum(m.face_adjacency_angles, math.pi * 0.999)
        give = t * np.tan(bend / 2) * L
        if self.hinged:                                       # a printed groove: as deep as the sheet less its skin, plus half its flat bottom
            give = ((t - self.p["hinge"]) * np.tan(bend / 2) + self.p["hinge_w"] / 2 * (bend > math.radians(1))) * L
        for sl in slices:
            k = np.asarray(sl.pn.folds, int)
            if not len(k):
                continue
            side = m.face_adjacency_convex[k].astype(int)     # the face that closes: 1 = the inside (mountain), 0 = the outside
            need = np.zeros((2, len(m.faces)))
            for f in m.face_adjacency[k].T:
                np.add.at(need, (side, f), give[k])
            stuck = (need[side[:, None], m.face_adjacency[k]] > 2 * m.area_faces[m.face_adjacency[k]]).any(1)
            if stuck.any():
                sl.warnings.append(f"{int(stuck.sum())} fold(s) cannot close in {t:g} mm sheet: folding takes t × tan(bend / 2) "
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
        if self.hinged:
            bend = np.minimum(m.face_adjacency_angles, math.pi * 0.999)
            give = ((self.t - self.p["hinge"]) * np.tan(bend / 2) + self.p["hinge_w"] / 2) * (bend > math.radians(1))
            for f in m.face_adjacency.T:
                np.maximum.at(room, f, give)
        for sl in slices:
            for f in sl.pn.faces:
                tri = Polygon(sl.pn.tri[f]); r = 2 * tri.area / tri.length            # the inscribed circle's radius
                h = 2 * tri.area / max(np.linalg.norm(np.diff(np.vstack([sl.pn.tri[f], sl.pn.tri[f][:1]]), axis=0), axis=1))   # the least height
                joint = {"rivet": holes, "laced": holes, "strip": holes, "rib": slot}.get(self.p["joint"], lambda h: 0)(h)   # as fit_sizes shrinks them
                frame = max((1 - share) * r, 1.25 * self.p["min_feature"] + room[f] + joint)      # a quarter over: the thin-spot check measures to the hair
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

    def vee(self, sl, a, b, k, f=None):
        """The V groove a printed panel gets along edge a→b (a fold, or a seam edge to mitre) of adjacency k: opened to
        the edge's bend, on the face that closes (the inside of a convex edge), down to the hinge skin. An edge
        between faces in one plane bends nothing and gets none."""
        bend = float(self.mesh.face_adjacency_angles[k])
        if not self.hinged or bend < math.radians(1):
            return
        h, g = self.p["hinge"], self.p["hinge_w"]
        # the walls turn about the skin and meet when each has turned atan(half the opening / the depth): the opening
        # is set by the bend alone. The flat bottom is inside it, not added to it (added, a 90° fold closed at 97°)
        stop = min(max(bend + math.radians(self.p["hinge_stop"]), 0), math.pi * 0.999)
        wide = max(g / 2, (self.t - h) * math.tan(stop / 2))
        top = bool(self.mesh.face_adjacency_convex[k]) == self.inside       # the closing face is the one up on the bed
        sl.vees.append([*map(float, a), *map(float, b), g, h, wide, top])
        for face in ([f] if f is not None else self.mesh.face_adjacency[k]):      # a fold grooves both of its faces
            fl = list(self.mesh.faces[face]); va, vb = self.mesh.face_adjacency_edges[k]
            la, lb = self.local[face][fl.index(va)], self.local[face][fl.index(vb)]
            self.grooved.setdefault(int(face), []).append([*(round(float(x), 4) for x in (*la, *lb)), round(wide, 4), 1 if self.mesh.face_adjacency_convex[k] else -1])

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
        M = M.copy(); M[:3, 3] -= M[:3, 2] * self.t / 2
        return M

    def mv(self, convex, styles=("solid", "dashed")):
        """Mountain (styles[0]) or valley line for an edge, seen from the face up on the cutter: a convex edge folds as a
        mountain seen from outside and as a valley seen from inside."""
        return styles[0] if bool(convex) != self.inside else styles[1]

    def check_folds(self, ctx, panels, seams):
        """A fold line in a panel, or a joint whose tab or strip bends over the seam, needs a sheet that folds: 3 mm
        plywood cracks along the score where 3 mm cardboard folds. Every face its own panel, joined by ribs, folds
        nothing."""
        p = self.p; kind = p.get("material_kind") or p.get("material"); most = FOLDS.get(kind)
        if self.hinged and (p["joint"] not in FOLDED_JOINTS or self.thin_tabs):      # printed with a groove at every fold: the skin is what folds
            return False
        folds = sum(len(pn.folds) for pn in panels) + (len(seams) if p["joint"] in FOLDED_JOINTS else 0)
        if most is None or not folds or self.t <= most:
            return False
        why = "it does not fold, it cracks along the line" if most == 0 else f"it folds along a score up to about {most:g} mm"
        msg = (f"{folds} fold(s) in {self.t:g} mm {kind}: {why}. Cut every face as its own panel (separate) and join them with "
               f"a joint that needs no fold (rib, rivet or laced), or use a thinner or foldable material"
               + (". Printed, the plain `seam` joint with a `hinge` skin folds along a groove at every fold" if p["printed"] else ""))
        ctx.errors.append(msg)
        fix = {"separate": True, "joint": "rib"}
        if (target_faces(ctx.mesh, p["facet"]) or len(ctx.mesh.faces)) > MAX_PANELS:    # each face is a part now: as few as build cuts
            fix["facet"] = math.ceil(math.sqrt(ctx.mesh.area / (0.433 * MAX_PANELS)))
        ctx.fixes = [{"error": msg, "options": [{"title": "every face its own panel, joined by ribs", "set": fix,
                                                 "note": "rigid panels, each rib cut at its seam's angle and slotted in from the back"}]}]
        return True

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def usable_sheet(p):
        """Panel size limit for the unfolder: the sheet minus margins, minus room for glue tabs that grow the outline."""
        room = p["tab_h"] if p["joint"] in ("tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle") else 0
        return (p["sheet"][0] - 2 * p["sheet_margin"] - 2 * room, p["sheet"][1] - 2 * p["sheet_margin"] - 2 * room)

    def side(self, sl, f, va, vb):
        """Edge va→vb of face f in panel-layout coords and in the face's own frame (for the 3D parts)."""
        fl = list(self.mesh.faces[f]); ia, ib = fl.index(va), fl.index(vb)
        A, B, d, n = edge_geom(sl.pn.tri[f], ia, ib)
        la, lb, ld, ln = edge_geom(self.local[f], ia, ib)
        tri = Polygon(sl.pn.tri[f]); L = float(np.linalg.norm(B - A))
        return dict(sl=sl, f=f, A=A, B=B, d=d, n=n, L=L, tri=tri, h=2 * tri.area / L,      # h = height of the triangle over this edge
                    lmid=(la + lb) / 2, ld=ld, ln=ln)

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
        p, sl = self.p, s["sl"]
        text = str(j); A, d, n, L = s["A"], s["d"], s["n"], s["L"]
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
                c = A + d * (along * L) + n * (deep + h / 2 + s.get("back", 0))
                b = mark_box(float(c[0]), float(c[1]), text, p["font"], rot)
                if sl.room.covers(b) and free(b):
                    sl.marks.append((float(c[0]), float(c[1]), text, round(rot, 2)))
                    return
        sl.skipped.setdefault("seam number", []).append(j)

    def fit_sizes(self, sides):
        """Joint sizes that fit both triangles: holes at ≤ 20 % of the triangle height, ≤ 30 % wide; rib slots start at
        ≤ 10 % and reach ≤ 32 % so that three ribs (one per edge) never meet in the middle of a triangle."""
        p = self.p; h = min(s["h"] for s in sides)
        if p["joint"] == "rib":
            inset, hole, rib = min(p["inset"], 0.1 * h), p["hole_d"], min(p["rib_w"], max(0.22 * h, 2 * self.t))
        else:
            inset, hole, rib = min(p["inset"], 0.2 * h), min(p["hole_d"], 0.3 * h), p["rib_w"]
        if inset < p["inset"] - 1e-9 or hole < p["hole_d"] - 1e-9 or (p["joint"] == "rib" and rib < p["rib_w"] - 1e-9):
            for s in sides:
                s["sl"].reduced += 1
        return inset, hole, rib

    def collides(self, s, geom):
        return any(geom.intersects(c) for c in self.face_cuts.get(s["f"], ()))

    def add_cut(self, s, geom):
        s["sl"].cuts.append(geom); self.face_cuts.setdefault(s["f"], []).append(geom)

    def cut_if_fits(self, s, geom, j, what):
        if s["tri"].buffer(-self.p["min_feature"]).contains(geom) and not self.collides(s, geom):
            self.add_cut(s, geom); return True
        s["sl"].skipped.setdefault(what, []).append(j)
        return False

    def folded_tab(self, a, b, poly):
        """A tab drawn outside edge A→B of face a, shown in 3D folded flat against the inside of face b."""
        A, d, out, L = a["A"], a["d"], -a["n"], a["L"]
        pts = [b["lmid"] + (float(np.dot(P - A, d)) / L - 0.5) * L * b["ld"] + float(np.dot(P - A, out)) * b["ln"] for P in np.asarray(poly.exterior.coords)]
        M = self.frames[b["f"]].copy(); h = self.p["hinge"]
        if self.thin_tabs:                                    # a flap of the skin, folded round the edge onto the outside of the mating panel
            M[:3, 3] += M[:3, 2] * (h / 2 + self.t / 2)         # (every facet is then sunk half a sheet, see build)
        else:
            M[:3, 3] -= M[:3, 2] * self.t                      # just inside the mating panel
        b["sl"].tab_facets.append((M, as_multi(Polygon(pts)))); b["sl"].tab_of.append(b["f"]); b["sl"].tab_t.append(h if self.thin_tabs else None)

    # ---------------------------------------------------------------- joints
    def joint(self, j, k, sides, phi, convex):
        p = self.p; jt = p["joint"]
        if jt in ("rivet", "laced", "strip"):
            return self.holes(j, sides, phi, convex)
        if jt == "loops":
            return self.loops(j, sides)
        if jt == "rib":
            return self.rib(j, k, sides, phi)
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
        trims = self.face_trims.get(s["f"])                   # the face as it is cut: less its cut-back seam edges
        tri_in = (s["tri"].difference(unary_union(trims)) if trims else s["tri"]).buffer(-r)
        if tri_in.is_empty:
            return None
        line = LineString([s["A"] + s["n"] * inset, s["B"] + s["n"] * inset])
        hit = line.intersection(tri_in)
        segs = [g for g in shapely.get_parts(hit) if g.geom_type == "LineString" and not g.is_empty]
        if not segs:
            return None
        seg = max(segs, key=lambda g: g.length); c = np.asarray(seg.coords)
        return sorted(float(np.dot(c[i] - line.coords[0], s["d"])) / s["L"] for i in (0, -1))

    def holes(self, j, sides, phi, convex):
        """Holes at the same parameters on both panels, spread over the interval that fits both triangles."""
        p = self.p; L = sides[0]["L"]; want = 2 if p["joint"] != "rivet" else 1
        inset, hole_d, _ = self.fit_sizes(sides)
        ranges = [self.hole_range(s, inset + s.get("back", 0), hole_d) for s in sides]
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
            circles = [circle(s["A"] + (s["B"] - s["A"]) * q + s["n"] * (inset + s.get("back", 0)), hole_d) for s in sides]
            if any(self.collides(s, c) for s, c in zip(sides, circles)):
                continue
            for s, c in zip(sides, circles):
                self.add_cut(s, c)
            placed.append(q)
        if len(placed) < want:
            for s in sides:
                s["sl"].skipped.setdefault("hole", []).append(j)
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
            d, n, m = s["ld"], s["ln"], s["lmid"]
            g = affinity.affine_transform(half, [d[0], sgn * n[0], d[1], sgn * n[1], m[0], m[1]])
            M = self.frames[s["f"]].copy(); M[:3, 3] -= M[:3, 2] * self.t     # strips sit inside the panels
            sl.facets.append((M, as_multi(g)))
        return [sl]

    def loops(self, j, sides):
        """Eyelet loops alternating along the seam: side A gets the even positions, side B the odd ones, so the loops
        interleave like hinge knuckles and one lace runs through all of them. Loops stay in their panel's plane."""
        p = self.p; L = sides[0]["L"]
        _, hole_d, _ = self.fit_sizes(sides)
        loop_d = 2 * hole_d + 2 * max(hole_d * 0.8, p["min_feature"])
        n = max(2, int(L // (loop_d * 1.15)))
        for i in range(n):
            q = (i + 0.5) / n; s = sides[i % 2]
            c = s["A"] + (s["B"] - s["A"]) * q - s["n"] * (loop_d * 0.5 - 0.6)      # centre just outside the edge
            loop = unary_union([circle(c, loop_d), Polygon([s["A"] + (s["B"] - s["A"]) * q - s["d"] * loop_d * 0.45, s["A"] + (s["B"] - s["A"]) * q + s["d"] * loop_d * 0.45,
                                                            c + s["d"] * loop_d * 0.45, c - s["d"] * loop_d * 0.45])])
            s["sl"].additions.append(loop)
            hole = circle(c, hole_d)
            s["sl"].cuts.append(hole)
            s["sl"].tab_facets.append((self.frames[s["f"]], as_multi(s["sl"].pn.to_local(s["f"], loop.difference(hole))))); s["sl"].tab_of.append(s["f"]); s["sl"].tab_t.append(None)
        for s in sides:
            self.mark(s, j, p["font"] * 0.5)
        return []

    def rib(self, j, k, sides, phi):
        p = self.p; t = self.t; tr = p["rib_thick"] or t
        inset, _, w = self.fit_sizes(sides); tab = w; inset += sides[0].get("back", 0)
        # slots in both panels, perpendicular to the seam (never across a fold or into another cut)
        slots = [rect_along(s["A"] + (s["B"] - s["A"]) / 2 + s["n"] * inset, s["A"] + (s["B"] - s["A"]) / 2 + s["n"] * (inset + tab), tr + p["slot_offset"]) for s in sides]   # inset holds the cut-back: the same on both sides for a rib
        if not all(s["tri"].buffer(-p["min_feature"] / 2).contains(sl_) and not self.collides(s, sl_) for s, sl_ in zip(sides, slots)):
            for s in sides:
                s["sl"].skipped.setdefault("rib slot", []).append(j)
                self.mark(s, j, p["font"] * 0.5)
            return []
        for s, sl_ in zip(sides, slots):
            self.add_cut(s, sl_); self.mark(s, j, inset - s.get("back", 0) + tab + p["font"] * 0.45)   # mark() adds the cut-back itself
        # rib frame: origin = edge midpoint, x = into panel A along its surface, y = into the model (−normal A), z ∥ edge
        m = self.mesh; fa, fb = (int(x) for x in m.face_adjacency[k]); va, vb = m.face_adjacency_edges[k]
        E = m.vertices[[va, vb]].mean(0); e = m.vertices[vb] - m.vertices[va]; e /= np.linalg.norm(e)
        na, nb = m.face_normals[fa], m.face_normals[fb]

        def inward(f):
            c = m.triangles_center[f] - E; c -= np.dot(c, e) * e; return c / np.linalg.norm(c)
        dA, dB = inward(fa), inward(fb)
        # the rib is drawn about where the panels' mid-planes meet; they lie half a sheet inside the surface (see sunk)
        M = frame_xy(E - t / (2 * max(1 + na @ nb, 0.1)) * (na + nb), dA, -na)
        dB2 = np.array([dB @ dA, dB @ -na]); nB2 = np.array([-nb @ dA, nb @ na])
        L = inset + tab + t * 2

        def arm(d, n):
            body = Polygon([d * 0 + n * t / 2, d * L + n * t / 2, d * L + n * (t / 2 + w), n * (t / 2 + w)])
            tabp = Polygon([d * inset - n * (t / 2 + 0.5), d * (inset + tab) - n * (t / 2 + 0.5), d * (inset + tab) + n * (t / 2 + 0.1), d * inset + n * (t / 2 + 0.1)])
            return unary_union([body, tabp])
        nA2 = np.array([0.0, 1.0]); dA2 = np.array([1.0, 0.0])
        corner = Polygon([nA2 * t / 2, nA2 * (t / 2 + w), nB2 * (t / 2 + w), nB2 * t / 2])
        rib = unary_union([arm(dA2, nA2), arm(dB2, nB2), corner]).buffer(0)
        sl = Slice(f"R-{j}", "J", M, tr, note=f"{phi:.0f}°")
        sl.raw = as_multi(rib)
        sl.marks.append((float(L * 0.5), float(t / 2 + w * 0.5), str(j)))
        return [sl]

    def tabs(self, j, sides, jt, convex, swapped=False):
        """Tabs on side a of seam j, glued to side b. A tab that would land on its own panel (a concave net) is tried
        from the other side first — the seam then has its tab on panel b, folded onto a — and only when neither
        side has room is the seam left plain, with a warning."""
        p = self.p; t = self.t; a, b = sides
        inset, _, _ = self.fit_sizes(sides)
        L = a["L"]; h = min(p["tab_h"], L * 0.6, b["h"] * 0.6); A, d, n = a["A"], a["d"], a["n"]
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
                slot = rect_along(b["A"] + (b["B"] - b["A"]) / 2 + b["n"] * inset - b["d"] * width / 2,
                                  b["A"] + (b["B"] - b["A"]) / 2 + b["n"] * inset + b["d"] * width / 2, t + p["slot_offset"])
                self.cut_if_fits(b, slot, j, "tongue slot")
        elif jt == "puzzle":
            neck = h * 0.55; head = h * 0.9
            mid = A + d * L / 2
            body = Polygon([mid - d * neck / 2, mid + d * neck / 2, mid + d * neck / 2 + out * h * 0.5, mid - d * neck / 2 + out * h * 0.5])
            polys.append(unary_union([body, circle(mid + out * (h * 0.5 + head * 0.3), head)]))
            bm = b["A"] + (b["B"] - b["A"]) / 2 + b["n"] * inset
            hole = unary_union([circle(bm + b["n"] * head * 0.3, head + p["slot_offset"]),
                                rect_along(bm - b["n"] * inset * 0.2, bm + b["n"] * head * 0.3, neck + p["slot_offset"])])
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
        sl = a["sl"]
        if sl.taken is None or sl.taken_tabs != len(sl.additions):          # the panel with the tabs it has so far
            sl.taken = unary_union([sl.raw, *sl.additions]); sl.taken_tabs = len(sl.additions)
        base = LineString([A, A + d * L]).buffer(0.6)
        for poly in polys:
            if poly.intersection(sl.raw).area > 0.02 * poly.area or poly.buffer(0.3).intersection(sl.taken).difference(base).area > 0.05:
                if not swapped:
                    return self.tabs(j, [b, a], jt, convex, swapped=True)
                a["sl"].warnings.append(f"seam {j}: tab would overlap or touch the panel on either side — reduced to a plain seam (lower tab_h)")
                break
        else:
            a["sl"].additions += polys
            if self.thin_tabs:
                a["sl"].thin += polys; a["sl"].thin_t = self.p["hinge"]
            # the hinge is scored across each tab's base, not along the whole seam edge: the rest of that edge is a cut,
            # and a score under a cut is wasted on the laser and invisible on the part
            a["sl"].lines += [(self.mv(convex), hl) for hl in hinges]
            a["sl"].lines += [(self.mv(False), bl) for bl in bends]
            for poly in polys:
                self.folded_tab(a, b, poly)
        self.mark(a, j, p["font"] * 0.5, on_tab=bool(polys) and polys[0] in a["sl"].additions)
        self.mark(b, j, (inset + t + p["font"] * 0.6) if jt in ("tongue", "puzzle") else p["font"] * 0.5)
