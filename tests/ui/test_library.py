"""The project library: the loaded example is the page's own state, so a page without the dropdown can open one;
the zip module and the two stores under the library."""
import base64
import contextlib
import io
import json
import re
import time
import zipfile

import pytest

from .helpers import ROOT, example, menu, set_fields, settle, still


def wipe(page):
    """An empty library behind the browser store, and nothing saved in this tab. The files are removed through the
    store itself: the library refuses to delete one it cannot read, and some tests leave one. The store tests below
    delete the database instead; both leave it empty, and the library opens it again on its next call."""
    page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore();
        for (const f of await b.list()) await b.remove(f.file); await S.idxSet('browser', []);
        const root = await navigator.storage.getDirectory();
        for (const d of ['lib', 'lib2']) await root.removeEntry(d, {recursive: true}).catch(() => {});
        const st = __t.lib.storeState();
        if (st.kind !== 'browser' || st.left) { await S.kvDel('folder'); await __t.lib.restoreStore() } else __t.lib.useStore(b);
        __t.lib.setSaved(null);
        const s = __t.state(); s.project = ''; s.rev = '1.0'; (await import('/static/js/project.js')).syncProject() }""")


ANSWERS = []


def on_dialog(page, fn):
    """`fn` answers the page's next dialog (confirm). One a test left unused is taken off when it ends: a failed test's
    answer must not answer the next test's question."""
    ANSWERS.append(fn); page.once("dialog", fn)


@pytest.fixture(autouse=True)
def empty_library(page):
    wipe(page)
    yield
    for fn in ANSWERS:
        with contextlib.suppress(KeyError):                                   # an answer that was used is gone already
            page.remove_listener("dialog", fn)
    ANSWERS.clear()
    page.evaluate("import('/static/js/librarypage.js').then(P => P.hideLibrary())")   # one page for the run: the next test starts on the app


def lib(page):
    """The library as entries() lists it, in its order: [(name, [rev, …]), …]."""
    return [(p["name"], [r["rev"] for r in p["revs"]]) for p in page.evaluate("__t.lib.entries()")]


def save(page, answer=None):
    """saveCurrent() with `ask` answering `answer`: [its result, the clashes it was asked about]."""
    return page.evaluate("""async a => { const asked = [];
        const r = await __t.lib.saveCurrent(c => { asked.push(c); return Promise.resolve(a) }); return [r, asked] }""", answer)


def name(page, n):
    set_fields(page, [("pname", n)]); settle(page)


def bump(page, major=False):
    """+0.1 or +1 as a click, waited for: the button lists the library first when nothing has listed it yet."""
    before = page.text_content("#prev")
    menu(page, "#pmajor" if major else "#pminor")
    page.wait_for_function("b => document.querySelector('#prev').textContent !== b", arg=before)


def put(page, file, text):
    """A file written into the browser store behind the library's back: another tab, or a file copied in."""
    page.evaluate("([f, t]) => import('/static/js/store.js').then(S => S.browserStore().write(f, t))", [file, text])


def read(page, file):
    """A file as the store holds it, parsed when it is a project."""
    t = page.evaluate("f => import('/static/js/store.js').then(S => S.browserStore().read(f))", file)
    return json.loads(t) if t.startswith("{") else t


def test_open_example_is_page_state(page):
    example(page, "horse_statue")
    assert page.evaluate("__t.project().then(p => p.example)") == "horse_statue"
    assert page.evaluate("__t.job()").startswith("ex_")


def test_zip_made_in_the_page_opens_in_python(page):
    b64 = page.evaluate("""async () => { const {zip} = await import('/static/js/zip.js');
        const buf = await zip([{name:'a_v1.0.lamina.json', text:'{"n":"é"}'}, {name:'b_v2.0.lamina.json', text:'{}'}]).arrayBuffer();
        return btoa(String.fromCharCode(...new Uint8Array(buf))) }""")
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(b64)))
    assert z.testzip() is None and z.namelist() == ["a_v1.0.lamina.json", "b_v2.0.lamina.json"]
    assert z.read("a_v1.0.lamina.json").decode() == '{"n":"é"}'
    assert all(i.flag_bits & 0x800 for i in z.infolist())              # names are flagged UTF-8


def test_unzip_reads_back_and_names_bad_entries(page):
    files = [{"name": "a_v1.0.lamina.json", "text": '{"n":"é"}'}, {"name": "ü_v2.0.lamina.json", "text": "{}"}]
    back = page.evaluate("""async files => { const {zip, unzip} = await import('/static/js/zip.js');
        const r = await unzip(await zip(files).arrayBuffer()); return {files: [...r], bad: r.bad} }""", files)
    assert back == {"files": files, "bad": []}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:                               # made by Python: one stored, one deflated entry
        z.writestr("stored.json", '{"s":1}', zipfile.ZIP_STORED)
        z.writestr("deflated.json", '{"d":2}' * 50, zipfile.ZIP_DEFLATED)
    back = page.evaluate("""async b64 => { const {unzip} = await import('/static/js/zip.js');
        const r = await unzip(Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer); return {files: [...r], bad: r.bad} }""",
        base64.b64encode(buf.getvalue()).decode())
    assert back == {"files": [{"name": "stored.json", "text": '{"s":1}'}], "bad": ["deflated.json"]}
    err = page.evaluate("""async () => { const {unzip} = await import('/static/js/zip.js');
        try { await unzip(new TextEncoder().encode('{"not":"a zip"}').buffer) } catch (e) { return e.message } }""")
    assert err == "not a zip"


UNZIP = """async b64 => { const {unzip} = await import('/static/js/zip.js');
    try { const r = await unzip(Uint8Array.from(atob(b64), c => c.charCodeAt(0)).buffer); return {files: [...r], bad: r.bad} }
    catch (e) { return e.name + ': ' + e.message } }"""


