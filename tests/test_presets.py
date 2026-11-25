"""Every bundled example opens on a preset (examples/presets.json) that slices without an error, and without a
warning unless it is still on STILL_WARNS. Made on a 3D printer, every printed panel lies on each printer's plate."""
import json
import pathlib

import numpy as np
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


# every printer's plate in the machine list (web/static/js/catalog.js: the print beds and the printers by name)
PLATES = [(180, 180), (220, 220), (250, 210), (250, 220), (256, 256), (300, 300), (325, 320), (350, 350)]
PETG = (0.8, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6)                    # its stock thicknesses (catalog.js)


def printed(name, plate, **kw):
    """The example as the page makes it after What you make with = 3D printer, on `plate`: PETG at the example's
    thickness when PETG comes in it, else at 2.4 mm (its middle stock), no kerf, the printer's 0.2 mm slot offset.
    Returns the plan and its errors, each part's own counted as the page counts them."""
    pr = PRESETS[name]; t = pr["params"].get("thickness", 3)
    plan = build(EXAMPLES / f"{name}.stl", pr["mode"], {**pr["params"], "material": "PETG", "printed": True, "kerf": 0, "slot_offset": 0.2,
                                                        "thickness": t if any(abs(t - s) < 1e-6 for s in PETG) else 2.4, "sheet": list(plate), **kw})
    return plan, plan["errors"] + [f"{sl['label']}: {e}" for sl in plan["slices"] for e in sl["errors"]]


@pytest.mark.parametrize("plate", PLATES, ids="{0[0]}x{0[1]}".format)
@pytest.mark.parametrize("name", sorted(k for k, v in PRESETS.items() if v["mode"] == "folded"))
def test_every_printed_panel_lies_on_its_plate(name, plate):
    """A part that fits the plate is laid on it; one too big for it says so. Bug 080: the room the nester kept for a
    printed panel's seam-number tags made a panel just smaller than the plate fit it at no angle, and it was laid past
    the edge (7 of the 304 example and plate pairs, all folded: the only printed parts with seam tags)."""
    plan, _ = printed(name, plate)
    W, H = plate
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            xy = np.array([q for poly in pc["placed"] for ring in poly for q in ring])
            on = xy.min() >= -0.01 and (xy.max(0) <= (W + 0.01, H + 0.01)).all()
            assert on or any(e.startswith(f"{pc['label']} does not fit the sheet") for e in sl["errors"]), (pc["label"], xy.min(0), xy.max(0))


@pytest.mark.parametrize("joint", ["tab", "click"])
def test_the_cow_prints_on_a_180_mm_plate(joint):
    """The 3D-print guide's cow on the generic 3D printer's first plate: 2 errors with tabs and 3 with click joints
    before bug 080 (P-5 laid to 214 mm on 180)."""
    plan, errs = printed("cow", (180, 180), joint=joint)
    assert not errs, errs[:3]
