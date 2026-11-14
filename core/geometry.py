"""Frames, sections and ray casts. Everything 2D is a shapely (Multi)Polygon in a slice's local frame."""
from __future__ import annotations
import functools, math
import numpy as np
import shapely
from shapely.errors import GEOSException
import shapely.affinity
import trimesh
from shapely.geometry import Polygon, MultiPolygon, Point, LineString, MultiLineString, box
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


def to_local(M, pts, z=False) -> np.ndarray:
    """World points in M's frame: x, y on the slice (and its z, with `z`)."""
    pts = np.atleast_2d(np.asarray(pts, float))
    p = np.c_[pts, np.ones(len(pts))]
    return (np.linalg.inv(M) @ p.T).T[:, :3 if z else 2]


def to_world(M, pts2d, z=0.0) -> np.ndarray:
    pts2d = np.atleast_2d(np.asarray(pts2d, float))
    p = np.c_[pts2d, np.full(len(pts2d), z), np.ones(len(pts2d))]
    return (M @ p.T).T[:, :3]


def into(a_M, b_M, geom):
    """Geometry in b's local plane → a's local plane (both z = 0; exact for parallel frames, close enough for small tilts)."""
    T = np.linalg.inv(a_M) @ b_M
    return shapely.affinity.affine_transform(geom, [T[0, 0], T[0, 1], T[1, 0], T[1, 1], T[0, 3], T[1, 3]])


def min_dims(poly):
    """Side lengths of the minimum rotated bounding rectangle (w, h), sorted: the hull measured across each of its own
    edge directions, keeping the smallest box. Not GEOS's minimum_rotated_rectangle, which comes back as a flat line
    when the hull has several points on one straight edge (slot corners on a slanted side do that) — a 120 × 660 mm
    part measured 0.0 × 125, failed as "too thin" and was never split to fit the sheet."""
    hull = poly.convex_hull
    if hull.geom_type != "Polygon":                        # a point or a line: no width
        return 0.0, float(hull.length)
    h = np.asarray(hull.exterior.coords)
    e = np.diff(h, axis=0); e = e[np.hypot(*e.T) > 1e-12]; e /= np.hypot(*e.T)[:, None]
    w, t = np.ptp(h @ e.T, axis=0), np.ptp(h @ np.c_[-e[:, 1], e[:, 0]].T, axis=0)
    k = int(np.argmin(w * t))
    return tuple(sorted((float(w[k]), float(t[k]))))


def min_rect_angle(geom):
    """The turn (degrees) that lays the long side of GEOS's minimum rotated rectangle along x: a starting angle for
    nesting and for a label along a part. Where that rectangle degenerates to a line (see min_dims) 0 is as good a
    start as any, so this does not go through min_dims."""
    r = geom.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return 0.0
    c = np.asarray(r.exterior.coords); e = c[1:] - c[:-1]
    i = int(np.argmax(np.hypot(e[:, 0], e[:, 1])))
    return -math.degrees(math.atan2(e[i, 1], e[i, 0]))


def even_odd(polys):
    """Rings sorted into faces and holes the even-odd way: a ring inside a ring is a hole, one inside that a face
    again — the symmetric difference of them all (a glyph's counters, a section's loops where there is no rtree to
    sort them). An invalid ring (a contour touching itself) is mended first."""
    return functools.reduce(lambda a, b: a.symmetric_difference(b), (g if g.is_valid else g.buffer(0) for g in polys))


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
        polys = [even_odd(loops)] if loops else []
    polys = [p for p in polys if p.is_valid and p.area > 1e-6]
    if not polys:
        return MultiPolygon()
    out = unary_union(polys)
    # A flat wall is two triangles, and the plane crossing their diagonal leaves a point on the straight edge — at a
    # different place on every layer. The same cube with a hole came out as 100 outlines alike in shape and unlike in
    # points, and intersecting them for the stack's aligned dowels kept every point of every layer: 393,370 vertices,
    # and the job never got past "placing slices" (reported). Off they come, 0.1 µm of tolerance. Douglas-Peucker,
    # not the topology-preserving simplify, which reads uninitialised memory in the browser's GEOS 3.12.
    lean = out.simplify(1e-4, preserve_topology=False)
    return as_multi(lean if lean.is_valid and not lean.is_empty else out)


