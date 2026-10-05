"""The app in a real browser against a real server: the workflows people actually run, and every parameter of every
technique touched at least once, so a field that stops driving the slicer — or a button that throws — fails here
instead of in someone's inbox.

    uv run --with playwright playwright install chromium
    LAMINA_UI=1 uv run --with playwright pytest tests/test_ui.py -q

It drives the page the way a person does (real input events, the debounce, the real /api/slice), and fails on any
uncaught JavaScript error, on a status line that never settles, and on a parameter whose value does not reach the
plan the server built.
"""
import json
import math
import os
import pathlib
import re
import socket
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not os.environ.get("LAMINA_UI"), reason="set LAMINA_UI=1 (needs playwright's chromium)")

# list-shaped parameters are placed from the 3D view (points, axes, per-slice maps), not typed into a box: the sweep
# sets everything with a box of its own, and test_the_tables_take_a_row exercises the rest through their + buttons
TYPED = ("number", "int", "bool", "choice", "text", "vec2", "vec3")


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:                       # a free port, so a running dev server is not in the way
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "web.app:app", "--port", str(port)], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        import urllib.request
        for _ in range(120):
            try:
                urllib.request.urlopen(url + "/api/modes", timeout=1); break   # noqa: S310 — the server this test just started
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("the server never came up")
        yield url
    finally:
        proc.terminate(); proc.wait(timeout=20)


@pytest.fixture(scope="module")
def page(server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1500, "height": 950})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.goto(server + "/")
        settle(pg)
        yield pg
        browser.close()


@pytest.fixture(autouse=True)
def fresh(page):
    """Every test starts from the defaults of every tab. One page for the whole module is what makes this suite fast,
    and this is the price: a technique or a remeshed model left behind would slow down or break the next test.
    The model too: the egg, unless the test before left another one (an upload of the cube made the next test's
    shift-drag miss), and not the page's default, which can change and be slower to re-slice."""
    if page.evaluate("() => window.__t.job()") != "ex_egg":
        page.click('nav button[data-t="model"]')
        page.select_option("#example", "egg")
    for tab in ("model", "technique", "sheet", "checks"):
        page.click(f'nav button[data-t="{tab}"]')
        page.click(f'button.reset[data-reset="{tab}"]')
        page.wait_for_timeout(200)
    settle(page)
    yield


def settle(page, timeout=180_000):
    """Wait for the status line to stand still: a change debounces, so it has to be ready twice over."""
    for _ in range(2):
        page.wait_for_function("() => /^(ready|error)/.test(document.getElementById('status')?.textContent)", timeout=timeout)
        page.wait_for_timeout(600)
    assert not page.errors, page.errors
    return page.text_content("#status")


def plan(page):
    return page.evaluate("() => window.__t.plan()")


def set_fields(page, values):
    """Type into the app's own boxes and let its handlers do the rest — the path a person's keystroke takes."""
    page.evaluate("""vals => {
        for (const [id, v] of vals) {
            const el = document.getElementById(id);
            if (!el) continue;
            if (el.type === 'checkbox') { el.checked = v; el.dispatchEvent(new Event('input', {bubbles: true})); }
            else { el.value = v; el.dispatchEvent(new Event('input', {bubbles: true})); }
        }
    }""", values)


def sweep_values(schema):
    """A value per parameter, one step off its default: different enough that a box which drives nothing shows up,
    close enough that no slice takes a minute. Returns [(input id, value), …] and {name: expected in the plan}."""
    ids, want = [], {}
    for p in schema:
        if p["type"] not in TYPED or p["group"] == "hidden" or p["name"] == "units":
            continue                                 # units changes how every other box reads: its own test below
        name, d = p["name"], p["default"]
        if p["type"] == "bool":
            v = not d
        elif p["type"] == "choice":
            v = next((c for c in p["choices"] if c != d), d)
        elif p["type"] == "text":
            v = "ui test"
        elif name == "size":
            v = [200.0, 150.0, 180.0]        # a step off zero would be a model one millimetre tall, and nothing to cut
        elif name == "shrinkwrap":
            v = 4.0                          # a step off zero is the finest grid the model allows: a million faces,
                                             # and every slice after it crawls. 4 mm voxels remesh in a moment
        elif p["type"] in ("vec2", "vec3"):
            step = p["step"] or 1
            v = [min(x + step, p["max"]) if p["max"] is not None else x + step for x in d]
        else:
            step = p["step"] or (1 if p["type"] == "int" else 0.5)
            v = d + step
            if p["max"] is not None:
                v = min(v, p["max"])
            if p["min"] is not None:
                v = max(v, p["min"])
            v = int(v) if p["type"] == "int" else round(v, 4)
        want[name] = v
        if p["type"] in ("vec2", "vec3"):
            ids += [(f"p_{name}_{i}", x) for i, x in enumerate(v)]
        else:
            ids.append((f"p_{name}", v))
    # a new `size` is the new 100 %, so the form resets `scale` to 1 when you type one: set the scale after it
    ids.sort(key=lambda kv: kv[0] == "p_scale")
    return ids, want


@pytest.mark.timeout(1800)
def test_every_parameter_of_every_technique_reaches_the_slicer(page, server):
    """Each technique in turn: fill every box it offers with a value one step off the default, slice once, and check
    the server's plan came back holding exactly those values. A field that stops being wired up — renamed, dropped
    from the form, read from the wrong place — cannot pass this."""
    import urllib.request
    modes = json.loads(urllib.request.urlopen(server + "/api/modes").read())   # noqa: S310 — the fixture's own server
    assert modes, "no techniques"
    for m in modes:
        page.click('nav button[data-t="technique"]')
        page.click(f'#modes button[data-m="{m["name"]}"]')
        settle(page)
        ids, want = sweep_values(m["common"] + m["params"])
        assert len(want) > 20, (m["name"], len(want))          # the sweep must really be sweeping
        set_fields(page, ids)
        settle(page)
        got = plan(page)["params"]
        wrong = {k: (v, got.get(k)) for k, v in want.items()
                 if not (isinstance(v, (int, float)) and not isinstance(v, bool) and abs(float(got.get(k, 1e9)) - v) < 1e-3
                         or isinstance(v, list) and all(abs(a - b) < 1e-3 for a, b in zip(v, got.get(k, [])))
                         or got.get(k) == v)}
        assert not wrong, (m["name"], wrong)
        page.click('nav button[data-t="model"]')
        page.click("#origsize")                                # back to a plain model for the next technique
        settle(page)


@pytest.mark.timeout(1200)
@pytest.mark.parametrize("name,value", [("shrinkwrap", 2), ("hollow", 6), ("thicken", 2), ("round", 2), ("smooth", 5), ("scale", 0.5)])
def test_each_model_preparation_setting_still_leaves_parts_to_cut(page, name, value):
    """The sweep above proves every box is wired up; it cannot prove the result is usable, because all of them at
    once is a model nobody would ask for (a 0.5 mm hollow shell has nothing left to cut). So the settings that
    rebuild the mesh get one sensible value each, and each has to come back with parts."""
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    page.click('nav button[data-t="model"]')
    page.click("#origsize")
    settle(page)
    set_fields(page, [(f"p_{name}", value)])
    settle(page)
    p = plan(page)
    assert p["params"][name] == value
    assert p["counts"]["parts"] > 0, (name, p["errors"], p["notes"])
    page.click("#origsize")
    settle(page)


