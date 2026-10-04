"""Real core.plan.build() runs across all five construction modes on tiny examples (autofix="off", so
nothing is silently added or removed behind the test's back): the slice count matches exactly what the
mode's own parameters ask for, and a shape with no reason to fail comes back with zero errors.
"""
import json
import pathlib

import numpy as np
import pytest
import trimesh

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# (model, mode, params, expected slice count)
MODE_CASES = [
    ("cube", "stacked", {"distribution": "count", "count": 6}, 6),
    ("cube", "interlocked", {"nx": 3, "ny": 4}, 3 + 4),
    ("cylinder", "radial", {"count": 5, "ring_count": 3}, 2 * 5 + 3),
    ("cube", "curve", {"count": 6, "spines": 1}, 6 + 1),
]


@pytest.mark.parametrize("model, mode, params, expected", MODE_CASES, ids=[c[1] for c in MODE_CASES])
def test_slice_count_matches_params_and_clean(model, mode, params, expected):
    plan = build(EXAMPLES / f"{model}.stl", mode, {**params, "autofix": "off"})
    assert plan["counts"]["slices"] == expected
    assert plan["counts"]["errors"] == 0


def test_folded_separate_panel_count_equals_face_count():
    """separate=True + facet=0 (no decimation) makes every triangle its own panel — panel count is
    exactly the mesh's own face count, folded's version of "the count the params ask for"."""
    mesh = trimesh.load(EXAMPLES / "cube.stl", force="mesh")
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "separate": True, "joint": "laced", "autofix": "off"})
    panels = [s for s in plan["slices"] if s["group"] == "F"]
    assert len(panels) == len(mesh.faces)
    assert plan["counts"]["errors"] == 0


def test_folded_facet_zero_is_still_capped(monkeypatch):
    """facet=0 ("keep every triangle") used to make target_faces return 0, which skipped the face-count guard and
    sent the whole mesh into the unfolder — a scanned model then never came back. The cap is on the face count
    itself now, so it fires whichever way the count was asked for. Lowered here so the cube trips it."""
    from core.modes import folded
    monkeypatch.setattr(folded, "MAX_FACES", 8)                  # cube.stl has 12 faces
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "autofix": "off"})
    assert any("this can unfold" in e for e in plan["errors"])
    assert [s for s in plan["slices"] if s["group"] == "F"]      # degraded to a preview, did not stall or crash


def test_radial_several_axes_are_tied_together_by_a_spine():
    """A fan per lobe — the snowman's three balls — with one spine through every axis. The spine is cut whole, runs
    the height of the model and every ring slots onto it: that is what stops one lobe coming off the next. The fan
    plane the spine lies on is not cut a second time as half-slices, so each axis keeps 2 × (count − 1) of them."""
    h = float(trimesh.load(EXAMPLES / "snowman.stl", force="mesh").extents[2])
    axes = [[[0, 0, -h / 2], [0, 0, -h / 6]], [[0, 0, -h / 6], [0, 0, h / 6]], [[0, 0, h / 6], [0, 0, h / 2]]]
    plan = build(EXAMPLES / "snowman.stl", "radial",
                 {"axes": axes, "count": 4, "spine": 1, "ring_count": 2, "thickness": 3, "autofix": "off"})
    for i in (1, 2, 3):
        assert len([s for s in plan["slices"] if s["label"].startswith(f"R{i}-")]) == 2 * (4 - 1)
    spine = [s for s in plan["slices"] if s["label"] == "SP-1"]
    assert len(spine) == 1
    tall = max(pc["bbox"][3] - pc["bbox"][1] for pc in spine[0]["pieces"])
    assert tall > 0.9 * h                                  # one part through all three balls, not one per ball
    rings = [s for s in plan["slices"] if s["label"].startswith("Z-")]
    assert len(rings) == 3 * 2
    assert all("SP-1" in s["engages"] for s in rings)

    # the 3D view draws and drags the axes the plan actually used, so they have to come back with it
    assert len(plan["axes3d"]) == len(axes)
    for got, want in zip(plan["axes3d"], axes):
        assert all(abs(a - b) < 1e-6 for end, w in zip(got, want) for a, b in zip(end, w))
    plain = build(EXAMPLES / "snowman.stl", "radial", {"count": 4, "ring_count": 2, "autofix": "off"})
    assert len(plain["axes3d"]) == 1              # the single default axis is draggable before `axes` is filled in


