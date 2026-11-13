"""Closed outlines from an SVG or DXF file given as text: the outline of a plate."""
from __future__ import annotations
import io, math, re
import numpy as np
import shapely
from lxml import etree
from shapely.geometry import Polygon, LineString
from shapely.ops import polygonize, unary_union

PX_MM = 25.4 / 96
UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": PX_MM}
DXF_UNIT_MM = {1: 25.4, 4: 1.0, 5: 10.0, 6: 1000.0}     # $INSUNITS; 0 and the rest read as mm
SAMPLES = 24                                              # points per curve segment: about 0.1 mm for a 20 mm radius
SKIP = {"defs", "clipPath", "mask", "symbol", "pattern"}
ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
NUMBER = re.compile(r"\s*([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)\s*([a-z%]*)")


def outlines(text: str) -> tuple[Polygon, list[str]]:
    """The plate drawn in an SVG or DXF file: its largest closed outline, with the closed outlines inside it as holes,
    in millimetres, y up; and notes (plain sentences) about what was ignored. Raises ValueError with a plain message
    when the text is neither format or holds no closed outline."""
    notes: list[str] = []
    root = _xml_root(text)
    rings = _svg_rings(root, notes) if root is not None else _dxf_rings(text, notes)
    return _plate(rings, notes), notes


def _xml_root(text):
    try:
        root = etree.fromstring(text.encode("utf-8"))
    except etree.XMLSyntaxError:
        return None
    return root if isinstance(root.tag, str) and etree.QName(root).localname == "svg" else None


# --- SVG ---------------------------------------------------------------------------------------------------------

def _num(s, default=0.0):
    m = NUMBER.match(s) if s else None
    return float(m.group(1)) if m else default


def _transform(s) -> np.ndarray:
    """3x3 matrix of an SVG transform list (chained left to right)."""
    M = np.eye(3)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        a = [float(x) for x in TOKEN.findall(args)]
        T = np.eye(3)
        if name == "matrix" and len(a) == 6:
            T = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate":
            T[:2, 2] = (a[0], a[1] if len(a) > 1 else 0)
        elif name == "scale":
            T[0, 0], T[1, 1] = a[0], a[1] if len(a) > 1 else a[0]
        elif name == "rotate":
            c, s_ = math.cos(math.radians(a[0])), math.sin(math.radians(a[0]))
            T = np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]])
            if len(a) == 3:
                T = _transform(f"translate({a[1]} {a[2]})") @ T @ _transform(f"translate({-a[1]} {-a[2]})")
        elif name == "skewX":
            T[0, 1] = math.tan(math.radians(a[0]))
        elif name == "skewY":
            T[1, 0] = math.tan(math.radians(a[0]))
        M = M @ T
    return M


def _arc(p0, rx, ry, phi, large, sweep, p1):
    """Points along an SVG elliptical arc from p0 to p1 (spec F.6.5: endpoint to centre parameters)."""
    if p0 == p1 or rx == 0 or ry == 0:
        return [p1]
    rx, ry, phi = abs(rx), abs(ry), math.radians(phi)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    k = x1 ** 2 / rx ** 2 + y1 ** 2 / ry ** 2
    if k > 1:                                              # radii too small: grow them to just reach p1
        rx, ry = rx * math.sqrt(k), ry * math.sqrt(k)
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1 ** 2 - ry ** 2 * x1 ** 2
    den = rx ** 2 * y1 ** 2 + ry ** 2 * x1 ** 2
    co = math.sqrt(max(0.0, num / den)) * (-1 if bool(large) == bool(sweep) else 1)
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2
    cy = s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2
    a0 = math.atan2((y1 - cy1) / ry, (x1 - cx1) / rx)
    da = math.atan2((-y1 - cy1) / ry, (-x1 - cx1) / rx) - a0
    if sweep and da < 0:
        da += 2 * math.pi
    elif not sweep and da > 0:
        da -= 2 * math.pi
    a = a0 + da * np.linspace(0, 1, SAMPLES + 1)[1:]
    pts = [(cx + rx * math.cos(t) * c - ry * math.sin(t) * s, cy + rx * math.cos(t) * s + ry * math.sin(t) * c) for t in a]
    pts[-1] = p1
    return pts


def _bezier(*P):
    t = np.linspace(0, 1, SAMPLES + 1)[1:, None]
    P = [np.asarray(p, float) for p in P]
    n = len(P) - 1
    pts = sum(math.comb(n, k) * (1 - t) ** (n - k) * t ** k * p for k, p in enumerate(P))
    return [tuple(p) for p in pts]


