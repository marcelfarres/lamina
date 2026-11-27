"""Band lattice: rings along any of x, y and z, half-lapped where they cross. The first family stays whole, each slot
opens outward in the band placed first and inward in the one placed after it, and a band that cannot slide in whole
is cut into pieces that can, each cut a straight tongue the later piece slides onto — and every piece is checked to
slide in past the ones already there (core/slidein.py)."""
import pathlib
import re

import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from core.modes.bands import Bands
from core.plan import build
from core.ringcut import tongue
from core.slidein import FREE_AREA, covers, sweep
from core.split import tab

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
CUBE = EXAMPLES / "cube.stl"                        # 180 mm, centred
BASE = {"autofix": "off", "thickness": 4, "nx": 3, "ny": 3, "nz": 3, "ring_wall": 12}


def shape(plan, label):
    """A band as cut, all its pieces together, in its own frame."""
    sl = next(s for s in plan["slices"] if s["label"] == label)
    polys = [Polygon(rings[0], rings[1:]) for pc in sl["pieces"] for f in pc["facets"] for rings in f["rings"]]
    return unary_union(polys), sl


def test_two_families_half_lap_with_the_first_whole_and_the_second_cut_in_two():
    plan = build(CUBE, "bands", {**BASE, "z": False})
    assert plan["counts"]["slices"] == 6 and plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    for lab in ("X-1", "X-2", "X-3"):
        g, sl = shape(plan, lab)
        assert len(sl["pieces"]) == 1                                   # placed first: whole
        assert set(sl["engages"]) == {"Y-1", "Y-2", "Y-3"}
    for lab in ("Y-1", "Y-2", "Y-3"):
        assert len(shape(plan, lab)[1]["pieces"]) == 2                 # top and bottom slide in from opposite sides
    assert "X → Y" in " ".join(plan["notes"])


def test_the_slot_opens_outward_in_the_first_band_and_inward_in_the_second():
    plan = build(CUBE, "bands", {**BASE, "z": False})
    x2, _ = shape(plan, "X-2"); y2, _ = shape(plan, "Y-2")
    # the joint at the top of the cube, on the line x = y = 0: the walls run from z = 78 to 90 and meet at 84.
    # Both bands' local y is world z; their local x is 0 on that line
    assert not x2.contains(Point(0, 87)) and x2.contains(Point(0, 81))    # first band: cut from the outside in
    assert y2.contains(Point(0, 87)) and not y2.contains(Point(0, 81))    # second: from the inside out
    assert x2.contains(Point(10, 87)) and y2.contains(Point(10, 81))      # and only a slot wide


def test_three_families_cut_the_later_bands_and_join_every_cut_with_a_tongue():
    plan = build(CUBE, "bands", BASE)
    # no warning: not one cut is a glued butt joint, every one has its tongue
    assert plan["counts"]["slices"] == 9 and plan["counts"]["errors"] == 0 and plan["counts"]["warnings"] == 0
    note = next(n for n in plan["notes"] if n.startswith("assembly"))
    first = note.split(": ")[1][0]
    cuts = int(note.split("; ")[1].split(" cut")[0])
    assert cuts > 0
    whole = [s for s in plan["slices"] if s["label"].startswith(first)]
    assert whole and all(len(s["pieces"]) == 1 for s in whole)
    assert plan["counts"]["parts"] == len(whole) + cuts                 # a closed ring cut k times is k pieces
    later = {pc["label"] for s in plan["slices"] if s not in whole for pc in s["pieces"]}
    assert set(plan["steps"]) == later and sorted(plan["steps"].values()) == list(range(1, len(later) + 1))


def later_pieces(plan):
    first = next(n for n in plan["notes"] if n.startswith("assembly")).split(": ")[1][0]
    return {pc["label"]: s for s in plan["slices"] if not s["label"].startswith(first) for pc in s["pieces"]}


@pytest.mark.parametrize("model, prm, clean", [
    ("cube.stl", {}, True),
    ("sphere.stl", {"thickness": 3}, True),     # the defaults in the sphere example's own 3 mm stock: 5 x 5 x 4 locked two
    ("sphere.stl", {"nx": 3, "ny": 3, "nz": 3}, True),
    ("sphere.stl", {"nx": 4, "ny": 4, "nz": 4}, True),
    # the head locked 7 pieces where its lines ran along the walls of the bands they cross, until those moved (nudge);
    # one band's slots still cut it in two
    ("head_igea.stl", {}, False),
    # the head as the app opens it (its preset: standing, 3 mm stock, rounded and smoothed) locked Z-4-2 and X-2-1: past
    # their slots Y-1's line ran within half a sheet of their walls, and its sheet brushed them as they slid in (shaved)
    ("head_igea.stl", {"thickness": 3, "rotate": [90, 0, 0], "round": 3, "smooth": 6}, True),
])
def test_every_piece_slides_in_past_the_ones_already_there(model, prm, clean):
    plan = build(EXAMPLES / model, "bands", prm)
    later = later_pieces(plan)
    locked = set(later) - set(plan["steps"])
    for lab in locked:                                                  # a piece that cannot get in is its band's error
        assert any(e.startswith(f"{lab} cannot slide in: ") for e in later[lab]["errors"])
    assert not any(e.startswith(f"{lab} cannot") for s in plan["slices"] for e in s["errors"] for lab in plan["steps"])
    assert not locked, sorted(locked)
    assert not clean or plan["counts"]["errors"] == 0, [(s["label"], e) for s in plan["slices"] for e in s["errors"]]


