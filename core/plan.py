"""Pipeline: mesh → modify form → mode.build → sections → cuts → checks → split → pack → plan.json.

    uv run python -m core.plan examples/egg.stl --mode interlocked --set nx=5 ny=4 thickness=3 --out working-files/egg
"""
from __future__ import annotations
import argparse, json, math, os, pathlib, shutil, threading, time
import numpy as np
import trimesh
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, MultiLineString, MultiPoint
from shapely.ops import unary_union
from .modes import load_all, Ctx
from .geometry import section_polygons, as_multi, poly_coords, line_coords, mark_box, mark_rot, min_dims, min_rect_angle, orient_arrows, trim_thin
from .checks import STRUCTURAL, check_plan, suggest_fixes, crossing_suggestions
from .split import split_slice, fits_rotated, islands
from .nest import nest
from .model import Piece, label_codes, label_tag

MODES = load_all()
CAD_SUFFIXES = {".step", ".stp", ".brep", ".iges", ".igs"}


def report(text, frac, artifact=None):
    """Where progress() forwards each stage of build(): what is happening, how far along (0..1), and — when a stage
    has just finished something worth looking at before the rest — the file it wrote. A no-op here; the server and
    the browser worker point it at the page, where a slice of a big model takes long enough to look stuck."""


class _Run(threading.local):
    """The build under way on this thread: a server runs several at once (one per request thread), and with these
    shared, one build's start wiped another's stage marks — the timing log then put 72 s slices down as 10."""
    def __init__(self):
        self.stages: list[tuple[str, float]] = []   # (stage text, clock) marks
        self.band = (0.0, 1.0)                      # the slice of the bar this pass owns (see the autofix loop in build)


_run = _Run()
DETAIL = " · "                            # everything after it is detail of the stage, not a stage of its own


def progress(text, frac):
    _run.stages.append((text, time.perf_counter()))
    lo, hi = _run.band
    report(text, lo + frac * (hi - lo))


def timing() -> dict[str, float]:
    """Seconds per stage of the build, read off the progress marks; a stage's detail ("sectioning · 3 / 16",
    "· pass 2 of 3") folds into one row. This is what an optimisation has to move, so it rides in the plan and in
    the server's timing log."""
    out = {}
    for (text, t0), (_, t1) in zip(_run.stages, _run.stages[1:]):
        k = text.split(DETAIL)[0]
        out[k] = round(out.get(k, 0.0) + t1 - t0, 3)
    return out


def coerce_params(mode, raw: dict) -> dict:
    p = {prm.name: prm.coerce(raw.get(prm.name)) for prm in mode.all_params()}
    # older projects stored a boolean, or "remove" (auto-fix used to delete what nothing held): that is report-only now
    if p.get("autofix") not in ("add", "off"):
        p["autofix"] = "off" if str(p.get("autofix")).lower() in ("false", "0", "remove") else "add"
    if "cloth" in raw and "separate" not in raw:                    # older names
        p["separate"] = bool(raw["cloth"])
    if "label_inside" in raw and "label_place" not in raw:          # a project saved when labels were a tickbox: on the parts, or beside them
        p["label_place"] = "on" if str(raw["label_inside"]).lower() in ("true", "1") else "beside"
    if "simplify" in raw and "facet" not in raw and "facet" in p and raw["simplify"] in (0, "0"):
        p["facet"] = 0
    return p


def load_cad(path) -> trimesh.Trimesh:
    """STEP / IGES / BREP via CadQuery (optional extra):  uv sync --extra cad"""
    try:
        import cadquery as cq
    except ImportError:
        raise RuntimeError("CAD import needs CadQuery: run `uv sync --extra cad` (STL/OBJ/3MF/PLY/OFF/GLB need nothing extra)") from None
    suf = pathlib.Path(path).suffix.lower()
    if suf in (".iges", ".igs"):
        raise RuntimeError("IGES is not supported — export STEP (or STL) from your CAD instead")
    shape = cq.importers.importStep(str(path)) if suf in (".step", ".stp") else cq.Workplane().add(cq.importers.importBrep(str(path)))
    solids = shape.solids().vals() or shape.vals()
    meshes = []
    for s in solids:
        verts, tris = s.tessellate(0.05, 0.2)
        meshes.append(trimesh.Trimesh([v.toTuple() for v in verts], tris))
    return trimesh.util.concatenate(meshes)


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


ONE_SHEET_H = 100000.0     # "one sheet" mode nests against this height and reports the length actually used
REMESH_FACES = 120000      # about how many faces a remesh may have: plenty of detail, and every later section stays quick
SQUARE_MIN, SQUARE_MAX = 0.5, 15.0   # degrees off square that square_up offers to take back


