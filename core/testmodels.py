"""Test model set: geometric + organic shapes, each chosen to stress something.

    python -m core.testmodels examples/

geometric: cube, cylinder, cone, pyramid, sphere, torus, bracket (L + hole), tube (hollow), tall_bar (needs splitting)
organic:   egg, snowman (asymmetric), blob (metaball, bumpy), pear, twisted (twisted ellipsoid), bowl (thin shell),
           dumbbell (two spheres on a neck: radial with an axis per lobe), wavy_torus (ring with a 3-period sine wave and an LED channel through it)
"""
import sys, pathlib
import numpy as np
import trimesh
from trimesh.creation import icosphere, torus, box, cylinder, cone


def rot(m, deg, axis):
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(deg), axis)); return m


def union(*ms): return trimesh.boolean.union(list(ms))
def diff(a, *bs): return trimesh.boolean.difference([a, *bs])


def blob():
    """Metaball: sum of gaussians, marching cubes → smooth bumpy organic solid."""
    from skimage import measure
    n = 64; lin = np.linspace(-1.3, 1.3, n)
    X, Y, Z = np.meshgrid(lin, lin, lin, indexing="ij")
    centers = [(0, 0, 0, 0.6), (0.6, 0.2, 0.3, 0.45), (-0.5, 0.4, -0.2, 0.4), (0.1, -0.6, 0.4, 0.35), (-0.2, -0.1, 0.7, 0.3)]
    F = sum(np.exp(-((X - cx) ** 2 + (Y - cy) ** 2 + (Z - cz) ** 2) / r ** 2) for cx, cy, cz, r in centers)
    verts, faces, _, _ = measure.marching_cubes(F, 0.5, spacing=(lin[1] - lin[0],) * 3)
    m = trimesh.Trimesh(verts, faces); m.apply_scale(45); trimesh.repair.fix_normals(m)
    return m


def pear():
    a = icosphere(4, 26); b = icosphere(4, 18); b.apply_translation([0, 0, 30]); b.apply_scale([1, 1, 1.25])
    return union(a, b)


def twisted():
    m = icosphere(5, 30); m.apply_scale([1.4, 0.7, 1.0])
    v = m.vertices.copy(); ang = v[:, 2] / 30 * np.radians(40)
    x = v[:, 0] * np.cos(ang) - v[:, 1] * np.sin(ang); y = v[:, 0] * np.sin(ang) + v[:, 1] * np.cos(ang)
    m.vertices = np.c_[x, y, v[:, 2]]; return m


def bowl():
    outer = icosphere(4, 40); inner = icosphere(4, 34); inner.apply_translation([0, 0, 6])
    cut = box([100, 100, 50]); cut.apply_translation([0, 0, 35])
    return diff(outer, inner, cut)


def dumbbell():
    """Two spheres on a neck: the case for radial with an axis per lobe — a fan each, the neck is where the bands
    meet, and a spine through both axes holds one ball to the other."""
    return union(icosphere(4, 24).apply_translation([0, 0, -36]), icosphere(4, 24).apply_translation([0, 0, 36]),
                 cylinder(radius=10, height=72, sections=64))


def wavy_torus(size=316, led_d=7):
    """A torus whose ring rises and falls: three peaks and three valleys of a sine wave around it, `size` mm across
    (a Bambu H2C's 325 × 320 bed less its preset's 2 mm sheet margins, so the widest stacked slice prints flat in one piece),
    with a closed channel of `led_d` mm along the tube's centre for an LED light tube. The wave shears the channel, so
    at its steepest it is 12 % narrower across than tall: 7 mm still passes a 5 mm tube everywhere. Built in mm, then
    ÷ 3 for the ×3 every model gets below."""
    R = size * 3 / 8
    def wave(m):
        v = m.vertices.copy(); v[:, 2] += size / 15 * np.sin(3 * np.arctan2(v[:, 1], v[:, 0]))
        m.vertices = v; return m
    outer = wave(torus(major_radius=R, minor_radius=R / 3, major_sections=144, minor_sections=48))
    channel = wave(torus(major_radius=R, minor_radius=led_d / 2, major_sections=144, minor_sections=24))
    channel.invert()                          # inward-facing: a void inside the solid, no boolean needed
    return trimesh.util.concatenate([outer, channel]).apply_scale(1 / 3)


