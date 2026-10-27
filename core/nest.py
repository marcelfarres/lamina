"""Polygon nesting with no-fit polygons, after Deepnest (Jack Qiao, github.com/Jack000/Deepnest, MIT) and its
predecessor SVGnest. For the next part, the positions where it would overlap a placed part are that part's no-fit
polygon: the Minkowski sum of the placed outline and the negated new one. The positions where it stays on the sheet
are the inner-fit rectangle. The rectangle minus the union of the no-fit polygons is the free region, and the part
goes to its lowest, then leftmost, vertex: it slides into concavities and holes, where a corner search only tries the
corners of bounding boxes. Deepnest computes the Minkowski sum with Clipper; here each outline is cut into convex
pieces (constrained Delaunay triangles merged while they stay convex) and the sum is the union of the hulls of the
piece pairs, which shapely does. Parts are placed one by one, largest first, each tried at its minimum-rectangle
angle plus quarter turns (with `grain`, as it stands or upside down); labels afterwards, in free space next to each
part, with a leader line.

Not taken from Deepnest: its genetic algorithm over the part order and rotations (minutes of search for a few
percent of sheet) and its merging of shared cut lines.
"""
from __future__ import annotations
import math
import sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import shapely
from shapely import affinity
from scipy.ndimage import binary_erosion, distance_transform_edt
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import nearest_points, split, unary_union
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree
from .geometry import as_multi, fit_on_part, label_angles, label_box, label_rect, mark_box, mark_rot, min_rect_angle, robust, widest_spot

ROTS = (0, 90, 180, 270)
# A part's rotations on one sheet are independent, and their no-fit union, the costliest call of a slice, runs in GEOS
# with the GIL let go: side by side it was 2.0–2.7× faster (cow_spot, bunny, bowl). The browser build has no threads.
each = map if sys.platform == "emscripten" else ThreadPoolExecutor(len(ROTS), thread_name_prefix="nest").map


def _bounds(pts):
    """x0, y0, x1, y1 of a point array."""
    return (*pts.min(0), *pts.max(0))
CELL = 2.0       # mm: the raster of a sheet that says which parts cannot fit it (Sheet.room)
PIECES = 16         # convex pieces a placed part may cost the no-fit polygons; past that it is its hull (see _convex_pieces)
TOL = 0.5           # mm: the nesting outline is grown by this and simplified by this, so the parts never come closer
                    # than the gap and rarely more than the gap plus TOL
POCKET = 2.0        # mm: the convex pieces of an outline may overrun its concavities by this, so a part nested in a
                    # pocket keeps up to this much more than the gap to the pocket wall; a concave arc needs a chord
                    # every 2·sqrt(2·radius·POCKET), which is what the count of pieces, and the nesting time, follow


def _put(pc, sheet_i, rot, dx, dy, at=None):
    """The piece placed: on sheet `sheet_i`, turned `rot` and moved by (dx, dy), its outline, lines and marks moved
    with it. `place` says where it sits — its corner, or `at` where the caller means a spot (the margin)."""
    T = lambda g: affinity.translate(affinity.rotate(g, rot, origin=(0, 0)), dx, dy)
    geom = as_multi(T(pc.kerfed))
    pc.placed, pc.placed_lines, pc.placed_marks = geom, [(s, T(l)) for s, l in pc.lines], [(*T(Point(m[0], m[1])).coords[0], m[2], mark_rot(m)) for m in pc.marks]
    pc.place = (sheet_i, *(at or geom.bounds[:2]), rot)
    return geom


def _hull(geom):
    return np.asarray(orient(geom.convex_hull).exterior.coords)[:-1]       # counter-clockwise, closing point dropped


def _fill_small_holes(geom, area):
    """`geom` with every hole smaller than `area` filled: nothing to nest fits in them, and each costs the
    decomposition a cut."""
    return as_multi(MultiPolygon([Polygon(g.exterior, [r for r in g.interiors if Polygon(r).area >= area]) for g in as_multi(geom).geoms]))


