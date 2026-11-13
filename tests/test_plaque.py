"""Plaque: real core.plan.build() runs. The slices stand on the back plate with teeth through plate slots, the model
behind the plate is left out, and a piece that does not reach the plate hangs from the slice beside it or is left out."""
import numpy as np
import pytest
import trimesh
from shapely.geometry import MultiPolygon, Polygon

from core.modes.plaque import SHAPES
from core.plan import build

BASE = {"thickness": 3, "space": 3, "autofix": "off", "split": False, "sheet": [1000, 1000]}


def stl(tmp_path, mesh, name="m"):
    path = tmp_path / f"{name}.stl"
    mesh.export(path)
    return path


def shape(piece_or_slice):
    pcs = piece_or_slice.get("pieces", [piece_or_slice])
    return MultiPolygon([Polygon(r[0], r[1:]) for pc in pcs for r in pc["kerfed"]])


def by_group(plan, g):
    return [s for s in plan["slices"] if s["group"] == g]


@pytest.fixture(scope="module")
def ball(tmp_path_factory):
    return stl(tmp_path_factory.mktemp("plaque"), trimesh.creation.icosphere(4, 50.0), "ball")


def test_every_slice_stands_on_the_plate_with_teeth_as_long_as_the_plate_is_thick(ball):
    plan = build(ball, "plaque", {**BASE, "sink": 50, "plate_thickness": 5, "plate": "circle"})
    assert plan["counts"]["errors"] == 0
    (plate,), slices = by_group(plan, "W"), by_group(plan, "S")
    assert plate["thickness"] == 5 and all(s["thickness"] == 3 for s in slices)
    assert len(slices) >= 10 and not by_group(plan, "P")           # a half ball has no floating piece: no spacers
    teeth = 0
    for s in slices:
        g = shape(s)
        assert g.bounds[1] == pytest.approx(-5, abs=1e-6)           # the teeth end flush with the back of the plate
        below = g.intersection(Polygon([(-1e4, -10), (1e4, -10), (1e4, -0.01), (-1e4, -0.01)]))
        n = len(getattr(below, "geoms", [below]))
        assert n >= 2, f"{s['label']} has {n} tooth"
        teeth += n
    assert sum(len(p.interiors) for p in shape(plate).geoms) == teeth      # one plate slot for every tooth
    # nothing of the model behind the plate: the ball is 100 deep, half of it is left
    assert max(shape(s).bounds[3] for s in slices) == pytest.approx(50, abs=1.0)
    assert plan["coverage"] > 0.9


def test_teeth_are_spread_evenly_and_a_long_stretch_gets_more_of_them(ball):
    plan = build(ball, "plaque", {**BASE, "sink": 50, "tooth_spacing": 20, "tooth_width": 6})
    mid = max(by_group(plan, "S"), key=lambda s: s["extents"][0])   # the slice through the middle: about 100 mm on the plate
    below = shape(mid).intersection(Polygon([(-1e4, -10), (1e4, -10), (1e4, -0.01), (-1e4, -0.01)]))
    xs = sorted(g.centroid.x for g in below.geoms)
    assert len(xs) >= 5
    assert np.ptp(np.diff(xs)) < 1e-3                               # the same step between every two teeth


@pytest.mark.parametrize("kind", SHAPES)
def test_every_plate_shape_holds_the_model(ball, kind):
    plan = build(ball, "plaque", {**BASE, "sink": 50, "plate": kind, "plate_margin": 15})
    assert plan["counts"]["errors"] == 0
    plate = shape(by_group(plan, "W")[0])
    x0, y0, x1, y1 = plate.bounds
    assert x1 - x0 >= 100 + 2 * 15 - 1 and y1 - y0 >= 100 + 2 * 15 - 1     # the 100 mm ball and the margin all round


def test_plate_size_rotation_and_offset_place_the_plate(ball):
    plan = build(ball, "plaque", {**BASE, "sink": 50, "plate": "rectangle", "plate_size": [200, 120], "plate_offset": [10, 0]})
    plate = by_group(plan, "W")[0]
    assert plate["extents"] == pytest.approx([200, 120], abs=0.01)
    assert shape(plate).bounds[0] == pytest.approx(-90, abs=0.01)   # moved 10 mm along the plate's x


def mushroom(extra=None):
    """A stem on the plate with a wide cap above it: slices beside the stem cut the cap only, which reaches no plate."""
    stem = trimesh.creation.box([12, 60, 30]); stem.apply_translation([0, 0, 15])
    cap = trimesh.creation.box([48, 60, 30]); cap.apply_translation([0, 0, 45])
    m = trimesh.boolean.union([stem, cap])
    return trimesh.util.concatenate([m, extra]) if extra is not None else m


