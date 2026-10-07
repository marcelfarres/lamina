// Lamina without a server. The page always asks api/… first; when nothing answers (GitHub Pages, a static Space,
// file://) the same requests go to a web worker running the Python app in Pyodide, and download links are served
// from it as blobs. Loaded before the app script, so its first fetch already goes through here.
(() => {
  const real = window.fetch.bind(window);
  const isApi = u => /(^|\/)(api|jobs)\//.test(u);
  // The worker gets one request at a time: Python cannot be interrupted mid-slice, so a slice posted behind another
  // ran to its end — four slider moves were four whole slices, the last value a minute and a half late, and a new
  // example waited for the old one to finish. Now a newer slice drops the waiting ones, and the one still running is
  // raced: a spare worker starts loading Python (~20 s even cached) and whichever comes first, the old slice ending
  // or the spare being ready, is where the newest slice runs. The other one is terminated. Nothing is posted before
  // Python is ready: until then a newer slice simply takes the waiting one's place.
  let mode = null, worker = null, spare = null, running = null, ready = false; const queue = [];
  const REPLACED = {status: 409, headers: {'content-type': 'application/json'}, body: new TextEncoder().encode('{"detail":"a newer slice of this page replaced this one"}')};
  const box = () => document.getElementById('pyload') || Object.assign(document.body.appendChild(document.createElement('div')),
    {id: 'pyload', style: 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#232429;color:#e6e6e3;border:1px solid #4f8cff;border-radius:6px;padding:8px 14px;font:13px system-ui,sans-serif;z-index:99;max-width:80vw'});
  function spawn() {
    const w = new Worker('static/browser-worker.js', {type: 'module'});
    w.onmessage = e => {
      const m = e.data;
      if (w !== worker && w !== spare) return;                          // one already terminated
      if (w === spare) {                                                // ready first: the replaced slice stops here
        if (m.failed) { w.terminate(); spare = null }                   // the next replacement tries again
        if (m.progress !== '') return;
        if (running?.stale) { worker.terminate(); running.res(REPLACED); running = null; worker = w } else w.terminate();
        spare = null; pump(); return;
      }
      // a slice under way; a mesh riding along is one the build has finished with, shown before the rest of it
      if (m.frac !== undefined) {
        if (running.stale) return;                                      // replaced: its stages and its mesh are not the page's
        if (m.model instanceof Uint8Array) m.model = URL.createObjectURL(new Blob([m.model]));
        window.dispatchEvent(new CustomEvent('lamina-progress', {detail: m}));
        return;
      }
      if (m.progress !== undefined) {                                   // Python loading
        if (m.progress) box().textContent = m.progress; else { box().remove(); ready = true; pump() }
        return;
      }
      running.res(m); running = null; pump();
    };
    return w;
  }
  function pump() {
    if (running || !ready || !queue.length) return;
    running = queue.shift(); worker.postMessage(running.msg);
  }
  async function viaWorker(url, opts = {}) {
    worker ??= spawn();
    const u = new URL(url, location.href);
    const msg = {method: (opts.method || 'GET').toUpperCase(), path: u.pathname.replace(/^.*\/(api|jobs)\//, '$1/'), query: u.search.slice(1), form: null};
    if (opts.body instanceof FormData) { msg.form = []; for (const [k, v] of opts.body) msg.form.push(v instanceof File ? [k, v.name, new Uint8Array(await v.arrayBuffer())] : [k, v]) }
    const slice = msg.path === 'api/slice';
    if (slice) {                                                        // only the newest slice matters to the page
      for (const q of queue.filter(q => q.slice)) { queue.splice(queue.indexOf(q), 1); q.res(REPLACED) }
      if (running?.slice) { running.stale = true; spare ??= spawn() }
    }
    const r = await new Promise(res => { queue.push({msg, res, slice}); pump() });
    return new Response(r.body, {status: r.status, headers: r.headers});
  }
  window.fetch = async (url, opts) => {
    const u = typeof url === 'string' ? url : url.url;
    if (!isApi(u)) return real(url, opts);
    if (mode !== 'static') {
      const r = await real(url, opts).catch(() => null);
      if (mode === 'server' || (r && r.status !== 404)) { mode = 'server'; return r }
      mode = 'static'; document.documentElement.dataset.static = '1';   // the page tells the user what running in the browser costs
    }
    return viaWorker(u, opts);
  };
  document.addEventListener('click', e => {   // download links: fetched from the worker, saved as a file
    const a = e.target.closest('a[href]'); if (mode !== 'static' || !a || !isApi(a.getAttribute('href'))) return;
    e.preventDefault();
    viaWorker(a.href).then(async r => {
      const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') || '')?.[1] || a.href.split('/').pop().split('?')[0];
      Object.assign(document.createElement('a'), {href: URL.createObjectURL(await r.blob()), download: name}).click();
    });
  });
})();
