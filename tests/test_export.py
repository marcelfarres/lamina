"""core.export (SVG/DXF) and core.solid (STL/3MF) against a real plan. Expected entity counts are
derived from the plan's own data (never hardcoded), then checked against the parsed export output —
lxml for SVG, ezdxf for DXF — so nothing here trusts export.py's own claims about what it wrote.
"""
import io
import json
import pathlib
import re
import zipfile

import ezdxf
import numpy as np
import trimesh
from lxml import etree
from shapely.geometry import Polygon

from core.export import design_name, export
from core.plan import build
from core.solid import assembled, proto_set

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def sheet0_expected_counts(plan):
    """OUTER/INNER path counts and SCORE/LABEL entity counts for sheet 0, computed straight from the
    plan's own placed/lines/marks/label_pos data (see core.geometry.poly_coords for the placed shape:
    one entry per region, each region [exterior, hole, hole...])."""
    pieces = [pc for sl in plan["slices"] for pc in sl["pieces"] if pc["place"][0] == 0]
    outer = sum(len(pc["placed"]) for pc in pieces)  # one OUTER path per region (region[0])
    inner = sum(len(region) - 1 for pc in pieces for region in pc["placed"])  # holes: region[1:]
    score = sum(len(pc["lines"]) for pc in pieces)
    marks = sum(len(pc["marks"]) for pc in pieces)
    label_pos = sum(1 for pc in pieces if pc.get("label_pos"))
    if plan.get("scale_check", {}).get("sheet") == 0:   # the calibration bar export() adds to the first sheet with room
        outer += 1; label_pos += 1
    return dict(outer=outer, inner=inner, score=score, marks=marks, label_pos=label_pos)


def test_svg_layers_and_entity_counts_stacked(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    exp = sheet0_expected_counts(plan)

    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))
    assert len(tree.xpath('//svg:g[@class="OUTER"]/svg:path', namespaces=SVG_NS)) == exp["outer"]
    assert len(tree.xpath('//svg:g[@class="INNER"]/svg:path', namespaces=SVG_NS)) == exp["inner"]
    # stacked cube has no fold lines, so SCORE is legitimately absent
    assert exp["score"] == 0
    assert not tree.xpath('//svg:g[@class="SCORE"]', namespaces=SVG_NS)


