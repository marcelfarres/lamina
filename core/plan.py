"""Pipeline: mesh → modify form → mode.build → sections → cuts → checks → split → pack → plan.json.

    uv run python -m core.plan examples/egg.stl --mode interlocked --set nx=5 ny=4 thickness=3 --out working-files/egg
"""
from __future__ import annotations
import argparse, json, pathlib, time
import numpy as np
import trimesh
from shapely import affinity
from shapely.ops import unary_union
from .modes import load_all, Ctx
from .geometry import section_polygons, as_multi, poly_coords, line_coords
from .checks import check_plan, min_dims, autofix, suggest_fixes, crossing_suggestions
from .split import split_slice, fits_rotated
from .nest import nest, _min_rect_angle
from .model import Piece

MODES = load_all()
CAD_SUFFIXES = {".step", ".stp", ".brep", ".iges", ".igs"}


def report(text, frac):
    """Where progress() forwards each stage of build(): what is happening and how far along (0..1). A no-op here; the
    browser worker points it at the page, where a slice of a big model in Pyodide takes long enough to look stuck."""


STAGES: list[tuple[str, float]] = []      # (stage text, clock) marks of the build under way — one build at a time per process


def progress(text, frac):
    STAGES.append((text, time.perf_counter()))
    report(text, frac)


def timing() -> dict[str, float]:
    """Seconds per stage of the build, read off the progress marks; a counted stage ("sectioning 3 / 16") folds into
    one row. This is what an optimisation has to move, so it rides in the plan and in the server's timing log."""
    out = {}
    for (text, t0), (_, t1) in zip(STAGES, STAGES[1:]):
        k = text.split(" ")[0] if text[-1].isdigit() else text
        out[k] = round(out.get(k, 0.0) + t1 - t0, 3)
    return out


def coerce_params(mode, raw: dict) -> dict:
    p = {prm.name: prm.coerce(raw.get(prm.name)) for prm in mode.all_params()}
    if p.get("autofix") not in ("add", "remove", "off"):            # older projects stored a boolean
        p["autofix"] = "off" if str(p.get("autofix")).lower() in ("false", "0") else "add"
    if "cloth" in raw and "separate" not in raw:                    # older names
        p["separate"] = bool(raw["cloth"])
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


def rasterize(seg, shape):
    """Even-odd scanline fill of one layer from its cut segments (n, 2, 2) in grid units: the point (i, j) is inside
    when an odd number of segments cross the row j to its left. Works on the bare segment soup — no loop linking, so
    a missing triangle (an open loop) costs nothing, and it is one numpy pass for the whole layer."""
    y = np.arange(shape[1])[:, None]
    (x0, y0), (x1, y1) = seg[:, 0].T[:, None, :], seg[:, 1].T[:, None, :]           # (1, n) each, against rows (m, 1)
    cross = (y0 <= y) != (y1 <= y)                                                    # half-open rule: a vertex on the row counts once
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.where(cross, x0 + (y - y0) * (x1 - x0) / (y1 - y0), 0)
    rows, cols = np.nonzero(cross)[0], np.clip(np.ceil(x[cross]), 0, None).astype(int)   # a crossing left of the grid counts for every point
    keep = cols < shape[0]
    count = np.zeros(shape, int)
    np.add.at(count, (cols[keep], rows[keep]), 1)
    return np.cumsum(count, axis=0) % 2 == 1


def voxelize_solid(mesh, pitch):
    """Occupancy grid of the solid at `pitch` — the matrix and the world position of its [0, 0, 0] voxel. The mesh is
    cut at every layer and the cut rasterised, so the grid is solid from the start. trimesh's own voxeliser splits
    every triangle down to half a voxel and then fills the shell: 13 s on a 40k-face head at 1 mm, where this takes
    about a second. Like that shell, this is conservative: the samples sit at the voxels' corners and a voxel is solid
    when any of its eight corners is inside, so the solid grows by half a voxel and a thin feature — a bunny's ear
    at 1.7 mm — survives instead of vanishing between voxel centres."""
    from scipy import ndimage
    from trimesh.intersections import mesh_plane
    lo = np.floor(mesh.bounds[0] / pitch).astype(int) - 1
    n = np.ceil(mesh.bounds[1] / pitch).astype(int) + 2 - lo
    c = np.zeros(n + 1, bool)                          # corner samples: c[j] sits at (lo + j - 0.5) * pitch
    for k in range(n[2] + 1):
        seg = mesh_plane(mesh, [0, 0, 1], [0, 0, (lo[2] + k - 0.5) * pitch])
        if not len(seg):
            continue
        seg = seg[:, :, :2] / pitch - lo[:2] + 0.5
        _, ends = np.unique(np.round(seg.reshape(-1, 2), 4), axis=0, return_counts=True)
        if (ends % 2).any():                  # an end where an odd number of segments meet: a loop is open (a hole in a
            chains = trimesh.load_path(seg).discrete   # scan) — link the segments into chains and close each straight across
            seg = np.concatenate([np.stack([ch, np.roll(ch, -1, 0)], 1) for ch in chains])
        c[:, :, k] = rasterize(seg, n[:2] + 1)
    m = c[:-1] | c[1:]; m = m[:, :-1] | m[:, 1:]; m = m[:, :, :-1] | m[:, :, 1:]
    return ndimage.binary_fill_holes(m), lo * pitch     # a cavity — a scan's inner surface, a duplicated shell — is solid, as before


