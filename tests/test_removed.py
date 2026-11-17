"""Removed faces (Folded Panels): the faces the user took off the surface are not cut, and they stay removed when the
faces are made again, the model is resized or turned. Real core.unfold / core.plan.build() runs, autofix off."""
import pathlib
import numpy as np
import trimesh
from core.modes.folded import target_faces
from core.mesh import load_mesh, simplify
from core.plan import build, MODES, coerce_params
from core.unfold import faces_at

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
PAPER = {"facet": 25, "joint": "seam", "edge_fit": "outer", "material": "paper", "thickness": 0.3, "autofix": "off"}


def egg(facet=25, **params):
    """The egg as the folded technique sees it at this facet size, and the 4×4 from the file's coordinates to it."""
    p = coerce_params(MODES["folded"], {"facet": facet, **params})
    src = load_mesh(EXAMPLES / "egg.stl", p, surface=True)
    return simplify(src, target_faces(src, facet)), np.array(src.metadata["frame"])


def in_file(tris, frame):
    """Triangles of the model (mm) in the file's own coordinates, as the page keeps them: [[[x, y, z] × 3], …]."""
    flat = np.c_[np.reshape(tris, (-1, 3)), np.ones(len(tris) * 3)] @ np.linalg.inv(frame).T
    return flat[:, :3].reshape(-1, 3, 3).round(4).tolist()


def panel_area(plan):
    return sum(pc["area"] for s in plan["slices"] if s["group"] == "F" for pc in s["pieces"])


def test_a_face_is_found_again_by_its_own_triangle():
    mesh, _ = egg()
    top = mesh.triangles_center[:, 2] > 5
    assert 5 < top.sum() < len(top) - 5
    assert (faces_at(mesh, mesh.triangles[top]) == top).all()
    assert not faces_at(mesh, []).any()
    assert not faces_at(mesh, [[1, 2, 3]]).any()             # not triangles: nothing found, nothing raised


def test_the_same_place_is_removed_when_the_faces_are_made_again():
    coarse, _ = egg(25)
    top = coarse.triangles_center[:, 2] > 5
    fine, _ = egg(12)
    again = faces_at(fine, coarse.triangles[top])
    z = fine.triangles_center[:, 2]
    assert z[again].min() > 5 - 12 and z[~again].max() < 5 + 12        # the rim moves by a triangle at most
    assert abs(fine.area_faces[again].sum() - coarse.area_faces[top].sum()) < 0.15 * coarse.area_faces[top].sum()


def test_the_far_side_of_a_thin_wall_stays():
    wall = trimesh.creation.box([60, 60, 2])
    up = wall.face_normals[:, 2] > 0.9
    assert (faces_at(wall, wall.triangles[up]) == up).all()


def test_removed_faces_are_not_cut_and_follow_the_model_when_it_is_resized_or_turned():
    mesh, frame = egg()
    top = mesh.triangles_center[:, 2] > 5
    removed = in_file(mesh.triangles[top], frame)
    kept = mesh.area_faces[~top].sum()
    whole = build(EXAMPLES / "egg.stl", "folded", PAPER)
    assert abs(panel_area(whole) - mesh.area) < 0.01 * mesh.area
    plan = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "removed": removed})
    assert abs(panel_area(plan) - kept) < 0.01 * kept
    assert np.allclose(plan["frame"], frame)
    # the page gets the faces that are left, each edge with the two faces across it, numbered as the edges it draws
    f3 = plan["faces3d"]
    assert f3["removed"] == top.sum() and len(f3["f"]) == (~top).sum() and len(whole["faces3d"]["f"]) == len(top)
    tri = np.array(f3["v"])[np.array(f3["f"])]
    assert abs(np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum() / 2 - kept) < 0.01 * kept
    ends = {e[0]: {tuple(e[2]), tuple(e[3])} for e in plan["edges3d"]}
    for k, (a, b) in enumerate(f3["adj"]):
        shared = {tuple(f3["v"][i]) for i in f3["f"][a]} & {tuple(f3["v"][i]) for i in f3["f"][b]}
        assert len(shared) == 2 and (k not in ends or ends[k] == shared)
    # coverage is measured on what is left of the model: taking 4 faces in 10 off does not lower it, or raise it to 1
    assert not plan["errors"] and abs(plan["coverage"] - whole["coverage"]) < 0.05
    assert bool([n for n in plan["notes"] if "coverage" in n]) == bool([n for n in whole["notes"] if "coverage" in n])
    # twice the size, facet with it: the same faces, four times the area
    big = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "removed": removed, "scale": 2, "facet": 50})
    assert abs(panel_area(big) - 4 * kept) < 0.02 * 4 * kept
    turned = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "removed": removed, "rotate": [90, 0, 30]})
    assert abs(panel_area(turned) - kept) < 0.02 * kept


def test_a_piece_cut_off_from_the_rest_stays_and_is_named():
    mesh, frame = egg()
    z = mesh.triangles_center[:, 2]
    band = (z > -10) & (z < 10)                                        # a ring round the egg: a cap above, a bowl below
    plan = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "removed": in_file(mesh.triangles[band], frame)})
    assert abs(panel_area(plan) - mesh.area_faces[~band].sum()) < 0.01 * mesh.area
    said = [w for s in plan["slices"] for w in s["warnings"] if "cut off from the rest" in w]
    assert len(said) == 1 and "P-" in said[0]
    # one opening is no island: nothing is said
    plain = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "removed": in_file(mesh.triangles[z > 5], frame)})
    assert not [w for s in plain["slices"] for w in s["warnings"] if "cut off from the rest" in w]


def test_every_face_removed_is_an_error_and_no_part():
    mesh, frame = egg()
    plan = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "removed": in_file(mesh.triangles, frame)})
    assert not plan["slices"] and any("every face" in e for e in plan["errors"])
    assert plan["faces3d"] == {"v": [], "f": [], "adj": [], "removed": len(mesh.faces)} and plan["frame"]   # what the page needs to put them back


def test_a_seam_on_the_rim_or_among_the_removed_faces_goes_without_a_word():
    mesh, frame = egg()
    top = mesh.triangles_center[:, 2] > 5
    side = top[mesh.face_adjacency]                                    # per edge: is each of its two faces removed
    ends = lambda k: mesh.vertices[mesh.face_adjacency_edges[k]].round(3).tolist()   # noqa: E731
    rim, gone = int(np.flatnonzero(side[:, 0] != side[:, 1])[0]), int(np.flatnonzero(side.all(1))[0])
    prm = {**PAPER, "removed": in_file(mesh.triangles[top], frame)}
    plan = build(EXAMPLES / "egg.stl", "folded", {**prm, "seams": [ends(rim), ends(gone)]})
    assert not [w for s in plan["slices"] for w in s["warnings"] if "seams you chose" in w]
    assert not [e for e in plan["edges3d"] if e[1] == "chosen"]
    plan = build(EXAMPLES / "egg.stl", "folded", {**prm, "seams": [ends(rim), [[0, 0, 0], [1, 1, 1]]]})
    said = [w for s in plan["slices"] for w in s["warnings"] if "seams you chose" in w]
    assert len(said) == 1 and said[0].startswith("1 of the 2 seams you chose")