CUT_OFF = """() => {
  // every visible box, select and readout: does what it holds fit what it shows? (the text measured in the box's own font)
  const cv = document.createElement('canvas').getContext('2d'), px = v => parseFloat(v) || 0, out = [];
  const where = el => (el.closest('section[data-tab]') || {}).dataset?.tab || (el.closest('#sel') ? 'selection panel' : 'view');
  for (const el of document.querySelectorAll('input, select')) {
    if (!(el.offsetWidth || el.offsetHeight) || ['checkbox', 'range', 'file', 'radio', 'hidden', 'color'].includes(el.type)) continue;
    const cs = getComputedStyle(el); cv.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const text = el.tagName === 'SELECT' ? (el.selectedOptions[0]?.textContent || '') : (el.value || el.placeholder || '');
    if (!text) continue;
    let have = el.clientWidth - px(cs.paddingLeft) - px(cs.paddingRight);
    if (el.type === 'number' && cs.appearance !== 'textfield') have -= 15;     // the spinner arrows
    if (el.tagName === 'SELECT') have -= 18;                                    // the drop arrow
    const need = cv.measureText(text).width;
    if (need > have + 0.5) out.push(`${where(el)}: ${el.id || el.title || el.dataset.ln || el.tagName} shows "${text}" in ${Math.round(have)} px, needs ${Math.round(need)}`);
  }
  for (const el of document.querySelectorAll('#stats b, #sel b, .k')) {
    if ((el.offsetWidth || el.offsetHeight) && el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflow !== 'visible')
      out.push(`${where(el)}: "${el.textContent.trim().slice(0, 40)}" cut off`);
  }
  return out;
}"""


@pytest.mark.timeout(1200)
def test_no_number_on_screen_is_cut_off(page):
    """A value the box is too narrow for reads as a different number (-168 as -16) or as nothing at all — the radial
    axes table showed six empty-looking boxes a row. Every technique, every tab, a part selected, in mm, cm and in:
    whatever a field, select or readout holds has to fit in what it shows."""
    found = {}
    scenes = [("dumbbell", "radial"), ("snowman", "radial"), ("egg", "interlocked"), ("cube", "stacked"), ("pyramid", "curve"), ("wedge", "folded")]
    for example, mode in scenes:
        page.click('nav button[data-t="model"]')
        page.select_option("#example", example); settle(page)
        page.click('nav button[data-t="technique"]')
        page.click(f'#modes button[data-m="{mode}"]'); settle(page)
        page.evaluate("() => { const m = window.__t.parts().find(x => x.userData.group !== 'B'); if (m) window.__t.select(m.userData.slice) }")
        for unit in ("mm", "cm", "in"):
            page.select_option("#unit", unit); page.wait_for_timeout(300)
            for tab in ("model", "technique", "sheet", "checks", "export"):
                page.click(f'nav button[data-t="{tab}"]'); page.wait_for_timeout(150)
                for line in page.evaluate(CUT_OFF):
                    found.setdefault(line.split(" shows")[0].split(':')[0] + line.split(':')[1].split(' shows')[0], f"{example}/{mode}/{unit}: {line}")
        page.select_option("#unit", "mm"); page.evaluate("() => window.__t.deselect()")
    assert not found, "\n".join(found.values())


@pytest.mark.timeout(600)
def test_the_tables_take_a_row(page):
    """The list-shaped parameters: + on a points / axes table and a chip typed into a chips box. These add geometry
    the 3D view usually places, and each has thrown at some point — a row of zeros, an axis with no length."""
    page.click('nav button[data-t="technique"]')
    for m in ("curve", "radial"):
        page.click(f'#modes button[data-m="{m}"]')
        settle(page)
        before = plan(page)
        names = page.eval_on_selector_all("#tabs [data-add]", "els => els.map(e => e.dataset.add)")
        for name in names:       # by name: a click re-renders the form, so a button found before it is gone
            page.click(f'#tabs [data-add="{name}"]')
            settle(page)
        p = plan(page)
        assert p["counts"]["parts"] > 0, m
        if m == "curve":         # the curve's + grows the curve on screen; the branch's hangs below it
            assert {"curve", "branches"} <= set(names), names
            assert len(p["params"]["curve"]) == len(before["curve_pts"]) + 1, p["params"]["curve"]
            assert len(p["params"]["branches"]) == 1 and any(s["label"] == "K1" for s in p["slices"])


@pytest.mark.timeout(600)
def test_undo_walks_back_every_change_and_redo_walks_forward(page):
    """The reported one: undo is used exactly when something moved by accident, so it has to be safe to lean on.
    Ten changes, ten undos, and the design is the one it started from — no uncaught error, no stuck status."""
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    for i in range(10):
        set_fields(page, [("p_thickness", 3.5 + i)])
        page.wait_for_timeout(450)                             # each change lands as its own undo step
    settle(page)
    assert page.evaluate("() => window.__t.state().thickness") == 12.5

    def walk(button, limit=120):
        """Press it until it runs out — clicks faster than the debounce, so many steps cost one slice."""
        for n in range(limit):
            if page.is_disabled(button):
                return n
            page.click(button)
            page.wait_for_timeout(120)
        raise AssertionError(f"{button} never ran out")

    back = walk("#undo")                                       # the whole history, past the technique change too
    settle(page)
    assert back >= 10, back
    assert page.evaluate("() => window.__t.state().thickness") != 12.5
    assert walk("#redo") == back                               # and every step forward again
    settle(page)
    assert page.evaluate("() => window.__t.state().thickness") == 12.5
    assert page.evaluate("() => window.__t.plan().mode") == "stacked"


@pytest.mark.timeout(900)
def test_the_whole_job_from_upload_to_cut_files(page):
    """Upload a model, change technique, save the project, open it again, download the cut files, clear the data."""
    page.click('nav button[data-t="model"]')
    page.set_input_files("#file", str(ROOT / "examples" / "pear.stl"))
    settle(page)
    assert plan(page)["counts"]["parts"] > 0
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="interlocked"]')
    settle(page)
    page.fill("#pname", "ui test")
    with page.expect_download() as saved:
        page.click("#psave2")
    proj = saved.value
    page.click('nav button[data-t="export"]')
    with page.expect_download() as zipped:
        page.click("#dl a")
    assert zipped.value.suggested_filename.endswith(".zip")
    # the project file reopens the job — model, technique and every setting
    path = ROOT / "working-files" / "ui_test.lamina.json"
    proj.save_as(path)
    page.set_input_files("#pfile", str(path))
    settle(page)
    assert plan(page)["mode"] == "interlocked"
    assert page.evaluate("() => window.__t.state().project") == "ui test"
    path.unlink(missing_ok=True)
    ok = lambda d: d.accept()
    page.on("dialog", ok)
    page.click("#clear")
    page.wait_for_load_state("load")
    settle(page)
    page.remove_listener("dialog", ok)                   # left in place it would answer the next test's dialogs


