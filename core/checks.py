"""Physical-world checks on the finished 2D geometry. Errors = will not work; warnings = look at it.
Every message says what is wrong AND what to do about it; `suggest_fixes` turns the common ones into one-click options."""
from __future__ import annotations
import numpy as np
from shapely.geometry import MultiPolygon, Point
from shapely import affinity

HELD_GROUPS = ("X", "Y", "R", "C")     # regions in these groups must be held by a slot / dowel / the core
STRUCTURAL = ("X", "Y", "R", "C", "S")  # take part in the assembly-connectivity check (panels, pegs, strips, ribs do not)


def min_dims(poly):
    """Side lengths of the minimum rotated bounding rectangle (w, h), sorted."""
    r = poly.minimum_rotated_rectangle
    if r.geom_type != "Polygon":
        return 0.0, 0.0
    c = list(r.exterior.coords)
    a = ((c[0][0] - c[1][0]) ** 2 + (c[0][1] - c[1][1]) ** 2) ** 0.5
    b = ((c[1][0] - c[2][0]) ** 2 + (c[1][1] - c[2][1]) ** 2) ** 0.5
    return tuple(sorted((a, b)))


def check_slice(sl, p):
    mf, mp = p["min_feature"], p["min_part"]
    if sl.profile is None or sl.profile.is_empty:
        sl.errors.append("empty — plane does not hit material"); return
    raw_n = len(sl.raw.geoms)
    regions = list(sl.profile.geoms)
    if len(regions) > raw_n:
        what = "holes" if sl.group in ("F", "J", "P") else "slots"
        sl.errors.append(f"{what} cut the part into {len(regions)} loose regions (was {raw_n}) — move this slice a little (offset), "
                         f"lower the notch ratio, use fewer crossing slices, or make the connection holes smaller")
    for i, reg in enumerate(regions):
        tag = f"region {i + 1}" if len(regions) > 1 else "part"
        small, large = min_dims(reg)
        glued_island = sl.group == "S" and len(regions) > 1        # stacked islands (ears, horns) are kept: glue them carefully
        if large < mp:
            (sl.warnings if glued_island else sl.errors).append(f"{tag} too small ({small:.1f}×{large:.1f} mm < {mp} mm) — {'a tiny glued island: fiddly to handle, round / thicken the model to merge it' if glued_island else 'too small to cut and handle: delete it, enlarge the model, or lower min_part'}")
        elif small < mf:
            (sl.warnings if glued_island else sl.errors).append(f"{tag} too thin ({small:.1f} mm < {mf} mm) — it would break: thicken / round the model, use thicker material, or delete it")
        # thin necks: erode by half the min feature; anything that vanishes or fragments is fragile
        eroded = reg.buffer(-mf / 2)
        if eroded.is_empty:
            (sl.warnings if glued_island else sl.errors).append(f"{tag} thinner than {mf} mm everywhere — it would break: thicken / round the model or lower min_feature")
        elif eroded.geom_type == "MultiPolygon" and len(eroded.geoms) > 1:
            sl.warnings.append(f"{tag} has a bridge thinner than {mf} mm (splits into {len(eroded.geoms)} pieces when eroded) — fragile: thicken / round the model, "
                               f"move the slice (offset), or accept and handle with care")
        # engagement: a region must be held by something (a slot, a dowel, the core) unless it is the only region of a stacked slice
        if sl.group in HELD_GROUPS or (sl.group == "S" and len(regions) > 1):
            held = any(reg.intersects(c) for c in sl.cuts)
            if not held and sl.group != "S":
                sl.errors.append(f"{tag} floats — no slot or dowel holds it: add a crossing slice through it, move this slice, or delete it")
            elif not held and p.get("space", 0) > 0:     # stacked with a gap: nothing touches, so an island without a connector hangs in the air
                sl.errors.append(f"{tag} floats — nothing holds it across the gap: add a connection point inside it (alt-click), use a smaller dowel, or set the gap to 0 and glue it")
            elif not held:
                sl.warnings.append(f"{tag} is a separate island — glued to its neighbours only (no dowel / peg through it); add a connection point inside it if it must be rigid")
    if sl.group in ("X", "Y") and not sl.engages:
        sl.errors.append("no crossing slice — this slice touches nothing: add a slice of the other family through it, move it toward the centre, or delete it")
    # hole wall check: a closed cut (hole, slot, dowel) must leave at least min_feature of material to the outline
    if sl.cuts:
        inner = sl.raw.buffer(-mf)
        for c in sl.cuts:
            if sl.raw.contains(c) and not inner.contains(c):
                sl.warnings.append(f"a hole sits closer than {mf} mm to the outline (thin wall may tear) — move the connection point inward, use a smaller dowel, or accept")
                break
    # Slicer's "multiple / overlapping notches on one part": two cuts crossing each other inside the material
    inside = [c for c in sl.cuts if sl.raw.intersects(c)]
    if len(inside) > 1:
        from shapely.strtree import STRtree
        tree = STRtree(inside)
        for i, a in enumerate(inside):
            if any(j > i and a.intersection(inside[j]).intersection(sl.raw).area > 0.25 for j in tree.query(a)):
                sl.warnings.append("two slots / holes overlap each other (the connection is weakened) — fewer connection points, move the slice (offset), change the angle, or delete one slice")
                break


