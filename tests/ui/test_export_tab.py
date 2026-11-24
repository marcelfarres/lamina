"""The Export tab by machine (feature/export-tab; Marcel, 2026-11-22, questions 6 to 8 of the export review): what the
job is and which machine makes what, the fit test only where a joint needs it, one main button per machine with the
rest folded, a warning when the plan has errors, and no section of the last job left open."""
import re

from .helpers import plan, settle, use, zip_of

EXPORT = 'nav button[data-t="export"]'
SHOWN_LINKS = """() => [...document.querySelectorAll('section[data-tab="export"] a[href]')]
    .filter(a => a.offsetParent).map(a => a.getAttribute('href'))"""


def export_tab(page, name):
    """The example opened as the library opens it, then its Export tab: what the summary says."""
    use(page, name)
    page.click(EXPORT)
    return page.inner_text("#machines")


def stock(page, **boxes):
    """What you make with, material, thickness and machine set on Sheet & fit, the controls a person uses, each waited for."""
    page.click('nav button[data-t="sheet"]')
    for box, value in boxes.items():
        if box == "kind":
            page.click(f'#kind [data-kind="{value}"]')
        else:
            page.select_option(f"#{box}", value)
        settle(page)
    page.click(EXPORT)


def test_a_laser_job_names_its_machine_and_stock_and_has_one_main_file(page):
    said = export_tab(page, "vase")
    rods = len({r[5] for r in plan(page)["rods"] if len(r) >= 8})          # by name, as the assembly key lists them
    assert said.startswith("This job is cut.") and "✂ LASER · CO2 laser, cardboard 3 mm" in said and "600 × 400 mm" in said
    assert f"Also {rods} dowel rods" in said and f"{rods} dowel(s)" in page.inner_text("#weight")   # one count on the tab
    assert [page.text_content(h) for h in ("#fit_title", "#dl_title", "#build_title")] == \
        ["1 · Fit test — cut this first", "2 · The files, by machine", "3 · Build it"]
    kerf = page.locator("#kerf_go a")                                     # the kerf test, next to the fit test
    assert kerf.inner_text().startswith("✂ kerf test to cut · 7 squares") and "/kerftest?fmt=svg,dxf" in kerf.get_attribute("href")
    main = page.locator("#x_files a.main")
    assert main.count() == 1 and main.get_attribute("data-machine") == "laser"
    assert main.inner_text() == "✂ LASER · sheets SVG + DXF (.zip)" and "/export?fmt=svg,dxf" in main.get_attribute("href")
    assert "README.txt" in page.inner_text("#dl .hint")                     # what it is for, on the page
    assert page.inner_text("#dlfit a").startswith("✂ fit test to cut · 5 hole sizes")
    assert not any(page.is_visible(h) for h in ("#dl_other", "#x_labels", "#more", "#x_errors"))   # the rest is folded
    assert "/key?" in page.get_attribute("#key_go a", "href")


def test_a_router_job_names_the_router_and_its_bit(page):
    use(page, "torus")
    stock(page, material="plywood", kind="router", thicklist="6", machine="shapeoko")
    said = page.inner_text("#machines")
    assert "⚙ CNC ROUTER · Shapeoko 4 XXL (CNC), plywood 6 mm" in said and "bit 3.175 mm" in said
    assert page.get_attribute("#x_files a.main", "data-machine") == "router"
    assert page.inner_text("#x_files a.main").startswith("⚙ CNC ROUTER · sheets") and page.inner_text("#dlfit a").startswith("⚙ fit test to cut")
    assert page.locator("#kerf_go").count() == 0                         # its CAM program offsets the bit: no kerf to find


def test_a_printed_job_shows_its_print_set_and_no_cut_file(page, server):
    """fold_box (seam joints: nothing for a fit test) and the vase printed in PETG (dowel pins: the print fit test).
    Neither shows a laser button: the fit-test buttons once showed through their hidden mark on a printed job. The
    print set button names what its zip holds, read from the zip: its plates, its pin plates, README, and the
    assembly key only when the zip has it; the summary counts the pin plates."""
    said = export_tab(page, "fold_box")
    assert said.startswith("This job is printed.") and "⬢ 3D PRINTER · Bambu Lab H2C, PETG 2 mm" in said
    assert not page.is_visible("#x_fit") and not page.is_visible("#pr_fold") and page.text_content("#dl_title") == "1 · The print files"
    main = page.locator("#pr_go a.main")
    assert main.get_attribute("data-machine") == "printer" and "/proto?" in main.get_attribute("href") and "scale=1" in main.get_attribute("href")
    assert page.is_visible("#pr_labels") and page.is_visible("#slicer_fold")
    links = page.evaluate(SHOWN_LINKS)
    assert not any("/fitcut" in h or "/export?" in h for h in links), links

    use(page, "vase")
    stock(page, material="PETG")
    assert page.evaluate("() => window.__t.state().printed")
    assert page.text_content("#fit_title") == "1 · Fit test — print this first"
    page.click("#fit_info > summary")                                       # what the fit test is: the printing words
    assert page.is_visible("#fit_what_print") and not page.is_visible("#fit_what")
    links = page.evaluate(SHOWN_LINKS)
    assert any("/fit?" in h for h in links) and not any("/fitcut" in h or "/export?" in h for h in links), links
    page.wait_for_function("() => document.querySelector('#pr_go a').textContent.includes('plate-1')", timeout=180_000)
    label = page.inner_text("#pr_go a")
    names = zip_of(page.request.get(f"{server}/{page.get_attribute('#pr_go a', 'href')}").body()).namelist()
    pins = [n[:-4] for n in names if re.fullmatch(r"pins-\d+\.3mf", n)]
    assert pins and all(s in label for s in pins) and "plate-1" in label, (label, names)
    assert ("assembly key" in label) == any(n.endswith("assembly-key.txt") for n in names), (label, names)
    assert ("README" in label) == ("README.txt" in names), (label, names)
    rods = len({r[5] for r in plan(page)["rods"] if len(r) >= 8})
    assert f"{len(pins)} plate{'s' * (len(pins) > 1)} of dowel pins ({rods})" in page.inner_text("#machines")


