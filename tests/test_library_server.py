"""The library kept by the server (LAMINA_LIBRARY): off unless set; set, a flat folder of project files that every
browser reads and writes through api/library, with no name that leads out of it and no write that leaves half a file."""
import os
import subprocess
import sys
import time
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
    assert api.get("/api/library", headers={"host": "evil.example"}).status_code == 404   # off, whatever the name
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
    assert api.get(URL).text == '{"a":1}'                                 # the file as it is, streamed
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


def test_a_conditional_write_lands_only_on_what_the_page_compared(api, lib):
    """expect=absent: the file must not be there; size and mtime: it must still be exactly that. Checked under the
    lock as the file is swapped in; else 412, and the file and the folder stay as they were."""
    assert api.put(URL, content="one", params={"expect": "absent"}).status_code == 200
    r = api.put(URL, content="two", params={"expect": "absent"})            # another browser saved it first
    assert r.status_code == 412 and r.json()["detail"] == f"{FILE} changed in projects since the page listed it."
    (w,) = api.get("/api/library").json()["files"]
    for stale in ({"size": w["size"] + 1, "mtime": w["mtime"]}, {"size": w["size"], "mtime": w["mtime"] - 1}):
        assert api.put(URL, content="two", params=stale).status_code == 412
    assert (lib / FILE).read_text() == "one" and projects(lib) == [FILE]  # no side file left behind
    assert api.put(URL, content="two", params={"size": w["size"], "mtime": w["mtime"]}).status_code == 200
    assert (lib / FILE).read_text() == "two"
    assert api.put("/api/library/new_v1.0.lamina.json", content="x", params=w).status_code == 412   # gone is not "this"
    assert api.put(URL, content="three").status_code == 200              # no condition: as before


def test_a_folder_in_the_files_place_is_no_endless_question(api, lib):
    """The listing shows no folder, so the page expects the name free: the write then fails (503), not 412, or the
    page would list, expect free and be told "changed" for ever."""
    (lib / FILE).mkdir()
    assert api.put(URL, content="{}", params={"expect": "absent"}).status_code == 503


OWN = ["127.0.0.1", "127.0.0.1:8000", "192.168.1.20:8000", "[::1]", "[::1]:8000", "[fe80::1]:8000", "localhost",
       "localhost:8000", "nas", "NAS:8000", "nas.local", "nas.local:8000", "box.lan", "box.home.arpa:8000",
       "lamina.example.org", "lamina.example.org:443"]
STRANGE = ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "localhost.evil.example",
           "nas.local.evil.example", "lamina.example.org.evil", "::1", "[::1", "a b", "nas:80:80", "x.lamina"]


@pytest.mark.parametrize("host", OWN)
def test_the_library_answers_on_its_own_addresses(api, lib, monkeypatch, host):
    monkeypatch.setattr(webapp, "HOSTS", {"lamina.example.org"})              # LAMINA_HOSTS=lamina.example.org
    assert api.get("/api/library", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", STRANGE)
def test_a_page_on_another_name_cannot_reach_the_library(api, lib, monkeypatch, host):
    """DNS rebinding: a page on evil.example points its name at this server, and the browser sends Host: evil.example."""
    monkeypatch.setattr(webapp, "HOSTS", {"lamina.example.org"})
    (lib / FILE).write_text("{}")
    h = {"host": host}
    for r in (api.get("/api/library", headers=h), api.get(URL, headers=h), api.put(URL, content="x", headers=h),
              api.delete(URL, headers=h)):
        assert r.status_code == 403 and "LAMINA_HOSTS" in r.json()["detail"], r.text
    assert (lib / FILE).read_text() == "{}"
    assert api.get("/api/project", headers=h).status_code == 200            # the rest of the app is not the library's


def test_lamina_hosts_is_read_from_the_setting():
    r = subprocess.run([sys.executable, "-c", "import web.app as a; print(sorted(a.HOSTS))"], cwd=webapp.HERE.parent,
                       capture_output=True, text=True, env={**os.environ, "LAMINA_HOSTS": " Lamina.Example.org, b.example ,"},
                       timeout=120)
    assert r.stdout.strip() == "['b.example', 'lamina.example.org']", r.stderr


def test_only_the_library_is_left_to_its_own_cap(api, monkeypatch):
    monkeypatch.setattr(webapp, "MAX_UPLOAD", 3)
    assert api.post("/jobs/api/library/x", content=b"x" * 1_000_010).status_code == 413


def test_side_files_a_dead_write_left_are_swept_at_start(lib):
    """A write or the write probe killed half way leaves its dot-file: the server removes those an hour old as it starts."""
    old = time.time() - 7200
    for n in (".a1b2.tmp", ".c3d4.probe", FILE, ".own-notes"):
        (lib / n).write_text("x")
        os.utime(lib / n, (old, old))
    (lib / ".e5f6.tmp").write_text("x")                                    # a write under way: fresh
    r = subprocess.run([sys.executable, "-c", "import web.app"], cwd=webapp.HERE.parent, capture_output=True, text=True,
                       env={**os.environ, "LAMINA_LIBRARY": str(lib)}, timeout=120)
    assert r.returncode == 0, r.stderr
    assert projects(lib) == [".e5f6.tmp", ".own-notes", FILE]


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
       "sub/../x.lamina.json",
       "!" * 20_000]                                                          # a long crafted name: refused at once, nothing backtracks


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
    (lib / FILE).write_text("{}")
    (lib / "twin.lamina.json").symlink_to(lib / FILE)                     # a link inside to inside is no project file either
    assert api.put("/api/library/twin.lamina.json", content="x").status_code == 400 and (lib / FILE).read_text() == "{}"


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


def test_the_page_is_told_the_reason_never_a_path(api, lib, monkeypatch):
    """An OS error is told in the system's own words; one without them (made with a message only) names its kind, never
    its text, which can be a path on the server."""
    def refused(*a, **k):
        raise OSError(str(lib / ".x.probe"))
    monkeypatch.setattr(webapp.tempfile, "mkstemp", refused)
    problem = api.get("/api/project").json()["library"]["problem"]
    assert problem.startswith("The server cannot write to its library folder projects (OSError).") and str(lib) not in problem
    r = api.put(URL, content="{}")
    assert r.status_code == 503 and r.json()["detail"] == problem


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