def test_a_piece_that_does_not_reach_the_plate_hangs_from_the_slice_beside_it(tmp_path):
    plan = build(stl(tmp_path, mushroom()), "plaque", {**BASE, "dowel_d": 8})
    assert plan["counts"]["errors"] == 0, [s["errors"] for s in plan["slices"]]
    slices, spacers = by_group(plan, "S"), by_group(plan, "P")
    assert len(slices) == 8                                         # 48 mm of cap at 3 + 3 mm
    floating = [s for s in slices if shape(s).bounds[1] > 1]        # no tooth: it stands on nothing
    assert len(floating) == 6 and spacers
    for s in floating:                                              # each hangs on three spacers to the slice toward the stem,
        holes = [Polygon(r).centroid for p in shape(s).geoms for r in p.interiors]
        assert len(holes) >= 3
        a, b, c = max(((a, b, c) for a in holes for b in holes for c in holes), key=lambda t: Polygon(t).area)
        assert Polygon([a, b, c]).area > 50                         # … not in one line: three points hold a plane
    assert not any("fewer than 3" in n for n in plan["notes"])
    # a spacer's slot runs along the plate's normal (the slice's y): seen from the front, the spacer shows its edge
    hole = Polygon(shape(floating[0]).geoms[0].interiors[0])
    assert hole.bounds[3] - hole.bounds[1] > hole.bounds[2] - hole.bounds[0]
    # and no spacer slot breaks out of its slice
    for s in slices:
        for p in shape(s).geoms:
            assert all(Polygon(p.exterior).buffer(-1.9).contains(Polygon(r)) for r in p.interiors)


def test_a_piece_no_neighbour_can_hold_is_left_out_and_said_or_kept_with_its_error(tmp_path):
    far = trimesh.creation.box([10, 10, 6]); far.apply_translation([60, 0, 50])      # in the air, beside nothing
    path = stl(tmp_path, mushroom(far))
    plan = build(path, "plaque", {**BASE, "dowel_d": 5})
    assert plan["counts"]["errors"] == 0
    assert any("left out" in n for n in plan["notes"])
    assert max(float(np.array(s["M"])[0, 3]) for s in by_group(plan, "S")) < 30       # no slice out where the far box is
    kept = build(path, "plaque", {**BASE, "dowel_d": 5, "floating": "keep"})
    assert kept["counts"]["errors"] > 0 and not any("left out" in n for n in kept["notes"])


def test_a_radial_fan_stands_round_a_hole_with_teeth_under_every_half_slice(ball):
    plan = build(ball, "plaque", {**BASE, "layout": "radial", "planes": 8, "sink": 50, "plate": "circle"})
    assert plan["counts"]["errors"] == 0, plan["errors"]
    fan = by_group(plan, "R")
    assert len(fan) == 16 and not by_group(plan, "S")               # 8 planes, two half-slices each
    least = 3 / 2 / np.tan(np.pi / 16)                              # where two neighbours' inner corners would meet
    for s in fan:
        g = shape(s)
        assert g.bounds[0] >= least - 1e-6                          # every half-slice ends outside the hole
        below = g.intersection(Polygon([(-1e4, -10), (1e4, -10), (1e4, -0.01), (-1e4, -0.01)]))
        assert len(getattr(below, "geoms", [below])) >= 2
    turns = sorted(round(float(np.degrees(np.arctan2(np.array(s["M"])[1, 0], np.array(s["M"])[0, 0]))) % 360, 3) for s in fan)
    assert np.allclose(np.diff(turns), 22.5)                        # evenly round the centre
    plate = shape(by_group(plan, "W")[0])
    assert len(plate.geoms) == 1 and sum(len(p.interiors) for p in plate.geoms) >= 32      # one piece, a slot for every tooth


def test_a_hole_too_small_for_the_fan_is_an_error_with_the_radius_that_fits(ball):
    plan = build(ball, "plaque", {**BASE, "layout": "radial", "planes": 8, "sink": 50, "radius": 2})
    assert plan["counts"]["slices"] == 0 and "collide" in plan["errors"][0]
    r = plan["fixes"][0]["options"][0]["set"]["radius"]
    assert build(ball, "plaque", {**BASE, "layout": "radial", "planes": 8, "sink": 50, "radius": r})["counts"]["errors"] == 0


def test_the_drop_example_is_one_body_and_slices_clean_as_a_fan():
    from core.testmodels import droplet
    assert droplet().body_count == 1                                # rings, column and bulb: nothing in the air
    plan = build("examples/droplet.stl", "plaque", {**BASE, "layout": "radial", "plate": "circle"})
    assert plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    assert len(by_group(plan, "R")) == 24


def test_slices_cannot_run_along_the_axis_the_plate_is_square_to(ball):
    plan = build(ball, "plaque", {**BASE, "back": "-z", "axis": "z"})
    assert plan["counts"]["slices"] == 0 and plan["errors"]
    assert {o["set"]["axis"] for o in plan["fixes"][0]["options"]} == {"x", "y"}


def test_touching_slices_keep_a_wall_between_their_plate_slots(ball):
    plan = build(ball, "plaque", {**BASE, "space": 0, "sink": 50})
    assert not any("plate slots" in e for e in plan["errors"]), plan["errors"]
    plate = shape(by_group(plan, "W")[0])
    assert len(plate.geoms) == 1                                    # the plate is still one piece
