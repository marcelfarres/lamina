"""Cut-file export from plan.json: SVG, DXF, PDF, EPS — per sheet or one file per piece.

    uv run python -m core.export working-files/egg.json --fmt svg dxf pdf eps --labels --out working-files/egg_cut/

Layers / colours follow Slicer's Cut Layout convention:
  OUTER   blue    #0055ff   outer silhouette of each part
  INNER   green   #00aa00   interior cuts (slots, holes)
  SCORE   yellow  #d4a800   fold lines (folded panels): solid = mountain, dashed = valley (dotted = perforate) — score, do not cut
  LABEL   red     #ff0000   part labels + leader lines + sheet border (engrave / do not cut)
"""
from __future__ import annotations
import argparse, html, json, pathlib
import ezdxf
import numpy as np
from ezdxf import units as dxfunits
from shapely.geometry import box
from .geometry import as_multi, poly_coords

COLORS = {"OUTER": "#0055ff", "INNER": "#00aa00", "SCORE": "#d4a800", "LABEL": "#ff0000"}
RGB = {k: tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)) for k, v in COLORS.items()}
ACI = {"OUTER": 5, "INNER": 3, "SCORE": 2, "LABEL": 1}
UNIT = {"mm": 1.0, "cm": 0.1, "in": 1 / 25.4}
PT = 72 / 25.4


class Item:
    """One piece ready to draw: rings [(layer, [(x,y)...])], scores [(style, [(x,y)...])], marks [(x, y, text)], label.
    `names` (puzzle mode) replaces what is engraved; `key` stays the real label, which is what the sheet and the 3D
    view match a selection on."""
    def __init__(self, pc, rings_key, note="", names=None):
        self.rings = []
        for region in pc[rings_key]:
            self.rings.append(("OUTER", region[0]))
            self.rings += [("INNER", r) for r in region[1:]]
        self.key = pc["label"]
        self.label = (names or {}).get(pc["label"], pc["label"]) + (f" {note}" if note else "")
        self.label_pos = pc.get("label_pos")
        self.leader = pc.get("leader")
        self.scores = pc.get("lines") or []
        self.marks = pc.get("marks") or []


def items_for_sheet(plan, si):
    names = plan.get("codes") or {}
    items = [Item(pc, "placed", sl.get("note", ""), names) for sl in plan["slices"] for pc in sl["pieces"] if pc["place"][0] == si]
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
                    lw = 0.62 * font * len(pc["label"]) + 2
                    boxes.append((lp[0] - lw / 2, lp[1] - font * 0.7, lp[0] + lw / 2, lp[1] + font * 0.7))
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
    if "scale_check" not in plan:
        plan["scale_check"] = _free_spot(plan, w, h + font * 1.8) or {}
    spot = plan["scale_check"]
    if spot.get("sheet") != si:
        return None
    x, y = spot["x"], spot["y"]
    placed = [[[(px + x, py + y) for px, py in ring] for ring in region] for region in pc["kerfed"]]
    return Item({**pc, "placed": placed, "label_pos": (x + w / 2, y + h + font * 0.9, 0), "leader": None}, "placed", note)


def identical_groups(plan):
    """Pieces grouped by outline (plan.mark_identical decided it, so the files, the cut list and the parts table agree):
    [(piece, note, [every label in the group], [the ones cut from the same file but turned over])], copies dropped."""
    group = lambda pc: (pc.get("same") or []) + (pc.get("flipped") or [])
    copies = {l for sl in plan["slices"] for pc in sl["pieces"] for l in group(pc)}
    return [(pc, sl.get("note", ""), [pc["label"], *group(pc)], pc.get("flipped") or [])
            for sl in plan["slices"] for pc in sl["pieces"] if pc["label"] not in copies]


def item_for_piece(pc, note="", pad=1.0, names=None):
    """Piece alone at the origin (kerf applied, no sheet placement): cuts and label only."""
    it = Item(pc, "kerfed", note, names)
    xs = [x for _, r in it.rings for x, _ in r]; ys = [y for _, r in it.rings for _, y in r]
    x0, y0 = min(xs) - pad, min(ys) - pad
    it.rings = [(l, [(x - x0, y - y0) for x, y in r]) for l, r in it.rings]
    it.scores, it.marks = [], []
    w, h = max(xs) - x0 + pad, max(ys) - y0 + pad
    it.label_pos = (w / 2, h + 3, 0); it.leader = None
    return it, w, h + 6


DASH = {"solid": "", "dashed": "1.5,1", "dotted": "0.4,0.8"}
DXF_LT = {"solid": "BYLAYER", "dashed": "DASHED", "dotted": "DOT"}
PS_DASH = {"solid": "[] 0 setdash", "dashed": "[3 2] 0 setdash", "dotted": "[1 2] 0 setdash"}


