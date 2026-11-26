"""The 3D view shows a slice's parts as soon as they are cut, before the sheets are nested (nearly half of a slice):
while the page is still busy the scene already holds the new slice's parts, the plan everything else reads is still
the last whole one, and a click in the view takes hold of nothing. When the slice ends the page is as it always was."""
import pytest

from .helpers import plan, set_fields, settle, use

# Watches every frame from before the change until its slice ends: the layers drawn and the plan's, the first time the
# scene holds parts that are not the plan's while the page is busy, and what a click in the middle of the view takes
WATCH = """async () => { const {ST} = await import('/static/js/state.js'), S = await import('/static/js/scene.js');
  const drawn = () => [...new Set(S.parts.children.filter(m => m.userData.group !== 'B').map(m => m.userData.slice))].sort().join(' ');
  const planned = () => ST.plan.slices.map(s => s.label).sort().join(' ');
  const c = __t.canvas().getBoundingClientRect(), x = (c.left + c.right) / 2, y = (c.top + c.bottom) / 2;
  const before = drawn(); let started = false, early = null;
  window.__watch = new Promise(done => (function look() {
    started ||= ST.busy;
    if (started && ST.busy && !early && drawn() !== before) early = {drawn: drawn(), plan: planned(), partial: !!ST.partial, hit: __t.hitAt(x, y)};
    if (started && !ST.busy) return done({before, early, after: drawn(), plan: planned(), partial: !!ST.partial, hit: __t.hitAt(x, y)});
    requestAnimationFrame(look) })());
  return before }"""


@pytest.mark.timeout(900)                             # the statue's layers, nested twice on a busy machine
def test_the_3d_view_shows_the_parts_before_the_sheets(page):
    use(page, "horse_statue")
    errors = []
    log = lambda m: m.type == "error" and errors.append(m.text)
    page.on("console", log)
    try:
        before = page.evaluate(WATCH)
        set_fields(page, [("p_thickness", plan(page)["params"]["thickness"] + 1)])   # thicker layers: fewer of them, made again
        seen = page.evaluate("() => window.__watch")
        settle(page)
    finally:
        page.remove_listener("console", log)
    early, done = seen["early"], plan(page)
    assert early, "the scene changed only when the slice was done"
    assert early["drawn"] == seen["after"] == seen["plan"] != before     # the new slice's layers, the same ones the answer drew
    assert early["plan"] == before and early["partial"]                 # while everything else still read the last whole plan
    assert early["hit"] is None and seen["hit"]                         # a click took hold of nothing, and does again once it is done
    assert not seen["partial"] and "partial" not in done and done["sheets"] >= 1 and done["timing"]
    assert not errors and not page.errors, (errors, page.errors)