def vase():
    """A vase for the stacked spacing curve: a foot, a belly and a neck that flares at the lip — the radius changes
    fast at the foot, the shoulder and the lip and hardly at all on the belly, so even slices waste layers on the belly
    and miss the curves. Revolved from a profile; 54 mm tall before the ×3."""
    z = np.linspace(0, 54, 60)
    r = 10 + 12 * np.exp(-((z - 20) / 11) ** 2) + 3 * np.exp(-((z - 54) / 4) ** 2) + 2 * np.exp(-(z / 3) ** 2)   # belly, lip, foot
    r[0] = 8
    profile = np.c_[np.r_[0, r, 0], np.r_[z[0], z, z[-1]]]
    m = trimesh.creation.revolve(profile, sections=96)
    return m.apply_translation([0, 0, -27])


def ripple():
    """A block whose top is a ripple that tightens from one end to the other, for the interlocked spacing curves:
    the first family needs close slices where the ripple is tight and few where it is slow, and the second family
    runs along the ripple, where even spacing is right — one curve per family. 70 × 40 × 20 before the ×3."""
    from shapely.geometry import Polygon
    x = np.linspace(-35, 35, 141)
    top = 14 + 5 * np.sin(0.09 * (x + 35) ** 1.45)                     # the chirp: slow on the left, tight on the right
    poly = Polygon([(-35, 0), (35, 0)] + [(float(a), float(b)) for a, b in zip(x[::-1], top[::-1])])
    m = trimesh.creation.extrude_polygon(poly, 40)                     # extruded along z; stood up so the ripple runs along x
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return m.apply_translation([0, 20, -7])


def berry():
    """A ball with a cluster of bumps on one side, for the radial spacing curve: the fan's planes should crowd the
    bumpy side and spread on the smooth one — the curve round the axis, closing on itself."""
    parts = [icosphere(4, 24)]
    for a, el in ((0, 0.25), (0.5, -0.2), (-0.55, 0.05), (0.2, 0.7), (-0.15, -0.6)):
        q = np.array([np.cos(a) * np.cos(el), np.sin(a) * np.cos(el), np.sin(el)]) * 23
        parts.append(icosphere(3, 8).apply_translation(q))
    return union(*parts)


def hook():
    """A tube that runs straight, bends through a right angle and runs on, for the curve technique's spacing curve:
    ribs close together round the bend and far apart on the straights. A circle swept along the path, in the x–z
    plane: 40 mm in along x, a quarter turn of 26 mm radius, 40 mm up along z."""
    from shapely.geometry import Point
    R = 26
    arc = [(R * np.sin(a), 0, R - R * np.cos(a)) for a in np.linspace(0, np.pi / 2, 25)]
    path = np.array([(-40, 0, 0)] + arc + [(R, 0, R + 40)])
    return trimesh.creation.sweep_polygon(Point(0, 0).buffer(9, 32), path, cap=True)


def droplet():
    """A drop falling into still water, for the plaque's radial layout: rings that fade outward on a disc, and one
    column rising from the middle with a bulb on top — all one body, nothing in the air. A profile turned about z;
    the column is thick enough to stand outside the hole a radial fan leaves in its middle. 100 across before the ×3."""
    R, rn, rb = 50.0, 7.5, 10.0                         # the disc, the column's neck, the bulb
    r = np.linspace(R, rn, 260)
    z = 7 + 5.5 * np.cos(2 * np.pi * (r - rn) / 11.5) * np.exp(-(r - rn) / 38) + 30 * np.exp(-(r - rn) / 2.6)
    top = float(z[-1]); cz = top + np.sqrt(rb ** 2 - rn ** 2)   # the bulb: a ball sitting on the neck
    arc = [(rb * np.sin(a), cz - rb * np.cos(a)) for a in np.linspace(np.arcsin(rn / rb), np.pi, 40)]
    prof = [(0.0, 0.0), (R, 0.0)] + [(float(a), float(b)) for a, b in zip(r, z)] + arc[1:-1] + [(0.0, cz + rb)]
    return trimesh.creation.revolve(np.array(prof), sections=120)


