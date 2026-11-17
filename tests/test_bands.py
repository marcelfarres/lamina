"""Band lattice: rings along any of x, y and z, half-lapped where they cross. The first family stays whole, each slot
opens outward in the band placed first and inward in the one placed after it, and a band that cannot slide in whole
is cut into pieces that can, joined by puzzle tabs."""
import pathlib

import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from core.plan import build

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
CUBE = EXAMPLES / "cube.stl"                        # 180 mm, centred
BASE = {"autofix": "off", "thickness": 4, "nx": 3, "ny": 3, "nz": 3, "ring_wall": 12}


def shape(plan, label):
    """A band as cut, all its pieces together, in its own frame."""
    sl = next(s for s in plan["slices"] if s["label"] == label)
    polys = [Polygon(rings[0], rings[1:]) for pc in sl["pieces"] for f in pc["facets"] for rings in f["rings"]]
    return unary_union(polys), sl


def test_two_families_half_lap_with_the_first_whole_and_the_second_cut_in_two():
    plan = build(CUBE, "bands", {**BASE, "z": False})
    assert plan["counts"]["slices"] == 6 and plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    for lab in ("X-1", "X-2", "X-3"):
        g, sl = shape(plan, lab)
        assert len(sl["pieces"]) == 1                                   # placed first: whole
        assert set(sl["engages"]) == {"Y-1", "Y-2", "Y-3"}
    for lab in ("Y-1", "Y-2", "Y-3"):
        assert len(shape(plan, lab)[1]["pieces"]) == 2                 # top and bottom slide in from opposite sides
    assert "X → Y" in " ".join(plan["notes"])


def test_the_slot_opens_outward_in_the_first_band_and_inward_in_the_second():
    plan = build(CUBE, "bands", {**BASE, "z": False})
    x2, _ = shape(plan, "X-2"); y2, _ = shape(plan, "Y-2")
    # the joint at the top of the cube, on the line x = y = 0: the walls run from z = 78 to 90 and meet at 84.
    # Both bands' local y is world z; their local x is 0 on that line
    assert not x2.contains(Point(0, 87)) and x2.contains(Point(0, 81))    # first band: cut from the outside in
    assert y2.contains(Point(0, 87)) and not y2.contains(Point(0, 81))    # second: from the inside out
    assert x2.contains(Point(10, 87)) and y2.contains(Point(10, 81))      # and only a slot wide


def test_three_families_cut_the_later_bands_and_join_every_cut_with_a_tab():
    plan = build(CUBE, "bands", BASE)
    assert plan["counts"]["slices"] == 9 and plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    note = next(n for n in plan["notes"] if n.startswith("assembly"))
    first = note.split(": ")[1][0]
    cuts = int(note.split("; ")[1].split(" cut")[0])
    assert cuts > 0
    whole = [s for s in plan["slices"] if s["label"].startswith(first)]
    assert whole and all(len(s["pieces"]) == 1 for s in whole)
    assert plan["counts"]["parts"] == len(whole) + cuts                 # a closed ring cut k times is k pieces
    # a puzzle tab: a piece's outline bulges past the straight cut, so no piece is a plain arc of the ring
    cut = [s for s in plan["slices"] if len(s["pieces"]) > 1]
    assert all(any(len(f["rings"][0][0]) > 40 for pc in s["pieces"] for f in pc["facets"]) for s in cut)


def test_the_order_decides_which_family_stays_whole():
    plan = build(CUBE, "bands", {**BASE, "order": "zxy"})
    assert all(len(s["pieces"]) == 1 for s in plan["slices"] if s["label"].startswith("Z"))
    assert "Z → X → Y" in " ".join(plan["notes"])


def test_without_cuts_a_locked_band_is_an_error():
    plan = build(CUBE, "bands", {**BASE, "z": False, "band_cuts": False})
    errs = [e for s in plan["slices"] for e in s["errors"]]
    assert sum("cannot slide in whole" in e for e in errs) == 3            # the three Y bands
    assert all(len(s["pieces"]) == 1 for s in plan["slices"])


def test_one_family_is_not_a_lattice():
    plan = build(CUBE, "bands", {**BASE, "y": False, "z": False})
    assert plan["counts"]["slices"] == 0 and any("at least two" in e for e in plan["errors"])
    assert any(o["set"] == {"y": True} for f in plan["fixes"] for o in f["options"])


@pytest.mark.parametrize("wall, expect", [(12, 180 ** 2 - 156 ** 2), (30, 180 ** 2 - 120 ** 2)])
def test_a_band_takes_its_own_wall(wall, expect):
    plan = build(CUBE, "bands", {**BASE, "z": False, "wall": {"X-2": wall}})
    g, _ = shape(plan, "X-2")
    slots = 6 * 4 * 6 * (1 if wall == 12 else 0.5)                     # six half-depth slots, give or take
    assert abs(g.area - expect) < slots + 300
