"""Marcel's interface test as page tests: each test opens the example a step of it names and checks what that step
says he should see. Steps 1, 2, 3, 5 and 12 are in test_misc, test_library, test_look, test_standoff and test_misc."""
import json

import numpy as np
import pytest
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from .helpers import EDGE_ON_MODEL, ROOT, plan, set_fields, settle, state, use

LIGHTS = "async () => (await window.__t.project()).state.lights"
# the point nearest the middle of the view on a face of its own (not removed, not in a merged face)
OWN_FACE = """() => { const r = __t.canvas().getBoundingClientRect(), f = __t.faces(), m = __t.plan().faces3d.merged; let best = null;
  for (let x = r.left + 80; x < r.right - 80; x += 9) for (let y = r.top + 100; y < r.bottom - 120; y += 9) { const u = f.under(x, y);
    if (u?.face === undefined || m[u.face] >= 0) continue; const d = Math.hypot(x - r.left - r.width / 2, y - r.top - r.height / 2); if (!best || d < best.d) best = {x, y, d, i: u.face} }
  return best }"""


def open_ends(p, name):
    """How many ends of a stacked job's dowel holes are open on a step, of how many: the model sectioned at the layer
    under each dowel's pair and at the layer over it (as tests/test_hide_dowels.py does), and the hole not wholly in
    the section."""
    from core.geometry import section_polygons
    from core.mesh import load_mesh
    from core.plan import MODES, coerce_params
    mesh = load_mesh(ROOT / "examples" / f"{name}.stl", coerce_params(MODES["stacked"], p["params"]), [])
    zs = sorted(s["M"][2][3] for s in p["slices"]); ends = []
    for a, b, d, *_ in p["rods"]:
        lo, hi = sorted((a[2], b[2]))
        for z in [z for z in zs if z < lo - 1e-6][-1:] + [z for z in zs if z > hi + 1e-6][:1]:
            M = np.eye(4); M[2, 3] = z
            ends.append(not section_polygons(mesh, M).contains(Point(a[:2]).buffer(d / 2)))
    return sum(ends), len(ends)


def test_hide_dowels_on_the_vase_leaves_no_dowel_hole_open_on_a_step(page):
    """Step 6: the vase on the Stacked card, hide dowels on. The vase tapers, so the layer beyond a pair of layers can
    stop short of a dowel's hole and leave it open on the step. Ticked, every hole is covered by the layer under its
    pair and the one over it, and the pairs keep their dowels."""
    use(page, "vase", "stacked")
    before = plan(page); was, _ = open_ends(before, "vase")
    assert was > 0, "the vase shows no open hole without hide dowels: the step tests nothing"
    set_fields(page, [("p_hide_dowels", True)]); settle(page)
    p = plan(page); now, ends = open_ends(p, "vase")
    assert p["params"]["hide_dowels"] and now == 0 and ends, (was, now, ends)
    assert len(p["rods"]) >= 0.8 * len(before["rods"]), (len(p["rods"]), len(before["rods"]))


def test_the_paper_lamp_opens_with_paper_windows_and_takes_another_merge(page):
    """Step 7: paper_lamp opens with its windows closed with paper: a paper part for each window, cut from sheets of
    paper. With the select-faces tool a click on a face, grow and merge make more of its faces one flat face, kept by
    the slice, with no warning about it."""
    use(page, "paper_lamp")
    p = plan(page)
    assert p["params"]["window_fill"] == "paper" and any(s["label"].startswith("W-") for s in p["slices"]) and "paper" in p["sheet_stock"]
    flat = lambda: sum(g >= 0 for g in plan(page)["faces3d"]["merged"])   # noqa: E731  faces in a merged face
    before = flat()
    page.click("#fit"); page.evaluate("() => document.getElementById('v3d').scrollIntoView()")
    page.click('#tools button[data-tool="face"]')
    q = page.evaluate(OWN_FACE)
    assert q, "no face of its own in view"
    page.mouse.click(q["x"], q["y"]); page.click('[data-faces="grow"]')
    assert page.evaluate("() => window.__t.faces().selected.length") > 1
    page.click('[data-faces="merge"]'); page.wait_for_timeout(600); settle(page)
    p = plan(page)
    assert flat() > before and not [w for s in p["slices"] for w in s["warnings"] if "merged" in w] and p["counts"]["errors"] == 0
    page.keyboard.press("Escape")


