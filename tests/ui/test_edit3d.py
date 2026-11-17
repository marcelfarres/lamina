"""Editing in the 3D view: curve branches, dowels, handles, lines, dragging, turning and the corner cube."""
import math
import re

import pytest

from .helpers import settle, plan, set_fields, still, ON_PART, state, use


@pytest.mark.timeout(900)
def test_a_curve_takes_a_branch_from_a_hoof(page):
    """Shift+alt-click each hoof of the horse in view, in curve mode: a branch from the curve out to it, every one
    with ribs and a spine of its own (a joint in the air between splayed legs held nothing). Alt-click on a joint
    plane reaches the leg behind it. Alt-click branch 1's rod and it is gone, parts and all, and the edit made for
    branch 2's joint stays with that leg, now branch 1."""
    use(page, "horse")
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
    branches = state(page)["branches"]
    assert len(branches) == 2 and not p["errors"], (branches, p["errors"])
    for i, (_, tip) in enumerate(branches, 1):
        assert tip[2] < -0.35 * p["bbox"][2], branches                   # its tip is down at the hoof
        own = [s["label"] for s in p["slices"] if re.match(rf"R{i}-|K{i}$", s["label"])]
        assert f"K{i}" in own and len(own) >= 4, (i, own, branches)

    curve = state(page)["curve"]
    x, y = page.evaluate("""() => {   // a pixel on a joint plane with a part behind it
      const c = window.__t.canvas().getBoundingClientRect(), B = window.__t.parts().filter(m => m.userData.group === 'B');
      const at = (x, y) => window.__t.hit({clientX: x, clientY: y});
      for (let y = c.top + 10; y < c.bottom - 10; y += 4) for (let x = c.left + 10; x < c.right - 10; x += 4) {
        if (at(x, y)?.object.userData.group !== 'B') continue;
        B.forEach(m => m.visible = false); const h = at(x, y); B.forEach(m => m.visible = true);
        if (h?.object.userData.slice) return [x, y] } }""")
    page.keyboard.down("Alt"); page.mouse.click(x, y); page.keyboard.up("Alt")
    settle(page)
    assert state(page)["curve"] != curve      # a curve point at the leg, not a dead click

    page.evaluate("() => { window.__t.state().offset = {'J-2': 4} }")
    a, b = branches[0]
    x, y = page.evaluate("p => window.__t.screen(p)", [(u + v) / 2 for u, v in zip(a, b)])
    page.keyboard.down("Alt"); page.mouse.click(x, y); page.keyboard.up("Alt")
    settle(page)
    assert state(page)["branches"] == branches[1:]
    assert state(page)["offset"] == {"J-1": 4}
    assert not [s["label"] for s in plan(page)["slices"] if re.match(r"R2-|K2$", s["label"])]


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
    use(page, "horse", "stacked")
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
    use(page, mode="stacked")
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
        still(page)
        settle(page)
        return page.evaluate("l => [(window.__t.state().offset || {})[l] || 0, (window.__t.state().tilt || {})[l] || 0]", label)

    assert drag() == [0, 0], "a plain drag on the part moved it"
    assert drag("Shift")[1] != 0, "shift-drag on the part no longer tilts it"


@pytest.mark.timeout(600)
def test_a_line_added_with_the_button_places_dowels(page):
    """+ line used to add 0,0,0 → 0,0,0: a line nothing crosses, so no dowel, and a stack with a gap then lost its
    layers to autofix (reported). Two presses now give two lines up the model, a dowel through every layer they meet,
    and every layer stays. On the torus, where a line a fixed distance out from the middle fell in its hole."""
    use(page, "torus")
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


def test_a_drag_while_a_slice_runs_turns_the_view_not_the_model(page):
    """Reported: the statue "is not there if you move it before it is complete". Picked from the list on the Model
    tab, the turn rings still had the last model's size, and a drag across the middle of the view to look round
    caught one: the statue was turned upside down (rotate x = -162) and sliced again with ten errors. While a slice
    runs a drag turns the view only."""
    use(page, "head_igea")
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
    assert state(page)["rotate"] == [0, 0, 0]
    assert plan(page)["counts"]["errors"] == 0