def world_pts(s):
    """Every outline point of a slice's pieces, in world coordinates."""
    out = []
    for pc in s["pieces"]:
        for fc in pc["facets"]:
            M = np.array(fc["M"])
            for region in fc["rings"]:
                for ring in region:
                    pts = np.array(ring)
                    out.append((M @ np.c_[pts, np.zeros(len(pts)), np.ones(len(pts))].T).T[:, :3])
    return np.concatenate(out)


def test_radial_axes_side_by_side_each_keep_to_their_own_lobe():
    """The dumbbell: an axis through each ball, parallel, across the neck. Each axis owns the part of the model
    nearest to it, so every ring and half-slice of one ball stops at the middle of the neck, nothing of one ball is
    slotted onto anything of the other, the spine — automatic, since there are two axes — is one part through both,
    and every ring is on it. Clean with the checks on and autofix off."""
    axes = [[[-72, 0, -108], [72, 0, -108]], [[-72, 0, 108], [72, 0, 108]]]
    plan = build(EXAMPLES / "dumbbell.stl", "radial", {"axes": axes, "count": 8, "ring_count": 4, "thickness": 3, "autofix": "off"})
    assert plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    by = {s["label"]: s for s in plan["slices"]}
    lobe = lambda s: np.sign(s["M"][2][3])                        # rings and half-slices sit on their axis: z = ±108
    for s in plan["slices"]:
        if s["label"] == "SP-1":
            continue
        assert (world_pts(s)[:, 2] * lobe(s) >= -3).all(), s["label"]      # nothing past the neck's middle (a hair of clearance)
        assert all(e == "SP-1" or lobe(by[e]) == lobe(s) for e in s["engages"]), s["label"]
    spine = by["SP-1"]
    assert len(spine["pieces"]) == 1 and np.ptp(world_pts(spine)[:, 2]) > 0.9 * 360
    assert all("SP-1" in s["engages"] for s in plan["slices"] if s["label"].startswith("Z-"))


def test_radial_axes_meeting_at_an_angle_share_the_plane_they_lie_in():
    """A snowman with an axis per ball, each tilted to its ball and meeting the next at the waist — not parallel,
    but on one plane: that plane is the spine, every fan starts on it, and the lobes meet along the surface halfway
    between their axes. Clean with autofix off."""
    axes = [[[6, 0, -171], [15, 0, -21]], [[15, 0, -21], [33, 0, 84]], [[33, 0, 84], [42, 0, 171]]]
    plan = build(EXAMPLES / "snowman.stl", "radial", {"axes": axes, "count": 4, "ring_count": 2, "thickness": 3, "autofix": "off"})
    assert plan["counts"]["errors"] == 0
    assert [s["label"] for s in plan["slices"] if s["label"].startswith("SP-")] == ["SP-1"]
    for i in (1, 2, 3):
        assert len([s for s in plan["slices"] if s["label"].startswith(f"R{i}-")]) == 2 * (4 - 1)
    assert all("SP-1" in s["engages"] for s in plan["slices"] if s["label"].startswith("Z-"))


