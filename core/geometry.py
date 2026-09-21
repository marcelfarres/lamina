"""Frames, sections and ray casts. Everything 2D is a shapely (Multi)Polygon in a slice's local frame."""
from __future__ import annotations
import functools, math
import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, Point, LineString, MultiLineString
from shapely.ops import unary_union

try:
    import rtree  # noqa: F401 — trimesh's ray broad phase. Decided once: asking trimesh on every cast makes it compute
    HAVE_RTREE = True   # the bounds of every triangle before it finds out (0.15 s a cast on a 280k-face head, never cached)
except ImportError:                                       # the browser build has none
    HAVE_RTREE = False


def frame(origin, normal, up_hint=(0, 0, 1)) -> np.ndarray:
    """4x4 local->world. Local z = normal; local y = up_hint projected onto the plane; local x = y × z."""
    n = np.asarray(normal, float); n = n / np.linalg.norm(n)
    up = np.asarray(up_hint, float)
    if abs(np.dot(up, n)) > 0.999:
        up = np.array([0.0, 1, 0]) if abs(n[1]) < 0.9 else np.array([1.0, 0, 0])
    v = up - np.dot(up, n) * n; v /= np.linalg.norm(v)
    u = np.cross(v, n)
    M = np.eye(4); M[:3, 0] = u; M[:3, 1] = v; M[:3, 2] = n; M[:3, 3] = origin
    return M


def frame_xy(origin, x_axis, y_axis) -> np.ndarray:
    """4x4 from explicit in-plane axes (orthonormalised)."""
    u = np.asarray(x_axis, float); u = u / np.linalg.norm(u)
    v = np.asarray(y_axis, float); v = v - np.dot(v, u) * u; v = v / np.linalg.norm(v)
    M = np.eye(4); M[:3, 0] = u; M[:3, 1] = v; M[:3, 2] = np.cross(u, v); M[:3, 3] = origin
    return M


def rot_about(axis, deg) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(math.radians(deg), axis)[:3, :3]


def to_local(M, pts) -> np.ndarray:
    pts = np.atleast_2d(np.asarray(pts, float))
    p = np.c_[pts, np.ones(len(pts))]
    return (np.linalg.inv(M) @ p.T).T[:, :2]


def to_world(M, pts2d, z=0.0) -> np.ndarray:
    pts2d = np.atleast_2d(np.asarray(pts2d, float))
    p = np.c_[pts2d, np.full(len(pts2d), z), np.ones(len(pts2d))]
    return (M @ p.T).T[:, :3]


def section_polygons(mesh: trimesh.Trimesh, M: np.ndarray) -> MultiPolygon:
    """Cross-section of the mesh on the local z=0 plane of M, as polygons (with holes) in local 2D."""
    sec = mesh.section(plane_origin=M[:3, 3], plane_normal=M[:3, 2])
    if sec is None or len(sec.entities) == 0:
        return MultiPolygon()
    path2d, _ = sec.to_2D(to_2D=np.linalg.inv(M))
    try:
        polys = list(path2d.polygons_full)
    except ImportError:                                   # trimesh sorts loops into holes with rtree; the browser build
        loops = [p for p in path2d.polygons_closed if p is not None and p.area > 1e-6]   # has none: even-odd fill is the same
        polys = [functools.reduce(lambda a, b: a.symmetric_difference(b), loops)] if loops else []
    polys = [p for p in polys if p.is_valid and p.area > 1e-6]
    if not polys:
        return MultiPolygon()
    return as_multi(unary_union([unripple(p, mesh.metadata.get("lamina_pitch", 0)) for p in polys]))


def unripple(geom, pitch: float):
    """Take the grid out of an outline cut from a remeshed model.

    A voxel pass leaves a ripple along every curve about a fifth of the pitch deep — not a staircase (the smoothing
    in `modify_form` takes the corners off) but a bumpy edge, and on a 180 mm model at 1.5 mm voxels that is a
    visible 1.3 mm of wobble on what was a smooth curve. Neither a finer grid nor more smoothing passes reach it: the
    ripple is the grid itself, and the grid is bounded by memory. So it comes off here, where the curve is a line
    rather than a surface — a moving average around the ring over about five voxels of arc, which is longer than the
    ripple and far shorter than any shape the model is meant to have. Measured on the egg at `round 2`: the outline's
    spread about the original fell from 0.285 mm to 0.092 mm, and 1.27 mm of peak-to-trough to 0.42 mm, costing
    0.07 mm of size. Only for meshes the voxel pass built: `pitch` is 0 for a model sliced as it was modelled.

    Takes a single polygon or several: the browser build has no rtree, so it sorts its loops with one
    symmetric_difference and arrives here with a MultiPolygon where the desktop build passes them one at a time.
    """
    if pitch <= 0:
        return geom
    out = []
    for poly in getattr(geom, "geoms", [geom]):
        if not isinstance(poly, Polygon) or poly.is_empty:
            out.append(poly)                            # a stray line or point: not ours to smooth, not ours to drop
            continue
        rings = [_ring_average(np.asarray(poly.exterior.coords), pitch)]
        rings += [_ring_average(np.asarray(r.coords), pitch) for r in poly.interiors]
        smooth = Polygon(rings[0], rings[1:]).buffer(0)
        out.append(smooth if smooth.is_valid and not smooth.is_empty else poly)
    return unary_union(out) if len(out) != 1 else out[0]


