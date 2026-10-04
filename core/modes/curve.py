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
from ..notch import cut_slots

PLANES = {"xz": (0, 2, 1), "yz": (1, 2, 0), "xy": (0, 1, 2)}      # (u, v, w=plane normal)


def lock(r, k, ctx, open_dir):
    """Slot rib `r` and spine `k` into each other: the rib opens toward `open_dir`, the spine the other way."""
    cut_slots(r, k, ctx, tuple(open_dir), ctx.p["notch_ratio"])
    cut_slots(k, r, ctx, tuple(-np.asarray(open_dir)), 1 - ctx.p["notch_ratio"])


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
    def reach(ctx, eu, ev, Q, keep=slice(None)):
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

    def _branches(self, ctx, ev, ew):
        """[start, tip, direction, length, spine normal, region] per branch. The region — past the joint plane J-i,
        and on its own side of the plane between it and each neighbouring branch (radial's B-i-j) — is what the
        branch's parts own and the body's do not. The spine normal is the body spines' made square to the branch:
        a branch spine lies parallel to the body's and never crosses them."""
        out = []
        for i, seg in enumerate(ctx.p["branches"] or []):
            a, b = (np.asarray(q, float) for q in seg)
            L = float(np.linalg.norm(b - a))
            if L < 1e-6:
                ctx.errors.append(f"branch {i + 1} has no length: give it a start and a tip (they are the same point)")
                continue
            d = (b - a) / L; ns = ew - (ew @ d) * d
            ns = ns if np.linalg.norm(ns) > 0.2 else np.cross(d, ev)
            out.append([a, b, d, L, ns / np.linalg.norm(ns)])
        # one sign for every direction, as radial's axes: a leg down and an arm up would otherwise cancel in _bounds
        axes = [((a + b) / 2, d if d @ out[0][2] >= 0 else -d, L / 2, ns) for a, b, d, L, ns in out]
        bounds = Radial._bounds(ctx, axes) if len(out) > 1 else {}
        joints = [ctx.frame(f"J-{i + 1}", a, d, up_hint=ns) for i, (a, _, d, _, ns) in enumerate(out)]
        for i, (br, J) in enumerate(zip(out, joints)):          # read back from the frame: offset / tilt on J-i move it
            br.append([(J[:3, 3], J[:3, 2])] + [(M[:3, 3], M[:3, 2] * (np.sign((axes[i][0] - M[:3, 3]) @ M[:3, 2]) or 1.0))
                                                for k, M in bounds.items() if i in k])
        ctx.axes3d = [[a.tolist(), b.tolist()] for a, b, *_ in out]
        ctx.bounds3d = ([{"label": f"J-{i + 1}", "M": np.round(J, 6).tolist(), "size": round(0.6 * br[3], 1)} for i, (br, J) in enumerate(zip(out, joints))]
                        + [{"label": f"B-{i + 1}-{j + 1}", "M": np.round(M, 6).tolist(), "size": round(1.3 * min(axes[i][2], axes[j][2]) * 2, 1)}
                           for (i, j), M in bounds.items()])
        return out

    def _limbs(self, ctx, br, ribs, pitch):
        """Each branch's ribs (R2-3), square to it at the body's rib pitch, and its spine (K2) through them, with a
        tongue reaching back past the joint into the body, where it slots into the body ribs. A part keeps the one
        island nearest its branch — a plane across the front legs also cuts the other leg."""
        p = ctx.p; big = ctx.span; out = []

        def part(lab, group, M, region, near):
            sec = as_multi(section_polygons(ctx.mesh, M).intersection(region))
            if sec.is_empty:
                return []
            c = Point(to_local(M, [near])[0]); isl = min(sec.geoms, key=c.distance)
            sl = Slice(lab, group, M, ctx.thickness_of(lab), clip=as_multi(isl.buffer(0.01)))   # the clip keeps slots to it
            sl.raw = as_multi(isl)
            return [sl]
        for i, (a, b, d, L, ns, cell) in enumerate(br):
            nb = max(1, round(L / pitch)); lrs = []
            for j in range(nb):
                lab = f"R{i + 1}-{j + 1}"; c = a + d * (L * (j + 0.5) / nb)
                M = ctx.frame(lab, c, d, up_hint=ns)
                lrs += part(lab, "X", M, Radial._owned(M, cell, big), c)
            lab = f"K{i + 1}"; Mk = ctx.frame(lab, (a + b) / 2, ns, up_hint=d)
            e = np.cross(ns, d) * 1.5 * pitch; down = d * max(2 * pitch, 4 * p["thickness"])
            tongue = Polygon(to_local(Mk, [a + e + d * pitch, a - e + d * pitch, a - e - down, a + e - down]))
            others = unary_union([Radial._owned(Mk, c2, big) for *_, c2 in br if c2 is not cell])
            ks = ctx.keep(part(lab, "Y", Mk, unary_union([Radial._owned(Mk, cell, big), tongue]).difference(others), a + d * pitch))
            lrs = ctx.keep(lrs)
            for k in ks:
                for r in lrs:
                    lock(r, k, ctx, r.M[:3, 0])
                for r in ribs:                                   # body spines are parallel to it: no crossing
                    lock(r, k, ctx, d)
                if not any(x.startswith("R-") for x in k.engages):
                    ctx.errors.append(f"branch {i + 1}: its start is past the body's ribs, nothing holds it — extend the "
                                      f"curve over it, or move the start (J-{i + 1}) into the body")
            out += lrs + ks
        return out

    legend = ("R-4 = the 4th rib along the curve, counted from its start · "
              "K-1 = the 1st spine, the long part that threads through every rib and holds the spacing · "
              "R2-3 = the 3rd rib of branch 2 · K2 = branch 2's spine · J-2 = where branch 2 leaves the body")
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
        br = self._branches(ctx, ev, ew)
        sq = Polygon([(-ctx.span, -ctx.span), (ctx.span, -ctx.span), (ctx.span, ctx.span), (-ctx.span, ctx.span)])

        def clip(M):                                             # body parts stop where a branch's own begin
            owned = [g for *_, cell in br if not (g := Radial._owned(M, cell, ctx.span)).is_empty]
            return as_multi(sq.difference(unary_union(owned))) if owned else None
        W = self.across(ctx, Q[:, 0], u, eu, ew)                 # the curve's third coordinate: through the body, not the box
        ctx.curve3d = (ctx.mid + np.outer(Q[:, 0], eu) + np.outer(Q[:, 1], ev) + np.outer(W, ew)).tolist()   # for the 3D view
        ctx.curve_pts = [[float(a), float(b), float(c)] for (a, b), c in zip(pts, self.across(ctx, pts[:, 0], u, eu, ew))]
        n = p["count"] if p["distribution"] == "count" else max(1, int(s[-1] // p["spacing"]))
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
        body = ~np.any([np.all([(V - m) @ nm > 0 for m, nm in cell], axis=0) for *_, cell in br], axis=0) if br else slice(None)
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
            for r in ribs:
                for k in spines:
                    lock(r, k, ctx, r.M[:3, 0])                       # ribs open toward their in-plane normal
        return ribs + spines + self._limbs(ctx, br, ribs, s[-1] / (n + 1))
