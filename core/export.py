"""Cut-file export from plan.json: SVG, DXF, PDF, EPS — per sheet or one file per piece.

    uv run python -m core.export working-files/egg.json --fmt svg dxf pdf eps --labels --out working-files/egg_cut/

Layers / colours follow Slicer's Cut Layout convention:
  OUTER   blue    #0055ff   outer silhouette of each part
  INNER   green   #00aa00   interior cuts (slots, holes)
  SCORE   yellow  #d4a800   fold lines (folded panels): solid = mountain, dashed = valley (dotted = perforate) — score, do not cut
  GUIDE   orange  #ff8800   the next layer's outline engraved on the slice below it (stacked, `next_outline`) — engrave, do not cut
  LABEL   red     #ff0000   part labels + leader lines + sheet border (engrave / do not cut). Every text is drawn in a
                            single-stroke font (core.font): open polylines the laser engraves in one pass, in every format
In the SVG each part is one group (<g class="piece" data-label="…">) holding its own layers, labels and marks, so it can
be moved as a unit in a vector editor; the colours above are on each part's layer groups, which is what laser software sorts by.
`grouped=False` writes the older colour-first layout instead, one group per colour for the whole sheet.
"""
from __future__ import annotations
import argparse, html, json, math, pathlib
import ezdxf
import numpy as np
import shapely
from ezdxf import units as dxfunits
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from .font import strokes as glyphs
from .geometry import as_multi, label_box, label_rect, poly_coords

COLORS = {"OUTER": "#0055ff", "INNER": "#00aa00", "SCORE": "#d4a800", "GUIDE": "#ff8800", "LABEL": "#ff0000"}
RGB = {k: tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)) for k, v in COLORS.items()}
ACI = {"OUTER": 5, "INNER": 3, "SCORE": 2, "GUIDE": 30, "LABEL": 1}
UNIT = {"mm": 1.0, "cm": 0.1, "in": 1 / 25.4}
PT = 72 / 25.4


class Item:
    """One piece ready to draw: rings [(layer, [(x,y)...])], scores [(style, [(x,y)...])], marks [(x, y, text)], label.
    `names` (puzzle mode) replaces what is engraved; `key` stays the real label, which is what the sheet and the 3D
    view match a selection on."""
    def __init__(self, pc, rings_key, note="", names=None, tag=""):
        self.rings = []
        for region in pc[rings_key]:
            self.rings.append(("OUTER", region[0]))
            self.rings += [("INNER", r) for r in region[1:]]
        self.key = pc["label"]
        self.size = pc.get("label_size")         # the label's capital height, when the sheet had to shrink it (else the font)
        # `tag` is the model's name (plan["label_tag"]), engraved first so parts of two models never get mixed up
        self.label = (f"{tag} " if tag and not pc.get("label_short") else "") + (names or {}).get(pc["label"], pc["label"]) + (f" {note}" if note else "")
        self.label_pos = pc.get("label_pos")
        self.leader = pc.get("leader")
        self.scores = pc.get("lines") or []
        self.marks = pc.get("marks") or []
        # the marks turn with their part: on the sheet by its placement, so a dowel number stays beside its hole and a
        # seam number on its seam however the part was nested; in the part's own frame (kerfed) not at all
        self.rot = (pc.get("place") or [0, 0, 0, 0])[3] if rings_key == "placed" else 0.0


def items_for_sheet(plan, si):
    names = plan.get("codes") or {}
    items = [Item(pc, "placed", sl.get("note", ""), names, plan.get("label_tag", ""))
             for sl in plan["slices"] for pc in sl["pieces"] if pc["place"][0] == si]
    coupon = scale_check_item(plan, si)
    return items + [coupon] if coupon else items


# ------------------------------------------------------------------ scale check: a bar to cut first and measure
def scale_check_piece(plan):
    """A calibration bar: 10 cm for metric jobs, 4 in for inch jobs, kerf-compensated like every part so measuring the
    cut bar checks the compensation too. Returns (piece dict at the origin, note, w, h)."""
    units = plan["params"].get("units", "mm"); kerf = plan.get("kerf", 0.0) or 0.0
    L, txt = (101.6, "4 in") if units == "in" else (100.0, "10 cm")
    h = 12.0
    g = as_multi(box(0, 0, L, h).buffer(kerf / 2, join_style=2))
    return {"label": "scale-check", "kerfed": poly_coords(g), "lines": [], "marks": []}, f"{txt} - cut this first and measure it", L + kerf, h + kerf


