import * as THREE from 'three';
import {state, ST} from './state.js';
import {$$, $, status, esc, CLIENT} from './util.js';
import {highlight, showPane} from './edit3d.js';
import {fmtLen, fmtMass, fmtVol, fmtArea, DU, DUNIT, inU, inUnit, toMM} from './units.js';
import {act} from './history.js';
import {dens, machineOf, machineKind} from './presets.js';
import {renderFields, lenMM, showTab} from './form.js';
import {slice} from './slice.js';
import {parts} from './scene.js';
import {openGuide} from './guide.js';
import {sheetSeams, toggleSeam} from './seams.js';

// ---------------------------------------------------------------- sheets + report
const pieceToSlice=()=>{const m={};for(const s of ST.plan?.slices||[])for(const pc of s.pieces)m[pc.label]=s.label;return m};
export function hlSheet(label){const map=pieceToSlice();let first=null;for(const p of $$('#sheets path[data-label]')){const on=label&&map[p.dataset.label]===label;p.classList.toggle('hl',on);if(on&&!first)first=p}
  if(first)first.scrollIntoView({block:'nearest',behavior:'smooth'})}
export function renderSheets(svgs){
  $('#sheets').innerHTML=svgs.map((s,i)=>`<div class="sheet"><div class="t"><span>sheet ${i+1} of ${svgs.length} — ${fmtLen(ST.plan.sheet[0])} × ${fmtLen(ST.plan.sheet[1])}${ST.plan.sheet_thick?.[i]&&!state.printed?` · ${fmtLen(ST.plan.sheet_thick[i])} ${esc(ST.plan.sheet_stock?.[i]||'stock')}`:''}</span><a data-open="${i}">open full size ↗</a></div>${s}</div>`).join('');
  const bad=new Set(ST.plan.slices.filter(s=>s.errors.length).flatMap(s=>s.pieces.map(p=>p.label)));   // Slicer: red = part with a problem
  // status line: what is selected (so a click is never silent)
  if(ST.selected)status(`${$('#status').textContent.replace(/ · selected.*$/,'')} · selected ${ST.selected}`);
  for(const p of $$('#sheets path[data-label]'))if(bad.has(p.dataset.label))p.setAttribute('stroke','#ff5555');
  $('#sheets').onclick=e=>{const a=e.target.closest('a[data-open]');if(a){const s=$$('#sheets svg')[+a.dataset.open].cloneNode(true);s.querySelector('g.seams')?.remove();window.open(URL.createObjectURL(new Blob([s.outerHTML],{type:'image/svg+xml'})));return}
    const edge=e.target.closest('line.hit');if(edge)return toggleSeam(+edge.dataset.k);   // choosing seams: an edge of the net
    const p=e.target.closest('path[data-label]');if(!p)return;const lab=pieceToSlice()[p.dataset.label],m=parts.children.find(c=>c.userData.slice===lab);if(m)highlight(m);else showPane(lab)};
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
  // counted by name, as the assembly key lists them and a printed job prints them (export.rods_of): two named rods end to
  // end on one line are two to cut, though they weigh as one line
  const named=new Set((ST.plan.rods||[]).filter(r=>r.length>=8).map(r=>r[5])).size;
  return {n:named||lines.size,len,vol}}
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
      return `<div class="hint">${fmtLen(t)} stock: ${b.n} part(s) · ${fmtMass(b.v*g)}${state.printed?'':` · ${n} sheet(s), ${fmtArea(n*area0)}`}</div>`}).join(''):'')   // a plate holds every thickness
    +`<div class="hint">at ${+(d*DU()).toPrecision(4)} ${DUNIT()}, set with the material on Sheet &amp; fit</div>`;
  renderEstimates();
}
// What the cut takes: the lengths come from the server, measured on the very paths the cut files draw (core.export.measure);
// the speeds and the price are typed here, kept in this browser (not in the job), and the tiles follow the typing with no
// slice. Time is the cutting at the cut speed (score included) and the engraving at the engrave speed: pierces and travel
// are not in it, so it is a lower bound, never part of the cut. Speeds are stored in mm/s whatever the page shows.
const EST='lamina.estimates';
const estGet=()=>{try{return JSON.parse(localStorage.getItem(EST))||{}}catch(e){return {}}};
const estSet=o=>{try{localStorage.setItem(EST,JSON.stringify(o))}catch(e){}};
const fmtRun=mm=>ST.unit==='in'?(mm<304.8?`${+(mm/25.4).toPrecision(3)} in`:`${+(mm/304.8).toPrecision(3)} ft`):(mm<1000?`${+mm.toPrecision(3)} mm`:`${+(mm/1000).toPrecision(3)} m`);
const fmtTime=s=>s<90?`${Math.round(s)} s`:s<5400?`${Math.round(s/60)} min`:`${+(s/3600).toPrecision(3)} h`;
const speedIn=v=>ST.unit==='in'?+(v/25.4).toPrecision(4):v;       // mm/s → the number shown
function estimateTiles(){const t=ST.estimate?.total,o=estGet();if(!t)return '';
  const time=o.cut>0&&(o.engrave>0||!t.engrave)?(t.cut+t.score)/o.cut+(t.engrave?t.engrave/o.engrave:0):null;
  const k=(tip,v,l)=>`<div class="k" data-tip="${tip}"><b>${v}</b>${l}</div>`;
  return k('The length the machine cuts through: every outline and every hole, measured on the lines of the cut files',fmtRun(t.cut),'to cut')
    +k('How many times the cutter pierces the sheet: once for each cut line, a closed ring or one stretch of an outline split by holding bridges',t.pierces,'pierces')
    +(t.score?k('The length scored, not cut through: the fold lines',fmtRun(t.score),'to score'):'')
    +k('The length engraved: labels, numbers, arrows, guide lines and leader lines. Labels off in the options take them out',fmtRun(t.engrave),'to engrave')
    +k('Cutting and scoring at the cut speed, plus engraving at the engrave speed. Pierces and travel between lines are not in it: the real time is longer. Never part of the cut files',time==null?'set a speed':'≈ '+fmtTime(time),'machine time')
    +k('Sheets × the price of one sheet. A sheet used in part counts whole',o.price>0?+(ST.plan.sheets*o.price).toFixed(2):'set a price',`${ST.plan.sheets} ${SH()}(s) × price`)}
