// ---------------------------------------------------------------- the library page
// The library drawn as cards, the top bar's library and save, and the question a save onto another revision asks.
// What save, open and delete do is library.js's: this draws its listing and asks before anything is lost.
import {$, $$, esc, status} from './util.js';
import {state, ST} from './state.js';
import * as lib from './library.js';

let ex={}, shown=[], opened=new Set(), listing=0, drawn='', toExamples=false;   // ex: the examples and how to open one, for the Examples section; toExamples: scroll there once Yours is drawn
// busy: saves, links and imports under way. The folder buttons wait for them: a second link would start, and a
// reconnect queued behind them loses the click its prompt needs. rec: a reconnect under way; note: the page's last
// message, shown under the folder line (the status line is under the library page)
let busy=0, rec=false, note='', saving=false, failed='';   // failed: the note a listing error left, cleared by the next good listing
const two=n=>String(n).padStart(2,'0');
const when=iso=>{const d=new Date(iso);return `${d.getFullYear()}-${two(d.getMonth()+1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`};
// the picture comes from a file: anything but a picture is shown as none
const pic=(src,name)=>String(src).startsWith('data:image/')?`<img src="${esc(src)}" alt="">`:`<div class="ph">${esc(name)}</div>`;
const plural=(n,w)=>`${n} ${w}${n===1?'':'s'}`;
// a list of files in a message: five by name at most, so the note stays a line or two
const few=l=>l.length>5?`${l.slice(0,5).join(', ')} and ${l.length-5} more`:l.join(', ');

function card(p,now){const r=p.revs[0], n=p.revs.length;
  // an unreadable file is listed by its file name, and Lamina neither opens nor deletes it
  if(r.bad)return `<div class="card bad" data-name="${esc(p.name)}"><div class="ph">⚠</div><div class="t"><div class="n">${esc(r.file)}</div><div class="m">⚠ cannot be read</div></div></div>`;
  const on=p.revs.some(v=>v.file===now?.file), open=opened.has(p.name);
  return `<div class="card${on?' on':''}${open?' wide':''}" data-name="${esc(p.name)}">${pic(r.preview,p.name)}
    ${on?'<span class="now">✓ open now</span>':''}<button class="more">${plural(n,'revision')} ${open?'▴':'▾'}</button>
    <div class="t"><div class="n">${esc(p.name)}</div><div class="m">v${esc(r.rev)} · ${when(r.saved)}</div></div>
    ${open?`<div class="revs">${p.revs.map(v=>`<div class="rev" data-file="${esc(v.file)}"><b>v${esc(v.rev)}</b><span class="sp">${when(v.saved)}${v.file===now?.file?' · ✓ open now':''}</span>
      <button class="small open">open</button><button class="small export">export</button><button class="small delete">✕ delete</button></div>`).join('')}
      <div><span class="sp">the whole project</span><button class="small exportproject">export all ${n}</button><button class="small deleteproject">✕ delete project</button></div></div>`:''}</div>`}
// an example is the server's file: opened, it is the model in hand, and a save of it is a new project of yours
const exCard=n=>`<div class="card" data-example="${esc(n)}"><img src="static/examples/${esc(n)}.webp" alt=""><div class="t"><div class="n">${esc(n)}</div><div class="m">example · read-only</div></div></div>`;

// listed again on every show and change; a listing that finishes after a newer one started is dropped, and one that
// draws what is there is not drawn again: a slice tells onChange twice, and a re-draw takes the button under the pointer
async function render(){const k=++listing, ps=await lib.entries().catch(e=>{
    const s=lib.storeState();if(s.state!=='needs-permission'&&!s.problem){tell(`Library not listed: ${e.message}`,'err');failed=note}return null});   // those the folder line says
  if(k!==listing)return;
  if(ps&&failed){if(note===failed)note='';failed=''}
  where();
  // no cards of a library that cannot be listed (they would not open): where they are instead
  if(!ps){const s=lib.storeState();$('#libyours').innerHTML=drawn=s.state==='needs-permission'?`<p class="hint">Your projects are in <b>${esc(s.label)}</b>. Reconnect it to see them here.</p>`:'';return}
  const y=$('#libyours'), now=lib.inHand();shown=ps;
  const html=ps.length?`<h2>Yours · ${plural(ps.length,'project')}</h2><div class="grid">${ps.map(p=>card(p,now)).join('')}</div>`
    :'<p class="hint">No projects yet. Save one with <b>save</b>, or import files.</p>';
  if(html!==drawn){y.innerHTML=drawn=html;find()}
  if(toExamples){toExamples=false;$('#libexamples').scrollIntoView()}   // after Yours is drawn: drawing it moves the section
  y.dataset.listed=1}
