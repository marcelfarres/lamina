"""The rest: the report dialog, release notes, what an example opens with, the machine, the wheel, a phone,
the spacing graph, the name field and the build order."""
import pytest

from .helpers import example, settle, plan, set_fields, state, use, menu, ROOT


@pytest.mark.timeout(600)
def test_a_report_is_gathered_while_the_slicer_is_stuck(page):
    """Reported: "compiling report froze, unless I reloaded the page", during a slice that never finished. In the
    browser version one worker runs all the Python, so the report's request for the uploaded model waited behind the
    stuck slice. Here that request never answers at all, and the report still comes back with the model in it."""
    page.click('nav button[data-t="model"]')
    page.set_input_files("#file", str(ROOT / "examples" / "cube.stl"))
    settle(page)
    page.evaluate("""() => { const real = window.fetch;   // the slicer is busy: whatever asks it for the model waits forever
        window.fetch = (u, o) => /\\/source/.test(String(u)) ? new Promise(() => {}) : real(u, o) }""")
    menu(page, "[data-feedback]")                     # the report dialog, as the reporter opens it
    got = page.evaluate("""() => Promise.race([
        window.__feedback.build().then(async fd => JSON.parse(await fd.get('project').text()).model?.name ?? 'no model'),
        new Promise(r => setTimeout(() => r('still gathering after 10 s'), 10000))])""")
    page.reload()                                          # put fetch back for the next test (and wait for the page: a bare
                                                           # location.reload() let the next test click a page still loading)
    settle(page)
    assert got == "cube.stl", got


@pytest.mark.timeout(600)
def test_what_is_new_shows_itself_once_when_the_version_changes(page, server):
    """A version this browser has not seen opens the release notes by itself, once. Someone opening Lamina for the
    first time is shown nothing — none of it is new to them — and the header button opens the whole list whenever
    they want it. The notes are CHANGELOG.md itself, so the dialog cannot drift from the release."""
    def reload_with(seen):
        page.evaluate("v => v === null ? localStorage.removeItem('slicer_seen_version')"
                      " : localStorage.setItem('slicer_seen_version', JSON.stringify(v))", seen)
        page.goto(server + "/")
        settle(page)
        page.wait_for_timeout(600)                       # the notes are fetched after the page is up

    versions = page.evaluate("async () => (await (await fetch('changelog.md')).text()).split(/^## +/m).slice(1).map(p => p.split('\\n')[0].trim())")
    latest = versions[0]
    assert len(versions) > 3, "the app could not read CHANGELOG.md"
    heads = lambda: page.eval_on_selector_all("#news_body h5", "els => els.map(e => e.textContent.replace('Version ', ''))")

    reload_with(None)                                    # never seen Lamina: nothing is new, so nothing opens
    assert not page.locator("#newsdlg[open]").count(), "a first-time visitor was shown release notes"
    assert page.evaluate("() => JSON.parse(localStorage.getItem('slicer_seen_version'))") == latest

    # last seen two versions back (0.2.1, with 0.2.2 and its next-day fix 0.2.3 out since): both, newest first — the
    # fix must not hide the release it fixed
    reload_with(versions[2])
    assert page.locator("#newsdlg[open]").count(), "a new version did not announce itself"
    assert page.locator("#news_tour:not([hidden])").count(), "no button to the tour of what is new under the title"
    assert heads() == versions[:2] and len(page.text_content("#news_body")) > 200, heads()
    page.click("#news_go")

    reload_with("0.0.1")                                 # a version no longer listed: every version
    assert heads() == versions, heads()
    page.click("#news_go")

    page.goto(server + "/")                              # and not again on the next visit
    settle(page)
    page.wait_for_timeout(600)
    assert not page.locator("#newsdlg[open]").count(), "the release notes came back a second time"

    menu(page, "#newsbtn")                               # the button still opens them, newest version first
    page.wait_for_timeout(400)
    assert page.locator("#newsdlg[open]").count()
    heads = page.eval_on_selector_all("#news_body h5", "els => els.map(e => e.textContent)")
    assert heads[0].endswith(latest) and len(heads) > 1, heads
    page.click("#news_go")


def test_an_example_starts_every_technique_from_its_defaults(page):
    """Reported: the horse switched to stacked after the statue came back with the statue's preset (2 mm square
    dowels, axis y, random), so its tab spacers were all "thinner than 2 mm". The technique memory carried the last
    example's preset; a new example now starts every technique from its defaults and its own preset."""
    page.click('nav button[data-t="model"]')
    example(page, "horse_statue")
    example(page, "horse")
    use(page, mode="stacked")
    defaults = page.evaluate("async () => Object.fromEntries((await (await fetch('api/modes')).json())"
                             ".find(m => m.name === 'stacked').params.map(p => [p.name, p.default]))")
    st = state(page)
    for k in ("dowel_d", "dowel_shape", "axis", "placement", "space"):
        assert st[k] == defaults[k], (k, st[k], defaults[k])


