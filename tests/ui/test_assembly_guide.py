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
# Each card's picture, decoded: the share of its frame in colour, and the share of the coloured pixels outside the frame.
# Colour is the new part, or its blue stripes where built parts hide it: those are grey with grey edge lines, the ground white.
DRAWN = """() => Promise.all([...document.querySelectorAll('.card')].map(async c => {
    const img = c.querySelector('img'), r = c.querySelector('.pic rect[stroke-dasharray]'), [x, y, w, h] = ['x', 'y', 'width', 'height'].map(a => +r.getAttribute(a));
    await img.decode();
    const cv = Object.assign(document.createElement('canvas'), {width: img.naturalWidth, height: img.naturalHeight}), g = cv.getContext('2d');
    g.drawImage(img, 0, 0);
    const d = g.getImageData(0, 0, cv.width, cv.height).data; let inside = 0, out = 0;
    for (let i = 0; i < d.length; i += 4) {
        if (Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2]) < 24) continue;
        const px = (i / 4) % cv.width, py = Math.floor(i / 4 / cv.width);
        px >= x && px < x + w && py >= y && py < y + h ? inside++ : out++;
    }
    return [inside / (w * h), out / Math.max(1, inside + out)];
}))"""


def guide_of(page):
    page.click('nav button[data-t="export"]')
    with page.expect_popup() as pop:
        page.click("#guide_go")
    tab = pop.value
    try:
        tab.wait_for_selector(".page", timeout=120_000)
        return tab.evaluate(CARDS), tab.evaluate(DRAWN), tab.locator(".page").count(), tab.inner_text(".head"), tab.get_attribute("#save", "download"), tab.url
    finally:
        tab.close()


@pytest.mark.parametrize("name, mode", [("vase", "stacked"), ("torus", "interlocked")])
def test_the_guide_has_a_card_per_part_step_and_leaves_the_3d_view_alone(page, name, mode):
    use(page, name, mode)
    before = page.evaluate(VIEW)
    cards, drawn, pages, head, save, url = guide_of(page)
    assert page.evaluate(VIEW) == before                                   # steps, explode, background, every colour and place
    labels = [pc["label"] for s in plan(page)["slices"] for pc in s["pieces"] if any(f["rings"] for f in pc["facets"])]
    assert before["max"] == str(len(labels)) and len(cards) == len(labels)           # a card for each part step
    assert [c["label"] for c in cards] == labels and [c["num"] for c in cards] == list(range(1, len(labels) + 1))
    assert pages == math.ceil(len(labels) / 6) and url.startswith("blob:") and save.endswith(".html")
    assert all(c["img"].startswith("data:image/jpeg;base64,") for c in cards)
    cover, stray = zip(*drawn)                                             # each picture shows its new part, in its frame
    assert min(cover) > 0.15 and max(stray) < 0.02     # measured 0.27-0.46 and at most 0.004; a part hidden behind built ones, unmarked, gave 0.017
    assert len({c["img"] for c in cards}) == len(cards)                    # each step has its own picture
    assert all(c["svg"] and c["frame"] and "Sheet" in c["text"] and "mm" in c["text"] for c in cards)
    assert "Assembly guide" in head and "parts" in head
    if mode == "stacked":                                                  # a layer goes onto the layer below, not onto "dowel"
        below = [pc["label"] for pc in plan(page)["slices"][0]["pieces"]]
        assert cards[0]["onto"].startswith("nothing") and cards[1]["onto"] == ", ".join(below) and "dowel" not in cards[1]["onto"]
    else:
        assert all(c["onto"] for c in cards)
