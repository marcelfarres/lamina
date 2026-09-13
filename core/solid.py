"""3D solids from a plan (pure trimesh): assembled model, one part, or a prototyping set — every part flat for
3D printing at a chosen scale, with its label engraved as a groove or cut through. The set includes plate.3mf,
which opens in OrcaSlicer / PrusaSlicer as one named object per part, ready to arrange.

    uv run python -m core.solid working-files/egg.json --out working-files/egg_assembled.stl [--part X-3]
    uv run python -m core.solid working-files/egg.json --proto working-files/egg_proto --scale 0.5 --labels groove
    uv run python -m core.solid working-files/egg.json --fit working-files/egg_fit --step 0.1     # 5 slot offsets to try first
"""
from __future__ import annotations
import argparse, contextlib, json, math, pathlib, tempfile
import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
import shapely


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
    for fc in pc["facets"]:
        M = np.array(fc["M"])
        for rings in fc["rings"]:
            poly = Polygon(rings[0], rings[1:])
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            m = extrude(poly, thickness)
            m.apply_translation([0, 0, -thickness / 2]); m.apply_transform(M)
            parts.append(m)
    return trimesh.util.concatenate(parts) if parts else trimesh.Trimesh()


def assembled(plan, part=None) -> trimesh.Trimesh:
    ms = [piece_mesh(pc, sl["thickness"]) for sl in plan["slices"] for pc in sl["pieces"] if part is None or pc["label"] == part]
    return trimesh.util.concatenate(ms) if ms else trimesh.Trimesh()


# ---------------------------------------------------------------- text → polygons (labels engraved in prototypes)
def text_polygons(text, height, res=8) -> MultiPolygon:
    """Glyph outlines of `text` as polygons, the capitals `height` mm tall (rendered with Pillow, traced with
    scikit-image). Bold, so the strokes print: at 5 mm they are about 0.8 mm wide, two passes of a 0.4 mm nozzle."""
    from PIL import Image, ImageDraw, ImageFont
    from skimage import measure
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
    # outer contours minus inner ones (holes of 'o', 'a' …): even-odd via symmetric differences of nested polygons
    polys.sort(key=lambda g: -g.area)
    out = []
    for g in polys:
        if not g.is_valid:
            g = g.buffer(0)
        holder = next((h for h in out if h.contains(g.representative_point())), None)
        if holder is None:
            out.append(g)
        else:
            out[out.index(holder)] = holder.difference(g)
    if not out:
        return MultiPolygon()
    g = unary_union(out)
    k = height / (g.bounds[3] - g.bounds[1])
    return affinity.scale(g, k, k, origin=(0, 0))


def label_inside(geom, text, min_h, inset=1.0):
    """The label as polygons inside the part: at the fattest spot of its largest region (the centre of the biggest
    inscribed circle, so away from every edge and slot), turned along the region's long axis and slid along it as
    far as a label length when the fat spot is near an end, 1.5 × `min_h` tall where that fits and `min_h`
    otherwise. None when even `min_h` fits nowhere: the part then gets no label and the README says so, rather
    than a label too small to read or one cut into an edge."""
    from .nest import _min_rect_angle
    txt = text_polygons(text, min_h)
    tx, ty = (txt.bounds[0] + txt.bounds[2]) / 2, (txt.bounds[1] + txt.bounds[3]) / 2
    w = txt.bounds[2] - txt.bounds[0]
    inner = geom.buffer(-inset)
    for g in sorted(getattr(inner, "geoms", [inner]), key=lambda g: -g.area)[:3]:
        if g.is_empty:
            continue
        cx, cy = shapely.maximum_inscribed_circle(g, 0.1).coords[0]
        along = -_min_rect_angle(g)
        for rot in (along, along + 90):
            rot = (rot + 90) % 180 - 90                                  # never upside down
            ux, uy = np.cos(np.radians(rot)), np.sin(np.radians(rot))
            for f in (1.5, 1.0):
                base = affinity.rotate(affinity.scale(txt, f, f, origin=(tx, ty)), rot, origin=(tx, ty))
                for s in (0, -0.25, 0.25, -0.5, 0.5, -1, 1):
                    tt = affinity.translate(base, cx - tx + s * f * w * ux, cy - ty + s * f * w * uy)
                    if g.contains(tt):
                        return tt
    return None