def _free_spot(plan, w, h, step=10.0):
    """First (sheet, x, y) with room for a w x h block, scanning each sheet from its top-right corner, where bottom-left
    nesting leaves space. Parts and their labels are the obstacles."""
    W, H = plan["sheet"]; p = plan["params"]; m = p.get("sheet_margin", 5); gap = p.get("gap", 3); font = p.get("font", 4.0)
    for si in range(plan["sheets"]):
        boxes = []
        for sl in plan["slices"]:
            for pc in sl["pieces"]:
                if pc["place"][0] != si:
                    continue
                xs = [x for region in pc["placed"] for x, _ in region[0]]; ys = [y for region in pc["placed"] for _, y in region[0]]
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
                lp = pc.get("label_pos")
                if lp:
                    lw, lh = label_box(f"{'' if pc.get('label_short') else plan.get('label_tag') or ''} {pc['label']}".strip(), pc.get("label_size") or font)
                    boxes.append((lp[0] - lw / 2, lp[1] - lh / 2, lp[0] + lw / 2, lp[1] + lh / 2))
        B = np.array(boxes) if boxes else np.zeros((0, 4))
        for y in np.arange(H - m - h, m - 1e-9, -step):
            for x in np.arange(W - m - w, m - 1e-9, -step):
                if not len(B) or not np.any((B[:, 0] < x + w + gap) & (B[:, 2] > x - gap) & (B[:, 1] < y + h + gap) & (B[:, 3] > y - gap)):
                    return {"sheet": int(si), "x": float(x), "y": float(y)}
    return None


def scale_check_item(plan, si):
    """The calibration bar as an item on sheet `si`, if that is the first sheet with room for it (the spot is kept in
    plan['scale_check'] so every export and the preview agree)."""
    if not plan["params"].get("scale_check", True):
        return None
    pc, note, w, h = scale_check_piece(plan)
    font = plan["params"].get("font", 4.0)
    lw, lh = label_box(f"{pc['label']} {note}", font)
    block = max(w, lw)                               # the bar with its note above it: the note is the wider of the two
    if "scale_check" not in plan:
        plan["scale_check"] = _free_spot(plan, block, h + lh + 1) or {}
    spot = plan["scale_check"]
    if spot.get("sheet") != si:
        return None
    x, y = spot["x"] + (block - w) / 2, spot["y"]    # the bar centred under its note
    placed = [[[(px + x, py + y) for px, py in ring] for ring in region] for region in pc["kerfed"]]
    return Item({**pc, "placed": placed, "label_pos": (x + w / 2, y + h + 1 + lh / 2, 0), "leader": None}, "placed", note)


def identical_groups(plan):
    """Pieces grouped by outline (plan.mark_identical decided it, so the files, the cut list and the parts table agree):
    [(piece, note, [every label in the group], [the ones cut from the same file but turned over])], copies dropped."""
    group = lambda pc: (pc.get("same") or []) + (pc.get("flipped") or [])
    copies = {l for sl in plan["slices"] for pc in sl["pieces"] for l in group(pc)}
    return [(pc, sl.get("note", ""), [pc["label"], *group(pc)], pc.get("flipped") or [])
            for sl in plan["slices"] for pc in sl["pieces"] if pc["label"] not in copies]


def label_on_part(pc):
    """The sheet's label spot in the part's own frame, (x, y, rot), when the label is engraved on the part — the
    placement undone: the part was turned `rot` about its origin and moved so its corner landed at `place`. None when
    the label sits beside the part on the sheet (it has a leader line), which a lone part's file cannot show."""
    if not pc.get("label_pos") or pc.get("leader"):
        return None
    _, px, py, rot = pc["place"]
    bx, by, *_ = affinity.rotate(MultiPolygon([Polygon(r[0], r[1:]) for r in pc["kerfed"]]), rot, origin=(0, 0)).bounds
    x, y, lrot = pc["label_pos"]
    lx, ly = affinity.rotate(shapely.points([x - (px - bx), y - (py - by)]), -rot, origin=(0, 0)).coords[0]
    return float(lx), float(ly), lrot - rot