def _dash(style):
    return DASH.get(style, "")


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
    return f"_{mm * UNIT[u]:.3g}{u}"


def sheet_title(plan, si):
    p = plan["params"]; u = p.get("units", "mm")
    thick = f"{sheet_thickness(plan, si) * UNIT[u]:.3g} {u} stock"
    return f"{p.get('project') or ''} v{p.get('rev') or '1.0'} · {plan['mode']} · {thick} · sheet {si + 1}/{plan['sheets']}".strip(" ·")


def svg_doc(items, width, height, labels, border=False, font=4.0, units="mm", title=""):
    """y is flipped so the drawing reads like the plan (y up). Physical size via width/height units, viewBox in mm."""
    f = UNIT[units]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width * f:.4f}{units}" height="{height * f:.4f}{units}" viewBox="0 0 {width} {height}">']
    for layer in ("OUTER", "INNER"):
        out.append(f'<g id="{layer}" fill="none" stroke="{COLORS[layer]}" stroke-width="0.15">')
        for it in items:
            for lay, ring in it.rings:
                if lay == layer:
                    out.append(f'<path data-label="{it.key}" d="' + " ".join(f"{'M' if i == 0 else 'L'}{x:.3f},{height - y:.3f}" for i, (x, y) in enumerate(ring)) + ' Z"/>')
        out.append("</g>")
    if any(it.scores for it in items):
        out.append(f'<g id="SCORE" fill="none" stroke="{COLORS["SCORE"]}" stroke-width="0.15">')
        for it in items:
            for style, pts in it.scores:
                d = " ".join(f"{'M' if i == 0 else 'L'}{x:.3f},{height - y:.3f}" for i, (x, y) in enumerate(pts))
                out.append(f'<path d="{d}"{" stroke-dasharray=" + chr(34) + _dash(style) + chr(34) if _dash(style) else ""}/>')
        out.append("</g>")
    if labels or border:
        out.append(f'<g id="LABEL" fill="{COLORS["LABEL"]}" stroke="{COLORS["LABEL"]}" stroke-width="0.15" font-family="sans-serif" font-size="{font}">')
        if border:
            out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="none"/>')
        if title:
            out.append(f'<text x="{font * 0.5}" y="{font * 1.2}" stroke="none">{html.escape(title)}</text>')
        if labels:
            for it in items:
                for mx, my, txt in it.marks:
                    out.append(f'<text x="{mx:.2f}" y="{height - my:.2f}" font-size="{font * 0.6}" text-anchor="middle" dominant-baseline="middle" stroke="none">{html.escape(str(txt))}</text>')
                if not it.label_pos:
                    continue
                lx, ly, rot = it.label_pos
                out.append(f'<text x="{lx:.2f}" y="{height - ly:.2f}" transform="rotate({-rot} {lx:.2f} {height - ly:.2f})" text-anchor="middle" dominant-baseline="middle" stroke="none">{html.escape(it.label)}</text>')
                if it.leader:
                    (ax, ay), (bx, by) = it.leader
                    out.append(f'<line x1="{ax:.2f}" y1="{height - ay:.2f}" x2="{bx:.2f}" y2="{height - by:.2f}"/>')
        out.append("</g>")
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
    for it in items:
        for layer, ring in it.rings:
            msp.add_lwpolyline(S(ring), close=True, dxfattribs={"layer": layer})
        for style, pts in it.scores:
            msp.add_lwpolyline(S(pts), dxfattribs={"layer": "SCORE", "linetype": DXF_LT.get(style, "BYLAYER")})
        if labels:
            for mx, my, txt in it.marks:
                msp.add_text(txt, height=font * 0.6 * f, dxfattribs={"layer": "LABEL"}).set_placement((mx * f, my * f), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
        if labels and it.label_pos:
            lx, ly, rot = it.label_pos
            msp.add_text(it.label, height=font * f, dxfattribs={"layer": "LABEL", "rotation": rot}).set_placement((lx * f, ly * f), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
            if it.leader:
                msp.add_line(tuple(v * f for v in it.leader[0]), tuple(v * f for v in it.leader[1]), dxfattribs={"layer": "LABEL"})
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
        for layer in ("OUTER", "INNER"):
            c.setStrokeColorRGB(*RGB[layer])
            for it in items:
                for lay, ring in it.rings:
                    if lay == layer:
                        p = c.beginPath(); p.moveTo(ring[0][0] * PT, ring[0][1] * PT)
                        for x, y in ring[1:]: p.lineTo(x * PT, y * PT)
                        p.close(); c.drawPath(p, stroke=1, fill=0)
        c.setStrokeColorRGB(*RGB["SCORE"])
        for it in items:
            for style, pts in it.scores:
                c.setDash({"solid": [], "dashed": [3, 2], "dotted": [1, 2]}.get(style, []))
                p = c.beginPath(); p.moveTo(pts[0][0] * PT, pts[0][1] * PT)
                for x, y in pts[1:]: p.lineTo(x * PT, y * PT)
                c.drawPath(p, stroke=1, fill=0)
        c.setDash([])
        c.setStrokeColorRGB(*RGB["LABEL"]); c.setFillColorRGB(*RGB["LABEL"])
        if border:
            c.rect(0, 0, w * PT, h * PT, stroke=1, fill=0)
        if labels:
            for it in items:
                c.setFont("Helvetica", font * 0.6 * PT)
                for mx, my, txt in it.marks:
                    c.drawCentredString(mx * PT, my * PT - font * 0.6 * PT * 0.35, txt)
                if not it.label_pos:
                    continue
                lx, ly, rot = it.label_pos
                c.setFont("Helvetica", font * PT)
                c.saveState(); c.translate(lx * PT, ly * PT); c.rotate(rot); c.drawCentredString(0, -font * PT * 0.35, it.label); c.restoreState()
                if it.leader:
                    c.line(it.leader[0][0] * PT, it.leader[0][1] * PT, it.leader[1][0] * PT, it.leader[1][1] * PT)
        c.showPage()
    c.save()


# ------------------------------------------------------------------ EPS — hand-written PostScript, one file per sheet
def eps_doc(items, w, h, labels, border, font):
    out = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {int(w * PT + 1)} {int(h * PT + 1)}", "0.3 setlinewidth",
           f"/Helvetica findfont {font * PT:.2f} scalefont setfont"]

    def path(pts, close):
        s = " ".join(f"{x * PT:.2f} {y * PT:.2f} {'moveto' if i == 0 else 'lineto'}" for i, (x, y) in enumerate(pts))
        return f"newpath {s} {'closepath ' if close else ''}stroke"
    for layer in ("OUTER", "INNER"):
        out.append("%s setrgbcolor" % " ".join(f"{v:.3f}" for v in RGB[layer]))
        out += [path(ring, True) for it in items for lay, ring in it.rings if lay == layer]
    out.append("%s setrgbcolor" % " ".join(f"{v:.3f}" for v in RGB["SCORE"]))
    for it in items:
        for style, pts in it.scores:
            out.append(PS_DASH.get(style, PS_DASH["solid"]) + " " + path(pts, False))
    out.append("[] 0 setdash %s setrgbcolor" % " ".join(f"{v:.3f}" for v in RGB["LABEL"]))
    if border:
        out.append(path([(0, 0), (w, 0), (w, h), (0, h)], True))
    if labels:
        for it in items:
            for mx, my, txt in it.marks:
                out.append(f"gsave /Helvetica findfont {font * 0.6 * PT:.2f} scalefont setfont {mx * PT:.2f} {my * PT:.2f} translate ({txt}) dup stringwidth pop -2 div {-font * 0.6 * PT * 0.35:.2f} moveto show grestore")
            if not it.label_pos:
                continue
            lx, ly, rot = it.label_pos
            out.append(f"gsave {lx * PT:.2f} {ly * PT:.2f} translate {rot} rotate ({it.label}) dup stringwidth pop -2 div {-font * PT * 0.35:.2f} moveto show grestore")
            if it.leader:
                out.append(path([it.leader[0], it.leader[1]], False))
    out.append("%%EOF")
    return "\n".join(out)


# ------------------------------------------------------------------ assembly key: the map that comes out of the cut
GROUPS = {"S": "stacked slice", "X": "X slice", "Y": "Y slice", "R": "radial half-slice", "C": "ring slice",
          "F": "folded panel", "J": "joint part", "P": "peg"}


def key_text(plan):
    """What the labels mean, which part is which, and the order the 3D view builds them in — written beside the cut
    files so the plan survives the walk from the machine to the bench. In puzzle mode what is engraved is a code that
    says nothing about where its part goes, and this file is the only way back."""
    p = plan["params"]; codes = plan.get("codes") or {}
    u = p.get("units", "mm"); f = UNIT[u]
    title = f"{p.get('project') or 'Lamina'} v{p.get('rev') or '1.0'} — assembly key"
    out = [title, "=" * len(title),
           f"{plan['mode']} · {plan['counts']['slices']} slices · {plan['counts']['parts']} parts · {plan['sheets']} sheet(s)",
           "", "How the labels read"]
    out += ["  " + s.strip() for s in (plan.get("legend") or "").split(" · ") if s.strip()]
    out += ["  A part too big for the sheet is cut into pieces and the piece number comes last: Z-3-2 is the second piece of Z-3.",
            "  Each label is engraved beside its own part on the sheet, with a line pointing at it."]
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
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ driver
def export(plan, out_dir, fmts=("svg", "dxf"), labels=True, per_piece=False, border=True, font=None, units=None, key=False):
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    font = font or plan["params"].get("font", 4.0); units = units or plan["params"].get("units", "mm")
    names = plan.get("codes") or {}                 # puzzle mode: engraved codes instead of positions
    written = []

    def write(stem, items, w, h, border_, fmts=fmts, title=""):
        for fmt in fmts:
            f = out_dir / f"{stem}.{fmt}"
            if fmt == "svg": f.write_text(svg_doc(items, w, h, labels, border_, font, units, title), encoding="utf-8")
            elif fmt == "dxf": dxf_doc(items, labels, (w, h) if border_ else None, font, units).saveas(f)
            elif fmt == "eps": f.write_text(eps_doc(items, w, h, labels, border_, font), encoding="latin-1")
            elif fmt == "pdf": pdf_doc(f, [(items, w, h)], labels, border_, font)
            written.append(f)
    if per_piece:                                   # identical pieces once, with the quantity in the file name and the label
        rows = []
        if plan["params"].get("scale_check", True):
            cpc, cnote, _, _ = scale_check_piece(plan)
            it, w, h = item_for_piece(cpc, cnote); write("scale-check", [it], w, h, False)
            rows.append(("scale-check", 1, cnote))
        thick = {pc["label"]: sl["thickness"] for sl in plan["slices"] for pc in sl["pieces"]}
        for pc, note, labels, flips in identical_groups(plan):
            n = len(labels); t = thick[pc["label"]]
            # in puzzle mode the file is named after the code too: a folder of Z-1, Z-2 … gives the order away
            stem = names.get(pc["label"], pc["label"]) + (f"_x{n}" if n > 1 else "") + thick_tag(plan, t)
            # the drawing carries the count and how many of them are turned over; the cut list names which ones
            it, w, h = item_for_piece(pc, " ".join(x for x in ([f"×{n}"] if n > 1 else []) + [f"({len(flips)} turned over)" if flips else "", note] if x), names=names)
            write(stem, [it], w, h, False)
            also = "also " + ", ".join(names.get(l, l) for l in labels[1:]) if n > 1 else note
            rows.append((stem, n, "; ".join(x for x in [also, "turn over " + ", ".join(names.get(l, l) for l in flips) if flips else ""] if x)))
        f = out_dir / "cut-list.txt"
        f.write_text("file                  qty  notes\n" + "".join(f"{s:22s}{n:3d}  {t}\n".rstrip() + "\n" for s, n, t in rows), encoding="utf-8")
        written.append(f)
    else:
        W, H = plan["sheet"]
        pages = [(items_for_sheet(plan, si), W, H) for si in range(plan["sheets"])]
        for si, (items, _, _) in enumerate(pages):
            write(f"sheet{si + 1}{thick_tag(plan, sheet_thickness(plan, si))}", items, W, H, border,
                  [x for x in fmts if x != "pdf"], sheet_title(plan, si) if labels else "")
        if "pdf" in fmts:                           # one multi-page PDF for all sheets
            f = out_dir / "sheets.pdf"; pdf_doc(f, pages, labels, border, font); written.append(f)
    if key:
        f = out_dir / "assembly-key.txt"; f.write_text(key_text(plan), encoding="utf-8"); written.append(f)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan"); ap.add_argument("--out", required=True)
    ap.add_argument("--fmt", nargs="+", default=["svg", "dxf"], choices=["svg", "dxf", "pdf", "eps"])
    ap.add_argument("--labels", action="store_true"); ap.add_argument("--per-piece", action="store_true")
    ap.add_argument("--no-border", action="store_true"); ap.add_argument("--font", type=float)
    ap.add_argument("--units", choices=["mm", "cm", "in"])
    ap.add_argument("--no-key", action="store_true", help="leave out assembly-key.txt (what the labels mean, the build order, and in puzzle mode the codes)")
    a = ap.parse_args(argv)
    plan = json.loads(pathlib.Path(a.plan).read_text())
    for f in export(plan, a.out, a.fmt, a.labels, a.per_piece, not a.no_border, a.font, a.units, key=not a.no_key):
        print(f)


if __name__ == "__main__":
    main()