def test_radial_axes_at_right_angles_work_and_the_fix_keeps_them_on_their_lobes():
    """The dumbbell with its axes at right angles: across the lower ball along x, up the upper ball along z. They
    share the plane y = 0, so it slices clean with one spine through both. Turn the upper one to y and no plane
    holds both; the one-click fix keeps each axis on its own ball (centre and length unchanged) and turns it back
    into a common plane — exactly the layout above, clean again. The fix used to project the ends onto the best-fit
    plane, which collapsed the x axis to a point."""
    base = {"count": 8, "ring_count": 4, "thickness": 3, "autofix": "off"}
    good = [[[-72, 0, -108], [72, 0, -108]], [[0, 0, 36], [0, 0, 180]]]
    plan = build(EXAMPLES / "dumbbell.stl", "radial", {**base, "axes": good})
    assert plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    assert [s["label"] for s in plan["slices"] if s["label"].startswith("SP-")] == ["SP-1"]
    skew = build(EXAMPLES / "dumbbell.stl", "radial", {**base, "axes": [good[0], [[0, -72, 108], [0, 72, 108]]]})
    fixed = skew["fixes"][0]["options"][0]["set"]["axes"]
    for (a, b), (c, d) in zip(fixed, good):                               # exactly the working layout, end for end
        assert np.allclose(a, c, atol=0.5) and np.allclose(b, d, atol=0.5), (fixed, good)
        assert abs(float(np.linalg.norm(np.subtract(b, a))) - 144) < 0.5  # every axis keeps its length
    assert np.allclose(np.mean(fixed[1], axis=0), [0, 0, 108], atol=0.5)  # …and stays on its ball
    again = build(EXAMPLES / "dumbbell.stl", "radial", {**base, "axes": fixed})
    assert again["counts"]["errors"] == 0 and again["counts"]["warnings"] == 0


def test_radial_a_lobe_between_two_others_reaches_the_spine_through_the_neck(tmp_path):
    """Three balls on a neck, a parallel axis through each: the middle ball's rings have no side of their own and
    reach the spine through a neighbour. Its rings near the axis go down the neck at no cost; its edge rings would
    have to cut the neighbour's cap off the spine, so they stay off it and are held by their own half-slices. The
    spine stays one piece, every lobe is on it, and the plan has no error — this used to report the spine cut into
    three loose regions."""
    from trimesh.creation import icosphere, cylinder
    m = trimesh.boolean.union([icosphere(4, 70).apply_translation([0, 0, z]) for z in (-160, 0, 160)]
                              + [cylinder(radius=28, height=320, sections=64)])
    path = tmp_path / "triple.stl"; m.export(path)
    axes = [[[-70, 0, z], [70, 0, z]] for z in (-160, 0, 160)]
    plan = build(path, "radial", {"axes": axes, "count": 8, "ring_count": 4, "thickness": 3, "autofix": "off"})
    assert plan["counts"]["errors"] == 0
    spine = next(s for s in plan["slices"] if s["label"] == "SP-1")
    assert len(spine["pieces"]) == 1
    rings = {s["label"]: s for s in plan["slices"] if s["label"].startswith("Z-")}
    on = {l for l, s in rings.items() if "SP-1" in s["engages"]}
    lobe = lambda l: (int(l[2:]) - 1) // 4                        # four rings per axis, numbered straight through
    assert {lobe(l) for l in on} == {0, 1, 2}                    # every ball tied to the spine
    assert on >= {"Z-6", "Z-7"} and not on & {"Z-5", "Z-8"}       # the middle ball: inner rings on, edge rings off


def test_radial_axes_on_no_single_plane_are_refused_with_a_fix():
    """No flat sheet passes through skew axes, so nothing could join one fan to the next: an error, and a one-click
    fix that puts every axis end on the plane nearest to all of them — applying it gives a plan with a spine."""
    axes = [[[0, 0, -80], [0, 0, 0]], [[-40, 30, 60], [40, 30, 60]]]
    plan = build(EXAMPLES / "snowman.stl", "radial", {"axes": axes, "count": 4, "ring_count": 2, "autofix": "off"})
    assert any("not on one plane" in e for e in plan["errors"])
    assert not [s for s in plan["slices"] if s["label"].startswith("SP-")]
    fix = plan["fixes"][0]["options"][0]
    flat = build(EXAMPLES / "snowman.stl", "radial", {"axes": fix["set"]["axes"], "count": 4, "ring_count": 2, "autofix": "off"})
    assert not any("plane" in e for e in flat["errors"])
    assert [s["label"] for s in flat["slices"] if s["label"].startswith("SP-")] == ["SP-1"]


