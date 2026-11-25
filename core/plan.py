"""Pipeline: mesh → modify form → mode.build → sections → cuts → checks → split → pack → plan.json.

    uv run python -m core.plan examples/egg.stl --mode interlocked --set nx=5 ny=4 thickness=3 --out working-files/egg
"""
from __future__ import annotations
import argparse, io, json, os, pathlib, pickle, shutil, threading, time
import numpy as np
import shapely
from shapely.geometry import MultiPolygon
from shapely.ops import unary_union
from . import progress as bar
from .progress import DETAIL, progress
from .modes import load_all, Ctx
from .geometry import section_polygons, as_multi, poly_coords, line_coords, min_dims, trim_thin
from .labels import mark_box, mark_rot, mark_size, orient_arrows
from .checks import STRUCTURAL, check_plan, suggest_fixes, crossing_suggestions
from .split import split_slice, fits_rotated, islands, pieces_of
from .nest import nest
from .mesh import kept, load_mesh, reuse, simplify, square_up
from .unfold import points_at
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
PARTS_STAGES = ("placing slices and slots", "sectioning", "checking the parts and the assembly")   # what a kept result skips
_NO_PARTS = bar.parts      # the parts hook nobody listens to: build() makes no partial plan for it
_MISSING = object()        # a parameter the parts read that the job did not have


class Params(dict):
    """The job's parameters: a plain dict to every stage, which notes in `seen`, while it is a set, each key read or
    written. Those are what the parts (_slices) depend on: a later build of the same model with the same values for
    them can take the parts as they were (_take). Reading the dict whole — a copy, a loop, `{**p}` — may depend on
    any key: `whole` is set, and nothing is kept."""
    seen = None
    whole = False

    def __getitem__(self, k):
        if self.seen is not None:
            self.seen.add(k)
        return dict.__getitem__(self, k)

    def get(self, k, default=None):
        if self.seen is not None:
            self.seen.add(k)
        return dict.get(self, k, default)

    def __contains__(self, k):
        if self.seen is not None:
            self.seen.add(k)
        return dict.__contains__(self, k)

    def __setitem__(self, k, v):
        if self.seen is not None:
            self.seen.add(k)
        dict.__setitem__(self, k, v)


def _whole(name):
    f = getattr(dict, name)

    def whole(self, *a, **kw):
        if self.seen is not None:
            self.whole = True
        return f(self, *a, **kw)
    return whole


# __iter__ too: a dict subclass with its own __iter__ is copied through keys() and __getitem__, never past them
for _name in ("__iter__", "__len__", "__repr__", "__eq__", "__ne__", "__or__", "__ror__", "__ior__", "__reversed__", "__delitem__",
              "keys", "values", "items", "copy", "update", "setdefault", "pop", "popitem", "clear"):
    setattr(Params, _name, _whole(_name))