def modify_form(mesh, p, notes):
    """Slicer's Modify Form: shrinkwrap (voxel remesh), round (drop features smaller than r and round corners =
    morphological opening + closing), thicken (dilate), hollow (keep a wall). One voxel pass."""
    from scipy import ndimage
    pitch = max(p["shrinkwrap"] or max(mesh.extents) / 120, max(mesh.extents) / 300)   # 300³ voxels at most: a fine pitch on a big model is a memory request, not a detail
    pad = int(np.ceil((p["thicken"] + p["round"]) / pitch)) + 2
    m, origin = voxelize_solid(mesh, pitch)
    m = np.pad(m, pad)
    if p["round"]:
        n = max(1, int(round(p["round"] / pitch)))
        ball = ndimage.generate_binary_structure(3, 1)
        m = ndimage.binary_opening(m, ball, iterations=n)        # removes thin / pointy features
        m = ndimage.binary_closing(m, ball, iterations=n)        # fills narrow gaps, rounds concave corners
    if p["thicken"]:   # at least one voxel: scipy reads iterations < 1 as "until nothing changes", which fills the whole box
        m = ndimage.binary_dilation(m, iterations=max(1, int(round(p["thicken"] / pitch))))
    if p["hollow"]:
        n = max(1, int(round(p["hollow"] / pitch)))
        m = m & ~ndimage.binary_erosion(m, iterations=n)
    out = trimesh.voxel.ops.matrix_to_marching_cubes(m, pitch=pitch)
    out.apply_translation(origin - pad * pitch)
    notes.append(f"modify form: remeshed at {pitch:.2f} mm voxels ({len(out.faces)} faces)")
    return out


def smooth_mesh(mesh, iterations):
    """Taubin smoothing (volume-preserving Laplacian): softens pointy vertices without shrinking the model."""
    m = mesh.copy()
    trimesh.smoothing.filter_taubin(m, iterations=int(iterations))
    return m


ONE_SHEET_H = 100000.0     # "one sheet" mode nests against this height and reports the length actually used


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
    import shapely
    pts = mesh.sample(3000, seed=0)                      # seeded: the same model and params must give the same plan
    if len(pts) == 0:
        return 1.0
    covered = np.zeros(len(pts), bool)
    P = np.c_[pts, np.ones(len(pts))]
    for sl in slices:
        if sl.profile is None or sl.group in ("P", "J"):
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


def load_mesh(path, params, notes=None, mode=""):
    notes = [] if notes is None else notes
    path = pathlib.Path(path)
    progress("loading the model", 0.02)
    mesh = load_cad(path) if path.suffix.lower() in CAD_SUFFIXES else trimesh.load(path, force="mesh")
    if params["up_axis"] != "z":
        src = "xyz".index(params["up_axis"])
        mesh.apply_transform(trimesh.geometry.align_vectors(np.eye(3)[src], [0, 0, 1]))
    rot = params.get("rotate") or [0, 0, 0]
    if any(rot):
        mesh.apply_transform(trimesh.transformations.euler_matrix(*np.radians(rot[:3]), "sxyz"))
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
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
    open_surface = not mesh.is_watertight and mode == "folded"      # masks, clothing patterns: keep the surface, no repair
    if open_surface:
        notes.append("open surface (not a closed solid): kept as is — its boundary edges stay open, only inner edges get joints")
    if params["shrinkwrap"] or params["hollow"] or params["thicken"] or params["round"] or (not mesh.is_watertight and not open_surface):
        if not mesh.is_watertight and not params["shrinkwrap"]:
            notes.append("mesh is not watertight — auto shrinkwrap applied (set shrinkwrap to control the resolution)")
        progress("modify form: remeshing", 0.06)
        mesh = modify_form(mesh, params, notes)
    if params["smooth"]:
        progress("smoothing", 0.16)
        mesh = smooth_mesh(mesh, params["smooth"])
    mesh.apply_translation(-mesh.bounds.mean(0))
    return mesh