def _path(d) -> list[tuple[list, bool]]:
    """Subpaths of a path's `d` as (points, closed), in user units."""
    out, pts, cur, start = [], [], (0.0, 0.0), (0.0, 0.0)
    ctrl, prev = None, ""                                  # last control point, for S and T reflections
    toks, i, cmd = TOKEN.findall(d or ""), 0, ""
    while i < len(toks):
        if toks[i].isalpha():
            cmd, i = toks[i], i + 1
        elif not cmd:
            break
        up, rel = cmd.upper(), cmd.islower()
        if up == "Z":
            if pts:
                out.append((pts, True))
            pts, cur, ctrl, prev = [], start, None, "Z"
            continue
        n = ARGS.get(up)
        if n is None or i + n > len(toks) or any(t.isalpha() for t in toks[i:i + n]):
            break
        a, i = [float(x) for x in toks[i:i + n]], i + n
        ox, oy = cur if rel else (0.0, 0.0)
        if up == "M":
            if pts:
                out.append((pts, False))
            cur = start = (a[0] + ox, a[1] + oy)
            pts, cmd, ctrl = [cur], ("l" if rel else "L"), None
        else:
            if not pts:                                    # drawing after Z starts a new subpath at its start
                pts = [cur]
            if up == "L":
                new = [(a[0] + ox, a[1] + oy)]
            elif up == "H":
                new = [(a[0] + ox, cur[1])]
            elif up == "V":
                new = [(cur[0], a[0] + oy)]
            elif up == "C":
                c1, c2, e = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy), (a[4] + ox, a[5] + oy)
                new, ctrl = _bezier(cur, c1, c2, e), c2
            elif up == "S":
                c1 = (2 * cur[0] - ctrl[0], 2 * cur[1] - ctrl[1]) if ctrl and prev in "CS" else cur
                c2, e = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy)
                new, ctrl = _bezier(cur, c1, c2, e), c2
            elif up == "Q":
                c1, e = (a[0] + ox, a[1] + oy), (a[2] + ox, a[3] + oy)
                new, ctrl = _bezier(cur, c1, e), c1
            elif up == "T":
                c1 = (2 * cur[0] - ctrl[0], 2 * cur[1] - ctrl[1]) if ctrl and prev in "QT" else cur
                e = (a[0] + ox, a[1] + oy)
                new, ctrl = _bezier(cur, c1, e), c1
            else:                                          # A
                new = _arc(cur, a[0], a[1], a[2], a[3], a[4], (a[5] + ox, a[6] + oy))
            pts += new
            cur = pts[-1]
            if up not in "CSQT":
                ctrl = None
        prev = up
    if pts:
        out.append((pts, False))
    return out


def _shape_path(el, tag) -> str | None:
    """A basic shape as path data, or None when it is not a path-like shape."""
    g = lambda k, default=0.0: _num(el.get(k), default)
    if tag == "rect":
        x, y, w, h = g("x"), g("y"), g("width"), g("height")
        rx, ry = el.get("rx"), el.get("ry")
        rx, ry = (_num(rx) if rx else None), (_num(ry) if ry else None)
        rx, ry = (rx if rx is not None else ry or 0), (ry if ry is not None else rx or 0)
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx <= 0 or ry <= 0:
            return f"M{x} {y}h{w}v{h}h{-w}Z"
        return (f"M{x + rx} {y}h{w - 2 * rx}a{rx} {ry} 0 0 1 {rx} {ry}v{h - 2 * ry}a{rx} {ry} 0 0 1 {-rx} {ry}"
                f"h{-(w - 2 * rx)}a{rx} {ry} 0 0 1 {-rx} {-ry}v{-(h - 2 * ry)}a{rx} {ry} 0 0 1 {rx} {-ry}Z")
    if tag in ("circle", "ellipse"):
        rx = g("r") if tag == "circle" else g("rx")
        ry = rx if tag == "circle" else g("ry")
        cx, cy = g("cx"), g("cy")
        return f"M{cx - rx} {cy}a{rx} {ry} 0 1 0 {2 * rx} 0a{rx} {ry} 0 1 0 {-2 * rx} 0Z"
    return None


