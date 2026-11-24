"""Holding bridges: a few short stretches of each part's outline left uncut, so the part stays in its sheet while the
rest of the sheet is cut — it cannot drop through the bed, tilt up into the head or be blown off by the air assist —
and is broken out by hand afterwards, its stub sanded off.

The gap left in the cut path is the bridge's width plus the kerf: the beam burns half a kerf past each end of an open
cut, so the web left standing is the width asked for (`gap_of`).

Where they go (the placement follows LaserSlicer's bridges.ts, GPL-3.0, github.com/DrKlenkk/LaserSlicer): every point
on a 0.5 mm grid along the outline is scored by how straight the outline is around it and how far it is from a corner;
the bridges are spread evenly by arc length, each slides up to a quarter of the spacing to a better spot, and of 48
start offsets the one with the best mean-plus-worst score wins, marked down when two bridges end up close in space (on a
folded outline equal arc spacing does not mean far apart). Two bridges sit on opposite sides, four on the four sides of
a square. An outline too short for the count gets fewer.

Lamina's own part: a bridge never sits on a joint. The stub left on a slot wall, a puzzle tab, a tooth or the end of a
fold would stop the joint closing, and the plan does not keep where its joints are — so the outline is read for them
(`_joints`): a stretch inside a notch narrower than twice `reach` (a slot, a socket) or along a protrusion narrower
than that (a tab, a tooth, a finger) is no place for one, and neither is the end of a fold line.
"""
from __future__ import annotations
import numpy as np
import shapely
from shapely.geometry import Polygon

CORNER = 25.0        # deg: a vertex turning more than this is a corner
HALF = 6.0           # deg of turning inside a window that halves its straightness score
STEP = 0.5           # mm between the points scored along an outline
OFFSETS = 48         # start offsets tried for the even spread


def gap_of(width, kerf):
    """The gap left in the cut path for a web `width` wide."""
    return width + max(0.0, kerf)


def reach_of(p, thick):
    """Half the width under which a notch or protrusion of an outline counts as a joint. Slots are about a sheet wide;
    puzzle tabs `tab` wide and plaque teeth `tooth_width`: twice the reach must clear the widest of them."""
    return max(2.0, 1.5 * thick, 0.5 * max(p.get("tab", 8.0), p.get("tooth_width", 0.0)) + 1.0)


def _joints(poly, r):
    """Where the outline of `poly` is a joint, as one geometry (or None): the notches narrower than 2r and the
    protrusions narrower than 2r. Not every narrow stretch is a protrusion: the whole part may be that narrow, and a
    hollowed layer's wall between a hole and the outline is too — a tab's sides are the outline, a wall's other side is
    a hole, so a narrow piece lying more than a fifth along a hole is a wall. Buffering leaves slivers along every curve
    (a scanned layer's outline yields thousands): one under 1 mm², or too thin to survive a 0.1 mm inset, is one of
    those. The outline is simplified to 0.05 mm first, for speed."""
    poly = poly.simplify(0.05)
    opened, closed = poly.buffer(-r, quad_segs=4).buffer(r, quad_segs=4), poly.buffer(r, quad_segs=4).buffer(-r, quad_segs=4)
    rings = [shapely.LineString(i.coords) for g in getattr(poly, "geoms", [poly]) for i in g.interiors]
    holes = shapely.union_all(rings).buffer(0.05) if rings else None
    out = []
    for g, tabs in ((poly.difference(opened), True), (closed.difference(poly), False)):
        for q in getattr(g, "geoms", [g]):
            if q.geom_type != "Polygon" or q.area <= 1.0:
                continue
            if tabs and (q.area >= 0.25 * poly.area or holes is not None and q.boundary.intersection(holes).length > 0.2 * q.length):
                continue
            if not q.buffer(-0.1).is_empty:
                out.append(q)
    return shapely.union_all(out) if out else None


class _Ring:
    """A closed outline walked by arc length: its vertices, their arc positions s (s[n] = perimeter), the turning at
    each vertex in degrees and its running sum."""

    def __init__(self, ring):
        pts = np.asarray(ring, float)
        keep = np.r_[True, np.hypot(*np.diff(pts, axis=0).T) > 1e-9]          # drop repeated points
        pts = pts[keep]
        if len(pts) > 1 and np.hypot(*(pts[0] - pts[-1])) <= 1e-9:
            pts = pts[:-1]
        self.pts = pts; n = len(pts)
        seg = np.roll(pts, -1, 0) - pts
        self.s = np.r_[0.0, np.cumsum(np.hypot(*seg.T))]; self.P = self.s[-1]
        a = np.arctan2(seg[:, 1], seg[:, 0])
        self.turn = np.degrees(np.abs((a - np.roll(a, 1) + np.pi) % (2 * np.pi) - np.pi)) if n else np.zeros(0)
        self.cum = np.r_[0.0, np.cumsum(self.turn)]
        self.corners = self.s[:n][self.turn > CORNER]

    def at(self, x):
        """Points at arc positions x (any real numbers: taken round the ring)."""
        x = np.mod(x, self.P); i = np.clip(np.searchsorted(self.s, x, "right") - 1, 0, len(self.pts) - 1)
        t = (x - self.s[i]) / np.maximum(self.s[i + 1] - self.s[i], 1e-12)
        return self.pts[i] + (np.roll(self.pts, -1, 0)[i] - self.pts[i]) * t[:, None]

    def turning(self, a, b):
        """Total turning of the vertices with arc position in [a, b], for arrays a <= b (any reals, b - a < P)."""
        def C(x):
            k = np.floor(x / self.P); return k * self.cum[-1] + self.cum[np.searchsorted(self.s[:-1], x - k * self.P, "right")]
        return C(b) - C(a - 1e-9)

    def to_corner(self, x):
        """Arc distance from each x to the nearest corner (inf without corners)."""
        if not len(self.corners):
            return np.full(len(x), np.inf)
        d = np.abs(np.mod(x, self.P)[:, None] - self.corners[None, :])
        return np.minimum(d, self.P - d).min(axis=1)

    def piece(self, x0, length):
        """The open stretch of the ring from arc position x0 over `length`, with the vertices in between."""
        x0 = x0 % self.P; x1 = x0 + length
        s2 = np.r_[self.s[:-1], self.s[:-1] + self.P]; p2 = np.r_[self.pts, self.pts]
        inner = p2[(s2 > x0 + 1e-9) & (s2 < x1 - 1e-9)]
        return [tuple(map(float, q)) for q in np.r_[self.at(np.array([x0])), inner, self.at(np.array([x1]))]]


