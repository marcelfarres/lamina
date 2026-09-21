"""Modify form and connector placement keep to what was asked: a small thicken stays small, a square dowel keeps
its wall."""
import collections
import pathlib
import re

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point

from core.geometry import section_polygons, unripple
from core.plan import MODES, build, coerce_params, load_mesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_thicken_smaller_than_a_voxel_does_not_fill_the_box():
    """A 400 mm cone remeshes at 3.3 mm voxels; thicken 1 mm rounds to no whole voxel. That must dilate by one voxel,
    not (scipy's reading of iterations=0) until the whole padded volume is solid."""
    plan = build(EXAMPLES / "cone.stl", "stacked",
                 {"size": [0, 0, 400], "thicken": 1, "connect": "none", "distribution": "count", "count": 6, "autofix": "off"})
    widths = [sl["extents"][0] for sl in plan["slices"]]
    assert min(widths) < 0.6 * max(widths)          # still a cone: the top slice is far narrower than the base
    assert plan["bbox"][2] < 415                    # one voxel of growth, not the padding


def test_a_union_that_left_a_seam_is_mended_not_remeshed():
    """The pear is two spheres joined with a seam of duplicate faces: not watertight, no open edge. That is mended and
    sliced as modelled — smooth outlines — where a voxel remesh would have left stairs on every slice."""
    plan = build(EXAMPLES / "pear.stl", "radial", {"count": 6, "ring_count": 4, "autofix": "off"})
    assert any("mended" in n for n in plan["notes"]) and not any("remeshed" in n for n in plan["notes"])
    ring = next(pc for sl in plan["slices"] if sl["label"] == "Z-2" for pc in sl["pieces"])
    assert len(ring["placed"][0][0]) < 400                          # the sphere's own facets; a 1/120 remesh gave twice that


def test_a_gap_means_nothing_is_glued():
    """With a space between the layers, an island without a connector hangs in the air and the layers touch nothing:
    the checks must say so (errors), where the same stack at gap 0 is merely glued (warnings)."""
    base = {"axis": "z", "distribution": "count", "count": 8, "connect": "none", "autofix": "off"}
    gapped = build(EXAMPLES / "horse.stl", "stacked", {**base, "space": 10})
    errs = [e for sl in gapped["slices"] for e in sl["errors"]]
    assert any("across the gap" in e for e in errs)                  # a leg island nothing holds
    assert any("not connected to the main assembly" in e for e in errs)   # the layers themselves
    glued = build(EXAMPLES / "horse.stl", "stacked", base)
    assert not [e for sl in glued["slices"] for e in sl["errors"] if "across the gap" in e or "not connected" in e]


def test_the_curve_runs_through_the_body_not_the_box():
    """The horse's head is turned: its centre sits 30 mm to one side of the bounding box's middle plane at the
    head, 15 mm to the other side at the body. The curve must follow that, so the ribs cut the neck squarely."""
    plan = build(EXAMPLES / "horse.stl", "curve", {"plane": "yz", "count": 8, "spines": 1, "autofix": "off"})
    x = [pt[0] for pt in plan["curve3d"]]
    assert max(x) - min(x) > 25
    assert len(plan["curve_pts"][0]) == 3                      # control points carry the third coordinate for the 3D view


def test_a_prototype_too_thin_to_print_is_planned_again_thicker():
    """3 mm parts at x0.25 would print 0.75 mm. Printing them 1.2 mm thick would not fit slots cut for 0.75, so the
    prototype's plan is rebuilt at 4.8 mm material; at x0.5 (1.5 mm printed) the plan stands."""
    from core.solid import proto_plan
    plan = build(EXAMPLES / "egg.stl", "interlocked", {"nx": 4, "ny": 3, "thickness": 3, "autofix": "off"})
    same, note = proto_plan(plan, 0.5, 1.2)
    assert same is plan and note is None
    thick, note = proto_plan(plan, 0.25, 1.2)
    assert thick["params"]["thickness"] == 4.8 and "re-planned at 4.8 mm" in note
    assert all(sl["thickness"] == 4.8 for sl in thick["slices"])


