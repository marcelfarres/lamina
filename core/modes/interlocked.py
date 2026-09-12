import numpy as np
from . import Mode, Param, register
from ..model import Slice
from ..geometry import rot_about
from ..notch import interlock


@register
class Interlocked(Mode):
    name = "interlocked"
    title = "Interlocked Slices"
    description = "Two perpendicular families of slotted slices that lock together egg-crate style."
    params = [
        Param("up", "choice", "z", "Assembly axis: 1st family is inserted from +up, 2nd family from −up", choices=["x", "y", "z"]),
        Param("distribution", "choice", "count", "count = N slices per family; distance = one slice every `spacing` mm", choices=["count", "distance"]),
        Param("nx", "int", 5, "1st family: slice count", 1, 200, 1, show_if=("distribution", "count")),
        Param("ny", "int", 4, "2nd family: slice count", 1, 200, 1, show_if=("distribution", "count")),
        Param("spacing", "number", 30, "Slice spacing (mm)", 1, 500, 0.5, unit="mm", show_if=("distribution", "distance")),
        Param("rotate_grid", "number", 0, "Rotate the grid about the assembly axis (deg)", 0, 180, 5, unit="deg"),
        Param("extra_x", "chips", [], "Extra 1st-family slices at these positions (mm from the centre) — added by the fix buttons", unit="mm"),
        Param("extra_y", "chips", [], "Extra 2nd-family slices at these positions (mm from the centre)", unit="mm"),
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
