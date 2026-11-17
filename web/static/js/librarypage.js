// ---------------------------------------------------------------- the library page
// The library drawn as cards, the top bar's library and save, and the question a save onto another revision asks.
// What save, open and delete do is library.js's: this draws its listing and asks before anything is lost.
import {$, $$, esc, status} from './util.js';
import {state, ST} from './state.js';
import * as lib from './library.js';

let ex={}, shown=[], opened=new Set(), listing=0, drawn='', toExamples=false;   // ex: the examples and how to open one, for the Examples section; toExamples: scroll there once Yours is drawn
const two=n=>String(n).padStart(2,'0');
const when=iso=>{const d=new Date(iso);return `${d.getFullYear()}-${two(d.getMonth()+1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`};
// the picture comes from a file: anything but a picture is shown as none
const pic=(src,name)=>String(src).startsWith('data:image/')?`<img src="${esc(src)}" alt="">`:`<div class="ph">${esc(name)}</div>`;
const plural=(n,w)=>`${n} ${w}${n>1?'s':''}`;

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
async function render(){const k=++listing, ps=await lib.entries().catch(e=>{status(e.message,'err');return null});
  if(k!==listing||!ps)return;
  const y=$('#libyours'), now=lib.inHand();shown=ps;
  const html=ps.length?`<h2>Yours · ${plural(ps.length,'project')}</h2><div class="grid">${ps.map(p=>card(p,now)).join('')}</div>`
    :'<p class="hint">No projects yet. Save one with <b>save</b>, or import files.</p>';
  if(html!==drawn){y.innerHTML=drawn=html;find()}
  if(toExamples){toExamples=false;$('#libexamples').scrollIntoView()}   // after Yours is drawn: drawing it moves the section
  y.dataset.listed=1}
function find(){const q=$('#libfind').value.trim().toLowerCase();for(const c of $$('#library .card'))c.hidden=!(c.dataset.name??c.dataset.example).toLowerCase().includes(q)}

const leave=()=>!lib.unsaved()||confirm('This tab has unsaved changes. Open anyway and lose them?');
async function open(file){if(!leave())return;hideLibrary();try{await lib.openRevision(file)}catch(e){status(e.message,'err')}}
async function act(f){try{await f()}catch(e){status(e.message,'err')}render()}
async function onCard(e){const c=e.target.closest('.card');if(!c||c.classList.contains('bad'))return;
  const name=c.dataset.name, p=shown.find(p=>p.name===name), b=e.target.closest('button'), file=e.target.closest('.rev')?.dataset.file;
  if(!p)return;
  if(b?.matches('.more')){opened.has(name)?opened.delete(name):opened.add(name);return render()}
  if(b?.matches('.open'))return open(file);
  if(b?.matches('.delete')){const v=p.revs.find(v=>v.file===file);if(confirm(`Delete ${name} v${v.rev}? It cannot be undone.`))act(()=>lib.removeRevision(file));return}
  if(b?.matches('.deleteproject')){if(confirm(`Delete the project ${name} and its ${plural(p.revs.length,'revision')}? It cannot be undone.`))act(()=>lib.removeProject(name));return}
  if(b||e.target.closest('.revs'))return;   // export, and the space between the rows
  open(p.revs[0].file)}
function onExample(e){const c=e.target.closest('.card');if(c&&leave()){hideLibrary();ex.openExample(c.dataset.example)}}

export function showLibrary(){$('#library').hidden=false;delete $('#libyours').dataset.listed;return render()}
// closed, it keeps no cards (nor which were expanded) and drops a listing on its way: a reopen draws from a new
// listing, every card short, never under the pointer
export function hideLibrary(){$('#library').hidden=true;listing++;toExamples=false;opened.clear();$('#libyours').innerHTML=drawn=''}
// before the first technique there is nothing to compare, and the change listeners call this from the start
export function refreshUnsaved(){if(ST.mode)$('#punsaved').hidden=!lib.unsaved()}

// a save onto a revision that is not the one in hand: 'replace' | 'keep' | null. `many` (an import) shows the box that
// says the answer holds for the rest; ticked, the answer comes as {answer, rest:true}
export function askClash({name,rev,next},many=false){const d=$('#libask');
  $('#libask_msg').textContent=`${name} v${rev} is already in the library, and it is not the revision this tab opened or last saved.`;
  $('#libask_replace').textContent=`replace v${rev}`;$('#libask_keep').textContent=`keep both: save this as v${next}`;
  $('#libask_rest').checked=false;$('#libask_restl').hidden=!many;d.returnValue='';d.showModal();
  return new Promise(ok=>d.addEventListener('close',()=>{const a=d.returnValue||null;ok(many&&$('#libask_rest').checked?{answer:a,rest:true}:a)},{once:true}))}

export function initLibraryPage(o){ex=o;
  $('#popen').onclick=showLibrary;$('#libclose').onclick=hideLibrary;$('#libyours').onclick=onCard;$('#libfind').oninput=find;
  $('#libexamples').innerHTML=`<h2>Examples · open one, save it, and it becomes a project of yours</h2><div class="grid">${o.examples.map(exCard).join('')}</div>`;
  $('#libexamples').onclick=onExample;
  $('#exopen').onclick=()=>{toExamples=true;showLibrary()};
  // a save that fails after its file was written says so in its own words. A save names the project's own name and
  // revision as they stand after it (a fallback name, or a 'keep' that took the next revision, are in them by then),
  // not the library's revision in hand: there is none when the store changed meanwhile
  $('#psave2').onclick=async()=>{try{if(await lib.saveCurrent(askClash))status(`saved ${state.project} v${state.rev}`)}catch(e){status(e.message,'err')}};
  for(const a of ['replace','keep','cancel'])$('#libask_'+a).onclick=()=>$('#libask').close(a==='cancel'?'':a);
  addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#library').hidden&&!document.querySelector('dialog[open]'))hideLibrary()});
  // the Model tab's button names the example in hand (a slice tells onChange once its job is back)
  lib.onChange(()=>{refreshUnsaved();$('#exopen').textContent=ST.job?.startsWith('ex_')?`${ST.job.slice(3)} · pick another…`:'pick an example…';
    if(!$('#library').hidden)render()})}
