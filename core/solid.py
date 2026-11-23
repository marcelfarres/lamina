"""3D solids from a plan (pure trimesh): assembled model, one part, or a prototyping set — every part flat for
3D printing at a chosen scale, with its label engraved as a groove or cut through. The set includes plate.3mf,
which opens in OrcaSlicer / PrusaSlicer as one named object per part, ready to arrange, each with the print settings
it needs (write_3mf).

    uv run python -m core.solid working-files/egg.json --out working-files/egg_assembled.stl [--part X-3]
    uv run python -m core.solid working-files/egg.json --out working-files/egg.step --body      (one solid)
    uv run python -m core.solid working-files/egg.json --out working-files/egg_assembled.step     # solids for CAD (core/step.py)
    uv run python -m core.solid working-files/egg.json --proto working-files/egg_proto --scale 0.5 --labels groove
    uv run python -m core.solid working-files/egg.json --fit working-files/egg_fit --step 0.1     # 5 slot offsets to try first
"""
from __future__ import annotations
import argparse, io, json, pathlib, re, tempfile, zipfile
from html import unescape
from xml.sax.saxutils import quoteattr
import numpy as np
import trimesh
from types import SimpleNamespace
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree
import shapely
from .export import design_name, export, rods_of
from .geometry import dowel, even_odd, facet_polys
from .labels import PRINT_MARK, TAG_CLEAR, TAG_FONT, TAG_PAD, beside, fit_on_part, label_angles, mark_box, tag_room
from .step import step_text


_no_engine = False   # trimesh has no triangulation engine here (the browser build): remembered, or it logs advice per piece


def extrude(poly, height) -> trimesh.Trimesh:
    """A polygon (holes included) as a solid `height` thick. trimesh caps it with earcut or triangle; the browser build
    has neither, so there shapely's constrained Delaunay triangulates the caps and trimesh only adds the walls."""
    global _no_engine
    if not _no_engine:
        try:
            return trimesh.creation.extrude_polygon(poly, height)
        except ValueError:                                             # "No available triangulation engine!"
            _no_engine = True
    tris = np.array([t.exterior.coords[:3] for t in shapely.constrained_delaunay_triangles(poly).geoms])   # (n, 3, 2)
    v, inv = np.unique(tris.reshape(-1, 2).round(6), axis=0, return_inverse=True)
    f = inv.ravel().reshape(-1, 3)
    a, b = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    cw = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] < 0                      # walls need every cap triangle counter-clockwise
    f[cw] = f[cw][:, ::-1]
    return trimesh.creation.extrude_triangulation(v, f, height)


def piece_mesh(pc, thickness) -> trimesh.Trimesh:
    """Every facet extruded by the thickness, centred on its plane, placed with its frame."""
    parts = []
    for poly, M, own in facet_polys(pc):
        t = own or thickness                                # a thin printed tab is not the sheet's thickness
        m = extrude(poly, t)
        m.apply_translation([0, 0, -t / 2]); m.apply_transform(M)
        parts.append(m)
    return trimesh.util.concatenate(parts) if parts else trimesh.Trimesh()


