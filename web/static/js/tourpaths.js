import {$, $$, esc, ls, lsSet} from './util.js';
import {state, ST} from './state.js';
import {MACHINES, MATERIALS} from './catalog.js';
import {start, card, tab} from './tour.js';
import * as lib from './library.js';
import {hold} from './history.js';

// The tour of the page, by machine: the start card asks what he makes with, then that machine's way from the model to
// its export button walks on an example made for it. No sentence here is the tour's own except the two cards: a
// setting's step says that setting's hover help (its schema help), the others the help dialog's line for that part,
// the techniques step each technique's own description. A reworded help changes the tour with it, and a part or a
// text that has gone fails tests/ui/test_tour_paths.py instead of leaving a step that says nothing.

// ---------------------------------------------------------------- reading the page
// whole sentences up to max characters; the rest under "more"
const cut=(s,max=220)=>{s=(s||'').replace(/`/g,'').replace(/\s+/g,' ').trim(); const ss=s.split(/(?<=[.!?])\s+(?=[A-Z(])/);
  let lead=ss[0]||'',i=1; for(;i<ss.length&&(lead+' '+ss[i]).length<=max;i++)lead+=' '+ss[i]; return {lead,more:ss.slice(i).join(' ')}};
const para=(s,max)=>{const {lead,more}=cut(s,max); return `<p>${esc(lead)}</p>${more?`<details><summary>more</summary><p>${esc(more)}</p></details>`:''}`};
const cap=s=>s.charAt(0).toUpperCase()+s.slice(1);
// the help dialog's line that starts with this bold word, without the word when a dash follows it
export const helpOf=bold=>{const li=$$('#helpdlg li').find(l=>l.querySelector('b')?.textContent.trim()===bold); if(!li)return '';
  const t=li.textContent.replace(/\s+/g,' ').trim(), r=t.slice(bold.length).trim(); return cap(r.startsWith('—')?r.slice(1).trim():t)};
const tipOf=row=>row?.querySelector('.k[data-tip]')?.dataset.tip||'';
const nameOf=row=>(row?.querySelector('.k')?.firstChild?.textContent||'').trim();
const textOf=q=>($(q)?.textContent||'').replace(/\s+/g,' ').trim();
// A row's help. A choice's help lists every choice ("a = … · b = …"): the one on show is said (or the ones a path
// names), the others only named.
function say(row,max,want){const t=tipOf(row).replace(/\s+/g,' ').trim(), sel=row.querySelector('select'), segs=t.split(' · ');
  if(!sel||segs.length<3)return para(t,max);
  const of=v=>segs.find(x=>x.startsWith(v+' =')), w=(want||[sel.value]).filter(of);
  return w.map(v=>`<p><b>${esc(v)}</b>: ${esc(cut(of(v).slice(v.length+2),max).lead)}</p>`).join('')
    +`<p class="hint">Other choices: ${esc(segs.map(x=>x.split(' =')[0]).filter(v=>!w.includes(v)&&v.length<20).join(', '))}</p>`}
// a technique's first clause, without its brackets
const short=d=>{d=(d||'').replace(/\s*\([^)]*\)/g,'').replace(/`/g,'').split(/\. |: | — /)[0].replace(/\.$/,''); return d.length>80?d.split(', ')[0]:d};
const idle=()=>new Promise(r=>{const f=()=>!ST.timer&&!ST.busy?r():setTimeout(f,200);f()});
const tabOf=el=>{const t=el?.closest('section[data-tab]')?.dataset.tab; if(t)tab(t)()};