def test_radial_lobes_meet_at_a_flat_plane_you_can_move():
    """Neighbouring lobes are parted by a flat plane between their axes — through the middle of the axes' closest
    points, facing centre to centre — carried in the plan as B-1-2 so the 3D view can show it and the per-slice
    offset moves it: raised 25 mm, the lower ball's half-slices reach 25 mm higher."""
    axes = [[[0.7, -2, -168], [0.7, -2, -5.7]], [[16.8, 3.6, -5.7], [16.8, 3.6, 97.6]], [[36.6, 10.4, 97.6], [36.6, 10.4, 168]]]
    base = {"axes": axes, "count": 6, "ring_count": 3, "thickness": 3, "autofix": "off"}
    plan = build(EXAMPLES / "snowman.stl", "radial", base)
    labels = [b["label"] for b in plan["bounds3d"]]
    assert labels == ["B-1-2", "B-2-3"]                             # the plane between the first and last ball would sit inside the middle one
    M = np.array(plan["bounds3d"][0]["M"])
    assert abs(M[2, 3] + 5.7) < 1e-6 and M[2, 2] > 0.98               # at the waist, facing up the stack
    top = lambda p: max(world_pts(s)[:, 2].max() for s in p["slices"] if s["label"].startswith("R1-"))
    raised = build(EXAMPLES / "snowman.stl", "radial", {**base, "offset": {"B-1-2": 25}})
    assert abs((top(raised) - top(plan)) - 25) < 1.5
    assert raised["counts"]["errors"] == 0


def test_radial_spine_slot_reaches_the_spines_edge_past_a_lobe():
    """Three vertical axes side by side up a leaning snowman (the bundled preset): at the height of a middle ring the
    spine's material runs on past that ring's lobe. Its slot for the ring has to run on to the spine's own edge —
    stopped at the lobe boundary it is a slit inside the sheet, and the insertion check refuses it."""
    axes = [[[0.7, -2, -168], [0.7, -2, -5.7]], [[16.8, 3.6, -5.7], [16.8, 3.6, 97.6]], [[36.6, 10.4, 97.6], [36.6, 10.4, 168]]]
    plan = build(EXAMPLES / "snowman.stl", "radial", {"axes": axes, "count": 6, "ring_count": 3, "thickness": 3, "autofix": "off"})
    assert plan["counts"]["errors"] == 0, [f"{s['label']}: {e}" for s in plan["slices"] for e in s["errors"]][:3]
    assert all("SP-1" in s["engages"] for s in plan["slices"] if s["label"].startswith("Z-"))


