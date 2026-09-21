// The Python side of browser.js: Pyodide + the same core/ and web/app.py the server runs, answering one request per
// message through web/browser.py. Jobs live in IndexedDB so a refresh resumes the session, as on the server.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.6/full/';
const say = progress => postMessage({progress});
const APP = '/app', EXAMPLES = APP + '/examples';

const ready = (async () => {
  say('loading Python in your browser — first time about 60 MB, cached afterwards…');
  const {loadPyodide} = await import(PYODIDE + 'pyodide.mjs');    // a module worker: Pyodide no longer runs in classic ones
  const py = await loadPyodide({indexURL: PYODIDE, packages: ['numpy', 'scipy', 'shapely', 'networkx', 'scikit-image', 'pillow', 'lxml', 'fastapi', 'micropip']});
  say('installing Lamina…');
  const reqs = (await (await fetch('py/requirements.txt')).text()).split('\n').map(l => l.trim()).filter(Boolean)
    .map(l => l.endsWith('.whl') ? new URL('py/' + l, self.location.href).href : l);
  await py.runPythonAsync(`import micropip; await micropip.install(${JSON.stringify(reqs)})`);
  py.unpackArchive(await (await fetch('py/core.zip')).arrayBuffer(), 'zip', {extractDir: APP});
  py.FS.mkdirTree(EXAMPLES);
  for (const f of ['index.json', 'presets.json'])                    // the list, and what each example opens with
    py.FS.writeFile(`${EXAMPLES}/${f}`, await (await fetch(`py/examples/${f}`)).text());
  py.FS.mkdirTree(APP + '/web/static');                            // app.py mounts it; the page itself is served by the site
  py.FS.mkdirTree(APP + '/working-files'); py.FS.mount(py.FS.filesystems.IDBFS, {}, APP + '/working-files');
  await new Promise((res, rej) => py.FS.syncfs(true, e => e ? rej(e) : res()));
  // your own machine: nothing expires on its own, "clear my data" is the only delete
  py.runPython(`import os, sys; os.environ['LAMINA_TTL_HOURS'] = '0'; sys.path.insert(0, ${JSON.stringify(APP)})`);
  const handle = py.pyimport('web.browser').handle;
  // build() stages → the page's progress bar. An `artifact` is a file the build has finished with and the page can
  // show at once (the preview mesh): the worker is busy building, so it cannot answer a fetch for it — the bytes
  // travel with the message instead. readFile hands back a view into the WASM heap, so it has to be copied.
  py.globals.set('report', (text, frac, artifact) => {
    let model = null;
    if (artifact) { try { model = py.FS.readFile(artifact).slice() } catch (e) { model = null } }
    postMessage({progress: text, frac, model}, model ? [model.buffer] : []);
  });
  py.runPython('import core.plan; core.plan.report = report');
  say('');
  return {py, handle};
})().catch(err => { say('Python could not be loaded — ' + err); throw err });

onmessage = async e => {
  const {py, handle} = await ready, m = e.data;
  try {
    // bundled models come over one by one, when picked — or when a resumed session re-slices its job "ex_<name>"
    const field = k => m.form?.find(f => f[0] === k)?.[1] || '', job = field('job');
    const ex = field('example') || (job.startsWith('ex_') ? job.slice(3) : '');
    if (/^[A-Za-z0-9_-]+$/.test(ex) && !py.FS.analyzePath(`${EXAMPLES}/${ex}.stl`).exists)
      py.FS.writeFile(`${EXAMPLES}/${ex}.stl`, new Uint8Array(await (await fetch(`py/examples/${ex}.stl`)).arrayBuffer()));
    const r = handle(m.method, m.path, m.query, py.toPy(m.form)), [status, headers, raw] = r.toJs({dict_converter: Object.fromEntries});
    let body = raw; if (!(raw instanceof Uint8Array)) { const b = raw.getBuffer(); body = b.data.slice(); b.release(); raw.destroy() }
    r.destroy();
    if (m.method !== 'GET') py.FS.syncfs(false, () => {});
    postMessage({id: m.id, status, headers, body});
    // A plan is a graph with back-references — every piece names its slice, every slice holds its pieces — so it
    // only goes when the cyclic collector runs. Left to itself that is not before the next slice asks for its own
    // arrays, and a heap under that much pressure stops giving GEOS numbers it can work with: slicing the same
    // model a fourth way returned "orientationIndex encountered NaN". One collection per request costs milliseconds.
    py.runPython('import gc; gc.collect()');
  } catch (err) {
    postMessage({id: m.id, status: 500, headers: {'content-type': 'application/json'}, body: new TextEncoder().encode(JSON.stringify({detail: String(err)}))});
  }
};
