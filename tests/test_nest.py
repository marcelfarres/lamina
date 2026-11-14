"""core.nest packs Pieces onto sheets via two different algorithms depending on how many pieces
there are (rectangle packing above core.nest.MANY, greedy polygon fitting below it). Both paths must
place every part inside its sheet (minus margin) with zero pairwise overlap. Checked geometrically
with shapely against the plan's own placed coordinates, not against anything nest.py reports about
itself — the routing threshold is force-selected via monkeypatch so this doesn't depend on where
MANY is currently set.
"""
import math
import pathlib

import numpy as np
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

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


@pytest.mark.parametrize(("model", "mode", "params", "many"), [
    ("tube", "folded", {"thickness": 1, "kerf": 0.15}, None),
    ("bowl", "stacked", {"sheet": [200, 150], "kerf": 0.15}, None)],      # 164 parts: the rectangle packer
    ids=["sheet_sized_panel", "rect_path_full_sheet"])
def test_every_part_lands_inside_the_sheet_margin(monkeypatch, model, mode, params, many):
    """Found by the validation sweep: 1271 parts in 181 jobs outside the margin. A folded panel that fills the
    sheet so exactly that the gap tips it over (586 × 390 mm on 600 × 400) was placed by its unturned corner and
    landed 485 mm off the sheet; the rectangle packer centred each part in a rectangle one gap bigger, so every part
    along the far edges ran half a gap into the margin."""
    if many is not None:
        monkeypatch.setattr(nest, "MANY", many)
    plan = build(EXAMPLES / f"{model}.stl", mode, params)
    sw, sh = plan["sheet"]; m = plan["params"]["sheet_margin"]
    for i in range(plan["sheets"]):
        for poly in placed_polygons(plan, i):
            x0, y0, x1, y1 = poly.bounds
            assert x0 >= m - 1e-6 and y0 >= m - 1e-6 and x1 <= sw - m + 1e-6 and y1 <= sh - m + 1e-6, \
                f"sheet {i}: ({x0:.1f},{y0:.1f})-({x1:.1f},{y1:.1f}) outside the {m:g} mm margin of {sw:g} × {sh:g}"


@pytest.mark.parametrize(("model", "mode", "params"), [
    ("pyramid", "interlocked", {"autofix": "off"}),
    ("pyramid", "radial", {"spine": 1}),
    ("cube", "radial", {"rotate": [30, 20, 0]})])
def test_no_two_parts_are_nested_on_top_of_each_other(model, mode, params):
    """Found by the validation sweep: parts overlapping on the sheet by up to 773 mm². A no-fit polygon was traced
    from the piece's lowest vertex while its edges were sorted by angle, and an edge horizontal to within rounding
    sorted first: every no-fit polygon of that part came out shifted by the edge, and spots inside them read as free."""
    plan = build(EXAMPLES / f"{model}.stl", mode, {"thickness": 3, "slot_offset": 0.2, "kerf": 0.15, **params})
    for i in range(plan["sheets"]):
        polys = placed_polygons(plan, i)
        for a in range(len(polys)):
            for b in range(a + 1, len(polys)):
                assert polys[a].intersection(polys[b]).area < 1e-6, f"sheet {i}: {a} over {b}"


