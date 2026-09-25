"""Record the landing page's stills and clips from the running app, and encode them into docs/media.

    uv run --with playwright python scripts/media/record.py            every scene
    uv run --with playwright python scripts/media/record.py axes lobes only these

Starts the app on a free port and Playwright's Chromium with remote debugging, runs capture.mjs against it (the
scenes: which example, which parameters, which clip), then make_media.py (crop, scale, h264). The same on Windows,
macOS and the Linux runner of .github/workflows/media.yml. Needs node (capture.mjs) and ffmpeg on the PATH, and
`playwright install chromium` once.

Exits non-zero when a scene failed or ended on errors, so a release never ships a clip of a broken plan.
"""
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait(url, what, tries=120):
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=2)  # noqa: S310 — our own server / browser, just started
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{what} never came up at {url}")


def main(scenes):
    from playwright.sync_api import sync_playwright
    port, cdp = free_port(), free_port()
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "web.app:app", "--port", str(port)], cwd=ROOT,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait(f"http://127.0.0.1:{port}/api/examples", "the server")
        with sync_playwright() as p:
            # software GL: the runner has no GPU, and the frames must look the same on any machine
            browser = p.chromium.launch(args=[f"--remote-debugging-port={cdp}", "--use-angle=swiftshader",
                                              "--enable-unsafe-swiftshader", "--hide-scrollbars"])
            page = browser.new_page(viewport={"width": 1574, "height": 907})
            page.goto(f"http://127.0.0.1:{port}/#interlocked")
            wait(f"http://127.0.0.1:{cdp}/json", "the browser")
            run = subprocess.run(["node", str(HERE / "capture.mjs"), *scenes], cwd=ROOT, text=True,
                                 capture_output=True, env={**os.environ, "CDP_PORT": str(cdp)})
            print(run.stdout, run.stderr, sep="")
            browser.close()
    finally:
        server.terminate(); server.wait(timeout=20)
    # a clip of a plan with errors, or a scene that threw, is not something to publish. The checks still is the one
    # shot that is meant to show errors (its fix buttons are the point of it)
    bad = [ln for ln in run.stdout.splitlines()
           if "failed:" in ln or (re.search(r"parts E[1-9]", ln) and not ln.startswith("shot checks"))]
    if run.returncode or bad:
        sys.exit("recording failed:\n" + "\n".join(bad or [f"capture.mjs exited {run.returncode}"]))
    subprocess.run([sys.executable, str(HERE / "make_media.py")], cwd=ROOT, check=True)


if __name__ == "__main__":
    main(sys.argv[1:])
