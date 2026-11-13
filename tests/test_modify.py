"""Modify form and connector placement keep to what was asked: a small thicken stays small, a square dowel keeps
its wall."""
import collections
import os
import pathlib
import re

import numpy as np
import pytest
import shapely
import trimesh
from shapely.geometry import Point

from core.geometry import dowel_leverage, section_polygons
from core.mesh import load_mesh, reuse
from core.plan import MODES, build, coerce_params

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_thicken_smaller_than_a_grid_step_acts_exactly():
    """A 400 mm cone remeshes on a 3.3 mm grid; thicken 1 mm is under one step. On the binary grid that acted as a
    whole step (3.3 mm, and the note said so); on the distance field it is 1 mm. The cone's base edge and its tip
    are sharp, and marching cubes takes up to half a step off a sharp feature (the base came out 0.8 mm wider, not
    2; the tip a step short), so the measure is a cut through the cone's flank, which is a surface: 1 mm out along
    its normal, which on a flank at 1:2 is 1.12 mm wider on each side."""
    plan = build(EXAMPLES / "cone.stl", "stacked",
                 {"size": [0, 0, 400], "thicken": 1, "connect": "none", "distribution": "count", "count": 6, "autofix": "off"})
    widths = [sl["extents"][0] for sl in plan["slices"]]
    assert min(widths) < 0.6 * max(widths)          # still a cone: the top slice is far narrower than the base
    assert 398.5 < plan["bbox"][2] < 402.5
    plain = load_mesh(EXAMPLES / "cone.stl", coerce_params(MODES["stacked"], {"size": [0, 0, 400]}), [])
    thick = load_mesh(EXAMPLES / "cone.stl", coerce_params(MODES["stacked"], {"size": [0, 0, 400], "thicken": 1}), [])

    def width_at(mesh, z):                            # the cut's reach in x at a height above the base
        M = np.eye(4); M[2, 3] = mesh.bounds[0][2] + z
        return section_polygons(mesh, M).bounds[2]

    grew = width_at(thick, 201) - width_at(plain, 200)     # the thickened base sits 1 mm lower: the same height
    assert abs(grew - 1.12) < 0.2, grew


def test_round_removes_a_thin_fin_and_rounds_the_corners_to_the_radius_asked(tmp_path):
    """A 60 mm box with a 3 mm fin standing on top, rounded 4 mm: the fin goes (thinner than the ball), and the
    box's square corners come back as fillets of the ball's radius, 2 mm — the corner point of the cut outline sits
    2·(√2−1) = 0.83 mm inside where the square's corner was, plus a flat of about half a grid step (2 mm grid): the
    one marching-cubes pass over a sharp corner, the eroded box's, cuts it by that much, and the fillet is drawn
    about the cut. The binary grid gave 3·pitch = 6 mm corners for any value asked."""
    box = trimesh.creation.box((60, 60, 60))
    fin = trimesh.creation.box((3, 40, 20)); fin.apply_translation([0, 0, 40])
    trimesh.util.concatenate([box, fin]).export(tmp_path / "finned.stl")
    p = coerce_params(MODES["stacked"], {"thickness": 3, "round": 4})
    mesh = load_mesh(tmp_path / "finned.stl", p, [])
    assert abs(mesh.extents[2] - 60) < 0.5, mesh.extents    # the fin is gone, the box is not thinner
    corner = Point(30, 30).distance(mid_outline(mesh))
    assert 0.83 - 0.3 < corner < 0.83 + 1.2, corner


def test_a_model_saved_in_metres_says_so(tmp_path):
    """Blender's STL is in metres: a 100 mm cube arrives 0.1 mm across and slices to nothing. Say why, and the size
    that fixes it does."""
    trimesh.creation.box([0.1, 0.1, 0.1]).export(tmp_path / "cube.stl")
    plan = build(tmp_path / "cube.stl", "stacked", {"connect": "none", "thickness": 3})
    assert plan["counts"]["slices"] == 0 and any("only 0.1 mm across" in n for n in plan["notes"])
    plan = build(tmp_path / "cube.stl", "stacked", {"connect": "none", "thickness": 3, "size": [100, 0, 0]})
    assert plan["counts"]["slices"] == 33 and not any("mm across" in n for n in plan["notes"])


