"""The guided tours (web/static/js/tour.js). The tour of what is new runs live on the page and puts back everything it
changed; each of its steps is a note of its version (CHANGELOG.md, the one copy of the text) with a part on the page.
A UI change that moves a part, or a note reworded, fails here rather than leaving a step that points at nothing."""
import re

import pytest

from .helpers import ROOT, menu, settle

TOUR = "(await import(new URL('static/js/tour.js', document.baseURI)))"   # the module the page itself loaded
NEW = f"async () => Object.fromEntries(Object.entries({TOUR}.NEW).map(([v, rows]) => [v, rows.map(r => [r.note, r.target])]))"
# what a tour may change and must put back
LOOK = """() => ({tab: document.querySelector('nav button.on').dataset.t,
    level: document.querySelector('#level button[aria-pressed="true"]').dataset.level,
    lamp: document.querySelector('#lamp').checked, library: document.querySelector('#library').hidden,
    menu: document.querySelector('details.menu:has(#helpbtn)').open, undo: document.querySelector('#undo').disabled})"""
# the step on show: its counter, title, and where its ring, its bubble and the part are (the part from the step table)
STEP = """t => { const d = document.querySelector('#tourdlg'); if (!d?.open) return null;
    const box = e => { const r = e?.getBoundingClientRect(); return r && [r.left, r.top, r.right, r.bottom] };
    const [n, N] = d.querySelector('.n').textContent.split(' / ').map(Number);
    return {n, N, title: d.querySelector('h4').textContent, text: d.querySelector('.tx').textContent.trim(),
            ring: box(document.querySelector('#tourring')), bubble: box(d), part: box(document.querySelector(t[n - 1])),
            W: innerWidth, H: innerHeight} }"""


def notes():
    """{version: [the bold title of each entry]} from CHANGELOG.md."""
    out = {}
    for part in re.split(r"^## +", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), flags=re.M)[1:]:
        v, body = part.split("\n", 1)
        out[v.strip()] = re.findall(r"^- \*\*(.+?)\*\*", body, flags=re.M)
    return out


def walk(page, targets, check=lambda s: None):
    """Press next through a tour already started, checking every step on the way; returns the titles seen."""
    page.wait_for_selector("#tourdlg[open]")
    seen = []
    for _ in range(len(targets) + 2):
        page.wait_for_function("n => !document.querySelector('#tourdlg').open || +document.querySelector('#tourdlg .n').textContent.split(' / ')[0] > n", arg=len(seen))
        page.wait_for_timeout(150)                     # the ring and the bubble follow on the next frame
        s = page.evaluate(STEP, targets)
        if s is None:
            return seen
        seen.append(s["title"])
        assert s["N"] == len(targets) and s["text"], s
        assert s["part"] and s["part"][2] > s["part"][0], f"step {s['n']} has no part on the page: {targets[s['n'] - 1]}"
        r, p = s["ring"], s["part"]   # the ring round the part, kept inside the window
        assert r[0] <= max(p[0], 2) + 1 and r[1] <= max(p[1], 2) + 1 and r[2] >= min(p[2], s["W"] - 2) - 1 and r[3] >= min(p[3], s["H"] - 2) - 1, s
        b = s["bubble"]
        assert b[0] >= 0 and b[1] >= 0 and b[2] <= s["W"] and b[3] <= s["H"], f"step {s['n']}: the bubble leaves the window {s}"
        check(s)
        assert not page.errors, page.errors
        page.click("#tourdlg .go")
    raise AssertionError(f"the tour did not end: {seen}")


def test_every_step_of_the_tour_of_what_is_new_is_a_note_of_its_version(page):
    new, by_version = page.evaluate(NEW), notes()
    assert new.get("0.4.0"), "no tour of what is new in 0.4.0"
    for v, rows in new.items():
        assert v in by_version, f"{v} has tour steps but no notes in CHANGELOG.md"
        gone = [n for n, _ in rows if n not in by_version[v]]
        assert not gone, f"{v}: these steps name notes CHANGELOG.md does not have: {gone}"