def test_build_reports_its_progress_from_start_to_one(tmp_path):
    """What the page's overlay is drawn from: every stage in order, per-slice sections, ending at 1.0 — and the
    preview mesh announced as soon as it is written, so the 3D view can show the model before the slices exist."""
    import core.plan as P
    seen = []
    P.report = lambda text, frac, artifact=None: seen.append((text, frac, artifact))
    try:
        build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off"},
              mesh_out=tmp_path / "model.stl")
    finally:
        P.report = lambda text, frac, artifact=None: None
    fr = [f for _, f, _ in seen]
    assert fr == sorted(fr) and fr[0] < 0.1 and fr[-1] == 1.0
    assert sum("sectioning" in t for t, _, _ in seen) == 4 and any("nesting" in t for t, _, _ in seen)
    early = [(t, f, a) for t, f, a in seen if a]
    assert len(early) == 1 and early[0][2].endswith("model.stl") and early[0][1] < 0.25   # before the slices are cut
    assert (tmp_path / "model.stl").exists()                                              # and it is really there


def test_a_slice_turns_about_the_point_the_view_gives_it():
    """A radial half-slice's frame origin sits out on the fan axis, in the middle of the model — so rolling it turned
    the part about a point it does not contain and swung it across the model, which is what "it goes back to the
    origin" looked like. Given the part's own middle as `pivot`, the plane still passes through that point: the part
    turns where it stands. Without one, nothing changes from how it always behaved."""
    import numpy as np
    base = {"count": 4, "rings": 1, "autofix": "off"}
    plan0 = build(EXAMPLES / "egg.stl", "radial", base)
    sl = next(s for s in plan0["slices"] if s["group"] == "R")
    M = np.array(sl["M"])
    centre = (M[:3, 3] + 40 * M[:3, 0]).tolist()          # a point on the plane, 40 mm out from its frame origin

    def gap(plan):                                        # how far the part's middle ends up off its own plane
        s = next(x for x in plan["slices"] if x["label"] == sl["label"])
        m = np.array(s["M"])
        return abs(float(np.dot(np.asarray(centre) - m[:3, 3], m[:3, 2])))

    rolled = {**base, "roll": {sl["label"]: 30}}
    assert gap(build(EXAMPLES / "egg.stl", "radial", rolled)) > 15          # 40 mm × sin 30° — the part has swung off
    # still on its own plane, to the six decimals the plan rounds the frame to
    assert gap(build(EXAMPLES / "egg.stl", "radial", {**rolled, "pivot": {sl["label"]: centre}})) < 1e-4


def test_a_second_autofix_pass_never_sends_the_bar_backwards():
    """The stages repeat when autofix adds crossing slices, which used to drop the bar from 70 % back to 20 % with no
    word about why. Each extra pass now has a band of its own at the end, and says which pass it is."""
    import core.plan as P
    seen = []
    P.report = lambda text, frac, artifact=None: seen.append((text, frac))
    try:                                                     # spines 0 leaves every rib floating: autofix adds them
        build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "add"})
    finally:
        P.report = lambda text, frac, artifact=None: None
    fr = [f for _, f in seen]
    assert fr == sorted(fr), [x for x in seen if x[1] < max(f for _, f in seen[:seen.index(x)] or [(0, 0)])][:3]
    assert any("pass 2 of 3" in t for t, _ in seen), [t for t, _ in seen][:20]
    assert fr[-1] == 1.0


def test_square_dowel_keeps_its_wall_to_the_outline():
    """Random points are sampled a margin inside the overlap; that margin must come from the hole's real reach (a
    square's corner, 0.71 d), or the wall check flags every hole near a curved edge."""
    plan = build(EXAMPLES / "cone.stl", "stacked",
                 {"connect": "dowel", "dowel_shape": "square", "placement": "random", "dowel_d": 8, "n_points": 2,
                  "space": 5, "distribution": "count", "count": 6, "autofix": "off"})
    assert plan["rods"]                              # the dowels are there (rods, not cut parts)
    assert not [w for sl in plan["slices"] for w in sl["warnings"] if "closer than" in w]


