"""Band lattice: the model cut into rings — bands — along any of x, y and z, half-lapped where two bands cross.

Each band is a section with only a wall left inside its outline (core/ring.py). Where two bands cross, the line their
planes meet on runs through both walls in short stretches — usually two per pair, one on each side of the model —
and each stretch is one joint: a slot in each band, from opposite ends, meeting in the middle (`notch_ratio`). Where
the line runs along a wall instead of through it, the slot would split that wall lengthwise: such a band is first
moved a little along its normal, off it (nudge).

Assembly is family by family, in `order`. The first family stays whole. A band of a later family slides onto the
bands already in place along the crossing line of each joint, inward from the surface; a band whose joints ask for
different directions — the top and the bottom of a ring, or joints with two families — cannot go in whole, so it is
cut between them into pieces that each slide one way. So each joint's slot opens outward in the band placed first and
inward in the band placed after it, and runs through the rest of that band's wall along the line, so nothing of either
is in the other's way as it slides in. A joint solid right across the model slides the way of its neighbours on its
line (settle). A cut goes only where each piece, slid in, passes the bands of the joints either side (plain). Where
two joints are too close for one: if the wall between their slots is boxed in by both earlier bands — their lines
cross in or near it — that corner is cut off and glued in last, and the wall either side slides either joint's way;
else the band is cut along one joint's line up to its slot, the earlier band clamped between the two pieces
(corner_cuts).

A puzzle tab mates only pressed in from above, and a band's piece arrives in its own plane, held there by its slots: so
a later band's cuts are rejoined by a straight tongue along the way the later piece at the cut slides in, which needs
the order the pieces go in. `lattice` cuts every band plainly, asks core/slidein.py for that order, cuts again with
the tongues, and checks the order once more on the pieces as cut — a piece that cannot get in is an error."""
from __future__ import annotations
import itertools
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union

from . import Mode, Param, register
from ..geometry import as_multi, crossings, section_polygons, to_local
from ..model import Slice
from ..notch import _clip_segments, slot_polygon
from ..ring import ring as ring_of
from ..ringcut import CUT_W, STEP, Ring, shorten
from ..slidein import FREE_AREA, Part, covers, solve, strips, sweep

FAMS = "xyz"
ORDERS = ["auto"] + ["".join(o) for o in itertools.permutations(FAMS)]
SQUARE = np.cos(np.radians(45))      # a tongue only where the later piece slides into the cut within 45° of square to it
ALONG = 0.1                          # and a piece slides along a cut it meets up to 6° the wrong way: the kerf is its room
# A crossing band's sheet runs along a band's wall where it touches the wall — grown by half the sheet, the growth taken
# off the length again — for more than this many walls on their line (nudge): the slot follows the line through that
# wall and splits it lengthwise, or, with the line just off the wall, the sheet goes through the wall with no slot at
# all; the pieces beside it have no way in. Measured with 2 to 4 bands per family: the sphere's and the cube's walls,
# met straight or slanting, at most 2.8 walls long (3.1 in 3 mm stock, at the end bands of 2); along the head's flat
# sides 3 to 10, and each piece the head locked at its defaults was beside one. The sphere's end bands of 3 run inside
# its shell right across it (7.5 walls): moved, the sphere loses the loose regions their slots cut
GRAZE = 3.25
STEPS = 6                            # places tried each way, evenly up to REACH of the spacing: on the head 4 left graze, 6 none
REACH = 0.25                         # of the spacing to the next band: a band never passes its neighbour or leaves the model
NUDGE_BANDS = 40                     # more bands than this: no search for grazing joints (each try re-finds a band's joints)


@dataclass
class Band(Slice):
    """A band, with the pieces `Bands.lattice` cut it into (None: whole) for plan.build's `cut` hook."""
    cut_to: list | None = None


def inplane(M, d):
    """World direction d, in M's plane, as a 2D unit vector in M's frame."""
    v = (np.linalg.inv(M)[:3, :3] @ d)[:2]
    return v / np.linalg.norm(v)


class Joint:
    """One stretch of a crossing line where two bands' walls overlap: `a` placed before `b`. Along the world line
    p0 + d·s it runs from `lo` to `hi`; `out` is the way to the model's surface from it (+1 along d, −1 against, 0 when
    the wall is solid right across the model there and either way will do)."""
    def __init__(self, a, b, p0, d, lo, hi, out):
        self.a, self.b, self.p0, self.d, self.lo, self.hi, self.out = a, b, p0, d, lo, hi, out
        self.slots, self.ends = {}, {}       # per band label: its slot here, and the slot's closed end (2D, its frame)
        self.free = out == 0                 # solid right across: `out` is settled (Bands.settle), then may turn (slot)

    def at(self, s):
        return self.p0 + self.d * s

    @property
    def mid(self):
        return self.at((self.lo + self.hi) / 2)

    def motion(self):
        """How the later band moves as it goes in: inward along the line. A key, so two joints compare equal."""
        if self.out == 0:
            return None
        v = -self.out * self.d
        return tuple(np.round(v, 3))


