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
        self.p.select_option("#look", "group")             # by family: picking a material sets its look, and keeps it
        self.p.evaluate("n => window.__t.openExample(n)", name)   # what the library's example cards call
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

    def tick(self, name, on):               # a tick box, the same way
        self.p.evaluate("([n, on]) => {const s = document.querySelector('#p_' + n); s.checked = on;"
                        " for (const e of ['input', 'change']) s.dispatchEvent(new Event(e, {bubbles: true}))}",
                        [name, on])
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


# the back of the lion: the largest joined area of faces that face backward (normal y over 0.3), behind the middle.
# A seam round it, one click on it and `connected` take off the back alone; the face and the whole front mane stay
LION_BACK = """() => (() => { const F = window.__t.plan().faces3d, V = F.v, sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const ny = F.f.map(([a, b, c]) => { const u = sub(V[b], V[a]), w = sub(V[c], V[a]), n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]; return n[1] / Math.hypot(...n) });
  const my = F.f.map(f => (V[f[0]][1] + V[f[1]][1] + V[f[2]][1]) / 3), nb = F.f.map(() => []); F.adj.forEach(([a, b]) => { nb[a].push(b); nb[b].push(a) });
  const ok = F.f.map((_, i) => ny[i] > 0.3 && my[i] > 0), seen = new Set(); let best = [];
  for (let i = 0; i < F.f.length; i++) { if (!ok[i] || seen.has(i)) continue; const part = [i]; seen.add(i);
    for (let k = 0; k < part.length; k++) for (const j of nb[part[k]]) if (ok[j] && !seen.has(j)) { seen.add(j); part.push(j) }
    if (part.length > best.length) best = part }
  const back = new Set(best);
  return {back: [...back], loop: F.adj.filter(([a, b]) => back.has(a) !== back.has(b)).map(([a, b]) => F.f[a].filter(i => F.f[b].includes(i)).map(i => V[i]))} })()"""


V3D = "#v3d"                                # the 3D view alone, its bar and its tool column: not the warnings under it


def lion(app):                               # the lion opens in Folded Panels; its first slice takes about a minute
    app.example("lion_head")
    app.p.wait_for_function("window.__t.plan()?.faces3d && window.__t.idle()", timeout=300_000)
    app.tab("technique")                     # the Model tab draws the rotate rings round the model


def look(app, az):                           # the lion from `az`, filling the view
    app.p.evaluate(f"() => {{ document.getElementById('fit').click(); const d = __t.camera.position.distanceTo(__t.target()); __t.cam({az}, 12, d * 0.88); __t.frame() }}")
    app.p.wait_for_timeout(600)


def n040_seams(app):
    lion(app)
    app.p.evaluate(f"() => __t.applyFix({{seams: ({LION_BACK})().loop}})")
    app.idle()
    app.p.click('#tools [data-tool="seam"]')
    look(app, 20)                            # from the side: the seam loop runs round the back, behind the mane
    app.shot("0.4.0-seams", V3D, [('#tools [data-tool="seam"]', "")])
    app.p.keyboard.press("Escape")
    app.p.evaluate("() => __t.applyFix({seams: []})")
    app.idle()


def n040_mask(app):
    lion(app)
    app.p.evaluate(f"() => __t.applyFix({{seams: ({LION_BACK})().loop}})")
    app.idle()
    app.p.click('#tools [data-tool="face"]')
    look(app, 60)                            # from behind: the back of the head, which goes
    at = app.p.evaluate(f"""() => {{ const back = new Set(({LION_BACK})().back), r = __t.canvas().getBoundingClientRect(), f = __t.faces(); let best = null;
      for (let x = r.left + 80; x < r.right - 80; x += 10) for (let y = r.top + 100; y < r.bottom - 120; y += 10) {{ const u = f.under(x, y);
        if (u?.face === undefined || !back.has(u.face)) continue; const d = Math.hypot(x - r.left - r.width / 2, y - r.top - r.height / 2); if (!best || d < best.d) best = {{x, y, d}} }}
      return best }}""")
    app.p.mouse.click(at["x"], at["y"])
    app.p.click('[data-faces="connected"]')
    app.p.click('[data-faces="remove"]')
    app.idle()
    look(app, -60)                           # the mask from the front, the removed back as dashed outlines behind it
    app.shot("0.4.0-mask", V3D, [('#tools [data-tool="face"]', ""), ("#facebar", "select faces")])
    app.p.evaluate("() => document.querySelector('[data-faces=back]').click()")
    app.p.keyboard.press("Escape")
    app.p.evaluate("() => __t.applyFix({seams: []})")
    app.idle()