def test_a_closed_cavity_is_solid_and_a_doubled_surface_is_one(tmp_path):
    """A scan with an inner surface: hollow measures its wall from the outside — one 3 mm wall at radius 27, not a
    second void sheet carved in the middle of the 7 mm the model already has. And a model exported twice over
    itself (watertight, and even-odd reads it as empty) is one surface: thicken 1 grows it by 1, not a crash.
    Parts that overlap in the file are one solid: see the curve-branch T in test_modes."""
    outer, inner = trimesh.creation.icosphere(4, 30), trimesh.creation.icosphere(4, 23)
    inner.invert()
    trimesh.util.concatenate([outer, inner]).export(tmp_path / "shell.stl")
    mesh = load_mesh(tmp_path / "shell.stl", coerce_params(MODES["stacked"], {"thickness": 3, "hollow": 3}), [])
    assert len(mesh.split(only_watertight=False)) == 2, "one outer and one inner surface"
    radii = np.linalg.norm(mesh.vertices, axis=1)
    assert abs(radii.max() - 30) < 0.3 and abs(radii.min() - 27) < 0.3, (radii.min(), radii.max())
    assert not ((radii > 27.5) & (radii < 29.5)).any(), "a void sheet inside the wall"

    trimesh.util.concatenate([outer, outer.copy()]).export(tmp_path / "doubled.stl")
    thick = load_mesh(tmp_path / "doubled.stl", coerce_params(MODES["stacked"], {"thickness": 3, "thicken": 1}), [])
    assert abs(thick.extents[0] - 62) < 0.3, thick.extents


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


def test_build_reports_its_progress_from_start_to_one(tmp_path, monkeypatch):
    """What the page's overlay is drawn from: every stage in order, per-slice sections, ending at 1.0 — and the
    preview mesh announced as soon as it is written, so the 3D view can show the model before the slices exist."""
    import core.progress as P
    seen = []
    # monkeypatch puts back the hook it found: the server's, which is how a newer slice stops an older one — a
    # hand-made reset to a no-op left the rest of the test run with no way to stop a slice (test_web failed after it)
    monkeypatch.setattr(P, "report", lambda text, frac, artifact=None: seen.append((text, frac, artifact)))
    build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off"},
          mesh_out=tmp_path / "model.stl")
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


def test_a_second_autofix_pass_never_sends_the_bar_backwards(monkeypatch):
    """The stages repeat when autofix adds crossing slices, which used to drop the bar from 70 % back to 20 % with no
    word about why. Each extra pass now has a band of its own at the end, and says which pass it is."""
    import core.progress as P
    seen = []
    monkeypatch.setattr(P, "report", lambda text, frac, artifact=None: seen.append((text, frac)))   # put back after
    build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "add"})   # spines 0: every rib floats, autofix adds them
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


@pytest.mark.parametrize(("setting", "value", "offset"), [("round", 2, 0), ("shrinkwrap", 2, 0), ("thicken", 2, 2), ("hollow", 6, 0)])
def test_modify_form_leaves_a_smooth_curve_smooth(setting, value, offset):
    """Reported twice: "the curves get destroyed if we touch any of those parameters", then "round creates a very
    bumpy surface, pixelated, low polygon". The binary voxel grid left a ripple about a fifth of a voxel deep along
    every curve and moved the whole surface out by most of a voxel. On the distance field the cut outline of the
    egg sits where the model's own outline is — `offset` mm out for thicken — to a few hundredths of a millimetre
    (measured: spread 0.01–0.02 mm, peak to trough 0.1–0.2 mm, on a 180 mm part)."""
    p = coerce_params(MODES["stacked"], {"thickness": 3})
    plain = load_mesh(EXAMPLES / "egg.stl", p, [])
    edge = mid_outline(plain).boundary

    q = coerce_params(MODES["stacked"], {"thickness": 3, setting: value})
    cut = mid_outline(load_mesh(EXAMPLES / "egg.stl", q, []))
    d = np.array([edge.distance(Point(v)) for g in cut.geoms for v in np.asarray(g.exterior.coords)])
    assert abs(d.mean() - offset) < 0.15, f"outline sits {d.mean():.3f} mm from the original curve, {offset} asked"
    assert d.std() < 0.05, f"outline wobbles by {d.std():.3f} mm about the original curve"
    assert d.max() - d.min() < 0.4, f"outline wanders {d.max() - d.min():.2f} mm peak to trough"


