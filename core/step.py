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


def step_text(plan, part=None, name="lamina") -> str:
    """The assembled model (or the one part labelled `part`) as a STEP file: one solid per flat piece of a part,
    named with the part's label, each where it sits in the assembly."""
    s, name = _Step(), _text(name)
    shape, context, frame = s.product(name)
    solids = [b for sl in plan["slices"] for pc in sl["pieces"] if part is None or pc["label"] == part
              for poly, M in facet_polys(pc) if (b := s.prism(pc["label"], poly, M, sl["thickness"]))]
    shown = s.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION('',({','.join([frame, *solids])}),{context})")
    s.add(f"SHAPE_DEFINITION_REPRESENTATION({shape},{shown})")
    return HEAD.format(name=name) + "".join(f"#{i}={row};\n" for i, row in enumerate(s.rows, 1)) + "ENDSEC;\nEND-ISO-10303-21;\n"
