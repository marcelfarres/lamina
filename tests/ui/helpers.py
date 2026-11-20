"""What the UI tests share: waiting for the page, reading its state, filling its boxes, and the snippets of
JavaScript more than one test runs."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
# list-shaped parameters are placed from the 3D view (points, axes, per-slice maps), not typed into a box: the sweep
# sets everything with a box of its own, and test_the_tables_take_a_row exercises the rest through their + buttons
TYPED = ("number", "int", "bool", "choice", "text", "vec2", "vec3")


def settle(page, timeout=180_000):
    """Wait for the page to be idle: no change waiting out its debounce, no slice running. Watching the status line
    for a while was not enough: on a slow runner the debounce outlasted the wait and the last slice's "ready" passed
    for the next one's (bugs/024). A slice that failed keeps the plan before it, so it fails here, with its message,
    rather than as a stale value further on."""
    page.wait_for_function("() => window.__t?.idle() && /^(ready|error)/.test(document.getElementById('status')?.textContent)", timeout=timeout)
    assert not page.errors, page.errors
    status = page.text_content("#status")
    assert status.startswith("ready"), status
    return status


def plan(page):
    return page.evaluate("() => window.__t.plan()")


def menu(page, item):
    """Press an item of a header menu: the menu opened first, as a person does."""
    page.click(f"details.menu:has({item}) > summary"); page.click(f"details.menu {item}")


def state(page):
    return page.evaluate("() => window.__t.state()")


def example(page, name):
    """Open a bundled example the way every way into one does (the dropdown, the library), and wait for its slice."""
    page.evaluate("n => __t.openExample(n)", name)
    settle(page)


def use(page, name=None, mode=None):
    """The sequence most tests start with: the example opened on the Model tab, then the technique picked on the
    Technique tab, each waited for."""
    if name:
        page.click('nav button[data-t="model"]')
        example(page, name)
    if mode:
        page.click('nav button[data-t="technique"]')
        page.click(f'#modes button[data-m="{mode}"]')
        settle(page)


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


def zip_of(body):
    import io, zipfile
    return zipfile.ZipFile(io.BytesIO(body))


def still(page):
    """Wait until the view stops gliding after a drag (damping eases it a step per frame): five frames in a row with
    the camera where it was. A fixed wait ran out mid-glide on the CI runner's few frames a second, and the next press
    landed on the layer beside the one the test had picked."""
    page.evaluate("""async () => { const k = () => window.__t.camera.position.toArray().map(v => v.toFixed(4)).join();
      for (let same = 0, last = k(); same < 5;) { await new Promise(r => requestAnimationFrame(r)); const now = k(); same = now === last ? same + 1 : 0; last = now } }""")


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


ON_PART = """label => {
  // the pixel on the selected part nearest the middle of the view (not a handle, and clear of the corner cube,
  // which takes a press before the part does)
  const c = window.__t.canvas().getBoundingClientRect(), mx = (c.left + c.right) / 2, my = (c.top + c.bottom) / 2;
  let best = null, d = Infinity;
  for (let y = c.top + 20; y < c.bottom - 20; y += 6) for (let x = c.left + 20; x < c.right - 20; x += 6)
    if (Math.hypot(x - mx, y - my) < d && window.__t.hitAt(x, y) === label) { best = [x, y]; d = Math.hypot(x - mx, y - my) }
  return best;
}"""