from .modes.folded import simplify as decimate    # noqa: E402 — fewer faces, same shape. Folded panels have needed
# this since they were written, including the fallback that matters most here: where there is no wheel for quadric
# decimation (the browser build) it clusters vertices in plain numpy instead of handing back the mesh untouched.
# That mesh is the one every section is cut from and the one the preview ships, so leaving it at half a million
# faces is what put the browser's heap under enough pressure to hand GEOS a NaN.


def coverage(mesh, slices, r, lat=3.0):
    """Fraction of the model's surface represented by the parts: sample points on the surface and count those that
    have a part within `r` across its plane (about half a slice spacing) and within `lat` sideways. A leg or an ear
    no slice reaches lowers it.

    The two tolerances are deliberately different: with lateral slack as large as the across-plane one, a leg
    projects onto the body's cross-section and reads as represented (a 3x2 slicing of a cow scored 100 %).
    Surface samples, not volume samples: point-in-mesh tests ray-cast every sample against every triangle and need
    gigabytes on a 40k-face model, while surface points answer the same question for one barycentric mix each.
    Dense slicings (interlocked, radial) put a slice near every point and legitimately score close to 100 %; the
    number carries the most signal for stacked and folded work.
    """
    pts = mesh.sample(3000, seed=0)                      # seeded: the same model and params must give the same plan
    if len(pts) == 0:
        return 1.0
    covered = np.zeros(len(pts), bool)
    P = np.c_[pts, np.ones(len(pts))]
    for sl in slices:
        if sl.profile is None or sl.group in ("P", "J", "W"):     # spacers, pegs and a plaque's back plate are not sections of the model
            continue
        for M, geom in (sl.facets or [(sl.M, sl.profile)]):
            loc = (np.linalg.inv(M) @ P.T).T
            idx = np.where((np.abs(loc[:, 2]) <= r) & ~covered)[0]
            if not len(idx):
                continue
            # where the model widens, a surface point sits just outside the nearest cross-section; a few mm of
            # lateral slack still counts that as represented
            probe = geom.buffer(lat, join_style=1)
            covered[idx[shapely.contains_xy(probe, loc[idx, 0], loc[idx, 1])]] = True
    return float(covered.mean())


MESH_PARAMS = ("up_axis", "rotate", "size", "scale", "shrinkwrap", "hollow", "thicken", "round", "smooth")   # all _prepare reads
_last = None   # [key, mesh, notes, {name: what was worked out from it}]: the model as last prepared


def load_mesh(path, params, notes=None, mode=""):
    """The model as every later stage sees it. The last one is kept: a new project name, a sheet, a thickness reslices
    without loading and remeshing it again (a second or more of every slice, many more in the browser).
    ponytail: one model kept, so two server clients take turns missing it; key it per client if that ever shows."""
    global _last
    path = pathlib.Path(path)
    progress("loading the model", 0.02)
    st = path.stat()
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns, mode == "folded", repr([params.get(k) for k in MESH_PARAMS]))
    hit = _last                                     # read once: another request thread may replace it meanwhile
    if not hit or hit[0] != key:
        said = []
        hit = _last = [key, _prepare(path, params, said, mode), said, {}]
    if notes is not None:
        notes.extend(hit[2])
    mesh = hit[1].copy()
    mesh.metadata["lamina_key"] = key              # which prepared model it is a copy of, for reuse()
    return mesh


def reuse(mesh, name, make):
    """`make(mesh)`, worked out once per prepared model and kept with it: the preview the 3D view shows (7 s of every
    slice in the browser), the square-up offer (half a second). Anything else is made fresh."""
    hit = _last
    if not hit or hit[0] != mesh.metadata.get("lamina_key"):
        return make(mesh)
    if name not in hit[3]:
        hit[3][name] = make(mesh)
    return hit[3][name]


