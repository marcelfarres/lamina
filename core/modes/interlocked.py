import numpy as np
from shapely.geometry import LineString, Point
from . import Mode, Param, register
from ..model import Slice
from ..geometry import as_multi, frame, rot_about, section_polygons, to_local, to_world
from ..notch import interlock


@register
class Interlocked(Mode):
    name = "interlocked"
    title = "Interlocked Slices"
    description = "Two perpendicular families of slotted slices that lock together egg-crate style."
    legend = ("X-2 = the 2nd slice of the X family, Y-4 = the 4th of the Y family, each counted from the low end · "
              "the two families cross at right angles and half-lap into each other: X slots drop in from one side, Y from the other")
    params = [
        Param("up", "choice", "z", "Assembly axis: 1st family is inserted from +up, 2nd family from −up", choices=["x", "y", "z"]),
        Param("distribution", "choice", "count", "count = N slices per family; distance = one slice every `spacing`", choices=["count", "distance"]),
        Param("nx", "int", 5, "1st family: slice count", 1, 200, 1, show_if=("distribution", "count")),
        Param("ny", "int", 4, "2nd family: slice count", 1, 200, 1, show_if=("distribution", "count")),
        Param("spacing", "number", 30, "Slice spacing (mm)", 1, 500, 0.5, unit="mm", show_if=("distribution", "distance")),
        Param("rotate_grid", "number", 0, "Rotate the grid about the assembly axis (deg)", 0, 180, 5, unit="deg"),
        Param("extra_x", "chips", [], "Extra 1st-family slices at these positions, measured from the centre — added by the fix buttons", unit="mm"),
        Param("extra_y", "chips", [], "Extra 2nd-family slices at these positions, measured from the centre", unit="mm"),
    ]

    def axes(self, ctx):
        p = ctx.p
        up = "xyz".index(p["up"]); a1, a2 = (up + 1) % 3, (up + 2) % 3
        R = rot_about(ctx.ax[up], p["rotate_grid"])
        return up, a1, a2, R @ ctx.ax[a1], R @ ctx.ax[a2], ctx.ax[up]

    def build(self, ctx):
        p = ctx.p
        up, a1, a2, e1, e2, eu = self.axes(ctx)
        L1, L2 = ctx.ext[a1], ctx.ext[a2]
        if p["distribution"] == "distance":
            n1, n2 = max(1, int(L1 // p["spacing"])), max(1, int(L2 // p["spacing"]))
        else:
            n1, n2 = p["nx"], p["ny"]
        name1, name2 = "xyz"[a1].upper(), "xyz"[a2].upper()
        fams = []
        for name, group, e, L, n, extra in ((name1, "X", e1, L1, n1, p["extra_x"]), (name2, "Y", e2, L2, n2, p["extra_y"])):
            pos = sorted(list(ctx.positions(L, [p["thickness"]] * n)) + [float(x) for x in extra])
            labs = [f"{name}-{j + 1}" for j in range(len(pos))]
            fams.append(ctx.keep([Slice(lab, group, ctx.frame(lab, ctx.mid + e * s, e, up_hint=eu), ctx.thickness_of(lab))
                                  for lab, s in zip(labs, pos)]))
        interlock(fams[0], fams[1], ctx, a_open=tuple(eu), b_open=tuple(-eu))
        ctx.cover_r = max(L1 / max(1, n1), L2 / max(1, n2)) / 2 + p["thickness"]
        return fams[0] + fams[1]

    def crossing_fix(self, ctx, sl, point):
        """A slice of the other family through `point` would hold it."""
        up, a1, a2, e1, e2, eu = self.axes(ctx)
        other, e, key = ("2nd", e2, "extra_y") if sl.group == "X" else ("1st", e1, "extra_x")
        s = round(float(np.dot(np.asarray(point) - ctx.mid, e)), 1)
        return {"title": f"add a {other}-family slice at {s:g} mm", "set": {key: list(ctx.p[key]) + [s]}}

    def hold(self, slices, ctx):
        """Auto-fix's crossing slices for the groups nothing joins to the rest. A slice through the middle of a loose
        region holds that region, but on a tube or a torus it holds it to nothing: the new slice's own section there
        is just as loose, and the region used to be deleted — 70 to 80 % of the tube. So each loose group gets the
        position, across its regions, whose section reaches from the group into the main assembly (or failing that
        into another loose group, which a later one can then carry): the cut is checked, not assumed. Nothing found:
        the slice through the region's middle, as before. Returns the parameter changes, one per group."""
        up, a1, a2, e1, e2, eu = self.axes(ctx)
        t, mid = ctx.p["thickness"], ctx.mid
        # A new slice keeps a full wall from every slice of its family: their slots in each crossing slice are the
        # material plus the slot offset wide, and need `min_feature` of material between them. 1 mm over the
        # thickness left the cow's added slices 4.5 mm apart, 1.3 mm of wall between their slots.
        apart = t + ctx.p["slot_offset"] + ctx.p["min_feature"]
        xy = [s for s in slices if s.group in ("X", "Y")]
        by = {s.label: s for s in xy}
        loose = {}                                       # (slice, region) → its group's key
        for sl in xy:
            for e in sl.errors:
                if "floats" in e or "no crossing" in e or "not connected" in e:
                    key = e.split("separate group: ")[1].split(")")[0] if "separate group" in e else sl.label
                    for r in [int(e.split()[1]) - 1] if e.startswith("region") else range(len(sl.profile.geoms)):
                        loose[(sl.label, r)] = key
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        taken = {"X": [], "Y": []}                       # where each family already has a slice, along its own normal
        for s in xy:
            taken[s.group].append(float((s.M[:3, 3] - mid) @ (e1 if s.group == "X" else e2)))
        groups = {}
        for lr, key in loose.items():
            groups.setdefault(key, []).append(lr)
        area = lambda lr: by[lr[0]].profile.geoms[lr[1]].area        # noqa: E731
        sets = []
        for key, regs in sorted(groups.items(), key=lambda kv: -sum(map(area, kv[1]))):
            if find(key) == find("MAIN"):
                continue
            best = None
            for lb, r in sorted(regs, key=area, reverse=True):
                sl = by[lb]; reg = sl.profile.geoms[r]
                new, e, k = ("Y", e2, "extra_y") if sl.group == "X" else ("X", e1, "extra_x")
                span = (to_world(sl.M, np.asarray(reg.exterior.coords)[:, :2]) - mid) @ e
                rp = reg.representative_point(); s0 = float((to_world(sl.M, [(rp.x, rp.y)])[0] - mid) @ e)
                lo, hi = span.min() + t / 2, span.max() - t / 2
                cands = np.linspace(lo, hi, max(2, min(40, int((hi - lo) / max(0.5, t / 2)) + 1))) if hi > lo else [s0]
                for s in sorted(cands, key=lambda s: abs(s - s0)):
                    if any(abs(s - q) < apart for q in taken[new]):
                        continue
                    score = self._joins(ctx, [x for x in xy if x.group == sl.group], (lb, r), e, float(s), eu, loose, find)
                    if score and (best is None or score[0] > best[0]):
                        best = (*score, float(s), k, new)
                    if score and score[0] == 2:
                        break
                if best and best[0] == 2:
                    break
            if best:
                score, joined, s, k, new = best
                for j in joined:
                    parent[find(j)] = find("MAIN") if score == 2 else find(next(iter(joined)))
            else:                                        # nothing reaches the rest: hold the region where it is
                lb, r = regs[0]; sl = by[lb]; rp = sl.profile.geoms[r].representative_point()
                new, k = ("Y", "extra_y") if sl.group == "X" else ("X", "extra_x")
                s = float((to_world(sl.M, [(rp.x, rp.y)])[0] - mid) @ (e2 if new == "Y" else e1))
                if any(abs(s - q) < apart for q in taken[new]):
                    continue
            taken[new].append(s)
            sets.append({k: list(ctx.p[k]) + [round(s, 1)]})
        return sets

    @staticmethod
    def _joins(ctx, fam, region, e, s, eu, loose, find):
        """A new slice of the other family at `s` along `e`: which groups its section would join through `region` —
        (2, groups) when the main assembly is among them, (1, groups) for two loose groups, None otherwise. Where the
        new plane crosses each slice of the region's family it notches a strip of that slice's material; the strips
        lying on one piece of the new section are joined by it."""
        mid = ctx.mid; M = frame(mid + e * s, e, up_hint=eu)
        hits = []                                        # (slice, region, world point of the crossing strip)
        for T in fam:
            a, b = e @ T.M[:3, 0], e @ T.M[:3, 1]; n2 = a * a + b * b
            if n2 < 1e-9:
                continue
            c = s - (T.M[:3, 3] - mid) @ e; p0 = np.array([a, b]) * c / n2; d = np.array([-b, a]) / np.sqrt(n2)
            line = LineString([p0 - d * 1e4, p0 + d * 1e4])
            for j, g in enumerate(T.profile.geoms):
                for part in getattr(line.intersection(g), "geoms", [line.intersection(g)]):
                    if part.length > 0.3:
                        q = part.interpolate(0.5, normalized=True)
                        hits.append((T.label, j, to_world(T.M, [(q.x, q.y)])[0]))
        if not any((h[0], h[1]) == region for h in hits):
            return None
        polys = list(as_multi(section_polygons(ctx.mesh, M)).geoms)
        on = lambda w: next((i for i, q in enumerate(polys) if q.distance(Point(to_local(M, [w])[0][:2])) < 0.5), None)  # noqa: E731
        piece = [on(h[2]) for h in hits]
        mine = {piece[i] for i, h in enumerate(hits) if (h[0], h[1]) == region} - {None}
        joined = {find(loose.get((h[0], h[1]), "MAIN")) for i, h in enumerate(hits) if piece[i] in mine}
        if find("MAIN") in joined:
            return 2, joined
        return (1, joined) if len(joined) > 1 else None
