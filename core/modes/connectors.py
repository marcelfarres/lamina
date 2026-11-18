"""Connectors: the dowels, or the pegs and spacers of tabs, between consecutive slices. Stacked and the plaque both place them with this."""
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from ..model import ABC, Slice
from ..geometry import dowel, dowel_leverage, hole_reach, LEVERAGE_OK, rect_along, as_multi, frame_xy, into, to_local
from ..labels import mark_box, mark_rot

_dist = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])   # noqa: E731

MIN_DOWEL = 2.0            # below this a dowel is not worth cutting for: too small to buy, too weak to locate anything
ABC_LOWER = ABC.lower()    # the letters of connector names, no i or o (they read as 1 and 0 when engraved small)


@dataclass
class Layer(Slice):
    """A slice of the stacked family — a layer, a peg or a spacer, a plaque's slice — with what the connector placer keeps on it."""
    pair: int = 0                       # stacked peg / spacer: the pair of layers it sits between (assembly order)
    cutkeys: dict = field(default_factory=dict)   # stacked: (x, y, angle) → the cut there, so an aligned dowel is cut once
    cutnames: dict = field(default_factory=dict)  # stacked: the same key → its dowel's name (Z-3a), so a rod carried up keeps its name
    inner: MultiPolygon | None = None   # stacked: raw eroded by min_feature, where a cut keeps a full wall (cached)
    dowel_room: list = field(default_factory=list)  # stacked: where a rod through this slice and a neighbour can go (checks)


def hole_mark(sl, hole, text, font):
    """The dowel's mark engraved beside its hole (or a tab's slot): a box of `text` at 0.6 of the font, in the first of
    eight directions round the hole — above first — where the whole mark lies on the slice's material, clear of the
    outline, every cut in the slice and every mark already there. A hole with no room round it (a small island) gets
    none: the assembly key still names it."""
    w, h = (lambda b: (b[2] - b[0], b[3] - b[1]))(mark_box(0, 0, text, font).bounds)
    cx, cy = hole.centroid.coords[0]
    reach = max(math.hypot(x - cx, y - cy) for x, y in hole.exterior.coords)
    room = sl.raw.buffer(-0.3)
    cuts = [c.buffer(0.3) for c in sl.cuts]
    taken = [mark_box(*m[:3], font, mark_rot(m)) for m in sl.marks]
    for ang in (90, 270, 0, 180, 45, 135, 225, 315):
        dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        far = reach + 0.6 + abs(dx) * w / 2 + abs(dy) * h / 2         # the box's edge nearest the hole 0.6 mm from it
        x, y = cx + dx * far, cy + dy * far
        b = mark_box(x, y, text, font)
        if room.covers(b) and all(b.disjoint(c) for c in cuts) and all(b.disjoint(m) for m in taken):
            sl.marks.append((x, y, text))
            return


