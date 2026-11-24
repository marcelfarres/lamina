"""The kerf test (core.calibrate), measured on the files it writes: each pair's square and hole sizes in the DXF, the
values engraved in the SVG, the range that follows the job's kerf."""
import pathlib

import ezdxf
from lxml import etree
from shapely.geometry import Polygon

from core.calibrate import S, kerf_test, kerf_values
from core.export import design_name
from core.plan import build

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"


def _plan(**extra):
    plan = build(EXAMPLES / "cube.stl", "stacked", {"distribution": "count", "count": 3, "autofix": "off"})
    plan["params"].update(extra)
    return plan


def _sizes(dxf, layer, f=1.0):
    return sorted(round((Polygon([(x * f, y * f) for x, y, *_ in e.get_points()]).bounds[2]
                         - Polygon([(x * f, y * f) for x, y, *_ in e.get_points()]).bounds[0]), 4)
                  for e in dxf.modelspace().query("LWPOLYLINE") if e.dxf.layer == layer)


def test_each_pair_is_drawn_for_its_own_kerf_so_the_true_kerf_comes_out_snug(tmp_path):
    plan = _plan(kerf=0.15)
    ks = kerf_values(plan["params"])
    assert ks == [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
    files = kerf_test(plan, tmp_path, ("svg", "dxf", "pdf"))
    name = design_name(plan)
    assert {f.name for f in files} == {f"{name} kerf-test.svg", f"{name} kerf-test.dxf", f"{name} kerf-test.pdf", "README.txt"}
    dxf = ezdxf.readfile(tmp_path / f"{name} kerf-test.dxf")
    squares = _sizes(dxf, "OUTER")[:7]                                 # the plate is the eighth, and the largest
    holes = _sizes(dxf, "INNER")
    assert squares == [round(S + k, 4) for k in ks]                    # grown by half the kerf on each side
    assert holes == sorted(round(S - k, 4) for k in ks)                # shrunk by the same
    svg = etree.parse(str(tmp_path / f"{name} kerf-test.svg"))
    texts = [t for t in svg.xpath("//@data-text")]
    for k in ks:
        assert texts.count(f"{k:.3g}") == 2                            # on the square and under its hole


def test_the_range_follows_the_machine_and_never_goes_below_zero():
    assert kerf_values({"kerf": 0}) == [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]       # none set: a CO2 laser's 0.15 in the middle
    assert kerf_values({"kerf": 0.2}) == [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35]
    assert kerf_values({"kerf": 1.5}) == [0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25]     # a plasma: quarter millimetres
    assert kerf_values({"kerf": 0.05})[0] == 0.0


def test_inches_write_the_values_in_inches(tmp_path):
    plan = _plan(kerf=0.2, units="in")
    kerf_test(plan, tmp_path, ("svg", "dxf"))
    name = design_name(plan)
    texts = etree.parse(str(tmp_path / f"{name} kerf-test.svg")).xpath("//@data-text")
    assert f"{0.2 / 25.4:.3g}" in texts and any("(in)" in t for t in texts)
    dxf = ezdxf.readfile(tmp_path / f"{name} kerf-test.dxf")
    assert _sizes(dxf, "OUTER", 25.4)[3] == round(S + 0.2, 4)        # the DXF is in inches, the square still 20.2 mm