def item_for_piece(pc, note="", pad=1.0, names=None, tag="", font=4.0):
    """Piece alone at the origin (kerf applied, no sheet placement): its cuts, its fold or guide lines, its seam
    numbers and its label — on the part exactly where the sheet engraves it, or above the drawing when the sheet puts
    it beside the part. The drawing is grown so a label overrunning a small part still comes out whole for the maker
    to trim."""
    it = Item(pc, "kerfed", note, names, tag)
    xs = [x for _, r in it.rings for x, _ in r]; ys = [y for _, r in it.rings for _, y in r]
    x0, y0 = min(xs) - pad, min(ys) - pad
    it.rings = [(l, [(x - x0, y - y0) for x, y in r]) for l, r in it.rings]
    it.scores = [(s, [(x - x0, y - y0) for x, y in pts]) for s, pts in pc.get("kerfed_lines") or []]   # in the part's own frame, like `kerfed`
    it.marks = [(m[0] - x0, m[1] - y0, m[2], m[3] if len(m) > 3 else 0.0) for m in pc.get("kerfed_marks") or []]
    w, h = max(xs) - x0 + pad, max(ys) - y0 + pad
    it.leader = None
    on = label_on_part(pc)
    if on is None:
        it.label_pos = (w / 2, h + 3, 0)                 # above the part, as the single-part files always did
        return it, w, h + 6
    x, y, rot = on[0] - x0, on[1] - y0, on[2]
    bx0, by0, bx1, by1 = label_rect(x, y, rot, *label_box(it.label, it.size or font)).bounds
    dx, dy = min(0.0, bx0 - 1), min(0.0, by0 - 1)      # a label overrunning left/bottom moves the whole drawing
    if dx or dy:
        it.rings = [(l, [(qx - dx, qy - dy) for qx, qy in r]) for l, r in it.rings]
        it.scores = [(s, [(qx - dx, qy - dy) for qx, qy in pts]) for s, pts in it.scores]
        it.marks = [(m[0] - dx, m[1] - dy, *m[2:]) for m in it.marks]
        x -= dx; y -= dy; w -= dx; h -= dy; bx1 -= dx; by1 -= dy
    it.label_pos = (x, y, rot)
    return it, max(w, bx1 + 1), max(h, by1 + 1)         # grow the sheet of paper so nothing is clipped


# The dash of each line style as (SVG dasharray in mm, PDF / PostScript dash in points, DXF linetype — its pattern is
# defined in dxf_doc). Each format keeps its own numbers: the laser and the printer read them at different scales.
DASH = {"solid": ((), [], "BYLAYER"), "dashed": ((1.5, 1), [3, 2], "DASHED"), "dotted": ((0.4, 0.8), [1, 2], "DOT")}
LINE_LAYER = {"guide": "GUIDE", "orient": "LABEL"}   # a line's layer by its style: the next layer's outline is engraved (GUIDE),
                                     # the orientation arrows go with the labels, every fold line is scored (SCORE)


def line_layer(style):
    return LINE_LAYER.get(style, "SCORE")


def strokes(items):
    """Every line of the drawing, item by item, as (layer, points, closed, dash style, part key): the cut rings
    (closed, solid), then the fold and guide lines. A style DASH does not know — "guide" — draws solid."""
    for it in items:
        for layer, ring in it.rings:
            yield layer, ring, True, "solid", it.key
        for style, pts in it.scores:
            yield line_layer(style), pts, False, style if style in DASH else "solid", it.key


def texts(items, font):
    """Every text to engrave, item by item, as (text, its strokes, leader): the marks (joint and dowel numbers, at 0.6
    of the font, turned with their part) then the label at `font`, turned as the sheet placed it, with the leader line
    from it to its part. The strokes are the single-stroke font's polylines, centred on the text's spot, in sheet mm — the same
    lines in every format, so what the laser engraves never depends on a font the machine's software has."""
    for it in items:
        for m in it.marks:
            yield str(m[2]), glyphs(str(m[2]), font * 0.6, m[0], m[1], it.rot + (m[3] if len(m) > 3 else 0.0)), None
        if it.label_pos:
            x, y, rot = it.label_pos
            yield it.label, glyphs(it.label, it.size or font, x, y, rot), it.leader


