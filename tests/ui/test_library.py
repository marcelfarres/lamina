"""The project library: the loaded example is the page's own state, so a page without the dropdown can open one;
the zip module and the two stores under the library."""
import base64
import io
import zipfile

import pytest

from .helpers import example, set_fields, settle, still


def wipe(page):
    """An empty library behind the browser store, and nothing saved in this tab. The store tests below delete the
    database instead; both leave it empty, and the library opens it again on its next call."""
    page.evaluate("""async () => { const S = await import('/static/js/store.js'); __t.lib.useStore(S.browserStore());
        for (const p of await __t.lib.entries()) await __t.lib.removeProject(p.name); __t.lib.setSaved(null);
        const s = __t.state(); s.project = ''; s.rev = '1.0'; (await import('/static/js/project.js')).syncProject() }""")


@pytest.fixture(autouse=True)
def empty_library(page):
    wipe(page)


def lib(page):
    """The library as entries() lists it, in its order: [(name, [rev, …]), …]."""
    return [(p["name"], [r["rev"] for r in p["revs"]]) for p in page.evaluate("__t.lib.entries()")]


def save(page, answer=None):
    """saveCurrent() with `ask` answering `answer`: [its result, the clashes it was asked about]."""
    return page.evaluate("""async a => { const asked = [];
        const r = await __t.lib.saveCurrent(c => { asked.push(c); return Promise.resolve(a) }); return [r, asked] }""", answer)


def name(page, n):
    set_fields(page, [("pname", n)]); settle(page)


def test_open_example_is_page_state(page):
    example(page, "horse_statue")
    assert page.evaluate("__t.project().then(p => p.example)") == "horse_statue"
    assert page.evaluate("__t.job()").startswith("ex_")
    page.evaluate("document.querySelector('#example').value = 'egg'")       # the box is no longer the truth
    assert page.evaluate("__t.project().then(p => p.example)") == "horse_statue"


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


# each store test starts from an empty store: the browser one deletes the database (so opening it also covers the
# first run, when it does not exist yet), the folder one works in a fresh sub-folder of the origin's private folder
FRESH = """async kind => { const S = await import('/static/js/store.js');
    if (kind === 'browser') { await new Promise((ok, no) => { const r = indexedDB.deleteDatabase('lamina_library');
        r.onsuccess = ok; r.onerror = () => no(r.error); r.onblocked = () => no(new Error('blocked')) }); return S.browserStore() }
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
    b = page.evaluate(ui, [True, 3, 2, True])
    assert page.evaluate("__t.banner()").startswith("step 3")                 # the view did change: short of the end
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
    name(page, "a/b"); first, _ = save(page)
    name(page, "a_b"); second, asked = save(page)
    assert (first["file"], second["file"], asked) == ("a_b_v1.0.lamina.json", "a_b~2_v1.0.lamina.json", [])
    assert sorted(lib(page)) == [("a/b", ["1.0"]), ("a_b", ["1.0"])]          # the names come from inside the files
    page.click("#pminor"); settle(page)                                        # its next revision keeps its own stem
    assert save(page)[0] == {"file": "a_b~2_v1.1.lamina.json"}


def test_save_never_writes_onto_a_file_that_cannot_be_read(page):
    page.evaluate("import('/static/js/store.js').then(S => S.browserStore().write('lamp_v1.0.lamina.json', 'not json'))")
    name(page, "lamp")
    assert save(page) == [{"file": "lamp~2_v1.0.lamina.json"}, []]
    assert sorted(lib(page)) == [("lamp", ["1.0"]), ("lamp_v1.0.lamina.json", [""])]
    assert page.evaluate("import('/static/js/store.js').then(S => S.browserStore().read('lamp_v1.0.lamina.json'))") == "not json"


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
    page.click("#pminor"); settle(page); save(page)
    assert lib(page) == [("lamp", ["1.1", "1.0"])]


def test_bump_from_an_old_revision_goes_to_the_next_free(page):
    name(page, "lamp")
    for _ in range(4):
        save(page); page.click("#pminor"); settle(page)
    assert lib(page) == [("lamp", ["1.3", "1.2", "1.1", "1.0"])]
    page.evaluate("__t.lib.openRevision('lamp_v1.0.lamina.json')"); settle(page)
    page.click("#pminor")
    assert page.evaluate("__t.state().rev") == "1.4" and page.text_content("#prev") == "1.4"
    page.click("#pmajor")
    assert page.evaluate("__t.state().rev") == "2.0"
    settle(page)


def test_changed_name_is_a_new_project(page):
    name(page, "lamp"); save(page)
    (before,) = page.evaluate("__t.lib.entries()")
    name(page, "lamp-big"); assert save(page) == [{"file": "lamp-big_v1.0.lamina.json"}, []]
    after = page.evaluate("__t.lib.entries()")
    assert sorted(p["name"] for p in after) == ["lamp", "lamp-big"]
    assert next(p for p in after if p["name"] == "lamp") == before              # untouched


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
        assert page.evaluate("__t.lib.unsaved()") is True


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
    name(page, "lamp"); save(page); page.click("#pminor"); settle(page); save(page)
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
            q.onsuccess = () => ok('deleted'); q.onerror = () => ok('error'); q.onblocked = () => ok('blocked') });
        return [e, del] }""")
    assert r == ["DataCloneError", "deleted"]


def test_folder_list_skips_a_file_that_vanished(page):
    r = page.evaluate(f"""async () => {{ const s = await ({FRESH})('folder'), P = FileSystemFileHandle.prototype, g = P.getFile;
        await s.write('a_v1.0.lamina.json', '{{}}'); await s.write('gone_v1.0.lamina.json', '{{}}');
        P.getFile = function () {{ return this.name === 'gone_v1.0.lamina.json' ? Promise.reject(new DOMException('gone', 'NotFoundError')) : g.call(this) }};
        try {{ return (await s.list()).map(e => e.file) }} finally {{ P.getFile = g }} }}""")
    assert r == ["a_v1.0.lamina.json"]