def test_a_remeshed_model_sections_the_browser_s_way_of_sorting_loops(monkeypatch):
    """The browser build has no rtree, so `polygons_full` raises and `section_polygons` sorts its loops with one
    symmetric_difference — arriving with a MultiPolygon where the desktop build passes one polygon at a time. That
    difference got past the unit tests once and failed the published build on a remeshed model."""
    @property
    def no_rtree(self):
        raise ImportError("rtree is not available (as in the browser build)")

    monkeypatch.setattr(trimesh.path.Path2D, "polygons_full", no_rtree)
    mesh = load_mesh(EXAMPLES / "bunny.stl", coerce_params(MODES["stacked"], {"thickness": 3, "round": 2}), [])
    assert len(mesh.faces) != len(trimesh.load(EXAMPLES / "bunny.stl").faces), "this test is only meaningful on a remeshed model"
    assert not mid_outline(mesh).is_empty
    plan = build(EXAMPLES / "bunny.stl", "stacked", {"thickness": 3, "round": 2, "distribution": "count", "count": 8})
    assert plan["counts"]["parts"] > 0 and not plan["errors"], plan["errors"]


@pytest.mark.parametrize("shape", ["box", "tube"])
def test_a_straight_wall_cuts_the_same_outline_on_every_layer(shape):
    """Reported: stacked never got past "placing slices" on a 300 mm cube with a hole. A flat wall is two triangles,
    and the plane crossing their diagonal left a point on the straight edge, somewhere else on every layer. The
    aligned dowels intersect every layer's outline; that kept all of those points, 393,370 vertices by the 15th of
    100 layers, and one intersection took longer than the user would wait. A box and a tube (the hole) here, cut 100
    times: each layer is its corners and nothing else, and so is the intersection of all of them."""
    mesh = trimesh.creation.box((300, 300, 300)) if shape == "box" else \
        trimesh.creation.annulus(r_min=15, r_max=150, height=300, sections=32)
    corners = 4 + 1 if shape == "box" else 2 * (32 + 1)          # each ring closes on its first point
    inter = None
    for z in np.linspace(-148.5, 148.5, 100):
        M = np.eye(4); M[2, 3] = z
        sec = section_polygons(mesh, M)
        assert shapely.get_num_coordinates(sec) == corners, (z, shapely.get_num_coordinates(sec))
        inter = sec if inter is None else inter.intersection(sec)
    assert shapely.get_num_coordinates(inter) <= corners + 2, shapely.get_num_coordinates(inter)
    assert abs(inter.area - sec.area) < 1e-6 * sec.area


@pytest.mark.parametrize("shape,corners,area", [("square", 4, 36.0), ("pencil", 6, 23.38)])
def test_a_dowel_rod_has_the_section_of_its_hole(shape, corners, area):
    """The 3D view draws each rod from the section the plan gives it: a round rod in a square hole was all it ever
    showed, so changing the dowel shape changed nothing on screen."""
    plan = build(EXAMPLES / "egg.stl", "stacked", {"connect": "dowel", "dowel_d": 6, "dowel_shape": shape, "autofix": "off"})
    secs = [shapely.Polygon(r[3]) for r in plan["rods"]]
    assert secs and all(len(s.exterior.coords) - 1 == corners and s.area == pytest.approx(area, abs=0.01) for s in secs)


def dowels_by_level(plan):
    """Every dowel the plan places, grouped by the layer it starts at — `rods` is the placer's own output, where the
    inner rings of a cut outline would also count the model's own voids (a hollowed layer is a ring)."""
    level = collections.defaultdict(list)
    for a, *_ in plan["rods"]:
        level[round(float(a[2]), 1)].append(np.asarray(a[:2], float))
    return level


