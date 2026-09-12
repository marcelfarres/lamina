"""Regression matrix: plan + sheet export + PNG previews (PIL) for many model/mode/feature combinations,
then one contact sheet to eyeball. Exit code 1 if any case crashes.

    uv run python tests/run_matrix.py [substring-filter]      → working-files/matrix/contact.png
"""
import pathlib, sys, traceback
import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "working-files" / "matrix"; OUT.mkdir(parents=True, exist_ok=True)

from core.plan import build
from core.export import export

CASES = {
    # name: (model, mode, params)
    "cube_stacked":         ("cube", "stacked", {"thickness": 3}),
    "cube_interlocked":     ("cube", "interlocked", {"nx": 3, "ny": 3}),
    "cylinder_radial":      ("cylinder", "radial", {"count": 6, "ring_count": 4}),
    "cone_stacked_dowel":   ("cone", "stacked", {"connect": "dowel", "dowel_d": 6, "dowel_shape": "cross", "thickness": 3}),
    "cone_stacked_outer_pegs": ("cone", "stacked", {"surface": "outer", "connect": "tab", "dowel_d": 8, "thickness": 3}),
    "egg_stacked_spacers":  ("egg", "stacked", {"space": 10, "connect": "tab", "placement": "random", "n_points": 3, "thickness": 3}),
    "pyramid_interlocked":  ("pyramid", "interlocked", {"nx": 4, "ny": 4, "notch_ratio": 0.65}),
    "sphere_interlocked_flare": ("sphere", "interlocked", {"nx": 5, "ny": 5, "notch_factor": 0.5}),
    "torus_interlocked":    ("torus", "interlocked", {"nx": 6, "ny": 6}),
    "torus_radial":         ("torus", "radial", {"count": 8, "ring_count": 3}),
    "egg_rotated":          ("egg", "interlocked", {"nx": 5, "ny": 4, "rotate": [0, 35, 0], "center": [10, 0, 0]}),
    "bracket_interlocked_dogbone": ("bracket", "interlocked", {"nx": 5, "ny": 4, "relief": "dogbone", "tool_d": 3}),
    "bracket_stacked_x":    ("bracket", "stacked", {"axis": "x", "thickness": 6}),
    "tube_stacked":         ("tube", "stacked", {"thickness": 6}),                 # ring slices, no dowel: glue-only
    "tall_bar_split":       ("tall_bar", "stacked", {"axis": "y", "distribution": "count", "count": 4, "sheet": [300, 300], "tab": 8}),
    "tall_bar_tilt":        ("tall_bar", "interlocked", {"nx": 3, "ny": 2, "tilt": {"X-2": 20, "Y-1": -15}, "offset": {"X-1": 10}}),
    "egg_stacked_var_thick":("egg", "stacked", {"distribution": "count", "count": 8, "thickness": 6, "thick": {"Z-1": 3, "Z-8": 3}}),
    "egg_interlocked_kerf": ("egg", "interlocked", {"nx": 5, "ny": 4, "kerf": 0.2, "compensate": True, "slot_offset": 0.15}),
    "egg_radial":           ("egg", "radial", {"count": 4, "ring_count": 3, "hole_d": 8}),
    "egg_curve":            ("egg", "curve", {"count": 7, "spines": 1, "curve": [[-60, -8], [0, 8], [60, -8]]}),
    "egg_hollow":           ("egg", "stacked", {"hollow": 8, "thickness": 4}),
    "snowman_interlocked":  ("snowman", "interlocked", {"nx": 4, "ny": 4}),
    "blob_interlocked":     ("blob", "interlocked", {"nx": 6, "ny": 5}),
    "blob_stacked":         ("blob", "stacked", {"thickness": 4, "connect": "dowel", "dowel_d": 5}),
    "pear_radial":          ("pear", "radial", {"count": 6, "ring_count": 5}),
    "twisted_interlocked":  ("twisted", "interlocked", {"nx": 6, "ny": 4, "rotate_grid": 30}),
    "bowl_interlocked":     ("bowl", "interlocked", {"nx": 5, "ny": 5}),          # thin shell: expect thin/floating checks
    "bowl_stacked":         ("bowl", "stacked", {"thickness": 3}),
    "sphere_interlocked_up_y": ("sphere", "interlocked", {"up": "y", "nx": 4, "ny": 4}),
    "cube_folded_tab":      ("cube", "folded", {"facet": 0, "joint": "tab"}),
    "egg_folded_strip":     ("egg", "folded", {"facet": 25, "joint": "strip"}),
    "head_igea_interlocked":("head_igea", "interlocked", {"nx": 8, "ny": 6, "thickness": 3}),
    "head_igea_folded_cloth":("head_igea", "folded", {"facet": 16, "joint": "laced", "separate": True}),
    "head_igea_stacked":    ("head_igea", "stacked", {"thickness": 3, "connect": "dowel", "dowel_d": 6}),
    "cow_spot_folded_rib":  ("cow_spot", "folded", {"facet": 18, "joint": "rib", "thickness": 1, "rib_w": 6, "inset": 3}),
    "cow_spot_interlocked": ("cow_spot", "interlocked", {"nx": 7, "ny": 5, "thickness": 3}),
    "horse_curve":          ("horse", "curve", {"count": 10, "spines": 1, "plane": "yz"}),
    "snowman_folded_tongue": ("snowman", "folded", {"facet": 16, "joint": "tongue"}),
    "bunny_stacked_outer":  ("bunny", "stacked", {"thickness": 4, "surface": "outer", "connect": "tab", "dowel_d": 8}),
    "horse_radial_center":  ("horse", "radial", {"count": 5, "ring_count": 4, "thickness": 3, "center": [0, 0, 20]}),
}

