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


def fold_test():
    """A small box to print flat and fold (folded panels, printed): an L with one corner cut off and a sloping lid, so
    one net carries 90° and 45° mountain folds, a 90° valley fold and seams at odd angles. 48 × 48 × 32 mm as exported."""
    from shapely.geometry import Polygon
    m = trimesh.creation.extrude_polygon(Polygon([(0, 0), (48, 0), (48, 24), (24, 24), (24, 48), (12, 48), (0, 36)]), 20)
    v = m.vertices.copy(); top = v[:, 2] > 10; v[top, 2] += 0.25 * v[top, 0]
    return trimesh.Trimesh(v / 3, m.faces)                # the export scales every model × 3


def fold_lamp(rings=6, around=6, height=120.0):
    """A lamp shade to print flat and fold (folded panels, printed, with `window`): an open tube of triangles whose
    radius swells and narrows like the blob in a lava lamp, each ring half a step round from the one below and the
    whole given a twist, so no two folds line up. Open at both ends; about 80 mm across and 120 mm tall as exported."""
    def ring(i):
        u = i / rings; z = height * u
        a = 2 * np.pi * (np.arange(around) + 0.5 * i) / around + 0.5 * np.sin(2.2 * u * np.pi)
        r = 30 + 14 * np.sin(np.pi * (1.35 * u + 0.1)) ** 2 + 5 * np.sin(3 * a + 4 * u) * np.sin(np.pi * u) - 9 * u * u
        return np.c_[r * np.cos(a), r * np.sin(a), np.full(around, z)]
    v = np.vstack([ring(i) for i in range(rings + 1)])
    faces = []
    for i in range(rings):
        for j in range(around):
            a, b = i * around + j, i * around + (j + 1) % around
            c, d = (i + 1) * around + j, (i + 1) * around + (j + 1) % around      # ring i + 1 sits half a step on
            faces += [(a, b, c), (b, d, c)]
    return trimesh.Trimesh(v / 3, faces, process=False)   # the export scales every model × 3


def droplet():
    """Rings on still water after a drop, for the plaque's radial layout: long, soft waves that fade a little toward
    the rim and sink smoothly to almost nothing at it, on a disc. A profile turned about z. Nothing stands in the middle: a radial fan leaves a hole there, and
    a thin column would be cut to slivers. 100 across before the ×3."""
    R = 50.0
    r = np.linspace(R, 0, 400)
    fade = np.clip((R - r) / 16, 0, 1); fade = fade * fade * (3 - 2 * fade)      # the last third of a wave sinks into the plate
    z = 1.0 + fade * (6 + 4.2 * np.cos(2 * np.pi * r / 14) * np.exp(-r / 90))
    prof = [(0.0, 0.0), (R, 0.0)] + [(float(a), float(b)) for a, b in zip(r, z)]
    return trimesh.creation.revolve(np.array(prof), sections=144)


