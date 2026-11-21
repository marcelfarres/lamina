"""The snap joint of printed folded panels: a wall on the inside of each panel at a seam and a printed clip over the
two. Real core.plan.build() and core.solid runs on the bundled printed examples, and the joint's own geometry put
together the way a shut seam puts it."""
import json
import math
import pathlib

import numpy as np
import pytest
import trimesh
from shapely import affinity
from shapely.geometry import Polygon
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


def test_every_seam_of_the_box_gets_two_walls_and_a_clip_and_nothing_is_reported():
    plan = box(joint="snap")
    panels = [s for s in plan["slices"] if s["group"] == "F"]; clips = [s for s in plan["slices"] if s["group"] == "J"]
    walls = [r for s in panels for pc in s["pieces"] for r in pc.get("rails", [])]
    assert plan["counts"]["errors"] == 0 and not [w for s in plan["slices"] for w in s["warnings"]]
    assert len(clips) >= 11 and len(walls) == 2 * len(clips)          # 11 seams, a clip on two walls
    assert {s["label"][:2] for s in clips} == {"K-"} and all(s["thickness"] == F.SNAP_CLIP for s in clips)
    for r in walls:                                                   # a wall stands on the panel, as long as a clip is wide and a little more
        assert math.dist(r["a"], r["b"]) == pytest.approx(F.SNAP_LONG, abs=1e-3) and min(z for _, z in r["profile"]) < 2 < max(z for _, z in r["profile"])


def test_nothing_of_the_joint_is_on_the_face_that_shows():
    """Asked for: no mechanism on the visible side. The panels' outline and every hole in it are those of a plain seam."""
    plain, snap = outline(box(joint="seam")), outline(box(joint="snap"))
    assert plain.symmetric_difference(snap).area < 1e-6


@pytest.mark.parametrize("bend,outward", [(5, True), (30, True), (60, True), (94, True), (100, True), (15, False), (40, False)])
def test_the_two_walls_of_a_shut_seam_meet_on_one_plane_and_the_clip_holds_both(bend, outward):
    f = F.Folded(); f.p = {"snap_h": next(q.default for q in F.Folded.params if q.name == "snap_h"), "snap_fit": 0.1}; f.t, f.skin, f.land, f.stop, f.hinged = 2.0, 0.4, 0.4, 0.0, True
    b = math.radians(bend); profile, at, up, back, lean = f.snap_wall(b, outward)
    assert lean <= F.SNAP_LEAN + 1e-9                                 # prints without support
    # the seam shut: panel A to the left of the plane the panels meet on (x = 0), the model's inside up. An outward
    # seam turns about the top of its skin (what the mitre is cut for), an inward one about its outer edge
    phi = math.pi - b if outward else math.pi + b; c, s = math.cos(phi / 2), math.sin(phi / 2)
    u = np.array([-s, c]); z = np.array([c, s]); pivot = f.skin if outward else 0.0
    to = lambda q: tuple(u * q[0] + z * (q[1] - pivot))               # noqa: E731
    wall = Polygon([to(q) for q in profile]); mirror = lambda g: affinity.scale(g, -1, 1, origin=(0, 0))   # noqa: E731
    front = [to(tuple(at + up * h))[0] for h in (0.0, 3.0, 6.0)]
    assert max(abs(x) for x in front) < 1e-6                          # its front is that plane: the two walls lie face to face
    assert wall.bounds[2] < 1e-6                                      # … and nothing of it is past the plane
    sheet = Polygon([to(q) for q in ((0, f.t), (9, f.t), (9, 0), (0.5, 0))])
    clip = affinity.translate(f.snap_clip(), 0, to(tuple(at))[1])
    assert clip.intersection(unary_union([wall, mirror(wall), sheet, mirror(sheet)])).area < 1e-6    # it goes on without cutting into anything
    hook = Polygon([(-9, to(tuple(at))[1] + F.SNAP_LEDGE - 0.6), (0, to(tuple(at))[1] + F.SNAP_LEDGE - 0.6), (0, to(tuple(at))[1] + F.SNAP_LEDGE), (-9, to(tuple(at))[1] + F.SNAP_LEDGE)])
    reach = clip.intersection(hook).bounds[2]                         # how far the left leg's hook comes in under the ledge
    back_face = -F.SNAP_WALL                                          # the wall's back, where the groove is cut into it
    assert back_face < reach < back_face + F.SNAP_GROOVE              # the hook is in the groove: it cannot lift off
    plate = f.snap_clip(whole=True).difference(f.snap_clip())
    assert plate.area > 2 * F.SNAP_WALL * (F.SNAP_LEDGE - 1)                     # the plate fills the space between the legs: they cannot spread
    assert f.snap_clip(whole=True).area > F.CLIP_AREA > 34                       # it stands on more than what came off the bed in his first print


def test_a_seam_bent_too_far_for_a_wall_to_print_is_left_plain_and_said():
    plan = build(ROOT / "examples" / "fold_test.stl", "folded", {**PRESET, "material_kind": "PETG", "autofix": "off", "joint": "snap"})
    said = [w for s in plan["slices"] for w in s["warnings"] if "bend past what the clip (snap) joint can do" in w]
    assert said and "seam 13: it bends 104° outward" in said[0] and "Glue them" in said[0] and plan["counts"]["errors"] == 0


def test_the_snap_joint_on_a_cut_sheet_is_an_error_and_the_seams_stay_plain():
    plan = build(BOX, "folded", {"facet": 0, "joint": "snap", "material": "card", "thickness": 1, "autofix": "off"})
    assert any("snap joint is for printed panels" in e for e in plan["errors"])
    assert not [s for s in plan["slices"] if s["group"] == "J"] and not [pc for s in plan["slices"] for pc in s["pieces"] if pc.get("rails")]


def test_a_clip_too_small_to_print_well_is_said_with_the_wall_height_that_cures_it():
    said = lambda plan: [w for s in plan["slices"] for w in s["warnings"] if "come off the bed" in w]   # noqa: E731
    low = box(joint="snap", snap_h=6.0)
    assert said(low) and "Set `snap wall` to" in said(low)[0] and not said(box(joint="snap"))
    cure = float(said(low)[0].split("Set `snap wall` to ")[1].split(" mm")[0])
    assert not said(box(joint="snap", snap_h=cure))


@pytest.mark.skipif(not has_boolean(), reason="needs manifold3d to fuse the walls onto the panel")
def test_the_print_files_are_closed_solids_with_the_walls_fused_on(tmp_path):
    plan = box(joint="snap"); files = proto_set(plan, tmp_path)
    panel = trimesh.load(next(f for f in files if f.name == "P-1.stl")); clip = trimesh.load(next(f for f in files if f.name.startswith("K-") and f.suffix == ".stl"))
    assert panel.is_watertight and len(panel.split(only_watertight=False)) == 1
    assert 8 < panel.bounds[1][2] < 12.5                              # 2 mm of panel and the walls on it, leaning
    assert panel.volume > trimesh.load(next(f for f in proto_set(box(joint="seam"), tmp_path / "plain") if f.name == "P-1.stl")).volume + 200   # 24 walls
    assert clip.is_watertight and clip.bounds[1][2] == pytest.approx(F.SNAP_CLIP)
    bed = clip.section(plane_origin=[0, 0, 0.1], plane_normal=[0, 0, 1]).to_2D()[0].area
    top = clip.section(plane_origin=[0, 0, F.SNAP_CLIP - 0.1], plane_normal=[0, 0, 1]).to_2D()[0].area
    assert bed > 1.3 * top                                                       # it stands on its plate; above it, the U