// where the library is kept, said in words and an icon (📁, ⚠, 💾), with what can be done about it. A problem (the
// server cannot write its folder, start-up could not read where the library is) is the line, with its fix in it
function where(){const s=lib.storeState(), b=(id,t)=>`<button class="small" id="${id}"${busy?' disabled':''}>${t}</button>`;
  const it=s.browser===1?'it':'them', stayed=s.left?` Your files stayed in <b>${esc(s.left)}</b>.`:'',
    have=s.browser?` ${plural(s.browser,'revision')} ${s.browser===1?'is':'are'} still in this browser`:'',
    still=have&&`${have}: unlink to see ${it}, or press ${s.state==='folder'?'change folder':'pick another folder'} and pick <b>${esc(s.label)}</b> to move ${it}.`;
  const [line,buttons]=s.problem?[`⚠ ${esc(s.problem)}`,'']
    :s.state==='server'?[`📁 kept in the folder <b>${esc(s.label)}</b> on the server · ${plural(s.files,'file')}.${have&&have+'.'}${stayed}`,s.browser?b('libtoserver',`move ${it} to the server folder`):'']
    :s.state==='folder'?[`📁 kept in the folder <b>${esc(s.label)}</b> · ${plural(s.files,'file')}.${still}${stayed}`,b('libchange','change folder')+b('libunlink','unlink')]
    :s.state==='needs-permission'?[`⚠ The linked folder <b>${esc(s.label)}</b> cannot be reached.${still}`,b('libreconnect',rec?'reconnecting…':'reconnect folder')+b('libchange','pick another folder')+b('libunlink','unlink')]
    :['💾 kept in this browser only. Clearing the site data deletes them: use <b>export all</b> for a backup.'+stayed,
      lib.canLink()?b('liblink','link a folder'):'<button class="small" id="liblink" disabled title="needs Chrome or Edge">link a folder (needs Chrome or Edge)</button>'];
  $('#libwhere').innerHTML=`<span>${line}</span><span class="sp"></span>${buttons}${note?`<div class="note">${esc(note)}</div>`:''}`}
const redraw=()=>$('#library').hidden?where():render();
// a message of the library page: under its folder line, where it is seen (⚠ for one that needs the person), and on
// the status line for when the page is closed
function tell(text,kind=''){note=(kind==='err'?'⚠ ':'')+text;status(text,kind);where()}
async function hold(f){busy++;where();try{return await f()}finally{busy--;where()}}
// The browser's prompt needs the click it came from: lib.reconnect() asks at once, before anything here waits
function reconnect(){const {label}=lib.storeState(), p=lib.reconnect();rec=true;
  return hold(()=>p).catch(()=>false).then(ok=>{rec=false;
    tell(ok?`reconnected the folder ${label}`:`Not reconnected: the linked folder ${label} cannot be reached. Reconnect it and allow Lamina to use it, pick another folder, or unlink it.`,ok?'':'err');
    redraw();return ok})}
// a revision by its file name, as the person knows it: "bunny plaque v1.0"
const named=f=>{const m=/^(.*)_v(.+)\.lamina\.json$/.exec(f);return m?`${m[1]} v${m[2]}`:f};
// what a move did (a link, or the move into the server's folder): how many moved, and each revision that stayed in
// this browser, that it is safe, why, and what to do. `did` names the move; again(it) says how to move the rest
function told(did,{moved,skipped,changed,kept,refused},again){const no=refused.map(r=>r.file), asked=skipped.filter(f=>!changed.includes(f)&&!no.includes(f)),
    left=skipped.length-no.length, it=left===1?'it':'them', out=[`${did}${skipped.length?', not all moved':''}: ${plural(moved.length,'revision')} moved into it.`];
  if(kept.length)out.push(`${few(kept.map(k=>`${k.rev} as v${k.as}`))} moved in as a new revision instead of replacing, as the folder's file cannot be read.`);
  if(asked.length)out.push(`${few(asked.map(named))} stayed in this browser, safe: the folder already had that revision and the question was cancelled.`);
  if(changed.length)out.push(`${few(changed.map(named))} stayed in this browser, safe: another tab saved ${changed.length===1?'it':'them'} again during the move (the folder has the copy from before).`);
  if(refused.length)out.push(`${few(refused.map(r=>`${named(r.file)} (${r.why})`))} stayed in this browser, safe: the folder did not take ${refused.length===1?'it':'them'}. Export ${refused.length===1?'it':'them'} to keep a copy.`);
  if(left)out.push(again(it));
  return out.join(' ')}
