"""Plaque: the model cut off at a flat back plate, and its slices standing on edge on that plate, held in it by teeth
that go through plate slots. A piece of a slice that does not reach the plate hangs from the slice beside it on
stacked's flat spacers, turned edge-on to whoever looks at the plaque."""
import math
from dataclasses import replace

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from . import Param, register
from .stacked import Stacked
from ..model import Slice
from ..geometry import as_lines, as_multi, frame, frame_xy, rot_about, to_local, to_world
from ..notch import interlock
from ..vector import outlines

BIG = 1e5
SHAPES = ["circle", "ellipse", "rectangle", "rounded", "hexagon", "shield", "silhouette", "file"]
SHIELD = [(-.5, .40), (-.42, .43), (-.30, .40), (-.12, .47), (0, .50), (.12, .47), (.30, .40), (.42, .43), (.5, .40),
          (.5, -.12), (.40, -.30), (.22, -.42), (0, -.50), (-.22, -.42), (-.40, -.30), (-.5, -.12)]
_S = {q.name: q for q in Stacked.params}
# stacked's connector settings as the plaque always uses them: flat spacers, three to a floating piece, their slots
# along the plate's normal so the spacer is seen edge-on from the front
FIXED = {"connect": "tab", "placement": "random", "n_points": 3, "dowel_shape": "round", "dowels": [], "lines": [], "spacer_dir": "y"}


def outline(kind, pts, margin):
    """The plate's outline round the model's footprint `pts` (plate x, y), `margin` clear of it all round."""
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; w, h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin
    r = float(np.hypot(*(pts - (cx, cy)).T).max()) + margin
    if kind == "circle":
        return Point(cx, cy).buffer(r, 64)
    if kind == "ellipse":                        # the ellipse through the corners of the footprint's box, plus the margin
        return affinity.scale(Point(cx, cy).buffer(1, 64), (x1 - x0) / math.sqrt(2) + margin, (y1 - y0) / math.sqrt(2) + margin)
    if kind == "hexagon":
        R = r / math.cos(math.pi / 6)
        return Polygon([(cx + R * math.cos(a), cy + R * math.sin(a)) for a in np.arange(6) * math.pi / 3])
    if kind == "shield":                         # its lower half tapers, so it is drawn a quarter bigger than the box
        return Polygon([(cx + x * w * 1.25, cy + y * h * 1.25) for x, y in SHIELD]).buffer(-5).buffer(5, 16)   # its tips rounded: a sharp one is a thin spot
    rect = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return rect.buffer(-0.12 * min(w, h)).buffer(0.12 * min(w, h), 16) if kind == "rounded" else rect


def silhouette(mesh, Mp, margin):
    """The shadow of `mesh` on the plate, grown by `margin`, its holes filled."""
    front = mesh.face_normals @ Mp[:3, 2] > 0                # every point of the shadow lies under a face that looks forward
    tris = to_local(Mp, mesh.vertices)[mesh.faces[front]]
    polys = shapely.polygons(tris)
    shadow = shapely.union_all(shapely.buffer(polys[shapely.area(polys) > 1e-9], 0.01)).buffer(margin, 16)
    whole = max(as_multi(shadow).geoms, key=lambda g: g.area)
    return Polygon(whole.exterior).simplify(0.05, preserve_topology=False)


