"""The click joint of printed folded panels: a tooth on the inside of one panel and a bar bridged between two posts on
the inside of the other, no part of its own. Real core.plan.build() and core.solid runs on the bundled printed box,
and the joint's own geometry put together the way a shut seam puts it."""
import json
import math
import pathlib

import numpy as np
import pytest
import trimesh
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import core.modes.folded as F
from core.plan import build
from core.solid import has_boolean, proto_set

ROOT = pathlib.Path(__file__).resolve().parent.parent
PRESET = json.loads((ROOT / "examples" / "presets.json").read_text(encoding="utf-8"))["fold_box"]["params"]
BOX = ROOT / "examples" / "fold_box.stl"


def box(**extra):
    return build(BOX, "folded", {**PRESET, "material_kind": "PETG", "autofix": "off", **extra})


def outline(plan):
    return unary_union([Polygon(r[0], r[1:]) for s in plan["slices"] if s["group"] == "F" for pc in s["pieces"] for r in pc["kerfed"]])


def joint(snap_h=7.5):
    f = F.Folded(); f.p = {"snap_h": snap_h, "snap_fit": 0.1}; f.t, f.skin, f.land, f.stop, f.hinged = 2.0, 0.4, 0.4, 0.0, True
    return f


def test_the_seams_of_the_box_click_with_no_part_of_their_own_and_nothing_on_the_face_that_shows():
    plan = box(joint="click")
    walls = [r for s in plan["slices"] for pc in s["pieces"] for r in pc.get("rails", [])]
    said = [w for s in plan["slices"] for w in s["warnings"]]
    assert plan["counts"]["errors"] == 0 and all("without a click joint" in w for w in said)     # a small box: some seams are too short for a bar
    assert {s["group"] for s in plan["slices"]} == {"F"}              # panels only: no clip, nothing loose
    bars = [r for r in walls if min(z for _, z in r["profile"]) > 2.5]            # the bars: off the panel, between their posts
    assert len(bars) >= 6 and len(walls) == 8 * len(bars)             # a click: a wall, the tooth and its ridge; a bar, two posts, two blocks
    assert all(F.CLICK_SPAN[0] + 1 - 1e-3 <= math.dist(r["a"], r["b"]) <= F.CLICK_SPAN[1] + 1 + 1e-3 for r in bars)
    assert outline(box(joint="seam")).symmetric_difference(outline(plan)).area < 1e-6
    feet = [(F.Rail(r["a"], r["b"], r["into"], r["profile"]).foot(), tuple(round(x, 3) for x in r["into"])) for r in walls]
    assert not [1 for i, (a, na) in enumerate(feet) for b, nb in feet[i + 1:] if na != nb and a.intersection(b).area > 1e-3]   # no two seams' walls grow into one


