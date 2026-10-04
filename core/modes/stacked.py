"""Stacked: parallel sections, touching or spaced apart, connected by dowel rods, flat pegs, or tabbed spacers."""
import math

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from . import Mode, Param, register
from ..model import Slice
from ..geometry import dowel, dowel_leverage, hole_reach, LEVERAGE_OK, rect_along, as_multi, section_polygons, frame_xy, to_local

CONNECT_HELP = ("dowel = round/square rods through holes (drawn in the 3D view), the default: glue alone leaves every layer free to "
                "slide while it dries, and two dowels through a piece hold it where it belongs · tab = flat pieces cut from the sheet: "
                "a peg between touching slices, or a spacer (body + tabs into slots) when `space` > 0 — keeps the distance and the "
                "orientation · none = glue only, for a stack you are happy to line up by eye")

MIN_DOWEL = 2.0            # below this a dowel is not worth cutting for: too small to buy, too weak to locate anything


@register
class Stacked(Mode):
    name = "stacked"
    title = "Stacked Slices"
    description = ("Parallel cross-sections, touching or with an empty space between them, glued or connected by dowels, pegs or "
                   "tabbed spacers. `surface` makes the outline follow the surface through the slice (Slicer's 3D Slices).")
    params = [
        Param("axis", "choice", "z", "Slice direction (normal of the slices)", choices=["x", "y", "z"]),
        Param("distribution", "choice", "distance", "distance = one slice every thickness + space; count = N evenly spread slices", choices=["distance", "count"]),
        Param("count", "int", 10, "Number of slices", 1, 500, 1, show_if=("distribution", "count")),
        Param("space", "number", 0.0, "Empty space between consecutive slices (mm); spacers keep it", 0, 500, 0.5, unit="mm"),
        Param("surface", "choice", "mid", "Outline of each slice: mid = section at the middle; outer = union of the sections through the slice thickness (sand down to shape, Slicer's 3D Slices); inner = intersection (never protrudes)", choices=["mid", "outer", "inner"]),
        Param("connect", "choice", "dowel", CONNECT_HELP, choices=["none", "dowel", "tab"]),
        Param("dowel_d", "number", 6.0, "Dowel diameter / peg & spacer width (mm)", 0.5, 100, 0.5, unit="mm", show_if=("connect", ["dowel", "tab"])),
        Param("dowel_shape", "choice", "round", "Dowel hole shape (round, square, pencil = hexagon, cross, horizontal / vertical slot)", choices=["round", "square", "pencil", "cross", "hslot", "vslot"], show_if=("connect", "dowel")),
        Param("placement", "choice", "aligned", "aligned = the same points through the whole stack, so each dowel is one straight rod (every island that persists gets its own); to move one or add your own, alt-click a slice in the 3D view or type it under dowels · random = new points for every pair of slices, spread as far apart as that pair allows, so no two layers share a hole · lines = straight dowels you draw yourself, start → end, holes wherever they cross between two slices", choices=["aligned", "random", "lines"], show_if=("connect", ["dowel", "tab"])),
        Param("n_points", "int", 2, "Connection points per pair of slices (per island)", 1, 20, 1, show_if=("placement", ["aligned", "random"])),
        Param("dowels", "points", [], "Your own dowels, on top of the automatic ones (n_points), each straight through every layer it fits (x, y in the slice plane, 0, 0 = the middle of the model). Alt-click a slice in the 3D view to add one there or remove the one you click; type its x, y here to move it", unit="mm", show_if=("placement", "aligned")),
        Param("lines", "lines3", [], "Each line is one straight dowel through the stack: a start and an end point in "
              "the model's own x, y, z (0, 0, 0 is the middle of the model). Every pair of slices the line passes through "
              "gets a hole where it crosses between them, so a slanted line steps across the layers. + line draws one up "
              "the middle to start from, alt-click the model for one up through that point (again on it to remove it); "
              "two lines hold every layer, one lets it turn", unit="mm", show_if=("placement", "lines")),
        Param("spacer_dir", "choice", "alternate", "Orientation of pegs / spacers in the slice plane", choices=["x", "y", "alternate"], show_if=("connect", "tab")),
    ]
    hidden_common = ("notch_ratio", "notch_factor", "notch_angle")

    legend = ("Z-3 = the 3rd slice along the stacking axis, counted from the low end (X- or Y- when you stack along those) · "
              "P-n = an alignment peg or a spacer, which goes between two slices")

    def build(self, ctx):
        p = ctx.p
        ax = "xyz".index(p["axis"]); normal = ctx.ax[ax]; up = ctx.ax[(ax + 2) % 3]
        length = ctx.ext[ax]; t = p["thickness"]; gap = p["space"]
        if p["distribution"] == "count":
            labels = [f"{p['axis'].upper()}-{i + 1}" for i in range(p["count"])]
            th = [ctx.thickness_of(l) for l in labels]; pos = ctx.positions(length, th)
        else:
            n = ctx.count_by_thickness(length, t, gap)
            labels = [f"{p['axis'].upper()}-{i + 1}" for i in range(n)]
            th = [ctx.thickness_of(l) for l in labels]; pos = ctx.stacked_positions(length, th, gap)
        slices = ctx.keep([Slice(lab, "S", ctx.frame(lab, ctx.mid + normal * z, normal, up_hint=up), tk)
                           for lab, z, tk in zip(labels, pos, th)])
        self.profiles(ctx, slices)
        slices = [s for s in slices if not s.raw.is_empty]
        ctx.rods = []
        ctx.cover_r = (t + gap) / 2 + 0.5 if p["distribution"] == "distance" else length / (2 * max(1, len(slices))) + 0.5
        if p["space"] > 0 and p["connect"] == "none":
            ctx.errors.append(f"space = {p['space']:g} mm between slices but no connectors — the slices would float: set connect to tab (spacers) or dowel, or set space to 0")
        if p["connect"] == "none" or len(slices) < 2:
            return slices
        extra = self.connect(ctx, slices)
        # assembly order: a slice, then the connectors that sit on it, then the next slice …
        by_pair = {}
        for sl in extra:
            by_pair.setdefault(getattr(sl, "pair", 0), []).append(sl)
        out = []
        for i, sl in enumerate(slices):
            out.append(sl); out += by_pair.get(i, [])
        return out

    def profiles(self, ctx, slices):
        """Section each slice now (connector placement needs them); plan.build reuses `raw`."""
        for sl in slices:
            secs = [section_polygons(ctx.mesh, sl.M)]
            if ctx.p["surface"] != "mid":
                for dz in (-sl.thickness / 2 + 0.01, sl.thickness / 2 - 0.01):
                    M = sl.M.copy(); M[:3, 3] += M[:3, 2] * dz
                    secs.append(section_polygons(ctx.mesh, M))
            g = secs[0]
            for s in secs[1:]:
                g = g.intersection(s) if ctx.p["surface"] == "inner" else unary_union([g, s])
            sl.raw = as_multi(g)

    # ---------------------------------------------------------------- connectors
    def spread(self, region, n, apart=0.0, clear=(), by=0.0):
        """n points inside a region, as far apart as it will take them: along its longer axis, from the ends inward
        until the region contains them all. `apart` is the least separation worth having — two holes closer than
        their own width merge into one, which locates nothing (a cone's apex used to give two 6 mm dowels 4 mm
        apart). `clear` are holes already cut in this slice, to stay `by` away from: where a tapering model makes a
        dowel move inward, its replacement must not land in the wall of the one above it — so the line across the
        region is tried as well as the line along it. A region that takes neither gets nothing.
        Points around the region go in as well — evenly along its outline, pulled in toward the middle until they
        fit — and where the line does not hold it, the set that holds it best wins (dowel_leverage). On a line alone
        a bumpy layer only took two points pulled in near its middle, and three on a line left a disc held along one
        diameter."""
        x0, y0, x1, y1 = region.bounds; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; w, h = x1 - x0, y1 - y0

        def ok(pts):
            return (min((np.hypot(q[0] - r[0], q[1] - r[1]) for q in pts for r in pts if q is not r), default=apart) >= apart
                    and all(region.contains(Point(q)) for q in pts)
                    and all(np.hypot(q[0] - r[0], q[1] - r[1]) > by for q in pts for r in clear))

        # as many as fit, down to two: three that do not fit a small layer used to fall straight to one point, which
        # the carried rods then crowded (the horse's legs came out worse held for asking more dowels)
        for n in range(n, 1, -1):
            sets = []
            for span, along_x in sorted([(w, True), (h, False)], reverse=True):
                for k in (0.45, 0.38, 0.3, 0.22, 0.15):
                    pts = [(cx + span * t, cy) if along_x else (cx, cy + span * t) for t in np.linspace(-k, k, n)]
                    if ok(pts):
                        sets.append(pts); break
            c = region.centroid
            for start in np.arange(4) / (4 * n):          # ponytail: 4 starting angles; a finer search if one misses
                edge = np.array([region.exterior.interpolate(start + i / n, normalized=True).coords[0] for i in range(n)])
                for k in (0.9, 0.75, 0.6, 0.45):
                    pts = [(float(x), float(y)) for x, y in (c.x, c.y) + k * (edge - (c.x, c.y))]
                    if ok(pts):
                        sets.append(pts); break
            # the line first, as it always was where it holds: moving holes that already hold crowds the next pair
            # (the hollowed bunny's second layer lost its dowels to two moved out into its ring)
            good = [pts for pts in sets if dowel_leverage(region, pts) <= LEVERAGE_OK]
            if sets:
                return good[0] if good else min(sets, key=lambda pts: dowel_leverage(region, pts))
        # one point: the region's own, or where that lands in the wall of a hole already cut, the spot around the
        # region farthest from those holes (a hollowed bunny's crumb of a layer lost its only dowel this way)
        c, m = region.representative_point(), region.centroid
        if ok([(c.x, c.y)]):
            return [(c.x, c.y)]
        edge = [region.exterior.interpolate(t, normalized=True) for t in np.arange(16) / 16]
        fits = [q for q in ((m.x + k * (e.x - m.x), m.y + k * (e.y - m.y)) for e in edge for k in (0.8, 0.5)) if ok([q])]
        return [max(fits, key=lambda q: min((np.hypot(q[0] - r[0], q[1] - r[1]) for r in clear), default=0))] if fits else []

    def common_points(self, ctx, margin):
        """The same points through the whole stack: n_points per island of the region common to every slice (cached)."""
        if not hasattr(ctx, "_common_pts"):
            inter = None
            for sl in ctx._stack:
                inter = sl.raw if inter is None else inter.intersection(sl.raw)
            inter = inter.buffer(-margin) if inter is not None else None
            pts = []
            if inter is not None and not inter.is_empty:
                for isl in getattr(inter, "geoms", [inter]):
                    pts += self.spread(isl, ctx.p["n_points"], apart=2.5 * ctx.p["dowel_d"])
            ctx._common_pts = pts
        return ctx._common_pts

    def points_for_pair(self, ctx, a, b, i, d, margin, taken):
        """Connection points (local xy of slice a) between consecutive slices a, b — per island of their overlap,
        each keeping a full wall of material from every hole already cut in slice a (`taken`)."""
        p = ctx.p
        # Two holes need `min_feature` of material between their edges, the same wall this job asks for everywhere
        # else — so their centres are two of the hole's reach (the cut, with its slot offset) plus that wall apart.
        # Any less and connect's `fits` turns the point down: points spread as far apart as they go land right on
        # this limit, so a smaller one here lost the horse's random dowels a layer at a time.
        clearance = 2 * margin - p["min_feature"]
        raw = a.raw.intersection(b.raw)
        overlap = raw.buffer(-margin)
        # An island is somewhere this connector really fits: the hole and the wall around it. Hollowing a model turns
        # every layer into a thin ring, and eroding that ring leaves a scatter of crumbs — each of which used to be
        # given points of its own, which is how a job asking for two pins per layer came back with fifteen.
        islands = []
        for g in getattr(raw, "geoms", [raw]):
            isl = g.buffer(-margin)
            islands += [h for h in getattr(isl, "geoms", [isl]) if not h.is_empty and h.area >= (d / 2) ** 2]
        # where a rod through this pair can go, kept on both slices (b's own frame: a layer can be tilted) for the
        # spread check to offer a dowel that will really be cut — the piece alone offered ears spots nothing cut
        T = np.linalg.inv(b.M) @ a.M
        a.__dict__.setdefault("dowel_room", []).extend(islands)
        b.__dict__.setdefault("dowel_room", []).extend(
            shapely.affinity.affine_transform(h, [T[0, 0], T[0, 1], T[1, 0], T[1, 1], T[0, 3], T[1, 3]]) for h in islands)
        if not islands:
            return []
        out = []
        want = max(1, p["n_points"])
        if p["placement"] == "aligned":
            fixed = [q for q in list(p["dowels"]) + self.common_points(ctx, margin) if overlap.contains(Point(q))]
            clear = lambda q, pts: all(np.hypot(q[0] - r[0], q[1] - r[1]) > clearance for r in pts)   # noqa: E731
            for isl in islands:
                # held is the piece's hold, not the overlap's: an ear's overlap is a sliver of the ear, and two dowels
                # holding the sliver dropped the third rod the ear itself needed (1.37 where the check promised 0.9)
                piece = max(as_multi(a.raw).geoms, key=lambda g: g.intersection(isl).area)
                lev = lambda pts: dowel_leverage(piece, pts)                                    # noqa: E731
                # dowels someone placed come on top of the n_points asked for: counted in, one typed into a horse's
                # ear stood in for one of its two and the ear came out held 1.56 where the check promised 1.2
                need = want + sum(isl.contains(Point(q)) for q in p["dowels"])
                held = lambda pts: len(pts) >= need and lev(pts) <= LEVERAGE_OK                 # noqa: E731
                mine = [q for q in fixed if isl.contains(Point(q))]
                # One point is a hinge: a piece pinned once still turns about it, which is exactly what a glued stack
                # does while it dries. Two locate it. An island the common points miss (an ear) gets its own, and one
                # they touch only once is topped up from its own spread, clear of the point already there.
                # A dowel is a straight rod: where this slice already carries a hole that is still inside the overlap,
                # the rod carries on through it. Choosing a fresh spread every pair walks the points inward a few
                # millimetres a layer on anything tapered — close enough to the hole above to merge with it, which is
                # how a cone came out with holes 5 mm apart and half its layers with no dowel at all.
                # Enough of them is not only a count: the shared points sit in the region common to every layer — on a
                # sphere, the smallest one — so a 200 mm piece in the middle was held by two dowels 46 mm apart
                # (reported). Rods carry on farthest out first; a piece they still do not hold is offered them topped up
                # from its own spread toward its edge, or that spread whole beside the dowels typed in (topping one rod
                # up left the blob's foot lopsided, 2.2) — one that holds first, then the count, then the better hold:
                # counting first chose three dowels bunched on a horse's leg over two that held it.
                c = isl.centroid
                for q in sorted(taken, key=lambda q: -np.hypot(q[0] - c.x, q[1] - c.y)):
                    if held(mine):
                        break
                    if isl.contains(Point(q)) and clear(q, mine):
                        mine.append(q)
                if not held(mine):
                    here = [q for q in taken if isl.buffer(clearance).contains(Point(q))]
                    fresh = self.spread(isl, want, apart=2.5 * d, clear=here, by=clearance)
                    topped = list(mine)
                    for q in fresh:
                        if len(topped) < need and clear(q, topped):
                            topped.append(q)
                    own = [q for q in p["dowels"] if isl.contains(Point(q))]
                    own += [q for q in fresh if clear(q, own)]
                    mine = min((mine, topped, own), key=lambda pts: (lev(pts) > LEVERAGE_OK, -min(len(pts), need), lev(pts)))
                out += mine
        elif p["placement"] == "random":
            rng = np.random.default_rng(1000 + i)
            for isl in islands:
                x0, y0, x1, y1 = isl.bounds
                # 800 candidates at once: inside the island and clear of the holes already cut (one shapely call per
                # island instead of one per candidate)
                q = np.round(rng.uniform((x0, y0), (x1, y1), (800, 2)), 1)
                q = q[shapely.contains_xy(isl, q[:, 0], q[:, 1])]
                if len(q) and taken:
                    q = q[(np.linalg.norm(q[:, None] - np.asarray(taken, float), axis=2) >= clearance).all(1)]
                if not len(q):
                    continue
                # Then each point as far as it can get from the ones already chosen, starting from the candidate
                # farthest from a random one. Taking the first candidates that merely kept clear of each other left
                # both dowels of a pair at one end of the layer and the other end free to lift (reported; the
                # farthest point of a layer sat 0.9 of its width from any dowel) — this keeps the randomness in
                # where the spread starts, not in whether it covers the layer.
                far, got = np.linalg.norm(q - q[0], axis=1), []
                while len(got) < p["n_points"] and (not got or far.max() > clearance):
                    k = int(far.argmax()); got.append((float(q[k, 0]), float(q[k, 1])))
                    to_k = np.linalg.norm(q - q[k], axis=1)
                    far = to_k if len(got) == 1 else np.minimum(far, to_k)     # the random seed is not a dowel
                out += got
        else:                                                # lines: where each 3D line crosses the mid-gap plane
            zmid = float(np.dot(b.M[:3, 3] - a.M[:3, 3], a.M[:3, 2])) / 2
            for ln in p["lines"]:
                P0, P1 = (to_local_z(a.M, q) for q in ln[:2])
                if abs(P1[2] - P0[2]) < 1e-9:
                    continue
                u = (zmid - P0[2]) / (P1[2] - P0[2])
                if 0 <= u <= 1:
                    q = P0[:2] + (P1[:2] - P0[:2]) * u
                    if overlap.contains(Point(q)):
                        out.append((float(q[0]), float(q[1])))
        return out      # whether each one really fits, against the cuts already made, is connect's `fits`

    def connect(self, ctx, slices):
        p = ctx.p; t = p["thickness"]; gap = p["space"]; d = p["dowel_d"]; mf = p["min_feature"]
        tab = p["connect"] == "tab"
        # keep the hole's real reach from the outline, not d/2: a square's corner sits at 0.71 d, a slot's end at 0.75 d
        margin = hole_reach(d + p["slot_offset"], p["dowel_shape"]) + mf
        rod = [[round(x, 3), round(y, 3)] for x, y in dowel((0, 0), d, p["dowel_shape"]).exterior.coords[:-1]]   # the rod's section, for the 3D view
        ctx._stack = slices
        extra, k, skipped = [], 0, 0
        tab_w, sw = (d if gap == 0 else d * 0.6), t + p["slot_offset"]    # a tab's width along its slot, the slot's width
        reach = math.hypot(tab_w, sw) / 2 if tab else margin - mf          # how far a cut reaches from its centre, any way it turns

        def cut(x, y, ang):
            """What one connector cuts into a slice at its local (x, y): the dowel's hole, or the slot a tab goes into."""
            if not tab:
                return dowel((x, y), d + p["slot_offset"], p["dowel_shape"])
            dx, dy = np.cos(np.radians(ang)) * tab_w / 2, np.sin(np.radians(ang)) * tab_w / 2
            return rect_along((x - dx, y - dy), (x + dx, y + dy), sw)

        def fits(sl, g, key):
            """A full wall from the outline and from every other cut in the slice: two cuts closer than that run into
            each other and come out as one ragged opening (the reported 6 mm dowels arriving as 8 and 9 mm blobs).
            The same aligned dowel coming round again is the hole already there; a slot is not, it holds one tab."""
            cuts = sl.__dict__.setdefault("_cutkeys", {})
            if key in cuts:
                return not tab
            inner = sl.__dict__.setdefault("_inner", sl.raw.buffer(-mf))
            return inner.contains(g) and all(g.distance(c) >= mf for c in cuts.values())

        def add_cut(sl, geom, key, other, pt):   # a slice touches two pairs: the same aligned point is cut once
            if key not in sl._cutkeys:
                sl._cutkeys[key] = geom; sl.cuts.append(geom); sl.engages.append("tab" if tab else "dowel")
            sl.links.append((other, geom, pt))

        def place(a, b, i, j, x, y):
            """Connector j of pair i at the first spot by (x, y) that fits both slices: that spot, or None. A dowel is a
            straight rod and goes exactly there. A slot holds one tab, so consecutive pairs step theirs sideways (the
            spacer below a slice and the one above sit side by side); the other side, then the other direction, then
            no step are tried before the point is given up. The fit is tested on the cut itself — tested on a round
            hole at the unstepped point, every second pair of an aligned stack lost all its spacers to the slots of
            the pair before, and the layers they held were cut off as floating."""
            nonlocal k
            if tab:
                ang = {"x": 0.0, "y": 90.0, "alternate": 90.0 * (j % 2)}[p["spacer_dir"]]
                step = d * 1.2 * (1 if i % 2 else -1)
                angs = (ang, 90.0 - ang) if p["spacer_dir"] == "alternate" else (ang,)
                tries = [(A, s) for A in angs for s in (step, -step)] + [(A, 0.0) for A in angs]
            else:
                tries = [(0.0, 0.0)]
            for ang, s in tries:
                dx, dy = np.cos(np.radians(ang)), np.sin(np.radians(ang))
                xa, ya = x + dx * s, y + dy * s
                xb, yb = to_local(b.M, [(a.M @ np.array([xa, ya, 0, 1]))[:3]])[0]
                ka, kb = (round(xa, 2), round(ya, 2), ang), (round(xb, 2), round(yb, 2), ang)
                ga, gb = cut(xa, ya, ang), cut(xb, yb, ang)
                if fits(a, ga, ka) and fits(b, gb, kb):
                    break
            else:
                return None
            spacing = float(np.dot(b.M[:3, 3] - a.M[:3, 3], a.M[:3, 2]))
            pt = tuple((a.M @ np.array([xa, ya, spacing / 2, 1]))[:3])           # world point in the gap: the connection's identity
            add_cut(a, ga, ka, b.label, pt); add_cut(b, gb, kb, a.label, pt)
            if not tab:
                ctx.rods.append([list((a.M @ np.array([xa, ya, -t / 2, 1]))[:3]), list((a.M @ np.array([xa, ya, spacing + t / 2, 1]))[:3]), d,
                                 rod, list(a.M[:3, 0])])
                return xa, ya
            # one flat piece across the gap: a peg when space = 0, a spacer (body + a tab each end) otherwise
            k += 1
            M = frame_xy(np.array(pt), a.M[:3, :3] @ np.array([dx, dy, 0]), a.M[:3, 2])   # piece plane: spacer direction × stack normal
            L = spacing + t                                                     # from the far side of a to the far side of b
            body = Polygon([(-d / 2, -gap / 2), (d / 2, -gap / 2), (d / 2, gap / 2), (-d / 2, gap / 2)]) if gap > 0 else None
            tabs = Polygon([(-tab_w / 2, -L / 2), (tab_w / 2, -L / 2), (tab_w / 2, L / 2), (-tab_w / 2, L / 2)])
            sl = Slice(f"P-{k}", "P", M, t)
            sl.raw = as_multi(unary_union([body, tabs]) if body is not None else tabs)
            sl.pair = i
            extra.append(sl)
            return xa, ya

        bare, rooms = 0, []
        want = max(1, p["n_points"])
        for i, (a, b) in enumerate(zip(slices, slices[1:])):
            # what slice a already carries, for every placement: an aligned point repeats exactly and is kept
            taken = [(x, y) for x, y, *_ in a.__dict__.setdefault("_cutkeys", {})]
            pts = self.points_for_pair(ctx, a, b, i, d, margin, taken)
            got = [q for q in (place(a, b, i, j, x, y) for j, (x, y) in enumerate(pts)) if q]
            skipped += len(pts) - len(got)
            # Every island the two share is held, by as many connectors as were asked for, whatever the placer chose
            # for it: one it gave fewer (crowded out by the cuts already in a, or points skipped) is topped up. Left
            # empty, the check finds it floating and auto-fix cuts it off; left with one, it turns on it. Where a
            # connector's centre can go is worked out exactly — a wall in from both outlines and from every cut
            # already there, plus the connector's own reach — so a small layer with room for one finds it; its most
            # inward spot is taken first, then each as far from the others as the room allows. No room at all, and
            # the check says what size would fit. Lines are the connectors someone drew; nothing is added to those.
            for isl in [] if p["placement"] == "lines" else as_multi(a.raw.intersection(b.raw)).geoms:
                have = [q for q in got if isl.contains(Point(q))]
                # As many as asked for on top of any typed in, and for dowels, on past that while the piece is not
                # held and the next spot holds it better (at most as many again): a dowel typed into a bunny's ear
                # made the count, and the ear's tip lost the dowel the count used to bring it — 1.37 for 0.9 promised.
                piece = max(as_multi(a.raw).geoms, key=lambda g: g.intersection(isl).area)
                on = lambda: [(x, y) for x, y, _ in a._cutkeys if piece.contains(Point(x, y))]   # noqa: E731
                loose = lambda: not tab and dowel_leverage(piece, on()) > LEVERAGE_OK            # noqa: E731
                need = want + (sum(isl.contains(Point(q)) for q in p["dowels"]) if p["placement"] == "aligned" else 0)
                if len(have) >= need and not loose():
                    continue
                room = inside = isl.buffer(-(mf + reach))
                near = [c for s in (a, b) for c in s.__dict__.get("_cutkeys", {}).values() if c.distance(isl) < mf + reach]
                if near and not room.is_empty:
                    room = room.difference(unary_union(near).buffer(mf + reach))
                # a dowel from the pair below can carry on up through this pair: its hole in a is already there
                q = [] if tab else [(x, y) for x, y, _ in a._cutkeys if inside.contains(Point(x, y))
                                    and all(np.hypot(x - m[0], y - m[1]) > 0.01 for m in have)]
                if not room.is_empty:
                    parts = sorted(as_multi(room).geoms, key=lambda g: -g.area)
                    x0, y0, x1, y1 = room.bounds; h = max(d / 4, math.sqrt(room.area) / 20)
                    grid = np.stack(np.meshgrid(np.arange(x0, x1, h), np.arange(y0, y1, h)), -1).reshape(-1, 2)
                    q += [shapely.maximum_inscribed_circle(g, 0.1).coords[0] for g in parts]   # each room's middle first
                    q += [tuple(c) for c in grid[shapely.contains_xy(room, grid[:, 0], grid[:, 1])]]
                def far(q, ms):                                        # farthest from the connectors in ms first
                    q.sort(key=lambda pt: -min(np.hypot(pt[0] - m[0], pt[1] - m[1]) for m in ms))
                if have:
                    far(q, have)                                       # a second connector goes far from the first
                mine = []
                while q and (len(have) + len(mine) < need or len(mine) < want and loose()
                             and dowel_leverage(piece, on() + [q[0]]) < dowel_leverage(piece, on())):
                    s = place(a, b, i, len(got) + len(mine), *q.pop(0))
                    if s:
                        mine.append(s); far(q, have + mine)
                got += mine
            if not got:      # nothing this size fits here: remember the biggest hole these two layers would take
                bare += 1
                both = a.raw.intersection(b.raw)
                if not both.is_empty:
                    rooms.append(max(shapely.maximum_inscribed_circle(g, 0.5).length * 2 for g in as_multi(both).geoms))
        # These two go in the plan's notes, not on a slice: check_plan clears every slice's warnings before it runs,
        # so a message a mode leaves there never reaches anyone.
        said = []
        if skipped:
            said.append(f"{skipped} connection point(s) skipped — no spot there keeps a {mf:g} mm wall from the outline and "
                        "from the other connectors: move the points inward (alt-click) or reduce dowel_d")
        if bare and p["placement"] == "lines":
            # Here nothing was short of room: the lines put no point there. Offering a smaller dowel sent people
            # looking for a size problem that did not exist.
            said.append(f"{bare} pair(s) of slices got no connector — none of the {len(p['lines'])} line(s) passes "
                        "through the material of both: add a line that does (+ line on the Technique tab draws one up "
                        "the middle of the model to start from), or set placement to aligned")
        elif bare:
            # Connectors are on and some layers got none: at this diameter nothing fits in them, and a stack that is
            # only glued slides while it dries. Say what would fit rather than leave it quietly unaligned.
            # The widest hole those layers hold is the inscribed circle less the wall on *both* sides — and the hole
            # reaches further than d/2 for a square (0.71 d), which is what `margin` already measured for this shape.
            # The median of them, not the widest: sized to the widest, only one pair in the stack could take it. A
            # size at or above the one that just failed means these pairs are not short of room at all — they are
            # narrow strips, or all their room is inside the wall of a hole already cut — so no size is offered.
            # What is left after eroding has to be an island the placer will use, not a sliver: it keeps only those
            # of at least (d/2)² — a disc of that area has radius d/(2·√π), so that comes off the radius too.
            reach = (margin - p["min_feature"]) / (d + p["slot_offset"])       # hole radius per mm of diameter
            room = float(np.median(rooms)) if rooms else 0.0
            fits = round((room / 2 - p["min_feature"]) / (reach + 1 / (2 * math.sqrt(math.pi))) - p["slot_offset"], 1)
            said.append(f"{bare} pair(s) of slices got no connector — a {p['dowel_d']:g} mm one does not fit them: "
                        + (f"set dowel_d to about {fits:g} mm" if MIN_DOWEL <= fits < p["dowel_d"] else
                           "they overlap only in strips too narrow to hold one — fewer slices, a thicker hollow wall, "
                           "or set connect to tab")
                        + ", or set connect to none and line them up by eye")
        if said:
            ctx.notes_extra = " · ".join([getattr(ctx, "notes_extra", "") or ""] + said).strip(" ·")
        if p["placement"] == "aligned" and p["dowels"]:
            used = {(round(x, 2), round(y, 2)) for s in slices for x, y, *_ in getattr(s, "_cutkeys", ())}
            for x, y in p["dowels"]:
                if (round(x, 2), round(y, 2)) not in used:
                    slices[0].warnings.append(f"dowel point ({x:g}, {y:g}) is outside the material of every pair of slices — nothing cut; alt-click nearer the middle of a slice")
        return extra


def to_local_z(M, pt):
    q = np.linalg.inv(M) @ np.array([pt[0], pt[1], pt[2], 1.0])
    return q[:3]
