"""Slots where one slice family crosses another.

For a crossing pair (A gets the slot, B passes through it) the A∩B line is cast against the mesh; every
in-mesh segment (limited to where both slices actually have material — half-slices are clipped) becomes one slot
in A, open toward A's insertion side, reaching `ratio` of the segment from that side. B gets the complementary
slot (1 − ratio) from the other side, so the two always meet.
"""
from __future__ import annotations
import math
import numpy as np
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from .geometry import plane_plane_line, line_segments_in_mesh, to_local, rect_along, circle


def slot_polygon(a_open, a_end, width, p) -> Polygon:
    """Slot in local 2D from the (overshot) open end `a_open` to the closed end `a_end`, with mouth flare and relief."""
    base = rect_along(a_open, a_end, width)
    parts = [base]
    d = np.asarray(a_end) - np.asarray(a_open); L = np.linalg.norm(d)
    if L < 1e-9:
        return base
    d = d / L; n = np.array([-d[1], d[0]])
    flare = p["notch_factor"] * width
    if flare > 0:
        depth = flare / math.tan(math.radians(p["notch_angle"]))
        mouth = np.asarray(a_open); inner = mouth + d * depth
        parts.append(Polygon([mouth + n * (width / 2 + flare), mouth - n * (width / 2 + flare),
                              inner - n * width / 2, inner + n * width / 2]))
    td = p["tool_d"]
    if td > 0 and p["relief"] != "square":
        end = np.asarray(a_end); r = td / 2
        for s in (1, -1):
            corner = end + n * s * width / 2
            if p["relief"] == "dogbone":
                c = corner + (-d + n * s) * r / math.sqrt(2)
            elif p["relief"] == "tbone_h":   # relief along the slot direction
                c = corner - d * r
            else:                             # tbone_v: relief across the slot
                c = corner + n * s * r
            parts.append(circle(c, td))
    return unary_union(parts)


def _clip_segments(segments, p0, d, slices):
    """Keep only the parts of the (s_in, s_out) intervals that lie inside every clipped slice's `clip` polygon."""
    for sl in slices:
        if sl.clip is None:
            continue
        out = []
        for s_in, s_out in segments:
            a, b = to_local(sl.M, [p0 + d * s_in, p0 + d * s_out])
            hit = LineString([a, b]).intersection(sl.clip)
            for ln in getattr(hit, "geoms", [hit]):
                if ln.is_empty or ln.geom_type != "LineString":
                    continue
                c = np.asarray(ln.coords)
                t0 = np.linalg.norm(c[0] - a) / max(np.linalg.norm(b - a), 1e-9)
                t1 = np.linalg.norm(c[-1] - a) / max(np.linalg.norm(b - a), 1e-9)
                lo, hi = sorted((s_in + (s_out - s_in) * t0, s_in + (s_out - s_in) * t1))
                if hi - lo > 0.3:
                    out.append((lo, hi))
        segments = out
    return segments


def cut_slots(a, b, ctx, open_toward, ratio, through=False):
    """Add to slice `a` the slots where slice `b` crosses it — one per in-mesh segment of the crossing line. With
    `through` (a spine and a ring: one sheet each along the line) it is one slot for the whole line instead, from
    a's own edge on the open side across every segment to the closed end — cut through where the line leaves the
    material and comes back (a chord grazing a neck), half-lapped in the segment that holds the closed end. One
    half-lap per segment is a slot no part can slide past, and a slot that stops at the lobe boundary while the
    sheet's material goes on is a slit inside it that nothing slides into."""
    p = ctx.p
    ln = plane_plane_line(a.M, b.M)
    if ln is None:
        return
    p0, d = ln
    if np.dot(d, open_toward) < 0:
        d = -d
    width = b.thickness + p["slot_offset"]
    made = 0
    segs = line_segments_in_mesh(ctx.mesh, p0, d, ctx.span)
    pieces = _clip_segments(segs, p0, d, (a, b))
    spans, edge = pieces, None
    if through and pieces:
        spans = [(min(s for s, _ in pieces), max(e for _, e in pieces))]
        edge = max(e for _, e in _clip_segments(segs, p0, d, (a,)))
    for s_in, s_out in spans:
        # d points toward the open side; the open end is s_out, closed end is s_out - ratio*length
        length = s_out - s_in
        sc = s_out - ratio * length
        closed = p0 + d * sc
        opening = p0 + d * ((s_out if edge is None else edge) + 1.0 + width)   # overshoot past the surface so the slot is open
        a_open, a_end = to_local(a.M, [opening, closed])
        cut = slot_polygon(a_open, a_end, width, p)
        a.cuts.append(cut)
        # who this slot is for + where (world) → connectivity check: the piece of material that holds the closed end
        hold = min(pieces, key=lambda m: 0.0 if m[0] <= sc <= m[1] else min(abs(sc - m[0]), abs(sc - m[1])))
        a.links.append((b.label, cut, tuple(p0 + d * (hold[0] + hold[1]) / 2)))
        made += 1
    if made:
        a.engages.append(b.label)
        a.slot_dirs[b.label] = tuple(d)          # checks.check_insertion slides b out this way and looks for what blocks it


def interlock(family_a, family_b, ctx, a_open=(0, 0, 1), b_open=(0, 0, -1), ratio=None):
    """Slot two families into each other. Family A opens toward a_open (inserted from there) and takes `ratio`."""
    ratio = ctx.p["notch_ratio"] if ratio is None else ratio
    for a in family_a:
        for b in family_b:
            cut_slots(a, b, ctx, a_open, ratio)
    for b in family_b:
        for a in family_a:
            cut_slots(b, a, ctx, b_open, 1.0 - ratio)