function renderEstimates(){const el=$('#estimates');if(state.printed||!ST.estimate){el.innerHTML='';return}
  const o=estGet(),u=ST.unit==='in'?'in/s':'mm/s',f=(id,tip,l,v,un)=>`<label data-tip="${tip}">${l} <input id="${id}" type="number" min="0" step="any" value="${v>0?v:''}"> ${un}</label>`;
  el.innerHTML=`<h3>Estimates</h3><div class="stats" id="est_tiles">${estimateTiles()}</div>
    <div class="hint">An estimate and a lower bound: pierces and travel are not in the time, and none of it is part of the cut files</div>
    <div class="est-in">${f('est_cut','How fast the machine cuts and scores. Your machine or its material table says; it is not part of the job','cut speed',speedIn(o.cut),u)}
    ${f('est_engrave','How fast the machine engraves','engrave speed',speedIn(o.engrave),u)}
    ${f('est_price','What one sheet costs you, as a plain number with no currency','price per sheet',o.price,'')}</div>
    <div class="hint">remembered in this browser, not part of the job</div>`}
$('#estimates').addEventListener('input',e=>{const id=e.target.id,v=+e.target.value;if(!/^est_/.test(id))return;
  const mm=id==='est_price'?v:ST.unit==='in'?v*25.4:v;estSet({...estGet(),[id.slice(4)]:mm>0?mm:0});$('#est_tiles').innerHTML=estimateTiles()});