# ------------------------------------------------------------------ SVG
def sheet_thickness(plan, si):
    """The stock this sheet is cut from: nesting keeps one thickness per sheet."""
    p = plan["params"]
    return (plan.get("sheet_thick") or [p.get("thickness", 0.0)] * max(1, plan["sheets"]))[si]


def thick_tag(plan, mm):
    """Thickness for a file name, but only when the job mixes several: then the files must say which stock each one
    is cut from, and a wrong sheet ruins every fit on it."""
    if len({round(sl["thickness"], 6) for sl in plan["slices"]}) < 2:
        return ""
    u = plan["params"].get("units", "mm")
    return f" {mm * UNIT[u]:.3g}{u}"


def design_name(plan):
    """<project or model>_v<rev>: what every file of a job is named after, the zip it comes in and each file in it, so
    the cut files of two designs unzipped into one folder never mix (sheet1.svg of one over sheet1.svg of the other).
    One word: the spaces in a file name separate part, material, thickness and quantity. ASCII only: the zip's name
    travels in an HTTP header, which carries nothing else."""
    p = plan["params"]
    stem = "".join(c if c.isascii() and c.isalnum() or c in "-_." else "_" for c in str(p.get("project") or p.get("model_name") or "")).strip("_.")
    return f"{stem or 'model'}_v{p.get('rev') or '1.0'}"


def mat_tag(plan):
    """The stock in a file name, when the job says what it is: a file that leaves for a machine should name what it is
    cut from. It is one word, joined by dashes ("stainless-steel"), because the spaces separate part, material,
    thickness and quantity; anything but a letter or digit becomes a dash — the name travels from a project file
    someone else wrote, and a path separator in it must never reach the file system."""
    m = "-".join("".join(c if c.isalnum() else " " for c in str(plan["params"].get("material") or "")).split())
    return f" {m}" if m else ""


def sheet_title(plan, si):
    p = plan["params"]; u = p.get("units", "mm")
    thick = f"{sheet_thickness(plan, si) * UNIT[u]:.3g} {u} stock"
    return (f"{p.get('project') or ''} v{p.get('rev') or '1.0'} · {plan['mode']} · {thick} · "
            f"{'plate' if p.get('printed') else 'sheet'} {si + 1}/{plan['sheets']}").strip(" ·")