def _convex_pieces(geom, tol, cap, coarse=False):
    """`_pieces` below, and its hull alone when the engine fails on the way (see geometry.robust)."""
    out = robust(lambda q: _pieces(q, tol, cap, coarse), geom)
    return out if out is not None else [_hull(geom)]


def _pieces(geom, tol, cap, coarse=False):
    """Convex pieces whose union covers geom and overruns it by at most `tol` (an approximate convex decomposition):
    each piece is split at its deepest notch, along the bisector of the notch, until the hull of every piece is
    within `tol` of it. Holes are notches too, so a ring becomes a few wedges around an open middle. Coordinate
    arrays, one hull each. More than `cap` pieces and the answer is coarse: the hull round the outside (the no-fit
    polygons cost a ring per piece of every placed part, and a scanned outline with dozens of shallow pockets is not
    worth that) with each hole kept as the largest disc it holds — convex, and inside the hole, so the wedges between
    hull and disc still cover every bit of material — and a hollow slice's middle stays open to the small parts."""
    out, todo = [], list(as_multi(geom).geoms)
    while todo:
        if len(out) + len(todo) > cap:
            if coarse:
                return [_hull(geom)]
            discs = []
            for g in as_multi(geom).geoms:
                for r in g.interiors:
                    c = robust(lambda q: shapely.maximum_inscribed_circle(q, tol), Polygon(r))
                    if c is not None and c.length > 2 * tol:
                        discs.append(Point(c.coords[0]).buffer(c.length * 0.98, 4).exterior)
            return _pieces(Polygon(geom.convex_hull.exterior, discs), tol, cap, coarse=True) if discs else [_hull(geom)]
        p = todo.pop()
        hull = p.convex_hull
        deepest = None
        for k, ring in enumerate((p.exterior, *p.interiors)):
            c = np.asarray(ring.coords)[:-1]
            d = shapely.distance(hull.exterior, shapely.points(c))
            j = int(np.argmax(d))
            if deepest is None or d[j] > deepest[0]:
                deepest = (d[j], c, j, k > 0)
        depth, c, j, in_hole = deepest
        if depth <= tol:
            out.append(_hull(p)); continue
        v = c[j]; u = [c[j - 1] - v, c[(j + 1) % len(c)] - v]
        u = [e / np.hypot(*e) for e in u]
        into = -(u[0] + u[1])                                 # the bisector of the notch, pointing into the part
        if np.hypot(*into) < 1e-9:
            into = np.array([-u[0][1], u[0][0]])
        into /= np.hypot(*into)
        if not p.contains(Point(*(v + into * 1e-6))):
            into = -into
        span = math.hypot(*(np.subtract(hull.bounds[2:], hull.bounds[:2])))
        t = (shapely.get_coordinates(p.boundary.intersection(LineString([v - into * span, v + into * span]))) - v) @ into
        ahead, behind = t[t > 1e-6], -t[t < -1e-6]
        # Ahead, to the first boundary the bisector meets. From a hole, one chord to the outside is a bridge that
        # does not cut, so the cut also runs back across the hole and through the far wall (the second hit behind).
        t0, t1 = (np.sort(behind)[1] if len(behind) > 1 else None) if in_hole else 0.0, ahead.min() if len(ahead) else None
        halves = [] if t0 is None or t1 is None else [q for q in split(p, LineString([v - into * (t0 + 1e-6), v + into * (t1 + 1e-6)])).geoms if q.area > 1e-9]
        if len(halves) < 2:                                   # no cut found: the hull, which is safe, just coarse
            out.append(_hull(p)); continue
        todo += halves
    return out


