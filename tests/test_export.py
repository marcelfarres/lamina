"""core.export (SVG/DXF) and core.solid (STL/3MF) against a real plan. Expected entity counts are
derived from the plan's own data (never hardcoded), then checked against the parsed export output —
lxml for SVG, ezdxf for DXF — so nothing here trusts export.py's own claims about what it wrote.
"""
import pathlib
import re

import ezdxf
import trimesh
from lxml import etree

from core.export import export
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

    tree = etree.parse(str(tmp_path / "sheet1.svg"))
    outer_g = tree.xpath('//svg:g[@id="OUTER"]', namespaces=SVG_NS)[0]
    inner_g = tree.xpath('//svg:g[@id="INNER"]', namespaces=SVG_NS)[0]
    assert len(outer_g.xpath('.//svg:path', namespaces=SVG_NS)) == exp["outer"]
    assert len(inner_g.xpath('.//svg:path', namespaces=SVG_NS)) == exp["inner"]
    # stacked cube has no fold lines, so SCORE is legitimately absent
    assert exp["score"] == 0
    assert not tree.xpath('//svg:g[@id="SCORE"]', namespaces=SVG_NS)


def test_svg_score_and_label_counts_folded(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    exp = sheet0_expected_counts(plan)
    assert exp["score"] > 0  # folded panels have fold lines — this plan should actually exercise SCORE

    tree = etree.parse(str(tmp_path / "sheet1.svg"))
    score_g = tree.xpath('//svg:g[@id="SCORE"]', namespaces=SVG_NS)[0]
    label_g = tree.xpath('//svg:g[@id="LABEL"]', namespaces=SVG_NS)[0]
    assert len(score_g.xpath('.//svg:path', namespaces=SVG_NS)) == exp["score"]
    # LABEL text = per-piece marks + per-piece label + the sheet title text
    assert len(label_g.xpath('.//svg:text', namespaces=SVG_NS)) == exp["marks"] + exp["label_pos"] + 1


def test_dxf_reloads_with_same_layers_and_matching_entity_counts(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    export(plan, tmp_path, fmts=("dxf",), labels=True)
    exp = sheet0_expected_counts(plan)

    doc = ezdxf.readfile(str(tmp_path / "sheet1.dxf"))
    assert sorted(l.dxf.name for l in doc.layers if l.dxf.name in ("OUTER", "INNER", "SCORE", "LABEL")) == [
        "INNER", "LABEL", "OUTER", "SCORE",
    ]
    msp = doc.modelspace()
    # +1 lwpolyline for the sheet border rectangle that export() draws when border=True (the default)
    assert len(list(msp.query("LWPOLYLINE"))) == exp["outer"] + exp["inner"] + exp["score"] + 1
    # DXF gets one TEXT per mark + one per label, no separate sheet-title text (SVG-only)
    assert len(list(msp.query("TEXT"))) == exp["marks"] + exp["label_pos"]


def test_a_project_name_is_text_in_the_svg_not_markup(tmp_path):
    """The sheet title comes from the project file, and the UI puts the SVG straight into the page: a name that is
    markup must arrive as text (a crafted project attached to a bug report would otherwise run in the reader's app)."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "project": '</text><img src=x onerror="alert(1)">'})
    export(plan, tmp_path, fmts=("svg",), labels=True)
    tree = etree.parse(str(tmp_path / "sheet1.svg"))                          # still well-formed…
    assert not tree.xpath("//*[local-name()='img']")                          # …and the tag is not an element
    assert '<img' in "".join(tree.xpath('//svg:g[@id="LABEL"]/svg:text/text()', namespaces=SVG_NS))   # but text


def test_pdf_has_one_page_per_sheet(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    export(plan, tmp_path, fmts=("pdf",), labels=True)
    data = (tmp_path / "sheets.pdf").read_bytes()
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
    assert (tmp_path / "cut" / "cut-list.txt").exists() and list((tmp_path / "cut").glob("*.eps"))
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
    the part is widest, not beside the slot it slides on. A part with no room for it gets none, not a tiny one."""
    from shapely.geometry import box
    from core.solid import label_inside
    slot = box(28, 10, 32, 20)
    part = box(0, 0, 60, 20).difference(slot)                          # a 60 × 20 bar with a slot from the top edge
    lab = label_inside(part, "Z-12-3", 5.0)
    assert lab is not None
    assert lab.bounds[3] - lab.bounds[1] >= 5.0 - 1e-6                  # capitals at least 5 mm tall
    assert part.buffer(-1.0 + 1e-6).contains(lab)                        # inside, a millimetre off every edge
    assert lab.distance(slot) >= 1.0 - 1e-6                              # the slot included
    assert label_inside(box(0, 0, 60, 6), "Z-12-3", 5.0) is None         # a 6 mm bar cannot hold 5 mm letters


def test_proto_set_says_which_parts_had_no_room_for_a_label(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    files = proto_set(plan, tmp_path, font=150)                          # "Z-1" in 150 mm letters fits no 180 mm square
    readme = (tmp_path / "README.txt").read_text(encoding="utf-8")
    assert tmp_path / "README.txt" in files
    assert all(pc["label"] in readme for sl in plan["slices"] for pc in sl["pieces"])


def test_fit_test_is_the_jobs_joints_at_five_offsets_on_a_small_stand_in(tmp_path):
    """Before printing the model, five small assemblies with its joints: the job's own slot offset in the middle and
    two steps either way, every radial half-slice kept (that is what makes the real one tight), rings cut to two,
    each part engraved with its offset, all on one plate and one STL per offset."""
    from core.solid import fit_plan, fit_set
    plan = build(EXAMPLES / "egg.stl", "radial", {"count": 5, "ring_count": 3, "slot_offset": 0.1, "autofix": "off"})
    v = fit_plan(plan, 2, 0.1)
    assert abs(v["params"]["slot_offset"] - 0.3) < 1e-9 and v["params"]["count"] == 5 and v["params"]["ring_count"] == 2
    assert max(v["bbox"]) < 100 and v["counts"]["parts"] == 12                   # 2 rings + 10 half-slices, small
    files = {f.name for f in fit_set(plan, tmp_path, step=0.1)}
    assert {"fit_-0.10.stl", "fit_0.00.stl", "fit_0.10.stl", "fit_0.20.stl", "fit_0.30.stl", "plate.3mf", "README.txt"} <= files
    scene = trimesh.load(tmp_path / "plate.3mf")
    per_tag = {}
    for name in scene.geometry:
        per_tag[name.split(" ")[0]] = per_tag.get(name.split(" ")[0], 0) + 1
    assert per_tag == {t: 12 for t in ("-0.10", "0.00", "0.10", "0.20", "0.30")}
    assert "0.10, in the middle" in (tmp_path / "README.txt").read_text(encoding="utf-8")


def test_proto_set_3mf_reloads_with_one_named_geometry_per_part(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    proto_set(plan, tmp_path)

    scene = trimesh.load(tmp_path / "plate.3mf")
    assert isinstance(scene, trimesh.Scene)
    assert len(scene.geometry) == plan["counts"]["parts"]
    expected_labels = {pc["label"] for sl in plan["slices"] for pc in sl["pieces"]}
    assert set(scene.geometry.keys()) == expected_labels
