"""STEP (ISO 10303-21, AP214) of a plan's parts as true solids, for CAD. A part is a flat outline with a thickness,
so its solid has planar faces only: top, bottom and one wall per outline segment. That needs no CAD kernel (the
browser build has none): the file is written as text. A CAD program then shows two clean faces per part where the
STL shows its triangles. Curved edges stay the polylines they are in the cut files: one narrow wall per segment.

    uv run python -m core.solid working-files/egg.json --out working-files/egg.step [--part X-3]
"""
from __future__ import annotations
from typing import NamedTuple
import numpy as np
from shapely.geometry.polygon import orient
from .geometry import facet_polys

HEAD = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Lamina parts as solids'),'2;1');
FILE_NAME('{name}.step','',(''),(''),'Lamina','Lamina','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN {{ 1 0 10303 214 1 1 1 1 }}'));
ENDSEC;
DATA;
"""
MIN_EDGE = 1e-6     # mm: the shortest edge written; ten times what the 7 decimals of a coordinate tell apart
ACCURACY = 1e-5     # mm: the file's distance accuracy (UNCERTAINTY_MEASURE_WITH_UNIT): points nearer are one to a CAD kernel


def _text(s) -> str:
    """A name as a STEP string: the quote and the backslash (STEP's own escape) doubled, a letter outside ASCII in
    STEP's X2 form so two names never become one, a control character (a line break would split the row) a space."""
    out = []
    for c in str(s):
        o = ord(c)
        if c in "'\\":
            out.append(c + c)
        elif 32 <= o < 127:
            out.append(c)
        elif o < 160:
            out.append(" ")
        elif o < 0x10000:
            out.append(f"\\X2\\{o:04X}\\X0\\")
        else:
            out.append(f"\\X4\\{o:08X}\\X0\\")
    return "".join(out)


def _xyz(v) -> str:
    """Reals as STEP wants them: always with the point, never an exponent. 7 decimals: 0.1 nm on a millimetre."""
    return ",".join(f"{x + 0.0:.7f}".rstrip("0") for x in np.round(np.asarray(v, float), 7))


def _unit(v):
    return v / np.linalg.norm(v)


def _ring(coords):
    """A ring's corners (x, y) without the closing repeat, without a point that repeats the one before it (nearer
    than MIN_EDGE: it has no wall, and written with 7 decimals the two would be one point) and without the points
    that lie on a straight run: each would split one flat wall into two with a line between them. By hand, not
    shapely's simplify: the one that keeps a ring valid reads bad memory in the browser build's GEOS (3.12)."""
    p = np.asarray(coords, float)[:-1, :2]
    p = p[np.linalg.norm(p - np.roll(p, 1, 0), axis=1) > MIN_EDGE]
    a, b = p - np.roll(p, 1, 0), np.roll(p, -1, 0) - p
    return p[np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) > 1e-9 * np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)]


class _Vertex(NamedTuple):
    ref: str            # the VERTEX_POINT
    point: str          # its CARTESIAN_POINT, which the lines and planes through it use too
    at: np.ndarray      # where it is