def test_a_job_on_two_machines_gives_each_its_fit_test_and_its_file(page, server):
    said = export_tab(page, "shade")
    n = len(plan(page)["standoffs"]["items"])
    assert said.startswith("Two machines make this model.") and "✂ LASER · CO2 laser, acrylic 3 mm" in said
    assert f"⬢ 3D PRINTER · {n} standoffs" in said and "Order: fit test, then cut, then print." in said
    assert page.text_content("#fit_title") == "1 · Fit test — cut and print this first"
    fits = page.eval_on_selector_all("#dlfit a", "as => as.map(a => a.getAttribute('href'))")
    assert any("/fitcut?" in h for h in fits) and any(h.endswith("/standoffs?fit=1") for h in fits), fits
    mains = page.eval_on_selector_all("#x_files a.main", "as => as.map(a => [a.dataset.machine, a.textContent])")
    assert mains == [["laser", "✂ LASER · sheets SVG + DXF (.zip)"], ["printer", f"⬢ 3D PRINTER · {n} standoffs (3MF)"]]
    got = page.request.get(f"{server}/{page.get_attribute('#dl_standoffs a', 'href')}")
    assert got.body()[:2] == b"PK" and f"3D-PRINT standoffs x{n}.3mf" in got.headers["content-disposition"]
    layers = plan(page)["counts"]["slices"]                                # a stack's parts are its layers
    assert f"{layers} layers" in said and f"{n} standoffs, 1 plate" in said
    page.wait_for_function("() => /fit test to print · \\d+ standoff/.test(document.querySelector('#dlfit').textContent)", timeout=180_000)
    fit = zip_of(page.request.get(f"{server}/{next(h for h in fits if h.endswith('/standoffs?fit=1'))}").body())
    made = len(re.findall(rb'<object id="\d+" name="', fit.read("3D/3dmodel.model")))   # one named object per standoff
    assert made and f"fit test to print · {made} standoff" in page.inner_text("#dlfit"), page.inner_text("#dlfit")


def test_a_glued_job_has_no_fit_test(page):
    """The paper lamp is held by glue tabs: its fit test was 1,100 parts that test nothing."""
    said = export_tab(page, "paper_lamp")
    assert plan(page)["fit_test"] is False and not page.is_visible("#x_fit")
    assert [page.text_content(h) for h in ("#dl_title", "#build_title")] == ["1 · The files, by machine", "2 · Build it"]
    assert said.count("✂ LASER") == 2 and "card 1 mm" in said and "paper" in said       # its two stocks, a line each
    page.click("#pr_fold > summary")
    assert page.locator("#fit_go").count() == 0                              # no print fit test under Prototyping either


def test_a_plan_with_errors_says_so_on_the_export_tab(page):
    use(page, "dumbbell")
    page.evaluate("() => window.__t.applyFix({axes: [[[-72, 0, -108], [72, 0, -108]], [[0, -72, 108], [0, 72, 108]]]})"); settle(page)
    errors = plan(page)["counts"]["errors"]
    assert errors > 0
    page.click(EXPORT)
    said = page.inner_text("#x_errors")
    assert page.is_visible("#x_errors") and said.startswith("⚠ WARNING") and f"{errors} error" in said
    page.click("#x_errors button")
    assert "on" in page.get_attribute('section[data-tab="checks"]', "class").split()


def test_no_section_of_the_last_job_stays_open(page):
    """A printed job opened its print plates' section, and it stayed open on the laser job after it. Now no code
    opens one, and a new job closes what the last one had open; a section opened on this job stays open as it changes."""
    use(page, "fold_box"); page.click(EXPORT)
    page.click("#more_fold > summary"); page.click("#parts_fold > summary")
    use(page, "vase"); page.click(EXPORT)
    assert page.evaluate("() => [...document.querySelectorAll('section[data-tab=\"export\"] details')].filter(d => d.open).length") == 0
    assert page.is_visible("#pr_fold")
    page.click("#more_fold > summary"); page.click("#fit_opts > summary"); page.fill("#pr_step", "0.05")
    assert page.evaluate("() => document.getElementById('more_fold').open") and "step=0.05" in page.get_attribute("#dlfit a", "href")
