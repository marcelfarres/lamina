"""Polygon nesting with no-fit polygons, after Deepnest (Jack Qiao, github.com/Jack000/Deepnest, MIT) and its
predecessor SVGnest. For the next part, the positions where it would overlap a placed part are that part's no-fit
polygon: the Minkowski sum of the placed outline and the negated new one. The positions where it stays on the sheet
are the inner-fit rectangle. The rectangle minus the union of the no-fit polygons is the free region, and the part
goes to its lowest, then leftmost, vertex: it slides into concavities and holes, where a corner search only tries the
corners of bounding boxes. Deepnest computes the Minkowski sum with Clipper; here each outline is cut into convex
pieces (constrained Delaunay triangles merged while they stay convex) and the sum is the union of the hulls of the
piece pairs, which shapely does (core/nofit.py). Parts are placed one by one, largest first, each tried at its
minimum-rectangle angle plus quarter turns (with `grain`, as it stands or upside down); labels afterwards, in free
space next to each part, with a leader line.

Not taken from Deepnest: its genetic algorithm over the part order and rotations (minutes of search for a few
percent of sheet) and its merging of shared cut lines.
"""
from __future__ import annotations
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point, box
from shapely.ops import unary_union
from .geometry import as_multi, min_rect_angle
from .labels import fit_on_part, label_angles, label_box, mark_box, mark_rot, place_labels
from .nofit import Sheet, _convex_pieces, _fill_small_holes, _hull, _rot

ROTS = (0, 90, 180, 270)
# A part's rotations on one sheet are independent, and their no-fit union, the costliest call of a slice, runs in GEOS
# with the GIL let go: side by side it was 2.0–2.7× faster (cow_spot, bunny, bowl). The browser build has no threads.
each = map if sys.platform == "emscripten" else ThreadPoolExecutor(len(ROTS), thread_name_prefix="nest").map


def _bounds(pts):
    """x0, y0, x1, y1 of a point array."""
    return (*pts.min(0), *pts.max(0))
PIECES = 16         # convex pieces a placed part may cost the no-fit polygons; past that it is its hull (see _convex_pieces)
TOL = 0.5           # mm: the nesting outline is grown by this and simplified by this, so the parts never come closer
                    # than the gap and rarely more than the gap plus TOL
POCKET = 2.0        # mm: the convex pieces of an outline may overrun its concavities by this, so a part nested in a
                    # pocket keeps up to this much more than the gap to the pocket wall; a concave arc needs a chord
                    # every 2·sqrt(2·radius·POCKET), which is what the count of pieces, and the nesting time, follow
MANY = 150          # above this many pieces the rectangle packer takes over (see _nest)


@dataclass(frozen=True)
class NestJob:
    """What one `nest` call asks for, the same for every thickness group: the sheet (width, height), the gap between
    parts, the margin, the kerf, whether the grain is kept, and how the labels are placed (`labels`, `font`, `tag`, `place`)."""
    sheet: tuple
    gap: float
    margin: float
    kerf: float
    grain: bool
    labels: bool
    font: float
    tag: str
    place: str


@dataclass(frozen=True)
class Placed:
    """Where a packer puts one part: on sheet `sheet`, turned `rot` and moved by (dx, dy). `outline` is what the sheet
    keeps of it for the labels (the nesting outline, as moved); `at` is where the part's corner is said to sit when the
    caller means a spot (the margin), else the corner of the moved part. A packer returns these and writes nothing to
    the pieces: the better packing is chosen from them, and `_put` runs once, for that one."""
    pc: object
    sheet: int
    rot: float
    dx: float
    dy: float
    outline: object
    at: tuple | None = None


@dataclass
class Laid:
    """One finished sheet as `place_labels` reads it: its size and margin, the outlines placed on it and their pieces."""
    W: float
    H: float
    margin: float
    placed: list
    pieces: list


def _move(g, rot, dx, dy):
    return affinity.translate(affinity.rotate(g, rot, origin=(0, 0)), dx, dy)