def test_unzip_of_a_broken_zip(page):
    """A truncated zip, or one whose directory points past its end, is "not a zip", never a RangeError; an entry
    whose bytes do not match its CRC is named bad."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.json", '{"a":1}'); z.writestr("b.json", '{"b":2}')
    good = buf.getvalue()
    b64 = lambda b: base64.b64encode(b).decode()
    assert page.evaluate(UNZIP, b64(good[:-30])) == "Error: not a zip"         # the end record cut off
    far = bytearray(good); far[-6:-2] = (len(good) * 4).to_bytes(4, "little")   # the directory's offset, past the end
    assert page.evaluate(UNZIP, b64(bytes(far))) == "Error: not a zip"
    many = bytearray(good); many[-12:-10] = (9).to_bytes(2, "little")           # more entries than the directory holds
    assert page.evaluate(UNZIP, b64(bytes(many))) == "Error: not a zip"
    bent = bytearray(good); bent[good.index(b'{"a":1}') + 2] ^= 1              # one bit of a's text flipped
    assert page.evaluate(UNZIP, b64(bytes(bent))) == {"files": [{"name": "b.json", "text": '{"b":2}'}], "bad": ["a.json"]}


# each store test starts from an empty store: the browser one deletes the database (so opening it also covers the
# first run, when it does not exist yet), the folder one works in a fresh sub-folder of the origin's private folder
FRESH = """async kind => { const S = await import('/static/js/store.js');
    if (kind === 'browser') { await new Promise((ok, no) => { const r = indexedDB.deleteDatabase('lamina_library');
        r.onsuccess = ok; r.onerror = () => no(r.error) }); return S.browserStore() }
    const root = await navigator.storage.getDirectory(); await root.removeEntry('lib-test', {recursive: true}).catch(() => {});
    return S.folderStore(await root.getDirectoryHandle('lib-test', {create: true})) }"""


@pytest.mark.parametrize("kind", ["browser", "folder"])
def test_store_write_list_read_remove(page, kind):
    r = page.evaluate(f"""async kind => {{ const s = await ({FRESH})(kind), out = {{kind: s.kind, label: s.label}};
        out.w = await s.write('x_v1.0.lamina.json', '{{"a":1}}');
        if (kind === 'folder') {{ const d = await (await navigator.storage.getDirectory()).getDirectoryHandle('lib-test');
            const w = await (await d.getFileHandle('notes.json', {{create: true}})).createWritable(); await w.write('{{}}'); await w.close();
            await d.getDirectoryHandle('sub.lamina.json', {{create: true}}) }}
        out.list = await s.list(); out.text = await s.read('x_v1.0.lamina.json');
        await s.remove('x_v1.0.lamina.json'); out.after = await s.list(); return out }}""", kind)
    assert (r["kind"], r["label"]) == (kind, "lib-test" if kind == "folder" else "this browser")
    assert r["w"]["size"] == 7 and r["w"]["mtime"] > 0
    assert [(e["file"], e["size"]) for e in r["list"]] == [("x_v1.0.lamina.json", 7)] and r["list"][0]["mtime"] > 0
    assert r["text"] == '{"a":1}' and r["after"] == []


def test_folder_write_swaps_the_file_in_whole(page):
    """createWritable writes to a side file and close() swaps it in: a write that fails leaves the old file, and a
    new file that fails is not left behind empty."""
    r = page.evaluate(f"""async () => {{ const s = await ({FRESH})('folder'), P = FileSystemWritableFileStream.prototype;
        await s.write('x_v1.0.lamina.json', 'old'); const calls = [], write = P.write, close = P.close;
        P.close = function () {{ calls.push('close'); return close.call(this) }};
        await s.write('x_v1.0.lamina.json', 'new!'); P.close = close;
        P.write = () => Promise.reject(new Error('disk full'));
        const err = await s.write('x_v1.0.lamina.json', 'lost').catch(e => e.message);
        const err2 = await s.write('y_v1.0.lamina.json', 'lost').catch(e => e.message); P.write = write;
        return {{calls, err, err2, text: await s.read('x_v1.0.lamina.json'), list: (await s.list()).map(e => e.file)}} }}""")
    assert r == {"calls": ["close"], "err": "disk full", "err2": "disk full", "text": "new!", "list": ["x_v1.0.lamina.json"]}


def test_kv_holds_a_folder_handle_and_index_starts_empty(page):
    r = page.evaluate("""async () => { const S = await import('/static/js/store.js');
        const root = await navigator.storage.getDirectory(), d = await root.getDirectoryHandle('lib-test', {create: true});
        await S.kvSet('folder', d); const h = await S.kvGet('folder');
        const back = await (await h.getFileHandle('k.txt', {create: true})).getFile();
        await S.idxSet('browser', [{file: 'x_v1.0.lamina.json', size: 7}]);
        const out = {name: h.name, same: await h.isSameEntry(d), file: back.name, idx: await S.idxGet('browser'),
            none: await S.idxGet('never-written')};
        await S.kvDel('folder'); out.gone = (await S.kvGet('folder')) ?? null; return out }""")
    assert r == {"name": "lib-test", "same": True, "file": "k.txt", "idx": [{"file": "x_v1.0.lamina.json", "size": 7}],
                 "none": [], "gone": None}


def test_snapshot_is_a_small_picture_and_moves_nothing(page):
    example(page, "vase"); page.mouse.move(700, 300); page.mouse.down(); page.mouse.move(820, 360); page.mouse.up()   # orbit away
    still(page)
    page.evaluate("__t.select(__t.parts()[0].userData.slice)")                  # a highlight and a gizmo to put back
    # the page's view either side of the snapshot, in one task: the orbit's damping still nudges the camera by a
    # hundred-thousandth of a millimetre a frame long after it looks still. The scene's groups and the renderer are read
    # from the page's own modules (the same instances main.js imported); ST.dirty is set false first so its restore shows
    before, after, url = page.evaluate("""async () => { const S = await import('/static/js/scene.js'), {ST} = await import('/static/js/state.js');
        const v = () => JSON.stringify([S.camera.position, S.controls.target, S.renderer.domElement.width, S.renderer.domElement.height,
            S.renderer.getPixelRatio(), ST.dirty, [S.rings, S.gizmo, S.guides, S.axes, S.ghost, S.banner, ...S.axes.children].map(o => o.visible),
            S.parts.children.map(m => [m.visible, m.position, m.material.emissive.getHex()]), document.querySelector('#fold').value]);
        ST.dirty = false; const b = v(), u = S.snapshot(); return [b, v(), u] }""")
    assert url.startswith("data:image/")
    w, h = page.evaluate("u => new Promise(r => { const i = new Image(); i.onload = () => r([i.width, i.height]); i.src = u })", url)
    assert (w, h) == (320, 240)
    assert after == before
    assert len(url) < 120_000


def test_snapshot_is_the_fitted_view_not_the_users_camera(page):
    example(page, "vase"); a = page.evaluate("__t.snapshot()")
    page.evaluate("__t.cam(150, -40, __t.camera.position.distanceTo(__t.target()) * 4)"); still(page)   # far away, from below
    assert page.evaluate("__t.snapshot()") == a


def test_snapshot_ignores_selection_ghost_steps_and_explode(page):
    """The card is the model as built, not what the view happens to show: a part selected, the see-through model
    ticked, the steps slider short and the parts exploded give the same picture as none of them."""
    example(page, "vase")
    ui = """([ghost, steps, explode, sel]) => { const g = document.querySelector('#ghost'); g.checked = ghost; g.onchange();
        for (const [id, v] of [['#steps', steps], ['#explode', explode]]) { const el = document.querySelector(id);
            el.value = v ?? el.max; el.dispatchEvent(new Event('input', {bubbles: true})) }
        sel ? __t.select(__t.parts()[1].userData.slice) : __t.deselect(); return __t.snapshot() }"""
    a = page.evaluate(ui, [False, None, 1, False])
    try:
        b = page.evaluate(ui, [True, 3, 2, True])
        assert page.evaluate("__t.banner()").startswith("step 3")             # the view did change: short of the end
    finally:
        page.evaluate(ui, [True, None, 1, False])   # the view bar's own defaults: no tab's reset puts them back
    assert a.startswith("data:image/") and b == a


def test_next_free_revision(page):
    nf = lambda taken, cur, major: page.evaluate("([t,c,m]) => __t.lib.nextFree(t,c,m)", [taken, cur, major])
    assert nf(["1.0", "1.1", "1.2", "1.3"], "1.0", False) == "1.4"
    assert nf(["1.0", "1.1", "1.3"], "1.1", False) == "1.2"
    assert nf(["1.0", "2.0"], "1.0", True) == "3.0"
    assert nf([], "1.0", False) == "1.1"


def test_file_name_is_legal_and_two_names_do_not_collide(page):
    assert page.evaluate("__t.lib.fileName('a/b:c', '1.0')") == "a_b_c_v1.0.lamina.json"
    assert page.evaluate("s => __t.lib.fileName(s, '2.0')", 'x\\/:*?"<>|\x01\x1f') == "x" + "_" * 11 + "_v2.0.lamina.json"
    # no dot first and no two dots running: a name a server folder takes too (web/app.py, lib_path)
    assert page.evaluate("__t.lib.fileName('.x..y...z', '1..0')") == "_x_.y__.z_v1_.0.lamina.json"
    name(page, "a/b"); first, _ = save(page)
    name(page, "a_b"); second, asked = save(page)
    assert (first["file"], second["file"], asked) == ("a_b_v1.0.lamina.json", "a_b~2_v1.0.lamina.json", [])
    assert sorted(lib(page)) == [("a/b", ["1.0"]), ("a_b", ["1.0"])]          # the names come from inside the files
    bump(page); settle(page)                                                   # its next revision keeps its own stem
    assert save(page)[0] == {"file": "a_b~2_v1.1.lamina.json"}
    name(page, "a:b"); assert save(page) == [{"file": "a_b~3_v1.1.lamina.json"}, []]   # a rename keeps the revision


def test_names_that_differ_only_in_case_get_two_files(page):
    """A folder on Windows or macOS holds Lamp_v1.0 and lamp_v1.0 as one file: the second name takes ~2."""
    name(page, "Lamp"); save(page)
    name(page, "lamp"); assert save(page) == [{"file": "lamp~2_v1.0.lamina.json"}, []]
    assert sorted(lib(page)) == [("Lamp", ["1.0"]), ("lamp", ["1.0"])]


def test_unreadable_files_are_never_written_or_deleted(page):
    put(page, "lamp_v1.0.lamina.json", "not json"); put(page, "empty_v1.0.lamina.json", "{}")   # {} parses, and is no project
    name(page, "lamp")
    assert save(page) == [{"file": "lamp~2_v1.0.lamina.json"}, []]
    assert sorted(lib(page)) == [("empty_v1.0.lamina.json", [""]), ("lamp", ["1.0"]), ("lamp_v1.0.lamina.json", [""])]
    assert all(r["bad"] for p in page.evaluate("__t.lib.entries()") if p["name"] != "lamp" for r in p["revs"])
    for call in ("removeRevision('lamp_v1.0.lamina.json')", "removeProject('empty_v1.0.lamina.json')"):
        err = page.evaluate(f"__t.lib.{call}.then(() => null, e => e.message)")
        assert err and "cannot be read" in err
    assert read(page, "lamp_v1.0.lamina.json") == "not json" and read(page, "empty_v1.0.lamina.json") == {}


def test_keep_skips_a_revision_that_cannot_be_read(page):
    name(page, "lamp"); save(page)
    put(page, "lamp_v1.1.lamina.json", "not json")
    page.evaluate("__t.lib.setSaved(null)")                                    # a new project named like the old one
    r, asked = save(page, "keep")
    assert asked == [{"name": "lamp", "rev": "1.0", "next": "1.2"}] and r == {"file": "lamp_v1.2.lamina.json"}
    assert read(page, "lamp_v1.1.lamina.json") == "not json"
    settle(page)


def test_save_then_reload_then_open(page):
    page.click('nav button[data-t="technique"]'); page.click('#modes button[data-m="stacked"]'); settle(page)
    set_fields(page, [("p_thickness", 4)]); name(page, "lamp")
    assert save(page) == [{"file": "lamp_v1.0.lamina.json"}, []]
    page.reload(); settle(page)
    (p,) = page.evaluate("__t.lib.entries()")
    assert (p["name"], [r["rev"] for r in p["revs"]]) == ("lamp", ["1.0"]) and p["revs"][0]["preview"].startswith("data:image/")
    page.click('nav button[data-t="technique"]'); page.click('#modes button[data-m="interlocked"]'); settle(page)
    set_fields(page, [("p_thickness", 3)]); settle(page)
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    assert page.evaluate("__t.plan().mode") == "stacked" and page.evaluate("__t.state().thickness") == 4
    assert page.evaluate("__t.lib.unsaved()") is False                         # what was opened is what is in hand


def test_save_overwrites_only_the_revision_in_hand(page):
    name(page, "lamp"); save(page)
    (a,) = page.evaluate("__t.lib.entries()")[0]["revs"]
    set_fields(page, [("p_thickness", 4)]); settle(page)
    assert save(page) == [{"file": "lamp_v1.0.lamina.json"}, []]               # ask is never called
    (b,) = page.evaluate("__t.lib.entries()")[0]["revs"]
    assert b["saved"] > a["saved"] and lib(page) == [("lamp", ["1.0"])]


def test_bump_then_save_keeps_both(page):
    name(page, "lamp"); save(page)
    bump(page); settle(page); save(page)
    assert lib(page) == [("lamp", ["1.1", "1.0"])]


def test_bump_from_an_old_revision_goes_to_the_next_free(page):
    name(page, "lamp"); save(page)
    one = read(page, "lamp_v1.0.lamina.json")
    for rev in ("1.1", "1.2", "1.3"):                                          # copies made by hand: no slice each
        put(page, f"lamp_v{rev}.lamina.json", json.dumps({**one, "rev": rev, "state": {**one["state"], "rev": rev}}))
    assert lib(page) == [("lamp", ["1.3", "1.2", "1.1", "1.0"])]
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    bump(page)
    assert page.evaluate("__t.state().rev") == "1.4" and page.text_content("#prev") == "1.4"
    bump(page, major=True)
    assert page.evaluate("__t.state().rev") == "2.0"
    settle(page)


def test_changed_name_is_a_new_project(page):
    name(page, "lamp"); save(page)
    (before,) = page.evaluate("__t.lib.entries()")
    name(page, "lamp-big"); assert save(page) == [{"file": "lamp-big_v1.0.lamina.json"}, []]
    after = page.evaluate("__t.lib.entries()")
    assert sorted(p["name"] for p in after) == ["lamp", "lamp-big"]
    assert next(p for p in after if p["name"] == "lamp") == before              # untouched, in the list
    assert read(page, "lamp_v1.0.lamina.json")["saved"] == before["revs"][0]["saved"]   # and in the file


@pytest.mark.parametrize("answer", ["keep", "replace", None])
def test_save_onto_another_revision_asks(page, answer):
    name(page, "lamp"); save(page)
    (old,) = page.evaluate("__t.lib.entries()")[0]["revs"]
    page.evaluate("__t.lib.setSaved(null)")                                    # a new project, named like the old one
    set_fields(page, [("p_thickness", 4)]); settle(page)
    r, asked = save(page, answer)
    assert asked == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]
    if answer == "keep":
        assert r == {"file": "lamp_v1.1.lamina.json"} and lib(page) == [("lamp", ["1.1", "1.0"])]
        assert page.evaluate("__t.state().rev") == "1.1" and page.text_content("#prev") == "1.1"
        assert page.evaluate("__t.lib.entries()")[0]["revs"][1] == old
        settle(page)
    elif answer == "replace":
        assert r == {"file": "lamp_v1.0.lamina.json"} and lib(page) == [("lamp", ["1.0"])]
        assert page.evaluate("__t.lib.entries()")[0]["revs"][0]["saved"] > old["saved"]
    else:
        assert r is None and page.evaluate("__t.lib.entries()")[0]["revs"] == [old]
        assert read(page, "lamp_v1.0.lamina.json")["saved"] == old["saved"]
        assert page.evaluate("__t.lib.unsaved()") is True


def test_a_file_opened_from_disk_over_a_revision_asks(page):
    """Opened from the library, then the same name and revision opened from a file: that file is not this tab's revision."""
    name(page, "lamp"); save(page)
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    page.evaluate("""async () => { const S = await import('/static/js/store.js'), P = await import('/static/js/project.js');
        await P.openProjectText(await S.browserStore().read('lamp_v1.0.lamina.json'), 'lamp_v1.0.lamina.json') }"""); settle(page)
    assert save(page)[1] == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]


def test_only_the_file_in_hand_is_written_without_asking(page):
    """Two files with one name inside (a copy made by hand): the one opened is the one saved. Another store, or the
    same file saved by another tab since, asks."""
    name(page, "lamp"); save(page)
    put(page, "lamp-copy_v1.0.lamina.json", json.dumps(read(page, "lamp_v1.0.lamina.json")))
    first = read(page, "lamp_v1.0.lamina.json")["saved"]
    page.evaluate("__t.lib.openRevision('lamp-copy_v1.0.lamina.json')"); settle(page)
    set_fields(page, [("p_thickness", 4)]); settle(page)
    assert save(page) == [{"file": "lamp-copy_v1.0.lamina.json"}, []]
    assert read(page, "lamp_v1.0.lamina.json")["saved"] == first
    assert read(page, "lamp-copy_v1.0.lamina.json")["state"]["thickness"] == 4
    put(page, "lamp-copy_v1.0.lamina.json", json.dumps(read(page, "lamp-copy_v1.0.lamina.json")))   # another tab saved it
    assert save(page)[1] == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]
    save(page, "replace")
    asked = page.evaluate("""async () => { const S = await import('/static/js/store.js'), asked = [];
        __t.lib.useStore({...S.browserStore(), label: 'another folder'});
        try { await __t.lib.saveCurrent(c => { asked.push(c); return Promise.resolve(null) }) } finally { __t.lib.useStore(S.browserStore()) }
        return asked }""")
    assert asked == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]


def test_a_second_save_while_one_runs_gets_its_answer(page):
    name(page, "lamp")
    r = page.evaluate("""async () => { const asked = [], ask = c => { asked.push(c); return Promise.resolve(null) };
        const rs = await Promise.all([__t.lib.saveCurrent(ask), __t.lib.saveCurrent(ask)]); return [rs, asked] }""")
    assert r == [[{"file": "lamp_v1.0.lamina.json"}] * 2, []] and lib(page) == [("lamp", ["1.0"])]


def test_empty_name_takes_the_models_name(page):
    example(page, "egg"); name(page, "")
    assert save(page)[0] == {"file": "egg_v1.0.lamina.json"}
    assert lib(page) == [("egg", ["1.0"])] and page.input_value("#pname") == "egg"
    settle(page)


def test_unsaved_follows_changes_and_survives_reload(page):
    unsaved = lambda: page.evaluate("__t.lib.unsaved()")
    page.evaluate("() => { window.__seen = 0; __t.lib.onChange(() => window.__seen++) }")
    name(page, "lamp"); seen = page.evaluate("window.__seen")
    assert seen > 0                                                            # typing the name told the page
    save(page)
    assert unsaved() is False
    set_fields(page, [("p_thickness", 4)]); settle(page)
    assert unsaved() is True and page.evaluate("window.__seen") > seen         # so did the slice after a change
    save(page); assert unsaved() is False
    page.reload(); settle(page)
    assert unsaved() is False                                                  # what was saved came back with the session
    set_fields(page, [("p_thickness", 5)]); settle(page)
    page.reload(); settle(page)
    assert unsaved() is True


def test_an_example_as_it_opened_has_no_unsaved_changes(page):
    example(page, "vase")
    assert page.evaluate("__t.lib.unsaved()") is False
    set_fields(page, [("p_thickness", 4)]); settle(page)
    assert page.evaluate("__t.lib.unsaved()") is True
    assert save(page)[0] == {"file": "vase_v1.0.lamina.json"}                  # still a new project of its own


def test_unsaved_counts_another_techniques_settings(page):
    """A parameter both techniques have, changed on the other one and left there: the form is as saved, the memory
    a save would write is not."""
    shared = page.evaluate("""async () => { const {ST} = await import('/static/js/state.js'), m = n => ST.MODES.find(x => x.name === n).params;
        return m('interlocked').find(p => (p.type === 'int' || p.type === 'number') && m('stacked').some(q => q.name === p.name))?.name }""")
    assert shared, "no number parameter that both stacked and interlocked have"
    tech = lambda m: (page.click('nav button[data-t="technique"]'), page.click(f'#modes button[data-m="{m}"]'), settle(page))
    tech("interlocked"); tech("stacked"); name(page, "lamp"); save(page)
    form = page.evaluate("JSON.stringify(__t.state())")
    tech("interlocked")
    v = page.evaluate(f"__t.state().{shared}")
    set_fields(page, [(f"p_{shared}", v + 1)]); settle(page)
    tech("stacked")
    assert page.evaluate("JSON.stringify(__t.state())") == form and page.evaluate("__t.lib.unsaved()") is True


def test_an_uploaded_model_saved_is_not_unsaved_after_a_refresh(page):
    page.set_input_files("#file", str(ROOT / "examples" / "bracket.stl")); settle(page)
    assert page.evaluate("__t.lib.unsaved()") is True                          # a fresh upload is nobody's revision yet
    name(page, ""); assert save(page)[0] == {"file": "bracket_v1.0.lamina.json"}
    settle(page)                                    # the name it took reaches the session with the slice it starts
    page.reload(); settle(page)
    assert page.evaluate("__t.lib.unsaved()") is False
    set_fields(page, [("p_thickness", 4)]); settle(page)
    assert page.evaluate("__t.lib.unsaved()") is True