async function pick(){let dir;
  try{dir=await window.showDirectoryPicker({mode:'readwrite'})}catch(e){if(e.name!=='AbortError')tell(`Not linked: ${e.message}`,'err');return}   // closed: nothing to do
  tell(`linking ${dir.name}…`,'busy');
  try{const r=await hold(()=>lib.linkFolder(dir,c=>askClash(c,true,'link')));
    tell(told(`Linked ${dir.name}`,r,it=>`To move ${it}, press change folder, pick ${dir.name} again and choose keep both. To see ${it} or export ${it}, unlink.`),r.skipped.length?'err':'')}
  catch(e){tell(`Not linked: ${e.message}`,'err')}
  redraw()}
// the browser's revisions into the server's folder, asked about as a link asks
async function toServer(){const {label}=lib.storeState();tell(`moving the projects into ${label}…`,'busy');
  try{const r=await hold(()=>lib.moveToServer(c=>askClash(c,true,'link')));
    tell(told(`Server folder ${label}`,r,it=>`To move ${it}, press move ${it} to the server folder again and choose keep both.`),r.skipped.length?'err':'')}
  catch(e){tell(`Not moved: ${e.message}`,'err')}
  redraw()}
async function unlink(){try{await hold(lib.unlink);note='';status(`unlinked: the library is this browser again. Your files stayed in ${lib.storeState().left}.`)}catch(e){tell(`Not unlinked: ${e.message}`,'err')}redraw()}
function onWhere(e){const id=e.target.closest('button')?.id;
  if(id==='libreconnect')reconnect();else if(id==='libunlink')unlink();else if(id==='liblink'||id==='libchange')pick();else if(id==='libtoserver')toServer()}

// a download the page's way (scene.js's video): a link to the blob, clicked
async function down(f){try{const {name,blob}=await f(), a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),60000)}catch(e){tell(`Not exported: ${e.message}`,'err')}}
const WHY={twice:'this import had that revision twice',unreadable:'the file there cannot be read'};
async function importNow(files){if(!files.length)return;tell(`importing ${plural(files.length,'file')}…`,'busy');
  try{const {imported,bad,skipped,kept}=await hold(()=>lib.importFiles(files,c=>askClash(c,true,'import')));
    tell([`imported ${plural(imported.length,'file')}`,   // what was not imported second: the cut status line still says it
      bad.length&&`Not imported, as they cannot be read: ${few(bad)}`,
      kept.length&&`${kept.length} kept as a new revision instead of replacing: ${few(kept.map(k=>`${k.rev} as v${k.as} (${WHY[k.why]})`))}`,
      skipped.length&&`${skipped.length} skipped, as you kept what the library had: ${few(skipped)}`].filter(Boolean).join('. '),bad.length?'err':'')}
  catch(e){tell(e.message,'err')}
  redraw()}

function find(){const q=$('#libfind').value.trim().toLowerCase();for(const c of $$('#library .card'))c.hidden=!(c.dataset.name??c.dataset.example).toLowerCase().includes(q)}

const leave=()=>!lib.unsaved()||confirm('This tab has unsaved changes. Open anyway and lose them?');
async function open(file){if(!leave())return;hideLibrary();try{await lib.openRevision(file)}catch(e){status(`Not opened: ${e.message}`,'err')}}
async function act(f){try{await f()}catch(e){tell(`Not deleted: ${e.message}`,'err')}render()}   // a delete
async function onCard(e){const c=e.target.closest('.card');if(!c||c.classList.contains('bad'))return;
  const name=c.dataset.name, p=shown.find(p=>p.name===name), b=e.target.closest('button'), file=e.target.closest('.rev')?.dataset.file;
  if(!p)return;
  if(b?.matches('.more')){opened.has(name)?opened.delete(name):opened.add(name);return render()}
  if(b?.matches('.open'))return open(file);
  // a delete removes what this card shows: a revision saved again since (another browser) stays
  if(b?.matches('.delete')){const v=p.revs.find(v=>v.file===file);if(confirm(`Delete ${name} v${v.rev}? It cannot be undone.`))act(()=>lib.removeRevision(file,v));return}
  if(b?.matches('.deleteproject')){if(confirm(`Delete the project ${name} and its ${plural(p.revs.length,'revision')}? It cannot be undone.`))act(()=>lib.removeProject(name,p.revs));return}
  if(b?.matches('.export'))return down(()=>lib.exportRevision(file));
  if(b?.matches('.exportproject'))return down(()=>lib.exportProject(name));
  if(b||e.target.closest('.revs'))return;   // the space between the rows
  open(p.revs[0].file)}
function onExample(e){const c=e.target.closest('.card');if(c&&leave()){hideLibrary();ex.openExample(c.dataset.example)}}

export function showLibrary(){$('#library').hidden=false;delete $('#libyours').dataset.listed;return render()}
// closed, it keeps no cards (nor which were expanded) and drops a listing on its way: a reopen draws from a new
// listing, every card short, never under the pointer
export function hideLibrary(){$('#library').hidden=true;listing++;toExamples=false;opened.clear();note='';failed='';where();$('#libyours').innerHTML=drawn=''}
// before the first technique there is nothing to compare, and the change listeners call this from the start
export function refreshUnsaved(){if(ST.mode)$('#punsaved').hidden=!lib.unsaved()}