# 12 x bands in the 180 mm cube put the end ones at ±82.5 mm, inside the side walls (8 mm: 82 to 90): their lines with
# every y and z band run along a wall from end to end, the slots along it
GRAZING = {"autofix": "off", "nx": 12, "ny": 2, "nz": 2}


def x_of(plan, label):
    return shape(plan, label)[1]["M"][0][3]


def test_a_band_whose_line_runs_along_a_wall_is_moved_off_it():
    on, off = (build(CUBE, "bands", {**GRAZING, "nudge": n}) for n in (True, False))
    assert x_of(off, "X-12") == 82.5 and x_of(off, "X-1") == -82.5                  # off: where the count puts them
    assert not any("grazing" in n for n in off["notes"]) and not shape(off, "X-12")[1]["note"]
    # on: moved in until its sheet (1.5 mm) is off the wall, at most a quarter of the way to the next band (15 mm)
    assert 82.5 - 15 / 4 <= x_of(on, "X-12") <= 82 - 0.75 + 1e-6 and abs(x_of(on, "X-1") + x_of(on, "X-12")) < 1e-6
    note = next(n for n in on["notes"] if n.startswith("assembly"))
    moved = note.split("moved off a grazing joint (`move grazing bands`): ")[1]
    assert re.search(r"X-12 -\d+\.\d mm, its line with \w-\d ran 1\d\d mm along \w-\d's wall", moved), moved
    assert set(re.findall(r"(\w-\d+) [+-]\d", moved)) == {"X-1", "X-12"}             # nothing else grazes
    assert shape(on, "X-12")[1]["note"].startswith("moved -")
    assert not set(later_pieces(on)) - set(on["steps"])                              # every piece slides in


def test_a_band_moved_by_hand_stays_where_it_is_put():
    plan = build(CUBE, "bands", {**GRAZING, "offset": {"X-12": 0.5}})
    assert x_of(plan, "X-12") == 83.0 and x_of(plan, "X-1") > -82.5               # its mirror image is moved
    note = next(n for n in plan["notes"] if n.startswith("assembly"))
    assert "X-1 +" in note and "X-12 " not in note and not shape(plan, "X-12")[1]["note"]


def test_a_wall_a_sheet_brushes_past_the_slot_is_shaved(monkeypatch):
    # X-4 moved by hand to x = 81.5 mm, half a millimetre into the cube's hollow beside the side walls (82 to 90): its
    # line with each y and z band runs clear of their side walls, but its 1.5 mm sheet overlaps them by a quarter of a
    # millimetre past their slots, all the way along as those pieces slide in. Shaved there, every piece slides in
    prm = {"autofix": "off", "offset": {"X-4": 14}}
    plan = build(CUBE, "bands", prm)
    assert not set(later_pieces(plan)) - set(plan["steps"])
    g, _ = shape(plan, "Y-2")                                           # local x is ±world x, local y world z
    side = max((-1, 1), key=lambda s: g.contains(Point(s * 85, 0)) and not g.contains(Point(s * 82.1, 0)))
    assert not g.contains(Point(side * 82.1, 0)) and g.contains(Point(side * 82.4, 0))   # 0.25 mm off its side wall
    assert g.contains(Point(-side * 82.1, 0))                          # and nothing off the other side
    orig = Bands.slot_pair                                              # left on: they rub X-4's sheet and lock
    monkeypatch.setenv("LAMINA_NO_REUSE", "1")                          # the same job again with other code: its parts are made again
    monkeypatch.setattr(Bands, "slot_pair", staticmethod(lambda ctx, j, out: [t[:4] + (None,) for t in orig(ctx, j, out)]))
    rubbed = build(CUBE, "bands", prm)
    assert set(later_pieces(rubbed)) - set(rubbed["steps"])