def test_a_bump_after_a_refresh_goes_to_the_next_free(page):
    name(page, "lamp"); save(page); bump(page); settle(page); save(page)
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    page.reload(); settle(page)
    assert page.evaluate("__t.state().rev") == "1.0"
    bump(page)
    assert page.text_content("#prev") == "1.2"
    settle(page)


def test_a_refused_write_changes_nothing(page):
    name(page, "lamp"); save(page)
    set_fields(page, [("p_thickness", 4)]); settle(page)
    before = page.evaluate("__t.lib.entries()")
    assert page.evaluate("__t.lib.unsaved()") is True
    err = page.evaluate("""async () => { const S = await import('/static/js/store.js');
        __t.lib.useStore({...S.browserStore(), write: () => { throw new DOMException('full', 'QuotaExceededError') }});
        try { await __t.lib.saveCurrent(() => Promise.resolve('replace')); return null } catch (e) { return [e.constructor.name, e.message] }
        finally { __t.lib.useStore(S.browserStore()) } }""")
    assert err[0] == "Error" and "export" in err[1] and "full" in err[1]
    assert page.evaluate("__t.lib.entries()") == before
    assert page.evaluate("__t.lib.unsaved()") is True


def test_delete_revision_and_project(page):
    name(page, "lamp"); save(page); bump(page); settle(page); save(page)
    name(page, "vase"); save(page)
    page.evaluate("__t.lib.removeRevision('lamp_v1.1.lamina.json')")
    assert sorted(lib(page)) == [("lamp", ["1.0"]), ("vase", ["1.1"])]
    page.evaluate("__t.lib.removeProject('lamp')")
    assert lib(page) == [("vase", ["1.1"])] and page.evaluate("__t.lib.unsaved()") is False   # vase 1.1, in hand, is still saved
    page.evaluate("__t.lib.removeProject('vase')")
    assert lib(page) == [] and page.evaluate("__t.lib.unsaved()") is True      # the revision in hand is gone
    page.reload(); settle(page)
    assert lib(page) == []                                                     # the index agrees with the store


def test_store_rejects_with_the_error_and_lets_go_of_the_database(page):
    """A call that throws inside its transaction rejects with that error and closes the database: left open, it
    would block deleteDatabase (and another tab that opens a newer version)."""
    r = page.evaluate("""async () => { const S = await import('/static/js/store.js');
        const e = await S.kvSet('k', () => {}).then(() => null, e => e?.name ?? String(e));
        const del = await new Promise(ok => { const q = indexedDB.deleteDatabase('lamina_library');
            q.onsuccess = () => ok('deleted'); q.onerror = () => ok('error'); setTimeout(() => ok('still open'), 5000) });
        return [e, del] }""")
    assert r == ["DataCloneError", "deleted"]


def test_folder_list_skips_a_file_that_vanished(page):
    r = page.evaluate(f"""async () => {{ const s = await ({FRESH})('folder'), P = FileSystemFileHandle.prototype, g = P.getFile;
        await s.write('a_v1.0.lamina.json', '{{}}'); await s.write('gone_v1.0.lamina.json', '{{}}');
        P.getFile = function () {{ return this.name === 'gone_v1.0.lamina.json' ? Promise.reject(new DOMException('gone', 'NotFoundError')) : g.call(this) }};
        try {{ return (await s.list()).map(e => e.file) }} finally {{ P.getFile = g }} }}""")
    assert r == ["a_v1.0.lamina.json"]


# ---------------------------------------------------------------- the library page and the top bar
def library(page):
    """The library page opened from the top bar, its cards listed."""
    page.click("#popen")
    page.wait_for_function("() => !document.querySelector('#library').hidden && document.querySelector('#libyours').dataset.listed")


def cards(page):
    """The names on the cards that show, in their order."""
    return page.eval_on_selector_all("#libyours .card:not([hidden])", "cs => cs.map(c => c.dataset.name)")


def card(page, n):
    return page.locator(f'#libyours .card[data-name="{n}"]')


def said(page, start):
    """Wait for the status line to start with `start`; returns the whole line."""
    page.wait_for_function("s => document.querySelector('#status').textContent.startsWith(s)", arg=start)
    return page.text_content("#status")


def opened(page, file):
    """Wait until `file` is the revision in hand (read and opened, its slice started), then for its slice."""
    page.wait_for_function("f => __t.lib.inHand()?.file === f", arg=file)
    settle(page)


def revisions(page, n, revs):
    """Project `n` saved at each revision in `revs` (bumped between saves, so the last is the one in hand)."""
    name(page, n)
    for i, _ in enumerate(revs):
        if i:
            bump(page); settle(page)
        save(page)
    assert lib(page)[0] == (n, revs[::-1])


def test_top_bar_opens_and_closes_the_library(page):
    assert page.text_content("#popen") == "library" and page.text_content("#psave2") == "save"
    assert page.locator("#pfile").count() == 0
    before = page.evaluate("JSON.stringify([__t.state(), __t.job()])")
    library(page)
    assert page.text_content("#libyours").strip() == "No projects yet. Save one with save, or import files."
    assert page.text_content("#libwhere > span").strip() == "💾 kept in this browser only. Clearing the site data deletes them: use export all for a backup."
    page.keyboard.press("Escape")
    assert page.is_hidden("#library")
    library(page); page.click("#libclose")
    assert page.is_hidden("#library") and page.evaluate("JSON.stringify([__t.state(), __t.job()])") == before


def test_save_button_writes_and_clears_unsaved(page):
    name(page, "lamp")
    assert page.is_visible("#punsaved") and page.text_content("#punsaved") == "● unsaved changes"
    page.click("#psave2")
    assert said(page, "saved") == "saved lamp v1.0"
    assert page.is_hidden("#punsaved") and lib(page) == [("lamp", ["1.0"])]
    set_fields(page, [("p_thickness", 4)]); settle(page)
    assert page.is_visible("#punsaved")
    # a write that fails: its own words on the status line, nothing put before them
    page.evaluate("""async () => { const S = await import('/static/js/store.js');
        __t.lib.useStore({...S.browserStore(), write: () => Promise.reject(new Error('disk full'))}) }""")
    try:
        page.click("#psave2")
        line = said(page, "Not saved: lamp v1.0 could not be written in this browser")   # the cut line still says it
        assert "disk full" in line and page.get_attribute("#dot", "class") == "err"
        assert page.get_attribute("#status", "title") == line                  # the whole of it on hover
    finally:
        page.evaluate("import('/static/js/store.js').then(S => __t.lib.useStore(S.browserStore()))")
    assert page.is_visible("#punsaved")


def test_card_opens_the_newest_revision(page):
    revisions(page, "lamp", ["1.0", "1.1"])
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    library(page)
    card(page, "lamp").locator(".t").click()
    assert page.is_hidden("#library")
    opened(page, "lamp_v1.1.lamina.json")
    assert page.text_content("#prev") == "1.1"


def test_badge_opens_revisions_and_an_old_one_opens(page):
    revisions(page, "lamp", ["1.0", "1.1"])
    library(page)
    assert card(page, "lamp").locator(".more").inner_text() == "2 revisions ▾"
    card(page, "lamp").locator(".more").click()
    page.wait_for_selector("#libyours .rev")                                  # listed again, then drawn
    rows = card(page, "lamp").locator(".rev")
    assert rows.count() == 2 and page.is_visible("#library")
    assert rows.evaluate_all("rs => rs.map(r => r.dataset.file)") == ["lamp_v1.1.lamina.json", "lamp_v1.0.lamina.json"]
    assert "✓ open now" in rows.nth(0).inner_text() and "open now" not in rows.nth(1).inner_text()
    rows.nth(1).locator(".open").click()
    assert page.is_hidden("#library")
    opened(page, "lamp_v1.0.lamina.json")
    assert page.text_content("#prev") == "1.0"


def test_open_now_label(page):
    name(page, "lamp"); save(page)
    name(page, "vase"); save(page)
    library(page)
    assert "✓ open now" in card(page, "vase").inner_text() and "open now" not in card(page, "lamp").inner_text()
    meta = card(page, "lamp").locator(".m").inner_text()
    assert re.fullmatch(r"v1\.0 · \d{4}-\d\d-\d\d \d\d:\d\d", meta), meta


def test_yours_is_newest_first_and_find_filters(page):
    name(page, "aaa"); save(page)
    name(page, "zzz"); save(page)
    library(page)
    assert cards(page) == ["zzz", "aaa"]
    page.fill("#libfind", "AA")
    assert cards(page) == ["aaa"]
    page.fill("#libfind", "")
    assert cards(page) == ["zzz", "aaa"]


def test_opening_with_unsaved_changes_asks(page):
    name(page, "lamp"); save(page)
    saved = page.evaluate("__t.state().thickness")
    set_fields(page, [("p_thickness", saved + 1)]); settle(page)
    library(page)
    asked = []
    on_dialog(page, lambda d: (asked.append(d.message), d.dismiss()))
    card(page, "lamp").locator(".t").click()
    assert asked and "unsaved" in asked[0]
    assert page.is_visible("#library") and page.evaluate("__t.state().thickness") == saved + 1
    on_dialog(page, lambda d: d.accept())
    card(page, "lamp").locator(".t").click()
    assert page.is_hidden("#library")
    page.wait_for_function("() => !__t.lib.unsaved()"); settle(page)
    assert page.evaluate("__t.state().thickness") == saved and page.is_hidden("#punsaved")


def test_delete_asks_and_removes(page):
    revisions(page, "lamp", ["1.0", "1.1"])
    library(page)
    card(page, "lamp").locator(".more").click()
    page.wait_for_selector("#libyours .rev")
    assert card(page, "lamp").locator(".more").inner_text() == "2 revisions ▴"   # opened by this click, not left open before
    asked = []
    on_dialog(page, lambda d: (asked.append(d.message), d.dismiss()))
    card(page, "lamp").locator('.rev[data-file="lamp_v1.1.lamina.json"] .delete').click()
    assert "lamp v1.1" in asked[0] and lib(page) == [("lamp", ["1.1", "1.0"])]
    on_dialog(page, lambda d: d.accept())
    card(page, "lamp").locator('.rev[data-file="lamp_v1.1.lamina.json"] .delete').click()
    page.wait_for_function("() => document.querySelectorAll('#libyours .rev').length === 1")
    assert lib(page) == [("lamp", ["1.0"])] and page.is_visible("#punsaved")   # the revision in hand is gone
    on_dialog(page, lambda d: (asked.append(d.message), d.accept()))
    card(page, "lamp").locator(".deleteproject").click()
    page.wait_for_function("() => /No projects yet/.test(document.querySelector('#libyours').textContent)")
    assert "lamp" in asked[-1] and lib(page) == []


def test_a_name_with_html_is_shown_as_text(page):
    name(page, "<img src=x onerror=window.pwned=1>"); save(page)
    library(page)
    assert page.evaluate("window.pwned") is None
    assert page.locator("#libyours .card").first.inner_text().count("<img src=x") == 1


def test_placeholder_and_unreadable_cards(page):
    """A revision with no picture shows its name; a file that cannot be read is listed, and offers nothing to do."""
    put(page, "old_v1.0.lamina.json", json.dumps({"name": "old", "rev": "1.0", "mode": "stacked", "state": {}}))
    put(page, "junk_v1.0.lamina.json", "not json")
    library(page)
    assert card(page, "old").locator(".ph").inner_text() == "old"
    bad = card(page, "junk_v1.0.lamina.json")
    assert "⚠ cannot be read" in bad.inner_text() and bad.locator("button").count() == 0
    bad.click()
    assert page.is_visible("#library")


@pytest.mark.parametrize("answer", ["replace", "keep", "cancel"])
def test_clash_dialog_three_ways(page, answer):
    name(page, "lamp"); save(page)
    page.evaluate("__t.lib.setSaved(null)")                                    # a new project, named like the old one
    set_fields(page, [("p_thickness", 4)]); settle(page)
    page.click("#psave2")
    page.wait_for_selector("#libask[open]")
    assert "lamp v1.0" in page.text_content("#libask") and "v1.1" in page.text_content("#libask_keep")
    assert page.is_hidden("#libask_rest")                                       # one file: nothing to say for the rest
    page.click(f"#libask_{answer}")
    if answer == "cancel":
        page.wait_for_selector("#libask", state="hidden")
        assert lib(page) == [("lamp", ["1.0"])] and page.is_visible("#punsaved")
        return
    rev = "1.1" if answer == "keep" else "1.0"
    assert said(page, "saved") == f"saved lamp v{rev}"
    assert lib(page) == [("lamp", ["1.1", "1.0"] if answer == "keep" else ["1.0"])]
    if answer == "keep":
        settle(page)                                                           # the new revision number re-slices


def test_clash_dialog_answers_for_the_rest(page):
    """For many files at once (an import), a ticked box says the answer holds for the rest."""
    r = page.evaluate("""async () => { const P = await import('/static/js/librarypage.js');
        const a = P.askClash({name: 'lamp', rev: '1.0', next: '1.1'}, true);
        document.querySelector('#libask_rest').click(); document.querySelector('#libask_keep').click(); return a }""")
    assert r == {"answer": "keep", "rest": True}

# --- preview side (Task 8) ---
FIT = "() => { document.getElementById('fit').click(); return [__t.target().toArray(), __t.camera.position.toArray()] }"