def proto_part(pc, thickness, scale, labels, font, min_thick):
    """One part flat on z = 0 at `scale`, its label (`font` mm tall at least, see label_inside) as a groove (half
    depth, 0.6 mm at most) or a hole (through). Returns the mesh and whether the part got its label."""
    geom = unary_union([Polygon(r[0], r[1:]) for r in pc["kerfed"]]).buffer(0)
    geom = affinity.scale(geom, scale, scale, origin=(0, 0))
    x0, y0, x1, y1 = geom.bounds
    geom = affinity.translate(geom, -x0, -y0)
    t = max(thickness * scale, min_thick)
    label = label_inside(geom, pc["label"], font) if labels != "none" else None
    if label is not None and labels == "hole":
        geom = geom.difference(label)
    mesh = trimesh.util.concatenate([extrude(g, t) for g in getattr(geom, "geoms", [geom]) if g.area > 0])
    if label is not None and labels == "groove":
        depth = min(t * 0.5, 0.6)
        groove = trimesh.util.concatenate([extrude(g, depth + 0.01) for g in getattr(label, "geoms", [label]) if g.area > 0])
        groove.apply_translation([0, 0, t - depth])
        with contextlib.suppress(Exception):               # engine missing (the browser build): leave the part plain;
            mesh = trimesh.boolean.difference([mesh, groove], engine="manifold")   # named, or trimesh may wait on a Blender it finds
    return mesh, label is not None or labels == "none"


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


def _plate(plan, scene, scale, labels, font, min_thick, dx=0.0, tag=None):
    """Every part of the plan flat in the scene as the nester laid it out (turned as it was nested, sheets stacked in
    y, `dx` along x), each its own named object. `tag` replaces the engraved text and prefixes the names (the fit
    test engraves its offset). Yields (piece, mesh at the origin, mesh as placed, whether it got its label)."""
    sheet_h = plan["sheet"][1] + 20
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            m, labeled = proto_part({**pc, "label": tag or pc["label"]}, sl["thickness"], scale, labels, font, min_thick)
            si, x, y, rot = pc["place"]                       # the nested part's lower-left corner and its turn
            q = m.copy(); q.apply_transform(trimesh.transformations.rotation_matrix(np.radians(rot), [0, 0, 1]))
            q.apply_translation([dx + x * scale - q.bounds[0][0], (y + si * sheet_h) * scale - q.bounds[0][1], 0])
            name = f"{tag} {pc['label']}" if tag else pc["label"]
            scene.add_geometry(q, node_name=name, geom_name=name)
            yield pc, m, q, labeled


def _readme(out_dir, lines, files):
    if lines:
        f = out_dir / "README.txt"; f.write_text("\n".join(lines) + "\n", encoding="utf-8"); files.append(f)
    return files


def _unlabeled_note(unlabeled, font):
    return f"no room for a {font:g} mm label on {len(unlabeled)} part(s): {', '.join(unlabeled)} — a smaller label size would fit them"


def proto_set(plan, out_dir, scale=1.0, labels="groove", font=5.0, min_thick=1.2, plate=True, note=None):
    """One STL per part (flat) plus plate.3mf holding every part as its own named object, and README.txt when there
    is something to say: `note` (the re-plan, see proto_plan) and the parts that had no room for a label `font` mm
    tall. `font` is the letter height in printed millimetres whatever the scale: a label has to be read, not scaled.

    The plate is a 3MF scene rather than one concatenated STL because a slicer treats each <object> / <build><item>
    as a separate body: OrcaSlicer and PrusaSlicer can then move, copy and arrange the parts individually.
    """
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    files, unlabeled = [], []
    scene = trimesh.Scene()
    for pc, m, _, labeled in _plate(plan, scene, scale, labels, font, min_thick):
        if not labeled:
            unlabeled.append(pc["label"])
        f = out_dir / f"{pc['label']}.stl"; m.export(f); files.append(f)
    if plate and len(scene.geometry):
        f = out_dir / "plate.3mf"
        f.write_bytes(scene.export(file_type="3mf"))
        files.append(f)
    lines = [note] if note else []
    if unlabeled:
        lines.append(_unlabeled_note(unlabeled, font))
    return _readme(out_dir, lines, files)


# ---------------------------------------------------------------- fit test: the job's joints on a small stand-in, at offsets around its own
FIT_SIZE = 40.0     # mm across the stand-in sphere; radial grows it so 2 × count half-slices have room around the core
FIT_DROP = ("skip", "offset", "tilt", "roll", "thick", "grow", "extra_x", "extra_y", "dowels", "lines", "curve", "center")   # edits of the model's own slices


