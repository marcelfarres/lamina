"""The form: every box reaches the slicer, the model preparation settings, nothing cut off on screen, the
tables, undo, and the whole job from upload to cut files."""
import json

import pytest

from .helpers import settle, plan, set_fields, sweep_values, CUT_OFF, state, use, menu, ROOT


@pytest.mark.timeout(1800)
def test_every_parameter_of_every_technique_reaches_the_slicer(page, server):
    """Each technique in turn: fill every box it offers with a value one step off the default, slice once, and check
    the server's plan came back holding exactly those values. A field that stops being wired up — renamed, dropped
    from the form, read from the wrong place — cannot pass this."""
    import urllib.request
    modes = json.loads(urllib.request.urlopen(server + "/api/modes").read())   # noqa: S310 — the fixture's own server
    assert modes, "no techniques"
    for m in modes:
        use(page, mode=m["name"])
        ids, want = sweep_values(m["common"] + m["params"])
        assert len(want) > 20, (m["name"], len(want))          # the sweep must really be sweeping
        set_fields(page, ids)
        settle(page)
        got = plan(page)["params"]
        if "size" in want:                                     # the boxes read along the view's axes; the plan holds the model's own
            axes, model = page.evaluate("() => window.__t.sizeAxes()"), [0, 0, 0]
            for j, v in enumerate(want["size"]):
                model[axes[j]] = v
            want["size"] = model
        wrong = {k: (v, got.get(k)) for k, v in want.items()
                 if not (isinstance(v, (int, float)) and not isinstance(v, bool) and abs(float(got.get(k, 1e9)) - v) < 1e-3
                         or isinstance(v, list) and all(abs(a - b) < 1e-3 for a, b in zip(v, got.get(k, [])))
                         or got.get(k) == v)}
        assert not wrong, (m["name"], wrong)
        page.click('nav button[data-t="model"]')
        page.click("#origsize")                                # back to a plain model for the next technique
        settle(page)


@pytest.mark.timeout(1200)
@pytest.mark.parametrize("name,value", [("shrinkwrap", 2), ("hollow", 6), ("thicken", 2), ("round", 2), ("smooth", 5), ("scale", 0.5)])
def test_each_model_preparation_setting_still_leaves_parts_to_cut(page, name, value):
    """The sweep above proves every box is wired up; it cannot prove the result is usable, because all of them at
    once is a model nobody would ask for (a 0.5 mm hollow shell has nothing left to cut). So the settings that
    rebuild the mesh get one sensible value each, and each has to come back with parts."""
    use(page, mode="stacked")
    page.click('nav button[data-t="model"]')
    page.click("#origsize")
    settle(page)
    set_fields(page, [(f"p_{name}", value)])
    settle(page)
    p = plan(page)
    assert p["params"][name] == value
    assert p["counts"]["parts"] > 0, (name, p["errors"], p["notes"])
    page.click("#origsize")
    settle(page)


@pytest.mark.timeout(1200)
def test_no_number_on_screen_is_cut_off(page):
    """A value the box is too narrow for reads as a different number (-168 as -16) or as nothing at all — the radial
    axes table showed six empty-looking boxes a row. Every technique, every tab, a part selected, in mm, cm and in:
    whatever a field, select or readout holds has to fit in what it shows."""
    found = {}
    scenes = [("dumbbell", "radial"), ("snowman", "radial"), ("egg", "interlocked"), ("cube", "stacked"), ("pyramid", "curve"), ("wedge", "folded")]
    for example, mode in scenes:
        use(page, example, mode)
        page.evaluate("() => { const m = window.__t.parts().find(x => x.userData.group !== 'B'); if (m) window.__t.select(m.userData.slice) }")
        for unit in ("mm", "cm", "in"):
            page.select_option("#unit", unit); page.wait_for_timeout(300)
            for tab in ("model", "technique", "sheet", "checks", "export"):
                page.click(f'nav button[data-t="{tab}"]'); page.wait_for_timeout(150)
                for line in page.evaluate(CUT_OFF):
                    found.setdefault(line, f"{example}/{mode}/{unit}: {line}")     # the whole line: a box without a name must not hide another (040)
        page.select_option("#unit", "mm"); page.evaluate("() => window.__t.deselect()")
    assert not found, "\n".join(found.values())