def _prepare(path, params, notes, mode):
    mesh = load_cad(path) if path.suffix.lower() in CAD_SUFFIXES else trimesh.load(path, force="mesh")
    # `size` is the model's own, along the file's axes, and is applied before any turn: aimed at the world axes after
    # the turn, as it used to be, a bear made 500 mm tall and then stood up along x was 500 mm long and half as big
    # again (034). The page shows and takes the numbers along the view's axes and keeps them on the model's.
    size = params.get("size") or []
    if any(size):
        tgt = np.array([s if s else 0 for s in (list(size) + [0, 0, 0])[:3]], float)
        ext = mesh.extents
        if (tgt > 0).sum() == 1:                      # one value → uniform
            i = int(np.argmax(tgt)); mesh.apply_scale(tgt[i] / ext[i])
        else:
            mesh.apply_scale([tgt[i] / ext[i] if tgt[i] > 0 else 1 for i in range(3)])
    if params["scale"] != 1:                          # multiplies the target size when one is set
        mesh.apply_scale(params["scale"])
    if params["up_axis"] != "z":
        src = "xyz".index(params["up_axis"])
        mesh.apply_transform(trimesh.geometry.align_vectors(np.eye(3)[src], [0, 0, 1]))
    rot = params.get("rotate") or [0, 0, 0]
    if any(rot):
        mesh.apply_transform(trimesh.transformations.euler_matrix(*np.radians(rot[:3]), "sxyz"))
    if max(mesh.extents) < 5:                         # Blender writes metres: a 100 mm cube arrives 0.1 mm across
        notes.append(f"the model is only {max(mesh.extents):.3g} mm across — saved in metres or centimetres? Set size "
                     "to its real size in mm (100 mm cube: size 100)")
    # Folded panels are cut from the surface itself, so an open edge is the input and not a defect: a clothing
    # pattern, a mask, a shell with a neck hole is panelled around its boundary. Mending first closed exactly those
    # into solids — the decision has to come before the repair, not after it fails.
    surface = mode == "folded"
    # vertices merged and duplicate faces dropped for every model: a surface exported twice over itself is watertight
    # and even-odd reads it as empty, so it has to become one surface before anything asks what is inside it
    tight = mesh.is_watertight
    mesh.merge_vertices(); mesh.update_faces(mesh.nondegenerate_faces()); mesh.update_faces(mesh.unique_faces())
    if not mesh.is_watertight and not surface:        # a union that left a seam, a scan with a hole: mend before anything drastic
        trimesh.repair.fill_holes(mesh)
    if not mesh.is_winding_consistent:                # a patch wound the wrong way: turned, so that inside is one thing
        trimesh.repair.fix_normals(mesh)
    if not tight and mesh.is_watertight:
        notes.append("mesh was not watertight: mended (vertices merged, duplicate faces dropped, holes filled) and sliced as modelled")
    if surface and not mesh.is_watertight:
        notes.append("open surface (not a closed solid): panelled as it is — its boundary edges stay open and carry "
                     "no joints, and a hole in the surface stays a hole")
    auto = not mesh.is_watertight and not surface and not params["shrinkwrap"]
    sized = mesh.extents.copy()                       # before modify form grows it: what a scale acts on (the cap's fix)
    if params["shrinkwrap"] or params["hollow"] or params["thicken"] or params["round"] or auto:
        if auto:                                      # the finest grid, and smoothed: a scan's noise goes with its holes
            notes.append("mesh is not watertight and could not be mended — remeshed on a fine grid and smoothed (set shrinkwrap to choose the resolution)")
        progress("modify form: remeshing", 0.06)
        mesh = modify_form(mesh, params, notes, fine=auto)
    if params["smooth"] or auto:                      # Taubin: a volume-preserving Laplacian, so pointy vertices soften and nothing shrinks
        progress("smoothing", 0.16)
        mesh = mesh.copy(); trimesh.smoothing.filter_taubin(mesh, iterations=int(params["smooth"] or 10))
    mesh.apply_translation(-mesh.bounds.mean(0))
    mesh.metadata["sized_extents"] = sized
    return mesh


def square_up(mesh, rot):
    """The `rotate` that puts a boxy model's flat faces back on the axes, and how many degrees off it sits — or None.
    A box a few degrees off square (a slider at 85 instead of 90, a CAD export that came out tilted) stacks as a
    staircase and reads as "not my cube". Only for models that are mostly flat faces on their own box: an organic
    shape has no square to return to, and a model turned further than SQUARE_MAX was turned on purpose."""
    to_box, _ = trimesh.bounds.oriented_bounds(mesh)
    R = to_box[:3, :3]
    P = np.zeros((3, 3))                                 # the quarter turns that bring the box closest to how it sits now
    for i, row in enumerate(R.T):
        j = int(np.argmax(np.abs(row))); P[i, j] = np.sign(row[j])
    Q = P @ R
    off = float(np.degrees(np.arccos(np.clip((np.trace(Q) - 1) / 2, -1, 1))))
    if not SQUARE_MIN < off <= SQUARE_MAX or np.linalg.det(P) < 0:
        return None
    flat = (np.abs(mesh.face_normals @ Q.T).max(1) > np.cos(np.radians(1))) @ mesh.area_faces / mesh.area
    if flat < 0.5:
        return None
    M = Q @ trimesh.transformations.euler_matrix(*np.radians((list(rot or []) + [0, 0, 0])[:3]), "sxyz")[:3, :3]
    R4 = np.eye(4); R4[:3, :3] = M
    return [round(float(np.degrees(a)), 1) + 0.0 for a in trimesh.transformations.euler_from_matrix(R4, "sxyz")], off


MATCH_AREA = 2.0     # mm² of symmetric difference under which two outlines are one part without further looking


