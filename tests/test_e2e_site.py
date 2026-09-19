"""The published site, end to end in a real browser: Pyodide loads, every technique slices, an upload slices, a cut
file downloads, no uncaught error. This is what gates the deploy in .github/workflows/pages.yml. Locally:

    python deploy/build_site.py
    uv run --with playwright playwright install chromium
    LAMINA_E2E=1 uv run --with playwright pytest tests/test_e2e_site.py -q
"""
import functools
import http.server
import json
import os
import pathlib
import re
import threading
import urllib.parse

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The issue form prefills a dropdown by matching an option's text, so a technique the app names has to be one of
# them — read off the template itself, since a rename on either side is exactly what would break the prefill.
TEMPLATE_TECHNIQUES = re.findall(r"^ +- (\S.*)$", (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml")
                                 .read_text(encoding="utf-8").split("options:")[1].split("validations:")[0], re.M)
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

        # A bug report carries the data model, and its tick box is the only promise the dialog makes about the
        # model itself: ticked, the project file holds the uploaded mesh; unticked, not a byte of it travels.
        page.click("header [data-feedback]")
        said = "part X-3 has a slot cut through the outline"
        page.fill("#fb_what", said)
        carried = lambda: page.evaluate("""async () => {
            const p = (await window.__feedback.build()).get('project');
            return [p.size, JSON.parse(await p.text()).model?.name || ''];
        }""")
        ticked = carried()
        page.uncheck("#fb_tick")
        plain = carried()
        assert ticked[1] == "pear.stl", ticked                     # the mesh that was uploaded, by name
        assert plain[1] == "", plain
        assert ticked[0] > 2 * plain[0], (ticked, plain)           # and it is the mesh that makes up the size

        # both ways out, built from that same report: a prefilled email and a prefilled issue form
        page.check("#fb_tick")
        routes = page.evaluate("""async () => {
            const fd = await window.__feedback.build(), file = fd.get('project');
            return [window.__feedback.mailto(fd, file), window.__feedback.issueUrl(fd, file)];
        }""")
        mail, issue = (urllib.parse.urlsplit(u) for u in routes)
        mq, iq = (urllib.parse.parse_qs(u.query) for u in (mail, issue))
        assert mail.path == "lamina.3d.app@gmail.com", mail.path
        assert said in mq["body"][0] and said in iq["what"][0]                 # what the reporter typed, both ways
        assert "pear.stl_v1.0.lamina.json" in mq["body"][0], mq["body"][0]     # and which file to attach
        assert mq["body"][0].startswith(said) and "parts" in mq["body"][0]     # with the checks under it
        assert len(routes[0]) < 2000, len(routes[0])                           # mail clients cut long ones
        assert iq["template"] == ["bug_report.yml"]
        assert iq["technique"][0] in TEMPLATE_TECHNIQUES, iq["technique"]      # must match an option of the dropdown
        assert iq["report"][0].startswith("technique"), iq["report"][0][:80]
        assert len(routes[1]) < 8000, len(routes[1])                           # GitHub refuses more
        # pressing it saves the file to attach and leaves the dialog saying so
        with page.expect_download() as report_dl:
            page.click("#fb_gh")
        assert report_dl.value.suggested_filename.endswith(".lamina.json")
        assert "attach" in page.text_content("#fb_note")

        # The same dialog shares one machine or one material: no model, that one thing as JSON, into its own template.
        page.click("#fb_no")
        page.click('nav button[data-t="sheet"]')

        def shared(kind, said):
            page.click(f'[data-feedback="{kind}"]')
            assert page.is_hidden("#fb_att")
            page.fill("#fb_what", said)
            routes = page.evaluate("""async () => {
                const fd = await window.__feedback.build();
                return [window.__feedback.mailto(fd, null), window.__feedback.issueUrl(fd, null), fd.has('project')];
            }""")
            assert routes[2] is False
            mq, iq = (urllib.parse.parse_qs(urllib.parse.urlsplit(u).query) for u in routes[:2])
            assert iq["template"] == ["preset.yml"] and iq["kind"] == [kind.capitalize()] and "repro" not in iq
            assert mq["subject"][0].startswith(f"Lamina {kind}") and said in mq["body"][0]
            page.click("#fb_no")
            return json.loads(iq["settings"][0])

        # a machine of your own: the numbers as they stand, kept under the name typed, shared under it, deleted again
        page.fill("#p_slot_offset", "0.123")
        page.once("dialog", lambda d: d.accept("my K40"))
        page.click("#kadd")
        assert page.eval_on_selector("#machine", "s => s.value") == "my K40"
        m = shared("machine", "K40 with the stock lens")
        assert m["name"] == "my K40" and abs(m["slot_offset"] - 0.123) < 1e-9 and {"kerf", "relief", "tool_d", "bed"} <= set(m), m
        assert "material" not in m
        page.click("#kdel")
        assert "my K40" not in page.eval_on_selector_all("#machine option", "os => os.map(o => o.value)")
        mat = shared("material", "3 mm birch from the yard")
        assert mat["material"] == page.evaluate("window.__t.state().material") and {"thickness", "sheet", "thicknesses", "sheets"} <= set(mat), mat
        assert "kerf" not in mat

        # A project file is somebody else's text once a bug report is opened: markup in it must land as text, not run.
        bad = '<img src=x onerror="window.__pwned=1">'
        proj = json.dumps({"version": 3, "mode": "interlocked", "state": {"skip": [bad], "project": '"' + bad, "thick": {bad: 3}}, "example": "egg"})
        page.set_input_files("#pfile", {"name": "evil.lamina.json", "mimeType": "application/json", "buffer": proj.encode()})
        sliced("crafted project")
        assert page.evaluate("window.__pwned") is None
        assert page.evaluate("document.querySelectorAll('aside img').length") == 0
        assert page.text_content("#g-slices .chip").startswith(bad)                   # shown as it was written
        assert page.input_value("#pname") == '"' + bad
        assert not errors, errors
