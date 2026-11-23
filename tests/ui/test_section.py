"""The section control of the 3D view: a plane square to x, y or z takes away what lies beyond it. It is a view only:
off (0) no material carries a plane, on every part and every dowel rod carries the one plane at the chosen place of the
model's extent, it follows explode, steps and a new slice, and neither the library's picture, the project nor the
session knows about it."""
import json

from .helpers import settle, use

# every material of the model (parts, their panes and nets, dowel rods) with its planes, and the model's extent on each axis
READ = """async () => { const S = await import('/static/js/scene.js'), THREE = await import('three');
  const mats = new Set(); let rods = 0, b = new THREE.Box3();
  for (const m of S.parts.children) if (m.userData.group !== 'B') { b.expandByObject(m); m.traverse(o => o.isMesh && [].concat(o.material).forEach(x => mats.add(x))) }
  for (const o of S.axes.children) if (o.isMesh) { rods++; mats.add(o.material) }
  return {rods, lo: b.min.toArray(), hi: b.max.toArray(),
          planes: [...mats].map(m => (m.clippingPlanes || []).map(p => [p.normal.toArray(), p.constant]))} }"""
SET = """([axis, pct]) => { const a = document.querySelector('#section_axis'), s = document.querySelector('#section');
  a.value = axis; a.dispatchEvent(new Event('change', {bubbles: true}));
  s.value = pct; s.dispatchEvent(new Event('input', {bubbles: true})) }"""
SLIDE = """([id, v]) => { const e = document.querySelector(id); e.value = v < 0 ? +e.max + v : v; e.dispatchEvent(new Event('input', {bubbles: true})) }"""


def section(page, axis, pct):
    page.evaluate(SET, [axis, pct])


def read(page):
    return page.evaluate(READ)


def assert_cut(page, axis, pct):
    """Every material holds exactly one plane, facing -axis, at `pct` of the way from the model's maximum down."""
    r, k = read(page), "xyz".index(axis)
    lo, hi = r["lo"][k], r["hi"][k]
    assert r["rods"] > 0, "the vase has dowel rods: they are part of the model"
    want = hi - (hi - lo) * pct / 100
    for planes in r["planes"]:
        assert len(planes) == 1, planes
        (normal, constant), = planes
        assert normal == [-1 if i == k else 0 for i in range(3)], normal
        assert abs(constant - want) <= 0.01 * (hi - lo), (constant, want, lo, hi)


def test_section_off_leaves_every_material_whole(page):
    use(page, "vase", "stacked")
    assert page.text_content("#section_val") == "off"
    assert all(planes == [] for planes in read(page)["planes"])


def test_section_cuts_parts_and_rods_at_the_chosen_place_on_the_chosen_axis(page):
    use(page, "vase", "stacked")
    section(page, "y", 50)
    assert page.text_content("#section_val") == "50 %"          # the state is in the words, not in a colour
    assert_cut(page, "y", 50)
    section(page, "x", 50)                                       # the axis changes: the plane moves to x
    assert_cut(page, "x", 50)
    section(page, "z", 100)                                      # all the way: the plane is at the model's minimum
    assert_cut(page, "z", 100)
    section(page, "z", 0)
    assert page.text_content("#section_val") == "off"
    assert all(planes == [] for planes in read(page)["planes"])  # off again: no plane, no cost


def test_section_follows_explode_and_steps_and_a_new_slice(page):
    use(page, "vase", "stacked")
    section(page, "y", 50)
    page.evaluate(SLIDE, ["#explode", 2])
    assert_cut(page, "y", 50)                                    # measured on the exploded model
    page.evaluate(SLIDE, ["#steps", -3])
    assert_cut(page, "y", 50)
    page.evaluate(SLIDE, ["#explode", 1])
    # a new slice draws new parts and rods: the setting stays and is applied to them
    page.evaluate("() => { const h = document.querySelector('#p_hide_dowels'); h.checked = !h.checked; h.dispatchEvent(new Event('input', {bubbles: true})) }")
    settle(page)
    assert page.input_value("#section") == "50" and page.input_value("#section_axis") == "y"
    assert_cut(page, "y", 50)
    section(page, "y", 0)


def test_section_is_not_saved_and_not_in_the_librarys_picture(page):
    use(page, "vase", "stacked")
    page.evaluate(SLIDE, ["#explode", 1])
    whole = page.evaluate("() => __t.snapshot()")
    section(page, "y", 50)
    assert page.evaluate("() => __t.snapshot()") == whole        # a card is always the whole model
    assert_cut(page, "y", 50)                                    # and the view has its plane back afterwards
    for saved in (page.evaluate("() => __t.project()"), page.evaluate("() => __t.state()")):   # the project file and the session
        assert "section" not in json.dumps(saved), "the section is a view, not a setting"
    section(page, "y", 0)
