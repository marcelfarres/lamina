import {state, ST} from './state.js';
import {CLIENT, $, $$, status, esc} from './util.js';
import {inUnit} from './units.js';
import {record, act} from './history.js';
import {kind} from './presets.js';
import {renderSpacing} from './spacing.js';
import {memo, syncSizeHints} from './form.js';
import {render3D, showGhost} from './scene.js';
import {renderSheets, renderReport, SH} from './results.js';
import {changed} from './library.js';

// ---------------------------------------------------------------- slicing
export async function slice(){
  record(); changed();                             // one undo step per change that gets this far; the unsaved-changes text follows it
  if(ST.fresh){ST.trail=[];ST.trailT0=Date.now();act(ST.fresh);ST.fresh='';   // after record(): a new model's own settings are not steps
    for(const d of $$('section[data-tab="export"] details'))d.open=false}  // a new job's Export tab opens as drawn: no section of the last job left open
  const my=++ST.seq, fd=new FormData(), loading=ST.pendingFile;
  fd.append('client',CLIENT); fd.append('mode',ST.mode.name); fd.append('params',JSON.stringify({...state,light:undefined,lights:undefined,room:undefined,light_video:undefined,material_kind:kind(state.material)})); fd.append('memo',JSON.stringify(memo));   // the server keeps this as the tab's session; a material of your own is checked as the one it was made from
  if(ST.pendingFile)fd.append('model',ST.pendingFile); else if(ST.job)fd.append('job',ST.job); else fd.append('example',ST.example);
  status('slicing…','busy'); $('#busy').hidden=false; $('#busy_txt').textContent='slicing…'; $('#busy_note').textContent=''; $('#busy .bar').className='bar';
  expectStages(); $('#busy_steps').innerHTML=''; ST.ghostLive=false;   // this slice's own stages, counted from the settings it runs with
  ST.busy=true; ST.busySince=Date.now(); const t0=ST.busySince;
  pollProgress(my);
  try{
    const r=await fetch('api/slice',{method:'POST',body:fd});
    const j=await r.json().catch(()=>({detail:r.statusText||`HTTP ${r.status}`}));   // a refusal before the app (413) is not JSON
    if(my!==ST.seq)return;
    // the server was updated under an open tab: this page is the old one, so fetch it again (once — never a loop)
    if(r.status===422&&!sessionStorage.reloaded){sessionStorage.reloaded=1;return location.reload()}
    if(!r.ok)throw new Error(typeof j.detail==='string'?j.detail:j.detail?JSON.stringify(j.detail):r.statusText);   // a 422 details itself as objects
    if(ST.pendingFile)ST.srcFile=ST.pendingFile; ST.pendingFile=null; ST.job=j.job; ST.plan=j.plan; const t1=Date.now();
    render3D(j.model); renderSheets(j.sheets); renderReport(); syncSizeHints(); renderSpacing();
    status(`ready · ${j.took} s · ${ST.plan.counts.parts} parts · ${ST.plan.sheets} ${SH()}(s) · ${ST.plan.counts.errors} errors`,ST.plan.counts.errors?'err':'');
    act(`sliced in ${j.took} s: ${ST.plan.counts.parts} parts, ${ST.plan.counts.errors} errors, ${ST.plan.counts.warnings} warnings`);
    // where the time went, for anyone tuning it: the build's stages (seconds), the round trip around them, and the page's own drawing
    console.info('lamina timing', ST.mode.name, {...ST.plan.timing, 'round trip beyond the build': +((t1-t0)/1000-j.took).toFixed(2), 'page drawing': (Date.now()-t1)/1000});
  }catch(e){if(my===ST.seq){act('slice failed: '+e.message); status('error: '+inUnit(e.message),'err'); if(loading)modelFailed(loading,e.message)}}
  if(my===ST.seq){$('#busy').hidden=true;ST.busy=false;changed()}   // and once it is back: an upload now has its job
}
// The model never arrived, so the 3D view still shows the one before it and the file box still names this one —
// which is exactly how a failed upload reads as "it loaded the wrong model". Clear the box and say so in a dialog:
// a line of red text in the header is missed precisely when it matters most.
function modelFailed(file,msg){
  ST.pendingFile=null; $('#file').value='';
  const big=/too large|over \d+ *MB|up to \d+ MB|Memory|allocat/i.test(msg);
  popup(`${file.name} could not be loaded`, msg,
    (big?`<p>That file is ${(file.size/1e6).toFixed(0)} MB. ${document.documentElement.dataset.static?'This published version runs entirely inside your browser, which is why there is a ceiling at all.':''}
       Running Lamina on your own computer has no size limit and is far faster — <a href="${LOCAL_DOC}" target="_blank" rel="noopener">how to install it</a> (a double-click installer, or one command).
       Or open the model in your 3D program and reduce / decimate it to fewer triangles first.</p>`
      :`<p>Try another file, or <a data-feedback href="https://github.com/marcelfarres/lamina/issues/new?template=bug_report.yml" target="_blank" rel="noopener">report it</a> if the model is fine elsewhere.</p>`)
    +`<p style="color:var(--muted);font-size:12.5px">The view still shows <b>${ST.job&&ST.job.startsWith('ex_')?ST.job.slice(3):'the previous model'}</b> — nothing about your job has changed.</p>`);
}
export const LOCAL_DOC='https://marcelfarres.github.io/lamina/#start';
// one dialog for everything fatal: a model that did not load, a file big enough to be worth a warning first
export const oops=$('#oops');
export function popup(title,msg,help,ok='OK',onOk=null){
  $('#oops_title').textContent=title; $('#oops_msg').textContent=msg; $('#oops_msg').hidden=!msg;
  $('#oops_help').innerHTML=help; $('#oops_go').textContent=ok; $('#oops_no').hidden=!onOk;
  oops.returnValue=''; oops.onclose=()=>{if(onOk)onOk(oops.returnValue==='go')};   // onOk(false) = cancelled or Esc
  if(!oops.open)oops.showModal();
}
// the browser build reports build() stages (browser.js relays them); on a server they are polled, so the local
// version says what it is doing too instead of "slicing…" for a minute
async function pollProgress(my){
  while(my===ST.seq&&ST.busy){
    await new Promise(r=>setTimeout(r,500));
    if(my!==ST.seq||!ST.busy||document.documentElement.dataset.static)return;     // in the browser the worker posts them
    const d=await fetch(`api/progress?client=${CLIENT}`).then(r=>r.ok?r.json():null).catch(()=>null);
    if(d&&d.frac!==undefined&&my===ST.seq&&ST.busy)window.dispatchEvent(new CustomEvent('lamina-progress',{detail:d}));
  }
}
// What a slice is made of, in the order it happens, so a long wait has a shape: a bare percentage said nothing about
// how many of these there are, and the per-stage counters ("12 of 34") looked like the whole job restarting. The
// three marked 0 only run when the model asks for them, so they appear in the list only once they have.
const STAGES=[['loading the model',1],['modify form: remeshing',0],['smoothing',0],['preparing the preview model',1],
  ['placing slices and slots',1],['sectioning',1],['checking the parts and the assembly',1],
  ['nesting the parts on sheets',1],['measuring coverage',1]];
