"""Polygon nesting with no-fit polygons, after Deepnest (Jack Qiao, github.com/Jack000/Deepnest, MIT) and its
predecessor SVGnest. For the next part, the positions where it would overlap a placed part are that part's no-fit
polygon: the Minkowski sum of the placed outline and the negated new one. The positions where it stays on the sheet
are the inner-fit rectangle. The rectangle minus the union of the no-fit polygons is the free region, and the part
goes to its lowest, then leftmost, vertex: it slides into concavities and holes, where a corner search only tries the
corners of bounding boxes. Deepnest computes the Minkowski sum with Clipper; here each outline is cut into convex
pieces (constrained Delaunay triangles merged while they stay convex) and the sum is the union of the hulls of the
piece pairs, which shapely does. Parts are placed one by one, largest first, each tried at its minimum-rectangle
angle plus quarter turns; labels afterwards, in free space next to each part, with a leader line.

Not taken from Deepnest: its genetic algorithm over the part order and rotations (minutes of search for a few
percent of sheet) and its merging of shared cut lines.
"""
from __future__ import annotations
import math
import numpy as np
import shapely
from shapely import affinity
from scipy.ndimage import binary_erosion, distance_transform_edt
from shapely.geometry import LineString, Point, box
from shapely.ops import split
from shapely.strtree import STRtree
from .geometry import as_multi

ROTS = (0, 90, 180, 270)
CELL = 2.0          # mm: the raster of a sheet that says which parts cannot fit it (Sheet.room)
PIECES = 16         # convex pieces a placed part may cost the no-fit polygons; past that it is its hull (see _convex_pieces)
TOL = 0.5           # mm: the nesting outline is grown by this and simplified by this, so the parts never come closer
                    # than the gap and rarely more than the gap plus TOL
POCKET = 2.0        # mm: the convex pieces of an outline may overrun its concavities by this, so a part nested in a
                    # pocket keeps up to this much more than the gap to the pocket wall; a concave arc needs a chord
                    # every 2·sqrt(2·radius·POCKET), which is what the count of pieces, and the nesting time, follow


def _min_rect_angle(geom):
    r = geom.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return 0.0
    c = np.asarray(r.exterior.coords); e = c[1:] - c[:-1]
    i = int(np.argmax(np.hypot(e[:, 0], e[:, 1])))
    return -math.degrees(math.atan2(e[i, 1], e[i, 0]))


def _xf(pc, rot, dx, dy):
    T = lambda g: affinity.translate(affinity.rotate(g, rot, origin=(0, 0)), dx, dy)
    return as_multi(T(pc.kerfed)), [(s, T(l)) for s, l in pc.lines], [(*T(Point(x, y)).coords[0], t) for x, y, t in pc.marks]


def _hull(geom):
    return _ccw(np.asarray(geom.convex_hull.exterior.coords)[:-1])


def _convex_pieces(geom, tol, cap):
    """Convex pieces whose union covers geom and overruns it by at most `tol` (an approximate convex decomposition):
    each piece is split at its deepest notch, along the bisector of the notch, until the hull of every piece is
    within `tol` of it. Holes are notches too, so a ring becomes a few wedges around an open middle. Coordinate
    arrays, one hull each. More than `cap` pieces and the answer is the one hull: the no-fit polygons cost a ring
    per piece of every placed part, and a scanned outline with dozens of shallow pockets is not worth that."""
    out, todo = [], list(as_multi(geom).geoms)
    while todo:
        if len(out) + len(todo) > cap:
            return [_hull(geom)]
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


def _ccw(c):
    x, y = c[:, 0], c[:, 1]
    return c if np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)) >= 0 else c[::-1]


