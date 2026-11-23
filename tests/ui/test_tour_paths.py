"""The tour of the page by machine (web/static/js/tourpaths.js). Every path walks from the model to its machine's
export button with no step skipped, every part it rings is on the page, and every sentence it says is read from the
page: a setting's help, the help dialog's line, a technique's description. A part moved or a help line gone fails
here, not in the tour. The tour opens its machine's example only when nothing can be lost, and puts the page back."""
import pytest

from .helpers import example, menu, set_fields, settle

PATHS = "(await import(new URL('static/js/tourpaths.js', document.baseURI)))"
# the step on show, or the card on show, or None when the dialog is shut
STEP = """() => { const d = document.querySelector('#tourdlg'); if (!d?.open) return null;
    const box = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom] };
    if (d.classList.contains('card')) return {card: true, text: d.textContent, bubble: box(d), W: innerWidth, H: innerHeight};
    const [n, N] = d.querySelector('.n').textContent.split(' / ').map(Number);
    return {n, N, id: d.dataset.step, title: d.querySelector('h4').textContent.trim(), text: d.querySelector('.tx').textContent.trim(),
            ring: box(document.querySelector('#tourring')), bubble: box(d), W: innerWidth, H: innerHeight,
            tab: document.querySelector('nav button.on').dataset.t} }"""
# each paragraph of the bubble against the step's sources, read again from the page: what is not found there is the
# tour's own text (a choice's "Other choices" line is a list of the source's own names, so it is left out)
SOURCED = f"""async ([path, i]) => {{ const M = {PATHS}, s = M.PATHS[path].steps[i];
    const norm = x => (x || '').toLowerCase().replace(/`/g, '').replace(/[=:·—,.;()]/g, ' ').replace(/\\s+/g, ' ').trim();
    const pool = (s.src || []).map(q => {{ if (/^[.#]|^section|^label/.test(q)) {{ const e = document.querySelector(q);
        return e?.querySelector?.('.k[data-tip]')?.dataset.tip || e?.textContent || '' }} return M.helpOf(q) }});
    if (s.id === 'techniques') pool.push(...(await (await fetch('api/modes')).json()).map(m => m.title + ' ' + m.description));
    const src = norm(pool.join(' | '));
    const paras = [...document.querySelectorAll('#tourdlg .tx p:not(.hint), #tourdlg .tx li')].map(p => norm(p.textContent)).filter(Boolean);
    return {{empty: pool.filter(x => !x).length, paras: paras.length, foreign: paras.filter(p => !src.includes(p.slice(0, 24)))}} }}"""
NEXT = """n => { const d = document.querySelector('#tourdlg'); if (!d.open || d.classList.contains('card')) return true;
    const g = d.querySelector('.go'); return +d.querySelector('.n').textContent.split(' / ')[0] > n && g && !g.disabled }"""
LOOK = "() => ({job: window.__t.job(), state: JSON.stringify(window.__t.state()), undo: document.querySelector('#undo').disabled, clean: document.querySelector('#punsaved').hidden})"


def choose(page, path):
    menu(page, "#tourbtn")
    page.wait_for_selector("#tourdlg.card[open]")
    page.click(f'#tourdlg [data-card="{path}"]')


def walk(page, path, check=None):
    """Press next to the end of the tour, checking every step; returns the steps seen."""
    seen = []
    while True:
        page.wait_for_function(NEXT, arg=seen[-1]["n"] if seen else 0, timeout=240_000)
        page.wait_for_timeout(150)                        # the ring and the bubble follow on the next frame
        s = page.evaluate(STEP)
        if s is None or s.get("card"):
            return seen
        assert s["title"] and len(s["text"]) > 20, s
        r, b = s["ring"], s["bubble"]
        assert r[2] - r[0] > 4 and r[3] - r[1] > 4, f"{path} step {s['id']}: no ring {s}"
        assert b[0] >= 0 and b[1] >= 0 and b[2] <= s["W"] + 1 and b[3] <= s["H"] + 1, f"{path} step {s['id']}: the bubble leaves the window {s}"
        if check:
            check(s)
        assert not page.errors, page.errors
        seen.append(s)
        page.click("#tourdlg .go")


@pytest.mark.timeout(900)
@pytest.mark.parametrize("path", ["laser", "router", "printer", "mix"])
def test_every_path_walks_from_the_model_to_its_export_button(page, path):
    """On an example as it opened, the path opens its machine's example and shows every one of its steps, in order,
    with its part on the page and every paragraph read from the page; it ends on the Export tab, then offers to keep
    the example."""
    plan = page.evaluate(f"async () => {{ const p = {PATHS}.PATHS['{path}']; return {{example: p.example, ids: p.steps.map(s => s.id)}} }}")
    modes = [m["title"] for m in page.evaluate("async () => (await (await fetch('api/modes')).json())")]
    example(page, "egg")                                  # nothing to lose: the tour may open its own example

    def sourced(s):
        r = page.evaluate(SOURCED, [path, s["n"] - 1])
        assert not r["empty"] and r["paras"] and not r["foreign"], f"{path} step {s['id']}: text not read from the page: {r}"
        if s["id"] == "techniques":
            assert all(m in s["text"] for m in modes), f"a technique is not named: {modes} in {s['text']}"
    choose(page, path)
    seen = walk(page, path, sourced)
    assert [s["id"] for s in seen] == plan["ids"], f"{path}: steps skipped"
    assert seen[-1]["id"] == "x-main" and seen[-1]["tab"] == "export", seen[-1]
    page.wait_for_selector("#tourdlg.card[open]")
    assert page.evaluate("() => window.__t.job()") == "ex_" + plan["example"]
    page.click('#tourdlg [data-card="keep"]')
    page.wait_for_selector("#tourdlg", state="hidden")
    settle(page)


