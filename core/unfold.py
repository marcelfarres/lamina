"""Mesh unfolding for Folded Panels.

Panels are grown greedily from a seed face over the dual graph: the neighbour across the best remaining edge is laid
flat next to the panel unless it would overlap it, lie in the room a glue flap needs (tab joints), or push the panel
past the sheet size — then that edge becomes a seam. Which edge is "best" is the strategy:
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
from .geometry import frame_xy, min_dims

STRATEGIES = ("flat", "strip", "area")
FLAT = math.radians(1)                # two faces closer to one plane than this are one flat piece: no score between them


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


class Panel:
    def __init__(self):
        self.faces = []            # face indices, in the order they were attached
        self.R, self.t = {}, {}    # face → layout transform (2x2, 2)
        self.tri = {}              # face → (3,2) layout coordinates
        self.union = None          # shapely polygon of the layout
        self.folds = []            # adjacency indices of the fold edges inside the panel
        self.parent = {}           # face → (the face it was laid out from, the adjacency index of the fold between them)

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


def contact(tri, fat, corners):
    """How far (mm) triangle `tri`'s outline runs within a hair of another face (`fat`, that face grown by the hair),
    not counting the 2 mm round the corners the two share: two faces that meet at a sharp point run close there."""
    near = tri.boundary.intersection(fat)
    for c in corners:
        near = near.difference(shapely.Point(c).buffer(2))
    return near.length


TAN_FLAP = math.tan(math.radians(30))


def flap_zone(tri, i, flap):
    """The room a glue flap takes outside edge i → i+1 of a laid-out triangle: the trapezoid folded.tabs draws there
    (from 8 % to 92 % of the edge, sides at 30°), `flap` high but no more than 0.6 of the edge."""
    A, B, C = (np.asarray(tri[(i + k) % 3], float) for k in range(3))
    L = float(np.linalg.norm(B - A)); d = (B - A) / L; n = np.array([-d[1], d[0]])
    if np.dot(C - A, n) > 0:
        n = -n                                          # away from the triangle
    h = min(flap, 0.6 * L); ti = min(h * TAN_FLAP, 0.84 * L * 0.4)
    x0, x1 = A + d * 0.08 * L, A + d * 0.92 * L
    return Polygon([x0, x1, x1 - d * ti + n * h, x0 + d * ti + n * h])


def flat_pieces(mesh, local, chosen, max_dims):
    """The flat pieces of the model: faces that lie in one plane and are joined edge to edge (no edge between them bends
    by FLAT or more, and none is a seam the user chose). A panel takes a flat piece whole or not at all, so no seam cuts
    across a flat side (a box side, a pentagon of a dodecahedron) and the side keeps one window. A flat piece that does
    not fit the sheet is left as single faces: it cannot be one part.
    Returns (face → the faces of its flat piece, face → its flat edges inside the piece)."""
    adj, ang = mesh.face_adjacency, mesh.face_adjacency_angles
    edges_of = defaultdict(list)
    for k in np.nonzero(ang < FLAT)[0]:
        if int(k) not in chosen:
            a, b = (int(f) for f in adj[k]); edges_of[a].append(int(k)); edges_of[b].append(int(k))
    piece, seen = {}, set()
    for f0 in list(edges_of):
        if f0 in seen:
            continue
        laid = lay_flat(mesh, local, edges_of, f0, np.eye(2), np.zeros(2))
        seen.update(laid)
        if max_dims:
            small, large = min_dims(shapely.MultiPoint(np.vstack([t for _, _, t, _ in laid.values()])))
            if small > min(max_dims) or large > max(max_dims):
                continue
        for f in laid:
            piece[f] = list(laid)
    return piece, edges_of


def lay_flat(mesh, local, edges_of, start, R, t):
    """The flat piece of face `start` laid out from `start` placed by (R, t), breadth first across its flat edges:
    face → (R, t, its triangle, (the face it hangs from, the edge between them), None for `start`)."""
    adj, aedges, faces = mesh.face_adjacency, mesh.face_adjacency_edges, mesh.faces
    out = {start: (R, t, (R @ local[start].T).T + t, None)}; todo = [start]
    while todo:
        p = todo.pop(0)
        for k in edges_of[p]:
            s = int(adj[k][1] if adj[k][0] == p else adj[k][0])
            if s in out:
                continue
            va, vb = aedges[k]; fp, fs = list(faces[p]), list(faces[s])
            R2, t2 = rigid(local[s][fs.index(va)], local[s][fs.index(vb)], out[p][2][fp.index(va)], out[p][2][fp.index(vb)])
            out[s] = (R2, t2, (R2 @ local[s].T).T + t2, (p, k)); todo.append(s)
    return out


def unfold_once(mesh, split, max_faces, max_dims, weights, local, chosen=frozenset(), flap=0.0):
    """`chosen`: the adjacency indices of the seams the user chose. No panel grows across one. `flap` (mm): a joint
    with a glue flap needs room for it outside the edge, on one panel or the other: every free edge of a panel keeps
    that room clear, so no face is laid where a flap must go and no face is laid whose own free edges have no room
    (a cow grown without it had 40 of its 217 seams with no room for a tab on either side). 0 = no flaps.
    A face of a flat piece (flat_pieces) comes with the rest of its piece, and every test below holds for all of them
    or none is laid."""
    adj, aedges = mesh.face_adjacency, mesh.face_adjacency_edges
    nb = defaultdict(list)
    for k, (a, b) in enumerate(adj):
        if k in chosen:
            continue
        nb[a].append((weights[k], b, k)); nb[b].append((weights[k], a, k))
    piece, edges_of = ({}, {}) if split else flat_pieces(mesh, local, chosen, max_dims)
    visited, panels, tree = set(), [], set()
    faces = [list(f) for f in mesh.faces]

    def room(cands, members):
        """The flap room of each free edge of the faces `cands` lays: (face, its two vertices) → zone. An edge to the
        face it hangs from, or to another face of its flat piece, is no free edge."""
        out = {}
        for f, _, _, tri, par in cands:
            inner = {frozenset(aedges[k]) for k in edges_of.get(f, ()) if int(adj[k][0] if adj[k][1] == f else adj[k][1]) in members}
            if par:
                inner.add(frozenset(aedges[par[1]]))
            fb = faces[f]
            for i in range(3):
                e = frozenset((fb[i], fb[(i + 1) % 3]))
                if e not in inner:
                    out[(f, e)] = flap_zone(tri, i, flap)
        return out

    def fits(new, members):
        """Whether the faces `new` (a face, or a flat piece) may all be laid: none overlaps the panel or lies against a
        face of it that is not its neighbour, none lies where a flap must go or leaves an edge of its own no room for one,
        and the panel still fits the sheet."""
        polys = [Polygon(c[3]) for c in new]
        if not all(q.is_valid for q in polys):
            return False
        for (f, _, _, tri, _), poly in zip(new, polys):
            # overlap is judged per triangle: neighbours share an edge (area 0), but a fan wrapping past 360° at a
            # saddle vertex genuinely overlaps
            b = poly.bounds
            near = np.nonzero((boxes[:, 0] < b[2] - 1e-9) & (boxes[:, 2] > b[0] + 1e-9)
                              & (boxes[:, 1] < b[3] - 1e-9) & (boxes[:, 3] > b[1] + 1e-9))[0]
            if any(poly.intersection(tris[i]).area > 1e-4 for i in near):
                return False                                # would overlap → seam
            # … and it may not lie against a face that is not its neighbour on the model: laid edge to edge, the outline
            # joins the two along that line, a cut is lost, and the face is held on two sides and cannot fold
            touch = np.nonzero((boxes[:, 0] <= b[2] + 1e-6) & (boxes[:, 2] >= b[0] - 1e-6)
                               & (boxes[:, 1] <= b[3] + 1e-6) & (boxes[:, 3] >= b[1] - 1e-6))[0]
            mates = {f2 for _, f2, _ in nb[f]}
            fat = poly.buffer(0.01)                         # two edges meet only to rounding: within a hair of each other
            fb = faces[f]
            if any(pn.faces[i] not in mates and contact(tris[i], fat, [tri[fb.index(v)] for v in fb if v in faces[pn.faces[i]]]) > 1.0 for i in touch):
                return False                                # → seam
        if flap:
            joined = {(p, frozenset(aedges[k])) for *_, (p, k) in new}   # these edges become folds: their flap room is no longer needed
            if any(key not in joined and shapely.intersects(z, q) and q.intersection(z).area > 0.02 * z.area for key, z in zones.items() for q in polys):
                return False                                # it would lie where another edge's flap goes → seam
            for key, z in room(new, members).items():
                zb = z.bounds
                if any(z.intersection(tris[i]).area > 0.02 * z.area
                       for i in np.nonzero((boxes[:, 0] < zb[2]) & (boxes[:, 2] > zb[0]) & (boxes[:, 1] < zb[3]) & (boxes[:, 3] > zb[1]))[0]):
                    return False                            # its own free edges would have no room for a flap → seam
                if any(c[0] != key[0] and z.intersection(q).area > 0.02 * z.area for c, q in zip(new, polys)):
                    return False
        if max_dims:
            # a panel whose axis-aligned box fits the sheet certainly fits; only when it does not is the minimum rotated
            # rectangle worth computing (it may still fit at an angle)
            bb = (min(boxes[:, 0].min(), *(q.bounds[0] for q in polys)), min(boxes[:, 1].min(), *(q.bounds[1] for q in polys)),
                  max(boxes[:, 2].max(), *(q.bounds[2] for q in polys)), max(boxes[:, 3].max(), *(q.bounds[3] for q in polys)))
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            if not ((w <= max(max_dims) and h <= min(max_dims)) or (w <= min(max_dims) and h <= max(max_dims))):
                sm, lg = min_dims(shapely.MultiPoint(np.vstack(pts + [c[3] for c in new])))
                if sm > min(max_dims) or lg > max(max_dims):
                    return False                            # would not fit the sheet → seam
        return True

    for seed in np.argsort(-mesh.area_faces):
        seed = int(seed)
        if seed in visited:
            continue
        pn = Panel()
        if seed in piece and max_faces and len(piece[seed]) > max_faces:   # a flat piece of more faces than a panel may have: face by face
            for f in piece[seed]:
                piece.pop(f)
        whole = seed in piece
        laid = lay_flat(mesh, local, edges_of, seed, np.eye(2), np.zeros(2)) if whole else {seed: (np.eye(2), np.zeros(2), local[seed].copy(), None)}
        cands = [(f, *v) for f, v in laid.items()]
        # The panel is a list of triangles with their bounding boxes, not a running union: a candidate is screened on
        # boxes (numpy), tested only against the few triangles it could touch, and the union is built once at the
        # end. Re-unioning a polygon that grows to hundreds of vertices per accepted face dominates the build time.
        tris, boxes, pts = [], np.zeros((0, 4)), []
        zones = room(cands, set(laid)) if flap else {}       # the flap room of each free edge: (face, its two vertices) → zone
        heap = []
        while True:
            for f, R, t, tri, par in cands:                     # lay them
                visited.add(f); pn.faces.append(f)
                pn.R[f], pn.t[f], pn.tri[f] = R, t, tri
                poly = Polygon(tri); tris.append(poly); boxes = np.vstack([boxes, poly.bounds]); pts.append(tri)
                if par:
                    pn.folds.append(par[1]); tree.add(par[1]); pn.parent[f] = par
                if not split:
                    for a2, f2, k2 in nb[f]:
                        if f2 not in visited:
                            heapq.heappush(heap, (a2, f, f2, k2))
            cands = None
            while heap and (not max_faces or len(pn.faces) < max_faces):
                a, fr, to, k = heapq.heappop(heap)
                if to in visited:
                    continue
                va, vb = aedges[k]
                fa, fb = faces[fr], faces[to]
                R, t = rigid(local[to][fb.index(va)], local[to][fb.index(vb)], pn.tri[fr][fa.index(va)], pn.tri[fr][fa.index(vb)])
                laid = lay_flat(mesh, local, edges_of, to, R, t) if to in piece else {to: (R, t, (R @ local[to].T).T + t, None)}
                new = [(f, R2, t2, tri, par or (fr, k)) for f, (R2, t2, tri, par) in laid.items()]
                if max_faces and len(new) > 1 and len(pn.faces) + len(new) > max_faces:
                    continue                                    # the flat piece would take the panel past its face count → seam
                if fits(new, set(laid)):
                    cands = new
                    break
            if cands is None:
                break
            if flap:
                for *_, (p, k) in cands:                      # these edges are folds now: their flap room is no longer needed
                    zones.pop((p, frozenset(aedges[k])), None)
                zones.update(room(cands, {c[0] for c in cands}))
        # Fixed-precision overlay: plain unary_union silently loses area on thin sliver triangles (5-9 % of a torus
        # panel in measured cases), which would shrink the exported outline. A 1 nm grid is far below any cutting
        # tolerance.
        pn.union = shapely.union_all(tris, grid_size=1e-6)
        panels.append(pn)
    # A panel is grown as a tree, so an edge that closes a loop in it (the sixth spoke of a flat hexagon cap) was never
    # walked. Where both of its faces already lie edge to edge in the layout the sheet is whole there: a fold like
    # any other, not a seam asking for a joint on an edge nobody cuts.
    own = {f: pn for pn in panels for f in pn.faces}
    for k, (a, b) in enumerate(adj):
        pn = own[a]
        if k not in tree and k not in chosen and own[b] is pn and all(
                np.abs(pn.tri[a][faces[a].index(v)] - pn.tri[b][faces[b].index(v)]).max() < 1e-6 for v in aedges[k]):
            pn.folds.append(k); tree.add(k)
    seams = [k for k in range(len(adj)) if k not in tree]
    return panels, seams


def unfold(mesh, split=False, max_faces=0, max_dims=None, strategy="flat", chosen=frozenset(), flap=0.0):
    """→ (frames, local, panels, seams). seams = adjacency indices that are NOT folds (need a joint).
    chosen: adjacency indices that must be seams (the user's choice): the panels are laid out round them.
    strategy: flat | strip | area | auto (best of all, plus two randomised runs; only for ≤ 800 faces).
    flap: room (mm) a glue flap needs outside every free edge, see unfold_once."""
    frames, local = face_frames(mesh)
    if split:
        panels, seams = unfold_once(mesh, True, max_faces, max_dims, edge_weights(mesh, "flat"), local)
        return frames, local, panels, seams
    runs = [(s, None) for s in STRATEGIES] + [("flat", 1), ("flat", 2)] if strategy == "auto" and len(mesh.faces) <= 800 else [(strategy if strategy != "auto" else "flat", None)]
    best = None
    for strat, seed in runs:
        w = edge_weights(mesh, strat, np.random.default_rng(seed) if seed else None)
        panels, seams = unfold_once(mesh, False, max_faces, max_dims, w, local, chosen, flap)
        # fewest panels, then most compact (union area / bounding-rectangle area, summed)
        compact = sum(pn.union.area / max(np.prod(min_dims(pn.union)), 1e-9) for pn in panels) / len(panels)
        score = (len(panels), -compact)
        if best is None or score < best[0]:
            best = (score, panels, seams)
    _, panels, seams = best
    return frames, local, panels, seams


def edges_at(mesh, lines, tol=0.05):
    """The adjacency indices of the edges that `lines` ([[x, y, z], [x, y, z]], …) name by their two ends, within `tol`
    mm, and how many of the lines are no edge of this mesh: a seam chosen on the model keeps its place, not a number,
    and a mesh simplified again (another facet size, another model size) has other edges."""
    try:
        ends = np.asarray(lines, float).reshape(-1, 2, 3)
    except (TypeError, ValueError):
        return set(), len(lines)
    index = {frozenset(map(int, e)): k for k, e in enumerate(mesh.face_adjacency_edges)}
    found, lost = set(), 0
    for line in ends:
        d = np.abs(mesh.vertices[None] - line[:, None]).max(2)          # 2 ends × vertices
        at = d.argmin(1)
        k = index.get(frozenset(map(int, at))) if (d[[0, 1], at] <= tol).all() else None
        if k is None:
            lost += 1
        else:
            found.add(k)
    return found, lost


def faces_at(mesh, tris, frame=None):
    """Which faces of `mesh` lie where the triangles `tris` ([[x, y, z] × 3], …) are: a bool per face. A removed face
    keeps its place, not a number, and a mesh simplified again has other faces. A face is there when the line through
    its middle, along its own normal, meets one of the triangles that faces the same way, no further off than half
    that triangle's longest edge. Along the face's own normal: the triangles of a region lie edge to edge, so a line
    through the region meets one of them, where a flat projection onto each leaves a gap along every ridge between
    two. The same way: the far side of a thin wall is not there. `frame` (4 × 4) brings `tris` to the mesh first.
    ponytail: one pass over the faces per triangle (2000 triangles × 4000 faces is 0.2 s); a grid of the triangles
    if the lists ever get longer than the model has faces."""
    try:
        tris = np.asarray(tris, float).reshape(-1, 3, 3)
    except (TypeError, ValueError):
        tris = np.zeros((0, 3, 3))
    if frame is not None:
        tris = tris @ np.asarray(frame)[:3, :3].T + np.asarray(frame)[:3, 3]
    return points_at(mesh.triangles_center, mesh.face_normals, tris)


def points_at(mid, way, tris):
    """faces_at for any points on a surface (`mid`) with the surface's normal at each (`way`): which of them lie where
    the triangles `tris` (n × 3 × 3, in the points' coordinates) are."""
    here = np.zeros(len(mid), bool)
    for a, b, c in tris:                                     # Möller–Trumbore, every face's line against this triangle
        u, v = b - a, c - a
        n = np.cross(u, v)
        facing = way @ n                                      # 2 × its area × the cosine between the two normals
        with np.errstate(divide="ignore", invalid="ignore"):
            s = mid - a
            q = np.cross(s, u)
            bu = -np.einsum("ij,ij->i", s, np.cross(way, v)) / facing
            bv = -np.einsum("ij,ij->i", way, q) / facing
            off = -(q @ v) / facing
            reach = max(np.linalg.norm(u), np.linalg.norm(v), np.linalg.norm(c - b)) / 2
            here |= (facing > 1e-9) & (bu >= -1e-7) & (bv >= -1e-7) & (bu + bv <= 1 + 1e-7) & (np.abs(off) <= reach)
    return here


def closing_shortfall(mesh, give, folds):
    """Which of the fold edges `folds` (adjacency indices) cannot close. `give[k]` is what fold k takes off the closing
    face of each of its two faces, times its length (mm²): the inside of a mountain fold, the outside of a valley
    fold. A triangle keeps some of a face while Σ over its folds on that face ≤ 2 · its area (a point's distance to
    edge i is 2·area·λᵢ/Lᵢ in barycentric coordinates); past that the folds round it meet. Folds only: a seam edge
    is cut back or mitred, which is checked where that is done."""
    k = np.asarray(folds, int)
    side = mesh.face_adjacency_convex[k].astype(int)        # the face that closes: 1 = the inside, 0 = the outside
    need = np.zeros((2, len(mesh.faces)))
    for f in mesh.face_adjacency[k].T:
        np.add.at(need, (side, f), give[k])
    return (need[side[:, None], mesh.face_adjacency[k]] > 2 * mesh.area_faces[mesh.face_adjacency[k]]).any(1)


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
