"""Several people on one server never meet: everything a client slices lives under its own id, and neither another
id nor a crafted one reaches it."""
import io
import os
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from web import app as webapp

MINE, YOURS = "0" * 32, "f" * 32
CUBE = {"mode": "stacked", "example": "cube", "params": '{"distribution":"count","count":3,"autofix":"off"}'}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "JOBS", tmp_path)      # jobs go to the test's own directory, not the repo's
    return TestClient(webapp.app)


def test_a_client_cannot_reach_another_ones_job(api):
    job = api.post("/api/slice", data={"client": MINE, **CUBE}).json()["job"]
    assert api.get(f"/api/job/{MINE}/{job}/export").status_code == 200
    assert api.get(f"/api/job/{YOURS}/{job}/export").status_code == 404     # same job id, another client: nothing
    assert api.get(f"/api/job/{YOURS}/{job}/stl").status_code == 404
    assert api.get(f"/api/job/{YOURS}/{job}/source").status_code == 404


def test_the_session_belongs_to_the_client(api):
    job = api.post("/api/slice", data={"client": MINE, **CUBE}).json()["job"]
    assert api.get("/api/session", params={"client": MINE}).json()["job"] == job
    assert api.get("/api/session", params={"client": YOURS}).json() == {}   # a second tab starts empty


@pytest.mark.parametrize("bad", ["", "short", "../../working-files", "0" * 65])
def test_an_id_that_is_not_a_plain_name_is_refused(api, bad):
    assert api.get("/api/session", params={"client": bad}).status_code == 400
    assert api.post("/api/slice", data={"client": bad, **CUBE}).status_code in (400, 422)   # bad id, or none at all


def test_an_idle_client_is_swept_and_nothing_else_is(api, tmp_path):
    api.post("/api/slice", data={"client": YOURS, **CUBE})
    old = time.time() - webapp.TTL - 60
    stranger = tmp_path / "6d7677097e99"; stranger.mkdir(); (stranger / "keep.stl").write_text("not ours")
    for d in (tmp_path / YOURS, stranger):
        os.utime(d, (old, old))
    api.post("/api/slice", data={"client": MINE, **CUBE})              # any slice sweeps what has timed out
    assert not (tmp_path / YOURS).exists() and (tmp_path / MINE).exists()
    assert (stranger / "keep.stl").exists()                            # a directory that is not a client id is left alone


def test_a_client_that_comes_back_after_its_timeout_starts_over(api, tmp_path):
    """Its own directory is swept by the same request that needs it: slicing has to work, not crash."""
    api.post("/api/slice", data={"client": MINE, **CUBE})
    old = time.time() - webapp.TTL - 60
    os.utime(tmp_path / MINE, (old, old))
    assert api.post("/api/slice", data={"client": MINE, **CUBE}).status_code == 200


def test_clear_my_data_deletes_that_client_and_nobody_else(api, tmp_path):
    api.post("/api/slice", data={"client": MINE, **CUBE}); api.post("/api/slice", data={"client": YOURS, **CUBE})
    assert api.delete("/api/session", params={"client": MINE}).status_code == 200
    assert not (tmp_path / MINE).exists() and (tmp_path / YOURS).exists()
    assert api.get("/api/session", params={"client": MINE}).json() == {}


def test_ttl_zero_never_sweeps(api, tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "TTL", 0)
    api.post("/api/slice", data={"client": YOURS, **CUBE})
    os.utime(tmp_path / YOURS, (0, 0))
    api.post("/api/slice", data={"client": MINE, **CUBE})
    assert (tmp_path / YOURS).exists()


def test_a_model_over_the_upload_limit_is_refused(api, monkeypatch):
    monkeypatch.setattr(webapp, "MAX_UPLOAD", 100)
    files = {"model": ("big.stl", b"x" * 101)}
    assert api.post("/api/slice", data={"client": MINE, "mode": "stacked"}, files=files).status_code == 413
    assert not list(webapp.JOBS.glob("*/*/upload.*"))                 # refused before anything reaches the disk


def test_the_solid_downloads_of_a_job(api):
    """STL of the assembly, and the prototype set: at a scale where the parts still print thick enough the zip is
    the plate and the parts; at a scale where they would not, the job is planned again and the zip says so."""
    job = api.post("/api/slice", data={"client": MINE, **CUBE}).json()["job"]
    stl = api.get(f"/api/job/{MINE}/{job}/stl")
    assert stl.status_code == 200 and len(stl.content) > 84                       # binary STL: header + triangles
    names = lambda r: zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    same = names(api.get(f"/api/job/{MINE}/{job}/proto", params={"scale": 1}))
    assert "plate.3mf" in same and "README.txt" not in same
    thin = names(api.get(f"/api/job/{MINE}/{job}/proto", params={"scale": 0.1, "min_thick": 1.2}))
    assert "plate.3mf" in thin and "README.txt" in thin


def test_every_zip_carries_the_project_file_that_reopens_the_job(api):
    """A cut file or a printed part found later has to lead back to the model that made it: the zips carry the same
    project file the UI's "open project" reads (technique, every parameter, and an uploaded model itself)."""
    import json
    job = api.post("/api/slice", data={"client": MINE, **CUBE}).json()["job"]
    for url in (f"/api/job/{MINE}/{job}/export", f"/api/job/{MINE}/{job}/proto?scale=1"):
        z = zipfile.ZipFile(io.BytesIO(api.get(url).content))
        name = next(n for n in z.namelist() if n.endswith(".lamina.json"))
        proj = json.loads(z.read(name))
        assert proj["mode"] == "stacked" and proj["example"] == "cube" and proj["state"]["count"] == 3
        assert "model" not in proj                                       # a bundled example is named, not embedded


def test_a_job_id_cannot_climb_out_of_its_client(api):
    assert api.get(f"/api/job/{MINE}/ex_.././ex_cube/export").status_code in (400, 404)
    assert api.post("/api/slice", data={"client": MINE, "mode": "stacked", "example": "../cube"}).status_code == 400