def svg_doc(items, width, height, labels, border=False, font=4.0, units="mm", title="", margin=5.0, grouped=True):
    """y is flipped so the drawing reads like the plan (y up). Physical size via width/height units, viewBox in mm.
    Every part is one <g class="piece" data-label="…">: its cuts, fold and guide lines, marks, arrows, label and
    leader, each in a sub-group named after its layer — so a part dragged somewhere else in Inkscape or Illustrator
    takes its labels and dowel numbers with it, and nothing goes out of register. The laser's software sorts the
    lines by colour, which each layer group carries whatever part it is in. The border and the title, which belong to the
    sheet and not to a part, are the first group. The title is engraved in the top margin, sized to fit the band
    nothing else uses, or left out when the margin holds no legible text.

    `grouped=False` writes the older colour-first layout instead: one group per colour for the whole sheet, with the
    border, the arrows and every label in the single LABEL group. For a tool that keeps the colours apart and never
    moves a part on its own."""
    f = UNIT[units]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width * f:.4f}{units}" height="{height * f:.4f}{units}" viewBox="0 0 {width} {height}">']

    def d_of(pts, closed=False):
        return " ".join(f"{'M' if i == 0 else 'L'}{x:.3f},{height - y:.3f}" for i, (x, y) in enumerate(pts)) + (" Z" if closed else "")

    def text_path(text, sts):
        """One text: one path of open strokes, its words in data-text (what the tests and a reader of the file go by)."""
        return f'<path data-text="{html.escape(text, quote=True)}" d="{" ".join(d_of(st) for st in sts)}"/>'

    def label_group(body):
        return [f'<g class="LABEL" fill="none" stroke="{COLORS["LABEL"]}" stroke-width="0.15" stroke-linecap="round" stroke-linejoin="round">'] + body + ["</g>"]

    def layer_group(layer, on):
        body = [f'<g class="{layer}" fill="none" stroke="{COLORS[layer]}" stroke-width="0.15">']
        for _, pts, closed, style, key in on:
            tag = f' data-label="{html.escape(key, quote=True)}"' if closed else ""
            dash = f' stroke-dasharray="{",".join(f"{v:g}" for v in DASH[style][0])}"' if DASH[style][0] else ""
            body.append(f'<path{tag} d="{d_of(pts, closed)}"{dash}/>')
        return body + ["</g>"]

    sheet = []
    if border:
        sheet.append(f'<rect x="0" y="0" width="{width}" height="{height}"/>')
    size = min(font, margin * 0.6)
    if title and size >= 1.5:
        sheet.append(text_path(title, glyphs(title, size, size * 0.5, height - margin / 2, anchor="start")))
    if grouped:
        if sheet:
            out += ['<g class="sheet">'] + label_group(sheet) + ["</g>"]
        for it in items:
            out.append(f'<g class="piece" data-label="{html.escape(it.key, quote=True)}">')
            lines = list(strokes([it]))
            for layer in ("OUTER", "INNER", "GUIDE", "SCORE"):
                on = [s for s in lines if s[0] == layer]
                if not on:                                            # a layer with nothing on it is left out
                    continue
                out += layer_group(layer, on)
            if labels:
                # the orientation arrows, then the marks and the label with its leader line
                body = [f'<path d="{d_of(pts)}"/>' for lay, pts, *_ in lines if lay == "LABEL"]
                for text, sts, leader in texts([it], font):
                    body.append(text_path(text, sts))
                    if leader:
                        (ax, ay), (bx, by) = leader
                        body.append(f'<line x1="{ax:.2f}" y1="{height - ay:.2f}" x2="{bx:.2f}" y2="{height - by:.2f}"/>')
                if body:
                    out += label_group(body)
            out.append("</g>")
    else:
        lines = list(strokes(items))
        for layer in ("OUTER", "INNER", "GUIDE", "SCORE"):
            on = [s for s in lines if s[0] == layer]
            if not on:
                continue
            out += layer_group(layer, on)
        body = list(sheet)
        if labels:
            body += [f'<path d="{d_of(pts)}"/>' for lay, pts, *_ in lines if lay == "LABEL"]
            for text, sts, leader in texts(items, font):
                body.append(text_path(text, sts))
                if leader:
                    (ax, ay), (bx, by) = leader
                    body.append(f'<line x1="{ax:.2f}" y1="{height - ay:.2f}" x2="{bx:.2f}" y2="{height - by:.2f}"/>')
        if body:
            out += label_group(body)
    out.append("</svg>")
    return "\n".join(out)


# ------------------------------------------------------------------ DXF
def dxf_doc(items, labels, border=None, font=4.0, units="mm"):
    f = UNIT[units]
    doc = ezdxf.new("R2010"); doc.units = {"mm": dxfunits.MM, "cm": dxfunits.CM, "in": dxfunits.IN}[units]
    for name, aci in ACI.items():
        doc.layers.add(name, color=aci)
    doc.linetypes.add("DASHED", pattern=[1.5 * f, 1.0 * f, -0.5 * f])
    doc.linetypes.add("DOT", pattern=[0.6 * f, 0.0, -0.6 * f])
    msp = doc.modelspace()
    S = lambda pts: [(x * f, y * f) for x, y in pts]
    for layer, pts, closed, style, _ in strokes(items):        # a cut ring takes its layer's linetype; a line names its own
        if layer == "LABEL" and not labels:                       # the orientation arrows go with the labels
            continue
        msp.add_lwpolyline(S(pts), close=closed, dxfattribs={"layer": layer} if closed else {"layer": layer, "linetype": DASH[style][2]})
    if labels:
        for _, sts, leader in texts(items, font):
            for st in sts:
                msp.add_lwpolyline(S(st), dxfattribs={"layer": "LABEL"})
            if leader:
                msp.add_line(tuple(v * f for v in leader[0]), tuple(v * f for v in leader[1]), dxfattribs={"layer": "LABEL"})
    if border:
        w, h = border
        msp.add_lwpolyline(S([(0, 0), (w, 0), (w, h), (0, h)]), close=True, dxfattribs={"layer": "LABEL"})
    return doc