def _same_outline(c, h, tol, w=0.1):
    """`h` is `c` as a cutter would see it: everywhere within `w` mm of it, a tenth of a millimetre, under any kerf.
    The symmetric difference decides where it is small (one part) or past `tol` of the area (two); in between the
    outlines are compared edge to edge — a 0.1 % allowance alone let a 6 mm dowel hole a millimetre off (12 mm² on a
    200 cm² layer) pass as the same part, and the second copy was cut with its holes in the wrong place, while a
    sphere's layers a few hundredths of a millimetre apart in radius are the same part to any cutter."""
    d = c.symmetric_difference(h).area
    if d <= MATCH_AREA:
        return True
    if d > tol * c.area:
        return False
    return c.buffer(w).covers(h) and h.buffer(w).covers(c)


def _moved(e, rot, x0, y0):
    """An engraving (lines, mark points, mark texts) turned `rot` about the origin and moved by (-x0, -y0), as its outline was."""
    mv = lambda g: affinity.translate(affinity.rotate(g, rot, origin=(0, 0)), -x0, -y0)
    return mv(e[0]), mv(e[1]), e[2]


def _match(c, g, tol, mirror, ce, ge, turns=(0, 90, 180, 270)):
    """How outline `g` fits outline `c` (both at the origin, long side along x): "same" under one of `turns`,
    "flipped" when it only fits as its mirror image, None when it does not fit at all. What is engraved on them (`ce`,
    `ge`: guide lines, marks with their texts, in the same frames) has to coincide under that same move: two slices
    with the same outline but another layer's outline, or another seam number, marked on them are two parts."""
    if abs(c.area - g.area) > tol * c.area:
        return None
    flip = lambda x: affinity.scale(x, -1, 1, origin=(0, 0))
    tries = (("same", g, ge), ("flipped", flip(g), (flip(ge[0]), flip(ge[1]), ge[2]))) if mirror else (("same", g, ge),)   # mirrored once, not per turn
    for kind, m, me in tries:
        for r in turns:
            h = affinity.rotate(m, r, origin=(0, 0)); x0, y0, _, _ = h.bounds
            if _same_outline(c, affinity.translate(h, -x0, -y0), tol) and _coincide(ce, _moved(me, r, x0, y0)):
                return kind
    return None


def _coincide(a, b, w=0.05):
    """Engravings `a` and `b` are the same: each line set within `w` mm of the other (well under a kerf and over any
    drift), and every mark's text at the other's spot, within half a millimetre."""
    (la, pa, ta), (lb, pb, tb) = a, b
    if la.is_empty != lb.is_empty or not (la.is_empty or la.buffer(w).covers(lb) and lb.buffer(w).covers(la)):
        return False
    return len(ta) == len(tb) and all(any(t == u and p.distance(q) < 0.5 for q, u in zip(pb.geoms, tb)) for p, t in zip(pa.geoms, ta))


def mark_identical(pieces, mirror=False, tol=1e-3, grain=False):
    """Pieces with the same cut outline — kerf applied, any quarter turn, and with `mirror` also turned over — are one
    part in several copies: the first of each set keeps the others' labels in `same`, the ones that have to be turned
    over in `flipped`, so they are cut once with a quantity and listed once. What is engraved on a piece — a guide line
    (stacked, `next_outline`), a seam number — is part of what the piece is and has to match too; fold lines keep every
    folded panel a part of its own. With `grain` only a copy as it stands or upside down is the same part: one turned
    sideways would be cut across the grain."""
    groups = []                                     # [(first piece, its outline at the origin, what is engraved on it there)]
    for pc in pieces:
        if any(s != "guide" for s, _ in pc.lines):  # score lines (folded panels): each fold pattern is its own part
            continue
        a = 0.0 if grain else min_rect_angle(pc.kerfed)
        g = affinity.rotate(pc.kerfed, a, origin=(0, 0)); x0, y0, _, _ = g.bounds; g = affinity.translate(g, -x0, -y0)
        ge = _moved((MultiLineString([ln for _, ln in pc.lines]), MultiPoint([m[:2] for m in pc.marks]), [m[2] for m in pc.marks]), a, x0, y0)
        for first, c, ce in groups:
            # same outline but cut from other stock is not the same part: it belongs on the other thickness's sheet
            kind = _match(c, g, tol, mirror, ce, ge, (0, 180) if grain else (0, 90, 180, 270)) if first.parent.thickness == pc.parent.thickness else None
            if kind:
                (first.same if kind == "same" else first.flipped).append(pc.label)
                break
        else:
            groups.append((pc, g, ge))


