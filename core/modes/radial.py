"""Radial: half-slices fanning out from a central axis, locked by horizontal ring slices (full sections) with
radial slots. Several axes — a snowman with one per ball, a dumbbell with one through each ball — are parted by flat
planes between neighbouring axes (each a part in the 3D view: move and tilt it like a slice), so the fans never run
into each other, and a spine (one full plane through every axis, cut whole and slotted into every ring) ties the
lobes together.
Assembly: stack the rings on a pole or jig, then slide each half-slice in from the outside."""
import math
import numpy as np
from shapely.geometry import Polygon
from . import Mode, Param, register, MAX_SLICES
from ..model import Slice
from ..geometry import rot_about, as_multi, circle
from ..notch import cut_slots

COINCIDENT = math.cos(math.radians(3))     # two planes this close in angle are the same sheet, not a crossing
CLEARANCE = 0.5                            # each lobe stops this far short of the plane between it and the next


def closest(A0, A1, B0, B1):
    """The closest pair of points on two segments — for parallel ones, at the middle of their overlap."""
    u = A1 - A0; v = B1 - B0; w = A0 - B0
    a, b, c, d, e = u @ u, u @ v, v @ v, u @ w, v @ w
    parallel = a * c - b * b < 1e-9 * a * c  # no single closest pair: take the middle of where they overlap
    s = float(np.mean(np.clip([(B0 - A0) @ u / a, (B1 - A0) @ u / a], 0, 1)) if parallel
              else np.clip((b * e - c * d) / (a * c - b * b), 0, 1))   # else the lines' closest point, clamped on
    t = float(np.clip((b * s + e) / c, 0, 1)); s = float(np.clip((b * t - d) / a, 0, 1))
    return A0 + s * u, B0 + t * v