def as_multi(g) -> MultiPolygon:
    if g is None or g.is_empty:
        return MultiPolygon()
    if isinstance(g, Polygon):
        return MultiPolygon([g])
    if isinstance(g, MultiPolygon):
        return g
    return MultiPolygon([p for p in shapely.get_parts(g) if isinstance(p, Polygon)])


def as_lines(g) -> MultiLineString:
    if g is None or g.is_empty:
        return MultiLineString()
    if isinstance(g, LineString):
        return MultiLineString([g])
    if isinstance(g, MultiLineString):
        return g
    return MultiLineString([l for l in shapely.get_parts(g) if isinstance(l, LineString)])


def robust(op, *geoms, default=None):
    """`op(*geoms)`, and when the geometry engine throws — the browser build's GEOS now and then reports
    "orientationIndex encountered NaN/Inf" from an overlay or an inscribed circle on a perfectly finite outline, where
    the desktop's never does — the same once more on precision-snapped copies (the snapping overlay is the robust
    one), else `default`: a label that goes beside its part, a thin spot not reported, beats a model that will not slice."""
    try:
        return op(*geoms)
    except GEOSException:
        try:
            return op(*[shapely.set_precision(q, 1e-6) for q in geoms])
        except GEOSException:
            return default


def label_box(text, font):
    """The room an engraved label takes at `font` mm (the height of a capital): (w, h) — the stroke font's own width
    with a millimetre either side, never under 6 mm, and 1.4 capitals, which holds the descenders. The sheet
    placement and the per-piece export size a label the same way through this."""
    from .font import width
    return max(6.0, width(text, font) + 2), font * 1.4


def mark_box(x, y, text, font, rot=0.0):
    """The room a small engraved mark (a seam or dowel number, at 0.6 of the font) takes, centred on (x, y) and turned
    `rot` degrees — the mark's own turn in its part's frame; a mark on a nested part is turned by the placement too."""
    from .font import width
    s = font * 0.6
    b = box(x - (width(text, s) + 0.6) / 2, y - s * 0.7, x + (width(text, s) + 0.6) / 2, y + s * 0.7)
    return shapely.affinity.rotate(b, rot, origin=(x, y)) if rot else b


def mark_rot(m):
    """A mark's own turn, 0 for the three-value marks."""
    return float(m[3]) if len(m) > 3 else 0.0


def label_rect(x, y, rot, w, h):
    """A w × h label's box, centred on (x, y) and turned `rot` degrees, as the sheet carries it."""
    return shapely.affinity.rotate(box(x - w / 2, y - h / 2, x + w / 2, y + h / 2), rot, origin=(x, y))


def fit_block(region, w, h, angles=(0, 90)):
    """Centre and turn of a w × h block lying wholly inside `region` (holes respected), or None. For each turn the
    region is laid flat along it and eroded by the block — the region overlapped with itself moved by each corner and
    each edge middle of the block, a quick stand-in for the exact erosion — and the roomiest spot of what is left
    (the centre of its largest inscribed circle) is checked exactly."""
    region = as_multi(region)
    if region.is_empty:
        return None
    for ang in angles:
        R = shapely.affinity.rotate(region, -ang, origin=(0, 0)) if ang else region
        E = R
        for dx, dy in ((w / 2, h / 2), (-w / 2, h / 2), (w / 2, -h / 2), (-w / 2, -h / 2), (w / 2, 0), (-w / 2, 0), (0, h / 2), (0, -h / 2)):
            E = robust(lambda a, b: a.intersection(b), E, shapely.affinity.translate(R, dx, dy))
            if E is None or E.is_empty:
                break
        if E is None:
            continue
        for piece in sorted(as_multi(E).geoms, key=lambda q: -q.area):
            disc = robust(lambda q: shapely.maximum_inscribed_circle(q, 0.5), piece)
            for cx, cy in ([disc.coords[0]] if disc is not None else []) + [piece.representative_point().coords[0]]:
                if R.covers(box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)):
                    x, y = shapely.affinity.rotate(Point(cx, cy), ang, origin=(0, 0)).coords[0] if ang else (cx, cy)
                    return (float(x), float(y), float(ang))
    return None


