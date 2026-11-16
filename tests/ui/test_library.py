"""The project library: the loaded example is the page's own state, so a page without the dropdown can open one;
the zip module and the two stores under the library."""
import base64
import io
import zipfile

import pytest

from .helpers import example


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