def test_snapshot_of_a_plaque_looks_from_the_front(page):
    """The bonsai stands on its plate at -y. The preview's own camera (caught at the renderer) and the fit button both
    look from +y, so the card and the view show the slices, not the plate's back (the owner, 2026-11-17)."""
    example(page, "bonsai")
    assert page.evaluate("() => [__t.plan().mode, __t.plan().params.back]") == ["plaque", "-y"]
    target, before = page.evaluate(FIT)
    shot = page.evaluate("""async () => { const {renderer} = await import('/static/js/scene.js'), r = renderer.render, cams = [];
        renderer.render = function (s, c) { cams.push(c.position.toArray()); return r.call(this, s, c) };
        try { return [__t.snapshot().length, cams[0]] } finally { renderer.render = r } }""")
    assert shot[0] > 1000
    assert shot[1][1] > target[1] and before[1] > target[1]
    assert shot[1] == pytest.approx(before)                                    # the picture and the fit button agree
    assert page.evaluate(FIT) == [target, before]


def test_fit_of_the_model_alone_is_from_the_standard_side(page):
    """Before a model's parts land, the view shows its ghost and ST.plan is still the last model's: the plaque's side
    rule is the plan's, so the ghost alone is seen from the standard side (-y), not from the last plaque's front."""
    example(page, "bonsai")
    target, eye = page.evaluate("""async () => { const S = await import('/static/js/scene.js'), kids = [...S.parts.children];
        S.parts.clear(); try { return (%s)() } finally { S.parts.add(...kids) } }""" % FIT)
    assert eye[1] < target[1]


def test_fit_of_a_model_that_is_no_plaque_is_as_before(page):
    """The pose the fit button gave the vase before the plaque rule, measured on that code (2026-11-17)."""
    example(page, "vase")
    target, eye = page.evaluate(FIT)
    assert target == pytest.approx([0, 0, -0.2815055847167969], abs=1e-3)
    assert eye == pytest.approx([185.2492963010318, -264.64185185861686, 158.5036055304533], abs=1e-3)


# ---------------------------------------------------------------- follow-ups of the library page's review
def ask(page, many, *clicks):
    """askClash shown; `clicks` are ids clicked or keys pressed in it, in order. Returns what it resolved to."""
    page.evaluate("m => { window.__asked = import('/static/js/librarypage.js').then(P => P.askClash({name: 'lamp', rev: '1.0', next: '1.1'}, m)) }", many)
    page.wait_for_selector("#libask[open]")
    for c in clicks:
        page.click(c) if c.startswith("#") else page.keyboard.press(c)
    return page.evaluate("window.__asked")


def test_clash_dialog_escape_and_the_box(page):
    assert ask(page, False, "Escape") is None                                  # as cancel
    assert ask(page, True, "#libask_keep") == "keep"                           # many files, the box left unticked
    assert ask(page, True, "#libask_rest", "#libask_cancel") == {"answer": None, "rest": True}


def test_a_closed_library_keeps_no_cards(page):
    name(page, "lamp"); save(page)
    library(page)
    assert cards(page) == ["lamp"]
    page.click("#libclose")
    assert page.inner_html("#libyours") == ""                                  # a reopen draws them again, from a new listing
    library(page)
    assert cards(page) == ["lamp"]


def test_save_says_saved_when_the_store_switched_meanwhile(page):
    """The status line names what was saved without asking the library what is in hand: here the store's label
    changes while the save runs, so nothing is in hand of the store the library holds when the save is done."""
    name(page, "lamp")
    page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore(), s = {...b};
        s.write = async (f, t) => { const w = await b.write(f, t); setTimeout(() => { s.label = 'another folder' }); return w };
        __t.lib.useStore(s) }""")
    try:
        page.click("#psave2")
        assert said(page, "saved") == "saved lamp v1.0"
        assert page.evaluate("__t.lib.inHand()") is None
    finally:
        page.evaluate("import('/static/js/store.js').then(S => __t.lib.useStore(S.browserStore()))")


def test_unsaved_marker_waits_for_a_technique(page):
    r = page.evaluate("""async () => { const {ST} = await import('/static/js/state.js'), P = await import('/static/js/librarypage.js'), m = ST.mode;
        ST.mode = null; try { P.refreshUnsaved(); return 'quiet' } catch (e) { return e.message } finally { ST.mode = m } }""")
    assert r == "quiet"


def test_shortcuts_are_off_while_the_library_is_open(page):
    t = page.evaluate("__t.state().thickness")
    set_fields(page, [("p_thickness", t + 1)]); settle(page)
    library(page)
    page.fill("#libfind", "x"); page.fill("#libfind", "")                     # the browser's own undo has an edit to take back
    page.evaluate("document.activeElement.blur()")                            # not in a text box: that keeps its own keys
    page.keyboard.press("Control+z"); page.keyboard.press("?")
    assert page.input_value("#libfind") == ""
    page.wait_for_timeout(300)
    assert page.evaluate("__t.state().thickness") == t + 1 and page.evaluate("__t.idle()")
    assert page.evaluate("document.querySelector('#helpdlg').open") is False


# --- examples section (Task 8) ---
def examples(page):
    """The names on the example cards that show, in their order."""
    return page.eval_on_selector_all("#libexamples .card:not([hidden])", "cs => cs.map(c => c.dataset.example)")


def test_examples_section_opens_an_example(page):
    names = page.evaluate("fetch('api/examples').then(r => r.json())")
    library(page)
    assert examples(page) == names
    page.wait_for_function("() => [...document.querySelectorAll('#libexamples img')].every(i => i.complete)")
    assert page.eval_on_selector_all("#libexamples img", "is => is.map(i => i.naturalWidth)") == [320] * len(names)
    c = page.locator('#libexamples .card[data-example="cow"]')
    assert c.locator(".n").inner_text() == "cow" and c.locator(".m").inner_text() == "example · read-only"
    on_dialog(page, lambda d: d.accept())                                         # the tab resets before a test can count as changes
    c.click()
    assert page.is_hidden("#library")
    settle(page)
    assert page.evaluate("__t.project().then(p => p.example)") == "cow"


def test_an_example_asks_before_unsaved_changes_go(page):
    set_fields(page, [("p_thickness", 4)]); settle(page)
    library(page)
    asked = []
    on_dialog(page, lambda d: (asked.append(d.message), d.dismiss()))
    page.click('#libexamples .card[data-example="cow"]')
    assert asked and "unsaved" in asked[0] and page.is_visible("#library") and page.evaluate("__t.job()") == "ex_egg"


def test_saving_an_example_makes_a_project_of_yours(page):
    example(page, "egg"); name(page, "")
    page.click("#psave2"); said(page, "saved egg")
    library(page)
    assert cards(page) == ["egg"] and "egg" in examples(page)


def test_the_dropdown_is_gone(page):
    assert page.locator("#example").count() == 0
    page.click('nav button[data-t="model"]')
    assert page.text_content("#exopen") == "egg · pick another…"              # the example in hand
    assert page.get_attribute("#libfind", "placeholder") == "find a project or example"
    name(page, "lamp"); save(page)                                             # Yours is drawn above the section
    page.click("#exopen")
    page.wait_for_function("() => !document.querySelector('#library').hidden && document.querySelector('#libyours').dataset.listed")
    page.wait_for_function("() => Math.abs(document.querySelector('#libexamples').getBoundingClientRect().top) < 2")
    page.click("#libclose")
    page.set_input_files("#file", str(ROOT / "examples" / "bracket.stl")); settle(page)
    assert page.text_content("#exopen") == "pick an example…"                  # an upload is no example


def test_find_filters_examples_too(page):
    name(page, "horse lamp"); save(page)
    library(page)
    page.fill("#libfind", "HORSE")
    assert cards(page) == ["horse lamp"]
    assert examples(page) == [n for n in page.evaluate("fetch('api/examples').then(r => r.json())") if "horse" in n]
    page.fill("#libfind", "")
    assert len(examples(page)) > 10

# --- linked folder (Task 7) ---
LIB = "(await navigator.storage.getDirectory()).getDirectoryHandle('lib', {create: true})"


def folder(page, answer="keep"):
    """Link the private folder 'lib' as the library, the way #liblink does after the picker; a clash answers `answer`."""
    page.evaluate(f"async a => {{ await __t.lib.linkFolder(await {LIB}, () => Promise.resolve(a)) }}", answer)


def drop(page, file, text):
    """A file written into the folder behind the library's back: by hand, or by another tab."""
    page.evaluate(f"""async ([f, t]) => {{ const w = await (await (await {LIB}).getFileHandle(f, {{create: true}})).createWritable();
        await w.write(t); await w.close() }}""", [file, text])


def on_disk(page):
    """Everything in the folder: {name: its text, or None for a sub-folder}."""
    return page.evaluate(f"""async () => {{ const out = {{}};
        for await (const [n, h] of (await {LIB}).entries()) out[n] = h.kind === 'file' ? await (await h.getFile()).text() : null;
        return out }}""")


def browser_files(page):
    return page.evaluate("import('/static/js/store.js').then(S => S.browserStore().list())")


def read_text(page, file):
    return page.evaluate("f => import('/static/js/store.js').then(S => S.browserStore().read(f))", file)


def project(name, rev="1.0"):
    return json.dumps({"name": name, "rev": rev, "mode": "stacked", "state": {"rev": rev}})


def test_linking_moves_the_browser_projects_into_the_folder(page):
    name(page, "lamp"); save(page); name(page, "vase"); save(page)
    texts = {f: read_text(page, f) for f in ("lamp_v1.0.lamina.json", "vase_v1.0.lamina.json")}
    drop(page, "egg_v1.0.lamina.json", project("egg"))
    folder(page)
    assert sorted(lib(page)) == [("egg", ["1.0"]), ("lamp", ["1.0"]), ("vase", ["1.0"])]
    assert browser_files(page) == []
    disk = on_disk(page)
    assert sorted(disk) == ["egg_v1.0.lamina.json", "lamp_v1.0.lamina.json", "vase_v1.0.lamina.json"]
    assert all(disk[f] == t for f, t in texts.items())                         # moved as they were
    assert page.evaluate("__t.lib.storeState()") == {"kind": "folder", "label": "lib", "state": "folder", "files": 3, "left": "",
                                                     "browser": 0}
    assert save(page) == [{"file": "vase_v1.0.lamina.json"}, []]               # the revision in hand moved with it


def test_linking_asks_on_a_clash_and_moves_unreadable_files_as_they_are(page):
    name(page, "lamp"); save(page); name(page, "lamp2"); save(page); put(page, "junk_v1.0.lamina.json", "not json")
    drop(page, "lamp_v1.0.lamina.json", project("lamp")); drop(page, "lamp2_v1.0.lamina.json", project("lamp2"))
    r, asked = page.evaluate(f"""async () => {{ const asked = [];
        const r = await __t.lib.linkFolder(await {LIB}, c => {{ asked.push(c); return Promise.resolve({{answer: 'keep', rest: true}}) }});
        return [r, asked] }}""")
    assert len(asked) == 1 and asked[0]["next"] == "1.1"                       # the answer served the second clash too
    assert sorted(r["moved"]) == ["junk_v1.0.lamina.json", "lamp2_v1.1.lamina.json", "lamp_v1.1.lamina.json"]
    disk = on_disk(page)
    assert disk["junk_v1.0.lamina.json"] == "not json" and disk["lamp_v1.0.lamina.json"] == project("lamp")
    assert json.loads(disk["lamp_v1.1.lamina.json"])["rev"] == "1.1" and browser_files(page) == []


def test_the_folder_is_the_library(page):
    folder(page)
    drop(page, "egg_v1.0.lamina.json", project("egg")); drop(page, "egg_v1.1.lamina.json", project("egg", "1.1"))
    assert lib(page) == [("egg", ["1.1", "1.0"])]
    page.evaluate("__t.lib.removeProject('egg')")
    assert lib(page) == [] and on_disk(page) == {}


def test_unchanged_files_are_not_read_again(page):
    folder(page)
    drop(page, "a_v1.0.lamina.json", project("a")); drop(page, "b_v1.0.lamina.json", project("b"))
    reads = page.evaluate(f"""async () => {{ const S = await import('/static/js/store.js'), f = S.folderStore(await {LIB});
        window.__reads = 0; __t.lib.useStore({{...f, read: x => {{ window.__reads++; return f.read(x) }}}});
        const n = []; await __t.lib.entries(); n.push(__reads); await __t.lib.entries(); n.push(__reads); return n }}""")
    assert reads == [2, 2]                                                     # the second listing read nothing
    drop(page, "a_v1.0.lamina.json", project("a-touched"))
    assert page.evaluate("__t.lib.entries().then(() => __reads)") == 3 and sorted(lib(page))[0] == ("a-touched", ["1.0"])


