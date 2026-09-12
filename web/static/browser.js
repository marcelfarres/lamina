// Lamina without a server. The page always asks api/… first; when nothing answers (GitHub Pages, a static Space,
// file://) the same requests go to a web worker running the Python app in Pyodide, and download links are served
// from it as blobs. Loaded before the app script, so its first fetch already goes through here.
(() => {
  const real = window.fetch.bind(window);
  const isApi = u => /(^|\/)(api|jobs)\//.test(u);
  let mode = null, worker = null, nextId = 0; const waiting = new Map();
  const box = () => document.getElementById('pyload') || Object.assign(document.body.appendChild(document.createElement('div')),
    {id: 'pyload', style: 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#232429;color:#e6e6e3;border:1px solid #4f8cff;border-radius:6px;padding:8px 14px;font:13px system-ui,sans-serif;z-index:99;max-width:80vw'});
  function start() {
    worker = new Worker('static/browser-worker.js', {type: 'module'});
    worker.onmessage = e => {
      const m = e.data;
      if (m.progress !== undefined) { m.progress ? box().textContent = m.progress : box().remove(); return }
      const w = waiting.get(m.id); waiting.delete(m.id); w(m);
    };
  }
  async function viaWorker(url, opts = {}) {
    if (!worker) start();
    const u = new URL(url, location.href), id = nextId++;
    const msg = {id, method: (opts.method || 'GET').toUpperCase(), path: u.pathname.replace(/^.*\/(api|jobs)\//, '$1/'), query: u.search.slice(1), form: null};
    if (opts.body instanceof FormData) { msg.form = []; for (const [k, v] of opts.body) msg.form.push(v instanceof File ? [k, v.name, new Uint8Array(await v.arrayBuffer())] : [k, v]) }
    const r = await new Promise(res => { waiting.set(id, res); worker.postMessage(msg) });
    return new Response(r.body, {status: r.status, headers: r.headers});
  }
  window.fetch = async (url, opts) => {
    const u = typeof url === 'string' ? url : url.url;
    if (!isApi(u)) return real(url, opts);
    if (mode !== 'static') {
      const r = await real(url, opts).catch(() => null);
      if (mode === 'server' || (r && r.status !== 404)) { mode = 'server'; return r }
      mode = 'static';
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