@pytest.mark.parametrize("bend,outward", [(5, True), (30, True), (60, True), (94, True), (100, True), (15, False), (27, False)])
def test_the_tooth_goes_under_the_bar_and_stands_up_behind_it_and_everything_prints_without_support(bend, outward):
    f = joint(); b = math.radians(bend); c = f.click_parts(b, outward)
    # the seam shut: the tooth's panel to the left of the plane the panels meet on (x = 0), the model's inside up
    phi = math.pi - b if outward else math.pi + b; co, si = math.cos(phi / 2), math.sin(phi / 2)
    u = np.array([-si, co]); z = np.array([co, si]); pivot = f.skin if outward else 0.0
    to = lambda q: tuple(u * q[0] + z * (q[1] - pivot))               # noqa: E731
    mirror = lambda g: affinity.scale(g, -1, 1, origin=(0, 0))        # noqa: E731
    bar = mirror(Polygon([to(q) for q in c.bar]))
    edge = ((f.snap_wall(b, outward)[1][0], f.t), (f.land / 2, f.skin)) if outward else ((0, f.t),)      # an outward seam's edge is mitred
    sheet = mirror(Polygon([to(q) for q in ((0, 0), (9, 0), (9, f.t), *edge)]))
    assert bar.bounds[0] == pytest.approx(0, abs=1e-6)                          # the bar's front is the plane: it meets the tooth's wall
    ridges = []
    for _, _, profile in c.teeth:                                               # the tooth in its middle, beside it, and further out
        tooth = Polygon([to(q) for q in profile]).buffer(0)
        assert tooth.intersection(unary_union([bar, sheet])).area < 1e-6        # shut, it cuts into nothing of the other panel
        past = tooth.intersection(Polygon([(0.05, -20), (20, -20), (20, 20), (0.05, 20)]))      # what of it is through the plane
        assert past.area > 2 and past.distance(sheet) > 0.25                    # … and stays clear of its inside face
        ridges.append(max(y for x, y in tooth.exterior.coords if x > bar.bounds[2]) - bar.bounds[1])   # how far it stands up behind the bar
    assert ridges[0] == pytest.approx(F.CLICK_BITE, abs=1e-6)                   # in the middle: it cannot pull out
    assert ridges[1] < 0 and c.teeth[0][1] == F.CLICK_RIDGE / 2 < c.teeth[1][1]  # the ridge is in the middle only: beside it the tooth is under the bar's level
    assert c.thick in F.CLICK_THICK and c.strain <= F.CLICK_STRAIN              # the bar is stretched no more than that letting the tooth past
    assert c.strain == pytest.approx(12 * F.CLICK_BITE * c.thick / (F.CLICK_SPAN[0] - F.CLICK_RIDGE) ** 2)
    assert all(len(p) <= 5 for p in (c.wall, c.post, c.guide)) and c.reach < 12 and f.click_parts(b, outward, room=4.0).reach <= max(3.2, f.click_parts(b, outward, room=0).reach) + 1e-6      # the ramp stays 0.8 mm inside a narrow frame
    for profile in (*(p for _, _, p in c.teeth), c.wall, c.post, c.guide):      # as printed: no underside over 50° from upright
        ring = list(orient(Polygon(profile).buffer(0)).exterior.coords)
        for (x0, z0), (x1, z1) in zip(ring, ring[1:]):
            if x1 - x0 > 1e-9 and max(z0, z1) > f.t + 0.7:                     # faces down, above the sheet and the wall's 0.6 mm lead
                assert math.atan2(x1 - x0, abs(z1 - z0)) <= F.SNAP_LEAN + 1e-6


def test_a_longer_seam_gets_a_longer_and_thicker_bar_at_no_more_strain():
    short, long = joint().click_parts(math.radians(40), True, span=F.CLICK_SPAN[0]), joint().click_parts(math.radians(40), True, span=F.CLICK_SPAN[1])
    assert long.thick > short.thick and max(short.strain, long.strain) <= F.CLICK_STRAIN


def test_every_upright_stands_on_a_ramp_several_times_as_deep_as_the_wall():
    f = joint(); c = f.click_parts(math.radians(40), True); bare = f.click_parts(math.radians(40), True, room=3.0)
    foot = lambda profile: max(x for x, z in profile if z < f.t + 0.1) - min(x for x, z in profile if z < f.t + 0.1)   # noqa: E731
    assert foot(c.post) > 2 * foot(bare.post) and foot(c.wall) > 2 * foot(bare.wall)
    assert Polygon(c.post).area > 1.4 * Polygon(bare.post).area


def test_a_seam_whose_tooth_needs_higher_walls_than_allowed_is_left_plain_and_said():
    assert "raise `snap wall`" in joint(snap_h=4.0).click_parts(math.radians(27), False)
    plan = build(ROOT / "examples" / "fold_test.stl", "folded", {**PRESET, "material_kind": "PETG", "autofix": "off", "joint": "click"})
    said = [w for s in plan["slices"] for w in s["warnings"] if "without a click joint" in w]
    assert any("bends more than 100°" in w for w in said) and plan["counts"]["errors"] == 0


def test_the_click_joint_on_a_cut_sheet_is_an_error_and_the_seams_stay_plain():
    plan = build(BOX, "folded", {"facet": 0, "joint": "click", "material": "card", "thickness": 1, "autofix": "off"})
    assert any("click joint is for printed panels" in e for e in plan["errors"])
    assert not [pc for s in plan["slices"] for pc in s["pieces"] if pc.get("rails")]


@pytest.mark.skipif(not has_boolean(), reason="needs manifold3d to fuse the walls onto the panel")
def test_the_print_file_is_one_closed_solid_with_the_bars_bridged_on(tmp_path):
    files = proto_set(box(joint="click"), tmp_path)
    assert [f.name for f in files if f.suffix == ".stl"] == ["P-1.stl"]        # the panels and nothing else to print
    panel = trimesh.load(tmp_path / "P-1.stl")
    assert panel.is_watertight and len(panel.split(only_watertight=False)) == 1
    assert 4 < panel.bounds[1][2] < 10