def test_an_example_opens_with_its_technique_s_own_gap_between_slices(page):
    """Reported: the bonsai plaque was "missing some slices from the branches and the sides of the pot". An example
    opened with space forced to 0 on top of its technique's defaults, so a plaque's slices touched (70 of them) and
    nine pieces no neighbour had room to hold were left out. The gap is the technique's default unless the preset
    names one: 3 mm for a plaque, 35 slices and the plate."""
    use(page, "bonsai")
    assert state(page)["space"] == 3
    pl = plan(page)
    assert pl["counts"]["slices"] == 36 and pl["counts"]["errors"] == 0, pl["counts"]
    assert "9 floating piece(s) left out" not in " ".join(pl["notes"]), pl["notes"]
    example(page, "vase")                    # a technique whose default is touching slices keeps it
    assert state(page)["space"] == 0


def test_an_example_keeps_the_machine_s_values(page):
    """The machine's kerf and slot fit are not the model's. Pick a machine, tune its slot offset as a fit test would,
    open another example: the machine and the tuned offset stay, and the slice is cut with them. An example that names
    its own machine brings that machine's values. Reset with everything else, the machine kept its name but sliced at
    slot offset 0 (reported)."""
    st = lambda: page.evaluate("() => { const s = window.__t.state(); return [s.machine, s.slot_offset, window.__t.plan().params.slot_offset] }")
    page.click('nav button[data-t="sheet"]')
    page.select_option("#machine", "hand"); settle(page)
    assert st() == ["hand", 0.1, 0.1]                         # the machine's own values, applied
    page.fill("#p_slot_offset", "0.23"); page.press("#p_slot_offset", "Enter"); settle(page)
    use(page, "torus")
    assert st() == ["hand", 0.23, 0.23]                       # still yours, and sliced with it
    example(page, "wavy_torus")   # names its machine: a PETG print on the H2C
    assert st() == ["bambu_h2c", 0.2, 0.2]


def test_a_router_lays_the_parts_two_bits_apart(page):
    """A bit cuts its own width round each part: a router sets the gap between parts to twice its bit, the Sheet tab's
    reset keeps that, and the plan is laid with it. The 3 mm laser gap left 3.18 mm between parts for a 3.175 mm bit."""
    gap = lambda: page.evaluate("() => [window.__t.state().gap, window.__t.plan().params.gap]")   # noqa: E731
    use(page, "torus")
    page.click('nav button[data-t="sheet"]')
    page.select_option("#material", "plywood"); settle(page)
    page.click('#kind [data-kind="router"]'); settle(page)
    page.select_option("#machine", "shapeoko"); settle(page)
    assert gap() == [6.35, 6.35]
    page.click('button.reset[data-reset="sheet"]'); settle(page)
    assert page.evaluate("() => window.__t.state().machine") == "shapeoko" and gap() == [6.35, 6.35]

def test_the_notes_keep_their_lists_from_a_windows_checkout(page, server):
    """A Windows checkout serves CHANGELOG.md with CRLF line endings: a blank line is then \r\n\r\n, and the dialog
    showed a whole version as one paragraph with its bullets inline (reported). Served that way, every bullet of the
    newest version is a list item of its own.

    The markdown is written here rather than read from the repo's CHANGELOG.md: the run-together only shows with two
    bullets in a section, and the newest one there happens to hold one (an `## Unreleased` with a single note, as
    #16 added) — the test then failed with `assert 1 > 1` on a dialog that was right."""
    text = ("# Changelog\n\nWhat changed in each release.\n\n"
            "## 9.9.9\n\n### Added\n\n"
            "- **The first note.** It runs over more than one line,\n  as a changelog bullet does.\n"
            "- **The second note.** Two bullets are enough to run into each other.\n\n"
            "## 9.9.8\n\n- An older note.\n")
    bullets = 2
    page.route("**/changelog.md", lambda r: r.fulfill(body=text.replace("\n", "\r\n"), content_type="text/markdown"))
    try:
        page.evaluate("v => localStorage.setItem('slicer_seen_version', JSON.stringify(v))", "9.9.8")
        page.goto(server + "/"); settle(page); page.wait_for_timeout(600)
        assert page.locator("#newsdlg[open]").count(), "the newest version did not announce itself"
        items = page.eval_on_selector_all("#news_body li", "els => els.map(e => e.textContent)")
        assert len(items) == bullets, items                              # every bullet a list item of its own
        assert not any(" - **" in t or "\n" in t for t in items)          # no bullet run into another
    finally:
        page.unroute("**/changelog.md")
        if page.locator("#newsdlg[open]").count():
            page.click("#news_go")                       # left open, it takes every later test's clicks


