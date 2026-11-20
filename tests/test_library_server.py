"""The library kept by the server (LAMINA_LIBRARY): off unless set; set, a flat folder of project files that every
browser reads and writes through api/library, with no name that leads out of it and no write that leaves half a file."""
import os
import subprocess
import sys
import urllib.parse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from web import app as webapp, browser

FILE = "lamp_v1.0.lamina.json"
URL = f"/api/library/{FILE}"


@pytest.fixture
def api():
    return TestClient(webapp.app)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """The library in the test's own folder `projects`; tmp_path itself is the "outside" nothing may reach."""
    d = tmp_path / "projects"
    d.mkdir()
    monkeypatch.setattr(webapp, "LIBRARY", d.resolve())
    return d


def projects(d):
    """What is in the folder, but the lock file the server keeps there."""
    return sorted(n for n in os.listdir(d) if n != ".lamina.lock")


def test_off_when_unset(api, monkeypatch):
    monkeypatch.setattr(webapp, "LIBRARY", None)
    assert api.get("/api/library").status_code == 404
    assert api.get(URL).status_code == 404
    assert api.put(URL, content="{}").status_code == 404
    assert api.delete(URL).status_code == 404
    assert api.get("/api/project").json() == {"version": webapp.PROJECT_VERSION}       # as before the setting existed


def test_the_static_site_answers_off():
    """The browser build never has the setting: api/library is not there, and api/project says nothing of it."""
    assert browser.handle("GET", "api/library", "", None)[0] == 404
    assert browser.handle("GET", f"api/library/{FILE}", "", None)[0] == 404
    status, _, body = browser.handle("GET", "api/project", "", None)
    assert status == 200 and b"library" not in body


def test_on_it_names_its_folder(api, lib):
    assert api.get("/api/project").json() == {"version": webapp.PROJECT_VERSION, "library": {"name": "projects", "problem": ""}}


