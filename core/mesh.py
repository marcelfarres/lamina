"""The model as every later stage sees it: loaded, sized, turned, mended, modified, and kept for the next slice."""
from __future__ import annotations
import math
import pathlib
import numpy as np
import trimesh
from .progress import progress
from .remesh import modify_form

CAD_SUFFIXES = {".step", ".stp", ".brep", ".iges", ".igs"}
SQUARE_MIN, SQUARE_MAX = 0.5, 15.0   # degrees off square that square_up offers to take back


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


def cluster(m, cell):
    """Vertex clustering (Rossignac–Borrel): every vertex snaps to the mean of its grid cell and faces that fold flat
    go. Panels come out a little more angular than with quadric decimation, but it is plain numpy — the browser
    build, which has no fast-simplification wheel, decimates with this."""
    _, inv = np.unique(np.floor(m.vertices / cell).astype(np.int64), axis=0, return_inverse=True); inv = inv.ravel()
    v = np.zeros((inv.max() + 1, 3)); np.add.at(v, inv, m.vertices); v /= np.bincount(inv)[:, None]
    f = inv[m.faces]; f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    out = trimesh.Trimesh(v, f, process=True); out.update_faces(out.unique_faces())
    return out


def simplify(mesh, target):
    """Fewer faces, same shape: `target` of them, by quadric decimation, or where there is no wheel for that (the
    browser build) by vertex clustering. Folded panels are unfolded from it; the mesh every section is cut from and
    the one the preview ships are decimated by it too, since half a million faces put the browser's heap under
    enough pressure to hand GEOS a NaN."""
    m = mesh.copy()
    if target and len(m.faces) > target:
        try:
            import fast_simplification
            pts, faces = fast_simplification.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces, np.int32), target_count=int(target))
            m = trimesh.Trimesh(pts, faces, process=True)
        except ImportError:
            m = cluster(m, math.sqrt(m.area / (0.433 * target)))   # a cell per target-sized equilateral triangle
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces()); m.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(m)
    return m


MESH_PARAMS = ("up_axis", "rotate", "size", "scale", "shrinkwrap", "hollow", "thicken", "round", "smooth")   # all _prepare reads
_last = None   # [key, mesh, notes, {name: what was worked out from it}]: the model as last prepared


def load_mesh(path, params, notes=None, surface=False):
    """The model as every later stage sees it. The last one is kept: a new project name, a sheet, a thickness reslices
    without loading and remeshing it again (a second or more of every slice, many more in the browser). `surface`:
    the technique cuts the surface itself (Mode.surface), so an open edge is kept, not mended.
    ponytail: one model kept, so two server clients take turns missing it; key it per client if that ever shows."""
    global _last
    path = pathlib.Path(path)
    progress("loading the model", 0.02)
    st = path.stat()
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns, surface, repr([params.get(k) for k in MESH_PARAMS]))
    hit = _last                                     # read once: another request thread may replace it meanwhile
    if not hit or hit[0] != key:
        said = []
        hit = _last = [key, _prepare(path, params, said, surface), said, {}]
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


def _prepare(path, params, notes, surface):
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
    # into solids — the decision has to come before the repair, not after it fails: that is `surface`.
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
