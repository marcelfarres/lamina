"""Band lattice: the model cut into rings — bands — along any of x, y and z, half-lapped where two bands cross.

Each band is a section with only a wall left inside its outline (core/ring.py). Where two bands cross, the line their
planes meet on runs through both walls in short stretches — usually two per pair, one on each side of the model —
and each stretch is one joint: a slot in each band, from opposite ends, meeting in the middle (`notch_ratio`).

Assembly is family by family, in `order`. The first family stays whole. A band of a later family slides onto the
bands already in place along the crossing line of each joint, inward from the surface; a band whose joints ask for
different directions — the top and the bottom of a ring, or joints with two families — cannot go in whole, so it is
cut between them into pieces that each slide one way, rejoined by puzzle tabs. So each joint's slot opens outward in
the band placed first and inward in the band placed after it, and runs through the rest of that band's wall along
the line, so nothing of either is in the other's way as it slides in."""
from __future__ import annotations
import itertools

import numpy as np
from shapely.geometry import Point

from . import Mode, Param, register
from ..geometry import as_multi, crossings, section_polygons, to_local
from ..model import Slice
from ..notch import _clip_segments, slot_polygon
from ..ring import ring as ring_of
from ..ringcut import STEP, Ring, shorten

FAMS = "xyz"
ORDERS = ["auto"] + ["".join(o) for o in itertools.permutations(FAMS)]