def test_write_list_read_remove(api, lib):
    w = api.put(URL, content='{"a":1}').json()
    st = (lib / FILE).stat()
    assert w == {"size": 7, "mtime": st.st_mtime_ns // 1_000_000}
    (lib / "notes.json").write_text("{}")
    (lib / "sub.lamina.json").mkdir()                                     # a folder with the ending is no project file
    assert api.get("/api/library").json() == {"name": "projects", "problem": "", "files": [{"file": FILE, **w}]}
    assert api.get(URL).json() == {"text": '{"a":1}', **w}
    assert api.delete(URL).json() == {"removed": True}
    assert projects(lib) == ["notes.json", "sub.lamina.json"]
    assert api.get(URL).status_code == 404
    assert api.delete(URL).json() == {"removed": True}                    # gone already: gone


def test_a_write_replaces_the_whole_file(api, lib):
    api.put(URL, content="x" * 50)
    w = api.put(URL, content="short").json()
    assert (lib / FILE).read_text() == "short" and w["size"] == 5 and projects(lib) == [FILE]


def test_conditional_remove_only_while_unchanged(api, lib):
    w = api.put(URL, content='{"a":1}').json()
    assert api.delete(URL, params={"size": w["size"] + 1, "mtime": w["mtime"]}).json() == {"removed": False}
    assert api.delete(URL, params={"size": w["size"], "mtime": w["mtime"] - 1}).json() == {"removed": False}
    assert (lib / FILE).read_text() == '{"a":1}'                           # another save since: it stays
    assert api.delete(URL, params=w).json() == {"removed": True} and projects(lib) == []
    assert api.delete(URL, params=w).json() == {"removed": True}          # gone already counts as gone


def test_a_failed_write_leaves_the_old_file(api, lib, monkeypatch):
    api.put(URL, content="old")

    def full(*a):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(webapp.os, "replace", full)
    r = api.put(URL, content="new")
    assert r.status_code == 503 and r.json()["detail"] == f"{FILE} could not be written in projects (No space left on device)."
    assert (lib / FILE).read_text() == "old" and projects(lib) == [FILE]  # no side file left behind either


def test_a_write_that_stops_half_way_leaves_the_old_file(api, lib):
    api.put(URL, content="old")

    def body():
        yield b"new, half"
        raise OSError("the connection dropped")
    with pytest.raises((OSError, ExceptionGroup)):                          # through the middleware's task group, here
        api.put(URL, content=body())
    assert (lib / FILE).read_text() == "old" and projects(lib) == [FILE]


BAD = ["../x.lamina.json", "..\\x.lamina.json", "a/b.lamina.json", "a\\b.lamina.json", ".hidden.lamina.json",
       ".lamina.json", "x.json", "x.lamina.json.tmp", "/x.lamina.json", "C:\\x.lamina.json", "C:x.lamina.json",
       "x:y.lamina.json", "x\x00.lamina.json", "x\n.lamina.json", "a..b.lamina.json", "x.lamina.json/..",
       "sub/../x.lamina.json"]


@pytest.mark.parametrize("name", BAD)
def test_every_bad_name_is_refused(api, lib, tmp_path, name):
    with pytest.raises(HTTPException) as e:                               # the one gate every call goes through
        webapp.lib_path(name)
    assert e.value.status_code == 400 and "not the name of a project file" in e.value.detail
    url = "/api/library/" + urllib.parse.quote(name, safe="")
    for r in (api.put(url, content="{}"), api.get(url), api.delete(url), api.delete(url, params={"size": 2, "mtime": 0})):
        assert r.status_code in (400, 404), r.text                       # 404: the router itself takes no newline
    assert projects(lib) == [] and sorted(os.listdir(tmp_path)) == ["projects"]     # nothing written, inside or out


def test_an_absolute_path_is_refused(api, lib, tmp_path):
    out = tmp_path / "x.lamina.json"
    r = api.put("/api/library/" + urllib.parse.quote(str(out), safe=""), content="{}")
    assert r.status_code == 400 and not out.exists()


def test_a_link_out_of_the_folder_is_not_followed(api, lib, tmp_path):
    secret = tmp_path / "secret.lamina.json"
    secret.write_text("secret")
    try:
        (lib / "link.lamina.json").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("this user cannot make symbolic links here (Windows without developer mode)")
    assert api.get("/api/library").json()["files"] == []                  # not listed, so no size or date leaks out
    url = "/api/library/link.lamina.json"
    for r in (api.get(url), api.put(url, content="changed"), api.delete(url)):
        assert r.status_code == 400
    assert secret.read_text() == "secret" and (lib / "link.lamina.json").is_symlink()


def test_the_size_cap_follows_the_upload_cap(api, lib, monkeypatch):
    """A project carries its model as base64, 4/3 of the model, plus room for its settings and picture. The upload
    cap's own check (the middleware) would refuse that, so the library keeps its own, in plain words."""
    monkeypatch.setattr(webapp, "MAX_UPLOAD", 3)
    cap = webapp.library_cap()
    assert cap == 4 + 1_000_000
    r = api.put(URL, content=b"x" * (cap + 1))
    assert r.status_code == 413 and r.json()["detail"].startswith("This project is bigger than the")
    r = api.put(URL, content=iter([b"x" * cap, b"x"]))                    # no length announced: counted as it comes
    assert r.status_code == 413 and projects(lib) == []
    assert api.put(URL, content=b"x" * cap).status_code == 200 and (lib / FILE).stat().st_size == cap


def test_a_folder_the_server_cannot_write_says_so(api, lib, monkeypatch):
    def refused(*a, **k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(webapp.tempfile, "mkstemp", refused)
    problem = api.get("/api/project").json()["library"]["problem"]
    assert problem.startswith("The server cannot write to its library folder projects (Permission denied).")
    if hasattr(os, "getuid"):
        assert f"give the folder to user {os.getuid()}: sudo chown -R {os.getuid()} " in problem
    else:
        assert "may write to it" in problem
    r = api.put(URL, content="{}")
    assert r.status_code == 503 and r.json()["detail"] == problem and projects(lib) == []
    assert api.get("/api/library").json()["problem"] == problem           # listed still, with what is wrong


def test_a_read_only_folder_names_the_mount(api, lib, monkeypatch):
    def refused(*a, **k):
        raise OSError(30, "Read-only file system")
    monkeypatch.setattr(webapp.tempfile, "mkstemp", refused)
    problem = api.get("/api/project").json()["library"]["problem"]
    assert "(Read-only file system)" in problem and "read-only" in problem.split(").", 1)[1]


def test_the_log_says_it_at_start(tmp_path):
    """A folder that cannot be made (a file is in its way) is said on the server's own output as it starts."""
    (tmp_path / "file").write_text("")
    r = subprocess.run([sys.executable, "-c", "import web.app"], cwd=webapp.HERE.parent, capture_output=True, text=True,
                       env={**os.environ, "LAMINA_LIBRARY": str(tmp_path / "file" / "projects")}, timeout=120)
    assert r.returncode == 0 and "Lamina: The server cannot write to its library folder projects" in r.stderr