def n040_rings(app):
    app.example("head_igea", "stacked")
    app.set("distribution", "count")
    app.set("count", 10)
    app.p.check("#p_ring_slices")              # a tick: App.set types a value, a checkbox needs check()
    app.idle()
    app.set("ring_wall", 8)
    app.shot("0.4.0-rings", (0, 40, 1574, 860), [("section[data-tab=technique] .f[data-p=ring_slices]", "ring slices")])
    app.p.uncheck("#p_ring_slices")
    app.idle()


def n040_bands(app):
    app.example("sphere", "bands")             # the sphere at the defaults (4 x 4): no error, every piece has a way in
    app.view(30, 20, 0.9)
    app.shot("0.4.0-bands", "#v3d", [])


def n040_max_length(app):
    app.example("head_igea", "stacked")
    app.set("distribution", "count")
    app.set("count", 10)
    app.p.check("#p_ring_slices")
    app.idle()
    app.set("max_length", 150)
    app.p.select_option("#viewmode", "only2d")
    app.p.wait_for_timeout(800)
    x0, y0, x1, y1 = app.box("#sheets")              # the sheet only, where the pieces lie (its top half is empty)
    app.shot("0.4.0-max-length", (x0, y0 + 0.5 * (y1 - y0), x1, y1), [])
    app.p.select_option("#viewmode", "both")
    app.set("max_length", 0)
    app.p.uncheck("#p_ring_slices")
    app.idle()


# the horse example's curve and branches in 0.3.3, before its head became a branch of its own
HORSE_033 = {"curve": [[-119, 11], [-89, 18], [-59, 23], [-14, 10], [16, 13], [50, 22], [76, 47], [91, 76], [106, 89], [136, 83]],
             "branches": [[[-2, 46.6, -33], [-5.2, 64.5, -128]], [[40.5, 36.8, -33], [49, 25.8, -125]],
                          [[-2.8, -100.1, -11], [-5, -134.2, -125]], [[52, -83.1, -15], [54.9, -101, -125]]]}


def n040_horse_head(app):
    """The horse's head in 0.3.3 (one slab) beside the example now (its own spine and ribs), parts only, from its
    right front, where the head shows its profile."""
    halves = []
    for label, old in (("0.3.3: one slab", True), ("0.4.0: spine and ribs", False)):
        app.example("horse")
        if old:
            app.p.evaluate("f => window.__t.applyFix(f)", HORSE_033)
            app.idle()
        app.view(60, 15)
        app.p.uncheck("#ghost")
        app.p.evaluate("() => { const t = window.__t; t.target().set(-25, 120, 80); t.cam(60, 15, 300);"
                       " for (const g of [t.guides(), t.axes()]) for (const o of g) o.visible = false;"
                       " for (const m of t.parts()) if (m.userData.group === 'B') m.visible = false; t.frame() }")
        app.p.wait_for_timeout(500)
        x0, y0, x1, y1 = app.box("#v3d")
        w, h = x1 - x0, y1 - y0
        halves.append(caption(app.grab((x0 + 0.24 * w, y0 + 0.2 * h, x1 - 0.18 * w, y1 - 0.12 * h)), label))
        app.p.check("#ghost")
    save("0.4.0-horse-head", side_by_side(*halves))


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


def n040_spacing(app):
    app.example("vase", "stacked")          # the vase opens with vary the spacing on
    app.level("basic")
    row, graph = (f"section[data-tab=technique] .f[data-p={p}]" for p in ("spacing_vary", "spacing_curve"))
    app.p.locator(graph).evaluate("e => e.scrollIntoView({block: 'center'})")   # the section is below the fold
    app.p.wait_for_timeout(300)
    app.shot("0.4.0-spacing", (0, app.box(row)[1] - 60, 470, app.box(graph)[3]), [(row, "vary the spacing")])


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
    app.example("vase", "stacked")          # two dowel points 3 mm apart: no room for both, so 8 are left out, each ringed
    app.p.evaluate("d => window.__t.applyFix({dowels: d})", [[0, 0], [3, 0]])
    app.idle()
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


