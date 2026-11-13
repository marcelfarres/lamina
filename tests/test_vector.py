"""core.vector: closed outlines from SVG and DXF text."""
import io, math
import ezdxf
import pytest
from core.vector import outlines

MM = 25.4 / 96


def svg(body, head='width="100mm" height="100mm" viewBox="0 0 100 100"'):
    return f'<svg xmlns="http://www.w3.org/2000/svg" {head}>{body}</svg>'


def dxf(draw, units=4):
    doc = ezdxf.new()
    doc.units = units
    draw(doc.modelspace())
    out = io.StringIO()
    doc.write(out)
    return out.getvalue()


def test_rect_with_circle_hole():
    p, notes = outlines(svg('<rect x="10" y="10" width="60" height="40"/><circle cx="40" cy="30" r="8"/>'))
    assert p.bounds == pytest.approx((10, -50, 70, -10))
    assert len(p.interiors) == 1
    assert p.area == pytest.approx(60 * 40 - math.pi * 64, rel=0.01)
    assert notes == []


def test_path_relative_commands_and_cubic():
    # a 20 x 10 box whose right edge bulges out by a cubic: M, l, c, h, v-less closing with z
    p, _ = outlines(svg('<path d="m 10,10 l 20,0 c 5,0 5,10 0,10 h -20 z"/>'))
    minx, miny, maxx, maxy = p.bounds
    assert (minx, maxx) == pytest.approx((10, 33.75))        # the curve's extreme x is 30 + 0.75 * 5
    assert (miny, maxy) == pytest.approx((-20, -10))
    assert p.area == pytest.approx(230, rel=0.01)                # 200 plus the bulge, 150 * 6 * integral of t^2 (1-t)^2 = 30


def test_two_arcs_make_a_circle():
    p, _ = outlines(svg('<path d="M 30 50 A 20 20 0 1 1 70 50 A 20 20 0 1 1 30 50 Z"/>'))
    assert p.area == pytest.approx(math.pi * 400, rel=0.01)
    assert p.bounds == pytest.approx((30, -70, 70, -30), abs=0.1)


def test_number_formats_and_implicit_lineto():
    p, _ = outlines(svg('<path d="M1e1 10 L 30 1e1 30 30 10 30z"/>'))
    assert p.area == pytest.approx(400)
    p, _ = outlines(svg('<path d="M10 10 H30 V-.5e1 H10 Z"/>'))   # "-.5e1" is -5
    assert p.area == pytest.approx(20 * 15)


def test_nested_group_transforms():
    body = '<g transform="translate(10 0)"><g transform="scale(2) rotate(90)"><rect width="5" height="3"/></g></g>'
    p, _ = outlines(svg(body))
    # rect 5x3 rotated 90 deg -> x in [-3, 0], y in [0, 5]; scaled 2 -> x [-6, 0], y [0, 10]; moved +10 in x; y flipped
    assert p.bounds == pytest.approx((4, -10, 10, 0))
    assert p.area == pytest.approx(60)


def test_rotate_about_centre():
    p, _ = outlines(svg('<rect x="0" y="0" width="10" height="10" transform="rotate(90 5 5)"/>'))
    assert p.bounds == pytest.approx((0, -10, 10, 0))


def test_y_is_up():
    top, _ = outlines(svg('<rect x="0" y="5" width="10" height="10"/>'))
    low, _ = outlines(svg('<rect x="0" y="80" width="10" height="10"/>'))
    assert top.bounds[1] > low.bounds[1]


def test_px_without_units():
    p, _ = outlines('<svg xmlns="http://www.w3.org/2000/svg"><rect width="96" height="48"/></svg>')
    assert p.bounds == pytest.approx((0, -48 * MM, 96 * MM, 0))


def test_viewbox_scales_to_width():
    p, _ = outlines('<svg xmlns="http://www.w3.org/2000/svg" width="2in" viewBox="0 0 10 10"><rect width="10" height="5"/></svg>')
    assert p.bounds[2] == pytest.approx(50.8)


def test_skips_defs_and_notes_ignored_things():
    body = ('<defs><rect width="90" height="90"/></defs><rect width="20" height="20"/><text>hi</text>'
            '<line x1="0" y1="0" x2="5" y2="5"/><polyline points="0,0 5,5 9,0"/><image href="x.png"/>'
            '<rect x="50" y="50" width="5" height="5"/>')
    p, notes = outlines(svg(body))
    assert p.area == pytest.approx(400)
    assert "text ignored" in notes
    assert "2 open line(s) ignored: only closed outlines are used" in notes
    assert "1 image ignored" in notes
    assert "1 closed outline(s) outside the plate ignored" in notes


def test_island_in_hole_is_ignored():
    p, notes = outlines(svg('<rect width="90" height="90"/><rect x="10" y="10" width="70" height="70"/>'
                            '<rect x="30" y="30" width="10" height="10"/>'))
    assert len(p.interiors) == 1
    assert p.area == pytest.approx(90 * 90 - 70 * 70)
    assert "1 closed outline(s) inside a hole ignored" in notes


def test_dxf_polyline_and_circle():
    text = dxf(lambda m: (m.add_lwpolyline([(0, 0), (50, 0), (50, 50), (0, 50)], close=True),
                         m.add_circle((25, 25), 10), m.add_text("hello")))
    p, notes = outlines(text)
    assert p.bounds == pytest.approx((0, 0, 50, 50))
    assert len(p.interiors) == 1
    assert p.area == pytest.approx(2500 - math.pi * 100, rel=0.01)
    assert "text ignored" in notes


def test_dxf_square_of_four_lines():
    def draw(m):
        pts = [(0, 0), (40, 0), (40, 30), (0, 30)]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            m.add_line(a, b)
    p, _ = outlines(dxf(draw))
    assert p.area == pytest.approx(1200)
    assert p.bounds == pytest.approx((0, 0, 40, 30))


def test_dxf_inches():
    p, _ = outlines(dxf(lambda m: m.add_lwpolyline([(0, 0), (2, 0), (2, 1), (0, 1)], close=True), units=1))
    assert p.bounds == pytest.approx((0, 0, 50.8, 25.4))


def test_open_line_only():
    with pytest.raises(ValueError, match="no closed outline"):
        outlines(svg('<line x1="0" y1="0" x2="5" y2="5"/>'))
    with pytest.raises(ValueError, match="no closed outline"):
        outlines(dxf(lambda m: m.add_line((0, 0), (5, 5))))


def test_garbage():
    with pytest.raises(ValueError, match="not an SVG or DXF file"):
        outlines("this is not a drawing")
    with pytest.raises(ValueError, match="not an SVG or DXF file"):
        outlines("<html><body/></html>")
