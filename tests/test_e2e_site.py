"""The published site, end to end in a real browser: Pyodide loads, every technique slices, an upload slices, a cut
file downloads, no uncaught error. This is what gates the deploy in .github/workflows/pages.yml. Locally:

    python deploy/build_site.py
    uv run --with playwright playwright install chromium
    LAMINA_E2E=1 uv run --with playwright pytest tests/test_e2e_site.py -q
"""
import functools
import http.server
import os
import pathlib
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not os.environ.get("LAMINA_E2E"), reason="set LAMINA_E2E=1 (needs _site/ and playwright's chromium)")


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "_site"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.mark.timeout(1200)                                   # the Python runtime downloads and every technique slices in Pyodide: minutes, not the suite's 180 s
def test_the_site_slices_in_the_browser(site):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(site + "/app/")

        def sliced(what):                                    # the status line ends "ready · …" or "error: …"
            page.wait_for_timeout(700)                       # long enough for the click to have flipped it to "slicing…"
            page.wait_for_function("() => /^(ready|error)/.test(document.getElementById('status').textContent)", timeout=300_000)
            status = page.text_content("#status")
            assert status.startswith("ready"), (what, status)
            return status

        sliced("first load")                                 # the runtime download happens here
        assert page.locator("#example option").count() > 10
        # every example opens on its preset — the browser build must ship and load examples/presets.json too
        active = lambda: page.eval_on_selector("#modes button.on", "b => b.dataset.m")
        assert active() == "radial", ("the default example (egg) opens radial", active())
        page.select_option("#example", "bunny"); sliced("bunny")
        assert active() == "stacked", ("bunny opens stacked, standing up", active())
        page.click('nav button[data-t="technique"]')         # the buttons live in tabs: open each before clicking
        for mode in page.eval_on_selector_all("#modes button", "bs => bs.map(b => b.dataset.m)"):
            page.click(f'#modes button[data-m="{mode}"]')
            sliced(mode)
        page.click('nav button[data-t="model"]')
        page.set_input_files("#file", str(ROOT / "examples" / "pear.stl"))
        assert "parts" in sliced("upload")
        page.click('nav button[data-t="export"]')
        with page.expect_download() as dl:
            page.click("#dl a")
        assert dl.value.suggested_filename.endswith(".zip")
        assert not errors, errors
