"""Polygon nesting: parts are placed one by one (largest first) at bottom-left "extreme points" — the corners
left by already placed parts — trying the part pre-rotated to its minimum bounding rectangle plus 90° turns.
Collision tests are on the real outlines (buffered by half the gap), so round and concave parts pack closer
than their bounding boxes. Labels are placed afterwards in free space next to each part, with a leader line.

Limits: extreme-point greedy with polygon tests (O(n² · rotations) shapely queries). No-fit-polygon nesting
(SVGnest / libnest2d) would pack concavities that need sliding; a metaheuristic over the part order would pack tighter.
"""
from __future__ import annotations
import math
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point, box
from shapely.strtree import STRtree
from .geometry import as_multi

ROTS = (0, 90, 180, 270)
TRIES = 150         # candidate corners examined per part and rotation, half of them the lowest and half spread over
                    # the rest of the sheet (see `candidates`), which bounds the cost without blinding the search.


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


class Sheet:
    """Parts already placed on one sheet, with their bounding boxes for cheap screening: the hot loop tries hundreds
    of candidate positions per part, so a candidate is screened on its bounding box with numpy and the translated
    polygon is only built when a neighbour's box actually overlaps."""
    def __init__(self, W, H, margin):
        self.W, self.H, self.margin = W, H, margin
        self.placed, self.pieces, self.probes = [], [], []
        self.boxes = np.zeros((0, 4))                     # x0, y0, x1, y1 per placed part
        self.points = {(margin, margin)}                  # candidate bottom-left corners

    def candidates(self, n=TRIES):
        """Positions to try, bottom-left first. Half the budget is the lowest corners and half is spread evenly over
        the rest of the sheet: with the lowest corners alone a sheet looks full as soon as its bottom row is blocked."""
        pts = sorted(self.points, key=lambda q: (q[1], q[0]))
        if len(pts) <= n:
            return pts
        head, rest = pts[: n // 2], pts[n // 2:]
        step = max(1, len(rest) // (n - n // 2))
        return head + rest[::step]

    def in_sheet(self, b):
        return b[0] >= self.margin - 1e-6 and b[1] >= self.margin - 1e-6 and b[2] <= self.W - self.margin + 1e-6 and b[3] <= self.H - self.margin + 1e-6

    def near(self, b):
        """Indices of placed parts whose bounding box overlaps b (numpy, no geometry built)."""
        if not len(self.boxes):
            return []
        B = self.boxes
        hit = (B[:, 0] < b[2] - 1e-9) & (B[:, 2] > b[0] + 1e-9) & (B[:, 1] < b[3] - 1e-9) & (B[:, 3] > b[1] + 1e-9)
        return np.nonzero(hit)[0]

    def free(self, geom, idxs):
        """Free of real overlap. Candidates sit exactly on a neighbour's corner and shapely counts touching as
        intersecting, so each placed part keeps a `probe` shrunk by a micron: touching it is fine, entering it is not.
        The probes are prepared, so this is an indexed predicate rather than an intersection-area computation."""
        return not any(shapely.intersects(self.probes[i], geom) for i in idxs)

    def fits(self, geom):
        b = geom.bounds
        return self.in_sheet(b) and self.free(geom, self.near(b))

    def add(self, geom, pc, track=True):
        """track=False records the part for label placement only — the candidate-point bookkeeping below is
        quadratic and pointless for the rectangle path, which never searches corners."""
        self.placed.append(geom); self.pieces.append(pc)
        if not track:
            return
        probe = geom.buffer(-1e-3)
        shapely.prepare(probe)
        self.probes.append(probe)
        x0, y0, x1, y1 = geom.bounds
        self.boxes = np.vstack([self.boxes, [x0, y0, x1, y1]])
        # new corners to try next: right of the part, above it, and the same on the sheet's edges
        self.points |= {(x1, y0), (x0, y1), (x1, self.margin), (self.margin, y1)}
        B = self.boxes
        keep = set()
        for px, py in self.points:                       # drop points outside the sheet or buried inside a part
            if px >= self.W - self.margin or py >= self.H - self.margin:
                continue
            if np.any((B[:, 0] < px - 1e-9) & (B[:, 2] > px + 1e-9) & (B[:, 1] < py - 1e-9) & (B[:, 3] > py + 1e-9)):
                continue
            keep.add((px, py))
        self.points = keep


MANY = 150          # above this many pieces the rectangle packer takes over (see nest)


def _rect_nest(prepared, sheet, gap, margin):
    """Rectangle packing of the parts' minimum bounding boxes — the path for many pieces. Above `MANY` parts the
    polygon search is about 100x slower and, measured on 200 and 400 identical crescents, packs no tighter (same
    sheet count and usage either way), so the count is the right gate. Skyline rather than MaxRects: MaxRects
    de-duplicates its free-rectangle list on every insert, which is quadratic in the part count."""
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
        sheets.setdefault(b, Sheet(sheet[0], sheet[1], margin)).add(geom, pc, track=False)
        done.add(i)
    n = max(sheets) + 1 if sheets else 0
    for i, (pc, rot0) in enumerate(prepared):                  # bigger than a whole sheet (already flagged)
        if i not in done:
            g = affinity.rotate(pc.kerfed, rot0, origin=(0, 0))
            geom, lines, marks = _xf(pc, rot0, margin - g.bounds[0], margin - g.bounds[1])
            pc.place = (n, margin, margin, rot0); pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
            sheets.setdefault(n, Sheet(sheet[0], sheet[1], margin)).add(geom, pc, track=False); n += 1
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
        placed_ok = False
        # Round joins, with the offset measured on the buffered bounds: under a mitre join a sharp corner grows a
        # spike far beyond `half`, and the part would stick out past the sheet margin and be rejected even by an
        # empty sheet. One buffer per part (it was the nesting's biggest cost), turned for each rotation.
        grown = pc.kerfed.buffer(half, join_style=1)                 # keep the gap to the neighbours
        turned = {r: affinity.rotate(grown, rot0 + r, origin=(0, 0)) for r in ROTS}
        for sh in sheets + [None]:
            if sh is None:
                sh = Sheet(W, H, margin); sheets.append(sh)
            best = None
            spots = sh.candidates()                          # same list for every rotation: sorting once per sheet
            for r in ROTS:
                gb = turned[r]
                gx0, gy0, gx1, gy1 = gb.bounds
                w, h = gx1 - gx0, gy1 - gy0
                for (px, py) in spots:
                    b = (px, py, px + w, py + h)
                    if not sh.in_sheet(b):
                        continue
                    idxs = sh.near(b)
                    dx, dy = px - gx0, py - gy0
                    cand = None
                    if len(idxs):                                     # only now is the polygon worth building
                        cand = affinity.translate(gb, dx, dy)
                        if not sh.free(cand, idxs):
                            continue
                    score = (b[3], b[2])                              # lowest top, then leftmost right edge
                    if best is None or score < best[0]:
                        best = (score, r, dx, dy, cand if cand is not None else affinity.translate(gb, dx, dy))
                    break                                             # first (lowest) point that fits for this rotation
            if best is not None:
                _, r, dx, dy, cand = best
                geom, lines, marks = _xf(pc, rot0 + r, dx, dy)
                pc.place = (sheets.index(sh), geom.bounds[0], geom.bounds[1], rot0 + r)
                pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
                sh.add(cand, pc); placed_ok = True
                break
        if not placed_ok:                                           # genuinely bigger than one sheet (already flagged)
            sh = Sheet(W, H, margin); sheets.append(sh)
            geom, lines, marks = _xf(pc, rot0, margin - pc.kerfed.bounds[0], margin - pc.kerfed.bounds[1])
            pc.place = (len(sheets) - 1, margin, margin, rot0); pc.placed, pc.placed_lines, pc.placed_marks = geom, lines, marks
            sh.add(geom, pc)
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