def test_folded_panels_keep_an_open_surface_instead_of_closing_it(tmp_path):
    """A clothing pattern, a mask, a shell with a neck hole is the input for folded panels, not a broken solid.
    Mending ran before anything looked at the mesh and closed exactly these into solids; now the surface is panelled
    as it is, every triangle of it surviving."""
    ball = trimesh.creation.icosphere(subdivisions=2, radius=40)
    open_mesh = trimesh.Trimesh(ball.vertices, ball.faces[ball.triangles_center[:, 2] <= 25], process=True)
    assert not open_mesh.is_watertight
    path = tmp_path / "open.stl"
    open_mesh.export(path)

    plan = build(path, "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    assert any("open surface" in n for n in plan["notes"])
    assert not any("remesh" in n for n in plan["notes"])
    assert plan["counts"]["faces"] == len(open_mesh.faces)      # nothing was filled in behind the panels' back
    assert [s for s in plan["slices"] if s["group"] == "F"]


def test_size_then_scale_multiply():
    """size sets the target, scale multiplies it: asked for 30 mm across at scale 0.5, the model comes out 15 mm."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "size": [30, 0, 0], "scale": 0.5, "autofix": "off"})
    assert abs(plan["bbox"][0] - 15) < 1e-6


def test_stacked_cube_is_a_whole_cube_and_a_tilted_one_is_offered_square(tmp_path):
    """Reported: a 100 mm cube stacked from 4 mm stock came out as 23 layers, 92 mm, all of the missing height at the
    top — and the reporter's rotate x = 85 turned it into a staircase with nothing saying so. A cube now stacks as
    tall as it is, centred, and one sitting a few degrees off square carries a note with the rotate that squares it."""
    stl = tmp_path / "cube100.stl"
    trimesh.creation.box([100, 100, 100]).export(stl)
    params = {"axis": "y", "thickness": 4, "connect": "none", "autofix": "off"}
    plan = build(stl, "stacked", params)
    ys = [sl["M"][1][3] for sl in plan["slices"]]
    assert plan["counts"]["slices"] == 25 and abs(min(ys) + max(ys)) < 1e-6 and plan["coverage"] > 0.99
    assert not plan["square"]
    tilted = build(stl, "stacked", {**params, "rotate": [85, 0, 0]})
    assert tilted["square"] == {"rotate": [90.0, 0.0, 0.0], "off": 5.0}
    assert build(stl, "stacked", {**params, "rotate": tilted["square"]["rotate"]})["coverage"] > 0.99


@pytest.mark.parametrize("joint", ["rivet", "laced", "strip"])
def test_folded_holes_keep_the_wall_the_check_asks_for(joint):
    """Reported on the wedge: P-1 'a hole sits closer than 2 mm to the outline', and its one-click fix set dowel_d,
    which folded never reads. The panel holes were placed half a min_feature from the edge while the check asks for
    a whole one, a hole exactly min_feature in was counted as closer, and a strip's end holes sat in its rounded cap
    at 0.47 mm. Every hole now keeps the full wall, so the warning has nothing to report."""
    plan = build(EXAMPLES / "wedge.stl", "folded", {"thickness": 1, "facet": 0, "joint": joint, "autofix": "off"})
    assert not [w for s in plan["slices"] for w in s["warnings"] if "closer than" in w]
    assert sum(1 for s in plan["slices"] if s["group"] == "F" for _ in s["pieces"]) >= 1


def test_one_sheet_nests_everything_on_one_strip():
    """one_sheet ignores the sheet height: one sheet as wide as asked and as long as it needs, nothing split."""
    params = {"nx": 6, "ny": 5, "sheet": [200, 120], "autofix": "off"}
    many = build(EXAMPLES / "egg.stl", "interlocked", params)
    one = build(EXAMPLES / "egg.stl", "interlocked", {**params, "one_sheet": True})
    assert many["sheets"] > 1 and one["sheets"] == 1
    assert one["sheet"][0] == 200 and one["sheet"][1] > 120
    assert one["counts"]["parts"] == one["counts"]["slices"]
    assert one["params"]["sheet"] == [200, 120]                     # the user's sheet is reported back untouched


def test_build_is_deterministic():
    """Same model and params, same plan JSON: the coverage sampler is seeded, nothing else draws randomness.
    The stage timing is the one thing in a plan that is allowed to differ between two runs."""
    params = {"nx": 4, "ny": 3, "autofix": "off"}
    p1 = build(EXAMPLES / "egg.stl", "interlocked", params); p1.pop("timing", None)
    p2 = build(EXAMPLES / "egg.stl", "interlocked", params); p2.pop("timing", None)
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)


# the horse on the landing page: its body curve and a branch down each leg, from where it leaves the body to the hoof
HORSE = {"size": [0, 300, 0], "thicken": 1, "round": 2, "thickness": 3, "slot_offset": 0.1, "plane": "yz", "count": 20, "spines": 1}
HORSE_CURVE = [[-119, 11], [-89, 18], [-59, 23], [-14, 10], [16, 13], [50, 22], [76, 47], [91, 76], [106, 89], [136, 83]]
BRANCHES = [[[-2, 46.6, -33], [-5.2, 64.5, -128]], [[40.5, 36.8, -33], [49, 25.8, -125]],
            [[-2.8, -100.1, -11], [-5, -134.2, -125]], [[52, -83.1, -15], [54.9, -101, -125]]]
# each leg's centreline, measured on the model: a leg bends, its branch is one straight line from body to hoof
LEGS = [[[-2.0, 46.6, -33], [-2.3, 47.8, -61], [-3.7, 49.2, -81], [-3.6, 54.9, -101], [-5.2, 64.5, -128]],
        [[40.5, 36.8, -33], [44.5, 30.7, -61], [47.1, 23.6, -81], [48.6, 19.9, -101], [49.0, 25.8, -125]],
        [[-2.8, -100.1, -11], [-2.8, -120.4, -41], [-3.8, -133.5, -69], [-4.1, -139.7, -97], [-5.0, -134.2, -125]],
        [[52.0, -83.1, -15], [50.7, -95.5, -45], [52.1, -104.1, -69], [52.9, -110.4, -97], [54.9, -101.0, -125]]]


def test_curve_branches_hold_every_leg_of_the_horse():
    """A branch per leg: its ribs square to the leg and a spine of its own down the middle of it, reaching back into
    the body and slotted into the body ribs. Measured on the cut parts: every 2 mm along each leg's centreline lies
    in a branch spine (within 6 mm of its plane, within 2 mm of its outline), each leg keeps its ribs, nothing is in
    error and the model is still covered."""
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    plan = build(EXAMPLES / "horse.stl", "curve", {**HORSE, "curve": HORSE_CURVE, "branches": BRANCHES, "autofix": "add"})
    assert plan["counts"]["errors"] == 0, [(s["label"], s["errors"]) for s in plan["slices"] if s["errors"]] + plan["errors"]
    assert plan["coverage"] >= 0.9
    spines = [(np.array(s["M"]), unary_union([Polygon(r[0], r[1:]) for pc in s["pieces"] for r in pc["kerfed"]]))
              for s in plan["slices"] if s["label"][0] == "K" and s["label"][1:2].isdigit()]
    for i, leg in enumerate(LEGS, 1):
        C = np.array(leg)
        X = np.concatenate([np.linspace(a, b, max(2, int(np.linalg.norm(b - a) // 2)), endpoint=False) for a, b in zip(C, C[1:])])
        held = np.zeros(len(X), bool)
        for M, g in spines:
            L = (np.c_[X, np.ones(len(X))] @ np.linalg.inv(M).T)[:, :3]
            held |= (np.abs(L[:, 2]) < 6) & np.array([g.distance(Point(x)) < 2 for x in L[:, :2]])
        assert held.mean() >= 0.95, f"leg {i}: {held.mean():.0%} of it in a branch spine"
        assert len([s for s in plan["slices"] if s["label"].startswith(f"R{i}-")]) >= 5
    assert len(plan["axes3d"]) == 4 and {b["label"] for b in plan["bounds3d"]} >= {"J-1", "J-2", "J-3", "J-4"}


def test_curve_branch_past_the_ribs_is_an_error():
    """The landing page's shorter curve stops before the hind legs: the third branch's spine meets no body rib, so
    nothing holds the leg on — said, not cut as a loose leg. The fourth starts further forward and its tongue
    still reaches R-1."""
    plan = build(EXAMPLES / "horse.stl", "curve", {**HORSE, "curve": [[-85, 22], [-30, 32], [25, 30], [55, 55], [90, 74]],
                                                    "branches": BRANCHES, "autofix": "off"})
    assert [e[:8] for e in plan["errors"]] == ["branch 3"], plan["errors"]


def test_curve_branch_follows_its_joint_and_either_end_can_come_first():
    """J-1 moved 15 mm down the leg takes branch 1's start with it — its ribs and spine stay one assembly, not a
    tongue on its own with every rib floating — and a branch typed hoof first is the same branch, not a joint at the
    hoof that hands the whole body to the leg."""
    plan = build(EXAMPLES / "horse.stl", "curve", {**HORSE, "curve": HORSE_CURVE, "autofix": "off", "offset": {"J-1": 15},
                                                    "branches": [BRANCHES[0][::-1]] + BRANCHES[1:]})
    assert plan["counts"]["errors"] == 0, [(s["label"], s["errors"]) for s in plan["slices"] if s["errors"]] + plan["errors"]
    assert plan["coverage"] >= 0.9
    assert len([s for s in plan["slices"] if s["label"].startswith("R1-")]) >= 5


def test_curve_branch_takes_its_limb_and_no_more(tmp_path):
    """A box body along y with an arm straight out of its side and a leg down and out at a slant, a branch each.
    The body keeps everything the branches' parts do not take: a rib far from both limbs is as big as with no
    branches (past J alone, the arm took a 4 mm slab off every rib). The arm's spine lies flat, so the body ribs
    cross it and hold it — square to the curve plane, it was parallel to them and held by nothing — and the leg's
    slanted spine stops short of the body spine instead of crossing it unslotted."""
    import trimesh
    T = trimesh.util.concatenate([trimesh.creation.box([40, 200, 40]), trimesh.creation.box([80, 30, 30]).apply_translation([60, 0, 0]),
                                  trimesh.creation.cylinder(12, segment=[[5, 60, -5], [60, 60, -75]])])
    sh = -T.bounds.mean(0); T.apply_translation(sh); T.export(tmp_path / "t.stl")
    base = {"plane": "yz", "count": 12, "spines": 1, "thickness": 3, "curve": [[-95, sh[2]], [95, sh[2]]], "autofix": "off", "shrinkwrap": 2}
    area = lambda p: {s["label"]: sum(pc["area"] for pc in s["pieces"]) for s in p["slices"]}
    bare = build(tmp_path / "t.stl", "curve", base)
    # R2-1, the leg's rib at the joint, grazes the body's corner: on its plane it would meet K2 twice, which 2 mm either way clears
    plan = build(tmp_path / "t.stl", "curve", {**base, "offset": {"R2-1": 2}, "branches": [[(np.add(q, sh)).tolist() for q in seg]
                                                                    for seg in ([[15, 0, 0], [100, 0, 0]], [[14, 60, -15], [58, 60, -72]])]})
    assert plan["counts"]["errors"] == 0 and not plan["errors"], [(s["label"], s["errors"]) for s in plan["slices"] if s["errors"]] + plan["errors"]
    assert plan["coverage"] >= 0.9
    for lab in ("R-1", "R-2", "R-3"):
        assert abs(area(plan)[lab] - area(bare)[lab]) < 1, (lab, area(plan)[lab], area(bare)[lab])
    by = {s["label"]: s for s in plan["slices"]}
    assert abs(np.array(by["K1"]["M"])[:3, 2] @ [0, 0, 1]) > 0.99                          # the arm's spine lies flat
    assert sum(x.startswith("R-") for x in by["K1"]["engages"]) >= 2 and sum(x.startswith("R-") for x in by["K2"]["engages"]) >= 2
    K = np.array(by["K-1"]["M"]); side = (world_pts(by["K2"]) - K[:3, 3]) @ K[:3, 2]      # K2's outline against K-1's plane
    assert (side > 3).all() or (side < -3).all(), (side.min(), side.max())
