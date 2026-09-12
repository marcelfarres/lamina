"""Every bundled example opens on a preset (examples/presets.json) that slices without an error."""
import json
import pathlib

import pytest

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
PRESETS = {k: v for k, v in json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}


def test_every_example_has_a_preset():
    assert set(PRESETS) == {p.stem for p in EXAMPLES.glob("*.stl")}


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_preset_slices_without_an_error(name):
    pr = PRESETS[name]
    plan = build(EXAMPLES / f"{name}.stl", pr["mode"], {"slot_offset": 0.1, "thickness": 3, **pr["params"]})   # what the UI sends: 3 mm cardboard, the machine's slot offset
    errs = [f"{sl['label']}: {e}" for sl in plan["slices"] for e in sl["errors"]]
    assert not errs, errs[:3]
    assert plan["coverage"] > 0.8