def test_a_turn_keeps_the_model_s_size(page):
    """Reported: a bear sized 500 mm tall, stood up along x (up axis), came back 763 × 566 × 500 — `size` aimed at
    whatever lay along z after the turn. Size belongs to the model now: through the up axis (x and y), a quarter
    turn and a typed turn the model keeps its size, the number stays the model's z, and the box of the view axis that
    dimension lies along is the one that shows it."""
    page.click('nav button[data-t="model"]')
    set_fields(page, [("p_size_2", 100)]); settle(page)
    before = sorted(plan(page)["bbox"])
    assert plan(page)["bbox"][2] == pytest.approx(100, abs=0.1)
    boxes = lambda: [page.input_value(f"#p_size_{i}") for i in range(3)]
    size = lambda: state(page)["size"]
    for up, box in (("x", 0), ("y", 0), ("z", 2)):            # the file's z lies along the view's x once x or y is up (the slicer's own turn)
        page.select_option("#p_up_axis", up); settle(page)
        assert size() == [0, 0, 100] and boxes()[box] == "100" and [b for b in boxes() if b] == ["100"], (up, boxes())
        assert sorted(plan(page)["bbox"]) == pytest.approx(before, abs=0.5)
    page.click('button[data-rot="1"]'); settle(page)          # a quarter turn about y: the 100 now lies along x
    assert size() == [0, 0, 100] and boxes()[0] == "100" and sorted(plan(page)["bbox"]) == pytest.approx(before, abs=0.5)
    set_fields(page, [("p_rotate_1", 0), ("p_rotate_0", 90)]); settle(page)   # typed turns, as the sliders send them: along y now
    assert size() == [0, 0, 100] and boxes()[1] == "100" and sorted(plan(page)["bbox"]) == pytest.approx(before, abs=0.5)
    set_fields(page, [("p_size_1", 50)]); settle(page)        # typed into the box it shows in, it is still the model's z
    assert size() == [0, 0, 50] and plan(page)["bbox"][1] == pytest.approx(50, abs=0.1)
    page.click("#origsize"); settle(page)


def test_the_cube_snaps_on_a_click_and_a_drag_turns_the_view_not_the_model(page):
    """Reported from a Mac: a drag on the corner cube "moves a bit then jumps to the next face", and a drag on the
    model after it sliced the model again. The cube snapped on press while the orbit's own drag ran on under it; and
    in the flat view it gave, two turn rings are edge-on lines through the model, which the next drag grabbed. Now a
    click on the cube gives the flat view, a drag on it turns the view, and a drag on the model in a flat view turns
    the view only."""
    use(page, mode="stacked")   # the reporter's technique: rings, no axis rod through the middle
    page.click('nav button[data-t="model"]')
    page.click("#fit"); still(page)
    cv = page.locator("#v3d canvas").first.bounding_box()
    cube = (cv["x"] + cv["width"] - 10 - 46, cv["y"] + cv["height"] - 10 - 46)   # the cube's centre: a 92 px square 10 px in from the bottom right
    look = lambda: page.evaluate("() => window.__t.camera.position.clone().sub(window.__t.target()).normalize().toArray()")
    flat = lambda v: max(abs(c) for c in v) > 0.999
    assert not flat(look())
    page.mouse.click(*cube); page.wait_for_timeout(500); still(page)
    assert flat(look()), look()                                   # a click: the flat view of the face under the pointer
    page.mouse.move(*cube); page.mouse.down(); page.mouse.move(cube[0] - 80, cube[1] + 40, steps=8); page.mouse.up(); still(page)
    assert not flat(look()), look()                               # a drag: the view turned, no face snapped to
    page.mouse.click(*cube); page.wait_for_timeout(500); still(page)
    assert flat(look())
    cx, cy = cv["x"] + cv["width"] / 2, cv["y"] + cv["height"] / 2   # the model's centre, where the edge-on rings run
    page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 120, cy + 30, steps=8); page.mouse.up(); still(page)
    assert not flat(look())
    assert state(page)["rotate"] == [0, 0, 0]
    assert page.evaluate("() => window.__t.idle()")