def _rot(pieces, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    R = np.array([[c, s], [-s, c]])                       # p @ R turns each row counter-clockwise, like affinity.rotate
    return [p @ R for p in pieces]


def _edges(c):
    """A convex, counter-clockwise piece ready for Minkowski sums: its lowest point and its edges sorted by angle."""
    e = np.roll(c, -1, 0) - c
    e = e[np.hypot(e[:, 0], e[:, 1]) > 1e-12]
    ang = np.arctan2(e[:, 1], e[:, 0]) % (2 * np.pi)
    o = np.argsort(ang, kind="stable")
    return c[np.lexsort((c[:, 0], c[:, 1]))[0]], e[o], ang[o]


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


class Sheet:
    """Parts already placed on one sheet: their grown outlines (for the labels) and convex pieces (for the no-fit polygons)."""
    def __init__(self, W, H, margin):
        self.W, self.H, self.margin = W, H, margin
        self.placed, self.pieces, self.convex = [], [], []
        # A raster of the sheet, CELL wide, a cell blocked when a placed part covers it whole, and the radius of the
        # largest disc the free cells hold (a distance transform): a part whose hull holds a bigger disc cannot fit,
        # and is not searched for a spot, which costs a union per rotation. A blocked frame stands for the margin.
        self.blocked = np.ones((int(H / CELL) + 3, int(W / CELL) + 3), bool)
        self.blocked[self.cell(margin):self.cell(H - margin) + 1, self.cell(margin):self.cell(W - margin) + 1] = False
        self.room_r = distance_transform_edt(~self.blocked).max() * CELL

    def cell(self, v):
        return int(v / CELL) + 1

    def add(self, geom, pc, convex=()):
        self.placed.append(geom); self.pieces.append(pc)
        self.convex += [_edges(p) for p in convex]
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
        return r <= self.room_r + 1.5 * CELL

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


def _rect_nest(prepared, sheet, gap, margin):
    """Rectangle packing of the parts' minimum bounding boxes — the path for many pieces. Above `MANY` parts the
    polygon nesting is far slower (quadratic in the part count) and, measured on 200 and 400 identical crescents with
    the corner search it replaced, packed no tighter, so the count is the gate. Skyline rather than MaxRects:
    MaxRects de-duplicates its free-rectangle list on every insert, which is quadratic in the part count."""
    from rectpack import newPacker, SkylineBlWm, PackingMode, PackingBin, SORT_AREA
    W, H = sheet[0] - 2 * margin, sheet[1] - 2 * margin
    packer = newPacker(mode=PackingMode.Offline, bin_algo=PackingBin.BFF, pack_algo=SkylineBlWm, sort_algo=SORT_AREA, rotation=True)
    dims = []
    for i, (pc, rot0) in enumerate(prepared):
        x0, y0, x1, y1 = affinity.rotate(pc.kerfed, rot0, origin=(0, 0)).bounds
        w, h = x1 - x0 + gap, y1 - y0 + gap
        dims.append((w, h))
        if (w <= W + gap and h <= H + gap) or (h <= W + gap and w <= H + gap):
            packer.add_rect(w, h, i)
    packer.add_bin(W + gap, H + gap, count=float("inf"))
    packer.pack()
    sheets, done = {}, set()
    for b, x, y, w, h, i in packer.rect_list():
        pc, rot0 = prepared[i]
        w0, h0 = dims[i]
        rot = rot0 + (90 if abs(w - h0) < 1e-6 and abs(h - w0) < 1e-6 and abs(w0 - h0) > 1e-6 else 0)
        g = affinity.rotate(pc.kerfed, rot, origin=(0, 0))
        dx, dy = margin + x + gap / 2 - g.bounds[0], margin + y + gap / 2 - g.bounds[1]
        geom, lines, marks = _xf(pc, rot, dx, dy)
        pc.place = (b, geom.bounds[0], geom.bounds[1], rot)
        pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
        sheets.setdefault(b, Sheet(sheet[0], sheet[1], margin)).add(geom, pc)
        done.add(i)
    n = max(sheets) + 1 if sheets else 0
    for i, (pc, rot0) in enumerate(prepared):                  # bigger than a whole sheet (already flagged)
        if i not in done:
            g = affinity.rotate(pc.kerfed, rot0, origin=(0, 0))
            geom, lines, marks = _xf(pc, rot0, margin - g.bounds[0], margin - g.bounds[1])
            pc.place = (n, margin, margin, rot0); pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
            sheets.setdefault(n, Sheet(sheet[0], sheet[1], margin)).add(geom, pc); n += 1
    return [sheets[k] for k in sorted(sheets)]


def nest(pieces, sheet, gap, margin, kerf=0.0, label_h=0.0, font=4.0):
    """Sets piece.place, .kerfed, .placed(+lines, marks), .label_pos, .leader. Returns sheet count.

    One sheet is one stock thickness. A part whose thickness was changed is cut from another piece of material, so
    it gets sheets of its own rather than sharing one and being cut from the wrong stock."""
    by_thick = {}
    for pc in pieces:
        by_thick.setdefault(round(pc.parent.thickness, 6), []).append(pc)
    if len(by_thick) < 2:
        return _nest(pieces, sheet, gap, margin, kerf, label_h, font)
    n = 0
    for t in sorted(by_thick):
        group = by_thick[t]
        used = _nest(group, sheet, gap, margin, kerf, label_h, font)
        for pc in group:
            pc.place = (pc.place[0] + n, *pc.place[1:])      # each group numbered after the ones before it
        n += used
    return n


def _nest(pieces, sheet, gap, margin, kerf=0.0, label_h=0.0, font=4.0):
    W, H = sheet
    k = kerf / 2; half = gap / 2
    prepared = []
    for pc in pieces:
        pc.kerfed = as_multi(pc.geom.buffer(k, join_style=2)) if k else pc.geom
        rot0 = _min_rect_angle(pc.kerfed)
        prepared.append((pc, rot0))
    if len(prepared) > MANY:
        sheets = _rect_nest(prepared, sheet, gap, margin)
        if label_h:
            for sh in sheets:
                place_labels(sh, font)
        return max(1, len(sheets))
    order = sorted(range(len(prepared)), key=lambda i: -prepared[i][0].kerfed.area)
    sheets = [Sheet(W, H, margin)]
    for i in order:
        pc, rot0 = prepared[i]
        grown = pc.kerfed.buffer(half + TOL, join_style=1).simplify(TOL)   # half the gap on each part keeps them the gap apart
        convex = _convex_pieces(grown, POCKET, PIECES)
        turned = {r: _rot(convex, rot0 + r) for r in ROTS}
        # ponytail: the part on its way in is its convex hull, the placed ones their pieces, so the no-fit polygons
        # cost pieces × 1 rings, not pieces × pieces: a part slides into a placed part's cavity or hole, but not its
        # own cavity around a placed part's bulge. Pass turned[r] to spot() for that, at the quadratic cost.
        hull = {r: _rot([_hull(grown)], rot0 + r) for r in ROTS}
        disc = shapely.maximum_inscribed_circle(grown.convex_hull, TOL).length
        best = None
        for sh in sheets + [None]:                                # first sheet it fits on
            if sh is None:
                sh = Sheet(W, H, margin); sheets.append(sh)
            if not sh.room(disc):
                continue
            for r in ROTS:
                pts = np.concatenate(turned[r])
                bounds = (*pts.min(0), *pts.max(0))
                xy = sh.spot(hull[r], bounds)
                if xy is None:
                    continue
                score = (xy[1] + bounds[3], xy[0] + bounds[2])    # lowest top, then leftmost right edge
                if best is None or score < best[0]:
                    best = (score, r, float(xy[0]), float(xy[1]))
            if best is not None:
                break
        if best is None:                                            # genuinely bigger than one sheet (already flagged)
            geom, lines, marks = _xf(pc, rot0, margin - pc.kerfed.bounds[0], margin - pc.kerfed.bounds[1])
            pc.place = (len(sheets) - 1, margin, margin, rot0); pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
            sh.add(geom, pc)
            continue
        _, r, x, y = best
        geom, lines, marks = _xf(pc, rot0 + r, x, y)
        pc.place = (sheets.index(sh), geom.bounds[0], geom.bounds[1], rot0 + r)
        pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
        sh.add(affinity.translate(affinity.rotate(grown, rot0 + r, origin=(0, 0)), x, y), pc, [p + (x, y) for p in turned[r]])
    if label_h:
        for sh in sheets:
            place_labels(sh, font)
    return len(sheets)


def place_labels(sh, font):
    """Each label in free space next to its part: try above, right, below, left at growing distances; leader to the outline."""
    tree = STRtree(sh.placed)
    taken = []
    for pc in sh.pieces:
        w = max(6.0, 0.62 * font * len(pc.label) + 2); h = font * 1.4
        x0, y0, x1, y1 = pc.placed.bounds; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        spots = []
        for d in (1.0, 4.0, 8.0, 14.0, 22.0):
            spots += [(cx, y1 + d + h / 2, 0), (x1 + d + w / 2, cy, 0), (cx, y0 - d - h / 2, 0), (x0 - d - w / 2, cy, 0),
                      (x1 + d + h / 2, cy, 90), (x0 - d - h / 2, cy, 90)]
        chosen = None
        for lx, ly, rot in spots:
            bw, bh = (w, h) if rot == 0 else (h, w)
            rect = box(lx - bw / 2, ly - bh / 2, lx + bw / 2, ly + bh / 2)
            if rect.bounds[0] < 0 or rect.bounds[1] < 0 or rect.bounds[2] > sh.W or rect.bounds[3] > sh.H:
                continue
            if any(rect.intersects(sh.placed[i]) for i in tree.query(rect)) or any(rect.intersects(t) for t in taken):
                continue
            chosen = (lx, ly, rot, rect); break
        if chosen is None:                                          # crowded: inside the part, at its representative point
            c = pc.placed.representative_point(); chosen = (c.x, c.y, 0, box(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2))
        lx, ly, rot, rect = chosen
        taken.append(rect)
        anchor = Point(lx, ly)
        near = min((p.exterior for p in pc.placed.geoms), key=lambda r: r.distance(anchor))
        q = near.interpolate(near.project(anchor))
        pc.label_pos = (lx, ly, rot)
        pc.leader = ((lx, ly), (q.x, q.y))
