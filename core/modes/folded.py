"""Folded Panels: unfold the (simplified) surface into flat panels with fold lines; join the seams with tabs,
holes (rivet / laced), connecting strips, or slotted angle ribs. Paper, card, cardboard, sheet metal.

Joint sizes adapt to the triangle they sit in (a hole or slot never crosses a fold or the outline); what had to
shrink is reported per panel. Tabs are shown in the 3D view folded onto the panel they glue to."""
from __future__ import annotations
import math
import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree
from . import Mode, Param, register
from ..model import Slice
from ..geometry import as_multi, circle, rect_along, frame_xy
from ..unfold import unfold

JOINTS = ["seam", "tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle", "rivet", "laced", "loops", "strip", "rib"]
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
    legend = ("P-7 = the 7th panel · the number engraved beside a seam is the seam number, and the panel carrying the same "
              "number on one of its edges is the one that edge folds to · S-n = the connecting strip for seam n, "
              "R-n = the angle rib for seam n · on the score layer a solid line is a mountain fold, a dashed line a valley fold")
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
        Param("edge_labels", "bool", True, "Engrave the seam number beside every joint on both panels, so mating edges can be found"),
    ]
    hidden_common = ("notch_ratio", "notch_factor", "notch_angle", "relief", "tool_d", "margin", "tab", "offset", "tilt", "roll", "thick", "center", "skip")

    def build(self, ctx):
        p = ctx.p; t = p["thickness"]; self.p = p; self.t = t
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
        for i, pn in enumerate(panels):
            sl = Slice(f"P-{i + 1}", "F", frames[pn.faces[0]], t)
            sl.pn = pn
            sl.raw = as_multi(pn.union.buffer(0))
            sl.additions, sl.skipped, sl.reduced, sl.tab_facets = [], {}, 0, []
            for k in pn.folds:
                fa = list(mesh.faces[mesh.face_adjacency[k][0]])
                va, vb = mesh.face_adjacency_edges[k]
                f = mesh.face_adjacency[k][0]
                sl.lines.append((styles[0] if convex[k] else styles[1], LineString([pn.tri[f][fa.index(va)], pn.tri[f][fa.index(vb)]])))
            slices.append(sl)
            for f in pn.faces:
                owner[f] = sl
        extra = []
        for j, k in enumerate(seams, 1):
            fa, fb = (int(x) for x in mesh.face_adjacency[k])
            va, vb = mesh.face_adjacency_edges[k]
            sides = [self.side(owner[f], f, va, vb) for f in (fa, fb)]
            phi = self.interior_angle(k)
            extra += self.joint(j, k, sides, phi, convex[k])
        # additions (tabs) → raw; facets for the 3D view: the profile of every face in its own frame (+ folded tabs)
        for sl in slices:
            for what, js in sl.skipped.items():
                ids = ", ".join(map(str, sorted(set(js))[:12])) + (" …" if len(set(js)) > 12 else "")
                sl.warnings.append(f"{len(set(js))} seam(s) without a {what} — no room inside the triangle even after shrinking the joint (seams {ids}): "
                                   f"use fewer triangles (`simplify`), a bigger model, or smaller hole_d / inset / rib_w")
            if sl.reduced:
                sl.warnings.append(f"{sl.reduced} joint(s) made smaller than asked to fit their triangle — fine for paper, check strength for metal")
            if sl.additions:
                sl.raw = as_multi(unary_union([sl.raw, *sl.additions]).buffer(0))
            tree = STRtree(sl.cuts) if sl.cuts else None
            sl.facets = []
            for f in sl.pn.faces:
                tri = Polygon(sl.pn.tri[f])
                near = [sl.cuts[i] for i in tree.query(tri)] if tree is not None else []
                g = as_multi(sl.pn.to_local(f, tri.difference(unary_union(near)) if near else tri))
                if not g.is_empty:
                    sl.facets.append((frames[f], g))
            sl.facets += sl.tab_facets
        n_panels = len(slices)
        if not p["separate"] and n_panels > 0.6 * len(mesh.faces):
            ctx.errors.append(f"unfolding gave {n_panels} panels for {len(mesh.faces)} faces — use a bigger facet size or enlarge the sheet")
        ctx.notes_extra = f"unfolded {len(mesh.faces)} triangles into {n_panels} panel(s), {len(seams)} seams"
        return slices + extra

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

    def mark(self, s, j, depth):
        if self.p["edge_labels"]:
            m = (s["A"] + s["B"]) / 2 + s["n"] * min(depth, s["h"] * 0.5)
            s["sl"].marks.append((float(m[0]), float(m[1]), str(j)))

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
        if s["tri"].buffer(-self.p["min_feature"] / 2).contains(geom) and not self.collides(s, geom):
            self.add_cut(s, geom); return True
        s["sl"].skipped.setdefault(what, []).append(j)
        return False

    def folded_tab(self, a, b, poly):
        """A tab drawn outside edge A→B of face a, shown in 3D folded flat against the inside of face b."""
        A, d, out, L = a["A"], a["d"], -a["n"], a["L"]
        pts = [b["lmid"] + (float(np.dot(P - A, d)) / L - 0.5) * L * b["ld"] + float(np.dot(P - A, out)) * b["ln"] for P in np.asarray(poly.exterior.coords)]
        M = self.frames[b["f"]].copy(); M[:3, 3] -= M[:3, 2] * self.t          # just inside the mating panel
        b["sl"].tab_facets.append((M, as_multi(Polygon(pts))))

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
        other edges (hole radius + half the min feature)."""
        r = hole_d / 2 + self.p["min_feature"] / 2
        tri_in = s["tri"].buffer(-r)
        if tri_in.is_empty:
            return None
        line = LineString([s["A"] + s["n"] * inset, s["B"] + s["n"] * inset])
        hit = line.intersection(tri_in)
        segs = [g for g in getattr(hit, "geoms", [hit]) if g.geom_type == "LineString" and not g.is_empty]
        if not segs:
            return None
        seg = max(segs, key=lambda g: g.length); c = np.asarray(seg.coords)
        return sorted(float(np.dot(c[i] - line.coords[0], s["d"])) / s["L"] for i in (0, -1))

    def holes(self, j, sides, phi, convex):
        """Holes at the same parameters on both panels, spread over the interval that fits both triangles."""
        p = self.p; L = sides[0]["L"]; want = 2 if p["joint"] != "rivet" else 1
        inset, hole_d, _ = self.fit_sizes(sides)
        ranges = [self.hole_range(s, inset, hole_d) for s in sides]
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
            circles = [circle(s["A"] + (s["B"] - s["A"]) * q + s["n"] * inset, hole_d) for s in sides]
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
        wall = hole_d; Wd = 2 * inset + hole_d + 2 * wall; Ls = L
        strip = LineString([(-Ls / 2 + Wd / 2, 0), (Ls / 2 - Wd / 2, 0)]).buffer(Wd / 2)
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
            s["sl"].tab_facets.append((self.frames[s["f"]], as_multi(s["sl"].pn.to_local(s["f"], loop.difference(hole)))))
        for s in sides:
            self.mark(s, j, p["font"] * 0.5)
        return []

    def rib(self, j, k, sides, phi):
        p = self.p; t = self.t; tr = p["rib_thick"] or t
        inset, _, w = self.fit_sizes(sides); tab = w
        # slots in both panels, perpendicular to the seam (never across a fold or into another cut)
        slots = [rect_along(s["A"] + (s["B"] - s["A"]) / 2 + s["n"] * inset, s["A"] + (s["B"] - s["A"]) / 2 + s["n"] * (inset + tab), tr + p["slot_offset"]) for s in sides]
        if not all(s["tri"].buffer(-p["min_feature"] / 2).contains(sl_) and not self.collides(s, sl_) for s, sl_ in zip(sides, slots)):
            for s in sides:
                s["sl"].skipped.setdefault("rib slot", []).append(j)
                self.mark(s, j, p["font"] * 0.5)
            return []
        for s, sl_ in zip(sides, slots):
            self.add_cut(s, sl_); self.mark(s, j, inset + tab + p["font"] * 0.45)
        # rib frame: origin = edge midpoint, x = into panel A along its surface, y = into the model (−normal A), z ∥ edge
        m = self.mesh; fa, fb = (int(x) for x in m.face_adjacency[k]); va, vb = m.face_adjacency_edges[k]
        E = m.vertices[[va, vb]].mean(0); e = m.vertices[vb] - m.vertices[va]; e /= np.linalg.norm(e)
        na, nb = m.face_normals[fa], m.face_normals[fb]

        def inward(f):
            c = m.triangles_center[f] - E; c -= np.dot(c, e) * e; return c / np.linalg.norm(c)
        dA, dB = inward(fa), inward(fb)
        M = frame_xy(E, dA, -na)
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

    def tabs(self, j, sides, jt, convex):
        p = self.p; t = self.t; a, b = sides
        inset, _, _ = self.fit_sizes(sides)
        L = a["L"]; h = min(p["tab_h"], L * 0.6, b["h"] * 0.6); A, B, d, n = a["A"], a["B"], a["d"], a["n"]
        out = -n                                        # tabs protrude away from the panel
        tan = math.tan(math.radians(p["tab_angle"]))

        def trap(s0, s1, height, top_inset):
            x0, x1 = A + d * (s0 * L), A + d * (s1 * L)
            ti = min(top_inset, (s1 - s0) * L * 0.4)
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
                else:                polys.append(Polygon([A + d * (c - hw) * L, A + d * (c + hw) * L, A + d * c * L + out * h]))   # diamond / ticked
        # a tab may not land on the panel itself (concave layouts) — then it is a plain seam
        for poly in polys:
            if poly.intersection(a["sl"].raw).area > 0.02 * poly.area:
                a["sl"].warnings.append(f"seam {j}: tab would overlap the panel — reduced to a plain seam (lower tab_h)")
                break
        else:
            a["sl"].additions += polys
            a["sl"].lines.append(("solid" if convex else "dashed", LineString([A, B])))
            a["sl"].lines += [("dashed", bl) for bl in bends]
            for poly in polys:
                self.folded_tab(a, b, poly)
        self.mark(a, j, p["font"] * 0.5)
        self.mark(b, j, (inset + t + p["font"] * 0.6) if jt in ("tongue", "puzzle") else p["font"] * 0.5)
