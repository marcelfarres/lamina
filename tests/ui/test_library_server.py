"""The library kept by the server (LAMINA_LIBRARY): a server of its own with the setting, and a tab of its own on it.
The folder is the library, in every browser (LAMINA_BROWSER=firefox runs these in Firefox): what a save writes is a
file in it, a file put in it is a card, the projects already in the browser move in the way a link moves them, and a
folder the server cannot write is said on the folder line, with no save going anywhere else."""
import json

import pytest

from serve import serve_app
from .conftest import new_page
from .helpers import settle
from .test_library import card, lib, library, name, note, put, said, save, where, wipe


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    return tmp_path_factory.mktemp("server") / "projects"


@pytest.fixture(scope="module")
def server(folder):
    with serve_app({"LAMINA_LIBRARY": str(folder)}) as url:
        yield url


@pytest.fixture(scope="module")
def page(server, browser):
    pg = new_page(browser, server)
    yield pg
    pg.context.close()


@pytest.fixture(autouse=True)
def empty(page, folder):
    """An empty folder, an empty browser store, nothing saved in this tab, the app's own page in front."""
    for f in folder.glob("*.lamina.json"):
        f.unlink()
    wipe(page)
    page.evaluate("__t.lib.restoreStore()")
    yield
    page.evaluate("import('/static/js/librarypage.js').then(P => P.hideLibrary())")


def line(page):
    """The folder line's own words, without its buttons and its note."""
    return page.inner_text("#libwhere > span").strip()


def files(folder):
    return sorted(f.name for f in folder.glob("*.lamina.json"))


def browser_files(page):
    return [f["file"] for f in page.evaluate("import('/static/js/store.js').then(S => S.browserStore().list())")]


def project(n, rev="1.0", extra=""):
    return json.dumps({"name": n, "rev": rev, "mode": "stacked", "state": {"rev": rev}}) + extra


def test_the_server_folder_is_the_library(page, folder):
    assert page.evaluate("__t.lib.storeState()") == {"kind": "server", "label": "projects", "state": "server", "files": 0,
                                                     "left": "", "browser": 0}
    library(page)
    text, buttons = where(page)
    assert text.strip() == "📁 kept in the folder projects on the server · 0 files."
    assert buttons == [] and page.locator("#libwhere button").count() == 0    # no link, change, unlink or reconnect


def test_save_writes_a_file_in_the_folder(page, folder):
    name(page, "lamp")
    page.click("#psave2")
    assert said(page, "saved") == "saved lamp v1.0"
    assert files(folder) == ["lamp_v1.0.lamina.json"]
    p = json.loads((folder / "lamp_v1.0.lamina.json").read_text(encoding="utf-8"))
    st = page.evaluate("__t.state()")
    assert (p["name"], p["rev"], p["mode"], p["state"]["thickness"]) == ("lamp", "1.0", page.evaluate("__t.plan().mode"), st["thickness"])
    assert p["preview"].startswith("data:image/") and p["saved"].endswith("Z")
    assert browser_files(page) == []                                           # nothing in the browser
    assert save(page) == [{"file": "lamp_v1.0.lamina.json"}, []]               # its own revision: no question
    page.reload(); settle(page)
    assert lib(page) == [("lamp", ["1.0"])] and page.evaluate("__t.lib.unsaved()") is False


def test_a_file_put_in_the_folder_is_in_the_library(page, folder):
    (folder / "egg_v1.0.lamina.json").write_text(project("egg"), encoding="utf-8")
    (folder / "egg_v1.1.lamina.json").write_text(project("egg", "1.1"), encoding="utf-8")
    assert lib(page) == [("egg", ["1.1", "1.0"])]
    library(page)
    assert card(page, "egg").locator(".more").inner_text() == "2 revisions ▾"
    assert "· 2 files." in where(page)[0]


def test_a_file_changed_in_the_folder_asks_before_a_save(page, folder):
    name(page, "lamp"); save(page)
    f = folder / "lamp_v1.0.lamina.json"
    by_hand = f.read_text(encoding="utf-8") + " "
    f.write_text(by_hand, encoding="utf-8")
    assert save(page) == [None, [{"name": "lamp", "rev": "1.0", "next": "1.1"}]]
    assert f.read_text(encoding="utf-8") == by_hand


def test_delete_removes_the_file(page, folder):
    name(page, "lamp"); save(page)
    name(page, "vase"); save(page)
    library(page)
    card(page, "lamp").locator(".more").click(); page.wait_for_selector("#libyours .rev")
    page.once("dialog", lambda d: d.accept())
    card(page, "lamp").locator(".delete").click()
    page.wait_for_function("() => !document.querySelector('#libyours .card[data-name=\"lamp\"]')")
    assert files(folder) == ["vase_v1.0.lamina.json"]
    page.evaluate("__t.lib.removeProject('vase')")
    assert files(folder) == [] and lib(page) == []