def test_a_part_too_big_for_the_sheet_keeps_its_sheet_to_itself():
    """A model far bigger than the sheet, split off: whatever cannot be cut small enough overhangs its sheet, but it
    may never be nested over — the reported "parts overlap each other and run off the page" was a part placed
    without its no-fit polygon, so every later part read the sheet as empty."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 6, "size": [600, 600, 300],
                                                    "sheet": [200, 150], "split": False, "autofix": "off"})
    assert any("bigger than the 200 × 150 mm sheet" in e for e in plan["errors"]), plan["errors"]
    for sheet_index in range(plan["sheets"]):
        polys = placed_polygons(plan, sheet_index)
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                assert polys[i].intersection(polys[j]).area < 1e-6, f"sheet {sheet_index}: {i} over {j}"


def test_a_part_over_the_sheet_both_ways_is_cut_both_ways():
    """One pass of the splitter fixes one direction. A part wider and longer than the sheet needs both, or the pieces
    it produces still do not fit and land on top of each other."""
    from types import SimpleNamespace
    from shapely.geometry import box
    from core.geometry import as_multi
    from core.split import split_slice, fits_rotated
    sl = SimpleNamespace(label="Z-1", profile=as_multi(box(0, 0, 600, 400)), lines=[], marks=[], warnings=[], errors=[],
                         pieces=None, facets=None, thickness=3)
    split_slice(sl, (300, 300), 5, 8)
    assert len(sl.pieces) >= 4
    assert all(fits_rotated(pc.geom, (300, 300), 5) for pc in sl.pieces), [pc.geom.bounds for pc in sl.pieces]
    assert abs(sum(pc.geom.area for pc in sl.pieces) - 600 * 400) < 1e-6      # the pieces still tile the part


@pytest.mark.parametrize("many", [0, 10_000], ids=["rect_path", "polygon_path"])
def test_keep_the_grain_lays_every_part_as_it_stands_or_upside_down(monkeypatch, many):
    """Asked for (032): the grain has to run the same way through every part. With `grain` each part's placed outline
    is its own outline moved, or turned 180°, never sideways; without it the nester turns this cube's slices 270°."""
    from shapely import affinity
    monkeypatch.setattr(nest, "MANY", many)
    model, mode, params = BUILD_ARGS

    shape = lambda rings: unary_union([Polygon(r[0], r[1:]) for r in rings])

    def off(own, placed, deg):                       # what is left over when the part's own outline, turned, is laid on it
        g = affinity.rotate(own, deg, origin=(0, 0))
        return affinity.translate(g, placed.bounds[0] - g.bounds[0], placed.bounds[1] - g.bounds[1]).symmetric_difference(placed).area

    def turns(plan):
        pairs = [(shape(pc["kerfed"]), shape(pc["placed"])) for sl in plan["slices"] for pc in sl["pieces"]]
        return [min((0, 90, 180, 270), key=lambda d: off(own, placed, d)) for own, placed in pairs]

    assert any(t in (90, 270) for t in turns(build(model, mode, params)))
    kept = build(model, mode, {**params, "grain": True})
    assert set(turns(kept)) <= {0, 180}, turns(kept)
    assert not kept["errors"]


def test_keep_the_grain_splits_a_part_that_only_fits_turned():
    """A 580 × 380 part on a 400 × 600 sheet fits only turned sideways: with `grain` it is cut across its width into
    pieces that fit as they stand, and only that way."""
    from types import SimpleNamespace
    from shapely.geometry import box
    from core.geometry import as_multi
    from core.split import split_slice
    part = lambda: SimpleNamespace(label="Z-1", profile=as_multi(box(0, 0, 580, 380)), lines=[], marks=[], warnings=[],
                                   errors=[], pieces=None, facets=None, thickness=3)
    free, kept = part(), part()
    split_slice(free, (400, 600), 5, 8)
    split_slice(kept, (400, 600), 5, 8, grain=True)
    assert len(free.pieces) == 1
    assert len(kept.pieces) == 2, [pc.geom.bounds for pc in kept.pieces]
    for pc in kept.pieces:
        x0, y0, x1, y1 = pc.geom.bounds
        assert x1 - x0 <= 390 and y1 - y0 <= 590 and y1 - y0 > 370       # cut across x only: each keeps the full height
    assert abs(sum(pc.geom.area for pc in kept.pieces) - 580 * 380) < 1e-6


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
    files = {f.name.split(" ", 1)[1] for f in export(plan, tmp_path, fmts=("svg",), labels=True)}
    assert f"sheet{sheet_of['Z-2'] + 1} 6mm.svg" in files
    assert any(f.endswith(" 3mm.svg") for f in files)
    pieces = {f.name.split(" ", 1)[1] for f in export(plan, tmp_path / "pp", fmts=("svg",), labels=True, per_piece=True)}
    assert "Z-2 6mm x1.svg" in pieces                          # the identical squares are not merged across stock
    assert any(f.startswith("Z-1") and f.endswith(" 3mm x3.svg") for f in pieces)


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


def test_a_layer_in_separate_islands_is_cut_as_separate_parts(tmp_path):
    """Two blocks 300 mm apart: every layer falls apart into two islands. Each island is its own part, labelled and
    nested on its own, so both fit a 200 mm sheet. As one part per layer they spanned 350 mm, fitted no sheet, and
    the lobes of a real model's layer kept the empty space between them on the sheet with one label for all."""
    import trimesh
    far = trimesh.creation.box((50, 50, 30)); far.apply_translation((300, 0, 0))
    trimesh.util.concatenate([trimesh.creation.box((50, 50, 30)), far]).export(tmp_path / "two.stl")
    plan = build(tmp_path / "two.stl", "stacked", {"distribution": "count", "count": 3, "sheet": [200, 200], "split": False, "autofix": "off"})
    for sl in plan["slices"]:                       # (two loose blocks are rightly "not connected"; what matters: they fit)
        assert not [e for e in sl["errors"] if "does not fit" in e], sl["errors"]
        assert sorted(pc["label"] for pc in sl["pieces"]) == [f"{sl['label']}-1", f"{sl['label']}-2"]
        for pc in sl["pieces"]:
            assert pc["label_pos"], pc["label"]                                  # every island carries its own label
            x0, y0, x1, y1 = Polygon(pc["placed"][0][0]).bounds
            assert x1 - x0 < 60 and y1 - y0 < 60, (pc["label"], x1 - x0, y1 - y0)   # one 50 mm block, not both