def test_the_notes_show_their_pictures(page, server):
    """Each change you can see has a picture under it in CHANGELOG.md, by its repo path (web/static/news/…) so that
    GitHub shows it too. The dialog shows it from static/news/ beside the page, a clip's picture opens its video,
    and a link can only be http(s) or a path: the notes become HTML."""
    pic = "web/static/news/0.4.0-lamp.jpg"
    text = ("# Changelog\n\n## 9.9.9\n\n### Added\n\n"
            "- **A picture.** Under its entry.\n\n"
            f"  ![The lamp tick]({pic})\n\n"
            "- **A clip.** Its picture opens the video.\n\n"
            f"  [![The fold ▶]({pic})](https://marcelfarres.github.io/lamina/media/fold.mp4)\n\n"
            "- **A link.** [r/Lamina3D](https://www.reddit.com/r/Lamina3D) and [no](javascript:alert(1)).\n\n"
            "## 9.9.8\n\n- An older note.\n")
    page.route("**/changelog.md", lambda r: r.fulfill(body=text, content_type="text/markdown"))
    try:
        page.evaluate("v => localStorage.setItem('slicer_seen_version', JSON.stringify(v))", "9.9.8")
        page.goto(server + "/"); settle(page); page.wait_for_timeout(600)
        page.wait_for_function("[...document.querySelectorAll('#news_body img')].every(i => i.complete)")
        imgs = page.eval_on_selector_all("#news_body img", "els => els.map(i => [i.getAttribute('src'), i.alt, i.naturalWidth])")
        assert imgs == [["static/news/0.4.0-lamp.jpg", "The lamp tick", 900], ["static/news/0.4.0-lamp.jpg", "The fold ▶", 900]], imgs
        links = page.eval_on_selector_all("#news_body a", "els => els.map(a => [a.getAttribute('href'), a.textContent])")
        assert links == [["https://marcelfarres.github.io/lamina/media/fold.mp4", ""],
                         ["https://www.reddit.com/r/Lamina3D", "r/Lamina3D"], ["#", "no"]], links
    finally:
        page.unroute("**/changelog.md")
        if page.locator("#newsdlg[open]").count():
            page.click("#news_go")