def test_a_seam_is_chosen_on_the_model_or_on_a_sheet_and_shows_on_both(page):
    """Asked for: to say where a folded model is cut apart. With the `put a seam` tool, a click on an edge of the model
    puts a seam there and a click on an edge of the net does the same; the edge under the pointer lights up in both
    views; a seam of the user's is marked on the model and on both panel edges it lies on; a click on it gives it back;
    a drag along an edge paints a seam, and turns nothing: in this tool the right button turns the view."""
    # the middle of an edge of one kind: on the model (facing the camera, nearest the middle of the view) and on a sheet
    on_model = """kind => { const cam = __t.camera, V3 = cam.position.constructor, r = __t.canvas().getBoundingClientRect(); let best = null;
      for (const e of __t.plan().edges3d) { if (e[1] !== kind) continue; const mid = new V3(...e[2]).add(new V3(...e[3])).multiplyScalar(.5), to = mid.clone().sub(cam.position);
        if (new V3(...e[4]).dot(to) > -0.5 * to.length()) continue; const q = mid.clone().project(cam), x = r.left + (q.x + 1) / 2 * r.width, y = r.top + (1 - q.y) / 2 * r.height;
        const d = Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2)); if (!best || d < best.d) best = {k: e[0], x, y, d} }
      return best }"""
    on_sheet = """kind => { const K = new Map(__t.plan().edges3d.map(e => [e[0], e[1]]));
      const l = [...document.querySelectorAll('#sheets line.hit')].find(l => K.get(+l.dataset.k) === kind); l.scrollIntoView({block: 'center'});
      const b = l.getBoundingClientRect(); return {k: +l.dataset.k, x: b.left + b.width / 2, y: b.top + b.height / 2} }"""
    seen = """() => { const p = __t.plan(), n = k => p.edges3d.filter(e => e[1] === k).length;
      return {yours: __t.state().seams.length, chosen: n('chosen'), cut: n('chosen') + n('seam'), panels: p.slices.filter(s => s.group === 'F').length,
              marks: document.querySelectorAll('#sheets line.mine').length, lit: document.querySelectorAll('#sheets line.hov').length, hover: __t.seams().hover,
              tip: document.getElementById('seamtip').hidden ? '' : document.getElementById('seamtip').innerText} }"""
    top = lambda: page.evaluate("() => document.getElementById('v3d').scrollIntoView()")   # noqa: E731
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="folded"]'); settle(page)
    set_fields(page, [("p_facet", 30)]); page.wait_for_timeout(600); settle(page)
    page.click("#fit")
    start = page.evaluate(seen)
    assert start["yours"] == start["chosen"] == start["marks"] == 0 and not page.is_visible("#seampanel")
    assert not page.evaluate("() => window.__t.seams().shown")               # no edge lines until they are asked for
    page.click('#tools button[data-tool="seam"]')
    assert page.is_visible("#seampanel") and page.evaluate("() => window.__t.seams().shown")
    assert not page.query_selector('[data-p="seams"] [data-seams="mode"]')    # one place to start it: the tool
    # on the model: the fold under the pointer lights up there and on its sheet, and says what a click does
    top(); e = page.evaluate(on_model, "fold"); page.mouse.move(e["x"], e["y"]); page.wait_for_timeout(200)
    s = page.evaluate(seen)
    assert s["hover"] == e["k"] and s["lit"] == 1 and "put a seam here" in s["tip"], s
    page.mouse.click(e["x"], e["y"]); page.wait_for_timeout(600); settle(page)
    s = page.evaluate(seen)
    assert s["yours"] == s["chosen"] == 1 and s["marks"] == 2, s            # a seam lies on two panel edges
    assert page.evaluate("k => window.__t.plan().edges3d.find(e => e[0] === k)[1]", e["k"]) == "chosen"
    assert s["cut"] - s["panels"] == start["cut"] - start["panels"]         # as many seams as before, per panel: one of the program's went
    # on a sheet: the same, and the edge lights up on the model
    f = page.evaluate(on_sheet, "fold"); page.mouse.move(f["x"], f["y"]); page.wait_for_timeout(200)
    s = page.evaluate(seen)
    assert s["hover"] == f["k"] and s["lit"] == 1 and "put a seam here" in s["tip"], s
    page.mouse.click(f["x"], f["y"]); page.wait_for_timeout(600); settle(page)
    s = page.evaluate(seen)
    assert s["yours"] == s["chosen"] == 2 and s["marks"] == 4, s
    # a click on a seam of the user's gives the edge back to the program
    top(); g = page.evaluate(on_model, "chosen"); page.mouse.move(g["x"], g["y"]); page.wait_for_timeout(200)
    s = page.evaluate(seen)
    assert s["lit"] == 2 and "your seam" in s["tip"], s
    page.mouse.click(g["x"], g["y"]); page.wait_for_timeout(600); settle(page)
    s = page.evaluate(seen)
    assert s["yours"] == s["chosen"] == 1 and s["marks"] == 2, s
    page.click('#seampanel [data-seams="clear"]'); page.wait_for_timeout(600); settle(page)
    assert page.evaluate(seen)["yours"] == 0 and page.evaluate(seen)["chosen"] == 0
    # a drag along a fold paints it: one seam, one slice, and the view did not turn; the right button turns it
    ends = """() => { const cam = __t.camera, V3 = cam.position.constructor, r = __t.canvas().getBoundingClientRect(), at = p => { const q = new V3(...p).project(cam); return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height] };
      for (const e of __t.plan().edges3d) { if (e[1] !== 'fold') continue; const to = new V3(...e[2]).sub(cam.position); if (new V3(...e[4]).dot(to) > -0.7 * to.length()) continue;
        const A = at(e[2]), B = at(e[3]), mid = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2]; if (Math.hypot(A[0] - B[0], A[1] - B[1]) > 40 && Math.hypot(mid[0] - r.left - r.width / 2, mid[1] - r.top - r.height / 2) < 120) return {A, B} } }"""
    eye = lambda: page.evaluate("() => window.__t.camera.position.toArray()")   # noqa: E731
    top(); d = page.evaluate(ends); was = eye()
    (ax, ay), (bx, by) = d["A"], d["B"]
    page.mouse.move(ax + (bx - ax) * 0.2, ay + (by - ay) * 0.2); page.mouse.down(); page.mouse.move(ax + (bx - ax) * 0.8, ay + (by - ay) * 0.8, steps=8); page.mouse.up()
    page.wait_for_timeout(600); settle(page)
    s = page.evaluate(seen)
    assert s["yours"] == s["chosen"] >= 1 and eye() == was, s
    page.mouse.move(ax, ay); page.mouse.down(button="right"); page.mouse.move(ax + 80, ay, steps=6); page.mouse.up(button="right")
    assert eye() != was
    page.keyboard.press("Escape")
    assert not page.is_visible("#seampanel") and not page.evaluate("() => window.__t.seams().shown")
    assert page.get_attribute('#tools button[data-tool=""]', "aria-pressed") == "true"


