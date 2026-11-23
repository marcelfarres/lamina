"""Ring slices: a section with only a wall of a set width left inside its outline, the middle cut away.

Shared by stacked (`ring_slices`) and the band lattice (`bands`). The wall is measured in the slice's own plane, so it is
the same width all the way round whatever the slope of the surface — unlike `hollow`, which shells the 3D model and
leaves a slice through a gently sloping wall much wider than the wall asked for, and its top and bottom solid."""
from __future__ import annotations
from shapely.ops import nearest_points, unary_union
from .geometry import as_multi


def middle(section, wall, min_feature):
    """What is cut away from `section` to leave a wall `wall` wide: the section moved in by the wall, with every
    stretch of it narrower than `min_feature` left out. Each island and each hole of the section gets its own wall,
    because moving the outline in moves a hole's edge out. Where the section is narrower than twice the wall there
    is no middle, and it stays solid there. Empty when the wall is 0 or nothing is left to cut away."""
    if wall <= 0 or section is None or section.is_empty:
        return as_multi(None)
    inner = section.buffer(-wall)
    if inner.is_empty:
        return as_multi(None)
    # an opening as thin as a hair is not a hole worth cutting: an opening by min_feature takes those out
    inner = inner.buffer(-min_feature / 2).buffer(min_feature / 2)
    return as_multi(inner.intersection(section))


def ring(section, wall, min_feature):
    """The section with its middle cut away (see `middle`): the ring that stays."""
    mid = middle(section, wall, min_feature)
    return as_multi(section) if mid.is_empty else as_multi(section.difference(mid))


COLLAR = 2.0   # × min_feature: wider than the widest wall checks.thin_spots flags (1.5 × min_feature, its second tier)


def collared(section, wall, cuts, min_feature):
    """The ring `wall` grown locally round each of `cuts` (dowel holes, tab slots) so each sits in material: a collar
    COLLAR × `min_feature` wide round the cut, wider than any wall the thin-spot check flags (at exactly 1.5 × it
    flagged every peg slot's collar), and a stem as wide as the collar from it to the nearest point of the ring, the
    corners where it meets the ring filled in. Kept inside `section`, so the outline is never crossed. Returns the ring
    as cut."""
    if not cuts:
        return wall
    keep = [wall]
    for c in cuts:
        half = max(c.bounds[2] - c.bounds[0], c.bounds[3] - c.bounds[1]) / 2
        collar = c.buffer(COLLAR * min_feature)
        if not wall.is_empty and c.distance(wall) > 0:
            _, near = nearest_points(c, wall)
            collar = unary_union([collar, near.buffer(half + COLLAR * min_feature)]).convex_hull
        keep.append(collar)
    # closing by min_feature fills the notch where a collar meets the ring: no thin neck, no sharp inside corner
    r = min_feature
    return as_multi(unary_union(keep).buffer(r).buffer(-r).intersection(section))
