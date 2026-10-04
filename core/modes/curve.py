"""Curve: ribs perpendicular to a user curve (boat hull / fuselage construction), interlocked with spine slices
that lie in the curve's plane."""
import math
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from . import Mode, Param, register
from .radial import Radial
from ..geometry import as_multi, section_polygons, to_local
from ..model import Slice
from ..notch import interlock

PLANES = {"xz": (0, 2, 1), "yz": (1, 2, 0), "xy": (0, 1, 2)}      # (u, v, w=plane normal)


def island(M, sec, near):
    """The piece of `sec` (in frame M) nearest `near`, None when there is none: a plane across the front legs also
    cuts the other leg."""
    sec = as_multi(sec)
    return None if sec.is_empty else min(sec.geoms, key=Point(to_local(M, [near])[0]).distance)


def part(ctx, lab, group, M, isl):
    sl = Slice(lab, group, M, ctx.thickness_of(lab), clip=as_multi(isl.buffer(0.01)))   # the clip keeps slots to it
    sl.raw = as_multi(isl)
    return sl


def resample(pts, n_dense=400):
    """Smooth curve through the control points (Catmull-Rom; straight for 2 points) as a dense polyline + arc length."""
    P = np.asarray(pts, float)
    if len(P) < 3:
        d = np.linspace(0, 1, n_dense)[:, None]
        Q = P[0] + (P[-1] - P[0]) * d
    else:
        Q = []
        ext = np.vstack([P[0] * 2 - P[1], P, P[-1] * 2 - P[-2]])
        for i in range(1, len(ext) - 2):
            p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
            for t in np.linspace(0, 1, max(4, n_dense // (len(P) - 1)), endpoint=False):
                Q.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
        Q.append(P[-1]); Q = np.asarray(Q)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
    return Q, s


@register
class Curve(Mode):
    name = "curve"
    title = "Curve (ribs)"
    description = ("Slices perpendicular to a curve, like the ribs of a hull or the vertebrae of an animal: the ribs turn with the "
                   "model's bend instead of staying parallel. The default curve follows the middle of the model; alt-click on the "
                   "model in the 3D view to add or remove control points (orange line, blue dots). Spine slices in the curve plane "
                   "lock the ribs together. A leg, arm or tail takes a branch: ribs square to it and a spine of its own that "
                   "reaches back into the body and slots into the body's ribs (shift+alt-click its tip to add one).")

    def crossing_fix(self, ctx, sl, point):
        """A rib region nothing holds needs another spine through it; a spine region needs another rib. A branch's
        parts (R2-3, K2) are spaced by its own length, which neither changes."""
        if sl.label[1:2].isdigit():
            return None
        if sl.group == "X":
            return {"title": f"add a spine ({ctx.p['spines'] + 1} in total)", "set": {"spines": ctx.p["spines"] + 1}}
        return {"title": f"add a rib ({ctx.p['count'] + 1} in total)", "set": {"count": ctx.p["count"] + 1, "distribution": "count"}}

    @staticmethod
    def reach(ctx, eu, ev, Q, keep):
        """How far the material reaches from the curve, measured in the curve's plane — two rib planes meet along a
        line at some distance from the curve, and that line must stay outside the model. Sampled, not exact. Only
        the `keep` vertices count: a leg with ribs of its own is not where the body ribs meet."""
        V = ctx.mesh.vertices[keep]
        V = V[:: max(1, len(V) // 2000)] - ctx.mid
        C = Q[:: max(1, len(Q) // 60)]
        d2 = (V @ eu)[:, None] - C[None, :, 0]
        e2 = (V @ ev)[:, None] - C[None, :, 1]
        return float(np.sqrt((d2 ** 2 + e2 ** 2).min(1)).max())

    def default_curve(self, ctx, u, v, eu, ev):
        """A curve through the middle of the model: section centroids at 5 stations along the plane's first axis."""
        from ..geometry import section_polygons, frame
        L = ctx.ext[u]; pts = []
        for s in np.linspace(-0.4, 0.4, 5) * L:
            sec = section_polygons(ctx.mesh, frame(ctx.mid + eu * s, eu, up_hint=ctx.ax[(u + 2) % 3] if u != (u + 2) % 3 else ev))
            if not sec.is_empty:
                c = sec.centroid; P = frame(ctx.mid + eu * s, eu, up_hint=ctx.ax[(u + 2) % 3])[:3, :3] @ np.array([c.x, c.y, 0]) + ctx.mid + eu * s
                pts.append([float(np.dot(P - ctx.mid, eu)), float(np.dot(P - ctx.mid, ev))])
        m = ctx.p["margin"] or ctx.p["thickness"]
        return pts if len(pts) >= 2 else [[-L / 2 + m, 0], [L / 2 - m, 0]]

    def across(self, ctx, U, u, eu, ew):
        """Where the body's centre lies across the curve plane, at each `U` along it: the section centroids' component
        along the plane normal, interpolated. A horse with its head turned has its centre 30 mm to one side there —
        the curve, the ribs and the spines follow that instead of the bounding box's middle plane."""
        from ..geometry import section_polygons, frame
        st, wv = [], []
        lo, hi = -0.48 * ctx.ext[u], 0.48 * ctx.ext[u]
        for s in np.linspace(lo, hi, 16):
            F = frame(ctx.mid + eu * s, eu, up_hint=ctx.ax[(u + 2) % 3])
            sec = section_polygons(ctx.mesh, F)
            if sec.is_empty:
                continue
            c = sec.centroid; P = F[:3, :3] @ np.array([c.x, c.y, 0]) + ctx.mid + eu * s
            st.append(s); wv.append(float(np.dot(P - ctx.mid, ew)))
        if len(st) < 2:
            return np.zeros(len(U))
        return np.interp(U, st, wv)

    def _branches(self, ctx, ew, C, pitch):
        """[row, start, tip, direction, length, spine normal, region, ribs] per branch, numbered by its row in the
        table (a row left out keeps the others' labels and edits). The start is the end nearer the curve and sits on
        the joint plane J-i as edited. The region — past J-i, on its own side of the plane between it and each
        neighbouring branch (radial's B-i-j), and no further to either side than its own ribs' sections reach, plus
        a pitch — is what the branch's parts own and the body's do not. The spine contains the curve's tangent where
        the branch leaves it, so the body ribs cross it square, whichever way the branch points."""
        big = ctx.span; out = []
        for i, seg in enumerate(ctx.p["branches"] or []):
            a, b = (np.asarray(q, float) for q in seg)
            if np.linalg.norm(C - b, axis=1).min() < np.linalg.norm(C - a, axis=1).min():
                a, b = b, a                                      # drawn from the tip: a joint at the hoof owns the body
            if np.linalg.norm(b - a) < 1e-6:
                ctx.errors.append(f"branch {i + 1} has no length: give it a start and a tip (they are the same point)")
                continue
            d = (b - a) / np.linalg.norm(b - a)
            j = int(np.linalg.norm(C - a, axis=1).argmin()); t = C[min(j + 1, len(C) - 1)] - C[max(j - 1, 0)]
            t -= (t @ ew) * ew                                   # in the curve's plane, as the ribs are: a leg pulls C sideways
            ns = np.cross(d, t / np.linalg.norm(t))
            ns = ns if np.linalg.norm(ns) > 0.2 else ew - (ew @ d) * d    # a tail runs on along the curve
            ns /= np.linalg.norm(ns)
            J = ctx.frame(f"J-{i + 1}", a, d, up_hint=ns)
            a = a + d * ((J[:3, 3] - a) @ J[:3, 2]) / (d @ J[:3, 2]); L = float((b - a) @ d)
            if L < 1e-6:
                ctx.errors.append(f"branch {i + 1}: its joint (J-{i + 1}) is moved past its tip")
                continue
            out.append([i, a, b, d, L, ns, J])
        lobes, b3d = Radial._parted(ctx, [((a + b) / 2, d, L / 2, ns) for _, a, b, d, L, ns, _ in out], [br[0] + 1 for br in out])
        ctx.axes3d = [[[float(x) for x in q] for q in seg] for seg in ctx.p["branches"] or []]    # as the table has them
        ctx.bounds3d = [{"label": f"J-{i + 1}", "M": np.round(J, 6).tolist(), "size": round(0.6 * L, 1)} for i, _, _, _, L, _, J in out] + b3d
        for br, lobe in zip(out, lobes):
            i, a, b, d, L, ns, J = br
            cell = [(J[:3, 3], J[:3, 2])] + lobe; nb = max(1, round(L / pitch)); secs = []
            for j in range(nb):
                lab = f"R{i + 1}-{j + 1}"; c = a + d * (L * (j + 0.5) / nb); M = ctx.frame(lab, c, d, up_hint=ns)
                secs.append((lab, M, c, section_polygons(ctx.mesh, M).intersection(Radial._owned(M, cell, big))))
            # Sideways the region stops a pitch past the sections of the branch's outer half — past J alone, a branch
            # out of the body's side took a slab of it as long as the body, and its parts keep only the leg. Nearer
            # the joint a slanted rib's plane runs on through the body
            E = np.array([ns, np.cross(d, ns)])
            X = np.vstack([[a, b]] + [np.asarray(g.exterior.coords) @ M[:3, :2].T + M[:3, 3]
                                      for _, M, c, S in secs[nb // 2:] if (g := island(M, S, c)) is not None]) - a
            lo, hi = (X @ E.T).min(0) - pitch, (X @ E.T).max(0) + pitch
            cell += [(a + e * h, -e) for e, h in zip(E, hi)] + [(a + e * h, e) for e, h in zip(E, lo)]
            br[6:] = [cell, [(lab, M, g) for lab, M, c, S in secs if (g := island(M, S.intersection(Radial._owned(M, cell, big)), c)) is not None]]
        return out

    def _limbs(self, ctx, br, spines, ribs, pitch):
        """Each branch's ribs (R2-3), square to it at the body's rib pitch, and its spine (K2) through them, with a
        tongue reaching back past the joint into the body, where it slots into the body ribs. The spine runs through
        the middle of the outer half's sections, not along the line: a line clicked on the hoof's skin put it there."""
        big = ctx.span; out = []
        for i, a, b, d, _, ns, cell, isles in br:
            lrs = ctx.keep([part(ctx, lab, "X", M, isl) for lab, M, isl in isles])
            if isles:
                off = np.mean([(M[:3, :2] @ isl.centroid.coords[0] + M[:3, 3] - a) @ ns for _, M, isl in isles[len(isles) // 2:]])
                a, b = a + ns * off, b + ns * off
            lab = f"K{i + 1}"; Mk = ctx.frame(lab, (a + b) / 2, ns, up_hint=d)
            e = np.cross(ns, d) * 1.5 * pitch; down = d * max(2 * pitch, 4 * ctx.p["thickness"])
            # the tongue stops short of each body spine: a branch at a slant would cross it in the body, unslotted
            h = [(s.thickness + ctx.thickness_of(lab)) / 2 + 1 for s in spines]
            bands = [Radial._owned(Mk, [(s.M[:3, 3] + s.M[:3, 2] * w, -s.M[:3, 2]), (s.M[:3, 3] - s.M[:3, 2] * w, s.M[:3, 2])], big) for s, w in zip(spines, h)]
            tongue = Polygon(to_local(Mk, [a + e + d * pitch, a - e + d * pitch, a - e - down, a + e - down])).difference(unary_union(bands))
            others = unary_union([Radial._owned(Mk, c2, big) for *_, c2, _ in br if c2 is not cell])
            isl = island(Mk, section_polygons(ctx.mesh, Mk).intersection(unary_union([Radial._owned(Mk, cell, big), tongue]).difference(others)), a + d * pitch)
            ks = ctx.keep([part(ctx, lab, "Y", Mk, isl)] if isl is not None else [])
            for r in lrs:
                interlock([r], ks, ctx, r.M[:3, 0], -r.M[:3, 0])
            interlock(ribs, ks, ctx, d, -d)
            if ks and not any(x.startswith("R-") for x in ks[0].engages):
                ctx.errors.append(f"branch {i + 1}: its start is past the body's ribs, nothing holds it — extend the "
                                  f"curve over it, or move the start (J-{i + 1}) into the body")
            out += lrs + ks
        return out

    legend = ("R-4 = the 4th rib along the curve, counted from its start · "
              "K-1 = the 1st spine, the long part that threads through every rib and holds the spacing · "
              "R2-3 = the 3rd rib of branch 2 · K2 = branch 2's spine · J-2 = where branch 2 leaves the body · "
              "B-1-2 = the plane between branches 1 and 2")
    params = [
        Param("plane", "choice", "xz", "Plane that contains the curve (first letter = along, second = up)", choices=["xz", "yz", "xy"]),
        Param("curve", "points", [], "Control points [[u,v],...] in the plane (model centred at 0); fewer than two = a curve through the middle along the plane's first axis", unit="mm"),
        Param("branches", "lines3", [], "One line per leg, arm or tail: start where it leaves the body → its tip (mm from the model's centre). "
                                        "Each gets ribs square to it and its own spine, which reaches back into the body and slots into the "
                                        "body ribs. Empty = none", unit="mm"),
        Param("distribution", "choice", "count", "count = N ribs; distance = one rib every `spacing` of curve length", choices=["count", "distance"]),
        Param("count", "int", 8, "Rib count", 1, 300, 1),
        Param("spacing", "number", 20, "Rib spacing along the curve (mm)", 1, 500, 0.5, unit="mm"),
        Param("spines", "int", 1, "Spine slices in the curve plane (0 = ribs only, glue/wire them yourself)", 0, 20, 1),
    ]

    def build(self, ctx):
        p = ctx.p
        u, v, w = PLANES[p["plane"]]; eu, ev, ew = ctx.ax[u], ctx.ax[v], ctx.ax[w]
        cv = p["curve"] if len(p["curve"] or []) >= 2 else self.default_curve(ctx, u, v, eu, ev)
        pts = np.array(sorted([float(q[0]), float(q[1])] for q in cv))   # in-plane; the UI may hand back the w it was shown
        Q, s = resample(pts)
        W = self.across(ctx, Q[:, 0], u, eu, ew)                 # the curve's third coordinate: through the body, not the box
        C = ctx.mid + np.outer(Q[:, 0], eu) + np.outer(Q[:, 1], ev) + np.outer(W, ew)
        ctx.curve3d = C.tolist()                                 # for the 3D view
        ctx.curve_pts = [[float(a), float(b), float(c)] for (a, b), c in zip(pts, self.across(ctx, pts[:, 0], u, eu, ew))]
        n = p["count"] if p["distribution"] == "count" else max(1, int(s[-1] // p["spacing"]))
        br = self._branches(ctx, ew, C, s[-1] / (n + 1))

        def clip(M):                                             # body parts stop where a branch's own begin
            owned = [g for *_, cell, _ in br if not (g := Radial._owned(M, cell, ctx.span)).is_empty]
            return as_multi(Radial._owned(M, [], ctx.span).difference(unary_union(owned))) if owned else None
        stations = np.linspace(0, s[-1], n + 2)[1:-1] if n > 1 else [s[-1] / 2]
        # station position and tangent angle in the curve plane
        place = []
        for si in stations:
            j = int(np.searchsorted(s, si)); j = min(max(j, 1), len(Q) - 1)
            a = (si - s[j - 1]) / max(s[j] - s[j - 1], 1e-9)
            q = Q[j - 1] * (1 - a) + Q[j] * a
            tang = Q[min(j + 1, len(Q) - 1)] - Q[max(j - 2, 0)]
            place.append((q, math.atan2(tang[1], tang[0]), float(np.interp(si, s, W))))
        # Ribs perpendicular to a bend meet on its inside: two neighbours whose planes differ by θ and sit `d` apart
        # cross at d / (2·tan(θ/2)) from the curve, so the turn between consecutive ribs is limited to keep that
        # crossing outside the model. The reach is doubled because a crossing exactly at the material's edge still
        # cuts the parts living there. Clamping runs outward from the middle rib, so on a bend tighter than the
        # model is wide the shortfall is shared by both ends instead of piling up at one.
        V = ctx.mesh.vertices
        body = ~np.any([np.all([(V - m) @ nm > 0 for m, nm in cell], axis=0) for *_, cell, _ in br], axis=0) if br else slice(None)
        reach = 2 * (self.reach(ctx, eu, ev, Q, body) + p["thickness"])
        turned = 0
        mid = len(place) // 2
        for i in list(range(mid + 1, len(place))) + list(range(mid - 1, -1, -1)):
            k = i - 1 if i > mid else i + 1                      # the neighbour already settled
            d = float(np.linalg.norm(place[i][0] - place[k][0]))
            lim = 2 * math.atan(d / (2 * reach)) if reach > 1e-9 else math.pi
            prev = place[k][1]
            diff = (place[i][1] - prev + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) > lim:
                place[i] = (place[i][0], prev + math.copysign(lim, diff), *place[i][2:]); turned += 1
        if turned:
            ctx.notes_extra = (f"{turned} rib(s) turned less than the curve so they do not cross inside the model "
                               f"(the bend is tighter than the model is wide); a gentler curve or fewer ribs keeps them perpendicular")
        ribs = []
        for i, (q, ang, wq) in enumerate(place):
            # ribs stay square to the curve within its plane: turning them with the sideways drift as well makes
            # neighbours cross inside a turned neck, and the turn limit above only knows the in-plane angle
            origin = ctx.mid + q[0] * eu + q[1] * ev + wq * ew
            normal = math.cos(ang) * eu + math.sin(ang) * ev
            lab = f"R-{i + 1}"
            M = ctx.frame(lab, origin, normal, up_hint=ew)          # local y = plane normal, local x = in-plane perpendicular
            ribs.append(Slice(lab, "X", M, ctx.thickness_of(lab), clip=clip(M)))
        ribs = ctx.keep(ribs)
        ctx.cover_r = s[-1] / (2 * max(1, n)) + p["thickness"]
        spines = []
        if p["spines"]:
            labs = [f"K-{k + 1}" for k in range(p["spines"])]; th = [ctx.thickness_of(l) for l in labs]
            w_mid = float(W.mean())                                  # spines spread around the body's centre, not the box's
            for lab, off, tk in zip(labs, ctx.positions(ctx.ext[w], th), th):
                M = ctx.frame(lab, ctx.mid + ew * (off + w_mid), ew, up_hint=ev)
                spines.append(Slice(lab, "Y", M, tk, clip=clip(M)))
            spines = ctx.keep(spines)
            for r in ribs:                                           # ribs open toward their in-plane normal
                interlock([r], spines, ctx, r.M[:3, 0], -r.M[:3, 0])
        return ribs + spines + self._limbs(ctx, br, spines, ribs, s[-1] / (n + 1))