def _put(p):
    """The piece placed as `p` says, its outline, lines and marks moved with it. `place` says where it sits — its
    corner, or `p.at` where the caller means a spot (the margin)."""
    pc, T = p.pc, lambda g: _move(g, p.rot, p.dx, p.dy)
    geom = as_multi(T(pc.kerfed))
    pc.placed, pc.placed_lines, pc.placed_marks = geom, [(s, T(l)) for s, l in pc.lines], [(*T(Point(m[0], m[1])).coords[0], m[2], mark_rot(m)) for m in pc.marks]
    pc.placed_cover = None if pc.parent.cover is None else as_multi(T(pc.parent.cover))
    pc.place = (p.sheet, *(p.at or geom.bounds[:2]), p.rot)


def _count(placed):
    """How many sheets the placements use. Counted by the last one, not by the sheets that hold a part: a part too big
    for the first sheet takes the next, and the first stays empty."""
    return max((p.sheet for p in placed), default=-1) + 1


def _oversize(pc, rot0, sheet_i, margin):
    """A part bigger than a sheet (already flagged), or filling one so exactly the gap tips it over: it takes sheet
    `sheet_i` to itself, its corner at the margin. Where the part's corner lands once it is turned: the unturned
    outline's corner put a 586 × 390 mm panel 485 mm off a 600 × 400 sheet, with nothing said."""
    b = affinity.rotate(pc.kerfed, rot0, origin=(0, 0)).bounds
    dx, dy = margin - b[0], margin - b[1]
    return Placed(pc, sheet_i, rot0, dx, dy, as_multi(_move(pc.kerfed, rot0, dx, dy)), at=(margin, margin))


def _rect_nest(prepared, job):
    """Rectangle packing of the parts' minimum bounding boxes — the path for many pieces. Above `MANY` parts the
    polygon nesting is far slower (quadratic in the part count) and, measured on 200 and 400 identical crescents with
    the corner search it replaced, packed no tighter, so the count is the gate. Skyline rather than MaxRects:
    MaxRects de-duplicates its free-rectangle list on every insert, which is quadratic in the part count. With `grain`
    no part is turned."""
    from rectpack import newPacker, SkylineBlWm, PackingMode, PackingBin, SORT_AREA
    gap, margin, grain = job.gap, job.margin, job.grain
    W, H = job.sheet[0] - 2 * margin, job.sheet[1] - 2 * margin
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
    out, done = [], set()
    for b, x, y, w, h, i in packer.rect_list():
        pc, rot0 = prepared[i]
        w0, h0 = dims[i]
        rot = rot0 + (90 if abs(w - h0) < 1e-6 and abs(h - w0) < 1e-6 and abs(w0 - h0) > 1e-6 else 0)
        g = affinity.rotate(pc.nest_shape, rot, origin=(0, 0))
        # each rectangle is the part plus one gap, in a bin one gap wider than the sheet inside its margins: the part
        # sits at the rectangle's corner, so the gap falls between neighbours and the last one ends at the margin.
        # Centred in its rectangle, every part on the far edges ran half a gap into the margin.
        dx, dy = margin + x - g.bounds[0], margin + y - g.bounds[1]
        out.append(Placed(pc, b, rot, dx, dy, affinity.translate(g, dx, dy)))
        done.add(i)
    n = max((p.sheet for p in out), default=-1) + 1
    for i, (pc, rot0) in enumerate(prepared):                  # bigger than a whole sheet (already flagged)
        if i not in done:
            out.append(_oversize(pc, rot0, n, margin)); n += 1
    return out


def nest(pieces, sheet, gap, margin, kerf=0.0, labels=False, font=4.0, tag="", place="part", grain=False):
    """Sets piece.place, .kerfed, .placed(+lines, marks), .label_pos, .leader. Returns sheet count.

    One sheet is one stock thickness. A part whose thickness was changed is cut from another piece of material, so
    it gets sheets of its own rather than sharing one and being cut from the wrong stock. With `grain` every part
    keeps its own frame's x along the sheet's width, turned 0° or 180° only, so the grain runs one way on all of them."""
    job = NestJob(tuple(sheet), gap, margin, kerf, grain, labels, font, tag, place)
    by_thick = {}
    for pc in pieces:
        by_thick.setdefault(round(pc.parent.thickness, 6), []).append(pc)
    placed, n = [], 0
    for t in sorted(by_thick):
        got = _nest(by_thick[t], job)
        placed += [replace(p, sheet=p.sheet + n) for p in got]      # each group numbered after the ones before it
        n += _count(got)
    for p in placed:
        _put(p)
    if labels:
        for k in sorted({p.sheet for p in placed}):
            on = [p for p in placed if p.sheet == k]
            place_labels(Laid(*job.sheet, margin, [p.outline for p in on], [p.pc for p in on]), font, tag, place)
    return max(1, n)