class _Step:
    """The DATA section as it grows: add() numbers an entity and returns its reference."""
    def __init__(self):
        self.rows, self.dirs = [], {}

    def add(self, entity) -> str:
        self.rows.append(entity)
        return f"#{len(self.rows)}"

    def product(self, name):
        """The product the solids belong to, in millimetres. Returns what a shape hangs on, the context it is
        measured in and the frame it stands in."""
        add = self.add
        app = add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
        add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
        mechanical = add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
        product = add(f"PRODUCT('{name}','{name}','',({mechanical}))")
        add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part','',({product}))")
        formation = add(f"PRODUCT_DEFINITION_FORMATION('','',{product})")
        design = add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
        definition = add(f"PRODUCT_DEFINITION('design','',{formation},{design})")
        shape = add(f"PRODUCT_DEFINITION_SHAPE('','',{definition})")
        mm = add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
        radian = add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
        steradian = add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
        accuracy = add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-5),{mm},'distance_accuracy_value','')")
        context = add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({accuracy}))"
                      f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({mm},{radian},{steradian}))REPRESENTATION_CONTEXT('',''))")
        origin = add("CARTESIAN_POINT('',(0.,0.,0.))")
        frame = add(f"AXIS2_PLACEMENT_3D('',{origin},{self.direction([0, 0, 1])},{self.direction([1, 0, 0])})")
        return shape, context, frame

    def direction(self, v) -> str:
        """One DIRECTION per different direction: the walls of a part share a few, and the file is a quarter smaller."""
        key = _xyz(v)
        if key not in self.dirs:
            self.dirs[key] = self.add(f"DIRECTION('',({key}))")
        return self.dirs[key]

    def vertex(self, at) -> _Vertex:
        point = self.add(f"CARTESIAN_POINT('',({_xyz(at)}))")
        return _Vertex(self.add(f"VERTEX_POINT('',{point})"), point, at)

    def edge(self, a, b) -> str:
        """The straight edge from vertex a to vertex b."""
        d = b.at - a.at
        vector = self.add(f"VECTOR('',{self.direction(_unit(d))},{_xyz([np.linalg.norm(d)])})")
        line = self.add(f"LINE('',{a.point},{vector})")
        return self.add(f"EDGE_CURVE('',{a.ref},{b.ref},{line},.T.)")

    def loop(self, edges) -> str:
        """A closed run of (edge, forward?) pairs, counter-clockwise seen from outside the solid."""
        walked = [self.add(f"ORIENTED_EDGE('',*,*,{e},.{'T' if forward else 'F'}.)") for e, forward in edges]
        return self.add(f"EDGE_LOOP('',({','.join(walked)}))")

    def face(self, loops, through, normal, ref) -> str:
        """A flat face through the vertex `through`: its outline first, then its holes; `normal` points out of the
        solid, `ref` lies in the face."""
        axes = self.add(f"AXIS2_PLACEMENT_3D('',{through.point},{self.direction(normal)},{self.direction(ref)})")
        plane = self.add(f"PLANE('',{axes})")
        bounds = [self.add(f"FACE_{'' if i else 'OUTER_'}BOUND('',{lp},.T.)") for i, lp in enumerate(loops)]
        return self.add(f"ADVANCED_FACE('',({','.join(bounds)}),{plane},.T.)")

    def wall(self, a, b, bottom, rise_b, top, rise_a, up) -> str:
        """The flat wall on the outline segment a → b: along the bottom, up at b, back along the top, down at a."""
        along = _unit(b.at - a.at)
        return self.face([self.loop([(bottom, True), (rise_b, True), (top, False), (rise_a, False)])], a, np.cross(along, up), along)

    def prism(self, name, poly, M, thickness):
        """One polygon (holes included) as a solid `thickness` thick, centred on its plane, placed with its frame M.
        None when the outline has no area left."""
        M = np.asarray(M, float)
        mirrored = np.linalg.det(M[:3, :3]) < 0                         # a mirroring frame turns every ring over
        poly = orient(poly)                                             # outline counter-clockwise, holes clockwise
        walls, top_loops, bottom_loops = [], [], []
        for k, ring in enumerate([poly.exterior, *poly.interiors]):
            p = _ring(ring.coords)
            if len(p) < 3:
                if k == 0:
                    return None
                continue
            p = p[::-1] if mirrored else p
            n = len(p)
            nxt = [(i + 1) % n for i in range(n)]
            bottom, top = ([self.vertex(at) for at in (np.c_[p, np.full(n, z), np.ones(n)] @ M.T)[:, :3]] for z in (-thickness / 2, thickness / 2))
            bottom_edges = [self.edge(bottom[i], bottom[nxt[i]]) for i in range(n)]
            top_edges = [self.edge(top[i], top[nxt[i]]) for i in range(n)]
            rises = [self.edge(bottom[i], top[i]) for i in range(n)]
            if k == 0:                                                  # the outline says which way is up, and where the flat faces lie
                up, ref, on_top, on_bottom = _unit(top[0].at - bottom[0].at), _unit(bottom[1].at - bottom[0].at), top[0], bottom[0]
            walls += [self.wall(bottom[i], bottom[nxt[i]], bottom_edges[i], rises[nxt[i]], top_edges[i], rises[i], up) for i in range(n)]
            top_loops.append(self.loop([(e, True) for e in top_edges]))
            bottom_loops.append(self.loop([(e, False) for e in reversed(bottom_edges)]))
        faces = [*walls, self.face(top_loops, on_top, up, ref), self.face(bottom_loops, on_bottom, -up, ref)]
        return self.add(f"MANIFOLD_SOLID_BREP('{_text(name)}',{self.add(f'''CLOSED_SHELL('',({','.join(faces)}))''')})")

    def shell(self, name, V, F):
        """A closed triangle mesh (V, F) as solids with flat faces, a list. A surface that encloses a positive volume is
        the outside of a solid. One piece of material (a lump of one_body) has one, and a hollow inside it (a folded box
        closes its panels round air) has a surface of its own, which STEP writes as a void: a closed shell facing into
        the hollow, taken the other way (BREP_WITH_VOIDS). Several outsides with no hollow (a standoff's pin, body and
        pin where nothing joins them, in the browser build) are a solid each."""
        import trimesh
        # an edge shorter than MIN_EDGE (a union leaves some of 1e-8 mm where solids cross) would be written as one
        # point twice: its ends become one vertex, and the triangles on it, left without area, go
        V, F = np.asarray(V, float), np.asarray(F)
        half = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
        one = trimesh.graph.connected_component_labels(half[np.linalg.norm(V[half[:, 0]] - V[half[:, 1]], axis=1) < MIN_EDGE], node_count=len(V))
        first = np.empty(one.max() + 1, int); first[one[::-1]] = np.arange(len(V))[::-1]
        F = first[one][F]
        F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 2] != F[:, 0])]
        part = trimesh.graph.connected_component_labels(trimesh.Trimesh(V, F, process=False).face_adjacency, node_count=len(F))
        surfaces = [F[part == k] for k in range(part.max() + 1)]
        volume = [np.einsum("ij,ij->", V[f[:, 0]], np.cross(V[f[:, 1]], V[f[:, 2]])) for f in surfaces]
        outsides = [f for f, v in zip(surfaces, volume) if v > 0]
        hollows = [f for f, v in zip(surfaces, volume) if v <= 0]
        if hollows and len(outsides) > 1:                # one_body gives one lump at a time: it never happens there
            raise ValueError(f"{name}: hollows inside {len(outsides)} solids, and which one holds which is not known")
        closed = lambda f: self.add(f"CLOSED_SHELL('',({','.join(self.faces(V, f))}))")   # noqa: E731
        if not outsides:                                 # a crumb a union splits off, with no volume: nothing to write
            return []
        if not hollows:
            return [self.add(f"MANIFOLD_SOLID_BREP('{_text(name)}',{closed(f)})") for f in outsides]
        voids = [self.add(f"ORIENTED_CLOSED_SHELL('',*,{closed(f[:, ::-1])},.F.)") for f in hollows]
        return [self.add(f"BREP_WITH_VOIDS('{_text(name)}',{closed(outsides[0])},({','.join(voids)}))")]

    def faces(self, V, F):
        """A closed triangle surface as flat faces: the triangles that lie side by side in one plane are one face
        (trimesh's facets). A face's edges are those of its triangles that no other of its triangles has, walked the
        way its triangles turn, so its outline runs counter-clockwise seen from the side its normal points to and its
        holes the other way; the outline is the loop with the largest area. Faces that meet share their vertices and
        edges, as a closed shell needs."""
        import trimesh
        mesh = trimesh.Trimesh(V, F, process=False)
        # A sliver (a union leaves some where solids cross) has no plane of its own worth the name: its third corner is
        # less than ACCURACY from its longest edge, so within the file's accuracy it lies on that edge, and it joins
        # the face across it. A face made of slivers only is no face. Until it joins one, a triangle has none (-1).
        side = np.linalg.norm(V[F[:, [1, 2, 0]]] - V[F], axis=2).max(1)
        flat = 2 * mesh.area_faces < ACCURACY * np.maximum(side, 1e-300)
        kept = [k for k, g in enumerate(mesh.facets) if not flat[g].all()]
        groups, normals = [list(mesh.facets[k]) for k in kept], [mesh.facets_normal[k] for k in kept]
        lone = np.setdiff1d(np.arange(len(F)), np.concatenate(groups) if groups else [])
        groups += [[i] for i in lone if not flat[i]]; normals += list(mesh.face_normals[[i for i in lone if not flat[i]]])
        group = np.full(len(F), -1); [group.__setitem__(g, k) for k, g in enumerate(groups)]
        across = {}
        for t, (a, b, c) in enumerate(F.tolist()):
            for e in ((a, b), (b, c), (c, a)):
                across[e] = t
        waiting = [t for t in np.flatnonzero(flat) if group[t] < 0]
        while waiting:                                   # a run of slivers joins from its far end inward
            left = []
            for t in waiting:                            # all three corners lie on one line: across its longest edge first
                a, b, c = F[t]
                k = next((k for p, q in sorted(((a, b), (b, c), (c, a)), key=lambda e: -np.linalg.norm(V[e[1]] - V[e[0]]))
                          if (k := group[across[(q, p)]]) >= 0), -1)
                if k < 0:
                    left.append(t); continue
                group[t] = k; groups[k].append(t)
            if len(left) == len(waiting):
                raise ValueError(f"{len(left)} slivers with no face beside them")
            waiting = left
        verts, edges, faces = {}, {}, []

        def vertex(i):
            if i not in verts:
                verts[i] = self.vertex(V[i])
            return verts[i]

        def edge(a, b):                                  # one EDGE_CURVE per pair, from the lower vertex: walked both ways
            k = (min(a, b), max(a, b))
            if k not in edges:
                edges[k] = self.edge(vertex(k[0]), vertex(k[1]))
            return edges[k], a < b
        for g, n in zip(groups, normals):
            tri = F[g]
            half = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]).tolist()
            inside, nxt = set(map(tuple, half)), {}
            for a, b in half:
                if (b, a) not in inside:
                    nxt.setdefault(a, []).append(b)
            loops = []
            while nxt:                                   # ponytail: at a corner two loops touch, either way on is taken
                start = a = next(iter(nxt)); lp = []
                while True:
                    lp.append(a); b = nxt[a].pop()
                    if not nxt[a]:
                        del nxt[a]
                    if b == start:
                        break
                    a = b
                loops.append(lp)
            area = [float(n @ np.cross(V[lp], V[np.roll(lp, -1)]).sum(0)) for lp in loops]
            loops = [loops[i] for i in np.argsort(area)[::-1]]
            out = loops[0]
            faces.append(self.face([self.loop([edge(lp[i], lp[(i + 1) % len(lp)]) for i in range(len(lp))]) for lp in loops],
                                   vertex(out[0]), n, _unit(V[out[1]] - V[out[0]])))
        return faces


