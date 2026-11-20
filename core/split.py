"""Split a slice that does not fit the sheet into pieces joined by puzzle tabs, and a slice that falls apart into
separate islands into one piece per island."""
from __future__ import annotations
import math
import numpy as np
import shapely
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
from .geometry import as_lines, as_multi, circle, min_dims
from .model import Piece

# every tab is a union and a difference on the growing piece outlines, so the count decides whether a split takes a
# second or an hour: beyond these it is the sheet or the model that is wrong, and the slice says so instead
MAX_PIECES = 12                       # sheets a part may span
MAX_TABS = 24                         # tabs along one cut

def fits_rotated(geom, sheet, margin, grain=False):
    """Does the part fit the sheet in any orientation? With `grain` only as it stands (or upside down, the same box):
    the nester may not turn it sideways.

    The minimum-area rectangle alone is not enough: for a diagonal shape it can be longer than the axis-aligned box
    (a 500x380 panel measured 493x460 that way and was refused although it fits upright). Either box fitting suffices.
    """
    sw, sh = sheet[0] - 2 * margin, sheet[1] - 2 * margin
    x0, y0, x1, y1 = geom.bounds
    if grain:
        return x1 - x0 <= sw and y1 - y0 <= sh
    fits = lambda w, h: (w <= sw and h <= sh) or (h <= sw and w <= sh)
    return fits(x1 - x0, y1 - y0) or fits(*min_dims(geom))


def tab(cx, cy, along, w, depth, side):
    """Round-headed puzzle tab centred on the cut line at (cx,cy), protruding `depth` to `side`."""
    ax, ay = along; px, py = -ay * side, ax * side
    neck = w * 0.55
    body = Polygon([(-neck / 2, -0.01), (neck / 2, -0.01), (neck / 2, depth * 0.5), (-neck / 2, depth * 0.5)])
    head = circle((0, depth * 0.5 + w * 0.3), w * 0.9)
    shape = unary_union([body, head])
    return Polygon([(cx + ax * x + px * y, cy + ay * x + py * y) for x, y in shape.exterior.coords])


def _strips(profile, axis, room, tab_w, sl):
    """Cut `profile` across `axis` into strips joined by puzzle tabs, each at most `room` long that way, its tabs
    included. Returns the strips (the profile itself when it would take more than MAX_PIECES, with the slice saying
    so). A strip whose neighbours' tabs stick out past `room` is cut again into one strip more: a tab reaches 1.8 ×
    tab_w past its cut, more than the 1 × tab_w kept free at each end (bug 048)."""
    x0, y0, x1, y1 = profile.bounds
    w, h = x1 - x0, y1 - y0
    usable = room - 2 * tab_w
    n = max(2, math.ceil((w if axis == 0 else h) / usable))
    if n > MAX_PIECES:                                    # a part many sheets long is a wrong setting, not a puzzle
        sl.errors.append(f"{w:.0f}×{h:.0f} mm is {n} sheets long: use a bigger sheet or `one_sheet`, a smaller model, or a technique with smaller parts")
        return [profile]
    for k in range(n, MAX_PIECES + 1):
        pieces, cuts, errors, warnings = _strips_of(profile, axis, k, usable, tab_w)
        if all(g.bounds[2 + axis] - g.bounds[axis] <= room + 1e-6 for g in pieces):
            break
    sl.split_cuts = cuts
    for e in errors:
        sl.errors.append(e)
    for x in warnings:
        sl.warnings.append(x)
    return pieces


