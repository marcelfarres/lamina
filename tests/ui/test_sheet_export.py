"""The Sheet and Export tabs: sheet size, units, weights, materials, every control and every download."""
import json
import math
import pathlib
import re

import pytest

from .helpers import settle, plan, set_fields, zip_of, state, use, menu, example


@pytest.mark.timeout(600)
def test_a_model_too_big_for_the_sheet_says_what_would_fit(page):
    """510 × 298 mm of cardboard and a model half a metre tall: the parts cannot fit, so the report has to say so and
    name the size that would — not quietly draw parts over each other and off the page."""
    use(page, mode="stacked")
    page.click('nav button[data-t="sheet"]')
    set_fields(page, [("p_sheet_0", 510), ("p_sheet_1", 298), ("p_split", False)])
    settle(page)
    page.click('nav button[data-t="model"]')
    set_fields(page, [("p_size_1", 500)])
    settle(page)
    p = plan(page)
    assert any("bigger than the 510 × 298 mm sheet" in e for e in p["errors"]), p["errors"]
    assert any("set `size` to about" in e for e in p["errors"]), p["errors"]
    fixes = [o["title"] for sl in p["slices"] for f in sl["fixes"] for o in f["options"]]
    assert any(t.startswith("scale the model to") for t in fixes), fixes
    assert any(t == "split oversize parts" for t in fixes), fixes
    page.click("#origsize")
    settle(page)


@pytest.mark.timeout(900)
def test_units_change_what_is_shown_never_what_is_stored(page):
    """The unit on the toolbar is how lengths read, never what they are. Typed in inches, a value reaches the server
    exact (1/16 in is 1.5875 mm, not 1.59); the boxes step in round numbers of the unit, so 0.25 in is a valid entry;
    switching back and forth leaves every stored value where it was; and the planner's messages, its fix buttons and
    the help, all written in mm, read in the unit on show."""
    use(page, mode="stacked")
    page.select_option("#unit", "in")
    page.click('nav button[data-t="sheet"]')
    step, low = page.eval_on_selector("#p_thickness", "el => [el.step, el.min]")
    assert re.fullmatch(r"0\.0*[125]", step), step                      # a round step of the unit, not 0.0019685
    assert abs(float(low) / float(step) - round(float(low) / float(step))) < 1e-9, (low, step)   # min on the step grid
    assert page.eval_on_selector("#p_thickness", "el => { el.value = '0.25'; return el.checkValidity() }")

    set_fields(page, [("p_thickness", 0.0625)])                          # 1/16 in
    settle(page)
    assert plan(page)["params"]["thickness"] == 1.5875
    assert "1/16 in stock" in page.text_content("#sheets")               # the sheet header reads the fraction it is sold by
    # a slice of its own thickness, from its panel: selected through the parts table's own handler (the table sits in
    # a panel this viewport keeps closed)
    label = page.eval_on_selector("#parts tr[data-s]", "tr => { tr.click(); return tr.dataset.s }")
    page.eval_on_selector("#n_thick", "el => { el.value = '0.09375'; el.dispatchEvent(new Event('change')) }")   # 3/32 in
    settle(page)
    assert state(page)["thick"][label] == 2.38125   # was rounded to 2.38

    before = page.evaluate("() => JSON.stringify(window.__t.state())")
    for _ in range(10):
        for u in ("cm", "mm", "in"):
            page.select_option("#unit", u)
    assert page.evaluate("() => JSON.stringify(window.__t.state())") == before

    page.select_option("#unit", "mm")                                    # a job that does not fit, set up in mm …
    set_fields(page, [("p_sheet_0", 510), ("p_sheet_1", 298), ("p_split", False)])
    settle(page)
    page.click('nav button[data-t="model"]')
    set_fields(page, [("p_size_1", 500)])
    settle(page)
    page.select_option("#unit", "in")                                    # … read in inches, without a re-slice
    msgs = page.text_content("#msgs")
    assert "20.0787 × 11.7323 in sheet" in msgs, msgs
    assert not re.search(r"\d\s*mm\b", msgs), msgs
    assert not any(re.search(r"\d\s*mm\b", t) for t in page.eval_on_selector_all("#msgs .fix", "fs => fs.map(f => f.textContent)"))
    page.click('nav button[data-t="sheet"]')
    page.hover('[data-p="thickness"] .k')
    tip = page.text_content("#tip")
    assert "(in)" in tip and "0.0118 in" in tip and not re.search(r"\d\s*mm\b|\(mm\)", tip), tip
    page.select_option("#unit", "mm")
    page.click('nav button[data-t="model"]')
    page.click("#origsize")
    settle(page)


