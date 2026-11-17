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


# The sphere and the head at their defaults have pieces that cannot get in, so these two are a finding, held strict:
# the sphere's three bands cross close to one point at Z-2's corners, where its two slots overlap and no cut can part
# them; the head has cuts that find no clean place between their joints (slots too close together).
@pytest.mark.parametrize("model, prm", [
    ("cube.stl", {}),
    pytest.param("sphere.stl", {"nx": 3, "ny": 3, "nz": 3}, marks=pytest.mark.xfail(strict=True, reason="Z-2's corners lock pieces")),
    pytest.param("head_igea.stl", {}, marks=pytest.mark.xfail(strict=True, reason="cuts with no clean place lock pieces")),
])
def test_every_piece_slides_in_past_the_ones_already_there(model, prm):
    plan = build(EXAMPLES / model, "bands", prm)
    later = later_pieces(plan)
    locked = set(later) - set(plan["steps"])
    for lab in locked:                                                  # a piece that cannot get in is its band's error
        assert any(e.startswith(f"{lab} cannot slide in: ") for e in later[lab]["errors"])
    assert not any(e.startswith(f"{lab} cannot") for s in plan["slices"] for e in s["errors"] for lab in plan["steps"])
    assert not locked, sorted(locked)


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
