"""Mesh unfolding for Folded Panels.

Panels are grown greedily from a seed face over the dual graph: the neighbour across the best remaining edge is laid
flat next to the panel unless it would overlap it (or push the panel past the sheet size) — then that edge becomes
a seam. Which edge is "best" is the strategy:
  flat   flattest dihedral first (Pepakura / Blender-style minimum-angle spanning tree)
  strip  edges most perpendicular to the model's main axis first → long strips that bend gently
         (Mitani & Suzuki 2004 strip idea; Schlickenrieder's steepest-edge cut)
  area   largest neighbour first, ties by angle (compact patches)
  auto   run all three (and two randomised orders) and keep the unfolding with the fewest panels, then the best
         sheet compactness — a bounded version of the search-based unfolders (Takahashi 2011 GA, Korpitsch 2020 SA,
         Zawallich 2024 tabu search). See docs/folded-panels.md.

Limits: greedy + multi-start. Simulated annealing / tabu over the spanning tree (Korpitsch, Zawallich) or modifying
the mesh until it unfolds (Bhargava 2024) would find better unfoldings at a higher cost.
"""
from __future__ import annotations
import heapq, math
from collections import defaultdict
import numpy as np
import shapely
from shapely.geometry import Polygon
from .geometry import frame_xy
from .checks import min_dims

STRATEGIES = ("flat", "strip", "area")


def face_frames(mesh):
    """Per face: 4x4 frame (origin = vertex 0, z = outward normal) and the triangle in that frame (F,3,2)."""
    V = mesh.vertices[mesh.faces]
    N = mesh.face_normals
    u = V[:, 1] - V[:, 0]; u = u / np.linalg.norm(u, axis=1)[:, None]
    v = np.cross(N, u)
    d = V - V[:, :1]
    local = np.stack([np.einsum("fij,fj->fi", d, u), np.einsum("fij,fj->fi", d, v)], -1)
    frames = [frame_xy(V[f, 0], u[f], v[f]) for f in range(len(V))]
    return frames, local


def rigid(la, lb, La, Lb):
    """2D rotation R and translation t with R@la + t = La and R@lb + t = Lb."""
    th = math.atan2(*(Lb - La)[::-1]) - math.atan2(*(lb - la)[::-1])
    c, s = math.cos(th), math.sin(th)
    R = np.array([[c, -s], [s, c]])
    return R, La - R @ la


def cloud_dims(pts):
    """Side lengths of the smallest rotated rectangle around a point cloud (sorted)."""
    return min_dims(shapely.MultiPoint(pts).oriented_envelope)


class Panel:
    def __init__(self):
        self.faces = []            # face indices, in the order they were attached
        self.R, self.t = {}, {}    # face → layout transform (2x2, 2)
        self.tri = {}              # face → (3,2) layout coordinates
        self.union = None          # shapely polygon of the layout
        self.folds = []            # adjacency indices of the fold edges inside the panel

    def to_local(self, f, geom):
        """Layout geometry → the face's own 2D frame (inverse rigid transform)."""
        from shapely import affinity
        R, t = self.R[f], self.t[f]
        o = -R.T @ t
        return affinity.affine_transform(geom, [R[0, 0], R[1, 0], R[0, 1], R[1, 1], o[0], o[1]])


def edge_weights(mesh, strategy, rng=None):
    """Priority per adjacency edge (lower = attach earlier)."""
    ang = mesh.face_adjacency_angles
    if strategy == "flat":
        w = ang.copy()
    elif strategy == "strip":
        e = mesh.vertices[mesh.face_adjacency_edges[:, 1]] - mesh.vertices[mesh.face_adjacency_edges[:, 0]]
        e /= np.linalg.norm(e, axis=1)[:, None] + 1e-12
        axis = np.linalg.svd(mesh.vertices - mesh.vertices.mean(0), full_matrices=False)[2][0]   # main axis of the model
        w = np.abs(e @ axis) + 0.1 * ang                # edges perpendicular to the axis first → strips along it
    else:                                              # area: big faces first (ties by angle)
        area = mesh.area_faces
        w = -np.minimum(area[mesh.face_adjacency[:, 0]], area[mesh.face_adjacency[:, 1]]) / area.max() + 0.5 * ang / math.pi
    if rng is not None:
        w = w + rng.uniform(0, 0.15, len(w))
    return w


