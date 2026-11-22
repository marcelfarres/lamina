"""The 3D view tells its parts apart by more than colour (the owner is colour-blind): the second family of a
two-family technique (a radial job's ring slices, an interlocked job's Y slices) carries a stripe pattern the first
does not, under every look, the band lattice's third family stripes the other way, and a part with errors carries a
net of dark lines on top of its red. The library's picture of the model does not change with the lamp."""
from .helpers import ON_PART, ROOT, example, settle, state, use

KINDS = """() => window.__t.parts().filter(m => m.userData.group !== 'B').map(m => ({group: m.userData.group,
  bad: m.userData.bad, striped: !!m.material.map, net: m.children.some(c => c.material?.wireframe)}))"""
OFF_PLANE = "() => window.__t.applyFix({axes: [[[-72, 0, -108], [72, 0, -108]], [[0, -72, 108], [0, 72, 108]]]})"
LUMA = """g => { const [r, gr, b] = window.__t.parts().find(m => m.userData.group === g).material.color.getStyle()
  .match(/[\\d.]+/g).map(Number); return 0.299 * r + 0.587 * gr + 0.114 * b }"""


def kinds(page, **where):
    return [k for k in page.evaluate(KINDS) if all(k[w] == v for w, v in where.items())]


def test_ring_slices_are_striped_under_every_look(page):
    use(page, "dumbbell")
    assert kinds(page, group="C") and kinds(page, group="R")
    for look in ("group", "cardboard", "foam"):                 # foam: a dark look, the stripes must show on it too
        page.select_option("#look", look)
        assert all(k["striped"] for k in kinds(page, group="C")), look
        assert not any(k["striped"] for k in kinds(page, group="R")), look
        # a ring seen edge-on shows no stripe: it differs from a fin in lightness too, under a material look as well
        luma = [page.evaluate(LUMA, g) for g in "RC"]
        assert abs(luma[0] - luma[1]) >= 40, (look, luma)
    # one texture for every striped part, made once
    assert len(set(page.evaluate("() => window.__t.parts().filter(m => m.material.map).map(m => m.material.map.uuid)"))) == 1
    assert not any(k["net"] for k in kinds(page))          # no errors, no net


def test_the_y_family_of_an_interlocked_job_is_striped(page):
    use(page, "cylinder")
    assert kinds(page, group="X") and kinds(page, group="Y")
    assert all(k["striped"] for k in kinds(page, group="Y"))
    assert not any(k["striped"] for k in kinds(page, group="X"))


def test_a_part_with_errors_carries_a_net(page):
    use(page, "dumbbell")
    # the fan axes on no plane: the half-slices lose what holds them (the case test_sheet_export's one-click fix starts from)
    page.evaluate(OFF_PLANE)
    settle(page)
    assert kinds(page, bad=True), "no part with errors to look at"
    assert all(k["net"] for k in kinds(page, bad=True))
    assert not any(k["net"] for k in kinds(page, bad=False))
    # the net takes no click: a press on a part with errors selects that part
    label = page.evaluate("() => window.__t.parts().find(m => m.userData.bad).userData.slice")
    xy = page.evaluate(ON_PART, label)
    assert xy, f"{label} not on screen"
    assert page.evaluate("([x, y]) => window.__t.pickAt(x, y)", xy) == label


def test_the_band_lattice_tells_its_three_families_apart_by_pattern(page):
    """X plain, Y striped, Z striped the other way: X and Z differ by hue only, and under a material look not at all.
    Under a material look Y and Z are also set apart from X in lightness."""
    use(page, "cube", "bands")
    for look in ("group", "cardboard"):
        page.select_option("#look", look)
        assert kinds(page, group="X") and not any(k["striped"] for k in kinds(page, group="X")), look
        assert kinds(page, group="Z") and all(k["striped"] for k in kinds(page, group="Y") + kinds(page, group="Z")), look
    turn = page.evaluate("""() => Object.fromEntries(['Y', 'Z'].map(g => [g, [...new Set(window.__t.parts()
        .filter(m => m.userData.group === g).map(m => m.material.map.uuid + ' ' + m.material.map.rotation))]]))""")
    (y,), (z,) = turn["Y"], turn["Z"]                                          # one texture a family, made once
    assert y.split()[0] != z.split()[0] and float(y.split()[1]) == -float(z.split()[1]) != 0    # the other diagonal
    luma = [page.evaluate(LUMA, g) for g in "XZ"]                               # under cardboard, the last look
    assert abs(luma[0] - luma[1]) >= 40, luma
    page.select_option("#look", "group")


LAMP = "on => { const b = document.querySelector('#lamp'); b.checked = on; b.dispatchEvent(new Event('change')) }"


def test_the_library_picture_does_not_depend_on_the_lamp(page):
    """A save made with the lamp ticked gets the picture of one made without: the lamp's dark room is a way to look at
    the model, not the model. The lamp is on again after the picture."""
    off = page.evaluate("() => window.__t.snapshot()")
    page.evaluate(LAMP, True)
    try:
        assert page.evaluate("() => window.__t.snapshot()") == off
        assert page.evaluate("() => [document.querySelector('#lamp').checked, window.__t.lamp(), document.querySelector('#light_on').checked]") == [True, True, True]
    finally:
        page.evaluate(LAMP, False)


LIT = "() => [document.querySelector('#lamp').checked, window.__t.lamp(), !!window.__t.state().light]"


def test_the_light_goes_off_when_a_model_opens(page):
    """An example or an upload opens with the light off, and the Light tab's reset turns it off: the tick was kept,
    and a big model drawn lit with its shadows is slow without a graphics card (bugs/071). The room goes back too."""
    page.evaluate(LAMP, True)
    assert page.evaluate(LIT) == [True, True, True]
    example(page, "vase")
    assert page.evaluate(LIT) == [False, False, False]
    page.evaluate(LAMP, True)
    page.set_input_files("#file", str(ROOT / "examples" / "pear.stl")); settle(page)
    assert page.evaluate(LIT) == [False, False, False]
    page.evaluate(LAMP, True)
    page.evaluate("() => { window.__t.state().room = {show: false} }")
    page.click('nav button[data-t="light"]'); page.click('button.reset[data-reset="light"]')
    assert page.evaluate(LIT) == [False, False, False]
    assert "room" not in state(page)
