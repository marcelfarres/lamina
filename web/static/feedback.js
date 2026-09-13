// "Report a problem" — the same dialog on the landing page and in the app, opened by any link carrying
// data-feedback. Those links point at the GitHub issue form underneath, so they still work with this script
// missing or JavaScript off; the dialog only takes over when it is there.
//
// It hosts nothing and posts nowhere. The report is gathered here and handed to whichever of the two ways out the
// reporter prefers — an email, or the GitHub issue form — both opened prefilled, both sent by them. A server that
// took reports automatically would save one click and cost a public endpoint, a token and its upkeep; this does
// not, and it works the same in the published site, in Docker and on a laptop with no network at all.
//
// What it gathers is the point: a page says what it can attach with  laminaFeedback(collect), where
// collect(withModel) resolves to {technique, summary, file} — file being the project file, which carries the model
// itself only when withModel. The landing page registers nothing, so there the dialog is the description alone.
(() => {
const ISSUE = 'https://github.com/marcelfarres/lamina/issues/new';
const MAIL = 'lamina.3d.app@gmail.com';        // the project's own address: a report never depends on holding an account
let collect = null;
window.laminaFeedback = fn => { collect = fn };

const CSS = `
#fb_dlg{width:min(580px,92vw);border:1px solid var(--line,#2f3138);border-radius:10px;background:var(--panel,#1c1d21);color:var(--ink,#e6e6e3);padding:22px;font:14px/1.55 Inter,system-ui,sans-serif}
#fb_dlg::backdrop{background:#000b}
#fb_dlg h3{margin:0 0 6px;font-size:18px}
#fb_dlg label{display:block;margin:14px 0 0}
#fb_dlg textarea{display:block;width:100%;margin-top:5px;padding:7px 9px;border:1px solid var(--line,#2f3138);border-radius:5px;background:var(--panel2,#232429);color:inherit;font:inherit}
#fb_dlg .m{color:var(--muted,#9a9ba3);font-size:12.5px;font-weight:400}
#fb_dlg .warn{border:1px solid var(--line,#2f3138);border-left:3px solid var(--warn,#f5b642);background:#0003;padding:10px 13px;margin-top:16px;border-radius:6px;font-size:12.5px;line-height:1.5;color:var(--muted,#9a9ba3)}
#fb_dlg .row{display:flex;gap:10px;align-items:center;justify-content:flex-end;flex-wrap:wrap;margin-top:18px}
#fb_dlg button{padding:8px 15px;border-radius:6px;border:1px solid var(--line,#2f3138);background:var(--panel2,#232429);color:inherit;font:inherit;cursor:pointer}
#fb_dlg button.go{background:var(--acc-btn,#2563eb);border-color:transparent;color:#fff;font-weight:600}
#fb_dlg #fb_tick{width:auto;margin-right:7px;accent-color:var(--acc,#4f8cff)}
#fb_dlg #fb_note:empty{display:none}`;

// What is about to travel, said plainly before any of it does. The model is the expensive part of the promise, so
// the sentence that matters most is in the same breath as the ask.
const WARN = {
  app: `What goes with your report: the technique, every setting, and what the checks said. With the box ticked the model file is saved alongside it for you to attach — that is what makes a report reproducible, so please do, unless it is a model you are not free to share. Nothing is sent by this page: your mail program or the GitHub form opens with everything filled in, and you press send. An issue on GitHub is public; an email is not.`,
  page: `What goes with your report: your description, the address of this page and your browser version. No model and no settings — this page has none. Nothing is sent by this page: your mail program or the GitHub form opens with it filled in, and you press send. An issue on GitHub is public; an email is not.`,
};

const FORM = `<form id="fb_form">
  <h3>Report a problem</h3>
  <p class="m" style="margin:0">Lamina is an alpha and this is the quickest way to a fix. Nothing is too small.</p>
  <label>What went wrong <span class="m">— what you did, what you saw, what you expected instead</span>
    <textarea id="fb_what" rows="5" required placeholder="Interlocked, 5 × 4 on the egg: part X-3 has a slot cut clean through the outline."></textarea></label>
  <label id="fb_att" hidden><input type="checkbox" id="fb_tick" checked>Attach the model and every setting</label>
  <div class="warn" id="fb_warn"></div>
  <p class="m" id="fb_note" style="margin-top:14px"></p>
  <div class="row"><button type="button" id="fb_no">Cancel</button>
    <button type="button" id="fb_gh">Open the GitHub issue form</button>
    <button type="submit" class="go" id="fb_go">Email it</button></div>
</form>`;

document.head.appendChild(Object.assign(document.createElement('style'), {textContent: CSS}));
const dlg = Object.assign(document.createElement('dialog'), {id: 'fb_dlg'});
document.body.appendChild(dlg);
const $ = s => dlg.querySelector(s);
const cut = (v, n) => (v ?? '').toString().slice(0, n);
const save = (blob, name) => Object.assign(document.createElement('a'), {href: URL.createObjectURL(blob), download: name}).click();

function show() {
  dlg.innerHTML = FORM;                                        // a fresh form every time
  $('#fb_att').hidden = !collect;
  $('#fb_warn').textContent = collect ? WARN.app : WARN.page;
  $('#fb_no').onclick = () => dlg.close();
  $('#fb_gh').onclick = () => hand('github');
  $('#fb_form').onsubmit = e => { e.preventDefault(); hand('email') };   // submit = the default button, so Enter sends
  dlg.showModal();
  $('#fb_what').focus();
}

// Everything the report carries, as the fields a form post would have used — one shape, whichever way it goes out.
async function build() {
  const withModel = !!collect && !$('#fb_att').hidden && $('#fb_tick').checked;
  const got = collect ? await collect(withModel) : null;
  const fd = new FormData();
  fd.append('what', $('#fb_what').value.trim());
  fd.append('page', location.origin + location.pathname);      // the page, never its query string or hash
  fd.append('agent', navigator.userAgent);
  if (got?.technique) fd.append('technique', got.technique);
  if (got?.summary) fd.append('summary', got.summary);
  if (got?.file) fd.append('project', got.file, got.file.name);
  return fd;
}

async function hand(via) {
  if (!$('#fb_form').reportValidity()) return;
  $('#fb_note').textContent = 'gathering the report…';
  let fd;
  try { fd = await build() } catch (e) { $('#fb_note').textContent = 'could not read the model: ' + e.message; return }
  const file = fd.get('project');
  if (file) save(file, file.name);                             // neither route can carry it, so it lands in Downloads
  if (via === 'email') location.href = mailto(fd, file); else open(issueUrl(fd, file), '_blank', 'noopener');
  $('#fb_note').textContent = (via === 'email' ? 'Your mail program should be opening.' : 'The issue form is open in another tab.')
    + (file ? ` Please attach ${file.name} — it was just saved to your downloads.` : '');
}

// the same record either way, as plain text
const asText = fd => [fd.get('what'), '', `technique: ${fd.get('technique') || '—'}`, `page: ${fd.get('page')}`,
                      `browser: ${fd.get('agent')}`, '', fd.get('summary') || ''].join('\n');

// long mailto bodies are cut by some clients, so the settings are trimmed; the attached project file has them all
const mailto = (fd, file) =>
  `mailto:${MAIL}?subject=${encodeURIComponent('Lamina report: ' + cut(fd.get('what').split(/\r?\n/)[0], 80))}`
  + `&body=${encodeURIComponent(cut(asText(fd), 1500) + (file ? `\n\n(please attach ${file.name})` : ''))}`;

// GitHub prefills an issue form by field id (bug_report.yml) and refuses a URL over roughly 8 kB, so this is trimmed
function issueUrl(fd, file) {
  const q = new URLSearchParams({template: 'bug_report.yml', what: cut(fd.get('what'), 3000)});
  if (fd.get('technique')) q.set('technique', fd.get('technique'));
  if (fd.get('summary')) q.set('report', cut(fd.get('summary'), 2500));
  q.set('repro', file ? `The attached project file (${file.name}) carries the model and every setting.` : '');
  q.set('version', cut(fd.get('agent'), 300));
  return ISSUE + '?' + q;
}

addEventListener('click', e => { const a = e.target.closest('[data-feedback]'); if (a) { e.preventDefault(); show() } });
window.__feedback = {show, build, mailto, issueUrl};      // test hook (tests/test_e2e_site.py)
})();
