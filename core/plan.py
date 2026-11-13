"""Pipeline: mesh → modify form → mode.build → sections → cuts → checks → split → pack → plan.json.

    uv run python -m core.plan examples/egg.stl --mode interlocked --set nx=5 ny=4 thickness=3 --out working-files/egg
"""
from __future__ import annotations
import argparse, json, os, pathlib, shutil, threading, time
import numpy as np
import shapely
from shapely.geometry import MultiPolygon
from shapely.ops import unary_union
from . import progress as bar
from .progress import DETAIL, progress
from .modes import load_all, Ctx
from .geometry import section_polygons, as_multi, poly_coords, line_coords, mark_box, mark_rot, min_dims, orient_arrows, trim_thin
from .checks import STRUCTURAL, check_plan, suggest_fixes, crossing_suggestions
from .split import split_slice, fits_rotated, islands
from .nest import nest
from .mesh import load_mesh, reuse, simplify, square_up
from .identical import mark_identical
from .model import Piece, label_codes, label_tag

MODES = load_all()


def coerce_params(mode, raw: dict) -> dict:
    p = {prm.name: prm.coerce(raw.get(prm.name)) for prm in mode.all_params()}
    # older projects stored a boolean, or "remove" (auto-fix used to delete what nothing held): that is report-only now
    if p.get("autofix") not in ("add", "off"):
        p["autofix"] = "off" if str(p.get("autofix")).lower() in ("false", "0", "remove") else "add"
    if "cloth" in raw and "separate" not in raw:                    # older names
        p["separate"] = bool(raw["cloth"])
    if "label_inside" in raw and "label_place" not in raw:          # a project saved when labels were a tickbox: on the parts, or beside them
        p["label_place"] = "on" if str(raw["label_inside"]).lower() in ("true", "1") else "beside"
    if "simplify" in raw and "facet" not in raw and "facet" in p and raw["simplify"] in (0, "0"):
        p["facet"] = 0
    return p


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


def shed_slivers(raw, prof, cuts, mf, mp):
    """What is not a piece of the model, though the geometry has it: a shaving a slot cuts off its own part, thinner
    than min_feature everywhere — the slot's waste, which would snap off at the cutter — and a speck where the plane
    only grazes the surface, thinner than min_feature everywhere and shorter than min_part every way (the bunny's
    0.5 mm² toe edges). Those go; any region of the model past either size stays, held or flagged, never deleted.
    Returns the profile and how many went."""
    keep = []
    for r in prof.geoms:
        if r.buffer(-mf / 2).is_empty:
            if min_dims(r)[1] < mp:
                continue
            if any(r.distance(c) < 1e-6 for c in cuts):
                parent = max(raw.geoms, key=lambda q: q.intersection(r).area)
                if not parent.buffer(-mf / 2).is_empty and parent.area > 2 * r.area:
                    continue
        keep.append(r)
    return MultiPolygon(keep), len(prof.geoms) - len(keep)   # empty: the plane only grazes the model, there is no part


def _swap_in(mesh, dest, waits=(0, 0.05, 0.1, 0.2, 0.4, 0.8)):
    """Write `mesh` to `dest` without ever leaving a half-written file there; True when it got there. See build()."""
    tmp = dest.with_suffix(f".{threading.get_ident()}.stl")
    mesh.export(tmp)
    try:
        for wait in waits:
            time.sleep(wait)
            try:
                os.replace(tmp, dest)
                return True
            except PermissionError:
                try:
                    shutil.copyfile(tmp, dest)
                    return True
                except PermissionError:
                    continue
        return False
    finally:
        tmp.unlink(missing_ok=True)