// ---------------------------------------------------------------- the steps
// Rows of the form. The ring takes the first one on show and those right under it; a hidden row still gives its
// text. A row held back on basic, or in a folded section, is shown the page's own way (its section's "more", its heading).
const rows=(id,sels,{say:want}={})=>{const all=()=>sels.map(s=>$(s)).filter(Boolean);
  return {id,src:sels,
    open:()=>{const rs=all(); if(!rs.length)throw new Error('no row'); tabOf(rs[0]);
      for(const r of rs){const sec=r.closest('.sec'); if(sec?.classList.contains('folded'))sec.querySelector('h3.sub')?.click();
        if(!r.getClientRects().length&&r.classList.contains('adv'))sec?.querySelector(':scope>.more')?.click()}},
    target:()=>{const vis=all().filter(r=>r.getClientRects().length),ring=vis.slice(0,1);
      for(const r of vis.slice(1))if(r.getBoundingClientRect().top-ring.at(-1).getBoundingClientRect().bottom<70)ring.push(r);
      return sels.filter(s=>ring.includes($(s))).join(',')},
    title:()=>nameOf(all().find(r=>r.getClientRects().length)),
    text:()=>{const rs=all(); return rs.map(r=>say(r,rs.length>1?150:230,want)).join('')}}};
const param=(id,names,o)=>rows(id,names.map(n=>`.f[data-p="${n}"]`),o);
// a part of the page and the help dialog's lines for it
const help=(id,target,bolds,{open,title=bolds[0]}={})=>({id,src:bolds,target,open,title:cap(title),
  text:()=>bolds.map(b=>para(helpOf(b),bolds.length>1?150:220)).join('')});
const tabName=t=>textOf(`nav button[data-t="${t}"]`);

const model=help('model','label.f:has(#file),label.f:has(#exopen)',['Model'],{open:tab('model')});
const techniques={id:'techniques',src:['Technique'],target:'#modes',open:tab('technique'),title:()=>tabName('technique'),
  text:()=>para(helpOf('Technique'))+`<ul>${ST.MODES.map(m=>`<li><b>${esc(m.title)}</b>: ${esc(short(m.description))}</li>`).join('')}</ul>`};
const technique={id:'technique',src:['#mdesc'],target:'#modes button.on',open:tab('technique'),title:()=>textOf('#modes button.on').replace(/^✓\s*/,''),
  text:()=>para(textOf('#mdesc'))};
const level=help('level','#find,#level',['find a setting','basic / all'],{title:'basic / all'});
const material=rows('material',['.f:has(#material)','.f:has(#thicklist)']), machine=rows('machine',['.f:has(#machine)']);
const checks=help('checks','#lower',['Checks','sheets'],{open:async()=>{tab('checks')();await idle()}});
const view={id:'view',src:['tools','#hint summary'],target:'#tools',title:'Tools',
  text:()=>para(helpOf('tools'))+`<p>${esc(($('#hint summary')?.firstChild?.textContent||'').replace(/[\s·]+$/,''))}</p>`};
const light=help('light','label:has(#lamp)',['light']);
const library=help('library','#popen,#psave2',['library','save']);
const laserFit=param('fit-settings',['compensate','kerf','slot_offset']);

// The Export tab's parts. ponytail: today's ids; feature/export-tab gives #machines, #x_fit (#fit_what),
// #x_files a.main[data-machine] with its .hint, and #x_folded: they replace these when it merges
const EXPORT={summary:'#weight',fit:'#dlfit',fitText:'section[data-tab="export"] details.info.cutonly p.hint',
  main:{laser:['#dl .r:first-child','#dl .r:first-child .hint'],router:['#dl .r:first-child','#dl .r:first-child .hint'],
    printer:['#pr_go','#pr_go'],mix:['#two_machines','#two_machines']}};
const xSummary=help('x-summary',EXPORT.summary,['Export'],{open:async()=>{tab('export')();await idle()},title:tabName('export')||'Export'});
const xFit={id:'x-fit',src:[EXPORT.fitText],target:EXPORT.fit,open:tab('export'),title:()=>textOf('section[data-tab="export"] h2.cutonly'),text:()=>para(textOf(EXPORT.fitText))};
const xMain=m=>({id:'x-main',src:[EXPORT.main[m][1]],target:EXPORT.main[m][0],open:async()=>{tab('export')();await idle()},
  title:()=>textOf(m==='printer'?'#pr_title':'#dl_title'),text:()=>para(textOf(EXPORT.main[m][1]))});

