"""Modify form: the model remeshed on a signed distance field (shrinkwrap, round, thicken, hollow)."""
from __future__ import annotations
import math
import numpy as np
import trimesh

REMESH_FACES = 120000      # about how many faces a remesh may have: plenty of detail, and every later section stays quick


def rasterize(seg, shape, winding=False):
    """Scanline fill of one layer from its cut segments (n, 2, 2) in grid units. Even-odd: the point (i, j) is inside
    when an odd number of segments cross the row j to its left. Works on the bare segment soup — no loop linking, so
    a missing triangle (an open loop) costs nothing, and it is one numpy pass for the whole layer. `winding`, for
    segments that all run anticlockwise about their solid: the non-zero rule, so a region two parts share (a leg
    pushed into a body) is solid, where even-odd made it a void and cut the leg off."""
    y = np.arange(shape[1])[:, None]
    (x0, y0), (x1, y1) = seg[:, 0].T[:, None, :], seg[:, 1].T[:, None, :]           # (1, n) each, against rows (m, 1)
    cross = (y0 <= y) != (y1 <= y)                                                    # half-open rule: a vertex on the row counts once
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.where(cross, x0 + (y - y0) * (x1 - x0) / (y1 - y0), 0)
    rows, cols = np.nonzero(cross)[0], np.clip(np.ceil(x[cross]), 0, None).astype(int)   # a crossing left of the grid counts for every point
    keep = cols < shape[0]
    count = np.zeros(shape, int)
    np.add.at(count, (cols[keep], rows[keep]), np.broadcast_to(np.sign(y1 - y0), cross.shape)[cross][keep] if winding else 1)
    total = np.cumsum(count, axis=0)
    return total != 0 if winding else total % 2 == 1


def close_ends(odd):
    """Segments that close the open ends of a layer's cut: each odd end joined to the nearest one left. A loop with one
    gap gets the chord across it. Linking the segments into chains first (trimesh's load_path) came back empty at the
    rim of a scan's hole, where three segments meet at an end, and the slice failed."""
    odd, out = list(odd), []
    while odd:
        a = odd.pop()
        b = odd.pop(int(np.argmin([np.hypot(*(q - a)) for q in odd])))
        out.append([a, b])
    return np.array(out).reshape(-1, 2, 2)


OFF_GRID = 0.41   # the samples sit this far (in pitches) past the grid lines: a face that lands exactly on a sample
                  # (a 60 mm box on a 2 mm grid, with samples on the even millimetres) has its corner cut a whole
                  # sample short by marching cubes, whatever the field says — 1.8 mm at 2.5 mm pitch against 0.3
                  # with the samples between the lines. Not a half: a 4 mm pitch would put them back on the integers


def inside_at(mesh, pitch, pad):
    """Where the solid is, sampled at the grid corners (lo + OFF_GRID + j) * pitch: the mesh is cut at every layer
    and the cut rasterised, so the grid is solid from the start and an open loop (a hole in a scan) is closed
    straight across. trimesh's own voxeliser splits every triangle down to half a voxel and then fills the shell:
    13 s on a 40k-face head at 1 mm, where this takes about a second. Exact point-in-solid, not a conservative
    voxel: the surface is put back where it was by the distances `field` measures, not by the grid. A closed,
    consistently wound mesh is filled by the non-zero winding rule — parts pushed into each other are one solid, a
    surface exported twice is one, a cavity the model is wound to enclose is a cavity; anything else (a scan with a
    hole) by even-odd, as the sections are. What to make of a cavity is `modify_form`'s call."""
    from trimesh.intersections import mesh_plane
    lo = np.floor(mesh.bounds[0] / pitch).astype(int) - pad
    n = np.ceil(mesh.bounds[1] / pitch).astype(int) + pad + 1 - lo
    c = np.zeros(n, bool)
    z = mesh.triangles[:, :, 2]; zlo, zhi = z.min(1), z.max(1)
    winding = mesh.is_watertight and mesh.is_winding_consistent   # every loop closed, every segment given a way round
    for k in range(n[2]):
        h = (lo[2] + OFF_GRID + k) * pitch             # only the triangles this layer passes through: the same cut,
        seg, faces = mesh_plane(mesh, [0, 0, 1], [0, 0, h], local_faces=np.flatnonzero((zlo <= h) & (zhi >= h)), return_faces=True)   # 2.3× faster
        if not len(seg):
            continue
        seg = np.round(seg[:, :, :2] / pitch - lo[:2] - OFF_GRID, 4)
        if winding:                           # anticlockwise about the solid: its outward normal to the right of the way walked
            d, nrm = seg[:, 1] - seg[:, 0], mesh.face_normals[faces]
            flip = nrm[:, 0] * d[:, 1] - nrm[:, 1] * d[:, 0] < 0
            seg[flip] = seg[flip, ::-1]
        else:
            pts, ends = np.unique(seg.reshape(-1, 2), axis=0, return_counts=True)
            if (ends % 2).any():              # an end where an odd number of segments meet: a loop is open (a hole in a
                seg = np.concatenate([seg, close_ends(pts[ends % 2 == 1])])   # scan) — close it straight across
        c[:, :, k] = rasterize(seg, n[:2], winding)
    return c, (lo + OFF_GRID) * pitch


