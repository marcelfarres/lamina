"""Paper lamps (Folded Panels): faces merged into one flat face, one window per flat piece, and windows closed by a
pane: a paper part on a cut job, a thin printed layer on a printed job. Real core.plan.build() runs, autofix off."""
import pathlib
import numpy as np
from shapely.geometry import Point, Polygon
from core.mesh import flatten
from core.plan import build
from core.solid import proto_part
from core.export import export
from tests.test_removed import egg, in_file

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
CARD = {"autofix": "off", "thickness": 1, "material": "card", "joint": "tab", "facet": 0, "window": 0.6}


def cube(**params):
    return build(EXAMPLES / "cube.stl", "folded", {**CARD, **params})


def panels(plan):
    return [s for s in plan["slices"] if s["group"] == "F"]


def holes(plan):
    return sum(len(rings) - 1 for s in panels(plan) for pc in s["pieces"] for rings in pc["kerfed"])


def papers(plan):
    return [fc["paper"] for s in panels(plan) for pc in s["pieces"] for fc in pc["facets"] if "paper" in fc]


def top_of_egg(facet=25):
    mesh, frame = egg(facet)
    return mesh, frame, mesh.triangles_center[:, 2] > mesh.bounds[1][2] * 0.6


def test_merged_faces_become_one_flat_face_and_the_surface_stays_closed():
    mesh, _, top = top_of_egg()
    new, went = flatten(mesh, top)
    assert (went == top).all() and new.is_watertight and new.is_winding_consistent
    flat = new.face_normals[int((~went).sum()):]
    assert 2 <= len(flat) < top.sum() and (flat @ flat[0]).min() > 1 - 1e-9
    assert flat[0][2] > 0.9                                    # it still faces up, as the faces it came from


def test_faces_that_are_not_one_piece_are_left_alone_with_the_reason():
    mesh, _, top = top_of_egg()
    assert flatten(mesh, np.ones(len(mesh.faces), bool))[0] is None        # the whole model has no rim
    one = np.zeros(len(mesh.faces), bool); one[0] = True
    new, why = flatten(mesh, one)
    assert new is None and "fewer than two" in why


def test_a_merged_group_stays_merged_when_the_faces_are_made_again():
    mesh, frame, top = top_of_egg(25)
    group = in_file(mesh.triangles[top], frame)
    for facet in (25, 15):                                    # the facet size it was picked at, and another
        plan = build(EXAMPLES / "egg.stl", "folded", {"autofix": "off", "facet": facet, "joint": "seam", "thickness": 0.3,
                                                      "material": "paper", "merged": [group]})
        f3 = plan["faces3d"]; of = np.array(f3["merged"]); v = np.array(f3["v"]); tri = v[np.array(f3["f"])[of == 0]]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); n /= np.linalg.norm(n, axis=1)[:, None]
        assert len(tri) >= 2 and (n @ n[0]).min() > 1 - 1e-6, facet
        assert not any("merged" in w for s in plan["slices"] for w in s["warnings"])
    assert (np.array(build(EXAMPLES / "egg.stl", "folded", {"autofix": "off", "facet": 25, "joint": "seam"})["faces3d"]["merged"]) == -1).all()


def test_a_group_that_cannot_be_made_flat_is_said_and_nothing_is_lost():
    mesh, frame, _ = top_of_egg()
    plan = build(EXAMPLES / "egg.stl", "folded", {"autofix": "off", "facet": 25, "joint": "seam", "merged": [in_file(mesh.triangles[:1], frame)]})
    assert plan["counts"]["faces"] and len(plan["faces3d"]["f"]) == len(mesh.faces)
    assert any("1 of the 1 groups of faces you merged are left as they are" in w for s in plan["slices"] for w in s["warnings"])


def test_a_flat_side_of_several_faces_gets_one_window():
    plan = cube()
    assert plan["counts"]["errors"] == 0 and len(plan["faces3d"]["f"]) == 12
    assert holes(plan) == 6                                    # a square window per side, not two triangles
    assert not papers(plan) and plan["sheet_stock"] == [""] * plan["sheets"]


def test_a_cut_job_gets_a_paper_part_for_every_window_on_sheets_of_paper(tmp_path):
    plan = cube(window_fill="paper")
    panes = [s for s in plan["slices"] if s["label"].startswith("W-")]
    assert holes(plan) == 6 and len(panes) == 6 and len(papers(plan)) == 6
    assert {s["thickness"] for s in panes} == {0.2} and {s["stock"] for s in panes} == {"paper"}
    on = {pc["place"][0] for s in panes for pc in s["pieces"]}
    assert on.isdisjoint(pc["place"][0] for s in panels(plan) for pc in s["pieces"])
    assert all(plan["sheet_stock"][i] == ("paper" if i in on else "") for i in range(plan["sheets"]))
    open_ = cube()
    window = sum(pc["area"] for s in panels(open_) for pc in s["pieces"])
    assert window == sum(pc["area"] for s in panels(plan) for pc in s["pieces"])      # the panels are cut as without paper
    cut = [Polygon(r).area for s in panels(plan) for pc in s["pieces"] for rings in pc["kerfed"] for r in rings[1:]]   # the windows' own sizes
    for pane, paper in zip(panes, papers(plan)):
        side = Polygon(paper["rings"][0][0])
        assert paper["t"] == 0.2 and paper["z"] == -1.0       # against the inside face of the 1 mm panel
        assert abs(side.area - pane["pieces"][0]["area"]) < 0.1 and max(cut) < side.area < min(cut) * 1.5   # reaches over its window, on to the frame
        assert paper["part"] == pane["label"]                 # the 3D view shows where the paper part goes
    files = [f.name for f in export(plan, tmp_path, fmts=("svg",))]
    assert any("paper" in n for n in files) and any("card" in n for n in files)


