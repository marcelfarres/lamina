"""Every bundled example opens on a preset (examples/presets.json) that slices without an error, and without a
warning unless it is still on STILL_WARNS."""
import json
import pathlib

import pytest

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
PRESETS = {k: v for k, v in json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}
# Examples that still open with a warning, each waiting for better settings (bug 045). A new example opens clean, and
# one that opens clean comes off the list, so it only gets shorter.
STILL_WARNS = {"bunny"}


def opened(name):
    """The example as a fresh page opens it: 3 mm cardboard (unless the preset names a material), the machine's kerf and
    slot offset, the preset. The material sets the limits the checks use (bug 079: without it, the thinnest finger was
    checked as plywood's). Returns the plan, its errors and its warnings, each part's own counted as the page counts them.
    tests/browser_env.py runs the same without the compiled extras."""
    pr = PRESETS[name]
    plan = build(EXAMPLES / f"{name}.stl", pr["mode"], {"kerf": 0.15, "slot_offset": 0.1, "thickness": 3, "material": "cardboard", **pr["params"]})
    errs = plan["errors"] + [f"{sl['label']}: {e}" for sl in plan["slices"] for e in sl["errors"]]
    warns = plan["warnings"] + [f"{sl['label']}: {w}" for sl in plan["slices"] for w in sl["warnings"]]
    return plan, errs, warns


def test_every_example_has_a_preset():
    assert set(PRESETS) == {p.stem for p in EXAMPLES.glob("*.stl")}


def test_every_example_has_a_preview():
    have = {p.stem for p in (ROOT / "web/static/examples").glob("*.webp")}
    assert have == {p.stem for p in (ROOT / "examples").glob("*.stl")}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_slices_without_an_error(name):
    plan, errs, warns = opened(name)
    assert not plan["counts"]["errors"], errs[:3]
    assert plan["coverage"] > 0.8
    assert bool(plan["counts"]["warnings"]) == (name in STILL_WARNS), warns[:3] or f"{name} opens without a warning now: take it off STILL_WARNS"
