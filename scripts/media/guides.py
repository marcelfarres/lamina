"""The pictures of the site's guides (docs/<slug>/index.html), from the running app, into
docs/media/guides/<slug>-<n>.jpg: one for each numbered step, the control the step names ringed and labelled, and
<slug>-<name>.jpg for what one setting changes.

    uv run python scripts/media/guides.py                  every guide
    uv run python scripts/media/guides.py stacked-slices   only these

One function for each guide. It walks the guide's steps in their order, from a new tab at the guide's own link
(app/index.html#<technique>/<example>), and step() saves one picture for each: the window's width, so the reader sees
where the control is. compare() saves what one setting changes: the 3D view at two or three values, with the counts.
The look is news.py's: its App, its ring with a dark edge and a word label, its 900 px JPGs. Run it again after an
interface change, then look at every picture before it goes in a page.
"""
import functools
import http.server
import io
import sys
import threading

from PIL import Image, ImageDraw

from news import ROOT, App, caption, fold_to, save, side_by_side, tag
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


# ---- the steps the guides share ----------------------------------------------------------------------------------


def opened(app, step):                      # the app as the guide's link opens it, then where a model of yours goes in
    step(("nav button[data-t=model]", "Model tab", "below"))
    step(("label.f:has(#file)", "upload"))


def kind(app, step, k, label):              # Sheet & fit: what you make with
    app.tab("sheet")
    app.p.click(f"#kind button[data-kind={k}]")
    app.idle()
    step((f"#kind button[data-kind={k}]", label))


def sheet(app, step):                       # the machine under it, the material and its thickness
    step(("#kind .f:has(#machine)", "machine", "below"))
    step((".f:has(#material)", "material"))
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


# ---- what a setting changes: the 3D view once for each value, from one camera -------------------------------------


def counts(app, *names):                    # "93 parts · 3 sheet(s)", as the counts under the 3D view read
    rows = dict(app.p.eval_on_selector_all("#stats .stats > div", "ds => ds.map(d => [d.lastChild.textContent.trim(),"
                                           " d.querySelector('b').textContent.replace(/[^\\d.,%× ]/g, '').trim()])"))   # no ✓ or ⚠
    return " · ".join(f"{rows[n]} {n}" for n in names)


def view_middle(app, aspect):               # the model in the 3D view, clear of the bar over it and the tools left of it
    x0, y0, x1, y1 = app.box("#view canvas")
    w = min((y1 - y0 - 142) * aspect, x1 - x0 - 200)
    return (x0 + x1 - w) / 2 + 30, y0 + 112, (x0 + x1 + w) / 2 + 30, y1 - 30


def compare(app, slug, name, param, *values, az=-55, el=18, zoom=1.0, aspect=0.8, show=("parts", "sheet(s)", "errors"), word=None):
    """<slug>-<name>.jpg: the middle of the 3D view once for each value of one setting, side by side, the value in the
    top corner and the counts of that plan in the bottom one. The value it had is set again at the end: the pictures
    after it go on from the plan the guide's link opens. aspect: how wide each view is for 1 high (a wide model)."""
    put = app.tick if isinstance(values[0], bool) else app.set
    was = app.p.eval_on_selector(f"#p_{param}", "s => s.type === 'checkbox' ? s.checked : s.value")
    app.view(az, el, zoom)
    shots = []
    for v in values:
        put(param, v)
        img = caption(app.grab(view_middle(app, aspect)), f"{word or param}: {'on' if v is True else 'off' if v is False else v}")
        tag(ImageDraw.Draw(img), 10, img.height - 44, counts(app, *show))
        shots.append(img)
        for m in app.p.locator("#msgs .msg.err").all_inner_texts()[:2]:    # what the guide's words must say about it
            print(f"  {param}={v}: {' '.join(m.split())[:200]}")
    put(param, was)
    app.p.select_option("#viewmode", "both")
    app.p.wait_for_timeout(500)
    save(f"{slug}-{name}", side_by_side(*shots), OUT)


