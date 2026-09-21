"""Test model set: geometric + organic shapes, each chosen to stress something.

    python -m core.testmodels examples/

geometric: cube, cylinder, cone, pyramid, sphere, torus, bracket (L + hole), tube (hollow), tall_bar (needs splitting)
organic:   egg, snowman (asymmetric), blob (metaball, bumpy), pear, twisted (twisted ellipsoid), bowl (thin shell),
           dumbbell (two spheres on a neck: radial with an axis per lobe)
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
