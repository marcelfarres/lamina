"""The cut estimates of the Export tab (feature/estimates): the lengths come from the slice response, the speeds and the
price are typed on the page and kept in the browser, and the tiles follow the typing with no slice."""
from .helpers import settle, use

EXPORT = 'nav button[data-t="export"]'
KEY = "lamina.estimates"


def tiles(page):
    return {t.split("\n")[1]: t.split("\n")[0] for t in page.locator("#est_tiles .k").all_inner_texts()}


def test_the_tiles_follow_the_typed_speeds_and_price(page):
    page.evaluate(f"() => localStorage.removeItem('{KEY}')")
    use(page, "cube")
    page.click(EXPORT)
    est = page.evaluate("() => window.__t.estimate()")["total"]
    sheets = page.evaluate("() => window.__t.plan().sheets")
    shown = tiles(page)
    assert shown["pierces"] == str(est["pierces"]) > "0" and shown["machine time"] == "set a speed" and shown["to engrave"]
    assert shown[f"{sheets} sheet(s) × price"] == "set a price"
    page.fill("#est_cut", "20"); page.fill("#est_engrave", "100"); page.fill("#est_price", "12.5")
    secs = (est["cut"] + est["score"]) / 20 + est["engrave"] / 100
    got = tiles(page)
    assert got["machine time"] == (f"≈ {round(secs)} s" if secs < 90 else f"≈ {round(secs / 60)} min" if secs < 5400 else f"≈ {secs / 3600:.3g} h")
    assert got[f"{sheets} sheet(s) × price"] == f"{sheets * 12.5:g}"
    assert all(page.get_attribute(s, "data-tip") for s in ("#est_tiles .k", "label:has(#est_cut)", "label:has(#est_engrave)", "label:has(#est_price)"))
    page.reload(); settle(page); page.click(EXPORT)                         # kept in this browser
    assert [page.input_value(i) for i in ("#est_cut", "#est_engrave", "#est_price")] == ["20", "100", "12.5"]
    assert tiles(page)[f"{sheets} sheet(s) × price"] == f"{sheets * 12.5:g}"
    page.evaluate(f"() => localStorage.removeItem('{KEY}')")


def test_a_printed_job_has_no_estimates(page):
    use(page, "fold_box")
    page.click(EXPORT)
    assert page.evaluate("() => window.__t.state().printed") and page.locator("#est_tiles").count() == 0