def mid_outline(mesh):
    M = np.eye(4)
    M[:3, 3] = [0, 0, (mesh.bounds[0][2] + mesh.bounds[1][2]) / 2]
    return section_polygons(mesh, M)


@pytest.mark.parametrize(("setting", "value", "was", "was_pt"), [("round", 2, 0.285, 1.27), ("shrinkwrap", 2, 0.369, 1.47),
                                                                ("thicken", 2, 0.305, 1.17), ("hollow", 6, 0.537, 2.29)])
def test_modify_form_leaves_a_smooth_curve_smooth(setting, value, was, was_pt):
    """Reported as "the curves get destroyed if we touch any of those parameters". The voxel grid leaves a ripple
    about a fifth of a voxel deep along every curve — not steps, a wobbly edge, which is why counting sharp corners
    missed it. `was` / `was_pt` are what each setting measured on the egg before `unripple`: the spread of the cut
    outline about the as-modelled curve, and how far it wandered peak to trough on a 180 mm part."""
    p = coerce_params(MODES["stacked"], {"thickness": 3})
    plain = load_mesh(EXAMPLES / "egg.stl", p, [], "stacked")
    edge = mid_outline(plain).boundary

    q = coerce_params(MODES["stacked"], {"thickness": 3, setting: value})
    cut = mid_outline(load_mesh(EXAMPLES / "egg.stl", q, [], "stacked"))
    d = np.array([edge.distance(Point(v)) for g in cut.geoms for v in np.asarray(g.exterior.coords)])
    # the mean is the material the setting adds or takes away, which is the point of it; the spread is the ripple
    assert d.std() < 0.6 * was, f"outline wobbles by {d.std():.3f} mm about the original curve (was {was} mm)"
    assert d.max() - d.min() < 0.6 * was_pt, f"outline wanders {d.max() - d.min():.2f} mm peak to trough (was {was_pt} mm)"


def test_the_outline_smoothing_survives_the_browser_s_way_of_sorting_loops(monkeypatch):
    """The browser build has no rtree, so `polygons_full` raises and `section_polygons` sorts its loops with one
    symmetric_difference — arriving with a MultiPolygon where the desktop build passes one polygon at a time. That
    difference got past the unit tests and failed the published build with
    `AttributeError: 'MultiPolygon' object has no attribute 'exterior'`."""
    @property
    def no_rtree(self):
        raise ImportError("rtree is not available (as in the browser build)")

    monkeypatch.setattr(trimesh.path.Path2D, "polygons_full", no_rtree)
    mesh = load_mesh(EXAMPLES / "bunny.stl", coerce_params(MODES["stacked"], {"thickness": 3, "round": 2}), [], "stacked")
    assert mesh.metadata.get("lamina_pitch"), "this test is only meaningful on a remeshed model"
    assert not mid_outline(mesh).is_empty
    plan = build(EXAMPLES / "bunny.stl", "stacked", {"thickness": 3, "round": 2, "distribution": "count", "count": 8})
    assert plan["counts"]["parts"] > 0 and not plan["errors"], plan["errors"]


def test_a_model_sliced_as_modelled_is_not_smoothed_at_all():
    """`unripple` is for outlines cut from a remeshed model and nothing else: no modify form, no voxel grid, so the
    section must come through with every point exactly where the mesh put it."""
    p = coerce_params(MODES["stacked"], {"thickness": 3})
    mesh = load_mesh(EXAMPLES / "cube.stl", p, [], "stacked")
    assert not mesh.metadata.get("lamina_pitch"), "nothing was asked for, so nothing should have been remeshed"
    got = mid_outline(mesh)
    assert got.equals(unripple(list(got.geoms)[0], 0)), "an outline with no grid behind it was altered"