def shed_slivers(raw, prof, cuts, mf, mp):
    """What is not a piece of the model, though the geometry has it: a shaving a slot cuts off its own part, thinner
    than min_feature everywhere — the slot's waste, which would snap off at the cutter — and a speck where the plane
    only grazes the surface, thinner than min_feature everywhere and shorter than min_part every way (the bunny's
    0.5 mm² toe edges). Those go; any region of the model past either size stays, held or flagged, never deleted.
    Returns the profile and how many went."""
    keep = []
    for r in prof.geoms:
        if r.buffer(-mf / 2).is_empty:
            if min_dims(r)[1] < mp:
                continue
            if any(r.distance(c) < 1e-6 for c in cuts):
                parent = max(raw.geoms, key=lambda q: q.intersection(r).area)
                if not parent.buffer(-mf / 2).is_empty and parent.area > 2 * r.area:
                    continue
        keep.append(r)
    return MultiPolygon(keep), len(prof.geoms) - len(keep)   # empty: the plane only grazes the model, there is no part


def _swap_in(mesh, dest, waits=(0, 0.05, 0.1, 0.2, 0.4, 0.8)):
    """Write `mesh` to `dest` without ever leaving a half-written file there; True when it got there. See build()."""
    tmp = dest.with_suffix(f".{threading.get_ident()}.stl")
    mesh.export(tmp)
    try:
        for wait in waits:
            time.sleep(wait)
            try:
                os.replace(tmp, dest)
                return True
            except PermissionError:
                try:
                    shutil.copyfile(tmp, dest)
                    return True
                except PermissionError:
                    continue
        return False
    finally:
        tmp.unlink(missing_ok=True)


