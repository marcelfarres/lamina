"""Take the pictures of CHANGELOG.md from the running app, into web/static/news/<version>-<slug>.jpg.

    uv run python scripts/media/news.py              every picture
    uv run python scripts/media/news.py 0.4.0-lamp   only these

One function for each picture: n040_lamp_example makes 0.4.0-lamp-example.jpg. It opens an example, sets what the
entry is about, crops to that area and rings the new thing with a short label (never colour alone: a thick ring with
a dark edge, and words). The file is 900 px wide at most and under 150 KB, which tools/notes_check.py checks. The
what-is-new dialog shows these files offline: web/static ships in the wheel and in the browser build.
"""
import io
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "static" / "news"
sys.path.insert(0, str(ROOT / "tests"))     # run as a script, only scripts/media is on the path
from serve import serve_app  # noqa: E402

RING, EDGE = "#E69F00", "#000000"           # Okabe-Ito orange, with a black edge so it reads on any background
W, KB = 900, 150
FONT = ImageFont.truetype("arialbd.ttf", 22) if sys.platform == "win32" else ImageFont.load_default(22)
VIEW = "#view"                              # the 3D view with its bar and its tool column


class App:
    def __init__(self, page):
        self.p = page

    def idle(self):
        self.p.wait_for_function("window.__t && window.__t.idle()", timeout=180_000)
        self.p.wait_for_timeout(400)

    def example(self, name, mode=None):     # every picture starts here: the normal view, then the example
        self.p.select_option("#viewmode", "both")
        self.p.evaluate("e => {const s = document.querySelector('#example'); s.value = e;"
                        " s.dispatchEvent(new Event('change'))}", name)
        self.idle()
        if mode:
            self.mode(mode)

    def mode(self, m):
        self.tab("technique")
        self.p.click(f"#modes button[data-m={m}]")
        self.idle()

    def tab(self, t):
        self.p.click(f"nav button[data-t={t}]")
        self.p.wait_for_timeout(300)

    def level(self, lv):
        self.p.click(f"#level button[data-level={lv}]")
        self.p.wait_for_timeout(300)

    def set(self, name, v):                 # a setting, typed in as a user does
        self.p.evaluate("([n, v]) => {const s = document.querySelector('#p_' + n); s.value = v;"
                        " for (const e of ['input', 'change']) s.dispatchEvent(new Event(e, {bubbles: true}))}",
                        [name, str(v)])
        self.idle()

    def view(self, az, el, zoom=1.0, only3d=True):
        """The 3D view alone (or beside the sheets), from the Technique tab: the Model tab rings the model with the
        handles that turn it."""
        self.tab("technique")
        self.p.select_option("#viewmode", "only3d" if only3d else "both")
        self.p.wait_for_timeout(600)
        self.p.click("#fit")
        self.p.wait_for_timeout(300)
        self.p.evaluate("([az, el, z]) => window.__t.cam(az, el, window.__t.camera.position.length() * z)",
                        [az, el, zoom])
        self.p.wait_for_timeout(600)

    def box(self, sel):
        b = self.p.locator(sel).first.bounding_box()
        if not b:
            raise SystemExit(f"not on the screen: {sel}")
        return b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]

    def grab(self, area, marks=()):
        """area: a selector or a box (x0, y0, x1, y1). marks: (selector or box, label) to ring."""
        img = Image.open(io.BytesIO(self.p.screenshot())).convert("RGB")
        box = lambda a: self.box(a) if isinstance(a, str) else a
        x0, y0, x1, y1 = box(area)
        pad = 12
        x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)
        d = ImageDraw.Draw(img)
        for m, label in marks:
            a, b, c, e = box(m)
            r = (a - 6, b - 6, c + 6, e + 6)
            d.rounded_rectangle(r, 10, outline=EDGE, width=8)
            d.rounded_rectangle(r, 10, outline=RING, width=4)
            if label:                       # over the ring, or under it when there is no room above
                tw = d.textlength(label, font=FONT)
                lx = min(max(r[0], x0 + 4), x1 - tw - 20)
                ly = r[1] - 38 if r[1] - 38 > y0 else r[3] + 6
                tag(d, lx, ly, label)
        return img.crop((int(x0), int(y0), int(x1), int(y1)))

    def shot(self, name, area, marks=()):
        save(name, self.grab(area, marks))


