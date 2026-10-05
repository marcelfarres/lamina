"""Per-piece export merges identical pieces with a quantity and writes a cut list; every export carries a calibration
bar; a split never leaves a partial puzzle tab."""
import pathlib
import types

from shapely.geometry import Point, box
from shapely.ops import unary_union

from core.export import design_name, export, identical_groups
from core.geometry import as_multi
from core.plan import build
from core.split import split_slice

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_per_piece_export_merges_identical_pieces_with_a_quantity(tmp_path):
    """A cube cut into four equal slabs is four identical squares: one file, quantity 4, the twins named in the cut list.
    Every per-piece file is "<part> <material> x<qty>", quantity last and written even when there is one of it."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off", "material": "plywood"})
    files = {f.name.split(" ", 1)[1] for f in export(plan, tmp_path, fmts=("svg", "eps"), labels=True, per_piece=True)}
    assert "Z-1 plywood x4.svg" in files and not any(f.startswith("Z-2") for f in files)
    assert "scale-check plywood x1.svg" in files and "scale-check plywood x1.eps" in files
    cut_list = (tmp_path / f"{design_name(plan)} cut-list.txt").read_text(encoding="utf-8")
    assert "Z-1 plywood x4" in cut_list and "also Z-2, Z-3, Z-4" in cut_list
    assert "×4" in (tmp_path / f"{design_name(plan)} Z-1 plywood x4.svg").read_text(encoding="utf-8")
    # a material of several words is one word in the name, so the spaces still split it into its four fields;
    # a stranger's material name cannot reach outside the folder
    for material, tag in (("stainless steel", "stainless-steel"), ("birch / yard\\..", "birch-yard")):
        plan["params"]["material"] = material
        names = {f.name.split(" ", 1)[1] for f in export(plan, tmp_path / tag, fmts=("svg",), labels=True, per_piece=True)}
        assert f"Z-1 {tag} x4.svg" in names, names
        assert all(len(n.split(" ")) in (3, 4) for n in names if n.endswith(".svg")), names


def test_parts_carry_the_model_name_and_the_cut_list_their_size(tmp_path):
    """Two models have the same part names, so every engraved label starts with the model's (cube Z-1 beside egg Z-1),
    and the cut list gives each part's width × height in the export's units. A name from someone else's file is
    cleaned before it is engraved: a bracket would break the EPS string it is written into."""
    base = {"distribution": "count", "count": 4, "autofix": "off", "connect": "none"}
    plan = build(EXAMPLES / "cube.stl", "stacked", base)
    export(plan, tmp_path / "mm", fmts=("svg",), labels=True, per_piece=True)
    assert ">cube Z-1 ×4<" in (tmp_path / "mm" / f"{design_name(plan)} Z-1 x4.svg").read_text(encoding="utf-8")
    rows = (tmp_path / "mm" / f"{design_name(plan)} cut-list.txt").read_text(encoding="utf-8").splitlines()
    assert "size (mm)" in rows[0] and any(r.startswith(f"{design_name(plan)} Z-1 x4") and "180.0 × 180.0" in r for r in rows), rows
    assert any(r.startswith(f"{design_name(plan)} scale-check") and "100.0 × 12.0" in r for r in rows), rows
    export(plan, tmp_path / "in", fmts=("svg",), labels=True, per_piece=True, units="in")
    assert "7.087 × 7.087" in (tmp_path / "in" / f"{design_name(plan)} cut-list.txt").read_text(encoding="utf-8")   # 180 mm in inches
    export(plan, tmp_path / "sheet", fmts=("svg",), labels=True)
    assert (tmp_path / "sheet" / f"{design_name(plan)} sheet1.svg").read_text(encoding="utf-8").count(">cube Z-") == 4

    odd = build(EXAMPLES / "cube.stl", "stacked", {**base, "project": "my (final) \\ cube"})
    assert odd["label_tag"] == "my final cube"
    export(odd, tmp_path / "odd", fmts=("eps",), labels=True, per_piece=True)
    assert "(my final cube Z-1 ×4)" in (tmp_path / "odd" / f"{design_name(odd)} Z-1 x4.eps").read_text(encoding="latin-1")

    off = build(EXAMPLES / "cube.stl", "stacked", {**base, "label_model": False})
    export(off, tmp_path / "off", fmts=("svg",), labels=True, per_piece=True)
    assert off["label_tag"] == "" and ">Z-1 ×4<" in (tmp_path / "off" / f"{design_name(off)} Z-1 x4.svg").read_text(encoding="utf-8")


def test_mirror_ok_merges_a_part_with_its_mirror_image(tmp_path):
    """With `mirror_ok` a part and the part that is its mirror image share one file, cut twice and one of them turned
    over; the cut list says which one, because turning it over is the difference between a fit and scrap."""
    base = {"autofix": "off"}
    off = build(EXAMPLES / "egg.stl", "curve", base)
    on = build(EXAMPLES / "egg.stl", "curve", {**base, "mirror_ok": True})
    assert not any(pc["flipped"] for sl in off["slices"] for pc in sl["pieces"])       # off by default: no flipping
    flips = [(pc["label"], pc["flipped"]) for sl in on["slices"] for pc in sl["pieces"] if pc["flipped"]]
    assert flips, "no mirror pair found on the curve egg"
    assert len(identical_groups(on)) == len(identical_groups(off)) - len(flips)        # each pair is one file fewer
    files = {f.name.split(" ", 1)[1] for f in export(on, tmp_path, fmts=("svg",), labels=True, per_piece=True)}
    label, twins = flips[0]
    assert f"{label} x2.svg" in files and not any(f.startswith(twins[0] + ".") for f in files)
    cut_list = (tmp_path / f"{design_name(on)} cut-list.txt").read_text(encoding="utf-8")
    assert f"turn over {', '.join(twins)}" in cut_list
    assert "(1 turned over)" in (tmp_path / f"{design_name(on)} {label} x2.svg").read_text(encoding="utf-8")


def test_scale_check_bar_on_the_first_sheet_and_in_inches(tmp_path):
    plan = build(EXAMPLES / "egg.stl", "interlocked", {"nx": 4, "ny": 3, "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    spot = plan["scale_check"]
    assert spot["sheet"] == 0
    assert "10 cm" in (tmp_path / f"{design_name(plan)} sheet1.svg").read_text(encoding="utf-8")
    W, H = 100.0 + plan["kerf"], 12.0 + plan["kerf"]                 # the bar overlaps no part
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            if pc["place"][0] != 0:
                continue
            xs = [x for r in pc["placed"] for x, _ in r[0]]; ys = [y for r in pc["placed"] for _, y in r[0]]
            assert max(xs) <= spot["x"] or min(xs) >= spot["x"] + W or max(ys) <= spot["y"] or min(ys) >= spot["y"] + H
    plan_in = build(EXAMPLES / "egg.stl", "interlocked", {"nx": 4, "ny": 3, "units": "in", "autofix": "off"})
    export(plan_in, tmp_path / "in", fmts=("svg",), labels=True)
    assert "4 in" in (tmp_path / "in" / f"{design_name(plan_in)} sheet1.svg").read_text(encoding="utf-8")
    off = build(EXAMPLES / "egg.stl", "interlocked", {"nx": 4, "ny": 3, "scale_check": False, "autofix": "off"})
    export(off, tmp_path / "off", fmts=("svg",), labels=True)
    assert "10 cm" not in (tmp_path / "off" / f"{design_name(off)} sheet1.svg").read_text(encoding="utf-8")


def test_kerf_applies_only_when_compensation_is_on():
    base = {"nx": 4, "ny": 3, "kerf": 1.0, "autofix": "off"}
    off = build(EXAMPLES / "egg.stl", "interlocked", base)
    on = build(EXAMPLES / "egg.stl", "interlocked", {**base, "compensate": True})
    assert off["kerf"] == 0 and on["kerf"] == 1.0
    assert on["material_area_mm2"] == off["material_area_mm2"]        # the parts themselves are the same
    area = lambda plan: sum(unary_union([box(*[c for c in (min(x for x, _ in r[0]), min(y for _, y in r[0]), max(x for x, _ in r[0]), max(y for _, y in r[0]))]) for r in pc["kerfed"]]).area for sl in plan["slices"] for pc in sl["pieces"])
    assert area(on) > area(off)                                       # but the cut outlines grew by the kerf


def test_split_tabs_are_whole_next_to_a_hole():
    """A bar too long for the sheet is split where a hole sits on the cut: every tab is a complete one, nudged clear of
    the hole or dropped, never clipped into a partial connector."""
    profile = as_multi(box(0, 0, 300, 120).difference(Point(150, 60).buffer(20)))
    sl = types.SimpleNamespace(label="B-1", profile=profile, lines=[], marks=[], warnings=[], pieces=None, facets=None)
    split_slice(sl, (200, 200), 5, 8)
    assert len(sl.pieces) == 2
    assert not any("no puzzle tab" in w for w in sl.warnings)
    a, b = (pc.geom for pc in sl.pieces)
    assert abs(unary_union([a, b]).area - profile.area) < 1e-6
    c = sl.split_cuts[1]
    assert abs(c - 150) >= 20                                          # the cut moved off the hole …
    assert sum(len(p.interiors) for pc in sl.pieces for p in pc.geom.geoms) == 1   # … which is whole, on one piece
    big = 1e4
    heads = list(as_multi(a.intersection(box(c + 0.02, -big, big, big))).geoms) + list(as_multi(b.intersection(box(-big, -big, c - 0.02, big))).geoms)
    areas = sorted(h.area for h in heads)
    assert len(areas) >= 3, areas
    assert areas[0] > 0.95 * areas[-1], areas                         # all the same size: no partial tab


def test_split_tabs_interlock_on_a_plain_bar():
    """Tabs alternate sides and each socket is the exact negative of a tab, so the pieces tile the original."""
    profile = as_multi(box(0, 0, 300, 120))
    sl = types.SimpleNamespace(label="B-1", profile=profile, lines=[], marks=[], warnings=[], pieces=None, facets=None)
    split_slice(sl, (200, 200), 5, 8)
    a, b = (pc.geom for pc in sl.pieces)
    big = 1e4
    ha = as_multi(a.intersection(box(150.02, -big, big, big))); hb = as_multi(b.intersection(box(-big, -big, 149.98, big)))
    assert len(ha.geoms) >= 2 and len(hb.geoms) >= 2                  # tabs on both sides
    assert a.intersection(b).area < 1e-6 and abs(a.area + b.area - profile.area) < 1e-6
