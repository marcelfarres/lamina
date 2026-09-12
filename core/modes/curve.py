"""Curve: ribs perpendicular to a user curve (boat hull / fuselage construction), interlocked with spine slices
that lie in the curve's plane."""
import math
import numpy as np
from . import Mode, Param, register
from ..model import Slice
from ..notch import cut_slots

PLANES = {"xz": (0, 2, 1), "yz": (1, 2, 0), "xy": (0, 1, 2)}      # (u, v, w=plane normal)


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
                   "lock the ribs together.")

    def crossing_fix(self, ctx, sl, point):
        """A rib region nothing holds needs another spine through it; a spine region needs another rib."""
        if sl.group == "X":
            return {"title": f"add a spine ({ctx.p['spines'] + 1} in total)", "set": {"spines": ctx.p["spines"] + 1}}
        return {"title": f"add a rib ({ctx.p['count'] + 1} in total)", "set": {"count": ctx.p["count"] + 1, "distribution": "count"}}

    @staticmethod
    def reach(ctx, eu, ev, Q):
        """How far the material reaches from the curve, measured in the curve's plane — two rib planes meet along a
        line at some distance from the curve, and that line must stay outside the model. Sampled, not exact."""
        V = ctx.mesh.vertices
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
        return pts if len(pts) >= 2 else [[-L / 2 + ctx.p["margin"], 0], [L / 2 - ctx.p["margin"], 0]]

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
    params = [
        Param("plane", "choice", "xz", "Plane that contains the curve (first letter = along, second = up)", choices=["xz", "yz", "xy"]),
        Param("curve", "list", [], "Control points [[u,v],...] in the plane (mm, model centred at 0); empty = straight line through the middle along the plane's first axis", unit="mm"),
        Param("distribution", "choice", "count", "count = N ribs; distance = one rib every `spacing` mm of curve length", choices=["count", "distance"]),
        Param("count", "int", 8, "Rib count", 1, 300, 1),
        Param("spacing", "number", 20, "Rib spacing along the curve (mm)", 1, 500, 0.5, unit="mm"),
        Param("spines", "int", 1, "Spine slices in the curve plane (0 = ribs only, glue/wire them yourself)", 0, 20, 1),
    ]

    def build(self, ctx):
        p = ctx.p
        u, v, w = PLANES[p["plane"]]; eu, ev, ew = ctx.ax[u], ctx.ax[v], ctx.ax[w]
        pts = np.array([[float(q[0]), float(q[1])] for q in (p["curve"] or self.default_curve(ctx, u, v, eu, ev))])   # in-plane; the UI may hand back the w it was shown
        Q, s = resample(pts)
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
        reach = 2 * (self.reach(ctx, eu, ev, Q) + p["thickness"])
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
            ribs.append(Slice(lab, "X", M, ctx.thickness_of(lab)))
        ribs = ctx.keep(ribs)
        ctx.cover_r = s[-1] / (2 * max(1, n)) + p["thickness"]
        spines = []
        if p["spines"]:
            labs = [f"K-{k + 1}" for k in range(p["spines"])]; th = [ctx.thickness_of(l) for l in labs]
            w_mid = float(W.mean())                                  # spines spread around the body's centre, not the box's
            for lab, off, tk in zip(labs, ctx.positions(ctx.ext[w], th), th):
                M = ctx.frame(lab, ctx.mid + ew * (off + w_mid), ew, up_hint=ev)
                spines.append(Slice(lab, "Y", M, tk))
            spines = ctx.keep(spines)
            for r in ribs:
                open_dir = tuple(r.M[:3, 0])                          # ribs open toward their in-plane normal, spines the other way
                for k in spines:
                    cut_slots(r, k, ctx, open_dir, p["notch_ratio"])
                    cut_slots(k, r, ctx, tuple(-r.M[:3, 0]), 1 - p["notch_ratio"])
        return ribs + spines