def test_the_fold_lamp_is_lit_a_spot_is_added_and_dragged_and_the_steps_end_folded(page):
    """Step 8: fold_lamp, the light ticked over the 3D view. On the Light tab a second light is added and made a spot;
    the move-a-light tool drags it across the view: it moves and the first light stays. At the end of the steps
    slider the panels are folded up."""
    use(page, "fold_lamp")
    page.check("#lamp"); page.click('nav button[data-t="light"]')
    page.click("#g-light button[data-act=add]")
    page.select_option("#g-light select[data-l=like]", "gu10")                 # the tab shows the light just added
    page.eval_on_selector("#lt_p0", "e => { e.value = 40; e.dispatchEvent(new Event('input', {bubbles: true})) }")   # apart from the first
    first, spot = page.evaluate(LIGHTS)
    assert spot["like"] == "gu10" and spot["pos"][0] == 40, spot
    page.click("#tools button[data-tool=light]")
    x, y = page.evaluate("""async () => { const m = await import(location.origin + '/static/js/scene.js');
      const l = m.scene.getObjectsByProperty('isLight', true).filter(x => x.castShadow && x.parent.visible).sort((a, b) => b.position.x - a.position.x)[0];
      return window.__t.screen(l.position.toArray()) }""")
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 30, y + 20, steps=3); page.mouse.move(x + 60, y + 40, steps=3); page.mouse.up()
    now = page.evaluate(LIGHTS)
    assert now[0]["pos"] == first["pos"] and now[1]["pos"] != spot["pos"] and now[1]["like"] == "gu10", (first, spot, now)
    page.keyboard.press("Escape")
    n = int(page.get_attribute("#steps", "max"))
    page.evaluate("k => { const e = document.getElementById('steps'); e.value = k; e.dispatchEvent(new Event('input')) }", n)
    page.wait_for_timeout(300)
    assert float(page.input_value("#fold")) == 1 and page.evaluate("() => window.__t.banner()") == ""


def test_the_fold_box_takes_the_click_joint_then_the_snap_joint(page):
    """Step 10: fold_box, joint click, then snap. Click: walls on the panels and no part of its own, and the click's
    own settings show. Snap: a clip for every seam, a part of its own drawn in the 3D view, on two walls each; the
    click's settings go. Neither is an error."""
    use(page, "fold_box")
    page.click('nav button[data-t="technique"]'); page.click('#level button[data-level="all"]')
    shown = lambda n: page.locator(f'.f[data-p="{n}"]').is_visible()   # noqa: E731
    walls = lambda p: sum(len(pc.get("rails") or []) for s in p["slices"] for pc in s["pieces"])   # noqa: E731
    clips = lambda p: [s["label"] for s in p["slices"] if s["group"] == "J"]   # noqa: E731
    try:
        page.select_option("#p_joint", "click"); settle(page); p = plan(page)
        assert p["params"]["joint"] == "click" and walls(p) > 10 and not clips(p) and p["counts"]["errors"] == 0, p["counts"]
        assert shown("click_size") and shown("snap_h")
        page.select_option("#p_joint", "snap"); settle(page); p = plan(page); k = clips(p)
        assert len(k) >= 11 and all(x.startswith("K-") for x in k) and walls(p) == 2 * len(k) and p["counts"]["errors"] == 0, p["counts"]
        assert not shown("click_size") and shown("snap_fit")
        assert set(k) <= set(page.evaluate("() => window.__t.parts().map(m => m.userData.slice)"))
    finally:
        page.click('#level button[data-level="basic"]')                 # the level is the browser's, not the tab's: put back


def test_the_cow_as_a_plaque_offers_two_fixes_and_one_click_makes_it_stand(page):
    """Step 11 (bug 060): the cow on the Plaque card touches its plate with one hoof, so nothing stands on it: an
    error, said as one, with two one-click fixes. One click on the first slices it again with what that fix sets,
    and the cow stands, with no error."""
    use(page, "cow", "plaque")
    msg = page.locator("#msgs .msg.err", has_text="nothing stands on the plate")
    assert msg.count() == 1 and msg.inner_text().startswith("✖ ERROR") and msg.locator(".fix").count() == 2
    fix = json.loads(msg.locator(".fix").first.get_attribute("data-fix"))
    msg.locator(".fix").first.click(); settle(page)
    p, st = plan(page), state(page)
    assert p["counts"]["errors"] == 0 and p["counts"]["parts"] > 5 and all(st[k] == v for k, v in fix.items()), (p["counts"], fix)
    assert not page.locator("#msgs .msg.err", has_text="nothing stands").count()