@pytest.mark.timeout(600)                         # ten slices of the egg: 166 s on a busy machine
def test_faces_are_selected_removed_and_stay_removed_when_the_faces_are_made_again(page):
    """Asked for: to keep only a part of a folded model (a mask from a head). With the `select faces` tool a click or a
    drag selects faces, `grow` and `connected` add to the selection, `remove` takes the faces off: they are not cut,
    and they stay off when the face size changes. A click on a removed face puts it back; undo puts back a remove."""
    here = """() => { const r = __t.canvas().getBoundingClientRect(), f = __t.faces(); let best = null;   // a point on a face, or on a removed one, nearest the middle of the view
      for (let x = r.left + 80; x < r.right - 80; x += 9) for (let y = r.top + 100; y < r.bottom - 120; y += 9) { const u = f.under(x, y); if (!u) continue;
        const d = Math.hypot(x - r.left - r.width / 2, y - r.top - r.height / 2), k = u.ghost !== undefined ? 'ghost' : 'face'; if (!best?.[k] || d < best[k].d) (best ||= {})[k] = {x, y, d, i: u[k]} }
      return best }"""
    seen = """() => { const p = __t.plan(), f = __t.faces(); return {faces: p.faces3d.f.length, off: p.faces3d.removed, places: (__t.state().removed || []).length, sel: f.selected.length, ghosts: f.ghosts,
      area: p.slices.filter(s => s.group === 'F').reduce((a, s) => a + s.pieces.reduce((b, c) => b + c.area, 0), 0), bar: document.getElementById('facebar').innerText, errors: p.errors} }"""
    tools = lambda: page.evaluate("() => [...document.querySelectorAll('#tools button')].filter(b => !b.hidden).map(b => b.dataset.tool)")   # noqa: E731
    eye = lambda: page.evaluate("() => window.__t.camera.position.toArray()")   # noqa: E731
    wait = lambda: (page.wait_for_timeout(600), settle(page))   # noqa: E731
    use(page, "egg", "folded"); assert tools() == ["", "seam", "face"]
    set_fields(page, [("p_facet", 30)]); wait(); page.click("#fit")
    page.evaluate("() => document.getElementById('v3d').scrollIntoView()")
    whole = page.evaluate(seen)
    assert whole["off"] == whole["places"] == 0 and not page.is_visible("#facebar")
    page.click('#tools button[data-tool="face"]')
    assert page.is_visible("#facebar") and page.evaluate("() => window.__t.faces().shown") and "none removed" in whole["bar"] + page.evaluate(seen)["bar"]
    # a click selects one face; grow adds the faces across its edges, but not across a seam of the user's; a drag
    # paints more, and does not turn the view
    p = page.evaluate(here)["face"]
    page.evaluate("i => { const F = __t.plan().faces3d, [a, b] = F.adj.find(e => e.includes(i)); __t.applyFix({seams: [F.f[a].filter(v => F.f[b].includes(v)).map(v => F.v[v])]}) }", p["i"]); wait()
    assert len(state(page)["seams"]) == 1 and page.evaluate(here)["face"]["i"] == p["i"]
    page.mouse.click(p["x"], p["y"])
    assert page.evaluate("() => window.__t.faces().selected") == [p["i"]]
    page.click('[data-faces="grow"]'); assert page.evaluate(seen)["sel"] == 3
    was = eye(); page.mouse.move(p["x"] - 70, p["y"] - 40); page.mouse.down(); page.mouse.move(p["x"] + 70, p["y"] + 40, steps=14); page.mouse.up()
    n = page.evaluate(seen)["sel"]; assert n > 3 and eye() == was, n
    page.click('[data-faces="remove"]'); wait()
    s = page.evaluate(seen)
    assert s["faces"] == whole["faces"] - n and s["off"] == s["places"] == s["ghosts"] == n and s["sel"] == 0 and f"{n} removed" in s["bar"], s
    assert s["area"] < whole["area"] and not s["errors"]
    # the seam was on an edge of a face that went: it went with it, and nothing says a seam was lost
    assert state(page)["seams"] == [] and "on no edge" not in page.inner_text("#seam_n")
    # the faces made again at another size: the same places are off, without a click
    set_fields(page, [("p_facet", 20)]); wait()
    t = page.evaluate(seen)
    assert t["places"] == n and t["off"] > 0 and abs(t["area"] - s["area"]) < 0.15 * s["area"], (s, t)
    # a click on a removed face puts that place back; the button puts all back
    page.evaluate("() => document.getElementById('v3d').scrollIntoView()")
    g = page.evaluate(here)["ghost"]; page.mouse.click(g["x"], g["y"]); wait()
    assert page.evaluate(seen)["places"] == n - 1
    page.click('#facebar [data-faces="back"]'); wait()
    back = page.evaluate(seen); assert back["places"] == back["off"] == back["ghosts"] == 0, back
    # connected with no seam of the user's in the way takes every face: an error, nothing to cut, and undo brings them back
    p = page.evaluate(here)["face"]; page.mouse.click(p["x"], p["y"]); page.click('[data-faces="connected"]')
    assert page.evaluate(seen)["sel"] == back["faces"]
    page.click('[data-faces="remove"]'); wait()
    gone = page.evaluate(seen); assert gone["faces"] == 0 and any("every face" in e for e in gone["errors"]) and gone["ghosts"] == back["faces"], gone
    page.click("#undo"); wait()
    assert page.evaluate(seen)["faces"] == back["faces"] and page.evaluate(seen)["places"] == 0
    page.keyboard.press("Escape")
    assert not page.is_visible("#facebar") and page.get_attribute('#tools button[data-tool=""]', "aria-pressed") == "true"