@pytest.mark.timeout(900)
def test_the_export_tab_weighs_the_parts(page):
    """The cube as four 180 × 180 mm slices of 14 ga steel (1.897 mm, 7.85 g/cm³): 4 × 32400 mm² × 1.897 mm =
    245.85 cm³, which is 1.93 kg — worked out by hand, not by the page. One slice cut from 6 mm instead weighs on its
    own stock line (1.45 kg + 1.53 kg = 2.97 kg). Inches read in pounds and lb/in³, and a material of your own keeps
    the density typed for it."""
    use(page, "cube", "stacked")
    set_fields(page, [("p_distribution", "count"), ("p_count", 4), ("p_connect", "none")])
    settle(page)
    page.click('nav button[data-t="sheet"]')
    page.select_option("#material", "steel")
    page.select_option("#thicklist", "1.897")                            # 14 ga
    settle(page)
    page.click('nav button[data-t="export"]')
    weight = lambda: page.text_content("#weight")
    assert "1.93 kg" in weight() and "246 cm³" in weight() and "7.85 g/cm³" in weight(), weight()
    # the stock area to buy: whole sheets, offcuts included, against the area that becomes parts
    p = plan(page)
    buy = p["sheets"] * p["sheet"][0] * p["sheet"][1]                       # mm²
    assert f"{buy/1e6:.3g} m²" in weight() and "to buy" in weight(), weight()
    assert f"{p['material_area_mm2']/1e6:.3g} m² in the parts" in weight(), weight()

    page.evaluate("""() => { window.__t.state().thick = {'Z-2': 6};
        document.getElementById('p_count').dispatchEvent(new Event('input', {bubbles: true})) }""")
    settle(page)
    assert "2.97 kg" in weight(), weight()
    assert "1.897 mm stock: 3 part(s) · 1.45 kg" in weight() and "6 mm stock: 1 part(s) · 1.53 kg" in weight(), weight()
    page.evaluate("""() => { window.__t.state().thick = {};
        document.getElementById('p_count').dispatchEvent(new Event('input', {bubbles: true})) }""")
    settle(page)

    page.select_option("#unit", "in")
    assert "4.25 lb" in weight() and "0.2836 lb/in³" in weight(), weight()
    assert f"{buy/92903.04:.3g} ft²" in weight(), weight()                   # square feet, not m²
    page.select_option("#unit", "mm")

    # dowels: two aligned rods, each one piece from the first slice's outer face to the last one's, of the same steel
    page.click('nav button[data-t="technique"]')
    set_fields(page, [("p_connect", "dowel")])
    settle(page)
    page.click('nav button[data-t="export"]')
    p = plan(page)
    assert len(p["rods"]) == 2 * 3, p["rods"]                            # two points × three pairs of slices
    n = p["slices"][0]["M"]; z = sorted(sum(s["M"][i][3] * n[i][2] for i in range(3)) for s in p["slices"])
    rod = (z[-1] - z[0]) + 1.897                                         # outer face to outer face
    sec = p["rods"][0][3]                                                # the rod's section as cut: a 96-gon, not π r²
    area = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(sec, sec[1:] + sec[:1]))) / 2
    assert abs(area - math.pi * 3 ** 2) < 0.01 * math.pi * 3 ** 2, area  # 6 mm dowels
    mass = 2 * rod * area * 7.85 / 1000                                  # in grams
    assert "2 dowel(s)" in weight() and f"{mass:.3g} g" in weight(), (mass, weight())
    # assembled = parts + dowels, the parts now 8 holes lighter: 6 mm dowels + the fiber laser's 0.15 mm slot offset
    holes = 8 * math.pi * 3.075 ** 2 * 1.897 * 7.85 / 1000
    assert f"{(245.8512 * 7.85 - holes + mass) / 1000:.3g} kg" in weight(), (holes, mass, weight())
    page.click('nav button[data-t="technique"]')
    set_fields(page, [("p_connect", "none")])
    settle(page)

    page.click('nav button[data-t="sheet"]')                             # a material of your own, with its own density
    # the name is answered by the page's own prompt: an earlier test leaves a handler that accepts every dialog empty
    page.evaluate("() => { const p = window.prompt; window.prompt = () => (window.prompt = p, 'birch from the yard') }")
    page.click("#matadd")
    assert page.eval_on_selector("#material", "s => s.value") == "birch from the yard"
    set_fields(page, [("density", 0.6)])
    page.select_option("#material", "plywood")
    page.select_option("#material", "birch from the yard")                 # the density went with the material
    assert page.input_value("#density") == "0.6"
    page.select_option("#thicklist", "1.897")
    settle(page)
    page.click('nav button[data-t="export"]')
    assert "148 g" in weight(), weight()                                 # 245.85 cm³ × 0.6 g/cm³ = 147.5 g
    page.click('nav button[data-t="sheet"]')
    page.click("#matdel")
    assert "birch from the yard" not in page.eval_on_selector_all("#material option", "os => os.map(o => o.value)")
    assert page.eval_on_selector("#material", "s => s.value") == "steel"   # back to the built-in it was made from
    settle(page)