def _svg_rings(root, notes):
    """Closed rings (arrays of mm points, y up) of every drawable shape in an SVG, under its transforms."""
    unit_mm = PX_MM
    w, vb = root.get("width", ""), re.findall(r"[-+.\w]+", root.get("viewBox", ""))
    m = NUMBER.match(w)
    if m and m.group(2) in UNIT_MM and len(vb) == 4 and float(vb[2]) > 0:
        unit_mm = float(m.group(1)) * UNIT_MM[m.group(2)] / float(vb[2])
    base = np.diag([unit_mm, -unit_mm, 1.0])               # user units to mm, y flipped
    rings, seen = [], {"open": 0, "text": 0, "image": 0}

    def walk(el, M):
        if not isinstance(el.tag, str):
            return
        tag = etree.QName(el).localname
        if tag in SKIP:
            return
        M = M @ _transform(el.get("transform"))
        if tag in ("text", "image"):
            seen[tag] += 1
            return
        if tag in ("path", "rect", "circle", "ellipse"):
            subs = _path(el.get("d") if tag == "path" else _shape_path(el, tag))
        elif tag in ("polygon", "polyline", "line"):
            if tag == "line":
                subs = [([], False)]
            else:
                v = [float(x) for x in TOKEN.findall(el.get("points", ""))]
                p = list(zip(v[0::2], v[1::2]))
                subs = [(p, tag == "polygon" or (len(p) > 2 and p[0] == p[-1]))]
        else:
            subs = []
            for child in el:
                walk(child, M)
        for pts, closed in subs:
            if closed and len(pts) >= 3:
                rings.append((M @ np.c_[pts, np.ones(len(pts))].T).T[:, :2])
            else:
                seen["open"] += 1
    walk(root, base)
    _note_ignored(notes, **seen)
    return rings


# --- DXF ---------------------------------------------------------------------------------------------------------

def _dxf_rings(text, notes):
    import ezdxf
    from ezdxf import path as dxfpath
    try:
        doc = ezdxf.read(io.StringIO(text))
    except Exception:
        raise ValueError("not an SVG or DXF file") from None
    k = DXF_UNIT_MM.get(doc.units, 1.0)
    rings, open_lines, seen = [], [], {"open": 0, "text": 0, "image": 0}
    for e in doc.modelspace():
        kind = e.dxftype()
        if kind in ("TEXT", "MTEXT"):
            seen["text"] += 1
        elif kind == "IMAGE":
            seen["image"] += 1
        elif kind in ("LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE", "SPLINE", "ARC", "LINE"):
            p = dxfpath.make_path(e)
            pts = np.array([(v.x, v.y) for v in p.flattening(0.1)]) * k
            if len(pts) < 2:
                continue
            if p.is_closed and len(pts) >= 4:
                rings.append(pts)
            else:
                open_lines.append(pts)
    if open_lines:
        # ponytail: endpoints snapped by rounding to 0.01 mm, a pair straddling a rounding edge stays open
        lines = [LineString(np.round(p, 2)) for p in open_lines if len(np.round(p, 2)) > 1]
        joined = [np.asarray(g.exterior.coords) for g in polygonize(unary_union(lines))]
        rings += joined
        seen["open"] = 0 if joined else len(open_lines)
    _note_ignored(notes, **seen)
    return rings


def _note_ignored(notes, open, text, image):
    if open:
        notes.append(f"{open} open line(s) ignored: only closed outlines are used")
    if text:
        notes.append("text ignored")
    if image:
        notes.append(f"{image} image ignored")


# --- rings to the plate ------------------------------------------------------------------------------------------

def _plate(rings, notes) -> Polygon:
    polys = []
    for r in rings:
        p = Polygon(r)
        if not p.is_valid:                                 # self-intersecting: keep its largest piece
            p = max((g for g in getattr(shapely.make_valid(p), "geoms", [shapely.make_valid(p)])
                     if g.geom_type == "Polygon"), key=lambda g: g.area, default=Polygon())
        if p.area >= 1e-6:
            polys.append(p)
    if not polys:
        raise ValueError("no closed outline in the file: the plate needs one closed shape")
    polys.sort(key=lambda p: -p.area)
    plate, holes, nested, outside = polys[0], [], 0, 0
    for p in polys[1:]:
        if not plate.contains(p):
            outside += 1
        elif any(h.contains(p) for h in holes):            # even-odd, one level deep: an island in a hole is dropped
            nested += 1
        else:
            holes.append(p)
    if outside:
        notes.append(f"{outside} closed outline(s) outside the plate ignored")
    if nested:
        notes.append(f"{nested} closed outline(s) inside a hole ignored")
    return Polygon(plate.exterior, [h.exterior for h in holes])
