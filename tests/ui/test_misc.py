"""The rest: the report dialog, release notes, what an example opens with, the machine, the wheel, a phone,
the spacing graph, the name field and the build order."""
import pytest

from .helpers import settle, plan, set_fields, state, use, menu, ROOT


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
    page.select_option("#example", "horse_statue"); settle(page)
    page.select_option("#example", "horse"); settle(page)
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
    page.select_option("#example", "vase"); settle(page)                    # a technique whose default is touching slices keeps it
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
    page.select_option("#example", "wavy_torus"); settle(page)   # names its machine: a PETG print on the H2C
    assert st() == ["bambu_h2c", 0.2, 0.2]


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
    use(page, "ripple"); page.click('nav button[data-t="technique"]')
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
    page.select_option("#example", "fold_test")
    page.wait_for_timeout(1500); settle(page)
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
    use(page, mode="folded"); assert not page.is_visible("#tools")     # nothing but turning the view: no column


def test_a_connector_left_out_is_counted_and_the_export_text_opens_on_a_click(page):
    """The vase leaves dowels out: that is a warning the count shows, with a ring in the 3D view for each place. On
    the Export tab the text about a file is behind its own line, and the parts table opens on its heading."""
    use(page, "vase", "stacked"); pl = plan(page)
    assert pl["warnings"] and "left out" in pl["warnings"][0], (pl["warnings"], pl["notes"])
    assert pl["counts"]["warnings"] >= 1 and len(pl["left_out"]) == int(pl["warnings"][0].split("connector")[0])
    assert page.locator("#msgs .msg.warn").first.inner_text().startswith("⚠ WARNING")
    page.click('nav button[data-t="export"]'); info = page.locator("#dl details.info").first
    assert not info.locator(".hint").is_visible(); info.locator("summary").click(); assert info.locator(".hint").is_visible()
    assert not page.locator("#parts table").is_visible(); page.click("#parts_fold > summary"); assert page.locator("#parts table").is_visible()


def test_the_lamp_lights_the_model_from_inside_and_leaves_the_view_as_it_was(page):
    """The lamp tick turns on a bulb, the shadow pass and the bulb-height slider; a re-slice keeps it on; off, the
    view has no shadow pass and the slider is gone. The 3D bar holds its controls on the vase without a page error."""
    use(page, "vase", "stacked"); errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
    shadows = lambda: page.evaluate("() => window.__t.lamp()")   # noqa: E731
    assert not shadows() and not page.is_visible("#lampl")
    page.check("#lamp"); assert shadows() and page.is_visible("#lampl")
    page.eval_on_selector("#lampz", "e => { e.value = 0.9; e.dispatchEvent(new Event('input')) }")
    set_fields(page, [["p_count", 12]]); settle(page); assert shadows() and plan(page)["counts"]["slices"] == 12
    page.uncheck("#lamp"); assert not shadows() and not page.is_visible("#lampl") and not errs, errs