def bonsai():
    """A bonsai in its pot, for the plaque: a gnarled trunk that leans one way and back, thinning as it climbs, roots
    that grip the soil, three branches, and clouds of foliage at their ends. Stands along z with its back to −y; cut
    at half its depth it is a relief of the tree on its plate. Trunk and branches are balls strung along a curve,
    each cloud is a handful of flattened balls: no two alike, and the same tree every time (a fixed seed)."""
    from scipy.interpolate import CubicSpline
    rng = np.random.default_rng(11)

    def limb(pts, r0, r1, n, knots=0.14):
        pts = np.array(pts, float)
        path = CubicSpline(np.linspace(0, 1, len(pts)), pts)(np.linspace(0, 1, n))
        path[1:-1, 0] += rng.normal(0, 0.35, n - 2)                     # bark: the line wanders, the girth swells and thins
        rad = np.linspace(r0, r1, n) * (1 + knots * np.sin(np.linspace(0, 9, n) + rng.uniform(0, 6)) + rng.normal(0, 0.04, n))
        return [icosphere(2, float(r)).apply_translation(c) for c, r in zip(path, rad)]

    def cloud(c, size, n):
        size = np.array(size, float); out = [icosphere(3, 1).apply_scale(size * 0.62).apply_translation(c)]   # a core holds it together
        for _ in range(n):
            d = rng.normal(size=3); d = d / np.linalg.norm(d) * rng.uniform(0.25, 0.8)
            d[2] = abs(d[2]) * 0.9 - 0.15                               # flat underneath, heaped on top
            k = rng.uniform(0.34, 0.56) * size[0]
            out.append(icosphere(2, 1).apply_scale([k, k * 0.85, k * rng.uniform(0.5, 0.75)]).apply_translation(np.array(c) + d * size))
        return out

    pot = trimesh.creation.revolve(np.array([(0, 0), (11.5, 0), (12.5, 1), (15.5, 7.5), (16.6, 8), (16.6, 9.6), (0, 9.6)]), sections=64).apply_scale([1.5, 0.56, 1])
    soil = icosphere(3, 1).apply_scale([21, 7.5, 2.6]).apply_translation([0, 0, 9.4])
    trunk = limb([(-6, 0, 10), (-11, 0, 19), (-3, 0, 27), (8, 0, 33), (7, 0, 43), (-1, 0, 50), (-3, 0, 55)], 6.0, 2.0, 54)
    roots = [b for end in [(-17, 0, 10.5), (3, 0, 10.5), (-10, 2, 10.2)] for b in limb([(-7, 0, 13), end], 3.2, 1.3, 9, 0.05)]
    limbs = limb([(4, 0, 30), (13, 0, 30), (21, 0, 34), (26, 0, 34)], 2.8, 1.5, 22) + limb([(7, 0, 40), (-4, 0, 40), (-13, 0, 44), (-18, 0, 44)], 2.6, 1.5, 22) \
        + limb([(4, 0, 46), (10, 0, 48), (14, 0, 51)], 2.0, 1.3, 12)
    leaves = cloud((-3, 0, 58), (14, 7.5, 6.5), 11) + cloud((27, 0, 37), (12, 7, 5.5), 9) + cloud((-20, 0, 47), (11.5, 7, 5), 9) + cloud((15, 0, 53), (8, 6, 4.2), 6)
    return union(pot, soil, *trunk, *roots, *limbs, *leaves)


def figure():
    """A dancer made of smooth blobs, for the plaque's crossed layout: a head that floats above the shoulders, a
    body that leans, one arm up and one flung out, one leg standing and one drawn up. Stands along z with its back
    to −y; cut at half its depth every blob stands on the plate, so nothing needs to touch."""
    from scipy.interpolate import CubicSpline

    def limb(pts, r0, r1, n=28):
        path = CubicSpline(np.linspace(0, 1, len(pts)), np.array(pts, float))(np.linspace(0, 1, n))
        return [icosphere(2, float(r)).apply_translation(c) for c, r in zip(path, np.linspace(r0, r1, n))]

    head = icosphere(3, 10.5).apply_translation([5, 0, 97])
    body = limb([(3, 0, 68), (0, 0, 56), (-4, 0, 42)], 13.5, 11.0)
    stand = limb([(-8, 0, 40), (-12, 0, 22), (-7, 0, 5)], 9.0, 5.5)
    drawn = limb([(0, 0, 40), (19, 0, 32), (7, 0, 17)], 8.5, 5.5)
    up = limb([(10, 0, 66), (25, 0, 76), (29, 0, 96)], 6.5, 4.8)
    out = limb([(-6, 0, 65), (-24, 0, 59), (-33, 0, 76)], 6.5, 4.8)
    return trimesh.util.concatenate([head, union(*body, *stand, *drawn, *up, *out)]).apply_scale([1, 1, 1])


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
    # printed and folded: a groove at every fold
    "fold_test": fold_test,
    "fold_lamp": fold_lamp,
    # for the plaque
    "droplet": droplet,
    "bonsai": bonsai,
    "figure": figure,
}

if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "examples"); out.mkdir(exist_ok=True)
    for name, fn in MODELS.items():
        m = fn()
        m.apply_scale(3)                      # ~150–200 mm objects: realistic for card / cardboard / sheet metal
        if not m.is_watertight and name != "fold_lamp":        # the lamp is an open shade: its two ends stay open
            trimesh.repair.fill_holes(m)
        m.export(out / f"{name}.stl")
        print(f"{name:9s} bbox {np.round(m.extents, 1)} watertight={m.is_watertight} faces={len(m.faces)}")