def test_delete_lists_the_library_once(page):
    name(page, "lamp"); save(page); bump(page); settle(page); save(page)
    n = page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore(); let n = 0;
        __t.lib.useStore({...b, list: () => { n++; return b.list() }});
        try { await __t.lib.removeProject('lamp'); return n } finally { __t.lib.useStore(b) } }""")
    assert n == 1 and lib(page) == []


def test_other_things_in_the_folder(page):
    folder(page)
    drop(page, "notes.json", "{}"); drop(page, "x_v1.0.lamina.json", '{"name":"x","mo')
    page.evaluate(f"async () => {{ await (await {LIB}).getDirectoryHandle('sub.lamina.json', {{create: true}}) }}")
    (p,) = page.evaluate("__t.lib.entries()")
    assert p["name"] == "x_v1.0.lamina.json" and [r["bad"] for r in p["revs"]] == [True]
    err = page.evaluate("__t.lib.removeProject('x_v1.0.lamina.json').then(() => null, e => e.message)")
    assert err and "cannot be read" in err
    assert on_disk(page) == {"notes.json": "{}", "x_v1.0.lamina.json": '{"name":"x","mo', "sub.lamina.json": None}
    library(page)                                                              # the page opens, with one card
    assert cards(page) == ["x_v1.0.lamina.json"] and "cannot be read" in card(page, "x_v1.0.lamina.json").inner_text()


def test_a_file_changed_on_disk_asks_before_save(page):
    folder(page); name(page, "lamp")
    assert save(page) == [{"file": "lamp_v1.0.lamina.json"}, []]
    assert save(page)[1] == []                                                 # unchanged since this tab saved it
    by_hand = on_disk(page)["lamp_v1.0.lamina.json"] + " "
    drop(page, "lamp_v1.0.lamina.json", by_hand)
    assert save(page) == [None, [{"name": "lamp", "rev": "1.0", "next": "1.1"}]]
    assert on_disk(page)["lamp_v1.0.lamina.json"] == by_hand


def test_no_fallback_when_the_folder_cannot_be_reached(page):
    folder(page); name(page, "lamp")
    r = page.evaluate("""async () => { const P = FileSystemDirectoryHandle.prototype, keep = {}, out = {};
        for (const k of ['queryPermission', 'requestPermission']) keep[k] = Object.getOwnPropertyDescriptor(P, k);
        P.queryPermission = async () => 'prompt'; P.requestPermission = async () => 'denied';
        try { out.restored = await __t.lib.restoreStore();
            out.err = await __t.lib.saveCurrent(() => Promise.resolve('replace')).then(() => null, e => e.message);
            out.reconnected = await __t.lib.reconnect(); out.state = __t.lib.storeState() }
        finally { for (const k in keep) keep[k] ? Object.defineProperty(P, k, keep[k]) : delete P[k] }
        return out }""")
    assert r["restored"] == "needs-permission" and r["reconnected"] is False
    assert r["err"] and "Reconnect" in r["err"] and "export" in r["err"]
    assert (r["state"]["kind"], r["state"]["label"], r["state"]["state"]) == ("folder", "lib", "needs-permission")
    assert browser_files(page) == [] and on_disk(page) == {}
    page.evaluate("import('/static/js/librarypage.js').then(P => P.showLibrary())")   # not #popen: that reconnects
    text, buttons = where(page)
    assert "cannot be reached" in text and "libreconnect" in buttons
    assert page.evaluate("__t.lib.reconnect()") is True and page.evaluate("__t.lib.storeState().state") == "folder"
    assert save(page)[0] == {"file": "lamp_v1.0.lamina.json"}


def test_unlink_leaves_the_files(page):
    name(page, "lamp"); save(page); folder(page)
    page.evaluate("__t.lib.unlink()")
    assert lib(page) == [] and sorted(on_disk(page)) == ["lamp_v1.0.lamina.json"]
    assert page.evaluate("__t.lib.storeState()") == {"kind": "browser", "label": "this browser", "state": "browser",
                                                     "files": 0, "left": "lib", "browser": 0}
    assert page.evaluate("import('/static/js/store.js').then(S => S.kvGet('folder'))") is None
    library(page)
    assert "Your files stayed in lib." in where(page)[0]


def test_link_state_survives_reload(page):
    name(page, "lamp"); save(page); folder(page)
    before = page.evaluate("__t.lib.entries()")
    page.reload(); settle(page)
    assert page.evaluate("__t.lib.entries()") == before                        # it waits for start-up to pick the store
    assert page.evaluate("__t.lib.storeState()")["kind"] == "folder" and page.evaluate("__t.lib.storeState().state") == "folder"


def test_a_save_writes_the_settings_it_started_with(page):
    """A change made while the model is read for a save belongs to the next save, not half to this one."""
    name(page, "lamp"); t = page.evaluate("__t.state().thickness")
    page.evaluate("async () => { const p = __t.lib.saveCurrent(() => Promise.resolve(null)); __t.state().thickness += 1; await p }")
    assert read(page, "lamp_v1.0.lamina.json")["state"]["thickness"] == t
    assert page.evaluate("__t.lib.unsaved()") is True


def test_a_failed_listing_is_tried_again(page):
    name(page, "lamp"); save(page)
    r = page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore(); let n = 0;
        __t.lib.useStore({...b, list: () => n++ ? b.list() : Promise.reject(new Error('busy'))});
        try { return [(await __t.lib.listed()).length, (await __t.lib.listed()).length] } finally { __t.lib.useStore(b) } }""")
    assert r == [0, 1]


# --- linked folder, review round 1 ---
def link(page, answers=()):
    """linkFolder with `ask` giving `answers` in turn (then None): [its result, the clashes it was asked about]."""
    return page.evaluate(f"""async a => {{ const asked = [];
        const r = await __t.lib.linkFolder(await {LIB}, c => {{ asked.push(c); return Promise.resolve(a[asked.length - 1] ?? null) }});
        return [r, asked] }}""", list(answers))


def test_a_save_during_a_link_is_not_lost(page):
    """The save is pressed in the middle of the link (while it asks about a clash): lamp has moved, vase not yet."""
    name(page, "vase"); save(page); name(page, "lamp"); save(page)
    set_fields(page, [("p_thickness", 4)]); settle(page)
    drop(page, "vase_v1.0.lamina.json", project("vase"))
    unsaved = page.evaluate(f"""async () => {{ const d = await {LIB}; let s;
        await __t.lib.linkFolder(d, () => {{ s = __t.lib.saveCurrent(() => Promise.resolve('replace')); return Promise.resolve('replace') }});
        await s; return __t.lib.unsaved() }}""")
    disk = on_disk(page)
    # the save ran after the link, into the folder: the new setting is in the file, and nothing is left unsaved
    assert json.loads(disk["lamp_v1.0.lamina.json"])["state"]["thickness"] == 4 and unsaved is False
    assert browser_files(page) == []


def test_two_links_at_once_give_one_result(page):
    name(page, "lamp"); save(page); name(page, "vase"); save(page)
    a, b = page.evaluate(f"""async () => {{ const d = await {LIB}, ask = () => Promise.resolve(null);
        return await Promise.all([__t.lib.linkFolder(d, ask), __t.lib.linkFolder(d, ask)]) }}""")
    assert a == b and sorted(a["moved"]) == ["lamp_v1.0.lamina.json", "vase_v1.0.lamina.json"]
    assert sorted(on_disk(page)) == ["lamp_v1.0.lamina.json", "vase_v1.0.lamina.json"] and browser_files(page) == []


def test_a_revision_another_tab_saved_asks_after_the_link(page):
    name(page, "lamp"); save(page)
    other = read(page, "lamp_v1.0.lamina.json"); other["state"]["thickness"] = 9
    put(page, "lamp_v1.0.lamina.json", json.dumps(other))                      # another tab saved it since
    folder(page)
    assert save(page)[1] == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]
    assert json.loads(on_disk(page)["lamp_v1.0.lamina.json"])["state"]["thickness"] == 9


def test_keep_skips_the_revisions_still_in_the_browser(page):
    name(page, "lamp"); save(page)
    x = read_text(page, "lamp_v1.0.lamina.json"); y = project("lamp", "1.1"); z = project("lamp") + " "
    put(page, "lamp_v1.1.lamina.json", y); drop(page, "lamp_v1.0.lamina.json", z)
    link(page, ["keep", "replace"])
    disk = on_disk(page)
    assert disk["lamp_v1.0.lamina.json"] == z and disk["lamp_v1.1.lamina.json"] == y
    assert {k: v for k, v in json.loads(disk["lamp_v1.2.lamina.json"]).items() if k not in ("rev", "state")} == \
        {k: v for k, v in json.loads(x).items() if k not in ("rev", "state")}


def test_a_link_that_fails_half_way_loses_nothing(page):
    name(page, "a"); save(page); name(page, "b"); save(page)
    err = page.evaluate(f"""async () => {{ const d = await {LIB}, P = FileSystemWritableFileStream.prototype, w = P.write; let n = 0;
        P.write = function (...x) {{ return n++ ? Promise.reject(new DOMException('full', 'QuotaExceededError')) : w.apply(this, x) }};
        try {{ return await __t.lib.linkFolder(d, () => Promise.resolve(null)).then(() => null, e => e.message) }} finally {{ P.write = w }} }}""")
    assert err and "stopped" in err and "still in this browser" in err and "lib" in err
    places = sorted([f["file"] for f in browser_files(page)] + list(on_disk(page)))
    assert places == ["a_v1.0.lamina.json", "b_v1.0.lamina.json"]
    assert page.evaluate("__t.lib.storeState().kind") == "browser"
    assert page.evaluate("import('/static/js/store.js').then(S => S.kvGet('folder'))") is None


def test_keep_replace_and_skip_never_lose_a_file(page):
    """keep on an unreadable browser file moves its bytes; replace onto an unreadable folder file keeps both; a skip
    leaves the revision in the browser and says so."""
    put(page, "junk_v1.0.lamina.json", "not json"); drop(page, "junk_v1.0.lamina.json", "other")
    name(page, "lamp"); save(page); drop(page, "lamp_v1.0.lamina.json", "broken")
    name(page, "vase"); save(page); drop(page, "vase_v1.0.lamina.json", project("vase"))
    r, asked = link(page, ["keep", "replace", None])
    assert [c["name"] for c in asked] == ["junk_v1.0.lamina.json", "lamp", "vase"]
    disk = on_disk(page)
    assert disk["junk_v1.0.lamina.json"] == "other" and disk["junk_v1.1.lamina.json"] == "not json"
    assert disk["lamp_v1.0.lamina.json"] == "broken" and json.loads(disk["lamp_v1.1.lamina.json"])["rev"] == "1.1"
    assert disk["vase_v1.0.lamina.json"] == project("vase")
    assert r["skipped"] == ["vase_v1.0.lamina.json"] and [f["file"] for f in browser_files(page)] == ["vase_v1.0.lamina.json"]


def test_a_file_name_without_a_revision_keeps_its_name(page):
    put(page, "foo.lamina.json", project("foo")); drop(page, "foo.lamina.json", project("foo") + " ")
    r, _ = link(page, ["keep"])
    assert r["moved"] == ["foo_v1.1.lamina.json"] and sorted(on_disk(page)) == ["foo.lamina.json", "foo_v1.1.lamina.json"]


def test_the_index_belongs_to_its_folder(page):
    """An index made for another folder is not trusted, even for a file of the same name, size and time."""
    folder(page); drop(page, "x_v1.0.lamina.json", project("x"))
    r = page.evaluate(f"""async () => {{ const S = await import('/static/js/store.js'), d = await {LIB};
        const d2 = await (await navigator.storage.getDirectory()).getDirectoryHandle('lib2', {{create: true}});
        const f = (await S.folderStore(d).list())[0], forged = [{{...f, name: 'forged', rev: '1.0', saved: new Date(f.mtime).toISOString(), preview: ''}}];
        await S.idxSet('folder', {{dir: d2, entries: forged}}); const a = (await __t.lib.entries())[0].name;
        await S.idxSet('folder', {{dir: d, entries: forged}}); const b = (await __t.lib.entries())[0].name; return [a, b] }}""")
    assert r == ["x", "forged"]


def test_a_listing_overtaken_by_another_store_changes_nothing(page):
    name(page, "lamp"); save(page)
    r = page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore();
        __t.lib.useStore({...b, list: () => new Promise(ok => setTimeout(() => ok(b.list()), 200))});
        const p = __t.lib.entries(); await new Promise(ok => setTimeout(ok, 50));
        __t.lib.useStore({...b, list: async () => []}); await p; const files = __t.lib.storeState().files;
        __t.lib.useStore(b); return files }""")
    assert r == 0


def test_reconnect_needs_the_folder_to_be_there(page):
    folder(page)
    r = page.evaluate("""async () => { await (await navigator.storage.getDirectory()).removeEntry('lib', {recursive: true});
        return [await __t.lib.restoreStore(), await __t.lib.reconnect()] }""")
    assert r == ["needs-permission", False]


def test_the_library_waits_for_start_up_to_pick_the_store(page):
    name(page, "lamp"); save(page); drop(page, "egg_v1.0.lamina.json", project("egg"))
    names = page.evaluate(f"""async () => {{ const S = await import('/static/js/store.js'); await S.kvSet('folder', await {LIB});
        const r = __t.lib.restoreStore(), e = await __t.lib.entries(); await r; return e.map(p => p.name) }}""")
    assert names == ["egg"]


def test_a_change_of_size_at_the_same_time_asks(page):
    """A copy written in the same millisecond still asks: size and mtime are compared."""
    name(page, "lamp"); save(page)
    page.evaluate("""() => new Promise((ok, no) => { const q = indexedDB.open('lamina_library'); q.onerror = () => no(q.error);
        q.onsuccess = () => { const t = q.result.transaction('revisions', 'readwrite'), s = t.objectStore('revisions');
            s.get('lamp_v1.0.lamina.json').onsuccess = e => { const r = e.target.result; s.put({...r, text: r.text + ' ', size: r.size + 1}) };
            t.oncomplete = () => { q.result.close(); ok() } } })""")
    assert save(page)[1] == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]


def test_permission_lost_in_a_session_says_reconnect(page):
    folder(page)
    r = page.evaluate("""async () => { const P = FileSystemDirectoryHandle.prototype, e = P.entries;
        P.entries = function () { throw new DOMException('no', 'NotAllowedError') };
        try { return [await __t.lib.entries().then(() => null, x => x.message), __t.lib.storeState().state] } finally { P.entries = e } }""")
    assert "Reconnect" in r[0] and r[1] == "needs-permission"
    assert page.evaluate("__t.lib.reconnect()") is True and page.evaluate("__t.lib.storeState().state") == "folder"


def test_folder_write_never_deletes_a_file_it_could_not_check(page):
    r = page.evaluate(f"""async () => {{ const s = await ({FRESH})('folder'), P = FileSystemDirectoryHandle.prototype, g = P.getFileHandle;
        const W = FileSystemWritableFileStream.prototype, w = W.write; await s.write('x_v1.0.lamina.json', 'old'); let once = true;
        P.getFileHandle = function (n, o) {{ if (!o && once) {{ once = false; return Promise.reject(new DOMException('busy', 'InvalidStateError')) }} return g.call(this, n, o) }};
        W.write = () => Promise.reject(new Error('disk full'));
        try {{ await s.write('x_v1.0.lamina.json', 'new').catch(() => {{}}) }} finally {{ P.getFileHandle = g; W.write = w }}
        return await s.read('x_v1.0.lamina.json').catch(e => e.name) }}""")
    assert r == "old"


# --- linked folder, review round 2 ---
def test_reconnect_asks_at_once_while_a_save_waits(page):
    """The browser's prompt needs the click it came from: reconnect asks before the queue, not after a waiting save."""
    folder(page); name(page, "lamp"); save(page); page.evaluate("__t.lib.setSaved(null)")   # the next save asks
    calls = page.evaluate("""async () => { const P = FileSystemDirectoryHandle.prototype, keep = Object.getOwnPropertyDescriptor(P, 'requestPermission'), calls = [];
        P.requestPermission = async () => { calls.push('request'); return 'granted' };
        try { let answer; await new Promise(ok => { window.__s = __t.lib.saveCurrent(() => { ok(); return new Promise(r => answer = r) }) });
            const r = __t.lib.reconnect(); calls.push('before the answer'); answer(null); await window.__s; calls.push(String(await r)); return calls }
        finally { keep ? Object.defineProperty(P, 'requestPermission', keep) : delete P.requestPermission } }""")
    assert calls == ["request", "before the answer", "true"]