def test_the_server_store_answers_as_the_others(page, folder):
    """Every call of the store's shape, on the real server: record and removeIf too, which only a move uses."""
    r = page.evaluate("""async () => { const S = await import('/static/js/store.js'), s = S.serverStore({name: 'projects', problem: ''});
        const out = {kind: s.kind, label: s.label, w: await s.write('x_v1.0.lamina.json', '{"a":1}')};
        out.list = await s.list(); out.text = await s.read('x_v1.0.lamina.json'); out.rec = await s.record('x_v1.0.lamina.json');
        out.stale = await s.removeIf('x_v1.0.lamina.json', {size: 99, mtime: out.w.mtime});
        out.gone = await s.removeIf('x_v1.0.lamina.json', out.w);
        await s.write('y_v1.0.lamina.json', '{}'); await s.remove('y_v1.0.lamina.json');
        out.bad = await s.write('../x.lamina.json', '{}').then(() => null, e => e.message);
        out.after = await s.list(); return out }""")
    assert (r["kind"], r["label"], r["text"]) == ("server", "projects", '{"a":1}')
    assert r["w"]["size"] == 7 and r["list"] == [{"file": "x_v1.0.lamina.json", **r["w"]}]
    assert r["rec"] == {"file": "x_v1.0.lamina.json", "text": '{"a":1}', **r["w"]}
    assert (r["stale"], r["gone"], r["after"]) == (False, True, [])
    assert "not the name of a project file" in r["bad"] and not (folder.parent / "x.lamina.json").exists()


def test_browser_projects_are_counted_and_moved_to_the_server_folder(page, folder):
    put(page, "lamp_v1.0.lamina.json", project("lamp")); put(page, "vase_v1.0.lamina.json", project("vase"))
    (folder / "lamp_v1.0.lamina.json").write_text(project("lamp", extra=" "), encoding="utf-8")   # the folder has it already
    page.evaluate("__t.lib.restoreStore()")
    assert page.evaluate("__t.lib.storeState().browser") == 2
    library(page)
    assert line(page) == "📁 kept in the folder projects on the server · 1 file. 2 revisions are still in this browser."
    assert where(page)[1] == ["libtoserver"] and page.inner_text("#libtoserver") == "move them to the server folder"
    page.click("#libtoserver")
    page.wait_for_selector("#libask[open]")
    assert page.text_content("#libask h3") == "Move onto a revision already there?"
    page.click("#libask_keep")
    assert note(page) == "Server folder projects: 2 revisions moved into it."
    assert files(folder) == ["lamp_v1.0.lamina.json", "lamp_v1.1.lamina.json", "vase_v1.0.lamina.json"]
    assert (folder / "lamp_v1.0.lamina.json").read_text(encoding="utf-8") == project("lamp", extra=" ")   # kept, not replaced
    assert json.loads((folder / "lamp_v1.1.lamina.json").read_text(encoding="utf-8"))["rev"] == "1.1"
    assert browser_files(page) == []
    page.wait_for_function(r"() => /· 3 files\.$/.test(document.querySelector('#libwhere > span').innerText.trim())")   # listed again
    assert line(page) == "📁 kept in the folder projects on the server · 3 files." and where(page)[1] == []


def test_a_cancelled_move_says_what_stayed(page, folder):
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    (folder / "lamp_v1.0.lamina.json").write_text(project("lamp", extra=" "), encoding="utf-8")
    page.evaluate("__t.lib.restoreStore()")
    library(page)
    page.click("#libtoserver"); page.wait_for_selector("#libask[open]"); page.click("#libask_cancel")
    text = note(page)
    assert text.startswith("⚠ Server folder projects, not all moved: 0 revisions moved into it. lamp v1.0 stayed in this browser, safe:")
    assert text.endswith("To move it, press move it to the server folder again and choose keep both.")
    assert browser_files(page) == ["lamp_v1.0.lamina.json"]
    assert "1 revision is still in this browser." in where(page)[0] and page.inner_text("#libtoserver") == "move it to the server folder"


def test_a_folder_the_server_cannot_write(browser, tmp_path):
    """Made unusable portably: a file stands where the folder should be made. Docker's read-only mount and the owner
    problem are the same path on the server (library_problem); the Docker check runs them for real."""
    (tmp_path / "file").write_text("")
    with serve_app({"LAMINA_LIBRARY": str(tmp_path / "file" / "projects")}) as url:
        pg = new_page(browser, url)
        try:
            state = pg.evaluate("__t.lib.storeState()")
            assert state["state"] == "server" and state["problem"].startswith("The server cannot write to its library folder projects (")
            pg.click("#popen")                                                 # no listing: the folder is not there
            pg.wait_for_function("() => /^⚠ The server cannot write/.test(document.querySelector('#libwhere').innerText)")
            assert line(pg) == "⚠ " + state["problem"] and where(pg)[1] == []
            assert pg.locator("#libwhere .note").count() == 0                      # said once, on the line
            pg.click("#libclose")
            name(pg, "lamp")
            pg.click("#psave2")
            msg = said(pg, "Not saved:")                                       # the listing before the write says it
            assert msg == "Not saved: " + state["problem"]
            assert pg.get_attribute("#status", "title") == msg and pg.get_attribute("#dot", "class") == "err"
            assert browser_files(pg) == []                                     # no fallback to the browser
        finally:
            pg.context.close()
