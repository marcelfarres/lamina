"""The browser build (web/browser.py) answers the page's requests by calling the same endpoint functions the server
runs — so slicing, the ghost model, the cut files and the guards all work without a server."""
import io
import json
import os
import pathlib
import subprocess
import sys
import zipfile

import pytest

from web import app as webapp, browser

MINE = "0" * 32
PARAMS = '{"distribution":"count","count":3,"autofix":"off"}'


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS", tmp_path)
    return tmp_path


def test_slice_ghost_and_cut_files_without_a_server(jobs):
    status, _, body = browser.handle("GET", "api/modes", "", None)
    assert status == 200 and json.loads(body)[0]["name"]
    status, _, body = browser.handle("POST", "api/slice", "", [["client", MINE], ["mode", "stacked"], ["params", PARAMS], ["example", "cube"]])
    assert status == 200
    job = json.loads(body)["job"]
    status, _, body = browser.handle("GET", f"jobs/{MINE}/{job}/model.stl", "", None)
    assert status == 200 and len(body) > 84                       # the ghost mesh the 3D view loads
    status, headers, body = browser.handle("GET", f"api/job/{MINE}/{job}/export", "fmt=svg&labels=1", None)
    assert status == 200 and headers["content-disposition"].endswith('.zip"')
    assert any(n.endswith(".svg") for n in zipfile.ZipFile(io.BytesIO(body)).namelist())
    assert browser.handle("DELETE", "api/session", f"client={MINE}", None)[0] == 200 and not (jobs / MINE).exists()


def test_an_upload_arrives_as_bytes(jobs):
    data = (pathlib.Path(__file__).parent.parent / "examples" / "cube.stl").read_bytes()
    status, _, body = browser.handle("POST", "api/slice", "", [["client", MINE], ["mode", "stacked"], ["params", PARAMS], ["model", "cube.stl", data]])
    assert status == 200 and json.loads(body)["plan"]["counts"]["parts"] == 3


def test_solids_extrude_without_a_triangulation_engine(jobs, monkeypatch):
    """The browser has no earcut / triangle: the caps come from shapely's constrained Delaunay instead, same solid."""
    import trimesh
    from core import solid
    from shapely.geometry import Polygon
    ring = Polygon([(0, 0), (40, 0), (40, 30), (0, 30)], holes=[[(10, 10), (20, 10), (20, 20), (10, 20)]])
    native = solid.extrude(ring, 3)
    monkeypatch.setattr(trimesh.creation, "extrude_polygon", lambda *a, **k: (_ for _ in ()).throw(ValueError("No available triangulation engine!")))
    fallback = solid.extrude(ring, 3)
    assert fallback.is_watertight and abs(fallback.volume - native.volume) < 1e-6 and abs(fallback.volume - ring.area * 3) < 1e-6


def test_every_feature_works_without_the_compiled_extras(tmp_path):
    """What Pyodide cannot ship — rtree, fast-simplification, manifold3d, earcut — must not take a feature with it.
    A fresh interpreter (tests/browser_env.py) blocks those modules before trimesh loads and runs the whole matrix."""
    root = pathlib.Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "tests" / "browser_env.py"), str(tmp_path)], capture_output=True, text=True,
                       cwd=root, env={**os.environ, "PYTHONPATH": str(root)}, timeout=900)
    assert r.returncode == 0 and r.stdout.rstrip().endswith("ok"), r.stdout[-1500:] + r.stderr[-2500:]


def test_the_guards_still_answer(jobs):
    assert browser.handle("GET", "api/job/short/x/export", "", None)[0] == 400          # bad client id
    assert browser.handle("GET", f"jobs/{MINE}/../../etc/passwd", "", None)[0] == 404     # cannot leave jobs/
    assert browser.handle("GET", "api/nothing", "", None)[0] == 404
