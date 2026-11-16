"""The project library: the loaded example is the page's own state, so a page without the dropdown can open one."""
from .helpers import example


def test_open_example_is_page_state(page):
    example(page, "horse_statue")
    assert page.evaluate("__t.project().then(p => p.example)") == "horse_statue"
    assert page.evaluate("__t.job()").startswith("ex_")
    page.evaluate("document.querySelector('#example').value = 'egg'")       # the box is no longer the truth
    assert page.evaluate("__t.project().then(p => p.example)") == "horse_statue"
