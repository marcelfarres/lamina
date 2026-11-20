"""Printed standoffs on the page: the menu entry, its settings, the 3D view and the download."""
from .helpers import plan, set_fields, settle, use, zip_of


def test_the_shade_opens_on_printed_standoffs_drawn_in_3d_and_in_the_zip(page, server):
    """The shade example opens with `connect with` on standoff: the menu names it, its own settings show and the tab
    spacer's do not, every standoff is drawn in the 3D view as a pin and a body, and the sheets zip carries the print
    file. Set back to dowel, the standoffs go and rods come."""
    use(page, "shade")
    p = plan(page)
    n = len(p["standoffs"]["items"])
    assert n and p["params"]["connect"] == "standoff" and p["rods"] == []
    page.click('nav button[data-t="technique"]')
    assert page.eval_on_selector("#p_connect", "s => s.selectedOptions[0].textContent") == "standoff (3D printed)"
    assert page.locator("#p_shoulder").is_visible() and not page.locator("#p_spacer_dir").is_visible()
    drawn = "() => window.__t.axes().filter(m => m.isMesh && m.geometry.type === 'ExtrudeGeometry').length"
    assert page.evaluate(drawn) == 2 * n                                # a pin and a body each
    href = page.eval_on_selector_all("#dl a", "as => as.find(a => a.textContent === 'sheets SVG + DXF').getAttribute('href')")
    names = zip_of(page.request.get(f"{server}/{href}").body()).namelist()
    assert [x for x in names if "3D-PRINT standoffs" in x and x.endswith(".3mf")], names
    said = page.text_content("#two_machines")                           # the Export tab says which machine makes what
    assert "LASER" in said and "3D PRINTER" in said and f"{n} standoffs" in said

    set_fields(page, [("p_connect", "dowel")])
    settle(page)
    p = plan(page)
    assert p["standoffs"] is None and p["rods"] and page.evaluate(drawn) == len(p["rods"])
