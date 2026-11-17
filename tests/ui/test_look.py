"""The 3D view tells its parts apart by more than colour (the owner is colour-blind): the second family of a
two-family technique (a radial job's ring slices, an interlocked job's Y slices) carries a stripe pattern the first
does not, under every look, and a part with errors carries a net of dark lines on top of its red."""
from .helpers import ON_PART, settle, use

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