def _ring_average(ring: np.ndarray, pitch: float) -> np.ndarray:
    """Moving average around a closed ring, over `5 · pitch` of arc. A ring too short to hold the window is left as
    it is — a part a few voxels across is all corner, and averaging it away would cost the part its shape."""
    c = np.asarray(ring)[:-1]
    seg = float(np.median(np.hypot(*np.diff(np.vstack([c, c[:1]]), axis=0).T))) if len(c) > 2 else 0.0
    window = int(round(5 * pitch / seg)) if seg > 0 else 0
    window += window % 2 == 0                                  # odd, so the average stays centred on its point
    if window < 3 or len(c) < 3 * window:
        return ring
    k = np.ones(window) / window
    pad = np.concatenate([c[-window:], c, c[:window]])
    sm = np.stack([np.convolve(pad[:, i], k, mode="same")[window:window + len(c)] for i in (0, 1)], axis=1)
    return np.vstack([sm, sm[:1]])


def as_multi(g) -> MultiPolygon:
    if g is None or g.is_empty:
        return MultiPolygon()
    if isinstance(g, Polygon):
        return MultiPolygon([g])
    if isinstance(g, MultiPolygon):
        return g
    return MultiPolygon([p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)])


def as_lines(g) -> MultiLineString:
    if g is None or g.is_empty:
        return MultiLineString()
    if isinstance(g, LineString):
        return MultiLineString([g])
    if isinstance(g, MultiLineString):
        return g
    return MultiLineString([l for l in getattr(g, "geoms", []) if isinstance(l, LineString)])


def line_segments_in_mesh(mesh, p0, d, span) -> list[tuple[float, float]]:
    """Inside-segments (s_in, s_out) of the line p0 + s*d against the mesh."""
    d = np.asarray(d, float); d = d / np.linalg.norm(d)
    origin = np.asarray(p0, float) - d * span
    if HAVE_RTREE:
        locs, _, _ = mesh.ray.intersects_location([origin], [d], multiple_hits=True)   # rtree broad phase, cached on the mesh
    else:                                                 # the browser build: a broad phase of our own — only the triangles
        from types import SimpleNamespace                 # whose bounding sphere the line passes through are tested
        from trimesh.ray.ray_triangle import ray_triangle_id
        cache = mesh.metadata.setdefault("lamina_spheres", {})
        if "c" not in cache:                              # once per mesh
            tri = mesh.triangles; c = tri.mean(1)
            cache.update(c=c, r2=(np.linalg.norm(tri - c[:, None], axis=2).max(1) + 1e-6) ** 2)
        v = cache["c"] - origin; t = v @ d
        near = np.flatnonzero(np.einsum("ij,ij->i", v, v) - t * t <= cache["r2"])   # squared distance to the line
        tree = SimpleNamespace(bounds=mesh.bounds, intersection=lambda b: near)
        _, _, locs = ray_triangle_id(mesh.triangles, [origin], [d], triangles_normal=mesh.face_normals, tree=tree, multiple_hits=True)
    if len(locs) == 0:
        return []
    s = np.sort((locs - p0) @ d)
    s = s[np.r_[True, np.diff(s) > 1e-6]]
    if len(s) % 2:
        s = s[:-1]
    return [(float(s[i]), float(s[i + 1])) for i in range(0, len(s), 2) if s[i + 1] - s[i] > 0.3]


def plane_plane_line(Ma, Mb):
    """Intersection line (p0, d) of the z=0 planes of frames Ma, Mb; None if parallel."""
    na, nb = Ma[:3, 2], Mb[:3, 2]
    d = np.cross(na, nb)
    if np.linalg.norm(d) < 1e-6:
        return None
    d = d / np.linalg.norm(d)
    A = np.vstack([na, nb, d]); b = np.array([na @ Ma[:3, 3], nb @ Mb[:3, 3], 0.0])
    return np.linalg.solve(A, b), d


def rect_along(a, b, width) -> Polygon:
    """Rectangle of `width` centred on the segment a->b (2D)."""
    return LineString([a, b]).buffer(width / 2, cap_style=2)


def circle(c, d) -> Polygon:
    return Point(c).buffer(d / 2, quad_segs=24)


def dowel(c, d, shape="round") -> Polygon:
    """Dowel hole of size d at c. Shapes follow Slicer: round, square, pencil (hexagon), cross, hslot, vslot."""
    x, y = c; r = d / 2
    if shape == "square":
        return Polygon([(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r)])
    if shape == "pencil":
        return Polygon([(x + r * math.cos(a), y + r * math.sin(a)) for a in np.arange(6) * math.pi / 3])
    if shape == "cross":
        w = d / 3
        return unary_union([rect_along((x - r, y), (x + r, y), w), rect_along((x, y - r), (x, y + r), w)])
    if shape == "hslot":
        return LineString([(x - r, y), (x + r, y)]).buffer(r / 2)
    if shape == "vslot":
        return LineString([(x, y - r), (x, y + r)]).buffer(r / 2)
    return circle(c, d)


def poly_coords(mp: MultiPolygon) -> list:
    """[[exterior, hole, hole...], ...] as plain lists for JSON (bulk coordinate extraction: panels have 100s of holes)."""
    import shapely
    out = []
    for p in mp.geoms:
        rings = shapely.get_rings(p)
        coords = np.round(shapely.get_coordinates(rings), 4)
        parts = np.split(coords, np.cumsum(shapely.get_num_coordinates(rings))[:-1])
        out.append([r[:-1].tolist() for r in parts])
    return out


def line_coords(ml) -> list:
    return [list(map(list, np.round(np.asarray(l.coords), 4))) for l in as_lines(ml).geoms]