@pytest.mark.parametrize(("name", "over", "least"), [("bunny", {"thicken": 3}, 70), ("cow_spot", {}, 30),
                                                    ("cone", {}, 30), ("head_igea", {}, 36)])
def test_a_stack_is_dowelled_through_without_holes_running_together(name, over, least):
    """Two faults from one report. Too many, merged: eroding a hollow layer leaves crumbs and each crumb was given
    a pair of its own — 185 dowels on the bunny, two of them 0.6 mm apart. Too few: every pair chose a fresh
    spread, so on anything tapered the points walked inward a few mm a layer, landed in the wall of the hole above,
    and were dropped — the cone had 6 mm dowels 5.5 mm apart and half its layers with none at all.

    The bunny is modelled as a 7 mm shell; thickened 3 mm its rings take a 6 mm dowel with a wall to spare (the
    voxel pass used to fill it solid first, and `hollow 8` then made the rings). `least` is a floor a little under
    what is measured now (bunny 97, cow 36, cone 34, head 38), so the test fails if a change starts losing dowels
    again without pinning today's numbers exactly."""
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


def test_a_stack_with_nothing_joining_its_layers_keeps_every_layer():
    """Reported as "the model loses some layers when lines is selected". With a gap between layers and no line
    through them nothing joins the layers; autofix took each unheld island away, and a layer that is all islands (the
    horse's four legs) went whole — 11 of 20. A layer stays and says what joins it; the note names the lines, not a
    dowel size, because nothing here was short of room."""
    job = {"connect": "dowel", "placement": "lines", "lines": [], "space": 5, "thickness": 3,
           "distribution": "count", "count": 20}
    on = build(EXAMPLES / "horse.stl", "stacked", job)
    off = build(EXAMPLES / "horse.stl", "stacked", {**job, "autofix": "off"})
    layers = lambda plan: {s["label"] for s in plan["slices"] if s["group"] == "S"}      # noqa: E731
    assert layers(on) == layers(off) and len(layers(on)) == 20, sorted(layers(off) - layers(on))
    note = next(n for n in on["notes"] if "got no connector" in n)
    assert "line" in note and "set dowel_d" not in note, note


@pytest.mark.parametrize("model", ["egg", "dumbbell", "torus"])
def test_aligned_tab_spacers_hold_every_layer_without_overlapping(model):
    """Reported on the wavy torus (aligned, tab spacers, 5 mm gap): "removed 1 region(s) of Z-1 (nothing holds it)"
    and "Z-2: two slots / holes overlap each other". The fit was tested on a round hole at the point before the tab
    stepped sideways, and against the other holes' centres, not their slots: every second pair of the egg's 19
    layers lost all its spacers (17 layers "not connected"), and spacers that did fit cut into each other. Every pair
    of layers is now joined, by its own spacer, and every slot keeps a full wall from every other."""
    job = {"axis": "z", "space": 5, "connect": "tab", "placement": "aligned", "n_points": 2, "thickness": 3,
           "slot_offset": 0.2, "min_feature": 2.0}
    on = build(EXAMPLES / f"{model}.stl", "stacked", job)
    off = build(EXAMPLES / f"{model}.stl", "stacked", {**job, "autofix": "off"})
    assert not [n for n in on["notes"] if "auto-fix" in n]
    said = [f"{s['label']}: {e}" for s in off["slices"] for e in s["errors"] + s["warnings"]]
    assert not said, said[:3]
    # where each spacer stands: the middle of the gap it bridges, from its placed frame (z up the stack)
    zs = sorted(s["M"][2][3] for s in off["slices"] if s["group"] == "S")
    held = collections.Counter(int(np.searchsorted(zs, s["M"][2][3])) for s in off["slices"] if s["group"] == "P")
    assert sorted(held) == list(range(1, len(zs))), f"gaps with no spacer: {sorted(set(range(1, len(zs))) - set(held))}"