@pytest.mark.timeout(600)
def test_back_puts_the_page_as_it_was(page):
    example(page, "egg")
    before = page.evaluate(LOOK)
    choose(page, "laser")
    page.wait_for_function("() => document.querySelector('#tourdlg')?.dataset.step === 'techniques'", timeout=240_000)
    assert page.evaluate("() => window.__t.job()") == "ex_vase"
    page.keyboard.press("Escape")                         # ended early: the end card all the same
    page.wait_for_selector("#tourdlg.card[open]")
    page.click('#tourdlg [data-card="back"]')
    settle(page)
    assert page.evaluate(LOOK) == before


@pytest.mark.timeout(600)
def test_on_his_own_work_the_tour_only_points(page):
    example(page, "egg")
    set_fields(page, [("p_scale", 1.25)]); settle(page)  # a change not saved: there is something to lose
    before = page.evaluate(LOOK)
    assert not before["clean"], "the change did not count as unsaved"
    menu(page, "#tourbtn")
    page.wait_for_selector("#tourdlg.card[open]")
    assert "changes nothing" in page.text_content("#tourdlg")
    page.click('#tourdlg [data-card="laser"]')
    walk(page, "laser")
    page.wait_for_timeout(500)
    assert not page.locator("#tourdlg[open]").count(), "an end card on work that was only pointed at"
    settle(page)
    assert page.evaluate(LOOK) == before


def test_every_machine_has_a_path_and_every_path_an_example(page):
    r = page.evaluate(f"""async () => {{ const M = {PATHS}, C = await import(new URL('static/js/catalog.js', document.baseURI));
        return {{to: Object.fromEntries(Object.keys(C.MACHINES).map(k => [k, M.pathOf(k)])),
                 examples: Object.values(M.PATHS).map(p => p.example), have: await (await fetch('api/examples')).json()}} }}""")
    assert set(r["to"].values()) == {"laser", "router", "printer"}, r["to"]
    assert r["to"]["co2"] == "laser" and r["to"]["router"] == "router", r["to"]
    assert not [e for e in r["examples"] if e not in r["have"]], r


def visitor(browser, url, **kw):
    """A browser that has never seen Lamina and does not say it is driven by a program (the tour is never offered to one that does)."""
    ctx = browser.new_context(**kw)
    ctx.add_init_script("Object.defineProperty(Navigator.prototype, 'webdriver', {get: () => false})")
    pg = ctx.new_page(); pg.errors = []; pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(url + "/"); settle(pg)
    return ctx, pg


@pytest.mark.timeout(600)
def test_a_first_visit_is_offered_the_tour_once(server, browser):
    ctx, pg = visitor(browser, server, viewport={"width": 1500, "height": 950})
    try:
        pg.wait_for_selector("#tourdlg.card[open]", timeout=30_000)
        assert "What do you make with?" in pg.text_content("#tourdlg")
        pg.click("#tourdlg [data-card='']")              # Not now
        pg.wait_for_selector("#tourdlg", state="hidden")
        assert pg.evaluate("() => localStorage.getItem('lamina.tour')")
        pg.reload(); settle(pg); pg.wait_for_timeout(1500)
        assert not pg.locator("#tourdlg[open]").count(), "the tour was offered twice"
        # someone who had an older version: What's new, never the first-visit card
        pg.evaluate("() => { localStorage.removeItem('lamina.tour'); localStorage.setItem('slicer_seen_version', JSON.stringify('0.0.1')) }")
        pg.reload(); settle(pg); pg.wait_for_selector("#newsdlg[open]")
        pg.click("#news_go"); pg.wait_for_timeout(1500)
        assert not pg.locator("#tourdlg[open]").count(), "an update was offered the first-visit tour"
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


@pytest.mark.timeout(600)
def test_the_start_card_and_a_step_fit_a_phone(server, browser):
    ctx, pg = visitor(browser, server, viewport={"width": 390, "height": 844})
    try:
        pg.wait_for_selector("#tourdlg.card[open]", timeout=30_000)
        inside = "() => { const r = document.querySelector('#tourdlg').getBoundingClientRect(); return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight }"
        assert pg.evaluate(inside), "the start card leaves a phone's window"
        pg.click('#tourdlg [data-card="laser"]')
        pg.wait_for_function("() => document.querySelector('#tourdlg')?.dataset.step === 'model'", timeout=240_000)
        pg.wait_for_timeout(200)
        assert pg.evaluate(inside), "a step leaves a phone's window"
        assert not pg.errors, pg.errors
    finally:
        ctx.close()
