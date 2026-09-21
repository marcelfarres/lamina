"""Split a slice that does not fit the sheet into pieces joined by puzzle tabs."""
from __future__ import annotations
import math
import numpy as np
from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union
from .geometry import as_multi, circle
from .checks import min_dims
from .model import Piece

# every tab is a union and a difference on the growing piece outlines, so the count decides whether a split takes a
# second or an hour: beyond these it is the sheet or the model that is wrong, and the slice says so instead
MAX_PIECES = 12                       # sheets a part may span
MAX_TABS = 24                         # tabs along one cut

def fits(w, h, sheet, margin):
    sw, sh = sheet[0] - 2 * margin, sheet[1] - 2 * margin
    return (w <= sw and h <= sh) or (h <= sw and w <= sh)


def fits_rotated(geom, sheet, margin):
    """Does the part fit the sheet in any orientation?

    The minimum-area rectangle alone is not enough: for a diagonal shape it can be longer than the axis-aligned box
    (a 500x380 panel measured 493x460 that way and was refused although it fits upright). Either box fitting suffices.
    """
    x0, y0, x1, y1 = geom.bounds
    if fits(x1 - x0, y1 - y0, sheet, margin):
        return True
    small, large = min_dims(geom)
    return fits(large, small, sheet, margin)


def tab(cx, cy, along, w, depth, side):
    """Round-headed puzzle tab centred on the cut line at (cx,cy), protruding `depth` to `side`."""
    ax, ay = along; px, py = -ay * side, ax * side
    neck = w * 0.55
    body = Polygon([(-neck / 2, -0.01), (neck / 2, -0.01), (neck / 2, depth * 0.5), (-neck / 2, depth * 0.5)])
    head = circle((0, depth * 0.5 + w * 0.3), w * 0.9)
    shape = unary_union([body, head])
    return Polygon([(cx + ax * x + px * y, cy + ay * x + py * y) for x, y in shape.exterior.coords])


def _strips(profile, axis, sheet, margin, tab_w, sl):
    """Cut `profile` across `axis` into strips joined by puzzle tabs. Returns the strips (the profile itself when it
    would take more than MAX_PIECES, with the slice saying so)."""
    x0, y0, x1, y1 = profile.bounds
    w, h = x1 - x0, y1 - y0
    usable = max(sheet) - 2 * margin - 2 * tab_w
    n = max(2, math.ceil((w if axis == 0 else h) / usable))
    if n > MAX_PIECES:                                    # a part many sheets long is a wrong setting, not a puzzle
        sl.errors.append(f"{w:.0f}×{h:.0f} mm is {n} sheets long: use a bigger sheet or `one_sheet`, a smaller model, or a technique with smaller parts")
        return [profile]
    lo, hi = (x0, x1) if axis == 0 else (y0, y1)
    cuts = list(np.linspace(lo, hi, n + 1))
    big = 10 * max(w, h) + 1000
    # a cut through a hole or slot would leave half a connector on each piece: slide each internal cut sideways to
    # the nearest position that misses every hole, as long as both neighbouring pieces still fit the sheet
    holes = [Polygon(r) for poly in as_multi(profile).geoms for r in poly.interiors]
    cut_line = lambda x: LineString([(x, -big), (x, big)] if axis == 0 else [(-big, x), (big, x)])
    for k in range(1, n):
        if not any(h.intersects(cut_line(cuts[k])) for h in holes):
            continue
        for d in sorted((s * j * tab_w for j in range(1, 40) for s in (1, -1)), key=abs):
            x = cuts[k] + d
            if (cuts[k - 1] + 2 * tab_w < x < cuts[k + 1] - 2 * tab_w and x - cuts[k - 1] <= usable and cuts[k + 1] - x <= usable
                    and not any(h.intersects(cut_line(x)) for h in holes)):
                cuts[k] = x; break
    sl.split_cuts = cuts
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
            # tab() protrudes toward the LOWER piece for side > 0, so that tab belongs to the higher piece and is cut
            # out of the lower one (the other way round the union and the difference are both no-ops: no tab at all)
            owner, other = (i + 1, i) if side > 0 else (i, i + 1)
            pieces_geom[owner] = unary_union([pieces_geom[owner], t])
            pieces_geom[other] = pieces_geom[other].difference(t)
            tabs.append(t)
        if not tabs:
            sl.warnings.append(f"no puzzle tab fits along the split at {c:.0f} mm (an opening is in the way): glue that joint, or move the split with a different sheet size")
    return [as_multi(g) for g in pieces_geom if not g.is_empty]


def split_slice(sl, sheet, margin, tab_w):
    """Cut the slice into pieces that each fit the sheet. One pass fixes one direction, so a part over the sheet both
    ways — a big model on a small sheet — is cut the long way and then across, until every piece fits or nothing can
    be cut further."""
    if fits_rotated(sl.profile, sheet, margin):          # the packer may rotate the part freely
        sl.pieces = [Piece(sl.label, sl.profile, sl, sl.lines, sl.marks)]
        return
    x0, y0, x1, y1 = sl.profile.bounds
    w, h = x1 - x0, y1 - y0
    long_first = (0, 1) if w >= h else (1, 0)
    geoms = [sl.profile]
    for axis in long_first * 2:
        bad = [i for i, g in enumerate(geoms) if not fits_rotated(g, sheet, margin)]
        if not bad:
            break
        cut = [g2 for i, g in enumerate(geoms) for g2 in (_strips(g, axis, sheet, margin, tab_w, sl) if i in bad else [g])]
        if len(cut) == len(geoms):                       # nothing could be cut further (MAX_PIECES): the slice said so
            break
        geoms = cut
    sl.pieces = [Piece(f"{sl.label}-{i + 1}", g, sl) for i, g in enumerate(geoms)]
    sl.warnings.append(f"split into {len(sl.pieces)} pieces ({w:.0f}×{h:.0f} mm does not fit the sheet)")
