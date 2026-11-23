"""Inside-corner relief for a round bit: real core.plan.build() runs of the torus example (interlocked, 6 mm plywood)
and a ball on Plaque, with the router presets' slot offset and bit. A bit of the job's diameter rolled outside every
outline and inside every hole reaches every inside corner of every slot (bug 074: the dogbone sat in the slot wall)."""
import pathlib

import pytest
import trimesh
from shapely.geometry import MultiPolygon, Polygon

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIT = 3.175                                                    # the router presets' bit (web/static/js/catalog.js)
ROUTER = {"slot_offset": 0.2, "kerf": BIT, "tool_d": BIT, "autofix": "off"}


def missed(plan, group=None):
    """Each piece of material a bit of BIT rolled along the cut lines cannot remove (mm²): in an outline's inside
    corners (closing by the bit) and in a hole's corners (opening by the bit)."""
    r = BIT / 2; out = []
    for s in plan["slices"]:
        if group and s["group"] != group:
            continue
        for pc in s.get("pieces", [s]):
            for ring in pc["kerfed"]:
                g = Polygon(ring[0])
                left = [g.buffer(r, 64).buffer(-r, 64).difference(g)]
                left += [Polygon(h).difference(Polygon(h).buffer(-r, 64).buffer(r, 64)) for h in ring[1:]]
                out += [q.area for m in left for q in getattr(m, "geoms", [m])]
    return out


@pytest.fixture(scope="module")
def ball(tmp_path_factory):
    path = tmp_path_factory.mktemp("relief") / "ball.stl"
    trimesh.creation.icosphere(4, 50.0).export(path)
    return path


@pytest.mark.parametrize("relief", ["square", "dogbone", "tbone_h", "tbone_v"])
def test_a_bit_of_the_jobs_diameter_reaches_every_inside_corner_of_every_slot(relief, ball):
    torus = build(ROOT / "examples" / "torus.stl", "interlocked", {"thickness": 6, "nx": 8, "ny": 8, **ROUTER, "relief": relief})
    plaque = build(ball, "plaque", {"thickness": 3, "space": 3, "split": False, "sheet": [1000, 1000], "sink": 50,
                                    "plate": "circle", **ROUTER, "relief": relief})
    for name, worst in (("torus", max(missed(torus))), ("plate", max(missed(plaque, "W")))):   # the plate's slots
        if relief == "square":
            assert worst > 0.5, name          # no relief: the bit leaves a round corner the mating part stops on
        else:
            assert worst < 0.001, (name, worst)   # 7.44 mm² a corner on the torus when the dogbone sat in the wall


def closest(plan):
    """The smallest distance between two parts on one sheet (mm), as placed: the room a bit has between them."""
    by_sheet = {}
    for s in plan["slices"]:
        for pc in s.get("pieces", [s]):
            by_sheet.setdefault(pc["place"][0], []).append(MultiPolygon([Polygon(r[0], r[1:]) for r in pc["placed"]]))
    return min(a.distance(b) for parts in by_sheet.values() for i, a in enumerate(parts) for b in parts[i + 1:])


def test_parts_closer_than_the_bit_are_warned_and_the_router_gap_keeps_them_two_bits_apart():
    job = {"thickness": 6, "nx": 8, "ny": 8, **ROUTER, "relief": "dogbone", "sheet": [600, 400]}
    said = lambda plan: [w for w in plan["warnings"] if f"{BIT:g} mm bit" in w]     # noqa: E731
    torus = lambda gap: build(ROOT / "examples" / "torus.stl", "interlocked", {**job, "gap": gap})   # noqa: E731
    tight = torus(1)
    assert closest(tight) < BIT and said(tight) and tight["counts"]["warnings"] >= 1
    laser = torus(3)                     # the laser's gap: this layout keeps every pair over one bit (3.36 mm), so no word
    assert closest(laser) >= BIT and not said(laser)
    roomy = torus(2 * BIT)               # the router machines' gap
    assert closest(roomy) >= 2 * BIT - 0.01 and not said(roomy)
