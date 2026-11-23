"""Holding bridges (core.bridges): where they go on an outline, what they leave standing, and how the export writes the
outline they interrupt. Geometry is measured on the result, never taken from the placer's own numbers."""
import math
import pathlib

import ezdxf
from lxml import etree
from shapely.geometry import LineString, Point, box

from core.bridges import gap_of, place, reach_of, split
from core.export import design_name, export
from core.plan import build

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def ring(poly):
    return list(poly.exterior.coords)[:-1]


def gaps(r, pieces):
    """The gaps between consecutive open stretches, as (start, end) points."""
    return [(a[-1], b[0]) for a, b in zip(pieces, pieces[1:] + pieces[:1])]


def test_the_gap_is_the_width_plus_the_kerf_so_the_web_left_is_the_width():
    sq = box(0, 0, 40, 40)
    for width, kerf in ((0.5, 0.2), (1.0, 0.0), (0.3, 0.15)):
        pieces = split(ring(sq), place(ring(sq), [], 2, width, kerf, 3.0), width, kerf)
        assert len(pieces) == 2
        for a, b in gaps(ring(sq), pieces):
            assert abs(math.dist(a, b) - gap_of(width, kerf)) < 1e-6 and gap_of(width, kerf) == width + kerf
        cut = sum(LineString(p).length for p in pieces)
        assert abs(cut + 2 * (width + kerf) - 160) < 1e-6          # the stretches and the gaps make up the whole outline


def test_two_bridges_sit_mid_edge_on_opposite_sides_and_four_one_per_side():
    sq = box(0, 0, 40, 40)
    for n in (2, 4):
        mids = [Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                for a, b in gaps(ring(sq), split(ring(sq), place(ring(sq), [], n, 0.5, 0.1, 3.0), 0.5, 0.1))]
        sides = {min(range(4), key=lambda k: [m.y, 40 - m.x, 40 - m.y, m.x][k]) for m in mids}
        assert len(sides) == n                                      # each on its own side
        for m in mids:                                              # and well away from the corners
            assert min(math.dist((m.x, m.y), c) for c in ((0, 0), (40, 0), (40, 40), (0, 40))) > 10


def test_no_bridge_inside_a_slot_however_many_are_asked_for():
    # a 60 x 40 part with a 3 mm slot 20 mm deep from the top, like an interlocked slice
    part = box(0, 0, 60, 40).difference(box(28.5, 20, 31.5, 41))
    slot = box(28.4, 19.9, 31.6, 40.1)
    for n in range(1, 9):
        c = place(ring(part), [], n, 0.5, 0.15, reach_of({}, 3.0))
        assert c
        for a, b in gaps(ring(part), split(ring(part), c, 0.5, 0.15)):
            assert not slot.contains(Point(a)) and not slot.contains(Point(b))


def test_no_bridge_on_a_puzzle_tab_or_a_plaque_tooth():
    # a strip with a tab sticking out of its right end (the width of `tab`), and teeth along its bottom
    tab = box(100, 12, 108, 20)
    teeth = [box(10 + 25 * k, -6, 20 + 25 * k, 0.5) for k in range(4)]
    part = box(0, 0, 100, 32).union(tab)
    for t in teeth:
        part = part.union(t)
    keep_off = [tab.buffer(0.1)] + [t.buffer(0.1).difference(box(-1, 0.4, 101, 33)) for t in teeth]
    r = reach_of({"tab": 8, "tooth_width": 10}, 3.0)
    for n in (2, 4, 8):
        for a, b in gaps(ring(part), split(ring(part), place(ring(part), [], n, 0.5, 0.1, r), 0.5, 0.1)):
            mid = Point((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            assert not any(k.contains(mid) for k in keep_off), (n, mid)


def test_no_bridge_at_the_end_of_a_fold_line():
    sq = box(0, 0, 40, 40)
    end = (20.0, 0.0)                                               # a fold meeting the bottom edge mid-way
    c = place(ring(sq), [], 4, 0.5, 0.1, 3.0, ends=[end, (20.0, 40.0)])
    for a, b in gaps(ring(sq), split(ring(sq), c, 0.5, 0.1)):
        assert math.dist(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), end) > 1.5


def test_a_short_outline_gets_fewer_and_a_tiny_one_none():
    small = box(0, 0, 4, 4)                                         # 16 mm round: room for 4 at most with 0.6 mm gaps + 1.5 mm clearance
    assert 1 <= len(place(ring(small), [], 8, 0.5, 0.1, 3.0)) < 8
    assert place(ring(box(0, 0, 0.8, 0.8)), [], 2, 0.5, 0.1, 3.0) == []


def test_a_narrow_part_still_gets_its_bridges():
    # a ring slice's wall (6 mm) is narrower than twice the joint reach: the whole part is not mistaken for a tab
    wall = Point(0, 0).buffer(50, 64).difference(Point(0, 0).buffer(44, 64))
    assert len(place(ring(wall), [list(wall.interiors[0].coords)[:-1]], 3, 0.5, 0.1, reach_of({}, 3.0))) == 3


def _cube_plan(**extra):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    plan["params"].update(extra)
    return plan


def test_the_export_cuts_each_outline_as_open_stretches_between_its_bridges(tmp_path):
    plan = _cube_plan(bridges=3, bridge_width=0.5)
    export(plan, tmp_path, fmts=("svg", "dxf"), labels=True)
    name = design_name(plan)
    tree = etree.parse(str(tmp_path / f"{name} sheet1.svg"))
    outer = tree.xpath('//svg:g[@class="OUTER"]/svg:path', namespaces=SVG_NS)
    parts = {p.get("data-label") for p in outer}
    assert None not in parts                                        # every stretch still names its part (the sheet view picks by it)
    for lab in parts - {"scale-check"}:
        ds = [p.get("d") for p in outer if p.get("data-label") == lab]
        assert len(ds) == 3 and not any(d.rstrip().endswith("Z") for d in ds)
    dxf = ezdxf.readfile(tmp_path / f"{name} sheet1.dxf")
    out = [e for e in dxf.modelspace().query("LWPOLYLINE") if e.dxf.layer == "OUTER"]
    assert out and not any(e.closed for e in out) and len(out) == 3 * len(parts)


def test_no_bridges_leaves_every_outline_closed(tmp_path):
    for plan in (_cube_plan(), _cube_plan(bridges=2, printed=True)):
        export(plan, tmp_path, fmts=("dxf",), labels=False)
        dxf = ezdxf.readfile(tmp_path / f"{design_name(plan)} sheet1.dxf")
        assert all(e.closed for e in dxf.modelspace().query("LWPOLYLINE") if e.dxf.layer in ("OUTER", "INNER"))