def test_what_is_new_opens_on_this_version_and_every_picture_in_it_loads(page):
    """Marcel's interface test, step 1: help ▾ → What is new opens on the version the app is (pyproject.toml), and
    every picture of the real CHANGELOG.md is in the dialog and loads (the tests above serve a changelog of their
    own). The pictures load lazily, as the dialog is scrolled: here all at once."""
    import tomllib
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    pictures = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").count("![")
    menu(page, "#newsbtn"); page.wait_for_selector("#newsdlg[open]")
    try:
        heads = page.eval_on_selector_all("#news_body h5", "els => els.map(e => e.textContent)")
        assert heads[0].endswith(version), heads[:2]
        page.eval_on_selector_all("#news_body img", "is => is.forEach(i => { i.loading = 'eager' })")
        page.wait_for_function("[...document.querySelectorAll('#news_body img')].every(i => i.complete)", timeout=60_000)
        imgs = page.eval_on_selector_all("#news_body img", "is => is.map(i => [i.getAttribute('src'), i.naturalWidth])")
        assert len(imgs) == pictures > 0 and all(w > 0 for _, w in imgs), [s for s, w in imgs if not w]
    finally:
        page.click("#news_go")


def test_the_wheel_zooms_back_out(page, server):
    """Wheel in, wheel out the same notches: the camera is back where it was. At a pixel ratio under 1 (a browser
    zoomed out) one notch put the camera on the point it turns about and zooming out made it NaN; a fast flick sent
    deltas of a thousand and more and dived into the model, past the clipping plane (reported). A flick is one notch
    now, and the camera stops short of the point it turns about."""
    pg = page.context.browser.new_page(viewport={"width": 1500, "height": 950}, device_scale_factor=0.9)
    pg.errors = []; pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    try:
        pg.goto(server + "/"); settle(pg)
        box = pg.locator("#v3d canvas").first.bounding_box()
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        dist = lambda: pg.evaluate("() => window.__t.camera.position.distanceTo(window.__t.target())")
        start = dist()
        for dy in [-100] * 10 + [-3000] + [100] * 10 + [3000]:      # ten notches and a flick in, the same out
            pg.mouse.wheel(0, dy); pg.wait_for_timeout(60)
            d = dist(); assert d == d and d > start / 200, d                # never NaN, never onto the target
        pg.wait_for_timeout(400)
        assert abs(dist() / start - 1) < 0.01, (start, dist())
    finally:
        pg.close()


def test_a_phone_is_told_once_that_lamina_is_made_for_a_computer(page, server):
    """A phone gets the whole app and, once, a notice that it is made for a computer. A computer never sees it (every
    other test here runs on one, and the notice would sit over the page)."""
    assert not page.locator("#oops[open]").count()
    ctx = page.context.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
    pg = ctx.new_page(); pg.errors = []; pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    try:
        pg.goto(server + "/"); pg.wait_for_selector("#oops[open]", timeout=60_000)
        assert pg.text_content("#oops_title") == "Lamina is made for a computer"
        assert pg.text_content("#oops_go") == "Continue on this phone"
        pg.click("#oops_go"); assert not pg.locator("#oops[open]").count()
        pg.reload(); pg.wait_for_timeout(3000)
        assert not pg.locator("#oops[open]").count(), "told twice"
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


def test_the_spacing_graph_follows_the_technique_and_the_switch(page):
    """An example that opens with a spacing curve shows the graph in the form under its tick — one per family for
    interlocked — and the plan carries the positions it drew; the switch off hides it and the slices go back to even."""
    use(page, "vase"); page.click('nav button[data-t="technique"]')
    assert page.locator(".spc canvas").first.is_visible()
    assert page.evaluate("() => document.querySelectorAll('.spc canvas').length") == 1
    assert plan(page)["spacing"] and plan(page)["params"]["spacing_vary"]
    example(page, "ripple"); page.click('nav button[data-t="technique"]')
    assert page.evaluate("() => document.querySelectorAll('.spc canvas').length") == 2    # x and y families
    set_fields(page, [["p_spacing_vary", False]]); settle(page)
    assert not page.locator(".spc canvas").first.is_visible()
    assert not plan(page).get("spacing")


def test_the_spacing_graph_buttons_change_the_curve_and_the_slices(page):
    """Every gesture of the graph has a button: a starting shape, a point added, its gap typed, the point removed, the
    curve reset. Each one changes the curve in the state, and the plan that comes back follows it."""
    use(page, "vase")
    page.click('nav button[data-t="technique"]')
    curve = lambda: page.evaluate("() => window.__t.state().spacing_curve")
    gaps = lambda: [round(b - a, 2) for a, b in zip(plan(page)["spacing"][0]["positions"], plan(page)["spacing"][0]["positions"][1:])]
    page.click('.spc button[data-arg="ends"]'); settle(page)
    assert len(curve()) == 3 and curve()[0][1] < curve()[1][1] > curve()[2][1]
    g = gaps(); assert g[0] < g[len(g) // 2] > g[-1], g                       # dense at both ends, as the chip says
    page.click('.spc button[data-spc="add"]'); settle(page)
    assert len(curve()) == 4
    page.fill('.spc [data-spc="v"]', "7")                                     # the added point is the selected one
    page.click('.spc button[data-spc="del"]'); settle(page)                   # pressed straight after typing: the value lands, then the point goes
    assert len(curve()) == 3
    page.click('.spc button[data-arg="model"]'); settle(page)                 # read off the slices on screen
    assert len(curve()) == 7 and len({v for _, v in curve()}) > 1
    page.click('.spc button[data-spc="reset"]'); settle(page)
    assert len(curve()) == 3 and not page.locator('.f[data-p="spacing_curve"].changed').count()   # the default again: its mark is gone


def test_the_panel_folds_finds_and_puts_a_default_back(page):
    """A section folds on its heading, a changed setting is marked and its sign puts the default back, a click on a name
    opens its help, the search box leaves only the rows that match — from every tab — and a warning says it is one in
    words."""
    page.click('nav button[data-t="technique"]'); page.click('#modes button[data-m="stacked"]'); settle(page)
    sec = page.locator('#g-technique .sec[data-sec="Joining"]')
    assert sec.locator(".f").first.is_visible()
    sec.locator("h3").click(); assert not sec.locator(".f").first.is_visible()
    sec.locator("h3").click(); assert sec.locator(".f").first.is_visible()
    default = page.evaluate("() => window.__t.state().space")
    assert not page.locator('.f[data-p="space"].changed').count()
    set_fields(page, [["p_space", default + 3]]); settle(page)
    assert page.locator('.f[data-p="space"].changed').count() and plan(page)["params"]["space"] == default + 3
    page.click('.f[data-p="space"] .chg'); settle(page)
    assert plan(page)["params"]["space"] == default and not page.locator('.f[data-p="space"].changed').count()
    page.click('.f[data-p="axis"] > .k'); assert page.locator('.f[data-p="axis"] .help').is_visible()
    page.click('.f[data-p="axis"] > .k'); assert not page.locator('.f[data-p="axis"] .help').count()
    page.fill("#find", "kerf")
    shown = page.evaluate("() => [...document.querySelectorAll('#tabs .f[data-p]')].filter(f => f.offsetParent).map(f => f.dataset.p)")
    assert shown and all("kerf" in n or n == "compensate" for n in shown), shown     # rows of the Sheet & fit tab, seen from Technique
    page.press("#find", "Escape")
    assert page.locator('.f[data-p="axis"]').is_visible()
    use(page, "blob")
    warns = page.locator("#msgs .msg.warn").all_text_contents()
    assert all(w.startswith("⚠ WARNING") for w in warns), warns


def test_the_short_name_field_sets_what_the_labels_start_with(page):
    """The model's name on every label is a code of up to four letters: derived from the name, or typed in the
    short name field, which is kept to letters and digits, in capitals, cut to four; the sheet's labels start with it."""
    assert plan(page)["label_tag"] == "EGG"
    page.click('nav button[data-t="sheet"]')
    set_fields(page, [["p_short_name", "m-e o"]]); settle(page)
    assert plan(page)["label_tag"] == "MEO"
    set_fields(page, [["p_short_name", "abcdefg"]]); settle(page)
    assert plan(page)["label_tag"] == "ABCD"
    texts = page.evaluate("() => [...document.querySelectorAll('#sheets path[data-text]')].map(p => p.dataset.text)")
    labels = [t for t in texts if " R-" in t]                                   # the parts' labels, not the title or the scale check
    assert labels and all(t.startswith("ABCD ") for t in labels), labels[:5]


def test_the_build_order_names_the_part_going_in(page):
    """Part way along the steps slider the 3D view carries the step and the name of the part going in, at the top,
    so a recording of the build order says what each piece is; at the end nothing is shown."""
    n = int(page.get_attribute("#steps", "max"))
    assert n > 2
    page.evaluate("k => { const e = document.getElementById('steps'); e.value = k; e.dispatchEvent(new Event('input')) }", n // 2)
    page.wait_for_timeout(300)
    text = page.evaluate("() => window.__t.banner()")
    assert text.startswith(f"step {n // 2} / {n}") and "EGG " in text, text
    page.evaluate("k => { const e = document.getElementById('steps'); e.value = k; e.dispatchEvent(new Event('input')) }", n)
    page.wait_for_timeout(300)
    assert page.evaluate("() => window.__t.banner()") == ""


def test_a_folded_job_folds_up_at_the_end_of_its_steps(page):
    """Asked for: the steps slider should take a folded job from flat to folded. After the last part is in, the slider
    has twenty more steps that fold the panels up: flat when the last part goes in, half folded half way, folded at
    the end, with the share in the banner. The printed-fold settings show on a printed job and not on a cut one."""
    shown = lambda name: page.evaluate("n => { const e = document.querySelector(`[data-p=${n}]`); return !!e && getComputedStyle(e).display !== 'none' }", name)   # noqa: E731
    page.click('nav button[data-t="technique"]')
    assert not shown("hinge")                                              # the egg in cardboard: nothing printed
    assert not page.is_visible("#foldl")                                  # … and nothing to fold: no fold slider
    page.click('nav button[data-t="model"]')
    example(page, "fold_test")
    page.click('nav button[data-t="technique"]')
    assert shown("hinge") and shown("hinge_w") and shown("hinge_stop")
    assert page.is_visible("#foldl")
    parts = plan(page)["counts"]["parts"]; n = int(page.get_attribute("#steps", "max"))
    assert n == parts + 20
    state = lambda: page.evaluate("() => [+document.querySelector('#fold').value, window.__t.banner()]")   # noqa: E731
    step = lambda k: (page.evaluate("k => { const e = document.getElementById('steps'); e.value = k; e.dispatchEvent(new Event('input')) }", k), page.wait_for_timeout(200))   # noqa: E731
    step(parts); fold, text = state()
    assert fold == 0 and text.startswith(f"step {parts} / {n}")
    step(parts + 10); fold, text = state()
    assert fold == 0.5 and "folding 50 %" in text
    step(n); fold, text = state()
    assert fold == 1 and text == ""


def test_basic_holds_back_the_fine_settings_until_they_are_asked_for(page):
    """The form starts on basic: a group shows what a first piece needs and names the others at its foot. A click
    there, the search box or "all" shows them, and a setting that is not at its default is never held back."""
    use(page, "vase", "stacked"); page.click('nav button[data-t="technique"]')
    row = lambda n: page.locator(f'.f[data-p="{n}"]')                                  # noqa: E731
    assert page.locator("#tabs.basic").count() and row("count").is_visible() and not row("shift").is_visible()
    more = page.locator('.sec[data-sec="Slices"] > .more'); assert "shift stack" in more.inner_text()
    more.click(); assert row("shift").is_visible()
    page.click('#level button[data-level="all"]'); assert row("surface").is_visible() and not more.is_visible()
    page.select_option("#p_surface", "outer"); settle(page)
    page.click('#level button[data-level="basic"]')
    assert row("surface").is_visible() and not row("shift").is_visible()               # the changed one stays; the group is shut again
    page.fill("#find", "shift"); assert row("shift").is_visible(); page.fill("#find", "")
    page.click('.f[data-p="surface"] .chg'); settle(page); assert not row("surface").is_visible()


def test_a_tool_in_the_3d_view_does_what_the_key_does(page):
    """Tilting a slice needed shift held down, which no button said and a tablet cannot do. The tool is picked, a click
    selects the slice and a drag tilts it; Esc goes back to turning the view; a technique shows only its own tools."""
    use(page, "vase", "stacked")
    tools = lambda: page.evaluate("() => [...document.querySelectorAll('#tools button')].filter(b => !b.hidden).map(b => b.dataset.tool)")   # noqa: E731
    assert tools() == ["", "alt", "tilt", "roll"]
    box = page.locator("#v3d canvas").bounding_box(); x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] * 0.3
    page.click('#tools button[data-tool="tilt"]'); page.mouse.click(x, y)
    page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + 40, y, steps=6); page.mouse.up(); settle(page)
    tilt = state(page)["tilt"]; assert len(tilt) == 1 and list(tilt.values())[0], tilt
    page.keyboard.press("Escape"); assert page.get_attribute('#tools button[data-tool=""]', "aria-pressed") == "true"
    use(page, mode="curve"); assert tools() == ["", "alt", "branch", "tilt", "roll"]
    use(page, mode="folded"); assert tools() == ["", "seam", "face"] and page.is_visible("#tools")   # its own two: seams and faces


def test_a_connector_left_out_is_counted_and_the_export_text_opens_on_a_click(page):
    """Two dowel points typed 3 mm apart cannot both be cut: the dowels left out are a warning the count shows, with a
    ring in the 3D view for each place. (The vase example itself cuts every dowel since bug 046.) On the Export tab the
    download buttons come first (step 12 of Marcel's interface test): every file's button is on its own line with the
    text about it after it, closed; the text and the parts table open on a click. The main button's text shows under it;
    the other formats are folded under it (feature/export-tab)."""
    use(page, "vase", "stacked")
    page.evaluate("() => window.__t.applyFix({dowels: [[0, 0], [3, 0]]})"); settle(page); pl = plan(page)
    assert pl["warnings"] and "left out" in pl["warnings"][0], (pl["warnings"], pl["notes"])
    assert pl["counts"]["warnings"] >= 1 and len(pl["left_out"]) == int(pl["warnings"][0].split("connector")[0])
    assert page.locator("#msgs .msg.warn").first.inner_text().startswith("⚠ WARNING")
    page.click('nav button[data-t="export"]')
    assert page.is_visible("#dl a.main + .hint")
    page.click("#other_fold > summary")
    rows = page.evaluate("""() => [...document.querySelectorAll('#dl_other .r')].map(r => [r.firstElementChild.tagName,
        !!r.querySelector('details.info'), !r.querySelector('details[open]'), !!r.firstElementChild.offsetParent])""")
    assert rows and all(r == ["A", True, True, True] for r in rows if r[1]) and all(r[0] == "A" and r[3] for r in rows), rows
    info = page.locator("#dl_other details.info").first
    assert not info.locator(".hint").is_visible(); info.locator("summary").click(); assert info.locator(".hint").is_visible()
    assert not page.locator("#parts table").is_visible(); page.click("#parts_fold > summary"); assert page.locator("#parts table").is_visible()


def test_the_lights_are_settings_of_the_project_and_leave_the_view_as_it_was(page):
    """The light tick turns on the shadow pass and the tone mapping; off, the view has neither. The shadows are the soft
    ones: three.js's shadow code was replaced (a three.js update that changes it fails here, not silently). The Light
    tab holds the lights: one small LED in the middle until something is changed, then a list in the project. A light
    takes a kind, a place and a size; a second one is added; an undo takes a step back without slicing; a re-slice
    keeps them; a new model starts with its own."""
    use(page, "vase", "stacked"); errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
    shadows = lambda: page.evaluate("() => window.__t.lamp()")   # noqa: E731
    look = lambda: page.evaluate("async () => {const m = await import(location.origin + '/static/js/scene.js'),"   # noqa: E731
                                 " T = await import('three'), c = T.ShaderChunk.shadowmap_pars_fragment;"
                                 " return [m.renderer.toneMapping === T.AgXToneMapping, c.includes('pen = max( R') && c.includes('lampQuad')]}")
    lit = lambda: page.evaluate("async () => {const m = await import(location.origin + '/static/js/scene.js');"   # noqa: E731
                                " return m.scene.getObjectsByProperty('isLight', true).filter(l => l.castShadow && l.parent.visible)"
                                ".map(l => [l.isSpotLight ? 'spot' : 'bulb', +l.position.z.toFixed(1), +l.intensity.toFixed(0)])}")
    saved = lambda: page.evaluate("async () => {const s = (await window.__t.project()).state; return [s.light, s.lights]}")   # noqa: E731
    put = lambda k, v: page.eval_on_selector(f"#lt_{k}", "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})) }", v)   # noqa: E731
    assert not shadows() and look() == [False, True] and lit() == []
    page.check("#lamp"); assert shadows() and look() == [True, True] and saved() == [True, None]
    (kind, z0, bright), = lit(); assert kind == "bulb"
    page.click('nav button[data-t="light"]'); assert page.is_checked("#light_on") and page.locator(".lrow").count() == 1
    put("p2", 20); (_, z1, _), = lit(); assert z1 < z0 and saved()[1][0]["pos"] == [0, 0, 20]
    page.select_option("#g-light select[data-l=like]", "gu10"); assert page.is_visible("#lt_angle")
    (kind, _, spot), = lit(); assert kind == "spot" and spot > bright and saved()[1][0]["angle"] == 36
    put("angle", 90); assert page.input_value("#g-light select[data-l=like]") == "own"
    page.wait_for_timeout(600)                                       # the slider's step of undo is taken
    page.click("#g-light button[data-act=add]"); assert [k for k, *_ in lit()] == ["spot", "bulb"] and page.locator(".lrow").count() == 2
    page.wait_for_timeout(600); page.keyboard.press("Control+z"); page.wait_for_timeout(300)
    assert len(saved()[1]) == 1 and page.locator(".lrow").count() == 1 and page.evaluate("window.__t.idle()")
    set_fields(page, [["p_count", 12]]); settle(page); assert shadows() and plan(page)["counts"]["slices"] == 12 and len(lit()) == 1
    # the project as text, opened again after the tab was reset: its lights are back, and its units are the file's
    before = saved(); text = page.evaluate("async () => {const p = await window.__t.project(); p.unit = 'cm'; return JSON.stringify(p)}")
    page.click('section[data-tab="light"] button.reset'); assert saved()[1] is None
    page.evaluate("async t => (await import(location.origin + '/static/js/project.js')).openProjectText(t, 'test')", text)
    settle(page); assert saved() == before and page.input_value("#unit") == "cm" and [k for k, *_ in lit()] == ["spot"]
    page.select_option("#unit", "mm"); settle(page)
    page.uncheck("#lamp"); assert not shadows() and look() == [False, True] and saved()[0] is False
    use(page, "cone", "stacked"); assert saved()[1] is None and not errs, errs

def test_a_light_is_moved_in_the_view_and_the_room_and_the_picture_are_settings(page):
    """The move-a-light tool is in the tool column while the light is on: a drag of the z arrow lifts the light, a drag
    of the light moves it across the view, a drag beside it turns the view, a drag of the dot at a spot's cone aims it. The room's settings and the video tick are
    in the project; the picture button saves a PNG; none of it slices."""
    use(page, "cone", "stacked"); errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
    tool = page.locator("#tools button[data-tool=light]")
    assert not tool.is_visible()
    page.check("#lamp"); page.click('nav button[data-t="light"]'); tool.click(); assert page.is_visible("#lighthint")
    at = lambda: page.evaluate("async () => {const m = await import(location.origin + '/static/js/scene.js'),"   # noqa: E731
                               " l = m.scene.getObjectsByProperty('isLight', true).find(x => x.castShadow && x.parent.visible),"
                               " a = l.parent.children.find(c => c.children[0]?.type === 'ArrowHelper'), p = l.position.toArray(), q = [...p]; q[2] += a.scale.x * .8;"
                               " return [window.__t.screen(p), window.__t.screen(q)]}")
    saved = lambda: page.evaluate("async () => {const s = (await window.__t.project()).state; return [s.lights, s.room, s.light_video]}")   # noqa: E731

    def drag(x, y, dx, dy):
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + dx / 2, y + dy / 2, steps=3); page.mouse.move(x + dx, y + dy, steps=3); page.mouse.up()

    z0 = float(page.input_value("#lt_p2")); _, tip = at(); drag(*tip, 0, -50)
    (x, y, z), = [saved()[0][0]["pos"]]; assert (x, y) == (0, 0) and z > z0 and float(page.input_value("#lt_p2")) == z
    here, _ = at(); drag(*here, 60, 0); x1, y1, _ = saved()[0][0]["pos"]; assert (x1, y1) != (0, 0)
    cam = page.evaluate("window.__t.camera.position.toArray()"); box = page.locator("#v3d canvas").bounding_box()
    drag(box["x"] + 60, box["y"] + box["height"] - 60, 50, 0); assert page.evaluate("window.__t.camera.position.toArray()") != cam
    # a spot is aimed: by its tilt and turn, or by the dot at the end of its cone; what lamp it is like does not change
    page.select_option("#g-light select[data-l=like]", "gu10")     # a spot shows its tilt and turn at once; moving one aims it
    assert page.is_visible("#lt_tilt") and page.is_visible("#lt_turn") and page.input_value("#g-light select[data-l=aim]") == "up"
    page.eval_on_selector("#lt_tilt", "e => { e.value = 90; e.dispatchEvent(new Event('input', {bubbles: true})) }")
    spot = saved()[0][0]; assert (spot["aim"], spot["tilt"], spot["like"]) == ("free", 90, "gu10")
    dot = page.evaluate("async () => {const m = await import(location.origin + '/static/js/scene.js'),"
                        " d = m.scene.getObjectsByProperty('isMesh', true).find(c => c.visible && c.parent.visible && c.renderOrder === 30 && c.geometry.type === 'SphereGeometry');"
                        " return window.__t.screen(d.position.toArray())}")
    drag(*dot, 0, 70); spot = saved()[0][0]; assert spot["aim"] == "free" and spot["tilt"] > 90, spot
    page.keyboard.press("Escape"); assert not page.is_visible("#lighthint")
    page.select_option("#g-light select[data-l=r_floor]", "wood"); page.uncheck("#light_video")
    assert saved()[1:] == [{"show": True, "size": 2, "walls": "white", "floor": "wood", "back": 10}, False]
    with page.expect_download() as d:
        page.click("#g-light button[data-act=png]")
    assert d.value.suggested_filename.endswith("_light.png") and page.evaluate("window.__t.idle()") and not errs, errs
    page.uncheck("#lamp"); assert not tool.is_visible()