def test_the_preview_is_the_scene_at_the_press(page):
    """A save that waits in the queue (here behind a link's question) keeps the picture of when it was pressed."""
    name(page, "lamp"); save(page); drop(page, "lamp_v1.0.lamina.json", project("lamp")); name(page, "pot")
    page.evaluate(f"""async () => {{ const d = await {LIB}; window.__pre = __t.snapshot();
        await new Promise(ok => {{ window.__l = __t.lib.linkFolder(d, () => {{ ok(); return new Promise(r => window.__answer = r) }}) }});
        window.__s = __t.lib.saveCurrent(() => Promise.resolve(null)) }}""")
    example(page, "vase")
    pre = page.evaluate("async () => { window.__answer(null); await window.__l; await window.__s; return window.__pre }")
    assert json.loads(on_disk(page)["pot_v1.0.lamina.json"])["preview"] == pre and page.evaluate("__t.snapshot()") != pre


def test_the_revision_in_hand_follows_only_as_it_was_read(page):
    """Another tab saves lamp while the link is busy with another file: the newer bytes move, and the next save asks."""
    name(page, "lamp"); save(page)
    put(page, "a_v1.0.lamina.json", project("a")); drop(page, "a_v1.0.lamina.json", project("a"))
    newer = read(page, "lamp_v1.0.lamina.json"); newer["state"]["thickness"] = 9
    page.evaluate(f"""async t => {{ const S = await import('/static/js/store.js'), d = await {LIB};
        await __t.lib.linkFolder(d, () => S.browserStore().write('lamp_v1.0.lamina.json', t).then(() => 'keep')) }}""", json.dumps(newer))
    assert json.loads(on_disk(page)["lamp_v1.0.lamina.json"])["state"]["thickness"] == 9
    assert save(page)[1] == [{"name": "lamp", "rev": "1.0", "next": "1.1"}]


def test_a_save_that_cannot_be_copied_rejects(page):
    name(page, "lamp")
    r = page.evaluate("""() => { const s = __t.state(); s.unclonable = () => {};
        try { return __t.lib.saveCurrent(() => Promise.resolve(null)).then(() => 'saved', e => 'rejected ' + e.name) }
        catch (e) { return 'threw ' + e.name } finally { delete s.unclonable } }""")
    assert r == "rejected DataCloneError"


# --- linked folder, review round 3 ---
def test_a_revision_saved_by_another_tab_during_the_link_stays(page):
    """Another tab saves lamp while the link asks about it: the newer record is not deleted with the one that moved."""
    name(page, "lamp"); save(page); drop(page, "lamp_v1.0.lamina.json", project("lamp"))
    old = read_text(page, "lamp_v1.0.lamina.json")
    newer = json.loads(old); newer["state"]["thickness"] = 9
    r = page.evaluate(f"""async t => {{ const S = await import('/static/js/store.js'), d = await {LIB};
        return await __t.lib.linkFolder(d, () => S.browserStore().write('lamp_v1.0.lamina.json', t).then(() => 'keep')) }}""",
        json.dumps(newer))
    assert r["skipped"] == ["lamp_v1.0.lamina.json"] and r["changed"] == ["lamp_v1.0.lamina.json"]
    assert json.loads(read_text(page, "lamp_v1.0.lamina.json"))["state"]["thickness"] == 9   # still in the browser
    disk = on_disk(page)
    kept = json.loads(old); kept["rev"] = kept["state"]["rev"] = "1.1"                  # the copy read before: kept beside
    assert disk["lamp_v1.0.lamina.json"] == project("lamp") and json.loads(disk["lamp_v1.1.lamina.json"]) == kept


def test_a_call_before_start_up_waits_for_the_kept_folder(page):
    """A call made before main.js has run restoreStore() (main.js is held back for a moment, so the library module is
    loaded and called first) waits for it, and lists the folder, not the browser."""
    name(page, "lamp"); save(page); folder(page); put(page, "b_v1.0.lamina.json", project("b"))   # b only in the browser
    page.add_init_script("""if (sessionStorage.__early === '1') { sessionStorage.__early = '';
        window.__early = import('/static/js/library.js').then(L => L.entries()).then(e => e.map(p => p.name)) }""")
    held = lambda route: (time.sleep(1.5), route.continue_())
    page.route("**/static/js/main.js", held)
    try:
        page.evaluate("sessionStorage.__early = '1'"); page.reload(); settle(page)
    finally:
        page.unroute("**/static/js/main.js", held)
    assert page.evaluate("window.__early") == ["lamp"]


# --- export and import (Task 6) ---
def import_files(page, files, answers=()):
    """importFiles() of Files made of `files` [(name, text or bytes, lastModified or None)], `ask` giving `answers` in
    turn (then None): [its result, the clashes it was asked about]."""
    fs = [[n, base64.b64encode(b if isinstance(b, bytes) else b.encode()).decode(), t] for n, b, t in files]
    return page.evaluate("""async ([fs, a]) => { const asked = [];
        const files = fs.map(([n, b, t]) => new File([Uint8Array.from(atob(b), c => c.charCodeAt(0))], n, t ? {lastModified: t} : {}));
        const r = await __t.lib.importFiles(files, c => { asked.push(c); return Promise.resolve(a[asked.length - 1] ?? null) });
        return [r, asked] }""", [fs, list(answers)])


def zipped(*entries):
    """A zip made by Python: (name, text) entries are stored, (name, text, method) ones as `method` says."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t, *m in entries:
            z.writestr(n, t, m[0] if m else zipfile.ZIP_STORED)
    return buf.getvalue()


def test_export_all_then_import_into_an_empty_library(page):
    name(page, "lamp"); save(page); name(page, "vase"); save(page)
    lamp = read(page, "lamp_v1.0.lamina.json"); lamp["rev"] = "1.1"
    put(page, "lamp_v1.1.lamina.json", json.dumps(lamp))
    before = page.evaluate("__t.lib.entries()")
    b64, skipped = page.evaluate("""async () => { const r = await __t.lib.exportAll(); window.__zip = r.blob;
        const u = new Uint8Array(await r.blob.arrayBuffer()); let s = ''; for (const x of u) s += String.fromCharCode(x);
        return [btoa(s), r.skipped] }""")
    z = zipfile.ZipFile(io.BytesIO(base64.b64decode(b64)))
    assert sorted(z.namelist()) == ["lamp_v1.0.lamina.json", "lamp_v1.1.lamina.json", "vase_v1.0.lamina.json"] and skipped == []
    assert z.read("vase_v1.0.lamina.json").decode() == read_text(page, "vase_v1.0.lamina.json")
    wipe(page)
    assert lib(page) == []
    r = page.evaluate("__t.lib.importFiles([new File([window.__zip], 'lamina-library.zip')], () => Promise.resolve(null))")
    assert sorted(r["imported"]) == sorted(z.namelist()) and r["bad"] == []
    assert all(read_text(page, f) == z.read(f).decode() for f in z.namelist())   # their dates were in them: written as they were
    strip = lambda ps: [{**p, "revs": [{k: v for k, v in rv.items() if k not in ("size", "mtime")} for rv in p["revs"]]} for p in ps]
    assert strip(page.evaluate("__t.lib.entries()")) == strip(before)          # names, revisions, dates and pictures


def test_import_clash_replace_keep_and_rest(page):
    put(page, "lamp_v1.0.lamina.json", project("lamp")); put(page, "lamp_v1.1.lamina.json", project("lamp", "1.1"))
    other = lambda rev: json.dumps({"name": "lamp", "rev": rev, "mode": "stacked", "state": {"rev": rev, "thickness": 9}})
    # keep, for the rest: 1.0 takes 1.3 (1.1 is the library's, 1.2 still to come), 1.1 takes 1.4, 1.2 lands as it is
    r, asked = import_files(page, [(f"lamp_v{v}.lamina.json", other(v), None) for v in ("1.0", "1.1", "1.2")],
                            [{"answer": "keep", "rest": True}])
    assert asked == [{"name": "lamp", "rev": "1.0", "next": "1.3"}]
    assert r == {"imported": ["lamp_v1.3.lamina.json", "lamp_v1.4.lamina.json", "lamp_v1.2.lamina.json"], "bad": [], "skipped": [],
                 "kept": []}
    assert lib(page) == [("lamp", ["1.4", "1.3", "1.2", "1.1", "1.0"])]
    assert read(page, "lamp_v1.0.lamina.json") == json.loads(project("lamp"))   # nothing written over
    assert read(page, "lamp_v1.3.lamina.json")["rev"] == read(page, "lamp_v1.3.lamina.json")["state"]["rev"] == "1.3"
    # replace writes over; a skip leaves the library as it was
    r, asked = import_files(page, [("a.lamina.json", other("1.0"), None), ("b.lamina.json", other("1.1"), None)], ["replace", None])
    assert len(asked) == 2 and r["imported"] == ["lamp_v1.0.lamina.json"] and r["skipped"] == ["lamp v1.1"]
    assert read(page, "lamp_v1.0.lamina.json")["state"]["thickness"] == 9
    assert read(page, "lamp_v1.1.lamina.json") == json.loads(project("lamp", "1.1"))
    # replace onto a file that cannot be read keeps both
    put(page, "lamp_v1.5.lamina.json", "not json")
    r, asked = import_files(page, [("c.lamina.json", other("1.5"), None)], ["replace"])
    assert asked == [{"name": "lamp", "rev": "1.5", "next": "1.6"}] and r["imported"] == ["lamp_v1.6.lamina.json"]
    assert r["kept"] == [{"rev": "lamp v1.5", "as": "1.6", "why": "unreadable"}]
    assert read(page, "lamp_v1.5.lamina.json") == "not json"


def test_import_reports_bad_files(page):
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    before = page.evaluate("__t.lib.entries()")
    z = zipped(("egg_v1.0.lamina.json", project("egg")), ("pear_v1.0.lamina.json", project("pear") * 20, zipfile.ZIP_DEFLATED))
    t = 1_700_000_000_000                                                      # the File's own date
    r, asked = import_files(page, [("x.lamina.json", "{", None), ("more.zip", z, t), ("junk.zip", b"PK nothing", None)])
    assert asked == [] and r == {"imported": ["egg_v1.0.lamina.json"], "bad": ["x.lamina.json", "pear_v1.0.lamina.json", "junk.zip"],
                                    "skipped": [], "kept": []}
    after = page.evaluate("__t.lib.entries()")
    egg = next(p for p in after if p["name"] == "egg")["revs"][0]
    assert egg["saved"] == "2023-11-14T22:13:20.000Z" and egg["preview"] == ""  # no date inside: the File's; no picture: none
    assert [p for p in after if p["name"] != "egg"] == before


def test_export_buttons_download(page):
    name(page, "lamp"); save(page)
    library(page)
    card(page, "lamp").locator(".more").click()
    page.wait_for_selector("#libyours .rev")
    with page.expect_download() as d:
        card(page, "lamp").locator(".export").click()
    assert d.value.suggested_filename == "lamp_v1.0.lamina.json"
    with open(d.value.path(), encoding="utf-8") as f:
        assert f.read() == read_text(page, "lamp_v1.0.lamina.json")
    with page.expect_download() as d:
        card(page, "lamp").locator(".exportproject").click()
    assert d.value.suggested_filename == "lamp.lamina.zip"
    assert zipfile.ZipFile(d.value.path()).namelist() == ["lamp_v1.0.lamina.json"]
    with page.expect_download() as d:
        page.click("#libexportall")
    assert d.value.suggested_filename == "lamina-library.zip"


def test_drop_files_on_the_library(page):
    library(page)
    prevented = page.evaluate("""t => { const dt = new DataTransfer(); dt.items.add(new File([t], 'egg_v1.0.lamina.json'));
        const e = new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true});
        document.querySelector('#libyours').dispatchEvent(e); return e.defaultPrevented }""", project("egg"))
    assert prevented                                                            # the browser does not open the file
    page.wait_for_selector('#libyours .card[data-name="egg"]')
    assert note(page) == "imported 1 file"
    with page.expect_file_chooser() as fc:
        page.click("#libimport")
    assert fc.value.is_multiple()
    fc.value.set_files([{"name": "pear_v1.0.lamina.json", "mimeType": "application/json", "buffer": project("pear").encode()},
                        {"name": "x.lamina.json", "mimeType": "application/json", "buffer": b"{"}])
    page.wait_for_selector('#libyours .card[data-name="pear"]')
    assert note(page) == "⚠ imported 1 file. Not imported, as they cannot be read: x.lamina.json"


# --- the folder line (Task 7, the page) ---
def note(page, busy=False):
    """The message the library page shows in its folder line: what the person sees (the status line is under the page).
    The result of an action, not its "importing…" or "linking…" (unless `busy`)."""
    page.locator("#libwhere .note").wait_for(state="visible")
    if not busy:
        page.wait_for_function("() => !document.querySelector('#libwhere .note').innerText.endsWith('…')")
    return page.inner_text("#libwhere .note")


def where(page):
    """The folder line's text, and the ids of its buttons that can be pressed."""
    return page.evaluate("""() => [document.querySelector('#libwhere').innerText,
        [...document.querySelectorAll('#libwhere button:not(:disabled)')].map(b => b.id)]""")


