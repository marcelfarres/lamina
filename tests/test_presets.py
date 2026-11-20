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
STILL_WARNS = {"horse_statue", "lion_head"}


def test_every_example_has_a_preset():
    assert set(PRESETS) == {p.stem for p in EXAMPLES.glob("*.stl")}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_slices_without_an_error(name):
    pr = PRESETS[name]
    # what the UI sends: 3 mm cardboard, the machine's kerf and slot offset
    plan = build(EXAMPLES / f"{name}.stl", pr["mode"], {"kerf": 0.15, "slot_offset": 0.1, "thickness": 3, **pr["params"]})
    # the counts the page shows: each part's messages and the plan's own (a connector the technique left out)
    errs = plan["errors"] + [f"{sl['label']}: {e}" for sl in plan["slices"] for e in sl["errors"]]
    assert not plan["counts"]["errors"], errs[:3]
    assert plan["coverage"] > 0.8
    warns = plan["warnings"] + [f"{sl['label']}: {w}" for sl in plan["slices"] for w in sl["warnings"]]
    assert bool(plan["counts"]["warnings"]) == (name in STILL_WARNS), warns[:3] or f"{name} opens without a warning now: take it off STILL_WARNS"