def standoff_kinds(plan):
    """The printed standoffs of a plan by size, biggest count first: [(S1, gap, its two ends, its items)], an end a
    (pin length, whether it is a flush pin). Two that differ only in which end is up are one part turned over."""
    kinds = {}
    for e in (plan.get("standoffs") or {}).get("items", []):
        kinds.setdefault((e["gap"], *sorted(zip(e["pins"], e["flush"]), reverse=True)), []).append(e)
    ranked = sorted(kinds.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [(f"S{n + 1}", gap, ends, items) for n, ((gap, *ends), items) in enumerate(ranked)]


SLIVER = 1e-4      # mm: what a join drops. Faces that are one plane by design (a click bar's top and its posts') come out a
                   # float apart, each from its own transform; the union keeps slivers between them, and a slicer that
                   # merges corners that close finds edges three faces share (bugs/075)


def _joined(parts) -> trimesh.Trimesh:
    """Solids that touch or overlap as one, slivers under SLIVER dropped: joined where solids can be cut here, else
    shells a slicer joins."""
    if not has_boolean():
        return trimesh.util.concatenate(parts)
    import manifold3d as mf
    m = trimesh.boolean.union(parts, engine="manifold")
    k = mf.Manifold(mf.Mesh64(vert_properties=np.asarray(m.vertices, float), tri_verts=np.ascontiguousarray(m.faces, dtype=np.uint64))).simplify(SLIVER).to_mesh64()
    return trimesh.Trimesh(np.asarray(k.vert_properties)[:, :3], np.asarray(k.tri_verts, dtype=np.int64), process=False)


def standoff_mesh(plan, gap, ends, half=0) -> trimesh.Trimesh:
    """One standoff along z from z = 0: a pin, the body over the gap, a pin. `ends` gives each pin's (length, flush),
    and a pin has the section of the hole it goes into. `half` 1 or -1 gives the half of it on that side of the plane
    through its axis (the section's y = 0), which it is cut along to be printed."""
    so = plan["standoffs"]
    (p0, f0), (p1, f1) = ends
    side = shapely.box(-1e3, min(0, half * 1e3), 1e3, max(0, half * 1e3)) if half else None

    def length(name, h, z):
        poly = Polygon(so[name]) if side is None else Polygon(so[name]).intersection(side)
        return extrude(poly, h).apply_translation([0, 0, z])
    parts = [length("flush" if f0 else "pin", p0, 0), length("flush" if f1 else "pin", p1, p0 + gap)]
    if gap > 0:
        parts.insert(1, length("body", gap, p0))
    return _joined(parts)


def standoff_print(plan, gap, ends) -> trimesh.Trimesh:
    """A standoff as it is printed, on z = 0, its axis along x: cut in half along its length, both halves with the cut
    face down, side by side, the two bodies touching along one line on the plate and joined there over a height of
    `standoff_hinge`. That line is the hinge: with nothing between the halves there is one place to bend, and folded
    shut about it the two halves are the standoff, edge on edge (a strip between them bent at either of its sides and
    closed the halves out of line: Marcel's second print). The second half lies turned half a turn about that line.
    Each half only gets narrower as it rises, so nothing needs a support, and the layers run along the pins. With no
    gap there is no body to hinge: the pin is printed whole, on a flat side."""
    so, h = plan["standoffs"], plan["params"]["standoff_hinge"]
    if gap == 0:
        m = standoff_mesh(plan, gap, ends).apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        return m.apply_translation(-m.bounds[0])
    R = Polygon(so["body"]).bounds[2]                                  # the body's edge: where the two halves touch
    a = standoff_mesh(plan, gap, ends, 1).apply_transform([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    b = standoff_mesh(plan, gap, ends, -1).apply_transform([[0, 0, 1, 0], [-1, 0, 0, 2 * R], [0, -1, 0, 0], [0, 0, 0, 1]])
    # two round bodies side by side meet in a line with no area: the bar fills the bottom of the valley between them,
    # so they are one solid there, `standoff_hinge` high and nowhere wider than the bodies themselves
    lap = 0.3
    hinge = trimesh.creation.box([gap, 2 * lap, h]).apply_translation([ends[0][0] + gap / 2, R, h / 2])
    m = _joined([a, hinge, b])
    return m.apply_translation([0, R, 0])


WHY_TWO_SHAPES = ("Why two shapes: a layer inside the stack has a standoff under it and one over it in the same hole, so each",
                  "pin can go only half way in. A hole with a standoff on one side only has room for a pin through the whole",
                  "layer, which holds better and leaves no open hole. The shape of the hole says which pin it takes: a long",
                  "pin does not go into a shared hole, where it would push the other standoff out.")


def standoff_text(plan, f=1.0, u="mm") -> list:
    """What to print and where each size goes, as lines: for the note beside the print file and for the assembly key."""
    shape = plan["params"]["dowel_shape"]
    out = ["3D PRINT — the standoffs, in the file named 3D-PRINT."
           + ("" if plan["params"].get("printed") else " The sheet files are for the cutter."),
           "A standoff's body keeps two layers apart. A pin at each end goes into a hole:",
           f"  {shape} pin, short  -> a {shape} hole. Two standoffs share it, one from each side.",
           "  pentagon pin, long  -> a pentagon hole. The pin goes through and ends flush.",
           *WHY_TWO_SHAPES,
           "Print them as they lie in the file: each is two halves, flat side down, touching along one edge. No supports.",
           "Fold the two halves together about that edge, then push the pins into the holes. The holes keep it closed.",
           "Each has its size (S1, S2 ...) on a tag beside it, a chip on a thin line: read it, then snap the tag off.", "",
           f"{'size':<6}{'qty':<6}{'gap':<8}{'pins':<34}between"]
    end = lambda e: f"{e[0] * f:.3g} {'pentagon' if e[1] else shape}"   # noqa: E731
    for tag, gap, ends, items in standoff_kinds(plan):
        where = [f"{e['lo']} / {e['hi']}" for e in items]
        where = sorted(set(where), key=where.index)
        out.append(f"{tag:<6}{len(items):<6}{gap * f:<8.3g}{f'{end(ends[0])} + {end(ends[1])} {u}':<34}"
                   + ", ".join(where[:8]) + (f" and {len(where) - 8} more pair(s)" if len(where) > 8 else ""))
    return out


def standoff_files(plan, out_dir, design, scale=1.0) -> list:
    """The print file for the standoffs, named so nobody sends it to the cutter: one 3MF, every standoff an object of
    its own named by its size (S1, S2 …), a row per size, each as standoff_print lays it. Beside it a note that says
    what it is."""
    scene = trimesh.Scene(); y = 0.0; laid = []
    for tag, gap, ends, items in standoff_kinds(plan):
        m = standoff_print(plan, gap, ends).apply_scale(scale)
        down = m.triangles[(m.face_normals[:, 2] < -0.99) & (m.triangles_center[:, 2] < 1e-3)]
        foot = unary_union([Polygon(t[:, :2]) for t in down]).buffer(0)          # what lies on the bed
        w, h = tag_room(tag, TAG_FONT)                                         # each with room above it for its size on a tag
        dx, dy = max(m.extents[0] + 3, w), m.extents[1] + 3 + h
        for n in range(len(items)):
            at = (n % 12 * dx, y + n // 12 * dy)
            laid.append((f"{tag} {n + 1}", tag, m.copy().apply_translation([*at, 0]), affinity.translate(foot, *at)))
        y += ((len(items) - 1) // 12 + 1) * dy + 3
    on = [f for *_, f in laid]
    for k, (name, tag, q, _) in enumerate(laid):
        mesh, foot, _ = print_tag(on, k, tag, TAG_FONT, 1e6, 1e6, 0.0)
        on.append(foot)
        scene.add_geometry(_joined([q, mesh]), node_name=name, geom_name=name)
    stem = f"{design} 3D-PRINT standoffs x{len(scene.geometry)}"
    f = pathlib.Path(out_dir) / f"{stem}.3mf"; needs = write_3mf(scene, f)
    note = pathlib.Path(out_dir) / f"{stem}.txt"
    note.write_text("\n".join(standoff_text(plan) + ["", *_settings_note({f.name: needs})]) + "\n", encoding="utf-8")
    return [f, note]


def _frame(x, z, at) -> np.ndarray:
    """The frame with its x and z axes along `x` and `z` (z square to x first), its origin at `at`."""
    z = np.asarray(z, float) / np.linalg.norm(z); x = np.asarray(x, float) - z * (np.asarray(x, float) @ z); x /= np.linalg.norm(x)
    M = np.eye(4); M[:3, :3] = np.c_[x, np.cross(z, x), z]; M[:3, 3] = at
    return M


def _standoffs(plan) -> list:
    return [standoff_mesh(plan, e["gap"], list(zip(e["pins"], e["flush"]))).apply_transform(_frame(e["x"], e["z"], np.array(e["at"]) - np.array(e["z"]) * e["pins"][0]))
            for e in (plan.get("standoffs") or {}).get("items", [])]


PIN_END = 0.4       # mm a printed dowel pin is shorter than its holes: a pin a hair long would keep two layers apart


def pin_print(plan, length) -> trimesh.Trimesh:
    """A printed job's dowel pin as it is printed: on z = 0, its axis along x, its section the dowel's less `pin_fit`,
    PIN_END shorter than the holes it fills. It lies on a flat side, so nothing needs a support: a round pin has one cut
    on it, 0.7 of its width wide; a vslot pin is the hslot pin turned a quarter, which is how it goes in."""
    p = plan["params"]; d = p["dowel_d"] - p["pin_fit"]; shape = {"vslot": "hslot"}.get(p["dowel_shape"], p["dowel_shape"])
    sec = dowel((0, 0), d, shape)
    if shape == "round":
        sec = sec.intersection(shapely.box(-d, -0.35 * d, d, d))
    # ponytail: a cross pin lies on the end of one arm, its side arms in the air (1 mm at a 3 mm dowel); a square one prints clean
    m = extrude(sec, length - PIN_END).apply_transform([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
    return m.apply_translation(-m.bounds[0])


def pin_files(plan, out_dir, written=None) -> list:
    """A printed stacked job's dowel pins, on the printer's bed as its layers are: pins-1.3mf, pins-2.3mf … nested as
    the plates are, every pin an object named after its dowel (Z-3a: dowel a between Z-3 and Z-4, as the assembly key
    and the marks by its holes say), its name on a tag beside it. One pin per dowel: a straight one through several
    layers is one long pin, as long as the key says, less PIN_END. Each file carries its pins' print settings
    (write_3mf: a pin's thickness on the bed is its fit in the hole); `written` ({file name: settings}) takes them."""
    from .model import Piece, Slice                      # here: core.model is the planner's, not needed for a laser job's files
    from .nest import nest
    p, pins = plan["params"], []
    for name, e in rods_of(plan).items():
        m = pin_print(plan, e["length"])
        pc = Piece(name, MultiPolygon([shapely.box(0, 0, *m.extents[:2])]), Slice(name, "P", np.eye(4), m.extents[2]))
        pins.append((pc, m))
    if not pins:
        return []
    nest([pc for pc, _ in pins], plan["sheet"], p["gap"], p["sheet_margin"], font=TAG_FONT, printed=True)
    plates, on = {}, {}
    for pc, m in pins:                                   # turned and moved as the nester placed its outline
        si, x, y, rot = pc.place
        q = m.copy().apply_transform(trimesh.transformations.rotation_matrix(np.radians(rot), [0, 0, 1]))
        q.apply_translation([x - q.bounds[0][0], y - q.bounds[0][1], 0])
        on.setdefault(si, []).append(pc.placed); plates.setdefault(si, []).append((pc.label, q))
    files = []
    for si in sorted(plates):
        scene, laid = trimesh.Scene(), on[si]
        for k, (name, q) in enumerate(plates[si]):
            tag, foot, _ = print_tag(laid, k, name, TAG_FONT, *plan["sheet"], p["sheet_margin"])
            laid.append(foot)
            scene.add_geometry(_joined([q, tag]), node_name=name, geom_name=name)
        f = pathlib.Path(out_dir) / f"pins-{si + 1}.3mf"; needs = write_3mf(scene, f); files.append(f)
        if written is not None:
            written[f.name] = needs
    return files


def pin_note(plan) -> list:
    """What the README says about the pins file."""
    p, n = plan["params"], len(rods_of(plan))
    return [f"{n} dowel pin(s) in pins-N.3mf: {p['dowel_d'] - p['pin_fit']:g} mm across ({p['dowel_shape']} dowel {p['dowel_d']:g} mm "
            f"less pin fit {p['pin_fit']:g}), each {PIN_END:g} mm shorter than its holes, lying on a flat side: no supports. "
            "Each is named on a tag as the assembly key names it (Z-3a: dowel a between Z-3 and Z-4): read it, then snap the tag off. "
            "Too tight or too loose: change pin fit"]


def assembled(plan, part=None) -> trimesh.Trimesh:
    ms = [piece_mesh(pc, sl["thickness"]) for sl in plan["slices"] for pc in sl["pieces"] if part is None or pc["label"] == part]
    ms += _standoffs(plan) if part is None else []
    return trimesh.util.concatenate(ms) if ms else trimesh.Trimesh()


WELD = 0.02         # mm every part of the one body is grown by: parts that touch along a line, or a float's width apart, fuse


def one_body(plan) -> list:
    """The assembled model as one solid for CAD (the STEP's one body): every part, standoff and dowel fused by
    manifold3d in float64 (trimesh's union casts to float32, bugs/067). Each part is grown by WELD, so parts that touch
    only along a line (a fold, a slot's bottom) or a hair apart fuse, and each dowel fills its hole, so a stack whose
    layers stand apart is one solid through its dowels. [(vertices, triangles)] per lump: a part that touches nothing
    stays a solid of its own, as one closed shell cannot hold two."""
    import manifold3d as mf                               # here: the browser build has none (has_boolean)
    p, ms = plan["params"], _standoffs(plan)
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            for poly, M, own in facet_polys(pc):
                t = (own or sl["thickness"]) + 2 * WELD
                ms.append(extrude(poly.buffer(WELD, join_style=2), t).apply_translation([0, 0, -t / 2]).apply_transform(M))
    for a, b, d, _, x, *_ in plan.get("rods") or []:     # a dowel as wide as its hole, from one end to the other
        ms.append(extrude(dowel((0, 0), d + p.get("slot_offset", 0.0), p["dowel_shape"]), float(np.linalg.norm(np.subtract(b, a)))).apply_transform(_frame(x, np.subtract(b, a), a)))
    whole = mf.Manifold.batch_boolean([mf.Manifold(mf.Mesh64(vert_properties=np.asarray(m.vertices, float), tri_verts=np.ascontiguousarray(m.faces, dtype=np.uint64)))
                                       for m in ms], mf.OpType.Add)
    return [(np.asarray(k.vert_properties)[:, :3], np.asarray(k.tri_verts, dtype=np.int64)) for k in (lump.to_mesh64() for lump in whole.decompose())]


def solid_bytes(plan, part=None, fmt="stl", body=False) -> bytes:
    """The assembled model, or the one part labelled `part`, as a file: `step` is solids for CAD (core/step.py), with
    `body` the whole model fused into one solid (one_body), anything else a mesh in that format. LookupError when the
    plan has no such part."""
    if part and part not in {pc["label"] for sl in plan["slices"] for pc in sl["pieces"]}:
        raise LookupError(f"no part {part} in this plan")
    if fmt == "step":
        # the standoffs are parts too, each a solid named by its size and the layers it joins (S1 Z-3/Z-4)
        size = {id(e): tag for tag, *_, items in standoff_kinds(plan) for e in items}
        items = (plan.get("standoffs") or {}).get("items", [])
        meshes = [(f"{size[id(e)]} {e['lo']}/{e['hi']}", m.vertices, m.faces) for e, m in zip(items, _standoffs(plan))] if not part and not body else []
        data = step_text(plan, part, design_name(plan), one_body(plan) if body and not part else None, meshes)
    else:
        data = assembled(plan, part).export(file_type=fmt)
    return data if isinstance(data, bytes) else data.encode()         # STEP and some mesh formats (OBJ, OFF) are text


# ---------------------------------------------------------------- text → polygons (labels engraved in prototypes)
def text_polygons(text, height, res=8) -> MultiPolygon:
    """Glyph outlines of `text` as polygons, the capitals `height` mm tall (rendered with Pillow, traced with
    scikit-image). Bold, so the strokes print: at 5 mm they are about 0.8 mm wide, two passes of a 0.4 mm nozzle."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        from skimage import measure
    except ImportError:          # left out on a Python it has no build for yet (pyproject, 027)
        raise RuntimeError("engraved labels on prototypes need scikit-image, which has no build for this Python yet: "
                           "run Lamina on Python 3.14 (uv tool install --python 3.14 lamina3d) or set labels to none") from None
    px = int(height * res * 1.4)                                         # the em is about 1.4 capitals
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, px); break
        except OSError:
            font = ImageFont.load_default(size=px)
    x0, y0, x1, y1 = font.getbbox(text)
    img = Image.new("L", (x1 - x0 + 4, y1 - y0 + 4), 0)
    ImageDraw.Draw(img).text((2 - x0, 2 - y0), text, fill=255, font=font)
    a = np.asarray(img) > 127
    polys = []
    for c in measure.find_contours(a.astype(float), 0.5):
        if len(c) > 3:
            pts = [(x / res, (a.shape[0] - y) / res) for y, x in c]
            polys.append(Polygon(pts))
    if not polys:
        return MultiPolygon()
    g = even_odd(polys)                                                  # outer contours minus inner ones (the holes of 'o', 'a' …)
    k = height / (g.bounds[3] - g.bounds[1])
    return affinity.scale(g, k, k, origin=(0, 0))


def text_at(text, height, x, y, rot):
    """`text` as polygons `height` mm tall, centred on (x, y) and turned `rot` degrees."""
    g = text_polygons(text, height); x0, y0, x1, y1 = g.bounds
    return affinity.rotate(affinity.translate(g, x - (x0 + x1) / 2, y - (y0 + y1) / 2), rot, origin=(x, y))


def label_on(room, text, font, marks=()):
    """The label as polygons on the part: where the whole label fits with room all round, clear of the `marks`
    (boxes) cut into it, by the sheets' rule (core.labels.fit_on_part), upright, a quarter turn or along the part,
    1.5 x `font` tall where that fits and `font` otherwise. None when it fits nowhere: the part then carries its
    number on a tag beside it (print_tag).
    ponytail: fit_block tries two spots per region, so a label that only fits squeezed between a slot and an end
    (a 60 x 20 bar slotted at its middle) is missed, on the sheets as here; the part then gets a tag, never no number."""
    txt = text_polygons(text, font); x0, y0, x1, y1 = txt.bounds
    for f in (1.5, 1.0):
        spot = fit_on_part(room, None, (x1 - x0) * f, (y1 - y0) * f, marks, label_angles(room), room=min(2.0, 0.3 * font * f))
        if spot:
            return text_at(text, font * f, *spot)
    return None


CHIP_H = 0.2        # mm: the tag's chip and its line are one layer (the first, the surest a printer lays down)
LETTER_H = 0.4      # mm: the number stands two layers above the chip. A chip this thin has no depth for a groove,
                    # and letters cut through it would lose the middles of 0, 4, 6, 8, 9, A, B, D, P and R
LINE_W = 0.9        # mm: the line is two lines of a 0.4 mm nozzle wide (0.18 mm² of plastic: it tears by hand)
LAP = 0.3           # mm the line runs into the part, so the two are one solid


def print_tag(laid, k, text, font, W, H, margin, toward=None):
    """The tag for the part `laid[k]` (the outlines on one plate, earlier tags included): a chip one layer high with
    the number raised on it, joined to the part by a line one layer high. It goes where the sheets put a label that
    has no room on its part (core.labels.beside): the nearest free spot, above the part first, `TAG_CLEAR` from every
    other part and tag, its line crossing none; with `toward` (x, y), the free spot nearest that point instead (a
    seam number's tag, near its seam). The plate is W x H with `margin`. Returns (mesh, footprint, whether it found
    free room); with none it goes beside the part anyway, over whatever lies there, for the caller to report."""
    f = max(font, TAG_FONT)
    txt = text_polygons(text, f); x0, y0, x1, y1 = txt.bounds
    w, h = x1 - x0 + 2 * TAG_PAD, y1 - y0 + 2 * TAG_PAD
    part = laid[k]
    found = beside(k, SimpleNamespace(placed=part), [(f, False, w + 2 * TAG_CLEAR, h + 2 * TAG_CLEAR)],
                   SimpleNamespace(W=W, H=H, margin=margin, placed=laid), STRtree(laid), [], toward=None if toward is None else Point(toward))
    if found:
        (cx, cy, rot), (_, q) = found[:2]
    else:
        bx0, _, bx1, by1 = part.bounds; rot = 0
        cx, cy = (bx0 + bx1) / 2, by1 + 0.8 + TAG_CLEAR + h / 2
        q = nearest_points(part, Point(cx, cy))[0].coords[0]
    chip = affinity.rotate(shapely.box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), rot, origin=(cx, cy))
    letters = affinity.rotate(affinity.translate(txt, cx - (x0 + x1) / 2, cy - (y0 + y1) / 2), rot, origin=(cx, cy))
    d = np.subtract(q, (cx, cy)); end = np.add(q, d / np.linalg.norm(d) * LAP)
    foot = unary_union([chip, LineString([(cx, cy), end]).buffer(LINE_W / 2, cap_style="flat")])
    mesh = _joined([extrude(foot, CHIP_H), *(extrude(g, CHIP_H + LETTER_H) for g in shapely.get_parts(letters) if g.area > 0)])
    return mesh, foot, found is not None


def has_boolean() -> bool:
    """Whether solids can be cut from each other here (manifold3d): the browser build has no wheel for it."""
    try:
        import manifold3d  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------- print settings each object of a 3MF needs
FIRST = 0.2         # mm: the first layer of a 0.4 mm nozzle's profiles, which the layer heights below count from.
                    # It is set for the whole plate, so the file cannot carry it: the README asks for it
LAYERS = (0.2, 0.16, 0.12, 0.1, 0.08)   # mm, 0.2 first: chips, panes and hinge skins are made in steps of it
THIN = 1.0          # mm: a flat top this low is a few layers, and half a layer off shows (a chip, a pane, a hinge skin)
BRIDGE_LEAN = 55    # degrees from vertical: an underside flatter than this is a bridge (a click joint's bar), not an
                    # overhang that prints (a click tooth's 55°, a leaning wall's 45°)
SPAN = 1.0          # mm: an underside narrower than this prints as a plain overhang (a snap groove's 0.7 mm ledge)


def print_needs(m) -> dict:
    """The slicer settings one object needs, measured on its mesh as it lies on the bed, as OrcaSlicer's per-object
    keys: a layer height that makes its flat tops a whole number of layers over the first one (its thin ones always,
    its main face too where one height does both), and thick bridges with no support under a bridge."""
    nz, z = m.face_normals[:, 2], m.triangles_center[:, 2]
    up = (nz > 0.99) & (z > 0.01)
    levels, inv = np.unique(z[up].round(2), return_inverse=True)
    area = np.bincount(inv, m.area_faces[up], len(levels))
    levels, area = levels[area > 0.5], area[area > 0.5]                 # a sliver sets no layer height
    fits = lambda need: next((h for h in LAYERS if (abs((need - FIRST) / h - np.round((need - FIRST) / h)) * h < 0.006).all()), None)   # noqa: E731
    out = {}
    if len(levels):
        thin, body = levels <= THIN, levels > THIN
        # the main face is the part's own: the largest flat top above THIN, not the tags' chips, which on a file of
        # small parts (pins) can cover more than the parts do
        main = levels[body][area[body].argmax()] if body.any() else levels[area.argmax()]
        h = fits(np.append(levels[thin], main)) or (fits(levels[thin]) if thin.any() else None)
        if h:
            out["layer_height"] = f"{h:g}"
    under = (nz < -np.sin(np.radians(BRIDGE_LEAN)) - 1e-3) & (z > 0.05)
    if under.any() and not unary_union([Polygon(t[:, :2]) for t in m.triangles[under]]).buffer(0).buffer(-SPAN / 2).is_empty:
        out.update(thick_bridges="1", enable_support="0")
    return out


def write_3mf(scene, f) -> dict:
    """The scene as a 3MF at `f`, each object's print_needs in Metadata/model_settings.config, where OrcaSlicer reads
    an object's own settings (with or without the rest of a project). Returns {object name: its settings}."""
    needs = {n: print_needs(m) for n, m in scene.geometry.items()}
    buf = io.BytesIO(scene.export(file_type="3mf"))
    with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as z:
        ids = {unescape(n.decode()): i.decode() for i, n in re.findall(rb'<object id="(\d+)" name="([^"]*)"', z.read("3D/3dmodel.model"))}
        objs = "".join(f'<object id="{ids[n]}"><metadata key="name" value={quoteattr(n)}/>'
                       + "".join(f'<metadata key="{k}" value="{v}"/>' for k, v in s.items()) + "</object>" for n, s in needs.items() if s)
        z.writestr("Metadata/model_settings.config", f'<?xml version="1.0" encoding="UTF-8"?>\n<config>{objs}</config>\n')
    pathlib.Path(f).write_bytes(buf.getvalue())
    return needs


def _settings_note(written) -> list:
    """What the README says about the settings written into each 3MF ({file name: write_3mf's result})."""
    lines = []
    for name, needs in written.items():
        if not needs:
            continue
        heights, bridged = {}, [n for n, s in needs.items() if "thick_bridges" in s]
        for n, s in needs.items():
            heights.setdefault(s.get("layer_height"), []).append(n)
        say = lambda names, every=len(needs): "every part" if len(names) == every else ", ".join(names)   # noqa: E731
        lines.append(f"{name} carries the print settings each part needs. OrcaSlicer applies them when it opens the file. "
                     + ". ".join([f"Layer height {h} mm for {say(ns)}" for h, ns in heights.items() if h]
                                 + [f"Thick bridges on and supports off for {say(bridged)}: each has a bridge (a click joint's bar), "
                                    "and a support under it would fill the joint"] * bool(bridged)) + ".")
        if None in heights:
            lines.append(f"no layer height of {', '.join(f'{h:g}' for h in LAYERS)} mm makes {say(heights[None])} a whole number of layers: "
                         "they print up to half a layer thinner or thicker.")
    if lines:
        lines.append(f"Set the first layer height to {FIRST:g} mm for the whole plate (the usual value for a 0.4 mm nozzle): a 3MF cannot "
                     "carry it, and the layer heights above count from it. Bambu Studio can drop settings per part when it imports "
                     "a file it did not save: check them there.")
    return lines


def vee(a, b, land, skin, wide, top, t) -> trimesh.Trimesh:
    """The V groove along a→b to take out of a part `t` thick: `land` wide at the bottom, `skin` above the far face,
    `wide` to each side where it opens on the top face (or the bottom one)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = (b - a) / np.linalg.norm(b - a); n = np.array([-d[1], d[0]])
    a, b = a - d * 0.01, b + d * 0.01                                   # a hair past both ends and the open face: no coplanar faces
    z0, z1 = (skin, t + 0.01) if top else (t - skin, -0.01)
    return trimesh.convex.convex_hull([[*(q + n * s * u), z] for q in (a, b) for u, z in ((land / 2, z0), (wide, z1)) for s in (-1, 1)])


def rail(a, b, into, profile) -> trimesh.Trimesh:
    """A wall standing on a part along a→b: its cross-section `profile` [(u, z)], u from the line into the part along
    `into` and z up from the bed, swept from a to b."""
    a, b = np.asarray(a, float), np.asarray(b, float); d = b - a; L = float(np.linalg.norm(d))
    m = extrude(Polygon(profile).buffer(0), L)             # drawn in x, y and swept along z: x → into, y → up, z → along the line
    T = np.eye(4); T[:2, 0] = into; T[2, 1] = 1.0; T[1, 1] = 0.0; T[:2, 2] = d / L; T[2, 2] = 0.0; T[:2, 3] = a
    m.apply_transform(T)
    if m.volume < 0:
        m.invert()
    return m


def proto_part(pc, thickness, scale, labels, font, min_thick):
    """One part flat on z = 0 at `scale`, its label (`font` mm tall at least, see label_on) as a groove (half
    depth, 0.6 mm at most) or a hole (through) — on a stacked layer only where the layer above hides it (`cover`),
    so the top layer prints clean. Returns the mesh, whether the part got the label it should have (one that did not
    gets a tag beside it, see _plate) and its outline as the mesh lies."""
    shape = lambda rings: affinity.scale(unary_union([Polygon(r[0], r[1:]) for r in rings]), scale, scale, origin=(0, 0))   # noqa: E731
    geom = shape(pc["kerfed"]).buffer(0)
    x0, y0, x1, y1 = geom.bounds
    geom = affinity.translate(geom, -x0, -y0)
    room = geom if pc.get("cover") is None else geom.intersection(affinity.translate(shape(pc["cover"]), -x0, -y0))
    if pc.get("paper"):                                    # a window's pane is too thin to carry a label
        room = room.difference(affinity.translate(shape(pc["paper"]), -x0, -y0).buffer(0.5))
    if pc.get("thin"):                                     # a printed glue tab is only the hinge skin: a name cut there does not show
        room = room.difference(unary_union([Polygon([(x * scale - x0, y * scale - y0) for x, y in r[0]]) for r in pc["thin"]]).buffer(0.01))
    t = max(thickness * scale, min_thick)
    # the seam numbers a printed panel carries (core.modes.folded sizes them PRINT_MARK tall), cut as its name is
    marks = [(m[0] * scale - x0, m[1] * scale - y0, m[2], m[3], 0.6 * m[4]) for m in pc.get("kerfed_marks") or []
             if labels != "none" and len(m) > 4 and 0.6 * m[4] >= PRINT_MARK - 1e-6]
    label = label_on(room, pc["label"], font, [mark_box(x, y, s, h / 0.6, r) for x, y, s, r, h in marks]) if labels != "none" and not room.is_empty else None
    if label is not None and labels == "hole":
        geom = geom.difference(label)
    mesh = trimesh.util.concatenate([extrude(g, t) for g in shapely.get_parts(geom) if g.area > 0])
    plain = []                                             # what this part should have had cut into it and has not: no boolean engine
    if pc.get("grooves") or pc.get("thin") or pc.get("paper"):   # a printed folded panel: a groove at every fold, its skin the hinge
        move = lambda x, y: (x * scale - x0, y * scale - y0)   # noqa: E731
        cuts = [vee(move(*g["a"]), move(*g["b"]), g["land"] * scale, g["skin"] * scale, g["wide"] * scale, g["top"], t) for g in pc.get("grooves", [])]
        # the glue tabs keep only the skin, a window closed by a pane only the pane: everything above it goes
        for rings, keep in [(r, pc["thin_t"]) for r in pc.get("thin", [])] + [(r, pc["paper_t"]) for r in pc.get("paper", [])]:
            tab = Polygon([move(x, y) for x, y in rings[0]]).buffer(0.01, join_style="mitre")
            top = extrude(tab, t - keep * scale + 0.01); top.apply_translation([0, 0, keep * scale]); cuts.append(top)
        if has_boolean():
            mesh = trimesh.boolean.difference([mesh, *cuts], engine="manifold")
        else:
            plain.append("fold grooves")
    if pc.get("rails"):                                    # the walls of a snap joint, standing on the panel
        at = lambda q: (q[0] * scale - x0, q[1] * scale - y0)   # noqa: E731
        walls = [rail(at(r["a"]), at(r["b"]), r["into"], [(u * scale, z * scale) for u, z in r["profile"]]) for r in pc["rails"]]
        mesh = _joined([mesh, *walls])
    cut = ([label] if label is not None and labels == "groove" else []) + [text_at(s, h, x, y, r) for x, y, s, r, h in marks]
    if cut:
        depth = min(t * 0.5, 0.6)
        groove = trimesh.util.concatenate([extrude(g, depth + 0.01) for c in cut for g in shapely.get_parts(c) if g.area > 0])
        groove.apply_translation([0, 0, t - depth])
        if has_boolean():
            mesh = trimesh.boolean.difference([mesh, groove], engine="manifold")   # named, or trimesh may wait on a Blender it finds
        else:
            plain.append("label")
    mesh.metadata["plain"] = plain
    seams = [(x * scale - x0, y * scale - y0, j) for x, y, j in pc.get("seam_tags", [])] if labels != "none" else []
    return mesh, label is not None or labels == "none", geom, seams


def proto_plan(plan, scale, min_thick, offset=None):
    """The plan the prototype is cut from. Parts scaled below `min_thick` cannot simply be printed thicker: their
    slots and holes were sized for the thin material and nothing would fit. So the whole job is planned again at the
    material thickness that prints to `min_thick` — every slot follows. `offset` is the slot offset the print gets,
    in printed millimetres: a fit is a clearance in millimetres, not a ratio, so the job's own offset (for the real
    material, at 1:1) is replaced by offset / scale. Returns (plan, note); note is None when the plan stands."""
    from .plan import build
    p = dict(plan["params"]); notes = []
    thin = min(sl["thickness"] for sl in plan["slices"]) if plan["slices"] else p["thickness"]
    if thin * scale < min_thick - 1e-9:
        need = round(min_thick / scale, 3)
        p["thickness"] = max(p["thickness"], need)
        p["thick"] = {k: max(v, need) for k, v in dict(p.get("thick") or {}).items()}
        notes.append(f"re-planned at {p['thickness']:g} mm material: at x{scale:.3g} the {plan['params']['thickness']:g} mm parts would print "
                     f"{plan['params']['thickness'] * scale:.2g} mm, thinner than the {min_thick:g} mm minimum, and thicker parts would not fit slots cut for thin ones")
    if offset is not None and abs(p["slot_offset"] * scale - offset) > 1e-9:
        p["slot_offset"] = round(offset / scale, 4)
        notes.append(f"slots {offset:g} mm wider than the material in the print (slot offset {p['slot_offset']:g} mm at x{scale:.3g}); "
                     f"the job's own {plan['params']['slot_offset']:g} mm is for the real material at 1:1")
    if not notes:
        return plan, None
    return build(plan["model"], plan["mode"], p), "; ".join(notes)


def _plate(plan, scene, scale, labels, font, min_thick, dx=0.0, tag=None, plates=None, around=None):
    """Every part of the plan flat in the scene as the nester laid it out (turned as it was nested, sheets stacked in
    y, `dx` along x), each its own named object. `tag` replaces the engraved text and prefixes the names (the fit
    test engraves its offset). `plates`, a dict, takes a scene per sheet instead, each sheet at the origin: a printed
    job's sheet is one build plate. A part with no room for its number gets a tag beside it, part of its object (see
    print_tag). `around` keeps the outlines on each plate between calls (the fit test lays its variants on one plate).
    Yields (piece, mesh at the origin, mesh as placed, where its number is: "part", "tag", or "over" for a tag that
    found no free room and lies over something else)."""
    sheet_h = 0 if plates is not None else plan["sheet"][1] + 20
    around = {} if around is None else around
    laid = []
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            text = tag or pc["label"]
            m, labeled, geom, seams = proto_part({**pc, "label": text}, sl["thickness"], scale, labels, font, min_thick)
            si, x, y, rot = pc["place"]                       # the nested part's lower-left corner and its turn
            turn = trimesh.transformations.rotation_matrix(np.radians(rot), [0, 0, 1])
            q = m.copy(); q.apply_transform(turn)
            move = (dx + x * scale - q.bounds[0][0], (y + si * sheet_h) * scale - q.bounds[0][1])
            q.apply_translation([*move, 0])
            on = around.setdefault(None if plates is None else si, [])
            on.append(affinity.translate(affinity.rotate(geom, rot, origin=(0, 0)), *move))
            laid.append((pc, m, q, labeled, si, text, on, len(on) - 1, turn, move, seams))
    # a printed job's plate is the bed it was nested on, with room kept for the tags; any other plate is arranged in the slicer
    bed = (*plan["sheet"], plan["params"]["sheet_margin"]) if plates is not None else (1e6, 1e6, 0.0)
    for pc, m, q, labeled, si, text, on, k, turn, move, seams in laid:
        where, lost, tags = "part", [], []
        # its own number when it had no room on it, and a printed panel's seam numbers with no room beside their seam
        for t, at in ([(text, None)] if not labeled else []) + [(j, turn[:2, :2] @ (x, y) + move) for x, y, j in seams]:
            mesh, foot, free = print_tag(on, k, t, font if at is None else PRINT_MARK, *bed, toward=at)
            on.append(foot); tags.append(mesh)
            if at is None:
                where = "tag" if free else "over"
            elif not free:
                lost.append(t)
        if tags:
            # joined where the part's file is written: manifold3d's solid is exact in float32 only in the frame it was
            # made in, and turned back after it, edges a float32 apart closed in the part's STL (bugs/067)
            plain = m.metadata["plain"]; back = np.linalg.inv(turn) @ trimesh.transformations.translation_matrix([-move[0], -move[1], 0])
            m = _joined([m, *(t.copy().apply_transform(back) for t in tags)]); m.metadata["plain"] = plain
            q = m.copy(); q.apply_transform(turn); q.apply_translation([*move, 0])
        name = f"{tag} {pc['label']}" if tag else pc["label"]
        (scene if plates is None else plates.setdefault(si, trimesh.Scene())).add_geometry(q, node_name=name, geom_name=name)
        yield pc, m, q, where, lost


def _readme(out_dir, lines, files):
    if lines:
        f = out_dir / "README.txt"; f.write_text("\n".join(lines) + "\n", encoding="utf-8"); files.append(f)
    return files


def _tag_note(tagged, over, font, lost=()):
    """What the README says about the parts that carry their number on a tag, and about the tags (a part's, or a
    seam number's: `lost`, (part, seam)) that found no free room on the plate."""
    lines = []
    if tagged or over:
        lines.append(f"{len(tagged) + len(over)} part(s) have no room for a {max(font, TAG_FONT):g} mm number and carry it on a tag beside them: "
                     f"{', '.join(tagged + over)}. A tag is a chip one layer high on a thin line: read the number, then snap the tag off")
    if over or lost:
        what = [*over, *(f"seam {j} of {p}" for p, j in lost)]
        lines.append(f"no free room on the plate for {len(what)} tag(s): {', '.join(what)}. They lie over other parts: "
                     "arrange the plate in the slicer before printing (a tag moves with its part)")
    return lines


def proto_set(plan, out_dir, scale=1.0, labels="groove", font=5.0, min_thick=1.2, plate=True, note=None):
    """One STL per part (flat) plus plate.3mf holding every part as its own named object, and README.txt when there
    is something to say: `note` (the re-plan, see proto_plan) and the parts that had no room for a label `font` mm
    tall, which carry it on a tag beside them, and the print settings each plate carries (write_3mf). `font` is the
    letter height in printed millimetres whatever the scale: a label has to be read, not scaled.

    The plate is a 3MF scene rather than one concatenated STL because a slicer treats each <object> / <build><item>
    as a separate body: OrcaSlicer and PrusaSlicer can then move, copy and arrange the parts individually.

    A printed job at full size (`printed`, scale 1) was nested on the printer's bed: each sheet is one plate, so it
    gets plate-1.3mf, plate-2.3mf … each laid out as nested, instead of every sheet stacked into one plate no bed holds.
    """
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    files, tagged = [], {"tag": [], "over": []}
    scene = trimesh.Scene()
    plates = {} if plan["params"].get("printed") and abs(scale - 1) < 1e-9 else None
    plain = set()                                          # what could not be cut into the parts here
    lost = []
    for pc, m, _, where, seams in _plate(plan, scene, scale, labels, font, min_thick, plates=plates):
        lost += [(pc["label"], j) for j in seams]
        plain.update(m.metadata.get("plain", ()))
        tagged.get(where, []).append(pc["label"])
        f = out_dir / f"{pc['label']}.stl"; m.export(f); files.append(f)
    written = {}
    for name, sc in ([("plate", scene)] if plates is None else [(f"plate-{si + 1}", plates[si]) for si in sorted(plates)]):
        if plate and len(sc.geometry):
            f = out_dir / f"{name}.3mf"
            written[f.name] = write_3mf(sc, f)
            files.append(f)
    if plan.get("standoffs"):                              # the connectors of the printed layers: a file of their own
        files += standoff_files(plan, out_dir, design_name(plan), scale)
    pins = pin_files(plan, out_dir, written) if plates is not None else []   # a printed job's dowels: printed too, on beds of their own
    files += pins
    lines = ([note] if note else []) + (pin_note(plan) if pins else [])
    if plain:                                             # said, not hidden: a folded panel without its grooves does not fold
        lines.append(f"this build cannot cut solids (no manifold3d, as in the browser): the parts were exported WITHOUT their {' and '.join(sorted(plain))}. "
                     "Printed folded panels need the grooves to fold: export them from the installed app")
    return _readme(out_dir, lines + _tag_note(tagged["tag"], tagged["over"], font, lost) + _settings_note(written), files)


# ---------------------------------------------------------------- fit test: the job's joints on a small stand-in, at offsets around its own
FIT_SIZE = 40.0     # mm across the stand-in sphere; radial grows it so 2 × count half-slices have room around the core
FIT_DROP = ("skip", "offset", "tilt", "roll", "thick", "grow", "extra_x", "extra_y", "dowels", "lines", "curve", "branches", "center")   # edits of the model's own slices


def fit_plan(plan, slot_offset, sheet=None, thickness=None):
    """The job's parameters on a small sphere at `slot_offset` (and `thickness`, the print's when it has to be
    thicker): the joints the model is held by, at the fit to try, without the model. Per-slice edits belong to the
    model and are dropped; the count that makes an assembly tight stays (every radial half-slice wedges at once),
    the others are cut to a few. `sheet` is the job's for cut files; the print gets a small one so the parts lie close."""
    p = {key: v for key, v in plan["params"].items() if key not in FIT_DROP}
    p["slot_offset"] = round(slot_offset, 4)
    p["thickness"] = thickness or p["thickness"]
    p.update(scale=1.0, size=[0, 0, 0], rotate=[0, 0, 0], split=False, autofix="off",
             hide_marks=False)                      # a coupon is known by the offset engraved on it: on every part, the top one too
    from .plan import MODES, build
    mode = plan["mode"]
    few, room = MODES[mode].fit(p)                 # the technique's own: which slices show its joint, on how big a stand-in
    p.update(few)
    size = max(FIT_SIZE, room)
    p["sheet"] = sheet or [max(200.0, 1.2 * size)] * 2
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        trimesh.creation.icosphere(3, size / 2).export(f.name)
    try:
        return build(pathlib.Path(f.name), mode, p)
    finally:
        pathlib.Path(f.name).unlink(missing_ok=True)


def fit_set(plan, out_dir, scale=1.0, labels="groove", font=5.0, min_thick=1.2, offset=0.2, step=0.1, steps=2):
    """Small assemblies to print and try before the prototype: the job's joints at the print slot offset `offset`
    (printed mm) and at ±1 … ±`steps` × `step` mm around it, every part engraved with its offset. The loosest that
    slides together without forcing and still holds is the print slot offset to set. One plate.3mf with the variants
    side by side, one STL per variant, and a README that says which is which. This dials in the print, and only the
    print: a clearance is millimetres, not a ratio, so the real material gets its own test, fit_sheets."""
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    files, tags, tagged, around = [], [], {"tag": [], "over": []}, {}
    scene = trimesh.Scene(); dx = 0.0
    thickness = max(plan["params"]["thickness"], round(min_thick / scale, 3))   # as proto_plan: thick enough to print
    for k in range(-steps, steps + 1):
        printed = round(offset + k * step, 3)
        vp = fit_plan(plan, printed / scale, thickness=thickness)
        tag = f"{printed:.2f}"; tags.append(tag)
        placed = []
        for pc, _, q, where, _ in _plate(vp, scene, scale, labels, font, min_thick, dx, tag, around=around):
            placed.append(q)
            tagged.get(where, []).append(f"{tag} {pc['label']}")
        v = trimesh.util.concatenate(placed); v.apply_translation([-dx, 0, 0])
        f = out_dir / f"fit_{tag}.stl"; v.export(f); files.append(f)
        dx = scene.bounds[1][0] + 10
    f = out_dir / "plate.3mf"; written = {f.name: write_3mf(scene, f)}; files.append(f)
    lines = [f"Print fit test for the {plan['mode']} job at x{scale:.3g}: {len(tags)} small assemblies with its joints, slots {', '.join(tags)} mm "
             f"wider than the material as printed (the print slot offset you set, {tags[steps]}, in the middle), every part engraved with its "
             "value. Print them and put each together: the loosest that slides on without forcing and still holds is the print slot offset to "
             "set (Prototyping). It says nothing about the real material at 1:1 — that is the cut-file fit test (Downloads)."]
    return _readme(out_dir, lines + _tag_note(tagged["tag"], tagged["over"], font) + _settings_note(written), files)


def fit_sheets(plan, out_dir, fmts=("svg", "dxf"), labels=True, step=0.1, steps=2):
    """The fit test as cut files at 1:1, for the real machine and material: the job's joints on the stand-in at its
    slot offset and ±1 … ±`steps` × `step` mm, a folder of sheets per offset, every part labelled with its offset.
    The loosest that still holds is the slot offset to set. This is the test that predicts the model's fit; a
    scaled print (fit_set) cannot, a clearance being millimetres, not a ratio, and the process and material theirs."""
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    files, tags = [], []
    for k in range(-steps, steps + 1):
        off = round(plan["params"]["slot_offset"] + k * step, 3); tag = f"{off:.2f}"; tags.append(tag)
        vp = fit_plan(plan, off, plan["params"]["sheet"])
        vp["label_tag"] = ""                                   # a coupon is known by its offset, not by the model
        for sl in vp["slices"]:
            for pc in sl["pieces"]:
                pc["label"] = tag                              # as short as the name it replaces: the label box was nested for that
        files += export(vp, out_dir / f"fit_{tag}", fmts, labels)
    lines = [f"Fit test for the {plan['mode']} job as cut files at 1:1, for the real machine and material: {len(tags)} small assemblies with "
             f"its joints, at slot offsets {', '.join(tags)} mm (the job's own, {tags[steps]}, in the middle), a folder of sheets each, every "
             "part labelled with its offset. Cut them and put each together: the loosest that slides on without forcing and still holds is "
             "the slot offset to set (Fit → slot offset)."]
    return _readme(out_dir, lines, files)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan"); ap.add_argument("--out"); ap.add_argument("--part")
    ap.add_argument("--body", action="store_true", help="with --out x.step: the whole model fused into one solid")
    ap.add_argument("--proto", help="output dir for the prototyping set"); ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--fit", help="output dir for the fit test: the job's joints on a small stand-in at 5 slot offsets"); ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--labels", choices=["none", "groove", "hole"], default="groove"); ap.add_argument("--min-thick", type=float, default=1.2)
    ap.add_argument("--font", type=float, default=5.0, help="label letter height in printed mm, whatever the scale")
    ap.add_argument("--offset", type=float, default=0.2, help="print slot offset: slots this much wider than the material, in printed mm")
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
    if not (a.out or a.proto or a.fit):
        ap.error("nothing to write: give --out, --proto or --fit")
    if a.fit:
        for f in fit_set(plan, a.fit, a.scale, a.labels, a.font, a.min_thick, a.offset, a.step):
            print(f)
    elif a.proto:
        plan, note = proto_plan(plan, a.scale, a.min_thick, a.offset)
        if note:
            print(note)
        for f in proto_set(plan, a.proto, a.scale, a.labels, a.font, a.min_thick, note=note):
            print(f)
    else:
        fmt = pathlib.Path(a.out).suffix[1:].lower()
        try:
            pathlib.Path(a.out).write_bytes(solid_bytes(plan, a.part, "step" if fmt == "stp" else fmt, a.body))
        except LookupError as e:
            ap.error(str(e))
        print(a.out)


if __name__ == "__main__":
    main()
