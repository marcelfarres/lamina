// The Python side of browser.js: Pyodide + the same core/ and web/app.py the server runs, answering one request per
// message through web/browser.py. Jobs live in IndexedDB so a refresh resumes the session, as on the server.
const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.8/full/';
const say = progress => postMessage({progress});
const APP = '/app', EXAMPLES = APP + '/examples';

const T = {}, mark = k => T[k] = +((performance.now() - T0) / 1000).toFixed(2), T0 = performance.now();   // seconds per start-up step, logged once ready

const get = (u, as) => fetch(u).then(r => r[as]());
const unwheel = (py, wheel) => py.unpackArchive(wheel, 'zip', {extractDir: py.runPython('import site; site.getsitepackages()[0]')});   // a wheel is a zip that goes into site-packages
const lines = async f => (await get(f, 'text')).split('\n').map(l => l.trim()).filter(Boolean);

const ready = (async () => {
  say('loading Python in your browser — first time about 60 MB, cached afterwards…');
  // what the site ships is fetched while Python loads, not after it
  const wheels = lines('py/requirements.txt').then(ws => Promise.all(ws.map(w => get('py/' + w, 'arrayBuffer'))));
  const core = get('py/core.zip', 'arrayBuffer');
  const examples = Promise.all(['index.json', 'presets.json'].map(f => get(`py/examples/${f}`, 'text')));   // the list, and what each example opens with
  const {loadPyodide} = await import(PYODIDE + 'pyodide.mjs');    // a module worker: Pyodide no longer runs in classic ones
  mark('pyodide.mjs');
  const py = await loadPyodide({indexURL: PYODIDE, packages: ['numpy', 'scipy', 'shapely', 'networkx', 'scikit-image', 'pillow', 'lxml', 'fastapi']});
  mark('loadPyodide+packages');
  say('installing Lamina…');
  for (const w of await wheels) unwheel(py, w);                      // pinned wheels beside the site: no resolver, no PyPI
  mark('wheels');
  py.unpackArchive(await core, 'zip', {extractDir: APP});
  py.FS.mkdirTree(EXAMPLES);
  (await examples).forEach((text, i) => py.FS.writeFile(`${EXAMPLES}/${['index.json', 'presets.json'][i]}`, text));
  py.FS.mkdirTree(APP + '/web/static');                            // app.py mounts it; the page itself is served by the site
  py.FS.mkdirTree(APP + '/working-files'); py.FS.mount(py.FS.filesystems.IDBFS, {}, APP + '/working-files');
  await new Promise((res, rej) => py.FS.syncfs(true, e => e ? rej(e) : res()));
  // your own machine: nothing expires on its own, "clear my data" is the only delete; jobs go under the working
  // directory, so it is the app's, where the persistent working-files/ is mounted
  py.runPython(`import importlib, os, sys; importlib.invalidate_caches(); os.environ['LAMINA_TTL_HOURS'] = '0'; os.chdir(${JSON.stringify(APP)}); sys.path.insert(0, ${JSON.stringify(APP)})`);
  mark('core.zip+examples+idbfs');
  const handle = py.pyimport('web.browser').handle;
  mark('import web.browser');
  // build() stages → the page's progress bar. An `artifact` is a file the build has finished with and the page can
  // show at once (the preview mesh): the worker is busy building, so it cannot answer a fetch for it — the bytes
  // travel with the message instead. readFile hands back a view into the WASM heap, so it has to be copied.
  let at = 0;   // where the bar stands: the parts ride with it
  py.globals.set('report', (text, frac, artifact) => {
    let model = null; at = frac;
    if (artifact) { try { model = py.FS.readFile(artifact).slice() } catch (e) { model = null } }
    postMessage({progress: text, frac, model}, model ? [model.buffer] : []);
  });
  // the parts before they are nested (core.progress.parts), for the 3D view: the plan as JSON, made during the call
  // (the build's lists grow after it), posted once
  py.globals.set('parts', json => postMessage({progress: '', frac: at, parts: json}));
  py.runPython('import json, core.progress; core.progress.report = report; core.progress.parts = lambda plan: parts(json.dumps(plan))');
  say(''); mark('ready'); console.info('lamina startup', T);
  return {py, handle};
})().catch(err => { postMessage({progress: 'Python could not be loaded — ' + err, failed: true}); throw err });

// ezdxf and reportlab only write (and read) DXF and PDF/EPS files, so they come with the first request that does,
// not with Python: the cut-file routes, and an uploaded .dxf outline
const needsWriters = m => /^api\/job\/[^/]+\/[^/]+\/(export|fitcut|kerftest)$/.test(m.path) || m.form?.some(f => f.length === 3 && /\.dxf$/i.test(f[1]));
let writers;
const loadWriters = py => writers ??= (async () => {
  say('loading the DXF and PDF writers…');
  const t = performance.now();
  await py.loadPackage(['pyparsing', 'fonttools', 'typing-extensions', 'charset-normalizer']);   // what the two need, from Pyodide
  for (const w of await Promise.all((await lines('py/export-requirements.txt')).map(w => get('py/' + w, 'arrayBuffer')))) unwheel(py, w);
  py.runPython('import importlib; importlib.invalidate_caches()');
  console.info('lamina startup', {writers: +((performance.now() - t) / 1000).toFixed(2)});
  say('');
})().catch(err => { writers = undefined; throw err });

onmessage = async e => {
  const {py, handle} = await ready, m = e.data;
  try {
    if (needsWriters(m)) await loadWriters(py);
    // bundled models come over one by one, when picked — or when a resumed session re-slices its job "ex_<name>"
    const field = k => m.form?.find(f => f[0] === k)?.[1] || '', job = field('job');
    const ex = field('example') || (job.startsWith('ex_') ? job.slice(3) : '');
    if (/^[A-Za-z0-9_-]+$/.test(ex) && !py.FS.analyzePath(`${EXAMPLES}/${ex}.stl`).exists)
      py.FS.writeFile(`${EXAMPLES}/${ex}.stl`, new Uint8Array(await (await fetch(`py/examples/${ex}.stl`)).arrayBuffer()));
    const attempt = () => {
      const r = handle(m.method, m.path, m.query, py.toPy(m.form)), [status, headers, raw] = r.toJs({dict_converter: Object.fromEntries});
      let body = raw; if (!(raw instanceof Uint8Array)) { const b = raw.getBuffer(); body = b.data.slice(); b.release(); raw.destroy() }
      r.destroy();
      return {status, headers, body};
    };
    const out = attempt();   // GEOS's NaN failure is tried once more in browser.handle, which sees a failed slice's 500
    if (m.method !== 'GET') py.FS.syncfs(false, () => {});
    postMessage(out);
    // A plan is a graph with back-references — every piece names its slice, every slice holds its pieces — so it
    // only goes when the cyclic collector runs. Left to itself that is not before the next slice asks for its own
    // arrays, and a heap under that much pressure stops giving GEOS numbers it can work with: slicing the same
    // model a fourth way returned "orientationIndex encountered NaN". One collection per request costs milliseconds.
    py.runPython('import gc; gc.collect()');
  } catch (err) {
    postMessage({status: 500, headers: {'content-type': 'application/json'}, body: new TextEncoder().encode(JSON.stringify({detail: String(err)}))});
  }
};
