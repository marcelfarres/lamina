"""Printed standoffs (stacked, `connect` = standoff): laser-cut layers held apart by 3D-printed posts — a body as long
as the gap and wider than the hole, a pin at each end in a hole. Real core.plan.build() runs."""
import json
import pathlib

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from core.export import export, key_text
from core.geometry import hole_reach
from core.plan import build
from core.solid import assembled, proto_set, standoff_kinds, standoff_mesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
# by distance: a layer, then 8 mm of air. Square holes, so a shared hole (4 corners) is told from a flush one (5)
JOB = {"space": 8, "connect": "standoff", "dowel_d": 5, "dowel_shape": "square", "thickness": 3, "autofix": "off"}


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


def test_the_print_file_holds_every_standoff_lying_flat_and_the_key_says_where_each_size_goes(tmp_path):
    """The export carries the print file beside the cut files, named 3D-PRINT so it is not taken for a cut file, with
    a note. One object per standoff, each a closed solid as long as the gap and its two pins, lying on the flat its
    body and both pins share, so it prints without supports. A pin is smaller than its hole by the slot offset and
    the pin fit. The assembly key lists the sizes and which pin goes in which hole."""
    plan = build(EXAMPLES / "egg.stl", "stacked", {**JOB, "slot_offset": 0.1, "pin_fit": 0.2})
    so = plan["standoffs"]
    files = export(plan, tmp_path, ("svg",), key=True)
    n = len(so["items"])
    f, note = (next(f for f in files if f.name.endswith(f"3D-PRINT standoffs x{n}{ext}")) for ext in (".3mf", ".txt"))   # named for its machine
    assert "pentagon pin, long" in note.read_text(encoding="utf-8")
    pin, flush, body = (Polygon(so[k]) for k in ("pin", "flush", "body"))
    assert np.allclose(pin.bounds, [-2.4, -2.4, 2.4, 2.4])              # 5 mm less the 0.2 fit, square as its 5.1 mm hole
    assert np.isclose(flush.bounds[1], -2.4) and np.isclose(body.bounds[1], -2.4)      # one flat under all three
    assert body.contains(pin.buffer(-0.01)) and body.contains(flush.buffer(-0.01))
    scene = trimesh.load(f)
    assert len(scene.geometry) == n
    tall = body.bounds[3] - body.bounds[1]                              # lying: from the flat to the top of the body
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
