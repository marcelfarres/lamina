"""core.nest packs Pieces onto sheets via two different algorithms depending on how many pieces
there are (rectangle packing above core.nest.MANY, greedy polygon fitting below it). Both paths must
place every part inside its sheet (minus margin) with zero pairwise overlap. Checked geometrically
with shapely against the plan's own placed coordinates, not against anything nest.py reports about
itself — the routing threshold is force-selected via monkeypatch so this doesn't depend on where
MANY is currently set.
"""
import pathlib

import pytest
from shapely.geometry import Polygon

import core.nest as nest
from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

# interlocked cube with nx=4, ny=4 -> 8 slices, at least 8 placed pieces: enough to force multiple
# sheets and real packing decisions under both algorithms.
BUILD_ARGS = (EXAMPLES / "cube.stl", "interlocked", {"nx": 4, "ny": 4, "autofix": "off"})


def placed_polygons(plan, sheet_index):
    """Rebuild real shapely polygons from a plan's own placed (sheet-space, kerf-applied) geometry
    for one sheet — this is the ground truth the nester produced, independent of its own bookkeeping.

    pc["placed"] is core.geometry.poly_coords() output: one entry per disjoint region, each region a
    list of rings [exterior, hole, hole, ...]."""
    polys = []
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            if pc["place"] is None or pc["place"][0] != sheet_index:
                continue
            for region in pc["placed"]:
                polys.append(Polygon(region[0], holes=region[1:]))
    return polys


@pytest.mark.parametrize("many", [0, 10_000], ids=["rect_path", "polygon_path"])
def test_placed_parts_fit_sheet_and_dont_overlap(monkeypatch, many):
    monkeypatch.setattr(nest, "MANY", many)
    model, mode, params = BUILD_ARGS
    plan = build(model, mode, params)

    assert plan["counts"]["parts"] > 0
    sw, sh = plan["sheet"]
    margin = plan["params"].get("sheet_margin", 0)

    for sheet_index in range(plan["sheets"]):
        polys = placed_polygons(plan, sheet_index)
        assert polys, f"sheet {sheet_index} has no placed pieces"

        for poly in polys:
            minx, miny, maxx, maxy = poly.bounds
            assert minx >= margin - 1e-6
            assert miny >= margin - 1e-6
            assert maxx <= sw - margin + 1e-6
            assert maxy <= sh - margin + 1e-6

        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                overlap = polys[i].intersection(polys[j]).area
                assert overlap < 1e-6, f"pieces {i} and {j} on sheet {sheet_index} overlap by {overlap}"


def test_a_part_of_another_thickness_gets_its_own_sheet_and_says_so(tmp_path):
    """One slice thickened by hand is cut from other stock: it may not share a sheet with the rest, the plan says
    what each sheet is cut from, and the cut files name it so the wrong sheet is not loaded on the machine."""
    from core.export import export, sheet_title
    params = {"distribution": "count", "count": 4, "thickness": 3, "thick": {"Z-2": 6}, "autofix": "off"}
    plan = build(EXAMPLES / "cube.stl", "stacked", params)
    odd = next(sl for sl in plan["slices"] if sl["label"] == "Z-2")
    assert odd["thickness"] == 6
    sheet_of = {pc["label"]: pc["place"][0] for sl in plan["slices"] for pc in sl["pieces"]}
    others = {sheet_of[pc["label"]] for sl in plan["slices"] for pc in sl["pieces"] if sl["label"] != "Z-2"}
    assert sheet_of["Z-2"] not in others                       # never nested together with the 3 mm parts
    assert plan["sheet_thick"][sheet_of["Z-2"]] == 6
    assert all(plan["sheet_thick"][s] == 3 for s in others)
    assert "6 mm stock" in sheet_title(plan, sheet_of["Z-2"]) and "3 mm stock" in sheet_title(plan, min(others))
    files = {f.name for f in export(plan, tmp_path, fmts=("svg",), labels=True)}
    assert f"sheet{sheet_of['Z-2'] + 1}_6mm.svg" in files
    assert any(f.endswith("_3mm.svg") for f in files)
    pieces = {f.name for f in export(plan, tmp_path / "pp", fmts=("svg",), labels=True, per_piece=True)}
    assert "Z-2_6mm.svg" in pieces                             # the identical squares are not merged across stock
    assert any(f.startswith("Z-1") and f.endswith("_3mm.svg") for f in pieces)


def test_a_disc_nests_inside_a_ring():
    """What the no-fit polygons buy over a corner search: the free region of a ring includes its hole, so a disc that
    fits the hole goes there, and one sheet holds both where two used to be needed."""
    from types import SimpleNamespace
    from shapely.geometry import Point
    from core.geometry import as_multi
    from core.model import Piece
    stock = SimpleNamespace(thickness=3)
    ring = Piece("ring", as_multi(Point(0, 0).buffer(40).difference(Point(0, 0).buffer(30))), stock)
    disc = Piece("disc", as_multi(Point(0, 0).buffer(25)), stock)
    assert nest.nest([ring, disc], (100, 100), gap=2, margin=0) == 1
    assert ring.placed.geoms[0].interiors[0].envelope.contains(disc.placed)
    assert ring.placed.distance(disc.placed) >= 2 - 1e-6


def test_all_parts_are_placed_somewhere(monkeypatch):
    """Sanity check independent of the sheet/overlap geometry: every piece the plan says exists has a
    place, and the total placed-piece count across sheets matches counts.parts."""
    monkeypatch.setattr(nest, "MANY", 10_000)
    model, mode, params = BUILD_ARGS
    plan = build(model, mode, params)
    placed = [pc for sl in plan["slices"] for pc in sl["pieces"] if pc["place"] is not None]
    assert len(placed) == plan["counts"]["parts"]