def test_random_dowels_spread_across_the_layer():
    """Reported: with random placement "the dowels are not evenly spaced and some areas are not supported". The first
    candidates that kept clear of each other were taken, often both at one end of a layer: the far end of the horse's
    worst layer sat 0.91 of its width from any dowel. Now each point goes as far as it can from the ones chosen, and
    that reach is measured on the section itself, per pair."""
    job = {"connect": "dowel", "placement": "random", "n_points": 2, "thickness": 3, "space": 5,
           "distribution": "count", "count": 20, "autofix": "off"}
    plan = build(EXAMPLES / "horse.stl", "stacked", job)
    mesh = load_mesh(EXAMPLES / "horse.stl", coerce_params(MODES["stacked"], job), [])
    reach, levels = [], dowels_by_level(plan)
    for z, pts in levels.items():
        M = np.eye(4); M[2, 3] = z + job["thickness"] / 2     # a rod starts half a thickness below its slice's plane
        body = max(section_polygons(mesh, M).geoms, key=lambda g: g.area)
        pts = [q for q in pts if body.contains(Point(q))]
        if len(pts) < 2:        # a leg with room for one dowel only: nothing there to spread
            continue
        edge = np.asarray(body.exterior.coords)
        far = np.linalg.norm(edge[:, None] - np.asarray(pts)[None], axis=2).min(1).max()
        x0, y0, x1, y1 = body.bounds
        reach.append(far / max(x1 - x0, y1 - y0))
    assert len(levels) >= 14, f"only {len(levels)} pairs got dowels"   # 14: three pairs of legs take one each
    assert len(reach) >= 10, f"only {len(reach)} pairs have dowels to spread"
    assert max(reach) < 0.7, f"a layer's far end is {max(reach):.2f} of its width from any dowel (was 0.91)"


@pytest.mark.parametrize("n", [2, 3])
def test_aligned_dowels_hold_a_big_piece_from_near_its_edge(n):
    """Reported: with aligned dowels "big pieces are only supported in the center". The shared points fit the layer
    common to the whole stack — a 200 mm sphere's smallest — so its 200 mm middle was held by dowels 46 mm apart: the
    play in their holes let its edge shift 2.2× as much (dowel_leverage). Now such a piece gets its own toward its
    edge; three go around it, not along a line. Measured per layer on the section, with every rod through it."""
    job = {"size": [0, 0, 200], "connect": "dowel", "placement": "aligned", "n_points": n, "dowel_d": 6,
           "thickness": 6, "distribution": "count", "count": 20, "autofix": "off"}
    plan = build(EXAMPLES / "sphere.stl", "stacked", job)
    mesh = load_mesh(EXAMPLES / "sphere.stl", coerce_params(MODES["stacked"], job), [])
    below, worst = [], 0.0
    for z, pts in sorted(dowels_by_level(plan).items()):
        pts, below = pts + below, pts               # a layer carries the rods from the one below and to the one above
        M = np.eye(4); M[2, 3] = z + job["thickness"] / 2
        body = max(section_polygons(mesh, M).geoms, key=lambda g: g.area)
        worst = max(worst, dowel_leverage(body, pts))
        if n == 3 and shapely.minimum_bounding_radius(body) > 90:      # the middle: not all on one line
            q = np.asarray(pts) - np.mean(pts, axis=0)
            assert np.linalg.svd(q, compute_uv=False)[1] > 20, f"z={z}: three dowels on a line"
    assert worst <= 1.0, f"a layer's far edge shifts {worst:.2f}× the play in its holes (was 2.2)"
    assert not [w for s in plan["slices"] for w in s["warnings"] if "bunched" in w]

    # two lines drawn 20 mm apart up the middle: the check says so, with the piece's size
    lines = [[[x, 0, -110], [x, 0, 110]] for x in (-10, 10)]
    drawn = build(EXAMPLES / "sphere.stl", "stacked", {**job, "placement": "lines", "lines": lines})
    said = [w for s in drawn["slices"] for w in s["warnings"] if "bunched" in w]
    assert said and "mm across" in said[0], said


