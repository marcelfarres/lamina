"""Ring slices (stacked `ring_slices`): each slice keeps only a wall of a set width inside its outline, measured in the
slice's own plane; holes and islands get their own wall, narrow stretches stay solid, the ends can stay solid, a
slice can have its own wall, and connectors sit in material."""
import pathlib

from shapely.geometry import Point, box

from core.geometry import as_multi
from core.plan import build
from core.ring import collared, ring

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
BASE = {"autofix": "off", "distribution": "count", "count": 6, "thickness": 6}


def test_a_ring_is_the_outline_moved_in_by_the_wall():
    sq = box(0, 0, 100, 100)
    r = ring(sq, 10, 2)
    assert abs(r.area - (100 * 100 - 80 * 80)) < 1.0                  # round inside corners take a hair less
    assert as_multi(r).geoms[0].interiors                              # one hole in the middle


def test_a_hole_and_an_island_each_get_their_own_wall():
    washer = Point(0, 0).buffer(50).difference(Point(0, 0).buffer(20))
    r = ring(washer, 5, 1)
    assert len(r.geoms) == 2                                           # a wall round the outside, a wall round the hole
    assert all(0.9 * w < g.area / (g.length / 2) < 1.1 * w for g, w in zip(r.geoms, (5, 5)))
    two = as_multi(box(0, 0, 50, 50).union(box(100, 0, 150, 50)))
    assert sum(len(g.interiors) for g in ring(two, 5, 1).geoms) == 2


def test_a_stretch_narrower_than_twice_the_wall_stays_solid():
    narrow = box(0, 0, 100, 15)                                         # 15 < 2 × 10
    assert ring(narrow, 10, 2).area == narrow.area
    dumbbell = box(0, 0, 60, 60).union(box(60, 25, 140, 35)).union(box(140, 0, 200, 60))
    r = ring(dumbbell, 10, 2)
    assert r.contains(box(70, 26, 130, 34))                            # the 10 mm bar between the ends is whole
    assert sum(len(g.interiors) for g in r.geoms) == 2                 # each end is a ring


def test_a_collar_keeps_a_wall_round_a_dowel_that_sits_off_the_ring():
    section = Point(0, 0).buffer(100)
    wall = ring(section, 4, 2)
    hole = Point(0, 91).buffer(3)                                       # 9 mm in from the outline: past the 4 mm wall
    cut = collared(section, wall, [hole], 2)
    assert cut.contains(hole.buffer(2.9))                                # a full collar round it, 1.5 × min_feature
    assert len(cut.geoms) == 1                                         # joined to the ring


def test_stacked_rings_are_hollow_with_the_wall_asked_for():
    solid = build(EXAMPLES / "cube.stl", "stacked", {**BASE, "connect": "none"})
    rings = build(EXAMPLES / "cube.stl", "stacked", {**BASE, "connect": "none", "ring_slices": True, "ring_wall": 12})
    assert rings["counts"]["slices"] == solid["counts"]["slices"] == 6 and rings["counts"]["errors"] == 0
    side = 180
    for sl in rings["slices"]:
        assert abs(sum(pc["area"] for pc in sl["pieces"]) - (side ** 2 - (side - 24) ** 2)) < 200
    assert rings["material_area_mm2"] < 0.3 * solid["material_area_mm2"]


def test_solid_ends_and_a_slice_of_its_own():
    p = {**BASE, "connect": "none", "ring_slices": True, "ring_wall": 12, "ring_caps": True, "wall": {"Z-3": 30}}
    plan = build(EXAMPLES / "cube.stl", "stacked", p)
    area = {sl["label"]: sum(pc["area"] for pc in sl["pieces"]) for sl in plan["slices"]}
    assert abs(area["Z-1"] - 180 ** 2) < 1 and abs(area["Z-6"] - 180 ** 2) < 1        # the ends closed
    assert abs(area["Z-2"] - (180 ** 2 - 156 ** 2)) < 200
    assert abs(area["Z-3"] - (180 ** 2 - 120 ** 2)) < 300                             # its own 30 mm wall


def test_dowels_wider_than_the_wall_sit_in_a_collar_with_no_thin_spots():
    p = {**BASE, "ring_slices": True, "ring_wall": 4, "connect": "dowel", "dowel_d": 6, "count": 4}
    plan = build(EXAMPLES / "cube.stl", "stacked", p)
    assert plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    assert plan["rods"]                                                              # the stack is held
    assert all("dowel" in sl["engages"] for sl in plan["slices"])


def test_a_ring_inside_the_hole_of_the_next_is_held_by_a_lug():
    """A vase flares by more than the wall from one slice to the next: a ring then lies inside the hole of the ring
    beside it and no dowel passes through both walls (8 of 10 rings were left unheld). The wider ring grows a lug in
    to where the other's wall is, so every ring is on a dowel, for little more material than the bare rings."""
    job = {"distribution": "count", "count": 10, "ring_slices": True, "ring_wall": 8}
    plan = build(str(EXAMPLES / "vase.stl"), "stacked", job)
    loose = [s["label"] for s in plan["slices"] for e in s.get("errors", []) if "not connected" in e]
    assert not loose and plan["counts"]["errors"] == 0, (loose, plan["counts"])
    area = lambda p: sum(pc["area"] for s in p["slices"] if s["label"].startswith("Z-") for pc in s["pieces"])   # noqa: E731
    solid = build(str(EXAMPLES / "vase.stl"), "stacked", {"distribution": "count", "count": 10})
    assert area(plan) < 0.4 * area(solid), (area(plan), area(solid))    # still rings: the lugs are a few percent
