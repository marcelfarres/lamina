import * as THREE from 'three';
import {state, ST} from './state.js';
import {$$, $, status, esc, CLIENT} from './util.js';
import {highlight} from './edit3d.js';
import {fmtLen, fmtMass, fmtVol, fmtArea, DU, DUNIT, inU, inUnit, toMM} from './units.js';
import {act} from './history.js';
import {dens} from './presets.js';
import {renderFields, lenMM} from './form.js';
import {slice} from './slice.js';
import {parts} from './scene.js';
import {sheetSeams, toggleSeam} from './seams.js';

// ---------------------------------------------------------------- sheets + report
const pieceToSlice=()=>{const m={};for(const s of ST.plan?.slices||[])for(const pc of s.pieces)m[pc.label]=s.label;return m};
export function hlSheet(label){const map=pieceToSlice();let first=null;for(const p of $$('#sheets path[data-label]')){const on=label&&map[p.dataset.label]===label;p.classList.toggle('hl',on);if(on&&!first)first=p}
  if(first)first.scrollIntoView({block:'nearest',behavior:'smooth'})}
export function renderSheets(svgs){
  $('#sheets').innerHTML=svgs.map((s,i)=>`<div class="sheet"><div class="t"><span>sheet ${i+1} of ${svgs.length} — ${fmtLen(ST.plan.sheet[0])} × ${fmtLen(ST.plan.sheet[1])}${ST.plan.sheet_thick?.[i]?` · ${fmtLen(ST.plan.sheet_thick[i])} stock`:''}</span><a data-open="${i}">open full size ↗</a></div>${s}</div>`).join('');
  const bad=new Set(ST.plan.slices.filter(s=>s.errors.length).flatMap(s=>s.pieces.map(p=>p.label)));   // Slicer: red = part with a problem
  // status line: what is selected (so a click is never silent)
  if(ST.selected)status(`${$('#status').textContent.replace(/ · selected.*$/,'')} · selected ${ST.selected}`);
  for(const p of $$('#sheets path[data-label]'))if(bad.has(p.dataset.label))p.setAttribute('stroke','#ff5555');
  $('#sheets').onclick=e=>{const a=e.target.closest('a[data-open]');if(a){const s=$$('#sheets svg')[+a.dataset.open].cloneNode(true);s.querySelector('g.seams')?.remove();window.open(URL.createObjectURL(new Blob([s.outerHTML],{type:'image/svg+xml'})));return}
    const edge=e.target.closest('line.hit');if(edge)return toggleSeam(+edge.dataset.k);   // choosing seams: an edge of the net
    const p=e.target.closest('path[data-label]');if(!p)return;const lab=pieceToSlice()[p.dataset.label],m=parts.children.find(c=>c.userData.slice===lab);if(m)highlight(m)};
  if(ST.selected)hlSheet(ST.selected);
  sheetSeams();
}
export function applyFix(set){act('clicked a fix');for(const [k,v] of Object.entries(set)){if(v&&typeof v==='object'&&!Array.isArray(v))state[k]={...(state[k]||{}),...v};else if(Array.isArray(v)&&['skip','extra_x','extra_y'].includes(k))state[k]=[...new Set([...(state[k]||[]),...v])];else state[k]=v}renderFields();slice()}
// what the printed prototype parts come out at — and the re-plan the server does when that is under the printer's minimum
// a printed job is printed as it is: full size, with the job's own slot offset (its machine's, for that printer)
export const SH=()=>state.printed?'plate':'sheet';
function prScale(){const size=lenMM('#pr_size');return state.printed?1:size>0?size/Math.max(...ST.plan.bbox):(+$('#pr_scale').value||1)}
function protoHint(){if(!ST.plan)return;const s=prScale(),mn=lenMM('#pr_min',1.2);
  const thin=Math.min(...ST.plan.slices.map(x=>x.thickness)),printed=thin*s,h=$('#pr_hint');
  if(printed>=mn-1e-9){h.textContent=`parts print ${fmtLen(printed)} thick (${fmtLen(thin)} × ${s.toFixed(3)})`;h.style.color=''}
  else{h.textContent=`at ×${s.toFixed(3)} the ${fmtLen(thin)} parts would print ${fmtLen(printed)}, under the ${fmtLen(mn)} minimum — the set is planned again at ${fmtLen(mn/s)} material so the slots fit the printed parts (a note travels in the zip)`;h.style.color='var(--warn)'}}