// What the job is, by machine, before any button: which machine makes what, from which stock, and in which order. A
// cut job has a line per stock it is nested on (a paper lamp's panes on paper, its panels on card). Names are escaped:
// a machine or a material can be one of yours
const pl=(n,w)=>`${n} ${w}${n===1?'':'s'}`;
// What the print files hold, read from the files: the server makes them once per plan (/contents, with the print set
// button's own settings, so the download after it is the same kept zip), and only while the Export tab is shown (a
// print set takes seconds); the tab is drawn again with their names and counts when they come
function contents(pq){const p=ST.plan;
  if(!(state.printed||p.standoffs))return null;
  if(ST.contents?.plan===p)return ST.contents.got;
  if(ST.contents?.asked!==p&&$('section[data-tab="export"]').classList.contains('on')){ST.contents={asked:p};
    fetch(`api/job/${CLIENT}/${ST.job}/contents?${pq}`).then(r=>r.ok?r.json():null).then(got=>{if(got&&ST.plan===p){ST.contents={plan:p,got};renderDownloads()}}).catch(()=>{})}
  return null}
// the print set button names what its zip holds, from the zip's names: the plates (a run of them shortened), the pins
// and standoffs files, README and the assembly key when they are in it
function setNames(names){const m=names.filter(n=>/\.3mf$/.test(n)).map(n=>n.replace(/\.3mf$/,'').replace(/^.* 3D-PRINT standoffs x(\d+)$/,'$1 standoffs'));
  const plates=m.filter(n=>/^plate-\d+$/.test(n)), rest=m.filter(n=>!/^plate-\d+$/.test(n));
  return [...(plates.length>3?[`${plates[0]} … ${plates.at(-1)}`]:plates),...rest,...(names.includes('README.txt')?['README']:[]),
    ...(names.some(n=>/assembly-key\.txt$/.test(n))?['assembly key']:[])].join(', ')}
function machinesNote(ico,KIND,rods,nso,c){const p=ST.plan,pa=p.params,
    bed=`${p.sheet.map(v=>+(+inU(v)).toPrecision(4)).join(' × ')} ${ST.unit}`, name=esc((machineOf(state.machine)?.name||state.machine||'').replace(/ \*$/,''));
  const pins=(c?.print_set||[]).filter(n=>/^pins-\d+\.3mf$/.test(n)).length;   // the pin plates, nested at export (pin_files)
  if(state.printed)return `<b>This job is printed.</b><br>${ico} <b>${KIND}</b> · ${name}, ${esc(state.material)} ${fmtLen(pa.thickness)} · ${pl(p.sheets,'plate')} ${bed}`
    +(rods?pins?`, and ${pl(pins,'plate')} of dowel pins (${rods})`:`, and ${rods} dowel pins`:'')+(nso?`, and ${nso} standoffs`:'');
  const by=new Map(), stack=ST.mode.name==='stacked', n=p.counts;
  for(let i=0;i<p.sheets;i++){const t=p.sheet_thick?.[i]??pa.thickness,s=p.sheet_stock?.[i]||state.material,k=`${s} ${t}`;by.set(k,[s,t,(by.get(k)?.[2]||0)+1])}
  const cut=[...by.values()].map(([s,t,k])=>`${ico} <b>${KIND}</b> · ${name}, ${esc(s)} ${fmtLen(t)} · ${pl(k,'sheet')} ${bed}`   // a stack's parts are its layers
    +(by.size===1?`, ${stack?pl(n.slices,'layer')+(n.parts===n.slices?'':` in ${pl(n.parts,'part')}`):pl(n.parts,'part')}`:'')+(KIND==='CNC ROUTER'&&pa.tool_d>0?` · bit ${fmtLen(pa.tool_d)}`:''));
  return `<b>${nso?'Two machines make this model.':KIND==='BY HAND'?'This job is cut by hand.':'This job is cut.'}</b><br>`+cut.join('<br>')
    +(nso?`<br>⬢ <b>3D PRINTER</b> · ${nso} standoffs, 1 plate<br>Order: fit test, then cut, then print.`:'')   // standoff_files lays them all in one 3MF
    +(rods?`<br>Also ${rods} dowel rods${pa.dowel_d?`, ${fmtLen(pa.dowel_d)} across`:''}: cut them to length by hand. The assembly key gives each length.`:'')}
