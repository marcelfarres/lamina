"""Does each piece of a band lattice reach its place, sliding in along its own motion, past the pieces already there?

A piece moves in its own plane only, so all of this is 2D in that plane: the other pieces of its band as they are, and
a piece of a crossing band as the strip of it on the line the two planes meet on, as wide as that band is thick. A
piece is free when those, swept along its motion, cover none of it — its slots have room for them to pass. The order
comes from taking the lattice apart: any piece free against everything still there comes out, and taking a piece out
only frees others, so a piece that has a way in for a straight slide is always found one. The assembly order is the
reverse. Where nothing more comes out, one piece is locked: it is taken out all the same, and what it held follows."""
from __future__ import annotations
import itertools

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from .geometry import as_lines, as_multi, plane_plane_line, to_local, to_world

# mm²: how much a sweep may cover of a piece and still let it pass. A strip's sweep runs along a slot's sides and a
# swept neighbour along a cut, so in a lattice that fits what they share is nothing, or float dust; a clash is a band's
# thickness by a wall, or a puzzle tab's head past its neck — tens of mm². Between the two, a tip rubbing past by a
# tenth or two of a millimetre along a few mm (measured: 0.05 to 1.2 mm² on the sphere and the head) — up to this
# much the kerf and the stock's give take it
FREE_AREA = 0.5


class Part:
    """One piece as the check sees it: `geom` in its band's frame, the ways it can slide in (`moves`, 2D unit vectors
    in that frame, tried in turn), and whether it is the fixed base (`fixed`: a first-family band, never moved)."""
    def __init__(self, label, band, geom, moves, fixed):
        self.label, self.band, self.geom, self.moves, self.fixed = label, band, geom, moves, fixed


def sweep(geom, v):
    """Everywhere `geom` passes moving by v: itself, where it ends, and the band each edge of it sweeps. Only an edge
    that faces along v sweeps outside the shape, and a run of those runs one way across v, so each run sweeps one
    simple polygon: the run and its translate — a few polygons to join, not one per edge. A convex shape (a crossing
    band's strip) is simpler still: the hull of where it starts and ends."""
    if geom.geom_type == "Polygon" and len(geom.exterior.coords) <= 5 and not geom.interiors:
        c = shapely.get_coordinates(geom)
        return shapely.multipoints(np.vstack([c, c + v])).convex_hull
    moved = shapely.affinity.translate(geom, *v)
    runs = []
    for g in as_multi(geom).geoms:
        g = orient(g)                                        # the material on the left of every edge, holes too
        for r in (g.exterior, *g.interiors):
            c = np.asarray(r.coords)[:-1, :2]; e = np.roll(c, -1, axis=0) - c
            front = e[:, 0] * v[1] - e[:, 1] * v[0] < -1e-9   # the outside of the edge faces along v
            if front.all():
                runs.append(np.vstack([c, c[:1]])); continue
            k = int(np.argmin(front))                        # start the walk on an edge that does not face along v
            for on, grp in itertools.groupby(np.roll(np.arange(len(c)), -k), key=lambda i: front[i]):
                if on:
                    idx = list(grp)
                    runs.append(c[idx + [(idx[-1] + 1) % len(c)]])
    return shapely.union_all([geom, moved, *(Polygon(np.vstack([p, p[::-1] + v])) for p in runs)])


def covers(obstacle, part, v, swept=None):
    """How much of `part` the obstacle covers as it sweeps along v. Most never come near: measured along v and across
    it, the sweep spans the obstacle's width across, and from its near end on along — when the part is outside either,
    nothing is swept over it, and the sweep is not made. `swept` keeps the sweeps made, for the next part to ask."""
    v = np.asarray(v, float); u = v / np.linalg.norm(v); w = np.array([-u[1], u[0]])
    a, b = shapely.get_coordinates(obstacle), shapely.get_coordinates(part)
    if (a @ w).min() > (b @ w).max() or (a @ w).max() < (b @ w).min() or (a @ u).min() > (b @ u).max():
        return 0.0
    swept = {} if swept is None else swept
    key = (id(obstacle), v.tobytes())
    if key not in swept:
        swept[key] = sweep(obstacle, v)
    return float(part.intersection(swept[key]).area)


def strips(a, b, parts, span):
    """Each of `parts` (of band b) as it lies in band a's plane: its material on the line the planes meet on, as wide
    as b's slab is across a's plane → [(part, strip in a's frame)]. Parallel planes: none."""
    ln = plane_plane_line(a.M, b.M)
    if ln is None:
        return []
    p0, d = ln
    line = LineString(to_local(b.M, [p0 - d * span, p0 + d * span]))
    w = b.thickness / max(1e-6, float(np.linalg.norm(np.cross(a.M[:3, 2], b.M[:3, 2]))))
    out = []
    for q in parts:
        for seg in as_lines(line.intersection(q.geom)).geoms:
            ends = to_local(a.M, to_world(b.M, np.asarray(seg.coords)[[0, -1]]))
            out.append((q, LineString(ends).buffer(w / 2, cap_style=2)))
    return out


def solve(parts, span):
    """The order the pieces go in and those that cannot: ([(part, move)], {part: the part most in its way}). The fixed
    parts are in place from the start and in neither."""
    by_band = {}
    for q in parts:
        by_band.setdefault(q.band.label, []).append(q)
    bands = {q.band.label: q.band for q in parts}
    cross = {}                                                # (band, other band) → strips, each pair once
    blocked = {}                                              # (part, move index) → {part in the way: area}
    swept = {}                                                # a piece's sweep serves every piece of its band moving that way
    for q in parts:
        if q.fixed:
            continue
        a = q.band
        obstacles = [(o, o.geom) for o in by_band[a.label] if o is not q]
        for lab, b in bands.items():
            if b.group != a.group:                            # the same family: parallel planes, never in each other's way
                key = (a.label, lab)
                if key not in cross:
                    cross[key] = strips(a, b, by_band[lab], span)
                obstacles += cross[key]
        for k, m in enumerate(q.moves):
            v = np.asarray(m) * span
            got = {}
            for o, g in obstacles:
                area = covers(g, q.geom, v, swept)
                if area > FREE_AREA:
                    got[o] = max(got.get(o, 0.0), area)
            blocked[q, k] = got
    present = set(parts); out = []; locked = {}
    moving = [q for q in parts if not q.fixed]
    in_way = lambda q: min(({o: s for o, s in blocked[q, k].items() if o in present} for k in range(len(q.moves))),   # noqa: E731
                           key=lambda w: (len(w), sum(w.values())), default={})
    while stuck := [q for q in moving if q in present]:
        free = next(((q, k) for q in stuck for k in range(len(q.moves)) if not blocked[q, k].keys() & present), None)
        if free:
            present.discard(free[0]); out.append((free[0], free[0].moves[free[1]]))
            continue
        # nothing comes out: one of these cannot get in — first one the fixed bands stop whatever else is out of the
        # way, then the one with the least in its way. Taken out all the same, what it held can follow, and goes in
        # before it — so a locked piece is reported, not the pieces behind it
        held = lambda q: all(any(o.fixed for o in blocked[q, k]) for k in range(len(q.moves)))   # noqa: E731
        q = min(stuck, key=lambda q: (not held(q), len(in_way(q)), sum(in_way(q).values())))
        w = in_way(q); locked[q] = max(w, key=lambda o: (o.fixed, w[o])) if w else None   # a fixed band first: always there
        present.discard(q)
    return out[::-1], locked
