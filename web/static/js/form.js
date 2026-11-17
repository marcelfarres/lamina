import * as THREE from 'three';
import {state, ST} from './state.js';
import {PLANE_IDX} from './catalog.js';
import {$, $$, esc, nice} from './util.js';
import {splitAxis, axisList, branchTo, curveList, newLine, dropLine} from './edit3d.js';
import {bounds, inU, show, isLen, fromU, applyUnit} from './units.js';
import {syncPresetSelects, applyMachine} from './presets.js';
import {renderSpacing} from './spacing.js';
import {slice} from './slice.js';
import {V3, applyLook, rings} from './scene.js';
import {applyFix} from './results.js';
import {syncProject} from './project.js';
import {syncSeams} from './seams.js';

// ---------------------------------------------------------------- form
// The length boxes outside the parameter form (Export tab): the mm value lives on the element — that is what the
// server is given — and the box shows it in the unit on show, so switching re-renders the box from the mm instead of
// converting what is on screen, which would drift a little every time.
export const lenMM=(id,d=0)=>{const v=$(id).dataset.mm; return v===''||v==null?d:+v};
export function lenBoxes(){
  for(const el of $$('input[data-len]')){const d=el.dataset,n=a=>d[a]==null?null:+d[a],b=bounds({unit:'mm',min:n('min'),max:n('max'),step:n('step')});
    el.value=d.mm===''?'':inU(+d.mm);
    for(const a of ['min','max','step'])if(b[a]!=null)el.setAttribute(a,b[a]);
    if(d.ph)el.placeholder=`e.g. ${+inU(+d.ph).toPrecision(1)}`;   // a round example in every unit: 100 mm, 10 cm, 4 in
    const k=el.previousElementSibling; k.textContent=k.textContent.replace(/\((?:mm|cm|in)\)/,`(${ST.unit})`);
  }}