@register
class Bands(Mode):
    name = "bands"
    title = "Band Lattice"
    rank = 1                           # listed after the original's techniques
    description = ("Rings (bands) cut along any of x, y and z — only a wall left inside each section — half-lapped where two "
                   "bands cross. The first family stays whole; a band that cannot slide in whole is cut into pieces, each cut "
                   "rejoined by a straight tongue the later piece slides onto, and every piece is checked to get past the "
                   "ones already in. It suits simple round or boxy shapes (a sphere, an egg, a box). On a shape with long flat "
                   "sides, a band whose crossing line runs along a wall is moved a little off it; some pieces may still have no "
                   "way in, and the Checks tab names each one.")
    legend = ("X-2 = the 2nd band across x, Y-4 the 4th across y, Z-1 the 1st across z, each counted from the low end · "
              "X-2-1, X-2-2 = the pieces a band is cut into, each cut a straight tongue the later piece slides onto (a puzzle "
              "tab in the first family) · assembly: the first family's bands go in whole, then the other pieces one at a time, "
              "each slid in along its slots from outside the model; a small corner cut off between two slots has no joint and "
              "is glued in last · a band moved off a grazing joint keeps its label: the notes say how far")
    params = [
        Param("x", "bool", True, "Bands across x (planes square to x)", label="x bands", section="Families — which bands, and how many"),
        Param("y", "bool", True, "Bands across y (planes square to y)", label="y bands"),
        Param("z", "bool", True, "Bands across z (planes square to z)", label="z bands"),
        Param("distribution", "choice", "count", "count = this many bands per family; distance = one band every so many mm, per family",
              choices=["count", "distance"]),
        Param("nx", "int", 4, "x bands: how many", 1, 200, 1, show_if=("distribution", "count"), label="x count"),
        Param("ny", "int", 4, "y bands: how many", 1, 200, 1, show_if=("distribution", "count"), label="y count"),
        Param("nz", "int", 4, "z bands: how many", 1, 200, 1, show_if=("distribution", "count"), label="z count"),
        Param("spacing_x", "number", 40, "x bands: one every so many mm", 1, 1000, 0.5, unit="mm", show_if=("distribution", "distance"), label="x spacing"),
        Param("spacing_y", "number", 40, "y bands: one every so many mm", 1, 1000, 0.5, unit="mm", show_if=("distribution", "distance"), label="y spacing"),
        Param("spacing_z", "number", 40, "z bands: one every so many mm", 1, 1000, 0.5, unit="mm", show_if=("distribution", "distance"), label="z spacing"),
        Param("ring_wall", "number", 8.0, "How wide each band's wall is (mm), measured in its own plane from the outline in. Every "
              "island and hole gets its own wall; where a section is narrower than twice the wall it stays solid. A band can "
              "have its own: select it in the 3D view", 0.5, 500, 0.5, unit="mm", label="wall", section="Bands — the wall"),
        Param("wall", "map", {}, "Per-band wall (mm)", group="slices", unit="mm", label="own walls"),
        Param("order", "choice", "auto", "Which family goes in first (and stays whole), second and third. auto = the order that "
              "needs the fewest cuts", choices=ORDERS, label="assembly order", section="Assembly — the order, and the cuts it needs",
              choice_labels={"auto": "auto (fewest cuts)", **{o: " → ".join(o.upper()) for o in ORDERS[1:]}}),
        Param("band_cuts", "bool", True, "Cut every band that cannot slide in whole into pieces that can, between the joints that "
              "ask for different directions, each cut rejoined by a straight tongue (`tab` wide) along the way the later piece slides "
              "in, or glued where none fits. Where two joints are too close for a cut between them, the cut goes along one of "
              "them, or the corner between their slots is cut off and glued in last. Off = such a band is an error",
              label="cut locked bands"),
        Param("nudge", "bool", True, "Move a band a little along its normal where the sheet of a band it crosses runs along "
              f"its wall, or along the other band's wall, for more than {GRAZE:g} walls: the slot cut along that line would split "
              "the wall lengthwise, and the pieces beside it could not slide in. A band moves at most a quarter of the way to "
              "its neighbour, and the notes name each band moved, how far and why. A band you moved yourself (offset, tilt, "
              f"roll) stays where you put it. Up to {NUDGE_BANDS} bands. Off = every band stays where the count or spacing "
              "puts it", label="move grazing bands"),
        Param("max_length", "number", 0.0, "Longest piece (mm), measured along the band: a longer one is cut again, the cuts spread "
              "evenly between the joints, clear of the slots, each with a tongue (a puzzle tab in the first family). 0 = no "
              "limit. A piece too big for the sheet is always cut", 0, 10000, 5, unit="mm", label="max piece length"),
        Param("cut_shift", "map", {}, "Slide a band's cuts along it (mm), each within the stretch between its two joints", group="slices", unit="mm", label="cut shifts"),
    ]

    # ---------------------------------------------------------------- build
    def build(self, ctx):
        p = ctx.p
        on = [f for f in FAMS if p[f]]
        self.joints, self.first, self.order, self.corners, self.pitch, self.moved = [], None, [], {}, {}, {}
        if len(on) < 2:
            e = "band lattice: turn on at least two of x, y and z bands — one family alone has nothing to cross"
            ctx.errors.append(e)
            ctx.fixes.append({"error": e, "options": [{"title": f"add {f} bands", "set": {f: True}} for f in FAMS if f not in on]})
            return []
        mf = p["min_feature"]
        if p["ring_wall"] < mf:
            e = f"band wall {p['ring_wall']:g} mm is thinner than min_feature ({mf:g} mm): the bands would break"
            ctx.errors.append(e)
            ctx.fixes.append({"error": e, "options": [{"title": f"wall {2 * mf:g} mm", "set": {"ring_wall": 2 * mf}}]})
        fams = {f: self.family(ctx, f) for f in on}
        fams = {f: v for f, v in fams.items() if v}
        joints = self.find_joints(ctx, fams)
        if p["nudge"]:
            joints = self.nudge(ctx, fams, joints)
        order = self.pick_order(p["order"], list(fams), joints)
        rank = {f: i for i, f in enumerate(order)}
        # a joint's `a` is the band placed first
        self.joints = [j if rank[j.a.group.lower()] < rank[j.b.group.lower()] else Joint(j.b, j.a, j.p0, j.d, j.lo, j.hi, j.out) for j in joints]
        self.first, self.order = order[0], order
        bands = [b for f in order for b in fams[f]]
        later = [b for b in bands if b.group.lower() != self.first]
        for b in later:
            self.settle(b)
        for j in self.joints:
            self.slot(ctx, j)
        for j in self.joints:
            if j.free:
                self.turn(ctx, j)
        self.walls = {b.label: as_multi(b.raw.difference(unary_union(b.cuts))) for b in bands}   # the profiles to come
        self.corners = {b.label: self.corner_cuts(ctx, b) for b in later} if p["band_cuts"] else {}
        self.flag(ctx, bands)
        ctx.cover_r = max(float(np.ptp((ctx.mesh.vertices - ctx.mid) @ ctx.ax[FAMS.index(f)])) / max(1, len(v)) for f, v in fams.items()) / 2 + p["thickness"]
        return bands

    def family(self, ctx, f):
        """The bands of family `f`: planes square to its axis, spread by count or spacing, each the section moved in
        by its wall. The ring is the band's `clip` too, so a crossing's slots are cut only where both walls are."""
        p = ctx.p; i = FAMS.index(f); e = ctx.ax[i]; up = ctx.ax[1] if f == "z" else ctx.ax[2]
        v = (ctx.mesh.vertices - ctx.mid) @ e
        L = float(np.ptp(v)); c = float(v.min() + v.max()) / 2
        n = p["n" + f] if p["distribution"] == "count" else max(1, int(L // p["spacing_" + f]))
        self.pitch[f] = L / n
        out = []
        for j, s in enumerate(ctx.positions(L, [p["thickness"]] * n)):
            lab = f"{f.upper()}-{j + 1}"
            out.append(Band(lab, f.upper(), ctx.frame(lab, ctx.mid + e * (c + s), e, up_hint=up), ctx.thickness_of(lab)))
        out = ctx.keep(out)
        for b in out:
            self.ring(ctx, b)
        return [b for b in out if not b.raw.is_empty]

    @staticmethod
    def ring(ctx, b):
        b.raw = b.clip = ring_of(section_polygons(ctx.mesh, b.M), ctx.override("wall", b.label, ctx.p["ring_wall"]), ctx.p["min_feature"])
        return b

    @staticmethod
    def find_joints(ctx, fams, only=None, grow=0.0):
        """Every stretch where two bands' walls overlap on their crossing line, with the way out to the surface, and how
        far each band's own wall runs along the line there (`along`: the length its slot follows); with `only`, the
        joints of that band alone. `grow`: each wall grown by that much all round first — where a crossing band's sheet,
        not only its plane, touches the wall (nudge)."""
        def wall(b):
            return Bands.grown(b, grow) if grow else b
        pairs = [(a, b) for f, g in itertools.combinations(list(fams), 2) for a in fams[f] for b in fams[g] if only is None or only is a or only is b]
        lines = crossings(ctx.mesh, ctx.span, [(a.M, b.M) for a, b in pairs])
        out = []
        for (a, b), cr in zip(pairs, lines):
            if cr is None:
                continue
            p0, d, segs = cr
            for (s0, s1), (t0, t1) in itertools.product(_clip_segments(segs, p0, d, (wall(a),)), _clip_segments(segs, p0, d, (wall(b),))):
                lo, hi = max(s0, t0), min(s1, t1)
                if hi - lo <= 0.3:
                    continue
                seg = min(segs, key=lambda m: 0.0 if m[0] - 1e-6 <= (lo + hi) / 2 <= m[1] + 1e-6 else min(abs(lo - m[0]), abs(hi - m[1])))
                to_hi, to_lo = seg[1] - hi, lo - seg[0]
                o = 0 if max(to_hi, to_lo) < 0.5 else (1 if to_hi <= to_lo else -1)
                out.append(Joint(a, b, p0, d, lo, hi, o))
                out[-1].along = ((a, s1 - s0), (b, t1 - t0))
        return out

    @staticmethod
    def grown(b, g):
        """Band b's wall grown by g all round, as _clip_segments takes a band: where a crossing band's sheet touches it."""
        if getattr(b, "_grown", (None,))[0] != g:
            b._grown = (g, SimpleNamespace(M=b.M, clip=b.clip.buffer(g)))
        return b._grown[1]

    def nudge(self, ctx, fams, joints):
        """Bands moved off grazing joints (GRAZE): each band in one is moved along its normal, as a hand `offset` moves
        it, to the nearest of STEPS places each way where its joints graze least, and not where it would stop crossing
        a band it crosses. The bands of one family share no joint, so each goes to its own best place; family by
        family, twice over, as moving one family moves the others' lines. A step is at most REACH of the spacing, so a
        band never passes its neighbour (each moves a quarter of the way at most) or leaves the model (the end bands
        sit half a spacing in). Measured on the walls grown by half the thickest sheet (`grown`), so a line just off a
        wall still grazes it. A band moved, tilted or rolled by hand stays. `fams` takes the moved bands → the joints
        as they are now; self.moved: {label: (mm, why)}."""
        p = ctx.p
        if sum(map(len, fams.values())) > NUDGE_BANDS:
            return joints
        hand = {lab for k in ("offset", "tilt", "roll") for lab, v in dict(p[k]).items() if v}
        wall = lambda b: ctx.override("wall", b.label, p["ring_wall"])   # noqa: E731
        grow = max(b.thickness for v in fams.values() for b in v) / 2
        base, exact = {b.label: b for v in fams.values() for b in v}, joints
        tried = {(lab, 0.0): (b, {}) for lab, b in base.items()}   # (label, mm) → (the band there, {other label: (it, joints)})
        joints = self.find_joints(ctx, fams, grow=grow)

        def graze(j):                                      # (the band whose wall j's line runs along, how far: mm)
            b, r = max(j.along, key=lambda t: t[1] / wall(t[0]))
            return b, r - 2 * grow

        def score(js):                                     # how many walls past GRAZE, all told
            return sum(max(0.0, graze(j)[1] / wall(graze(j)[0]) - GRAZE) for j in js)

        def trial(f, b, o):                                # band b moved o mm, and its joints: only those with a band
            if (b.label, o) not in tried:                  # moved since the last look are found again
                M = b.M.copy(); M[:3, 3] += M[:3, 2] * o                # as ctx.frame applies a hand `offset`
                tried[b.label, o] = (self.ring(ctx, Band(b.label, b.group, M, b.thickness)), {})
            nb, per = tried[b.label, o]
            stale = {g: [c for c in v if per.get(c.label, (None,))[0] is not c] for g, v in fams.items() if g != f}
            if not nb.raw.is_empty and any(stale.values()):
                near = self.find_joints(ctx, {g: [nb] if g == f else stale[g] for g in fams}, only=nb, grow=grow)
                for c in itertools.chain(*stale.values()):
                    per[c.label] = (c, [j for j in near if j.a is c or j.b is c])
            return nb, [j for _, js in per.values() for j in js]

        for _ in range(2):
            for f, v in fams.items():
                steps = [0.0] + [s * k * REACH * self.pitch[f] / STEPS for k in range(1, STEPS + 1) for s in (1, -1)]
                for i, b in enumerate(v):
                    mine = [j for j in joints if j.a is b or j.b is b]
                    now = score(mine)
                    if b.label in hand or now < 1e-6:
                        continue
                    crossed = {(j.b if j.a is b else j.a).label for j in mine}
                    best = None
                    for o in steps:                        # nearest first: a farther place has to be better
                        nb, js = trial(f, base[b.label], o)
                        if nb.raw.is_empty or crossed - {(j.b if j.a is nb else j.a).label for j in js}:
                            continue
                        n = score(js)
                        if n < now - 1e-6 and (best is None or n < best[0]):
                            best = (n, nb, o, js)
                        if n < 1e-6:                      # no graze left: no farther place can do better
                            break
                    if best is None:
                        continue
                    _, nb, o, js = best
                    if b.label not in self.moved:          # why: its longest graze where the count put it
                        j = max(mine, key=lambda j: graze(j)[1] / wall(graze(j)[0]))
                        why = f"its line with {(j.b if j.a is b else j.a).label} ran {graze(j)[1]:.0f} mm along {graze(j)[0].label}'s wall"
                        self.moved[b.label] = (o, why)
                    self.moved[b.label] = (o, self.moved[b.label][1])
                    v[i], joints = nb, [j for j in joints if j.a is not b and j.b is not b] + js
        self.moved = {k: m for k, m in self.moved.items() if m[0]}
        for v in fams.values():                            # a band back where it started is that band again
            v[:] = [b if b.label in self.moved else base[b.label] for b in v]
            for b in v:
                if b.label in self.moved:
                    b.note = f"moved {self.moved[b.label][0]:+.1f} mm off a grazing joint"
        return self.find_joints(ctx, fams) if self.moved else exact

    # ---------------------------------------------------------------- order and cuts
    @staticmethod
    def changes(keys):
        """Where a band's run of joints, in order round it, has to be cut so each piece slides in one way: each key is
        the set of ways its joint lets the piece go, None for either way (it goes with its neighbours). A piece runs on
        while its joints share a way; started at each joint in turn, the fewest cuts. → indices k: cut after key k."""
        known = [(i, frozenset(k)) for i, k in enumerate(keys) if k is not None]
        if len(known) < 2 or frozenset.intersection(*(k for _, k in known)):
            return []
        best = None
        for s in range(len(known)):
            cuts, share, prev = [], None, None
            for i, k in known[s:] + known[:s]:
                share = k if share is None else share & k
                if not share:
                    cuts.append(prev); share = k
                prev = i
            cuts.append(prev)                                   # and the cut back to where it started
            if best is None or len(cuts) < len(best):
                best = cuts
        return sorted(best)

    def runs(self, band, joints):
        """The joints a later band has with bands placed before it, per piece of its wall, in order round that piece's
        outline: [(component, [(arclength, joint)])]."""
        mine = [j for j in joints if j.b is band]
        out = []
        for comp in band.raw.geoms:
            ring = comp.exterior; got = []
            for j in mine:
                q = Point(to_local(band.M, [j.mid])[0][:2])
                if comp.distance(q) < band.thickness + 1:
                    got.append((ring.project(q), j))
            out.append((comp, sorted(got, key=lambda t: t[0])))
        return out

    def settle(self, band):
        """A joint solid right across the model (`out` 0) slides either way, but its slots allow one: the way of the
        nearest joint round the band along the same line, the piece it will be on — decided before the slots (slot()
        turns it only where that way would cut a band into more pieces); every later step reads this one `out`."""
        for comp, run in self.runs(band, self.joints):
            L = comp.exterior.length
            for s, j in run:
                if j.out:
                    continue
                same = [(min(abs(t - s), L - abs(t - s)), k) for t, k in run if k.out and abs(float(k.d @ j.d)) > 0.9]
                k = min(same, key=lambda c: c[0])[1] if same else None
                j.out = int(k.out * np.sign(k.d @ j.d)) if k else 1
        for j in self.joints:                          # one no ring of it comes near: as its slot was always cut
            if j.b is band and not j.out:
                j.out = 1

    def corner_cuts(self, ctx, band):
        """Two neighbouring joints P, Q of a later band that slide it different ways along crossing lines, and what to
        cut between them — {frozenset((P, Q)): (corner, cut, a point inside the corner or None)}:
        - a corner (`corner` True): a piece holding P slides in along P's way, and comes from across Q's line, so the
          wall in the path of Q's band (its strip, swept along P's way) cannot be on it — nor the wall in the path of
          P's band on Q's piece. Where those two paths cross on the wall — the lines cross in or near it, both slots
          beyond the crossing — that bit can go in neither way: it is cut off, from one slot's closed end to the
          other's, and glued in last; the wall either side then slides either joint's way, with no cut between them.
        - else, for when no cut between them finds a clean place (`corner` False): a cut along the line of the joint
          the other piece slides in toward, from the surface to its slot's closed end — where the earlier band is
          slotted and not in the way. The slot does the rest; the earlier band is clamped between the two pieces."""
        mf = ctx.p["min_feature"]; span = ctx.span; out = {}
        for _, run in self.runs(band, self.joints):
            for (_, P), (_, Q) in zip(run, run[1:] + run[:1]) if len(run) > 1 else ():
                if P.motion() == Q.motion() or abs(float(P.d @ Q.d)) > 0.9:
                    continue
                sP, sQ = P.slots[band.label], Q.slots[band.label]
                eP, eQ = P.ends[band.label], Q.ends[band.label]
                vP, vQ = inplane(band.M, -P.out * P.d), inplane(band.M, -Q.out * Q.d)
                T = eP + np.linalg.solve(np.column_stack([inplane(band.M, P.d), -inplane(band.M, Q.d)]), eQ - eP)[0] * inplane(band.M, P.d)
                toward = [(J, K) for J, K, v in ((P, Q, vQ), (Q, P, vP)) if (T - K.ends[band.label]) @ v >= 0]   # K's piece slides toward J's line
                bP, bQ = self.bar(ctx, band, P), self.bar(ctx, band, Q)
                box = 0.0 if toward or bP.is_empty or bQ.is_empty else \
                    self.walls[band.label].intersection(sweep(bP, vQ * span)).intersection(sweep(bQ, vP * span)).area
                if box > FREE_AREA:
                    cuts = [(True, LineString([eP, eQ]))]
                    inside = (eP + eQ) / 2 + (vP + vQ) / np.linalg.norm(vP + vQ) * 0.5   # the corner: beyond both closed ends
                else:                                        # along a line the other piece slides toward: past the crossing
                    inside = None
                    cuts = [(False, LineString([to_local(band.M, [J.at((J.hi if J.out > 0 else J.lo) + J.out)])[0][:2], J.ends[band.label]]))
                            for J, _ in toward]
                for corner, line in cuts:
                    cut = line.buffer(CUT_W / 2, cap_style=2)
                    if not any(cut.distance(c) < mf for c in band.cuts if c is not sP and c is not sQ):
                        out[frozenset((P, Q))] = (corner, cut, inside)
                        break
        return out

    def bar(self, ctx, band, j):
        """The earlier band's material at joint j, in `band`'s plane: its strip on their line, by j's slot."""
        whole = [g for _, g in strips(band, j.a, [Part(j.a.label, j.a, self.walls[j.a.label], [], True)], ctx.span)]
        return unary_union([g for g in whole if g.distance(j.slots[band.label]) < 1.0])

    def elements(self, band, run):
        """A later band's run of joints as its cuts are planned: [(joints, the ways they let the piece slide in)] — one
        joint and its way, or the two of a corner cut off (corner_cuts), either one's way."""
        pairs = {k for k, (corner, *_) in self.corners.get(band.label, {}).items() if corner}
        els = []
        for _, j in run:
            if els and frozenset((els[-1][0][-1], j)) in pairs:
                els[-1] = (els[-1][0] + [j], els[-1][1] | {j.motion()})
            else:
                els.append(([j], frozenset({j.motion()})))
        if len(els) > 1 and frozenset((els[-1][0][-1], els[0][0][0])) in pairs:
            last = els.pop()
            els[0] = (last[0] + els[0][0], last[1] | els[0][1])
        return els

    def pick_order(self, want, fams, joints):
        if want != "auto":
            o = [f for f in want if f in fams]
            return o + [f for f in fams if f not in o]
        best = None
        for o in itertools.permutations(fams):
            rank = {f: i for i, f in enumerate(o)}
            js = [j if rank[j.a.group.lower()] < rank[j.b.group.lower()] else Joint(j.b, j.a, j.p0, j.d, j.lo, j.hi, j.out) for j in joints]
            later = {j.b.label: j.b for j in js}
            n = sum(len(self.changes([m and {m} for m in (j.motion() for _, j in run)])) for b in later.values() for _, run in self.runs(b, js))
            if best is None or n < best[0]:
                best = (n, list(o))
        return best[1]

    def cut_points(self, band):
        """Where a later band has to be cut: (component, from, to) — the stretch of its outline, as arclength, between
        each pair of neighbouring joints that slide in different ways. The cut goes anywhere in it."""
        out = []
        for comp, run in self.runs(band, self.joints):
            els = self.elements(band, run)
            at = {j: s for s, j in run}; L = comp.exterior.length
            for k in self.changes([w for _, w in els]):
                j0, j1 = els[k][0][-1], els[(k + 1) % len(els)][0][0]
                s0, s1 = at[j0], at[j1]
                if s1 <= s0:
                    s1 += L
                out.append((comp, s0, s1, (j0, j1)))
        return out

    # ---------------------------------------------------------------- slots
    def slot(self, ctx, j):
        """The two slots of joint `j`: from the meeting point, outward through the rest of the first band's wall along
        the line, and inward through the rest of the later band's, each past its end so the slot is open."""
        for band, other, cut, end in self.slot_pair(ctx, j, j.out):
            j.slots[band.label], j.ends[band.label] = cut, end
            band.cuts.append(cut)
            band.links.append((other.label, cut, tuple(j.mid)))
            if other.label not in band.engages:
                band.engages.append(other.label)

    def turn(self, ctx, j):
        """A joint solid right across (settle()), once every slot is cut: turned the other way where its way cuts its
        two bands into more pieces than that one would — then `out` says so, for every step after."""
        def regions():
            return sum(len(as_multi(b.raw.difference(unary_union(b.cuts))).geoms) for b in (j.a, j.b))

        def swap(changes):                                   # [(band, slot out, slot in, its closed end)]
            for band, gone, cut, end in changes:
                band.cuts[next(i for i, c in enumerate(band.cuts) if c is gone)] = cut
                band.links[:] = [(lab, cut if c is gone else c, pt) for lab, c, pt in band.links]
                j.slots[band.label], j.ends[band.label] = cut, end
        was = regions()
        old = [(b, j.slots[b.label], j.ends[b.label]) for b in (j.a, j.b)]
        new = self.slot_pair(ctx, j, -j.out)                 # in the same order: (a, b)
        swap([(b, cut, n[2], n[3]) for (b, cut, _), n in zip(old, new)])
        if regions() < was:
            j.out = -j.out
        else:
            swap([(b, n[2], cut, end) for (b, cut, end), n in zip(old, new)])

    @staticmethod
    def slot_pair(ctx, j, out):
        """Joint j's two slots with the surface that way along its line: [(band, other band, slot, its closed end)]."""
        p = ctx.p; ratio = p["notch_ratio"]
        outer = j.hi if out > 0 else j.lo
        meet = outer - out * ratio * (j.hi - j.lo)              # the first band takes `ratio` of the joint from the surface side
        segs = [(j.lo - 1e4, j.hi + 1e4)]; made = []
        for band, other, sign in ((j.a, j.b, out), (j.b, j.a, -out)):
            mat = _clip_segments(segs, j.p0, j.d, (band,))        # the band's own wall along the whole line
            here = next((m for m in mat if m[0] - 1e-6 <= meet <= m[1] + 1e-6), (j.lo, j.hi))
            end = here[1] if sign > 0 else here[0]
            beyond = [m[0] - end for m in mat if m[0] > end + 1e-6] if sign > 0 else [end - m[1] for m in mat if m[1] < end - 1e-6]
            width = other.thickness + p["slot_offset"]
            over = 1.0 + width if not beyond else max(0.2, min(1.0 + width, min(beyond) - p["min_feature"]))
            a_open, a_end = to_local(band.M, [j.at(end + sign * over), j.at(meet)])
            made.append((band, other, slot_polygon(a_open[:2], a_end[:2], width, p), a_end[:2]))
        return made

    # ---------------------------------------------------------------- checks of its own
    def flag(self, ctx, bands):
        p = ctx.p; mf = p["min_feature"]
        for b in bands:
            crossed = set(b.engages)
            if len(crossed) < 2 and b.raw.area > 0:
                msg = (f"crosses {'only ' + next(iter(crossed)) if crossed else 'no other band'} — held at one place, it can turn: "
                       "move it toward the middle (offset), or delete it")
                (b.warnings if crossed else b.errors).append(msg)
        for j in self.joints:
            w = max(ctx.override("wall", j.a.label, p["ring_wall"]), ctx.override("wall", j.b.label, p["ring_wall"]))
            if j.hi - j.lo > 3 * w:
                for x, y in ((j.a, j.b), (j.b, j.a)):
                    x.warnings.append(f"meets {y.label} at a shallow angle to the surface: the joint is {j.hi - j.lo:.0f} mm long, "
                                      f"over 3 × the wall — loose and weak there: move one of them (offset)")
        for b in bands:                                      # two slots closer than a full wall: what is between them snaps
            cs = b.cuts                                      # (unless a corner is cut off there: then it is cut anyway)
            cornered = {frozenset((id(P.slots[b.label]), id(Q.slots[b.label]))) for (P, Q), (c, *_) in self.corners.get(b.label, {}).items() if c}
            close = any(0 < cs[i].distance(cs[k]) < mf and frozenset((id(cs[i]), id(cs[k]))) not in cornered
                        for i in range(len(cs)) for k in range(i + 1, len(cs)))
            if close:
                b.warnings.append(f"two of its slots are closer than {mf:g} mm: the wall between them would snap — move it (offset) or a band it crosses")
        if not p["band_cuts"]:
            for b in bands:
                if b.group.lower() != self.first and self.cut_points(b):
                    b.errors.append("cannot slide in whole: its joints with the bands placed before it slide in different ways — "
                                    "turn on `cut locked bands`, or delete it")

    # ---------------------------------------------------------------- pieces
    def cut(self, ctx, sl):
        """plan.build's hook: the pieces `lattice` cut the band into, or None to leave it whole."""
        return sl.cut_to

    def guide_outlines(self, ctx, slices):
        self.lattice(ctx, slices)                      # the outlines are final here, and what it finds is counted

    def lattice(self, ctx, bands, tongue=True):
        """Every band cut, the order its pieces go in, and the pieces that cannot: the first family's cuts (only for
        length or the sheet) with puzzle tabs — placed first, its pieces are pressed together flat — and every later
        band's cuts plain, to solve which piece at each cut goes in later; then those cut again with a tongue against
        the way that piece slides, and solved once more on the pieces as cut. `tongue` off keeps the puzzle tab there
        too, which the check has to catch."""
        if not bands:
            return
        p = ctx.p; later = [b for b in bands if b.group.lower() != self.first]
        if self.joints:
            for b in bands:
                if b not in later:
                    b.cut_to = self.cut_band(ctx, b, None)[0]
            said = [(b, list(b.warnings), list(b.errors)) for b in later]
            plain = {b.label: self.cut_band(ctx, b, self.plain(ctx, b)) for b in later}
            for b, w, e in said:                           # only the last cut of a band speaks
                b.warnings[:], b.errors[:] = w, e
                b.cut_to = plain[b.label][0]
            steps = self.solved(ctx, bands)[0]
            for b in later:
                b.cut_to = self.cut_band(ctx, b, self.face(ctx, b, plain[b.label][1], steps) if tongue else None)[0]
            steps, locked = self.solved(ctx, bands)
            for q, o in locked.items():
                if p["band_cuts"] or not self.cut_points(q.band):     # with cutting off, flag() has said so already
                    q.band.errors.append(f"{q.label} cannot slide in: " + (f"{o.label} is in its way" if o else "no way along its slots is clear")
                                         + " — move one of them (offset), or change the assembly order")
            for b, lab, corner in self.alone:
                if corner:
                    P, Q = sorted(corner, key=lambda j: j.a.label)
                    b.warnings.append(f"{lab} is the corner between its slots for {P.a.label} and {Q.a.label}, cut off: there both bands "
                                      "box it in, and the pieces beside it can only slide in without it — it has no joint: glue it in last")
                else:
                    b.warnings.append(f"{lab} has no joint: only glue at its cuts holds it — move the band or one it crosses (offset) to give it one")
            ctx.view["steps"] = {lab: n for lab, (n, _) in steps.items()}
        n = sum(len(b.cut_to or as_multi(b.profile).geoms) for b in later)
        cuts = sum(len(self.cut_points(b)) for b in later)
        corners = sum(c for cs in self.corners.values() for c, *_ in cs.values())
        ctx.notes_extra = (f"assembly: {' → '.join(f.upper() for f in self.order)} — the {self.first.upper()} bands go in whole, then the "
                           f"other {n} pieces one at a time, each slid in along its slots, in an order worked out piece by piece; "
                           f"{cuts} cut(s) let the locked bands in" + ("" if p["band_cuts"] else " (cutting is off)")
                           + (f"; {corners} corner(s) between two slots cut off, glued in last" if corners else "")
                           + ("" if not self.moved else " · moved off a grazing joint (`move grazing bands`): "
                              + "; ".join(f"{lab} {o:+.1f} mm, {why}" for lab, (o, why) in self.moved.items())))

    def parts(self, bands):
        """Every band's pieces as core/slidein.py takes them, labelled as plan.build will label them, each with the ways
        it can slide in: inward along its joints with bands placed before it; where those leave it open (a joint solid
        right across, or none), either way along the lines of its joints, or else of its band's. A joint is held by
        the piece its slot is cut in — two, where a cut runs along the joint to the slot. A corner cut off
        (corner_cuts) has no joint and no way in its plane: `moves` empty, it is glued in last."""
        out = []; self.alone = []                      # the pieces with no joint: (band, label, the corner it is, or None)
        for b in bands:
            geoms = b.cut_to or list(as_multi(b.profile).geoms)
            names = [f"{b.label}-{i + 1}" for i in range(len(geoms))] if b.cut_to or len(geoms) > 1 else [b.label]
            corner = {k: pq for pq, (c, _, inside) in self.corners.get(b.label, {}).items() if c
                      for k in range(len(geoms)) if geoms[k].distance(Point(inside)) < 0.1}
            moves = [[] for _ in geoms]; lines = [[] for _ in geoms]
            for j in self.joints:
                if b is j.a or b is j.b:
                    ks = [k for k in range(len(geoms)) if k not in corner and geoms[k].distance(j.slots[b.label]) < 0.1]
                    if not ks:                         # its slot shed with a sliver: the piece nearest
                        q = Point(to_local(b.M, [j.mid])[0][:2])
                        ks = [min(range(len(geoms)), key=lambda i: geoms[i].distance(q))]
                    d = inplane(b.M, j.d)
                    for k in ks:
                        lines[k] += [d, -d]
                        if b is j.b:
                            moves[k].append(-j.out * d)
            every = [v for m in moves for v in m]
            for k, (g, lab, m, ln) in enumerate(zip(geoms, names, moves, lines)):
                if k in corner:
                    self.alone.append((b, lab, corner[k]))
                    out.append(Part(lab, b, g, [], False))
                    continue
                if not ln and len(geoms) > 1:
                    self.alone.append((b, lab, None))
                ways = list({tuple(np.round(v, 3)): v for v in (m or ln or every + [-v for v in every])}.values())
                out.append(Part(lab, b, g, ways, b.group.lower() == self.first or not ways))
        return out

    def solved(self, ctx, bands):
        """The step each moving piece goes in at, with the way it slides ({label: (step, move)}), and the locked ones;
        the corners cut off go in last, glued (move None)."""
        parts = self.parts(bands)
        order, locked = solve([q for q in parts if q.moves or q.fixed], ctx.span)
        order += [(q, None) for q in parts if not q.moves and not q.fixed]
        return {q.label: (i + 1, v) for i, (q, v) in enumerate(order)}, locked

    @staticmethod
    def across(comps, e, i):
        """A cut from e to i in one of a band's rings `comps`: its normal, turned to the piece after it round the
        outline, which ring, and how far round that ring's outline it starts."""
        E = Point(e)
        k = min(range(len(comps)), key=lambda k: comps[k].exterior.distance(E))
        ext = comps[k].exterior; t = ext.project(E)
        p0, p1 = ext.interpolate(t - 0.5), ext.interpolate(t + 0.5)
        u = (i - e) / np.linalg.norm(i - e); n = np.array([-u[1], u[0]])
        return (n if n @ (p1.x - p0.x, p1.y - p0.y) >= 0 else -n), k, t

    def plain(self, ctx, b):
        """The joint for a later band's first cuts: a butt cut where one of the pieces either side can go in after the
        other — sliding toward it, or along the cut — and no cut where neither can: straight across a curved wall,
        between pieces that slide in square to each other, a cut can face away from both. Nor where a piece, as it
        slides in, would pass through the band of a joint either side: the wall between two joints, cut there, swept
        along each piece's way past those bands' strips as core/slidein.py sweeps them (a cut square across the wall
        near a joint whose band the other piece slides away from leaves a corner of that piece in the band's path)."""
        comps = list(b.raw.geoms); span = ctx.span
        reach = 2 * ctx.override("wall", b.label, ctx.p["ring_wall"]) + b.thickness
        runs = []                                      # per ring: (arclength, the ways the joint there lets its piece go, it)
        for _, run in self.runs(b, self.joints):
            ways = {j: [inplane(b.M, np.asarray(m)) for m in w] for js, w in self.elements(b, run) for j in js}
            runs.append([(s, ways[j], j) for s, j in run])
        lines, windows, swept = {}, {}, {}

        def bars(j):                                   # the earlier band's material on the joint's line, in b's frame
            if j.a.label not in lines:
                lines[j.a.label] = [g for _, g in strips(b, j.a, [Part(j.a.label, j.a, j.a.profile, [], True)], span)]
            return lines[j.a.label]

        def clear(piece, ways, obstacles):
            return any(all(covers(g, piece, v * span, swept) <= FREE_AREA for g in obstacles) for v in ways)

        def joint(e, i):
            n, k, t = self.across(comps, e, i)
            run = runs[k]
            if len(run) < 2:
                return True
            sb, before, jb = next((r for r in reversed(run) if r[0] <= t), run[-1])
            sa, after, ja = next((r for r in run if r[0] > t), run[0])
            if not (any(v @ n >= -ALONG for v in before) or any(v @ n <= ALONG for v in after)):
                return False
            ext = comps[k].exterior; L = ext.length
            if (k, sb) not in windows:                 # the wall between the two joints and round both, slotted
                a0 = (sb - reach) % L; a1 = a0 + min(L, (sa - sb) % L + 2 * reach)
                arc = unary_union([substring(ext, a0, min(a1, L))] + ([substring(ext, 0, a1 - L)] if a1 > L else []))
                windows[k, sb] = b.profile.intersection(arc.buffer(reach, cap_style=2))
            window = windows[k, sb]
            u = (i - e) / np.linalg.norm(i - e)
            sides = as_multi(window.difference(LineString([e - u, i + u]).buffer(CUT_W / 2, cap_style=2))).geoms
            gb, ga = (min(sides, key=lambda g: g.distance(j.slots[b.label])) for j in (jb, ja))   # each side: by its slot
            if gb is ga:
                return True
            obstacles = bars(jb) + bars(ja)
            return clear(gb, before, obstacles) and clear(ga, after, obstacles)
        return joint

    def face(self, ctx, b, rings, steps):
        """The joint for a later band's cuts, once the order is known: for a cut from e to i, its tongue's axis —
        against the way the later of the two pieces either side slides in, so that piece slides onto it — or None for
        no tongue here, where that piece slides into the cut more than 45° off square (one further along may do); True
        for a butt cut and no more looking, where the order does not say; False where the later piece would slide away
        from the earlier, through it, or where plain() would make no cut. Which pieces those are comes from the plain
        cut nearest it: the cut made now lands near it, between the same joints."""
        ok = self.plain(ctx, b)
        geoms = b.cut_to
        if not geoms:
            return ok
        comps = list(b.raw.geoms)
        names = [f"{b.label}-{k + 1}" for k in range(len(geoms))]
        side = lambda pt: min(range(len(geoms)), key=lambda k: geoms[k].distance(pt))   # noqa: E731
        plain = [(rg.ext.interpolate(t % rg.L), side(rg.ext.interpolate((t - 1) % rg.L)), side(rg.ext.interpolate((t + 1) % rg.L)))
                 for rg in rings for t, _, _ in rg.cuts]

        def axis(e, i):
            if not ok(e, i):
                return False
            _, before, after = min(plain, key=lambda c: c[0].distance(Point(e)))
            sb, sa = steps.get(names[before]), steps.get(names[after])
            if before == after or sb is None or sa is None or sb[1] is None or sa[1] is None:
                return True
            n = self.across(comps, e, i)[0]
            if sb[0] > sa[0]:                                  # the piece before it goes in later: n into that one
                n = -n
            a = -np.asarray(max(sb, sa, key=lambda s: s[0])[1])
            return a if a @ n >= SQUARE else None if a @ n >= -ALONG else False
        return axis

    def cut_band(self, ctx, sl, joint):
        """A band's cuts, each a line across the wall with `joint` (as ringcut.cut_line takes it) — the cuts a locked
        band needs to slide in, then more wherever a piece is longer than `max_length` or too big for the sheet:
        (the pieces, or None to leave it whole; its rings with the cuts made in them)."""
        p = ctx.p; shift = ctx.override("cut_shift", sl.label)
        locked = p["band_cuts"] and sl.group.lower() != self.first
        points = self.cut_points(sl) if locked else []
        rings = {c.wkb: Ring(c) for c in sl.raw.geoms}           # a shape comes back a new object each time it is asked for
        geom = sl.profile; made = glued = missed = 0
        planned = self.corners.get(sl.label, {}) if locked else {}
        corners = [c for corner, c, _ in planned.values() if corner]
        for c in corners:
            geom = as_multi(geom.difference(c))
        for comp, s0, s1, pair in points:
            rg = rings[comp.wkb]
            # from the middle of the stretch outward, half a millimetre at a time, anywhere between the two joints: the
            # first place a cut and its tab fit, else the first a plain cut fits (glued). A cut only has to clear the
            # slots by min_feature, which cut_line checks. Straight across the wall, or along the slots on either side:
            # between two slots that cross the wall at a slant — a ring meeting a band at a diagonal — a cut parallel
            # to them is the one that fits. A solid stretch has no inner edge to cut to
            mid = min(max((s0 + s1) / 2 + shift, s0), s1)
            n = min(400, max(1, int((s1 - s0) / STEP)))      # strictly between the joints: one at a joint is in neither stretch
            tries = sorted((s0 + (s1 - s0) * k / (n + 1) for k in range(1, n + 1)), key=lambda t: abs(t - mid))
            slants = [np.asarray(to_local(sl.M, [j.mid, j.mid + j.d])[1][:2]) - np.asarray(to_local(sl.M, [j.mid])[0][:2]) for j in pair]
            got = None if rg.holes.is_empty else rg.place(tries, sl, p, slants, joint)
            if got is None and (pre := planned.get(frozenset(pair))) is not None:   # else along a joint's line (corner_cuts)
                got = (rg.ext.project(pre[1].centroid), pre[1], False)
            if got is None:
                missed += 1
                continue
            rg.cuts.append(got)
            glued += not got[2]
            geom = as_multi(geom.difference(got[1]))
            made += 1
        if missed:
            sl.warnings.append(f"{missed} of the {len(points)} cut(s) it needs to slide in found no clean place between its joints (slots in the way, "
                               "or a solid wall): it cannot go in as it is — cut it there by hand, or move it or a band it crosses (offset)")
        geom, more, plain, stuck = shorten(sl, p, p["max_length"], rings.values(), geom, joint)
        made += more; glued += plain
        if stuck:
            sl.warnings.append(f"{stuck} piece(s) longer than `max_length` or too big for the sheet found no clean place to be cut "
                               "(slots close together all along): cut by hand, or move a band it crosses (offset)")
        if glued:
            sl.warnings.append(f"{glued} of its {made} cut(s) are plain butt joints — no room for a tongue or tab there (joints close "
                               "together, or a narrow wall), or the piece slides along the cut, not into it: glue those")
        return (list(as_multi(geom).geoms) if made or corners else None), list(rings.values())

    @staticmethod
    def fit(p):
        return {"distribution": "count", "nx": min(p["nx"], 3), "ny": min(p["ny"], 3), "nz": min(p["nz"], 3)}, 0.0

