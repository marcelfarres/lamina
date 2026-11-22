"""The app in a real browser against a real server: the workflows people actually run, and every parameter of every
technique touched at least once, so a field that stops driving the slicer — or a button that throws — fails here
instead of in someone's inbox.

    uv run playwright install chromium
    LAMINA_UI=1 uv run pytest tests/ui -q
    LAMINA_UI=1 LAMINA_BROWSER=firefox uv run pytest tests/ui -q     # or chrome / msedge: the browser installed here

It drives the page the way a person does (real input events, the debounce, the real /api/slice), and fails on any
uncaught JavaScript error, on a status line that never settles, and on a parameter whose value does not reach the
plan the server built.

One server and one page serve the whole run (session scope, however many files the tests sit in).
"""
import os
import pathlib

import pytest

from serve import serve_app
from .helpers import settle

HERE = pathlib.Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    """Keeps these tests out of a plain `pytest tests` run: they need playwright's chromium and take a long time."""
    if os.environ.get("LAMINA_UI"):
        return
    skip = pytest.mark.skip(reason="set LAMINA_UI=1 (needs playwright's chromium)")
    for item in items:
        if HERE in item.path.parents:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def server():
    with serve_app() as url:
        yield url


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        name = os.environ.get("LAMINA_BROWSER", "chromium")    # playwright's own, unless a test run asks for another
        b = p.firefox.launch() if name == "firefox" else p.chromium.launch(channel=None if name == "chromium" else name)
        yield b
        b.close()


def new_page(browser, url):
    """The app at `url` in a tab of its own (with its own storage), settled; an uncaught JavaScript error fails the test."""
    pg = browser.new_page(viewport={"width": 1500, "height": 950})
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(url + "/")
    settle(pg)
    return pg


@pytest.fixture(scope="session")
def page(server, browser):
    return new_page(browser, server)


@pytest.fixture(autouse=True)
def fresh(page):
    """Every test starts from the defaults of every tab. One page for the whole run is what makes this suite fast,
    and this is the price: a technique or a remeshed model left behind would slow down or break the next test.
    The model too: the egg, unless the test before left another one (an upload of the cube made the next test's
    shift-drag miss), and not the page's default, which can change and be slower to re-slice. The Light tab's reset
    first: a test that left the light on lit the next test's re-slices (bugs/069: the paper pane's, then a stack half a
    metre tall drawn with shadows hung the page). An example that opens turns it off by itself (bugs/071)."""
    if page.evaluate("() => window.__t.job()") != "ex_egg":
        page.click('nav button[data-t="model"]')
        page.evaluate("__t.openExample('egg')")
    for tab in ("light", "model", "technique", "sheet", "checks"):
        page.click(f'nav button[data-t="{tab}"]')
        page.click(f'button.reset[data-reset="{tab}"]')
        page.wait_for_timeout(200)
    settle(page)
    yield