const num=(id,v,p,extra='')=>{const b=bounds(p);return `<input type="number" id="${id}" value="${v==null?'':show(p,v)}" ${b.min!=null?`min="${b.min}"`:''} ${b.max!=null?`max="${b.max}"`:''} step="${b.step||'any'}" ${extra}>`};
// slider + number box for every bounded number (the slider drives live, the box allows exact / out-of-range values)
const slider=(id,v,p,extra='')=>{const b=bounds(p);return `<span class="sl"><input type="range" id="${id}_r" value="${show(p,v)}" min="${b.min}" max="${b.max}" step="${b.step||'any'}" data-for="${id}" ${extra}>${num(id,v,p,extra)}</span>`};
function field(p){
  const id='p_'+p.name, v=state[p.name], u=isLen(p)?` (${ST.unit})`:p.unit==='deg'?' (°)':''; let inp;
  if(p.type==='choice')inp=`<select id="${id}">${p.choices.map(c=>`<option value="${esc(c)}" ${c==v?'selected':''}>${esc(p.choice_labels?.[c]||c)}</option>`).join('')}</select>`;
  else if(p.type==='bool')inp=`<input type="checkbox" id="${id}" ${v?'checked':''}>`;
  else if(p.type==='vec2'||p.type==='vec3'){const n=p.type==='vec2'?2:3,lab=p.name==='sheet'?['w','h']:['x','y','z'],sl=p.unit==='deg';
    inp=sl?`<div class="rows">${[...Array(n)].map((_,i)=>`<div class="r"><small>${lab[i]}</small>${slider(id+'_'+i,(v||[])[i]||0,p,`data-vec="${p.name}" data-i="${i}"`)}</div>`).join('')}</div>`
        // `size` left at 0 is "however big the model is": the box is empty and shows what came out as a placeholder,
        // so typing one dimension tells you the other two instead of leaving three zeros that mean three things
        :`<span class="vec">${[...Array(n)].map((_,i)=>`<small>${lab[i]}</small>${num(id+'_'+i,(v||[])[p.name==='size'?sizeAxes()[i]:i]||(p.name==='size'?null:0),p,`data-vec="${p.name}" data-i="${i}" ${p.name==='size'?`placeholder="${ST.plan?+(+show(p,ST.plan.bbox[i])).toPrecision(3):'auto'}"`:''}`)}`).join('')}</span>`}
  else if(p.type==='text')inp=`<input id="${id}" value="${esc(v)}">`;
  else if(p.type==='file')inp=`<span><input type="file" id="${id}" accept=".svg,.dxf"><small class="hint">${v?'a file is loaded':'no file yet'}</small></span>`;   // kept as its text
  else if(p.type==='curve')inp=`<span class="hint">drawn in the graph under the 3D view</span>`;
  else if(p.type==='points')inp=`<div class="rows" id="${id}">${(v||[]).map((q,i)=>`<div class="r"><small>${i+1}</small><input type="number" step="any" value="${show(p,q[0])}" data-pt="${p.name}" data-i="${i}" data-j="0"><input type="number" step="any" value="${show(p,q[1])}" data-pt="${p.name}" data-i="${i}" data-j="1"><button class="small x" data-del="${p.name}" data-i="${i}">×</button></div>`).join('')}<div class="r"><button class="small" data-add="${p.name}">+ point</button><span class="hint">or alt-click in the 3D view</span></div></div>`;
  else if(p.type==='lines3')inp=`<div class="rows" id="${id}">${(v||[]).length?`<div class="r hint"><small></small>${['x','y','z'].map(a=>`<span style="flex:1;text-align:center">${a} (${ST.unit})</span>`).join('')}<span style="flex:0 0 24px"></span></div>`:''}${(v||[]).map((l,i)=>[0,1].map(e=>`<div class="r"><small>${e?'end':`${i+1} start`}</small>${[0,1,2].map(j=>`<input type="number" step="any" value="${show(p,l[e][j])}" data-ln="${p.name}" data-i="${i}" data-e="${e}" data-j="${j}" title="${e?'end':'start'} ${'xyz'[j]}">`).join('')}<span style="flex:0 0 24px">${e?'':`<button class="small x" data-del="${p.name}" data-i="${i}">×</button>`}</span></div>`).join('')).join('')}<div class="r"><button class="small" data-add="${p.name}">${{axes:'+ split an axis',branches:'+ branch'}[p.name]||'+ line'}</button><span class="hint">${{axes:'or alt-click the model for a parallel axis · drag them in the 3D view',branches:'or shift+alt-click a hoof, hand or tail tip · drag the ends in the 3D view · alt-click one to remove it'}[p.name]||'one straight dowel per line · or alt-click the model: a line up through that point'}</span></div></div>`;
  else if(p.type==='edges')inp=`<span class="seamcard"><span id="seam_n" class="hint"></span><span><button class="small" data-seams="mode"></button><button class="small" data-seams="clear">clear my seams</button></span></span>`;   // chosen in the 3D view and on the sheets; syncSeams writes the counts
  else if(p.type==='map'){const rows=Object.entries(v||{});if(ST.selected&&!(ST.selected in (v||{})))rows.push([ST.selected,p.name==='thick'?state.thickness:0]);
    inp=`<div class="rows" id="${id}">${rows.map(([k,x])=>`<div class="r"><small>${esc(k)}</small><input type="number" step="any" value="${show(p,x)}" data-map="${p.name}" data-k="${esc(k)}">${k in (v||{})?`<button class="small x" data-del="${p.name}" data-i="${esc(k)}">×</button>`:'<span class="hint">default</span>'}</div>`).join('')||'<span class="hint">no overrides — select a part in the 3D view and use the sliders</span>'}</div>`}
  else if(p.type==='labels'||p.type==='chips')inp=`<div class="chips" id="${id}">${(v||[]).map((x,i)=>`<span class="chip">${p.type==='chips'?show(p,x):esc(x)}<b data-del="${p.name}" data-i="${i}">×</b></span>`).join('')}<input placeholder="${p.type==='chips'?'value ⏎':'label ⏎'}" data-chip="${p.name}"></div>`;
  else inp=(p.min!=null&&p.max!=null)?slider(id,v,p):num(id,v,p);
  return `<div class="f${p.type==='lines3'||p.type==='edges'?' wide':''}" data-p="${p.name}" ${p.show_if?`data-show="${p.show_if[0]}:${[].concat(p.show_if[1]).join('|')}"`:''}><span class="k" data-tip="${p.help.replace(/"/g,'&quot;')}">${p.label||nice(p.name)}${u}</span>${inp}</div>`;
}
// a group's fields, with a heading where the section changes: "Title — the line under it", the line always on show, so
// what a switch governs is read, not hovered for (only the kerf follows "compensate kerf"; the slot fit always applies)
const fields=ps=>{let s='';return ps.map(p=>{if(!p.section||p.section===s)return field(p);s=p.section;const [t,line]=s.split(' — ');
  return `<h3 class="sub">${esc(t)}</h3>${line?`<p class="hint sub">${esc(line)}</p>`:''}${field(p)}`}).join('')};