def crossed_side(app, example, sink, settings):   # a side relief, crossed: one Y spine goes in first, X ribs onto it
    app.example(example, "plaque")
    for k, v in (("back", "-y"), ("sink", sink), ("layout", "crossed"), ("ny", 1), ("first", "y"), *settings):
        app.set(k, v)


def plaque_back(app):                         # the plaque settings as the example opens them, for the next picture
    for k, v in (("first", "x"), ("first_height", 100), ("layout", "parallel"), ("back", "-z"), ("sink", 0)):
        app.set(k, v)


def n040_first(app):
    # the low-poly cow: at ny 1 its rail misses the lowered head (5 ribs touch nothing); at ny 2 it runs through the
    # head, and only the last rib, at the tail, has an error
    crossed_side(app, "cow", 50, (("nx", 20), ("first_height", 35), ("ny", 2)))
    app.view(65, 30, 0.75)
    app.p.evaluate("() => {const s = document.querySelector('#steps'); s.value = 9;"   # the plate, the rail, 7 ribs
                   " s.dispatchEvent(new Event('input'))}")
    app.p.wait_for_timeout(1200)
    app.shot("0.4.0-first", VIEW, [("label:has(#steps)", "the rail goes in first")])
    app.p.evaluate("() => {const s = document.querySelector('#steps'); s.value = s.max; s.dispatchEvent(new Event('input'))}")
    plaque_back(app)


def pick_material(app, name):                # the Sheet tab's picker, from any tab: its own change handler runs
    app.p.evaluate("n => {const s = document.querySelector('#material'); s.value = n; s.dispatchEvent(new Event('change'))}", name)
    app.idle()


def n040_material(app):
    sheet, stock = app.p.input_value("#p_thickness"), app.p.input_value("#material")
    crossed_side(app, "egg", 60, (("nx", 26),))                       # 26 ribs: 3.9 mm fingers
    pick_material(app, "acrylic")                                     # picking a material picks its stock thickness
    app.set("thickness", 3)                                           # plywood takes 3.9 mm fingers, acrylic wants 4.5
    app.view(65, 20, 0.9, only3d=False)
    x0, y0, x1, _ = app.box(VIEW)
    row = "#msgs :text('acrylic can take')"
    app.shot("0.4.0-material", (x0, y0, x1, app.box(row)[3]), [(row, "")])
    plaque_back(app)
    pick_material(app, stock)
    app.set("thickness", sheet)
    assert (app.p.input_value("#material"), app.p.input_value("#p_thickness")) == (stock, sheet)


def n040_clean_tops(app):
    app.example("egg", "stacked")
    app.set("distribution", "count")
    app.set("count", 6)
    app.tick("orient_mark", True)                     # the arrows show what used to be engraved on top
    app.p.select_option("#viewmode", "only2d")
    app.p.wait_for_timeout(800)
    top = '#sheets path[data-label="Z-6"]'            # the egg's top layer
    shots = []
    for on, name in ((False, "before: on the top layer"), (True, "now: the top layer is clean")):
        app.tick("hide_marks", on)
        x0, y0, x1, y1 = app.box(top)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        shots.append(caption(app.grab((cx - 220, cy - 190, cx + 220, cy + 150), [(top, "")]), name))
    save("0.4.0-clean-tops", side_by_side(*shots))
    app.tick("hide_marks", True)
    app.tick("orient_mark", False)
    app.p.select_option("#viewmode", "both")