def unfold_once(mesh, split, max_faces, max_dims, weights, local):
    adj, aedges = mesh.face_adjacency, mesh.face_adjacency_edges
    nb = defaultdict(list)
    for k, (a, b) in enumerate(adj):
        nb[a].append((weights[k], b, k)); nb[b].append((weights[k], a, k))
    visited, panels, tree = set(), [], set()
    faces = [list(f) for f in mesh.faces]
    for seed in np.argsort(-mesh.area_faces):
        seed = int(seed)
        if seed in visited:
            continue
        pn = Panel(); visited.add(seed); pn.faces.append(seed)
        pn.R[seed], pn.t[seed], pn.tri[seed] = np.eye(2), np.zeros(2), local[seed].copy()
        # The panel is a list of triangles with their bounding boxes, not a running union: a candidate is screened on
        # boxes (numpy), tested only against the few triangles it could touch, and the union is built once at the
        # end. Re-unioning a polygon that grows to hundreds of vertices per accepted face dominates the build time.
        tris = [Polygon(pn.tri[seed])]
        boxes = np.array([tris[0].bounds])
        pts = [pn.tri[seed]]
        heap = [] if split else [(a, seed, f, k) for a, f, k in nb[seed]]
        heapq.heapify(heap)
        while heap and (not max_faces or len(pn.faces) < max_faces):
            a, fr, to, k = heapq.heappop(heap)
            if to in visited:
                continue
            va, vb = aedges[k]
            fa, fb = faces[fr], faces[to]
            La, Lb = pn.tri[fr][fa.index(va)], pn.tri[fr][fa.index(vb)]
            la, lb = local[to][fb.index(va)], local[to][fb.index(vb)]
            R, t = rigid(la, lb, La, Lb)
            tri = (R @ local[to].T).T + t
            poly = Polygon(tri)
            if not poly.is_valid:
                continue
            # overlap is judged per triangle: neighbours share an edge (area 0), but a fan wrapping past 360° at a
            # saddle vertex genuinely overlaps
            b = poly.bounds
            near = np.nonzero((boxes[:, 0] < b[2] - 1e-9) & (boxes[:, 2] > b[0] + 1e-9)
                              & (boxes[:, 1] < b[3] - 1e-9) & (boxes[:, 3] > b[1] + 1e-9))[0]
            if any(poly.intersection(tris[i]).area > 1e-4 for i in near):
                continue                                    # would overlap → seam
            if max_dims:
                # a panel whose axis-aligned box fits the sheet certainly fits; only when it does not is the
                # minimum rotated rectangle worth computing (it may still fit at an angle)
                bb = (min(boxes[:, 0].min(), b[0]), min(boxes[:, 1].min(), b[1]),
                      max(boxes[:, 2].max(), b[2]), max(boxes[:, 3].max(), b[3]))
                w, h = bb[2] - bb[0], bb[3] - bb[1]
                if not ((w <= max(max_dims) and h <= min(max_dims)) or (w <= min(max_dims) and h <= max(max_dims))):
                    sm, lg = cloud_dims(np.vstack(pts + [tri]))
                    if sm > min(max_dims) or lg > max(max_dims):
                        continue                            # would not fit the sheet → seam
            visited.add(to); pn.faces.append(to)
            pn.R[to], pn.t[to], pn.tri[to] = R, t, tri
            tris.append(poly); boxes = np.vstack([boxes, b]); pts.append(tri)
            pn.folds.append(k); tree.add(k)
            for a2, f2, k2 in nb[to]:
                if f2 not in visited:
                    heapq.heappush(heap, (a2, to, f2, k2))
        # Fixed-precision overlay: plain unary_union silently loses area on thin sliver triangles (5-9 % of a torus
        # panel in measured cases), which would shrink the exported outline. A 1 nm grid is far below any cutting
        # tolerance.
        pn.union = shapely.union_all(tris, grid_size=1e-6)
        panels.append(pn)
    seams = [k for k in range(len(adj)) if k not in tree]
    return panels, seams


def unfold(mesh, split=False, max_faces=0, max_dims=None, strategy="flat"):
    """→ (frames, local, panels, seams). seams = adjacency indices that are NOT folds (need a joint).
    strategy: flat | strip | area | auto (best of all, plus two randomised runs; only for ≤ 800 faces)."""
    frames, local = face_frames(mesh)
    if split:
        panels, seams = unfold_once(mesh, True, max_faces, max_dims, edge_weights(mesh, "flat"), local)
        return frames, local, panels, seams
    runs = [(s, None) for s in STRATEGIES] + [("flat", 1), ("flat", 2)] if strategy == "auto" and len(mesh.faces) <= 800 else [(strategy if strategy != "auto" else "flat", None)]
    best = None
    for strat, seed in runs:
        w = edge_weights(mesh, strat, np.random.default_rng(seed) if seed else None)
        panels, seams = unfold_once(mesh, False, max_faces, max_dims, w, local)
        # fewest panels, then most compact (union area / bounding-rectangle area, summed)
        compact = sum(pn.union.area / max(np.prod(min_dims(pn.union)), 1e-9) for pn in panels) / len(panels)
        score = (len(panels), -compact)
        if best is None or score < best[0]:
            best = (score, panels, seams)
    _, panels, seams = best
    return frames, local, panels, seams


def refold_error(mesh, frames, local, panels):
    """Test helper. A layout folds back into the mesh iff (a) every layout triangle is congruent to its 3D face and
    (b) the two faces of every fold share the edge endpoints in the layout. Returns the worst deviation in mm."""
    worst = 0.0
    faces = [list(f) for f in mesh.faces]
    for pn in panels:
        for f in pn.faces:
            P3 = mesh.vertices[mesh.faces[f]]; P2 = pn.tri[f]
            for i in range(3):
                worst = max(worst, abs(np.linalg.norm(P3[i] - P3[(i + 1) % 3]) - np.linalg.norm(P2[i] - P2[(i + 1) % 3])))
        for k in pn.folds:
            fa, fb = mesh.face_adjacency[k]; va, vb = mesh.face_adjacency_edges[k]
            for v in (va, vb):
                worst = max(worst, float(np.linalg.norm(pn.tri[fa][faces[fa].index(v)] - pn.tri[fb][faces[fb].index(v)])))
    return worst