export function renderFields(){
  const com=ST.mode.common, byG=g=>fields(com.filter(p=>p.group===g)); syncProject();
  $('#g-model').innerHTML=byG('model'); $('#g-technique').innerHTML=fields(ST.mode.params)+byG('technique'); $('#g-slices').innerHTML=byG('slices');
  $('#g-sheet').innerHTML=byG('sheet'); $('#g-fit').innerHTML=byG('fit'); $('#g-checks').innerHTML=byG('checks');
  applyShowIf(); syncPresetSelects(); renderSpacing(); syncSeams();
}
function applyShowIf(){for(const el of $$('.f[data-show]')){const [k,vals]=el.dataset.show.split(':');el.hidden=!vals.split('|').includes(String(state[k]))}}
export const allParams=()=>[...ST.mode.common,...ST.mode.params];
export function setVal(name,v){state[name]=v;applyShowIf();if(name==='rotate'||name==='up_axis')syncSizeBoxes();schedule()}
// `size` is the model's own: its three numbers are along the model file's axes, and the slicer scales it before any
// turn, so turning the model never changes its size (aimed at the view's axes after the turn, a bear 500 mm tall,
// stood up along x, came back 500 mm long and half as big again — reported). The boxes read along the view's axes:
// box x shows the model dimension that lies along x now, and a number typed there goes to that dimension.
// ponytail: a turn that is not a quarter turn takes the nearest axis for the boxes; the numbers themselves never move
const UP={z:[[1,0,0],[0,1,0],[0,0,1]],x:[[0,0,1],[0,1,0],[-1,0,0]],y:[[0,-1,0],[0,0,1],[-1,0,0]]};   // where each model axis points once the up axis is z (trimesh's align_vectors)
export function sizeAxes(){const u=UP[state.up_axis||'z'],e=new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(...(state.rotate||[0,0,0]).map(d=>d*Math.PI/180),'ZYX')).multiply(new THREE.Matrix4().makeBasis(V3(u[0]),V3(u[1]),V3(u[2]))).elements;
  return [0,1,2].map(j=>[0,1,2].reduce((a,i)=>Math.abs(e[4*i+j])>Math.abs(e[4*a+j])?i:a,0))}   // view axis j ← the model axis with most of it (row j's largest entry; column-major)
