"""The step pictures of the site's guides (docs/<slug>/index.html), from the running app, into
docs/media/guides/<slug>-<n>.jpg: one for each numbered step, the control the step names ringed and labelled.

    uv run python scripts/media/guides.py                  every guide
    uv run python scripts/media/guides.py stacked-slices   only these

One function for each guide. It walks the guide's steps in their order, from a new tab at the guide's own link
(app/index.html#<technique>), and step() saves one picture for each: the whole window, so the reader sees where the
control is. The look is news.py's: its App, its ring with a dark edge and a word label, its 900 px JPGs. Run it again
after an interface change, then look at every picture before it goes in a page.
"""
import functools
import http.server
import io
import sys
import threading

from PIL import Image, ImageDraw

from news import ROOT, App, fold_to, save, tag
from serve import serve_app                 # news.py puts tests/ on the path

OUT = ROOT / "docs" / "media" / "guides"
WINDOW = {"width": 1100, "height": 760}     # 900 px wide in the JPG: the labels on the page still read


WARN_FIX = "#msgs .msg.warn:has(.fix)"       # the first warning with its fix buttons, under the counts


def row(tab, p):                            # a setting's row, by its name in the technique's schema
    return f"section[data-tab={tab}] .f[data-p={p}]"


def stepper(app, slug):
    """step((selector or box, label), ...) saves <slug>-1.jpg, -2, ... in the order it is called. A ringed row in the
    settings column is scrolled to its middle first. A third item "below" puts the label under the ring: above it, it
    would hide the control of the step before. The picture is the window's width, from over the ringed controls down
    to the counts under the 3D view (Marcel, 2026-11-24: about half the height of the whole window)."""
    n = 0

    def step(*marks):
        nonlocal n
        n += 1
        for m, *_ in marks:
            if isinstance(m, str):
                app.p.locator(m).first.evaluate("e => e.closest('#tabs') && e.scrollIntoView({block: 'center'})")
        app.p.mouse.move(WINDOW["width"] - 5, 45)   # off every control: left on the last click, it opened that row's help
        app.p.wait_for_timeout(400)
        boxes = [app.box(m) if isinstance(m, str) else m for m, *_ in marks]
        bottom = min(WINDOW["height"], max(app.box("#stats")[3], *(b[3] + (50 if below else 0)   # room for a label under
                                                                     for b, (_m, _l, *below) in zip(boxes, marks))) + 6)
        top = max(0, min(min(b[1] for b in boxes) - 60, bottom - WINDOW["height"] // 2))
        img = app.grab((0, top, WINDOW["width"], bottom), [(m, "" if below else label) for m, label, *below in marks])
        oy = max(0, top - 12)                       # grab's crop starts 12 px over the area
        for (a, _, _, e), (_m, label, *below) in zip(boxes, marks):
            if below:
                tag(ImageDraw.Draw(img), a - 6, e + 12 - oy, label)
        save(f"{slug}-{n}", img, OUT)
    return step


def upload(app, name):                      # a reader's own model: an example's file, through the file box
    app.p.set_input_files("#file", str(ROOT / "examples" / f"{name}.stl"))
    app.idle()


# ---- the steps the guides share ----------------------------------------------------------------------------------


def opened(app, step, model=None):          # the app as the guide's link opens it, then upload: a model, or none
    step(("nav button[data-t=model]", "Model tab", "below"))
    step(("label.f:has(#file)", "upload"))
    if model:
        upload(app, model)


def kind(app, step, k, label):              # Sheet & fit: what you make with
    app.tab("sheet")
    app.p.click(f"#kind button[data-kind={k}]")
    app.idle()
    step((f"#kind button[data-kind={k}]", label))


def sheet(app, step, thickness=None):       # the machine under it, the material and its thickness
    step(("#kind .f:has(#machine)", "machine", "below"))
    step((".f:has(#material)", "material"))
    if thickness:
        app.set("thickness", thickness)
    step((row("sheet", "thickness"), "thickness"))


def checks(app, step):     # the counts under the 3D view, with the first warning and its fix buttons if there is one:
    s = app.box("#stats")  # one ring round both, so the label sits over the 3D view and hides none of the counts
    w = app.box(WARN_FIX) if app.p.locator(WARN_FIX).count() else s
    step(((min(s[0], w[0]), s[1], max(s[2], w[2]), max(s[3], w[3])), "errors and warnings" + (", and their fixes" if w is not s else "")))


def fit_and_cut(app, step):                 # the fit test first, its answer on Sheet & fit, then the sheets
    app.tab("export")
    step(("#dlfit .r", "fit test"))
    app.tab("sheet")
    step((row("sheet", "slot_offset"), "slot offset"))
    app.tab("export")
    step(("#dl a.main", "the sheets"))


def build_order(app, step):                 # the steps slider over the 3D view, half way: the order the parts go in
    half = "s => {s.value = Math.round(s.max / 2); s.dispatchEvent(new Event('input'))}"
    app.p.locator("#steps").evaluate(half)
    app.p.wait_for_timeout(1200)
    step(("label:has(#steps)", "steps"))
    app.p.locator("#steps").evaluate("s => {s.value = s.max; s.dispatchEvent(new Event('input'))}")


# ---- one function for each guide, its steps in order: the tabs left to right, as a new reader meets them ----------


def stacked_slices(app, step):              # the link opens the bunny; the pictures go on with the video's horse
    opened(app, step, "horse_statue")
    app.set("size_2", 260)
    step((row("model", "size"), "model size"))
    app.tab("technique")
    app.set("axis", "y")                                                # side profiles
    step((row("technique", "axis"), "axis"))
    step((row("technique", "distribution"), "distribution"))
    step((row("technique", "connect"), "connect with"))
    app.set("dowel_d", 2)          # the video's 2 mm rods; the bunny's 4 mm left one piece of the horse unjoined
    step((row("technique", "dowel_d"), "dowel diameter", "below"))
    kind(app, step, "laser", "Laser")
    sheet(app, step, 3)
    checks(app, step)
    fit_and_cut(app, step)


def interlocking_slices(app, step):         # the link opens the bracket; the pictures go on with the video's torus
    opened(app, step, "torus")
    app.set("size_0", 240)
    step((row("model", "size"), "model size"))
    app.tab("technique")
    step((row("technique", "up"), "assembly axis"))
    step((row("technique", "distribution"), "distribution"))
    app.set("nx", 9)                                                    # the video's 9 by 7
    app.set("ny", 7)
    step((row("technique", "nx"), "slices, 1st family"), (row("technique", "ny"), "slices, 2nd family", "below"))
    kind(app, step, "laser", "Laser")
    sheet(app, step, 3)
    checks(app, step)
    fit_and_cut(app, step)
    build_order(app, step)


def papercraft(app, step):                  # the cow the link opens: low-poly, it folds well
    opened(app, step)
    step((row("model", "size"), "model size"))
    app.tab("technique")
    step((row("technique", "facet"), "face size"))
    step((row("technique", "joint"), "joint"))
    kind(app, step, "laser", "Laser")
    sheet(app, step)
    checks(app, step)
    app.tab("export")
    step(("#dl a.main", "the sheets"), ("#other_fold > summary", "other formats", "below"))
    fold_to(app, 55)
    step(("label:has(#fold)", "fold"))
    fold_to(app, 100)


def print_flat_parts(app, step):            # the cow the link opens, printed: its panels print flat and fold up
    opened(app, step)
    kind(app, step, "printer", "3D printer")
    app.p.select_option("#machine", "bambu_x1")   # a named printer sets its bed (256 mm); on the generic 180 mm
    app.idle()                                    # plate two cow panels were laid past its edge (reported as a bug)
    step(("#kind .f:has(#machine)", "machine", "below"))
    step((".f:has(#material)", "material"))
    app.tab("technique")
    app.set("joint", "click")                                           # a printed joint: no glue
    step((row("technique", "joint"), "joint"))
    checks(app, step)
    app.tab("export")
    step(("#dl a.main", "print set"))


def model_to_laser_cut(app, step):          # the overview, on the bracket the link opens in Interlocked Slices
    opened(app, step)
    step((".f:has([data-rot])", "turn"))
    step((row("model", "size"), "model size"))
    app.tab("technique")
    step(("#modes", "the seven techniques"))
    app.tab("sheet")
    step(("#kind .kinds", "what you make with"))
    sheet(app, step)
    checks(app, step)
    app.tab("export")
    step(("#dl a.main", "the cut files"))


def fusion_alternative(app, step):          # moving a project over, on the bunny the link opens in Stacked Slices
    opened(app, step)
    app.tab("technique")
    step(("#modes button[data-m=stacked]", "the same name", "below"))   # above, it covered two other technique names
    app.tab("sheet")
    step((".f:has(#material)", "material"))
    step((row("sheet", "thickness"), "thickness"))
    checks(app, step)
    app.tab("export")
    step(("#dl a.main", "SVG and DXF"), ("#other_fold > summary", "PDF and EPS", "below"))


GUIDES = {                                  # each guide's link opens the app on its technique (Marcel, 2026-11-24)
    "stacked-slices": ("stacked", stacked_slices),
    "interlocking-slices": ("interlocked", interlocking_slices),
    "papercraft": ("folded", papercraft),
    "3d-print-flat-parts": ("folded", print_flat_parts),
    "3d-model-to-laser-cut": ("interlocked", model_to_laser_cut),
    "slicer-for-fusion-360-alternative": ("stacked", fusion_alternative),
}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def news_picture(browser):
    """web/static/news/0.4.1-guides.jpg, the CHANGELOG's picture: one step of the stacked guide as the site shows it,
    its number, words and picture. docs/ is the site without the app, so it is served as it is, with no build."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "docs")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    page = browser.new_page(viewport={"width": 900, "height": 900})
    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/stacked-slices/")
    page.evaluate("() => document.querySelectorAll('img[loading=lazy]').forEach(i => i.loading = 'eager')")
    page.wait_for_function("() => [...document.images].every(i => i.complete)")
    li, ol = page.locator("ol.steps > li").nth(7).bounding_box(), page.locator("ol.steps").bounding_box()   # step 8, Laser
    clip = {"x": ol["x"] - 8, "y": li["y"] - 10, "width": li["x"] + li["width"] - ol["x"] + 16, "height": li["height"] + 20}
    save("0.4.1-guides", Image.open(io.BytesIO(page.screenshot(clip=clip, full_page=True))).convert("RGB"))
    page.close()
    srv.shutdown()


def main(only):
    from playwright.sync_api import sync_playwright
    todo = {g: f for g, f in GUIDES.items() if not only or g in only}
    if only and len(todo) < len(only):
        raise SystemExit(f"no such guide: {sorted(set(only) - set(todo))}; there are {sorted(GUIDES)}")
    with serve_app() as url, sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"])
        for slug, (technique, f) in todo.items():
            page = browser.new_page(viewport=WINDOW)    # a new tab: no session, so the app opens as a reader's does
            page.goto(f"{url}/#{technique}")
            app = App(page)                             # idle() alone passes before the first slice has started
            page.wait_for_function("() => /^(ready|error)/.test(document.getElementById('status')?.textContent)", timeout=300_000)
            app.idle()
            f(app, stepper(app, slug))
            page.close()
        news_picture(browser)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