def build(model_path, mode_name, raw_params, out=None, mesh_out=None):
    mode = MODES[mode_name]
    p = coerce_params(mode, raw_params)
    p["model_name"] = p["model_name"] or pathlib.Path(model_path).stem   # the server sets the uploaded name; the CLI has the path
    notes = []
    _run.__init__()
    mesh = load_mesh(model_path, p, notes, mode_name)
    square = reuse(mesh, "square", lambda m: square_up(m, p["rotate"]))   # offered on the Model tab, beside rotate
    if mesh_out:                                    # processed model for the browser's ghost view (decimated)
        progress("preparing the preview model", 0.18)
        ghost = reuse(mesh, "preview", lambda m: decimate(m, 30000))
        # beside it, then swapped in: the page may still be downloading the last one, and rewritten in place it got a
        # file cut short (Linux CI: "network error" in the 3D view's loader). Windows refuses the swap while the file
        # is open (the page downloading it, a virus scanner reading it): then in place; refused that too (036: a
        # scanner holds it), tried again a moment later, and after 1.5 s the slice goes on with the last preview —
        # the preview is only what the view shows, never a reason for the slice to fail
        _swap_in(ghost, pathlib.Path(mesh_out))
        # the 3D view can show the model now, before the slices: not a stage of its own, the stage line stays put
        report("", 0.19, str(mesh_out))
    sheet0 = list(p["sheet"])
    if p["one_sheet"]:                              # one strip as wide as the sheet, as long as it needs: nest against a huge height
        p["sheet"] = [sheet0[0], ONE_SHEET_H]
    # build → section → check; with autofix = add, floating regions get a crossing slice and we build again (2 rounds)
    for attempt in range(3):
        # A second pass repeats these stages, which used to send the bar back to 20 % with no word about why. Each
        # extra pass gets a band of its own near the end instead, so the bar only moves forward, and every stage of
        # it says which pass it is and how many there can be.
        _run.band = (0.0, 1.0) if not attempt else (0.7 + 0.08 * (attempt - 1), 0.7 + 0.08 * attempt)
        again = "" if not attempt else f"{DETAIL}pass {attempt + 1} of 3, holding the parts that float"
        progress("placing slices and slots" + again, 0.2)
        ctx = Ctx(mesh, p)
        slices = mode.build(ctx)
        kept, shaved, grazed, trimmed = _profiles(slices, mesh, p, again)
        mode.guide_outlines(ctx, kept)                # on the finished outlines: grown, slivers shed
        dropped = [s for s in slices if s not in kept and s.label not in grazed]
        slices = kept
        progress("checking the parts and the assembly" + again, 0.7)
        n_err, n_warn = check_plan(slices, p, mesh, ctx.span)
        if p["autofix"] != "add" or not n_err or attempt == 2:
            break
        adds = crossing_suggestions(slices, ctx, mode)
        if not adds:
            break
        for s in adds:                          # merge the suggested parameter changes (extra slice positions, ring count …)
            for k, v in s.items():
                p[k] = sorted(set(map(float, p[k])) | set(map(float, v))) if isinstance(v, list) else v
        notes.append(f"auto-fix: added crossing slices ({len(adds)}) so every region is held")
    _run.band = (0.0, 1.0)                          # the passes are over: the last stages own the rest of the bar
    if trimmed:
        notes.append(f"{trimmed} thin spot(s) trimmed off the parts (trim_thin): a tip or sliver too thin for too long, which would have broken off — the part ends blunt there, a little short of the model")
    if shaved:
        notes.append(f"{shaved} sliver(s) thinner than {p['min_feature']:g} mm everywhere left out: shavings a slot cuts off its own part, "
                     f"and specks under {p['min_part']:g} mm where a slice only grazes the surface — too small to cut or handle")
    suggest_fixes(slices, p, ctx, mode)
    n_err += len(ctx.errors) + len(dropped)

    # split + pack
    progress("nesting the parts on sheets", 0.85)
    for sl in slices:
        if p["split"] and sl.facets is None:
            split_slice(sl, p["sheet"], p["sheet_margin"], p["tab"], p["grain"])
        else:
            sl.pieces = islands(sl) if sl.facets is None else [Piece(sl.label, sl.profile, sl, sl.lines, sl.marks)]   # a folded net stays whole
    n_err += _oversize(slices, p, sheet0, mesh, ctx)
    pieces = [pc for sl in slices for pc in sl.pieces]
    if p["orient_mark"]:                               # the same two directions on every part: which way is up, which face is the front
        for pc in pieces:                               # placed after the dowel and seam marks, in the room they leave
            pc.lines = pc.lines + orient_arrows(pc.geom, keep=[mark_box(*m[:3], p["font"], mark_rot(m)) for m in pc.marks])
    kerf = p["kerf"] if p["compensate"] else 0.0       # off by default: many machines compensate their own kerf
    tag = label_tag(p, model_path)                     # the model's name, engraved before every label: nested with room for it
    n_sheets = nest(pieces, p["sheet"], p["gap"], p["sheet_margin"], kerf, p["labels"], p["font"], tag, p["label_place"], p["grain"])
    if crowded := [pc.label for pc in pieces if pc.crowded]:
        notes.append(f"no free spot beside {len(crowded)} part(s) for their labels ({', '.join(crowded[:6])}{'…' if len(crowded) > 6 else ''}): "
                     "they sit on the part, overrunning it where it is small — a smaller font, a bigger gap or sheet, or `label_model` off gives them room")
    mark_identical(pieces, p["mirror_ok"], grain=p["grain"])   # which parts are the same part: one cut file, one row, a quantity
    # puzzle mode: what gets engraved is a code with no order in it. The plan keeps the real labels — the app, the
    # checks and the 3D view are the "plans" you consult when you give up — and the export carries the key.
    codes = label_codes([pc.label for pc in pieces], f"{pathlib.Path(model_path).name}|{mode_name}") if p["label_style"] == "code" else {}
    sheet_thick = [p["thickness"]] * n_sheets           # the stock each sheet is cut from: nest keeps one per sheet
    for pc in pieces:
        sheet_thick[pc.place[0]] = pc.parent.thickness
    sheet_out = sheet0
    if p["one_sheet"]:                              # report the strip at the length the parts and their labels actually took
        top = max([pc.placed.bounds[3] for pc in pieces] + [pc.label_pos[1] + p["font"] * 0.7 for pc in pieces if pc.label_pos], default=0.0) + p["sheet_margin"]
        sheet_out = [sheet0[0], float(np.ceil(top))]; p["sheet"] = sheet0
    progress("measuring coverage", 0.94)
    cov = coverage(mesh if ctx.clip is None else mesh.slice_plane(*ctx.clip), slices, ctx.cover_r or max(mesh.extents) / 8, lat=max(3.0, p["thickness"]))
    progress("done", 1.0)
    if ctx.notes_extra:
        notes.append(ctx.notes_extra)
    if cov < 0.9 and (slices or not ctx.errors):    # stopped before the first slice: the error says why, not this
        notes.append(f"model coverage {cov:.0%}: parts of the model have no geometry — more slices (count / spacing), a different axis, or round/thicken thin features")

    plan = {
        "model": str(pathlib.Path(model_path).resolve()), "mode": mode_name, "params": p, "notes": notes,
        "legend": mode.legend,                                               # what the labels mean (Export tab, assembly key)
        "bbox": [float(e) for e in mesh.extents],
        "axes": [a.tolist() for a in ctx.ax], "mid": ctx.mid.tolist(),      # slicing frame (for click-placed points in the UI)
        "curve3d": ctx.curve3d, "curve_pts": ctx.curve_pts,
        "axes3d": ctx.axes3d,                                                # radial's fan axes, curve's branches: drawn and dragged in 3D
        "clip": ctx.clip,                                                    # plaque: the plate's front face [point, normal]; the model behind it is not shown
        "bounds3d": ctx.bounds3d,                                            # the planes between lobes or at a branch's joint, moved and tilted like slices
        "spacing": ctx.spacing,                                              # what the drawn spacing curves gave: positions along each axis, for the graph
        "rods": ctx.rods,                                                    # dowel rods for the 3D view and the key: [[x0,y0,z0],[x1,y1,z1],d,section [[x,y]…] in the slice's x/y,slice x axis,name (Z-3a),from slice,to slice]
        "params_used": {k: p[k] for k in ("extra_x", "extra_y", "ring_count") if k in p},   # what autofix=add changed
        "sheets": n_sheets, "sheet": sheet_out, "sheet_thick": sheet_thick, "kerf": kerf,
        "counts": {"slices": len(slices), "parts": len(pieces), "errors": n_err, "warnings": n_warn, "faces": int(len(mesh.faces))},
        "codes": codes,                                                      # puzzle mode: engraved code → real label
        "label_tag": tag,                                                    # engraved before every label (the model's name)
        "errors": ctx.errors, "fixes": ctx.fixes,                            # mode-level errors and their one-click fixes
        "square": square and {"rotate": square[0], "off": round(square[1], 1)},   # a boxy model a few degrees off its axes
        "material_area_mm2": float(sum(pc.geom.area for pc in pieces)),
        "coverage": cov,
        "timing": timing(),
        "core_d_min": ctx.core_d_min,
        "sheet_usage": float(sum(pc.geom.area for pc in pieces) / max(1e-9, n_sheets * sheet_out[0] * sheet_out[1])),
        "slices": [_slice_json(sl) for sl in slices],
        "dropped": [{"label": s.label, "errors": s.errors} for s in dropped],
    }
    if out:
        out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(plan))
    return plan


