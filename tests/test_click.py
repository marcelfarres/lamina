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


def joint(snap_h=10.5, **more):
    f = F.Folded(); f.p = {"snap_h": snap_h, "snap_fit": 0.1, "click_bite": 1.0, "click_bar": 1.6, "click_deep": 2.4, "click_solid": 0.0, "click_size": 1.0, "click_post": 0.5, "material_kind": "PETG", **more}; f.t, f.skin, f.land, f.stop, f.hinged = 2.0, 0.4, 0.4, 0.0, True
    return f


def test_the_seams_of_the_box_click_with_no_part_of_their_own_and_nothing_on_the_face_that_shows():
    plan = box(joint="click")
    walls = [r for s in plan["slices"] for pc in s["pieces"] for r in pc.get("rails", [])]
    said = [w for s in plan["slices"] for w in s["warnings"]]
    assert plan["counts"]["errors"] == 0 and all("without a click joint" in w for w in said)     # a small box: some seams are too short for a bar
    assert {s["group"] for s in plan["slices"]} == {"F"}              # panels only: no clip, nothing loose
    aloft = [r for r in walls if min(z for _, z in r["profile"]) > 2.5]           # off the panel: the bars, and the fillets under their ends
    bars = [r for r in aloft if math.dist(r["a"], r["b"]) > 10]; fillets = [r for r in aloft if math.dist(r["a"], r["b"]) < 2]
    located = int(next(n for n in plan["notes"] if "locator" in n).split(" seam(s) close")[0].split()[-1])
    assert len(bars) >= 7 and len(fillets) == 6 * len(bars) and len(walls) == 14 * len(bars) - located
    # a click: a wall, the tooth and its ridge; a bar, two posts, two blocks, and a fillet of three steps at each end. A locator: no ridge
    assert all(F.CLICK_SPAN[0] * min(F.CLICK_SMALLER) + 1 - 1e-3 <= math.dist(r["a"], r["b"]) <= F.CLICK_SPAN[1] + 1 + 1e-3 for r in bars)   # a smaller click where a full one does not fit
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
    assert bar.bounds[0] == pytest.approx(F.CLICK_BACK, abs=1e-6)               # the bar's front stands back from the plane: only the panel edges meet
    ridges = []
    for _, _, profile in c.teeth:                                               # the tooth in its middle, beside it, and further out
        tooth = Polygon([to(q) for q in profile]).buffer(0)
        assert tooth.intersection(unary_union([bar, sheet])).area < 1e-6        # shut, it cuts into nothing of the other panel
        past = tooth.intersection(Polygon([(0.05, -20), (20, -20), (20, 20), (0.05, 20)]))      # what of it is through the plane
        assert past.area > 2 and past.distance(sheet) > 0.25                    # … and stays clear of its inside face
        ridges.append(max(y for x, y in tooth.exterior.coords if x > bar.bounds[2]) - bar.bounds[1])   # how far it stands up behind the bar
    assert ridges[0] == pytest.approx(c.bite, abs=1e-6) and F.CLICK_LOW <= c.bite <= f.p["click_bite"]   # in the middle: it cannot pull out
    assert ridges[1] < 0 and c.teeth[0][1] == F.CLICK_RIDGE / 2 < c.teeth[1][1]  # the ridge is in the middle only: beside it the tooth is under the bar's level
    assert F.CLICK_THIN <= c.thick <= f.p["click_bar"] and c.strain <= F.CLICK_STRAIN["PETG"] + 1e-9   # the bar is stretched no more than PETG takes letting the tooth past
    free = F.CLICK_SPAN[0] - F.CLICK_RIDGE - (c.fillet[-1][0] if c.fillet else 0) - 2 * c.support
    assert c.strain == pytest.approx(12 * c.bite * c.thick / free ** 2)
    runs = [length for length, _ in c.fillet]; deep = [max(z for _, z in prof) - min(z for _, z in prof) for _, prof in c.fillet]
    assert len(runs) == 3 and all(b - a <= 0.3 + 1e-9 for a, b in zip([0, *runs], runs)) and deep == sorted(deep, reverse=True)   # a fillet that prints: 0.3 mm a step
    assert all(len(p) <= 5 for p in (c.wall, c.post, c.guide)) and c.reach < 12.5 and f.click_parts(b, outward, room=4.0).reach <= max(3.2, f.click_parts(b, outward, room=0).reach) + 1e-6      # the ramp stays 0.8 mm inside a narrow frame
    for profile, lean in [*((p, F.CLICK_LEAN) for _, _, p in c.teeth), *((p, F.SNAP_LEAN) for p in (c.wall, c.post, c.guide))]:   # as printed: no underside steeper than prints
        ring = list(orient(Polygon(profile).buffer(0)).exterior.coords)
        for (x0, z0), (x1, z1) in zip(ring, ring[1:]):
            if x1 - x0 > 1e-9 and max(z0, z1) > f.t + 0.7:                     # faces down, above the sheet and the wall's 0.6 mm lead
                assert math.atan2(x1 - x0, abs(z1 - z0)) <= lean + 1e-6


