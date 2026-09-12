"""Real core.plan.build() runs across all five construction modes on tiny examples (autofix="off", so
nothing is silently added or removed behind the test's back): the slice count matches exactly what the
mode's own parameters ask for, and a shape with no reason to fail comes back with zero errors.
"""
import json
import pathlib

import pytest
import trimesh

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# (model, mode, params, expected slice count)
MODE_CASES = [
    ("cube", "stacked", {"distribution": "count", "count": 6}, 6),
    ("cube", "interlocked", {"nx": 3, "ny": 4}, 3 + 4),
    ("cylinder", "radial", {"count": 5, "ring_count": 3}, 2 * 5 + 3),
    ("cube", "curve", {"count": 6, "spines": 1}, 6 + 1),
]


@pytest.mark.parametrize("model, mode, params, expected", MODE_CASES, ids=[c[1] for c in MODE_CASES])
def test_slice_count_matches_params_and_clean(model, mode, params, expected):
    plan = build(EXAMPLES / f"{model}.stl", mode, {**params, "autofix": "off"})
    assert plan["counts"]["slices"] == expected
    assert plan["counts"]["errors"] == 0


def test_folded_separate_panel_count_equals_face_count():
    """separate=True + facet=0 (no decimation) makes every triangle its own panel — panel count is
    exactly the mesh's own face count, folded's version of "the count the params ask for"."""
    mesh = trimesh.load(EXAMPLES / "cube.stl", force="mesh")
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "separate": True, "joint": "laced", "autofix": "off"})
    panels = [s for s in plan["slices"] if s["group"] == "F"]
    assert len(panels) == len(mesh.faces)
    assert plan["counts"]["errors"] == 0


def test_folded_facet_zero_is_still_capped(monkeypatch):
    """facet=0 ("keep every triangle") used to make target_faces return 0, which skipped the face-count guard and
    sent the whole mesh into the unfolder — a scanned model then never came back. The cap is on the face count
    itself now, so it fires whichever way the count was asked for. Lowered here so the cube trips it."""
    from core.modes import folded
    monkeypatch.setattr(folded, "MAX_FACES", 8)                  # cube.stl has 12 faces
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "autofix": "off"})
    assert any("this can unfold" in e for e in plan["errors"])
    assert [s for s in plan["slices"] if s["group"] == "F"]      # degraded to a preview, did not stall or crash


def test_size_then_scale_multiply():
    """size sets the target, scale multiplies it: asked for 30 mm across at scale 0.5, the model comes out 15 mm."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "size": [30, 0, 0], "scale": 0.5, "autofix": "off"})
    assert abs(plan["bbox"][0] - 15) < 1e-6


def test_one_sheet_nests_everything_on_one_strip():
    """one_sheet ignores the sheet height: one sheet as wide as asked and as long as it needs, nothing split."""
    params = {"nx": 6, "ny": 5, "sheet": [200, 120], "autofix": "off"}
    many = build(EXAMPLES / "egg.stl", "interlocked", params)
    one = build(EXAMPLES / "egg.stl", "interlocked", {**params, "one_sheet": True})
    assert many["sheets"] > 1 and one["sheets"] == 1
    assert one["sheet"][0] == 200 and one["sheet"][1] > 120
    assert one["counts"]["parts"] == one["counts"]["slices"]
    assert one["params"]["sheet"] == [200, 120]                     # the user's sheet is reported back untouched


def test_build_is_deterministic():
    """Same model and params, same plan JSON: the coverage sampler is seeded, nothing else draws randomness.
    The stage timing is the one thing in a plan that is allowed to differ between two runs."""
    params = {"nx": 4, "ny": 3, "autofix": "off"}
    p1 = build(EXAMPLES / "egg.stl", "interlocked", params); p1.pop("timing", None)
    p2 = build(EXAMPLES / "egg.stl", "interlocked", params); p2.pop("timing", None)
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)
