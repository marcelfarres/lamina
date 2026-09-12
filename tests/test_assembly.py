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


def test_a_solid_section_slides_in():
    plan = build(EXAMPLES / "egg.stl", "interlocked", GRID)
    assert not [e for sl in plan["slices"] for e in sl["errors"] if "cannot slide" in e]
    assert plan["counts"]["errors"] == 0
