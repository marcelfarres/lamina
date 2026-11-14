"""The plaque's back plate: its outline, fitted round the model, the model's own shadow, or drawn in a file."""
import math

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point, Polygon, box

from .geometry import as_multi, to_local
from .vector import outlines

SHAPES = ["circle", "ellipse", "rectangle", "rounded", "hexagon", "shield", "silhouette", "file"]
SHIELD = [(-.5, .40), (-.42, .43), (-.30, .40), (-.12, .47), (0, .50), (.12, .47), (.30, .40), (.42, .43), (.5, .40),
          (.5, -.12), (.40, -.30), (.22, -.42), (0, -.50), (-.22, -.42), (-.40, -.30), (-.5, -.12)]
SHIELD_GROWTH = 1.25     # its lower half tapers, so the shield is drawn a quarter bigger than the box
SHIELD_ROUNDING = 5.0    # mm: its tips are rounded, a sharp one is a thin spot
ROUNDED_RADIUS = 0.12    # the rounded rectangle's corner radius, as a share of its shorter side


def outline(kind, pts, margin):
    """The plate's outline round the model's footprint `pts` (plate x, y), `margin` clear of it all round."""
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; w, h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin
    r = float(np.hypot(*(pts - (cx, cy)).T).max()) + margin
    if kind == "circle":
        return Point(cx, cy).buffer(r, 64)
    if kind == "ellipse":                        # the ellipse through the corners of the footprint's box, plus the margin
        return affinity.scale(Point(cx, cy).buffer(1, 64), (x1 - x0) / math.sqrt(2) + margin, (y1 - y0) / math.sqrt(2) + margin)
    if kind == "hexagon":
        R = r / math.cos(math.pi / 6)
        return Polygon([(cx + R * math.cos(a), cy + R * math.sin(a)) for a in np.arange(6) * math.pi / 3])
    if kind == "shield":
        return Polygon([(cx + x * w * SHIELD_GROWTH, cy + y * h * SHIELD_GROWTH) for x, y in SHIELD]).buffer(-SHIELD_ROUNDING).buffer(SHIELD_ROUNDING, 16)
    rect = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return rect.buffer(-ROUNDED_RADIUS * min(w, h)).buffer(ROUNDED_RADIUS * min(w, h), 16) if kind == "rounded" else rect


def silhouette(mesh, Mp, margin):
    """The shadow of `mesh` on the plate, grown by `margin`, its holes filled."""
    front = mesh.face_normals @ Mp[:3, 2] > 0                # every point of the shadow lies under a face that looks forward
    tris = to_local(Mp, mesh.vertices)[mesh.faces[front]]
    polys = shapely.polygons(tris)
    shadow = shapely.union_all(shapely.buffer(polys[shapely.area(polys) > 1e-9], 0.01)).buffer(margin, 16)
    whole = max(as_multi(shadow).geoms, key=lambda g: g.area)
    return Polygon(whole.exterior).simplify(0.05, preserve_topology=False)


def from_file(text, foot, margin):
    """The outline drawn in an SVG or DXF file, fitted round the model's footprint `foot`: the drawing's box covers the
    model's and the margin, its proportions kept. Returns the shape and what the reader said about the file."""
    if not text:
        raise ValueError("no file chosen: pick an SVG or DXF file, or another plate shape")
    shape, said = outlines(text)
    (fx0, fy0), (fx1, fy1) = foot.min(0), foot.max(0); x0, y0, x1, y1 = shape.bounds
    f = max((fx1 - fx0 + 2 * margin) / (x1 - x0), (fy1 - fy0 + 2 * margin) / (y1 - y0))
    return affinity.scale(affinity.translate(shape, (fx0 + fx1 - x0 - x1) / 2, (fy0 + fy1 - y0 - y1) / 2), f, f, origin=((fx0 + fx1) / 2, (fy0 + fy1) / 2)), said


def placed(shape, p):
    """The plate's outline sized, turned and moved as asked."""
    x0, y0, x1, y1 = shape.bounds; w, h = p["plate_size"]
    if w or h:
        fx = w / (x1 - x0) if w else h / (y1 - y0); fy = h / (y1 - y0) if h else fx
        shape = affinity.scale(shape, fx, fy)
    k = p["plate_scale"] / 100
    if k != 1 or p["plate_mirror"]:
        shape = affinity.scale(shape, -k if p["plate_mirror"] else k, k)
    if p["plate_rotation"]:
        shape = affinity.rotate(shape, p["plate_rotation"])
    return affinity.translate(shape, *p["plate_offset"])


def plate_shape(p, foot, covered_mesh, Mp):
    """The plate's outline as the settings `p` ask for it, round the model's footprint `foot` (plate x, y) or its shadow
    (`covered_mesh`, seen from the plate's frame `Mp`), and what to say about it (a text for the plan's notes, or "").
    Raises ValueError for a plate file that cannot be read."""
    said = ""
    if p["plate"] == "file":
        shape, parts = from_file(p["plate_file"], foot, p["plate_margin"])
        said = "plate file: " + ", ".join(parts) if parts else ""
    elif p["plate"] == "silhouette":
        shape = silhouette(covered_mesh, Mp, p["plate_margin"])
    else:
        shape = outline(p["plate"], foot, p["plate_margin"])
    return placed(shape, p), said