def test_next_layer_outline_goes_on_the_guide_layer_and_identical_slices_stay_one_part(tmp_path):
    """Stacked with `next_outline`: every slice but the top one carries the outline of the layer above it as a guide
    line, exported on a GUIDE layer of its own (engraved), one path per line in the plan, and no SCORE layer. Slices
    that are the same part with the same guide are still cut once: the cube's lower three slabs each carry the square
    above them (one file, quantity 3); the top slab, with nothing above it, is a part of its own."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off", "next_outline": True})
    pieces = [pc for sl in plan["slices"] for pc in sl["pieces"]]
    styles = [s for pc in pieces for s, _ in pc["lines"]]
    assert styles and set(styles) == {"guide"}
    assert sum(1 for pc in pieces if not pc["lines"]) == 1          # the top slice has no layer above it

    export(plan, tmp_path, fmts=("svg",), labels=True)
    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))
    assert not tree.xpath('//svg:g[@class="SCORE"]', namespaces=SVG_NS)
    assert len(tree.xpath('//svg:g[@class="GUIDE"]/svg:path', namespaces=SVG_NS)) == sum(len(pc["lines"]) for pc in pieces if pc["place"][0] == 0)

    files = {f.name.split(" ", 1)[1]: f for f in export(plan, tmp_path / "pieces", fmts=("svg",), labels=True, per_piece=True)}
    assert "Z-1 x3.svg" in files and "Z-4 x1.svg" in files, files
    # the one-file-per-part export carries the guide too, in the part's own frame
    piece = etree.parse(str(files["Z-1 x3.svg"]))
    z1 = next(pc for pc in pieces if pc["label"] == "Z-1")
    assert len(piece.xpath('//svg:g[@class="GUIDE"]//svg:path', namespaces=SVG_NS)) == len(z1["kerfed_lines"]) == len(z1["lines"]) > 0
    assert not etree.parse(str(files["Z-4 x1.svg"])).xpath('//svg:g[@class="GUIDE"]', namespaces=SVG_NS)


def test_guide_is_the_layer_as_cut_with_its_inner_edge(tmp_path):
    """The guide is the layer above as it will be cut, not as it was sectioned: a slice grown to mend a thin bridge
    overhangs the one below, so nothing of it lands on that slice's material, while the grown slice's own guide (the
    layer above it) does. A hollow layer marks its inner edge as well as its outer one."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "next_outline": True, "grow": {"Z-2": 2.0}})
    by = {pc["label"]: pc for sl in plan["slices"] for pc in sl["pieces"]}
    assert not by["Z-1"]["lines"], by["Z-1"]["lines"]                # Z-2 is 2 mm wider all round: it overhangs Z-1
    (_, ring), = by["Z-2"]["lines"]                                    # Z-3's square, well inside the grown Z-2
    xs = [x for x, _ in ring]; z2 = [x for x, _ in by["Z-2"]["kerfed"][0][0]]; z3 = [x for x, _ in by["Z-3"]["kerfed"][0][0]]
    assert abs((max(xs) - min(xs)) - (max(z3) - min(z3))) < 0.5 and (max(z2) - min(z2)) - (max(xs) - min(xs)) > 3

    plan = build(EXAMPLES / "tube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "connect": "none", "next_outline": True})
    by = {pc["label"]: pc for sl in plan["slices"] for pc in sl["pieces"]}
    assert len(by["Z-1"]["kerfed"][0]) == 2                            # the tube's slice is a ring: one outer edge, one hole
    lengths = sorted(sum(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 for (x0, y0), (x1, y1) in zip(pts, pts[1:])) for _, pts in by["Z-1"]["lines"])
    assert len(lengths) == 2 and lengths[0] < lengths[1] * 0.9          # both edges engraved: the inner ring is the shorter line


def test_a_split_slice_keeps_its_guide_on_every_strip():
    """A slice cut into strips for the sheet keeps the next layer's guide: each strip carries the part of the line that
    lies on it, and together the strips carry the whole line — the cube's square, which runs along the strips' own
    edges, the case rounding would lose."""
    import math
    import shapely
    from shapely.geometry import LineString, Polygon
    prm = {"distribution": "count", "count": 3, "autofix": "off", "connect": "none", "next_outline": True}
    whole = build(EXAMPLES / "cube.stl", "stacked", prm)
    strips = build(EXAMPLES / "cube.stl", "stacked", {**prm, "sheet": [120, 300], "split": True})
    length = lambda pts: sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    for sl in whole["slices"][:-1]:                                   # every layer but the top one carries a guide
        cut = next(s for s in strips["slices"] if s["label"] == sl["label"])
        assert len(cut["pieces"]) >= 2 and all(pc["kerfed_lines"] for pc in cut["pieces"]), [(pc["label"], pc["kerfed_lines"]) for pc in cut["pieces"]]
        for pc in cut["pieces"]:
            part = shapely.union_all([Polygon(r[0], r[1:]) for r in pc["kerfed"]]).buffer(1e-3)
            assert all(part.covers(LineString(pts)) for _, pts in pc["kerfed_lines"]), pc["label"]   # on its own strip
        assert abs(sum(length(pts) for pc in cut["pieces"] for _, pts in pc["kerfed_lines"])
                   - sum(length(pts) for _, pts in sl["pieces"][0]["kerfed_lines"])) < 1              # and nothing lost


def test_a_lone_part_file_puts_the_label_under_the_next_layer_like_the_sheet(tmp_path):
    """A slab with a block on one end: the slab's widest spot is its middle, which the block does not cover, so the
    label goes under the block's outline — on the sheet and, the same way, in the one-file-per-part export."""
    import numpy as np
    import shapely
    from shapely.geometry import LineString, Point, Polygon
    step = trimesh.creation.extrude_polygon(Polygon([(-50, -10), (50, -10), (50, 10), (-10, 10), (-10, 30), (-50, 30)]), 40)
    step.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))   # the step rises along z
    step.export(tmp_path / "step.stl")
    plan = build(tmp_path / "step.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off", "connect": "none",
                                                   "next_outline": True, "label_place": "on"})
    z2 = next(pc for sl in plan["slices"] for pc in sl["pieces"] if pc["label"] == "Z-2")   # the slab under the block
    under = shapely.polygonize([LineString(pts) for _, pts in z2["lines"]])
    assert 1300 < under.area < 1900 and under.covers(Point(z2["label_pos"][:2]))             # on the sheet: under the block
    files = export(plan, tmp_path, fmts=("svg",), labels=True, per_piece=True)
    tree = etree.parse(str(next(f for f in files if " Z-2 " in f.name)))
    d = tree.xpath('//svg:g[@class="GUIDE"]/svg:path/@d', namespaces=SVG_NS)[0]
    ring = Polygon([tuple(map(float, xy.split(","))) for xy in re.findall(r"[ML]([-\d.]+,[-\d.]+)", d)])
    label = next(t for t in tree.xpath('//svg:g[@class="LABEL"]/svg:path', namespaces=SVG_NS) if "Z-2" in t.get("data-text"))
    pts = [tuple(map(float, xy.split(","))) for xy in re.findall(r"[ML]([-\d.]+,[-\d.]+)", label.get("d"))]   # its strokes
    xs, ys = zip(*pts)
    assert ring.covers(Point((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))               # in its file: the same spot


def test_a_sliver_shed_from_the_layer_above_is_not_in_the_guide(tmp_path):
    """A speck beside the block, thinner than min_feature and shorter than min_part: shed from the layer's cut, so
    the layer below gets the block's ring as its guide and nothing for the speck."""
    import numpy as np
    import shapely
    from shapely.geometry import LineString, Polygon
    step = trimesh.creation.extrude_polygon(Polygon([(-50, -10), (50, -10), (50, 10), (-10, 10), (-10, 30), (-50, 30)]), 40)
    speck = trimesh.creation.extrude_polygon(Polygon([(20, 10), (21.5, 10), (21.5, 30), (20, 30)]), 8)
    step.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    speck.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    trimesh.util.concatenate([step, speck]).export(tmp_path / "step.stl")
    plan = build(tmp_path / "step.stl", "stacked", {"distribution": "count", "count": 4, "autofix": "off", "connect": "none",
                                                   "next_outline": True, "min_feature": 2, "min_part": 10})
    by = {sl["label"]: sl for sl in plan["slices"]}
    assert len(by["Z-3"]["pieces"]) == 1                                   # the speck is not a part of Z-3
    rings = shapely.polygonize([LineString(pts) for pc in by["Z-2"]["pieces"] for _, pts in pc["lines"]])
    assert len(rings.geoms) == 1 and 1300 < rings.area < 1900, rings.area   # and not engraved on Z-2 either


def test_a_lone_part_file_carries_its_seam_numbers(tmp_path):
    """Folded panels with `edge_labels`: the one-file-per-part export engraves each panel's seam numbers, as many as
    the sheet shows for it, and a strip's number keeps it a file of its own (test_cutlist checks the identity)."""
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    pieces = {pc["label"]: pc for sl in plan["slices"] for pc in sl["pieces"]}
    assert any(pc["marks"] for pc in pieces.values())
    for f in export(plan, tmp_path, fmts=("svg",), labels=True, per_piece=True):
        lab = f.name.split(" ")[1]
        if lab in pieces:
            texts = etree.parse(str(f)).xpath('//svg:g[@class="LABEL"]/svg:path/@data-text', namespaces=SVG_NS)
            small = [t for t in texts if lab not in t]                     # every text but the part's own label is a seam number
            assert len(small) == len(pieces[lab]["marks"]) == len(pieces[lab]["kerfed_marks"]), lab


def test_a_plain_per_piece_export_engraves_no_label(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    files = export(plan, tmp_path, fmts=("svg",), labels=False, per_piece=True)
    assert len(files) > 2
    for f in files:
        if f.suffix == ".svg":
            assert not etree.parse(str(f)).xpath('//svg:path[@data-text]', namespaces=SVG_NS), f.name


def test_a_name_in_another_script_still_exports_and_downloads(tmp_path):
    """A model or project named with an umlaut or in Chinese: the EPS, a Latin-1 file, is still written, and the file
    names stay ASCII, since the zip's name travels in an HTTP header that carries nothing else."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    plan["label_tag"] = "Büste 龙"; plan["params"]["project"] = "Büste 龙"
    files = export(plan, tmp_path, fmts=("eps", "svg"), labels=True, per_piece=True)
    assert design_name(plan).isascii() and design_name(plan).encode("latin-1")
    assert sum(f.suffix == ".eps" for f in files) == sum(f.suffix == ".svg" for f in files) > 0


def test_svg_score_and_label_counts_folded(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    exp = sheet0_expected_counts(plan)
    assert exp["score"] > 0  # folded panels have fold lines — this plan should actually exercise SCORE

    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))
    assert len(tree.xpath('//svg:g[@class="SCORE"]/svg:path', namespaces=SVG_NS)) == exp["score"]
    # LABEL texts (one stroke path each) = per-piece marks + per-piece label + the sheet title
    assert len(tree.xpath('//svg:g[@class="LABEL"]/svg:path[@data-text]', namespaces=SVG_NS)) == exp["marks"] + exp["label_pos"] + 1


def test_dxf_reloads_with_same_layers_and_matching_entity_counts(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    export(plan, tmp_path, fmts=("dxf",), labels=True)
    exp = sheet0_expected_counts(plan)

    doc = ezdxf.readfile(str(tmp_path / f"{design_name(plan)} sheet1.dxf"))
    assert sorted(l.dxf.name for l in doc.layers if l.dxf.name in ("OUTER", "INNER", "SCORE", "LABEL")) == [
        "INNER", "LABEL", "OUTER", "SCORE",
    ]
    msp = doc.modelspace()
    cut = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer != "LABEL"]
    assert len(cut) == exp["outer"] + exp["inner"] + exp["score"]
    # the labels are strokes on the LABEL layer — at least one per mark and per label, open, beside the closed border
    # rectangle export() draws when border=True (the default) — and never TEXT, which would take the reader's font
    label = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "LABEL"]
    assert sum(1 for e in label if e.closed) == 1 and sum(1 for e in label if not e.closed) >= exp["marks"] + exp["label_pos"]
    assert not list(msp.query("TEXT"))


def test_a_project_name_is_text_in_the_svg_not_markup(tmp_path):
    """The sheet title comes from the project file, and the UI puts the SVG straight into the page: a name that is
    markup must arrive as text (a crafted project attached to a bug report would otherwise run in the reader's app)."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "project": '</text><img src=x onerror="alert(1)">'})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))                          # still well-formed…
    assert not tree.xpath("//*[local-name()='img']")                          # …and the tag is not an element
    assert '<img' in "".join(tree.xpath('//svg:g[@class="LABEL"]/svg:path/@data-text', namespaces=SVG_NS))   # but text


def test_assembly_key_explains_the_labels_and_lists_every_part(tmp_path):
    """The map that comes out of the cut: what a label means (the mode's own legend) and every part with where it
    sits. It is written only when asked for, so the fit-test folders stay clean."""
    plan = build(EXAMPLES / "cylinder.stl", "radial", {"count": 5, "ring_count": 3, "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True, key=True)
    key = (tmp_path / f"{design_name(plan)} assembly-key.txt").read_text(encoding="utf-8")
    assert plan["legend"].split(" · ")[0] in key
    assert all(pc["label"] in key for sl in plan["slices"] for pc in sl["pieces"])

    export(plan, tmp_path / "plain", fmts=("svg",), labels=True)
    assert not (tmp_path / "plain" / f"{design_name(plan)} assembly-key.txt").exists()


def test_puzzle_mode_engraves_codes_and_the_key_is_the_way_back(tmp_path):
    """label_style=code engraves a code that gives nothing away — in the drawing and in the file name — while the
    plan, the sheet's data-label (what the UI matches a selection on) and the key keep the real labels."""
    params = {"distribution": "count", "count": 4, "label_style": "code", "autofix": "off"}
    plan = build(EXAMPLES / "egg.stl", "stacked", params)
    codes = plan["codes"]
    assert set(codes) == {pc["label"] for sl in plan["slices"] for pc in sl["pieces"]}

    export(plan, tmp_path, fmts=("svg",), labels=True, key=True)
    sheets = "".join(f.read_text(encoding="utf-8") for f in sorted(tmp_path.glob("* sheet*.svg")))
    for label, code in codes.items():
        assert f'data-text="EGG {code}"' in sheets        # engraved: the model's name and the code
        assert f' {label}"' not in sheets                 # never where the part goes
        assert f'data-label="{label}"' in sheets          # the sheet ↔ 3D selection is unchanged
    key = (tmp_path / f"{design_name(plan)} assembly-key.txt").read_text(encoding="utf-8")
    assert all(code in key and label in key for label, code in codes.items())
    assert build(EXAMPLES / "egg.stl", "stacked", params)["codes"] == codes   # same job, same codes as yesterday


def test_per_piece_files_in_puzzle_mode_are_named_after_the_code(tmp_path):
    """A folder of Z-1, Z-2, Z-3 would give the order away before a single piece is cut."""
    plan = build(EXAMPLES / "egg.stl", "stacked",
                 {"distribution": "count", "count": 4, "label_style": "code", "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True, per_piece=True)
    stems = {f.stem.split(" ")[1] for f in tmp_path.glob("*.svg")} - {"scale-check"}
    assert stems and stems <= set(plan["codes"].values())


def test_pdf_has_one_page_per_sheet(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    export(plan, tmp_path, fmts=("pdf",), labels=True)
    data = (tmp_path / f"{design_name(plan)} sheets.pdf").read_bytes()
    assert data.startswith(b"%PDF") and plan["sheets"] >= 1
    assert len(re.findall(rb"/Type\s*/Page\b", data)) == plan["sheets"]          # \b keeps the /Pages tree object out


def test_the_command_lines_run_the_same_pipeline(tmp_path, capsys):
    """README's headless recipe: plan → export → solids, each a module with a main()."""
    from core.plan import main as plan_main
    from core.export import main as export_main
    from core.solid import main as solid_main
    plan_main([str(EXAMPLES / "egg.stl"), "--mode", "interlocked", "--set", "nx=3", "ny=3", "thickness=3", "--out", str(tmp_path / "egg")])
    assert capsys.readouterr().out.startswith("interlocked: 6 slices")
    export_main([str(tmp_path / "egg.json"), "--out", str(tmp_path / "cut"), "--fmt", "svg", "eps", "--per-piece", "--labels"])
    assert list((tmp_path / "cut").glob("egg_v1.0 cut-list.txt")) and list((tmp_path / "cut").glob("*.eps"))
    solid_main([str(tmp_path / "egg.json"), "--proto", str(tmp_path / "proto"), "--scale", "0.2"])
    assert "re-planned" in capsys.readouterr().out and (tmp_path / "proto" / "plate.3mf").exists()
    plan_main([str(EXAMPLES / "egg.stl"), "--mode", "folded", "--list-params"])
    assert "joint" in capsys.readouterr().out


def test_solid_assembled_is_watertight_trimesh_with_positive_volume():
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    mesh = assembled(plan)
    assert isinstance(mesh, trimesh.Trimesh)
    assert mesh.volume > 0
    assert mesh.is_watertight


def test_proto_label_is_readable_and_clear_of_the_slot():
    """A printed label is a groove: it has to be read, so it is never shrunk below the asked height, and it goes where
    the part is widest, not beside the slot it slides on. A part with no room for it gets none on the part, not a
    tiny one (it carries its number on a tag beside it instead)."""
    from shapely.geometry import box
    from core.solid import label_on
    slot = box(40, 10, 44, 20)
    part = box(0, 0, 60, 20).difference(slot)                          # a 60 × 20 bar with a slot from the top edge
    lab = label_on(part, "Z-12-3", 5.0)
    assert lab is not None
    assert lab.bounds[3] - lab.bounds[1] >= 5.0 - 1e-6                  # capitals at least 5 mm tall
    assert part.buffer(-1.0 + 1e-6).contains(lab)                        # inside, a millimetre off every edge
    assert lab.distance(slot) >= 1.0 - 1e-6                              # the slot included
    assert label_on(box(0, 0, 60, 6), "Z-12-3", 5.0) is None             # a 6 mm bar cannot hold 5 mm letters


def _number(m):
    """Where an exported part's number is, measured on its mesh: ("part", letter height) for a groove in its top face,
    ("tag", letter height) for letters standing on a chip one layer high, (None, 0) for no number. A letter height is
    the short side of the smallest rectangle round the letters."""
    from shapely.geometry import MultiPoint
    from core.solid import CHIP_H, LETTER_H
    up, z, top = m.face_normals[:, 2] > 0.99, m.triangles_center[:, 2], m.bounds[1][2]
    for kind, at in (("part", top - min(top / 2, 0.6)), ("tag", CHIP_H + LETTER_H)):
        faces = m.triangles[up & (abs(z - at) < 0.01)]
        if kind == "tag" and not (up & (abs(z - CHIP_H) < 0.01)).any():
            continue                                                     # letters with no chip under them are not a tag
        if len(faces):
            r = MultiPoint(faces.reshape(-1, 3)[:, :2]).minimum_rotated_rectangle.exterior.coords
            return kind, min(np.hypot(*np.subtract(r[1], r[0])), np.hypot(*np.subtract(r[2], r[1])))
    return None, 0.0


def test_every_part_of_a_printed_plate_has_a_number_on_it_or_on_a_tag(tmp_path):
    """Bug 061: a printed part too small for its number had none, and nobody could tell where it went. Every part of
    every plate now carries its number: a groove on the part where it fits, else raised letters on a chip one layer
    high beside it, joined to the part by a thin line (one solid with it), on free room of the bed the nester kept
    for it: the tag touches no other part. The small end layers and the top layer, which is left clean on purpose,
    carry theirs on a tag."""
    from shapely.ops import unary_union
    from shapely.geometry import Polygon
    from core.solid import LINE_W
    bed = [150, 150]
    plan = build(EXAMPLES / "egg.stl", "stacked", {"printed": True, "sheet": bed, "sheet_margin": 2, "size": [0, 0, 60], "thickness": 3,
                                                   "autofix": "off", "font": 4})
    files = proto_set(plan, tmp_path, font=4)
    where, feet = {}, {}
    for f in (f for f in files if f.name.startswith("plate-")):
        scene = trimesh.load(f)
        for name in scene.graph.nodes_geometry:
            M, g = scene.graph[name]; m = scene.geometry[g].copy(); m.apply_transform(M)
            kind, h = _number(m)
            assert kind and h >= 4 - 0.05, (name, kind, h)                # a number, its letters 4 mm tall at least
            assert m.body_count == 1, name                                # the tag holds on to its part
            lo, hi = m.bounds
            assert lo[:2].min() >= 2 - 1e-6 and (hi[:2] <= np.array(bed) - 2 + 1e-6).all(), (name, lo, hi)   # on the bed, in its margin
            down = m.triangles[(m.face_normals[:, 2] < -0.99) & (m.triangles_center[:, 2] < 1e-3)]
            feet[f.name, name] = unary_union([Polygon(t[:, :2]) for t in down]).buffer(0)
            where[name] = kind
    assert set(where) == {pc["label"] for sl in plan["slices"] for pc in sl["pieces"]}   # every part, once
    tagged = sorted(n for n, k in where.items() if k == "tag")
    assert plan["slices"][-1]["pieces"][0]["label"] in tagged and len(tagged) >= 2, tagged   # the clean top, and the smallest
    for (fa, a), ga in feet.items():
        for (fb, b), gb in feet.items():
            if fa == fb and a < b:
                assert ga.distance(gb) > LINE_W, (a, b)                    # no tag or line runs into another part
    readme = (tmp_path / "README.txt").read_text(encoding="utf-8")
    assert all(n in readme for n in tagged) and "snap the tag off" in readme and "no free room" not in readme


def test_every_seam_number_of_a_printed_panel_is_on_the_print_and_readable(tmp_path):
    """Bug 064: a printed folded panel's seam numbers were not on the print at all (marks at 0.6 of the font, too thin
    for a nozzle; on a glue tab, which prints as the hinge skin only). Now each is cut into the panel 5 mm tall, its
    strokes two nozzle lines wide, clear of the tabs; a seam side with no room for that carries it on a tag beside the
    panel (a chip one layer high, the number standing on it). Measured on the exported mesh: every number the plan
    gives is there at full height, and every seam has its number on both sides. A laser job's numbers do not change."""
    from shapely import affinity, box, unary_union
    from core.labels import PRINT_MARK
    from core.solid import CHIP_H, LETTER_H
    pre = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["fold_test"]["params"]
    plan = build(EXAMPLES / "fold_test.stl", "folded", {**pre, "joint": "tab"})
    pc = plan["slices"][0]["pieces"][0]
    proto_set(plan, tmp_path)
    scene = trimesh.load(tmp_path / "plate-1.3mf")
    M, g = scene.graph[pc["label"]]; m = scene.geometry[g].copy(); m.apply_transform(M)
    up, z, top = m.face_normals[:, 2] > 0.99, m.triangles_center[:, 2], m.bounds[1][2]
    faces = lambda at: unary_union([Polygon(t[:, :2]) for t in m.triangles[up & (abs(z - at) < 0.01)]])   # noqa: E731
    grooves, chips, letters = faces(top - min(top / 2, 0.6)), faces(CHIP_H).buffer(0.6), faces(CHIP_H + LETTER_H)
    assert pc["marks"] and pc["seam_tags"], "the job shows both: numbers on the panel and on tags"
    for x, y, text, rot, size in pc["marks"]:                           # on the panel: cut, full height, off the tabs
        turn = rot + pc["place"][3]
        cut = affinity.rotate(grooves.intersection(affinity.rotate(box(x - 8, y - 4, x + 8, y + 4), turn, origin=(x, y))), -turn, origin=(x, y))
        assert 0.6 * size == PRINT_MARK and cut.bounds[3] - cut.bounds[1] >= PRINT_MARK - 0.05, (text, cut.bounds)
    on_tags = [letters.intersection(n) for n in getattr(letters.buffer(1.2), "geoms", [letters.buffer(1.2)])]
    on_tags = [n for n in on_tags if chips.contains(n.centroid)]
    assert len(on_tags) == len(pc["seam_tags"])                          # one tag for each number with no room on the panel
    for n in on_tags:                                                    # each standing 5 mm tall (one way or the other: 7 or 12)
        x0, y0, x1, y1 = n.bounds
        assert any(abs(e - PRINT_MARK) < 0.05 for e in (x1 - x0, y1 - y0)), n.bounds
    sides = [str(mk[2]) for mk in pc["marks"]] + [str(j) for *_, j in pc["seam_tags"]]
    assert all(sides.count(s) == 2 for s in sides), sorted(sides, key=lambda s: int(s.rstrip(".")))   # both sides of every seam
    laser = build(EXAMPLES / "fold_test.stl", "folded", {**pre, "joint": "tab", "printed": False, "material": "cardboard", "material_kind": "cardboard"})
    lpc = laser["slices"][0]["pieces"][0]
    assert "seam_tags" not in lpc and all(len(mk) < 5 or mk[4] < laser["params"]["font"] for mk in lpc["marks"])


def test_a_seam_number_that_reads_as_another_upside_down_has_a_dot(tmp_path):
    """A seam number 6 turned along its edge reads as 9 (Marcel, 2026-11-22: "Add a dot after 6 and 9", as Pepakura
    does). Every number that turned reads as another gets a dot after it, on the laser sheet and on the print; the
    rest stay plain. Measured on the exported sheet: the dot is one more stroke in the number's engraving."""
    from core.font import strokes
    from core.labels import seam_text
    assert [seam_text(j) for j in (6, 9, 16, 91, 68, 18, 106)] == ["6.", "9.", "16.", "91.", "68.", "18.", "106."]
    assert [seam_text(j) for j in (8, 69, 96, 88, 10, 60, 25, 7)] == ["8", "69", "96", "88", "10", "60", "25", "7"]
    pre = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["fold_test"]["params"]
    laser = {"printed": False, "material": "cardboard", "material_kind": "cardboard"}
    for plan in (build(EXAMPLES / "fold_test.stl", "folded", {**pre, "joint": "tab"}),                 # printed (the preset)
                 build(EXAMPLES / "fold_test.stl", "folded", {**pre, "joint": "tab", **laser})):
        texts = [str(mk[2]) for sl in plan["slices"] for pc in sl["pieces"] for mk in pc["marks"]]
        texts += [str(j) for sl in plan["slices"] for pc in sl["pieces"] for *_, j in pc.get("seam_tags", [])]
        assert {"6.", "9."} <= set(texts) and all(t == seam_text(int(t.rstrip("."))) for t in texts), sorted(texts)
    export(plan, tmp_path, fmts=("svg",))                                # the laser job's sheet
    sheets = list(tmp_path.glob(f"{design_name(plan)} sheet*.svg"))
    paths = [p for s in sheets for p in etree.parse(str(s)).xpath('//svg:path[@data-text="6." or @data-text="9."]', namespaces=SVG_NS)]
    assert paths
    for p in paths:
        assert p.get("d").count("M") == len(strokes(p.get("data-text")[0], 3.0)) + 1, p.get("data-text")


def test_a_printed_job_comes_out_as_one_plate_per_bed(tmp_path):
    """A printed job (PLA, PETG) was nested on the printer's bed, so each sheet is a plate: plate-1.3mf … plate-N.3mf,
    each holding that sheet's parts and fitting the bed — not one plate.3mf with every sheet stacked into a strip no
    printer takes. The cut files' titles say plate, not sheet."""
    bed = [256, 256]
    plan = build(EXAMPLES / "egg.stl", "stacked", {"printed": True, "sheet": bed, "thickness": 3, "autofix": "off"})
    assert plan["sheets"] > 1
    names = {f.name for f in proto_set(plan, tmp_path, scale=1.0)}
    assert "plate.3mf" not in names and {f"plate-{i + 1}.3mf" for i in range(plan["sheets"])} <= names
    on = {i: {pc["label"] for sl in plan["slices"] for pc in sl["pieces"] if pc["place"][0] == i} for i in range(plan["sheets"])}
    for i in range(plan["sheets"]):
        scene = trimesh.load(tmp_path / f"plate-{i + 1}.3mf")
        assert set(scene.geometry) == on[i]                                     # that plate's parts, all of them
        lo, hi = scene.bounds
        assert (hi - lo)[:2].max() <= max(bed) + 1e-6 and lo[:2].min() >= -1e-6, (i, lo, hi)
    export(plan, tmp_path / "cut", fmts=("svg",))
    assert "plate 1/" in next((tmp_path / "cut").glob("* sheet1.svg")).read_text(encoding="utf-8")   # by name: Linux lists a folder unsorted


def test_fit_test_is_the_jobs_joints_at_five_offsets_on_a_small_stand_in(tmp_path):
    """Before printing the model, five small assemblies with its joints: the job's own slot offset in the middle and
    two steps either way, every radial half-slice kept (that is what makes the real one tight), rings cut to two,
    each part engraved with its offset, all on one plate and one STL per offset."""
    from core.solid import fit_plan, fit_set, fit_sheets
    plan = build(EXAMPLES / "egg.stl", "radial", {"count": 5, "ring_count": 3, "slot_offset": 0.1, "autofix": "off"})
    v = fit_plan(plan, 0.3)
    assert abs(v["params"]["slot_offset"] - 0.3) < 1e-9 and v["params"]["count"] == 5 and v["params"]["ring_count"] == 2
    assert max(v["bbox"]) < 100 and v["counts"]["parts"] == 12                   # 2 rings + 10 half-slices, small
    # the print test: offsets in printed mm around the print slot offset, whatever the scale
    files = {f.name for f in fit_set(plan, tmp_path / "print", scale=0.5, offset=0.2, step=0.1)}
    assert {"fit_0.00.stl", "fit_0.10.stl", "fit_0.20.stl", "fit_0.30.stl", "fit_0.40.stl", "plate.3mf", "README.txt"} <= files
    scene = trimesh.load(tmp_path / "print" / "plate.3mf")
    per_tag = {}
    for name in scene.geometry:
        per_tag[name.split(" ")[0]] = per_tag.get(name.split(" ")[0], 0) + 1
    assert per_tag == {t: 12 for t in ("0.00", "0.10", "0.20", "0.30", "0.40")}
    assert "0.20, in the middle" in (tmp_path / "print" / "README.txt").read_text(encoding="utf-8")
    # the cut-file test: offsets around the job's own, at 1:1 on the job's sheet, a folder each
    cut = fit_sheets(plan, tmp_path / "cut", ("svg",), step=0.1)
    folders = {f.parent.name for f in cut if f.suffix == ".svg"}
    assert folders == {"fit_-0.10", "fit_0.00", "fit_0.10", "fit_0.20", "fit_0.30"}
    svg = next(f for f in cut if f.parent.name == "fit_0.30" and f.suffix == ".svg").read_text(encoding="utf-8")
    assert svg.count('data-text="0.30"') == 12 and "0.10, in the middle" in (tmp_path / "cut" / "README.txt").read_text(encoding="utf-8")


def test_the_print_gets_its_own_slot_offset_in_printed_mm(tmp_path):
    """A fit is a clearance in millimetres, not a ratio: the job's slot offset is for the real material at 1:1, and
    a print at ×0.5 with 0.2 mm printed clearance is planned at 0.4 mm slot offset, the README saying so."""
    from core.solid import proto_plan
    plan = build(EXAMPLES / "cube.stl", "interlocked", {"nx": 2, "ny": 2, "slot_offset": 0.05, "autofix": "off"})
    p, note = proto_plan(plan, 0.5, 0.5, offset=0.2)
    assert abs(p["params"]["slot_offset"] - 0.4) < 1e-9 and "0.2 mm wider" in note and "0.05 mm is for the real material" in note
    assert proto_plan(plan, 0.5, 0.5, offset=0.025)[1] is None                 # what the job already gives: nothing to redo


def test_proto_set_3mf_reloads_with_one_named_geometry_per_part(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    proto_set(plan, tmp_path)

    scene = trimesh.load(tmp_path / "plate.3mf")
    assert isinstance(scene, trimesh.Scene)
    assert len(scene.geometry) == plan["counts"]["parts"]
    expected_labels = {pc["label"] for sl in plan["slices"] for pc in sl["pieces"]}
    assert set(scene.geometry.keys()) == expected_labels


def _print_settings(f):
    """The settings per object a written 3MF carries, {object name: {key: value}}, read as OrcaSlicer reads them:
    Metadata/model_settings.config, each <object id> one of the model's objects, named as that object is."""
    z = zipfile.ZipFile(f)
    assert z.namelist().count("Metadata/model_settings.config") == 1
    model = etree.fromstring(z.read("3D/3dmodel.model"))
    names = {o.get("id"): o.get("name") for o in model.iter("{*}object")}
    out = {}
    for o in etree.fromstring(z.read("Metadata/model_settings.config")).iter("object"):
        meta = {m.get("key"): m.get("value") for m in o.iter("metadata")}
        assert meta.pop("name") == names[o.get("id")]
        out[names[o.get("id")]] = meta
    return out


def test_a_print_plate_carries_the_settings_each_part_needs(tmp_path):
    """Marcel (2026-11-22): a print that needs a layer height, or bridges, to succeed has to say so in the file. Each
    object of the 3MF carries the settings its mesh needs, where OrcaSlicer reads them: the click joint's bar is a
    bridge between two posts, so its panel gets thick bridges and no support under it; every part gets a layer height
    that makes its flat tops (a 2 mm panel, a 0.4 mm hinge skin, a 0.2 mm chip) whole layers over a 0.2 mm first one.
    The snap joint's 0.7 mm ledge is a short overhang that prints: no bridge settings. The README says it all."""
    from core.solid import FIRST, THIN
    pre = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["fold_box"]["params"]
    for joint, bridged in (("click", True), ("snap", False)):
        plan = build(EXAMPLES / "fold_box.stl", "folded", {**pre, "material_kind": "PETG", "autofix": "off", "joint": joint})
        out = tmp_path / joint
        proto_set(plan, out)
        for f in sorted(out.glob("plate-*.3mf")):
            got, scene = _print_settings(f), trimesh.load(f)
            assert set(got) == set(scene.geometry)                         # every object, by its name
            for name, s in got.items():
                assert s["layer_height"] == "0.2", (f.name, name, s)
                m = scene.geometry[name]
                up = (m.face_normals[:, 2] > 0.99) & (m.triangles_center[:, 2] > 0.01)
                z, area = m.triangles_center[up, 2].round(2), m.area_faces[up]
                tops = np.append(z[z <= THIN], z[area.argmax()])           # the thin tops and the main face (the walls' own steps are free)
                assert np.allclose((tops - FIRST) / 0.2, np.round((tops - FIRST) / 0.2), atol=0.03), (name, tops)
                panel = name.startswith("P")
                assert ("thick_bridges" in s) == (bridged and panel), (joint, name, s)
                if "thick_bridges" in s:
                    assert s["thick_bridges"] == "1" and s["enable_support"] == "0"
        readme = (out / "README.txt").read_text(encoding="utf-8")
        assert "Layer height 0.2 mm" in readme and "first layer height to 0.2 mm" in readme
        assert ("Thick bridges on and supports off" in readme) == bridged


def test_every_print_3mf_carries_its_settings(tmp_path):
    """The fit test's plate and the standoffs' file are written the same way as the part plates: each 3MF carries its
    objects' settings and still opens as the same named objects; the standoffs' note says what was set."""
    from core.solid import fit_set, standoff_files
    plan = build(EXAMPLES / "cube.stl", "stacked", {"thickness": 3, "autofix": "off"})
    fit_set(plan, tmp_path / "fit", scale=0.5)
    got = _print_settings(tmp_path / "fit" / "plate.3mf")
    assert set(got) == set(trimesh.load(tmp_path / "fit" / "plate.3mf").geometry) and all(s.get("layer_height") for s in got.values())
    job = {"space": 8, "connect": "standoff", "dowel_d": 5, "dowel_shape": "square", "thickness": 3, "autofix": "off"}
    f, note = standoff_files(build(EXAMPLES / "egg.stl", "stacked", job), tmp_path, "egg")
    got = _print_settings(f)
    assert set(got) == set(trimesh.load(f).geometry) and {s["layer_height"] for s in got.values()} == {"0.2"}
    assert not any("thick_bridges" in s for s in got.values())             # the halves only narrow as they rise
    assert "Layer height 0.2 mm for every part" in note.read_text(encoding="utf-8")


def test_a_part_no_layer_height_fits_is_said_not_set(tmp_path):
    """A layer height is written only where it makes the part whole layers: 3 mm parts at x0.5 print 1.5 mm, which
    0.1 mm layers over a 0.2 mm first one make; at x0.457 they print 1.37 mm, which none of the heights make. Those
    parts get no layer height, and the README names them instead of hiding it."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"thickness": 3, "autofix": "off"})
    proto_set(plan, tmp_path / "half", scale=0.5)
    assert {s["layer_height"] for s in _print_settings(tmp_path / "half" / "plate.3mf").values()} == {"0.1"}
    proto_set(plan, tmp_path / "odd", scale=0.457)
    got, labels = _print_settings(tmp_path / "odd" / "plate.3mf"), [pc["label"] for sl in plan["slices"] for pc in sl["pieces"]]
    bare = [n for n in labels if "layer_height" not in got.get(n, {})]
    assert bare
    readme = (tmp_path / "odd" / "README.txt").read_text(encoding="utf-8")
    assert "a whole number of layers" in readme and all(n in readme for n in bare)


def _step_rows(text):
    """A STEP file's DATA section as {reference: entity}, and the two readers the tests need: what kind of entity a
    reference names, and the references it holds in turn."""
    rows = dict(re.findall(r"^(#\d+)=(.*);$", text, re.M))
    return rows, lambda r: re.match(r"\(?([A-Z_0-9]+)", rows[r]).group(1), lambda r: re.findall(r"#\d+", rows[r])


def _odd_plan(M):
    """One part with a hole, its outline with a corner given three times (twice the same, once 0.1 nm away), a name
    with a letter outside ASCII and a quote, placed with the frame M."""
    square = [[0, 0], [40, 0], [40, 0], [40, 0.0000001], [40, 30], [0, 30], [0, 0]]
    hole = [[10, 10], [10, 20], [20, 20], [20, 10], [10, 10]]
    plan = {"slices": [{"thickness": 3, "pieces": [{"label": "Flügel 'A'", "facets": [{"M": np.asarray(M, float).tolist(), "rings": [[square, hole]]}]}]}]}
    return plan, [("", Polygon(square, [hole]), 3)]


def test_step_holds_one_closed_solid_per_flat_piece_of_a_part():
    """Asked for: the STL in Fusion is a million triangle lines that cannot be removed. The STEP holds each part as
    a solid with flat faces. Read from the file's own text, with no CAD kernel: a solid per polygon of the plan,
    named by its part; every edge walked once in each direction (the faces close, and agree on which side is out);
    Euler's count, V - E + F = 2 per solid (a through hole adds a handle and a loop on each flat face: they cancel);
    and the solids stand where the STL stands."""
    from core.geometry import facet_polys
    from core.step import step_text
    for mode, prm in (("interlocked", {"nx": 2, "ny": 2}), ("folded", {}), ("stacked", {"distribution": "count", "count": 3})):
        plan = build(EXAMPLES / "cube.stl", mode, {**prm, "autofix": "off"})
        polys = [(pc["label"], g, sl["thickness"]) for sl in plan["slices"] for pc in sl["pieces"] for g, _, _ in facet_polys(pc)]
        text = step_text(plan)
        assert text.startswith("ISO-10303-21;") and text.rstrip().endswith("END-ISO-10303-21;")
        assert sorted(re.findall(r"MANIFOLD_SOLID_BREP\('([^']*)'", text)) == sorted(label for label, _, _ in polys), mode
        walked = re.findall(r"ORIENTED_EDGE\('',\*,\*,(#\d+),\.([TF])\.\)", text)
        edges = re.findall(r"(#\d+)=EDGE_CURVE", text)
        assert sorted(walked) == sorted((e, d) for e in edges for d in "TF"), mode
        assert text.count("=VERTEX_POINT") - len(edges) + text.count("=ADVANCED_FACE") == 2 * len(polys), mode
        pts = np.array([[float(x) for x in m.split(",")] for m in re.findall(r"CARTESIAN_POINT\('',\(([^)]*)\)\)", text)])
        assert np.allclose([pts.min(0), pts.max(0)], assembled(plan).bounds, atol=1e-6), mode
        one = polys[0][0]
        assert set(re.findall(r"MANIFOLD_SOLID_BREP\('([^']*)'", step_text(plan, one))) == {one}


def test_step_hangs_its_solids_on_a_product_in_millimetres():
    """What a CAD program follows to find the solids, followed here with no CAD kernel: every reference names a row;
    the shape leads back to the product, named after the design; the solids stand in a frame, measured in mm."""
    from core.step import step_text
    plan = build(EXAMPLES / "cube.stl", "interlocked", {"nx": 2, "ny": 2, "autofix": "off"})
    rows, kind, refs = _step_rows(step_text(plan, name="cube v1"))
    assert all(x in rows for r in rows for x in refs(r))
    (shown,) = [r for r in rows if kind(r) == "SHAPE_DEFINITION_REPRESENTATION"]
    r, model = refs(shown)
    for want in ("PRODUCT_DEFINITION_SHAPE", "PRODUCT_DEFINITION", "PRODUCT_DEFINITION_FORMATION", "PRODUCT"):
        assert kind(r) == want
        last, r = r, refs(r)[0]
    assert rows[last].startswith("PRODUCT('cube v1','cube v1'")
    frame, *solids, context = refs(model)
    assert kind(model) == "ADVANCED_BREP_SHAPE_REPRESENTATION" and kind(frame) == "AXIS2_PLACEMENT_3D"
    assert {kind(b) for b in solids} == {"MANIFOLD_SOLID_BREP"} and len(solids) == plan["counts"]["parts"]
    assert rows[context].startswith("(GEOMETRIC_REPRESENTATION_CONTEXT(3)") and any(".MILLI.,.METRE." in rows[u] for u in refs(context))


def test_step_keeps_a_repeated_corner_a_mirroring_frame_and_a_hostile_name():
    """A point given twice keeps its corner (it once lost both, and the square came out a triangle), and one 0.1 nm
    from it makes no edge. A frame that mirrors gives the same count. A name keeps its letters outside ASCII in
    STEP's own escape, its quote doubled; a line break in the design's name cannot split a row."""
    from core.step import step_text
    for M in (np.eye(4), np.diag([-1.0, 1, 1, 1])):
        text = step_text(_odd_plan(M)[0], name="a\nb")
        assert text.count("=VERTEX_POINT") == 16 and text.count("=ADVANCED_FACE") == 10
        assert "PRODUCT('a b'" in text and "MANIFOLD_SOLID_BREP('Fl\\X2\\00FC\\X0\\gel ''A''" + "'," in text and text.isascii()
        rows, _, refs = _step_rows(text)
        assert all(x in rows for r in rows for x in refs(r))


def test_step_reads_back_as_valid_solids_in_a_cad_kernel(tmp_path):
    """OpenCascade (CadQuery, the optional CAD extra) reads the files: as many solids as polygons, each valid, their
    volume the outline's area times the thickness. A solid turned inside out would count negative."""
    import pytest
    from core.geometry import facet_polys
    from core.step import step_text
    cq = pytest.importorskip("cadquery", reason="the CAD kernel is an extra: uv sync --extra cad")
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    cases = [(plan, [("", g, sl["thickness"]) for sl in plan["slices"] for pc in sl["pieces"] for g, _, _ in facet_polys(pc)])]
    cases += [_odd_plan(M) for M in (np.eye(4), np.diag([-1.0, 1, 1, 1]))]
    for plan, polys in cases:
        (tmp_path / "it.step").write_text(step_text(plan), encoding="ascii")
        solids = cq.importers.importStep(str(tmp_path / "it.step")).solids().vals()
        assert len(solids) == len(polys) and all(b.isValid() for b in solids)
        want = sum(g.area * t for _, g, t in polys)
        assert abs(sum(b.Volume() for b in solids) - want) < 1e-6 * want


def test_step_one_body_fuses_the_whole_model_into_one_closed_solid(tmp_path):
    """Marcel, 2026-11-22: his STEP files had "over 100,000 parts", and he asked for "A choice on the STEP button":
    STEP: one body, every part, standoff and dowel fused into one solid. A stack whose layers stand apart is one solid
    through its dowels, a folded net one through its folds, slotted slices one through their slots. Read from the
    text: one solid named after the model (a folded box with the air inside it as a void), every edge walked once each way, its box the assembly's grown by the weld.
    In OpenCascade, when the CAD extra is there: one valid solid, with at least the parts' volume (nothing lost)."""
    import pytest
    from core.geometry import facet_polys
    from core.solid import WELD, one_body
    from core.step import step_text
    try:
        import cadquery as cq
    except ImportError:
        cq = None
    for mode, prm in (("stacked", {"distribution": "count", "count": 3}), ("folded", {}), ("interlocked", {"nx": 2, "ny": 2}), ("radial", {})):
        plan = build(EXAMPLES / "cube.stl", mode, {**prm, "autofix": "off"})
        text = step_text(plan, name="cube", lumps=one_body(plan))
        assert re.findall(r"(?:MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS)\('([^']*)'", text) == ["cube"], mode   # a closed box: with its hollow as a void
        walked = re.findall(r"ORIENTED_EDGE\('',\*,\*,(#\d+),\.([TF])\.\)", text)
        assert sorted(walked) == sorted((e, d) for e in re.findall(r"(#\d+)=EDGE_CURVE", text) for d in "TF"), mode
        pts = np.array([[float(x) for x in m.split(",")] for m in re.findall(r"CARTESIAN_POINT\('',\(([^)]*)\)\)", text)])
        lo, hi = assembled(plan).bounds                                   # grown by WELD, up to 5 WELD at a sharp mitred corner
        assert (pts.min(0) <= lo + 1e-6).all() and (pts.min(0) >= lo - 5 * WELD).all() and (pts.max(0) >= hi - 1e-6).all() and (pts.max(0) <= hi + 5 * WELD).all(), mode
        if cq:
            (tmp_path / "it.step").write_text(text, encoding="ascii")
            (solid,) = cq.importers.importStep(str(tmp_path / "it.step")).solids().vals()
            parts = sum(g.area * (own or sl["thickness"]) for sl in plan["slices"] for pc in sl["pieces"] for g, _, own in facet_polys(pc))
            assert solid.isValid() and solid.Volume() > parts, (mode, solid.Volume(), parts)
    if cq is None:
        pytest.skip("checked from the text only: the CAD kernel is an extra (uv sync --extra cad)")


def test_the_command_line_writes_step_and_refuses_what_it_cannot_write(tmp_path):
    """`--out x.step` writes solids named after the design, as the download does. A part that is not in the plan,
    or no output at all, is an error said in words: it was an empty file that looked fine, and a crash."""
    import pytest
    from core import solid
    plan = build(EXAMPLES / "cube.stl", "interlocked", {"nx": 2, "ny": 2, "autofix": "off"}, tmp_path / "plan")
    solid.main([str(tmp_path / "plan.json"), "--out", str(tmp_path / "cube.step")])
    assert f"PRODUCT('{design_name(plan)}'" in (tmp_path / "cube.step").read_text()
    for bad in (["--out", str(tmp_path / "no.step"), "--part", "X-99"], []):
        with pytest.raises(SystemExit):
            solid.main([str(tmp_path / "plan.json"), *bad])
    assert not (tmp_path / "no.step").exists()


def test_every_file_carries_the_design_name_so_two_designs_never_mix(tmp_path):
    """Asked for: two designs unzipped into one folder overwrote each other's sheet1.svg and cut-list.txt, and a
    part's file said nothing of whose part it was. Every file of a job starts with the design's name, the one its zip
    is named after: the project's when it has one, else the model's, and its revision."""
    cube = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    egg = build(EXAMPLES / "egg.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "project": "my egg", "rev": "2.1"})
    for per_piece in (False, True):
        out = tmp_path / str(per_piece)
        a = export(cube, out, fmts=("svg", "dxf", "pdf"), labels=True, per_piece=per_piece, key=True)
        b = export(egg, out, fmts=("svg", "dxf", "pdf"), labels=True, per_piece=per_piece, key=True)
        assert all(f.name.startswith("cube_v1.0 ") for f in a), [f.name for f in a]
        assert all(f.name.startswith("my_egg_v2.1 ") for f in b), [f.name for f in b]
        assert len({f.name for f in a} | {f.name for f in b}) == len(a) + len(b) == len(list(out.iterdir()))


def test_a_hostile_revision_in_a_project_file_writes_nothing_outside_the_job_folder(tmp_path):
    """033: the revision went into every file name as written, so a project file with rev "../../../evil" made export()
    write its sheet one folder above the job. The name and the revision get the same cleaning, and ".." alone falls
    back to 1.0."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "project": "a", "rev": "../../../evil"})
    job = tmp_path / "a" / "b" / "job"
    files = export(plan, job, fmts=("svg",), labels=True)
    assert files and all(f.resolve().parent == job.resolve() for f in files), [str(f) for f in files]
    assert design_name(plan) == "a_vevil"
    plan["params"]["rev"] = ".."
    assert design_name(plan) == "a_v1.0"


def test_each_part_is_one_svg_group_with_its_labels_and_marks(tmp_path):
    """Someone rearranging the sheet in a vector editor drags a part as one thing: its cuts, its dowel numbers, its
    label and leader, and its arrows are one <g class="piece">, so nothing goes out of register. The colour stays
    on each layer group, which is what laser software sorts the lines by."""
    from core.export import items_for_sheet
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "connect": "dowel",
                                                   "orient_mark": True, "label_place": "beside"})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))
    groups = tree.xpath('//svg:g[@class="piece"]', namespaces=SVG_NS)
    items = items_for_sheet(plan, 0)                               # the parts on the sheet and the scale-check bar with its note
    assert [g.get("data-label") for g in groups] == [it.key for it in items] and any(it.marks for it in items) and any(it.leader for it in items)
    for it, g in zip(items, groups):
        assert g.xpath('./svg:g[@class="OUTER"]/svg:path/@data-label', namespaces=SVG_NS) == [it.key]
        assert sorted(g.xpath('./svg:g[@class="LABEL"]/svg:path/@data-text', namespaces=SVG_NS)) == sorted([it.label] + [str(m[2]) for m in it.marks])
        assert len(g.xpath('./svg:g[@class="LABEL"]/svg:line', namespaces=SVG_NS)) == (1 if it.leader else 0)
        assert len(g.xpath('./svg:g[@class="LABEL"]/svg:path[not(@data-text)]', namespaces=SVG_NS)) == len(it.scores)   # the arrows
    assert tree.xpath('//svg:g[@class="sheet"]//svg:rect', namespaces=SVG_NS)                   # the border is the sheet's, not a part's
    assert {(g.get("stroke"), g.get("fill")) for g in tree.xpath('//svg:g[@class="OUTER"]', namespaces=SVG_NS)} == {("#0055ff", "none")}


def test_svg_can_fall_back_to_one_group_per_colour(tmp_path):
    """The switch on the Export tab for software that wants the colours kept apart: no <g class="piece">, one group
    per colour for the whole sheet, and the border, arrows and every label together in the single LABEL group."""
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True, grouped=False)
    exp = sheet0_expected_counts(plan)
    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))
    assert not tree.xpath('//svg:g[@class="piece"]', namespaces=SVG_NS)
    assert len(tree.xpath('//svg:g[@class="OUTER"]', namespaces=SVG_NS)) == 1
    assert len(tree.xpath('//svg:g[@class="OUTER"]/svg:path', namespaces=SVG_NS)) == exp["outer"]
    assert len(tree.xpath('//svg:g[@class="LABEL"]', namespaces=SVG_NS)) == 1
    assert len(tree.xpath('//svg:g[@class="LABEL"]/svg:path[@data-text]', namespaces=SVG_NS)) == exp["marks"] + exp["label_pos"] + 1


def test_job_export_can_switch_part_grouping_off():
    """The checkbox the Export tab adds: `grouped=0` on the endpoint produces the colour-first file, so software that
    keeps the colours apart and never moves a part on its own reads it as before."""
    from web.app import client_dir, job_export

    client, job = "group-export-test", "sheet-group"
    jd = client_dir(client) / job
    jd.mkdir(parents=True, exist_ok=True)
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    (jd / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    resp = job_export(client, job, fmt="svg", labels=1, key=0, grouped=0)
    with zipfile.ZipFile(io.BytesIO(resp.body)) as zf:
        svg = zf.read(next(name for name in zf.namelist() if name.endswith(".svg")))
    tree = etree.fromstring(svg)
    assert not tree.xpath('//svg:g[@class="piece"]', namespaces=SVG_NS)
    assert len(tree.xpath('//svg:g[@class="OUTER"]', namespaces=SVG_NS)) == 1