def _same(a, b):
    """The same value of the same type all the way down, in the same order: 1 and 1.0, (1, 2) and [1, 2], 0.0 and -0.0
    are not, nor a value of any type not listed here. A setting not surely the same is never taken for it."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return _same(list(a), list(b)) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(map(_same, a, b))
    if type(a) is float:
        return repr(a) == repr(b)
    return a is b or (type(a) in (str, int, bool) and a == b)


def _noting(p):
    """Start noting what the parts read of `p`; the values as they are now, for _keep. None: nothing can be kept."""
    try:
        before = pickle.dumps(dict(p), pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 — a parameter that does not pickle only means this build keeps nothing
        return None
    p.seen, p.whole = set(), False
    return before


def _keep(before, mode_name, mesh, p, made):
    """The parts' result `made`, taken right after they are made and before the sheets change them, as it is kept:
    (technique, {parameter read: its value then}, the result pickled). The model and the parameters are pickled by
    name: the model is large and the one a later build of it has too, the parameters are that build's own. None — the
    next build makes the parts again — when the parts read the parameters whole, or what a technique keeps does not
    pickle."""
    seen, p.seen = p.seen, None
    if p.whole:
        return None
    try:
        old = pickle.loads(before)       # noqa: S301 — bytes this build pickled, never anything from outside
        f = io.BytesIO()
        pk = pickle.Pickler(f, pickle.HIGHEST_PROTOCOL)
        refs = {id(mesh): "mesh", id(p): "p"}
        pk.persistent_id = lambda obj: refs.get(id(obj))
        pk.dump((*made, {k: dict.__getitem__(p, k) for k in p if k in seen}))   # and what the parts wrote into p
        return mode_name, {k: old.get(k, _MISSING) for k in seen}, f.getvalue()
    except Exception:  # noqa: BLE001 — the cache never fails a slice
        return None


def _take(hit, mode_name, mesh, p):
    """The parts an earlier build of this prepared model kept (_keep), unpickled afresh for this build onto its own
    model and parameters, with the values the parts wrote into the parameters put back — or None when the technique
    differs, a parameter they read has another value now, or the result does not load."""
    if not hit or hit[0] != mode_name or not all(_same(dict.get(p, k, _MISSING), v) for k, v in hit[1].items()):
        return None
    try:
        up = pickle.Unpickler(io.BytesIO(hit[2]))   # noqa: S301 — bytes an earlier build in this process pickled
        up.persistent_load = {"mesh": mesh, "p": p}.__getitem__
        *got, wrote = up.load()
    except Exception:  # noqa: BLE001 — a result that does not load is made again, never a failed slice
        return None
    dict.update(p, wrote)
    return got


def coverage(mesh, slices, r, lat=3.0, skip=None):
    """Fraction of the model's surface represented by the parts: sample points on the surface and count those that
    have a part within `r` across its plane (about half a slice spacing) and within `lat` sideways. A leg or an ear
    no slice reaches lowers it.

    The two tolerances are deliberately different: with lateral slack as large as the across-plane one, a leg
    projects onto the body's cross-section and reads as represented (a 3x2 slicing of a cow scored 100 %).
    Surface samples, not volume samples: point-in-mesh tests ray-cast every sample against every triangle and need
    gigabytes on a 40k-face model, while surface points answer the same question for one barycentric mix each.
    Dense slicings (interlocked, radial) put a slice near every point and legitimately score close to 100 %; the
    number carries the most signal for stacked and folded work.
    `skip`: triangles (n × 3 × 3) where the parts are not meant to be, the faces the user removed from a folded model;
    the points there are not counted.
    """
    pts, face = mesh.sample(3000, seed=0, return_index=True)   # seeded: the same model and params must give the same plan
    if skip is not None:
        pts = pts[~points_at(pts, mesh.face_normals[face], skip)]
    if len(pts) == 0:
        return 1.0
    covered = np.zeros(len(pts), bool)
    P = np.c_[pts, np.ones(len(pts))]
    for sl in slices:
        if sl.profile is None or sl.group in ("P", "J", "W"):     # spacers, pegs and a plaque's back plate are not sections of the model
            continue
        panes = getattr(sl, "papers", None) or []                 # folded: a window closed by a pane covers the model there
        for i, (M, geom) in enumerate(sl.facets or [(sl.M, sl.profile)]):
            if i < len(panes) and panes[i]:
                geom = geom.union(panes[i][0])
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


def swap_in(write, dest, waits=(0, 0.05, 0.1, 0.2, 0.4, 0.8)):
    """A file put at `dest` without ever leaving a half-written one there: `write(path)` writes it beside `dest`, then
    it is swapped in. True when it got there. Windows refuses the swap, and the in-place copy after it, while
    something still has the old file open (the page fetching it, a virus scanner): PermissionError for the preview
    (036), and for a job's plan.json "OSError [Errno 22] Invalid argument" (042), so every OSError is tried again."""
    tmp = dest.with_suffix(f".{threading.get_ident()}{dest.suffix}")
    write(tmp)
    try:
        for wait in waits:
            time.sleep(wait)
            try:
                os.replace(tmp, dest)
                return True
            except OSError:
                try:
                    shutil.copyfile(tmp, dest)
                    return True
                except OSError:
                    continue
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _closer_than(pieces, d):
    """Pairs of parts on one sheet less than `d` apart as laid, (distance, label, label), closest first."""
    if len(pieces) < 2:                                # no pair; an empty query is not a geometry array (bugs/076)
        return []
    geoms = [pc.placed for pc in pieces]
    a, b =shapely.STRtree(geoms).query(geoms, predicate="dwithin", distance=d - 1e-6)
    return sorted((geoms[i].distance(geoms[j]), pieces[i].label, pieces[j].label)
                  for i, j in zip(a, b) if i < j and pieces[i].place[0] == pieces[j].place[0])


