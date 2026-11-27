"""core.checks runs inside core.plan.build(); these tests trigger its two error conditions with real
geometry (no synthetic Slice fixtures) and verify autofix actually clears the one it claims to fix.
"""
import json
import pathlib
import re

from shapely.geometry import Polygon

from core.plan import build

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def test_a_warning_a_technique_leaves_on_a_slice_reaches_the_plan():
    """Stacked, aligned dowels, a dowel typed far outside the model: the technique says so on a slice while it builds,
    and the checks that run after it keep the message (they used to wipe every slice's warnings first)."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off", "placement": "aligned", "dowels": [[500, 500]]})
    assert any("outside the material" in w for sl in plan["slices"] for w in sl["warnings"]), [sl["warnings"] for sl in plan["slices"]]


def test_no_crossing_slice_error_and_autofix_add_resolves_it():
    """curve mode with spines=0 gives every rib nothing to cross (no spine slices exist at all), so
    check_slice()'s `sl.group in ("X", "Y") and not sl.engages` branch fires on every rib."""
    off = build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "off"})
    assert off["counts"]["errors"] > 0
    all_errors = [e for sl in off["slices"] for e in sl["errors"]]
    assert any("no crossing slice" in e for e in all_errors)

    fixed = build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "add"})
    assert fixed["counts"]["errors"] == 0


def test_auto_fix_holds_a_tube_by_joining_its_rings_and_takes_nothing_away():
    """Interlocked through a tube: the wall falls apart into strips nothing joins. Auto-fix added a slice through each
    loose strip's middle, just as loose there, then deleted what still floated: 71 % of the tube at 6 × 5. It now
    gives each loose group the position whose own section reaches the rest, and deletes nothing: the tube is held
    whole, and the parts cover the model as well as with auto-fix off."""
    job = {"nx": 6, "ny": 5, "thickness": 3}
    on = build(EXAMPLES / "tube.stl", "interlocked", job)
    off = build(EXAMPLES / "tube.stl", "interlocked", {**job, "autofix": "off"})
    assert off["counts"]["errors"] > 0 and on["counts"]["errors"] == 0, (off["counts"], on["counts"])
    assert on["params"]["extra_x"] or on["params"]["extra_y"]
    assert not [n for n in on["notes"] if "removed" in n], on["notes"]
    assert on["coverage"] >= off["coverage"] - 0.01, (on["coverage"], off["coverage"])


def test_a_piece_nothing_can_hold_stays_on_the_plan_with_its_fixes():
    """The horse's ear tips on a top layer of their own, in a gapped stack: no connector fits them and nothing
    touches them. Auto-fix used to delete the layer. It stays, says it floats, and offers what would hold it."""
    plan = build(EXAMPLES / "horse.stl", "stacked", {
        "thickness": 3, "axis": "z", "size": [0, 300, 0], "connect": "dowel", "dowel_shape": "square", "placement": "random",
        "space": 6, "dowel_d": 3, "n_points": 2, "round": 3, "thicken": 1, "margin": 3})
    top = plan["slices"][-1]                           # Z-28: the remesh no longer grows the model by most of a voxel
    assert top["pieces"] and any("floats" in e for e in top["errors"]), top["errors"]
    titles = [o["title"] for f in top["fixes"] for o in f["options"]]
    assert any("gap 0" in t for t in titles), titles


