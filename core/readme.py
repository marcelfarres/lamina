"""README.txt for every zip Lamina writes (cut files, the print set, a prototype, the fit tests, a mixed job): what is
in the zip and for which machine, the material, what each layer of a cut file does and in which order to run it, the
kerf, what to do by hand, the print notes, and how to build. One writer, so every zip answers the same questions. Each
section is written only when the zip needs it. Nothing here is a printer profile: only what Lamina knows from the parts.
"""
from __future__ import annotations

import pathlib
import re

from .export import COLORS, ORDER, design_name, line_layer, rods_of

CUT = {".svg", ".dxf", ".pdf", ".eps"}
# what each layer of a cut file does, in ORDER, with the colour word for its COLORS entry
LAYERS = {"FRAME": ("grey", "the sheet's edge and title, to show where the sheet is. Do not run it: switch its output off"),
          "LABEL": ("red", "engrave: part names, joint and dowel numbers, the arrows"),
          "GUIDE": ("orange", "engrave lightly: where the next part sits on this one"),
          "SCORE": ("yellow", "score, not through: the fold lines"),
          "INNER": ("green", "cut through: the holes and slots inside a part"),
          "OUTER": ("blue", "cut through: each part's outline. It runs last, so no part drops out before its holes are cut")}
# what a file is, by its name (the first rule that matches)
KINDS = [(r"3D-PRINT standoffs.*\.3mf$", "the standoffs, for the 3D printer, not the cutter"),
         (r"3D-PRINT standoffs.*\.txt$", "the sizes and print settings of the standoffs"),
         (r"sheet\d+.*\.(svg|dxf|eps)$", "the cut files, one per sheet"),
         (r"sheets\.pdf$", "all the sheets in one PDF, a page each"),
         (r"scale-check.*\.(svg|dxf|eps|pdf)$", "a square of known size: cut it first and measure it"),
         (r"\.(svg|dxf|eps|pdf)$", "the cut files, one per part"),
         (r"cut-list\.txt$", "how many of each part to cut, and its size"),
         (r"assembly-key\.txt$", "what each label means, and the order to build in"),
         (r"^pins-\d+\.3mf$", "the dowel pins, to print"),
         (r"^plate(-\d+)?\.3mf$", "the print plates: open them in OrcaSlicer or Bambu Studio"),
         (r"^fit_.*\.stl$", "each assembly of the fit test on its own"),
         (r"\.stl$", "each part on its own, flat, as STL")]


def _machine(p, cut, printed):
    if printed and not cut:
        return "a 3D printer (FDM)"
    m = (f"a CNC router with a {p['tool_d']:g} mm bit" if p.get("tool_d", 0) > 0 else "a laser or knife cutter")
    return m + (", and a 3D printer (FDM) for the standoffs" if printed else "")


def _thickness(plan):
    p, u = plan["params"], plan["params"].get("units", "mm")
    f = {"mm": 1.0, "cm": 0.1, "in": 1 / 25.4}[u]
    ts = sorted({round(t, 6) for t in plan.get("sheet_thick") or [p.get("thickness", 0.0)]})
    return " and ".join(f"{t * f:.3g} {u}" for t in ts)


def _layers(plan):
    """The layers this job's cut files hold: the frame, labels and outlines always; guides, scores and holes when a part has them."""
    pcs = [pc for sl in plan["slices"] for pc in sl["pieces"]]
    has = {"FRAME", "LABEL", "OUTER"} | {line_layer(s) for pc in pcs for s, _ in pc.get("lines") or []}
    return [k for k in ORDER if k in has or (k == "INNER" and any(len(r) > 1 for pc in pcs for r in pc["kerfed"]))]