@pytest.mark.timeout(600)
def test_a_model_that_cannot_be_loaded_says_so_and_keeps_the_job(page):
    """The reported confusion: an upload that fails leaves the previous model on screen while the file box names the
    new one, and the only word about it is a line of red text. It has to be a dialog, and the box has to let go."""
    page.click('nav button[data-t="model"]')
    page.click('#modes button[data-m="stacked"]') if page.is_visible('#modes button[data-m="stacked"]') else None
    settle(page)
    before = plan(page)["counts"]["parts"]
    bad = ROOT / "working-files" / "not-a-mesh.stl"
    bad.write_bytes(b"this is not a mesh" * 100)
    page.set_input_files("#file", str(bad))
    page.wait_for_function("() => document.getElementById('oops').open", timeout=120_000)
    assert "could not be loaded" in page.text_content("#oops_title")
    page.click("#oops_go")
    assert page.eval_on_selector("#file", "el => el.files.length") == 0      # the box lets go of the file
    assert plan(page)["counts"]["parts"] == before                           # and the job is untouched
    bad.unlink(missing_ok=True)
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_the_model_is_on_screen_before_the_slices_are_finished(page):
    """The reported one: a slow slice showed nothing at all until the last sheet was nested. The build says as soon
    as it has finished with the mesh, and the 3D view fills with it then — while the slices are still being cut —
    and the overlay lists the stages so the wait has a shape."""
    page.click('nav button[data-t="model"]')
    before = page.evaluate("() => [window.__t.ghostUrl(), window.__t.plan().counts.faces]")
    page.select_option("#example", "head_igea")            # detailed enough that the stages take seconds
    page.wait_for_function("old => window.__t.ghostUrl() !== old[0] && window.__t.ghost().length > 0",
                           arg=before, timeout=300_000)
    # the model is up, and the plan it belongs to has not come back yet: that gap is the whole point
    assert page.evaluate("() => window.__t.plan().counts.faces") == before[1]
    rows = page.eval_on_selector_all("#busy_steps li", "ls => ls.map(l => l.className + '|' + l.textContent)")
    assert len(rows) >= 6, rows
    assert any(r.startswith("done|") for r in rows) and any(r.startswith("now|") for r in rows), rows
    assert " of " in page.text_content("#busy_txt"), page.text_content("#busy_txt")   # "step 4 of 8 · … · 20%"
    settle(page)
    assert page.evaluate("() => window.__t.plan().counts.faces") != before[1]
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_a_new_model_does_not_inherit_the_last_one_s_geometry(page):
    """Axis lines, curve points and per-slice edits live in one model's millimetres and under its own part labels.
    Place three radial fans on one model, open another, and radial has to start from a single centred axis again —
    the fan belonged to the model it was drawn on, and so did the memory of it."""
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="radial"]')
    settle(page)
    page.evaluate("""() => {
        const h = window.__t.plan().bbox[2] / 2, s = window.__t.state();
        s.axes = [[[-40, 0, -h * .66], [40, 0, -h * .66]], [[-40, 0, 0], [40, 0, 0]], [[-40, 0, h * .66], [40, 0, h * .66]]];
        s.spine = 1; s.offset = {'R1-2a': 5};
        document.getElementById('p_count').dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    settle(page)
    assert len(page.evaluate("() => window.__t.state().axes")) == 3

    page.click('nav button[data-t="model"]')
    page.select_option("#example", "torus")                  # opens interlocked: a different technique entirely
    settle(page)
    assert page.evaluate("() => window.__t.state().axes ?? null") == []
    assert page.evaluate("() => window.__t.state().offset ?? null") == {}

    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="radial"]')
    settle(page)
    assert page.evaluate("() => window.__t.state().axes") == [], "the last model's fan came back"
    used = page.evaluate("() => window.__t.plan().axes3d")
    assert len(used) == 1, used                              # one axis…
    assert abs(used[0][0][0]) < 1e-6 and abs(used[0][0][1]) < 1e-6, used   # …through the middle of the model

    # Bug 004: an upload kept the last example's model settings — the horse's size 300, round 2, thicken 1 — and a
    # plain cube came back with rounded corners and a hole closed up. An upload starts from the model as drawn.
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "horse")
    settle(page)
    assert page.evaluate("() => window.__t.state().round") == 2   # the preset this is about, really applied
    page.set_input_files("#file", str(ROOT / "examples" / "cube.stl"))
    settle(page)
    got = page.evaluate("() => { const s = window.__t.state(); return [s.size, s.round, s.thicken] }")
    assert got == [[0, 0, 0], 0, 0], got
    assert [round(e) for e in plan(page)["bbox"]] == [180, 180, 180]   # the cube at its own size, not 300

    # an example, then the same file again: the box still held it, so choosing it fired nothing and the example stayed
    page.select_option("#example", "egg")
    settle(page)
    page.set_input_files("#file", str(ROOT / "examples" / "cube.stl"))
    settle(page)
    assert [round(e) for e in plan(page)["bbox"]] == [180, 180, 180], "the same file picked again did not load"
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_a_model_a_few_degrees_off_square_is_squared_by_its_button(page):
    """Bug 001: a cube turned 85° instead of 90° stacked into a staircase and nothing said so. The Model tab now says
    how far off it sits, and its button turns it the rest of the way."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "cube")
    settle(page)
    assert page.is_hidden("#square")                         # square already: nothing to offer
    set_fields(page, [("p_rotate_0", 85)])
    settle(page)
    assert page.is_visible("#square"), "a cube 5° off square was not noticed"
    page.click("#square button")
    settle(page)
    assert page.evaluate("() => window.__t.state().rotate") == [90, 0, 0]
    assert page.is_hidden("#square")
    assert [round(e) for e in plan(page)["bbox"]] == [180, 180, 180]   # square again: no tilted, taller box
    assert not page.errors, page.errors


@pytest.mark.timeout(900)
def test_a_curve_takes_a_branch_from_a_hoof(page):
    """Shift+alt-click each hoof of the horse in view, in curve mode: a branch from the curve out to it, every one
    with ribs and a spine of its own (a joint in the air between splayed legs held nothing). Alt-click on a joint
    plane reaches the leg behind it. Alt-click branch 1's rod and it is gone, parts and all, and the edit made for
    branch 2's joint stays with that leg, now branch 1."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "horse")
    settle(page)
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="curve"]')
    page.evaluate("() => window.__t.applyFix({branches: [], curve: []})")   # the horse opens with its four legs placed
    set_fields(page, [("p_plane", "yz"), ("p_count", 20)])
    settle(page)
    # looked for again after every branch: a branch lets the body ribs turn further, so the leg piece of a body rib
    # that was under a hoof can move away
    hoof = """() => {   // a pixel on the lowest part point of a leg with no branch yet
      const c = window.__t.canvas().getBoundingClientRect(), pts = [], bb = window.__t.plan().bbox, r = 0.08 * Math.max(...bb);
      const tips = (window.__t.state().branches || []).map(b => b[1]);
      for (let y = c.top + 10; y < c.bottom - 10; y += 5) for (let x = c.left + 10; x < c.right - 10; x += 5) {
        const h = window.__t.hit({clientX: x, clientY: y});
        if (h && h.object.userData.slice) pts.push([x, y, h.point.x, h.point.y, h.point.z]) }
      const z0 = Math.min(...pts.map(p => p[4]));
      return pts.filter(p => p[4] < z0 + 0.06 * bb[2] && !tips.some(t => Math.hypot(t[0] - p[2], t[1] - p[3]) < r))
        .sort((a, b) => a[4] - b[4])[0] }"""
    for _ in range(2):
        x, y, *_ = page.evaluate(hoof)
        page.keyboard.down("Shift"); page.keyboard.down("Alt"); page.mouse.click(x, y)
        page.keyboard.up("Alt"); page.keyboard.up("Shift")
        settle(page)
    p = plan(page)
    branches = page.evaluate("() => window.__t.state().branches")
    assert len(branches) == 2 and not p["errors"], (branches, p["errors"])
    for i, (_, tip) in enumerate(branches, 1):
        assert tip[2] < -0.35 * p["bbox"][2], branches                   # its tip is down at the hoof
        own = [s["label"] for s in p["slices"] if re.match(rf"R{i}-|K{i}$", s["label"])]
        assert f"K{i}" in own and len(own) >= 4, (i, own, branches)

    curve = page.evaluate("() => window.__t.state().curve")
    x, y = page.evaluate("""() => {   // a pixel on a joint plane with a part behind it
      const c = window.__t.canvas().getBoundingClientRect(), B = window.__t.parts().filter(m => m.userData.group === 'B');
      const at = (x, y) => window.__t.hit({clientX: x, clientY: y});
      for (let y = c.top + 10; y < c.bottom - 10; y += 4) for (let x = c.left + 10; x < c.right - 10; x += 4) {
        if (at(x, y)?.object.userData.group !== 'B') continue;
        B.forEach(m => m.visible = false); const h = at(x, y); B.forEach(m => m.visible = true);
        if (h?.object.userData.slice) return [x, y] } }""")
    page.keyboard.down("Alt"); page.mouse.click(x, y); page.keyboard.up("Alt")
    settle(page)
    assert page.evaluate("() => window.__t.state().curve") != curve      # a curve point at the leg, not a dead click

    page.evaluate("() => { window.__t.state().offset = {'J-2': 4} }")
    a, b = branches[0]
    x, y = page.evaluate("p => window.__t.screen(p)", [(u + v) / 2 for u, v in zip(a, b)])
    page.keyboard.down("Alt"); page.mouse.click(x, y); page.keyboard.up("Alt")
    settle(page)
    assert page.evaluate("() => window.__t.state().branches") == branches[1:]
    assert page.evaluate("() => window.__t.state().offset") == {"J-1": 4}
    assert not [s["label"] for s in plan(page)["slices"] if re.match(r"R2-|K2$", s["label"])]


ON_PART = """label => {
  // the pixel on the selected part nearest the middle of the view (not a handle, and clear of the corner cube,
  // which takes a press before the part does)
  const c = window.__t.canvas().getBoundingClientRect(), mx = (c.left + c.right) / 2, my = (c.top + c.bottom) / 2;
  let best = null, d = Infinity;
  for (let y = c.top + 20; y < c.bottom - 20; y += 6) for (let x = c.left + 20; x < c.right - 20; x += 6)
    if (Math.hypot(x - mx, y - my) < d && window.__t.hitAt(x, y) === label) { best = [x, y]; d = Math.hypot(x - mx, y - my) }
  return best;
}"""


@pytest.mark.timeout(600)
def test_a_report_is_gathered_while_the_slicer_is_stuck(page):
    """Reported: "compiling report froze, unless I reloaded the page", during a slice that never finished. In the
    browser version one worker runs all the Python, so the report's request for the uploaded model waited behind the
    stuck slice. Here that request never answers at all, and the report still comes back with the model in it."""
    page.click('nav button[data-t="model"]')
    page.set_input_files("#file", str(ROOT / "examples" / "cube.stl"))
    settle(page)
    page.evaluate("""() => { const real = window.fetch;   // the slicer is busy: whatever asks it for the model waits forever
        window.fetch = (u, o) => /\\/source/.test(String(u)) ? new Promise(() => {}) : real(u, o) }""")
    page.click("header [data-feedback]")                  # the report dialog, as the reporter opens it
    got = page.evaluate("""() => Promise.race([
        window.__feedback.build().then(async fd => JSON.parse(await fd.get('project').text()).model?.name ?? 'no model'),
        new Promise(r => setTimeout(() => r('still gathering after 10 s'), 10000))])""")
    page.reload()                                          # put fetch back for the next test (and wait for the page: a bare
                                                           # location.reload() let the next test click a page still loading)
    settle(page)
    assert got == "cube.stl", got


@pytest.mark.timeout(600)
def test_stacked_with_aligned_dowels_finishes_on_a_box_with_a_hole(page, tmp_path):
    """Bug 003: "as soon as I click Stacked Slices it never gets past Step 2 of 7". Their model: a 300 mm cube with a
    30 mm round hole, 144 triangles, uploaded on radial, then stacked at 3 mm with dowels aligned through every layer.
    The flat walls' triangle diagonals put a stray point on every layer's outline, and the intersection of 100 of them
    never finished (a plain box has too few walls to show it: 2 s either way). The reporter's path, in their settings."""
    import shapely
    import trimesh
    model = tmp_path / "cube with hole.stl"
    trimesh.creation.extrude_polygon(shapely.box(-150, -150, 150, 150).difference(shapely.Point(0, 0).buffer(15, 8)), 300).export(model)
    page.click('nav button[data-t="model"]')
    page.set_input_files("#file", str(model))                # opening on radial, like theirs
    settle(page)
    assert [round(e) for e in plan(page)["bbox"]] == [300, 300, 300] and plan(page)["counts"]["faces"] == 144
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    set_fields(page, [("p_thickness", 3), ("p_distribution", "distance"), ("p_space", 0), ("p_connect", "dowel"),
                      ("p_placement", "aligned"), ("p_n_points", 2)])
    settle(page, timeout=90_000)                             # it used to sit at "placing slices and slots" for good
    p = plan(page)
    layers = [s for s in p["slices"] if s["group"] == "S"]
    assert len(layers) == 100, (len(layers), p["bbox"])      # 300 mm of 3 mm layers, the whole height
    assert p["counts"]["errors"] == 0, p["counts"]
    assert not page.errors, page.errors


@pytest.mark.timeout(900)
def test_the_dowel_the_spread_check_offers_lands_where_it_says(page):
    """A layer held by dowels bunched together is told on the Checks tab, under its own label, which dowel would hold
    it, with a button. The button adds that dowel to the ones typed in (the Technique tab's dowels), a rod appears
    through that layer at that spot in the 3D view, and the warning goes. The horse stacked as its example used to
    open (random 3 mm square dowels, a 6 mm gap), set to aligned: the button is for dowels straight through the stack."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "horse")
    settle(page)
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    page.evaluate("""() => window.__t.applyFix({axis: 'z', size: [0, 300, 0], connect: 'dowel', dowel_shape: 'square', placement: 'random',
                                                space: 6, dowel_d: 3, n_points: 2, round: 3, thicken: 1, margin: 6})""")
    settle(page)
    set_fields(page, [("p_placement", "aligned")])
    settle(page)
    page.click('nav button[data-t="checks"]')
    offered = page.locator("#msgs .msg.warn", has_text="bunched together").filter(has=page.locator(".fix"))
    assert offered.count(), [w for s in plan(page)["slices"] for w in s["warnings"] if "bunched" in w]
    msg = offered.first
    label, text = msg.get_attribute("data-s"), msg.text_content()
    x, y = map(float, re.search(r"a dowel at \(([-\d.]+) mm, ([-\d.]+) mm\)", text).groups())
    assert plan(page)["params"]["dowels"] == []
    # in inches the spot is in inches too, the message and its button (it stayed in mm without a unit after it)
    page.select_option("#unit", "in")
    for t in (offered.first.text_content(), offered.first.locator(".fix").first.text_content()):
        spot = re.search(r"a dowel at \(([^)]*)\)", t).group(1)
        assert spot.count(" in") == 2 and "mm" not in spot, spot
    page.select_option("#unit", "mm")

    msg.locator(".fix").first.click()
    settle(page)
    p = plan(page)
    assert p["params"]["dowels"] == [[x, y]], p["params"]["dowels"]
    # the rod in the 3D view: through this layer, at the spot the message named (a rod is drawn from its start point)
    M = next(s for s in p["slices"] if s["label"] == label)["M"]
    wx, wy = M[0][0] * x + M[0][1] * y + M[0][3], M[1][0] * x + M[1][1] * y + M[1][3]
    rods = page.evaluate("""() => window.__t.axes().filter(m => m.isMesh && m.geometry.type === 'ExtrudeGeometry')
                                  .map(m => [m.position.x, m.position.y, m.position.z])""")
    assert len(rods) == len(p["rods"]), (len(rods), len(p["rods"]))
    assert [r for r in rods if math.hypot(r[0] - wx, r[1] - wy) < 0.1], f"no rod drawn at ({x}, {y}) of {label}"
    assert any(a[2] <= M[2][3] <= b[2] for a, b, *_ in p["rods"] if math.hypot(a[0] - wx, a[1] - wy) < 0.1), \
        f"the rod at ({x}, {y}) does not pass through {label}"
    assert not page.locator(f'#msgs .msg.warn[data-s="{label}"]', has_text="bunched together").count(), \
        page.locator(f'#msgs .msg[data-s="{label}"]').all_text_contents()
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_only_a_handle_moves_a_part(page):
    """Reported as "needs a step undo, it is easy to move a layer unintentionally": once a layer was selected, a drag
    anywhere on it slid it — which is also how you turn the view. A plain drag on the part now turns the view and
    leaves it where it was; shift-drag on it still tilts it, as the help says."""
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    set_fields(page, [("p_distribution", "count"), ("p_count", 8)])   # layers tall enough on screen to press one
    settle(page)
    label = page.evaluate("() => { const s = window.__t.plan().slices.filter(s => s.group === 'S'); return s[s.length >> 1].label }")
    page.evaluate("l => window.__t.select(l)", label)
    page.wait_for_timeout(300)

    def drag(mod=None):
        x, y = page.evaluate(ON_PART, label)           # found again each time: the plain drag turns the view
        if mod:
            page.keyboard.down(mod)
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 60, y + 40, steps=8); page.mouse.up()
        if mod:
            page.keyboard.up(mod)
        page.wait_for_timeout(600)
        settle(page)
        return page.evaluate("l => [(window.__t.state().offset || {})[l] || 0, (window.__t.state().tilt || {})[l] || 0]", label)

    assert drag() == [0, 0], "a plain drag on the part moved it"
    assert drag("Shift")[1] != 0, "shift-drag on the part no longer tilts it"


@pytest.mark.timeout(600)
def test_a_line_added_with_the_button_places_dowels(page):
    """+ line used to add 0,0,0 → 0,0,0: a line nothing crosses, so no dowel, and a stack with a gap then lost its
    layers to autofix (reported). Two presses now give two lines up the model, a dowel through every layer they meet,
    and every layer stays. On the torus, where a line a fixed distance out from the middle fell in its hole."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "torus")
    settle(page)
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    set_fields(page, [("p_placement", "lines"), ("p_space", 5)])
    settle(page)
    layers = len([s for s in plan(page)["slices"] if s["group"] == "S"])
    for _ in range(2):
        page.click('#tabs [data-add="lines"]')
        settle(page)
    p = plan(page)
    assert len(p["params"]["lines"]) == 2, p["params"]["lines"]
    # the torus's top and bottom pairs overlap in a sliver no 6 mm dowel fits; the old default placed none at all
    assert len(p["rods"]) >= layers - 1, (layers, len(p["rods"]))
    assert len([s for s in p["slices"] if s["group"] == "S"]) == layers

    # alt-click the model: a line straight up through that point; alt-click it again and it is gone
    mid = next(s["label"] for s in p["slices"] if s["group"] == "S" and s["label"].endswith(f"-{layers // 2}"))
    x, y = page.evaluate(ON_PART, mid)

    def alt_click():
        page.keyboard.down("Alt"); page.mouse.click(x, y); page.keyboard.up("Alt")
        settle(page)
        return plan(page)["params"]["lines"]

    added = alt_click()
    assert len(added) == 3 and added[2][0][:2] == added[2][1][:2], added          # straight up the stack
    assert len(alt_click()) == 2


@pytest.mark.timeout(600)
def test_a_model_too_big_for_the_sheet_says_what_would_fit(page):
    """510 × 298 mm of cardboard and a model half a metre tall: the parts cannot fit, so the report has to say so and
    name the size that would — not quietly draw parts over each other and off the page."""
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    page.click('nav button[data-t="sheet"]')
    set_fields(page, [("p_sheet_0", 510), ("p_sheet_1", 298), ("p_split", False)])
    settle(page)
    page.click('nav button[data-t="model"]')
    set_fields(page, [("p_size_1", 500)])
    settle(page)
    p = plan(page)
    assert any("bigger than the 510 × 298 mm sheet" in e for e in p["errors"]), p["errors"]
    assert any("set `size` to about" in e for e in p["errors"]), p["errors"]
    fixes = [o["title"] for sl in p["slices"] for f in sl["fixes"] for o in f["options"]]
    assert any(t.startswith("scale the model to") for t in fixes), fixes
    assert any(t == "split oversize parts" for t in fixes), fixes
    page.click("#origsize")
    settle(page)


@pytest.mark.timeout(900)
def test_units_change_what_is_shown_never_what_is_stored(page):
    """The unit on the toolbar is how lengths read, never what they are. Typed in inches, a value reaches the server
    exact (1/16 in is 1.5875 mm, not 1.59); the boxes step in round numbers of the unit, so 0.25 in is a valid entry;
    switching back and forth leaves every stored value where it was; and the planner's messages, its fix buttons and
    the help, all written in mm, read in the unit on show."""
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    page.select_option("#unit", "in")
    page.click('nav button[data-t="sheet"]')
    step, low = page.eval_on_selector("#p_thickness", "el => [el.step, el.min]")
    assert re.fullmatch(r"0\.0*[125]", step), step                      # a round step of the unit, not 0.0019685
    assert abs(float(low) / float(step) - round(float(low) / float(step))) < 1e-9, (low, step)   # min on the step grid
    assert page.eval_on_selector("#p_thickness", "el => { el.value = '0.25'; return el.checkValidity() }")

    set_fields(page, [("p_thickness", 0.0625)])                          # 1/16 in
    settle(page)
    assert plan(page)["params"]["thickness"] == 1.5875
    assert "1/16 in stock" in page.text_content("#sheets")               # the sheet header reads the fraction it is sold by
    # a slice of its own thickness, from its panel: selected through the parts table's own handler (the table sits in
    # a panel this viewport keeps closed)
    label = page.eval_on_selector("#parts tr[data-s]", "tr => { tr.click(); return tr.dataset.s }")
    page.eval_on_selector("#n_thick", "el => { el.value = '0.09375'; el.dispatchEvent(new Event('change')) }")   # 3/32 in
    settle(page)
    assert page.evaluate("() => window.__t.state().thick")[label] == 2.38125   # was rounded to 2.38

    before = page.evaluate("() => JSON.stringify(window.__t.state())")
    for _ in range(10):
        for u in ("cm", "mm", "in"):
            page.select_option("#unit", u)
    assert page.evaluate("() => JSON.stringify(window.__t.state())") == before

    page.select_option("#unit", "mm")                                    # a job that does not fit, set up in mm …
    set_fields(page, [("p_sheet_0", 510), ("p_sheet_1", 298), ("p_split", False)])
    settle(page)
    page.click('nav button[data-t="model"]')
    set_fields(page, [("p_size_1", 500)])
    settle(page)
    page.select_option("#unit", "in")                                    # … read in inches, without a re-slice
    msgs = page.text_content("#msgs")
    assert "20.0787 × 11.7323 in sheet" in msgs, msgs
    assert not re.search(r"\d\s*mm\b", msgs), msgs
    assert not any(re.search(r"\d\s*mm\b", t) for t in page.eval_on_selector_all("#msgs .fix", "fs => fs.map(f => f.textContent)"))
    page.click('nav button[data-t="sheet"]')
    page.hover('[data-p="thickness"] .k')
    tip = page.text_content("#tip")
    assert "(in)" in tip and "0.0118 in" in tip and not re.search(r"\d\s*mm\b|\(mm\)", tip), tip
    page.select_option("#unit", "mm")
    page.click('nav button[data-t="model"]')
    page.click("#origsize")
    settle(page)


@pytest.mark.timeout(900)
def test_the_export_tab_weighs_the_parts(page):
    """The cube as four 180 × 180 mm slices of 14 ga steel (1.897 mm, 7.85 g/cm³): 4 × 32400 mm² × 1.897 mm =
    245.85 cm³, which is 1.93 kg — worked out by hand, not by the page. One slice cut from 6 mm instead weighs on its
    own stock line (1.45 kg + 1.53 kg = 2.97 kg). Inches read in pounds and lb/in³, and a material of your own keeps
    the density typed for it."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "cube")
    settle(page)
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    set_fields(page, [("p_distribution", "count"), ("p_count", 4), ("p_connect", "none")])
    settle(page)
    page.click('nav button[data-t="sheet"]')
    page.select_option("#material", "steel")
    page.select_option("#thicklist", "1.897")                            # 14 ga
    settle(page)
    page.click('nav button[data-t="export"]')
    weight = lambda: page.text_content("#weight")
    assert "1.93 kg" in weight() and "246 cm³" in weight() and "7.85 g/cm³" in weight(), weight()

    page.evaluate("""() => { window.__t.state().thick = {'Z-2': 6};
        document.getElementById('p_count').dispatchEvent(new Event('input', {bubbles: true})) }""")
    settle(page)
    assert "2.97 kg" in weight(), weight()
    assert "1.897 mm stock: 3 part(s) · 1.45 kg" in weight() and "6 mm stock: 1 part(s) · 1.53 kg" in weight(), weight()
    page.evaluate("""() => { window.__t.state().thick = {};
        document.getElementById('p_count').dispatchEvent(new Event('input', {bubbles: true})) }""")
    settle(page)

    page.select_option("#unit", "in")
    assert "4.25 lb" in weight() and "0.2836 lb/in³" in weight(), weight()
    page.select_option("#unit", "mm")

    # dowels: two aligned rods, each one piece from the first slice's outer face to the last one's, of the same steel
    page.click('nav button[data-t="technique"]')
    set_fields(page, [("p_connect", "dowel")])
    settle(page)
    page.click('nav button[data-t="export"]')
    p = plan(page)
    assert len(p["rods"]) == 2 * 3, p["rods"]                            # two points × three pairs of slices
    n = p["slices"][0]["M"]; z = sorted(sum(s["M"][i][3] * n[i][2] for i in range(3)) for s in p["slices"])
    rod = (z[-1] - z[0]) + 1.897                                         # outer face to outer face
    sec = p["rods"][0][3]                                                # the rod's section as cut: a 96-gon, not π r²
    area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(sec, sec[1:] + sec[:1]))) / 2
    assert abs(area - math.pi * 3 ** 2) < 0.01 * math.pi * 3 ** 2, area  # 6 mm dowels
    mass = 2 * rod * area * 7.85 / 1000                                  # in grams
    assert "2 dowel(s)" in weight() and f"{mass:.3g} g" in weight(), (mass, weight())
    # assembled = parts + dowels, the parts now 8 holes lighter: 6 mm dowels + the fiber laser's 0.15 mm slot offset
    holes = 8 * math.pi * 3.075 ** 2 * 1.897 * 7.85 / 1000
    assert f"{(245.8512 * 7.85 - holes + mass) / 1000:.3g} kg" in weight(), (holes, mass, weight())
    page.click('nav button[data-t="technique"]')
    set_fields(page, [("p_connect", "none")])
    settle(page)

    page.click('nav button[data-t="sheet"]')                             # a material of your own, with its own density
    # the name is answered by the page's own prompt: an earlier test leaves a handler that accepts every dialog empty
    page.evaluate("() => { const p = window.prompt; window.prompt = () => (window.prompt = p, 'birch from the yard') }")
    page.click("#matadd")
    assert page.eval_on_selector("#material", "s => s.value") == "birch from the yard"
    set_fields(page, [("density", 0.6)])
    page.select_option("#material", "plywood")
    page.select_option("#material", "birch from the yard")                 # the density went with the material
    assert page.input_value("#density") == "0.6"
    page.select_option("#thicklist", "1.897")
    settle(page)
    page.click('nav button[data-t="export"]')
    assert "148 g" in weight(), weight()                                 # 245.85 cm³ × 0.6 g/cm³ = 147.5 g
    page.click('nav button[data-t="sheet"]')
    page.click("#matdel")
    assert "birch from the yard" not in page.eval_on_selector_all("#material option", "os => os.map(o => o.value)")
    assert page.eval_on_selector("#material", "s => s.value") == "steel"   # back to the built-in it was made from
    settle(page)


@pytest.mark.timeout(1200)
def test_every_material_is_complete(page):
    """Each material on the list, picked the way a person picks it: it lands on its own machine, one of its stock
    thicknesses, a sheet it is sold in and a 3D look that exists, and the Export tab weighs it at its own density.
    A material missing any of these would leave the form holding the last one's values."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "cube")
    settle(page)
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    set_fields(page, [("p_distribution", "count"), ("p_count", 2), ("p_connect", "none")])
    settle(page)
    page.click('nav button[data-t="sheet"]')
    names = page.eval_on_selector_all("#material option", "os => os.map(o => o.value)")
    for want in ("stainless steel", "brass", "copper", "greyboard", "polypropylene", "foam board", "EVA foam", "basswood", "balsa"):
        assert want in names, (want, names)
    looks = page.eval_on_selector_all("#look option", "os => os.map(o => o.value)")
    for name in names:
        page.select_option("#material", name)
        settle(page)
        got = page.evaluate("""() => ({machines: [...document.querySelectorAll('#machine option')].map(o => o.value),
            machine: document.getElementById('machine').value, thick: document.getElementById('thicklist').value,
            sheet: document.getElementById('sheetpreset').value, look: document.getElementById('look').value,
            density: +document.getElementById('density').value, t: window.__t.state().thickness})""")
        assert got["machine"] in got["machines"], (name, got)                       # a machine that cuts it
        assert got["thick"] and abs(float(got["thick"]) - got["t"]) < 1e-9, (name, got)   # one of its own stocks
        assert got["sheet"], (name, got)                                            # a size it is sold in
        assert got["look"] in looks, (name, got)
        assert 0.01 < got["density"] < 20, (name, got)
        # the weight is drawn with the plan that comes back after the switch: wait for it rather than read the last one
        page.wait_for_function("d => (document.getElementById('weight').textContent || '').includes(d + ' g/cm')",
                               arg=f"{got['density']:g}", timeout=60_000)
        assert f"{got['density']:g} g/cm³" in page.text_content("#weight"), (name, page.text_content("#weight"))
    page.select_option("#material", "stainless steel")                     # its own gauges, not carbon steel's
    assert "14 ga · 1.984 mm" in page.text_content("#thicklist")
    # printed materials: made by a printer and nothing else, nested on its bed, and the Export tab's print set at 1:1
    set_fields(page, [("pr_scale", 0.5)])                                  # it sits on the Export tab, closed here
    page.select_option("#material", "PETG")
    settle(page)
    machines = page.eval_on_selector_all("#machine option", "os => os.map(o => o.value)")
    assert "fdm" in machines and "co2" not in machines and "hand" not in machines, machines
    page.select_option("#machine", "bambu_h2c")
    settle(page)
    assert plan(page)["sheet"] == [325, 320] and plan(page)["params"]["slot_offset"] == 0.2
    assert page.input_value("#pr_scale") == "1"
    assert "1.27 g/cm³" in page.text_content("#weight")
    page.select_option("#material", "cardboard")
    settle(page)


@pytest.mark.timeout(600)
def test_what_is_new_shows_itself_once_when_the_version_changes(page, server):
    """A version this browser has not seen opens the release notes by itself, once. Someone opening Lamina for the
    first time is shown nothing — none of it is new to them — and the header button opens the whole list whenever
    they want it. The notes are CHANGELOG.md itself, so the dialog cannot drift from the release."""
    def reload_with(seen):
        page.evaluate("v => v === null ? localStorage.removeItem('slicer_seen_version')"
                      " : localStorage.setItem('slicer_seen_version', JSON.stringify(v))", seen)
        page.goto(server + "/")
        settle(page)
        page.wait_for_timeout(600)                       # the notes are fetched after the page is up

    versions = page.evaluate("async () => (await (await fetch('changelog.md')).text()).split(/^## +/m).slice(1).map(p => p.split('\\n')[0].trim())")
    latest = versions[0]
    assert len(versions) > 3, "the app could not read CHANGELOG.md"
    heads = lambda: page.eval_on_selector_all("#news_body h5", "els => els.map(e => e.textContent.replace('Version ', ''))")

    reload_with(None)                                    # never seen Lamina: nothing is new, so nothing opens
    assert not page.locator("#newsdlg[open]").count(), "a first-time visitor was shown release notes"
    assert page.evaluate("() => JSON.parse(localStorage.getItem('slicer_seen_version'))") == latest

    # last seen two versions back (0.2.1, with 0.2.2 and its next-day fix 0.2.3 out since): both, newest first — the
    # fix must not hide the release it fixed
    reload_with(versions[2])
    assert page.locator("#newsdlg[open]").count(), "a new version did not announce itself"
    assert heads() == versions[:2] and len(page.text_content("#news_body")) > 200, heads()
    page.click("#news_go")

    reload_with("0.0.1")                                 # a version no longer listed: every version
    assert heads() == versions, heads()
    page.click("#news_go")

    page.goto(server + "/")                              # and not again on the next visit
    settle(page)
    page.wait_for_timeout(600)
    assert not page.locator("#newsdlg[open]").count(), "the release notes came back a second time"

    page.click("#newsbtn")                               # the button still opens them, newest version first
    page.wait_for_timeout(400)
    assert page.locator("#newsdlg[open]").count()
    heads = page.eval_on_selector_all("#news_body h5", "els => els.map(e => e.textContent)")
    assert heads[0].endswith(latest) and len(heads) > 1, heads
    page.click("#news_go")


def zip_of(body):
    import io, zipfile
    return zipfile.ZipFile(io.BytesIO(body))


@pytest.mark.timeout(1800)
def test_every_control_does_what_it_says_and_every_download_holds_the_plan(page, server):
    """Every button, slider and download of the app, pressed once, and what it produced read back: the 3D view bar,
    the selected-part panel, revisions, help, saved presets, the thickness and sheet lists, the one-click fixes, and
    every file behind the Export tab — opened and held against the plan it came from (the sheets name every part, the
    key lists every part, the STL is whole, the prototype carries a plate). A control that stops working, or a file
    that stops matching what the screen shows, fails here."""
    import xml.etree.ElementTree as ET
    names = iter(["ui preset", "ui sheet"])
    answer = lambda d: d.accept(next(names, "ui")) if d.type == "prompt" else d.accept()
    page.on("dialog", answer)
    page.click('nav button[data-t="model"]'); page.select_option("#example", "egg"); settle(page)
    page.click('nav button[data-t="technique"]'); page.click('#modes button[data-m="interlocked"]'); settle(page)
    p = plan(page)
    labels = {pc["label"] for s in p["slices"] for pc in s["pieces"]}
    ev = page.evaluate

    # -- the 3D view bar
    page.fill("#explode", "2"); page.dispatch_event("#explode", "input")
    assert ev("() => window.__t.parts().some(m => m.position.length() > 1)"), "explode moved nothing"
    page.fill("#explode", "1"); page.dispatch_event("#explode", "input")
    page.fill("#steps", "1"); page.dispatch_event("#steps", "input")
    assert ev("() => window.__t.parts().filter(m => m.visible && m.userData.group !== 'B').length") == 1, "steps did not step"
    ev("() => { const s = document.querySelector('#steps'); s.value = s.max; s.dispatchEvent(new Event('input')) }")
    page.uncheck("#ghost"); assert ev("() => !window.__t.ghost()[0].parent.visible"), "the model did not hide"
    page.check("#ghost")
    before = ev("() => window.__t.parts()[0].material.color.getHex()")
    page.select_option("#look", "steel")
    assert ev("() => window.__t.parts()[0].material.color.getHex()") != before, "the look did not change the parts"
    page.select_option("#look", "group")
    page.select_option("#viewmode", "only3d"); assert "only3d" in page.get_attribute("#view", "class")
    page.select_option("#viewmode", "both")
    ev("() => window.__t.cam(10, 80, 50000)"); page.click("#fit")
    assert ev("() => window.__t.camera.position.length()") < 50000, "fit view did not bring the model back"

    # -- the selected-part panel: move, reset, close, delete
    lab = p["slices"][0]["label"]
    ev(f"() => window.__t.select('{lab}')"); page.wait_for_timeout(200)
    assert page.is_visible("#sel") and page.text_content("#sel b") == lab
    page.fill("#n_offset", "3"); page.dispatch_event("#n_offset", "change"); settle(page)
    assert abs(ev(f"() => window.__t.state().offset['{lab}']") - 3) < 1e-6, "the offset box did not reach the slice"
    page.click("#s_reset"); settle(page)
    assert ev(f"() => !(window.__t.state().offset || {{}})['{lab}']"), "reset left the offset"
    ev(f"() => window.__t.select('{lab}')"); page.click("#s_close"); assert not page.is_visible("#sel")
    ev(f"() => window.__t.select('{lab}')"); page.click("#s_del")
    page.wait_for_function(f"() => !window.__t.plan().slices.some(s => s.label === '{lab}')", timeout=180_000)   # the re-slice that drops it
    settle(page)
    assert lab in ev("() => window.__t.state().skip")
    ev("() => document.querySelector('#undo').click()"); settle(page)
    assert lab in {s["label"] for s in plan(page)["slices"]}, "undo did not bring the deleted slice back"

    # -- header: revisions and help
    rev = page.text_content("#prev")
    page.click("#pminor"); assert page.text_content("#prev") != rev
    page.click("#pmajor"); assert page.text_content("#prev").endswith(".0")
    page.click("#helpbtn"); assert page.locator("#helpdlg[open]").count(); page.click("#help_go")
    assert not page.locator("#helpdlg[open]").count()

    # -- the Sheet & fit lists: a saved preset, a thickness, a sheet size — added, then removed
    page.click('nav button[data-t="sheet"]')
    page.click("#psave"); assert "ui preset" in page.eval_on_selector_all("#presets option", "o => o.map(x => x.value)")
    page.select_option("#presets", "ui preset"); page.click("#pdel")
    assert "ui preset" not in page.eval_on_selector_all("#presets option", "o => o.map(x => x.value)")
    page.fill("#p_thickness", "2.37"); page.dispatch_event("#p_thickness", "input"); settle(page)
    page.click("#madd")
    assert 2.37 in ev("() => Object.values(JSON.parse(localStorage.getItem('slicer_thick') || '{}')).flat()")
    page.select_option("#thicklist", index=page.eval_on_selector_all("#thicklist option", "o => o.findIndex(x => +x.value === 2.37)"))
    page.click("#mdel")
    assert 2.37 not in ev("() => Object.values(JSON.parse(localStorage.getItem('slicer_thick') || '{}')).flat()")
    page.click("#sadd")
    assert any(s[0] == "ui sheet" for s in ev("() => JSON.parse(localStorage.getItem('slicer_sheets') || '[]')"))
    page.select_option("#sheetpreset", index=page.eval_on_selector_all("#sheetpreset option", "o => o.length - 1")); page.click("#sdel")
    assert not any(s[0] == "ui sheet" for s in ev("() => JSON.parse(localStorage.getItem('slicer_sheets') || '[]')"))
    page.click("#usage_optin") if page.is_visible("#usage_optin") else None
    page.fill("#p_thickness", "1.5"); page.dispatch_event("#p_thickness", "input"); settle(page)

    # -- every download: fetched as the link has it, opened, and held against the plan
    page.click('nav button[data-t="export"]')
    p = plan(page); labels = {pc["label"] for s in p["slices"] for pc in s["pieces"]}
    from core.export import design_name
    design = design_name(p)                              # every file in a zip is named after the design, as the zip is
    links = {a["t"]: a["h"] for a in page.eval_on_selector_all("#dl a", "as => as.map(a => ({t: a.textContent, h: a.getAttribute('href')}))")}
    get = lambda href: page.request.get(f"{server}/{href}")
    z = zip_of(get(links["sheets SVG + DXF"]).body())
    svgs = [n for n in z.namelist() if n.endswith(".svg")]
    assert svgs and any(n.endswith(".dxf") for n in z.namelist()) and f"{design} assembly-key.txt" in z.namelist()
    assert all(n.startswith(f"{design} ") or n == f"{design}.lamina.json" for n in z.namelist()), z.namelist()
    drawn = {el.get("data-label") for n in svgs for el in ET.fromstring(z.read(n)).iter() if el.get("data-label")}   # noqa: S314 — our own server's SVG
    assert labels <= drawn, f"parts in the plan but on no sheet: {sorted(labels - drawn)[:5]}"
    key = z.read(f"{design} assembly-key.txt").decode()
    assert all(lb in key for lb in labels), "the assembly key misses parts"
    pdf = zip_of(get(links["sheets PDF (one page per sheet)"]).body())       # zipped, with the key and the project file
    assert [pdf.read(n)[:4] for n in pdf.namelist() if n.endswith(".pdf")] == [b"%PDF"]
    eps = zip_of(get(links["sheets EPS"]).body())
    assert all(eps.read(n)[:4] == b"%!PS" for n in eps.namelist() if n.endswith(".eps"))
    pieces = zip_of(get(links["one file per piece SVG + DXF"]).body())
    assert f"{design} cut-list.txt" in pieces.namelist() and len([n for n in pieces.namelist() if n.endswith(".svg")]) >= 2
    stl = get(links["assembled STL"]).body()
    assert len(stl) == 84 + 50 * int.from_bytes(stl[80:84], "little") and int.from_bytes(stl[80:84], "little") > 100, "the STL is not whole"
    one = get(links["assembled STL"] + "?part=" + sorted(labels)[0]).body()     # one part alone, as the parts table offers it
    assert len(one) == 84 + 50 * int.from_bytes(one[80:84], "little") and 0 < len(one) < len(stl)
    assert json.loads(get(links["plan.json"]).body())["counts"]["parts"] == p["counts"]["parts"]
    fit = zip_of(get(links[next(t for t in links if t.startswith("fit test SVG"))]).body())
    assert "README.txt" in fit.namelist() and len({n.split("/")[0] for n in fit.namelist() if "/" in n}) == 5
    page.uncheck("#x_key"); page.uncheck("#x_labels")
    href = page.eval_on_selector("#dl a", "a => a.getAttribute('href')")
    assert "key=0" in href and "labels=0" in href
    assert not any(n.endswith("assembly-key.txt") for n in zip_of(get(href).body()).namelist())
    page.check("#x_key"); page.check("#x_labels")

    # -- prototyping: the fields reach the request, and the zips hold a plate
    page.fill("#pr_size", "120"); page.select_option("#pr_labels", "hole"); page.fill("#pr_font", "4")
    page.fill("#pr_min", "1"); page.fill("#pr_offset", "0.3"); page.fill("#pr_step", "0.05")
    for btn, want in (("#pr_go", "plate.3mf"), ("#fit_go", "plate.3mf")):
        with page.expect_download(timeout=300_000) as dl:
            page.click(btn)
        url = dl.value.url
        assert all(q in url for q in ("size=120", "labels=hole", "font=4", "min_thick=1", "offset=0.3")), url
        assert want in zip_of(pathlib.Path(dl.value.path()).read_bytes()).namelist()

    # -- the assembly video: a real webm, and the view put back as it was
    with page.expect_download(timeout=120_000) as vid:
        page.click("#vid_go")
    assert vid.value.suggested_filename.endswith(".webm") and pathlib.Path(vid.value.path()).stat().st_size > 10_000
    assert ev("() => window.__t.parts().every(m => m.userData.group === 'B' || m.visible)"), "the video left parts hidden"

    # -- a one-click fix: axes on no plane, one click puts them back on one and the error goes
    page.click('nav button[data-t="model"]'); page.select_option("#example", "dumbbell"); settle(page)
    ev("() => window.__t.applyFix({axes: [[[-72, 0, -108], [72, 0, -108]], [[0, -72, 108], [0, 72, 108]]]})"); settle(page)
    assert plan(page)["counts"]["errors"] > 0
    page.click("#msgs .fix"); settle(page)
    assert plan(page)["counts"]["errors"] == 0, plan(page)["errors"]
    page.remove_listener("dialog", answer)
    assert not page.errors, page.errors


def test_an_example_starts_every_technique_from_its_defaults(page):
    """Reported: the horse switched to stacked after the statue came back with the statue's preset (2 mm square
    dowels, axis y, random), so its tab spacers were all "thinner than 2 mm". The technique memory carried the last
    example's preset; a new example now starts every technique from its defaults and its own preset."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "horse_statue"); settle(page)
    page.select_option("#example", "horse"); settle(page)
    page.click('nav button[data-t="technique"]'); page.click('#modes button[data-m="stacked"]'); settle(page)
    defaults = page.evaluate("async () => Object.fromEntries((await (await fetch('api/modes')).json())"
                             ".find(m => m.name === 'stacked').params.map(p => [p.name, p.default]))")
    st = page.evaluate("() => window.__t.state()")
    for k in ("dowel_d", "dowel_shape", "axis", "placement", "space"):
        assert st[k] == defaults[k], (k, st[k], defaults[k])


def test_a_drag_while_a_slice_runs_turns_the_view_not_the_model(page):
    """Reported: the statue "is not there if you move it before it is complete". Picked from the list on the Model
    tab, the turn rings still had the last model's size, and a drag across the middle of the view to look round
    caught one: the statue was turned upside down (rotate x = -162) and sliced again with ten errors. While a slice
    runs a drag turns the view only."""
    page.click('nav button[data-t="model"]')
    page.select_option("#example", "head_igea"); settle(page)
    box = page.locator("#v3d canvas").first.bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.select_option("#example", "horse_statue")
    drags = 0
    for _ in range(6):                                   # across the middle, where the red ring runs edge-on
        page.wait_for_timeout(250)
        if page.locator("#busy").is_hidden():            # sliced: the rings are the statue's own now, and grabbing one turns it
            break
        page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 120, cy + 30, steps=8); page.mouse.up(); drags += 1
    settle(page)
    assert drags                                         # at least one drag landed while it sliced (a fast machine may finish first)
    assert page.evaluate("() => window.__t.state().rotate") == [0, 0, 0]
    assert plan(page)["counts"]["errors"] == 0
