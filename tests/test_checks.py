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


def test_auto_fix_holds_a_tube_by_joining_its_rings_and_takes_nothing_away():
    """Interlocked through a tube: the wall falls apart into strips nothing joins. Auto-fix added a slice through each
    loose strip's middle, just as loose there, then deleted what still floated: 71 % of the tube at 6 × 5. It now
    gives each loose group the position whose own section reaches the rest, and deletes nothing: the tube is held
    whole, and the parts cover the model as well as with auto-fix off."""
    job = {"nx": 6, "ny": 5, "thickness": 3}
    on = build(EXAMPLES / "tube.stl", "interlocked", job)
    off = build(EXAMPLES / "tube.stl", "interlocked", {**job, "autofix": "off"})
    assert off["counts"]["errors"] > 0 and on["counts"]["errors"] == 0, (off["counts"], on["counts"])
    assert on["params"]["extra_x"] or on["params"]["extra_y"]
    assert not [n for n in on["notes"] if "removed" in n], on["notes"]
    assert on["coverage"] >= off["coverage"] - 0.01, (on["coverage"], off["coverage"])


def test_a_piece_nothing_can_hold_stays_on_the_plan_with_its_fixes():
    """The horse's ear tips on a top layer of their own, in a gapped stack: no connector fits them and nothing
    touches them. Auto-fix used to delete the layer. It stays, says it floats, and offers what would hold it."""
    plan = build(EXAMPLES / "horse.stl", "stacked", {
        "thickness": 3, "axis": "z", "size": [0, 300, 0], "connect": "dowel", "dowel_shape": "square", "placement": "random",
        "space": 6, "dowel_d": 3, "n_points": 2, "round": 3, "thicken": 1, "margin": 3})
    top = next(s for s in plan["slices"] if s["label"] == "Z-29")
    assert top["pieces"] and any("floats" in e for e in top["errors"]), top["errors"]
    titles = [o["title"] for f in top["fixes"] for o in f["options"]]
    assert any("gap 0" in t for t in titles), titles


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


def test_a_part_with_points_along_a_straight_side_measures_its_real_size():
    """A 120 × 660 mm part turned 30°, with points along its long sides where slots meet them. GEOS's
    minimum_rotated_rectangle returns a flat line for it (area 0), and min_dims read that as 0.0 mm wide: the tall_bar
    preset's Y slices then failed as "too thin" and were never split to fit the sheet. Every size check and the
    sheet split go through min_dims."""
    from shapely import affinity
    from shapely.geometry import Polygon
    from core.checks import min_dims
    side = [-100, 50, 200]
    part = affinity.rotate(Polygon([(-60, -330), *[(-60, y) for y in side], (-60, 330), (60, 330),
                                    *[(60, y) for y in side[::-1]], (60, -330)]), 30, origin=(0, 0))
    assert part.minimum_rotated_rectangle.area < 1, "GEOS measures this one right now: the test no longer bites"
    w, h = min_dims(part)
    assert abs(w - 120) < 1e-6 and abs(h - 660) < 1e-6, (w, h)


def test_thin_feature_error_when_min_feature_exceeds_part():
    """The cube scaled to 40 mm with min_feature at the slider's top (50 mm): every stacked slice's own bulk reads
    as "too thin", forcing the check_slice() min_dims() thin-part branch."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {
        "distribution": "count", "count": 3, "size": [40, 40, 40], "min_feature": 50, "autofix": "off",
    })
    assert plan["counts"]["errors"] > 0
    all_errors = [e for sl in plan["slices"] for e in sl["errors"]]
    assert any("thin" in e.lower() for e in all_errors)