@pytest.mark.timeout(1200)
def test_every_material_is_complete(page):
    """Each material on the list, picked the way a person picks it: it lands on its own machine, one of its stock
    thicknesses, a sheet it is sold in and a 3D look that exists, and the Export tab weighs it at its own density.
    A material missing any of these would leave the form holding the last one's values."""
    use(page, "cube", "stacked")
    set_fields(page, [("p_distribution", "count"), ("p_count", 2), ("p_connect", "none")])
    settle(page)
    page.click('nav button[data-t="sheet"]')
    names = page.eval_on_selector_all("#material option", "os => os.map(o => o.value)")
    for want in ("stainless steel", "brass", "copper", "greyboard", "polypropylene", "foam board", "EVA foam", "basswood", "balsa"):
        assert want in names, (want, names)
    looks = page.eval_on_selector_all("#look option", "os => os.map(o => o.value)")
    for name in names:
        page.select_option("#material", name)
        settle(page)
        got = page.evaluate("""() => ({machines: [...document.querySelectorAll('#machine option')].map(o => o.value),
            machine: document.getElementById('machine').value, thick: document.getElementById('thicklist').value,
            sheet: document.getElementById('sheetpreset').value, look: document.getElementById('look').value,
            density: +document.getElementById('density').value, t: window.__t.state().thickness})""")
        assert got["machine"] in got["machines"], (name, got)                       # a machine that cuts it
        assert got["thick"] and abs(float(got["thick"]) - got["t"]) < 1e-9, (name, got)   # one of its own stocks
        assert got["sheet"], (name, got)                                            # a size it is sold in
        assert got["look"] in looks, (name, got)
        assert 0.01 < got["density"] < 20, (name, got)
        # the weight is drawn with the plan that comes back after the switch: wait for it rather than read the last one
        page.wait_for_function("d => (document.getElementById('weight').textContent || '').includes(d + ' g/cm')",
                               arg=f"{got['density']:g}", timeout=60_000)
        assert f"{got['density']:g} g/cm³" in page.text_content("#weight"), (name, page.text_content("#weight"))
    page.select_option("#material", "stainless steel")                     # its own gauges, not carbon steel's
    assert "14 ga · 1.984 mm" in page.text_content("#thicklist")
    # printed materials: made by a printer and nothing else, nested on its bed, and the Export tab's print set at 1:1
    set_fields(page, [("pr_scale", 0.5)])                                  # it sits on the Export tab, closed here
    page.select_option("#material", "PETG")
    settle(page)
    machines = page.eval_on_selector_all("#machine option", "os => os.map(o => o.value)")
    assert "fdm" in machines and "co2" not in machines and "hand" not in machines, machines
    page.select_option("#machine", "bambu_h2c")
    settle(page)
    assert plan(page)["sheet"] == [325, 320] and plan(page)["params"]["slot_offset"] == 0.2
    assert page.input_value("#pr_scale") == "1"
    assert "1.27 g/cm³" in page.text_content("#weight")
    page.select_option("#material", "cardboard")
    settle(page)


def test_the_look_follows_the_material_into_the_next_job(page):
    """Bug 057: fold_lamp's preset picks PETG, and picking a material turns the 3D look to that material's, plastic.
    The next example, a project or an undo put the material back to cardboard without the picker, and the look
    stayed: a cardboard job showed as blue plastic. Now the look follows the material whichever way it changed."""
    look = lambda: page.evaluate("() => [document.getElementById('material').value, document.getElementById('look').value,"   # noqa: E731
                                 " window.__t.parts()[0].material.color.getHex()]")
    use(page, "sphere")
    fresh = look()
    assert fresh[:2] == ["cardboard", "group"], fresh
    example(page, "fold_lamp")
    assert look()[:2] == ["PETG", "plastic"]
    example(page, "sphere")
    assert look() == fresh                                        # by family again, its parts in their family colours
    page.click('nav button[data-t="sheet"]')
    page.select_option("#material", "steel")
    settle(page)
    assert look()[:2] == ["steel", "steel"]                       # picking a material still shows its own look
    page.click("#undo")
    settle(page)
    assert look() == fresh