def test_a_bunched_piece_is_offered_the_dowel_that_holds_it():
    """The spread warning names one more dowel, and taking it has to hold the piece. A layer of the horse's ear comes
    out held 2.8 by two dowels close together. The spot is chosen where a rod is cut through a neighbour as well
    (chosen in the piece alone, no rod reached it), and the dowel taken comes on top of the n_points asked for:
    counted in, it stood in for one of the two and the ear came out 1.56 where 1.2 was promised. Measured on the
    section, with every rod through the layer. Pieces too small for two of these dowels to sit farther apart are not
    flagged at all (the pyramid's tip)."""
    job = {"connect": "dowel"}
    plan = build(EXAMPLES / "horse.stl", "stacked", job)
    label, w, fix = next((s["label"], f["error"], f["options"][0]) for s in plan["slices"] for f in s["fixes"]
                         if "bunched together" in f["error"])
    promised = float(re.search(r"brings that to ([\d.]+)×", w).group(1))
    x, y = fix["set"]["dowels"][-1]

    after = build(EXAMPLES / "horse.stl", "stacked", {**job, **fix["set"]})
    mesh = load_mesh(EXAMPLES / "horse.stl", coerce_params(MODES["stacked"], {**job, **fix["set"]}), [])
    sl = next(s for s in after["slices"] if s["label"] == label)
    M = np.asarray(sl["M"]); inv = np.linalg.inv(M)
    piece = next(g for g in section_polygons(mesh, M).geoms if g.buffer(1).contains(Point(x, y)))
    through = [(inv @ [*a[:3], 1])[:2] for a, b, *_ in after["rods"]
               if min(a[2], b[2]) <= M[2, 3] <= max(a[2], b[2]) and piece.contains(Point(*(inv @ [*a[:3], 1])[:2]))]
    held = dowel_leverage(piece, through)
    assert held <= promised + 0.05, f"{label} promised {promised}× with a dowel at ({x}, {y}), got {held:.2f}×"
    assert not [w for w in sl["warnings"] if "bunched" in w], sl["warnings"]
    assert not [w for s in build(EXAMPLES / "pyramid.stl", "stacked", job)["slices"] for w in s["warnings"] if "bunched" in w]

    # the bunny's thin 220 mm rings take a dowel only at a bulge: nothing to add, so it says what the wall lacks
    thin = [w for s in build(EXAMPLES / "bunny.stl", "stacked", job)["slices"] for w in s["warnings"]
            if "no dowel fits farther out" in w]
    assert thin, "a thin ring held 11.5× says nothing"
    wall, need = map(float, re.search(r"wall is about ([\d.]+) mm, a [\d.]+ mm dowel needs ([\d.]+) mm", thin[0]).groups())
    assert wall < need, thin[0]


def test_a_wall_too_thin_for_the_dowel_says_so():
    """Where a 6 mm dowel genuinely does not fit, placing none is right — but it has to be said, and any size it
    names has to work when followed. A 6 mm wall holds no dowel at all, so no size is offered there; the cow hollowed
    to an 8 mm wall is offered one, and following it fills the pairs — all but the odd strip narrower than the
    median the size is read from (the voxel pass's walls were 3 mm thicker than asked, and hid that)."""
    thin = build(EXAMPLES / "cow_spot.stl", "stacked",
                 {"connect": "dowel", "dowel_d": 6, "n_points": 2, "thickness": 3, "hollow": 6,
                  "distribution": "count", "count": 20})
    note = [n for n in thin["notes"] if "no connector" in n]
    assert note and not thin["rods"], (note, len(thin["rods"]))
    assert "set dowel_d" not in note[0], f"names a size, but none of them work here: {note[0]}"

    job = {"connect": "dowel", "dowel_d": 6, "n_points": 2, "thickness": 3, "hollow": 8,
           "distribution": "count", "count": 20}
    plan = build(EXAMPLES / "cow_spot.stl", "stacked", job)
    said = [n for n in plan["notes"] if "set dowel_d to about" in n]
    assert said, plan["notes"]
    d = float(re.search(r"set dowel_d to about ([\d.]+) mm", said[0]).group(1))
    assert d < job["dowel_d"], f"offers {d} mm, no smaller than the {job['dowel_d']} mm that just failed"
    after = build(EXAMPLES / "cow_spot.stl", "stacked", {**job, "dowel_d": d})
    assert len(after["rods"]) > 3 * len(plan["rods"]) + 20, f"following the advice ({d} mm) placed few more dowels"

    def bare(plan):                                   # pairs the note says got no connector
        return sum(int(re.search(r"(\d+) pair\(s\) of slices got no connector", n).group(1)) for n in plan["notes"] if "no connector" in n)

    assert bare(after) <= bare(plan) // 4, (bare(plan), bare(after))      # measured 18 → 4