def test_a_longer_seam_gets_a_longer_and_thicker_bar_at_no_more_strain():
    short, long = joint().click_parts(math.radians(40), True, span=F.CLICK_SPAN[0]), joint().click_parts(math.radians(40), True, span=F.CLICK_SPAN[1])
    assert long.thick > short.thick and max(short.strain, long.strain) <= F.CLICK_STRAIN["PETG"]


def test_a_short_bar_keeps_its_thickness_and_gets_a_lower_tooth_and_one_that_cannot_bend_even_that_far_is_said():
    b = math.radians(40); at = lambda span, **more: joint(click_bar=1.2, **more).click_parts(b, True, span=span)   # noqa: E731
    long, short = at(F.CLICK_SPAN[1]), at(F.CLICK_SPAN[0])
    assert long.thick == short.thick == 1.2 and long.bite == 1.0 and short.bite == F.CLICK_LOW   # his round 8 bar broke: a lower tooth, not a stretched bar
    assert at(F.CLICK_SPAN[1], material_kind="PLA").bite < long.bite                # a stiffer material: a lower tooth too
    assert joint(click_bar=3.0).click_parts(b, True).thick < 3.0                    # a bar too thick for even the lowest tooth is made thinner
    assert "cannot bend far enough" in at(F.CLICK_SPAN[0], material_kind="PLA")


def test_bar_support_takes_only_what_the_bar_can_still_stretch_and_the_fillet_comes_first():
    b = math.radians(40); at = lambda solid: joint(click_bar=1.2, click_solid=solid).click_parts(b, True, span=F.CLICK_SPAN[1])   # noqa: E731
    free, held, most = at(0.0), at(0.5), at(1.0)
    assert free.support == 0 and 0 < held.support <= most.support < (F.CLICK_SPAN[1] - F.CLICK_NOSE - F.CLICK_GAP) / 2   # never as far as asked: the bar would stretch too far
    assert all(c.fillet and c.fillet[-1][0] == pytest.approx(F.CLICK_FILLET) for c in (free, held, most))
    assert max(c.strain for c in (free, held, most)) <= F.CLICK_STRAIN["PETG"] + 1e-9 and held.press > free.press > 0
    plain, solid = box(joint="click", click_solid=0.0), box(joint="click", click_solid=1.0)
    posts = lambda plan: sum(math.dist(r["a"], r["b"]) * Polygon(r["profile"]).area for s in plan["slices"] for pc in s["pieces"] for r in pc["rails"])   # noqa: E731
    assert posts(solid) > posts(plain) and solid["counts"]["errors"] == 0           # the posts have grown in under the bar, as far as it lets them


def test_the_whole_click_goes_with_its_size_and_the_posts_with_theirs():
    b = math.radians(40); one, two = joint().click_parts(b, True, span=24.0), joint(click_size=2.0, snap_h=20).click_parts(b, True, span=48.0)
    assert two.thick == pytest.approx(2 * one.thick) and two.teeth[1][1] == 2 * one.teeth[1][1] == F.CLICK_NOSE and two.strain == pytest.approx(one.strain)
    foot = lambda c: max(x for x, z in c.post if z < 2.1) - min(x for x, z in c.post if z < 2.1)   # noqa: E731
    assert foot(joint(click_post=1.0).click_parts(b, True)) > foot(joint().click_parts(b, True)) + 0.5
    plan = build(ROOT / "examples" / "fold_test.stl", "folded", {**PRESET, "material_kind": "PETG", "autofix": "off", "joint": "click", "click_size": 0.7})
    short = [w for s in plan["slices"] for w in s["warnings"] if "the seam is too short" in w]
    assert int(short[0].split()[0]) < 8                     # smaller clicks fit seams the full size does not


def test_a_lid_closes_its_seams_in_one_motion_so_it_gets_one_click_on_the_seam_opposite_its_fold(monkeypatch):
    seen = []; click = F.Folded.click       # the box's lid: a hexagon of 25 mm edges on one fold, five seams that all close as it folds down

    def watched(self, j, k, sides, convex):
        had = len(sides[0].sl.rails); out = click(self, j, k, sides, convex); m = self.mesh
        if max(m.face_normals[s.f][2] for s in sides) > 0.99:                   # a seam of the lid
            seen.append((self.far(k, sides), len(sides[0].sl.rails) > had, m.vertices[m.face_adjacency_edges[k]].mean(axis=0), j in self.located))
        return out
    monkeypatch.setattr(F.Folded, "click", watched)
    assert box(joint="click")["counts"]["errors"] == 0 and len(seen) == 5
    far, placed, mid, located = seen[0]
    assert placed and not located and far == max(f for f, *_ in seen) > 40     # the click: on the seam across the lid from its fold
    assert all(np.linalg.norm(mid - m) > 20 for _, _, m, _ in seen[1:])
    assert all(loc for _, placed, _, loc in seen[1:] if placed) and sum(p for _, p, _, _ in seen) >= 3   # the others: locators, to go in with it