def tag(d, x, y, text):                     # a label: dark words on the ring's colour, with a dark edge
    tw = d.textlength(text, font=FONT)
    d.rounded_rectangle((x, y, x + tw + 16, y + 32), 6, fill=RING, outline=EDGE, width=2)
    d.text((x + 8, y + 3), text, fill=EDGE, font=FONT)


def caption(img, text):                     # a name in the top left corner
    tag(ImageDraw.Draw(img), 10, 10, text)
    return img


def side_by_side(*imgs):
    out = Image.new("RGB", (sum(i.width for i in imgs) + 8 * (len(imgs) - 1), max(i.height for i in imgs)), "#141517")
    x = 0
    for i in imgs:
        out.paste(i, (x, 0))
        x += i.width + 8
    return out


def save(name, img):
    if img.width > W:
        img = img.resize((W, round(img.height * W / img.width)), Image.LANCZOS)
    OUT.mkdir(exist_ok=True)
    for q in (85, 78, 70, 62, 55):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() < KB * 1024:
            break
    (OUT / f"{name}.jpg").write_bytes(buf.getvalue())
    print(f"{name}.jpg  {img.width}x{img.height}  {buf.tell() // 1024} KB")


# ---- 0.4.0 -----------------------------------------------------------------------------------------------------


def n040_lamp(app):
    app.example("fold_lamp")
    app.view(30, 12, 1.7)
    app.p.check("#lamp")
    app.p.wait_for_timeout(1500)
    app.shot("0.4.0-lamp", VIEW, [("label:has(#lamp)", "lamp")])
    app.p.uncheck("#lamp")


def n040_examples(app):
    halves = []
    for ex, open_, zoom in (("fold_box", 6, 1.7), ("fold_lantern", 0, 1.15)):   # closed, the box reads as a block
        app.example(ex)
        app.view(35, 22, zoom)
        app.p.evaluate("n => {const s = document.querySelector('#steps'); s.value = s.max - n;"
                       " s.dispatchEvent(new Event('input'))}", open_)
        app.p.wait_for_timeout(1200)
        halves.append(caption(app.grab("#v3d"), ex))
    save("0.4.0-examples", side_by_side(*halves))


def n040_settings(app):
    app.example("vase", "stacked")
    app.level("all")
    app.p.fill("#find", "")
    app.shot("0.4.0-settings", (0, 40, 470, 760), [("#find", "find a setting")])


def n040_basic(app):
    app.example("vase", "stacked")
    app.level("basic")
    app.shot("0.4.0-basic", (0, 40, 470, 620), [("#level", "basic / all")])


def n040_help(app):
    app.example("vase", "stacked")
    app.level("basic")
    row = "section[data-tab=technique] .f[data-p=count]"
    app.p.click(f"{row} .k")
    app.p.wait_for_timeout(300)
    app.shot("0.4.0-help", (0, 40, 470, 600), [(row, "click the name")])
    app.p.click(f"{row} .k")


def n040_spacing(app):
    app.example("vase", "stacked")          # the vase opens with vary the spacing on
    app.level("basic")
    app.shot("0.4.0-spacing", (0, 40, 470, 880),
             [("section[data-tab=technique] .f[data-p=spacing_vary]", "vary the spacing")])


def n040_tools(app):
    app.example("vase", "stacked")
    app.view(30, 15, 1.1)
    app.shot("0.4.0-tools", VIEW, [("#tools", "tools")])


def n040_export(app):
    app.example("vase", "stacked")
    app.tab("export")
    app.shot("0.4.0-export", (0, 40, 470, 700), [("#dl", "downloads first")])