def test_a_scan_with_a_hole_slices(tmp_path):
    """A mesh open at one end (the egg with its top 15 % gone, as a scan often is) is remeshed into the solid it
    encloses, the hole closed straight across: as wide as the egg, as tall as what is left of it. At the rim of the hole
    three cut segments met at an end and the slice failed ("need at least one array to concatenate")."""
    egg = trimesh.load(EXAMPLES / "egg.stl", force="mesh")
    top = egg.bounds[1][2] - 0.15 * egg.extents[2]
    egg.update_faces(egg.triangles_center[:, 2] <= top)
    egg.export(tmp_path / "open.stl")
    plan = build(tmp_path / "open.stl", "stacked", {"distribution": "count", "count": 8, "connect": "none", "autofix": "off"})
    assert abs(plan["bbox"][0] - 180) < 2.5 and abs(plan["bbox"][1] - 120) < 2.5           # the egg is 180 × 120 × 150
    assert abs(plan["bbox"][2] - (top - egg.bounds[0][2])) < 2.5                          # 127.5 left of its 150
    assert plan["counts"]["parts"] == 8 and plan["counts"]["errors"] == 0


def test_a_new_name_reslices_without_remeshing(tmp_path):
    """Changing the project name (or anything that does not shape the model) reuses the model as prepared and its
    preview: no second remesh, the same parts and notes. Changing a modify-form value remeshes again (reported: a name
    took a full re-mesh)."""
    job = {"distribution": "count", "count": 6, "connect": "none", "autofix": "off", "round": 3}
    a = build(EXAMPLES / "egg.stl", "stacked", {**job, "project": "first"}, mesh_out=tmp_path / "a.stl")
    b = build(EXAMPLES / "egg.stl", "stacked", {**job, "project": "second"}, mesh_out=tmp_path / "b.stl")
    p = coerce_params(MODES["stacked"], {**job, "project": "third"})
    m, again = load_mesh(EXAMPLES / "egg.stl", p, []), lambda _: pytest.fail("worked out again")
    reuse(m, "preview", again); reuse(m, "square", again)      # the builds kept both (no timing: CI is slow)
    c = build(EXAMPLES / "egg.stl", "stacked", {**job, "project": "second", "round": 4})
    assert "modify form: remeshing" in a["timing"] and "modify form: remeshing" not in b["timing"]
    assert (tmp_path / "a.stl").read_bytes() == (tmp_path / "b.stl").read_bytes()
    assert a["notes"] == b["notes"] and a["bbox"] == b["bbox"] and a["coverage"] == b["coverage"]
    assert [s["extents"] for s in a["slices"]] == [s["extents"] for s in b["slices"]]
    assert b["label_tag"] == "SECO"
    assert "modify form: remeshing" in c["timing"] and c["bbox"] != b["bbox"]


@pytest.mark.skipif(os.name == "nt", reason="Windows refuses to swap a file someone is reading: there it is written in place")
def test_a_preview_being_downloaded_is_never_cut_short(tmp_path):
    """The page may still be downloading the last preview when the next slice writes its own. Rewritten in place, the
    download got a file cut short ("network error" in the 3D view, Linux CI). Swapped in whole, the download in progress
    reads the whole old file and the next one finds the whole new one."""
    out = tmp_path / "model.stl"
    job = {"distribution": "count", "count": 4, "connect": "none", "autofix": "off"}
    build(EXAMPLES / "egg.stl", "stacked", {**job, "round": 3}, mesh_out=out)
    size = out.stat().st_size
    with open(out, "rb") as reading:                      # a download that has the file open
        build(EXAMPLES / "egg.stl", "stacked", {**job, "round": 6}, mesh_out=out)
        assert len(reading.read()) == size                 # the old preview, whole
    data = out.read_bytes()
    assert len(data) == 84 + 50 * int.from_bytes(data[80:84], "little") != size   # the new one, whole, and new