export const sizeToModel=w=>{const m=sizeAxes(),s=[0,0,0];for(let j=0;j<3;j++)if(w[j])s[m[j]]=w[j];return s};   // a size typed along the view's axes (project files before 0.3.2)
function syncSizeBoxes(){const p=allParams().find(q=>q.name==='size');if(!p)return;const m=sizeAxes(),s=state.size||[];for(let i=0;i<3;i++){const el=$('#p_size_'+i);if(el)el.value=s[m[i]]?show(p,s[m[i]]):''}}
// one delegated handler for every widget
$('#tabs').addEventListener('input',e=>{
  const t=e.target; if(t.id==='file')return; const P=name=>allParams().find(p=>p.name===name);
  if(t.dataset.for){const box=document.getElementById(t.dataset.for);box.value=t.value;box.dispatchEvent(new Event('input',{bubbles:true}));return}   // slider → its number box
  if(t.type==='number'){const r=document.getElementById(t.id+'_r');if(r)r.value=t.value}
  if(t.dataset.vec){const p=P(t.dataset.vec),v=[...(state[p.name]||[0,0,0])];v[p.name==='size'?sizeAxes()[+t.dataset.i]:+t.dataset.i]=fromU(p,+t.value||0);   // a size box is a view axis; the number is the model's
    if(p.name==='size'){ST.fitted=false;if(state.scale!==1){state.scale=1;for(const el of [$('#p_scale'),$('#p_scale_r')])if(el)el.value=1}}   // a new size is the new 100 %
    return setVal(p.name,v)}
  if(t.dataset.pt){const p=P(t.dataset.pt),v=(state[p.name]||[]).map(q=>[...q]);v[+t.dataset.i][+t.dataset.j]=fromU(p,+t.value||0);return setVal(p.name,v)}
  if(t.dataset.ln){const p=P(t.dataset.ln),v=(state[p.name]||[]).map(l=>l.map(q=>[...q]));v[+t.dataset.i][+t.dataset.e][+t.dataset.j]=fromU(p,+t.value||0);return setVal(p.name,v)}
  if(t.dataset.map){const p=P(t.dataset.map),v={...(state[p.name]||{})};v[t.dataset.k]=fromU(p,+t.value||0);return setVal(p.name,v)}
  if(t.dataset.chip)return;
  const p=allParams().find(p=>'p_'+p.name===t.id); if(!p)return;
  if(p.name==='units'){ST.unit=t.value;return applyUnit()}   // the Sheet tab's units box is the toolbar's, not a second one
  if(p.type==='file'){const f=t.files[0], hint=t.parentElement.querySelector('small'); if(f)f.text().then(x=>{setVal(p.name,x); if(hint)hint.textContent='a file is loaded'}); return}
  if(p.type==='bool')setVal(p.name,t.checked); else if(p.type==='choice'||p.type==='text')setVal(p.name,t.value); else setVal(p.name,t.value===''?p.default:fromU(p,+t.value));
  if(t.closest('#g-model'))ST.fitted=false;
});
// reset the parameters of one tab to their defaults
const TABGROUPS={model:['model'],technique:['technique','slices'],sheet:['sheet','fit'],checks:['checks']};
export function resetTab(tab){for(const p of ST.mode.common)if(TABGROUPS[tab].includes(p.group))state[p.name]=structuredClone(p.default);
  if(tab==='technique')for(const p of ST.mode.params)state[p.name]=structuredClone(p.default);
  // the material sets the 3D look when it is picked, so the reset material takes the look back to the page's own
  if(tab==='model')ST.fitted=false; if(tab==='sheet'){applyMachine(state.machine);$('#look').value='group';applyLook()}
  ST.unit=state.units||ST.unit; applyUnit(); slice()}   // the Sheet tab holds `units`: the page follows it back to mm
