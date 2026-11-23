"""Start the app on a free port and wait until it answers: the one copy, used by the UI tests (tests/ui/conftest.py)
and by the landing-page recorder (scripts/media/record.py)."""
import contextlib
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as s:                       # a free port, so a running dev server is not in the way
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


@contextlib.contextmanager
def serve_app(env=None):
    """The app's own uvicorn, for as long as the with block lasts, with `env` added to its environment (a setting
    such as LAMINA_LIBRARY). Yields its base URL."""
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "web.app:app", "--port", str(port)], cwd=ROOT,
                            env={**os.environ, **(env or {})}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        wait(url + "/api/modes", "the server")
        yield url
    finally:
        proc.terminate(); proc.wait(timeout=20)