def picker(page):
    """showDirectoryPicker answers the private folder 'lib' (a test cannot reach the real one); put back by reload."""
    page.evaluate(f"""async () => {{ const d = await {LIB}; window.__picked = [];
        window.showDirectoryPicker = async o => {{ window.__picked.push(o); return d }} }}""")


def test_link_button_follows_the_browser(page):
    name(page, "lamp"); save(page)
    picker(page); library(page)
    text, buttons = where(page)
    assert text.startswith("💾 kept in this browser only.") and buttons == ["liblink"]
    page.click("#liblink")
    page.wait_for_function("() => /kept in the folder lib · 1 file/.test(document.querySelector('#libwhere').innerText)")
    assert page.evaluate("window.__picked") == [{"mode": "readwrite"}]
    text, buttons = where(page)
    assert text.startswith("📁 kept in the folder lib · 1 file") and buttons == ["libchange", "libunlink"]
    assert note(page) == "Linked lib: 1 revision moved into it."
    page.click("#libunlink")
    page.wait_for_function("() => /Your files stayed in lib\\./.test(document.querySelector('#libwhere').innerText)")
    assert where(page)[1] == ["liblink"]
    page.evaluate("delete window.showDirectoryPicker; delete Window.prototype.showDirectoryPicker")
    page.click("#libclose"); library(page)
    assert page.get_attribute("#liblink", "disabled") is not None and page.get_attribute("#liblink", "title") == "needs Chrome or Edge"
    assert page.inner_text("#liblink") == "link a folder (needs Chrome or Edge)"
    page.reload(); settle(page)                                                # the browser's own picker back for the next tests


def test_link_from_the_page_names_what_stayed_in_the_browser(page):
    name(page, "lamp"); save(page); name(page, "a<b"); save(page); drop(page, "a_b_v1.0.lamina.json", project("a<b"))
    picker(page); library(page)
    page.click("#liblink")
    page.wait_for_selector("#libask[open]")
    page.click("#libask_cancel")                                               # a<b stays in the browser
    text = note(page)
    assert text.startswith("⚠ Linked lib, not all moved: 1 revision moved into it. a_b v1.0 stayed in this browser, safe:")
    assert "already had that revision" in text and "keep both" in text and "unlink" in text and "export" in text


def test_the_folder_line_when_it_cannot_be_reached(page):
    folder(page); library(page)
    page.evaluate("""() => { const P = FileSystemDirectoryHandle.prototype; window.__perm = {};
        for (const k of ['queryPermission', 'requestPermission']) window.__perm[k] = Object.getOwnPropertyDescriptor(P, k);
        window.__answer = 'denied'; P.queryPermission = async () => 'prompt'; P.requestPermission = async () => window.__answer }""")
    try:
        page.evaluate("__t.lib.restoreStore()")
        page.click("#libclose"); page.click("#popen")                         # the library button asks, and is refused
        page.wait_for_function("() => /Reconnect it/.test(document.querySelector('#libyours').innerText)")
        text, buttons = where(page)
        assert text.startswith("⚠ The linked folder lib cannot be reached.") and buttons == ["libreconnect", "libchange", "libunlink"]
        assert page.inner_text("#libyours") == "Your projects are in lib. Reconnect it to see them here."
        page.evaluate("document.querySelector('#libwhere .note')?.remove()")
        page.click("#libreconnect")
        assert note(page).startswith("⚠ Not reconnected: the linked folder lib cannot be reached")
        page.evaluate("window.__answer = 'granted'")
        page.click("#libreconnect")
        page.wait_for_function("() => /kept in the folder lib/.test(document.querySelector('#libwhere').innerText)")
        assert page.evaluate("__t.lib.storeState().state") == "folder"
    finally:
        page.evaluate("""() => { const P = FileSystemDirectoryHandle.prototype;
            for (const k in window.__perm) window.__perm[k] ? Object.defineProperty(P, k, window.__perm[k]) : delete P[k] }""")


def test_the_folder_buttons_wait_for_a_save(page):
    name(page, "lamp"); save(page); page.evaluate("__t.lib.setSaved(null)")    # the next save asks
    library(page)
    page.evaluate("document.querySelector('#psave2').click()")
    page.wait_for_selector("#libask[open]")
    assert where(page)[1] == [] and page.get_attribute("#liblink", "disabled") is not None
    page.evaluate("document.querySelector('#psave2').click()")                 # a second press while the first one asks
    assert page.text_content("#status").startswith("Not saved: another save is under way.")
    page.click("#libask_cancel")
    page.wait_for_function("() => !document.querySelector('#liblink').disabled")
    assert not page.text_content("#status").startswith("saved") and page.is_visible("#punsaved")


# --- export and import, review round 1 ---
def test_odd_fields_cannot_lock_the_library(page):
    """A number as `saved`, `name` or `rev`, imported or put in by hand, is listed as text: the listing, the page and
    export all go on working."""
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    r, _ = import_files(page, [("x.lamina.json", json.dumps({"name": "x", "mode": "stacked", "saved": 123}), 1_700_000_000_000),
                               ("y.lamina.json", json.dumps({"name": 42, "rev": 2, "mode": "stacked", "saved": True}), None)])
    assert r["imported"] == ["x_v1.0.lamina.json", "42_v2.lamina.json"]
    put(page, "z_v1.0.lamina.json", json.dumps({"name": {"a": 1}, "rev": [1], "mode": "stacked", "saved": {}, "preview": 7}))
    ps = page.evaluate("__t.lib.entries()")
    assert sorted(p["name"] for p in ps) == ["42", "[object Object]", "lamp", "x"]
    assert all(isinstance(v, str) for p in ps for r in p["revs"] for v in (r["rev"], r["saved"], r["preview"]))
    assert next(p for p in ps if p["name"] == "x")["revs"][0]["saved"] == "2023-11-14T22:13:20.000Z"
    assert len(page.evaluate("__t.lib.exportAll().then(r => r.skipped)")) == 0
    library(page)
    assert sorted(cards(page)) == ["42", "[object Object]", "lamp", "x"]


def test_an_index_with_odd_fields_is_not_trusted(page):
    """An index written before this fix can hold a number as `saved`: it is read again, not sorted as it is."""
    put(page, "a_v1.0.lamina.json", project("a")); put(page, "b_v1.0.lamina.json", project("b")); lib(page)
    page.evaluate("""async () => { const S = await import('/static/js/store.js');
        await S.idxSet('browser', (await S.idxGet('browser')).map(e => ({...e, saved: 123}))); __t.lib.useStore(S.browserStore()) }""")
    assert sorted(lib(page)) == [("a", ["1.0"]), ("b", ["1.0"])]


def test_import_lists_the_library_before_each_file(page):
    """Another tab saves lamp v1.0 while the import writes the file before it: the import asks, and leaves it."""
    other = json.dumps({"name": "lamp", "rev": "1.0", "mode": "stacked", "state": {"thickness": 9}})
    page.evaluate("""async t => { const S = await import('/static/js/store.js'), b = S.browserStore();
        __t.lib.useStore({...b, write: async (f, x) => { const w = await b.write(f, x);
            if (f === 'a_v1.0.lamina.json') await b.write('lamp_v1.0.lamina.json', t); return w }}) }""", other)
    try:
        r, asked = import_files(page, [("a.lamina.json", project("a"), None), ("lamp.lamina.json", project("lamp"), None)])
    finally:
        page.evaluate("import('/static/js/store.js').then(S => __t.lib.useStore(S.browserStore()))")
    assert asked == [{"name": "lamp", "rev": "1.0", "next": "1.1"}] and r["skipped"] == ["lamp v1.0"]
    assert read_text(page, "lamp_v1.0.lamina.json") == other


def test_two_files_of_one_revision_in_one_import_keep_both(page):
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    a = json.dumps({"name": "lamp", "rev": "1.0", "mode": "stacked", "state": {"rev": "1.0", "n": "a"}})
    b = json.dumps({"name": "lamp", "rev": "1.0", "mode": "stacked", "state": {"rev": "1.0", "n": "b"}})
    r, asked = import_files(page, [("a.lamina.json", a, None), ("b.lamina.json", b, None)], [{"answer": "replace", "rest": True}])
    assert len(asked) == 1 and r["imported"] == ["lamp_v1.0.lamina.json", "lamp_v1.1.lamina.json"]
    assert read(page, "lamp_v1.0.lamina.json")["state"]["n"] == "a" and read(page, "lamp_v1.1.lamina.json")["state"]["n"] == "b"


def test_zip_entry_paths_land_under_the_projects_name(page):
    z = zipped(("../x.lamina.json", project("x")), ("a/b.lamina.json", project("b")))
    r, _ = import_files(page, [("paths.zip", z, None)])
    assert r["imported"] == ["x_v1.0.lamina.json", "b_v1.0.lamina.json"]
    assert sorted(f["file"] for f in browser_files(page)) == ["b_v1.0.lamina.json", "x_v1.0.lamina.json"]