@pytest.mark.timeout(1800)
def test_every_control_does_what_it_says_and_every_download_holds_the_plan(page, server):
    """Every button, slider and download of the app, pressed once, and what it produced read back: the 3D view bar,
    the selected-part panel, revisions, help, saved presets, the thickness and sheet lists, the one-click fixes, and
    every file behind the Export tab — opened and held against the plan it came from (the sheets name every part, the
    key lists every part, the STL is whole, the prototype carries a plate). A control that stops working, or a file
    that stops matching what the screen shows, fails here."""
    import xml.etree.ElementTree as ET
    names = iter(["ui preset", "ui sheet"])
    answer = lambda d: d.accept(next(names, "ui")) if d.type == "prompt" else d.accept()
    page.on("dialog", answer)
    use(page, "egg", "interlocked")
    p = plan(page)
    labels = {pc["label"] for s in p["slices"] for pc in s["pieces"]}
    ev = page.evaluate

    # -- the 3D view bar
    page.fill("#explode", "2"); page.dispatch_event("#explode", "input")
    assert ev("() => window.__t.parts().some(m => m.position.length() > 1)"), "explode moved nothing"
    page.fill("#explode", "1"); page.dispatch_event("#explode", "input")
    page.fill("#steps", "1"); page.dispatch_event("#steps", "input")
    assert ev("() => window.__t.parts().filter(m => m.visible && m.userData.group !== 'B').length") == 1, "steps did not step"
    ev("() => { const s = document.querySelector('#steps'); s.value = s.max; s.dispatchEvent(new Event('input')) }")
    page.uncheck("#ghost"); assert ev("() => !window.__t.ghost()[0].parent.visible"), "the model did not hide"
    page.check("#ghost")
    before = ev("() => window.__t.parts()[0].material.color.getHex()")
    page.select_option("#look", "steel")
    assert ev("() => window.__t.parts()[0].material.color.getHex()") != before, "the look did not change the parts"
    page.select_option("#look", "group")
    page.select_option("#viewmode", "only3d"); assert "only3d" in page.get_attribute("#view", "class")
    page.select_option("#viewmode", "both")
    ev("() => window.__t.cam(10, 80, 50000)"); page.click("#fit")
    assert ev("() => window.__t.camera.position.length()") < 50000, "fit view did not bring the model back"

    # -- the selected-part panel: move, reset, close, delete
    lab = p["slices"][0]["label"]
    ev(f"() => window.__t.select('{lab}')"); page.wait_for_timeout(200)
    assert page.is_visible("#sel") and page.text_content("#sel b") == lab
    page.fill("#n_offset", "3"); page.dispatch_event("#n_offset", "change"); settle(page)
    assert abs(ev(f"() => window.__t.state().offset['{lab}']") - 3) < 1e-6, "the offset box did not reach the slice"
    page.click("#s_reset"); settle(page)
    assert ev(f"() => !(window.__t.state().offset || {{}})['{lab}']"), "reset left the offset"
    ev(f"() => window.__t.select('{lab}')"); page.click("#s_close"); assert not page.is_visible("#sel")
    ev(f"() => window.__t.select('{lab}')"); page.click("#s_del")
    page.wait_for_function(f"() => !window.__t.plan().slices.some(s => s.label === '{lab}')", timeout=180_000)   # the re-slice that drops it
    settle(page)
    assert lab in ev("() => window.__t.state().skip")
    ev("() => document.querySelector('#undo').click()"); settle(page)
    assert lab in {s["label"] for s in plan(page)["slices"]}, "undo did not bring the deleted slice back"

    # -- header: revisions and help
    rev = page.text_content("#prev")
    menu(page, "#pminor"); assert page.text_content("#prev") != rev
    menu(page, "#pmajor"); assert page.text_content("#prev").endswith(".0")
    menu(page, "#helpbtn"); assert page.locator("#helpdlg[open]").count(); page.click("#help_go")
    assert not page.locator("#helpdlg[open]").count()

    # -- the Sheet & fit lists: a saved preset, a thickness, a sheet size — added, then removed
    page.click('nav button[data-t="sheet"]')
    page.click("#psave"); assert "ui preset" in page.eval_on_selector_all("#presets option", "o => o.map(x => x.value)")
    page.select_option("#presets", "ui preset"); page.click("#pdel")
    assert "ui preset" not in page.eval_on_selector_all("#presets option", "o => o.map(x => x.value)")
    page.fill("#p_thickness", "2.37"); page.dispatch_event("#p_thickness", "input"); settle(page)
    page.click("#madd")
    assert 2.37 in ev("() => Object.values(JSON.parse(localStorage.getItem('slicer_thick') || '{}')).flat()")
    page.select_option("#thicklist", index=page.eval_on_selector_all("#thicklist option", "o => o.findIndex(x => +x.value === 2.37)"))
    page.click("#mdel")
    assert 2.37 not in ev("() => Object.values(JSON.parse(localStorage.getItem('slicer_thick') || '{}')).flat()")
    page.click("#sadd")
    assert any(s[0] == "ui sheet" for s in ev("() => JSON.parse(localStorage.getItem('slicer_sheets') || '[]')"))
    page.select_option("#sheetpreset", index=page.eval_on_selector_all("#sheetpreset option", "o => o.length - 1")); page.click("#sdel")
    assert not any(s[0] == "ui sheet" for s in ev("() => JSON.parse(localStorage.getItem('slicer_sheets') || '[]')"))
    page.click("#usage_optin") if page.is_visible("#usage_optin") else None
    page.fill("#p_thickness", "1.5"); page.dispatch_event("#p_thickness", "input"); settle(page)

    # -- every download: fetched as the link has it, opened, and held against the plan
    page.click('nav button[data-t="export"]')
    p = plan(page); labels = {pc["label"] for s in p["slices"] for pc in s["pieces"]}
    from core.export import design_name
    design = design_name(p)                              # every file in a zip is named after the design, as the zip is
    links = {a["t"]: a["h"] for a in page.eval_on_selector_all('section[data-tab="export"] .dl a', "as => as.map(a => ({t: a.textContent, h: a.getAttribute('href')}))")}
    get = lambda href: page.request.get(f"{server}/{href}")
    z = zip_of(get(links[next(t for t in links if t.endswith("sheets SVG + DXF (.zip)"))]).body())
    svgs = [n for n in z.namelist() if n.endswith(".svg")]
    assert svgs and any(n.endswith(".dxf") for n in z.namelist()) and f"{design} assembly-key.txt" in z.namelist()
    assert "README.txt" in z.namelist()                       # what is in the zip and how to cut it: the one name every zip shares
    assert all(n.startswith(f"{design} ") or n in (f"{design}.lamina.json", "README.txt") for n in z.namelist()), z.namelist()
    drawn = {el.get("data-label") for n in svgs for el in ET.fromstring(z.read(n)).iter() if el.get("data-label")}   # noqa: S314 — our own server's SVG
    assert labels <= drawn, f"parts in the plan but on no sheet: {sorted(labels - drawn)[:5]}"
    key = z.read(f"{design} assembly-key.txt").decode()
    assert all(lb in key for lb in labels), "the assembly key misses parts"
    pdf = zip_of(get(links["sheets PDF (one page per sheet)"]).body())       # zipped, with the key and the project file
    assert [pdf.read(n)[:4] for n in pdf.namelist() if n.endswith(".pdf")] == [b"%PDF"]
    groups = lambda z: sum(len(re.findall(rb"/Subtype\s*/Form\b", z.read(n))) for n in z.namelist() if n.endswith(".pdf"))   # noqa: E731
    assert groups(pdf) >= len(labels), "group parts is ticked: each part is one group in the PDF (bug 081)"
    page.eval_on_selector("#x_grouped", "e => e.click()")     # unticked: the PDF's link carries it, and the file is the lines alone
    assert groups(zip_of(get(page.eval_on_selector_all('section[data-tab="export"] .dl a', "as => as.find(a => a.textContent.startsWith('sheets PDF')).getAttribute('href')")).body())) == 0
    page.eval_on_selector("#x_grouped", "e => e.click()")
    eps = zip_of(get(links["sheets EPS"]).body())
    assert all(eps.read(n)[:4] == b"%!PS" for n in eps.namelist() if n.endswith(".eps"))
    pieces = zip_of(get(links["one file per piece SVG + DXF"]).body())
    assert f"{design} cut-list.txt" in pieces.namelist() and len([n for n in pieces.namelist() if n.endswith(".svg")]) >= 2
    stl = get(links["assembled STL"]).body()
    assert len(stl) == 84 + 50 * int.from_bytes(stl[80:84], "little") and int.from_bytes(stl[80:84], "little") > 100, "the STL is not whole"
    one = get(links["assembled STL"] + "?part=" + sorted(labels)[0]).body()     # one part alone, as the parts table offers it
    assert len(one) == 84 + 50 * int.from_bytes(one[80:84], "little") and 0 < len(one) < len(stl)
    assert get(links["STEP: parts"]).body().count(b"MANIFOLD_SOLID_BREP('") >= len(labels), "the STEP misses parts"
    assert 1 <= get(links["STEP: one body"]).body().count(b"MANIFOLD_SOLID_BREP('") < len(labels), "the one body is not fused"
    assert json.loads(get(links["plan.json"]).body())["counts"]["parts"] == p["counts"]["parts"]
    fit = zip_of(get(links[next(t for t in links if "fit test to cut" in t)]).body())
    assert "README.txt" in fit.namelist() and len({n.split("/")[0] for n in fit.namelist() if "/" in n}) == 5
    page.click("#opts_fold > summary")                                   # the options are folded under the main button
    page.uncheck("#x_key"); page.uncheck("#x_labels")
    href = page.eval_on_selector("#dl a", "a => a.getAttribute('href')")
    assert "key=0" in href and "labels=0" in href
    assert not any(n.endswith("assembly-key.txt") for n in zip_of(get(href).body()).namelist())
    page.check("#x_key"); page.check("#x_labels")

    # -- prototyping: the fields reach the request, and the zips hold a plate
    page.click("#pr_fold > summary"); page.click("#fit_opts > summary")   # both groups open on their heading: the joint step is with the fit test
    page.fill("#pr_size", "120"); page.select_option("#pr_labels", "hole"); page.fill("#pr_font", "4")
    page.fill("#pr_min", "1"); page.fill("#pr_offset", "0.3"); page.fill("#pr_step", "0.05")
    for btn, want in (("#pr_go", "plate.3mf"), ("#fit_go", "plate.3mf")):
        with page.expect_download(timeout=300_000) as dl:
            page.click(btn + " a")
        url = dl.value.url
        assert all(q in url for q in ("size=120", "labels=hole", "font=4", "min_thick=1", "offset=0.3")), url
        assert want in zip_of(pathlib.Path(dl.value.path()).read_bytes()).namelist()

    # -- the assembly video: a real webm, and the view put back as it was
    with page.expect_download(timeout=120_000) as vid:
        page.click("#vid_go")
    assert vid.value.suggested_filename.endswith(".webm") and pathlib.Path(vid.value.path()).stat().st_size > 10_000
    assert ev("() => window.__t.parts().every(m => m.userData.group === 'B' || m.visible)"), "the video left parts hidden"

    # -- a one-click fix: axes on no plane, one click puts them back on one and the error goes
    use(page, "dumbbell")
    ev("() => window.__t.applyFix({axes: [[[-72, 0, -108], [72, 0, -108]], [[0, -72, 108], [0, 72, 108]]]})"); settle(page)
    assert plan(page)["counts"]["errors"] > 0
    page.click("#msgs .fix"); settle(page)
    assert plan(page)["counts"]["errors"] == 0, plan(page)["errors"]
    page.remove_listener("dialog", answer)
    assert not page.errors, page.errors


def test_the_one_body_step_warns_on_folded_panels(page):
    """Marcel, 2026-11-22: STEP: one body on every technique, and on a Folded Panels job a plain warning that the file
    may not open as a valid solid in CAD (CAD rejected the fused panels of 6 of 8 folded examples). A stacked job has
    the row and no warning."""
    warning = "() => document.querySelector('#dl_step_body .warn')?.textContent || ''"
    use(page, "fold_box"); page.click('nav button[data-t="export"]'); page.click("#more_fold > summary")
    assert page.is_visible("#dl_step_body") and "may not open as a valid solid in CAD" in page.evaluate(warning)
    use(page, "vase"); page.click('nav button[data-t="export"]'); page.click("#more_fold > summary")   # a new job opens with it folded
    assert page.is_visible("#dl_step_body") and page.evaluate(warning) == ""
