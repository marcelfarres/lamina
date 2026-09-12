"""3D solids from a plan (pure trimesh): assembled model, one part, or a prototyping set — every part flat for
3D printing at a chosen scale, with its label engraved as a groove or cut through. The set includes plate.3mf,
which opens in OrcaSlicer / PrusaSlicer as one named object per part, ready to arrange.

    uv run python -m core.solid working-files/egg.json --out working-files/egg_assembled.stl [--part X-3]
    uv run python -m core.solid working-files/egg.json --proto working-files/egg_proto --scale 0.5 --labels groove
"""
from __future__ import annotations
import argparse, contextlib, json, pathlib
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
    """Glyph outlines of `text` as polygons `height` mm tall (rendered with Pillow, traced with scikit-image)."""
    from PIL import Image, ImageDraw, ImageFont
    from skimage import measure
    px = int(height * res)
    try:
        font = ImageFont.truetype("arial.ttf", px)
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
    return unary_union(out) if out else MultiPolygon()


def proto_part(pc, thickness, scale, labels, font, min_thick) -> trimesh.Trimesh:
    """One part flat on z = 0 at `scale`, with its label as a groove (half depth) or a hole (through)."""
    geom = unary_union([Polygon(r[0], r[1:]) for r in pc["kerfed"]]).buffer(0)
    geom = affinity.scale(geom, scale, scale, origin=(0, 0))
    x0, y0, x1, y1 = geom.bounds
    geom = affinity.translate(geom, -x0, -y0)
    t = max(thickness * scale, min_thick)
    label = None
    if labels != "none":
        txt = text_polygons(pc["label"], font)
        tx0, ty0, tx1, ty1 = txt.bounds
        c = geom.representative_point()
        # place the label at the biggest inscribed spot; shrink it until it fits inside the part with a margin
        for f in (1.0, 0.75, 0.55, 0.4):
            tt = affinity.scale(txt, f, f, origin=(0, 0))
            bx0, by0, bx1, by1 = tt.bounds
            tt = affinity.translate(tt, c.x - (bx0 + bx1) / 2, c.y - (by0 + by1) / 2)
            if geom.buffer(-0.6).contains(tt):
                label = tt; break
    if label is not None and labels == "hole":
        geom = geom.difference(label)
    mesh = trimesh.util.concatenate([extrude(g, t) for g in getattr(geom, "geoms", [geom]) if g.area > 0])
    if label is not None and labels == "groove":
        depth = min(t * 0.5, 0.6)
        groove = trimesh.util.concatenate([extrude(g, depth + 0.01) for g in getattr(label, "geoms", [label]) if g.area > 0])
        groove.apply_translation([0, 0, t - depth])
        with contextlib.suppress(Exception):               # engine missing (the browser build): leave the part plain;
            mesh = trimesh.boolean.difference([mesh, groove], engine="manifold")   # named, or trimesh may wait on a Blender it finds
    return mesh


def proto_plan(plan, scale, min_thick):
    """The plan the prototype is cut from. Parts scaled below `min_thick` cannot simply be printed thicker: their
    slots and holes were sized for the thin material and nothing would fit. So the whole job is planned again at the
    material thickness that prints to `min_thick` — every slot follows. Returns (plan, note); note is None when the
    plan as it stands prints thick enough."""
    thin = min(sl["thickness"] for sl in plan["slices"]) if plan["slices"] else plan["params"]["thickness"]
    if thin * scale >= min_thick - 1e-9:
        return plan, None
    from .plan import build
    p = dict(plan["params"]); need = round(min_thick / scale, 3)
    p["thickness"] = max(p["thickness"], need)
    p["thick"] = {k: max(v, need) for k, v in dict(p.get("thick") or {}).items()}
    note = (f"re-planned at {p['thickness']:g} mm material: at x{scale:.3g} the {plan['params']['thickness']:g} mm parts would print "
            f"{plan['params']['thickness'] * scale:.2g} mm, thinner than the {min_thick:g} mm minimum, and thicker parts would not fit slots cut for thin ones")
    return build(plan["model"], plan["mode"], p), note


def proto_set(plan, out_dir, scale=1.0, labels="groove", font=None, min_thick=1.2, plate=True):
    """One STL per part (flat) plus plate.3mf holding every part as its own named object.

    The plate is a 3MF scene rather than one concatenated STL because a slicer treats each <object> / <build><item>
    as a separate body: OrcaSlicer and PrusaSlicer can then move, copy and arrange the parts individually.
    """
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    font = font or max(2.5, plan["params"].get("font", 4.0) * scale)
    files = []
    scene = trimesh.Scene()
    sheet_h = plan["sheet"][1] + 20
    for sl in plan["slices"]:
        for pc in sl["pieces"]:
            m = proto_part(pc, sl["thickness"], scale, labels, font, min_thick)
            f = out_dir / f"{pc['label']}.stl"; m.export(f); files.append(f)
            if plate:
                si, x, y, rot = pc["place"]
                q = m.copy(); q.apply_translation([x * scale, (y + si * sheet_h) * scale, 0])
                scene.add_geometry(q, node_name=pc["label"], geom_name=pc["label"])
    if plate and len(scene.geometry):
        f = out_dir / "plate.3mf"
        f.write_bytes(scene.export(file_type="3mf"))
        files.append(f)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan"); ap.add_argument("--out"); ap.add_argument("--part")
    ap.add_argument("--proto", help="output dir for the prototyping set"); ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--labels", choices=["none", "groove", "hole"], default="groove"); ap.add_argument("--min-thick", type=float, default=1.2)
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
    if a.proto:
        plan, note = proto_plan(plan, a.scale, a.min_thick)
        if note:
            print(note)
        for f in proto_set(plan, a.proto, a.scale, a.labels, min_thick=a.min_thick):
            print(f)
    else:
        assembled(plan, a.part).export(a.out); print(a.out)


if __name__ == "__main__":
    main()