def covered(region, guides):
    """The part of `region` the next layer covers, rebuilt from the guide lines (the stacked "engrave next layer"
    outline): the rings they enclose, less a ring inside a ring, which is the layer above's hole — its inner edge is
    engraved too, and a label under it would show through. None when the part carries no guide."""
    if not guides:
        return None
    loops = [g for g in shapely.polygonize(guides).geoms if getattr(g, "area", 0) > 0]
    loops = [g for g in loops if not any(o is not g and Polygon(o.exterior).contains(g) for o in loops)]
    if not loops:
        return None
    under = shapely.union_all(loops).intersection(region)
    return None if under.is_empty else under


def fit_on_part(region, guides, w, h, marks=(), angles=(0, 90), room=0.0):
    return robust(lambda r: _fit_on_part(r, guides, w, h, marks, angles, room), region, default=None)


def _fit_on_part(region, guides, w, h, marks=(), angles=(0, 90), room=0.0):
    """Where a w × h label fits whole on a part's material with `room` to spare all round: inside the next layer's
    outline when the part carries one (`guides`), so the layer glued on top hides it, else anywhere on the part —
    clear of its holes and of the marks and arrows (boxes) already engraved on it — at the first of `angles` that
    holds it. None when it fits nowhere: a label crammed against the edge of a small part is better off beside it."""
    region = as_multi(region)
    if marks:
        region = robust(lambda a, b: as_multi(a.difference(b)), region, unary_union([m.buffer(0.5) for m in marks]), default=region)
    for cand in (covered(region, guides), region):
        if cand is not None and not cand.is_empty:
            spot = fit_block(cand, w + 2 * room, h + 2 * room, angles)
            if spot:
                return spot
    return None


def widest_spot(region):
    return robust(lambda r: _widest_spot(r), region, default=(0.0, 0.0, 0.0))


def _widest_spot(region):
    """The spot on a part with the most clearance all round — the centre of its largest inscribed circle: where a
    label that fits nowhere whole is still put, overrunning the outline, for the maker to trim rather than left off."""
    region = as_multi(region)
    if region.is_empty:
        return (0.0, 0.0, 0.0)
    discs = [d for d in (robust(lambda q: shapely.maximum_inscribed_circle(q, 0.5), g) for g in region.geoms) if d is not None]
    if not discs:
        return (0.0, 0.0, 0.0)
    best = max(discs, key=lambda c: c.length)
    return (float(best.coords[0][0]), float(best.coords[0][1]), 0.0)


def orient_arrows(region, longest=8.0, keep=()):
    return robust(lambda r: _orient_arrows(r, longest, keep), region, default=[])


def _orient_arrows(region, longest=8.0, keep=()):
    """Two arrows at a part's widest spot, on the LABEL layer: one up its frame's y, one shorter to the right along
    x, so every part of a model carries the same two directions and the engraved face is known to be the front. As
    (style, LineString) lines, shaft and head each, sized to the clearance there, clear of `keep` (the marks already
    engraved, as boxes); none on a part too small to hold a legible pair."""
    region = as_multi(region)
    if keep:
        region = robust(lambda a, b: as_multi(a.difference(b)), region, unary_union([k.buffer(0.6) for k in keep]), default=region)
    if region.is_empty:
        return []
    discs = [d for d in (robust(lambda q: shapely.maximum_inscribed_circle(q, 0.5), g) for g in region.geoms) if d is not None]
    if not discs:
        return []
    disc = max(discs, key=lambda c: c.length)
    (cx, cy), r = disc.coords[0], disc.length
    L = min(longest, 0.6 * r)                   # well inside the clearance: on a small part the arrows must not read as its edge
    if L < 3.0:
        return []
    out = []
    for dx, dy, length in ((0, 1, L), (1, 0, 0.65 * L)):
        tx, ty = cx + dx * length, cy + dy * length                      # the tip
        h = 0.3 * length; px, py = -dy, dx                                  # the head's half-width, across the shaft
        out.append(("orient", LineString([(cx, cy), (tx, ty)])))
        out.append(("orient", LineString([(tx - dx * h - px * h * 0.6, ty - dy * h - py * h * 0.6), (tx, ty), (tx - dx * h + px * h * 0.6, ty - dy * h + py * h * 0.6)])))
    return out


