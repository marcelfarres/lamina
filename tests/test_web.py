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
def api(jobs):
    return TestClient(webapp.app)


def test_a_client_cannot_reach_another_ones_job(api):
    job = api.post("/api/slice", data={"client": MINE, **CUBE}).json()["job"]
    assert api.get(f"/api/job/{MINE}/{job}/export").status_code == 200
    assert api.get(f"/api/job/{YOURS}/{job}/export").status_code == 404     # same job id, another client: nothing
    assert api.get(f"/api/job/{YOURS}/{job}/stl").status_code == 404
    assert api.get(f"/api/job/{YOURS}/{job}/source").status_code == 404


def test_a_newer_slice_stops_the_older_one_of_the_same_client(api):
    """The page keeps only its newest answer, so the server must not keep computing the others: they ran side by side
    under the GIL and made every slice of a busy page several times slower."""
    import threading
    got = {}
    slow = threading.Thread(target=lambda: got.update(old=api.post("/api/slice", data={"client": MINE, "mode": "stacked", "example": "wavy_torus"})))
    slow.start()
    for _ in range(600):                                                   # until the old one is really building
        if api.get("/api/progress", params={"client": MINE}).json():
            break
        time.sleep(0.05)
    assert api.post("/api/slice", data={"client": MINE, **CUBE}).status_code == 200
    slow.join()
    assert got["old"].status_code == 409, got["old"].text                 # stopped, not finished
    assert api.get("/api/session", params={"client": MINE}).json()["example"] == "cube"   # the newest is what resumes


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
    step = api.get(f"/api/job/{MINE}/{job}/step")                                 # the same as solids, for CAD
    assert step.status_code == 200 and step.content.startswith(b"ISO-10303-21;") and ".step" in step.headers["content-disposition"]
    assert api.get(f"/api/job/{MINE}/{job}/step", params={"part": "no such"}).status_code == 404
    one = api.get(f"/api/job/{MINE}/{job}/step", params={"body": 1})                # the whole model fused: one solid
    assert one.status_code == 200 and "onebody.step" in one.headers["content-disposition"] and one.content.count(b"MANIFOLD_SOLID_BREP(") == 1
    names = lambda r: zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    readme = lambda r: zipfile.ZipFile(io.BytesIO(r.content)).read("README.txt").decode().splitlines()
    same = api.get(f"/api/job/{MINE}/{job}/proto", params={"scale": 1, "offset": 0})
    # the job as it is, not planned again. Its README says one thing (bugs/068): the top layer prints clean (hidden
    # marks), so it carries its number on a tag beside it (bugs/061); then the print settings written into the plate
    note, *settings = readme(same)
    assert "plate.3mf carries the print settings" in settings[0]
    assert "plate.3mf" in names(same) and note.startswith("1 part(s) have no room") and "Z-3" in note
    thin = api.get(f"/api/job/{MINE}/{job}/proto", params={"scale": 0.1, "min_thick": 1.2})
    assert "plate.3mf" in names(thin) and readme(thin)[0].startswith("re-planned at")
    fit = names(api.get(f"/api/job/{MINE}/{job}/fit", params={"scale": 1, "offset": 0.2, "step": 0.05}))
    assert "plate.3mf" in fit and "README.txt" in fit and "fit_0.25.stl" in fit and "fit_0.10.stl" in fit
    cut = names(api.get(f"/api/job/{MINE}/{job}/fitcut", params={"fmt": "svg", "step": 0.1}))
    assert "README.txt" in cut and {n.split("/")[0] for n in cut if "/" in n} == {"fit_-0.20", "fit_-0.10", "fit_0.00", "fit_0.10", "fit_0.20"}


def test_every_zip_carries_the_project_file_that_reopens_the_job(api):
    """A cut file or a printed part found later has to lead back to the model that made it: the zips carry the same
    project file the library's import reads (technique, every parameter, and an uploaded model itself)."""
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


def test_an_export_zip_carries_the_project_file_the_page_saves(api):
    """The zip's project file says the layout version the page writes and reads, and the bug-report form offers every
    technique under the title the page sends (the page takes it from the schema)."""
    import json
    import pathlib
    import re
    job = api.post("/api/slice", data={"client": MINE, **CUBE}).json()["job"]
    z = zipfile.ZipFile(io.BytesIO(api.get(f"/api/job/{MINE}/{job}/export").content))
    proj = json.loads(z.read(next(n for n in z.namelist() if n.endswith(".lamina.json"))))
    assert proj["version"] == api.get("/api/project").json()["version"] == webapp.PROJECT_VERSION
    form = pathlib.Path(__file__).parent.parent / ".github/ISSUE_TEMPLATE/bug_report.yml"
    options = re.findall(r"^ +- (\S.*)$", form.read_text(encoding="utf-8").split("options:")[1].split("validations:")[0], re.M)
    assert sorted(options[:-1]) == sorted(m["title"] for m in api.get("/api/modes").json()) and options[-1].startswith("Not technique-specific")
