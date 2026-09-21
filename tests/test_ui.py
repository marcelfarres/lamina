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
import os
import pathlib
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
    and this is the price: a technique or a remeshed model left behind would slow down or break the next test."""
    for tab in ("model", "technique", "sheet", "checks"):
        page.click(f'nav button[data-t="{tab}"]')
        page.click(f'button.reset[data-reset="{tab}"]')
        page.wait_for_timeout(200)
    settle(page)
    yield


def settle(page, timeout=180_000):
    """Wait for the status line to stand still: a change debounces, so it has to be ready twice over."""
    for _ in range(2):
        page.wait_for_function("() => /^(ready|error)/.test(document.getElementById('status').textContent)", timeout=timeout)
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
        if p["type"] not in TYPED or p["group"] == "hidden":
            continue
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


@pytest.mark.timeout(600)
def test_the_tables_take_a_row(page):
    """The list-shaped parameters: + on a points / axes table and a chip typed into a chips box. These add geometry
    the 3D view usually places, and each has thrown at some point — a row of zeros, an axis with no length."""
    page.click('nav button[data-t="technique"]')
    for m in ("curve", "radial"):
        page.click(f'#modes button[data-m="{m}"]')
        settle(page)
        for btn in page.query_selector_all("#tabs [data-add]"):
            btn.click()
            settle(page)
        assert plan(page)["counts"]["parts"] > 0, m


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
    page.on("dialog", lambda d: d.accept())
    page.click("#clear")
    page.wait_for_load_state("load")
    settle(page)


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
    assert not page.errors, page.errors


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

    latest = page.evaluate("async () => (await (await fetch('changelog.md')).text()).split(/^## +/m)[1].split('\\n')[0].trim()")
    assert latest, "the app could not read CHANGELOG.md"

    reload_with(None)                                    # never seen Lamina: nothing is new, so nothing opens
    assert not page.locator("#newsdlg[open]").count(), "a first-time visitor was shown release notes"
    assert page.evaluate("() => JSON.parse(localStorage.getItem('slicer_seen_version'))") == latest

    reload_with("0.0.1")                                 # last seen an older version: shown once
    assert page.locator("#newsdlg[open]").count(), "a new version did not announce itself"
    body = page.text_content("#news_body")
    assert latest in page.text_content("#news_title") and len(body) > 200, (page.text_content("#news_title"), body[:80])
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