def n040_cards(app):
    app.example("vase", "stacked")
    app.tab("technique")
    menu = "details.menu:has(#helpbtn) > summary"
    app.p.click(menu)
    app.p.wait_for_timeout(300)
    app.shot("0.4.0-cards", (0, 0, 1000, 420), [("#modes", "technique cards"), (menu, "help menu")])
    app.p.click(menu)


def n040_warnings(app):
    app.example("vase", "stacked")          # the vase opens with 4 dowels that find no room: one warning, 4 rings
    app.view(25, 20, 0.75, only3d=False)
    x0, y0, x1, _ = app.box(VIEW)
    app.shot("0.4.0-warnings", (x0, y0, x1, app.box("#msgs")[3]), [("#msgs", "a warning, counted")])


def n040_fold(app):
    app.example("fold_lamp")
    app.view(30, 20, 1.3)
    app.p.evaluate("() => {const s = document.querySelector('#steps'); s.value = s.max - 10;"
                   " s.dispatchEvent(new Event('input'))}")
    app.p.wait_for_timeout(1200)
    app.shot("0.4.0-fold", VIEW, [("label:has(#steps)", "steps")])


def n040_lamp_example(app):
    app.example("fold_lamp")
    app.view(30, 20, 1.2)
    app.shot("0.4.0-lamp-example", VIEW, [])


# ---- 0.3.3 -----------------------------------------------------------------------------------------------------


def fold_to(app, share):                    # the fold slider runs 0 (flat) to 1 (folded)
    app.p.evaluate("v => {const s = document.querySelector('#fold'); s.value = v;"
                   " s.dispatchEvent(new Event('input'))}", share / 100)
    app.p.wait_for_timeout(1200)


def middle(app, sel, aspect=0.8):           # the middle of an area, aspect wide for each 1 high
    x0, y0, x1, y1 = app.box(sel)
    w = (y1 - y0) * aspect
    return (x0 + x1 - w) / 2, y0 + 50, (x0 + x1 + w) / 2, y1 - 30


def n033_plaque(app):                       # in front of the plate: from behind, a plaque is a board with teeth
    app.example("bonsai")
    app.view(50, 10, 1.0)
    app.shot("0.3.3-plaque", VIEW, [])


def n033_plaque_looks(app):
    looks = []
    for ex, az, el in (("bonsai", 50, 10), ("droplet", 30, 40), ("figure", 50, 10)):
        app.example(ex)
        app.view(az, el, 0.95)
        looks.append(caption(app.grab(middle(app, "#v3d")), ex))
    save("0.3.3-plaque-looks", side_by_side(*looks))


def n033_fold(app):
    app.example("fold_lamp")
    app.view(30, 20, 1.3)
    fold_to(app, 55)
    app.shot("0.3.3-fold", VIEW, [("label:has(#fold)", "fold")])
    fold_to(app, 100)


def n033_windows(app):
    app.example("fold_lamp")
    app.view(30, 12, 1.2)
    app.shot("0.3.3-windows", VIEW, [])


def n033_step(app):
    app.example("vase", "stacked")
    app.tab("export")
    app.p.locator("#dl").scroll_into_view_if_needed()
    app.shot("0.3.3-step", "#dl", [("#dl >> text=STEP", "assembled STEP")])


def picture_name(f):                        # n040_lamp_example -> 0.4.0-lamp-example
    v, slug = f.__name__.split("_", 1)
    return f"{v[1]}.{v[2]}.{v[3]}-{slug.replace('_', '-')}"


NAMES = {picture_name(f): f for n, f in list(globals().items()) if n[:1] == "n" and n[1:4].isdigit()}


def main(only):
    from playwright.sync_api import sync_playwright
    todo = {n: f for n, f in NAMES.items() if not only or n in only}
    if only and len(todo) < len(only):
        raise SystemExit(f"no such picture: {sorted(set(only) - set(todo))}; there are {sorted(NAMES)}")
    with serve_app() as url, sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1574, "height": 907})
        page.goto(url)
        app = App(page)
        app.idle()
        for f in todo.values():
            f(app)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
