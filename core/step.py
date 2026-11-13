"""STEP (ISO 10303-21, AP214) of a plan's parts as true solids, for CAD. A part is a flat outline with a thickness,
so its solid has planar faces only: top, bottom and one wall per outline segment. That needs no CAD kernel (the
browser build has none): the file is written as text. A CAD program then shows two clean faces per part where the
STL shows its triangles. Curved edges stay the polylines they are in the cut files: one narrow wall per segment.

    uv run python -m core.solid working-files/egg.json --out working-files/egg.step [--part X-3]
"""
from __future__ import annotations
import numpy as np
from shapely.geometry.polygon import orient
from .solid import facet_polys

HEAD = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('Lamina parts as solids'),'2;1');
FILE_NAME('{name}.step','',(''),(''),'Lamina','Lamina','');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN {{ 1 0 10303 214 1 1 1 1 }}'));
ENDSEC;
DATA;
"""
# the product, millimetres, and the origin frame: #8 is what the shape hangs on, #13 its context, #14 its frame
PRODUCT = """APPLICATION_CONTEXT('core data for automotive mechanical design processes')
APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#1)
PRODUCT_CONTEXT('',#1,'mechanical')
PRODUCT('{name}','{name}','',(#3))
PRODUCT_DEFINITION_FORMATION('','',#4)
PRODUCT_DEFINITION_CONTEXT('part definition',#1,'design')
PRODUCT_DEFINITION('design','',#5,#6)
PRODUCT_DEFINITION_SHAPE('','',#7)
(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))
(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))
(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())
UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-5),#9,'distance_accuracy_value','')
(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#12))GLOBAL_UNIT_ASSIGNED_CONTEXT((#9,#10,#11))REPRESENTATION_CONTEXT('',''))
AXIS2_PLACEMENT_3D('',#15,#16,#17)
CARTESIAN_POINT('',(0.,0.,0.))
DIRECTION('',(0.,0.,1.))
DIRECTION('',(1.,0.,0.))
PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#4))"""


def _text(s) -> str:
    """A name as a STEP string: ASCII, with the quote and the backslash (STEP's own escape) doubled."""
    return str(s).encode("ascii", "replace").decode().replace("\\", "\\\\").replace("'", "''")


def _xyz(v) -> str:
    """Reals as STEP wants them: always with the point, never an exponent. 7 decimals: 0.1 nm on a millimetre."""
    return ",".join(f"{x + 0.0:.7f}".rstrip("0") for x in np.round(v, 7))


def _unit(v):
    return v / np.linalg.norm(v)


def _ring(coords):
    """A ring's corners (x, y) without the closing repeat and without the points that lie on a straight run: each
    would split one flat wall into two with a line between them, and a repeated point has no wall at all."""
    p = np.asarray(coords, float)[:-1, :2]
    a, b = p - np.roll(p, 1, 0), np.roll(p, -1, 0) - p
    return p[np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]) > 1e-9 * np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-12)]


class _Step:
    """The DATA section as it grows: add() numbers an entity and returns its reference."""
    def __init__(self):
        self.rows, self.dirs = [], {}

    def add(self, entity) -> str:
        self.rows.append(entity)
        return f"#{len(self.rows)}"

    def direction(self, v) -> str:
        """One DIRECTION per different direction: the walls of a part share a few, and the file is a quarter smaller."""
        key = _xyz(v)
        if key not in self.dirs:
            self.dirs[key] = self.add(f"DIRECTION('',({key}))")
        return self.dirs[key]

    def vertex(self, p):
        point = self.add(f"CARTESIAN_POINT('',({_xyz(p)}))")
        return self.add(f"VERTEX_POINT('',{point})"), point, p

    def edge(self, a, b) -> str:
        """The straight edge from vertex a to vertex b."""
        d = b[2] - a[2]
        vec = self.add(f"VECTOR('',{self.direction(_unit(d))},{_xyz([np.linalg.norm(d)])})")
        return self.add(f"EDGE_CURVE('',{a[0]},{b[0]},{self.add(f'''LINE('',{a[1]},{vec})''')},.T.)")

    def loop(self, edges) -> str:
        """A closed run of (edge, forward?) pairs, counter-clockwise seen from outside the solid."""
        return self.add("EDGE_LOOP('',(%s))" % ",".join(self.add(f"ORIENTED_EDGE('',*,*,{e},.{'T' if fwd else 'F'}.)") for e, fwd in edges))

    def face(self, loops, origin, normal, ref) -> str:
        """A flat face through the point `origin` (a vertex's): its outline first, then its holes; `normal` points
        out of the solid, `ref` lies in the face."""
        plane = self.add(f"PLANE('',{self.add(f'''AXIS2_PLACEMENT_3D('',{origin},{self.direction(normal)},{self.direction(ref)})''')})")
        bounds = [self.add(f"FACE_{'' if i else 'OUTER_'}BOUND('',{lp},.T.)") for i, lp in enumerate(loops)]
        return self.add(f"ADVANCED_FACE('',({','.join(bounds)}),{plane},.T.)")

    def prism(self, name, poly, M, thickness):
        """One polygon (holes included) as a solid `thickness` thick, centred on its plane, placed with its frame M.
        None when the outline has no area left."""
        M = np.asarray(M, float)
        mirrored = np.linalg.det(M[:3, :3]) < 0                         # a mirroring frame turns every ring over
        poly = orient(poly)                                             # outline counter-clockwise, holes clockwise
        faces, tops, bottoms, up, ref = [], [], [], None, None
        for k, ring in enumerate([poly.exterior, *poly.interiors]):
            p = _ring(ring.coords)
            if len(p) < 3:
                if k == 0:
                    return None
                continue
            p = p[::-1] if mirrored else p
            n = len(p)
            B, T = ([self.vertex(q) for q in (np.c_[p, np.full(n, z), np.ones(n)] @ M.T)[:, :3]] for z in (-thickness / 2, thickness / 2))
            if up is None:
                up, ref = _unit(T[0][2] - B[0][2]), _unit(B[1][2] - B[0][2])
            nxt = [(i + 1) % n for i in range(n)]
            eb, et, ev = ([self.edge(V[i], W[nxt[i] if V is W else i]) for i in range(n)] for V, W in ((B, B), (T, T), (B, T)))
            for i in range(n):                                          # the wall on segment i: along the bottom, up, back along the top, down
                along = _unit(B[nxt[i]][2] - B[i][2])
                faces.append(self.face([self.loop([(eb[i], True), (ev[nxt[i]], True), (et[i], False), (ev[i], False)])], B[i][1], np.cross(along, up), along))
            tops.append((self.loop([(e, True) for e in et]), T[0][1]))
            bottoms.append((self.loop([(e, False) for e in reversed(eb)]), B[0][1]))
        faces.append(self.face([lp for lp, _ in tops], tops[0][1], up, ref))
        faces.append(self.face([lp for lp, _ in bottoms], bottoms[0][1], -up, ref))
        return self.add(f"MANIFOLD_SOLID_BREP('{_text(name)}',{self.add('''CLOSED_SHELL('',(%s))''' % ','.join(faces))})")


def step_text(plan, part=None, name="lamina") -> str:
    """The assembled model (or the one part labelled `part`) as a STEP file: one solid per flat piece of a part,
    named with the part's label, each where it sits in the assembly."""
    s = _Step()
    s.rows += PRODUCT.format(name=_text(name)).split("\n")
    solids = [b for sl in plan["slices"] for pc in sl["pieces"] if part is None or pc["label"] == part
              for poly, M in facet_polys(pc) if (b := s.prism(pc["label"], poly, M, sl["thickness"]))]
    s.add(f"SHAPE_DEFINITION_REPRESENTATION(#8,{s.add('''ADVANCED_BREP_SHAPE_REPRESENTATION('',(%s),#13)''' % ','.join(['#14', *solids]))})")
    return HEAD.format(name=_text(name)) + "".join(f"#{i}={row};\n" for i, row in enumerate(s.rows, 1)) + "ENDSEC;\nEND-ISO-10303-21;\n"