// a save, import or link onto a revision that is already there: 'replace' | 'keep' | null, asked in the action's own
// words. `many` (an import, a link) shows the box that says the answer holds for the rest; ticked, the answer comes as
// {answer, rest:true}
const WORDS={save:['Save over another revision?','is already in the library, and it is not the revision this tab opened or last saved.','save this as'],
  import:['Import onto a revision already there?','is already in the library.','import this as'],
  link:['Move onto a revision already there?','is already in the folder.','move this in as']};
export function askClash({name,rev,next},many=false,how='save'){const d=$('#libask'), [title,msg,as]=WORDS[how];
  $('#libask h3').textContent=title;$('#libask_msg').textContent=`${name} v${rev} ${msg}`;
  $('#libask_replace').textContent=`replace v${rev}`;$('#libask_keep').textContent=`keep both: ${as} v${next}`;
  $('#libask_rest').checked=false;$('#libask_restl').hidden=!many;d.returnValue='';d.showModal();
  return new Promise(ok=>d.addEventListener('close',()=>{const a=d.returnValue||null;ok(many&&$('#libask_rest').checked?{answer:a,rest:true}:a)},{once:true}))}

export function initLibraryPage(o){ex=o;
  // library and save ask for the folder again from their click (a reload loses Chrome's permission unless kept)
  $('#popen').onclick=async()=>{if(lib.storeState().state==='needs-permission')await reconnect();showLibrary()};
  $('#libclose').onclick=hideLibrary;$('#libyours').onclick=onCard;$('#libfind').oninput=find;$('#libwhere').onclick=onWhere;
  $('#libimport').onclick=()=>{const i=document.createElement('input');i.type='file';i.multiple=true;i.accept='.json,.zip';i.onchange=()=>importNow([...i.files]);i.click()};
  $('#libexportall').onclick=()=>down(async()=>{const r=await lib.exportAll();
    if(r.skipped.length)tell(`Not all exported: ${r.name} leaves out ${plural(r.skipped.length,'file')} that cannot be read: ${few(r.skipped)}`,'err');return r});
  // files dropped on the page are imported, not opened by the browser
  $('#library').ondragover=e=>e.preventDefault();$('#library').ondrop=e=>{e.preventDefault();importNow([...e.dataTransfer.files])};
  $('#libexamples').innerHTML=`<h2>Examples · open one, save it, and it becomes a project of yours</h2><div class="grid">${o.examples.map(exCard).join('')}</div>`;
  $('#libexamples').onclick=onExample;
  $('#exopen').onclick=()=>{toExamples=true;showLibrary()};
  // a save that fails after its file was written says so in its own words. A save names the project's own name and
  // revision as they stand after it (a fallback name, or a 'keep' that took the next revision, are in them by then),
  // not the library's revision in hand: there is none when the store changed meanwhile
  // A second press while a save runs writes nothing (the library answers it with the first one's result): it says so
  // rather than "saved", and the unsaved marker tells whether changes made since are in the file
  $('#psave2').onclick=async()=>{if(saving)return status('Not saved: another save is under way. Press save again once it is done.');
    // with the folder out of reach the prompt is asked for first and the save started at once after it, both inside the
    // click: the save is fixed at the press (not when the prompt is answered) and waits in the queue behind the reconnect
    saving=true;const r=lib.storeState().state==='needs-permission'?reconnect():null;
    // a save to the server's folder sends the whole project, model and all: the line says it is under way, and a
    // cancelled question puts the line back as it was
    const was=[$('#status').textContent,$('#dot').className], far=lib.storeState().kind==='server';if(far)status('saving…','busy');
    try{const ok=await hold(()=>lib.saveCurrent(askClash));await r;if(ok)status(`saved ${state.project} v${state.rev}`);else if(far)status(...was)}
    catch(e){await r;status(e.saved?e.message:`Not saved: ${e.message}`,'err')}finally{saving=false}};   // the failure first: the line is cut
  for(const a of ['replace','keep','cancel'])$('#libask_'+a).onclick=()=>$('#libask').close(a==='cancel'?'':a);
  addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#library').hidden&&!document.querySelector('dialog[open]'))hideLibrary()});
  // the Model tab's button names the example in hand (a slice tells onChange once its job is back)
  lib.onChange(()=>{refreshUnsaved();$('#exopen').textContent=ST.job?.startsWith('ex_')?`${ST.job.slice(3)} · pick another…`:'pick an example…';
    if(!$('#library').hidden)render()})}
