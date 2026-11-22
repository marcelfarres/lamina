"""Printed standoffs (stacked, `connect` = standoff): laser-cut layers held apart by 3D-printed posts — a body as long
as the gap and wider than the hole, a pin at each end in a hole. Real core.plan.build() runs."""
import json
import pathlib

import numpy as np
import pytest
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from core.export import design_name, export, key_text
from core.geometry import hole_reach
from core.plan import build
from core.solid import assembled, proto_set, standoff_files, standoff_kinds, standoff_mesh, standoff_print

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
# by distance: a layer, then 8 mm of air. Square holes, so a shared hole (4 corners) is told from a flush one (5)
JOB = {"space": 8, "connect": "standoff", "dowel_d": 5, "dowel_shape": "square", "thickness": 3, "autofix": "off"}
SHADE = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["shade"]["params"]   # the example he prints: flush pins both ends


def local(sl, at):
    """The world point `at` in the slice's own x, y."""
    return (np.linalg.inv(np.array(sl["M"])) @ np.array([*at, 1.0]))[:2]


def test_a_standoff_has_a_hole_in_both_layers_and_its_body_rests_on_both():
    """Every standoff joins two neighbour layers: each has a hole where its pin goes, and the whole body, wider than
    the hole by the shoulder, lies on the material of both, a full wall in from the outline and clear of the next
    body. Nothing is a rod to buy or a flat part to cut: the standoffs are the plan's own list."""
    plan = build(EXAMPLES / "egg.stl", "stacked", JOB)
    so, p = plan["standoffs"], plan["params"]
    assert plan["rods"] == [] and {sl["group"] for sl in plan["slices"]} == {"S"}
    assert not plan["counts"]["errors"], [e for sl in plan["slices"] for e in sl["errors"]]
    by = {sl["label"]: sl for sl in plan["slices"]}
    hole = p["dowel_d"] + p["slot_offset"]
    body_r = max(hole_reach(hole, "square"), hole_reach(hole, "pentagon")) + p["shoulder"]      # it covers either hole
    assert np.isclose(max(np.hypot(x, y) for x, y in so["body"]), body_r, atol=1e-3)
    assert len(so["items"]) >= 2 * (len(by) - 1)                       # two a pair at least: one would let a layer turn
    for e in so["items"]:
        assert e["gap"] == 8
        for label in (e["lo"], e["hi"]):
            sl = by[label]
            q = Point(local(sl, e["at"]))
            cut = unary_union([Polygon(r[0], r[1:]) for pc in sl["pieces"] for r in pc["kerfed"]])
            outline = unary_union([Polygon(r[0]) for pc in sl["pieces"] for r in pc["kerfed"]])
            assert outline.contains(q) and not cut.contains(q), (e["name"], label)          # a hole there
            assert outline.buffer(-p["min_feature"] + 0.01).contains(q.buffer(body_r)), (e["name"], label)
        assert "standoff" in by[e["lo"]]["engages"] and "standoff" in by[e["hi"]]["engages"]
    for label, sl in by.items():                                       # two bodies on one face never overlap
        for side in ("lo", "hi"):
            pts = [local(sl, e["at"]) for e in so["items"] if e[side] == label]
            assert all(np.hypot(*(a - b)) >= 2 * body_r for i, a in enumerate(pts) for b in pts[i + 1:]), label


