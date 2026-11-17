"""The 3D view tells its parts apart by more than colour (the owner is colour-blind): a radial job's ring slices carry
a stripe pattern its half-slices do not, under every look, and a part with errors carries a net of dark lines on
top of its red."""
from .helpers import settle, use

KINDS = """() => window.__t.parts().filter(m => m.userData.group !== 'B').map(m => ({group: m.userData.group,
  bad: m.userData.bad, striped: !!m.material.map, net: m.children.some(c => c.material?.wireframe)}))"""


def kinds(page, **where):
    return [k for k in page.evaluate(KINDS) if all(k[w] == v for w, v in where.items())]


def test_ring_slices_are_striped_under_every_look(page):
    use(page, "dumbbell")
    assert kinds(page, group="C") and kinds(page, group="R")
    for look in ("group", "cardboard"):
        page.select_option("#look", look)
        assert all(k["striped"] for k in kinds(page, group="C")), look
        assert not any(k["striped"] for k in kinds(page, group="R")), look
    assert not any(k["net"] for k in kinds(page))          # no errors, no net


def test_a_part_with_errors_carries_a_net(page):
    use(page, "dumbbell")
    # the fan axes on no plane: the half-slices lose what holds them (the case test_sheet_export's one-click fix starts from)
    page.evaluate("() => window.__t.applyFix({axes: [[[-72, 0, -108], [72, 0, -108]], [[0, -72, 108], [0, 72, 108]]]})")
    settle(page)
    assert kinds(page, bad=True), "no part with errors to look at"
    assert all(k["net"] for k in kinds(page, bad=True))
    assert not any(k["net"] for k in kinds(page, bad=False))