@register
class Radial(Mode):
    name = "radial"
    title = "Radial Slices"
    description = ("Half-slices radiating from an axis (move it with `center`, turn the fan with `angle`), held by horizontal ring "
                   "slices with radial slots. Give `axes` a line per lobe for a fan each — a snowman's balls, a dumbbell's — "
                   "each owning the part of the model nearest to it, tied together by a spine through every axis.")
    legend = ("R-2a / R-2b = the two halves of the 2nd radial plane of the fan, counted round from `angle` · "
              "R2-1a = the same on the 2nd axis, when the job has several · "
              "Z-3 = the 3rd ring slice along the axis, counted from the low end · "
              "SP-1 = a spine: the full plane that runs through every axis and ties the fans together")
    params = [
        Param("axis", "choice", "z", "Central axis (when `axes` below is empty)", choices=["x", "y", "z"]),
        Param("axes", "lines3", [], "One line per fan (start → end, mm from the model's centre): where that axis sits, which way it points, "
                                    "and the stretch of the model its rings are spread along. Empty = one axis through the centre. Neighbouring "
                                    "lobes are parted by a flat plane between their axes (B-1-2, a translucent part in the 3D view: click it and "
                                    "drag the arrow to move it, shift-drag to tilt, ctrl-drag to roll, or use the sliders), so the fans never "
                                    "run into each other, and a spine — one full plane through every axis — ties the lobes together. In the 3D "
                                    "view: drag an axis to move it, drag an end "
                                    "to move that end — every axis is its own two dots. A dumbbell: alt-click each ball for a parallel axis "
                                    "through the click, then drag it to the ball's centre. A snowman: + splits the axis in two, then drag the "
                                    "ends to the waists. Alt-click an axis to remove it. Seen face-on, the plane the other axes share holds "
                                    "the drag, so the spine survives it; turn the view until that plane is edge-on to move an axis off it. "
                                    "Every fan shares `count`, so neighbouring fans meet plane for plane", unit="mm"),
        Param("count", "int", 6, "Radial planes through each axis (gives 2 × count half-slices per axis)", 1, 90, 1),
        Param("angle", "number", 0, "Turn the whole fan about the axis (deg): where the first radial plane starts. The pattern repeats every 180 / count degrees. "
                                    "Axes side by side on one plane start their fans on the spine instead, and this does nothing", -90, 90, 1, unit="deg"),
        Param("spine", "int", 0, "Full planes through every axis, cut whole and slotted into every ring: what holds one fan to the next. "
                                 "0 = automatic: none for one axis, one for several. Axes on one line (a snowman's balls, one above the other) "
                                 "can take more; axes side by side on one plane share exactly one", 0, 8, 1),
        Param("core_d", "number", 0, "Central clearance: half-slices stop at this diameter (mm). 0 = automatic minimum so 2 × count slices fit around the axis; smaller than the minimum = collision error", 0, 300, 1, unit="mm"),
        Param("rings", "choice", "count", "Ring slices along each axis: count = N evenly spread, distance = one every `ring_spacing`", choices=["count", "distance"]),
        Param("ring_count", "int", 4, "Number of ring slices (per axis)", 1, 200, 1, show_if=("rings", "count")),
        Param("ring_spacing", "number", 40, "Ring spacing along the axis (mm)", 2, 1000, 1, unit="mm", show_if=("rings", "distance")),
        Param("hole_d", "number", 0, "Hole in the middle of every ring for a pole / dowel (mm); 0 = none", 0, 100, 0.5, unit="mm"),
    ]
    hidden_common = ("notch_ratio",)

    # ---------------------------------------------------------------- the axes and how they lie
    @staticmethod
    def perp(u):
        """A unit vector across `u`: where a fan's first radial plane points before `angle` turns it. The next world
        axis round from the one `u` mostly follows — the single-axis convention (z → x, x → y, y → z) — so taking hold
        of the default axis and dragging it does not turn the whole fan by a quarter."""
        v = np.eye(3)[(int(np.argmax(np.abs(u))) + 1) % 3]
        v = v - np.dot(v, u) * u
        return v / np.linalg.norm(v)

    def _axes(self, ctx):
        """[(origin, direction, half-length, first radial)] — one entry per fan. `axes` gives a line each (its
        midpoint is the fan's centre, its length the stretch its rings are spread along, and what is nearest to it
        is its lobe); empty = the single central axis of `axis` + `center`, exactly as before."""
        p = ctx.p
        ax = "xyz".index(p["axis"])
        single = [(ctx.mid, ctx.ax[ax], ctx.ext[ax] / 2, ctx.ax[(ax + 1) % 3])]
        out = []
        for i, seg in enumerate(p["axes"] or []):
            a, b = (np.asarray(v, float) for v in seg)
            u = b - a; L = float(np.linalg.norm(u))
            if L < 1e-6:
                ctx.errors.append(f"axis {i + 1} has no length: give it a start and an end (they are the same point)")
                continue
            u = u / L
            out.append(((a + b) / 2, u, L / 2, self.perp(u)))
        if not out:
            return single
        u0 = out[0][1]                                    # one direction for all of them: a fan is symmetric, so
        return [(O, u if u @ u0 >= 0 else -u, h, e) for O, u, h, e in out]     # only the sign of a line is arbitrary

    @staticmethod
    def _layout(axes, tol):
        """How the axes lie, from their ends: "line" — one axis, or several one after the other on one line, where
        every plane through the line is a spine; "plane" — all in one plane, side by side or meeting at the waists,
        which share exactly one spine (its normal comes back too); "skew" — on no single plane, with how far off one
        they are and the axes as they would be on the nearest plane (the one-click fix)."""
        P = np.array([[O - u * h, O + u * h] for O, u, h, _ in axes]).reshape(-1, 3)
        Q = P - P.mean(0); Vt = np.linalg.svd(Q)[2]
        if np.linalg.norm(Q - np.outer(Q @ Vt[0], Vt[0]), axis=1).max() < tol:
            return "line", None, 0.0, None
        off = float(np.abs(Q @ Vt[2]).max())
        flat = np.round(P - np.outer(Q @ Vt[2], Vt[2]), 1).reshape(-1, 2, 3).tolist()
        return ("plane" if off < tol else "skew"), Vt[2], off, flat

    def _bounds(self, ctx, axes):
        """The flat plane between every pair of axes: through the middle of their closest points, facing from one
        axis's centre to the other's — the mitre between a snowman's balls, the plane across a dumbbell's neck.
        Axes side by side (their stretches overlap along the direction) face each other straight across instead, so
        shortening one does not tilt the plane. Each is a labelled frame (B-1-2 = between axes 1 and 2), so the
        per-slice offset / tilt / roll move and turn it, and the 3D view shows it as a part to take hold of. Only
        the planes two lobes actually meet at are kept: with three balls in a row, the one between the first and the
        last would sit inside the middle ball. → {(i, j): frame}"""
        C = [O for O, _, _, _ in axes]
        out = {}
        for i in range(len(axes)):
            for j in range(i + 1, len(axes)):
                (Oi, ui, hi, ei), (Oj, uj, hj, _) = axes[i], axes[j]
                P, Q = closest(Oi - ui * hi, Oi + ui * hi, Oj - uj * hj, Oj + uj * hj)
                n = C[j] - C[i]
                um = ui + uj; um /= np.linalg.norm(um)
                lo = max((Oi - ui * hi) @ um, (Oj - uj * hj) @ um); up = min((Oi + ui * hi) @ um, (Oj + uj * hj) @ um)
                if up - lo > 0.5 * min(hi, hj):          # side by side: face straight across, not centre to centre
                    n = n - (n @ um) * um
                if np.linalg.norm(n) < 1e-6:
                    n = um
                out[(i, j)] = ctx.frame(f"B-{i + 1}-{j + 1}", (P + Q) / 2, n / np.linalg.norm(n), up_hint=ei)
        keep = {}
        for (i, j), M in out.items():
            m, n = M[:3, 3], M[:3, 2]
            if all(np.sign((m - out[k][:3, 3]) @ out[k][:3, 2]) == np.sign((C[i] - out[k][:3, 3]) @ out[k][:3, 2])
                   for k in out if k != (i, j) and i in k) and \
               all(np.sign((m - out[k][:3, 3]) @ out[k][:3, 2]) == np.sign((C[j] - out[k][:3, 3]) @ out[k][:3, 2])
                   for k in out if k != (i, j) and j in k):
                keep[(i, j)] = M
        return keep

    @staticmethod
    def _owned(M, planes, big):
        """The part of frame M's plane on this lobe's side of every (point, normal) boundary — the normal points into
        the lobe — as a local polygon, a hair inside each boundary so neighbouring lobes never claim the same
        millimetres."""
        g = Polygon([(-big, -big), (big, -big), (big, big), (-big, big)])
        for m, n in planes:
            a, b = float(n @ M[:3, 0]), float(n @ M[:3, 1]); c = float(n @ (M[:3, 3] - m)) - CLEARANCE; k = math.hypot(a, b)
            if k < 1e-9:                                  # the slice runs parallel to the boundary: all on one side of it
                if c < 0:
                    return Polygon()
                continue
            # the boundary's line in this plane, and the half-plane on the lobe's side of it. A boundary nearly
            # parallel to this plane meets it far away (c / k), so the half-plane reaches from there past the model
            p0 = -c / k ** 2 * np.array([a, b]); d = np.array([-b, a]) / k; nin = np.array([a, b]) / k
            L, D = 2 * big, max(c / k, 0.0) + 2 * big
            g = g.intersection(Polygon([p0 + d * L, p0 - d * L, p0 - d * L + nin * D, p0 + d * L + nin * D]))
        return g

    # ---------------------------------------------------------------- build
    def build(self, ctx):
        p = ctx.p
        t = p["thickness"]; n = p["count"]; big = ctx.span
        axes = self._axes(ctx)
        # where each axis runs, for the 3D view to draw and for its ends to be dragged — the single default axis
        # included, so it can be taken hold of before `axes` has ever been filled in
        ctx.axes3d = [[(O - u * h).tolist(), (O + u * h).tolist()] for O, u, h, _ in axes]
        several = len(axes) > 1
        bounds = self._bounds(ctx, axes) if several else {}
        # each lobe's side of every plane it meets a neighbour at: the normal turned to point into the lobe
        lobes = [[(M[:3, 3], M[:3, 2] * (np.sign((axes[i][0] - M[:3, 3]) @ M[:3, 2]) or 1.0)) for k, M in bounds.items() if i in k]
                 for i in range(len(axes))]
        ctx.bounds3d = [{"label": f"B-{i + 1}-{j + 1}", "M": np.round(M, 6).tolist(), "size": round(1.3 * min(axes[i][2], axes[j][2]) * 2, 1)}
                        for (i, j), M in bounds.items()]
        # the spine: automatic for several axes — without one nothing joins a fan to the next and the lobes part
        kind, n_s, off, flat = self._layout(axes, t)
        n_sp = p["spine"] or (1 if several else 0)
        spines, ang0 = [], p["angle"]
        if n_sp and kind == "line":                       # the whole pencil of planes through the line: n of them, on the fan's own angles
            O, u, _, e1 = axes[0]
            spines = [np.cross(u, rot_about(u, ang0 + 180.0 * (round(j * n / n_sp) % n) / n) @ e1) for j in range(min(n_sp, n))]
        elif n_sp and kind == "plane":
            spines, ang0 = [n_s], 0.0
            if n_sp > 1:
                ctx.errors.append(f"spine: axes side by side on one plane share exactly one plane — cut 1 instead of {n_sp}. Put every axis on one line for a fan of spines")
            # each fan starts on the spine, so it takes the place of one fan plane instead of crossing every half-slice
            axes = [(O, u, h, np.cross(n_s, u) / np.linalg.norm(np.cross(n_s, u))) for O, u, h, _ in axes]
        elif n_sp:
            msg = (f"spine: the axes are not on one plane ({off:.0f} mm off it) — no single sheet passes through all of them, so "
                   f"nothing joins one fan to the next. Move an axis, or one of its ends, until they lie on one plane")
            ctx.errors.append(msg)
            ctx.fixes = [{"error": msg, "options": [{"title": f"put the axes on one plane (moves each end by up to {off:.0f} mm)", "set": {"axes": flat},
                                                     "note": "every axis end moved onto the plane nearest to all of them; the spine then runs through every axis"}]}]
        nr = p["ring_count"] if p["rings"] == "count" else max(1, int(2 * min(a[2] for a in axes) // p["ring_spacing"]))
        if len(axes) * (2 * n + nr) > MAX_SLICES:
            ctx.errors.append(f"{len(axes)} axes × ({2 * n} half-slices + {nr} rings) is over the {MAX_SLICES} this "
                              f"can plan: fewer radial planes, fewer rings, or fewer axes")
            return []
        halves, rings, ring_i = [], [], 0
        ctx.core_d_min = 0.0
        for i, (O, u, h, e1) in enumerate(axes):
            # the planes of this fan, minus the ones a spine already is: that sheet is cut whole instead of in halves
            fan = []
            for k in range(n):
                radial = rot_about(u, ang0 + 180.0 * k / n) @ e1
                nrm = np.cross(u, radial)
                if not any(abs(nrm @ s) > COINCIDENT for s in spines):
                    fan.append((k, radial, nrm))
            need = 2 * (len(fan) * (t + p["slot_offset"]) / math.pi + t)     # the kept slices have to fit around the axis
            core_r = (p["core_d"] or need) / 2
            ctx.core_d_min = max(ctx.core_d_min, need)
            if p["core_d"] and p["core_d"] < need - 1e-6:
                ctx.errors.append(f"core_d = {p['core_d']:g} mm is too small: {2 * len(fan)} half-slices of {t:g} mm collide at the axis — core_d must be ≥ {need:.0f} mm (or fewer radial planes, or thinner material)")
            if p["hole_d"] and p["hole_d"] > 2 * core_r - 2 * p["min_feature"]:
                ctx.errors.append(f"hole_d = {p['hole_d']:g} mm leaves no wall between the ring hole and the slots — must be ≤ {2 * core_r - 2 * p['min_feature']:.0f} mm")
            tag = f"R{i + 1}" if several else "R"
            for k, radial, nrm in fan:
                for half, sgn in (("a", 1), ("b", -1)):
                    lab = f"{tag}-{k + 1}{half}"
                    M = ctx.frame(lab, O, nrm, up_hint=u)      # local x = ±radial, local y = the axis
                    sl = Slice(lab, "R", M, ctx.thickness_of(lab))
                    sx = np.sign(np.dot(M[:3, 0], radial)) * sgn   # which local-x side is this half
                    # its own side of the axis, past the core; with several axes its own lobe — up to the planes
                    # between it and its neighbours, however long its line is drawn — else the stretch of the axis
                    reach = big if several else h
                    clip = Polygon([(sx * core_r, -reach), (sx * big, -reach), (sx * big, reach), (sx * core_r, reach)])
                    sl.clip = as_multi(clip.intersection(self._owned(M, lobes[i], big)) if several else clip)
                    sl.radial = sgn * radial; sl.lobe = i
                    halves.append(sl)
            # ring slices, numbered straight through: Z-1 is the first ring of the first axis
            labs = [f"Z-{ring_i + j + 1}" for j in range(nr)]; ring_i += nr
            th = [ctx.thickness_of(l) for l in labs]
            for lab, z, tk in zip(labs, ctx.positions(2 * h, th), th):
                sl = Slice(lab, "C", ctx.frame(lab, O + u * z, u, up_hint=e1), tk)
                sl.lobe = i
                if several:                                   # a ring of one ball must not run on into the other
                    sl.clip = as_multi(self._owned(sl.M, lobes[i], big))
                if p["hole_d"] > 0:
                    sl.cuts.append(circle((0, 0), p["hole_d"]))
                rings.append(sl)
        halves = ctx.keep(halves); rings = ctx.keep(rings)
        # spines: full sections through every axis, held by every ring they cross
        O0, u0 = axes[0][0], axes[0][1]
        spine_sl = []
        for j, nrm in enumerate(spines):
            lab = f"SP-{j + 1}"
            spine_sl.append(Slice(lab, "R", ctx.frame(lab, O0, nrm, up_hint=u0), ctx.thickness_of(lab)))
        spine_sl = ctx.keep(spine_sl)
        # slots: half-slice takes `notch_ratio` from the axis side, ring the rest from the outside. A spine and a
        # half-slice both contain the axis, so they never cross — the rings hold both.
        r = p["notch_ratio"]
        for h in halves:
            for ring in rings:
                if ring.lobe != h.lobe:                   # a lobe's parts never reach another lobe's: no crossing to cast for
                    continue
                cut_slots(h, ring, ctx, tuple(-h.radial), r)
                cut_slots(ring, h, ctx, tuple(h.radial), 1 - r)
        # a ring slides onto the spine from its own side of the model: a dumbbell's lower rings come up from below
        # and its upper rings down from above, so neither has to pass through the other ball's part of the spine.
        # Both are one sheet along their crossing line (`through`): one slot each for the whole line, to their own
        # edges — the spine's material goes on past the ring's lobe, and a ring's chord may graze the neck
        centre = np.mean([a[0] for a in axes], axis=0)
        for sp in spine_sl:
            for ring in rings:
                d = np.cross(sp.M[:3, 2], ring.M[:3, 2])
                if np.linalg.norm(d) < 1e-9:
                    continue
                d = d / np.linalg.norm(d); side = float(np.dot(ring.M[:3, 3] - centre, d))
                s = np.sign(side) if abs(side) > t else 1.0
                cut_slots(sp, ring, ctx, tuple(s * d), r, through=True)
                cut_slots(ring, sp, ctx, tuple(-s * d), 1 - r, through=True)
        if not rings:
            ctx.errors.append("no ring slices — nothing holds the half-slices")
        ctx.cover_r = max(max(a[2] for a in axes) / max(1, nr), math.pi * max(ctx.ext) / (4 * n)) + t
        return halves + rings + spine_sl

    def crossing_fix(self, ctx, sl, point):
        if sl.group != "R":
            return None
        O, u = self._axes(ctx)[0][:2]
        z = float(np.dot(np.asarray(point) - O, u))
        return {"title": f"add a ring slice at {ctx.p['axis']} = {z:.0f} mm", "set": {"ring_count": ctx.p["ring_count"] + 1}, "note": "rings are spread evenly; for an exact position use offset on the nearest ring"}