def test_a_shared_hole_takes_two_half_pins_and_a_hole_of_its_own_a_flush_pin_in_another_shape():
    """A hole two standoffs use, one from each side of the layer, keeps the dowel hole shape (a square here) and each
    pin goes half way in. A hole one standoff uses is a pentagon, and its pin is as long as the layer is thick: it
    ends flush with the far face, so no hole is left half empty and the shape says which end goes in. The first and
    last layer have only such holes."""
    plan = build(EXAMPLES / "egg.stl", "stacked", JOB)
    items = plan["standoffs"]["items"]
    seen = set()
    for sl in plan["slices"]:
        holes = [Polygon(ring) for pc in sl["pieces"] for r in pc["kerfed"] for ring in r[1:]]
        ends = [(tuple(np.round(local(sl, e["at"]), 2)), e, i) for e in items for i, side in enumerate(("lo", "hi")) if e[side] == sl["label"]]
        for at in {a for a, _, _ in ends}:
            users = [(e, i) for a, e, i in ends if a == at]
            hole = next(h for h in holes if h.contains(Point(at)))
            own = len(users) == 1
            assert len(hole.exterior.coords) - 1 == (5 if own else 4), (sl["label"], at)
            for e, i in users:
                assert e["flush"][i] == own and e["pins"][i] == (3.0 if own else 1.4), (e["name"], sl["label"])
            seen.add(own)
        if sl is plan["slices"][0] or sl is plan["slices"][-1]:
            assert all(e["flush"][i] for _, e, i in ends) and ends, sl["label"]
    assert seen == {True, False}                                       # the egg has both kinds


@pytest.mark.parametrize("example,job", [("egg", JOB), ("shade", SHADE)], ids=["egg", "shade"])
def test_a_standoff_prints_as_two_halves_that_touch_and_fold_into_it(example, job):
    """Bug 058 (Marcel's first print: "the dowels are difficult to print"). A standoff is printed cut in half along
    its length, both halves with the cut face on the plate: one closed solid, no face that hangs in the air past 45
    degrees, and most of its footprint on the plate. The two bodies touch along one line and are joined there two
    layers high. His second print had a strip between the halves: "there is a space between each half ... it bends at
    the piece not the center of the tab", and the halves closed out of line. With no space the print is exactly two
    bodies wide, there is one line to fold on, and folded about it every point of the print lies on the standoff.
    On a job with square holes and shared pins, and on the shade example as it opens."""
    plan = build(EXAMPLES / f"{example}.stl", "stacked", job)
    so, h = plan["standoffs"], plan["params"]["standoff_hinge"]
    R = Polygon(so["body"]).bounds[2]; w = 0.0                         # no space between the halves
    assert h == 0.4
    for _, gap, ends, _ in standoff_kinds(plan):
        m = standoff_print(plan, gap, ends)
        L = gap + ends[0][0] + ends[1][0]
        assert m.is_watertight and len(m.split()) == 1
        assert np.allclose(m.bounds, [[0, 0, 0], [L, 4 * R + w, R]], atol=1e-3)      # two half bodies side by side, half as tall
        n, a, z = m.face_normals, m.area_faces, m.triangles[:, :, 2]
        assert a[(n[:, 2] < -np.cos(np.radians(45))) & (z.min(1) > 0.01)].sum() < 1e-6      # nothing for a support to hold
        whole = standoff_mesh(plan, gap, ends)
        on_plate = a[(n[:, 2] < -0.99) & (z.max(1) < 0.01)].sum()
        assert on_plate > 0.9 * whole.area_faces[np.abs(whole.face_normals[:, 2]) < 0.01].sum() / np.pi   # both cut faces, whole
        assert np.isclose(m.volume, whole.volume, rtol=0.002)             # the standoff: the join adds next to nothing
        # at the top of the join the two halves are less than a tenth of a millimetre apart: a line, not a strip
        low = m.section(plane_origin=[ends[0][0] + gap / 2, 0, 0], plane_normal=[1, 0, 0]).vertices
        assert np.abs(low[np.abs(low[:, 2] - h) < 1e-6][:, 1] - 2 * R).max() < 0.05
        # fold the second half over, half a turn about the line the halves touch on, and both lie on the standoff
        whole.apply_transform([[0, 0, 1, 0], [1, 0, 0, R], [0, 1, 0, 0], [0, 0, 0, 1]])
        v = m.vertices.copy()
        far = v[:, 1] > 2 * R
        v[far, 1] = 4 * R - v[far, 1]; v[far, 2] *= -1
        strip = (np.abs(v[:, 2]) <= h + 1e-6) & (v[:, 1] > 2 * R - 0.31)          # the join, where it runs into each half
        off = trimesh.proximity.closest_point(whole, v[~strip])[1]
        assert off.max() < 1e-3, off.max()