def label_angles(region):
    """The turns to try a label on a part at: upright, a quarter turn, and along the part's long side and across it
    when that side is not already square to the sheet."""
    long = -min_rect_angle(region) % 180
    if long > 90:
        long -= 180                                           # never upside down
    return (0, 90) if min(abs(long) % 90, 90 - abs(long) % 90) < 5 else (0, 90, round(long, 1), round(long + 90 if long < 0 else long - 90, 1))


def lines_in_mesh(mesh, lines, span) -> list[list[tuple[float, float]]]:
    """For each line (p0, d): its inside-segments (s_in, s_out) against the mesh, s along d from p0. One cast for all
    the lines: trimesh's bookkeeping per call cost about as much as the ray itself, and a slice casts hundreds — one
    per slot and one per pair of a family in the collision check."""
    if not lines:
        return []
    D = np.asarray([d for _, d in lines], float); D /= np.linalg.norm(D, axis=1)[:, None]
    P = np.asarray([p for p, _ in lines], float); O = P - D * span
    if HAVE_RTREE:
        locs, ray, _ = mesh.ray.intersects_location(O, D, multiple_hits=True)   # rtree broad phase, cached on the mesh
    else:                                                 # the browser build: a broad phase of our own — only the triangles
        from types import SimpleNamespace                 # whose bounding sphere the line passes through are tested
        from trimesh.ray.ray_triangle import ray_triangle_id
        cache = mesh.metadata.setdefault("lamina_spheres", {})
        if "c" not in cache:                              # once per mesh
            tri = mesh.triangles; c = tri.mean(1)
            cache.update(c=c, r2=(np.linalg.norm(tri - c[:, None], axis=2).max(1) + 1e-6) ** 2)
        locs, ray = [], []
        for k in range(len(lines)):
            v = cache["c"] - O[k]; t = v @ D[k]
            near = np.flatnonzero(np.einsum("ij,ij->i", v, v) - t * t <= cache["r2"])   # squared distance to the line
            tree = SimpleNamespace(bounds=mesh.bounds, intersection=lambda b, near=near: near)
            _, _, hit = ray_triangle_id(mesh.triangles, O[k:k + 1], D[k:k + 1], triangles_normal=mesh.face_normals, tree=tree, multiple_hits=True)
            locs += list(hit); ray += [k] * len(hit)
    locs, ray = np.asarray(locs, float).reshape(-1, 3), np.asarray(ray, int)   # no hit at all comes back shaped (0,)
    out = []
    for k in range(len(lines)):
        s = np.sort((locs[ray == k] - P[k]) @ D[k])
        s = s[np.r_[True, np.diff(s) > 1e-6]] if len(s) else s
        if len(s) % 2:
            s = s[:-1]
        out.append([(float(s[i]), float(s[i + 1])) for i in range(0, len(s), 2) if s[i + 1] - s[i] > 0.3])
    return out


def crossings(mesh, span, frames, toward=None):
    """For each pair of slice frames (Ma, Mb): the line their planes meet on and where it runs inside the model,
    (p0, d, [(s_in, s_out) …]) — or None where the planes are parallel. With `toward`, a direction per pair, d is
    turned to point that way (a slot's open side) and the cast runs along it: a ray grazing an edge hits an odd
    number of times and the last hit is the one dropped, so the direction has to be the one the caller means."""
    lines = [plane_plane_line(Ma, Mb) for Ma, Mb in frames]
    if toward is not None:
        lines = [None if ln is None else (ln[0], -ln[1] if np.dot(ln[1], t) < 0 else ln[1]) for ln, t in zip(lines, toward)]
    segs = iter(lines_in_mesh(mesh, [ln for ln in lines if ln is not None], span))
    return [None if ln is None else (ln[0], ln[1], next(segs)) for ln in lines]


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


def hole_reach(d, shape="round") -> float:
    """How far a dowel hole reaches from its centre: d/2 round, 0.71 d at a square's corner, 0.75 d at a slot's end."""
    return max(math.hypot(x, y) for x, y in dowel((0, 0), d, shape).exterior.coords)


LEVERAGE_OK = 0.8         # dowels that hold a piece: its far edge moves less than the play in their holes. 1.0 let
                           # rods carried up from a smaller layer stand in for three around the edge of a disc (0.69)