def test_one_sheet_is_as_long_as_the_parts_and_their_labels():
    """`one_sheet` reports the strip at the length it took: the topmost part's label, placed above it, is on the sheet
    too, not past its end where the cut file would clip it."""
    from core.geometry import label_box
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "one_sheet": True, "font": 10})
    font = plan["params"]["font"]
    for pc in (pc for sl in plan["slices"] for pc in sl["pieces"]):
        x, y, rot = pc["label_pos"]
        w, h = label_box(f"{plan['label_tag']} {pc['label']}".strip(), font)
        assert y + (h if rot == 0 else w) / 2 <= plan["sheet"][1], (pc["label"], pc["label_pos"], plan["sheet"])


def test_labels_inside_sit_on_their_part_and_a_lone_part_file_grows_to_hold_one(tmp_path):
    """`label_place` = on: every label is engraved on its own part — its centre inside the part's placed outline, with no
    leader line — while `beside` puts every one beside the part with a leader. In the one-file-per-part export a
    label wider than the part (a 60 mm font on the cube's 180 mm slab) is drawn whole: the drawing grows past the part."""
    import re
    from shapely.geometry import Point
    from core.export import export
    base = {"distribution": "count", "count": 3, "autofix": "off"}
    plan = build(EXAMPLES / "cube.stl", "stacked", {**base, "label_place": "on"})
    pieces = [pc for sl in plan["slices"] for pc in sl["pieces"]]
    for pc in pieces:
        x, y, _ = pc["label_pos"]
        assert Polygon(pc["placed"][0][0], pc["placed"][0][1:]).covers(Point(x, y)), pc["label"]
        assert pc["leader"] is None
    beside = build(EXAMPLES / "cube.stl", "stacked", {**base, "label_place": "beside"})
    assert all(pc["leader"] for sl in beside["slices"] for pc in sl["pieces"])

    x0, _, x1, _ = Polygon(pieces[0]["placed"][0][0]).bounds
    plan["params"]["font"] = 60.0                                     # "cube Z-1" at 60 mm: about 300 mm of label on a 180 mm slab
    for pc in pieces:
        pc["label_size"] = 60.0                                       # the size the sheet gave each label: the export engraves at it
    files = [f for f in export(plan, tmp_path, fmts=("svg",), labels=True, per_piece=True) if " Z-1 " in f.name]
    width, height = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', files[0].read_text(encoding="utf-8")).groups())
    assert max(width, height) > 1.5 * (x1 - x0), (width, height)    # the page outgrows the slab the way the label runs: it is all on it


@pytest.mark.parametrize("model, mode, params", [
    ("egg", "radial", {"count": 8, "ring_count": 5}),                                   # rings and half-slices: labels on the big ones, beside the slim ones
    ("torus", "interlocked", {"nx": 9, "ny": 7}),                                        # slotted rings: most labels beside
    ("cube", "stacked", {"distribution": "count", "count": 6, "placement": "random"}),   # slabs with dowel marks: labels on the parts, clear of the marks
])
def test_labels_sit_on_their_part_or_in_free_space_and_overlap_nothing(model, mode, params):
    """The default placement: a label is engraved on its own part when the whole of it fits on the material, clear of
    the holes and the marks there; otherwise it goes beside the part, inside the sheet margin, touching no part and no
    other label, with a leader line that crosses no other part. Nothing here was short of room (no crowded note)."""
    import shapely
    from shapely.geometry import LineString
    from core.geometry import label_box, label_rect, mark_box
    plan = build(EXAMPLES / f"{model}.stl", mode, {**params, "autofix": "off"})
    assert not [n for n in plan["notes"] if "no free spot" in n], plan["notes"]
    font, tag, m = plan["params"]["font"], plan["label_tag"], plan["params"]["sheet_margin"]
    W, H = plan["sheet"]
    pieces = [pc for sl in plan["slices"] for pc in sl["pieces"]]
    for si in range(plan["sheets"]):
        on = [pc for pc in pieces if pc["place"][0] == si]
        parts = {pc["label"]: shapely.union_all([Polygon(r[0], r[1:]) for r in pc["placed"]]) for pc in on}
        rects = {pc["label"]: label_rect(*pc["label_pos"], *label_box(f"{'' if pc['label_short'] else tag} {pc['label']}".strip(), pc["label_size"])) for pc in on}
        # room for every one in full or at four fifths — on the part, or right beside it, which wins over a full one
        # farther away — or at two thirds on the part itself (a narrow ring's name along the ring, rather than a line to it)
        assert all(pc["label_size"] >= 0.8 * font - 1e-9 or (pc["leader"] is None and pc["label_size"] >= 0.65 * font - 1e-9) for pc in on), \
            [(pc["label"], pc["label_size"]) for pc in on if pc["label_size"] < 0.8 * font]
        assert all(not pc["label_short"] or pc["leader"] is None for pc in on)      # the short form only ever on the part
        for pc in on:
            lab, r = pc["label"], rects[pc["label"]]
            if pc["leader"] is None:                                            # on the part: whole, and off its marks
                assert parts[lab].buffer(0.01).covers(r), lab
                assert all(r.disjoint(mark_box(x, y, t, font, rot + pc["place"][3])) for x, y, t, rot in pc["marks"]), lab
                continue
            x0, y0, x1, y1 = r.bounds
            assert x0 >= m - 1e-6 and y0 >= m - 1e-6 and x1 <= W - m + 1e-6 and y1 <= H - m + 1e-6, (lab, r.bounds)
            assert all(r.disjoint(g) for g in parts.values()), lab
            assert all(r.disjoint(rects[o]) for o in rects if o != lab), lab
            lead = LineString(pc["leader"])
            assert all(lead.disjoint(g) for o, g in parts.items() if o != lab), lab
            assert parts[lab].distance(lead) < 1e-3                             # it points at its own part


