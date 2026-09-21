"""core.checks runs inside core.plan.build(); these tests trigger its two error conditions with real
geometry (no synthetic Slice fixtures) and verify autofix actually clears the one it claims to fix.
"""
import pathlib

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_no_crossing_slice_error_and_autofix_add_resolves_it():
    """curve mode with spines=0 gives every rib nothing to cross (no spine slices exist at all), so
    check_slice()'s `sl.group in ("X", "Y") and not sl.engages` branch fires on every rib."""
    off = build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "off"})
    assert off["counts"]["errors"] > 0
    all_errors = [e for sl in off["slices"] for e in sl["errors"]]
    assert any("no crossing slice" in e for e in all_errors)

    fixed = build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "add"})
    assert fixed["counts"]["errors"] == 0


def test_a_stacked_layer_is_never_offered_for_deletion():
    """A layer of a stack *is* the model at that height: "delete Z-2" answers the check and ruins the piece, which is
    what the reporter hit. The fixes offered for a stacked layer keep it — glue the stack, thinner pegs, grow the
    outline, round the model — while the same errors elsewhere may still offer a deletion."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {
        "distribution": "count", "count": 3, "size": [40, 40, 40], "min_feature": 50, "autofix": "off",
    })
    stacked = [o["title"] for sl in plan["slices"] if sl["group"] == "S" for f in sl["fixes"] for o in f["options"]]
    assert stacked, "no fixes offered at all"
    assert not any(t.startswith("delete") for t in stacked), stacked
    assert any("grow" in t or "round" in t or "thicken" in t for t in stacked), stacked
    crossing = build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "off"})
    assert any(t.startswith("delete") for sl in crossing["slices"] for f in sl["fixes"] for o in f["options"] for t in [o["title"]])


def test_thin_feature_error_when_min_feature_exceeds_part():
    """The cube scaled to 40 mm with min_feature at the slider's top (50 mm): every stacked slice's own bulk reads
    as "too thin", forcing the check_slice() min_dims() thin-part branch."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {
        "distribution": "count", "count": 3, "size": [40, 40, 40], "min_feature": 50, "autofix": "off",
    })
    assert plan["counts"]["errors"] > 0
    all_errors = [e for sl in plan["slices"] for e in sl["errors"]]
    assert any("thin" in e.lower() for e in all_errors)