@pytest.mark.timeout(600)
def test_the_tables_take_a_row(page):
    """The list-shaped parameters: + on a points / axes table and a chip typed into a chips box. These add geometry
    the 3D view usually places, and each has thrown at some point — a row of zeros, an axis with no length."""
    page.click('nav button[data-t="technique"]'); page.click('#level button[data-level="all"]')   # the branches and the axes show on "all"
    for m in ("curve", "radial"):
        page.click(f'#modes button[data-m="{m}"]')
        settle(page)
        before = plan(page)
        names = page.eval_on_selector_all("#tabs [data-add]", "els => els.map(e => e.dataset.add)")
        for name in names:       # by name: a click re-renders the form, so a button found before it is gone
            page.click(f'#tabs [data-add="{name}"]')
            settle(page)
        p = plan(page)
        assert p["counts"]["parts"] > 0, m
        if m == "curve":         # the curve's + grows the curve on screen; the branch's hangs below it
            assert {"curve", "branches"} <= set(names), names
            assert len(p["params"]["curve"]) == len(before["curve_pts"]) + 1, p["params"]["curve"]
            assert len(p["params"]["branches"]) == 1 and any(s["label"] == "K1" for s in p["slices"])
    page.click('#level button[data-level="basic"]')


@pytest.mark.timeout(600)
def test_undo_walks_back_every_change_and_redo_walks_forward(page):
    """The reported one: undo is used exactly when something moved by accident, so it has to be safe to lean on.
    Ten changes, ten undos, and the design is the one it started from — no uncaught error, no stuck status."""
    use(page, mode="stacked")
    for i in range(10):
        set_fields(page, [("p_thickness", 3.5 + i)])
        page.wait_for_timeout(450)                             # each change lands as its own undo step
    settle(page)
    assert state(page)["thickness"] == 12.5

    def walk(button, limit=120):
        """Press it until it runs out — clicks faster than the debounce, so many steps cost one slice."""
        for n in range(limit):
            if page.is_disabled(button):
                return n
            page.click(button)
            page.wait_for_timeout(120)
        raise AssertionError(f"{button} never ran out")

    back = walk("#undo")                                       # the whole history, past the technique change too
    settle(page)
    assert back >= 10, back
    assert state(page)["thickness"] != 12.5
    assert walk("#redo") == back                               # and every step forward again
    settle(page)
    assert state(page)["thickness"] == 12.5
    assert page.evaluate("() => window.__t.plan().mode") == "stacked"


@pytest.mark.timeout(900)
def test_the_whole_job_from_upload_to_cut_files(page):
    """Upload a model, change technique, save the project, download the cut files, open it again from the library,
    clear the data."""
    page.click('nav button[data-t="model"]')
    page.set_input_files("#file", str(ROOT / "examples" / "pear.stl"))
    settle(page)
    assert plan(page)["counts"]["parts"] > 0
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="interlocked"]')
    settle(page)
    page.fill("#pname", "ui test")
    page.click("#psave2")
    page.wait_for_function("() => document.querySelector('#status').textContent.startsWith('saved ui test')")
    page.click('nav button[data-t="export"]')
    with page.expect_download() as zipped:
        page.click("#dl a")
    assert zipped.value.suggested_filename.endswith(".zip")
    # the saved project reopens the job — model, technique and every setting
    page.click('nav button[data-t="technique"]')
    page.click('#modes button[data-m="stacked"]')
    settle(page)
    page.click("#popen")
    page.once("dialog", lambda d: d.accept())               # the technique changed since: unsaved changes
    page.locator('#libyours .card[data-name="ui test"] .t').click()
    page.wait_for_function("() => !__t.lib.unsaved()")      # read and opened: its slice has started
    settle(page)
    assert plan(page)["mode"] == "interlocked"
    assert state(page)["project"] == "ui test"
    ok = lambda d: d.accept()
    page.on("dialog", ok)
    with page.expect_navigation():                       # the reload comes after the session's DELETE returns
        menu(page, "#clear")
    settle(page)
    page.remove_listener("dialog", ok)                   # left in place it would answer the next test's dialogs