def build(model_path, mode_name, raw_params, out=None, mesh_out=None):
    mode = MODES[mode_name]()                       # its own instance: a technique may keep this build's state on itself
    p = coerce_params(mode, raw_params)
    p["model_name"] = p["model_name"] or pathlib.Path(model_path).stem   # the server sets the uploaded name; the CLI has the path
    notes = []
    bar.start()
    mesh = load_mesh(model_path, p, notes, mode.surface)
    square = reuse(mesh, "square", lambda m: square_up(m, p["rotate"]))   # offered on the Model tab, beside rotate
    if mesh_out:                                    # processed model for the browser's ghost view (decimated)
        progress("preparing the preview model", 0.18)
        ghost = reuse(mesh, "preview", lambda m: simplify(m, 30000))
        # beside it, then swapped in: the page may still be downloading the last one, and rewritten in place it got a
        # file cut short (Linux CI: "network error" in the 3D view's loader). Windows refuses the swap while the file
        # is open (the page downloading it, a virus scanner reading it): then in place; refused that too (036: a
        # scanner holds it), tried again a moment later, and after 1.5 s the slice goes on with the last preview —
        # the preview is only what the view shows, never a reason for the slice to fail
        _swap_in(ghost, pathlib.Path(mesh_out))
        bar.show(str(mesh_out), 0.19)               # the 3D view can show the model now, before the slices
    sheet0 = list(p["sheet"])
    if p["one_sheet"]:                              # one strip as wide as the sheet, as long as it needs: nest against a huge height
        p["sheet"] = [sheet0[0], ONE_SHEET_H]
    # build → section → check; with autofix = add, floating regions get a crossing slice and we build again (2 rounds)
    for attempt in range(3):
        # A second pass repeats these stages, which used to send the bar back to 20 % with no word about why. Each
        # extra pass gets a band of its own near the end instead, so the bar only moves forward, and every stage of
        # it says which pass it is and how many there can be.
        bar.band(*((0.0, 1.0) if not attempt else (0.7 + 0.08 * (attempt - 1), 0.7 + 0.08 * attempt)))
        again = "" if not attempt else f"{DETAIL}pass {attempt + 1} of 3, holding the parts that float"
        progress("placing slices and slots" + again, 0.2)
        ctx = Ctx(mesh, p)
        slices = mode.build(ctx)
        kept, shaved, grazed, trimmed = _profiles(slices, mesh, p, again)
        mode.guide_outlines(ctx, kept)                # on the finished outlines: grown, slivers shed
        dropped = [s for s in slices if s not in kept and s.label not in grazed]
        slices = kept
        progress("checking the parts and the assembly" + again, 0.7)
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
    bar.band(0.0, 1.0)                              # the passes are over: the last stages own the rest of the bar
    if trimmed:
        notes.append(f"{trimmed} thin spot(s) trimmed off the parts (trim_thin): a tip or sliver too thin for too long, which would have broken off — the part ends blunt there, a little short of the model")
    if shaved:
        notes.append(f"{shaved} sliver(s) thinner than {p['min_feature']:g} mm everywhere left out: shavings a slot cuts off its own part, "
                     f"and specks under {p['min_part']:g} mm where a slice only grazes the surface — too small to cut or handle")
    suggest_fixes(slices, p, ctx, mode)
    n_err += len(ctx.errors) + len(dropped)

    # split + pack
    progress("nesting the parts on sheets", 0.85)
    for sl in slices:
        if p["split"] and sl.facets is None:
            split_slice(sl, p["sheet"], p["sheet_margin"], p["tab"], p["grain"])
        else:
            sl.pieces = islands(sl) if sl.facets is None else [Piece(sl.label, sl.profile, sl, sl.lines, sl.marks)]   # a folded net stays whole
    n_err += _oversize(slices, p, sheet0, mesh, ctx)
    pieces = [pc for sl in slices for pc in sl.pieces]
    if p["orient_mark"]:                               # the same two directions on every part: which way is up, which face is the front
        for pc in pieces:                               # placed after the dowel and seam marks, in the room they leave
            pc.lines = pc.lines + orient_arrows(pc.geom, keep=[mark_box(*m[:3], p["font"], mark_rot(m)) for m in pc.marks])
    kerf = p["kerf"] if p["compensate"] else 0.0       # off by default: many machines compensate their own kerf
    tag = label_tag(p, model_path)                     # the model's name, engraved before every label: nested with room for it
    n_sheets = nest(pieces, p["sheet"], p["gap"], p["sheet_margin"], kerf, p["labels"], p["font"], tag, p["label_place"], p["grain"])
    if crowded := [pc.label for pc in pieces if pc.crowded]:
        notes.append(f"no free spot beside {len(crowded)} part(s) for their labels ({', '.join(crowded[:6])}{'…' if len(crowded) > 6 else ''}): "
                     "they sit on the part, overrunning it where it is small — a smaller font, a bigger gap or sheet, or `label_model` off gives them room")
    mark_identical(pieces, p["mirror_ok"], grain=p["grain"])   # which parts are the same part: one cut file, one row, a quantity
    # puzzle mode: what gets engraved is a code with no order in it. The plan keeps the real labels — the app, the
    # checks and the 3D view are the "plans" you consult when you give up — and the export carries the key.
    codes = label_codes([pc.label for pc in pieces], f"{pathlib.Path(model_path).name}|{mode_name}") if p["label_style"] == "code" else {}
    sheet_thick = [p["thickness"]] * n_sheets           # the stock each sheet is cut from: nest keeps one per sheet
    for pc in pieces:
        sheet_thick[pc.place[0]] = pc.parent.thickness
    sheet_out = sheet0
    if p["one_sheet"]:                              # report the strip at the length the parts and their labels actually took
        top = max([pc.placed.bounds[3] for pc in pieces] + [pc.label_pos[1] + p["font"] * 0.7 for pc in pieces if pc.label_pos], default=0.0) + p["sheet_margin"]
        sheet_out = [sheet0[0], float(np.ceil(top))]; p["sheet"] = sheet0
    progress("measuring coverage", 0.94)
    cov = coverage(mesh, slices, ctx.cover_r or max(mesh.extents) / 8, lat=max(3.0, p["thickness"]))
    progress("done", 1.0)
    if ctx.notes_extra:
        notes.append(ctx.notes_extra)
    if cov < 0.9 and (slices or not ctx.errors):    # stopped before the first slice: the error says why, not this
        notes.append(f"model coverage {cov:.0%}: parts of the model have no geometry — more slices (count / spacing), a different axis, or round/thicken thin features")

    plan = {
        "model": str(pathlib.Path(model_path).resolve()), "mode": mode_name, "params": p, "notes": notes,
        "legend": mode.legend,                                               # what the labels mean (Export tab, assembly key)
        "bbox": [float(e) for e in mesh.extents],
        "axes": [a.tolist() for a in ctx.ax], "mid": ctx.mid.tolist(),      # slicing frame (for click-placed points in the UI)
        "curve3d": ctx.curve3d, "curve_pts": ctx.curve_pts,
        "axes3d": ctx.axes3d,                                                # radial's fan axes, curve's branches: drawn and dragged in 3D
        "bounds3d": ctx.bounds3d,                                            # the planes between lobes or at a branch's joint, moved and tilted like slices
        "spacing": ctx.spacing,                                              # what the drawn spacing curves gave: positions along each axis, for the graph
        "rods": ctx.rods,                                                    # dowel rods for the 3D view and the key: [[x0,y0,z0],[x1,y1,z1],d,section [[x,y]…] in the slice's x/y,slice x axis,name (Z-3a),from slice,to slice]
        "params_used": {k: p[k] for k in ("extra_x", "extra_y", "ring_count") if k in p},   # what autofix=add changed
        "sheets": n_sheets, "sheet": sheet_out, "sheet_thick": sheet_thick, "kerf": kerf,
        "counts": {"slices": len(slices), "parts": len(pieces), "errors": n_err, "warnings": n_warn, "faces": int(len(mesh.faces))},
        "codes": codes,                                                      # puzzle mode: engraved code → real label
        "label_tag": tag,                                                    # engraved before every label (the model's name)
        "errors": ctx.errors, "fixes": ctx.fixes,                            # mode-level errors and their one-click fixes
        "square": square and {"rotate": square[0], "off": round(square[1], 1)},   # a boxy model a few degrees off its axes
        "material_area_mm2": float(sum(pc.geom.area for pc in pieces)),
        "coverage": cov,
        "timing": bar.timing(),
        "core_d_min": ctx.core_d_min,
        "sheet_usage": float(sum(pc.geom.area for pc in pieces) / max(1e-9, n_sheets * sheet_out[0] * sheet_out[1])),
        "slices": [_slice_json(sl) for sl in slices],
        "dropped": [{"label": s.label, "errors": s.errors} for s in dropped],
    }
    if out:
        out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(plan))
    return plan