def build(model_path, mode_name, raw_params, out=None, mesh_out=None):
    mode = MODES[mode_name]()                       # its own instance: a technique may keep this build's state on itself
    p = Params(coerce_params(mode, raw_params))
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
        swap_in(ghost.export, pathlib.Path(mesh_out))
        bar.show(str(mesh_out), 0.19)               # the 3D view can show the model now, before the slices
    sheet0 = list(p["sheet"])
    if p["one_sheet"]:                              # one strip as wide as the sheet, as long as it needs: nest against a huge height
        p["sheet"] = [sheet0[0], ONE_SHEET_H]
    # The parts are kept with the prepared model: a build that changes none of the settings they read (a sheet size, a
    # gap, a font for most techniques) takes them as they were and goes straight on to the sheets. Kept only once the
    # build is through: one stopped or failed keeps nothing.
    store = None if os.environ.get("LAMINA_NO_REUSE") == "1" else kept(mesh)
    made = None
    if got := store is not None and _take(store.get("slices"), mode_name, mesh, p):
        slices, dropped, ctx, mode, notes = got
    else:
        before = store is not None and _noting(p)
        slices, dropped, ctx = _slices(mesh, mode, p, notes)
        made = before and _keep(before, mode_name, mesh, p, (slices, dropped, ctx, mode, notes))

    # split + pack
    progress("nesting the parts on sheets", 0.85)
    for sl in slices:
        if sl.facets is None and (geoms := mode.cut(ctx, sl)):      # the technique cuts it itself (a locked band)
            sl.pieces = pieces_of(sl, geoms)
            continue
        if p["split"] and sl.facets is None:
            split_slice(sl, p["sheet"], p["sheet_margin"], p["tab"], p["grain"])
        else:
            sl.pieces = islands(sl) if sl.facets is None else [Piece(sl.label, sl.profile, sl, sl.lines, sl.marks)]   # a folded net stays whole
    _oversize(slices, p, sheet0, mesh, ctx)
    pieces = [pc for sl in slices for pc in sl.pieces]
    if bar.parts is not _NO_PARTS:                 # only for a caller that listens: the CLI and the tests make no second plan
        bar.parts({**_head(model_path, mode_name, dict(p, sheet=sheet0), notes, mode, mesh, ctx),
                   "counts": _counts(slices, pieces, ctx, dropped, mesh), "label_tag": label_tag(p, model_path),
                   "warnings": ctx.warnings, "errors": ctx.errors, "fixes": ctx.fixes, "square": _square(square),
                   "slices": [_slice_json(sl, placed=False) for sl in slices], "partial": True})
    if p["orient_mark"]:                               # the same two directions on every part: which way is up, which face is the front
        for pc in pieces:                               # placed after the dowel and seam marks, in the room they leave
            room = pc.geom if pc.parent.cover is None else pc.geom.intersection(pc.parent.cover)   # a stacked layer: under the one above
            pc.lines = pc.lines + orient_arrows(room, keep=[mark_box(*m[:3], mark_size(m, p["font"]), mark_rot(m)) for m in pc.marks])
    kerf = p["kerf"] if p["compensate"] else 0.0       # off by default: many machines compensate their own kerf
    tag = label_tag(p, model_path)                     # the model's name, engraved before every label: nested with room for it
    n_sheets = nest(pieces, p["sheet"], p["gap"], p["sheet_margin"], kerf, p["labels"], p["font"], tag, p["label_place"], p["grain"], p["printed"])
    _past_the_edge(slices, p)
    if p["tool_d"] > 0 and (close := _closer_than(pieces, p["tool_d"])):   # a bit cuts its own width round each part
        d, a, b = close[0]
        ctx.warnings.append(f"{len(close)} pair(s) of parts lie closer on the sheet than the {p['tool_d']:g} mm bit (closest: {a} "
                            f"and {b}, {d:.2f} mm): the bit that cuts round one cuts into the other. Set the gap between parts "
                            f"to {2 * p['tool_d']:g} mm, twice the bit, as the router machines do")
    # counted once the parts are cut and laid: splitting a slice, cutting a ring into pieces, a piece too big for the
    # sheet and parts too close for the bit add their own, which the count taken at the check left out (bug 052)
    counts = _counts(slices, pieces, ctx, dropped, mesh)
    if crowded := [pc.label for pc in pieces if pc.crowded]:
        notes.append(f"no free spot beside {len(crowded)} part(s) for their labels ({', '.join(crowded[:6])}{'…' if len(crowded) > 6 else ''}): "
                     "they sit on the part, overrunning it where it is small — a smaller font, a bigger gap or sheet, or `label_model` off gives them room")
    mark_identical(pieces, p["mirror_ok"], grain=p["grain"])   # which parts are the same part: one cut file, one row, a quantity
    # puzzle mode: what gets engraved is a code with no order in it. The plan keeps the real labels — the app, the
    # checks and the 3D view are the "plans" you consult when you give up — and the export carries the key.
    codes = label_codes([pc.label for pc in pieces], f"{pathlib.Path(model_path).name}|{mode_name}") if p["label_style"] == "code" else {}
    sheet_thick = [p["thickness"]] * n_sheets           # the stock each sheet is cut from: nest keeps one per sheet
    sheet_stock = [""] * n_sheets                       # … and what that stock is, when it is not the job's material ("paper")
    tallest = {}                                        # a print plate holds every thickness: its tallest part
    for pc in pieces:
        tallest[pc.place[0]] = max(tallest.get(pc.place[0], 0.0), pc.parent.thickness); sheet_stock[pc.place[0]] = pc.parent.stock
    for s, t in tallest.items():
        sheet_thick[s] = t
    sheet_out = sheet0
    if p["one_sheet"]:                              # report the strip at the length the parts and their labels actually took
        top = max([pc.placed.bounds[3] for pc in pieces] + [pc.label_pos[1] + p["font"] * 0.7 for pc in pieces if pc.label_pos], default=0.0) + p["sheet_margin"]
        sheet_out = [sheet0[0], float(np.ceil(top))]; p["sheet"] = sheet0
    progress("measuring coverage", 0.94)
    cov = coverage(mesh if ctx.view["clip"] is None else mesh.slice_plane(*ctx.view["clip"]), slices, ctx.cover_r or max(mesh.extents) / 8, lat=max(3.0, p["thickness"]), skip=ctx.cover_skip)
    progress("done", 1.0)
    if ctx.notes_extra:
        notes.append(ctx.notes_extra)
    if cov < 0.9 and (slices or not ctx.errors):    # stopped before the first slice: the error says why, not this
        notes.append(f"model coverage {cov:.0%}: parts of the model have no geometry — more slices (count / spacing), a different axis, or round/thicken thin features")

    plan = {
        **_head(model_path, mode_name, dict(p), notes, mode, mesh, ctx),
        "sheets": n_sheets, "sheet": sheet_out, "sheet_thick": sheet_thick, "sheet_stock": sheet_stock, "kerf": kerf,
        "counts": counts,
        "codes": codes,                                                      # puzzle mode: engraved code → real label
        "label_tag": tag,                                                    # engraved before every label (the model's name)
        "warnings": ctx.warnings,                                            # what the technique left out that was asked for
        "errors": ctx.errors, "fixes": ctx.fixes,                            # mode-level errors and their one-click fixes
        "square": _square(square),                                           # a boxy model a few degrees off its axes
        "material_area_mm2": float(sum(pc.geom.area for pc in pieces)),
        "coverage": cov,
        "timing": bar.timing(),
        "reused": list(PARTS_STAGES) if got else [],                         # the stages taken from the last build, not done again
        "sheet_usage": float(sum(pc.geom.area for pc in pieces) / max(1e-9, n_sheets * sheet_out[0] * sheet_out[1])),
        "slices": [_slice_json(sl) for sl in slices],
        "dropped": [{"label": s.label, "errors": s.errors} for s in dropped],
    }
    if out:
        out = pathlib.Path(out); out.parent.mkdir(parents=True, exist_ok=True)
        # beside, then swapped in, as the preview is: written in place, the page still reading the last plan.json made
        # the write fail and the slice with it (042). Unlike the preview the plan is the result, so a file Windows
        # never lets go of is an error that says so, not a slice that quietly shows the plan before it.
        text = json.dumps(plan)
        if not swap_in(lambda tmp: tmp.write_text(text), out.with_suffix(".json")):
            raise OSError(f"the plan could not be written to {out.with_suffix('.json')}: another program keeps that file open")
    if made:
        store["slices"] = made                      # one result per prepared model, the newest: replaced whole, never half
    return plan