# ------------------------------------------------------------------ PDF (reportlab) — multi-page, one sheet per page
def pdf_doc(path, pages, labels, border, font):
    from reportlab.pdfgen import canvas
    c = None
    for items, w, h in pages:
        if c is None:
            c = canvas.Canvas(str(path), pagesize=(w * PT, h * PT))
        else:
            c.setPageSize((w * PT, h * PT))
        c.setLineWidth(0.3)
        lines = list(strokes(items))
        for layer in ("OUTER", "INNER", "SCORE", "GUIDE"):
            c.setStrokeColorRGB(*RGB[layer])
            for lay, pts, closed, style, _ in lines:
                if lay != layer:
                    continue
                if not closed:
                    c.setDash(DASH[style][1])
                p = c.beginPath(); p.moveTo(pts[0][0] * PT, pts[0][1] * PT)
                for x, y in pts[1:]: p.lineTo(x * PT, y * PT)
                if closed: p.close()
                c.drawPath(p, stroke=1, fill=0)
        c.setDash([])
        c.setStrokeColorRGB(*RGB["LABEL"]); c.setFillColorRGB(*RGB["LABEL"])
        if border:
            c.rect(0, 0, w * PT, h * PT, stroke=1, fill=0)
        if labels:
            c.setLineCap(1); c.setLineJoin(1)                 # round: a stroke font's corners, like the laser draws them
            arrows = [[st[1]] for st in lines if st[0] == "LABEL"]
            for _, sts, leader in [*((None, a, None) for a in arrows), *texts(items, font)]:
                for st in sts:
                    p = c.beginPath(); p.moveTo(st[0][0] * PT, st[0][1] * PT)
                    for x, y in st[1:]: p.lineTo(x * PT, y * PT)
                    c.drawPath(p, stroke=1, fill=0)
                if leader:
                    c.line(leader[0][0] * PT, leader[0][1] * PT, leader[1][0] * PT, leader[1][1] * PT)
        c.showPage()
    c.save()


# ------------------------------------------------------------------ EPS — hand-written PostScript, one file per sheet
def eps_doc(items, w, h, labels, border, font):
    out = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {int(w * PT + 1)} {int(h * PT + 1)}", "0.3 setlinewidth"]

    def path(pts, close):
        s = " ".join(f"{x * PT:.2f} {y * PT:.2f} {'moveto' if i == 0 else 'lineto'}" for i, (x, y) in enumerate(pts))
        return f"newpath {s} {'closepath ' if close else ''}stroke"
    lines = list(strokes(items))
    for layer in ("OUTER", "INNER", "SCORE", "GUIDE"):
        out.append("%s setrgbcolor" % " ".join(f"{v:.3f}" for v in RGB[layer]))
        out += [(f"[{' '.join(map(str, DASH[style][1]))}] 0 setdash " if not closed else "") + path(pts, closed)
                for lay, pts, closed, style, _ in lines if lay == layer]
    out.append("[] 0 setdash %s setrgbcolor" % " ".join(f"{v:.3f}" for v in RGB["LABEL"]))
    if border:
        out.append(path([(0, 0), (w, 0), (w, h), (0, h)], True))
    if labels:
        out.append("1 setlinecap 1 setlinejoin")
        out += [path(pts, False) for lay, pts, *_ in lines if lay == "LABEL"]
        for _, sts, leader in texts(items, font):
            out += [path(st, False) for st in sts]
            if leader:
                out.append(path([leader[0], leader[1]], False))
    out.append("%%EOF")
    return "\n".join(out)


# ------------------------------------------------------------------ assembly key: the map that comes out of the cut
GROUPS = {"S": "stacked slice", "X": "X slice", "Y": "Y slice", "R": "radial half-slice", "C": "ring slice",
          "F": "folded panel", "J": "joint part", "P": "peg / spacer"}