def _profiles(slices, mesh, p, again):
    """Each slice sectioned and its cuts taken out: the kept slices with `profile` set, how many slivers came off, and
    the labels of slices that only grazed the model (a speck, not a part, not an error). A slice the plane misses, or
    whose cuts leave nothing, says so and is dropped."""
    kept, shaved, grazed, trimmed = [], 0, set(), 0
    for i, sl in enumerate(slices):         # sections → profiles (modes may hand over a finished `raw` for synthetic parts)
        progress(f"sectioning{DETAIL}{i + 1} of {len(slices)}{again}", 0.35 + 0.35 * i / len(slices))
        sectioned = sl.group in STRUCTURAL       # a plane through the model, not a part the technique draws (peg, panel, strip)
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
        if sectioned and not prof.is_empty:
            prof, n = shed_slivers(sl.raw, prof, sl.cuts, p["min_feature"], p["min_part"])
            shaved += n
            if p.get("trim_thin") and not prof.is_empty:
                prof, n = trim_thin(prof, p["min_feature"])
                trimmed += n
            if prof.is_empty:                    # a speck and nothing else: not a part, not an error
                grazed.add(sl.label)
                continue
        if prof.is_empty:
            sl.errors.append("slots/holes remove all material — dropped")
            continue
        sl.profile = prof
        kept.append(sl)
    return kept, shaved, grazed, trimmed