def test_a_standoff_smaller_than_any_print_has_confirmed_is_warned_about_with_the_setting_that_grows_it():
    """Bug 058. A dowel diameter under 5 mm and shared pins under 2 mm long are each a warning of the plan: it says
    that no print has confirmed the size yet, never that it fails (no print is behind the two limits), and it names
    the setting that makes the pin bigger. With 6 mm pins and random placement no hole is shared, every pin is as
    long as the layer is thick, and nothing is warned."""
    said = lambda **job: build(EXAMPLES / "egg.stl", "stacked", {**JOB, **job})["warnings"]   # noqa: E731
    small = said(dowel_d=4)
    assert any("3.9 mm across" in w and "dowel diameter to 5 mm or more" in w for w in small), small
    assert any("are 1.4 mm long" in w and "placement to random" in w for w in small), small
    assert all("No print has confirmed" in w and "print one to check" in w for w in small) and len(small) == 2, small
    five = said()                                                      # 5 mm: wide enough, the shared pins still short
    assert len(five) == 1 and "are 1.4 mm long" in five[0], five
    plan = build(EXAMPLES / "egg.stl", "stacked", {**JOB, "dowel_d": 6, "placement": "random"})
    assert plan["warnings"] == [] and {n for e in plan["standoffs"]["items"] for n in e["pins"]} == {3.0}
    assert all(all(e["flush"]) for e in plan["standoffs"]["items"])


def test_the_print_file_holds_every_standoff_and_the_key_says_where_each_size_goes(tmp_path):
    """The export carries the print file beside the cut files, named 3D-PRINT so it is not taken for a cut file, with
    a note. One object per standoff, each a closed solid on the plate. A pin is smaller than its hole by the slot
    offset and the pin fit. The assembly key lists the sizes, which pin goes in which hole, and how to fold one."""
    plan = build(EXAMPLES / "egg.stl", "stacked", {**JOB, "slot_offset": 0.1, "pin_fit": 0.2})
    so = plan["standoffs"]
    files = export(plan, tmp_path, ("svg",), key=True)
    n = len(so["items"])
    f, note = (next(f for f in files if f.name.endswith(f"3D-PRINT standoffs x{n}{ext}")) for ext in (".3mf", ".txt"))   # named for its machine
    said = note.read_text(encoding="utf-8")
    assert "pentagon pin, long" in said and "Fold the two halves together" in said
    pin, flush, body = (Polygon(so[k]) for k in ("pin", "flush", "body"))
    assert np.allclose(pin.bounds, [-2.4, -2.4, 2.4, 2.4])              # 5 mm less the 0.2 fit, square as its 5.1 mm hole
    assert np.isclose(flush.bounds[1], -2.4)                            # the pentagon as far across as the square
    assert body.contains(pin.buffer(-0.01)) and body.contains(flush.buffer(-0.01))
    scene = trimesh.load(f)
    assert len(scene.geometry) == n
    tall = body.bounds[3]                                               # two halves, cut face down: half the body high
    assert all(g.is_watertight and np.isclose(g.bounds[0][2], 0, atol=1e-6) and np.isclose(g.bounds[1][2], tall, atol=1e-3) for g in scene.geometry.values())
    kinds = standoff_kinds(plan)
    assert [tag for tag, *_ in kinds] == [f"S{i + 1}" for i in range(len(kinds))] and sum(len(it) for *_, it in kinds) == n
    key = key_text(plan)
    total = 0.0
    for tag, gap, ends, its in kinds:
        m = standoff_mesh(plan, gap, ends)
        (p0, f0), (p1, f1) = ends
        assert m.is_watertight and np.isclose(m.extents[2], gap + p0 + p1)
        assert np.isclose(m.volume, body.area * gap + sum((flush if fl else pin).area * h for h, fl in ends), rtol=1e-3)
        assert f"{tag:<6}{len(its):<6}8" in key
        total += len(its) * m.volume
    assert "3D PRINT" in key and "The sheet files are for the cutter" in key and "Z-1 / Z-2" in key and "Dowels" not in key
    parts = sum(pc["area"] * sl["thickness"] for sl in plan["slices"] for pc in sl["pieces"])
    assert np.isclose(assembled(plan).volume, parts + total, rtol=1e-3)   # the assembled model has them in place