// What the cut parts weigh: each part's own area (holes and slots taken out) × its slice's thickness × the density.
// A job that mixes thicknesses is cut from several stocks, and each gets a line; the sheets are what you buy and lift.
// Dowel rods are bought, not cut, and are taken to be of the job's material. The plan stores them a pair of slices at
// a time, overlapping by a slice, so collinear pieces are merged: an aligned dowel through the stack counts once.
function rodStats(){const lines=new Map(),q=x=>Math.round(x*100);
  for(const [a,b,dd,sec] of ST.plan.rods||[]){const v=b.map((x,i)=>x-a[i]),n=Math.hypot(...v),u=v.map(x=>x/n),s=a.reduce((t,x,i)=>t+x*u[i],0);
    const k=[...u,...a.map((x,i)=>x-s*u[i]),dd].map(q).join(),area=Math.abs(THREE.ShapeUtils.area(sec.map(([x,y])=>new THREE.Vector2(x,y))));
    (lines.get(k)||lines.set(k,[]).get(k)).push([s,s+n,area])}
  let len=0,vol=0;
  for(const iv of lines.values()){iv.sort((p,r)=>p[0]-r[0]);let [lo,hi,area]=iv[0],l=0;
    for(const [a,b] of iv.slice(1)){if(a>hi){l+=hi-lo;lo=a}hi=Math.max(hi,b)}l+=hi-lo;
    len+=l;vol+=l*area}
  return {n:lines.size,len,vol}}
