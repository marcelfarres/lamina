"""Pieces cut short: a band or a ring slice longer than `max_length`, or too big for the sheet, is cut across its wall into
pieces joined by puzzle tabs — or, in a band that slides in, by straight tongues."""
import math
import pathlib

from shapely.geometry import Polygon
from shapely.ops import unary_union

from core.labels import mark_box
from core.plan import build

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
CUBE = EXAMPLES / "cube.stl"                        # 180 mm, centred
BANDS = {"autofix": "off", "thickness": 4, "nx": 3, "ny": 3, "nz": 3, "ring_wall": 12, "labels": False}
RINGS = {"autofix": "off", "distribution": "count", "count": 4, "thickness": 6, "connect": "none", "ring_slices": True,
         "ring_wall": 12, "labels": False}


def _polys(plan):
    return [(pc["place"][0], unary_union([Polygon(r[0], r[1:]) for r in pc["placed"]])) for s in plan["slices"] for pc in s["pieces"]]


def test_bands_are_cut_to_the_longest_piece_asked_for():
    whole = build(CUBE, "bands", BANDS)
    short = build(CUBE, "bands", {**BANDS, "max_length": 200})
    assert short["counts"]["errors"] == 0
    # each Y band's top and bottom are cut once more, across the face both halves slide in along: no tongue mates a
    # piece that slides along its cut, so those are glued butt joints — and every other cut has its tongue or tab
    said = {s["label"]: s["warnings"] for s in short["slices"] if s["warnings"]}
    assert set(said) == {"Y-1", "Y-2", "Y-3"} and all(w == [said["Y-1"][0]] and w[0].startswith("2 of its 4 cut(s) are plain butt") for w in said.values())
    assert short["counts"]["parts"] > whole["counts"]["parts"]
    for sl in short["slices"]:
        assert len(sl["pieces"]) >= math.ceil(4 * 180 / 200)          # the outline is 720 mm round
        for pc in sl["pieces"]:
            g = unary_union([Polygon(r[0], r[1:]) for f in pc["facets"] for r in f["rings"]])
            x0, y0, x1, y1 = g.bounds
            # along a square ring, 200 mm of outline spans at most 200 mm, plus the wall and a tongue or tab
            assert math.hypot(x1 - x0, y1 - y0) <= 200 + 12 + 2 * 8


def test_a_band_too_big_for_the_sheet_is_cut_across_its_wall():
    plan = build(CUBE, "bands", {**BANDS, "z": False, "sheet": [170, 170]})
    assert plan["counts"]["errors"] == 0
    first = [s for s in plan["slices"] if s["label"].startswith("X")]
    assert first and all(len(s["pieces"]) >= 2 for s in first)        # placed first, so whole until the sheet says no
    for _, g in _polys(plan):
        x0, y0, x1, y1 = g.bounds
        assert x1 <= 170 and y1 <= 170


def test_ring_slices_are_cut_to_the_longest_piece_asked_for():
    plan = build(CUBE, "stacked", {**RINGS, "max_length": 250})
    assert plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    assert all(len(s["pieces"]) == math.ceil(720 / 250) for s in plan["slices"])
    whole = build(CUBE, "stacked", RINGS)
    assert all(len(s["pieces"]) == 1 for s in whole["slices"])        # 0: no limit, and a ring that fits stays whole


def test_a_ring_slice_too_big_for_the_sheet_is_cut_across_its_wall_not_in_strips():
    plan = build(CUBE, "stacked", {**RINGS, "sheet": [170, 170]})
    assert plan["counts"]["errors"] == 0
    for sl in plan["slices"]:
        area = sum(pc["area"] for pc in sl["pieces"])
        assert abs(area - (180 ** 2 - 156 ** 2)) < 300                 # still the ring: nothing added, nothing lost
        assert len(sl["pieces"]) >= 2
    for _, g in _polys(plan):
        x0, y0, x1, y1 = g.bounds
        assert x1 <= 170 and y1 <= 170


def test_a_stretch_too_short_for_a_tab_gets_a_plain_cut_not_a_stuck_piece():
    # egg, no connectors, 100 slices (~1 min): two rings kept a 40.7 mm piece over the limit, blaming dowel holes (bug 053)
    plan = build(EXAMPLES / "egg.stl", "stacked", {"autofix": "off", "connect": "none", "ring_slices": True, "max_length": 40})
    assert not [w for s in plan["slices"] for w in s["warnings"] if "longer than `max_length`" in w or "close together" in w]
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            x0, y0, x1, y1 = unary_union([Polygon(r[0], r[1:]) for f in pc["facets"] for r in f["rings"]]).bounds
            assert math.hypot(x1 - x0, y1 - y0) <= 40 + 12 + 2 * 8        # the wall and a tab, as for a band


def test_no_ring_cut_runs_through_a_dowel_number():
    plan = build(EXAMPLES / "egg.stl", "stacked", {**RINGS, "connect": "dowel", "count": 6, "max_length": 60, "hide_marks": False})
    assert plan["counts"]["errors"] == 0
    marks = 0
    for sl in plan["slices"]:
        assert len(sl["pieces"]) > 1                                   # every ring is cut
        parts = [unary_union([Polygon(r[0], r[1:]) for r in pc["kerfed"]]) for pc in sl["pieces"]]
        for i, pc in enumerate(sl["pieces"]):
            others = unary_union(parts[:i] + parts[i + 1:])
            for m in pc["kerfed_marks"]:
                marks += 1                                              # a number's box has none of another piece in it
                assert mark_box(m[0], m[1], m[2], m[4] if len(m) > 4 else plan["params"]["font"], m[3]).intersection(others).area < 0.05, (sl["label"], m)
    assert marks
