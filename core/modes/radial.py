"""Radial: half-slices fanning out from a central axis, locked by horizontal ring slices (full sections) with
radial slots. Assembly: stack the rings on a pole or jig, then slide each half-slice in from the outside."""
import math
import numpy as np
from shapely.geometry import Polygon
from . import Mode, Param, register
from ..model import Slice
from ..geometry import rot_about, as_multi, circle
from ..notch import cut_slots


@register
class Radial(Mode):
    name = "radial"
    title = "Radial Slices"
    description = ("Half-slices radiating from an axis (move it with `center`, turn the fan with `angle`), held by horizontal ring "
                   "slices with radial slots. Ring count / spacing and every slice position are yours to set.")
    params = [
        Param("axis", "choice", "z", "Central axis", choices=["x", "y", "z"]),
        Param("count", "int", 6, "Radial planes through the axis (gives 2 × count half-slices)", 1, 90, 1),
        Param("angle", "number", 0, "Turn the whole fan about the axis (deg): where the first radial plane starts. The pattern repeats every 180 / count degrees", -90, 90, 1, unit="deg"),
        Param("core_d", "number", 0, "Central clearance: half-slices stop at this diameter (mm). 0 = automatic minimum so 2 × count slices fit around the axis; smaller than the minimum = collision error", 0, 300, 1, unit="mm"),
        Param("rings", "choice", "count", "Ring slices along the axis: count = N evenly spread, distance = one every `ring_spacing`", choices=["count", "distance"]),
        Param("ring_count", "int", 4, "Number of ring slices", 1, 200, 1, show_if=("rings", "count")),
        Param("ring_spacing", "number", 40, "Ring spacing along the axis (mm)", 2, 1000, 1, unit="mm", show_if=("rings", "distance")),
        Param("hole_d", "number", 0, "Hole in the middle of every ring for a pole / dowel (mm); 0 = none", 0, 100, 0.5, unit="mm"),
    ]
    hidden_common = ("notch_ratio",)

    def build(self, ctx):
        p = ctx.p
        ax = "xyz".index(p["axis"]); eu = ctx.ax[ax]; e1 = ctx.ax[(ax + 1) % 3]
        t = p["thickness"]; n = p["count"]; big = ctx.span
        need = 2 * (n * (t + p["slot_offset"]) / math.pi + t)                    # 2n slices of thickness t around the circumference
        core_r = (p["core_d"] or need) / 2
        ctx.core_d_min = need
        if p["core_d"] and p["core_d"] < need - 1e-6:
            ctx.errors.append(f"core_d = {p['core_d']:g} mm is too small: {2 * n} half-slices of {t:g} mm collide at the axis — core_d must be ≥ {need:.0f} mm (or fewer radial planes, or thinner material)")
        if p["hole_d"] and p["hole_d"] > 2 * core_r - 2 * p["min_feature"]:
            ctx.errors.append(f"hole_d = {p['hole_d']:g} mm leaves no wall between the ring hole and the slots — must be ≤ {2 * core_r - 2 * p['min_feature']:.0f} mm")
        # half-slices
        halves = []
        for k in range(n):
            ang = p["angle"] + 180.0 * k / n
            radial = rot_about(eu, ang) @ e1                  # in-plane radial direction
            nrm = np.cross(eu, radial)                         # plane contains the axis and the radial dir
            for half, sgn in (("a", 1), ("b", -1)):
                lab = f"R-{k + 1}{half}"
                M = ctx.frame(lab, ctx.mid, nrm, up_hint=eu)   # local x = ±radial, local y = axis
                sl = Slice(lab, "R", M, ctx.thickness_of(lab))
                sx = np.sign(np.dot(M[:3, 0], radial)) * sgn   # which local-x side is this half
                sl.clip = as_multi(Polygon([(sx * core_r, -big), (sx * big, -big), (sx * big, big), (sx * core_r, big)]))
                sl.radial = sgn * radial
                halves.append(sl)
        halves = ctx.keep(halves)
        # ring slices
        L = ctx.ext[ax]
        nr = p["ring_count"] if p["rings"] == "count" else max(1, int(L // p["ring_spacing"]))
        labs = [f"Z-{i + 1}" for i in range(nr)]; th = [ctx.thickness_of(l) for l in labs]
        rings = []
        for lab, z, tk in zip(labs, ctx.positions(L, th), th):
            sl = Slice(lab, "C", ctx.frame(lab, ctx.mid + eu * z, eu, up_hint=e1), tk)
            if p["hole_d"] > 0:
                sl.cuts.append(circle((0, 0), p["hole_d"]))
            rings.append(sl)
        rings = ctx.keep(rings)
        # slots: half-slice takes `notch_ratio` from the axis side, ring the rest from the outside
        r = p["notch_ratio"]
        for h in halves:
            for ring in rings:
                cut_slots(h, ring, ctx, tuple(-h.radial), r)
                cut_slots(ring, h, ctx, tuple(h.radial), 1 - r)
        if not rings:
            ctx.errors.append("no ring slices — nothing holds the half-slices")
        ctx.cover_r = max(L / max(1, nr) / 2, math.pi * max(ctx.ext) / (4 * n)) + t
        return halves + rings

    def crossing_fix(self, ctx, sl, point):
        if sl.group != "R":
            return None
        ax = "xyz".index(ctx.p["axis"]); z = float(np.dot(np.asarray(point) - ctx.mid, ctx.ax[ax]))
        return {"title": f"add a ring slice at {ctx.p['axis']} = {z:.0f} mm", "set": {"ring_count": ctx.p["ring_count"] + 1}, "note": "rings are spread evenly; for an exact position use offset on the nearest ring"}