class Connectors:
    """The connectors between consecutive `slices`, placed by `run()`: dowels, or the pegs and spacers of tabs. The plaque
    holds its floating pieces with the same placer and gives it: `settings` in place of ctx.p for everything about the
    connectors, `islands(a, b)` the places to hold for a pair (default: all their overlap, none for lines), `seeds(parts)`
    where the first connector of an island is tried (default: the middle of each room), `side_step` how many widths
    consecutive pairs put their spacers to one side and the other, clear of each other, and `typed` False to leave out
    the points typed in or drawn and the notes about them."""

    def __init__(self, ctx, slices, *, settings=None, islands=None, seeds=None, side_step=1.2, typed=True):
        self.ctx, self.slices, self.islands, self.seeds, self.side_step, self.typed = ctx, slices, islands, seeds, side_step, typed
        self.p = p = settings or ctx.p
        self.t = p["thickness"]; self.d = p["dowel_d"]; self.mf = p["min_feature"]
        self.tab = p["connect"] == "tab"
        # keep the hole's real reach from the outline, not d/2: a square's corner sits at 0.71 d, a slot's end at 0.75 d
        self.margin = hole_reach(self.d + p["slot_offset"], p["dowel_shape"]) + self.mf
        self.rod = [[round(x, 3), round(y, 3)] for x, y in dowel((0, 0), self.d, p["dowel_shape"]).exterior.coords[:-1]]   # the rod's section, for the 3D view
        tab_w = self.d if p["space"] == 0 else self.d * 0.6               # a tab's width along its slot
        self.slot_w = self.t + p["slot_offset"]                           # the slot's width
        self.reach = math.hypot(tab_w, self.slot_w) / 2 if self.tab else self.margin - self.mf   # how far a cut reaches from its centre, any way it turns
        self.extra = []                                                   # the pegs and spacers, as slices of their own
        self.skipped, self.bare, self.rooms = 0, 0, []                    # points that found no spot, pairs left without one, the room those pairs had
        self.named = {}                                                   # connectors so far per pair, for the letters
        self.common = None                                                # the points every slice shares (cached)

    def run(self):
        """Place the connectors pair by pair, say what went short, and give back the slices of the pegs and spacers."""
        p, ctx = self.p, self.ctx
        for i, (a, b) in enumerate(zip(self.slices, self.slices[1:])):
            # what slice a already carries, for every placement: an aligned point repeats exactly and is kept
            taken = [(x, y) for x, y, *_ in a.cutkeys]
            pts = self.points_for_pair(a, b, i, taken) if self.typed else []
            placed = [self.place(a, b, i, j, x, y) for j, (x, y) in enumerate(pts)]
            got = [q for q in placed if q]
            self.skipped += len(pts) - len(got)
            ctx.view["left_out"] += [[round(float(v), 3) for v in (a.M @ np.array([x, y, 0, 1]))[:3]] for (x, y), q in zip(pts, placed) if not q]
            for isl in self.islands_of(a, b):
                got += self.hold(a, b, i, isl, got)
            if not got:      # nothing this size fits here: remember the biggest hole these two layers would take
                self.bare += 1
                both = a.raw.intersection(b.raw)
                if not both.is_empty:
                    self.rooms.append(max(shapely.maximum_inscribed_circle(g, 0.5).length * 2 for g in as_multi(both).geoms))
        # what went short is about the whole stack, so it is a warning of the plan, not of a slice: something that
        # was asked for is not in the cut files (as a note it sat under a green "0 warnings")
        if self.typed:
            ctx.warnings += self._said()
        if p["placement"] == "aligned" and p["dowels"]:
            used = {(round(x, 2), round(y, 2)) for s in self.slices for x, y, *_ in s.cutkeys}
            for x, y in p["dowels"]:
                if (round(x, 2), round(y, 2)) not in used:
                    self.slices[0].warnings.append(f"dowel point ({x:g}, {y:g}) is outside the material of every pair of slices — nothing cut; alt-click nearer the middle of a slice")
        return self.extra

    # ------------------------------------------------------------ one connector
    def cut(self, x, y, ang, tab_w):
        """What one connector cuts into a slice at its local (x, y): the dowel's hole, or the slot a tab goes into."""
        p = self.p
        if not self.tab:
            return dowel((x, y), self.d + p["slot_offset"], p["dowel_shape"])
        dx, dy = np.cos(np.radians(ang)) * tab_w / 2, np.sin(np.radians(ang)) * tab_w / 2
        return rect_along((x - dx, y - dy), (x + dx, y + dy), self.slot_w)

    def fits(self, sl, g, key):
        """A full wall from the outline and from every other cut in the slice: two cuts closer than that run into
        each other and come out as one ragged opening (the reported 6 mm dowels arriving as 8 and 9 mm blobs).
        The same aligned dowel coming round again is the hole already there; a slot is not, it holds one tab."""
        if key in sl.cutkeys:
            return not self.tab
        if sl.inner is None:
            sl.inner = sl.raw.buffer(-self.mf)
        return sl.inner.contains(g) and all(g.distance(c) >= self.mf for c in sl.cutkeys.values())

    def add_cut(self, sl, geom, key, other, pt, name):   # a slice touches two pairs: the same aligned point is cut once
        font = self.p["font"]
        if key not in sl.cutkeys:
            sl.cutkeys[key] = geom; sl.cutnames[key] = name; sl.cuts.append(geom); sl.engages.append("tab" if self.tab else "dowel")
            # a hole that lands on a mark engraved before it wins: the mark moves (a hole holds the model, a mark only names it)
            for m in [m for m in sl.marks if mark_box(*m[:3], font, mark_rot(m)).distance(geom) < 0.3]:
                sl.marks.remove(m)
                hole_mark(sl, next(c for k2, c in sl.cutkeys.items() if sl.cutnames[k2].split("-", 1)[1] == m[2]), m[2], font)
            hole_mark(sl, geom, name.split("-", 1)[1], font)      # Z-3a is marked 3a: every slice of a stack shares the axis
        sl.links.append((other, geom, pt))

    def place(self, a, b, i, j, x, y):
        """Connector j of pair i at the first spot by (x, y) that fits both slices: that spot, or None."""
        # the gap this pair really has: the drawn spacing curve spreads pairs unevenly, and a pair's spacer is as
        # long as its own gap — a peg where the two touch, a spacer with a body where they do not
        spacing = float(np.dot(b.M[:3, 3] - a.M[:3, 3], a.M[:3, 2]))
        gap_i = max(0.0, round(spacing - (a.thickness + b.thickness) / 2, 3))
        tab_w = self.d if gap_i < 1e-6 else self.d * 0.6
        spot = self.first_spot(a, b, i, j, x, y, tab_w)
        if spot is None:
            return None
        xa, ya, ang, ka, kb, ga, gb = spot
        pt = tuple((a.M @ np.array([xa, ya, spacing / 2, 1]))[:3])           # world point in the gap: the connection's identity
        # the connector's name: the lower slice's and a letter (Z-3a, Z-3b …), or the name the hole in `a` already
        # has when a straight rod from the pair below carries on through this one
        name = a.cutnames.get(ka)
        if name is None:
            n = self.named.get(i, 0); self.named[i] = n + 1
            name = f"{a.label}{ABC_LOWER[n % len(ABC_LOWER)] * (n // len(ABC_LOWER) + 1)}"
        self.add_cut(a, ga, ka, b.label, pt, name); self.add_cut(b, gb, kb, a.label, pt, name)
        if self.tab:
            self.extra.append(self.tab_piece(name, a, i, pt, ang, spacing, gap_i, tab_w))
        else:
            self.ctx.view["rods"].append([list((a.M @ np.array([xa, ya, -self.t / 2, 1]))[:3]), list((a.M @ np.array([xa, ya, spacing + self.t / 2, 1]))[:3]), self.d,
                                  self.rod, list(a.M[:3, 0]), name, a.label, b.label])
        return xa, ya

    def first_spot(self, a, b, i, j, x, y, tab_w):
        """The first spot by (x, y) where this connector's cut fits both slices: (x, y in a, the angle, the keys of
        its cut in a and in b, the cuts), or None. A dowel is a straight rod and goes exactly there. A slot holds one
        tab, so consecutive pairs step theirs sideways (the spacer below a slice and the one above sit side by side);
        the other side, then the other direction, then no step are tried before the point is given up. The fit is
        tested on the cut itself — tested on a round hole at the unstepped point, every second pair of an aligned
        stack lost all its spacers to the slots of the pair before, and the layers they held were cut off as floating."""
        if self.tab:
            spacer_dir = self.p["spacer_dir"]
            ang = {"x": 0.0, "y": 90.0, "alternate": 90.0 * (j % 2)}[spacer_dir]
            step = self.d * self.side_step * (1 if i % 2 else -1)
            angs = (ang, 90.0 - ang) if spacer_dir == "alternate" else (ang,)
            tries = [(A, s) for A in angs for s in (step, -step)] + [(A, 0.0) for A in angs]
        else:
            tries = [(0.0, 0.0)]
        for ang, s in tries:
            dx, dy = np.cos(np.radians(ang)), np.sin(np.radians(ang))
            xa, ya = x + dx * s, y + dy * s
            xb, yb = to_local(b.M, [(a.M @ np.array([xa, ya, 0, 1]))[:3]])[0]
            ka, kb = (round(xa, 2), round(ya, 2), ang), (round(xb, 2), round(yb, 2), ang)
            ga, gb = self.cut(xa, ya, ang, tab_w), self.cut(xb, yb, ang, tab_w)
            if self.fits(a, ga, ka) and self.fits(b, gb, kb):
                return xa, ya, ang, ka, kb, ga, gb
        return None

    def tab_piece(self, name, a, i, pt, ang, spacing, gap_i, tab_w):
        """The flat piece across the gap — a peg when space = 0, a spacer (body + a tab each end) otherwise — as a slice of its own."""
        d, t = self.d, self.t
        dx, dy = np.cos(np.radians(ang)), np.sin(np.radians(ang))
        M = frame_xy(np.array(pt), a.M[:3, :3] @ np.array([dx, dy, 0]), a.M[:3, 2])   # piece plane: spacer direction × stack normal
        L = spacing + t                                                     # from the far side of a to the far side of b
        body = Polygon([(-d / 2, -gap_i / 2), (d / 2, -gap_i / 2), (d / 2, gap_i / 2), (-d / 2, gap_i / 2)]) if gap_i > 0 else None
        tabs = Polygon([(-tab_w / 2, -L / 2), (tab_w / 2, -L / 2), (tab_w / 2, L / 2), (-tab_w / 2, L / 2)])
        sl = Layer(name, "P", M, t)                                       # the peg is the connector: it carries its name
        sl.raw = as_multi(unary_union([body, tabs]) if body is not None else tabs)
        sl.pair = i
        return sl

    # ------------------------------------------------------------ topping a pair up
    def islands_of(self, a, b):
        """The islands of a pair that are held: what the plaque gave, none for lines, else all their overlap."""
        if self.islands:
            return self.islands(a, b)
        return [] if self.p["placement"] == "lines" else as_multi(a.raw.intersection(b.raw)).geoms

    @staticmethod
    def _cuts_in(a, piece):
        """The centres of a's cuts that lie in `piece`."""
        return [(x, y) for x, y, _ in a.cutkeys if piece.contains(Point(x, y))]

    def _loose(self, a, piece):
        return not self.tab and dowel_leverage(piece, self._cuts_in(a, piece)) > LEVERAGE_OK

    @staticmethod
    def _far(q, ms):                                        # farthest from the connectors in ms first
        q.sort(key=lambda pt: -min(_dist(pt, m) for m in ms))

    def hold(self, a, b, i, isl, got):
        """Every island the two share is held, by as many connectors as were asked for, whatever the placer chose
        for it: one it gave fewer (crowded out by the cuts already in a, or points skipped) is topped up. Left
        empty, the check finds it floating and auto-fix cuts it off; left with one, it turns on it. Where a
        connector's centre can go is worked out exactly — a wall in from both outlines and from every cut
        already there, plus the connector's own reach — so a small layer with room for one finds it; its most
        inward spot is taken first, then each as far from the others as the room allows. No room at all, and
        the check says what size would fit. Lines are the connectors someone drew; nothing is added to those.
        Gives the spots it placed."""
        p = self.p
        want = max(1, p["n_points"])
        have = [q for q in got if isl.contains(Point(q))]
        # As many as asked for on top of any typed in, and for dowels, on past that while the piece is not
        # held and the next spot holds it better (at most as many again): a dowel typed into a bunny's ear
        # made the count, and the ear's tip lost the dowel the count used to bring it — 1.37 for 0.9 promised.
        piece = max(as_multi(a.raw).geoms, key=lambda g: g.intersection(isl).area)
        need = want + (sum(isl.contains(Point(q)) for q in p["dowels"]) if p["placement"] == "aligned" else 0)
        if len(have) >= need and not self._loose(a, piece):
            return []
        q = self.spots(a, b, isl, have)
        if have:
            self._far(q, have)                                 # a second connector goes far from the first
        mine = []
        while q and (len(have) + len(mine) < need or len(mine) < want and self._loose(a, piece)
                     and dowel_leverage(piece, self._cuts_in(a, piece) + [q[0]]) < dowel_leverage(piece, self._cuts_in(a, piece))):
            s = self.place(a, b, i, len(got) + len(mine), *q.pop(0))
            if s:
                mine.append(s); self._far(q, have + mine)
        return mine

    def spots(self, a, b, isl, have):
        """The spots to try for a connector in island `isl`: a rod carried on from the pair below, then the seeds, then
        a grid over the room that is left."""
        mf, d = self.mf, self.d
        room = inside = isl.buffer(-(mf + self.reach))
        near = [c for s in (a, b) for c in s.cutkeys.values() if c.distance(isl) < mf + self.reach]
        if near and not room.is_empty:
            room = room.difference(unary_union(near).buffer(mf + self.reach))
        # a dowel from the pair below can carry on up through this pair: its hole in a is already there
        q = [] if self.tab else [(x, y) for x, y, _ in a.cutkeys if inside.contains(Point(x, y)) and all(_dist((x, y), m) > 0.01 for m in have)]
        if not room.is_empty:
            parts = sorted(as_multi(room).geoms, key=lambda g: -g.area)
            x0, y0, x1, y1 = room.bounds; h = max(d / 4, math.sqrt(room.area) / 20)
            grid = np.stack(np.meshgrid(np.arange(x0, x1, h), np.arange(y0, y1, h)), -1).reshape(-1, 2)
            q += self.seeds(parts) if self.seeds else [shapely.maximum_inscribed_circle(g, 0.1).coords[0] for g in parts]
            q += [tuple(c) for c in grid[shapely.contains_xy(room, grid[:, 0], grid[:, 1])]]
        return q

    # ------------------------------------------------------------ the points to start from
    @staticmethod
    def spread(region, n, apart=0.0, clear=(), by=0.0):
        """n points inside a region, as far apart as it will take them: along its longer axis, from the ends inward
        until the region contains them all. `apart` is the least separation worth having — two holes closer than
        their own width merge into one, which locates nothing (a cone's apex used to give two 6 mm dowels 4 mm
        apart). `clear` are holes already cut in this slice, to stay `by` away from: where a tapering model makes a
        dowel move inward, its replacement must not land in the wall of the one above it — so the line across the
        region is tried as well as the line along it. A region that takes neither gets nothing.
        Points around the region go in as well — evenly along its outline, pulled in toward the middle until they
        fit — and where the line does not hold it, the set that holds it best wins (dowel_leverage). On a line alone
        a bumpy layer only took two points pulled in near its middle, and three on a line left a disc held along one
        diameter."""
        x0, y0, x1, y1 = region.bounds; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; w, h = x1 - x0, y1 - y0

        def ok(pts):
            return (min((_dist(q, r) for q in pts for r in pts if q is not r), default=apart) >= apart
                    and all(region.contains(Point(q)) for q in pts)
                    and all(_dist(q, r) > by for q in pts for r in clear))

        # as many as fit, down to two: three that do not fit a small layer used to fall straight to one point, which
        # the carried rods then crowded (the horse's legs came out worse held for asking more dowels)
        for many in range(n, 1, -1):
            sets = []
            for span, along_x in sorted([(w, True), (h, False)], reverse=True):
                for k in (0.45, 0.38, 0.3, 0.22, 0.15):
                    pts = [(cx + span * t, cy) if along_x else (cx, cy + span * t) for t in np.linspace(-k, k, many)]
                    if ok(pts):
                        sets.append(pts); break
            c = region.centroid
            for start in np.arange(4) / (4 * many):       # ponytail: 4 starting angles; a finer search if one misses
                edge = np.array([region.exterior.interpolate(start + i / many, normalized=True).coords[0] for i in range(many)])
                for k in (0.9, 0.75, 0.6, 0.45):
                    pts = [(float(x), float(y)) for x, y in (c.x, c.y) + k * (edge - (c.x, c.y))]
                    if ok(pts):
                        sets.append(pts); break
            # the line first, as it always was where it holds: moving holes that already hold crowds the next pair
            # (the hollowed bunny's second layer lost its dowels to two moved out into its ring)
            good = [pts for pts in sets if dowel_leverage(region, pts) <= LEVERAGE_OK]
            if sets:
                return good[0] if good else min(sets, key=lambda pts: dowel_leverage(region, pts))
        # one point: the region's own, or where that lands in the wall of a hole already cut, the spot around the
        # region farthest from those holes (a hollowed bunny's crumb of a layer lost its only dowel this way)
        c, m = region.representative_point(), region.centroid
        if ok([(c.x, c.y)]):
            return [(c.x, c.y)]
        edge = [region.exterior.interpolate(t, normalized=True) for t in np.arange(16) / 16]
        fits = [q for q in ((m.x + k * (e.x - m.x), m.y + k * (e.y - m.y)) for e in edge for k in (0.8, 0.5)) if ok([q])]
        return [max(fits, key=lambda q: min((_dist(q, r) for r in clear), default=0))] if fits else []

    def common_points(self):
        """The same points through the whole stack: n_points per island of the region common to every slice (cached)."""
        if self.common is None:
            inter = None
            for sl in self.slices:
                inter = sl.raw if inter is None else inter.intersection(sl.raw)
            inter = inter.buffer(-self.margin) if inter is not None else None
            self.common = []
            if inter is not None and not inter.is_empty:
                for isl in shapely.get_parts(inter):
                    self.common += self.spread(isl, self.p["n_points"], apart=2.5 * self.d)
        return self.common

    def points_for_pair(self, a, b, i, taken):
        """Connection points (local xy of slice a) between consecutive slices a, b — per island of their overlap,
        each keeping a full wall of material from every hole already cut in slice a (`taken`)."""
        p = self.p; d = self.d; margin = self.margin
        # Two holes need `min_feature` of material between their edges, the same wall this job asks for everywhere
        # else — so their centres are two of the hole's reach (the cut, with its slot offset) plus that wall apart.
        # Any less and `fits` turns the point down: points spread as far apart as they go land right on
        # this limit, so a smaller one here lost the horse's random dowels a layer at a time.
        clearance = 2 * margin - p["min_feature"]
        raw = a.raw.intersection(b.raw)
        overlap = raw.buffer(-margin)
        # An island is somewhere this connector really fits: the hole and the wall around it. Hollowing a model turns
        # every layer into a thin ring, and eroding that ring leaves a scatter of crumbs — each of which used to be
        # given points of its own, which is how a job asking for two pins per layer came back with fifteen.
        islands = [h for g in shapely.get_parts(raw) for h in shapely.get_parts(g.buffer(-margin)) if not h.is_empty and h.area >= (d / 2) ** 2]
        # where a rod through this pair can go, kept on both slices (b's own frame: a layer can be tilted) for the
        # spread check to offer a dowel that will really be cut — the piece alone offered ears spots nothing cut
        a.dowel_room += islands
        b.dowel_room += [into(b.M, a.M, h) for h in islands]
        if not islands:
            return []
        if p["placement"] == "aligned":
            return self._aligned(a, islands, overlap, clearance, taken)
        if p["placement"] == "random":
            return self._random(islands, i, clearance, taken)
        return self._on_lines(a, b, overlap)

    def _aligned(self, a, islands, overlap, clearance, taken):
        """The points the whole stack shares, and the ones typed in, where they fall on this pair's islands; an island
        they miss, or hold badly, gets a spread of its own."""
        p = self.p; d = self.d; out = []
        want = max(1, p["n_points"])
        fixed = [q for q in list(p["dowels"]) + self.common_points() if overlap.contains(Point(q))]
        clear = lambda q, pts: all(_dist(q, r) > clearance for r in pts)   # noqa: E731
        for isl in islands:
            # held is the piece's hold, not the overlap's: an ear's overlap is a sliver of the ear, and two dowels
            # holding the sliver dropped the third rod the ear itself needed (1.37 where the check promised 0.9)
            piece = max(as_multi(a.raw).geoms, key=lambda g: g.intersection(isl).area)
            lev = lambda pts, piece=piece: dowel_leverage(piece, pts)                       # noqa: E731
            # dowels someone placed come on top of the n_points asked for: counted in, one typed into a horse's
            # ear stood in for one of its two and the ear came out held 1.56 where the check promised 1.2
            need = want + sum(isl.contains(Point(q)) for q in p["dowels"])
            held = lambda pts, need=need, lev=lev: len(pts) >= need and lev(pts) <= LEVERAGE_OK   # noqa: E731
            # A shared point is a rod through every layer, but a layer can already hold a rod carried up from wider
            # layers below, beside where the shared point falls: the vase's waist had them 3.8 mm apart, the two
            # holes overlapped, and `fits` left four dowels out. A shared point keeps a wall from every hole the
            # layer already has, or is that hole.
            mine = [q for q in fixed if isl.contains(Point(q)) and all(_dist(q, t) < 1e-6 or _dist(q, t) > clearance for t in taken)]
            # One point is a hinge: a piece pinned once still turns about it, which is exactly what a glued stack
            # does while it dries. Two locate it. An island the common points miss (an ear) gets its own, and one
            # they touch only once is topped up from its own spread, clear of the point already there.
            # A dowel is a straight rod: where this slice already carries a hole that is still inside the overlap,
            # the rod carries on through it. Choosing a fresh spread every pair walks the points inward a few
            # millimetres a layer on anything tapered — close enough to the hole above to merge with it, which is
            # how a cone came out with holes 5 mm apart and half its layers with no dowel at all.
            # Enough of them is not only a count: the shared points sit in the region common to every layer — on a
            # sphere, the smallest one — so a 200 mm piece in the middle was held by two dowels 46 mm apart
            # (reported). Rods carry on farthest out first; a piece they still do not hold is offered them topped up
            # from its own spread toward its edge, or that spread whole beside the dowels typed in (topping one rod
            # up left the blob's foot lopsided, 2.2) — one that holds first, then the count, then the better hold:
            # counting first chose three dowels bunched on a horse's leg over two that held it.
            c = isl.centroid
            for q in sorted(taken, key=lambda q: -_dist(q, (c.x, c.y))):
                if held(mine):
                    break
                if isl.contains(Point(q)) and clear(q, mine):
                    mine.append(q)
            if not held(mine):
                here = [q for q in taken if isl.buffer(clearance).contains(Point(q))]
                fresh = self.spread(isl, want, apart=2.5 * d, clear=here, by=clearance)
                topped = list(mine)
                for q in fresh:
                    if len(topped) < need and clear(q, topped):
                        topped.append(q)
                own = [q for q in p["dowels"] if isl.contains(Point(q))]
                own += [q for q in fresh if clear(q, own)]
                mine = min((mine, topped, own), key=lambda pts: (lev(pts) > LEVERAGE_OK, -min(len(pts), need), lev(pts)))
            out += mine
        return out      # whether each one really fits, against the cuts already made, is `fits`

    def _random(self, islands, i, clearance, taken):
        """n_points per island, drawn at random (seeded by the pair, so the same job gives the same plan)."""
        rng = np.random.default_rng(1000 + i); out = []
        for isl in islands:
            x0, y0, x1, y1 = isl.bounds
            # 800 candidates at once: inside the island and clear of the holes already cut (one shapely call per
            # island instead of one per candidate)
            q = np.round(rng.uniform((x0, y0), (x1, y1), (800, 2)), 1)
            q = q[shapely.contains_xy(isl, q[:, 0], q[:, 1])]
            if len(q) and taken:
                q = q[(np.linalg.norm(q[:, None] - np.asarray(taken, float), axis=2) >= clearance).all(1)]
            if not len(q):
                continue
            # Then each point as far as it can get from the ones already chosen, starting from the candidate
            # farthest from a random one. Taking the first candidates that merely kept clear of each other left
            # both dowels of a pair at one end of the layer and the other end free to lift (reported; the
            # farthest point of a layer sat 0.9 of its width from any dowel) — this keeps the randomness in
            # where the spread starts, not in whether it covers the layer.
            far, got = np.linalg.norm(q - q[0], axis=1), []
            while len(got) < self.p["n_points"] and (not got or far.max() > clearance):
                k = int(far.argmax()); got.append((float(q[k, 0]), float(q[k, 1])))
                to_k = np.linalg.norm(q - q[k], axis=1)
                far = to_k if len(got) == 1 else np.minimum(far, to_k)     # the random seed is not a dowel
            out += got
        return out

    def _on_lines(self, a, b, overlap):
        """Where each 3D line someone drew crosses the plane midway between the pair."""
        zmid = float(np.dot(b.M[:3, 3] - a.M[:3, 3], a.M[:3, 2])) / 2; out = []
        for ln in self.p["lines"]:
            P0, P1 = to_local(a.M, [q[:3] for q in ln[:2]], z=True)
            if abs(P1[2] - P0[2]) < 1e-9:
                continue
            u = (zmid - P0[2]) / (P1[2] - P0[2])
            if 0 <= u <= 1:
                q = P0[:2] + (P1[:2] - P0[:2]) * u
                if overlap.contains(Point(q)):
                    out.append((float(q[0]), float(q[1])))
        return out

    def _said(self):
        """The warnings about connectors that could not be placed: points skipped for want of a wall, and pairs of
        layers that got none — with the size that would fit them, when one would."""
        p = self.p; d = self.d; mf = self.mf; said = []
        skipped, bare, rooms, margin = self.skipped, self.bare, self.rooms, self.margin
        if skipped:
            said.append(f"{skipped} connector(s) left out — no spot there keeps a {mf:g} mm wall from the outline and from "
                        "the other connectors (the 3D view marks each place with a ring): move the points inward or "
                        "make the dowel diameter smaller")
        if bare and p["placement"] == "lines":
            # Here nothing was short of room: the lines put no point there. Offering a smaller dowel sent people
            # looking for a size problem that did not exist.
            said.append(f"{bare} pair(s) of slices got no connector — none of the {len(p['lines'])} line(s) passes "
                        "through the material of both: add a line that does (+ line on the Technique tab draws one up "
                        "the middle of the model to start from), or set placement to aligned")
        elif bare:
            # Connectors are on and some layers got none: at this diameter nothing fits in them, and a stack that is
            # only glued slides while it dries. Say what would fit rather than leave it quietly unaligned.
            # The widest hole those layers hold is the inscribed circle less the wall on *both* sides — and the hole
            # reaches further than d/2 for a square (0.71 d), which is what `margin` already measured for this shape.
            # The median of them, not the widest: sized to the widest, only one pair in the stack could take it. A
            # size at or above the one that just failed means these pairs are not short of room at all — they are
            # narrow strips, or all their room is inside the wall of a hole already cut — so no size is offered.
            # What is left after eroding has to be an island the placer will use, not a sliver: it keeps only those
            # of at least (d/2)² — a disc of that area has radius d/(2·√π), so that comes off the radius too.
            reach = (margin - mf) / (d + p["slot_offset"])       # hole radius per mm of diameter
            room = float(np.median(rooms)) if rooms else 0.0
            fits = round((room / 2 - mf) / (reach + 1 / (2 * math.sqrt(math.pi))) - p["slot_offset"], 1)
            said.append(f"{bare} pair(s) of slices got no connector — a {p['dowel_d']:g} mm one does not fit them: "
                        + (f"set the dowel diameter to about {fits:g} mm" if MIN_DOWEL <= fits < p["dowel_d"] else
                           "they overlap only in strips too narrow to hold one — fewer slices, a thicker hollow wall, "
                           "or set connect to tab")
                        + ", or set connect to none and line them up by eye")
        return said
