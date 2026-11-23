"""Record the landing page's stills and clips from the running app, and encode them into docs/media.

    uv run python scripts/media/record.py            every scene
    uv run python scripts/media/record.py axes lobes only these

Starts the app on a free port and Playwright's Chromium with remote debugging, runs capture.mjs against it (the
scenes: which example, which parameters, which clip), then make_media.py (crop, scale, h264). The same on Windows,
macOS and the Linux runner of .github/workflows/media.yml. Needs node (capture.mjs) and ffmpeg on the PATH, and
`playwright install chromium` once.

Exits non-zero when a scene failed or ended on errors, so a release never ships a clip of a broken plan.
"""
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests"))     # run as a script, only scripts/media is on the path
from serve import free_port, serve_app, wait  # noqa: E402


def main(scenes):
    from playwright.sync_api import sync_playwright
    cdp = free_port()
    with serve_app() as url, sync_playwright() as p:
        # software GL: the runner has no GPU, and the frames must look the same on any machine
        browser = p.chromium.launch(args=[f"--remote-debugging-port={cdp}", "--use-angle=swiftshader",
                                          "--enable-unsafe-swiftshader", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1574, "height": 907})
        page.goto(f"{url}/#interlocked")
        wait(f"http://127.0.0.1:{cdp}/json", "the browser")
        # every line as it comes, with the minutes since the start: a scene that hangs, or a scene set that outgrows
        # the workflow's timeout, shows where it got to (070: 59 minutes with no output, then the run was cancelled)
        t0 = time.monotonic()
        node = subprocess.Popen(["node", str(HERE / "capture.mjs"), *scenes], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, env={**os.environ, "CDP_PORT": str(cdp)})
        lines = []
        for ln in node.stdout:
            lines.append(ln.rstrip("\n"))
            print(f"{(time.monotonic() - t0) / 60:5.1f} min  {ln}", end="", flush=True)
        node.wait()
        browser.close()
    # a clip of a plan with errors, or a scene that threw, is not something to publish. The checks still is the one
    # shot that is meant to show errors (its fix buttons are the point of it)
    bad = [ln for ln in lines
           if "failed:" in ln or (re.search(r"parts E[1-9]", ln) and not ln.startswith("shot checks"))]
    if node.returncode or bad:
        sys.exit("recording failed:\n" + "\n".join(bad or [f"capture.mjs exited {node.returncode}"]))
    subprocess.run([sys.executable, str(HERE / "make_media.py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main(sys.argv[1:])
