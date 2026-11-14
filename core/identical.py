"""Which pieces are the same part: one cut file, one row in the cut list, a quantity."""
from __future__ import annotations
from shapely import affinity
from shapely.geometry import MultiLineString, MultiPoint
from .geometry import min_rect_angle

MATCH_AREA = 2.0     # mm² of symmetric difference under which two outlines are one part without further looking


def _same_outline(c, h, tol, w=0.1):
    """`h` is `c` as a cutter would see it: everywhere within `w` mm of it, a tenth of a millimetre, under any kerf.
    The symmetric difference decides where it is small (one part) or past `tol` of the area (two); in between the
    outlines are compared edge to edge — a 0.1 % allowance alone let a 6 mm dowel hole a millimetre off (12 mm² on a
    200 cm² layer) pass as the same part, and the second copy was cut with its holes in the wrong place, while a
    sphere's layers a few hundredths of a millimetre apart in radius are the same part to any cutter."""
    d = c.symmetric_difference(h).area
    if d <= MATCH_AREA:
        return True
    if d > tol * c.area:
        return False
    return c.buffer(w).covers(h) and h.buffer(w).covers(c)


def _moved(e, rot, x0, y0):
    """An engraving (lines, mark points, mark texts) turned `rot` about the origin and moved by (-x0, -y0), as its outline was."""
    mv = lambda g: affinity.translate(affinity.rotate(g, rot, origin=(0, 0)), -x0, -y0)
    return mv(e[0]), mv(e[1]), e[2]


def _match(c, g, tol, mirror, ce, ge, turns=(0, 90, 180, 270)):
    """How outline `g` fits outline `c` (both at the origin, long side along x): "same" under one of `turns`,
    "flipped" when it only fits as its mirror image, None when it does not fit at all. What is engraved on them (`ce`,
    `ge`: guide lines, marks with their texts, in the same frames) has to coincide under that same move: two slices
    with the same outline but another layer's outline, or another seam number, marked on them are two parts."""
    if abs(c.area - g.area) > tol * c.area:
        return None
    flip = lambda x: affinity.scale(x, -1, 1, origin=(0, 0))
    tries = (("same", g, ge), ("flipped", flip(g), (flip(ge[0]), flip(ge[1]), ge[2]))) if mirror else (("same", g, ge),)   # mirrored once, not per turn
    for kind, m, me in tries:
        for r in turns:
            h = affinity.rotate(m, r, origin=(0, 0)); x0, y0, _, _ = h.bounds
            if _same_outline(c, affinity.translate(h, -x0, -y0), tol) and _coincide(ce, _moved(me, r, x0, y0)):
                return kind
    return None


def _coincide(a, b, w=0.05):
    """Engravings `a` and `b` are the same: each line set within `w` mm of the other (well under a kerf and over any
    drift), and every mark's text at the other's spot, within half a millimetre."""
    (la, pa, ta), (lb, pb, tb) = a, b
    if la.is_empty != lb.is_empty or not (la.is_empty or la.buffer(w).covers(lb) and lb.buffer(w).covers(la)):
        return False
    return len(ta) == len(tb) and all(any(t == u and p.distance(q) < 0.5 for q, u in zip(pb.geoms, tb)) for p, t in zip(pa.geoms, ta))


def mark_identical(pieces, mirror=False, tol=1e-3, grain=False):
    """Pieces with the same cut outline — kerf applied, any quarter turn, and with `mirror` also turned over — are one
    part in several copies: the first of each set keeps the others' labels in `same`, the ones that have to be turned
    over in `flipped`, so they are cut once with a quantity and listed once. What is engraved on a piece — a guide line
    (stacked, `next_outline`), a seam number — is part of what the piece is and has to match too; fold lines keep every
    folded panel a part of its own. With `grain` only a copy as it stands or upside down is the same part: one turned
    sideways would be cut across the grain."""
    groups = []                                     # [(first piece, its outline at the origin, what is engraved on it there)]
    for pc in pieces:
        if any(s != "guide" for s, _ in pc.lines):  # score lines (folded panels): each fold pattern is its own part
            continue
        a = 0.0 if grain else min_rect_angle(pc.kerfed)
        g = affinity.rotate(pc.kerfed, a, origin=(0, 0)); x0, y0, _, _ = g.bounds; g = affinity.translate(g, -x0, -y0)
        ge = _moved((MultiLineString([ln for _, ln in pc.lines]), MultiPoint([m[:2] for m in pc.marks]), [m[2] for m in pc.marks]), a, x0, y0)
        for first, c, ce in groups:
            # same outline but cut from other stock is not the same part: it belongs on the other thickness's sheet
            kind = _match(c, g, tol, mirror, ce, ge, (0, 180) if grain else (0, 90, 180, 270)) if first.parent.thickness == pc.parent.thickness else None
            if kind:
                (first.same if kind == "same" else first.flipped).append(pc.label)
                break
        else:
            groups.append((pc, g, ge))
