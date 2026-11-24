"""The kerf test: pieces to cut first, from a scrap of the job's own stock with its own machine settings, that measure
the kerf so it is typed in, not guessed.

Seven squares and a plate with seven square holes, each pair drawn for one kerf value around the job's: the square
grown by half of it and its hole shrunk by half of it, the way core.nest compensates a part. Cut with the real kerf K,
the pair drawn for K comes out both exactly the nominal size, so its square fits its hole snug; pairs drawn for more
than K do not go in, pairs for less are loose. The snug one names the kerf. Each square carries its value on it, each
hole has its value under it.
"""
from __future__ import annotations
import pathlib
from shapely.geometry import Polygon, box
from .export import UNIT, Item, design_name, dxf_doc, pdf_doc, svg_doc
from .geometry import as_multi, poly_coords
from .readme import write_readme

S, PAD, M = 20.0, 8.0, 5.0         # the test square, the room between and round the pieces, the sheet's margin (mm)


def kerf_values(p):
    """Seven kerf values around the job's own (0.15 mm, a CO2 laser's, when it has none), never below 0, in steps that
    suit its size: 0.05 mm for a laser, 0.1 for a fiber or a coarse laser, 0.25 for a plasma."""
    c = p.get("kerf", 0) or 0.15
    step = 0.05 if c <= 0.3 else 0.1 if c <= 0.8 else 0.25
    lo = max(0.0, c - 3 * step)
    return [round(lo + i * step, 3) for i in range(7)]


def kerf_items(plan):
    """The kerf test as export Items on one small sheet, and the sheet's (width, height)."""
    p = plan["params"]; u = p.get("units", "mm"); f = UNIT[u]; font = p.get("font", 4.0)
    ks = kerf_values(p)
    txt = lambda k: f"{k * f:.3g}"                                  # noqa: E731 — the value as the page shows it
    pitch, row = S + PAD, font + 3                                  # a hole's value goes in a row under it
    pw, ph = 7 * pitch + PAD, PAD + row + S + PAD + font + 4        # the plate: holes over their values, its name on top
    sq_h = S + max(ks)                                              # the row of squares under the plate
    W, H = M + pw + max(ks) + M, M + sq_h + PAD + ph + M + font * 2
    x0, y0 = M, M + sq_h + PAD                                      # the plate's corner
    cx = [x0 + PAD + S / 2 + i * pitch for i in range(7)]
    holes = [box(x - S / 2, y0 + PAD + row, x + S / 2, y0 + PAD + row + S).buffer(-k / 2, join_style=2) for x, k in zip(cx, ks)]
    plate = box(x0, y0, x0 + pw, y0 + ph).buffer(ks[3] / 2, join_style=2)
    plate = Polygon(plate.exterior.coords, [h.exterior.coords for h in holes])
    marks = [[x, y0 + PAD + row / 2, txt(k), 0.0, font / 0.6] for x, k in zip(cx, ks)]   # marks are drawn at 0.6 of their size
    name = f"kerf test: the square that fits its hole snug is your kerf ({u})"
    items = [Item({"label": name, "placed": poly_coords(as_multi(plate)), "marks": marks, "lines": [], "leader": None,
                   "label_pos": (x0 + pw / 2, y0 + ph - 2 - font / 2, 0.0), "label_short": True}, "placed")]
    for x, k in zip(cx, ks):
        sq = box(x - S / 2, M + max(ks) / 2, x + S / 2, M + max(ks) / 2 + S).buffer(k / 2, join_style=2)
        items.append(Item({"label": txt(k), "placed": poly_coords(as_multi(sq)), "marks": [], "lines": [], "leader": None,
                           "label_pos": (x, M + sq_h / 2, 0.0), "label_short": True}, "placed"))
    return items, W, H


def kerf_test(plan, out_dir, fmts=("svg", "dxf"), labels=True):
    """The kerf test's files in `out_dir`, with a README.txt; returns the paths (as core.export.export does)."""
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    p = plan["params"]; u = p.get("units", "mm"); font = p.get("font", 4.0)
    items, W, H = kerf_items(plan)
    stem = f"{design_name(plan)} kerf-test"            # with_suffix would take a revision's ".0" for an extension
    title = f"kerf test · {', '.join(f'{k * UNIT[u]:.3g}' for k in kerf_values(p))} {u}"
    files = []
    for fmt in fmts:
        f = out_dir / f"{stem}.{fmt}"
        if fmt == "svg":
            f.write_text(svg_doc(items, W, H, labels, True, font, u, title if labels else "", M), encoding="utf-8")
        elif fmt == "dxf":
            dxf_doc(items, labels, (W, H), font, u).saveas(f)
        elif fmt == "pdf":
            pdf_doc(f, [(items, W, H)], labels, True, font)
        else:
            continue
        files.append(f)
    k = kerf_values(p)
    notes = [f"Cut it from a scrap of your stock, with the settings you will cut the job with: the plate and seven squares, each square "
             f"drawn for one kerf, {k[0] * UNIT[u]:.3g} to {k[-1] * UNIT[u]:.3g} {u}, its value engraved on it and under its hole.",
             "Push each square into the hole with the same value. The pair that fits snug, without play and without force, gives your kerf:",
             "type it in Sheet & fit -> kerf. Between two pairs, take the value between them. Cut it with no kerf offset in your laser program.",
             "Engrave the values (LABEL) first, then the holes (INNER), then the outlines (OUTER), as the job."]
    return write_readme(plan, out_dir, files, notes)