def _rot(pieces, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    R = np.array([[c, s], [-s, c]])                       # p @ R turns each row counter-clockwise, like affinity.rotate
    return [p @ R for p in pieces]


def _edges(c):
    """A convex, counter-clockwise piece ready for Minkowski sums: its edges in ring order from the one of smallest
    angle, their angles, and the vertex that edge starts from. An edge horizontal to within rounding is angle 0, never
    2π: a hull with two collinear edges along its top, negated, had one at 0 and the other at 2π, so sorting by angle
    put them at opposite ends of the ring, and every no-fit polygon of that part came out a wrong shape — parts were
    nested on top of each other, up to 773 mm² (found by the validation sweep)."""
    e = np.roll(c, -1, 0) - c
    keep = np.hypot(e[:, 0], e[:, 1]) > 1e-12
    c, e = c[keep], e[keep]
    ang = np.arctan2(e[:, 1], e[:, 0]) % (2 * np.pi)
    ang[ang > 2 * np.pi - 1e-9] = 0.0
    k = int(np.argmax(np.roll(ang, 1) - ang))                # where the ring's angles wrap from largest to smallest
    return c[k], np.roll(e, -k, 0), np.roll(ang, -k)


def _minkowski(A, b):
    """Convex ⊕ convex for every piece of A with the piece b, from their `_edges`: from the sum of the lowest points,
    the edges of both merged by angle. One sort for all the pairs; the rings come back as one polygon array."""
    sizes = np.array([len(a[1]) + len(b[1]) for a in A])
    seg = np.repeat(np.arange(len(A)), sizes)
    e = np.concatenate([np.concatenate([a[1], b[1]]) for a in A])
    ang = np.concatenate([np.concatenate([a[2], b[2]]) for a in A])
    e = e[np.lexsort((ang, seg))]
    before = np.cumsum(e, 0) - e                            # sum of the edges before each one, over all segments
    starts = np.cumsum(sizes) - sizes
    pts = before - np.repeat(before[starts], sizes, 0) + np.repeat([a[0] + b[0] for a in A], sizes, 0)
    return shapely.polygons(shapely.linearrings(pts, indices=seg))


LONG = 4            # a sheet taller than this many times its width is a `one_sheet` strip, not a sheet (see Sheet)


class Sheet:
    """Parts already placed on one sheet: their grown outlines (for the labels) and convex pieces (for the no-fit polygons)."""
    def __init__(self, W, H, margin):
        self.W, self.H, self.margin = W, H, margin
        self.placed, self.pieces, self.convex = [], [], []
        # A raster of the sheet, CELL wide, a cell blocked when a placed part covers it whole, and the radius of the
        # largest disc the free cells hold (a distance transform): a part whose hull holds a bigger disc cannot fit,
        # and is not searched for a spot, which costs a union per rotation. A blocked frame stands for the margin.
        # It is only ever a shortcut, so a `one_sheet` strip (100 m long: fifteen million cells, transformed again
        # for every part placed — 40 minutes for 400 parts) does without it and answers "yes, there is room", which
        # on a strip that long is also the truth.
        self.blocked = None
        if H <= LONG * W:
            self.blocked = np.ones((int(H / CELL) + 3, int(W / CELL) + 3), bool)
            self.blocked[self.cell(margin):self.cell(H - margin) + 1, self.cell(margin):self.cell(W - margin) + 1] = False
            self.room_r = distance_transform_edt(~self.blocked).max() * CELL

    def cell(self, v):
        return int(v / CELL) + 1

    def add(self, geom, pc, convex=()):
        self.placed.append(geom); self.pieces.append(pc)
        self.convex += [_edges(p) for p in convex]
        if self.blocked is None:
            return
        x0, y0, x1, y1 = geom.bounds
        ny, nx = self.blocked.shape                                       # a part too big for the sheet sticks out
        r0, r1, c0, c1 = max(self.cell(y0), 0), min(self.cell(y1) + 1, ny), max(self.cell(x0), 0), min(self.cell(x1) + 1, nx)
        if r1 <= r0 or c1 <= c0:
            return
        ys, xs = np.mgrid[r0:r1, c0:c1] * CELL - CELL / 2                 # cell centres
        inside = shapely.contains_xy(geom, xs, ys)
        self.blocked[r0:r1, c0:c1] |= binary_erosion(inside)              # only cells whose neighbours are inside too
        self.room_r = distance_transform_edt(~self.blocked).max() * CELL

    def room(self, r):
        return self.blocked is None or r <= self.room_r + 1.5 * CELL

    def spot(self, pieces, bounds):
        """Lowest, then leftmost, position of a part's origin where it fits, touching allowed, or None: the inner-fit
        rectangle (the sheet inside the margin, less the part's extent) minus the no-fit polygons of the placed parts.
        A no-fit polygon, the positions of the part's origin where it overlaps a placed one, is the placed outline ⊕
        the negated part: the union of the Minkowski sums of the convex pieces, pairwise."""
        bx0, by0, bx1, by1 = bounds
        x0, y0, x1, y1 = self.margin - bx0, self.margin - by0, self.W - self.margin - bx1, self.H - self.margin - by1
        if x1 < x0 or y1 < y0:
            return None
        free = box(x0, y0, x1 + 1e-9, y1 + 1e-9)          # a hair wide even when the part exactly spans the sheet
        if self.convex:
            free = free.difference(shapely.union_all(np.concatenate([_minkowski(self.convex, _edges(-p)) for p in pieces])))
        if free.is_empty:
            return None
        c = shapely.get_coordinates(free)
        return c[np.lexsort((c[:, 0], c[:, 1]))[0]]


MANY = 150          # above this many pieces the rectangle packer takes over (see nest)


def _rect_nest(prepared, sheet, gap, margin, grain=False):
    """Rectangle packing of the parts' minimum bounding boxes — the path for many pieces. Above `MANY` parts the
    polygon nesting is far slower (quadratic in the part count) and, measured on 200 and 400 identical crescents with
    the corner search it replaced, packed no tighter, so the count is the gate. Skyline rather than MaxRects:
    MaxRects de-duplicates its free-rectangle list on every insert, which is quadratic in the part count. With `grain`
    no part is turned."""
    from rectpack import newPacker, SkylineBlWm, PackingMode, PackingBin, SORT_AREA
    W, H = sheet[0] - 2 * margin, sheet[1] - 2 * margin
    packer = newPacker(mode=PackingMode.Offline, bin_algo=PackingBin.BFF, pack_algo=SkylineBlWm, sort_algo=SORT_AREA, rotation=not grain)
    dims = []
    for i, (pc, rot0) in enumerate(prepared):
        x0, y0, x1, y1 = affinity.rotate(pc.nest_shape, rot0, origin=(0, 0)).bounds
        w, h = x1 - x0 + gap, y1 - y0 + gap
        dims.append((w, h))
        if (w <= W + gap and h <= H + gap) or (not grain and h <= W + gap and w <= H + gap):
            packer.add_rect(w, h, i)
    packer.add_bin(W + gap, H + gap, count=float("inf"))
    packer.pack()
    sheets, done = {}, set()
    for b, x, y, w, h, i in packer.rect_list():
        pc, rot0 = prepared[i]
        w0, h0 = dims[i]
        rot = rot0 + (90 if abs(w - h0) < 1e-6 and abs(h - w0) < 1e-6 and abs(w0 - h0) > 1e-6 else 0)
        g = affinity.rotate(pc.nest_shape, rot, origin=(0, 0))
        # each rectangle is the part plus one gap, in a bin one gap wider than the sheet inside its margins: the part
        # sits at the rectangle's corner, so the gap falls between neighbours and the last one ends at the margin.
        # Centred in its rectangle, every part on the far edges ran half a gap into the margin.
        _put(pc, b, rot, margin + x - g.bounds[0], margin + y - g.bounds[1])
        sheets.setdefault(b, Sheet(sheet[0], sheet[1], margin)).add(affinity.translate(g, margin + x - g.bounds[0], margin + y - g.bounds[1]), pc)
        done.add(i)
    n = max(sheets) + 1 if sheets else 0
    for i, (pc, rot0) in enumerate(prepared):                  # bigger than a whole sheet (already flagged)
        if i not in done:
            g = affinity.rotate(pc.kerfed, rot0, origin=(0, 0))
            geom = _put(pc, n, rot0, margin - g.bounds[0], margin - g.bounds[1], at=(margin, margin))
            sheets.setdefault(n, Sheet(sheet[0], sheet[1], margin)).add(geom, pc); n += 1
    return [sheets[k] for k in sorted(sheets)]


def nest(pieces, sheet, gap, margin, kerf=0.0, labels=False, font=4.0, tag="", place="part", grain=False):
    """Sets piece.place, .kerfed, .placed(+lines, marks), .label_pos, .leader. Returns sheet count.

    One sheet is one stock thickness. A part whose thickness was changed is cut from another piece of material, so
    it gets sheets of its own rather than sharing one and being cut from the wrong stock. With `grain` every part
    keeps its own frame's x along the sheet's width, turned 0° or 180° only, so the grain runs one way on all of them."""
    by_thick = {}
    for pc in pieces:
        by_thick.setdefault(round(pc.parent.thickness, 6), []).append(pc)
    if len(by_thick) < 2:
        return _nest(pieces, sheet, gap, margin, kerf, labels, font, tag, place, grain)
    n = 0
    for t in sorted(by_thick):
        group = by_thick[t]
        used = _nest(group, sheet, gap, margin, kerf, labels, font, tag, place, grain)
        for pc in group:
            pc.place = (pc.place[0] + n, *pc.place[1:])      # each group numbered after the ones before it
        n += used
    return n


def _nest(pieces, sheet, gap, margin, kerf, labels, font, tag, place, grain):
    k = kerf / 2
    prepared = []
    for pc in pieces:
        pc.kerfed = as_multi(pc.geom.buffer(k, join_style=2)) if k else pc.geom
        pc.nest_shape = pc.kerfed
        if labels and place != "on":
            # A part too small to carry even its bare name is nested with the room for that name reserved above it,
            # so the label can sit right beside the part instead of wherever the packed sheet leaves a gap. The
            # reserve is only ever a hole the nester keeps; the part's own outline is what is cut and labelled.
            w, h = label_box(pc.label, font * 0.65)                           # the least the part could carry
            keep = [mark_box(*m[:3], font, mark_rot(m)) for m in pc.marks] + [ln.buffer(0.8) for s, ln in pc.lines if s == "orient"]
            if fit_on_part(pc.kerfed, [ln for s, ln in pc.lines if s == "guide"], w, h, keep, label_angles(pc.kerfed), room=min(2.0, 0.3 * font * 0.65)) is None:
                x0, y0, x1, y1 = pc.kerfed.bounds; cx = (x0 + x1) / 2
                pc.nest_shape = as_multi(unary_union([pc.kerfed, box(cx - w / 2, y1 + 1.0, cx + w / 2, y1 + 1.0 + h)]))
        prepared.append((pc, 0.0 if grain else min_rect_angle(pc.nest_shape)))
    sheets = _rect_nest(prepared, sheet, gap, margin, grain) if len(prepared) > MANY else _poly_nest(prepared, sheet, gap, margin, grain)
    if len(prepared) <= MANY and len(sheets) > 1:
        # the polygon nest fills bottom-left and lets a round part drop into the valley between two below it, which
        # can cost a whole column (seven rings: five and two, where three and three would do); the plain rectangle
        # packing is tried as well and kept when it takes fewer sheets, or as many with less on its emptiest one
        # (seven rings: five and two, where six and one would do — the first sheet full, the last for the rest). The
        # parts' own areas are compared: the polygon nest keeps grown outlines, and a part too big for the sheet
        # takes a sheet of its own in a different place in each nest's order. Each nest writes every piece's
        # placement, so the polygon one is put back when it stays: labels are placed against the outlines the
        # pieces really have
        kept = [(pc.place, pc.placed, pc.placed_lines, pc.placed_marks) for pc, _ in prepared]
        rect = _rect_nest(prepared, sheet, gap, margin, grain)
        least = lambda ss: min(sum(pc.kerfed.area for pc in sh.pieces) for sh in ss)
        if len(rect) < len(sheets) or (len(rect) == len(sheets) and least(rect) < least(sheets)):
            sheets = rect
        else:
            for (pc, _), was in zip(prepared, kept):
                pc.place, pc.placed, pc.placed_lines, pc.placed_marks = was
    if labels:
        for sh in sheets:
            place_labels(sh, font, tag, place)
    return max(1, len(sheets))


def _poly_nest(prepared, sheet, gap, margin, grain=False):
    """Every part on the first sheet with room for it, at the lowest-left spot of its free region (see the module
    docstring), largest first; a part bigger than a sheet takes the sheet it lands on to itself."""
    W, H = sheet; half = gap / 2
    rots = (0, 180) if grain else ROTS
    order = sorted(range(len(prepared)), key=lambda i: -prepared[i][0].kerfed.area)
    grown_all = [pc.nest_shape.buffer(half + TOL, join_style=1) for pc, _ in prepared]   # half the gap on each part keeps them the gap apart
    # a hole no part could go in — a dowel hole, a slot: smaller than the smallest part with its share of the gap — is
    # filled before the outline is cut into convex pieces: each hole is a notch to that cut, and a stacked slice with
    # thirty dowel holes blew past the piece cap and became its hull, which covered the big hollow in its middle
    # that the small parts should have gone into
    least = min(g.area for g in grown_all) if grown_all else 0.0
    sheets = [Sheet(W, H, margin)]
    for i in order:
        pc, rot0 = prepared[i]
        grown = _fill_small_holes(grown_all[i], least)
        # Douglas-Peucker, not the topology-preserving simplifier: GEOS 3.12 — the one Pyodide ships, so the browser
        # build — now and then throws "orientationIndex encountered NaN" from that one on a perfectly finite outline
        # (it reads memory it never wrote; the desktop's GEOS 3.13 does not). Both keep every point within TOL, which
        # the buffer above already allows for; a shape that comes out invalid keeps its full outline — slower, never wrong.
        thin = grown.simplify(TOL, preserve_topology=False)
        grown = thin if thin.is_valid and not thin.is_empty else grown
        convex = _convex_pieces(grown, POCKET, PIECES)
        turned = {r: _rot(convex, rot0 + r) for r in rots}
        # ponytail: the part on its way in is its convex hull, the placed ones their pieces, so the no-fit polygons
        # cost pieces × 1 rings, not pieces × pieces: a part slides into a placed part's cavity or hole, but not its
        # own cavity around a placed part's bulge. Pass turned[r] to spot() for that, at the quadratic cost.
        hull = {r: _rot([_hull(grown)], rot0 + r) for r in rots}
        disc = shapely.maximum_inscribed_circle(grown.convex_hull, TOL).length
        best = None
        for sh in sheets + [None]:                                # first sheet it fits on
            if sh is None:
                sh = Sheet(W, H, margin); sheets.append(sh)
            if not sh.room(disc):
                continue
            box_of = {r: _bounds(np.concatenate(turned[r])) for r in rots}
            spots = each(sh.spot, [hull[r] for r in rots], [box_of[r] for r in rots])   # side by side, scored in order
            for r, xy in zip(rots, spots):
                bounds = box_of[r]
                if xy is None:
                    continue
                score = (xy[1] + bounds[3], xy[0] + bounds[2])    # lowest top, then leftmost right edge
                if best is None or score < best[0]:
                    best = (score, r, float(xy[0]), float(xy[1]))
            if best is not None:
                break
        if best is None:        # bigger than one sheet (already flagged), or filling one so exactly the gap tips it over
            # where the part's corner lands once it is turned: the unturned outline's corner put a 586 × 390 mm panel
            # 485 mm off a 600 × 400 sheet, with nothing said
            b = affinity.rotate(pc.kerfed, rot0, origin=(0, 0)).bounds
            dx, dy = margin - b[0], margin - b[1]
            _put(pc, len(sheets) - 1, rot0, dx, dy, at=(margin, margin))
            # with its convex pieces, like any other part: without them the sheet reads as empty and the next parts
            # are nested on top of it — the oversize part overhangs the sheet, it does not share it
            sh.add(affinity.translate(affinity.rotate(grown, rot0, origin=(0, 0)), dx, dy), pc, [p + (dx, dy) for p in turned[0]])
            continue
        _, r, x, y = best
        _put(pc, sheets.index(sh), rot0 + r, x, y)
        sh.add(affinity.translate(affinity.rotate(grown, rot0 + r, origin=(0, 0)), x, y), pc, [p + (x, y) for p in turned[r]])
    return sheets


def place_labels(sh, font, tag="", place="part"):
    """Every part's label. `place` = "part": on the part itself where the whole label fits on its material — inside
    the next layer's outline where the piece carries one (the stacked "engrave next layer" guide), so the layer glued
    on top hides it, upright or turned along the part, clear of its marks and arrows — else beside the part in free
    space, with a leader line to its outline; "beside": always beside; "on": always on the part. Free space is space
    inside the sheet margin that no part (at the nesting gap), no earlier label and no leader line crosses, searched
    outward from the part's outline, above it first. A label with no room at the job's font is tried smaller, down to
    half, before it is put on the part's widest spot anyway, past its outline if it must, for the maker to trim in the
    laser software — counted (`crowded`) so the plan can say so. The one thing that never happens is a part coming
    out with no label at all."""
    text = lambda pc, short=False: f"{tag} {pc.label}" if tag and not short else pc.label   # `tag`: the model's short name first
    for g in sh.placed:
        shapely.prepare(g)
    tree = STRtree(sh.placed)
    taken = []
    for k, pc in enumerate(sh.pieces):
        keep = [mark_box(x, y, t, font, rot + pc.place[3]) for x, y, t, rot in pc.placed_marks] \
            + [ln.buffer(0.8) for s, ln in pc.placed_lines if s == "orient"]
        guides = [ln for s, ln in pc.placed_lines if s == "guide"]
        angles = label_angles(pc.placed) if place != "beside" else ()
        pc.crowded = False
        sizes = [font * sc for sc in (1.0, 0.8, 0.65)]
        # what may be engraved, best first: the full label at the font or a little under, then — a small part — the
        # part's name alone, without the model's short name, which the assembly key allows for
        forms = [(size, False) for size in sizes[:2]] + ([(size, True) for size in sizes[:2]] if tag else []) + [(sizes[2], False)] + ([(sizes[2], True)] if tag else [])
        spot = None
        if place != "beside":                                       # on the part
            for size, short in forms:                             # down to two thirds of the font: a peg's name along the peg
                w, h = label_box(text(pc, short), size)
                spot = fit_on_part(pc.placed, guides, w, h, keep, angles, room=0.0 if place == "on" else min(2.0, 0.3 * size))
                if spot:
                    break
        if spot is None and place == "on":
            size, short = forms[-1]; spot = widest_spot(pc.placed)
        if spot:
            pc.label_pos, pc.leader, pc.label_size, pc.label_short = spot, None, size, short
            taken.append(label_rect(*spot, *label_box(text(pc, short), size)))
            continue
        # beside the part: the nearest free spot wins, a smaller or shorter label close by over a full one far away;
        # then free space anywhere on the sheet with a line across whatever lies between, rather than on a part the
        # label would overrun, where it reads as part of the cut
        boxes = [(size, short, *label_box(text(pc, short), size)) for size, short in forms]
        found = _beside(k, pc, boxes, sh, tree, taken) or _beside(k, pc, boxes[2:], sh, tree, taken, across=True)
        if found:
            (pc.label_pos, pc.leader, rect), (pc.label_size, pc.label_short) = found[:3], found[3]
            taken.append(rect)
        else:                                                       # nowhere at all: the widest spot, counted
            size, short = forms[-1]
            pc.label_pos, pc.leader, pc.label_size, pc.label_short, pc.crowded = widest_spot(pc.placed), None, size, short, True
            taken.append(label_rect(*pc.label_pos, *label_box(text(pc, short), size)))


def _beside(k, pc, boxes, sh, tree, taken, across=False):
    """A free spot for a label beside part k, at the first of `boxes` — (size, short, w, h), best first — that has one
    on the nearest ring: ((x, y, rot), leader, rect, (size, short)) or None. Candidates lie on rings round the part's nested
    outline at growing distances, above the part first, the label upright or on its side, its near edge on the ring;
    a candidate is free when its box lies inside the sheet margin and touches no part, no label placed before it,
    and the leader from it to the part's own outline crosses no other part — unless `across`, the last resort, which
    lets the leader run over other parts and searches the whole sheet."""
    part = pc.placed.simplify(0.5)                          # the real outline: the nesting one may hold the room reserved for this label
    W, H, m = sh.W, sh.H, sh.margin
    x0, y0, x1, y1 = pc.placed.bounds; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for d in (0.8, 2.0, 3.5, 6.0, 10.0, 15.0, 22.0, 32.0, 45.0, 60.0, 85.0, 120.0) + ((170.0, 240.0, 340.0) if across else ()):
        pts = []
        for ring in (g.exterior for g in as_multi(part.buffer(d, join_style=1)).geoms):
            n = max(12, int(ring.length / max(4.0, min(h for *_, h in boxes) / 2)))
            pts += [ring.interpolate(i / n, normalized=True) for i in range(n)]
        pts.sort(key=lambda q: abs((math.degrees(math.atan2(q.y - cy, q.x - cx)) - 90 + 180) % 360 - 180))   # above first, below last
        for size, short, w, h in boxes:
            for p in pts:
                q = nearest_points(pc.placed, p)[0]                                   # where the leader lands: the part's own outline
                nx, ny = p.x - q.x, p.y - q.y; L = math.hypot(nx, ny)
                if L < 1e-6:
                    continue
                nx, ny = nx / L, ny / L
                for rot in (0, 90):
                    bw, bh = (w, h) if rot == 0 else (h, w)
                    reach = abs(nx) * bw / 2 + abs(ny) * bh / 2                     # the box's near edge sits on the ring
                    lx, ly = p.x + nx * reach, p.y + ny * reach
                    rect = box(lx - bw / 2, ly - bh / 2, lx + bw / 2, ly + bh / 2)
                    rx0, ry0, rx1, ry1 = rect.bounds
                    mm = 0.0 if across else m                       # the last resort may use the margin band, as the title does
                    if rx0 < mm or ry0 < mm or rx1 > W - mm or ry1 > H - mm:
                        continue
                    if rect.intersects(pc.placed) or any(i != k and sh.placed[i].intersects(rect) for i in tree.query(rect)) or any(rect.intersects(t) for t in taken):
                        continue
                    line = LineString([(lx, ly), (q.x, q.y)])
                    if not across and any(i != k and sh.placed[i].intersects(line) for i in tree.query(line)):
                        continue
                    start = rect.exterior.intersection(line)                           # the leader leaves the label at its edge
                    start = start.geoms[0] if start.geom_type.startswith("Multi") else start
                    sx, sy = start.coords[0] if not start.is_empty else (lx, ly)
                    return (lx, ly, rot), ((sx, sy), (q.x, q.y)), rect, (size, short)
    return None
