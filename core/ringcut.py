"""Cutting a ring into pieces: across its wall, from the outline to the inner edge, each cut a line with a puzzle tab.

Shared by the band lattice (a locked band's cuts, and pieces too long) and stacked ring slices (pieces too long).
The length of a piece is measured along the band — the stretch of its outline it takes — and a piece that does not
fit the sheet is always cut further, whatever the limit, so a ring never reaches the sheet-sized strip cuts of
core/split.py, which cut across the hollow. Each cut is placed clear of the slice's own cuts (slots, dowel holes) by
`min_feature`, as near as it can to where it should be, and with a tab where one fits."""
from __future__ import annotations
import math

import numpy as np
from shapely.geometry import LineString
from shapely.ops import nearest_points, unary_union

from .geometry import as_multi
from .split import MAX_PIECES, fits_rotated, tab

CUT_W = 0.1                       # the width of the line a ring is cut apart along: the puzzle joint's own fit is the kerf's
STEP = 0.5                        # mm along the outline between the places a cut is tried
CLEAR = 3.0                       # a cut's tab needs this many tab widths of outline from the next cut


def cut_line(E, I, p, sl, mf):
    """The line a ring is cut along from its outline at E to its inner edge at I, with a puzzle tab halfway, and
    whether the tab fit — or (None, False) where the cut would run into one of the slice's cuts."""
    e, i = np.array([E.x, E.y]), np.array([I.x, I.y]); L = float(np.linalg.norm(i - e)); u = (i - e) / L
    straight = LineString([e - u * 1.0, i + u * 1.0])
    if any(straight.distance(c) < mf for c in sl.cuts):         # a distance, not a buffer per cut: 200 bands tried 800 000 of them
        return None, False
    w = min(p["tab"], L / 1.6); parts, tabbed = [straight], False
    if w >= 2.0:
        c = (e + i) / 2
        t = tab(c[0], c[1], tuple(u), w, w * 1.2, 1)
        if sl.profile.contains(t.buffer(w * 0.25)) and not any(t.distance(cc) < mf for cc in sl.cuts):
            parts, tabbed = [straight.difference(t), t.exterior.difference(straight.buffer(0.03, cap_style=2))], True
    return unary_union(parts).buffer(CUT_W / 2, cap_style=2), tabbed


def across(E, v, edge):
    """Where a line from E, along ±v, first meets `edge` (more than a hair away), or None."""
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return None
    v = np.asarray(v) / n; e = np.array([E.x, E.y]); best = None
    for sgn in (1, -1):
        hit = LineString([e + sgn * v * 0.05, e + sgn * v * 1e4]).intersection(edge)
        for q in ([hit] if hit.geom_type == "Point" else list(getattr(hit, "geoms", []))):
            if q.geom_type == "Point" and (best is None or E.distance(q) < E.distance(best)):
                best = q
    return best


class Ring:
    """One component of a slice's ring and the cuts made in it so far: [(arclength on its outline, line, tabbed)]."""
    def __init__(self, comp):
        self.comp, self.ext, self.L = comp, comp.exterior, comp.exterior.length
        self.holes = unary_union([LineString(r.coords) for r in comp.interiors])
        self.cuts = []

    def ends(self, t, slants=()):
        """Where a cut from the outline at arclength t can end: the nearest point of the inner edge, and the inner edge
        along each of `slants`; a solid stretch, with no inner edge, is cut straight across to the far side."""
        E = self.ext.interpolate(t % self.L)
        if self.holes.is_empty:
            a, b = self.ext.interpolate((t - 0.5) % self.L), self.ext.interpolate((t + 0.5) % self.L)
            return E, [across(E, (-(b.y - a.y), b.x - a.x), self.ext)]
        return E, [nearest_points(E, self.holes)[1]] + [across(E, v, self.holes) for v in slants]

    def place(self, tries, sl, p, slants=()):
        """The first of `tries` (arclengths, best first) where a cut and its tab fit, else the first where a plain cut
        fits: (t, line, tabbed), or None."""
        mf = p["min_feature"]; best = None
        for t in tries:
            E, ends = self.ends(t, slants)
            for I in ends:
                if I is None or E.distance(I) < 1e-6:
                    continue
                line, tabbed = cut_line(E, I, p, sl, mf)
                if line is not None and (tabbed or best is None):
                    best = (t, line, tabbed)
                    if tabbed:
                        return best
        return best

    def stretches(self):
        """The pieces between neighbouring cuts, as (from, to) arclength, `to` past `from`; one closed stretch, the
        whole outline, while there is at most one cut — a ring cut once is still one piece."""
        ts = sorted(c[0] % self.L for c in self.cuts)
        if len(ts) < 2:
            return [(ts[0] if ts else 0.0, (ts[0] if ts else 0.0) + self.L)]
        return [(ts[i], ts[i + 1] if i + 1 < len(ts) else ts[0] + self.L) for i in range(len(ts))]