def _oversize(slices, p, sheet0, mesh, ctx):
    """Every finished piece, however it was made, has to fit the sheet: a part that does not overhangs the drawing and
    takes a sheet to itself, so it is an error whether or not `split` was asked to cut it — with the size the model
    would have to be for its parts to fit, so "too big for my sheet" comes with the number. Returns the errors added."""
    over = [(sl, pc, *min_dims(pc.geom)) for sl in slices for pc in sl.pieces      # rotation is free on the sheet
            if not fits_rotated(pc.geom, p["sheet"], p["sheet_margin"], p["grain"])]
    if not over:
        return 0
    sw, sh = p["sheet"][0] - 2 * p["sheet_margin"], p["sheet"][1] - 2 * p["sheet_margin"]
    if p["grain"]:                                  # the part as it stands: its width on the sheet's, its height on the sheet's
        over = [(sl, pc, b[3] - b[1], b[2] - b[0]) for sl, pc, *_ in over for b in [pc.geom.bounds]]
        f = min(min(sw / w, sh / h) for _, _, h, w in over)
    else:
        long_s, short_s = sorted((sw, sh), reverse=True)
        f = min(min(long_s / large, short_s / small) for _, _, small, large in over)
    fit = [round(float(e) * f, 1) for e in mesh.extents]
    fit_txt = " × ".join(f"{v:g}" for v in fit)
    for sl, pc, small, large in over:
        e = (f"{pc.label} does not fit the sheet ({large:.0f}×{small:.0f} mm on {sheet0[0]:g}×{sheet0[1]:g} mm) — "
             + ("split cannot cut a folded panel: use a smaller facet size or a bigger sheet" if sl.facets is not None
                else "enable split or use a bigger sheet" if not p["split"]
                else "even split cannot cut it small enough: use a bigger sheet or a smaller model"))
        sl.errors.append(e)
        # suggest_fixes has already run (the pieces only exist here), so this error brings its own fixes
        sl.fixes.append({"error": e, "options": ([] if p["split"] else [{"title": "split oversize parts", "set": {"split": True}}])
                         + [{"title": f"scale the model to {f:.0%} ({fit_txt} mm)", "set": {"scale": round(p["scale"] * f, 4)}}]
                         + ([] if p["one_sheet"] else [{"title": "one long sheet (cut the strip apart at the machine)", "set": {"one_sheet": True}}])})
    ctx.errors.append(f"{len(over)} part(s) are bigger than the {sheet0[0]:g} × {sheet0[1]:g} mm sheet: "
                      f"set `size` to about {fit_txt} mm ({f:.0%} of this model)"
                      + (", or use a bigger sheet" if p["one_sheet"] else ", use a bigger sheet, or turn on `one_sheet`"))
    return len(over) + 1


def _slice_json(sl):
    """A slice and its pieces as the plan carries them: the page, the 3D view, the checks and the export read this."""
    return {
        "label": sl.label, "group": sl.group, "M": np.round(sl.M, 6).tolist(), "thickness": sl.thickness, "note": sl.note,
        "engages": sl.engages, "extents": [round(sl.bbox[2] - sl.bbox[0], 2), round(sl.bbox[3] - sl.bbox[1], 2)],
        "errors": sl.errors, "warnings": sl.warnings, "fixes": sl.fixes,
        "pieces": [{"label": pc.label, "place": list(pc.place), "bbox": [round(b, 3) for b in pc.bbox],
                    "facets": [{"M": np.round(M, 6).tolist(), "rings": poly_coords(g)} for M, g in pc.facets],   # 3D view
                    "kerfed": poly_coords(pc.kerfed),        # local 2D, kerf applied (per-piece export)
                    "placed": poly_coords(pc.placed),        # sheet coordinates, kerf applied
                    "lines": [[s, line_coords(l)[0]] for s, l in pc.placed_lines],   # fold and guide lines on the sheet
                    "kerfed_lines": [[s, line_coords(l)[0]] for s, l in pc.lines],   # the same in the part's own frame (per-piece export)
                    "marks": [[round(m[0], 3), round(m[1], 3), m[2], round(mark_rot(m), 2)] for m in pc.placed_marks],
                    "kerfed_marks": [[round(m[0], 3), round(m[1], 3), m[2], round(mark_rot(m), 2)] for m in pc.marks],
                    "label_pos": pc.label_pos, "label_size": pc.label_size, "label_short": pc.label_short, "leader": pc.leader, "same": pc.same, "flipped": pc.flipped,
                    "area": round(float(pc.geom.area), 3),   # net of holes and slots: × its slice's thickness × density = its weight
                    } for pc in sl.pieces],
    }


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