def test_every_standoff_of_the_shade_carries_its_size_on_a_tag_and_touches_no_other(tmp_path):
    """The shade's print file: each object is one standoff with its size (S1 …) standing on a tag joined to it, one
    closed solid, so the size stays with its part on the bed; and no object runs into another."""
    from core.solid import CHIP_H, LETTER_H, LINE_W
    plan = build(EXAMPLES / "shade.stl", "stacked", SHADE)
    f = next(f for f in standoff_files(plan, tmp_path, design_name(plan)) if f.suffix == ".3mf")
    kinds = {tag: standoff_print(plan, gap, ends).volume for tag, gap, ends, _ in standoff_kinds(plan)}
    scene, feet = trimesh.load(f), []
    for name in scene.graph.nodes_geometry:
        M, g = scene.graph[name]; m = scene.geometry[g].copy(); m.apply_transform(M)
        up, z = m.face_normals[:, 2] > 0.99, m.triangles_center[:, 2]
        assert m.is_watertight and m.body_count == 1 and m.volume > kinds[name.split()[0]] + 1, name   # the standoff and its tag, one solid
        assert m.area_faces[up & (np.abs(z - (CHIP_H + LETTER_H)) < 0.01)].sum() > 2, name           # letters standing on the chip
        down = m.triangles[(m.face_normals[:, 2] < -0.99) & (m.triangles_center[:, 2] < 1e-3)]
        feet.append(unary_union([Polygon(t[:, :2]) for t in down]).buffer(0))
    assert len(feet) == len(plan["standoffs"]["items"])
    assert all(a.distance(b) > LINE_W for i, a in enumerate(feet) for b in feet[i + 1:])


def test_a_printed_job_gets_its_standoffs_in_the_print_set(tmp_path):
    """Layers that are 3D printed too: the print set holds the plates and the standoffs' own file."""
    plan = build(EXAMPLES / "egg.stl", "stacked", {**JOB, "printed": True, "size": [0, 0, 60], "sheet": [256, 256], "dowel_d": 4, "space": 6})
    names = [f.name for f in proto_set(plan, tmp_path, labels="none")]
    n = len(plan["standoffs"]["items"])
    assert n and any(x.endswith(f"3D-PRINT standoffs x{n}.3mf") for x in names) and "plate-1.3mf" in names, names


def test_uneven_gaps_give_standoffs_as_long_as_each_gap():
    """With a spacing curve the gaps differ from pair to pair: each standoff is as long as the gap between the two
    faces it sits between, and the sizes are told apart by that."""
    preset = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["vase"]["params"]
    plan = build(EXAMPLES / "vase.stl", "stacked", {**preset, "connect": "standoff"})
    z = {sl["label"]: (sl["M"][2][3], sl["thickness"]) for sl in plan["slices"]}
    for e in plan["standoffs"]["items"]:
        (z0, t0), (z1, t1) = z[e["lo"]], z[e["hi"]]
        assert np.isclose(e["gap"], z1 - z0 - (t0 + t1) / 2, atol=1e-3) and np.isclose(e["at"][2], z0 + t0 / 2, atol=1e-3)
    assert len({gap for _, gap, _, _ in standoff_kinds(plan)}) > 3


def test_touching_layers_get_a_plain_printed_pin_and_other_connectors_no_standoffs():
    """No gap, no body: the standoff is a pin through both layers' holes. A dowel or tab job has no standoffs at all."""
    touching = {**JOB, "space": 0, "thickness": 20}
    plan = build(EXAMPLES / "cube.stl", "stacked", touching)
    for _, gap, ends, _ in standoff_kinds(plan):
        assert gap == 0 and np.isclose(standoff_mesh(plan, gap, ends).extents[2], ends[0][0] + ends[1][0])
    for connect in ("dowel", "tab", "none"):
        assert build(EXAMPLES / "cube.stl", "stacked", {**touching, "connect": connect})["standoffs"] is None