def place(ring, holes, count, width, kerf, reach, ends=()):
    """Arc positions (from the ring's first point, ascending) of the bridges on one closed outer ring, `holes` its
    inner rings (they shape the joints, never get bridges), `ends` the points where fold lines meet it. Empty when the
    ring is too short or every spot on it is a joint."""
    R = _Ring(ring)
    if count < 1 or len(R.pts) < 3 or R.P <= 0:
        return []
    g = gap_of(width, kerf); c = max(1.5, width); h = g / 2 + c                # clearance either side of a gap
    minsep = g + 2 * c
    N = min(int(count), int(R.P // minsep))
    if N < 1:
        return []
    M = max(8, int(np.ceil(R.P / STEP))); step = R.P / M
    x = np.arange(M) * step
    # a spot is no use when its window (the gap and its clearance) touches a joint or a fold's end
    bad = np.zeros(M, bool)
    joints = _joints(Polygon(R.pts, [np.asarray(hh) for hh in holes]).buffer(0), reach)
    pts = shapely.points(R.at(x))
    if joints is not None:
        bad |= shapely.distance(pts, joints) < 0.05
    if len(ends):
        bad |= shapely.distance(pts, shapely.multipoints(np.asarray(ends, float))) < h
    w = int(np.ceil(h / step))
    win = np.convolve(np.r_[bad[-w:], bad, bad[:w]].astype(float), np.ones(2 * w + 1), "valid") > 0
    spacing = R.P / N
    straight = 1 / (1 + (R.turning(x - h, x + h) / HALF) ** 2)
    free = np.maximum(0.0, R.to_corner(x) - h)
    score = np.where(win, 0.0, straight * (0.5 + 0.5 * np.minimum(1.0, free / max(12.0, 4 * c, spacing / 4))))
    # the even spread: N targets per offset, each sliding to the best spot near it (never so far that two could touch)
    slide = max(0, int((min(spacing / 4, (spacing - minsep) / 2) - step) // step))
    d = np.arange(-slide, slide + 1)
    targets = np.rint((np.arange(OFFSETS)[:, None] / OFFSETS + np.arange(N)[None, :]) * spacing / step).astype(int)
    idx = (targets[:, :, None] + d[None, None, :]) % M
    vals = score[idx] - 0.02 * np.abs(d) / (slide + 1)                          # ties: stay near the target
    best = np.take_along_axis(idx, vals.argmax(axis=2)[:, :, None], 2)[:, :, 0]  # (offsets, N)
    sc = score[best]
    total = (sc.mean(axis=1) + sc.min(axis=1)) / 2
    if N > 1:                                                                   # two bridges close in space count less
        xy = R.at(best.ravel() * step).reshape(OFFSETS, N, 2)
        dmin = np.hypot(*(xy[:, :, None, :] - xy[:, None, :, :]).transpose(3, 0, 1, 2))
        dmin[:, np.arange(N), np.arange(N)] = np.inf
        total *= 0.5 + 0.5 * np.minimum(1.0, dmin.min(axis=(1, 2)) / (0.25 * spacing))
    o = int(total.argmax())
    return sorted(float(best[o, k] * step) for k in range(N) if sc[o, k] > 0)   # a bridge left on a joint is dropped


def split(ring, centres, width, kerf):
    """The open cut stretches of a ring between its bridges."""
    R = _Ring(ring); g = gap_of(width, kerf)
    return [R.piece(c0 + g / 2, (c1 - c0) % R.P - g if len(centres) > 1 else R.P - g)
            for c0, c1 in zip(centres, centres[1:] + centres[:1])]


def hold(items, p, thick):
    """Give each item's outer rings their bridges (`Item.open`: ring index -> the open stretches it is cut as). `p`
    the job's parameters, `thick` the thickest stock on the sheet (it sizes the joints). Returns the items."""
    count = int(p.get("bridges", 0) or 0)
    if count < 1 or p.get("printed"):
        return items
    width, kerf, reach = p.get("bridge_width", 0.5), p.get("kerf", 0.0) or 0.0, reach_of(p, thick)
    for it in items:
        ends = [q for style, pts in it.scores if style not in ("guide", "orient") and len(pts) > 1 for q in (pts[0], pts[-1])]   # fold lines only
        for i, (layer, ring) in enumerate(it.rings):
            if layer != "OUTER":
                continue
            holes = []
            for lay, r in it.rings[i + 1:]:
                if lay != "INNER":
                    break
                holes.append(r)
            centres = place(ring, holes, count, width, kerf, reach, ends)
            if centres:
                it.open[i] = split(ring, centres, width, kerf)
    return items