def fit_plan(plan, slot_offset, sheet=None, thickness=None):
    """The job's parameters on a small sphere at `slot_offset` (and `thickness`, the print's when it has to be
    thicker): the joints the model is held by, at the fit to try, without the model. Per-slice edits belong to the
    model and are dropped; the count that makes an assembly tight stays (every radial half-slice wedges at once),
    the others are cut to a few. `sheet` is the job's for cut files; the print gets a small one so the parts lie close."""
    p = {key: v for key, v in plan["params"].items() if key not in FIT_DROP}
    p["slot_offset"] = round(slot_offset, 4)
    p["thickness"] = thickness or p["thickness"]
    p.update(scale=1.0, size=[0, 0, 0], rotate=[0, 0, 0], split=False, autofix="off")
    mode, size = plan["mode"], FIT_SIZE
    if mode == "radial":
        p.update(rings="count", ring_count=min(p["ring_count"], 2))
        need = 2 * (p["count"] * (p["thickness"] + p["slot_offset"]) / math.pi + p["thickness"])    # as radial.py sizes the core
        size = max(size, 2 * need)
    elif mode == "interlocked":
        p.update(distribution="count", nx=min(p["nx"], 4), ny=min(p["ny"], 4))
    elif mode in ("stacked", "curve"):
        p.update(distribution="count", count=min(p["count"], 3))
    p["sheet"] = sheet or [max(200.0, 1.2 * size)] * 2
    from .plan import build
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
    files, unlabeled, tags = [], [], []
    scene = trimesh.Scene(); dx = 0.0
    thickness = max(plan["params"]["thickness"], round(min_thick / scale, 3))   # as proto_plan: thick enough to print
    for k in range(-steps, steps + 1):
        printed = round(offset + k * step, 3)
        vp = fit_plan(plan, printed / scale, thickness=thickness)
        tag = f"{printed:.2f}"; tags.append(tag)
        placed = []
        for pc, _, q, labeled in _plate(vp, scene, scale, labels, font, min_thick, dx, tag):
            placed.append(q)
            if not labeled:
                unlabeled.append(f"{tag} {pc['label']}")
        v = trimesh.util.concatenate(placed); v.apply_translation([-dx, 0, 0])
        f = out_dir / f"fit_{tag}.stl"; v.export(f); files.append(f)
        dx = scene.bounds[1][0] + 10
    f = out_dir / "plate.3mf"; f.write_bytes(scene.export(file_type="3mf")); files.append(f)
    lines = [f"Print fit test for the {plan['mode']} job at x{scale:.3g}: {len(tags)} small assemblies with its joints, slots {', '.join(tags)} mm "
             f"wider than the material as printed (the print slot offset you set, {tags[steps]}, in the middle), every part engraved with its "
             "value. Print them and put each together: the loosest that slides on without forcing and still holds is the print slot offset to "
             "set (Prototyping). It says nothing about the real material at 1:1 — that is the cut-file fit test (Downloads)."]
    if unlabeled:
        lines.append(_unlabeled_note(unlabeled, font))
    return _readme(out_dir, lines, files)


def fit_sheets(plan, out_dir, fmts=("svg", "dxf"), labels=True, step=0.1, steps=2):
    """The fit test as cut files at 1:1, for the real machine and material: the job's joints on the stand-in at its
    slot offset and ±1 … ±`steps` × `step` mm, a folder of sheets per offset, every part labelled with its offset.
    The loosest that still holds is the slot offset to set. This is the test that predicts the model's fit; a
    scaled print (fit_set) cannot, a clearance being millimetres, not a ratio, and the process and material theirs."""
    from .export import export
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    files, tags = [], []
    for k in range(-steps, steps + 1):
        off = round(plan["params"]["slot_offset"] + k * step, 3); tag = f"{off:.2f}"; tags.append(tag)
        vp = fit_plan(plan, off, plan["params"]["sheet"])
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
    ap.add_argument("--proto", help="output dir for the prototyping set"); ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--fit", help="output dir for the fit test: the job's joints on a small stand-in at 5 slot offsets"); ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--labels", choices=["none", "groove", "hole"], default="groove"); ap.add_argument("--min-thick", type=float, default=1.2)
    ap.add_argument("--font", type=float, default=5.0, help="label letter height in printed mm, whatever the scale")
    ap.add_argument("--offset", type=float, default=0.2, help="print slot offset: slots this much wider than the material, in printed mm")
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
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
        assembled(plan, a.part).export(a.out); print(a.out)


if __name__ == "__main__":
    main()