# the top end of every dowel on the screen, where the view's own ray finds no higher layer over it: an open hole
OPEN = """() => {const n = l => +String(l).split('-')[1], rods = window.__t.plan().rods, last = Math.max(...rods.map(r => n(r[7])));
  return rods.filter(r => n(r[7]) < last).map(([a, b, d, , , , , top]) => {       // the top layer's holes always show
    const [x, y] = window.__t.screen([a[0], a[1], b[2]]), hit = window.__t.hitAt(x, y);
    return !hit || hit !== 'gizmo' && n(hit) <= n(top) ? [x, y] : null}).filter(Boolean)}"""       # no layer hit = the rod's own end, seen in its hole


def n040_hide_dowels(app):
    sheet = app.p.input_value("#p_thickness")                    # the sheet as it was, for the pictures after this one
    app.example("vase", "stacked")
    app.tick("spacing_vary", False)                                # layers that touch: a gap shows every hole anyway
    app.set("distribution", "distance")
    app.set("placement", "random")
    app.set("thickness", 6)                                        # steps wider than a hole, so an open hole is seen whole
    shots = []
    for on in (False, True):
        app.tick("hide_dowels", on)
        app.view(30, 58, 0.85)
        holes = app.p.evaluate(OPEN)
        marks = [((x - 9, y - 9, x + 9, y + 9), "open hole" if i == 0 else "") for i, (x, y) in enumerate(sorted(holes, key=lambda q: q[1]))]
        x0, y0, x1, y1 = app.box("#view canvas")
        cx = (x0 + x1) / 2
        img = app.grab((cx - 330, y0 + 40, cx + 330, y1 - 40), marks)
        shots.append(caption(img, f"hide dowels on: {len(holes) or 'no'} open holes on the steps" if on else f"before: {len(holes)} open holes on the steps"))
    save("0.4.0-hide-dowels", side_by_side(*shots))
    app.tick("hide_dowels", False)
    app.set("thickness", sheet)
    app.p.select_option("#viewmode", "both")


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


# ---- 0.4.0, last: it leaves four saved projects in the page's library ----------------------------------------------


def n040_library(app):
    save_it = "window.__t.lib.saveCurrent(() => Promise.resolve('keep'))"
    for ex, name, bumps in (("horse", "horse, 3 mm ply", ["#pminor"]), ("vase", "vase for Anna", []),
                            ("bunny", "bunny plaque", []), ("fold_lamp", "desk lamp", ["#pminor", "#pmajor"])):
        app.example(ex)
        app.p.fill("#pname", name)
        app.idle()
        app.p.evaluate(save_it)
        for b in bumps:                     # a new revision from the version menu: v1.1, then v2.0
            app.p.click(f"details.menu:has({b}) > summary")
            app.p.click(b)
            app.idle()
            app.p.evaluate(save_it)
    app.p.click("#popen")
    app.p.wait_for_function("() => document.querySelector('#libyours').dataset.listed")
    app.p.evaluate("""async () => {const d = await (await navigator.storage.getDirectory())
                          .getDirectoryHandle('lib', {create: true}); window.showDirectoryPicker = async () => d}""")
    app.p.click("#liblink")                 # the page's own folder stands in for the one a person picks
    app.p.wait_for_function("() => /kept in the folder/.test(document.querySelector('#libwhere').innerText)")
    app.p.evaluate("document.querySelector('#libwhere .note')?.remove()")   # the link's result, shown once
    lamp = '#libyours .card[data-name="desk lamp"]'
    app.p.click(f"{lamp} .more")
    app.p.wait_for_function("() => [...document.querySelectorAll('#library img')].every(i => i.complete)")
    app.p.evaluate("document.querySelector('#library').scrollTop = 0")
    app.p.wait_for_timeout(300)
    x0, y0, _, _ = app.box("#library")
    x1 = app.box("#libyours .card >> nth=3")[2]
    revs = f"{lamp} .revs"
    _, ry0, rx1, ry1 = app.box(revs)
    img = app.grab((x0, y0, x1, ry1), [(revs, "")])
    ox, oy = max(0, x0 - 12), max(0, y0 - 12)                # grab's crop starts 12 px out
    tag(ImageDraw.Draw(img), rx1 - ox + 30, (ry0 + ry1) / 2 - oy - 16, "every revision kept: open, export, delete")
    save("0.4.0-library", img)                # the label beside the ring: above it, it would hide the card's name
    app.p.click("#libclose")


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