@pytest.mark.timeout(900)                         # 66 layers, 480 parts: 166 s on an idle machine, twice that on a busy one
def test_the_head_as_ring_slices_stands_on_dowels_and_its_long_rings_are_cut_with_puzzle_tabs(page):
    """Step 4: head_igea on the Stacked card, ring slices ticked, max piece length 60. Every pair of layers is held by
    dowels; a ring longer than 60 mm is cut across its wall into pieces that long at most (with its wall and a tab),
    and most cuts get a puzzle tab: a cut with no room for one is said."""
    use(page, "head_igea", "stacked")
    set_fields(page, [("p_ring_slices", True), ("p_max_length", 60)]); settle(page, timeout=480_000)
    p = plan(page); sl = p["slices"]
    assert p["params"]["ring_slices"] and p["params"]["max_length"] == 60
    held = {(s["label"], t["label"]) for s, t in zip(sl, sl[1:])}
    assert len(p["rods"]) >= len(held), (len(p["rods"]), len(held))
    cuts = sum(len(s["pieces"]) - 1 for s in sl)
    plain = sum(int(w.split(" of its ")[0]) for s in sl for w in s["warnings"] if "no room for a puzzle tab" in w)
    assert cuts >= len(sl) and 2 * plain < cuts, (cuts, plain)
    for s in sl:
        for pc in s["pieces"]:
            x0, y0, x1, y1 = unary_union([Polygon(r[0], r[1:]) for f in pc["facets"] for r in f["rings"]]).bounds
            assert np.hypot(x1 - x0, y1 - y0) <= 60 + 12 + 2 * 8, (pc["label"], x1 - x0, y1 - y0)   # the wall and a tab, as tests/test_piece_length.py
    assert not [w for s in sl for w in s["warnings"] if "longer than `max_length`" in w], p["counts"]


@pytest.mark.timeout(600)
def test_the_lion_head_loses_faces_and_its_panels_lie_round_a_seam_put_on_it(page):
    """Step 9: lion_head. With the select-faces tool a click, grow and remove take faces off: they are not cut. With the
    put-a-seam tool a click on a fold of the model makes it a seam of the user's: the net is cut apart there, so the
    panels lie round it, and it is marked on both panel edges it lies on."""
    wait = lambda: (page.wait_for_timeout(600), settle(page))   # noqa: E731
    top = lambda: page.evaluate("() => document.getElementById('v3d').scrollIntoView()")   # noqa: E731
    use(page, "lion_head")
    whole = plan(page); area = lambda p: sum(pc["area"] for s in p["slices"] if s["group"] == "F" for pc in s["pieces"])   # noqa: E731
    page.click("#fit"); top()
    page.click('#tools button[data-tool="face"]')
    q = page.evaluate(OWN_FACE); assert q, "no face in view"
    page.mouse.click(q["x"], q["y"]); page.click('[data-faces="grow"]')
    n = page.evaluate("() => window.__t.faces().selected.length"); assert n > 1
    page.click('[data-faces="remove"]'); wait()
    p = plan(page)
    assert p["faces3d"]["removed"] == n and len(p["faces3d"]["f"]) == len(whole["faces3d"]["f"]) - n and area(p) < area(whole), p["counts"]
    page.keyboard.press("Escape")
    page.click('#tools button[data-tool="seam"]'); top()
    e = page.evaluate(EDGE_ON_MODEL, "fold"); assert e, "no fold in view"
    page.mouse.move(e["x"], e["y"]); page.wait_for_timeout(200); page.mouse.click(e["x"], e["y"]); wait()
    p = plan(page)
    assert len(state(page)["seams"]) == 1 and dict((x[0], x[1]) for x in p["edges3d"])[e["k"]] == "chosen"
    assert page.locator("#sheets line.mine").count() == 2 and p["counts"]["errors"] == 0   # on the two panel edges it lies on
    page.keyboard.press("Escape")