@pytest.mark.timeout(600)
def test_the_tour_of_what_is_new_runs_live_and_puts_everything_back(page):
    """Started from What's new, it walks every step of 0.4.0 with its part on the page, shows the light, the other
    level and the library while their steps are on, and leaves the page as it found it."""
    before = page.evaluate(LOOK)
    rows = page.evaluate(NEW)["0.4.0"]
    menu(page, "#newsbtn")
    page.wait_for_selector("#newsdlg[open] #news_tour button")
    page.click("#news_tour button")
    assert not page.locator("#newsdlg[open]").count(), "What's new stayed open over the tour"

    def live(s):
        now = page.evaluate(LOOK)
        title = rows[s["n"] - 1][0]
        assert s["title"] == title.rstrip("."), s
        if title == "Light your model.":
            assert now["lamp"] and now["tab"] == "light", now
        if title == "Settings that are easy to read.":
            assert now["level"] != before["level"], now
        if title == "Your projects in a library.":
            assert not now["library"], now
        if title.startswith("A tidy top bar"):
            assert now["menu"], now
    seen = walk(page, [t for _, t in rows], live)
    assert len(seen) == len(rows), seen
    settle(page)
    assert page.evaluate(LOOK) == before


def test_the_arrows_step_the_tour_and_esc_ends_only_the_tour(page):
    before = page.evaluate(LOOK)
    page.evaluate(f"async () => {TOUR}.start([{{target: '#find', title: 'a', text: 'one'}}, {{target: '#level', title: 'b', text: 'two'}}])")
    page.wait_for_selector("#tourdlg[open]")
    title = lambda: page.text_content("#tourdlg h4")
    assert title() == "a"
    page.keyboard.press("ArrowLeft"); page.wait_for_timeout(100)
    assert title() == "a", "the left arrow on the first step ended the tour"
    page.keyboard.press("ArrowRight"); page.wait_for_function("() => document.querySelector('#tourdlg h4').textContent === 'b'")
    page.keyboard.press("ArrowLeft"); page.wait_for_function("() => document.querySelector('#tourdlg h4').textContent === 'a'")
    page.keyboard.press("Escape"); page.wait_for_selector("#tourdlg", state="hidden")
    assert page.locator("#tourring[hidden]").count()
    assert page.evaluate(LOOK) == before
    assert not page.errors, page.errors


def test_a_step_with_nothing_to_show_is_skipped(page):
    """A part that is not on the page, or an action that throws: the step is left out and the tour goes on."""
    page.evaluate(f"""async () => {TOUR}.start([{{target: '#no-such-part', title: 'gone'}},
        {{target: '#fit', title: 'throws', open() {{ throw new Error('broken step') }}}},
        {{target: '#popen', title: 'shown', text: 'the library'}}])""")
    page.wait_for_function("() => document.querySelector('#tourdlg')?.open && document.querySelector('#tourdlg h4').textContent === 'shown'")
    assert page.text_content("#tourdlg .n") == "3 / 3"
    page.click("#tourdlg .go")
    page.wait_for_selector("#tourdlg", state="hidden")
    assert not page.errors, page.errors


@pytest.mark.timeout(600)
def test_the_tour_fits_a_phone(server, browser):
    """At 390 px wide every bubble of the tour of what is new stays inside the window, over or under its part."""
    pg = browser.new_page(viewport={"width": 390, "height": 844})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    try:
        pg.goto(server + "/"); settle(pg)
        rows = pg.evaluate(NEW)["0.4.0"]
        pg.evaluate(f"async () => {{ const n = await import(new URL('static/js/news.js', document.baseURI)); {TOUR}.start(n.tourOf(await n.news())) }}")
        assert len(walk(pg, [t for _, t in rows])) == len(rows)
    finally:
        pg.close()
