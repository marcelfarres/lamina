// "Report a problem", "share your machine", "share your material" — one dialog on the landing page and in the
// app, opened by any element carrying data-feedback (empty = a bug report, "machine" or "material" = one to ship
// with Lamina). The links point at the GitHub issue form underneath, so they still work with this script missing
// or JavaScript off; the dialog only takes over when it is there.
//
// It hosts nothing and posts nowhere. The report is gathered here and handed to whichever of the two ways out the
// reporter prefers — an email, or the GitHub issue form — both opened prefilled, both sent by them. A server that
// took reports automatically would save one click and cost a public endpoint, a token and its upkeep; this does
// not, and it works the same in the published site, in Docker and on a laptop with no network at all. A machine
// or material goes the same two ways and is added to the built-in list by hand: the numbers are read, never run.
//
// What it gathers is the point: a page says what it can attach with  laminaFeedback({bug, machine, material}),
// where bug(withModel) resolves to {technique, summary, file} — file being the project file, which carries the
// model itself only when withModel — and the other two to {summary}, that one thing as JSON and nothing else. The
// landing page registers nothing, so there the dialog is the description alone.
(() => {
const ISSUE = 'https://github.com/marcelfarres/lamina/issues/new';
const MAIL = 'lamina.3d.app@gmail.com';        // the project's own address: a report never depends on holding an account
const collect = {};
window.laminaFeedback = fns => Object.assign(collect, fns);

// the things the dialog can be, and the issue template (with its field ids) each one lands in
const KIND = {
  bug: {title: 'Report a problem', lead: 'Lamina is an alpha and this is the quickest way to a fix. Nothing is too small.',
        ask: 'What went wrong', hint: '— what you did, what you saw, what you expected instead',
        eg: 'Interlocked, 5 × 4 on the egg: part X-3 has a slot cut clean through the outline.',
        template: 'bug_report.yml', field: 'report', subject: 'Lamina report: '},
  machine: {title: 'Share your machine', lead: 'A machine with its kerf and slot offset measured on the real thing is worth more than any default: shared, it ships with Lamina and the next person who owns one starts from it.',
        ask: 'Which machine', hint: '— make and model, and whether the kerf and slot offset come from a test cut',
        eg: 'xTool P2 (55 W CO2); kerf measured on 3 mm birch, slot offset from the fit test.',
        template: 'preset.yml', field: 'settings', kind: 'Machine', subject: 'Lamina machine: '},
  material: {title: 'Share your material', lead: 'A material with the thicknesses and sheet sizes it really comes in saves the next person the hunt: shared, it ships with Lamina.',
        ask: 'Which material', hint: '— what it is, where it is from, and what you cut it on',
        eg: '3 mm baltic birch from Home Depot, cut on a K40.',
        template: 'preset.yml', field: 'settings', kind: 'Material', subject: 'Lamina material: '},
};

const CSS = `
#fb_dlg{width:min(580px,92vw);border:1px solid var(--line,#2f3138);border-radius:10px;background:var(--panel,#1c1d21);color:var(--ink,#e6e6e3);padding:22px;font:14px/1.55 Inter,system-ui,sans-serif}
#fb_dlg::backdrop{background:#000b}
#fb_dlg h3{margin:0 0 6px;font-size:18px}
#fb_dlg label{display:block;margin:14px 0 0}
#fb_dlg [hidden]{display:none}
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
  bug: `What goes with your report: the technique, every setting, and what the checks said. With the box ticked the model file is saved alongside it for you to attach — that is what makes a report reproducible, so please do, unless it is a model you are not free to share. Nothing is sent by this page: your mail program or the GitHub form opens with everything filled in, and you press send. An issue on GitHub is public; an email is not.`,
  page: `What goes with your report: your description, the address of this page and your browser version. No model and no settings — this page has none. Nothing is sent by this page: your mail program or the GitHub form opens with it filled in, and you press send. An issue on GitHub is public; an email is not.`,
  machine: `What goes with it: the machine as selected — its name, kerf, slot offset, corner relief, tool diameter and bed size. No model, no material, no other settings. Nothing is sent by this page: your mail program or the GitHub form opens with it filled in, and you press send. An issue on GitHub is public; an email is not.`,
  material: `What goes with it: the material as selected — its name, the thickness and sheet size in use and the ones you added for it. No model, no machine, no other settings. Nothing is sent by this page: your mail program or the GitHub form opens with it filled in, and you press send. An issue on GitHub is public; an email is not.`,
};

const FORM = k => `<form id="fb_form">
  <h3>${k.title}</h3>
  <p class="m" style="margin:0">${k.lead}</p>
  <label>${k.ask} <span class="m">${k.hint}</span>
    <textarea id="fb_what" rows="5" required placeholder="${k.eg}"></textarea></label>
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
let kind = 'bug';

function show(k = 'bug') {
  kind = Object.hasOwn(KIND, k) ? k : 'bug';
  dlg.innerHTML = FORM(KIND[kind]);                            // a fresh form every time, from this file's own strings only
  $('#fb_att').hidden = !(kind === 'bug' && collect.bug);
  $('#fb_warn').textContent = WARN[collect[kind] ? kind : 'page'];
  $('#fb_no').onclick = () => dlg.close();
  $('#fb_gh').onclick = () => hand('github');
  $('#fb_form').onsubmit = e => { e.preventDefault(); hand('email') };   // submit = the default button, so Enter sends
  dlg.showModal();
  $('#fb_what').focus();
}

// Everything the report carries, as the fields a form post would have used — one shape, whichever way it goes out.
async function build() {
  const withModel = !$('#fb_att').hidden && $('#fb_tick').checked;
  const got = collect[kind] ? await collect[kind](withModel) : null;
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
  if (via === 'email') sendMail(mailto(fd, file)); else open(issueUrl(fd, file), '_blank', 'noopener');
  $('#fb_note').textContent = (via === 'email' ? 'Your mail program should be opening.' : 'The issue form is open in another tab.')
    + (file ? ` Please attach ${file.name} — it was just saved to your downloads.` : '');
}

// A mailto: in this tab is not safe: with a web mail handler (Gmail is the common one) the browser navigates the tab
// to the compose page and the job is gone. A new tab instead; a desktop mail program leaves that tab blank, and the
// blank is closed again — a tab that went to a web client is cross-origin by then, which the try swallows.
function sendMail(url) {
  const w = open(url, '_blank', 'noopener');
  setTimeout(() => { try { if (w && w.location.href === 'about:blank') w.close() } catch {} }, 2000);
}

// the same record either way, as plain text
const asText = fd => [fd.get('what'), '', `technique: ${fd.get('technique') || '—'}`, `page: ${fd.get('page')}`,
                      `browser: ${fd.get('agent')}`, '', fd.get('summary') || ''].join('\n');

// long mailto bodies are cut by some clients, so the settings are trimmed; the attached project file has them all
const mailto = (fd, file) =>
  `mailto:${MAIL}?subject=${encodeURIComponent(KIND[kind].subject + cut(fd.get('what').split(/\r?\n/)[0], 80))}`
  + `&body=${encodeURIComponent(cut(asText(fd), 1500) + (file ? `\n\n(please attach ${file.name})` : ''))}`;

// GitHub prefills an issue form by field id and refuses a URL over roughly 8 kB, so this is trimmed
function issueUrl(fd, file) {
  const k = KIND[kind], q = new URLSearchParams({template: k.template, what: cut(fd.get('what'), 3000)});
  if (fd.get('technique')) q.set('technique', fd.get('technique'));
  if (fd.get('summary')) q.set(k.field, cut(fd.get('summary'), 2500));
  if (k.kind) q.set('kind', k.kind);                            // the template's dropdown, prefilled by option text
  if (kind === 'bug') q.set('repro', file ? `The attached project file (${file.name}) carries the model and every setting.` : '');
  q.set('version', cut(fd.get('agent'), 300));
  return ISSUE + '?' + q;
}

addEventListener('click', e => { const a = e.target.closest('[data-feedback]'); if (a) { e.preventDefault(); show(a.dataset.feedback) } });
window.__feedback = {show, build, mailto, issueUrl, sendMail};      // test hook (tests/test_e2e_site.py)
})();