def key_text(plan):
    """What the labels mean, which part is which, and the order the 3D view builds them in — written beside the cut
    files so the plan survives the walk from the machine to the bench. In puzzle mode what is engraved is a code that
    says nothing about where its part goes, and this file is the only way back."""
    p = plan["params"]; codes = plan.get("codes") or {}
    u = p.get("units", "mm"); f = UNIT[u]
    title = f"{p.get('project') or p.get('model_name') or 'Lamina'} v{p.get('rev') or '1.0'} — assembly key"   # whose key it is
    out = [title, "=" * len(title),
           f"{plan['mode']} · {plan['counts']['slices']} slices · {plan['counts']['parts']} parts · {plan['sheets']} sheet(s)",
           "", "How the labels read"]
    out += ["  " + s.strip() for s in (plan.get("legend") or "").split(" · ") if s.strip()]
    if plan.get("label_tag"):
        out.append(f"  Every label starts with {plan['label_tag']}, short for {p.get('project') or p.get('model_name') or 'the model'}: parts of two models cut together are never mixed up.")
    out += ["  A part too big for the sheet is cut into pieces and the piece number comes last: Z-3-2 is the second piece of Z-3.",
            {"on": "  Each label is engraved on its own part.", "beside": "  Each label is engraved beside its own part on the sheet, with a line pointing at it."}
            .get(p.get("label_place"), "  Each label is engraved on its own part where it fits, else beside it on the sheet with a line pointing at it."),
            "  A small part may carry its name without the short name in front: that was all it had room for."]
    if p.get("orient_mark"):
        out.append("  The two arrows at the middle of each part: the engraved face is the front, and the long arrow points the same way on "
                   "every part (up the slice's own frame), the short one to its right — turn the parts until their arrows agree.")
    if codes:
        out += ["  Puzzle mode: what is engraved is the code in the first column below — it says nothing about where the part goes.",
                "  This file is the only way back, so leave it out of the zip (the tickbox under Export) to keep the puzzle."]
    out += ["", f"Build order — the order the 3D view plays on the steps slider. Centres are in {u} from the middle of the model.", "",
            f"{'step':>4}  " + ("code   " if codes else "") + f"{'part':<12}{'what':<20}{'centre':<24}goes onto"]
    step = 0
    for sl in plan["slices"]:
        what = GROUPS.get(sl["group"], sl["group"])
        onto = ", ".join(sl.get("engages") or [])
        centre = "(%.0f, %.0f, %.0f)" % tuple(sl["M"][i][3] * f for i in range(3))
        for pc in sl["pieces"]:
            step += 1
            out.append(f"{step:>4}  " + (f"{codes.get(pc['label'], '--'):<7}" if codes else "")
                       + f"{pc['label']:<12}{what:<20}{centre:<24}{onto[:60]}")
    rods = {}
    for r in plan.get("rods") or []:                  # a rod per pair of slices; a straight one through several keeps its name
        if len(r) >= 8:
            e = rods.setdefault(r[5], {"lo": r[6], "d": r[2], "pts": []}); e["hi"] = r[7]; e["pts"] += [r[0], r[1]]
    if rods:
        out += ["", "Dowels — named after the lower of the two slices each joins and a letter: Z-3a is dowel a between Z-3 and Z-4,",
                "and the mark 3a is engraved beside its hole on both slices. Cut each rod to its length.", "",
                f"{'dowel':<10}{'from':<10}{'to':<10}{'length':<12}diameter"]
        for name, e in rods.items():
            length = max(math.dist(a, b) for a in e["pts"] for b in e["pts"])   # the ends along one line: the two farthest apart
            out.append(f"{name:<10}{e['lo']:<10}{e['hi']:<10}{length * f:<12.3g}{e['d'] * f:.3g} {u}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ driver
def export(plan, out_dir, fmts=("svg", "dxf"), labels=True, per_piece=False, border=True, font=None, units=None, key=False, grouped=True):
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    font = font or plan["params"].get("font", 4.0); units = units or plan["params"].get("units", "mm")
    names = plan.get("codes") or {}                 # puzzle mode: engraved codes instead of positions
    design = design_name(plan)                      # before every file name: two designs' files never mix
    written = []

    def size_of(it):
        """Width × height of a piece's cut outline as it lies in its file, in the export's units."""
        xs = [x for _, r in it.rings for x, _ in r]; ys = [y for _, r in it.rings for _, y in r]
        f, dec = UNIT[units], {"mm": 1, "cm": 2, "in": 3}[units]
        return f"{(max(xs) - min(xs)) * f:.{dec}f} × {(max(ys) - min(ys)) * f:.{dec}f}"

    def write(stem, items, w, h, border_, fmts=fmts, title=""):
        for fmt in fmts:
            f = out_dir / f"{design} {stem}.{fmt}"
            if fmt == "svg": f.write_text(svg_doc(items, w, h, labels, border_, font, units, title, plan["params"].get("sheet_margin", 5.0), grouped), encoding="utf-8")
            elif fmt == "dxf": dxf_doc(items, labels, (w, h) if border_ else None, font, units).saveas(f)
            elif fmt == "eps": f.write_text(eps_doc(items, w, h, labels, border_, font), encoding="latin-1", errors="replace")   # a label in another script: ? for its letters, not a failed export
            elif fmt == "pdf": pdf_doc(f, [(items, w, h)], labels, border_, font)
            written.append(f)
    if per_piece:                                   # identical pieces once, named "<part> <material> <thickness> x<qty>"
        rows = []
        if plan["params"].get("scale_check", True):
            cpc, cnote, _, _ = scale_check_piece(plan)
            stem = "scale-check" + mat_tag(plan) + " x1"
            it, w, h = item_for_piece(cpc, cnote); write(stem, [it], w, h, False)
            rows.append((f"{design} {stem}", 1, size_of(it), cnote))
        thick = {pc["label"]: sl["thickness"] for sl in plan["slices"] for pc in sl["pieces"]}
        for pc, note, same, flips in identical_groups(plan):
            n = len(same); t = thick[pc["label"]]
            # in puzzle mode the file is named after the code too: a folder of Z-1, Z-2 … gives the order away
            stem = names.get(pc["label"], pc["label"]) + mat_tag(plan) + thick_tag(plan, t) + f" x{n}"
            # the drawing carries the count and how many of them are turned over; the cut list names which ones
            it, w, h = item_for_piece(pc, " ".join(x for x in ([f"×{n}"] if n > 1 else []) + [f"({len(flips)} turned over)" if flips else "", note] if x), names=names,
                                      tag=plan.get("label_tag", ""), font=font)
            write(stem, [it], w, h, False)
            also = "also " + ", ".join(names.get(l, l) for l in same[1:]) if n > 1 else note
            rows.append((f"{design} {stem}", n, size_of(it), "; ".join(x for x in [also, "turn over " + ", ".join(names.get(l, l) for l in flips) if flips else ""] if x)))
        # one row per file: how many to cut, and each part's width × height as it lies in its file (what to check
        # against the stock, and the way to tell two parts apart that look alike)
        fw = max(len(s) for s, *_ in rows) + 2; sw = max(len(z) for _, _, z, _ in rows) + 2
        f = out_dir / f"{design} cut-list.txt"
        f.write_text(f"{'file':<{fw}}qty  {f'size ({units})':<{sw}}notes\n"
                     + "".join(f"{s:<{fw}}{n:3d}  {z:<{sw}}{t}".rstrip() + "\n" for s, n, z, t in rows), encoding="utf-8")
        written.append(f)
    else:
        W, H = plan["sheet"]
        pages = [(items_for_sheet(plan, si), W, H) for si in range(plan["sheets"])]
        for si, (items, _, _) in enumerate(pages):
            write(f"sheet{si + 1}{mat_tag(plan)}{thick_tag(plan, sheet_thickness(plan, si))}", items, W, H, border,
                  [x for x in fmts if x != "pdf"], sheet_title(plan, si) if labels else "")
        if "pdf" in fmts:                           # one multi-page PDF for all sheets
            f = out_dir / f"{design} sheets.pdf"; pdf_doc(f, pages, labels, border, font); written.append(f)
    if key:
        f = out_dir / f"{design} assembly-key.txt"; f.write_text(key_text(plan), encoding="utf-8"); written.append(f)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan"); ap.add_argument("--out", required=True)
    ap.add_argument("--fmt", nargs="+", default=["svg", "dxf"], choices=["svg", "dxf", "pdf", "eps"])
    ap.add_argument("--labels", action="store_true"); ap.add_argument("--per-piece", action="store_true")
    ap.add_argument("--no-border", action="store_true"); ap.add_argument("--font", type=float)
    ap.add_argument("--units", choices=["mm", "cm", "in"])
    ap.add_argument("--no-key", action="store_true", help="leave out assembly-key.txt (what the labels mean, the build order, and in puzzle mode the codes)")
    ap.add_argument("--no-group", action="store_true", help="SVG: one group per colour for the whole sheet (older layout) instead of one group per part")
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
    for f in export(plan, a.out, a.fmt, a.labels, a.per_piece, not a.no_border, a.font, a.units, key=not a.no_key, grouped=not a.no_group):
        print(f)


if __name__ == "__main__":
    main()