def _head(model_path, mode_name, p, notes, mode, mesh, ctx):
    """What the plan says first, and the parts hook too: the job, and what the technique hands the 3D view."""
    return {
        "model": str(pathlib.Path(model_path).resolve()), "mode": mode_name, "params": p, "notes": notes,
        "legend": mode.legend,                                               # what the labels mean (Export tab, assembly key)
        "fit_test": mode.fit_test(p),                                        # a joint the slot offset sizes: the Export tab's step 1
        "bbox": [float(e) for e in mesh.extents],
        "axes": [a.tolist() for a in ctx.ax], "mid": ctx.mid.tolist(),      # slicing frame (for click-placed points in the UI)
        **ctx.view,                                                          # what the technique hands the 3D view: rods, curve, axes, bounds, spacing, clip, …
        "params_used": {k: p[k] for k in ("extra_x", "extra_y", "ring_count") if k in p},   # what autofix=add changed
    }


def _counts(slices, pieces, ctx, dropped, mesh):
    return {"slices": len(slices), "parts": len(pieces), "errors": sum(len(s.errors) for s in slices) + len(ctx.errors) + len(dropped),
            "warnings": sum(len(s.warnings) for s in slices) + len(ctx.warnings), "faces": int(len(mesh.faces))}


def _square(square):
    return square and {"rotate": square[0], "off": round(square[1], 1)}


