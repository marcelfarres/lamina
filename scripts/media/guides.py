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

from news import ROOT, App, save, tag
from serve import serve_app                 # news.py puts tests/ on the path

OUT = ROOT / "docs" / "media" / "guides"
WINDOW = {"width": 1100, "height": 760}     # 900 px wide in the JPG: the labels on the page still read


def row(tab, p):                            # a setting's row, by its name in the technique's schema
    return f"section[data-tab={tab}] .f[data-p={p}]"


def stepper(app, slug):
    """step((selector or box, label), ...) saves <slug>-1.jpg, -2, ... in the order it is called. A ringed row in the
    settings column is scrolled to its middle first. A third item "below" puts the label under the ring: above it, it
    would hide the control of the step before."""
    n = 0

    def step(*marks):
        nonlocal n
        n += 1
        for m, *_ in marks:
            if isinstance(m, str):
                app.p.locator(m).first.evaluate("e => e.closest('#tabs') && e.scrollIntoView({block: 'center'})")
        app.p.mouse.move(WINDOW["width"] - 5, 45)   # off every control: left on the last click, it opened that row's help
        app.p.wait_for_timeout(400)
        img = app.grab((0, 0, WINDOW["width"], WINDOW["height"]), [(m, "" if below else label) for m, label, *below in marks])
        for m, label, *below in marks:      # the crop starts at the window's corner: page and picture share their x, y
            if below:
                a, _, _, e = app.box(m) if isinstance(m, str) else m
                tag(ImageDraw.Draw(img), a - 6, e + 12, label)
        save(f"{slug}-{n}", img, OUT)
    return step


def upload(app, name):                      # a reader's own model: an example's file, through the file box
    app.p.set_input_files("#file", str(ROOT / "examples" / f"{name}.stl"))
    app.idle()


def stacked_slices(app, step):                 # the tabs left to right, as a new reader meets them
    step(("nav button[data-t=model]", "Model tab", "below"))            # as the link opens it: the bunny, stacked
    step(("label.f:has(#file)", "upload"))
    upload(app, "horse_statue")                                         # the horse of the guide's video
    app.set("size_2", 260)
    step((row("model", "size"), "model size"))
    app.tab("technique")
    app.set("axis", "y")                                                # side profiles
    step((row("technique", "axis"), "axis"))
    step((row("technique", "distribution"), "distribution"))
    step((row("technique", "connect"), "connect with"))
    app.set("dowel_d", 2)          # the video's 2 mm rods; the bunny's 4 mm left one piece of the horse unjoined
    step((row("technique", "dowel_d"), "dowel diameter", "below"))
    app.tab("sheet")
    app.p.click("#kind button[data-kind=laser]")
    app.idle()
    step(("#kind button[data-kind=laser]", "Laser"))
    step(("#kind .f:has(#machine)", "machine", "below"))
    step((".f:has(#material)", "material"))
    app.set("thickness", 3)
    step((row("sheet", "thickness"), "thickness"))
    step(("#stats", "errors and warnings"))
    app.tab("export")
    step(("#dlfit .r", "fit test"))
    app.tab("sheet")                        # the fit test's answer goes here, before the sheets are cut
    step((row("sheet", "slot_offset"), "slot offset"))
    app.tab("export")
    step(("#dl a.main", "the sheets"))


GUIDES = {"stacked-slices": ("stacked", stacked_slices)}   # each guide's link opens the app on its technique


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