COL = {"X": (217, 167, 96), "Y": (127, 176, 217), "S": (217, 192, 128), "R": (143, 208, 143), "C": (192, 112, 112), "F": (201, 160, 224), "J": (240, 192, 96), "P": (160, 160, 160)}


def iso_png(plan, path, size=(800, 600)):
    """Painter's-order orthographic view of every facet polygon (mid-plane only) — enough to eyeball a plan."""
    az, el = np.radians(-60), np.radians(30)
    R = np.array([[np.cos(az), np.sin(az), 0], [-np.sin(az), np.cos(az), 0], [0, 0, 1]])
    R = np.array([[1, 0, 0], [0, np.cos(el), np.sin(el)], [0, -np.sin(el), np.cos(el)]]) @ R
    polys = []
    for s in plan["slices"]:
        for pc in s["pieces"]:
            for fc in pc["facets"]:
                M = np.array(fc["M"])
                for rings in fc["rings"]:
                    P = np.array([[x, y, 0, 1] for x, y in rings[0]]) @ M.T
                    Q = P[:, :3] @ R.T
                    polys.append((Q[:, 1].mean(), Q[:, [0, 2]], COL.get(s["group"], (200, 200, 200))))
    if not polys:
        return
    allp = np.vstack([q for _, q, _ in polys]); lo, hi = allp.min(0), allp.max(0)
    sc = 0.9 * min(size[0] / (hi[0] - lo[0] + 1e-9), size[1] / (hi[1] - lo[1] + 1e-9))
    im = Image.new("RGB", size, (20, 21, 23)); d = ImageDraw.Draw(im)
    for _, q, col in sorted(polys, key=lambda t: -t[0]):
        pts = [(size[0] / 2 + (x - (lo[0] + hi[0]) / 2) * sc, size[1] / 2 - (y - (lo[1] + hi[1]) / 2) * sc) for x, y in q]
        if len(pts) >= 3:
            d.polygon(pts, fill=col, outline=(30, 30, 30))
    im.save(path)


def sheet_png(plan, path, si=0, width=800):
    W, H = plan["sheet"]; sc = width / W
    im = Image.new("RGB", (width, int(H * sc)), (29, 31, 36)); d = ImageDraw.Draw(im)
    for s in plan["slices"]:
        for pc in s["pieces"]:
            if pc["place"][0] != si:
                continue
            for rings in pc["placed"]:
                for i, r in enumerate(rings):
                    d.polygon([(x * sc, (H - y) * sc) for x, y in r], outline=(0, 85, 255) if i == 0 else (0, 170, 0))
            for _, pts in pc["lines"]:
                d.line([(x * sc, (H - y) * sc) for x, y in pts], fill=(212, 168, 0))
            if pc.get("label_pos"):
                lx, ly, _ = pc["label_pos"]; d.text((lx * sc, (H - ly) * sc), pc["label"], fill=(255, 80, 80), anchor="mm")
    im.save(path)


def main(flt=None):
    tiles, failed = [], 0
    for name, (model, mode, params) in CASES.items():
        if flt and flt not in name:
            continue
        stem = OUT / name
        try:
            plan = build(ROOT / "examples" / f"{model}.stl", mode, params, stem)
            export(plan, OUT / f"{name}_cut", ("svg",), labels=True)
            iso_png(plan, stem.with_name(f"{name}_preview.png")); sheet_png(plan, stem.with_name(f"{name}_sheet.png"))
            c = plan["counts"]
            issues = [f"{s['label']}: {e}" for s in plan["slices"] + plan["dropped"] for e in s.get("errors", [])] + plan["errors"]
            print(f"OK   {name:28s} {c['slices']:4d} parts {plan['sheets']} sheet(s) {plan['sheet_usage']:4.0%} {c['errors']:3d} err {c['warnings']:3d} warn  {'; '.join(issues)[:140]}")
        except Exception as e:
            failed += 1
            print(f"FAIL {name:28s} {e}"); traceback.print_exc(limit=3)
        for kind in ("preview", "sheet"):
            p = stem.with_name(f"{name}_{kind}.png")
            if p.exists():
                tiles.append((f"{name} / {kind}", p))
    if tiles:
        tw, th, cols = 400, 300, 4
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tw, rows * (th + 18)), "black"); d = ImageDraw.Draw(sheet)
        for i, (lab, p) in enumerate(tiles):
            im = Image.open(p).convert("RGB"); im.thumbnail((tw, th))
            x, y = (i % cols) * tw, (i // cols) * (th + 18)
            sheet.paste(im, (x, y + 18)); d.text((x + 4, y + 2), lab, fill="white")
        sheet.save(OUT / "contact.png"); print("contact sheet:", OUT / "contact.png")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)