def _profiles(slices, mesh, p, again):
    """Each slice sectioned and its cuts taken out: the kept slices with `profile` set, how many slivers came off, and
    the labels of slices that only grazed the model (a speck, not a part, not an error). A slice the plane misses, or
    whose cuts leave nothing, says so and is dropped."""
    kept, shaved, grazed, trimmed = [], 0, set(), 0
    for i, sl in enumerate(slices):         # sections → profiles (modes may hand over a finished `raw` for synthetic parts)
        progress(f"sectioning{DETAIL}{i + 1} of {len(slices)}{again}", 0.35 + 0.35 * i / len(slices))
        sectioned = sl.group in STRUCTURAL       # a plane through the model, not a part the technique draws (peg, panel, strip)
        if sl.raw is None:
            raw = section_polygons(mesh, sl.M)
            if sl.clip is not None:
                raw = as_multi(raw.intersection(sl.clip))
            sl.raw = raw
        if sl.raw.is_empty:
            sl.errors.append("plane does not hit material — dropped")
            continue
        g = dict(p["grow"]).get(sl.label)
        if g:                                    # per-slice outline growth (fix for thin bridges)
            sl.raw = as_multi(sl.raw.buffer(float(g), join_style=1))
        prof = as_multi(sl.raw.difference(unary_union(sl.cuts))) if sl.cuts else sl.raw
        if sectioned and not prof.is_empty:
            prof, n = shed_slivers(sl.raw, prof, sl.cuts, p["min_feature"], p["min_part"])
            shaved += n
            if p.get("trim_thin") and not prof.is_empty:
                prof, n = trim_thin(prof, p["min_feature"])
                trimmed += n
            if prof.is_empty:                    # a speck and nothing else: not a part, not an error
                grazed.add(sl.label)
                continue
        if prof.is_empty:
            sl.errors.append("slots/holes remove all material — dropped")
            continue
        sl.profile = prof
        kept.append(sl)
    return kept, shaved, grazed, trimmed