def test_a_paper_pane_is_a_sheet_of_its_own_that_folds_and_glows(page):
    """A window closed with paper: its pane is a mesh of its own on its panel, in the paper's colour, and folds with it.
    With the light on a pane casts a shadow and takes none, its far face takes the share the paper lets through
    (three.js's Lambert code is changed for it: an update that changes that code fails here, not silently), and a bulb
    gets that share back as a light with no shadows."""
    use(page, "fold_box", "folded"); errs = []; page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    seen = """async () => { const m = await import(location.origin + '/static/js/scene.js'), T = await import('three'),
      ps = __t.parts().filter(p => p.userData.pane).map(p => p.userData.pane), b = new T.Box3(); ps.forEach(p => b.expandByObject(p));
      const L = m.scene.getObjectsByProperty('isPointLight', true).filter(l => l.intensity > 0), main = L.find(l => l.castShadow), soft = L.find(l => !l.castShadow);
      return {n: ps.length, own: ps.every(p => p.material[0] === m.paper && p.material[1] === m.hatched && p.material[0] !== p.parent.material), cast: ps.every(p => p.castShadow), takes: ps.some(p => p.receiveShadow),
        color: m.paper.color.getHexString(), through: m.renderer.properties.get(m.paper).uniforms?.paperThrough?.value, high: +(b.max.z - b.min.z).toFixed(1),
        soft: soft && main ? soft.intensity / main.intensity : 0,
        chunk: T.ShaderChunk.lights_lambert_pars_fragment.includes('float dotNL = saturate( dot( geometryNormal, directLight.direction ) );')} }"""
    assert page.evaluate(seen)["n"] == 0                                           # open windows: no panes
    set_fields(page, [("p_window", 0.6), ("p_window_fill", "paper")]); settle(page)
    set_fields(page, [("p_paper_through", 30), ("p_paper_color", "#56b4e9")]); settle(page)
    off = page.evaluate(seen)
    assert off["n"] > 0 and off["own"] and off["chunk"] and off["color"] == "56b4e9" and not off["cast"] and off["soft"] == 0, off
    page.check("#lamp"); page.wait_for_timeout(600)
    on = page.evaluate(seen)
    assert on["cast"] and not on["takes"] and on["through"] == 0.3 and 0 < on["soft"] <= 0.3, on
    set_fields(page, [("fold", 0)]); page.wait_for_timeout(300)
    flat = page.evaluate(seen); assert flat["n"] == on["n"] and flat["high"] < on["high"] / 3, (flat, on)   # flat with their panels
    assert not errs, errs
