"""Take the library's preview picture of every bundled example, as the page itself takes a project's: open the example,
wait for its slice, and write __t.snapshot() to web/static/examples/<name>.webp.

    uv run python scripts/example_previews.py

Run it again after an example or its preset changes (tests/test_presets.py checks that every example has one). Needs
`playwright install chromium` once. Exits non-zero when a picture came out empty or not WebP, and writes no file then.
"""
import base64
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "static" / "examples"
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests" / "ui")]     # run as a script, only scripts/ is on the path
from helpers import settle  # noqa: E402
from serve import serve_app  # noqa: E402

PREFIX = "data:image/webp;base64,"


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(exist_ok=True)
    bad = []
    with serve_app() as url, sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(url + "/")
        page.wait_for_function("() => window.__t?.openExample", timeout=180_000)   # set only once init() passed its awaits
        settle(page)
        for name in sorted(f.stem for f in (ROOT / "examples").glob("*.stl")):
            page.evaluate("n => __t.openExample(n)", name)
            settle(page)
            data = page.evaluate("() => __t.snapshot()")
            if not data.startswith(PREFIX):
                bad.append(f"{name}: {data[:30] or 'empty'}")
                continue
            (OUT / f"{name}.webp").write_bytes(base64.b64decode(data[len(PREFIX):]))
            print(name)
        browser.close()
    if bad:
        sys.exit("no WebP picture for " + ", ".join(bad))


if __name__ == "__main__":
    main()