def sheet_close(app, slug, name, share=(0.0, 0.04, 0.5, 0.6)):   # the top left: the nester starts there
    """<slug>-<name>.jpg: a part of the first cut sheet, close enough to read its labels. The preview is a drawing, so
    it is made 2400 px wide for this one picture and is sharp at that size."""
    app.p.set_viewport_size({"width": 2400, "height": 1700})
    app.p.locator("#sheets svg").first.evaluate(     # a copy over the page: the preview's own panel would clip it
        "e => {const c = e.cloneNode(true); c.id = 'close'; e.parentNode.append(c); c.style.cssText ="
        " 'position:fixed;left:0;top:0;width:2400px;height:auto;max-width:none;z-index:99999;background:#1e1f24'}")
    app.p.wait_for_timeout(600)
    img = Image.open(io.BytesIO(app.p.locator("#close").screenshot())).convert("RGB")
    app.p.evaluate("() => document.querySelector('#close').remove()")
    app.p.set_viewport_size(WINDOW)
    app.p.wait_for_timeout(600)
    a, b, c, e = share
    save(f"{slug}-{name}", img.crop((int(a * img.width), int(b * img.height), int(c * img.width), int(e * img.height))), OUT)


def whole(app, slug, name):                 # the whole window as it is: the settings, the 3D view, the counts, the sheets
    app.p.mouse.move(WINDOW["width"] - 5, 45)
    app.p.wait_for_timeout(400)
    save(f"{slug}-{name}", app.grab((0, 0, WINDOW["width"], WINDOW["height"])), OUT)


# ---- one function for each guide. Every picture of a guide shows ONE model: the example its link opens (Marcel,
# 2026-11-25: the stacked guide showed the horse, then a vase). The steps every job has (upload, size, machine,
# material, thickness, checks, fit test, files) have their pictures once, in start(); a technique's guide shows that
# technique's settings, and what each one changes --------------------------------------------------------------------


def start(app, step):                       # the steps every job has, on the bracket in Interlocked Slices
    opened(app, step)
    step((".f:has([data-rot])", "turn"))
    step((row("model", "size"), "model size"))
    app.tab("technique")
    step(("#modes", "the seven techniques"))
    app.tab("sheet")
    step(("#kind .kinds", "what you make with"))
    sheet(app, step)
    checks(app, step)
    fit_and_cut(app, step)
    build_order(app, step)
    whole(app, "3d-model-to-laser-cut", "plan")


def machines(app, step):                    # Sheet & fit once for each kind of machine, on the same bracket
    for k, label in (("laser", "Laser"), ("router", "Router"), ("printer", "3D printer")):
        kind(app, step, k, label)
    app.p.click("#kind button[data-kind=laser]")
    app.idle()
    step((row("sheet", "compensate"), "compensate kerf"), (row("sheet", "slot_offset"), "slot offset", "below"))
    app.p.click("#kind button[data-kind=router]")
    app.idle()
    step((row("sheet", "relief"), "inside-corner relief"), (row("sheet", "tool_d"), "bit diameter", "below"))
    app.p.click("#kind button[data-kind=laser]")
    app.idle()
    compare(app, "laser-cnc-or-3d-printer", "thickness", "thickness", 3, 6, az=-50, el=30, zoom=1.5, show=("parts",))


def stacked_slices(app, step):              # the horse the link opens: side profiles, 3 mm, on 2 mm dowels
    step(("nav button[data-t=technique]", "Technique tab", "below"))
    app.tab("technique")
    step((row("technique", "axis"), "axis"))
    step((row("technique", "distribution"), "distribution"))
    step((row("technique", "space"), "gap between layers"))
    step((row("technique", "connect"), "connect with"), (row("technique", "dowel_d"), "dowel diameter", "below"))
    checks(app, step)
    sheet_close(app, "stacked-slices", "labels")
    compare(app, "stacked-slices", "axis", "axis", "y", "z", "x")
    compare(app, "stacked-slices", "thickness", "thickness", 3, 6)
    compare(app, "stacked-slices", "gap", "space", 0, 4, word="gap")
    compare(app, "stacked-slices", "rings", "ring_slices", False, True, show=("parts", "dm² material"), word="ring slices")


def interlocking_slices(app, step):         # the torus the link opens, 8 by 8 slices in 3 mm
    step(("nav button[data-t=technique]", "Technique tab", "below"))
    app.tab("technique")
    step((row("technique", "up"), "assembly axis"))
    step((row("technique", "distribution"), "distribution"))
    step((row("technique", "nx"), "slices, 1st family"), (row("technique", "ny"), "slices, 2nd family", "below"))
    checks(app, step)
    build_order(app, step)
    compare(app, "interlocking-slices", "count", "nx", 5, 8, 12, az=-50, el=35, zoom=1.15, aspect=1.15, word="slices, 1st family")
    compare(app, "interlocking-slices", "axis", "up", "z", "x", az=-50, el=35, zoom=1.15, aspect=1.15, word="assembly axis")
    compare(app, "interlocking-slices", "thickness", "thickness", 3, 6, az=-50, el=35, zoom=1.15, aspect=1.15)