def distance_to(mesh, pts, k=8):
    """Unsigned distance from `pts` to the surface, with no rtree (the browser build has none): the k nearest
    triangle centroids, then the exact point-to-triangle distance to each. Exact while no triangle is much bigger
    than its spacing from the points — measured against trimesh's rtree answer on the blob and the bunny, k=8 is
    within 0.015 mm, k=6 within 0.11 mm."""
    from scipy.spatial import cKDTree
    tri = mesh.triangles; cen = tri.mean(1)
    reach = np.linalg.norm(tri - cen[:, None], axis=2).max(1)   # how far a triangle extends from its centroid
    k = min(k, len(tri))
    dc, idx = (a.reshape(len(pts), -1) for a in cKDTree(cen).query(pts, k, workers=-1))
    best = np.full(len(pts), np.inf)
    for j in range(k):                                     # k passes over n points, not one over n·k: memory
        may = np.flatnonzero(dc[:, j] - reach[idx[:, j]] < best)   # a triangle that could still beat the best
        if not len(may):
            break
        c = trimesh.triangles.closest_point(tri[idx[may, j]], pts[may])
        best[may] = np.minimum(best[may], np.linalg.norm(c - pts[may], axis=1))
    return best


def field(mesh, inside, pitch, origin, inner, outer):
    """Signed distance to the surface (mm, positive inside) at every grid corner: exact to `inner` mm inside it and
    `outer` outside, as deep as the shifts to come need, and the grid's own chessboard distance beyond — never more
    than the true distance, so nothing a shift could move past the band is read as farther than it is, and a third
    the cost of a Euclidean transform. Triangles bigger than two grid steps are split first, so that the nearest
    centroids are the nearest triangles."""
    from scipy import ndimage
    steps = lambda m: ndimage.distance_transform_cdt(m, metric="chessboard")
    f = np.where(inside, steps(inside), -steps(~inside)) * float(pitch)
    near = (f <= inner) & (f >= -outer)
    if mesh.edges_unique_length.max() > 2 * pitch:         # marching cubes' own triangles never need it
        mesh = trimesh.Trimesh(*trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, 2 * pitch), process=False)
    f[near] = np.sign(f[near]) * distance_to(mesh, np.argwhere(near) * pitch + origin)
    return f


def surface(f, pitch, origin):
    """The zero surface of the field: marching cubes puts every vertex where the surface really crosses a grid
    edge, so a curve comes back a curve — no staircase, no ripple, nothing to smooth off."""
    from skimage.measure import marching_cubes
    if f.max() <= 0 or f.min() >= 0:
        raise RuntimeError("modify form leaves nothing of the model: round removes every feature thinner than its value, "
                           "and a model thinner than the grid everywhere has no inside to keep — lower the value, or set it to 0")
    v, faces, _, _ = marching_cubes(f, 0.0, spacing=(pitch,) * 3, gradient_direction="ascent")   # inside is positive: faces out
    return trimesh.Trimesh(v + origin, faces)