def test_every_upright_stands_on_a_ramp_several_times_as_deep_as_the_wall():
    f = joint(); c = f.click_parts(math.radians(40), True); bare = f.click_parts(math.radians(40), True, room=3.0)
    foot = lambda profile: max(x for x, z in profile if z < f.t + 0.1) - min(x for x, z in profile if z < f.t + 0.1)   # noqa: E731
    assert foot(c.post) > 2 * foot(bare.post) and foot(c.wall) > 2 * foot(bare.wall)
    assert Polygon(c.post).area > 1.4 * Polygon(bare.post).area


def test_a_click_beside_a_fold_that_would_close_onto_it_takes_a_shorter_bar():
    # the test piece: two of its clicks end beside a face that folds or closes over their panel. With the long
    # bar their end posts stood in its way and the fold stopped short (his print, 2026-11-17)
    plan = build(ROOT / "examples" / "fold_test.stl", "folded", {**PRESET, "material_kind": "PETG", "autofix": "off", "joint": "click"})
    rails = [r for s in plan["slices"] for pc in s["pieces"] for r in pc["rails"]]
    bars = sorted(round(math.dist(r["a"], r["b"]) - 1) for r in rails if len(r["profile"]) == 4 and min(z for _, z in r["profile"]) > 2.5 and math.dist(r["a"], r["b"]) > 10)
    assert bars[-1] == 24 and 16 in bars and len(rails) == 14 * len(bars) - sum(" locator" in n for n in plan["notes"])   # the clicks beside a fold: shorter bars


def test_a_piece_on_no_fold_gets_two_clicks_so_it_cannot_swing_out_and_the_rule_can_be_turned_off(monkeypatch):
    lid = [[a, b] for _, _, a, b, *_ in box(joint="seam")["edges3d"] if min(a[2], b[2]) > 22]    # the lid's six edges, all cut: a piece of its own
    seen = []; click = F.Folded.click

    def watched(self, j, k, sides, convex):
        had = len(sides[0].sl.rails); out = click(self, j, k, sides, convex)
        if max(self.mesh.face_normals[s.f][2] for s in sides) > 0.99:                 # a seam of the lid
            seen.append("locator" if j in self.located else "click" if len(sides[0].sl.rails) > had else "none")
        return out
    monkeypatch.setattr(F.Folded, "click", watched)
    assert len(lid) == 6 and box(joint="click", seams=lid)["counts"]["errors"] == 0 and len(seen) == 6
    assert seen.count("click") == 2 and seen.count("locator") >= 1            # put in place it closes six seams: two clicks, so it cannot swing about one
    seen.clear(); box(joint="click", seams=lid, click_together=False)
    assert "locator" not in seen and seen.count("click") >= 3                   # off: every seam that has room its own click, all at once


def test_every_piece_of_the_lamp_is_held_and_a_narrow_frame_gets_a_smaller_click(monkeypatch):
    # his v9 lamp: the loose triangle's two seams both lost their click (a frame 0.07 mm too narrow, a click placed
    # before it next door), and nothing held it. Now a seam a click does not fit gets a smaller one, and the seams
    # between two panels are placed first
    lamp = json.loads((ROOT / "examples" / "presets.json").read_text(encoding="utf-8"))["fold_lamp"]["params"]
    got = {}; click = F.Folded.click

    def watched(self, j, k, sides, convex):
        had = len(sides[0].sl.rails); out = click(self, j, k, sides, convex)
        got[j] = (sides[0].sl is not sides[1].sl, len(sides[0].sl.rails) > had); return out
    monkeypatch.setattr(F.Folded, "click", watched)
    plan = build(ROOT / "examples" / "fold_lamp.stl", "folded", {**lamp, "material_kind": "PETG", "autofix": "off", "joint": "click"})
    said = [str(w) for s in plan["slices"] for w in s["warnings"]]
    assert plan["counts"]["errors"] == 0 and not [w for w in said if "has no click joint on any of its seams" in w]
    assert [placed for between, placed in got.values() if between] == [True, True]   # the loose triangle: both its seams
    assert sum(placed for _, placed in got.values()) >= 11 and any("made smaller to fit" in n for n in plan["notes"])


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
    assert 4 < panel.bounds[1][2] < 12