def test_a_corner_boxed_in_by_two_bands_is_cut_off_and_glued_in_last():
    # sphere 3×2×2: the lines of X-1 (x = −60) and Y-1 (y = −45) cross inside Z-1's wall, both slots beyond the crossing.
    # The bit of wall between the two slots can slide in neither way; cut off, the rest of Z-1 goes in in two halves
    plan = build(EXAMPLES / "sphere.stl", "bands", {"nx": 3, "ny": 2, "nz": 2})
    assert plan["counts"]["errors"] == 0
    g, z1 = shape(plan, "Z-1")
    corners = [w for w in z1["warnings"] if " is the corner between its slots for " in w]
    assert len(corners) == 4 and len(z1["pieces"]) == 6
    assert any("for X-1 and Y-1" in w for w in corners)
    small = [pc for pc in z1["pieces"] if pc["area"] < 50]                # the four corners, 18 mm² each
    assert len(small) == 4
    steps = plan["steps"]
    assert set(steps) == set(later_pieces(plan))                        # every piece has a step: none locked
    corner = {pc["label"] for s in plan["slices"] for pc in s["pieces"] if pc["area"] < 50}   # Z-2 has its four too
    assert min(steps[lab] for lab in corner) > max(n for lab, n in steps.items() if lab not in corner)   # glued in last
    # both earlier bands keep their slots there: the crossing still holds Z-1
    for lab in ("X-1", "Y-1"):
        assert "Z-1" in shape(plan, lab)[1]["engages"]
    assert not g.contains(Point(-60, -40)) and not g.contains(Point(-55, -45))   # Z-1's slots for X-1 and Y-1


def test_a_band_is_cut_along_a_joint_where_no_cut_fits_between_two():
    # sphere 2×4×4: X-1 (x = −45) and Y-2 (y = −22.5) cross just inside Z-1's hollow; no cut fits between their slots,
    # so Z-1 is cut along X-1's line from the surface to its slot, and the two pieces clamp X-1 between them
    plan = build(EXAMPLES / "sphere.stl", "bands", {"nx": 2, "ny": 4, "nz": 4})
    assert plan["counts"]["errors"] == 0
    g, z1 = shape(plan, "Z-1")
    assert not any(" is the corner " in w for w in z1["warnings"])
    assert not g.contains(Point(-45, -36)) and g.contains(Point(-44, -36)) and g.contains(Point(-46, -36))
    assert set(plan["steps"]) == set(later_pieces(plan))
    assert "Z-1" in shape(plan, "X-1")[1]["engages"]


def test_the_check_catches_a_joint_that_cannot_slide_together(monkeypatch):
    # the old joint, the puzzle tab, forced on every cut of the lattice that passes with tongues (above): a round head
    # goes in only from above the sheet, and a band's piece slides in its own plane — so pieces lock, each is named
    monkeypatch.setattr(Bands, "guide_outlines", lambda self, ctx, slices: self.lattice(ctx, slices, tongue=False))
    plan = build(CUBE, "bands", BASE)
    found = [m for s in plan["slices"] for e in s["errors"] if (m := re.match(r"((\w-\d)-\d) cannot slide in: ((\w-\d)(-\d)?) is in its way", e))]
    assert found and any(m[2] == m[4] for m in found)                   # held by a piece of its own band: the tab
    assert {m[1] for m in found} == set(later_pieces(plan)) - set(plan["steps"])


def test_a_tongue_slides_in_and_a_round_head_does_not():
    # a piece arriving from above, along (0, -1), onto a joint fixed in place, with a socket cut round the joint with
    # the kerf's play. Straight sides let it down; a head wider than its neck catches under the piece
    v = np.array([0.0, -500.0])
    for joint, free in ((tongue(np.array([10.0, 0.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]), 6.0), True),
                        (tab(10.0, 0.0, (1.0, 0.0), 6.0, 7.2, 1), False)):
        piece = box(0, 0, 20, 12).difference(joint.buffer(0.05))
        assert joint.bounds[3] > 5 and piece.area > 150                # the joint reaches well into the piece
        assert (covers(joint, piece, v) <= FREE_AREA) == free, covers(joint, piece, v)
    assert abs(sweep(box(0, 0, 1, 1), np.array([10.0, 0.0])).area - 11.0) < 1e-9


def test_the_order_decides_which_family_stays_whole():
    plan = build(CUBE, "bands", {**BASE, "order": "zxy"})
    assert all(len(s["pieces"]) == 1 for s in plan["slices"] if s["label"].startswith("Z"))
    assert "Z → X → Y" in " ".join(plan["notes"])


def test_without_cuts_a_locked_band_is_an_error():
    plan = build(CUBE, "bands", {**BASE, "z": False, "band_cuts": False})
    errs = [e for s in plan["slices"] for e in s["errors"]]
    assert sum("cannot slide in whole" in e for e in errs) == 3            # the three Y bands
    assert all(len(s["pieces"]) == 1 for s in plan["slices"])


def test_one_family_is_not_a_lattice():
    plan = build(CUBE, "bands", {**BASE, "y": False, "z": False})
    assert plan["counts"]["slices"] == 0 and any("at least two" in e for e in plan["errors"])
    assert any(o["set"] == {"y": True} for f in plan["fixes"] for o in f["options"])


@pytest.mark.parametrize("wall, expect", [(12, 180 ** 2 - 156 ** 2), (30, 180 ** 2 - 120 ** 2)])
def test_a_band_takes_its_own_wall(wall, expect):
    plan = build(CUBE, "bands", {**BASE, "z": False, "wall": {"X-2": wall}})
    g, _ = shape(plan, "X-2")
    slots = 6 * 4 * 6 * (1 if wall == 12 else 0.5)                     # six half-depth slots, give or take
    assert abs(g.area - expect) < slots + 300
