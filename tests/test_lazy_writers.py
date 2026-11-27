"""The browser build loads ezdxf and reportlab with the first cut-file export, not with Python (web/static/browser-worker.js),
so a slice must not import them. Checked in a fresh interpreter, through the call the browser makes: one slice."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CODE = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from web import browser
status, _, body = browser.handle("POST", "api/slice", "", [["client", "test_client_0123456789"], ["mode", "stacked"], ["example", "blob"]])
assert status == 200, (status, body[:300])
print("LOADED", [m for m in ("ezdxf", "reportlab") if m in sys.modules])
"""


def test_a_slice_imports_neither_ezdxf_nor_reportlab(tmp_path):
    r = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True, cwd=tmp_path, timeout=170)   # cwd: where jobs are kept
    assert r.returncode == 0, r.stderr[-800:]
    assert "LOADED []" in r.stdout, r.stdout
