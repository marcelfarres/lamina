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


def test_thin_feature_error_when_min_feature_exceeds_part():
    """The cube scaled to 40 mm with min_feature at the slider's top (50 mm): every stacked slice's own bulk reads
    as "too thin", forcing the check_slice() min_dims() thin-part branch."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {
        "distribution": "count", "count": 3, "size": [40, 40, 40], "min_feature": 50, "autofix": "off",
    })
    assert plan["counts"]["errors"] > 0
    all_errors = [e for sl in plan["slices"] for e in sl["errors"]]
    assert any("thin" in e.lower() for e in all_errors)
