"""Seams the user chooses (Folded Panels): the unfolder never folds there, and the plan tells the page where every
fold and seam edge is, on the model and on the sheets. Real core.unfold / core.plan.build() runs, autofix off."""
import pathlib
import numpy as np
import pytest
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from core.modes.folded import target_faces
from core.mesh import load_mesh, simplify
from core.plan import build, MODES, coerce_params
from core.unfold import unfold, refold_error, edges_at

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
PAPER = {"facet": 25, "joint": "seam", "edge_fit": "outer", "material": "paper", "thickness": 0.3, "autofix": "off"}


def egg():
    p = coerce_params(MODES["folded"], {"facet": 25})
    src = load_mesh(EXAMPLES / "egg.stl", p, surface=True)
    return simplify(src, target_faces(src, 25))


def test_a_chosen_seam_is_never_folded_and_the_net_still_folds_back():
    mesh = egg()
    _, _, panels, _ = unfold(mesh, max_dims=(590, 390), strategy="auto")
    chosen = set(panels[0].folds[::7])                      # edges the unfolder folds when left alone
    assert len(chosen) >= 3
    frames, local, panels, seams = unfold(mesh, max_dims=(590, 390), strategy="auto", chosen=chosen)
    assert chosen <= set(seams)
    assert not chosen & {k for pn in panels for k in pn.folds}
    assert refold_error(mesh, frames, local, panels) < 1e-3
    assert sum(len(pn.folds) for pn in panels) + len(seams) == len(mesh.face_adjacency)
    assert sum(len(pn.faces) for pn in panels) == len(mesh.faces)
    for pn in panels:
        assert abs(pn.union.area - sum(Polygon(pn.tri[f]).area for f in pn.faces)) < 1e-3 * pn.union.area


def test_a_chosen_seam_across_a_flat_face_stays_a_seam():
    """The two triangles of a cube's face lie edge to edge in the net whatever is chosen, and an edge like that is
    made a fold again at the end of the unfolding. Not a chosen one."""
    mesh = trimesh.creation.box([60, 60, 60])
    diagonal = int(np.argmin(mesh.face_adjacency_angles))
    assert mesh.face_adjacency_angles[diagonal] < 1e-6
    assert diagonal not in unfold(mesh, strategy="flat")[3]
    _, _, panels, seams = unfold(mesh, strategy="flat", chosen={diagonal})
    assert diagonal in seams and all(diagonal not in pn.folds for pn in panels)


def test_edges_are_found_by_their_ends_and_a_line_that_is_no_edge_is_counted():
    mesh = egg()
    ends = mesh.vertices[mesh.face_adjacency_edges[[3, 40]]]
    lines = [np.round(ends[0], 3).tolist(), np.round(ends[1][::-1], 3).tolist(), [[0, 0, 0], [1, 1, 1]]]
    assert edges_at(mesh, lines) == ({3, 40}, 1)
    assert edges_at(mesh, [[1, 2, 3]]) == (set(), 1)        # not two ends: nothing found, nothing raised
    assert edges_at(mesh, []) == (set(), 0)


@pytest.mark.parametrize("score_side", ["inside", "outside"])
def test_the_plan_marks_every_edge_on_the_model_and_on_the_sheets(score_side):
    prm = {**PAPER, "score_side": score_side}
    plain = build(EXAMPLES / "egg.stl", "folded", prm)
    folds = [e for e in plain["edges3d"] if e[1] == "fold"]
    assert folds and not [e for e in plain["edges3d"] if e[1] == "chosen"]
    picked = [[e[2], e[3]] for e in folds[::9]]
    plan = build(EXAMPLES / "egg.stl", "folded", {**prm, "seams": picked})
    kind = {e[0]: e[1] for e in plan["edges3d"]}
    by_ends = {(tuple(e[2]), tuple(e[3])): e[1] for e in plan["edges3d"]}
    assert [by_ends[tuple(a), tuple(b)] for a, b in picked] == ["chosen"] * len(picked)
    assert sum(k == "chosen" for k in kind.values()) == len(picked)
    # a closed surface in the same number of panels has the same number of seams, whoever chose them
    count = lambda pl: (sum(s["group"] == "F" for s in pl["slices"]), sum(e[1] != "fold" for e in pl["edges3d"]))  # noqa: E731
    assert count(plan)[1] - count(plan)[0] == count(plain)[1] - count(plain)[0]
    seen = {}
    for s in plan["slices"]:
        for pc in s["pieces"]:
            outline = unary_union([Polygon(r[0], r[1:]) for r in pc["placed"]]).boundary
            scores = np.array([np.ravel(ln) for style, ln in pc["lines"] if len(ln) == 2 and style in ("solid", "dashed")])
            for k, x0, y0, x1, y1 in pc.get("edges", []):
                seen[k] = seen.get(k, 0) + 1
                if kind[k] == "fold":                        # where its score is drawn
                    assert np.abs(scores - [x0, y0, x1, y1]).max(1).min() < 0.01
                else:                                        # on the panel's cut outline (grown by the kerf)
                    assert outline.distance(Point((x0 + x1) / 2, (y0 + y1) / 2)) < plan["kerf"] + 0.05
    assert seen == {k: 1 if v == "fold" else 2 for k, v in kind.items()}


def test_a_seam_that_is_on_no_edge_any_more_is_said_and_left_out():
    plain = build(EXAMPLES / "egg.stl", "folded", PAPER)
    plan = build(EXAMPLES / "egg.stl", "folded", {**PAPER, "seams": [[[0, 0, 0], [1, 1, 1]]]})
    said = [w for s in plan["slices"] for w in s["warnings"] if "on no edge" in w]
    assert len(said) == 1 and said[0].startswith("1 of the 1 seams you chose")
    assert plan["edges3d"] == plain["edges3d"]


def test_separate_faces_have_no_seams_to_choose():
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "separate": True, "joint": "laced", "autofix": "off",
                                                    "seams": [[[0, 0, 0], [1, 1, 1]]]})
    assert plan["edges3d"] is None and not [w for s in plan["slices"] for w in s["warnings"] if "seams you chose" in w]
