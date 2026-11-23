"""What you make with (web/static/index.html #kind, main.js setKind, presets.js kindOf): one click on laser, router,
3D printer or laser + 3D printer sets `printed`, the machine with its values and bed, and a material it can make, in
one step of undo; the Export tab follows; a machine of your own sits under its kind; changing back brings back what
was there; and a setting the machine has no use for waits under its section's "+ N more" line (form.js NOT_FOR)."""
import pytest

from .helpers import plan, set_fields, settle, state, use

NOW = """() => { const s = window.__t.state(), p = window.__t.plan().params;
    const pick = o => ({printed: !!o.printed, machine: o.machine, material: o.material, thickness: o.thickness, kerf: o.kerf,
                        slot_offset: o.slot_offset, relief: o.relief, tool_d: o.tool_d, gap: o.gap, sheet: o.sheet, connect: o.connect});
    return {pressed: [...document.querySelectorAll('#kind [aria-pressed=true]')].map(b => b.dataset.kind), s: pick(s), plan: pick(p)} }"""
SHOWN = "q => { const e = document.querySelector(q); return !!e && e.getClientRects().length > 0 }"


def kind(page, k):
    page.click(f'#kind [data-kind="{k}"]')
    settle(page)
    return page.evaluate(NOW)


def cardboard_on_the_laser(page):
    page.click('nav button[data-t="sheet"]')
    page.click('#kind [data-kind="laser"]'); settle(page)
    page.select_option("#material", "cardboard"); settle(page)
    page.select_option("#machine", "co2"); settle(page)
    page.click('#level button[data-level="basic"]')


@pytest.fixture(autouse=True)
def cut_job(page):
    """Each test here starts on cardboard on the CO2 laser, on basic, as a fresh page does, and leaves the next test
    the same: the tabs' reset keeps the material and the machine a test before picked."""
    cardboard_on_the_laser(page)
    yield
    cardboard_on_the_laser(page)


def test_each_kind_sets_printed_the_machine_and_a_material(page):
    """One click sets what that kind needs, and the plan the server built is cut or printed with it."""
    use(page, "egg", "stacked")
    page.click('nav button[data-t="sheet"]')
    r = kind(page, "router")
    assert r["pressed"] == ["router"], r
    assert (r["s"]["printed"], r["s"]["machine"], r["s"]["material"], r["s"]["relief"], r["s"]["tool_d"], r["s"]["gap"]) == \
        (False, "router", "plywood", "dogbone", 3.175, 6.35), r            # plywood: a router does not cut cardboard
    assert (r["plan"]["tool_d"], r["plan"]["gap"], r["plan"]["material"]) == (3.175, 6.35, "plywood"), r
    r = kind(page, "printer")
    assert r["pressed"] == ["printer"], r
    assert (r["s"]["printed"], r["s"]["machine"], r["s"]["material"], r["s"]["kerf"], r["s"]["slot_offset"]) == \
        (True, "fdm", "PETG", 0, 0.2), r
    assert r["plan"]["printed"] and r["plan"]["material"] == "PETG" and plan(page)["sheet"] == [180, 180], r   # a print bed
    r = kind(page, "mix")                                                  # the laser this visit had, and standoffs
    assert r["pressed"] == ["mix"], r
    assert (r["s"]["printed"], r["s"]["machine"], r["s"]["material"], r["s"]["connect"]) == (False, "co2", "cardboard", "standoff"), r
    assert r["plan"]["connect"] == "standoff" and not r["plan"]["printed"], r
    r = kind(page, "laser")
    assert r["pressed"] == ["laser"] and r["s"]["connect"] == "dowel" and r["s"]["machine"] == "co2", r


def test_the_export_tab_follows_the_kind(page):
    """The Export tab names the job by its machines: a router job, a printed job, a cut job on printed standoffs."""
    use(page, "egg", "stacked")
    said = {}
    for k in ("router", "printer", "mix"):
        page.click('nav button[data-t="sheet"]')
        kind(page, k)
        page.click('nav button[data-t="export"]')
        said[k] = page.text_content("#machines")
    assert "This job is cut." in said["router"] and "⚙ CNC ROUTER" in said["router"], said
    assert "This job is printed." in said["printer"] and "⬢ 3D PRINTER" in said["printer"], said
    assert "Two machines make this model." in said["mix"] and "✂ LASER" in said["mix"], said


def test_undo_takes_a_kind_change_back_in_one_step(page):
    """Machine, material, thickness, sheet, compensation and `printed` change together, and one undo puts all back."""
    page.click('nav button[data-t="sheet"]')
    before = page.evaluate(NOW)
    after = kind(page, "printer")
    assert after["s"] != before["s"], after
    page.click("#undo")
    settle(page)
    back = page.evaluate(NOW)
    assert back["s"] == before["s"] and back["pressed"] == ["laser"], (before, back)


def test_changing_back_restores_what_was_there(page):
    """Off to the printer and back: the laser, the material, its thickness and the bed this job had come back; a router's
    gap of two bits goes when the bit does."""
    page.click('nav button[data-t="sheet"]')
    page.select_option("#machine", "glowforge"); settle(page)
    page.select_option("#thicklist", "3"); settle(page)
    was = page.evaluate(NOW)["s"]
    assert was["sheet"] == [495, 279] and was["thickness"] == 3, was
    kind(page, "printer")
    r = kind(page, "laser")["s"]
    assert (r["machine"], r["material"], r["thickness"], r["sheet"], r["printed"]) == ("glowforge", "cardboard", 3, [495, 279], False), r
    assert kind(page, "router")["s"]["gap"] == 6.35
    assert kind(page, "laser")["s"]["gap"] == 3, "the gap of two bits stayed on the laser"