def _strips_of(profile, axis, n, usable, tab_w):
    """`profile` cut across `axis` into `n` strips with their puzzle tabs → (strips, cuts, errors, warnings)."""
    x0, y0, x1, y1 = profile.bounds
    w, h = x1 - x0, y1 - y0
    errors, warnings = [], []
    lo, hi = (x0, x1) if axis == 0 else (y0, y1)
    cuts = list(np.linspace(lo, hi, n + 1))
    big = 10 * max(w, h) + 1000
    # A cut through a hole or slot would leave half a connector on each piece, and a cut along the line where the
    # slots of the other family end leaves the band beyond it in loose pieces held by nothing (the tall bar's lower
    # half came apart into three). Each internal cut slides sideways to the nearest position that misses every hole
    # and leaves the piece on each side of it in one region, as long as both still fit the sheet.
    holes = [Polygon(r) for poly in as_multi(profile).geoms for r in poly.interiors]
    cut_line = lambda x: LineString([(x, -big), (x, big)] if axis == 0 else [(-big, x), (big, x)])
    band = lambda a, b: box(a, -big, b, big) if axis == 0 else box(-big, a, big, b)
    # Counted a hair in: a cut exactly where the other family's slots end left the fingers between them joined by a
    # band thousandths of a millimetre high, one region on paper and loose fingers on the sheet (the upright tall bar).
    regions = lambda g: len(as_multi(g.buffer(-0.05)).geoms)   # noqa: E731
    whole = regions(profile)                              # a slice that is islands already stays as many
    def clean(k, x):
        return (not any(h.intersects(cut_line(x)) for h in holes)
                and regions(profile.intersection(band(cuts[k - 1], x))) <= whole
                and regions(profile.intersection(band(x, cuts[k + 1]))) <= whole)
    for k in range(1, n):
        if clean(k, cuts[k]):
            continue
        for d in sorted((s * j * tab_w for j in range(1, 40) for s in (1, -1)), key=abs):
            x = cuts[k] + d
            if cuts[k - 1] + 2 * tab_w < x < cuts[k + 1] - 2 * tab_w and x - cuts[k - 1] <= usable and cuts[k + 1] - x <= usable and clean(k, x):
                cuts[k] = x; break
        else:
            errors.append(f"no split position across {'x' if axis == 0 else 'y'} keeps the pieces whole: every one leaves a loose region held by nothing — "
                          f"a bigger sheet, `one_sheet`, a smaller model, or fewer crossing slices")
    pieces_geom = []
    for i in range(n):
        a, b = cuts[i], cuts[i + 1]
        region = box(a, -big, b, big) if axis == 0 else box(-big, a, big, b)
        pieces_geom.append(profile.intersection(region))
    # tabs on each internal cut: alternate sides; add to one piece, subtract from the neighbour
    for i, c in enumerate(cuts[1:-1]):
        line = profile.intersection(box(c - 0.01, -big, c + 0.01, big) if axis == 0 else box(-big, c - 0.01, big, c + 0.01))
        if line.is_empty:
            continue
        lo2, hi2 = (line.bounds[1], line.bounds[3]) if axis == 0 else (line.bounds[0], line.bounds[2])
        n_tabs = min(MAX_TABS, max(1, int((hi2 - lo2) // (tab_w * 3))))
        along = (0, 1) if axis == 0 else (1, 0)
        tabs = []
        for j, cc in enumerate(np.linspace(lo2, hi2, n_tabs + 2)[1:-1]):
            side = 1 if j % 2 == 0 else -1
            # a tab clipped by the outline or by a hole would be a partial connector, so a tab is only placed where the
            # whole of it, with material around it, lies inside the part — at its spot or nudged along the cut
            for d in (0, tab_w, -tab_w, 2 * tab_w, -2 * tab_w):
                cx, cy = (c, cc + d) if axis == 0 else (cc + d, c)
                t = tab(cx, cy, along, tab_w, tab_w * 1.2, side)
                room = t.buffer(tab_w * 0.25)
                if profile.contains(room) and all(room.disjoint(q) for q in tabs):
                    break
            else:
                continue
            # A tab belongs to the piece it sticks out of and is cut out of the one it sticks into (the other way round
            # the union and the difference are both no-ops: no tab at all). Which piece that is follows from where the
            # tab lies, not from `side`: a positive side points to the lower piece across x but to the higher one
            # across y, and reading it from `side` left every cut across y (a tall part) a plain butt joint (bug 048).
            into_lower = (t.centroid.x if axis == 0 else t.centroid.y) < c
            owner, other = (i + 1, i) if into_lower else (i, i + 1)
            pieces_geom[owner] = unary_union([pieces_geom[owner], t])
            pieces_geom[other] = pieces_geom[other].difference(t)
            tabs.append(t)
        if not tabs:
            warnings.append(f"no puzzle tab fits along the split at {c:.0f} mm (an opening is in the way): glue that joint, or move the split with a different sheet size")
    return [as_multi(g) for g in pieces_geom if not g.is_empty], cuts, errors, warnings


def pieces_of(sl, geoms):
    """One piece per geometry, named Z-1-1, Z-1-2 … Each mark goes with the piece nearest it; each line with the piece
    it lies on, cut to it — a split's cut runs through a guide line, an island's lines are its own — and merged back
    into one line per ring, since a line along a polygon's edge comes back from GEOS cut at every vertex. The piece is
    widened by a hair for the cut, so a line on its very edge is kept whole rather than lost to rounding."""
    near = lambda g: min(range(len(geoms)), key=lambda i: geoms[i].distance(g))
    on = lambda g: [(s, part) for s, ln in sl.lines for part in as_lines(shapely.line_merge(as_lines(ln.intersection(g.buffer(1e-6))))).geoms
                    if part.length > 1e-6]
    return [Piece(f"{sl.label}-{i + 1}", as_multi(g), sl, on(g), [m for m in sl.marks if near(Point(m[:2])) == i]) for i, g in enumerate(geoms)]


def islands(sl):
    """The slice as cut: one piece per island, named like a split (Z-1-1, Z-1-2 …). A layer that falls apart into
    separate shapes — the three lobes of the wavy torus's end layers — used to be one part, nested as one rigid group
    with the empty space between its lobes and labelled once."""
    geoms = list(as_multi(sl.profile).geoms)
    if len(geoms) == 1:
        return [Piece(sl.label, sl.profile, sl, sl.lines, sl.marks)]
    return pieces_of(sl, geoms)


def split_slice(sl, sheet, margin, tab_w, grain=False):
    """Cut the slice into pieces that each fit the sheet. One pass fixes one direction, so a part over the sheet both
    ways — a big model on a small sheet — is cut the long way and then across, until every piece fits or nothing can
    be cut further. With `grain` a piece stays as it stands, so only the direction that is over the sheet is cut."""
    if fits_rotated(sl.profile, sheet, margin, grain):   # the packer may rotate the part freely (or, with grain, flip it)
        sl.pieces = islands(sl)
        return
    x0, y0, x1, y1 = sl.profile.bounds
    w, h = x1 - x0, y1 - y0
    long_first = (0, 1) if w >= h else (1, 0)
    over = lambda g, axis: g.bounds[2 + axis] - g.bounds[axis] > sheet[axis] - 2 * margin   # noqa: E731

    def passes(short):
        """The cutting passes. `short`: the second way is cut to the sheet's short side, not its long one."""
        geoms = [sl.profile]
        for axis in long_first * 2:
            bad = [i for i, g in enumerate(geoms) if not fits_rotated(g, sheet, margin, grain)]
            if not bad:
                break
            if grain and not (bad := [i for i in bad if over(geoms[i], axis)]):
                continue
            room = (sheet[axis] if grain else min(sheet) if short and axis != long_first[0] else max(sheet)) - 2 * margin
            cut = [g2 for i, g in enumerate(geoms) for g2 in (_strips(g, axis, room, tab_w, sl) if i in bad else [g])]
            if len(cut) == len(geoms):                   # nothing could be cut further (MAX_PIECES): the slice said so
                break
            geoms = cut
        return geoms

    said = lambda: (list(getattr(sl, "errors", [])), list(sl.warnings))   # noqa: E731
    before = said()
    geoms = passes(False)
    if not grain and not all(fits_rotated(g, sheet, margin) for g in geoms):
        # Both ways cut to the sheet's long side can leave a near-square piece too big for the sheet either way, once
        # its tabs stick out (a bowl's rings on 200 × 150, bug 048). The part is planned again with the second way cut
        # to the short side, and that plan is kept when every piece fits; the first one's messages go with it.
        first, first_said, first_cuts = geoms, said(), getattr(sl, "split_cuts", None)
        if hasattr(sl, "errors"):
            sl.errors[:] = before[0]
        sl.warnings[:] = before[1]
        geoms = passes(True)
        if not all(fits_rotated(g, sheet, margin) for g in geoms):
            geoms, sl.split_cuts = first, first_cuts
            if hasattr(sl, "errors"):
                sl.errors[:] = first_said[0]
            sl.warnings[:] = first_said[1]
    sl.pieces = pieces_of(sl, geoms)
    sl.warnings.append(f"split into {len(sl.pieces)} pieces ({w:.0f}×{h:.0f} mm does not fit the sheet)")