def dowels_by_level(plan):
    """Every dowel the plan places, grouped by the layer it starts at — `rods` is the placer's own output, where the
    inner rings of a cut outline would also count the model's own voids (a hollowed layer is a ring)."""
    level = collections.defaultdict(list)
    for a, _b, _d in plan["rods"]:
        level[round(float(a[2]), 1)].append(np.asarray(a[:2], float))
    return level


@pytest.mark.parametrize(("name", "over", "least"), [("bunny", {"hollow": 8}, 25), ("cow_spot", {}, 30),
                                                    ("cone", {}, 30), ("head_igea", {}, 36)])
def test_a_stack_is_dowelled_through_without_holes_running_together(name, over, least):
    """Two faults from one report. Too many, merged: eroding a hollowed layer leaves crumbs and each crumb was given
    a pair of its own — 185 dowels on the hollowed bunny, two of them 0.6 mm apart. Too few: every pair chose a fresh
    spread, so on anything tapered the points walked inward a few mm a layer, landed in the wall of the hole above,
    and were dropped — the cone had 6 mm dowels 5.5 mm apart and half its layers with none at all.

    `least` is a floor a little under what is measured now (bunny 31, cow 36, cone 34, head 38), so the test fails if
    a change starts losing dowels again without pinning today's numbers exactly."""
    d, min_feature = 6, 2.0
    plan = build(EXAMPLES / f"{name}.stl", "stacked",
                 {"connect": "dowel", "dowel_d": d, "n_points": 2, "thickness": 3, "min_feature": min_feature,
                  "distribution": "count", "count": 20, **over})
    assert len(plan["rods"]) >= least, f"{len(plan['rods'])} dowels through {name}: layers are being left unaligned"
    for z, pts in dowels_by_level(plan).items():
        gaps = [float(np.hypot(*(pts[i] - pts[j]))) for i in range(len(pts)) for j in range(i + 1, len(pts))]
        # two holes need a wall of material between their edges, or they cut into one another and locate nothing
        assert all(g >= d + min_feature - 0.01 for g in gaps), \
            f"dowels {min(gaps):.1f} mm apart at z={z} leave no wall between them (d={d}, min_feature={min_feature})"


def test_a_wall_too_thin_for_the_dowel_says_so():
    """Where a 6 mm dowel genuinely does not fit, placing none is right — but it has to be said, and any size it
    names has to work when followed. A 6 mm wall holds no dowel at all, so no size is offered there; the hollowed
    bunny is offered one, and following it fills every pair."""
    thin = build(EXAMPLES / "cow_spot.stl", "stacked",
                 {"connect": "dowel", "dowel_d": 6, "n_points": 2, "thickness": 3, "hollow": 6,
                  "distribution": "count", "count": 20})
    note = [n for n in thin["notes"] if "no connector" in n]
    assert note and not thin["rods"], (note, len(thin["rods"]))
    assert "set dowel_d" not in note[0], f"names a size, but none of them work here: {note[0]}"

    job = {"connect": "dowel", "dowel_d": 6, "n_points": 2, "thickness": 3, "hollow": 8,
           "distribution": "count", "count": 20}
    plan = build(EXAMPLES / "bunny.stl", "stacked", job)
    said = [n for n in plan["notes"] if "set dowel_d to about" in n]
    assert said, plan["notes"]
    d = float(re.search(r"set dowel_d to about ([\d.]+) mm", said[0]).group(1))
    assert d < job["dowel_d"], f"offers {d} mm, no smaller than the {job['dowel_d']} mm that just failed"
    after = build(EXAMPLES / "bunny.stl", "stacked", {**job, "dowel_d": d})
    assert len(after["rods"]) > len(plan["rods"]), f"following the advice ({d} mm) placed no more dowels"
    assert not [n for n in after["notes"] if "no connector" in n], "advice followed, layers still unconnected"