def test_a_printed_job_prints_the_window_as_a_thin_layer_on_the_bed():
    job = {"thickness": 2, "printed": True, "hinge": 0, "joint": "seam", "material": "PLA"}
    plan = cube(**job, window_fill="paper")
    assert holes(plan) == 0 and not [s for s in plan["slices"] if s["label"].startswith("W-")]
    assert len(papers(plan)) == 6 and {p["z"] for p in papers(plan)} == {0.0} and plan["sheet_stock"] == [""] * plan["sheets"]
    for s in panels(plan):
        pc = s["pieces"][0]
        pane = sum(Polygon(r[0]).area for r in pc["paper"])
        solid, _, _, _ = proto_part(pc, 2, 1, "none", 5, 0.2)
        assert solid.is_watertight and not solid.metadata["plain"]
        assert abs(solid.volume - (pc["area"] * 2 - pane * (2 - 0.2))) < 0.01 * solid.volume
        # nothing is engraved on a pane: no seam number, and the part's own label keeps off it (0.2 mm would be cut through)
        thin = [Polygon(r[0]) for r in pc["paper"]]
        assert pc["kerfed_marks"] and not any(g.buffer(-0.01).contains(Point(m[0], m[1])) for m in pc["kerfed_marks"] for g in thin)
        with_label, got, _, _ = proto_part({**pc, "kerfed_marks": []}, 2, 1, "groove", 5, 0.2)   # the name alone: seam numbers have their own test (064)
        assert got and abs(with_label.volume - solid.volume) < 60          # a label's groove, not a hole in a pane
    thick = cube(**{**job, "thickness": 1.0}, window_fill="paper", paper_t=1.0)
    assert holes(thick) == 6 and not papers(thick)            # a pane as thick as the panel: the windows stay open, and it says so
    assert any("paper thickness" in w for s in thick["slices"] for w in s["warnings"])


def lamp(**params):
    import json
    preset = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["paper_lamp"]["params"]
    return build(EXAMPLES / "paper_lamp.stl", "folded", {**preset, "autofix": "off", **params})


def tab_area_in_windows(plan):
    """How much of the glue tabs (mm²) lies over a window of the face it is glued to, in the closed model. A window is
    its pane less the 4 mm the pane reaches over the frame (a window across several faces is a hole in none of them)."""
    import numpy as np
    from shapely.ops import unary_union
    facets = [(np.array(fc["M"]), fc) for s in plan["slices"] for pc in s["pieces"] for fc in pc["facets"]]
    holes = [(M, [Polygon(r[0]).buffer(-3.95 if fc["paper"]["z"] < 0 else 0, join_style="mitre") for r in fc["paper"]["rings"]]) for M, fc in facets if "paper" in fc]
    tabs = [(M, fc) for M, fc in facets if fc.get("hinge") and fc["hinge"][1:7] == [0, 0, 0, 0, 0, 1]]   # a tab rides on its face
    assert tabs and holes
    area = 0.0
    for Mt, tab in tabs:
        for Mh, hs in holes:
            if abs(Mt[:3, 2] @ Mh[:3, 2]) > 0.999 and abs((Mt[:3, 3] - Mh[:3, 3]) @ Mh[:3, 2]) < 5:      # in the plane of that face
                for rings in tab["rings"]:
                    w = (np.c_[np.array(rings[0]), np.zeros(len(rings[0])), np.ones(len(rings[0]))] @ Mt.T) @ np.linalg.inv(Mh).T
                    area += Polygon(w[:, :2]).buffer(0).intersection(unary_union(hs)).area
    return area


def test_the_paper_lamp_has_one_window_and_one_paper_shape_per_pentagon():
    """Three dodecahedra, 32 pentagons less the one at the bottom, opened for the bulb: every strategy keeps each
    pentagon whole (no seam across a flat side), so 31 windows and 31 papers, all the same pentagon."""
    for strategy in ("auto", "flat", "strip", "area"):
        plan = lamp(strategy=strategy)
        papers_ = [s for s in plan["slices"] if s["label"].startswith("W-")]
        assert plan["counts"]["errors"] == plan["counts"]["warnings"] == 0, strategy
        assert holes(plan) == 31 and len(papers_) == 31 and plan["faces3d"]["removed"] == 3, strategy
        assert len({round(s["pieces"][0]["area"], 1) for s in papers_}) == 1, strategy


def test_no_glue_tab_reaches_into_a_window():
    """A tab is glued to the frame of the face it folds under: never over the window (the pear lamp had 41 of its 45
    tabs partly over a window, and the 3D view drew dark lines where a tab and the pane lay in one plane)."""
    for plan in (lamp(), lamp(window=0.9), lamp(printed=True, material="PLA", thickness=2, hinge=0.4, sheet=[325, 320]),
                 cube(joint="tab", window_fill="paper"), cube(joint="multitab", window_fill="paper")):
        assert plan["counts"]["errors"] == 0
        assert tab_area_in_windows(plan) < 0.5