export function renderDownloads(){ // the labels checkbox applies to every cut file; the server names files <project or model>_v<rev>_…
  protoHint(); renderWeight();
  const b=`api/job/${CLIENT}/${ST.job}`,L=$('#x_labels').checked?1:0,K=$('#x_key').checked?1:0,G=$('#x_grouped').checked?1:0,step=lenMM('#pr_step',0.1),U=`&units=${ST.unit}`;   // the cut files come out in the unit on show, without a re-slice
  // what the labels on the parts mean, before the cut rather than after it
  $('#legend').innerHTML=`${(ST.mode.legend||'every part carries its own label').replace(/ · /g,'<br>')}`
    +(state.label_style==='code'?'<br><b>puzzle mode:</b> the parts are engraved with codes instead — assembly-key.txt maps them back':'');
  const p=ST.plan, printed=state.printed, nso=p.standoffs?.items.length||0, mix=nso&&!printed, [ico,KIND,MK]=machineKind(state.machine);
  const fit=p.fit_test!==false;          // a joint the slot offset sizes (Mode.fit_test); a plan saved before the field has one
  const rods=p.rods?.length?rodStats().n:0;
  // the print set and the print fit test: a printed job is printed as it is, full size, at its own slot offset and label size
  const pq=new URLSearchParams({scale:printed?1:$('#pr_scale').value||1,size:printed?0:lenMM('#pr_size'),labels:$('#pr_labels').value,font:printed?state.font:lenMM('#pr_font',5),min_thick:lenMM('#pr_min',1.2),offset:printed?state.slot_offset:lenMM('#pr_offset',0.2)}), fq=new URLSearchParams(pq);
  fq.set('step',step);
  // a printed job has nothing to cut, and a job with no joint the offset sizes has no fit test: their steps step aside
  for(const el of $$('.cutonly,.protoonly'))el.hidden=printed;
  for(const el of $$('.fitonly'))el.hidden=!fit;
  const kt=!printed&&!(state.tool_d>0);   // the kerf test, beside the fit test: for a cutter that burns its kerf (a router's CAM offsets its bit)
  $('#fit_what_print').hidden=!printed;
  const slot=$(printed?'#print_opts':'#pr_slot'); if($('#pr_shared').parentNode!==slot)slot.append($('#pr_shared'));   // one set of print controls: under the print set on a printed job (moved only when it changes place: a moved box loses the focus)
  $('#slicer_fold').hidden=!printed; $('#slicer_sum').textContent=`what the slicer must have: ${state.material}, 0.4 mm nozzle, first layer ${fmtLen(0.2)}`;   // core.solid.FIRST
  const c=contents(pq); $('#machines').innerHTML=machinesNote(ico,KIND,rods,nso,c);
  const ne=p.counts.errors; $('#x_errors').hidden=!ne;           // the files still download: the warning says what they hold
  if(ne){$('#x_errors').innerHTML=`<b>⚠ WARNING</b> · This plan has ${ne} error${ne>1?'s':''}: some parts do not go together, or the machine cannot make them. Correct ${ne>1?'them':'it'} before you cut or print. <button class="small">show the errors</button>`;
    $('#x_errors button').onclick=()=>showTab('checks')}
  // every file says what it is for: eight buttons in a row left the reader to know which program wants which format.
  // A row: [text, link, what it is for, its id, a warning shown under it, the machine]. A main row is the one file a
  // machine needs: outlined, marked with its machine (data-machine: the tour finds it), what it is for written under it.
  // The steps are numbered as they show
  const rows=(r,main)=>r.map(([t,u,use,id,warn,mk])=>`<div class="r"${id?` id="${id}"`:''}><a href="${u}"${main?` class="main" data-machine="${mk}"`:''}>${t}</a>`
    +(use?main?`<div class="hint">${use}</div>`:`<details class="info"><summary>what is it for?</summary><span class="hint">${use}</span></details>`:'')
    +`${warn?`<div class="msg warn"><b>⚠ WARNING</b> · ${warn}</div>`:''}</div>`).join('');
  let n=0; const num=t=>`${++n} · ${t}`;
  const more=[['assembled STL',`${b}/stl`,'the whole model built from its parts, as one 3D file: to look at it or render it in another program'],
    ['STEP: parts',`${b}/step`,'the same model as true solids, for CAD (Fusion, FreeCAD, Onshape): every part a body with flat faces, not a triangle mesh','dl_step'],
    // one body needs the solids library the browser build has none of (core.solid.one_body). Folded panels fuse where
    // grown panels and tabs cross, and CAD rejected 6 of 8 examples (Marcel: offer it with a warning)
    ...(document.documentElement.dataset.static?[]:[['STEP: one body',`${b}/step?body=1`,'the whole model as one solid with flat faces, for CAD: every part, standoff and dowel joined where they touch (grown by 0.02 mm so they do). A part that touches nothing stays a body of its own','dl_step_body',
      ST.mode.name==='folded'?'on Folded Panels this file may not open as a valid solid in CAD. If it does not, take STEP: parts':'']]),
    ['plan.json',`jobs/${CLIENT}/${ST.job}/plan.json`,'everything Lamina worked out, for scripts and other tools']];
  // 1 · the fit test, one per machine: the cut one at 1:1 on the real stock, and a mix's standoffs to try in its holes
  const kerfRow=[`${ico} kerf test to cut · 7 squares in 7 holes (SVG + DXF)`,`${b}/kerftest?fmt=svg,dxf&labels=${L}${U}`,
    'Seven squares and a plate with seven square holes, each pair drawn for one kerf around yours. Cut them from a scrap with the job\'s settings: '
    +'the square that fits its own hole snug, without play and without force, carries your kerf. Type it in Sheet & fit → kerf.','kerf_go'];
  if(fit){$('#fit_title').textContent=num(`Fit test — ${mix?'cut and print':printed?'print':'cut'} this first`);
    $('#fit_opts>summary').textContent=printed?'options: joint step':'options: joint step, PDF';
    const holes=ST.mode.name==='stacked'&&p.params.connect!=='tab'?'hole sizes':'slot offsets';
    $('#dlfit').innerHTML=printed?rows([['print fit test · 5 small joints (.zip)',`${b}/fit?${fq}`,'','fit_go']])
      :rows([[`${ico} fit test to cut · 5 ${holes} (SVG + DXF)`,`${b}/fitcut?fmt=svg,dxf&labels=${L}&step=${step}${U}`],
             ...(mix?[[`⬢ fit test to print · ${c?.fit_standoffs?pl(c.fit_standoffs,'standoff'):'the standoffs'} (3MF)`,`${b}/standoffs?fit=1`]]:[]),
             ...(kt?[kerfRow]:[])]);
    $('#dlfit_other').innerHTML=printed?'':rows([['fit test PDF',`${b}/fitcut?fmt=pdf&labels=${L}&step=${step}${U}`]])}
  // 2 · the files: one main button per machine, the other formats and the options folded under it
  $('#dl_title').textContent=num(printed?'The print files':'The files, by machine');
  $('#dl').innerHTML=printed?rows([[`print set (.zip)${c?.print_set?` · ${setNames(c.print_set)}`:''}`,`${b}/proto?${pq}`,'A 3MF per plate for the slicer, every part with the settings it needs, one STL per part, and README.txt: read it first.','pr_go','',MK]],true)
    :rows([[`${ico} ${KIND} · sheets SVG + DXF (.zip)`,`${b}/export?fmt=svg,dxf&labels=${L}&key=${K}&grouped=${G}${U}`,`An SVG and a DXF for each sheet${K?', the assembly key':''} and README.txt: read it first. Laser software opens the SVGs (LightBurn, xTool Creative Space, Glowforge), CAM the DXFs (Fusion, VCarve, SheetCAM).`,'','',MK]],true);
  $('#dl_other').innerHTML=printed?'':rows([
    ['sheets PDF (one page per sheet)',`${b}/export?fmt=pdf&labels=${L}&key=${K}&grouped=${G}${U}`,'print it at 100 % to cut by hand or check the sizes; Glowforge and LightBurn open it too'],
    ['sheets EPS',`${b}/export?fmt=eps&labels=${L}&key=${K}${U}`,'for CorelDRAW, Illustrator and laser drivers that ask for EPS'],
    ['one file per piece SVG + DXF',`${b}/export?fmt=svg,dxf&labels=${L}&key=${K}&per_piece=1&grouped=${G}${U}`,'every part on its own, not nested: to nest them yourself (Deepnest, your laser software) or cut them one at a time']]);
  $('#dl_print').innerHTML=mix?rows([[`⬢ 3D PRINTER · ${nso} standoffs (3MF)`,`${b}/standoffs`,'One 3MF for the slicer, every standoff an object of its own, named by its size (S1, S2 …). The note in the sheets zip says which size goes where.','dl_standoffs','','printer']],true):'';
  // 3 · build it: the key on its own, what goes where
  $('#build_title').textContent=num('Build it');
  $('#key_go').innerHTML=`<a href="${b}/key?units=${ST.unit}">assembly key (.txt) · which ${nso?'standoff':rods?(printed?'pin':'dowel'):'part'} goes where</a>`;
  $('#dl_proto').innerHTML=printed?'':rows([['prototype set (.zip) · plate.3mf for the slicer + one STL per part',`${b}/proto?${pq}`,'','pr_go'],
    ...(fit?[['print fit test (.zip) · 5 print slot offsets around yours',`${b}/fit?${fq}`,'','fit_go']]:[])]);
  $('#more').innerHTML=rows(more);
}
$('#guide_go').onclick=e=>{e.preventDefault();openGuide(e.currentTarget)};
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
  // the planner writes in mm; each message and fix is shown in the unit on show, and matched to its fixes on the raw text.
  // Its texts repeat what a project file says (a material's name), and a project file can be somebody else's: text, never markup
  const txt=s=>esc(inUnit(s));
  const fixBtns=(s,e)=>{const f=(s.fixes||[]).find(x=>x.error===e);return f?'<br>'+f.options.map((o,i)=>`<span class="fix" data-fix='${esc(JSON.stringify(o.set))}' title="${txt(o.note)}">${txt(o.title)}</span>`).join(''):''};
  // every message says what it is in a sign and a word, not by its colour alone; several notes fold into one line that
  // names them, so they do not push the sheets down (the Checks tab shows them open)
  const ERR='<b>✖ ERROR</b> · ', WARN='<b>⚠ WARNING</b> · ', short=n=>esc(inUnit(n).split(' — ')[0].slice(0,48));
  const notes=p.notes.length>1?[`<details class="msg note"><summary>ⓘ <b>${p.notes.length} notes</b> on how this was sliced · <span>${p.notes.map(short).join(' · ')}</span></summary>${p.notes.map(n=>`<div>${txt(n)}</div>`).join('')}</details>`]
    :p.notes.map(n=>`<div class="msg note">ⓘ ${txt(n)}</div>`);
  const msgs=[...notes,...p.errors.map(e=>`<div class="msg err">${ERR}${txt(e)}${fixBtns({fixes:p.fixes||[]},e)}</div>`),
    ...(p.warnings||[]).map(w=>`<div class="msg warn">${WARN}${txt(w)}</div>`),   // of the whole plan: what was asked for and left out
    ...p.dropped.flatMap(s=>s.errors.map(e=>`<div class="msg err">${ERR}${esc(s.label)}: ${txt(e)}</div>`)),
    ...p.slices.flatMap(s=>[...s.errors.map(e=>`<div class="msg err" data-s="${esc(s.label)}" title="click to select this part">${ERR}${esc(s.label)}: ${txt(e)}${fixBtns(s,e)}</div>`),
                            ...s.warnings.map(w=>`<div class="msg warn" data-s="${esc(s.label)}" title="click to select this part">${WARN}${esc(s.label)}: ${txt(w)}${fixBtns(s,w)}</div>`)])];
  const html=msgs.length?msgs.slice(0,40).join('')+(msgs.length>40?`<div class="msg note">… ${msgs.length-40} more</div>`:''):'<div class="msg ok">✓ All physical checks passed.</div>';
  $('#msgs').innerHTML=html; $('#report').innerHTML=html; $('#report details')?.setAttribute('open','');
  for(const el of $$('.fix'))el.onclick=e=>{e.stopPropagation();applyFix(JSON.parse(el.dataset.fix))};
  for(const box of [$('#msgs'),$('#report')])box.onclick=e=>{   // clicking a message selects the part it is about, in 3D and on the sheet
    if(e.target.closest('.fix'))return; const d=e.target.closest('.msg[data-s]'); if(!d)return;
    const m=parts.children.find(c=>c.userData.slice===d.dataset.s); if(m){highlight(m);ST.fitted=true}else showPane(d.dataset.s)};
  // the link itself does the download (a navigation on the server, a blob from the worker in the browser build); every
  // box of the tab is in some link, so a change makes the links again
  renderDownloads();
  // typing in a length box writes its mm back, so what the server is given never depends on the unit on show
  for(const el of $$('input[data-len]'))el.oninput=()=>{el.dataset.mm=el.value===''?'':toMM(+el.value);renderDownloads()};
  $('#pr_scale').oninput=$('#pr_labels').onchange=renderDownloads; $('#x_labels').onchange=$('#x_key').onchange=$('#x_grouped').onchange=renderDownloads;
  // Which formats people actually take away — the strongest signal of what machines they run. The link's own
  // query string already names them, so nothing extra has to be tracked to know it.
  $('section[data-tab="export"]').onclick=e=>{const a=e.target.closest('.dl a');if(!a||a.id==='vid_go'||a.id==='guide_go')return;
    const href=a.getAttribute('href')||'', path=href.split('?')[0].split('/').pop(), q=new URLSearchParams(href.split('?')[1]||'');
    const named={proto:'proto-3mf',fit:'fit-3mf'}[path]; if(named)return ST.countUse('export',named);   // the names these two were always counted under
    const fmts=(q.get('fmt')?q.get('fmt').split(','):[path.replace('.','-')]).map(f=>/fitcut/.test(href)?'fit-'+f:f);
    fmts.forEach(f=>ST.countUse('export',f+(q.get('per_piece')?'-per-piece':'')))};
  // one row per different part: its own size, how many to cut, and which pieces come off it
  const size=pc=>[pc.bbox[2]-pc.bbox[0],pc.bbox[3]-pc.bbox[1]].map(inU).join('×');
  $('#parts').innerHTML=`<table><tr><th>part</th><th>qty</th><th>group</th><th>t (${ST.unit})</th><th>size (${ST.unit})</th><th>engages</th><th class="k" data-tip="The other pieces cut from this part's file. ⇄ = its mirror image: cut it from the same file and turn it over (only when mirror ok is on)">same part</th><th>status</th></tr>${kinds.map(([s,pc,ls,fl])=>{
    const ss=ls.map(l=>sliceOf[l]||s), e=ss.reduce((n,x)=>n+x.errors.length,0), w=ss.reduce((n,x)=>n+x.warnings.length,0), also=ls.slice(1).map(l=>esc(fl.includes(l)?l+'⇄':l));
    return `<tr class="${e?'bad':''}" data-s="${esc(s.label)}"><td>${esc(pc.label)}${s.note?' '+esc(s.note):''}</td><td>${ls.length}</td><td>${esc(s.group)}</td><td>${inU(s.thickness)}</td><td>${size(pc)}</td><td>${esc([...new Set(s.engages)].join(', '))}</td><td title="${also.join(', ')}">${also.slice(0,3).join(', ')}${also.length>3?` +${also.length-3}`:''}</td><td>${e?'✗ '+e:w?'⚠ '+w:'✓'}</td></tr>`}).join('')}</table>`;
  $('#parts').onclick=e=>{const tr=e.target.closest('tr[data-s]');if(!tr)return;const m=parts.children.find(c=>c.userData.slice===tr.dataset.s);if(m)highlight(m);else showPane(tr.dataset.s)};
}