def _match(c, g, tol, mirror):
    """How outline `g` fits outline `c` (both at the origin, long side along x): "same" under some quarter turn,
    "flipped" when it only fits as its mirror image, None when it does not fit at all."""
    if abs(c.area - g.area) > tol * c.area:
        return None
    tries = (("same", g), ("flipped", affinity.scale(g, -1, 1, origin=(0, 0)))) if mirror else (("same", g),)
    for kind, m in tries:
        for r in (0, 90, 180, 270):
            h = affinity.rotate(m, r, origin=(0, 0)); x0, y0, _, _ = h.bounds
            if c.symmetric_difference(affinity.translate(h, -x0, -y0)).area <= tol * c.area:
                return kind
    return None


def mark_identical(pieces, mirror=False, tol=1e-3):
    """Pieces with the same cut outline — kerf applied, any quarter turn, and with `mirror` also turned over — are one
    part in several copies: the first of each set keeps the others' labels in `same`, the ones that have to be turned
    over in `flipped`, so they are cut once with a quantity and listed once."""
    groups = []                                     # [(first piece, its outline at the origin)]
    for pc in pieces:
        if pc.lines:                                # score lines (folded panels): each fold pattern is its own part
            continue
        g = affinity.rotate(pc.kerfed, _min_rect_angle(pc.kerfed), origin=(0, 0))
        x0, y0, _, _ = g.bounds; g = affinity.translate(g, -x0, -y0)
        for first, c in groups:
            # same outline but cut from other stock is not the same part: it belongs on the other thickness's sheet
            kind = _match(c, g, tol, mirror) if first.parent.thickness == pc.parent.thickness else None
            if kind:
                (first.same if kind == "same" else first.flipped).append(pc.label)
                break
        else:
            groups.append((pc, g))