def check_insertion(slices, p):
    """Slide every slotted part into place and look for what blocks it. A part crossing another can only travel
    along their crossing line, in through the slot's mouth; so in the slotted part's plane, sweep the crossing
    part's remaining material along that line out through the mouth — whatever material of the slotted part lies
    in the path (the second wall of a hollow section the line crosses twice, a concave outline that closes over the
    mouth) makes the assembly physically impossible, however good the slots look on paper."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union
    from .geometry import plane_plane_line, to_local, to_world, rect_along
    by = {s.label: s for s in slices}
    for a in slices:
        if a.profile is None or a.profile.is_empty:
            continue
        for lb, o in a.slot_dirs.items():
            b = by.get(lb)
            if b is None or b.profile is None or b.profile.is_empty:
                continue
            ln = plane_plane_line(a.M, b.M)
            if ln is None:
                continue
            p0, d = ln; o = np.asarray(o)
            x0, y0, x1, y1 = a.profile.bounds; big = 4 * max(x1 - x0, y1 - y0, 1.0)
            hit = LineString(to_local(b.M, [p0 - d * big, p0 + d * big])).intersection(b.profile)
            strips = []
            for g in getattr(hit, "geoms", [hit]):
                if g.geom_type != "LineString" or g.length < 0.3:
                    continue
                c = np.asarray(g.coords); w = to_world(b.M, [c[0], c[-1]])
                w = w[np.argsort(w @ o)]                       # far end first: the sweep runs from it, through the near end, out
                far, out = to_local(a.M, [w[0], w[1] + o * big])
                strips.append(rect_along(far, out, b.thickness))
            if not strips:
                continue
            blocked = a.profile.intersection(unary_union(strips))
            if blocked.area > 6 * b.thickness:            # a few thicknesses of path: a sliver at the mouth is sanded, a wall is not
                a.errors.append(f"{b.label} cannot slide into its slot: {a.label}'s material is in its path ({blocked.area / b.thickness:.0f} mm of it) — "
                                f"the crossing line meets {a.label} twice (a hollow or concave section): move {b.label} (offset), lower the notch ratio, or delete {b.label}")


def check_plan(slices, p, mesh=None, span=None):
    for sl in slices:
        sl.errors, sl.warnings = [], []
        check_slice(sl, p)
    check_insertion(slices, p)
    check_assembly(slices, p)
    if mesh is not None:
        check_collisions(slices, mesh, span or 4 * max(mesh.extents))
    errs = sum(len(s.errors) for s in slices); warns = sum(len(s.warnings) for s in slices)
    return errs, warns


def check_collisions(slices, mesh, span):
    """Two slices of the same family that cross inside the model (tilt / offset edits) have no slot for each other:
    they would physically collide. Crossing families are joined by slots and are fine."""
    from .geometry import plane_plane_line, line_segments_in_mesh, to_local
    groups = {}
    for s in slices:
        if s.group in ("X", "Y", "S", "R", "C") and s.profile is not None:
            groups.setdefault(s.group, []).append(s)
    for members in groups.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                ln = plane_plane_line(a.M, b.M)
                if ln is None:
                    continue
                p0, d = ln
                for s_in, s_out in line_segments_in_mesh(mesh, p0, d, span):
                    m = p0 + d * (s_in + s_out) / 2
                    la, lb = to_local(a.M, [m])[0], to_local(b.M, [m])[0]
                    if a.profile.contains(Point(la)) and b.profile.contains(Point(lb)):
                        msg = f"crosses {b.label} inside the model and nothing joins them (they collide) — reduce the tilt / offset, move one, or delete one"
                        a.errors.append(msg); b.errors.append(f"crosses {a.label} inside the model and nothing joins them (they collide) — reduce the tilt / offset, move one, or delete one")
                        break


# ---------------------------------------------------------------- assembly connectivity
def _regions_local(sl):
    return list(sl.profile.geoms)


def _into(a, b, geom):
    """Geometry in b's local plane → a's local plane (both z=0; exact for parallel frames, close enough for small tilts)."""
    T = np.linalg.inv(a.M) @ b.M
    return affinity.affine_transform(geom, [T[0, 0], T[0, 1], T[1, 0], T[1, 1], T[0, 3], T[1, 3]])


def check_assembly(slices, p):
    """Every structural region must reach the main assembly through slots, connectors or glued contact.
    Nodes = (slice, region); edges = a slot / connector shared by two regions (matched by its world point), or two
    glued stacked regions that overlap. Disconnected groups get an error with fixes (add slices / delete)."""
    struct = [s for s in slices if s.group in STRUCTURAL and s.profile is not None and not s.profile.is_empty]
    if len(struct) < 2:
        return
    idx = {s.label: i for i, s in enumerate(struct)}
    nodes = [(i, r) for i, s in enumerate(struct) for r in range(len(s.profile.geoms))]
    parent = {n: n for n in nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]; n = parent[n]
        return n

    def union(a, b):
        parent[find(a)] = find(b)
    # slots and connectors: link a's regions touching cut A with b's regions touching cut B when A and B are the same connection
    for i, a in enumerate(struct):
        for lb, cut_a, pt in a.links:
            if lb not in idx:
                continue
            j = idx[lb]; b = struct[j]
            match = [(cb, pb) for (la, cb, pb) in b.links if la == a.label and np.linalg.norm(np.subtract(pb, pt)) < 1.0]
            ra = [r for r, reg in enumerate(_regions_local(a)) if reg.intersects(cut_a)]
            for cb, _ in match or []:
                rb = [r for r, reg in enumerate(_regions_local(b)) if reg.intersects(cb)]
                for x in ra:
                    for y in rb:
                        union((i, x), (j, y))
    # glued contact between consecutive stacked slices (same group S, neighbouring in the stack order) — only when
    # they touch: with a gap, the connectors are the only thing joining them
    stack = [s for s in struct if s.group == "S"] if p.get("space", 0) == 0 else []
    for a, b in zip(stack, stack[1:]):
        i, j = idx[a.label], idx[b.label]
        rb_local = [_into(a, b, reg) for reg in _regions_local(b)]
        for x, ra in enumerate(_regions_local(a)):
            for y, rb in enumerate(rb_local):
                if ra.intersection(rb).area > p["min_feature"] ** 2:
                    union((i, x), (j, y))
    comps = {}
    for n in nodes:
        comps.setdefault(find(n), []).append(n)
    if len(comps) < 2:
        return
    main = max(comps.values(), key=lambda c: sum(struct[i].profile.geoms[r].area for i, r in c))
    for comp in comps.values():
        if comp is main:
            continue
        labels = sorted({struct[i].label for i, _ in comp})
        for i, r in comp:
            s = struct[i]; tag = f"region {r + 1} " if len(s.profile.geoms) > 1 else ""
            s.errors.append(f"{tag}is not connected to the main assembly (separate group: {', '.join(labels)}) — nothing joins it to the rest: "
                            f"add crossing slices / connection points through it, or delete it")


def autofix(slices, p):
    """Remove what cannot work: slices nothing crosses, regions nothing holds, held-family parts below the minimum size.
    A whole layer of a stack is never removed — take it out and the model has a gap through it — but one island of
    that layer is: the tip of an ear that touches nothing would fall off the finished piece anyway.
    Returns notes describing what was removed; check_plan must run again afterwards."""
    notes, keep = [], []
    for sl in slices:
        regions = list(sl.profile.geoms)
        drop = set()
        for e in sl.errors:
            if "no crossing slice" in e or "not connected to the main assembly" in e:
                if e.startswith("region"):
                    drop |= {int(e.split()[1]) - 1}
                elif sl.group != "S":
                    drop = set(range(len(regions)))
            if e.startswith("part too small") or e.startswith("part too thin") or e.startswith("part thinner"):
                drop = set(range(len(regions)))
            for i in range(len(regions)):
                if e.startswith(f"region {i + 1} ") and ("floats" in e or "too small" in e or "too thin" in e or "thinner" in e):
                    drop.add(i)
        if not drop:
            keep.append(sl); continue
        left = [r for i, r in enumerate(regions) if i not in drop]
        why = "nothing holds it" if any("float" in e or "no crossing" in e or "not connected" in e for e in sl.errors) else "below the minimum size"
        if left:
            sl.profile = MultiPolygon(left); sl.raw = MultiPolygon([r for r in sl.raw.geoms if any(r.intersects(x) for x in left)]) or sl.raw
            notes.append(f"auto-fix: removed {len(drop)} region(s) of {sl.label} ({why})")
            keep.append(sl)
        else:
            notes.append(f"auto-fix: removed slice {sl.label} ({why})")
    return keep, notes


def crossing_suggestions(slices, ctx, mode):
    """Parameter changes that would add a crossing slice through every floating / disconnected region (autofix = add)."""
    from .geometry import to_world
    sets = []
    for sl in slices:
        for e in sl.errors:
            if not ("floats" in e or "no crossing" in e or "not connected" in e):
                continue
            regs = list(sl.profile.geoms)
            r = int(e.split()[1]) - 1 if e.startswith("region") else 0
            if r < len(regs):
                c = regs[r].centroid
                fx = mode.crossing_fix(ctx, sl, to_world(sl.M, [(c.x, c.y)])[0])
                if fx:
                    sets.append(fx["set"])
    return sets


def suggest_fixes(slices, p, ctx, mode):
    """Per error, concrete parameter changes the UI can apply with one click."""
    from .geometry import to_world
    for sl in slices:
        sl.fixes = []
        t = sl.thickness
        # A layer of a stack is the model at that height: take it out and the model has a slot missing through it and
        # the layers above sit wrong. So a stacked layer is never offered for deletion — the fixes that keep it are.
        stack = sl.group == "S"
        def delete(lb, title=None, stack=stack):
            return [] if stack else [{"title": title or f"delete {lb}", "set": {"skip": [lb] if isinstance(lb, str) else lb}}]
        toward = float(np.sign(np.dot(ctx.mid - sl.M[:3, 3], sl.M[:3, 2])) or 1.0)   # toward the centre along the normal
        off = dict(p["offset"]).get(sl.label, 0.0)
        for e in sl.errors:
            opts = []
            if "no crossing slice" in e or "floats" in e or "not connected" in e:
                regs = list(sl.profile.geoms); r = int(e.split()[1]) - 1 if e.startswith("region") else 0
                if r < len(regs):
                    c = regs[r].centroid; fx = mode.crossing_fix(ctx, sl, to_world(sl.M, [(c.x, c.y)])[0])
                    if fx:
                        opts.append(fx)
                step = max(5.0, 0.1 * max(ctx.ext))
                opts.append({"title": f"move {sl.label} {step:.0f} mm toward the centre", "set": {"offset": {sl.label: round(off + toward * step, 1)}}})
                if "not connected" in e:
                    grp = e.split("separate group: ")[1].split(")")[0].split(", ")
                    opts += delete(grp, f"delete the group ({len(grp)} parts)")
                    opts.append({"title": "round the model 3 mm (merges thin gaps)", "set": {"round": 3}})
                    if stack:                          # keep the layer, join it instead: glue the stack or thin the pegs
                        opts.append({"title": "gap 0 (touching, glued)", "set": {"space": 0}})
                        opts.append({"title": f"smaller connectors ({p.get('dowel_d', 6) * 0.6:.1f} mm)", "set": {"dowel_d": round(p.get("dowel_d", 6) * 0.6, 1)}})
                elif "across the gap" in e:            # a stacked island the dowel does not fit in
                    opts.append({"title": f"smaller connectors ({p['dowel_d'] * 0.6:.1f} mm)", "set": {"dowel_d": round(p["dowel_d"] * 0.6, 1)}})
                    opts.append({"title": "gap 0 (touching, glued)", "set": {"space": 0}})
                else:
                    opts += delete(sl.label)
            elif "cannot slide into its slot" in e:
                other = e.split()[0]
                opts.append({"title": f"move {other} {2 * t:g} mm", "set": {"offset": {other: round(dict(p["offset"]).get(other, 0.0) + 2 * t, 1)}}})
                opts.append({"title": f"move {other} −{2 * t:g} mm", "set": {"offset": {other: round(dict(p["offset"]).get(other, 0.0) - 2 * t, 1)}}})
                opts.append({"title": "notch ratio 0.35", "set": {"notch_ratio": 0.35}})
                opts.append({"title": "notch ratio 0.65", "set": {"notch_ratio": 0.65}})
                opts += delete(other)
            elif "cut the part into" in e:
                opts.append({"title": f"move {sl.label} {2 * t:g} mm", "set": {"offset": {sl.label: round(off + 2 * t, 1)}}})
                opts.append({"title": f"move {sl.label} −{2 * t:g} mm", "set": {"offset": {sl.label: round(off - 2 * t, 1)}}})
                if mode.name in ("interlocked", "curve", "radial"):
                    opts.append({"title": "notch ratio 0.35", "set": {"notch_ratio": 0.35}})
                    opts.append({"title": "notch ratio 0.65", "set": {"notch_ratio": 0.65}})
                opts += delete(sl.label)
            elif "too small" in e or "too thin" in e or "thinner than" in e:
                opts.append({"title": f"grow {sl.label}'s outline {p['min_feature'] / 2:g} mm (bridges become ≥ {p['min_feature']:g} mm)", "set": {"grow": {sl.label: p["min_feature"] / 2}}})
                opts += delete(sl.label)
                opts.append({"title": "thicken the model 2 mm", "set": {"thicken": 2}})
                opts.append({"title": "round the model 2 mm", "set": {"round": 2}})
            elif "crosses" in e and "collide" in e:
                other = e.split()[1]
                opts.append({"title": f"reset tilt / roll / offset of {sl.label}", "set": {"tilt": {sl.label: 0}, "roll": {sl.label: 0}, "offset": {sl.label: 0}}})
                opts += delete(other)
            if opts:
                sl.fixes.append({"error": e, "options": opts})
        # warnings worth a one-click fix as well
        grow_opt = {"title": f"grow {sl.label}'s outline {p['min_feature'] / 2:g} mm (bridges become ≥ {p['min_feature']:g} mm)", "set": {"grow": {sl.label: p["min_feature"] / 2}}}
        for w in sl.warnings:
            opts = []
            if "bridge thinner" in w:
                opts = [grow_opt, {"title": "round the model 2 mm", "set": {"round": 2}}]
            elif "separate island" in w:
                opts = [{"title": "round the model 3 mm (merges it into the body)", "set": {"round": 3}}]
                if mode.name == "stacked" and p.get("connect") == "none":
                    opts.append({"title": "hold the stack with pegs", "set": {"connect": "tab"}})
            elif "closer than" in w and "outline" in w:
                opts = [{"title": f"smaller connectors ({max(2.0, p.get('dowel_d', 6) * 0.6):g} mm)", "set": {"dowel_d": round(max(2.0, p.get("dowel_d", 6) * 0.6), 1)}}]
            elif "skipped" in w and "connection point" in w:
                opts = [{"title": f"smaller connectors ({max(2.0, p.get('dowel_d', 6) * 0.6):g} mm)", "set": {"dowel_d": round(max(2.0, p.get("dowel_d", 6) * 0.6), 1)}},
                        {"title": "fewer connection points", "set": {"n_points": max(1, int(p.get("n_points", 2)) - 1)}}]
            elif "without a" in w and "seam" in w:
                opts = [{"title": f"bigger triangles (facet {p.get('facet', 15) * 1.5:g} mm)", "set": {"facet": round(p.get("facet", 15) * 1.5, 1)}},
                        {"title": "smaller joints", "set": {"hole_d": round(max(1.0, p.get("hole_d", 2.5) * 0.7), 1), "inset": round(max(1.0, p.get("inset", 4) * 0.7), 1)}}]
            if opts:
                sl.fixes.append({"error": w, "options": opts})
