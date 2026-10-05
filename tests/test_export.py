"""core.export (SVG/DXF) and core.solid (STL/3MF) against a real plan. Expected entity counts are
derived from the plan's own data (never hardcoded), then checked against the parsed export output —
lxml for SVG, ezdxf for DXF — so nothing here trusts export.py's own claims about what it wrote.
"""
import pathlib
import re

import ezdxf
import trimesh
from lxml import etree

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

    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))
    score_g = tree.xpath('//svg:g[@id="SCORE"]', namespaces=SVG_NS)[0]
    label_g = tree.xpath('//svg:g[@id="LABEL"]', namespaces=SVG_NS)[0]
    assert len(score_g.xpath('.//svg:path', namespaces=SVG_NS)) == exp["score"]
    # LABEL text = per-piece marks + per-piece label + the sheet title text
    assert len(label_g.xpath('.//svg:text', namespaces=SVG_NS)) == exp["marks"] + exp["label_pos"] + 1


def test_dxf_reloads_with_same_layers_and_matching_entity_counts(tmp_path):
    plan = build(EXAMPLES / "cube.stl", "folded", {"facet": 0, "joint": "laced", "autofix": "off"})
    export(plan, tmp_path, fmts=("dxf",), labels=True)
    exp = sheet0_expected_counts(plan)

    doc = ezdxf.readfile(str(tmp_path / f"{design_name(plan)} sheet1.dxf"))
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
    tree = etree.parse(str(tmp_path / f"{design_name(plan)} sheet1.svg"))                          # still well-formed…
    assert not tree.xpath("//*[local-name()='img']")                          # …and the tag is not an element
    assert '<img' in "".join(tree.xpath('//svg:g[@id="LABEL"]/svg:text/text()', namespaces=SVG_NS))   # but text


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
        assert f">egg {code}<" in sheets                  # engraved: the model's name and the code
        assert f" {label}<" not in sheets                 # never where the part goes
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
    assert svg.count(">0.30<") == 12 and "0.10, in the middle" in (tmp_path / "cut" / "README.txt").read_text(encoding="utf-8")


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
