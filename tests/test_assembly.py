"""The insertion sweep: a part must be able to slide into its slot along the crossing line."""
import pathlib

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
GRID = {"nx": 3, "ny": 3, "thickness": 3, "autofix": "off"}


def test_a_hollow_section_crossed_twice_cannot_be_assembled():
    """A tube on its side, sliced vertically: every crossing line goes through the top wall and the bottom wall.
    Half-lap slots meet on each wall, but the part's material on the other wall lies in the path — reported."""
    plan = build(EXAMPLES / "tube.stl", "interlocked", {**GRID, "rotate": [90, 0, 0]})
    blocked = [e for sl in plan["slices"] for e in sl["errors"] if "cannot slide into its slot" in e]
    assert blocked
    assert all("material is in its path" in e for e in blocked)


def test_a_hollow_section_is_blocked_in_every_material():
    """The tube's far wall puts 9 mm and more of material in the way: no sheet bends that aside or has it trimmed, not
    even the softest one the checks know."""
    from core.checks import FIT
    softest = max(FIT, key=lambda k: FIT[k][0])
    plan = build(EXAMPLES / "tube.stl", "interlocked", {**GRID, "rotate": [90, 0, 0], "material_kind": softest})
    assert [e for sl in plan["slices"] for e in sl["errors"] if "cannot slide into its slot" in e]


def test_the_material_sets_how_much_in_the_way_a_slice_gets_past(tmp_path):
    """A ring with a 5 mm wall puts 4 mm of material in each crossing slice's way: plywood is sanded that far, acrylic
    is not, and the error says what the material lets through."""
    import trimesh
    ring = tmp_path / "ring.stl"
    trimesh.creation.annulus(25, 30, 80, sections=96).export(ring)
    job = {**GRID, "rotate": [90, 0, 0]}
    blocked = lambda plan: [e for sl in plan["slices"] for e in sl["errors"] if "cannot slide into its slot" in e]   # noqa: E731
    assert not blocked(build(ring, "interlocked", {**job, "material_kind": "plywood"}))
    errs = blocked(build(ring, "interlocked", {**job, "material_kind": "acrylic"}))
    assert errs and all("acrylic lets 3 mm through" in e for e in errs)


def test_a_solid_section_slides_in():
    plan = build(EXAMPLES / "egg.stl", "interlocked", GRID)
    assert not [e for sl in plan["slices"] for e in sl["errors"] if "cannot slide" in e]
    assert plan["counts"]["errors"] == 0