def bonsai():
    """A bonsai in its pot, for the plaque: a trunk that leans one way and back, thinning as it climbs, two branches,
    and flat pads of foliage at their ends. Stands along z with its back to −y; cut at half its depth it is a relief
    of the tree on its plate. The trunk and branches are balls strung along a curve, each a little smaller."""
    from scipy.interpolate import CubicSpline

    def limb(pts, r0, r1, n):
        pts = np.array(pts, float); t = np.linspace(0, 1, len(pts))
        return [icosphere(2, r).apply_translation(c) for c, r in zip(CubicSpline(t, pts)(np.linspace(0, 1, n)), np.linspace(r0, r1, n))]

    pad = lambda c, size: icosphere(3, 1).apply_scale(size).apply_translation(c)   # noqa: E731
    pot = [box([44, 16, 8]).apply_translation([0, 0, 4]), box([48, 18, 3]).apply_translation([0, 0, 8.5])]
    trunk = limb([(-5, 0, 9), (-10, 0, 19), (-2, 0, 28), (8, 0, 35), (6, 0, 45), (-2, 0, 53)], 5.5, 2.2, 46)
    right = limb([(4, 0, 31), (13, 0, 31), (22, 0, 35)], 2.6, 1.6, 16)
    left = limb([(7, 0, 41), (-4, 0, 41), (-15, 0, 44)], 2.4, 1.6, 18)
    pads = [pad((-3, 0, 57), (15, 7.5, 6)), pad((25, 0, 38), (12, 7, 5)), pad((-19, 0, 47), (11, 7, 4.5)), pad((12, 0, 50), (8, 6, 4))]
    return union(*pot, *trunk, *right, *left, *pads)


MODELS = {
    # geometric
    "cube": lambda: box([60, 60, 60]),
    "cylinder": lambda: cylinder(radius=30, height=70, sections=96),
    "cone": lambda: cone(radius=35, height=70, sections=96),
    "pyramid": lambda: cone(radius=40, height=60, sections=4),
    "sphere": lambda: icosphere(4, 30),
    "torus": lambda: torus(major_radius=30, minor_radius=10, major_sections=96, minor_sections=48),
    "bracket": lambda: diff(union(box([80, 60, 12]), box([16, 60, 60]).apply_translation([-32, 0, 36])), cylinder(radius=10, height=20).apply_translation([15, 0, 0])),
    "tube": lambda: diff(cylinder(radius=30, height=80, sections=96), cylinder(radius=24, height=90, sections=96)),
    "tall_bar": lambda: rot(box([40, 30, 220]), 10, [0, 1, 0]),
    # organic
    "egg": lambda: icosphere(4, 25).apply_scale([1.2, 0.8, 1.0]),
    "snowman": lambda: union(icosphere(4, 30), icosphere(4, 22).apply_translation([6, 0, 40]), icosphere(4, 14).apply_translation([12, 4, 70])),
    "blob": blob,
    "pear": pear,
    "twisted": twisted,
    "bowl": bowl,
    "dumbbell": dumbbell,
    "wavy_torus": wavy_torus,
    # for the drawn spacing curve, one per technique
    "vase": vase,
    "ripple": ripple,
    "berry": berry,
    "hook": hook,
    # for the plaque
    "droplet": droplet,
    "bonsai": bonsai,
}

if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "examples"); out.mkdir(exist_ok=True)
    for name, fn in MODELS.items():
        m = fn()
        m.apply_scale(3)                      # ~150–200 mm objects: realistic for card / cardboard / sheet metal
        if not m.is_watertight:
            trimesh.repair.fill_holes(m)
        m.export(out / f"{name}.stl")
        print(f"{name:9s} bbox {np.round(m.extents, 1)} watertight={m.is_watertight} faces={len(m.faces)}")
