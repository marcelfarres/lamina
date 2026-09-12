"""Modify form and connector placement keep to what was asked: a small thicken stays small, a square dowel keeps
its wall."""
import pathlib

from core.plan import build

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


def test_build_reports_its_progress_from_start_to_one():
    """The browser worker shows these on the page: every stage in order, per-slice sections, ending at 1.0."""
    import core.plan as P
    seen = []
    P.progress = lambda text, frac: seen.append((text, frac))
    try:
        build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off"})
    finally:
        P.progress = lambda text, frac: None
    fr = [f for _, f in seen]
    assert fr == sorted(fr) and fr[0] < 0.1 and fr[-1] == 1.0
    assert sum("sectioning" in t for t, _ in seen) == 4 and any("nesting" in t for t, _ in seen)


def test_square_dowel_keeps_its_wall_to_the_outline():
    """Random points are sampled a margin inside the overlap; that margin must come from the hole's real reach (a
    square's corner, 0.71 d), or the wall check flags every hole near a curved edge."""
    plan = build(EXAMPLES / "cone.stl", "stacked",
                 {"connect": "dowel", "dowel_shape": "square", "placement": "random", "dowel_d": 8, "n_points": 2,
                  "space": 5, "distribution": "count", "count": 6, "autofix": "off"})
    assert plan["rods"]                              # the dowels are there (rods, not cut parts)
    assert not [w for sl in plan["slices"] for w in sl["warnings"] if "closer than" in w]