def test_seven_rings_fill_the_first_sheet_before_the_second():
    """Seven 180 mm rings on 600 × 400: the polygon nest drops the second row into the valleys of the first and fits
    five, the plain rectangle packing six. Same sheet count either way, so the one that leaves less for the last
    sheet is kept — the first sheet full, the second with the rest (the tube example had five, two and one)."""
    from types import SimpleNamespace
    from shapely.geometry import Point
    from core.geometry import as_multi
    from core.model import Piece
    stock = SimpleNamespace(thickness=3)
    rings = [Piece(f"Z-{i + 1}", as_multi(Point(0, 0).buffer(90).difference(Point(0, 0).buffer(80))), stock) for i in range(7)]
    assert nest.nest(rings, (600, 400), gap=3, margin=5) == 2
    assert sorted(pc.place[0] for pc in rings) == [0] * 6 + [1]


def test_a_disc_nests_inside_a_ring_full_of_dowel_holes():
    """A hollow model's slice is a ring with a wide middle and a dowel hole every few degrees along its band. Each
    hole was a notch to the convex decomposition behind the no-fit polygons; past the piece cap the ring became its
    hull and its middle was lost. The small holes are filled before that cut, and the disc goes in the middle."""
    from types import SimpleNamespace
    from shapely.geometry import Point
    from core.geometry import as_multi
    from core.model import Piece
    stock = SimpleNamespace(thickness=3)
    band = Point(0, 0).buffer(40).difference(Point(0, 0).buffer(30))
    holes = [Point(35 * math.cos(a), 35 * math.sin(a)).buffer(1.5) for a in np.linspace(0, 2 * math.pi, 30, endpoint=False)]
    ring = Piece("ring", as_multi(band.difference(unary_union(holes))), stock)
    disc = Piece("disc", as_multi(Point(0, 0).buffer(25)), stock)
    assert len(ring.geom.geoms[0].interiors) == 31
    assert nest.nest([ring, disc], (100, 100), gap=2, margin=0) == 1
    assert ring.placed.geoms[0].interiors[0].envelope.contains(disc.placed) or any(Polygon(i).contains(disc.placed) for i in ring.placed.geoms[0].interiors)


def test_two_turns_of_a_part_never_drop_the_same_kept_union():
    """A part's four turns ask a sheet for a spot side by side, and the sheet keeps the no-fit union of the last 16
    shapes. Two turns that both found it full dropped the same oldest entry, the second had nothing left to drop, and
    the whole slice failed with a KeyError: seen only on a busy machine, where the two get that close. Here every drop
    waits a moment between choosing the entry and dropping it, so they always do."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    class Slow(dict):
        def __delitem__(self, key):
            time.sleep(0.02)
            super().__delitem__(key)

    rect = lambda w, h: np.array([(0, 0), (w, 0), (w, h), (0, h)], float)   # noqa: E731
    ask = lambda sh, c: sh.spot([c], (0.0, 0.0, c[2, 0], c[2, 1]))          # noqa: E731
    sh = nest.Sheet(600, 400, 5)
    sh.convex.append(nest._edges(rect(100, 100)))
    sh.nfp = Slow()
    for i in range(16):                                    # the 16 it keeps
        ask(sh, rect(10 + i, 10))
    with ThreadPoolExecutor(8) as pool:                    # eight new shapes at once
        spots = list(pool.map(lambda i: ask(sh, rect(40 + i, 12)), range(8)))
    assert all(xy is not None for xy in spots) and len(sh.nfp) <= 16