def dowel_leverage(piece, pts) -> float:
    """How well the dowels through a piece hold it: the farthest the piece reaches from their middle, over the widest
    spacing between two of them. The play in the holes lets the piece turn by about play / spacing, which its far edge
    feels × that reach — so this is how many times the holes' play the far edge can shift. Two dowels 46 mm apart in
    the middle of a 200 mm disc: 2.2. The same two near its edges: 0.55; three around near the edge: 0.64. One dowel
    is a hinge: inf. (The farthest point of a polygon from a point is one of its vertices, so the exterior is exact.)"""
    q = np.asarray(pts, float).reshape(-1, 2)
    if len(q) < 2:
        return math.inf
    spacing = np.linalg.norm(q[:, None] - q[None], axis=2).max()
    reach = np.linalg.norm(np.asarray(piece.exterior.coords) - q.mean(0), axis=1).max()
    return float(reach / spacing)


def poly_coords(mp: MultiPolygon) -> list:
    """[[exterior, hole, hole...], ...] as plain lists for JSON (bulk coordinate extraction: panels have 100s of holes)."""
    out = []
    for p in mp.geoms:
        rings = shapely.get_rings(p)
        coords = np.round(shapely.get_coordinates(rings), 4)
        parts = np.split(coords, np.cumsum(shapely.get_num_coordinates(rings))[:-1])
        out.append([r[:-1].tolist() for r in parts])
    return out


def line_coords(ml) -> list:
    return [list(map(list, np.round(np.asarray(l.coords), 4))) for l in as_lines(ml).geoms]


def thin_spots(region, mf):
    return robust(lambda r: _thin_spots(r, mf), region, default=[])


def _thin_spots(region, mf):
    """The parts of `region` too thin for too long to survive the cutter or the hand — the point of a slice that
    meets the surface at a grazing angle, a wall left between a slot and the edge — as polygons: what an opening
    (erode, then dilate) takes off, kept where it runs long enough to matter. Two sizes: thinner than `mf` for 2 × `mf`,
    or thinner than 1.5 × `mf` for 4 × `mf` and at least three times as long as wide (a spike, not the scalloped edge
    of a scanned model, whose every shallow wave the wider opening takes a shaving off). A square or 45° corner loses
    less than that and is not one. A bridge thinner than `mf` between two bodies is also among them; `trim_thin`
    leaves those alone (see there)."""
    out = []
    for w, length, ratio in ((mf, 2 * mf, 0.0), (1.5 * mf, 4 * mf, 3.0)):
        thin = robust(lambda q, half=w / 2: q.difference(q.buffer(-half).buffer(half + 0.05)), region)
        if thin is None:
            continue
        for piece in as_multi(thin).geoms:
            a, b = min_dims(piece)
            if piece.area > 0.1 * w * w and b >= length and b >= ratio * a and not any(piece.intersects(q) for q in out):   # one spot, not one per size
                out.append(piece)
    return out


def trim_thin(region, mf):
    return robust(lambda r: _trim_thin(r, mf), region, default=(region, 0))


def _trim_thin(region, mf):
    """`region` with its thin tips and slivers cut off — a blunt end where the point was, a slot open to the edge
    where the wall beside it was — and how many went. A thin spot whose removal would split the region (a bridge)
    stays: that is a part in two pieces, which the check reports as such."""
    n = 0
    for piece in thin_spots(region, mf):
        cut = robust(lambda a, b: as_multi(a.difference(b)), region, piece.buffer(0.02, join_style=2))
        if cut is not None and len(cut.geoms) == len(region.geoms) and not cut.is_empty:
            region = cut; n += 1
    return region, n


def facet_polys(pc):
    """Every flat polygon of a piece (holes included) with the frame that places it in the assembly, and its own
    thickness where that is not the part's (a folded panel's thin printed tab), else None."""
    for fc in pc["facets"]:
        M = np.array(fc["M"])
        for rings in fc["rings"]:
            poly = Polygon(rings[0], rings[1:])
            for g in shapely.get_parts(poly if poly.is_valid else poly.buffer(0)):
                if not g.is_empty:
                    yield g, M, fc.get("t")