def write_readme(plan, out_dir, files, notes=(), scale=1.0, estimate=None) -> list:
    """README.txt in `out_dir` for the zip that holds `files` (paths under out_dir): it is added to `files`, which is
    returned. `notes`: what the zip's writer has to say (the fit test's use, a print's settings and tags, a re-plan).
    `scale` is the print's when it is not the job's own size (a prototype). `estimate`: core.export.measure's totals
    of the sheets in this zip, when they are the job's (a fit test's or a kerf test's zip has none)."""
    out_dir = pathlib.Path(out_dir); p = plan["params"]
    names = [f.relative_to(out_dir).as_posix() for f in files]
    cut = [n for n in names if pathlib.Path(n).suffix in CUT]
    prints = [n for n in names if pathlib.Path(n).suffix in (".3mf", ".stl")]
    real = p.get("printed") and abs(scale - 1) < 1e-9                       # a print job at its own size, not a prototype
    head = f"{design_name(plan)}: {plan['mode']}, " + (f"printed at x{scale:.3g}" if not real and prints and not cut else
                                                        f"{p.get('material') or 'sheet'} {_thickness(plan)}")
    out = [head, "=" * len(head), "", "IN THIS ZIP"]
    seen = {}
    for n in names:
        what = next((w for rx, w in KINDS if re.search(rx, pathlib.PurePath(n).name)), "")
        seen.setdefault((pathlib.PurePath(n).parent.as_posix(), what), []).append(n)
    for (_, what), ns in seen.items():
        shown = ", ".join(ns) if len(ns) <= 3 else f"{ns[0]} … {ns[-1]} ({len(ns)} files)"
        out.append(f"  {shown}: {what}" if what else f"  {shown}")
    out.append("  A .lamina.json file, when there is one, is this job as a Lamina project. Open it in Lamina to change the job.")
    out += ["", "MACHINE AND MATERIAL",
            f"  For {_machine(p, cut, bool(prints))}." + (f" Material: {p['material']}, {_thickness(plan)}." if p.get("material") and (cut or real) else "")]
    if cut:
        out += ["", "LAYERS", "  Each layer has its own colour. Run them in this order, top to bottom. The files list them in this order too.",
                "  If your program runs the layers in another order, set this order in its layer list."]
        out += [f"  {k:<6} {LAYERS[k][0]:<7} {COLORS[k]}  {LAYERS[k][1]}" for k in _layers(plan)]
        if estimate:
            m = estimate
            out.append(f"  About {m['cut'] / 1000:.1f} m to cut, {m['score'] / 1000:.1f} m to score, {m['engrave'] / 1000:.1f} m to engrave, {m['pierces']} pierces.")
        out += ["", "KERF"]
        if p.get("compensate") and p.get("kerf", 0) > 0:
            out.append(f"  Compensated for a kerf of {p['kerf']:g} mm: each line is half of it outside the part. Cut on the line, with no offset.")
        elif p.get("tool_d", 0) > 0:
            out.append("  Not compensated: each line is the part's exact size. Your CAM program offsets the bit (below).")
        else:
            out.append("  Not compensated: each line is the part's exact size. Set the kerf offset in your laser program"
                       + (f" ({p['kerf']:g} mm on this job)" if p.get("kerf", 0) > 0 else "") + ", or tick compensate in Lamina and export again.")
    hand = []
    if cut and p.get("tool_d", 0) > 0:
        hand += ["Cut OUTER outside the line and INNER inside the line: a profile toolpath with the bit's offset.",
                 "Add holding tabs to OUTER in your CAM program, so the parts stay in the sheet.",
                 "LABEL and GUIDE need a V-bit or a small engraving bit. If you have none, leave them out: the assembly key names each part."]
    if cut and (rods := rods_of(plan)) and not p.get("printed"):
        d = sorted({round(e["d"], 3) for e in rods.values()})
        hand.append(f"Cut {len(rods)} dowel rod(s), {' and '.join(f'{x:g}' for x in d)} mm across. The assembly key gives each length.")
    if prints and not real:
        hand.append("plate.3mf holds the parts as they lie on the sheets. Let your slicer arrange them on its bed before you print.")
    if hand:
        out += ["", "BY HAND", *(f"  {x}" for x in hand)]
    if notes:
        out += ["", "NOTES", *(f"  {x}" for x in notes)]
    key = next((n for n in names if n.endswith("assembly-key.txt")), None)
    if key:
        out += ["", "PUT IT TOGETHER", f"  Read {key}: what each label means, and the order to build in.",
                "  The steps slider of Lamina's 3D view plays the same order."]
    f = out_dir / "README.txt"
    f.write_text("\n".join(out) + "\n", encoding="utf-8")
    return [*files, f]