const pick=(q,v)=>{const e=$(q); e.value=v; for(const k of ['input','change'])e.dispatchEvent(new Event(k,{bubbles:true}))};
export const PATHS={
  laser:{label:'Laser cutter',sub:'or a knife cutter, plasma, by hand',example:'vase',
    steps:[model,techniques,param('join',['connect','dowel_d']),level,material,machine,laserFit,checks,view,light,library,xSummary,xFit,xMain('laser')]},
  router:{label:'CNC router',sub:'a spinning bit',example:'torus',
    setup:()=>{pick('#material','plywood');pick('#thicklist','6');pick('#machine','shapeoko')},   // as the export review cut it
    steps:[model,techniques,technique,level,material,machine,param('bit',['relief','tool_d']),param('gap',['gap']),checks,view,library,xSummary,xFit,xMain('router')]},
  printer:{label:'3D printer',sub:'the parts printed',example:'fold_box',
    steps:[model,techniques,param('join',['joint','hinge'],{say:['click','snap']}),level,material,param('plate',['printed','sheet']),machine,param('labels',['font']),checks,view,light,library,xSummary,xMain('printer')]},
  mix:{label:'Laser + 3D printer',sub:'cut layers on printed standoffs',example:'shade',
    steps:[model,techniques,param('join',['connect','pin_fit']),level,material,machine,laserFit,checks,view,light,library,xSummary,xFit,xMain('mix')]}};
// which path a machine takes: a printer cuts nothing but print materials, a router has a bit
export const pathOf=k=>{const m=MACHINES[k]; if(!m)return 'laser';
  return m.cuts.length&&m.cuts.every(c=>MATERIALS[c]?.family==='print')?'printer':m.relief!=='square'||m.tool>0?'router':'laser'};

// ---------------------------------------------------------------- start and end
let openExample;   // main.js's: every way into an example goes through it
export function initTour(o){openExample=o.openExample; $('#tourbtn').onclick=()=>begin(false)}
// The first visit: once, after the first slice, when nothing else is on show (the phone notice first). Never in a
// browser driven by a program: the tests, the media recorder and the release pictures see the page as it is.
export function offer(){if(navigator.webdriver||ls('lamina.tour',null))return;
  const d=$('dialog[open]:not(#tourdlg)'); if(d)return d.addEventListener('close',offer,{once:true});
  try{lsSet('lamina.tour','offered')}catch(e){}   // a private window may refuse it: then it is offered each visit
  begin(true)}
// An example opens only when nothing can be lost (an example as it opened, or a saved revision with no changes); on
// work of his own the tour only points. The end card keeps the example or puts back what was there, undo stack too.
export async function begin(first){
  const own=!(ST.job?.startsWith('ex_')&&!lib.unsaved()), here=pathOf(state.machine);
  const ch=Object.entries(PATHS).map(([k,p])=>`<button class="pick" data-card="${k}"${k===here?' autofocus':''}><b>${esc(p.label)}</b><small>${esc(p.sub)}</small></button>`).join('');
  const k=await card(first?'New to Lamina?':'Tour of the page',`<p>What do you make with?</p><div class="ch">${ch}</div>
    <p class="hint">${own?'You have work of your own open: the tour points at the parts of it and changes nothing.':'About 14 steps, on an example made for your machine. Your own work is never changed.'}</p>
    <div class="row"><button class="skip" data-card="">Not now</button>${first?'<span class="hint">later: ? help ▾ → Tour of the page</span>':''}</div>`);
  const p=PATHS[k]; if(!p)return;
  try{lsSet('lamina.tour',k)}catch(e){}
  const was={example:ST.example,file:ST.saved?.file}, back=own?null:hold();
  if(!own){openExample(p.example); p.setup?.(); lib.baseline()}
  await start(p.steps.map(s=>({...s,over:`Tour · ${p.label}`})),{skip:'end the tour'});
  if(own)return;
  const how=await card('That is the whole tour',`<p>You are on the ${esc(p.example)} example, set up for: ${esc(p.label)}. Keep it to try things, or go back to the page as it was.</p>
    <div class="row"><button data-card="back">Back to where I was</button><button class="go" data-card="keep">Keep this example</button></div>`);
  if(how!=='back')return;
  if(was.file)await lib.openRevision(was.file); else openExample(was.example);
  back()}