def build(model_path, mode_name, raw_params, out=None, mesh_out=None):
    mode = MODES[mode_name]
    p = coerce_params(mode, raw_params)
    notes = []
    STAGES.clear()
    mesh = load_mesh(model_path, p, notes, mode_name)
    if mesh_out:                                    # processed model for the browser's ghost view (decimated)
        progress("preparing the preview model", 0.18)
        ghost = mesh
        if len(mesh.faces) > 30000:
            try:
                import fast_simplification
                v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.int32), target_count=30000)
                ghost = trimesh.Trimesh(v, f)
            except ImportError:                          # no wheel for the browser build: the ghost is the whole mesh
                pass
        ghost.export(mesh_out)
    sheet0 = list(p["sheet"])
    if p["one_sheet"]:                              # one strip as wide as the sheet, as long as it needs: nest against a huge height
        p["sheet"] = [sheet0[0], ONE_SHEET_H]
    # build → section → check; with autofix = add, floating regions get a crossing slice and we build again (2 rounds)
    for attempt in range(3):
        progress("placing slices and slots", 0.2)
        ctx = Ctx(mesh, p)
        slices = mode.build(ctx)
        kept = []
        for i, sl in enumerate(slices):         # sections → profiles (modes may hand over a finished `raw` for synthetic parts)
            progress(f"sectioning {i + 1} / {len(slices)}", 0.35 + 0.35 * i / len(slices))
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
            if prof.is_empty:
                sl.errors.append("slots/holes remove all material — dropped")
                continue
            sl.profile = prof
            kept.append(sl)
        dropped = [s for s in slices if s not in kept]
        slices = kept
        progress("checking the parts and the assembly", 0.7)
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
    if p["autofix"] != "off" and n_err:
        slices, fixed = autofix(slices, p)
        if fixed:
            notes += fixed
            n_err, n_warn = check_plan(slices, p, mesh, ctx.span)
    suggest_fixes(slices, p, ctx, mode)
    n_err += len(ctx.errors) + len(dropped)

    # split + pack
    progress("nesting the parts on sheets", 0.85)
    for sl in slices:
        if p["split"] and sl.facets is None:
            split_slice(sl, p["sheet"], p["sheet_margin"], p["tab"])
        else:
            sl.pieces = [Piece(sl.label, sl.profile, sl, sl.lines, sl.marks)]
            if not fits_rotated(sl.profile, p["sheet"], p["sheet_margin"]):
                small, large = min_dims(sl.profile)      # rotation is free on the sheet
                sl.errors.append(f"does not fit the sheet ({large:.0f}×{small:.0f} mm) — "
                                 + ("split cannot cut a folded panel: use a smaller facet size or a bigger sheet" if sl.facets is not None
                                    else "enable split or use a bigger sheet"))
    pieces = [pc for sl in slices for pc in sl.pieces]
    kerf = p["kerf"] if p["compensate"] else 0.0       # off by default: many machines compensate their own kerf
    n_sheets = nest(pieces, p["sheet"], p["gap"], p["sheet_margin"], kerf, p["font"] * 1.6 if p["labels"] else 0, p["font"])
    mark_identical(pieces, p["mirror_ok"])             # which parts are the same part: one cut file, one row, a quantity
    sheet_thick = [p["thickness"]] * n_sheets           # the stock each sheet is cut from: nest keeps one per sheet
    for pc in pieces:
        sheet_thick[pc.place[0]] = pc.parent.thickness
    sheet_out = sheet0
    if p["one_sheet"]:                              # report the strip at the length the parts actually took
        top = max((pc.placed.bounds[3] for pc in pieces), default=0.0) + p["sheet_margin"]
        sheet_out = [sheet0[0], float(np.ceil(top))]; p["sheet"] = sheet0
    progress("measuring coverage", 0.94)
    cov = coverage(mesh, slices, getattr(ctx, "cover_r", max(mesh.extents) / 8), lat=max(3.0, p["thickness"]))
    progress("done", 1.0)
    if getattr(ctx, "notes_extra", None):
        notes.append(ctx.notes_extra)
    if cov < 0.9:
        notes.append(f"model coverage {cov:.0%}: parts of the model have no geometry — more slices (count / spacing), a different axis, or round/thicken thin features")

    plan = {
        "model": str(pathlib.Path(model_path).resolve()), "mode": mode_name, "params": p, "notes": notes,
        "bbox": [float(e) for e in mesh.extents],
        "axes": [a.tolist() for a in ctx.ax], "mid": ctx.mid.tolist(),      # slicing frame (for click-placed points in the UI)
        "curve3d": getattr(ctx, "curve3d", None), "curve_pts": getattr(ctx, "curve_pts", None),
        "rods": getattr(ctx, "rods", []),                                    # dowel rods for the 3D view: [[x0,y0,z0],[x1,y1,z1],d]
        "params_used": {k: p[k] for k in ("extra_x", "extra_y", "ring_count") if k in p},   # what autofix=add changed
        "sheets": n_sheets, "sheet": sheet_out, "sheet_thick": sheet_thick, "kerf": kerf,
        "counts": {"slices": len(slices), "parts": len(pieces), "errors": n_err, "warnings": n_warn, "faces": int(len(mesh.faces))},
        "errors": ctx.errors,
        "material_area_mm2": float(sum(pc.geom.area for pc in pieces)),
        "coverage": cov,
        "timing": timing(),
        "core_d_min": getattr(ctx, "core_d_min", None),
        "sheet_usage": float(sum(pc.geom.area for pc in pieces) / max(1e-9, n_sheets * sheet_out[0] * sheet_out[1])),
        "slices": [{
            "label": sl.label, "group": sl.group, "M": np.round(sl.M, 6).tolist(), "thickness": sl.thickness, "note": sl.note,
            "engages": sl.engages, "extents": [round(sl.bbox[2] - sl.bbox[0], 2), round(sl.bbox[3] - sl.bbox[1], 2)],
            "errors": sl.errors, "warnings": sl.warnings, "fixes": getattr(sl, "fixes", []),
            "pieces": [{"label": pc.label, "place": list(pc.place), "bbox": [round(b, 3) for b in pc.bbox],
                        "facets": [{"M": np.round(M, 6).tolist(), "rings": poly_coords(g)} for M, g in pc.facets],   # 3D view
                        "kerfed": poly_coords(pc.kerfed),        # local 2D, kerf applied (per-piece export)
                        "placed": poly_coords(pc.placed),        # sheet coordinates, kerf applied
                        "lines": [[s, line_coords(l)[0]] for s, l in pc.placed_lines],   # score lines on the sheet
                        "marks": [[round(x, 3), round(y, 3), t] for x, y, t in pc.placed_marks],
                        "label_pos": pc.label_pos, "leader": pc.leader, "same": pc.same, "flipped": pc.flipped,
                        } for pc in sl.pieces],
        } for sl in slices],
        "dropped": [{"label": s.label, "errors": s.errors} for s in dropped],
    }
    if out:
        out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(plan))
    return plan


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