export function renderWeight(){if(!ST.plan)return;const d=dens(),g=d/1000,by=new Map();   // g/cm³ → g per mm³
  for(const s of ST.plan.slices)for(const pc of s.pieces){const b=by.get(s.thickness)||{n:0,v:0};b.n++;b.v+=pc.area*s.thickness;by.set(s.thickness,b)}
  const parts=[...by.values()].reduce((a,b)=>a+b.v,0), rods=rodStats();
  const stock=[...Array(ST.plan.sheets).keys()].reduce((a,i)=>a+ST.plan.sheet[0]*ST.plan.sheet[1]*(ST.plan.sheet_thick?.[i]??state.thickness),0);
  const area0=ST.plan.sheet[0]*ST.plan.sheet[1], buy=ST.plan.sheets*area0;      // mm²: one sheet (the strip used, in one_sheet), and all of them
  const sheetsOf=new Map();                                            // sheets per stock, for the per-thickness lines
  for(const t of ST.plan.sheet_thick||[]){const k=+t.toFixed(6);sheetsOf.set(k,(sheetsOf.get(k)||0)+1)}
  $('#weight').innerHTML=`<div class="stats"><div class="k" data-tip="Every part as cut, holes and slots taken out, each at its own thickness"><b>${fmtMass(parts*g)}</b>parts</div>
    <div><b>${fmtVol(parts)}</b>of ${esc(state.material)}</div>`
    +(state.printed?'':`<div class="k" data-tip="The whole sheets the parts are nested on, offcuts included: what you buy and lift onto the machine"><b>${fmtMass(stock*g)}</b>${ST.plan.sheets} sheet(s)</div>
      <div class="k" data-tip="The whole sheets the parts are nested on, offcuts included: what you buy. The line below says how much of that area becomes parts"><b>${fmtArea(buy)}</b>to buy</div>`)
    +(rods.n?`<div class="k" data-tip="The dowel rods, bought rather than cut, taken to be of the same material as the parts"><b>${fmtMass(rods.vol*g)}</b>${rods.n} dowel(s)</div>
      <div class="k" data-tip="Parts and dowels together: what the finished model weighs, glue aside"><b>${fmtMass((parts+rods.vol)*g)}</b>assembled</div>`:'')+`</div>`
    +(state.printed?'':`<div class="hint">${fmtArea(ST.plan.material_area_mm2)} in the parts · ${Math.round(ST.plan.sheet_usage*100)} % of the stock used</div>`)
    +(rods.n?`<div class="hint">${rods.n} dowel(s), ${fmtLen(rods.len)} of rod in all</div>`:'')
    +(ST.plan.standoffs?`<div class="hint">${ST.plan.standoffs.items.length} printed standoff(s), not weighed here</div>`:'')
    +(by.size>1?[...by].sort((a,b)=>a[0]-b[0]).map(([t,b])=>{const n=sheetsOf.get(+t.toFixed(6))||0;
      return `<div class="hint">${fmtLen(t)} stock: ${b.n} part(s) · ${fmtMass(b.v*g)} · ${n} sheet(s), ${fmtArea(n*area0)}</div>`}).join(''):'')
    +`<div class="hint">at ${+(d*DU()).toPrecision(4)} ${DUNIT()}, set with the material on Sheet &amp; fit</div>`;
}
export function renderDownloads(){ // the labels checkbox applies to every cut file; the server names files <project or model>_v<rev>_…
  protoHint(); renderWeight();
  const b=`api/job/${CLIENT}/${ST.job}`,L=$('#x_labels').checked?1:0,K=$('#x_key').checked?1:0,G=$('#x_grouped').checked?1:0,step=lenMM('#pr_step',0.1),U=`&units=${ST.unit}`;   // the cut files come out in the unit on show, without a re-slice
  // what the labels on the parts mean, before the cut rather than after it
  $('#legend').innerHTML=`${(ST.mode.legend||'every part carries its own label').replace(/ · /g,'<br>')}`
    +(state.label_style==='code'?'<br><b>puzzle mode:</b> the parts are engraved with codes instead — assembly-key.txt maps them back':'');
  // a printed job has nothing to cut: the plates are under Print, and the cut files and their fit test step aside
  for(const el of $$('.cutonly,.protoonly'))el.hidden=state.printed;
  $('#pr_title').textContent=state.printed?'Print plates':'Prototyping (3D print)'; if(state.printed)$('#pr_fold').open=true;   // a printed job: the plates are the files
  $('#pr_go').textContent=state.printed?`download print plates (plate-1.3mf … plate-${ST.plan.sheets}.3mf, one per bed, + one STL per part)`
    :'download prototype set (plate.3mf for OrcaSlicer + one STL per part)';
  // every file says what it is for: eight buttons in a row left the reader to know which program wants which format
  const rows=r=>r.map(([t,u,use])=>`<div class="r"><a href="${u}">${t}</a>${use?`<details class="info"><summary>what is it for?</summary><span class="hint">${use}</span></details>`:''}</div>`).join('');
  const more=[['assembled STL',`${b}/stl`,'the whole model built from its parts, as one 3D file: to look at it or render it in another program'],
    ['assembled STEP',`${b}/step`,'the same model as true solids, for CAD (Fusion, FreeCAD, Onshape): every part a body with flat faces, not a triangle mesh'],
    ['plan.json',`jobs/${CLIENT}/${ST.job}/plan.json`,'everything Lamina worked out, for scripts and other tools']];
  $('#dl_title').textContent=state.printed?'The parts':'2 · The parts';
  // standoffs: which file is for which machine. Printed layers: one more file in the print set
  const nso=ST.plan.standoffs?.items.length, two=!nso?'':`<div class="msg note" id="two_machines">`+(state.printed
    ?`<b>Two print files.</b><br>⬢ The plates: the layers.<br>⬢ <b>3D-PRINT standoffs</b>: the ${nso} standoffs. Both are in the print set zip.`
    :`<b>Two machines make this model.</b><br>✂ <b>LASER</b>: the sheet files below.<br>⬢ <b>3D PRINTER</b>: the file named <b>3D-PRINT standoffs</b> (${nso} standoffs). It is inside every sheets zip, with a note that says which size goes where.`)+`</div>`;
  if(state.printed){$('#dl').innerHTML=two+rows(more);return}
  $('#dlfit').innerHTML=rows([['fit test SVG + DXF',`${b}/fitcut?fmt=svg,dxf&labels=${L}&step=${step}${U}`],['fit test PDF',`${b}/fitcut?fmt=pdf&labels=${L}&step=${step}${U}`]]);
  $('#dl').innerHTML=two+rows([
    ['sheets SVG + DXF',`${b}/export?fmt=svg,dxf&labels=${L}&key=${K}&grouped=${G}${U}`,'the usual one, a zip with one file per sheet: laser software opens the SVGs (LightBurn, xTool Creative Space, Glowforge), CAM the DXFs (Fusion, VCarve, SheetCAM)'],
    ['sheets PDF (one page per sheet)',`${b}/export?fmt=pdf&labels=${L}&key=${K}${U}`,'print it at 100 % to cut by hand or check the sizes; Glowforge and LightBurn open it too'],
    ['sheets EPS',`${b}/export?fmt=eps&labels=${L}&key=${K}${U}`,'for CorelDRAW, Illustrator and laser drivers that ask for EPS'],
    ['one file per piece SVG + DXF',`${b}/export?fmt=svg,dxf&labels=${L}&key=${K}&per_piece=1&grouped=${G}${U}`,'every part on its own, not nested: to nest them yourself (Deepnest, your laser software) or cut them one at a time'],
    ...more]);
}
export function renderReport(){
  const c=ST.plan.counts,p=ST.plan;
  // identical pieces are one part in several copies — the plan decided which, so the table and the cut files agree
  const sliceOf={}; for(const s of p.slices)for(const pc of s.pieces)sliceOf[pc.label]=s;
  const twins=pc=>[...(pc.same||[]),...(pc.flipped||[])];   // flipped = the same file, turned over (`mirror ok`)
  const copies=new Set(p.slices.flatMap(s=>s.pieces.flatMap(twins)));
  const kinds=p.slices.flatMap(s=>s.pieces.filter(pc=>!copies.has(pc.label)).map(pc=>[s,pc,[pc.label,...twins(pc)],pc.flipped||[]]));
  $('#stats').innerHTML=`<div class="stats"><div><b>${c.parts}</b>parts</div><div class="k" data-tip="How many different parts to cut: identical ones (same outline, any quarter turn, same stock — and with mirror ok also mirror images) count once — the Parts table and the per-piece export list them once, with the quantity"><b>${kinds.length}</b>different</div><div><b>${p.sheets}</b>${SH()}(s)</div><div><b>${(p.sheet_usage*100).toFixed(0)}%</b>${SH()} used</div>
   <div class="k" data-tip="How much of the model the parts represent: sample points inside the model that lie within a slice spacing of some part. Below 90 % parts of the model (legs, ears) have no geometry — add slices or change the axis"><b style="color:${p.coverage<0.9?'var(--warn)':'var(--ok)'}">${(p.coverage*100).toFixed(0)}%</b>model covered</div>
   <div><b>${(p.material_area_mm2/1e4).toFixed(1)}</b>dm² material</div><div><b>${p.bbox.map(v=>+(+inU(v)).toPrecision(3)).join(' × ')}</b>model ${ST.unit}</div>
   <div><b style="color:${c.errors?'var(--err)':'var(--ok)'}">${c.errors?'✖':'✓'} ${c.errors}</b>errors</div><div><b style="color:${c.warnings?'var(--warn)':'var(--ok)'}">${c.warnings?'⚠':'✓'} ${c.warnings}</b>warnings</div></div>`;   // a sign with each count: the colour is not the only thing that tells good from bad
  // the planner writes in mm; each message and fix is shown in the unit on show, and matched to its fixes on the raw text
  const fixBtns=(s,e)=>{const f=(s.fixes||[]).find(x=>x.error===e);return f?'<br>'+f.options.map((o,i)=>`<span class="fix" data-fix='${JSON.stringify(o.set).replace(/'/g,'&#39;')}' title="${inUnit(o.note||'')}">${inUnit(o.title)}</span>`).join(''):''};
  // every message says what it is in a sign and a word, not by its colour alone; several notes fold into one line that
  // names them, so they do not push the sheets down (the Checks tab shows them open)
  const ERR='<b>✖ ERROR</b> · ', WARN='<b>⚠ WARNING</b> · ', short=n=>esc(inUnit(n).replace(/<[^>]+>/g,'').split(' — ')[0].slice(0,48));
  const notes=p.notes.length>1?[`<details class="msg note"><summary>ⓘ <b>${p.notes.length} notes</b> on how this was sliced · <span>${p.notes.map(short).join(' · ')}</span></summary>${p.notes.map(n=>`<div>${inUnit(n)}</div>`).join('')}</details>`]
    :p.notes.map(n=>`<div class="msg note">ⓘ ${inUnit(n)}</div>`);
  const msgs=[...notes,...p.errors.map(e=>`<div class="msg err">${ERR}${inUnit(e)}${fixBtns({fixes:p.fixes||[]},e)}</div>`),
    ...(p.warnings||[]).map(w=>`<div class="msg warn">${WARN}${inUnit(w)}</div>`),   // of the whole plan: what was asked for and left out
    ...p.dropped.flatMap(s=>s.errors.map(e=>`<div class="msg err">${ERR}${s.label}: ${inUnit(e)}</div>`)),
    ...p.slices.flatMap(s=>[...s.errors.map(e=>`<div class="msg err" data-s="${s.label}" title="click to select this part">${ERR}${s.label}: ${inUnit(e)}${fixBtns(s,e)}</div>`),
                            ...s.warnings.map(w=>`<div class="msg warn" data-s="${s.label}" title="click to select this part">${WARN}${s.label}: ${inUnit(w)}${fixBtns(s,w)}</div>`)])];
  const html=msgs.length?msgs.slice(0,40).join('')+(msgs.length>40?`<div class="msg note">… ${msgs.length-40} more</div>`:''):'<div class="msg ok">✓ All physical checks passed.</div>';
  $('#msgs').innerHTML=html; $('#report').innerHTML=html; $('#report details')?.setAttribute('open','');
  for(const el of $$('.fix'))el.onclick=e=>{e.stopPropagation();applyFix(JSON.parse(el.dataset.fix))};
  for(const box of [$('#msgs'),$('#report')])box.onclick=e=>{   // clicking a message selects the part it is about, in 3D and on the sheet
    if(e.target.closest('.fix'))return; const d=e.target.closest('.msg[data-s]'); if(!d)return;
    const m=parts.children.find(c=>c.userData.slice===d.dataset.s); if(m){highlight(m);ST.fitted=true}};
  renderDownloads();
  // the link itself does the download (a navigation on the server, a blob from the worker in the browser build)
  const prq=()=>new URLSearchParams({scale:state.printed?1:$('#pr_scale').value||1,size:state.printed?0:lenMM('#pr_size'),labels:$('#pr_labels').value,font:lenMM('#pr_font',5),min_thick:lenMM('#pr_min',1.2),offset:state.printed?state.slot_offset:lenMM('#pr_offset',0.2)});
  $('#pr_go').onclick=e=>{e.currentTarget.href=`api/job/${CLIENT}/${ST.job}/proto?${prq()}`;ST.countUse('export','proto-3mf')};
  $('#fit_go').onclick=e=>{const q=prq();q.set('step',lenMM('#pr_step',0.1));e.currentTarget.href=`api/job/${CLIENT}/${ST.job}/fit?${q}`;ST.countUse('export','fit-3mf')};
  // typing in a length box writes its mm back, so what the server is given never depends on the unit on show
  for(const el of $$('input[data-len]'))el.oninput=()=>{el.dataset.mm=el.value===''?'':toMM(+el.value);(el.id==='pr_step'?renderDownloads:protoHint)()};
  $('#pr_scale').oninput=protoHint; $('#x_labels').onchange=$('#x_key').onchange=$('#x_grouped').onchange=renderDownloads;
  // Which formats people actually take away — the strongest signal of what machines they run. The link's own
  // query string already names them, so nothing extra has to be tracked to know it.
  $('#dl').onclick=e=>{const a=e.target.closest('a');if(!a)return;
    const href=a.getAttribute('href')||'', q=new URLSearchParams(href.split('?')[1]||'');
    const fmts=(q.get('fmt')?q.get('fmt').split(','):[href.split('?')[0].split('/').pop().replace('.','-')]).map(f=>/fitcut/.test(href)?'fit-'+f:f);
    fmts.forEach(f=>ST.countUse('export',f+(q.get('per_piece')?'-per-piece':'')))};
  // one row per different part: its own size, how many to cut, and which pieces come off it
  const size=pc=>[pc.bbox[2]-pc.bbox[0],pc.bbox[3]-pc.bbox[1]].map(inU).join('×');
  $('#parts').innerHTML=`<table><tr><th>part</th><th>qty</th><th>group</th><th>t (${ST.unit})</th><th>size (${ST.unit})</th><th>engages</th><th class="k" data-tip="The other pieces cut from this part's file. ⇄ = its mirror image: cut it from the same file and turn it over (only when mirror ok is on)">same part</th><th>status</th></tr>${kinds.map(([s,pc,ls,fl])=>{
    const ss=ls.map(l=>sliceOf[l]||s), e=ss.reduce((n,x)=>n+x.errors.length,0), w=ss.reduce((n,x)=>n+x.warnings.length,0), also=ls.slice(1).map(l=>fl.includes(l)?l+'⇄':l);
    return `<tr class="${e?'bad':''}" data-s="${s.label}"><td>${pc.label}${s.note?' '+s.note:''}</td><td>${ls.length}</td><td>${s.group}</td><td>${inU(s.thickness)}</td><td>${size(pc)}</td><td>${[...new Set(s.engages)].join(', ')}</td><td title="${also.join(', ')}">${also.slice(0,3).join(', ')}${also.length>3?` +${also.length-3}`:''}</td><td>${e?'✗ '+e:w?'⚠ '+w:'✓'}</td></tr>`}).join('')}</table>`;
  $('#parts').onclick=e=>{const tr=e.target.closest('tr[data-s]');if(!tr)return;const m=parts.children.find(c=>c.userData.slice===tr.dataset.s);if(m)highlight(m)};
}