def step_text(plan, part=None, name="lamina", lumps=None, meshes=()) -> str:
    """The assembled model (or the one part labelled `part`) as a STEP file: one solid per flat piece of a part,
    named with the part's label, each where it sits in the assembly, then the parts given as closed meshes, `meshes`
    [(label, V, F)] (a standoff), each as its solid. With `lumps` (core.solid.one_body: the model fused, a closed mesh
    per piece of it that touches no other) one solid per lump instead, named after the model."""
    s = _Step()
    shape, context, frame = s.product(_text(name))
    solids = ([b for V, F in lumps for b in s.shell(name, V, F)] if lumps is not None else
              [b for sl in plan["slices"] for pc in sl["pieces"] if part is None or pc["label"] == part
               for poly, M, own in facet_polys(pc) if (b := s.prism(pc["label"], poly, M, own or sl["thickness"]))]
              + [b for label, V, F in meshes for b in s.shell(label, V, F)])
    shown = s.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',({','.join([frame, *solids])}),{context})")
    s.add(f"SHAPE_DEFINITION_REPRESENTATION({shape},{shown})")
    return HEAD.format(name=_text(name)) + "".join(f"#{i}={row};\n" for i, row in enumerate(s.rows, 1)) + "ENDSEC;\nEND-ISO-10303-21;\n"
