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


def test_every_seam_of_the_box_clicks_with_no_part_of_its_own_and_nothing_on_the_face_that_shows():
    plan = box(joint="click")
    walls = [r for s in plan["slices"] for pc in s["pieces"] for r in pc.get("rails", [])]
    assert plan["counts"]["errors"] == 0 and not [w for s in plan["slices"] for w in s["warnings"]]
    assert {s["group"] for s in plan["slices"]} == {"F"}              # panels only: no clip, nothing loose
    assert len(walls) == 11 * 7                                       # a seam: a wall and a tooth; two posts, a bar, two guides
    bars = [r for r in walls if min(z for _, z in r["profile"]) > 2.5]            # the bars: off the panel, between their posts
    assert len(bars) == 11 and all(math.dist(r["a"], r["b"]) == pytest.approx(F.CLICK_SPAN + 1, abs=1e-3) for r in bars)
    assert outline(box(joint="seam")).symmetric_difference(outline(plan)).area < 1e-6


@pytest.mark.parametrize("bend,outward", [(5, True), (30, True), (60, True), (94, True), (100, True), (15, False), (27, False)])
def test_the_tooth_goes_under_the_bar_and_stands_up_behind_it_and_everything_prints_without_support(bend, outward):
    f = joint(); b = math.radians(bend); wall, nose, post, bar, guide, reach = f.click_parts(b, outward)
    # the seam shut: the tooth's panel to the left of the plane the panels meet on (x = 0), the model's inside up
    phi = math.pi - b if outward else math.pi + b; c, s = math.cos(phi / 2), math.sin(phi / 2)
    u = np.array([-s, c]); z = np.array([c, s]); pivot = f.skin if outward else 0.0
    to = lambda q: tuple(u * q[0] + z * (q[1] - pivot))               # noqa: E731
    mirror = lambda g: affinity.scale(g, -1, 1, origin=(0, 0))        # noqa: E731
    tooth = Polygon([to(q) for q in nose]).buffer(0); Bbar = mirror(Polygon([to(q) for q in bar]))
    edge = ((f.snap_wall(b, outward)[1][0], f.t), (f.land / 2, f.skin)) if outward else ((0, f.t),)      # an outward seam's edge is mitred
    sheet = mirror(Polygon([to(q) for q in ((0, 0), (9, 0), (9, f.t), *edge)]))
    assert tooth.intersection(unary_union([Bbar, sheet])).area < 1e-6           # shut, it cuts into nothing of the other panel
    past = tooth.intersection(Polygon([(0.05, -20), (20, -20), (20, 20), (0.05, 20)]))      # what of it is through the plane
    assert past.area > 2 and past.distance(sheet) > 0.25                        # … and stays clear of its inside face
    assert Bbar.bounds[0] == pytest.approx(0, abs=1e-6)                         # the bar's front is the plane: it meets the tooth's wall
    behind = max(y for x, y in tooth.exterior.coords if x > Bbar.bounds[2])     # the tooth's top, past the back of the bar
    assert behind - Bbar.bounds[1] == pytest.approx(F.CLICK_BITE, abs=1e-6)     # it stands this far up behind the bar: it cannot pull out
    assert min(x for x, y in tooth.exterior.coords if y > Bbar.bounds[1] + 0.05 and x > 0.5) > Bbar.bounds[2]   # … with room behind the bar
    assert max(q[1] for q in post) - min(q[1] for q in post) <= f.p["snap_h"] + 0.5 and reach < 3.0
    assert 6 * F.CLICK_BITE * F.CLICK_BAR[1] / F.CLICK_SPAN ** 2 < 0.025        # the bar bends under 2.5 % letting the tooth past
    for profile in (nose, post, guide):                                         # as printed: no underside over 50° from upright
        ring = list(orient(Polygon(profile).buffer(0)).exterior.coords)
        for (x0, z0), (x1, z1) in zip(ring, ring[1:]):
            if x1 - x0 > 1e-9 and max(z0, z1) > f.t + 0.7:                     # faces down, above the sheet and the wall's 0.6 mm lead
                assert math.atan2(x1 - x0, abs(z1 - z0)) <= F.SNAP_LEAN + 1e-6


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
    assert 4 < panel.bounds[1][2] < 9
