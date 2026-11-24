"""The printable assembly guide (Export tab, Build it): one card per build step, read from the document the row opens,
and the 3D view left exactly as it was."""
import math

import pytest

from .helpers import plan, use

VIEW = """async () => {
    const S = await import('/static/js/scene.js'), steps = document.querySelector('#steps');
    return {steps: steps.value, max: steps.max, explode: document.querySelector('#explode').value, bg: S.scene.background.getHex(),
            ghost: S.ghost.visible, axes: S.axes.visible, banner: S.banner.visible, canvas: [S.renderer.domElement.width, S.renderer.domElement.height],
            look: S.parts.children.map(m => [m.material.color.getHex(), !!m.material.map, m.visible, m.position.toArray()])};
}"""
CARDS = """() => [...document.querySelectorAll('.card')].map(c => ({
    num: +c.querySelector('.num').textContent, label: c.querySelector('.t').textContent, text: c.querySelector('.info').innerText,
    img: c.querySelector('img').src, svg: !!c.querySelector('svg path[fill-rule]'), frame: !!c.querySelector('.pic rect[stroke-dasharray]'),
    onto: [...c.querySelectorAll('.m')].find(m => m.textContent.startsWith('Goes onto')).textContent.replace('Goes onto', '').trim()}))"""


def guide_of(page):
    page.click('nav button[data-t="export"]')
    with page.expect_popup() as pop:
        page.click("#guide_go")
    tab = pop.value
    try:
        tab.wait_for_selector(".page", timeout=120_000)
        return tab.evaluate(CARDS), tab.locator(".page").count(), tab.inner_text(".head"), tab.get_attribute("#save", "download"), tab.url
    finally:
        tab.close()


@pytest.mark.parametrize("name, mode", [("vase", "stacked"), ("torus", "interlocked")])
def test_the_guide_has_a_card_per_part_step_and_leaves_the_3d_view_alone(page, name, mode):
    use(page, name, mode)
    before = page.evaluate(VIEW)
    cards, pages, head, save, url = guide_of(page)
    assert page.evaluate(VIEW) == before                                   # steps, explode, background, every colour and place
    labels = [pc["label"] for s in plan(page)["slices"] for pc in s["pieces"] if any(f["rings"] for f in pc["facets"])]
    assert before["max"] == str(len(labels)) and len(cards) == len(labels)           # a card for each part step
    assert [c["label"] for c in cards] == labels and [c["num"] for c in cards] == list(range(1, len(labels) + 1))
    assert pages == math.ceil(len(labels) / 6) and url.startswith("blob:") and save.endswith(".html")
    assert all(c["img"].startswith("data:image/jpeg;base64,") and len(c["img"]) > 4000 for c in cards), [(c["img"][:40], len(c["img"])) for c in cards[:3]]
    assert len({c["img"] for c in cards}) == len(cards)                    # each step has its own picture
    assert all(c["svg"] and c["frame"] and "Sheet" in c["text"] and "mm" in c["text"] for c in cards)
    assert "Assembly guide" in head and "parts" in head
    if mode == "stacked":                                                  # a layer goes onto the layer below, not onto "dowel"
        below = [pc["label"] for pc in plan(page)["slices"][0]["pieces"]]
        assert cards[0]["onto"].startswith("nothing") and cards[1]["onto"] == ", ".join(below) and "dowel" not in cards[1]["onto"]
    else:
        assert all(c["onto"] for c in cards)