def _between(a, b, n):
    """n arclengths spread from a to b, sorted from the middle out."""
    mid = (a + b) / 2
    return sorted((a + (b - a) * k / max(1, n - 1) for k in range(n)), key=lambda t: abs(t - mid))


def shorten(sl, p, limit, rings, geom):
    """Cut every piece of `rings` longer than `limit` along the outline (0 = no limit), or too big for the sheet, into
    pieces that are neither, the cuts spread evenly between the ones already made. `geom` is the slice as cut so far;
    returns (geom, cuts made, of them with no tab, pieces still too long or too big)."""
    sheet, margin, grain = p["sheet"], p["sheet_margin"], p["grain"]
    gap = CLEAR * p["tab"]
    made = plain = stuck = 0
    for rg in rings:
        if rg.holes.is_empty and fits_rotated(rg.comp, sheet, margin, grain) and not rg.cuts:
            continue                                             # solid, and no length to it: a plate, left whole
        # a ring many sheets round is a wrong setting, not a puzzle (as split.py says of a strip): a ring takes more
        # pieces than a strip does, so four times as many
        n = math.ceil(rg.L / min(limit or math.inf, max(sheet) - 2 * margin))
        if n > 4 * MAX_PIECES:
            sl.errors.append(f"a ring {rg.L:.0f} mm round would be cut into {n} pieces: use a bigger sheet"
                             + (" or a longer `max_length`" if limit else "") + ", a smaller model, or fewer, larger parts")
            continue
        todo, done = None, set()
        for _ in range(200):
            pieces = list(as_multi(geom).geoms)
            todo = None
            for a, b in rg.stretches():
                if (round(a, 3), round(b, 3)) in done:
                    continue
                at = rg.ext.interpolate(((a + b) / 2) % rg.L)
                piece = min(pieces, key=lambda g: g.distance(at))
                long = limit > 0 and b - a > limit
                if long or not fits_rotated(piece, sheet, margin, grain):
                    todo = (a, b, long)
                    break
            if todo is None:
                break
            a, b, long = todo
            closed = len(rg.cuts) < 2
            arc = b - a
            k = max(2, math.ceil(arc / limit)) if long else 2
            near = []
            if closed and not rg.cuts:
                # the first cut of a closed ring: anywhere — the even spread starts from wherever it lands
                tries = [a + rg.L * i / int(rg.L / STEP) for i in range(int(rg.L / STEP))]
            else:
                # nearest the even spread first, anywhere that keeps the piece before it within the limit: a window
                # only as wide as the slack in the spread closed to a single point on a band that needs its full count
                # (2400 mm round at 100 mm: 24 pieces of exactly 100), and one slot there left the band whole
                target = a + arc / k
                lo, hi = a + gap, min(b - gap, a + limit) if long else b - gap
                tries = _between(lo, hi, min(1600, int((hi - lo) / STEP) + 1)) if hi > lo else []
                tries.sort(key=lambda t: abs(t - target))
                # a tab is worth a little way, not a stub of a piece: near the spread first, tab or not, then the rest
                near = [t for t in tries if abs(t - target) <= arc / (4 * k)]
                tries = near + tries[len(near):]
            got = rg.place(near, sl, p) if not (closed and not rg.cuts) and near else None
            got = got or rg.place(tries, sl, p)
            if got is None and rg.cuts:
                # nowhere within the limit: anywhere in the stretch, so it is at least shorter, and cut again after
                wide = _between(a + gap, b - gap, min(1600, int((b - a - 2 * gap) / STEP) + 1)) if b - a > 2 * gap else []
                got = rg.place(sorted(wide, key=lambda t: abs(t - (a + limit if long else (a + b) / 2))), sl, p)
            if got is None:
                stuck += 1; done.add((round(a, 3), round(b, 3)))
                continue
            rg.cuts.append(got)
            geom = as_multi(geom.difference(got[1]))
            made += 1; plain += not got[2]
    return geom, made, plain, stuck
