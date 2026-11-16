"""The geometry of the polygon nester, which knows nothing of pieces: a part cut into convex pieces, the Minkowski sums
that make the no-fit polygons, and `Sheet`, one sheet's raster and no-fit cache (see core/nest.py)."""
from __future__ import annotations
import math
import threading
import numpy as np
import shapely
from scipy.ndimage import binary_erosion, distance_transform_edt
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import split
from shapely.geometry.polygon import orient
from .geometry import as_multi, robust

CELL = 2.0       # mm: the raster of a sheet that says which parts cannot fit it (Sheet.room)


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
    """Parts already placed on one sheet, as the polygon nester sees them: their convex pieces (for the no-fit polygons)
    and a raster of what they cover."""
    def __init__(self, W, H, margin):
        self.W, self.H, self.margin = W, H, margin
        self.convex = []
        self.nfp = {}            # the no-fit union for a part's shape, and how many placed pieces it covers (see spot)
        self.kept = threading.Lock()   # a part's turns ask at once (`each`): one of them at a time changes what is kept
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

    def add(self, geom, convex=()):
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
            # Identical parts come one after another (sorted by area), and a stack or a tube is mostly identical parts:
            # once a sheet is full, every later copy asks it again. The union of no-fit polygons is kept per shape,
            # the hull to the bit, and handed back while nothing has been placed since — the very same geometry, so
            # the answer is the one a fresh union gives. Nothing looser: the lowest vertex is chosen to the last bit,
            # so a union built in two steps, or one shared between hulls a rounding apart (a square's four turns),
            # flips ties between turns and renests the job onto another sheet.
            key = tuple(p.tobytes() for p in pieces)
            n, nfp = self.nfp.get(key, (0, None))
            if n != len(self.convex):
                nfp = shapely.union_all(np.concatenate([_minkowski(self.convex, _edges(-p)) for p in pieces]))
                with self.kept:       # two turns dropping the same oldest entry: the second had nothing to drop, and
                    if len(self.nfp) >= 16:                    # the slice failed with a KeyError
                        del self.nfp[next(iter(self.nfp))]
                    self.nfp[key] = (len(self.convex), nfp)
            free = free.difference(nfp)
        if free.is_empty:
            return None
        c = shapely.get_coordinates(free)
        return c[np.lexsort((c[:, 0], c[:, 1]))[0]]