const seenStages=new Set();
// The two that only run when the model preparation asks for them are known from the settings before the slice
// starts, so the count is right from the first frame instead of growing under you. (A mesh that has to be remeshed
// because it will not close is the one case nobody can predict; that one appears when it happens.)
function expectStages(){seenStages.clear();
  if(state.shrinkwrap||state.hollow||state.thicken||state.round)seenStages.add('modify form: remeshing');
  if(state.smooth)seenStages.add('smoothing');}
function renderStages(now,detail){
  const rows=STAGES.filter(([n,always])=>always||seenStages.has(n)), at=rows.findIndex(([n])=>n===now), end=now==='done';
  $('#busy_steps').innerHTML=rows.map(([n],i)=>`<li class="${end||i<at?'done':i===at?'now':''}">${esc(n)}${i===at&&detail?' · '+esc(detail):''}</li>`).join('');
  return at<0?'':`step ${at+1} of ${rows.length}`;
}
// one overlay for both: the browser build's worker posts these, a server's are polled above
window.addEventListener('lamina-progress',e=>{
  const {progress:text,frac,model}=e.detail;
  if(model){showGhost(model);ST.ghostLive=true}        // the mesh, ready before the slices: show it now
  if(!ST.busy)return;
  const pct=Math.round(frac*100);
  if(text){                                         // a stage; an artifact on its own leaves the line where it was
    const [name,...rest]=text.split(' · '); seenStages.add(name);
    const step=renderStages(name,rest.join(' · '));
    $('#busy_txt').textContent=`${step?step+' · ':''}${name} · ${pct}%`;
  }
  $('#busy .bar').className='bar known';$('#busy .bar i').style.width=pct+'%';status(`slicing… ${pct}%`,'busy')});
// in the browser build a big model takes minutes where the local version takes seconds: say so once the wait is real
const SLOW_NOTE='Running in the browser: a detailed model takes minutes here, seconds in the local or Docker version (README → Quick start). It is working — the percentage moves.';
setInterval(()=>{if(ST.busy&&document.documentElement.dataset.static&&Date.now()-ST.busySince>20000&&!$('#busy_note').textContent)$('#busy_note').textContent=SLOW_NOTE},1000);