$('#tabs').addEventListener('click',e=>{
  const t=e.target, P=name=>allParams().find(p=>p.name===name);
  if(t.dataset.rot!==undefined){const r=[...(state.rotate||[0,0,0])],i=+t.dataset.rot;r[i]=((r[i]+(e.shiftKey?-90:90)+180)%360+360)%360-180;state.rotate=r;ST.fitted=false;renderFields();schedule();return}
  if(t.dataset.add){const p=P(t.dataset.add);
    // + on the axes table splits the axis you can already see: the list starts from the one the plan used, so it is
    // kept rather than replaced (a zero-length line would draw nothing and slice nothing)
    if(p.name==='axes')setVal('axes',splitAxis(axisList()));
    else if(p.name==='branches'){   // a leg down to the bottom of the box, from a quarter of the way along and across: four presses, four legs
      const [ui,vi]=PLANE_IDX[state.plane||'xz'],wi=3-ui-vi,n=(state.branches||[]).length,A=k=>V3(ST.plan.axes[k]);
      const P=V3(ST.plan.curve3d[ST.plan.curve3d.length>>1]).addScaledVector(A(wi),(n%2?1:-1)*ST.plan.bbox[wi]/4).addScaledVector(A(ui),(n&2?-1:1)*ST.plan.bbox[ui]/4);
      setVal('branches',[...state.branches||[],branchTo(P.addScaledVector(A(vi),-ST.plan.bbox[vi]/2-P.dot(A(vi))))])}
    else setVal(p.name,[...(p.name==='curve'?curveList():state[p.name]||[]),p.type==='lines3'?newLine():[0,0]]);   // the curve grows from the one on screen
    renderFields()}
  else if(t.dataset.del){const p=P(t.dataset.del);if(p.type==='map'){const v={...state[p.name]};delete v[t.dataset.i];setVal(p.name,v)}
    else setVal(p.name,p.type==='lines3'?dropLine(+t.dataset.i):(state[p.name]||[]).filter((_,i)=>i!==+t.dataset.i));renderFields()}
});
$('#tabs').addEventListener('keydown',e=>{const t=e.target;if(!t.dataset.chip||e.key!=='Enter')return;const p=allParams().find(p=>p.name===t.dataset.chip);const raw=t.value.trim();if(!raw)return;
  const v=p.type==='chips'?fromU(p,+raw):raw; if(p.type==='chips'&&isNaN(v))return; setVal(p.name,[...(state[p.name]||[]),v]);renderFields()});
export const memo={};   // per-technique parameter memory: switching away and back restores what you had
// …but only what still means anything. These are placed on a particular model — in its millimetres, or under its
// part labels — or shape it (size, turn, modify form), so a new model clears them from the memory as well as from the
// form (see newModel). An upload after the horse example used to keep its size 300, round 3 and thicken 1: a square
// cube came back with 14 mm corners and its 15 mm hole closed to 3.5 mm.
export const MODEL_BOUND=['axes','curve','branches','dowels','skip','offset','tilt','roll','thick','grow','pivot','center','extra_x','extra_y',
  'rotate','size','scale','shrinkwrap','hollow','thicken','round','smooth'];
export function setMode(name,keep=true){
  const prev=ST.mode; ST.mode=ST.MODES.find(m=>m.name===name)||ST.MODES[0]; location.hash=ST.mode.name;
  if(prev&&prev!==ST.mode)memo[prev.name]=Object.fromEntries(prev.params.map(p=>[p.name,structuredClone(state[p.name])]));
  for(const p of ST.mode.common) if(!(keep&&p.name in state)) state[p.name]=structuredClone(p.default);
  for(const p of ST.mode.params) state[p.name]=keep&&memo[ST.mode.name]&&p.name in memo[ST.mode.name]?structuredClone(memo[ST.mode.name][p.name]):(keep&&prev===ST.mode&&p.name in state?state[p.name]:structuredClone(p.default));
  $$('#modes button').forEach(b=>b.classList.toggle('on',b.dataset.m===ST.mode.name)); $('#mdesc').textContent=ST.mode.description;
  renderFields();
}
export function showTab(t){$$('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));$$('section[data-tab]').forEach(s=>s.classList.toggle('on',s.dataset.tab===t));
  rings.visible=t==='model';ST.dirty=true}   // the turn rings only clutter the view outside the Model tab
export function schedule(){clearTimeout(ST.timer);ST.timer=setTimeout(()=>{ST.timer=null;slice()},350)}

export function syncSizeHints(){const p=allParams().find(q=>q.name==='size'); if(!p||!ST.plan)return;
  const sq=ST.plan.square, row=$('#square'); row.hidden=!sq;
  if(sq){row.querySelector('.hint').textContent=`sits ${sq.off}° off square`;const b=row.querySelector('button');
    b.textContent=`square it up (rotate ${sq.rotate.join(', ')})`;b.onclick=()=>applyFix({rotate:sq.rotate})}
  for(let i=0;i<3;i++){const el=$('#p_size_'+i); if(el)el.placeholder=+(+show(p,ST.plan.bbox[i])).toPrecision(3)}}   // a hint, not a value: three figures fit the box in every unit