def modify_form(mesh, p, notes, fine=False):
    """Slicer's Modify Form: shrinkwrap (remesh at a resolution), round (drop features thinner than r and round the
    corners off = morphological opening + closing), thicken (grow by t), hollow (keep a wall h). `fine` takes the
    finest grid, for a remesh nobody asked for.

    All of it on a signed distance field rather than a binary voxel grid. Growing a solid by r puts its surface
    exactly where the distance to the old one is r, so thicken is the field plus t, hollow a wall between 0 and h, and
    erosion the field minus r — exact, in millimetres, not rounded to whole voxels. Where one shift follows another
    (round's erode-then-dilate) the field is measured again against its own surface, since the distance to a grown
    solid is not the old distance plus r in a crease. On a binary grid the same operations with a one-cube ball gave
    the blob a 21° angle between neighbouring faces at the 95th percentile (the model: 6°), moved its surface
    1.6 mm, and rippled it by 0.5 mm; this leaves 4° and 0.03 mm."""
    ext = max(mesh.extents)
    r, t, h = p["round"], p["thicken"], p["hollow"]
    feats = [v for v in (r, t, h) if v]
    pitch = p["shrinkwrap"] or (min(feats) / 2 if feats else ext / (300 if fine else 120))
    pitch = max(pitch, ext / (300 if fine or p["shrinkwrap"] else 120))   # a grid finer than this is a memory request,
    # not a detail — and on a scan it also thins the neck of every ear and leg until the checks call them separate.
    # Nor finer than the mesh it would make: marching cubes lays about two triangles on every pitch² of surface, and
    # half a million of them is slow to section everywhere and more than the browser's heap will take beside a slice.
    # Coarsening the grid is the honest way to that ceiling — decimating afterwards would cost the watertight surface
    # every section depends on.
    pitch = max(pitch, math.sqrt(2 * mesh.area / REMESH_FACES))
    m = 1.5 * pitch                                        # the grid's own uncertainty about what is "near"
    inside, origin = inside_at(mesh, pitch, int(math.ceil((r / 2 + t) / pitch)) + 2)
    # A closed cavity — a scan's inner surface, a model wound to be hollow — is solid, as before: hollow measures its
    # wall from the outside. Its surface drops out of the measuring (a face whose normal points into the cavity:
    # left in, it would pull the field to zero through the middle of the material and round would hollow the
    # model). A shell open anywhere, the bunny example, stays a shell.
    from scipy import ndimage
    filled = ndimage.binary_fill_holes(inside)
    if filled.sum() > inside.sum():
        at = np.round((mesh.triangles.mean(1) + pitch * mesh.face_normals - origin) / pitch).astype(int)
        cavity = (filled & ~inside)[tuple(np.clip(at, 0, np.array(inside.shape) - 1).T)]
        mesh = mesh.submesh([np.flatnonzero(~cavity)], append=True)
    def again(f, inner, outer):                             # the field measured afresh against its own surface
        return field(surface(f, pitch, origin), f > 0, pitch, origin, inner, outer)

    # Each field is exact only as deep as the shifts read from it: a shift moves the surface, and what was exact
    # `inner` deep is exact `inner − shift` deep from where the surface now is.
    deep = h if h and not t else 0                          # hollow reads the field inside, unless thicken re-measures first
    if r:                   # opening then closing with a ball of diameter r — a feature thinner than r cannot hold the
        r /= 2              # ball and goes, a gap narrower than r is bridged — is erode r/2, dilate r, erode r/2
        f = field(mesh, filled, pitch, origin, r + m, m)
        f = again(f - r, m, 2 * r + m)
        f = again(f + 2 * r, r + deep + m, max(m, t + m - r)) - r
    else:
        f = field(mesh, filled, pitch, origin, deep + m, t + m)
    if t:
        f = again(f + t, h + m, m) if h else f + t          # the wall is measured inward from the thickened surface
    if h:
        f = np.minimum(f, h - f)
    out = surface(f, pitch, origin)
    notes.append(f"modify form: remeshed at {pitch:.2f} mm ({len(out.faces)} faces) — detail finer than about "
                 f"{pitch:.1f} mm is lost" + ("" if fine else "; every modify form value at 0 keeps the model as drawn"))
    return out