def test_a_machine_of_your_own_shows_under_its_kind(page):
    """A router of your own (+ beside the machine) is listed with the routers only, and comes back with its own fit."""
    page.click('nav button[data-t="sheet"]')
    kind(page, "router")
    page.fill("#p_slot_offset", "0.33"); page.press("#p_slot_offset", "Enter"); settle(page)
    page.once("dialog", lambda d: d.accept("my cnc"))
    page.click("#kadd")
    machines = lambda: page.eval_on_selector_all("#machine option", "os => os.map(o => o.value)")   # noqa: E731
    mine = lambda: page.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('slicer_machines') || '{}'))")   # noqa: E731
    try:
        assert page.input_value("#machine") == "my cnc" and "shapeoko" in machines() and "co2" not in machines()
        kind(page, "laser")
        assert "my cnc" not in machines() and "co2" in machines(), machines()
        r = kind(page, "router")
        assert page.input_value("#machine") == "my cnc" and (r["s"]["slot_offset"], r["s"]["tool_d"]) == (0.33, 3.175), r
        assert r["plan"]["slot_offset"] == 0.33, r
    finally:
        page.select_option("#machine", "my cnc"); page.click("#kdel"); settle(page)   # this browser keeps it otherwise
    assert "my cnc" not in mine()


def test_laser_and_printer_together_only_where_layers_stack(page):
    """Printed standoffs hold stacked layers apart: the fourth choice is offered with the stacked technique only, and
    says why when it is not."""
    use(page, "egg", "interlocked")
    page.click('nav button[data-t="sheet"]')
    mix = '#kind [data-kind="mix"]'
    assert page.is_disabled(mix) and "stacked" in page.get_attribute(mix, "title")
    use(page, mode="stacked")
    page.click('nav button[data-t="sheet"]')
    assert page.is_enabled(mix)


def test_the_choice_follows_a_setting_that_prints_part_of_the_job(page):
    """Marcel, 2026-11-23: a laser job whose layers go onto printed standoffs becomes laser + 3D printer by itself, and
    laser again when they go; the line under the choice says why, with no dialog; one undo takes the change back; a
    click on the choice itself needs no line."""
    use(page, "egg", "stacked")
    why = lambda: page.text_content("#kind_why")                         # noqa: E731
    pressed = lambda: page.evaluate("() => [...document.querySelectorAll('#kind [aria-pressed=true]')].map(b => b.dataset.kind)")   # noqa: E731
    set_fields(page, [("p_connect", "standoff")]); settle(page)
    assert pressed() == ["mix"] and why().startswith("Now Laser + 3D printer:") and "standoffs" in why(), why()
    assert not state(page)["printed"] and plan(page)["params"]["connect"] == "standoff"
    set_fields(page, [("p_connect", "dowel")]); settle(page)
    assert pressed() == ["laser"] and why().startswith("Now Laser: nothing is printed") and "dowel" in why(), why()
    page.click("#undo"); settle(page)
    assert pressed() == ["mix"] and state(page)["connect"] == "standoff" and "standoffs" in why(), "one undo takes it back"
    assert not page.locator("dialog[open]").count()
    page.click('nav button[data-t="sheet"]')
    kind(page, "laser")
    assert pressed() == ["laser"] and why() == "", "a click on the choice needs no line"


def test_a_machine_that_cannot_cut_the_material_brings_one_it_can(page):
    """A fiber laser cuts metal: picked on a cardboard job, it brings steel with it rather than a job it cannot cut."""
    page.click('nav button[data-t="sheet"]')
    page.select_option("#machine", "fiber"); settle(page)
    s = state(page)
    assert (s["machine"], s["material"]) == ("fiber", "steel"), s


def test_settings_a_kind_has_no_use_for_are_held_back(page):
    """A printer has no kerf and no bit, a laser no bit: those rows wait under their section's "+ N more" line, one
    click shows them, the search box finds them, a changed one shows by itself, and on "all" they are still held back."""
    page.click('nav button[data-t="sheet"]')
    row = lambda p: f'.f[data-p="{p}"]'                                   # noqa: E731
    shown = lambda p: page.evaluate(SHOWN, row(p))                        # noqa: E731
    more = lambda p: page.evaluate("q => document.querySelector(q).closest('.sec').querySelector(':scope>.more').textContent", row(p))   # noqa: E731
    assert not shown("relief") and not shown("tool_d") and shown("compensate"), "a laser needs no bit"
    assert "inside-corner relief" in more("relief") and "bit diameter" in more("relief")
    kind(page, "printer")
    assert not shown("compensate") and not shown("relief") and shown("slot_offset"), "the print set uses the slot fit"
    assert "compensate kerf" in more("compensate")
    page.evaluate("q => document.querySelector(q).closest('.sec').querySelector(':scope>.more').click()", row("compensate"))
    assert shown("compensate")
    page.fill("#find", "relief")
    assert shown("relief")
    page.fill("#find", ""); page.press("#find", "Escape")
    page.click('#level button[data-level="all"]')
    assert not shown("relief") and not shown("scale_check") and shown("sheet_margin"), "on all, still held back"
    kind(page, "laser")
    assert shown("scale_check") and not shown("relief")
    set_fields(page, [("p_relief", "dogbone")]); settle(page)
    assert shown("relief"), "a changed setting always shows"
    assert state(page)["relief"] == "dogbone"                             # held back, never reset