def papercraft(app, step):                  # the cow the link opens: low-poly, 1 mm card, glue tabs
    step(("nav button[data-t=technique]", "Technique tab", "below"))
    app.tab("technique")
    step((row("technique", "facet"), "face size"))
    step((row("technique", "joint"), "joint"))
    step((row("technique", "edge_labels"), "seam numbers"))
    checks(app, step)
    fold_to(app, 55)
    step(("label:has(#fold)", "fold"))
    fold_to(app, 100)
    compare(app, "papercraft", "facet", "facet", 0, 45, zoom=1.15, aspect=1.1, word="face size")
    compare(app, "papercraft", "joint", "joint", "tab", "laced", "rib", zoom=1.15, aspect=1.1)
    compare(app, "papercraft", "window", "window", 0, 0.6, zoom=1.15, aspect=1.1, word="windows in faces")


def print_flat_parts(app, step):            # the same cow, printed: its panels print flat and fold up
    kind(app, step, "printer", "3D printer")
    app.p.select_option("#machine", "bambu_x1")   # a named printer sets its bed (256 mm)
    app.idle()
    step(("#kind .f:has(#machine)", "machine", "below"))
    step((".f:has(#material)", "material"))
    app.tab("technique")
    app.set("joint", "click")                                           # a printed joint: no glue
    step((row("technique", "joint"), "joint"))
    step((row("technique", "hinge"), "hinge skin thickness"))
    checks(app, step)
    app.tab("export")
    step(("#dl a.main", "print set"))
    app.p.locator("#sheets").evaluate("e => e.scrollIntoView({block: 'start'})")   # under a long list of warnings
    app.p.wait_for_timeout(400)
    step((app.box("#sheets svg"), "one plate for each 3MF"))
    compare(app, "3d-print-flat-parts", "joint", "joint", "tab", "click", "snap", zoom=1.15, aspect=1.1, show=("parts", "plate(s)", "errors"))


GUIDES = {                                  # each guide's link opens the app on its technique AND its model
    "3d-model-to-laser-cut": ("interlocked/bracket", start),
    "laser-cnc-or-3d-printer": ("interlocked/bracket", machines),
    "stacked-slices": ("stacked/horse_statue", stacked_slices),
    "interlocking-slices": ("interlocked/torus", interlocking_slices),
    "papercraft": ("folded/cow", papercraft),
    "3d-print-flat-parts": ("folded/cow", print_flat_parts),
}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def news_picture(browser):
    """web/static/news/0.4.2-guides.jpg, the CHANGELOG's picture: one setting of the stacked guide as the site shows
    it, its name, what it changes and the horse at three values. docs/ is the site without the app, so it is served as
    it is, with no build."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "docs")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    page = browser.new_page(viewport={"width": 900, "height": 900})
    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/stacked-slices/")
    page.evaluate("() => document.querySelectorAll('img[loading=lazy]').forEach(i => i.loading = 'eager')")
    page.wait_for_function("() => [...document.images].every(i => i.complete)")
    b = page.locator(".setting").first.bounding_box()                    # axis
    clip = {"x": b["x"] - 8, "y": b["y"] - 6, "width": b["width"] + 16, "height": b["height"] + 16}
    save("0.4.2-guides", Image.open(io.BytesIO(page.screenshot(clip=clip, full_page=True))).convert("RGB"))
    page.close()
    srv.shutdown()


def main(only):
    from playwright.sync_api import sync_playwright
    todo = {g: f for g, f in GUIDES.items() if not only or g in only}
    if only and len(todo) < len(only):
        raise SystemExit(f"no such guide: {sorted(set(only) - set(todo))}; there are {sorted(GUIDES)}")
    with serve_app() as url, sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"])
        for slug, (link, f) in todo.items():
            page = browser.new_page(viewport=WINDOW)    # a new tab: no session, so the app opens as a reader's does
            page.goto(f"{url}/#{link}")
            app = App(page)                             # idle() alone passes before the first slice has started
            page.wait_for_function("() => /^(ready|error)/.test(document.getElementById('status')?.textContent)", timeout=300_000)
            app.idle()
            f(app, stepper(app, slug))
            page.close()
        if not only:                                    # the CHANGELOG's picture reads a page: after all of them are made
            news_picture(browser)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
