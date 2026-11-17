"""Stacked: parallel sections, touching or spaced apart, connected by dowel rods, flat pegs, or tabbed spacers."""
import math

import numpy as np
import shapely
import shapely.affinity
from shapely.ops import unary_union
from . import MAX_SLICES, Mode, Param, register, spacing_params
from .connectors import Connectors, Layer
from ..geometry import as_multi, as_lines, section_polygons, into
from ..ring import collared, ring as ring_of
from ..ringcut import Ring, shorten

CONNECT_HELP = ("dowel = round/square rods through holes (drawn in the 3D view), the default: glue alone leaves every layer free to "
                "slide while it dries, and two dowels through a piece hold it where it belongs · tab = flat pieces cut from the sheet: "
                "a peg between touching slices, or a spacer (body + tabs into slots) when `space` > 0 — keeps the distance and the "
                "orientation · none = glue only, for a stack you are happy to line up by eye")


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
        Param("shift", "number", 0.0, "Move every slice plane along the axis by this much (mm, + towards the top), so one slice lands on a feature of the model — a rim, a shoulder, the middle of a hole: read the slice's height off the 3D view and shift by the difference. With `distance` the stack is laid out again from the shifted start, one slice after another over the model, so only the remainder at its ends is uncovered; with `count` or a spacing curve a slice moved past an end of the model is left out and the notes say so. The slices are named by their place in the stack once moved, so a setting made for one by name (a thickness, an offset) may need its name updated", -500, 500, 0.1, unit="mm", label="shift stack"),
        Param("surface", "choice", "mid", "Outline of each slice: mid = section at the middle; outer = union of the sections through the slice thickness (sand down to shape, Slicer's 3D Slices); inner = intersection (never protrudes)", choices=["mid", "outer", "inner"]),
        Param("ring_slices", "bool", False, "Ring slices: keep only a wall `wall` wide inside each slice's outline and cut the middle away, so "
              "the stack is a shell of rings instead of solid discs. The wall is measured in the slice's own plane, the same all the way "
              "round (Modify form's `hollow` shells the 3D model instead, which leaves gently sloping layers wide and the ends solid). "
              "Every island and every hole gets its own wall; where a slice is narrower than twice the wall it stays solid. Dowels and "
              "spacers sit in the wall, which grows locally round each one that needs more room", label="ring slices",
              section="Ring slices — a wall instead of a solid slice"),
        Param("ring_wall", "number", 8.0, "How wide the wall of a ring slice is (mm), measured in the slice's plane from its outline in. "
              "A slice can have its own: select it in the 3D view", 0.5, 500, 0.5, unit="mm", show_if=("ring_slices", True), label="wall"),
        Param("ring_caps", "bool", False, "Keep the first and last slice solid, so the stack is closed at both ends. Off = they are rings too",
              show_if=("ring_slices", True), label="solid ends"),
        Param("max_length", "number", 0.0, "Longest piece of a ring slice (mm), measured along the ring: a longer ring is cut across "
              "its wall into pieces no longer, spread evenly, clear of the dowel holes, each with a puzzle tab. 0 = no limit. A ring "
              "too big for the sheet is always cut this way", 0, 10000, 5, unit="mm", show_if=("ring_slices", True), label="max piece length"),
        Param("wall", "map", {}, "Per-slice ring wall (mm), when ring slices are on", group="slices", unit="mm", label="own walls"),
        Param("next_outline", "bool", False, "Engrave the outline of the next layer onto each slice (GUIDE, orange): a light line showing where the layer stacked on top sits, so the stack lines up as it is glued. Drawn only where it lands on the slice's own material — a wider layer above stops at this layer's edge. Engrave, not cut; off by default", label="next layer outline"),
        Param("next_outline_offset", "number", 0.0, "Move the engraved outline in (−) or out (+) from the next layer's true edge (mm). A little negative — −0.25 or so — tucks the line under the layer above, so a glue-up a hair off still hides it; positive marks an overhang where the next layer is wider", -5, 5, 0.05, unit="mm", show_if=("next_outline", True), label="outline offset"),
        Param("connect", "choice", "dowel", CONNECT_HELP, choices=["none", "dowel", "tab"]),
        Param("dowel_d", "number", 6.0, "Dowel diameter / peg & spacer width (mm)", 0.5, 100, 0.5, unit="mm", show_if=("connect", ["dowel", "tab"])),
        Param("dowel_shape", "choice", "round", "Dowel hole shape (round, square, pencil = hexagon, cross, horizontal / vertical slot)", choices=["round", "square", "pencil", "cross", "hslot", "vslot"], show_if=("connect", "dowel")),
        Param("placement", "choice", "aligned", "aligned = the same points through the whole stack, so each dowel is one straight rod (every island that persists gets its own); to move one or add your own, alt-click a slice in the 3D view or type it under dowels · random = new points for every pair of slices, spread as far apart as that pair allows, so no two layers share a hole · lines = straight dowels you draw yourself, start → end, holes wherever they cross between two slices", choices=["aligned", "random", "lines"], show_if=("connect", ["dowel", "tab"])),
        Param("n_points", "int", 2, "Connection points per pair of slices (per island)", 1, 20, 1, show_if=("placement", ["aligned", "random"])),
        *spacing_params("slices", [("spacing_curve", "slice spacing", [[0, 10], [0.5, 10], [1, 10]])], 3, 30),
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
              "Z-3a = dowel a between Z-3 and Z-4 — a connector is named after the lower of the two slices it joins and a letter, "
              "and the mark 3a is engraved beside its hole on both slices, so a hole marked with a number lower than the slice's "
              "own takes the rod from below, one with its own number the rod going up · a straight rod through several slices "
              "keeps the name of the slice it starts from · with tab connectors Z-3a is the peg or spacer itself, a part of its own")

    def build(self, ctx):
        p = ctx.p
        ax = "xyz".index(p["axis"]); normal = ctx.ax[ax]; up = ctx.ax[(ax + 2) % 3]
        length = ctx.ext[ax]
        labels, pos, th, drawn = self.planes(ctx, ax)
        slices = ctx.keep([Layer(lab, "S", ctx.frame(lab, ctx.mid + normal * z, normal, up_hint=up), tk)
                           for lab, z, tk in zip(labels, pos, th)])
        self.profiles(ctx, slices)
        slices = [s for s in slices if not s.raw.is_empty]
        conn = None if p["connect"] == "none" or len(slices) < 2 else Connectors(ctx, slices)
        if p["ring_slices"]:
            self.ring_up(ctx, slices, conn)
        ctx.view["rods"] = []
        ctx.cover_r = self.cover_r(ctx, pos, drawn, length, len(slices))
        if p["space"] > 0 and p["connect"] == "none":
            ctx.errors.append(f"space = {p['space']:g} mm between slices but no connectors — the slices would float: set connect to tab (spacers) or dowel, or set space to 0")
        extra = conn.run() if conn else []
        self.ring_down(ctx, slices)
        return self.in_order(slices, extra) if conn else slices

    def cut(self, ctx, sl):
        """plan.build's hook: a ring slice longer than `max_length`, or too big for the sheet, cut across its wall into
        pieces (core/ringcut.py) — or None for the usual splitting."""
        if getattr(sl, "ring", None) is None:           # a solid slice, a peg or spacer, a plaque's plate
            return None
        geom, made, plain, stuck = shorten(sl, ctx.p, ctx.p["max_length"], [Ring(c) for c in sl.raw.geoms], sl.profile)
        if stuck:
            sl.warnings.append(f"{stuck} piece(s) longer than `max_length` or too big for the sheet found no clean place to be cut "
                               "(dowel holes close together all along): cut by hand, or move the dowels")
        if plain:
            sl.warnings.append(f"{plain} of its {made} cut(s) have no room for a puzzle tab (a narrow wall): glue those")
        return list(as_multi(geom).geoms) if made else None

    @staticmethod
    def ring_up(ctx, slices, conn):
        """Ring slices, first half: each slice keeps its section and the ring it will be cut as (`ring`), and `raw` is
        set to a ring wide enough for one connector to sit in it with a full wall all round, which the connectors
        are placed in."""
        p = ctx.p; mf = p["min_feature"]
        room = 2 * (conn.reach + conn.mf) + 0.5 if conn else 0.0      # a connector's reach and a wall, either side
        for i, sl in enumerate(slices):
            if p["ring_caps"] and i in (0, len(slices) - 1):
                continue
            w = ctx.override("wall", sl.label, p["ring_wall"])
            sl.ring = (sl.raw, ring_of(sl.raw, w, mf))
            sl.raw = ring_of(sl.raw, room, mf) if room > w else sl.ring[1]
            sl.inner = None

    @staticmethod
    def ring_down(ctx, slices):
        """Ring slices, second half: each slice cut back to its own wall, with a collar left round every connector."""
        mf = ctx.p["min_feature"]
        for sl in slices:
            if sl.ring is not None:
                section, wall = sl.ring
                sl.raw = collared(section, wall, sl.cuts, mf)
                sl.inner = None
        # a small slice next to a ring can drop through its hole: near the pole of a round model the end slice is
        # narrower than the middle of the one beside it, and nothing holds it — say why, and what closes it
        loose = [b.label for a, b, c in zip([None, *slices], slices, [*slices[1:], None])
                 if b.ring is not None and not any(n is not None and not into(n.M, b.M, n.raw).intersection(b.raw).is_empty for n in (a, c))]
        if loose:
            ends = {slices[0].label, slices[-1].label}
            what = ("turn on `solid ends`, or a narrower wall" if set(loose) & ends and not ctx.p["ring_caps"] else "a narrower wall, or fewer slices")
            ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, f"ring slices: {', '.join(loose[:6])}{'…' if len(loose) > 6 else ''} "
                                                     f"touch(es) no neighbour — each sits inside the hole of the ring next to it: {what}"] if x)

    @staticmethod
    def cover_r(ctx, pos, drawn, length, n):
        """How far across its plane a slice counts as covering the surface: half the widest step between two slices."""
        p = ctx.p
        return (max(np.diff(pos)) / 2 + 0.5 if len(pos) > 1 else length / 2) if drawn is not None else \
            (p["thickness"] + p["space"]) / 2 + 0.5 if p["distribution"] == "distance" else length / (2 * max(1, n)) + 0.5

    @staticmethod
    def in_order(slices, extra):
        """Assembly order: a slice, then the connectors that sit on it, then the next slice …"""
        by_pair = {}
        for sl in extra:
            by_pair.setdefault(sl.pair, []).append(sl)
        out = []
        for i, sl in enumerate(slices):
            out.append(sl); out += by_pair.get(i, [])
        return out

    def planes(self, ctx, ax):
        """Where the slices of the stack sit along axis `ax`: their labels, positions (0 = the middle of the model) and
        thicknesses, and what the spacing curve drew (None when the spacing is even)."""
        p = ctx.p
        length = ctx.ext[ax]; t = p["thickness"]; gap = p["space"]
        name = lambda i: f"{p['axis'].upper()}-{i + 1}"
        drawn = ctx.spaced("spacing_curve", length - 2 * p["margin"], p["count"])
        if drawn is not None:                             # the spacing curve: slices where it puts them, the stack as tall as the model
            pos = [-length / 2 + p["margin"] + q for q in drawn]
        elif p["distribution"] == "count":
            pos = ctx.positions(length, [t] * p["count"])
        else:                                             # one after another, each at its own thickness
            n = ctx.count_by_thickness(length, t, gap, ax)
            pos = ctx.stacked_positions(length, [ctx.thickness_of(name(i)) for i in range(n)], gap)
        by_distance = drawn is None and p["distribution"] == "distance"
        if p["shift"] and pos:
            pos = self.shifted(ctx, pos, name, length, t, gap, by_distance)
        if drawn is not None and p["shift"]:              # the graph's ticks follow the slices that are built
            ctx.view["spacing"][-1]["positions"] = [round(z + length / 2 - p["margin"], 3) for z in pos]
        # a slice is named by its place in the stack, so the names are given once the planes are final (a
        # per-slice thickness is looked up by name); laid by the curve, or moved by a shift, neighbours can overlap
        labels = [name(i) for i in range(len(pos))]
        th = [ctx.thickness_of(l) for l in labels]
        if drawn is not None or p["shift"]:
            tight = [(a, b, z2 - z1) for a, b, z1, z2, t1, t2 in zip(labels, labels[1:], pos, pos[1:], th, th[1:]) if z2 - z1 < (t1 + t2) / 2 - 1e-6]
            if tight:
                a, b, g = min(tight, key=lambda x: x[2])
                why = "raise the curve there or `spacing from`, use fewer slices, or thinner material" if drawn is not None else \
                      "use fewer slices, thinner material, or a smaller shift"
                ctx.errors.append(f"{'spacing curve' if drawn is not None else 'shift'}: {len(tight)} pair(s) of slices overlap — "
                                  f"{a} and {b} are {g:.1f} mm apart, less than the material: {why}")
        return labels, pos, th, drawn

    def shifted(self, ctx, pos, name, length, t, gap, refill):
        """Every slice plane moved by `shift` along the axis. A stack laid by distance is laid again from the shifted
        start: the lowest slice that fits inside the margins on the shifted grid, then one after another at each
        slice's own thickness plus the gap, as far up as the model goes — so a shift of any size leaves the model
        covered but for the remainder at its ends. Otherwise the slices keep their number and spacing, and one moved
        past an end of the model inside its margins is left out, with a note."""
        p = ctx.p; s = p["shift"]; room = length - 2 * p["margin"]
        pos = [z + s for z in pos]
        if refill:
            pitch = t + gap; k0 = math.ceil((-room / 2 + t / 2 - pos[0]) / pitch - 1e-9)
            z, out = pos[0] + k0 * pitch - t / 2, []          # the bottom face of the lowest slice
            while len(out) < MAX_SLICES:
                tk = ctx.thickness_of(name(len(out)))
                if z + tk > room / 2 + 1e-6:
                    break
                out.append(z + tk / 2); z += tk + gap
            if len(out) == MAX_SLICES:
                ctx.errors.append(f"{MAX_SLICES} slices from the shifted start and the model not covered: capped — use thicker material, more space, or `count`")
            return out
        kept = [z for z in pos if -room / 2 < z < room / 2]
        if len(kept) < len(pos):
            ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, f"shift {s:g} mm: {len(pos) - len(kept)} slice(s) moved past the end of the model and left out"] if x)
        return kept

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

    @staticmethod
    def fit(p):
        return {"distribution": "count", "count": min(p["count"], 3)}, 0.0

    def guide_outlines(self, ctx, slices):
        """Engrave each layer's outline onto the layer under it (GUIDE): the line to line the stack up by, so a layer
        that has to sit a certain way is marked on the layer it rests on. The neighbour's section is mapped into this
        slice's own frame — stacked slices are parallel, so that is a plain 2D transform — and only the part of its
        silhouette that lands on this slice's material is kept: a line can be engraved only where there is material to
        burn it into, so the overhang of a wider layer above stops at this layer's edge. Kept as `lines` with the style
        "guide", which the export draws on its own GUIDE layer (engrave, not cut or score). plan.build calls this once
        the outlines are final — grown where asked, slivers shed, slots and holes taken out of `profile` — so the line
        is the layer as it will be cut, inner edges of a hollow layer included."""
        if not ctx.p.get("next_outline"):
            return
        off = ctx.p["next_outline_offset"]
        slices = [s for s in slices if s.group == "S"]            # the layers, not the pegs or spacers between them
        for a, b in zip(slices, slices[1:]):
            # the material: slots and dowel holes leave nothing to engrave. Widened by a hair, mitred: an edge the two
            # layers share lands a rounding error outside the exact outline and the ring would lose that side
            clip = a.profile.buffer(1e-6, join_style=2)
            # the layer above as it will be cut, its holes and slots filled back in: a sliver shed from it (a shaving
            # thinner than min_feature) is not engraved as its edge, and a dowel hole is not engraved as a ring
            above = unary_union([b.profile, *b.cuts]).intersection(b.raw) if b.cuts else b.profile
            for poly in as_multi(above).geoms:
                placed = into(a.M, b.M, poly)                 # b's local xy → a's local xy
                # The guide sits on the next layer's true edge; a negative `next_outline_offset` pulls it in, so the
                # layer above still covers the line when the glue-up is a hair off. Mitred, not rounded, so a square
                # stays a square where the outline follows the part's corners.
                if off:
                    placed = placed.buffer(off, join_style=2)
                    if placed.is_empty:
                        continue
                for part in as_multi(placed).geoms:
                    for ring in (part.exterior, *part.interiors):
                        # A neighbour the same shape lies exactly on this slice's outline, and a line that hugs a
                        # polygon boundary comes back from GEOS cut at every vertex — one path per point, hundreds of
                        # them. Merging the pieces back into whole lines keeps the guide one line per ring.
                        merged = shapely.line_merge(as_lines(ring.intersection(clip)))
                        for ln in as_lines(merged).geoms:
                            if ln.length > 1e-6:
                                a.lines.append(("guide", ln))