@register
class Plaque(Stacked):
    name = "plaque"
    title = "Plaque"
    description = ("The model cut off at a flat back plate, its slices standing on edge on the plate: each slice has teeth that go "
                   "through plate slots. `sink` sets how deep the model goes into the plate; what is behind the plate is left out.")
    legend = ("W-1 = the back plate · X-2 / Y-4 in a crossed plaque = the 2nd slice of the first family and the 4th of the second, "
              "which half-lap into each other · R-5 = the 5th half-slice of a radial fan, counted round from `angle` · X-3 = the 3rd slice across the plate, counted from the low end (Y- or Z- when the slices "
              "run that way): its teeth go into the row of plate slots under it · X-3a = spacer a between X-3 and X-4, which "
              "holds a piece of one of them that does not reach the plate")
    params = [
        Param("back", "choice", "-z", "The side of the model that goes against the plate: the plate is square to this axis and the "
              "model sticks out of it the other way", choices=["-z", "+z", "-y", "+y", "-x", "+x"], label="back of the model"),
        Param("layout", "choice", "parallel", "How the slices stand on the plate: parallel = side by side, one after another · "
              "radial = a fan of half-slices round a centre (move it with `center`), their inner ends meeting round a small hole · "
              "crossed = two families at right angles, slotted into each other half way like an egg crate, both standing on the plate",
              choices=["parallel", "radial", "crossed"]),
        Param("axis", "choice", "x", "Slice direction (normal of the slices): one of the two axes that lie in the plate", choices=["x", "y", "z"],
              show_if=("layout", "parallel")),
        Param("planes", "int", 12, "Radial: planes through the centre; each gives two half-slices", 2, 90, 1, show_if=("layout", "radial")),
        Param("angle", "number", 0.0, "Radial: turn the whole fan about its centre (deg) · crossed: turn the grid on the plate",
              -90, 90, 1, unit="deg", show_if=("layout", ["radial", "crossed"])),
        Param("nx", "int", 8, "Crossed: slices of the first family, which goes into the plate first", 1, 200, 1, show_if=("layout", "crossed")),
        Param("ny", "int", 8, "Crossed: slices of the second family, which drops onto the first from the front", 1, 200, 1, show_if=("layout", "crossed")),
        Param("radius", "number", 0.0, "Radial: the radius of the hole in the middle of the fan, where the half-slices end (mm). "
              "0 = the least that lets them all fit round it; under that least their inner ends collide", 0, 500, 0.5, unit="mm",
              show_if=("layout", "radial")),
        Param("sink", "number", 0.0, "How far the model goes into the plate (mm), from its rearmost point: 0 = the model only touches "
              "the plate, more = more of its back is cut away. What is behind the plate's front face is left out", 0, 5000, 0.5, unit="mm"),
        Param("plate_thickness", "number", 0.0, "Thickness of the back plate's material (mm), which is also how long the teeth are: "
              "they end flush with the back of the plate. 0 = the same material as the slices", 0, 100, 0.05, unit="mm", label="plate thickness"),
        Param("plate", "choice", "rounded", "The plate's outline: a shape fitted round the model, or silhouette = the model's own "
              "shadow on the plate, grown by the margin · file = a shape of your own, drawn in an SVG or DXF file",
              choices=SHAPES, choice_labels={"rounded": "rounded rectangle", "file": "file (SVG / DXF)"}),
        Param("plate_file", "file", "", "The plate's outline from an SVG or DXF file: its largest closed shape is the plate, closed shapes "
              "inside it are cut out of the plate (a hanging hole, an ornament). The drawing is fitted round the model, keeping its "
              "proportions; place the model in it with plate scale, mirror, rotation and offset", show_if=("plate", "file"), label="plate file"),
        Param("plate_margin", "number", 20.0, "How far the plate reaches past the model all round (mm)", 0, 500, 1, unit="mm", label="plate margin"),
        Param("plate_size", "vec2", [0, 0], "The plate's width and height (mm), in place of the fit round the model; 0 = automatic. "
              "One value keeps the shape's proportions", 0, 5000, 1, unit="mm", label="plate size"),
        Param("plate_offset", "vec2", [0, 0], "Move the plate under the model (mm)", -5000, 5000, 1, unit="mm", label="plate offset"),
        Param("plate_scale", "number", 100.0, "The plate's size as a percentage of its fit round the model: over 100 leaves more plate "
              "round the model, under 100 lets the model reach past it", 10, 500, 1, unit="", label="plate scale (%)"),
        Param("plate_mirror", "bool", False, "Turn the plate's outline over, left to right: for a file drawn the other way round", label="plate mirror"),
        Param("plate_rotation", "number", 0.0, "Turn the plate about its middle (deg)", -180, 180, 1, unit="deg", label="plate rotation"),
        Param("teeth", "int", 2, "The fewest teeth for each stretch of a slice that stands on the plate. A slice that meets the plate "
              "in two separate stretches gets this many in each", 2, 20, 1),
        Param("tooth_width", "number", 10.0, "How wide a tooth is along its slice (mm); narrower where the stretch is short", 1, 200, 0.5, unit="mm", label="tooth width"),
        Param("tooth_spacing", "number", 60.0, "The most distance between two teeth (mm): a long stretch gets more teeth than "
              "`teeth`, spread evenly. 0 = `teeth` only", 0, 2000, 1, unit="mm", label="tooth spacing"),
        _S["distribution"], _S["count"], replace(_S["space"], default=3.0), _S["shift"], _S["surface"],
        Param("floating", "choice", "join", "A piece of a slice that does not reach the plate: join = it hangs from the slice beside "
              "it on three flat spacers, and a piece no neighbour can hold is left out and listed in the notes · keep = nothing is "
              "left out, the piece stays with its error", choices=["join", "keep"], label="floating pieces"),
        replace(_S["dowel_d"], show_if=None, label="spacer width", help="Width of the flat spacers that hold floating pieces (mm)"),
        *[q for q in Stacked.params if q.name.startswith("spacing_")],
    ]
    hidden_common = ("notch_ratio", "notch_factor", "notch_angle", "tilt", "roll")
    side_step = 0.0            # two joins that share a piece share its area out (build), so a spacer goes where it is put

    def build(self, ctx):
        p = ctx.p
        p.update(FIXED)
        k = "xyz".index(p["back"][1]); ax = "xyz".index(p["axis"]); radial = p["layout"] == "radial"; crossed = p["layout"] == "crossed"
        n_p = ctx.ax[k] * (1.0 if p["back"][0] == "-" else -1.0)        # the plate's normal: out of the plate, toward the front
        if ax == k and p["layout"] == "parallel":
            e = f"the slices stand on the plate, so their direction cannot be {p['axis']}, the axis the plate is square to"
            ctx.errors.append(e)
            ctx.fixes.append({"error": e, "options": [{"title": f"slice along {a}", "set": {"axis": a}} for a in "xyz" if a != p["axis"]]})
            return []
        normal = ctx.ax[ax]; plate_t = p["plate_thickness"] or p["thickness"]
        depth = ctx.mesh.vertices @ n_p
        z0 = float(depth.min()) + p["sink"]                             # the plate's front face
        if z0 >= depth.max() - 1e-6:
            ctx.errors.append(f"sink = {p['sink']:g} mm is the whole depth of the model ({np.ptp(depth):.0f} mm): nothing is left in front of the plate")
            return []
        ctx.covered = ctx.mesh.slice_plane(n_p * z0, n_p)               # what is left of the model: coverage is measured on it
        ctx.clip = [(n_p * z0).tolist(), n_p.tolist()]
        # the plate: its frame has the model's up as its y, and x to the right of someone looking at the plaque
        up = ctx.ax[1] if k == 2 else ctx.ax[2]
        Mp = frame_xy(n_p * (z0 - plate_t / 2), np.cross(up, n_p), up)
        mf = p["min_feature"]; slot_w = p["thickness"] + p["slot_offset"]
        ctx.rods = []
        clash = {}                      # crossed: slice → the stretches of its foot (from, to) where a slice of the other family stands
        fams = []
        if crossed:
            # Two families along the plate's own two directions, turned by `angle`. The first goes into the plate; the
            # second drops onto it from the front, so its slots open toward the plate and the first family's away.
            R = rot_about(n_p, p["angle"]); front = box(-BIG, 0, BIG, BIG); hub = Polygon(); wall = BIG
            for name, group, e, n in (("X", "X", R @ Mp[:3, 0], p["nx"]), ("Y", "Y", R @ Mp[:3, 1], p["ny"])):
                reach = (ctx.covered.vertices - ctx.mid) @ e
                L = float(np.ptp(reach)); c = float(reach.min() + reach.max()) / 2
                fam = []
                for j, s in enumerate(ctx.positions(L, [p["thickness"]] * n)):
                    lab = f"{name}-{j + 1}"
                    o = ctx.mid + e * (c + s + ctx.override("offset", lab))
                    fam.append(Slice(lab, group, frame(o + n_p * (z0 - o @ n_p), e, up_hint=n_p), ctx.thickness_of(lab), clip=as_multi(front)))
                fams.append(ctx.keep(fam))
            for mine, other in ((fams[0], fams[1]), (fams[1], fams[0])):
                for sl in mine:
                    at = [float((o.M[:3, 3] - sl.M[:3, 3]) @ sl.M[:3, 0]) for o in other]
                    clash[sl.label] = [(x - slot_w / 2, x + slot_w / 2) for x in at]
            slices = fams[0] + fams[1]
            ctx.cover_r = max(ctx.ext) / max(1, min(p["nx"], p["ny"])) / 2 + p["thickness"]
        elif radial:
            # 2 × planes half-slices, 180 / planes apart. Their inner corners meet where the chord between two
            # neighbours is one slice wide, and their plate slots keep a wall between them a little further out.
            n = p["planes"]; half = math.pi / (2 * n)
            least = slot_w / 2 / math.tan(half) + 0.5
            r = p["radius"] or least
            if r < least - 1e-6:
                e = f"radius = {r:g} mm: {2 * n} half-slices of {p['thickness']:g} mm need a hole of at least {least:.1f} mm radius, or their inner ends collide"
                ctx.errors.append(e)
                ctx.fixes.append({"error": e, "options": [{"title": f"radius {math.ceil(least * 2) / 2:g} mm", "set": {"radius": math.ceil(least * 2) / 2}},
                                                          {"title": "radius automatic", "set": {"radius": 0}}]})
                return []
            c = ctx.mid + n_p * (z0 - ctx.mid @ n_p)                    # the fan's centre, on the plate's front face
            slices = []
            for j in range(2 * n):
                a = math.radians(p["angle"]) + 2 * half * j
                d = Mp[:3, 0] * math.cos(a) + Mp[:3, 1] * math.sin(a)   # the way this half-slice points: its local x
                lab = f"R-{j + 1}"
                slices.append(Slice(lab, "R", frame(c, np.cross(d, n_p), up_hint=n_p), ctx.thickness_of(lab)))
            front = box(r, 0, BIG, BIG)
            hub = Point(*to_local(Mp, [c])[0]).buffer((slot_w + mf) / 2 / math.sin(half) + 0.5, 64)   # no tooth nearer the centre than this
            wall = 0.0
        else:
            labels, pos, th, drawn = self.planes(ctx, ax)
            slices = []
            for lab, z, tk in zip(labels, pos, th):
                o = ctx.mid + normal * (z + ctx.override("offset", lab))
                slices.append(Slice(lab, "S", frame(o + n_p * (z0 - o @ n_p), normal, up_hint=n_p), tk))   # local y = height above the plate
            front = box(-BIG, 0, BIG, BIG); hub = Polygon()
            ctx.cover_r = self.cover_r(ctx, pos, drawn, ctx.ext[ax], len(slices))
            wall = (min(np.diff(pos)) if len(pos) > 1 else BIG) - slot_w
        slices = ctx.keep(slices)
        self.profiles(ctx, slices)
        for sl in slices:
            sl.raw = as_multi(sl.raw.intersection(front))
        slices = [s for s in slices if not s.raw.is_empty]
        if not slices:
            return []
        if crossed:
            interlock([s for s in fams[0] if s in slices], [s for s in fams[1] if s in slices], ctx, a_open=tuple(n_p), b_open=tuple(-n_p))
        foot = to_local(Mp, ctx.mesh.vertices[depth >= z0 - 1e-9])     # the model in front of the plate, in the plate's x, y
        if p["plate"] == "file":
            try:
                if not p["plate_file"]:
                    raise ValueError("no file chosen: pick an SVG or DXF file, or another plate shape")
                shape, said = outlines(p["plate_file"])
            except ValueError as err:
                e = f"plate file: {err}"
                ctx.errors.append(e)
                ctx.fixes.append({"error": e, "options": [{"title": "use a rounded rectangle", "set": {"plate": "rounded"}}]})
                return []
            if said:
                ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, "plate file: " + ", ".join(said)] if x)
            # fitted round the model: the drawing's box covers the model's and the margin, its proportions kept
            (fx0, fy0), (fx1, fy1) = foot.min(0), foot.max(0); x0, y0, x1, y1 = shape.bounds
            f = max((fx1 - fx0 + 2 * p["plate_margin"]) / (x1 - x0), (fy1 - fy0 + 2 * p["plate_margin"]) / (y1 - y0))
            shape = affinity.scale(affinity.translate(shape, (fx0 + fx1 - x0 - x1) / 2, (fy0 + fy1 - y0 - y1) / 2), f, f, origin=((fx0 + fx1) / 2, (fy0 + fy1) / 2))
        elif p["plate"] == "silhouette":
            shape = silhouette(ctx.covered, Mp, p["plate_margin"])
        else:
            shape = outline(p["plate"], foot, p["plate_margin"])
        shape = self.placed(shape, p)
        plate = Slice("W-1", "W", Mp, plate_t); plate.raw = as_multi(shape)

        # teeth: every piece that stands on the plate, in every stretch where it does
        # Two neighbours' slots side by side leave a wall of plate as wide as the gap between the slices. Up to twice
        # the min feature that is a thin strip a tooth long, so every second slice's teeth sit a quarter step along,
        # beside the gaps of the slice before; under the min feature it is no wall, and a tooth still beside one of
        # the slice before is moved clear of it.
        close, tight = wall <= 2 * mf, wall < mf and not radial
        rim = shape.buffer(-mf).difference(hub)                         # a tooth keeps a wall from the plate's edge
        pieces, held, short, owner, beside = [], [], [], [], []
        for i, sl in enumerate(slices):
            mine, has, here = [], [], []
            for g in sl.raw.geoms:
                tt = self.teeth(p, sl, g, rim, Mp, plate_t, (0.25 if i % 2 else -0.25) if close else 0.0,
                                beside if tight else clash.get(sl.label, []), short)
                here += [(t[0].bounds[0], t[0].bounds[2]) for t in tt]
                for tooth, slot, pt in tt:
                    sl.links.append((plate.label, tooth, pt)); plate.links.append((sl.label, slot, pt))
                    plate.cuts.append(slot); owner.append(sl.label)
                # held: by its teeth, or in a crossed plaque by a slice of the other family slotted through it
                mine.append(unary_union([g, *[t[0] for t in tt]]) if tt else g); has.append(bool(tt) or any(g.intersects(c) for c in sl.cuts))
            pieces.append(mine); held.append(has); beside = here
        if short:
            ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, f"{len(short)} stretch(es) on the plate too short for {p['teeth']} teeth, "
                                                     f"given fewer ({', '.join(sorted(set(short))[:8])}): a narrower tooth width fits more"] if x)
        self.walls(ctx, plate.cuts, owner, mf)

        # floating pieces: each hangs from a piece beside it that is held, by the plate or by its own neighbour
        joins = {}                                                      # index of the lower slice → the overlaps to join across
        need = (p["dowel_d"] + 2 * mf) ** 2                             # an overlap with room for a spacer and its walls
        changed = p["layout"] == "parallel"   # a fan's neighbours stand at an angle, a crossed piece is held by what crosses it: no spacers
        while changed:
            changed = False
            for i in range(len(slices)):
                for j, g in enumerate(pieces[i]):
                    if held[i][j]:
                        continue
                    for nb in (i - 1, i + 1):
                        over = [g.intersection(h) for h, ok in zip(pieces[nb], held[nb]) if ok] if 0 <= nb < len(slices) else []
                        over = max(over, key=lambda o: o.area, default=None)
                        if over is not None and over.area >= need:
                            held[i][j] = changed = True
                            joins.setdefault(min(i, nb), []).append(over)
                            break
        joined = sum(len(v) for v in joins.values())
        # A piece in the middle of a chain takes spacers from both sides, and the first pair would spread its three over
        # the whole piece and leave the second none. Where two joins share a piece they share it out: one much smaller
        # than the other keeps its own area and the big one stays out of it; two of a size take a half each, along the
        # longer side — even pairs the low half, odd pairs the high one — so each has one compact area for its three.
        for i, overs in joins.items():
            beside = [c for k in (i - 1, i + 1) for c in joins.get(k, [])]
            for g in overs:
                for c in [c for c in beside if c.intersects(g)]:
                    if c.area < g.area / 2:
                        g = g.difference(c.buffer(mf))
                    elif c.area <= 2 * g.area:
                        x0, y0, x1, y1 = g.bounds; wide = x1 - x0 >= y1 - y0; xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
                        g = g.intersection(box(*((x0, y0, xm, y1) if wide else (x0, y0, x1, ym)) if i % 2 == 0 else
                                               ((xm, y0, x1, y1) if wide else (x0, ym, x1, y1))))
                if g.area >= need / 2:
                    ctx.joins.setdefault(slices[i].label, []).append(as_multi(g))
        loose = [(sl.label, g) for sl, gs, hs in zip(slices, pieces, held) for g, ok in zip(gs, hs) if not ok]
        if loose and p["floating"] == "join":
            pieces = [[g for g, ok in zip(gs, hs) if ok] for gs, hs in zip(pieces, held)]
            size = lambda g: f"{g.bounds[2] - g.bounds[0]:.0f} × {g.bounds[3] - g.bounds[1]:.0f} mm"   # noqa: E731
            ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, f"{len(loose)} floating piece(s) left out, no slice beside them can hold them: "
                                                     + ", ".join(f"{lab} ({size(g)})" for lab, g in loose[:12]) + ("…" if len(loose) > 12 else "")] if x)
        for sl, gs in zip(slices, pieces):
            sl.raw = as_multi(unary_union(gs)) if gs else as_multi(Polygon())
        slices = [s for s in slices if not s.raw.is_empty]
        if joined:
            ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, f"{joined} floating piece(s) hang from the slice beside them on spacers"] if x)
        extra = self.connect(ctx, slices) if ctx.joins else []
        few = sorted({sl.label for sl in slices for g in sl.raw.geoms if ctx.joins
                      and g.bounds[1] > -plate_t / 2 and 0 < sum(g.intersects(c) for c in sl.cuts) < 3})   # no tooth: it hangs
        if few:
            ctx.notes_extra = " · ".join(x for x in [ctx.notes_extra, f"{len(few)} floating piece(s) had room for fewer than 3 spacers and may turn or tilt "
                                                     f"({', '.join(few[:8])}{'…' if len(few) > 8 else ''}): a smaller spacer width fits more"] if x)
        return [plate] + self.in_order(slices, extra)

    @staticmethod
    def placed(shape, p):
        """The plate's outline sized, turned and moved as asked."""
        x0, y0, x1, y1 = shape.bounds; w, h = p["plate_size"]
        if w or h:
            fx = w / (x1 - x0) if w else h / (y1 - y0); fy = h / (y1 - y0) if h else fx
            shape = affinity.scale(shape, fx, fy)
        k = p["plate_scale"] / 100
        if k != 1 or p["plate_mirror"]:
            shape = affinity.scale(shape, -k if p["plate_mirror"] else k, k)
        if p["plate_rotation"]:
            shape = affinity.rotate(shape, p["plate_rotation"])
        return affinity.translate(shape, *p["plate_offset"])

    @staticmethod
    def teeth(p, sl, piece, rim, Mp, plate_t, turn, beside, short):
        """The teeth of one piece of a slice: (tooth in the slice's frame, its slot in the plate's frame, world point)
        for each. A stretch is where the piece stands on the plate, inside the plate's rim; each gets `teeth` teeth
        or more (one every `tooth_spacing`), evenly spread: the same step from tooth to tooth, half a step at each
        end. `turn` (± a quarter step) moves them all along, so that the teeth of two close neighbours do not sit side
        by side. `beside` are the teeth of the slice before this one, (from, to) along the slice, when the two are so
        close that slots side by side would touch: a tooth beside one of those moves along the slice by the least
        that clears it, a wall away, and is cut narrower where that is all that fits."""
        mf = p["min_feature"]; so = p["slot_offset"]; wmin = max(mf, 2.0); tw = p["tooth_width"]; out = []; wall = mf + so
        x0, _, x1, _ = piece.bounds
        for seg in as_lines(piece.intersection(LineString([(x0 - 1, 0.02), (x1 + 1, 0.02)]))).geoms:
            on_plate = LineString(to_local(Mp, to_world(sl.M, [c[:2] for c in seg.coords]))).intersection(rim)
            for part in as_lines(on_plate).geoms:
                a, b = sorted(to_local(sl.M, to_world(Mp, [c[:2] for c in part.coords]))[:, 0])
                L = b - a
                n = max(p["teeth"], math.ceil(L / p["tooth_spacing"]) if p["tooth_spacing"] else 0)
                width = lambda n, L=L: min(tw, L / (2 * n))                               # noqa: E731 — teeth take half the stretch at most
                while n > 1 and width(n) < wmin:
                    n -= 1
                w = width(n) if n > 1 else min(tw, L)
                spots = []
                for c in ([a + L * (i + 0.5 + turn) / n for i in range(n)] if w >= wmin else []):
                    for ww in (w, wmin):                                                   # narrower before nowhere
                        free = lambda c, ww=ww, a=a, b=b, spots=spots: (a + ww / 2 <= c <= b - ww / 2            # noqa: E731
                                                 and all(c + ww / 2 + wall <= lo or c - ww / 2 - wall >= hi for lo, hi in beside)
                                                 and all(abs(c - c2) >= (ww + w2) / 2 + wall for c2, w2 in spots))
                        near = sorted((q for lo, hi in beside for q in (lo - wall - ww / 2, hi + wall + ww / 2) if free(q)), key=lambda q, c=c: abs(q - c))
                        if free(c) or near:
                            spots.append((c if free(c) else near[0], ww)); break
                if spots and len(spots) < p["teeth"]:
                    short.append(sl.label)
                for c, w in spots:
                    hw, ht = (w + so) / 2, (sl.thickness + so) / 2
                    edge = [(c - hw, -plate_t / 2), (c + hw, -plate_t / 2)]
                    slot = Polygon([*to_local(Mp, to_world(sl.M, edge, -ht)), *to_local(Mp, to_world(sl.M, edge[::-1], ht))])
                    out.append((box(c - w / 2, -plate_t, c + w / 2, 0.02), slot, tuple(to_world(sl.M, [(c, -plate_t / 2)])[0])))
        return out

    @staticmethod
    def walls(ctx, slots, owner, mf):
        """Two plate slots with less than min_feature of plate between them: the plate would tear there, or fall into
        strips. Said once, with the slices of the closest pair."""
        if len(slots) < 2:
            return
        tree = STRtree(slots)
        a, b = tree.query(slots, predicate="dwithin", distance=mf - 1e-6)
        pairs = [(i, j) for i, j in zip(a, b) if i < j]
        if pairs:
            i, j = min(pairs, key=lambda q: slots[q[0]].distance(slots[q[1]]))
            ctx.errors.append(f"{len(pairs)} pair(s) of plate slots are less than {mf:g} mm apart — the plate would break between them "
                              f"(closest: {owner[i]} and {owner[j]}, {slots[i].distance(slots[j]):.1f} mm): more space between the "
                              f"slices, fewer or narrower teeth, or a lower min_feature")

    # ---------------------------------------------------------------- stacked's connectors, for floating pieces only
    def points_for_pair(self, ctx, a, b, i, d, margin, taken):
        return []

    def islands(self, ctx, a, b):
        return ctx.joins.get(a.label, [])

    def seeds(self, parts):
        """The first spacer of a floating piece goes at its edge, not its middle: the next two then go as far from it
        and from each other as the piece allows, and the three hold a plane."""
        out = []
        for g in parts:
            c = np.array(g.centroid.coords[0]); xy = np.array(g.exterior.coords)
            far = xy[np.argmax(np.hypot(*(xy - c).T))]
            out.append(tuple(far + (c - far) * min(1.0, 0.3 / max(1e-9, np.hypot(*(c - far))))))   # a hair in from the room's edge
        return out

    @staticmethod
    def _said(p, skipped, bare, rooms, margin, d):
        return []                                # a floating piece that found no room for a spacer is said by the checks