def _oversize(slices, p, sheet0, mesh, ctx):
    """Every finished piece, however it was made, has to fit the sheet: a part that does not overhangs the drawing and
    takes a sheet to itself, so it is an error whether or not `split` was asked to cut it — with the size the model
    would have to be for its parts to fit, so "too big for my sheet" comes with the number. Returns the errors added."""
    over = [(sl, pc, *min_dims(pc.geom)) for sl in slices for pc in sl.pieces      # rotation is free on the sheet
            if not fits_rotated(pc.geom, p["sheet"], p["sheet_margin"], p["grain"])]
    if not over:
        return 0
    sw, sh = p["sheet"][0] - 2 * p["sheet_margin"], p["sheet"][1] - 2 * p["sheet_margin"]
    if p["grain"]:                                  # the part as it stands: its width on the sheet's, its height on the sheet's
        over = [(sl, pc, b[3] - b[1], b[2] - b[0]) for sl, pc, *_ in over for b in [pc.geom.bounds]]
        f = min(min(sw / w, sh / h) for _, _, h, w in over)
    else:
        long_s, short_s = sorted((sw, sh), reverse=True)
        f = min(min(long_s / large, short_s / small) for _, _, small, large in over)
    fit = [round(float(e) * f, 1) for e in mesh.extents]
    fit_txt = " × ".join(f"{v:g}" for v in fit)
    for sl, pc, small, large in over:
        e = (f"{pc.label} does not fit the sheet ({large:.0f}×{small:.0f} mm on {sheet0[0]:g}×{sheet0[1]:g} mm) — "
             + ("split cannot cut a folded panel: use a smaller facet size or a bigger sheet" if sl.facets is not None
                else "enable split or use a bigger sheet" if not p["split"]
                else "even split cannot cut it small enough: use a bigger sheet or a smaller model"))
        sl.errors.append(e)
        # suggest_fixes has already run (the pieces only exist here), so this error brings its own fixes
        sl.fixes.append({"error": e, "options": ([] if p["split"] else [{"title": "split oversize parts", "set": {"split": True}}])
                         + [{"title": f"scale the model to {f:.0%} ({fit_txt} mm)", "set": {"scale": round(p["scale"] * f, 4)}}]
                         + ([] if p["one_sheet"] else [{"title": "one long sheet (cut the strip apart at the machine)", "set": {"one_sheet": True}}])})
    ctx.errors.append(f"{len(over)} part(s) are bigger than the {sheet0[0]:g} × {sheet0[1]:g} mm sheet: "
                      f"set `size` to about {fit_txt} mm ({f:.0%} of this model)"
                      + (", or use a bigger sheet" if p["one_sheet"] else ", use a bigger sheet, or turn on `one_sheet`"))
    return len(over) + 1


def _slice_json(sl):
    """A slice and its pieces as the plan carries them: the page, the 3D view, the checks and the export read this."""
    return {
        "label": sl.label, "group": sl.group, "M": np.round(sl.M, 6).tolist(), "thickness": sl.thickness, "note": sl.note,
        "engages": sl.engages, "extents": [round(sl.bbox[2] - sl.bbox[0], 2), round(sl.bbox[3] - sl.bbox[1], 2)],
        "errors": sl.errors, "warnings": sl.warnings, "fixes": sl.fixes,
        "pieces": [{"label": pc.label, "place": list(pc.place), "bbox": [round(b, 3) for b in pc.bbox],
                    "facets": [{"M": np.round(M, 6).tolist(), "rings": poly_coords(g)} for M, g in pc.facets],   # 3D view
                    "kerfed": poly_coords(pc.kerfed),        # local 2D, kerf applied (per-piece export)
                    "placed": poly_coords(pc.placed),        # sheet coordinates, kerf applied
                    "lines": [[s, line_coords(l)[0]] for s, l in pc.placed_lines],   # fold and guide lines on the sheet
                    "kerfed_lines": [[s, line_coords(l)[0]] for s, l in pc.lines],   # the same in the part's own frame (per-piece export)
                    "marks": [[round(m[0], 3), round(m[1], 3), m[2], round(mark_rot(m), 2)] for m in pc.placed_marks],
                    "kerfed_marks": [[round(m[0], 3), round(m[1], 3), m[2], round(mark_rot(m), 2)] for m in pc.marks],
                    "label_pos": pc.label_pos, "label_size": pc.label_size, "label_short": pc.label_short, "leader": pc.leader, "same": pc.same, "flipped": pc.flipped,
                    "area": round(float(pc.geom.area), 3),   # net of holes and slots: × its slice's thickness × density = its weight
                    } for pc in sl.pieces],
    }


def parse_set(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("model")
    ap.add_argument("--mode", choices=sorted(MODES), default="stacked")
    ap.add_argument("--set", nargs="*", help="param=value (JSON values allowed: sheet=[300,300] thick='{\"X-1\":6}')")
    ap.add_argument("--out", default="working-files/plan")
    ap.add_argument("--list-params", action="store_true")
    a = ap.parse_args(argv)
    if a.list_params:
        for prm in MODES[a.mode].all_params():
            print(f"{prm.name:14s} {prm.type:7s} default={prm.default!r:12} {prm.help}")
        return
    plan = build(a.model, a.mode, parse_set(a.set), a.out)
    c = plan["counts"]
    print(f"{plan['mode']}: {c['slices']} slices, {c['parts']} parts, {plan['sheets']} sheet(s) ({plan['sheet_usage']:.0%} used), {c['errors']} errors, {c['warnings']} warnings")
    for n in plan["notes"]: print(f"  note  {n}")
    for e in plan["errors"]: print(f"  ERROR {e}")
    for sl in plan["slices"] + plan["dropped"]:
        for e in sl.get("errors", []): print(f"  ERROR {sl['label']}: {e}")
        for w in sl.get("warnings", []): print(f"  warn  {sl['label']}: {w}")


if __name__ == "__main__":
    main()