def test_a_stacked_layer_is_never_offered_for_deletion():
    """A layer of a stack *is* the model at that height: "delete Z-2" answers the check and ruins the piece, which is
    what the reporter hit. The fixes offered for a stacked layer keep it — glue the stack, thinner pegs, grow the
    outline, round the model — while the same errors elsewhere may still offer a deletion."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {
        "distribution": "count", "count": 3, "size": [40, 40, 40], "min_feature": 50, "autofix": "off",
    })
    stacked = [o["title"] for sl in plan["slices"] if sl["group"] == "S" for f in sl["fixes"] for o in f["options"]]
    assert stacked, "no fixes offered at all"
    assert not any(t.startswith("delete") for t in stacked), stacked
    assert any("grow" in t or "round" in t or "thicken" in t for t in stacked), stacked
    crossing = build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "off"})
    assert any(t.startswith("delete") for sl in crossing["slices"] for f in sl["fixes"] for o in f["options"] for t in [o["title"]])


def test_a_part_with_points_along_a_straight_side_measures_its_real_size():
    """A 120 × 660 mm part turned 30°, with points along its long sides where slots meet them. GEOS's
    minimum_rotated_rectangle returns a flat line for it (area 0), and min_dims read that as 0.0 mm wide: the tall_bar
    preset's Y slices then failed as "too thin" and were never split to fit the sheet. Every size check and the
    sheet split go through min_dims."""
    from shapely import affinity
    from shapely.geometry import Polygon
    from core.checks import min_dims
    side = [-100, 50, 200]
    part = affinity.rotate(Polygon([(-60, -330), *[(-60, y) for y in side], (-60, 330), (60, 330),
                                    *[(60, y) for y in side[::-1]], (60, -330)]), 30, origin=(0, 0))
    assert part.minimum_rotated_rectangle.area < 1, "GEOS measures this one right now: the test no longer bites"
    w, h = min_dims(part)
    assert abs(w - 120) < 1e-6 and abs(h - 660) < 1e-6, (w, h)


def test_thin_feature_error_when_min_feature_exceeds_part():
    """The cube scaled to 40 mm with min_feature at the slider's top (50 mm): every stacked slice's own bulk reads
    as "too thin", forcing the check_slice() min_dims() thin-part branch."""
    plan = build(EXAMPLES / "cube.stl", "stacked", {
        "distribution": "count", "count": 3, "size": [40, 40, 40], "min_feature": 50, "autofix": "off",
    })
    assert plan["counts"]["errors"] > 0
    all_errors = [e for sl in plan["slices"] for e in sl["errors"]]
    assert any("thin" in e.lower() for e in all_errors)


def test_a_spacer_too_thin_offers_bigger_connectors_and_they_hold():
    """Reported: the horse in stacked with tab spacers on 2 mm connectors came back with every spacer "thinner than
    2 mm everywhere — thicken / round the model", which never reaches a spacer: it is drawn at the connector's size.
    The error says so, and its fix sets a connector size whose spacers keep the wall; applied, they are clean."""
    job = {"distribution": "count", "count": 6, "space": 4, "connect": "tab", "dowel_d": 2, "thickness": 3, "autofix": "off"}
    thin = build(EXAMPLES / "egg.stl", "stacked", job)
    spacers = [s for s in thin["slices"] if s["group"] == "P"]
    assert spacers and all(any("connector's size" in e for e in s["errors"]) for s in spacers), spacers[0]["errors"]
    fix = next(o["set"] for f in spacers[0]["fixes"] for o in f["options"] if "dowel_d" in o["set"])
    fixed = build(EXAMPLES / "egg.stl", "stacked", {**job, **fix})
    assert not [e for s in fixed["slices"] if s["group"] == "P" for e in s["errors"]], fix


def test_thin_tips_and_slivers_are_warned_and_trimmed_on_request():
    """A radial slice through a cone meets the surface at a grazing angle near the apex and ends in a point thinner
    than the min feature for centimetres: a warning on the part, with trimming among its fixes. With `trim_thin`
    the point is cut off blunt, the warning goes, and the plan says how many spots went."""
    cone = EXAMPLES / "cone.stl"
    params = {"count": 8, "ring_count": 4, "thickness": 3, "autofix": "off"}           # the example's preset
    plan = build(cone, "radial", params)
    thin = [(sl["label"], w) for sl in plan["slices"] for w in sl["warnings"] if "thin spot" in w]
    assert thin and all("trim thin spots" in w for _, w in thin)
    assert any("trim_thin" in json.dumps(f) for sl in plan["slices"] for f in sl["fixes"])
    trimmed = build(cone, "radial", {**params, "trim_thin": True})
    assert not [w for sl in trimmed["slices"] for w in sl["warnings"] if "thin spot" in w]
    assert any("thin spot(s) trimmed" in n for n in trimmed["notes"])
    area = lambda pl, lab: sum(Polygon(r[0], r[1:]).area for sl in pl["slices"] if sl["label"] == lab for pc in sl["pieces"] for r in pc["kerfed"])
    lab = thin[0][0]
    assert 0 < area(plan, lab) - area(trimmed, lab) < 0.05 * area(plan, lab)     # a point gone, the part otherwise whole


def test_a_geometry_operation_the_engine_refuses_is_retried_snapped_then_given_up():
    """The browser build's GEOS now and then throws on a finite outline where the desktop's never does. Such an
    operation is run again on precision-snapped copies, and when that fails too the caller gets its default — a
    label beside its part, a thin spot not reported — instead of a model that will not slice."""
    from shapely.errors import GEOSException
    from shapely.geometry import box
    from core.geometry import robust
    calls = []
    def flaky(a, b):
        calls.append((a, b))
        if len(calls) == 1:
            raise GEOSException("IllegalArgumentException: CGAlgorithmsDD::orientationIndex encountered NaN/Inf numbers")
        return a.difference(b)
    out = robust(flaky, box(0, 0, 10, 10), box(5, 0, 15, 10))
    assert len(calls) == 2 and abs(out.area - 50) < 1e-6                     # the second try, on snapped copies, went through
    def never(a):
        raise GEOSException("no")
    assert robust(never, box(0, 0, 1, 1)) is None
    assert robust(never, box(0, 0, 1, 1), default=[]) == []
    assert abs(robust(lambda a: a.buffer(1), box(0, 0, 1, 1)).area - box(0, 0, 1, 1).buffer(1).area) < 1e-9   # the ordinary path untouched


def test_a_finding_carries_its_kind_and_what_it_is_about_and_its_fix_does_not_read_the_words(monkeypatch):
    """The fixes of a finding are chosen by its kind, never by searching its sentence: a floating region says which
    region, a thin spot is only a kind, and the same findings reworded still get every option they got."""
    from core import plan as plan_mod
    from core.model import Issue, KINDS
    seen = []
    real = plan_mod.suggest_fixes

    def spy(slices, p, ctx, mode):
        found = [(sl, e) for sl in slices for e in [*sl.errors, *sl.warnings]]
        seen.append(found)
        real(slices, p, ctx, mode)
        seen.append({str(f["error"]): [o["title"] for o in f["options"]] for sl in slices for f in sl.fixes})
        if reword:                                     # the same kinds in other words: the fixes must not change
            for sl, e in found:
                lst = sl.errors if e in sl.errors else sl.warnings
                lst[lst.index(e)] = Issue("something else entirely", e.kind, **e.about) if getattr(e, "kind", "") else e
            real(slices, p, ctx, mode)
            seen.append({f["error"]: [o["title"] for o in f["options"]] for sl in slices for f in sl.fixes})

    monkeypatch.setattr(plan_mod, "suggest_fixes", spy)
    monkeypatch.setenv("LAMINA_NO_REUSE", "1")           # the cone is sliced twice: the second must make its parts again, or the spy sees nothing
    reword = False
    build(EXAMPLES / "cube.stl", "curve", {"count": 6, "spines": 0, "autofix": "off"})
    found = seen[0]
    none = [e for _, e in found if getattr(e, "kind", "") == "no-crossing"]
    assert none and all(isinstance(e, Issue) and e.kind in KINDS for _, e in found if getattr(e, "kind", ""))
    seen.clear()
    build(EXAMPLES / "horse.stl", "stacked", {
        "thickness": 3, "axis": "z", "size": [0, 300, 0], "connect": "dowel", "dowel_shape": "square", "placement": "random",
        "space": 6, "dowel_d": 3, "n_points": 2, "round": 3, "thicken": 1, "margin": 3, "autofix": "off"})
    gap = [e for _, e in seen[0] if getattr(e, "kind", "") == "gap"]
    assert gap and all(isinstance(e.about["region"], int) for e in gap)
    seen.clear()
    build(EXAMPLES / "cone.stl", "radial", {"count": 8, "ring_count": 4, "thickness": 3, "autofix": "off"})
    assert any(getattr(e, "kind", "") == "thin-spot" for _, e in seen[0])
    seen.clear()
    reword = True
    build(EXAMPLES / "cone.stl", "radial", {"count": 8, "ring_count": 4, "thickness": 3, "autofix": "off"})
    first, again = seen[1], seen[2]
    assert any("trim thin spots off every part" in t for ts in first.values() for t in ts)
    assert list(again.values()) == list(first.values()) and "something else entirely" in again


def test_an_island_whose_place_is_engraved_is_not_a_loose_island():
    """Bug 045: a stacked island with no dowel through it was warned about on every example (cow_spot, horse_statue,
    bunny) whether or not anything showed where it goes. With the next layer outline engraved, its place is marked (its
    own outline on the layer below, or the layer above's on it) and glue holds it like every other layer: no warning.
    Without the engraving it is still warned about, and the warning offers the engraving."""
    prm = {"axis": "x", "distribution": "count", "count": 6, "connect": "none", "autofix": "off"}   # the torus lying flat: two rings
    islands = lambda plan: [w for sl in plan["slices"] for w in sl["warnings"] if "separate island" in w]   # noqa: E731
    off = build(EXAMPLES / "torus.stl", "stacked", prm)
    assert len(islands(off)) == 8, islands(off)
    assert all(any(o["set"] == {"next_outline": True} for f in sl["fixes"] for o in f["options"])
               for sl in off["slices"] if any("separate island" in w for w in sl["warnings"]))
    on = build(EXAMPLES / "torus.stl", "stacked", {**prm, "next_outline": True})
    assert islands(on) == [] and on["counts"]["warnings"] == 0
    assert all(any(style == "guide" for pc in sl["pieces"] for style, _ in pc["lines"]) for sl in on["slices"][:-1])   # the marks that place them


def test_a_radial_core_ring_says_when_its_fingers_are_thinner_than_the_sheet():
    """Bug 055: the finger check ran on the X, Y and Z families only, so a radial core ring, notched round its edge by
    every half-slice, never said that 30 half-slices on the egg leave fingers well under the 3 mm sheet. Every family
    slotted into another is checked now; the egg as it opens (8 half-slices) leaves none."""
    job = {"thickness": 3, "slot_offset": 0.1, "autofix": "off"}
    crowded = build(EXAMPLES / "egg.stl", "radial", {**job, "count": 30, "ring_count": 12})
    warned = [w for sl in crowded["slices"] if sl["group"] == "C" for w in sl["warnings"] if "finger" in w]
    assert warned and all(float(re.search(r"\((\d+\.\d) mm <", w)[1]) < 3 for w in warned), warned[:2]
    plain = build(EXAMPLES / "egg.stl", "radial", {**job, "count": 8, "ring_count": 5})
    assert not [w for sl in plain["slices"] for w in sl["warnings"] if "finger" in w]