def _slices(mesh, mode, p, notes):
    """The parts: placed, sectioned, checked, and held where they float — everything that comes before the sheets.
    Returns the kept slices, those dropped, and the Ctx the technique filled."""
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
    return slices, dropped, ctx


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
    would have to be for its parts to fit, so "too big for my sheet" comes with the number."""
    over = [(sl, pc, *min_dims(pc.geom)) for sl in slices for pc in sl.pieces      # rotation is free on the sheet
            if not fits_rotated(pc.geom, p["sheet"], p["sheet_margin"], p["grain"])]
    if not over:
        return
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


def _past_the_edge(slices, p):
    """Every part that fits the sheet is on it once nested: one laid past the sheet's edge is an error, never a silent
    overhang in the cut file (bug 073: a card panel laid at an angle where it did not fit, 0 errors). A part too big for
    any sheet has its error already (_oversize). Runs before the errors are counted. Returns how many it added."""
    W, H = p["sheet"]; added = 0
    for sl in slices:
        for pc in sl.pieces:
            x0, y0, x1, y1 = pc.placed.bounds
            past = x0 < -0.01 or y0 < -0.01 or x1 > W + 0.01 or (y1 > H + 0.01 and not p["one_sheet"])   # one long sheet grows to fit
            if past and fits_rotated(pc.geom, p["sheet"], p["sheet_margin"], p["grain"]):
                sl.errors.append(f"{pc.label} is laid past the edge of sheet {pc.place[0] + 1} (to {max(x1, W):.0f} × {max(y1, H):.0f} mm on "
                                 f"{W:g} × {H:g}), though it fits the sheet turned: the cut file would run off the sheet. Please report it; "
                                 "a slightly bigger sheet or another face size lays it out again")
                added += 1
    return added


def _slice_json(sl, placed=True):
    """A slice and its pieces as the plan carries them: the page, the 3D view, the checks and the export read this.
    `placed` False: the pieces as the parts hook has them, before nesting — no place, nothing on a sheet, no label, and
    no piece_extra (folded's says where its edges lie on the sheet)."""
    return {
        "label": sl.label, "group": sl.group, "M": np.round(sl.M, 6).tolist(), "thickness": sl.thickness, "note": sl.note,
        "engages": sl.engages, "extents": [round(sl.bbox[2] - sl.bbox[0], 2), round(sl.bbox[3] - sl.bbox[1], 2)],
        "errors": sl.errors, "warnings": sl.warnings, "fixes": sl.fixes, **({"stock": sl.stock} if sl.stock else {}),
        "pieces": [{"label": pc.label, "place": list(pc.place) if placed else None, "bbox": [round(b, 3) for b in pc.bbox],
                    "facets": [{"M": np.round(M, 6).tolist(), "rings": poly_coords(g), **sl.facet_extra(i)}   # 3D view; a technique adds what its facets need (folded: hinge, bevel, t)
                               for i, (M, g) in enumerate(pc.facets)],
                    **({
                        "kerfed": poly_coords(pc.kerfed),        # local 2D, kerf applied (per-piece export)
                        "placed": poly_coords(pc.placed),        # sheet coordinates, kerf applied
                        "lines": [[s, line_coords(l)[0]] for s, l in pc.placed_lines],   # fold and guide lines on the sheet
                        "kerfed_lines": [[s, line_coords(l)[0]] for s, l in pc.lines],   # the same in the part's own frame (per-piece export)
                        "marks": [[round(m[0], 3), round(m[1], 3), m[2], round(mark_rot(m), 2), *m[4:]] for m in pc.placed_marks],   # a fifth value: its own size
                        "kerfed_marks": [[round(m[0], 3), round(m[1], 3), m[2], round(mark_rot(m), 2), *m[4:]] for m in pc.marks],
                        "label_pos": pc.label_pos, "label_size": pc.label_size, "label_short": pc.label_short, "leader": pc.leader, "same": pc.same, "flipped": pc.flipped,
                    } if placed else {}),
                    **({} if sl.cover is None else {"cover": poly_coords(as_multi(sl.cover.intersection(pc.geom)))}),   # local: where a printed label may go
                    **(sl.piece_extra(pc) if placed else {}),
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
    for w in plan["warnings"]: print(f"  warn  {w}")
    for e in plan["errors"]: print(f"  ERROR {e}")
    for sl in plan["slices"] + plan["dropped"]:
        for e in sl.get("errors", []): print(f"  ERROR {sl['label']}: {e}")
        for w in sl.get("warnings", []): print(f"  warn  {sl['label']}: {w}")


if __name__ == "__main__":
    main()
