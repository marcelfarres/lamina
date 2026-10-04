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
        Param("dowels", "points", [], "Your own dowels, each straight through every layer it fits (x, y in the slice plane, 0, 0 = the middle of the model); empty = automatic. Alt-click a slice in the 3D view to add one there or remove the one you click; type its x, y here to move it", unit="mm", show_if=("placement", "aligned")),
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
        # else — so their centres are a diameter plus that wall apart. Closer and they cut into one another.
        clearance = d + p["min_feature"]
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
                held = lambda pts: len(pts) >= want and dowel_leverage(isl, pts) <= LEVERAGE_OK   # noqa: E731
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
                        if len(topped) < want and clear(q, topped):
                            topped.append(q)
                    own = [q for q in p["dowels"] if isl.contains(Point(q))]
                    own += [q for q in fresh if clear(q, own)]
                    mine = min((mine, topped, own), key=lambda pts: (dowel_leverage(isl, pts) > LEVERAGE_OK,
                                                                     -min(len(pts), want), dowel_leverage(isl, pts)))
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
        # Last word, whatever placed them: two holes closer together than their own width run into each other and
        # come out as one ragged opening (the reported 6 mm dowels arriving as 8 and 9 mm blobs). A point that sits
        # exactly where one already is, is the same aligned point coming round again — that one is cut once and kept.
        keep, near = [], [tuple(q) for q in taken]
        for q in out:
            gaps = [np.hypot(q[0] - r[0], q[1] - r[1]) for r in near]
            if all(g > clearance or g < 0.01 for g in gaps):
                keep.append(q); near.append(tuple(q))
        return keep

    def connect(self, ctx, slices):
        p = ctx.p; t = p["thickness"]; gap = p["space"]; d = p["dowel_d"]
        # keep the hole's real reach from the outline, not d/2: a square's corner sits at 0.71 d, a slot's end at 0.75 d
        margin = hole_reach(d + p["slot_offset"], p["dowel_shape"]) + p["min_feature"]
        rod = [[round(x, 3), round(y, 3)] for x, y in dowel((0, 0), d, p["dowel_shape"]).exterior.coords[:-1]]   # the rod's section, for the 3D view
        ctx._stack = slices
        extra, k, skipped = [], 0, 0

        def add_cut(sl, geom, x, y, ang, tag, other, pt):   # a slice touches two pairs: the same aligned point must be cut once
            key = (round(x, 2), round(y, 2), ang)
            keys = sl.__dict__.setdefault("_cutkeys", set())
            if key not in keys:
                keys.add(key); sl.cuts.append(geom); sl.engages.append(tag)
            sl.links.append((other, geom, pt))
        bare, rooms = 0, []
        for i, (a, b) in enumerate(zip(slices, slices[1:])):
            # what slice a already carries, for every placement: an aligned point repeats exactly and is kept, one
            # that merely lands near an existing hole is not
            taken = [(x, y) for x, y, *_ in getattr(a, "_cutkeys", ())]
            pts = self.points_for_pair(ctx, a, b, i, d, margin, taken)
            if not pts:      # nothing this size fits here: remember the biggest hole these two layers would take
                bare += 1
                both = a.raw.intersection(b.raw)
                if not both.is_empty:
                    rooms.append(max(shapely.maximum_inscribed_circle(g, 0.5).length * 2 for g in as_multi(both).geoms))
            for j, (x, y) in enumerate(pts):
                # A tab slot belongs to one spacer: the slot angle depends on the point only, and consecutive pairs
                # step their point sideways, so the spacer below and the spacer above a slice sit next to each
                # other instead of crossing in the same slot.
                ang = {"x": 0.0, "y": 90.0, "alternate": 90.0 * (j % 2)}[p["spacer_dir"]]
                dx, dy = np.cos(np.radians(ang)), np.sin(np.radians(ang))
                if p["connect"] == "tab":
                    step = d * 1.2 * (1 if i % 2 else -1)
                    x, y = x + dx * step, y + dy * step
                w = (a.M @ np.array([x, y, 0, 1]))[:3]; bx, by = to_local(b.M, [w])[0]
                spacing = float(np.dot(b.M[:3, 3] - a.M[:3, 3], a.M[:3, 2]))
                pt = tuple((a.M @ np.array([x, y, spacing / 2, 1]))[:3])           # world point in the gap: the connection's identity
                if p["connect"] == "dowel":
                    add_cut(a, dowel((x, y), d + p["slot_offset"], p["dowel_shape"]), x, y, 0, "dowel", b.label, pt)
                    add_cut(b, dowel((bx, by), d + p["slot_offset"], p["dowel_shape"]), bx, by, 0, "dowel", a.label, pt)
                    ctx.rods.append([list((a.M @ np.array([x, y, -t / 2, 1]))[:3]), list((a.M @ np.array([x, y, spacing + t / 2, 1]))[:3]), d,
                                     rod, list(a.M[:3, 0])])
                    continue
                # tab connector: slots in both slices + one flat piece (peg when space = 0, spacer otherwise)
                tab_w = d if gap == 0 else d * 0.6
                sw = t + p["slot_offset"]
                sa = rect_along((x - dx * tab_w / 2, y - dy * tab_w / 2), (x + dx * tab_w / 2, y + dy * tab_w / 2), sw)
                sb = rect_along((bx - dx * tab_w / 2, by - dy * tab_w / 2), (bx + dx * tab_w / 2, by + dy * tab_w / 2), sw)
                if not (a.raw.buffer(-p["min_feature"]).contains(sa) and b.raw.buffer(-p["min_feature"]).contains(sb)):
                    skipped += 1; continue
                add_cut(a, sa, x, y, ang, "tab", b.label, pt); add_cut(b, sb, bx, by, ang, "tab", a.label, pt)
                k += 1
                o = (a.M @ np.array([x, y, spacing / 2, 1]))[:3]
                M = frame_xy(o, a.M[:3, :3] @ np.array([dx, dy, 0]), a.M[:3, 2])   # piece plane: spacer direction × stack normal
                L = spacing + t                                                     # from the far side of a to the far side of b
                body = Polygon([(-d / 2, -gap / 2), (d / 2, -gap / 2), (d / 2, gap / 2), (-d / 2, gap / 2)]) if gap > 0 else None
                tabs = Polygon([(-tab_w / 2, -L / 2), (tab_w / 2, -L / 2), (tab_w / 2, L / 2), (-tab_w / 2, L / 2)])
                sl = Slice(f"P-{k}", "P", M, t)
                sl.raw = as_multi(unary_union([body, tabs]) if body is not None else tabs)
                sl.pair = i
                extra.append(sl)
        # These two go in the plan's notes, not on a slice: check_plan clears every slice's warnings before it runs,
        # so a message a mode leaves there never reaches anyone.
        said = []
        if skipped:
            said.append(f"{skipped} connection point(s) skipped — the slot would cross the outline: move the points inward (alt-click) or reduce dowel_d")
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