def _nest(pieces, job):
    """The placements of one thickness group: the better of the polygon nest and the rectangle packing."""
    k = job.kerf / 2
    prepared = []
    for pc in pieces:
        pc.kerfed = as_multi(pc.geom.buffer(k, join_style=2)) if k else pc.geom
        pc.nest_shape = pc.kerfed
        if job.labels and job.place != "on":
            # A part too small to carry even its bare name is nested with the room for that name reserved above it,
            # so the label can sit right beside the part instead of wherever the packed sheet leaves a gap. The
            # reserve is only ever a hole the nester keeps; the part's own outline is what is cut and labelled.
            w, h = label_box(pc.label, job.font * 0.65)                       # the least the part could carry
            keep = [mark_box(*m[:3], job.font, mark_rot(m)) for m in pc.marks] + [ln.buffer(0.8) for s, ln in pc.lines if s == "orient"]
            if fit_on_part(pc.kerfed, pc.parent.cover, w, h, keep, label_angles(pc.kerfed), room=min(2.0, 0.3 * job.font * 0.65)) is None:
                x0, y0, x1, y1 = pc.kerfed.bounds; cx = (x0 + x1) / 2
                pc.nest_shape = as_multi(unary_union([pc.kerfed, box(cx - w / 2, y1 + 1.0, cx + w / 2, y1 + 1.0 + h)]))
        prepared.append((pc, 0.0 if job.grain else min_rect_angle(pc.nest_shape)))
    placed = _rect_nest(prepared, job) if len(prepared) > MANY else _poly_nest(prepared, job)
    count = _count
    if len(prepared) <= MANY and count(placed) > 1:
        # the polygon nest fills bottom-left and lets a round part drop into the valley between two below it, which
        # can cost a whole column (seven rings: five and two, where three and three would do); the plain rectangle
        # packing is tried as well and kept when it takes fewer sheets, or as many with less on its emptiest one
        # (seven rings: five and two, where six and one would do — the first sheet full, the last for the rest). The
        # parts' own areas are compared: the polygon nest keeps grown outlines, and a part too big for the sheet
        # takes a sheet of its own in a different place in each nest's order
        def least(ps):
            area = {}
            for p in ps:
                area[p.sheet] = area.get(p.sheet, 0) + p.pc.kerfed.area
            return min(area.values())
        rect = _rect_nest(prepared, job)
        if count(rect) < count(placed) or (count(rect) == count(placed) and least(rect) < least(placed)):
            placed = rect
    return placed


def _poly_nest(prepared, job):
    """Every part on the first sheet with room for it, at the lowest-left spot of its free region (see the module
    docstring), largest first; a part bigger than a sheet takes the sheet it lands on to itself."""
    (W, H), margin, half = job.sheet, job.margin, job.gap / 2
    rots = (0, 180) if job.grain else ROTS
    order = sorted(range(len(prepared)), key=lambda i: -prepared[i][0].kerfed.area)
    grown_all = [pc.nest_shape.buffer(half + TOL, join_style=1) for pc, _ in prepared]   # half the gap on each part keeps them the gap apart
    # a hole no part could go in — a dowel hole, a slot: smaller than the smallest part with its share of the gap — is
    # filled before the outline is cut into convex pieces: each hole is a notch to that cut, and a stacked slice with
    # thirty dowel holes blew past the piece cap and became its hull, which covered the big hollow in its middle
    # that the small parts should have gone into
    least = min(g.area for g in grown_all) if grown_all else 0.0
    sheets, out = [Sheet(W, H, margin)], []
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
            p = _oversize(pc, rot0, len(sheets) - 1, margin)
            # with its convex pieces, like any other part: without them the sheet reads as empty and the next parts
            # are nested on top of it — the oversize part overhangs the sheet, it does not share it
            p = replace(p, outline=_move(grown, rot0, p.dx, p.dy))
            sh.add(p.outline, [q + (p.dx, p.dy) for q in turned[0]])
            out.append(p)
            continue
        _, r, x, y = best
        p = Placed(pc, sheets.index(sh), rot0 + r, x, y, _move(grown, rot0 + r, x, y))
        sh.add(p.outline, [q + (x, y) for q in turned[r]])
        out.append(p)
    return out
