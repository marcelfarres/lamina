"""Printed standoffs (stacked, `connect` = standoff): laser-cut layers held apart by 3D-printed posts — a body as long
as the gap and wider than the hole, a pin at each end in a dowel hole. Real core.plan.build() runs."""
import json
import pathlib

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from core.export import export, key_text
from core.geometry import hole_reach
from core.plan import build
from core.solid import assembled, standoff_kinds, standoff_mesh

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
JOB = {"space": 8, "connect": "standoff", "dowel_d": 5, "thickness": 3, "autofix": "off"}   # by distance: a layer, then 8 mm of air


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
    body_r = hole_reach(p["dowel_d"] + p["slot_offset"], p["dowel_shape"]) + p["shoulder"]
    assert np.isclose(max(np.hypot(x, y) for x, y in so["body"]), body_r, atol=1e-3)
    assert len(so["items"]) >= 2 * (len(by) - 1)                       # two a pair at least: one would let a layer turn
    for e in so["items"]:
        assert e["gap"] == 8 and e["pins"] == [1.4, 1.4]                # the gap asked for; half the 3 mm layer less 0.1
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


def test_the_print_file_holds_every_standoff_and_the_key_says_where_each_size_goes(tmp_path):
    """The export carries the print file beside the cut files, named 3D-PRINT so it is not taken for a cut file, with
    a note: one object per standoff, a solid as tall as the gap and its two pins, the pin smaller than its hole by the
    slot offset and the pin fit. The assembly key lists the sizes."""
    plan = build(EXAMPLES / "egg.stl", "stacked", {**JOB, "dowel_shape": "square", "slot_offset": 0.1, "pin_fit": 0.2})
    files = export(plan, tmp_path, ("svg",), key=True)
    n = len(plan["standoffs"]["items"])
    f, note = (next(f for f in files if f.name.endswith(f"3D-PRINT standoffs x{n}{ext}")) for ext in (".3mf", ".txt"))   # named for its machine
    assert "The laser cuts the sheets" in note.read_text(encoding="utf-8")
    scene = trimesh.load(f)
    assert len(scene.geometry) == n
    (tag, gap, pins, items), = standoff_kinds(plan)                    # one gap, one size
    assert (tag, gap, pins, len(items)) == ("S1", 8, (1.4, 1.4), n)
    m = standoff_mesh(plan, gap, pins)
    assert m.is_watertight and np.isclose(m.extents[2], 8 + 2.8)
    pin = Polygon(plan["standoffs"]["pin"])
    assert np.allclose(pin.bounds, [-2.4, -2.4, 2.4, 2.4])              # 5 mm less the 0.2 fit, square as its 5.1 mm hole
    assert np.isclose(m.volume, pin.area * 2.8 + Polygon(plan["standoffs"]["body"]).area * 8, rtol=1e-3)
    key = key_text(plan)
    assert "3D PRINT" in key and f"S1    {n:<6}8" in key and "Z-1 / Z-2" in key and "Dowels" not in key
    whole = assembled(plan)                                            # the assembled model has them in place
    parts = sum(pc["area"] * sl["thickness"] for sl in plan["slices"] for pc in sl["pieces"])
    assert np.isclose(whole.volume, parts + n * m.volume, rtol=1e-3)


def test_uneven_gaps_give_one_size_of_standoff_for_each_gap():
    """With a spacing curve the gaps differ from pair to pair: each standoff is as long as the gap between the two
    faces it sits between, and the sizes are told apart by that."""
    preset = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))["vase"]["params"]
    plan = build(EXAMPLES / "vase.stl", "stacked", {**preset, "connect": "standoff"})
    z = {sl["label"]: (sl["M"][2][3], sl["thickness"]) for sl in plan["slices"]}
    for e in plan["standoffs"]["items"]:
        (z0, t0), (z1, t1) = z[e["lo"]], z[e["hi"]]
        assert np.isclose(e["gap"], z1 - z0 - (t0 + t1) / 2, atol=1e-3) and np.isclose(e["at"][2], z0 + t0 / 2, atol=1e-3)
    kinds = standoff_kinds(plan)
    assert len(kinds) > 3 and len({gap for _, gap, _, _ in kinds}) == len(kinds)


def test_touching_layers_get_a_plain_printed_pin_and_other_connectors_no_standoffs():
    """No gap, no body: the standoff is a pin through both layers' holes. A dowel or tab job has no standoffs at all."""
    touching = {**JOB, "space": 0, "thickness": 20}
    plan = build(EXAMPLES / "cube.stl", "stacked", touching)
    (_, gap, pins, _), = standoff_kinds(plan)
    assert gap == 0 and np.isclose(standoff_mesh(plan, gap, pins).extents[2], 2 * 9.9)
    for connect in ("dowel", "tab", "none"):
        assert build(EXAMPLES / "cube.stl", "stacked", {**touching, "connect": connect})["standoffs"] is None
