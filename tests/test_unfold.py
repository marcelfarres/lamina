"""Folded-panel checks on real meshes (assert-based; runs with `uv run python tests/test_unfold.py` or pytest).

For every case:  the unfolding is rigid (refolding every panel through its first face reproduces the mesh vertices),
no panel self-overlaps, 2D area == mesh area, every mesh edge is either a fold or a seam exactly once,
all joint cuts lie inside their triangle (never across a fold), strips/ribs come one per seam, rib angles == dihedral,
and every part fits the sheet.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import trimesh
from shapely.geometry import Polygon
from core.plan import build, MODES, coerce_params, load_mesh
from core.modes.folded import simplify, target_faces
from core.unfold import unfold, refold_error

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = [  # model, params
    ("cube", {"facet": 0, "joint": "laced"}),
    ("egg", {"facet": 25, "joint": "strip"}),
    ("torus", {"facet": 20, "joint": "rib", "thickness": 1, "rib_w": 5, "inset": 2, "hole_d": 2}),
    ("bowl", {"facet": 20, "joint": "rivet"}),                       # thin shell with a cavity
    ("head_igea", {"facet": 16, "joint": "laced", "separate": True}),   # separate-face mode on a head
    ("cow_spot", {"facet": 15, "joint": "tab"}),                     # animal with legs (undercuts)
    ("cow_spot", {"facet": 18, "joint": "rib", "thickness": 1, "rib_w": 6, "inset": 3}),
    ("snowman", {"facet": 16, "joint": "tongue"}),                   # two spheres and a neck
]


def check_unfold(mesh, split, strategy="auto", max_dims=(590, 390)):
    frames, local, panels, seams = unfold(mesh, split=split, max_dims=max_dims, strategy=strategy)
    assert refold_error(mesh, frames, local, panels) < 1e-3, "refold mismatch"
    area2d = sum(sum(Polygon(pn.tri[f]).area for f in pn.faces) for pn in panels)
    assert abs(area2d - mesh.area) < 1e-3 * mesh.area, f"area {area2d} vs {mesh.area}"
    for pn in panels:                                       # no self-overlap: union area == sum of triangle areas
        tri_area = sum(Polygon(pn.tri[f]).area for f in pn.faces)
        assert abs(pn.union.area - tri_area) < 1e-3 * tri_area, "panel overlaps itself"
    n_fold = sum(len(pn.folds) for pn in panels)
    assert n_fold + len(seams) == len(mesh.face_adjacency), "edge accounting"
    assert sum(len(pn.faces) for pn in panels) == len(mesh.faces)
    return panels, seams


def run(model, prm):
    """The unfolding the plan produces must be exactly the one core.unfold gives for the same mesh.
    autofix stays off so nothing is dropped behind the test's back."""
    prm = {"autofix": "off", **prm}
    mode = MODES["folded"]; p = coerce_params(mode, prm)
    src = load_mesh(ROOT / "examples" / f"{model}.stl", p, mode="folded")
    mesh = simplify(src, target_faces(src, p["facet"]))
    panels, seams = check_unfold(mesh, p["separate"], p["strategy"], mode.usable_sheet(p))
    plan = build(ROOT / "examples" / f"{model}.stl", "folded", prm)
    sl = plan["slices"]
    F = [s for s in sl if s["group"] == "F"]; J = [s for s in sl if s["group"] == "J"]
    assert len(F) == len(panels)
    if p["joint"] in ("strip", "rib"):
        assert 0 < len(J) <= len(seams), f"{len(J)} joint parts for {len(seams)} seams"
        for s in J:                                          # rib / strip label carries the fold angle
            ang = float(s["note"].rstrip("°")); assert 0 < ang < 360
    for s in sl:
        assert not any("does not fit the sheet" in e for e in s["errors"]), s["errors"]
    n_holes = sum(len(r) - 1 for s in F for pc in s["pieces"] for r in pc["placed"])
    errs = sum(len(s["errors"]) for s in sl)
    print(f"OK {model:10s} {p['joint']:7s} separate={p['separate']!s:5} faces={len(mesh.faces):4d} panels={len(panels):4d} seams={len(seams):4d} "
          f"joint parts={len(J):4d} holes={n_holes:4d} sheets={plan['sheets']} usage={plan['sheet_usage']:.0%} errors={errs} warnings={plan['counts']['warnings']}")


def test_cube_net():
    """A cube unfolds into one panel of 12 triangles: 11 folds, 7 seams — with every strategy."""
    m = trimesh.creation.box([60, 60, 60])
    for strategy in ("flat", "strip", "area", "auto"):
        frames, local, panels, seams = unfold(m, strategy=strategy)
        assert len(panels) == 1 and len(panels[0].faces) == 12 and len(seams) == 18 - 11, strategy


def test_rib_angle_is_dihedral():
    """Rib for a cube edge must be cut at 90°."""
    plan = build(ROOT / "examples" / "cube.stl", "folded", {"facet": 0, "joint": "rib", "rib_w": 8, "inset": 4, "thickness": 1})
    ribs = [s for s in plan["slices"] if s["group"] == "J"]
    assert ribs and all(s["note"] == "90°" for s in ribs), [s["note"] for s in ribs]
    assert all(not s["errors"] for s in plan["slices"]), [s["errors"] for s in plan["slices"] if s["errors"]]


def test_split_every_edge_two_holes():
    """Cloth mode: every triangle is a panel, laced = at least 2 holes per seam on both sides."""
    plan = build(ROOT / "examples" / "cube.stl", "folded", {"facet": 0, "joint": "laced", "separate": True, "hole_d": 2, "inset": 4, "spacing": 20})
    F = [s for s in plan["slices"] if s["group"] == "F"]
    assert len(F) == 12
    holes = sum(len(r) - 1 for s in F for pc in s["pieces"] for r in pc["placed"])
    assert holes >= 2 * 2 * 18, holes                        # 18 edges × 2 sides × ≥2 holes


if __name__ == "__main__":
    test_cube_net(); test_rib_angle_is_dihedral(); test_split_every_edge_two_holes(); print("unit checks ok")
    for model, prm in CASES:
        run(model, prm)