def test_export_all_names_a_file_it_cannot_read(page):
    put(page, "a_v1.0.lamina.json", project("a")); put(page, "b_v1.0.lamina.json", project("b"))
    page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore();
        __t.lib.useStore({...b, read: f => f === 'b_v1.0.lamina.json' ? Promise.reject(new Error('gone')) : b.read(f)}) }""")
    try:
        library(page)
        with page.expect_download() as d:
            page.click("#libexportall")
        assert zipfile.ZipFile(d.value.path()).namelist() == ["a_v1.0.lamina.json"]
        assert note(page) == "⚠ Not all exported: lamina-library.zip leaves out 1 file that cannot be read: b_v1.0.lamina.json"
    finally:
        page.evaluate("import('/static/js/store.js').then(S => __t.lib.useStore(S.browserStore()))")


def test_a_listing_that_fails_is_said_on_the_page(page):
    folder(page); drop(page, "a_v1.0.lamina.json", project("a"))
    page.evaluate("async () => { await (await navigator.storage.getDirectory()).removeEntry('lib', {recursive: true}) }")
    page.click("#popen")
    assert note(page).startswith("⚠ ") and page.is_visible("#libwhere .note")


def test_the_question_names_the_action(page):
    texts = page.evaluate("""async () => { const P = await import('/static/js/librarypage.js'), out = {};
        for (const how of ['save', 'import', 'link']) { const a = P.askClash({name: 'lamp', rev: '1.0', next: '1.1'}, how !== 'save', how);
            out[how] = document.querySelector('#libask').innerText; document.querySelector('#libask_cancel').click(); await a }
        return out }""")
    assert "Save" in texts["save"] and "save this as v1.1" in texts["save"]
    for how in ("import", "link"):
        assert "save" not in texts[how].lower() and "v1.1" in texts[how]


def test_revisions_left_in_the_browser_are_said_after_a_reload(page):
    name(page, "lamp"); save(page); drop(page, "lamp_v1.0.lamina.json", project("lamp"))
    link(page, [None])                                                           # the question cancelled: lamp stays
    assert page.evaluate("__t.lib.storeState().browser") == 1
    page.reload(); settle(page)
    library(page)
    assert "1 revision is still in this browser: unlink to see it, or press change folder and pick lib to move it." in where(page)[0]


def test_change_folder_says_where_the_files_stayed(page):
    folder(page)
    page.evaluate("""async () => { const d = await (await navigator.storage.getDirectory()).getDirectoryHandle('lib2', {create: true});
        window.showDirectoryPicker = async () => d }""")
    library(page)
    page.click("#libchange")
    page.wait_for_function("() => /kept in the folder lib2/.test(document.querySelector('#libwhere').innerText)")
    assert "Your files stayed in lib." in where(page)[0]
    page.reload(); settle(page)                                                # the browser's own picker back


def test_a_save_that_waits_for_reconnect_is_fixed_at_the_press(page):
    folder(page); name(page, "lamp"); t = page.evaluate("__t.state().thickness")
    page.evaluate("""() => { const P = FileSystemDirectoryHandle.prototype; window.__perm = {};
        for (const k of ['queryPermission', 'requestPermission']) window.__perm[k] = Object.getOwnPropertyDescriptor(P, k);
        P.queryPermission = async () => 'prompt'; P.requestPermission = () => new Promise(ok => { window.__grant = () => ok('granted') }) }""")
    try:
        page.evaluate("__t.lib.restoreStore()")
        page.click("#psave2")
        page.wait_for_function("() => !!window.__grant")
        page.evaluate("t => { __t.state().thickness = t + 1; window.__grant() }", t)   # changed while the prompt is up
        said(page, "saved")
    finally:
        page.evaluate("""() => { const P = FileSystemDirectoryHandle.prototype;
            for (const k in window.__perm) window.__perm[k] ? Object.defineProperty(P, k, window.__perm[k]) : delete P[k] }""")
    assert json.loads(on_disk(page)["lamp_v1.0.lamina.json"])["state"]["thickness"] == t


# --- texts (Task 9) ---
def test_clear_my_data_keeps_the_library(page):
    """The session goes (the page starts again on another example, with no project name); the library and the
    linked folder stay."""
    name(page, "lamp"); save(page); folder(page)
    assert "library" in page.get_attribute("#clear", "title")
    asked = []
    on_dialog(page, lambda d: (asked.append(d.message), d.accept()))
    with page.expect_navigation():
        menu(page, "#clear")
    settle(page)
    assert "The library is kept." in asked[0]
    assert page.evaluate("__t.job()") != "ex_egg" and page.evaluate("__t.state().project") != "lamp"
    assert page.evaluate("__t.lib.storeState()")["state"] == "folder" and lib(page) == [("lamp", ["1.0"])]


V1 = """async recs => { await new Promise((ok, no) => { const q = indexedDB.deleteDatabase('lamina_library');
        q.onsuccess = ok; q.onerror = () => no(q.error); q.onblocked = () => no(new Error('blocked')) });
    await new Promise((ok, no) => { const q = indexedDB.open('lamina_library', 1); q.onerror = () => no(q.error);
        q.onupgradeneeded = () => { const d = q.result; d.createObjectStore('revisions', {keyPath: 'file'});
            d.createObjectStore('kv'); d.createObjectStore('index') };
        q.onsuccess = () => { const t = q.result.transaction('revisions', 'readwrite');
            for (const r of recs) t.objectStore('revisions').put(r); t.oncomplete = () => { q.result.close(); ok() } } });
    __t.lib.useStore((await import('/static/js/store.js')).browserStore()) }"""


def test_a_version_1_library_is_listed_after_the_upgrade(page):
    """The database as version 1 left it: every record is listed after the upgrade, one without an mtime too."""
    lamp = project("lamp")
    vase = json.dumps({"name": "vase", "mode": "stacked", "state": {}, "saved": "2024-01-01T00:00:00.000Z"})
    page.evaluate(V1, [{"file": "lamp_v1.0.lamina.json", "text": lamp, "size": len(lamp), "mtime": 1_700_000_000_000},
                       {"file": "vase_v1.0.lamina.json", "text": vase, "size": len(vase)}])
    files = {f["file"]: f for f in browser_files(page)}
    assert files["lamp_v1.0.lamina.json"] == {"file": "lamp_v1.0.lamina.json", "size": len(lamp), "mtime": 1_700_000_000_000}
    assert files["vase_v1.0.lamina.json"]["mtime"] == 1_704_067_200_000         # repaired from its own date
    assert sorted(lib(page)) == [("lamp", ["1.0"]), ("vase", ["1.0"])]
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    assert save(page) == [{"file": "lamp_v1.0.lamina.json"}, []]
    b64 = page.evaluate("""async () => { const u = new Uint8Array(await (await __t.lib.exportAll()).blob.arrayBuffer());
        let s = ''; for (const x of u) s += String.fromCharCode(x); return btoa(s) }""")
    assert sorted(zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))).namelist()) == ["lamp_v1.0.lamina.json", "vase_v1.0.lamina.json"]


def test_a_failed_read_of_the_kept_folder_is_not_no_folder(page):
    """Start-up cannot read whether a folder is linked: the library says so, and a save goes nowhere."""
    name(page, "lamp")
    page.evaluate("""() => { const P = IDBObjectStore.prototype, get = P.get; window.__get = get;
        P.get = function (...a) { if (this.name === 'kv') { P.get = get; throw new Error('blocked') } return get.apply(this, a) } }""")
    try:
        page.evaluate("__t.lib.restoreStore()")
        err = page.evaluate("__t.lib.saveCurrent(() => Promise.resolve(null)).then(() => 'saved', e => e.message)")
        assert err == "The library could not be opened (blocked). Reload the page."   # with the reason (N2)
        assert page.evaluate("__t.lib.entries().then(() => 'listed', e => e.message)") == err
        page.click("#popen")
        page.wait_for_function("() => /could not be opened/.test(document.querySelector('#libwhere').innerText)")
        text, buttons = where(page)
        assert text.strip() == "⚠ " + err and buttons == []
        assert browser_files(page) == []
    finally:
        page.evaluate("() => { IDBObjectStore.prototype.get = window.__get; return __t.lib.restoreStore() }")
    assert page.evaluate("__t.lib.storeState().state") == "browser"


def test_an_index_entry_with_another_date_form_is_read_again(page):
    put(page, "a_v1.0.lamina.json", project("a")); lib(page)
    page.evaluate("""async () => { const S = await import('/static/js/store.js');
        await S.idxSet('browser', (await S.idxGet('browser')).map(e => ({...e, saved: 'Nov 5 2023'}))); __t.lib.useStore(S.browserStore()) }""")
    saved = page.evaluate("__t.lib.entries()")[0]["revs"][0]["saved"]
    assert saved != "Nov 5 2023" and saved.endswith("Z")


def test_kept_names_each_file_once(page):
    """b keeps both as v1.1 (this import had v1.0 twice); another tab puts an unreadable v1.1 there meanwhile, and b
    keeps both again, as v1.2: one line for b, with where it landed."""
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    page.evaluate("""async () => { const S = await import('/static/js/store.js'), b = S.browserStore(); let n = 0;
        __t.lib.useStore({...b, list: async () => { if (++n === 4) await b.write('lamp_v1.1.lamina.json', 'not json'); return b.list() }}) }""")
    try:
        two = [(f"{n}.lamina.json", json.dumps({"name": "lamp", "rev": "1.0", "mode": "stacked", "state": {"n": n}}), None) for n in "ab"]
        r, _ = import_files(page, two, [{"answer": "replace", "rest": True}])
    finally:
        page.evaluate("import('/static/js/store.js').then(S => __t.lib.useStore(S.browserStore()))")
    assert r["imported"] == ["lamp_v1.0.lamina.json", "lamp_v1.2.lamina.json"]
    assert r["kept"] == [{"rev": "lamp v1.0", "as": "1.2", "why": "twice"}]


def test_a_link_that_kept_both_says_why(page):
    name(page, "lamp"); save(page); drop(page, "lamp_v1.0.lamina.json", "not json")
    r, _ = link(page, ["replace"])
    assert r["kept"] == [{"rev": "lamp v1.0", "as": "1.1", "why": "unreadable"}]
    assert sorted(on_disk(page)) == ["lamp_v1.0.lamina.json", "lamp_v1.1.lamina.json"]


# --- export, import and the folder line, review leftovers (Task 9) ---
def test_an_import_does_not_read_the_library_again_for_each_file(page):
    """A listing reads the stored texts of new or changed revisions only: an import of 5 files into a library of 5
    reads none of the 5 again (it used to read every stored text before each file)."""
    for n in range(5):
        put(page, f"old{n}_v1.0.lamina.json", project(f"old{n}"))
    lib(page)                                                                  # indexed once
    page.evaluate("""() => { const P = IDBObjectStore.prototype; window.__idb = [P.get, P.getAll]; window.__texts = 0;
        for (const k of ['get', 'getAll']) { const f = P[k]; P[k] = function (...a) { const r = f.apply(this, a);
            if (this.name === 'revisions') r.addEventListener('success', () => { window.__texts += [r.result ?? []].flat().length });
            return r } } }""")
    try:
        r, _ = import_files(page, [(f"new{n}.lamina.json", project(f"new{n}"), None) for n in range(5)])
        texts = page.evaluate("window.__texts")
    finally:
        page.evaluate("() => { const P = IDBObjectStore.prototype; [P.get, P.getAll] = window.__idb }")
    assert len(r["imported"]) == 5 and texts == 0
    assert sorted(p for p, _ in lib(page)) == [f"new{n}" for n in range(5)] + [f"old{n}" for n in range(5)]


def test_a_field_that_cannot_be_text_is_one_bad_file(page):
    r, _ = import_files(page, [("a.lamina.json", project("a"), None),
                               ("odd.lamina.json", '{"name":{"toString":1},"mode":"stacked"}', None),
                               ("b.lamina.json", project("b"), None)])
    assert r["imported"] == ["a_v1.0.lamina.json", "b_v1.0.lamina.json"] and r["bad"] == ["odd.lamina.json"]


def test_a_replace_that_kept_both_says_why(page):
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    two = [(f"{n}.lamina.json", json.dumps({"name": "lamp", "rev": "1.0", "mode": "stacked", "state": {"n": n}}), None) for n in "ab"]
    r, _ = import_files(page, two, [{"answer": "replace", "rest": True}])
    assert r["kept"] == [{"rev": "lamp v1.0", "as": "1.1", "why": "twice"}]
    library(page)
    with page.expect_file_chooser() as fc:
        page.click("#libimport")
    put(page, "egg_v1.0.lamina.json", project("egg"))
    egg = lambda n: json.dumps({"name": "egg", "rev": "1.0", "mode": "stacked", "state": {"n": n}}).encode()
    fc.value.set_files([{"name": f"{n}.lamina.json", "mimeType": "application/json", "buffer": egg(n)} for n in "ab"])
    page.wait_for_selector("#libask[open]")
    page.check("#libask_rest"); page.click("#libask_replace")
    page.wait_for_function("() => /^imported/.test(document.querySelector('#libwhere .note')?.innerText)")
    assert note(page) == "imported 2 files. 1 kept as a new revision instead of replacing: egg v1.0 as v1.1 (this import had that revision twice)"


def test_a_saved_date_in_another_form_is_sorted_as_a_date(page):
    put(page, "old_v1.0.lamina.json", json.dumps({"name": "old", "mode": "stacked", "saved": "Nov 5 2023"}))
    put(page, "new_v1.0.lamina.json", json.dumps({"name": "new", "mode": "stacked", "saved": "2024-01-01T00:00:00.000Z"}))
    ps = page.evaluate("__t.lib.entries()")
    assert [p["name"] for p in ps] == ["new", "old"]
    assert ps[1]["revs"][0]["saved"] == page.evaluate("new Date('Nov 5 2023').toISOString()")


def test_a_file_with_its_name_only_in_the_settings_keeps_it(page):
    """A project file from before 0.3.x carries its name in state.project only: listed and opened under it."""
    put(page, "lamp_v1.0.lamina.json", json.dumps({"version": 3, "mode": "stacked", "state": {"project": "lamp"}, "example": "egg"}))
    assert lib(page) == [("lamp", ["1.0"])]
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    assert page.evaluate("__t.state().project") == "lamp" and page.input_value("#pname") == "lamp"


def test_a_number_as_name_opens_under_the_cards_name(page):
    put(page, "42_v2.lamina.json", json.dumps({"name": 42, "rev": 2, "mode": "stacked", "state": {}}))
    put(page, "egg_v1.0.lamina.json", json.dumps({"example": "egg", "mode": "stacked", "state": {}}))   # no name: the example's
    page.evaluate("__t.lib.openRevision('42_v2.lamina.json')"); settle(page)
    assert [page.evaluate("__t.state().project"), page.evaluate("__t.state().rev")] == ["42", "2"]
    assert save(page) == [{"file": "42_v2.lamina.json"}, []]
    page.evaluate("__t.lib.openRevision('egg_v1.0.lamina.json')"); settle(page)
    assert page.evaluate("__t.state().project") == "egg"
    assert save(page) == [{"file": "egg_v1.0.lamina.json"}, []]
    assert sorted(lib(page)) == [("42", ["2"]), ("egg", ["1.0"])]


def test_the_note_clears_after_a_good_listing_and_names_five(page):
    page.evaluate("""() => import('/static/js/store.js').then(S => { const b = S.browserStore();
        __t.lib.useStore({...b, list: () => Promise.reject(new Error('the list failed'))}) })""")
    page.click("#popen")
    assert note(page) == "⚠ Library not listed: the list failed"
    page.evaluate("import('/static/js/store.js').then(S => { __t.lib.useStore(S.browserStore()); __t.lib.setSaved(null) })")
    page.wait_for_function("() => document.querySelector('#libyours').dataset.listed && !document.querySelector('#libwhere .note')")
    with page.expect_file_chooser() as fc:
        page.click("#libimport")
    fc.value.set_files([{"name": f"x{n}.lamina.json", "mimeType": "application/json", "buffer": b"{"} for n in range(7)])
    page.wait_for_function("() => /cannot be read/.test(document.querySelector('#libwhere .note')?.innerText)")
    assert note(page) == "⚠ imported 0 files. Not imported, as they cannot be read: x0.lamina.json, x1.lamina.json, " \
                         "x2.lamina.json, x3.lamina.json, x4.lamina.json and 2 more"


def test_progress_and_delete_errors_are_said_on_the_page(page):
    put(page, "lamp_v1.0.lamina.json", project("lamp"))
    page.evaluate("""() => import('/static/js/store.js').then(S => { const b = S.browserStore();
        __t.lib.useStore({...b, remove: () => Promise.reject(new Error('the disk said no'))}) })""")
    try:
        library(page)
        with page.expect_file_chooser() as fc:
            page.click("#libimport")
        fc.value.set_files([{"name": "lamp.lamina.json", "mimeType": "application/json", "buffer": project("lamp").encode()}])
        page.wait_for_selector("#libask[open]")
        assert note(page, busy=True) == "importing 1 file…"
        page.click("#libask_cancel")
        page.wait_for_function("() => /skipped/.test(document.querySelector('#libwhere .note')?.innerText)")
        card(page, "lamp").locator(".more").click(); page.wait_for_selector("#libyours .rev")
        on_dialog(page, lambda d: d.accept())
        card(page, "lamp").locator(".delete").click()
        page.wait_for_function("() => /disk said no/.test(document.querySelector('#libwhere .note')?.innerText)")
        assert note(page) == "⚠ Not deleted: the disk said no"
    finally:
        page.evaluate("import('/static/js/store.js').then(S => __t.lib.useStore(S.browserStore()))")