class Joint:
    """One stretch of a crossing line where two bands' walls overlap: `a` placed before `b`. Along the world line
    p0 + d·s it runs from `lo` to `hi`; `out` is the way to the model's surface from it (+1 along d, −1 against, 0 when
    the wall is solid right across the model there and either way will do)."""
    def __init__(self, a, b, p0, d, lo, hi, out):
        self.a, self.b, self.p0, self.d, self.lo, self.hi, self.out = a, b, p0, d, lo, hi, out

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
                   "bands cross. The first family stays whole; a band that cannot slide in whole is cut into pieces joined by "
                   "puzzle tabs.")
    legend = ("X-2 = the 2nd band across x, Y-4 the 4th across y, Z-1 the 1st across z, each counted from the low end · "
              "X-2-1, X-2-2 = the pieces a band is cut into, joined by puzzle tabs · assembly: the first family's bands go "
              "in whole, then each later family's pieces, each slid in along its slots from outside the model")
    params = [
        Param("x", "bool", True, "Bands across x (planes square to x)", label="x bands", section="Families — which bands, and how many"),
        Param("y", "bool", True, "Bands across y (planes square to y)", label="y bands"),
        Param("z", "bool", True, "Bands across z (planes square to z)", label="z bands"),
        Param("distribution", "choice", "count", "count = this many bands per family; distance = one band every so many mm, per family",
              choices=["count", "distance"]),
        Param("nx", "int", 5, "x bands: how many", 1, 200, 1, show_if=("distribution", "count"), label="x count"),
        Param("ny", "int", 5, "y bands: how many", 1, 200, 1, show_if=("distribution", "count"), label="y count"),
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
              "ask for different directions, each cut rejoined by a puzzle tab (`tab` wide). Off = such a band is an error",
              label="cut locked bands"),
        Param("max_length", "number", 0.0, "Longest piece (mm), measured along the band: a longer one is cut again, the cuts spread "
              "evenly between the joints, clear of the slots, each with a puzzle tab. 0 = no limit. A piece too big for the sheet "
              "is always cut", 0, 10000, 5, unit="mm", label="max piece length"),
        Param("cut_shift", "map", {}, "Slide a band's cuts along it (mm), each within the stretch between its two joints", group="slices", unit="mm", label="cut shifts"),
    ]

    # ---------------------------------------------------------------- build
    def build(self, ctx):
        p = ctx.p
        on = [f for f in FAMS if p[f]]
        self.joints, self.first = [], None
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
        order = self.pick_order(p["order"], list(fams), joints)
        rank = {f: i for i, f in enumerate(order)}
        # a joint's `a` is the band placed first
        self.joints = [j if rank[j.a.group.lower()] < rank[j.b.group.lower()] else Joint(j.b, j.a, j.p0, j.d, j.lo, j.hi, j.out) for j in joints]
        self.first = order[0]
        bands = [b for f in order for b in fams[f]]
        for j in self.joints:
            self.slot(ctx, j)
        self.flag(ctx, bands)
        cuts = sum(len(self.cut_points(b)) for b in bands if b.group.lower() != self.first)
        ctx.notes_extra = (f"assembly: {' → '.join(f.upper() for f in order)} — the {order[0].upper()} bands go in whole, then each later "
                           f"band slides in along its slots from outside the model; {cuts} cut(s) let the locked bands in"
                           + ("" if p["band_cuts"] else " (cutting is off)"))
        ctx.cover_r = max(float(np.ptp((ctx.mesh.vertices - ctx.mid) @ ctx.ax[FAMS.index(f)])) / max(1, len(v)) for f, v in fams.items()) / 2 + p["thickness"]
        return bands

    def family(self, ctx, f):
        """The bands of family `f`: planes square to its axis, spread by count or spacing, each the section moved in
        by its wall. The ring is the band's `clip` too, so a crossing's slots are cut only where both walls are."""
        p = ctx.p; i = FAMS.index(f); e = ctx.ax[i]; up = ctx.ax[1] if f == "z" else ctx.ax[2]
        v = (ctx.mesh.vertices - ctx.mid) @ e
        L = float(np.ptp(v)); c = float(v.min() + v.max()) / 2
        n = p["n" + f] if p["distribution"] == "count" else max(1, int(L // p["spacing_" + f]))
        out = []
        for j, s in enumerate(ctx.positions(L, [p["thickness"]] * n)):
            lab = f"{f.upper()}-{j + 1}"
            out.append(Slice(lab, f.upper(), ctx.frame(lab, ctx.mid + e * (c + s), e, up_hint=up), ctx.thickness_of(lab)))
        out = ctx.keep(out)
        for b in out:
            b.raw = ring_of(section_polygons(ctx.mesh, b.M), ctx.override("wall", b.label, p["ring_wall"]), p["min_feature"])
            b.clip = b.raw
        return [b for b in out if not b.raw.is_empty]

    @staticmethod
    def find_joints(ctx, fams):
        """Every stretch where two bands' walls overlap on their crossing line, with the way out to the surface."""
        pairs = [(a, b) for f, g in itertools.combinations(list(fams), 2) for a in fams[f] for b in fams[g]]
        lines = crossings(ctx.mesh, ctx.span, [(a.M, b.M) for a, b in pairs])
        out = []
        for (a, b), cr in zip(pairs, lines):
            if cr is None:
                continue
            p0, d, segs = cr
            for lo, hi in _clip_segments(segs, p0, d, (a, b)):
                seg = min(segs, key=lambda m: 0.0 if m[0] - 1e-6 <= (lo + hi) / 2 <= m[1] + 1e-6 else min(abs(lo - m[0]), abs(hi - m[1])))
                to_hi, to_lo = seg[1] - hi, lo - seg[0]
                o = 0 if max(to_hi, to_lo) < 0.5 else (1 if to_hi <= to_lo else -1)
                out.append(Joint(a, b, p0, d, lo, hi, o))
        return out

    # ---------------------------------------------------------------- order and cuts
    @staticmethod
    def changes(keys):
        """Where a band's run of joints, in order round it, changes the way it slides in: a cut between each such pair.
        A joint that either way will do (None) goes with its neighbours. → indices k: cut between joint k and k+1."""
        known = [(i, k) for i, k in enumerate(keys) if k is not None]
        if len(known) < 2:
            return []
        return [known[i][0] for i in range(len(known)) if known[i][1] != known[(i + 1) % len(known)][1]]

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

    def pick_order(self, want, fams, joints):
        if want != "auto":
            o = [f for f in want if f in fams]
            return o + [f for f in fams if f not in o]
        best = None
        for o in itertools.permutations(fams):
            rank = {f: i for i, f in enumerate(o)}
            js = [j if rank[j.a.group.lower()] < rank[j.b.group.lower()] else Joint(j.b, j.a, j.p0, j.d, j.lo, j.hi, j.out) for j in joints]
            later = {j.b.label: j.b for j in js}
            n = sum(len(self.changes([j.motion() for _, j in run])) for b in later.values() for _, run in self.runs(b, js))
            if best is None or n < best[0]:
                best = (n, list(o))
        return best[1]

    def cut_points(self, band):
        """Where a later band has to be cut: (component, from, to) — the stretch of its outline, as arclength, between
        each pair of neighbouring joints that slide in different ways. The cut goes anywhere in it."""
        out = []
        for comp, run in self.runs(band, self.joints):
            ks = self.changes([j.motion() for _, j in run])
            L = comp.exterior.length
            for k in ks:
                s0, s1 = run[k][0], run[(k + 1) % len(run)][0]
                if s1 <= s0:
                    s1 += L
                out.append((comp, s0, s1, (run[k][1], run[(k + 1) % len(run)][1])))
        return out

    # ---------------------------------------------------------------- slots
    def slot(self, ctx, j):
        """The two slots of joint `j`: from the meeting point, outward through the rest of the first band's wall along
        the line, and inward through the rest of the later band's, each past its end so the slot is open."""
        p = ctx.p; ratio = p["notch_ratio"]
        out = j.out or 1
        outer, inner = (j.hi, j.lo) if out > 0 else (j.lo, j.hi)
        meet = outer - out * ratio * (j.hi - j.lo)              # the first band takes `ratio` of the joint from the surface side
        segs = [(j.lo - 1e4, j.hi + 1e4)]
        for band, other, sign in ((j.a, j.b, out), (j.b, j.a, -out)):
            mat = _clip_segments(segs, j.p0, j.d, (band,))        # the band's own wall along the whole line
            here = next((m for m in mat if m[0] - 1e-6 <= meet <= m[1] + 1e-6), (j.lo, j.hi))
            end = here[1] if sign > 0 else here[0]
            beyond = [m[0] - end for m in mat if m[0] > end + 1e-6] if sign > 0 else [end - m[1] for m in mat if m[1] < end - 1e-6]
            width = other.thickness + p["slot_offset"]
            over = 1.0 + width if not beyond else max(0.2, min(1.0 + width, min(beyond) - p["min_feature"]))
            a_open, a_end = to_local(band.M, [j.at(end + sign * over), j.at(meet)])
            cut = slot_polygon(a_open[:2], a_end[:2], width, p)
            band.cuts.append(cut)
            band.links.append((other.label, cut, tuple(j.mid)))
            if other.label not in band.engages:
                band.engages.append(other.label)

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
            cs = b.cuts
            close = any(0 < cs[i].distance(cs[k]) < mf for i in range(len(cs)) for k in range(i + 1, len(cs)))
            if close:
                b.warnings.append(f"two of its slots are closer than {mf:g} mm: the wall between them would snap — move it (offset) or a band it crosses")
        if not p["band_cuts"]:
            for b in bands:
                if b.group.lower() != self.first and self.cut_points(b):
                    b.errors.append("cannot slide in whole: its joints with the bands placed before it slide in different ways — "
                                    "turn on `cut locked bands`, or delete it")

    # ---------------------------------------------------------------- pieces
    def cut(self, ctx, sl):
        """plan.build's hook: the pieces a band is cut into, each cut a line across the wall with a puzzle tab — the
        cuts a locked band needs to slide in, then more wherever a piece is longer than `max_length` or too big for
        the sheet — or None to leave the band whole."""
        if sl.group.lower() not in FAMS or not self.joints:
            return None
        p = ctx.p; shift = ctx.override("cut_shift", sl.label)
        locked = p["band_cuts"] and sl.group.lower() != self.first
        points = self.cut_points(sl) if locked else []
        rings = {c.wkb: Ring(c) for c in sl.raw.geoms}           # a shape comes back a new object each time it is asked for
        geom = sl.profile; made = glued = missed = 0
        for comp, s0, s1, pair in points:
            rg = rings[comp.wkb]
            if rg.holes.is_empty:                        # a solid stretch has no inner edge to cut to
                missed += 1
                continue
            # from the middle of the stretch outward, half a millimetre at a time, anywhere between the two joints: the
            # first place a cut and its tab fit, else the first a plain cut fits (glued). A cut only has to clear the
            # slots by min_feature, which cut_line checks. Straight across the wall, or along the slots on either side:
            # between two slots that cross the wall at a slant — a ring meeting a band at a diagonal — a cut parallel
            # to them is the one that fits
            mid = min(max((s0 + s1) / 2 + shift, s0), s1)
            n = min(400, int((s1 - s0) / STEP) + 1)
            tries = sorted((s0 + (s1 - s0) * k / max(1, n - 1) for k in range(n)), key=lambda t: abs(t - mid))
            slants = [np.asarray(to_local(sl.M, [j.mid, j.mid + j.d])[1][:2]) - np.asarray(to_local(sl.M, [j.mid])[0][:2]) for j in pair]
            got = rg.place(tries, sl, p, slants)
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
        geom, more, plain, stuck = shorten(sl, p, p["max_length"], rings.values(), geom)
        made += more; glued += plain
        if stuck:
            sl.warnings.append(f"{stuck} piece(s) longer than `max_length` or too big for the sheet found no clean place to be cut "
                               "(slots close together all along): cut by hand, or move a band it crosses (offset)")
        if glued:
            sl.warnings.append(f"{glued} of its {made} cut(s) have no room for a puzzle tab (joints close together, or a narrow wall): glue those")
        if not made:
            return None
        return list(as_multi(geom).geoms)

    @staticmethod
    def fit(p):
        return {"distribution": "count", "nx": min(p["nx"], 3), "ny": min(p["ny"], 3), "nz": min(p["nz"], 3)}, 0.0

