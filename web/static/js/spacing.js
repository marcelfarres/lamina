import {state, ST} from './state.js';
import {$, $$, esc} from './util.js';
import {toMM, inU} from './units.js';
import {allParams, setVal} from './form.js';

// ---------------------------------------------------------------- the spacing curve editor, in the form under its tick
// One graph per `curve` parameter of the technique: the gap between neighbouring slices against the position along the
// way (or the angle round the axis, periodic, for radial). The upright lines are where the plan put the slices, and the
// strip under the graph is the model drawn from them: one bar a slice, as wide as the slice. Drag a point; double-click
// adds one; every gesture has a button too. Lengths are shown in the ST.unit on the toolbar.
const spc={drag:null,hover:null,pts:{},sel:{}};
const curveParams=()=>ST.mode?ST.mode.params.filter(p=>p.type==='curve'):[];
const spcDeg=()=>(allParams().find(p=>p.name==='spacing_min')||{}).unit==='deg';
const spcRange=()=>{const lo=+state.spacing_min||0;return [lo,Math.max(lo+1e-6,+state.spacing_max||1)]};
const spcPlan=name=>(ST.plan&&ST.plan.spacing||[]).find(s=>s.param===name);
// The widths of the slices a curve spread, in its order, where the plan tells: the group of slices that is as many as
// the curve's positions (the n-th curve of that many takes the n-th such group).
// ponytail: matched by count, so a slice dropped by the checks means no strip; the planner could send the widths with the positions
function spcWidths(name){
  const sp=spcPlan(name); if(!sp||!ST.plan.slices||spcDeg())return null;
  const by={}; for(const s of ST.plan.slices)(by[s.group]??=[]).push(s);
  const n=sp.positions.length, fit=Object.values(by).filter(a=>a.length===n), k=ST.plan.spacing.filter(s=>s.positions.length===n).indexOf(sp);
  const a=fit[Math.min(k,fit.length-1)]; return a&&n>1?a.map(s=>Math.max(...s.extents)):null}
// the shapes a curve can start from: [what the chip says, the points from `at` (0 = the least gap … 1 = the most)]
const SPC_SHAPES={even:['even',at=>[[0,at(.5)],[.5,at(.5)],[1,at(.5)]]],ends:['dense at both ends',at=>[[0,at(.1)],[.5,at(.8)],[1,at(.1)]]],
  mid:['dense in the middle',at=>[[0,at(.8)],[.5,at(.1)],[1,at(.8)]]],start:['dense at the start',at=>[[0,at(.1)],[1,at(.8)]]],model:['✦ follow the model',(at,name)=>spcFollow(at,name)]};
// small gaps where the model's width changes fast between neighbouring slices, large ones where it does not, at 7 places
// ponytail: read off the slices of the plan on screen, nearest sample; a finer first slicing gives a finer proposal
function spcFollow(at,name){
  const sp=spcPlan(name), w=spcWidths(name); if(!w||w.length<4)return null;
  const q=sp.positions, r=w.slice(1).map((x,i)=>Math.abs(x-w[i])/Math.max(1e-6,q[i+1]-q[i])), t=r.map((_,i)=>(q[i]+q[i+1])/2/sp.length), mx=Math.max(...r,1e-9);
  return [0,1,2,3,4,5,6].map(k=>{const u=k/6, near=r.filter((_,i)=>Math.abs(t[i]-u)<=1/6);   // the mean over a sixth of the way either side
    return [+u.toFixed(4),at(.85-.75*(near.length?near.reduce((a,b)=>a+b)/near.length:0)/mx)]})}
export function renderSpacing(){
  const deg=spcDeg();
  for(const box of $$('.spc')){const name=box.dataset.param;
    if(!box.firstChild){
      box.innerHTML=`<div class="chips"><span class="hint">start from</span>${Object.entries(SPC_SHAPES).filter(([k])=>!(deg&&(k==='start'||k==='model'))).map(([k,[t]])=>`<button class="small" data-spc="shape" data-arg="${k}">${t}</button>`).join('')}</div>
        <canvas width="744" height="430" data-param="${name}"></canvas><div class="cap"></div><div class="row pt"></div>
        <div class="row"><button class="small" data-spc="add">+ add point</button><button class="small" data-spc="smooth">smooth</button><button class="small" data-spc="reset">↺ reset curve</button></div>
        <div class="hint">drag a point · double-click the line adds one · the upright lines are the ${deg?'planes':'slices'}</div>`;
      spcBind(box.querySelector('canvas'));
      box.onclick=e=>{const b=e.target.closest('button[data-spc]');if(b)spcDo(name,b.dataset.spc,b.dataset.arg)};
      box.onchange=e=>{if(e.target.dataset.spc)spcDo(name,'type')}}
    spcDraw(name)}
}
// what a button of the graph does to its curve
function spcDo(name,act,arg){
  const p=curveParams().find(q=>q.name===name), [lo,hi]=spcRange(), deg=spcDeg(), at=f=>+(lo+(hi-lo)*f).toFixed(3), n0=(state[name]||[]).length;
  let pts=(state[name]||[]).map(q=>[+q[0],+q[1]]), i=spc.sel[name];
  if(act==='add'){if(pts.length<2)return;let b=0;for(let k=1;k<pts.length-1;k++)if(pts[k+1][0]-pts[k][0]>pts[b+1][0]-pts[b][0])b=k;   // in the widest stretch, on the curve
    const t=(pts[b][0]+pts[b+1][0])/2;pts.splice(b+1,0,[+t.toFixed(4),+spcSpline(pts,deg)(t).toFixed(3)]);spc.sel[name]=b+1}
  else if(act==='del'){if(!(pts.length>2&&i>0&&i<pts.length-1))return;pts.splice(i,1);delete spc.sel[name]}
  else if(act==='smooth')pts=pts.map(([t,v],k)=>[t,k&&k<pts.length-1?+((pts[k-1][1]+2*v+pts[k+1][1])/4).toFixed(3):v]);
  else if(act==='reset'){pts=structuredClone(p.default);delete spc.sel[name]}
  else if(act==='shape'){pts=SPC_SHAPES[arg][1](at,name);if(!pts)return;delete spc.sel[name]}
  else if(act==='type'){const box=$(`.spc[data-param="${name}"]`),ti=box.querySelector('[data-spc=t]'),vi=box.querySelector('[data-spc=v]'),sp=spcPlan(name),L=deg?180:sp?sp.length:0;
    if(!(i>=0&&i<n0)||!vi)return; const v=deg?+vi.value:toMM(+vi.value); if(v>0)pts[i][1]=+Math.min(hi,Math.max(lo,v)).toFixed(3);
    if(ti&&!ti.disabled&&L){const t=(deg?+ti.value:toMM(+ti.value))/L;pts[i][0]=+Math.min(pts[i+1][0]-0.02,Math.max(pts[i-1][0]+0.02,t)).toFixed(4)}}
  if(deg&&pts.length>1)pts[pts.length-1][1]=pts[0][1];   // the fan closes on itself
  setVal(name,pts); spcDraw(name)}
const SPC={l:86,r:14,t:14,b:312};   // the plot inside the canvas, in its own pixels (two a screen pixel): left and right margins, top and bottom edges
function spcGeom(c){const W=c.width;return {W,gx:t=>SPC.l+t*(W-SPC.l-SPC.r),gy:v=>SPC.b-v*(SPC.b-SPC.t)}}
// the curve as drawn: y as a fraction of from…to, so the graph always shows the whole range
const spcPts=name=>{const [lo,hi]=spcRange();return (state[name]||[]).map(([t,s])=>[+t,Math.min(1,Math.max(0,(s-lo)/(hi-lo)))])};
const spcStore=(name,pts)=>{const [lo,hi]=spcRange();return pts.map(([t,v])=>[+t.toFixed(4),+(lo+(hi-lo)*v).toFixed(3)])};
// monotone cubic (Fritsch–Carlson) through the points, periodic for radial: the same curve the planner draws
function spcSpline(pts,periodic){
  const n=pts.length,x=pts.map(p=>p[0]),y=pts.map(p=>p[1]); if(n<2)return t=>n?y[0]:0;
  if(periodic)y[n-1]=y[0];
  const h=[],d=[]; for(let i=0;i<n-1;i++){h.push(x[i+1]-x[i]);d.push(h[i]>1e-12?(y[i+1]-y[i])/h[i]:0)}
  const m=new Array(n).fill(0); for(let i=1;i<n-1;i++)m[i]=d[i-1]*d[i]<=0?0:(d[i-1]+d[i])/2;
  if(periodic)m[0]=m[n-1]=d[n-2]*d[0]<=0?0:(d[n-2]+d[0])/2; else{m[0]=d[0];m[n-1]=d[n-2]}
  for(let i=0;i<n-1;i++){if(d[i]===0){m[i]=m[i+1]=0;continue}const a=m[i]/d[i],b=m[i+1]/d[i],s=a*a+b*b;if(s>9){const q=3/Math.sqrt(s);m[i]=q*a*d[i];m[i+1]=q*b*d[i]}}
  return t=>{t=Math.min(x[n-1],Math.max(x[0],t));let i=0;while(i<n-2&&t>x[i+1])i++;if(h[i]<=1e-12)return y[i];const u=(t-x[i])/h[i],u2=u*u,u3=u2*u;
    return (2*u3-3*u2+1)*y[i]+(u3-2*u2+u)*h[i]*m[i]+(-2*u3+3*u2)*y[i+1]+(u3-u2)*h[i]*m[i+1]}}
function spcDraw(name){
  const box=$(`.spc[data-param="${name}"]`), c=box&&box.querySelector('canvas'); if(!c)return;
  const deg=spcDeg(), periodic=deg, [lo,hi]=spcRange(), wd=spcWidths(name), H=wd?430:376; if(c.height!==H)c.height=H;   // room for the model strip only when there is one
  const g=c.getContext('2d'), {W,gx,gy}=spcGeom(c), pts=spc.drag&&spc.drag.name===name?spc.pts[name]:spcPts(name), sel=spc.sel[name];
  const col=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim(), mid=(SPC.l+W-SPC.r)/2;
  g.fillStyle='#17181c'; g.fillRect(0,0,W,H);
  g.strokeStyle=col('--line'); g.lineWidth=2; g.font='21px system-ui,sans-serif'; g.fillStyle=col('--muted');
  const n3=v=>+(+v).toPrecision(3), lab=v=>deg?`${v.toFixed(0)}°`:`${n3(inU(v))}`;   // three figures: an axis number, not a measurement
  g.textAlign='right'; for(let i=0;i<=3;i++){const y=gy(i/3);g.beginPath();g.moveTo(SPC.l,y);g.lineTo(W-SPC.r,y);g.stroke();g.fillText(lab(lo+(hi-lo)*i/3),SPC.l-9,y+7)}
  const sp=spcPlan(name), L=sp?sp.length:(deg?180:1);
  if(sp){g.strokeStyle='#f5b64266';g.lineWidth=2;for(const q of sp.positions){const x=gx(q/L);g.beginPath();g.moveTo(x,SPC.t);g.lineTo(x,SPC.b);g.stroke()}}
  for(let i=0;i<=4;i++){g.textAlign=i===0?'left':i===4?'right':'center';g.fillText(deg?`${45*i}°`:sp?`${n3(inU(L*i/4))}`:`${i*25}%`,gx(i/4),SPC.b+27)}
  g.fillStyle=col('--ink'); g.textAlign='center';
  g.fillText(deg?'angle round the axis · 0° → 180°':`along the model${sp?` (${ST.unit})`:''} · start → end`,mid,SPC.b+56);
  g.save(); g.translate(22,(SPC.t+SPC.b)/2); g.rotate(-Math.PI/2); g.fillText(deg?'angle between planes (°)':`gap between slices (${ST.unit})`,0,0); g.restore();
  const f=spcSpline(pts,periodic); g.strokeStyle=col('--acc'); g.lineWidth=4.5; g.beginPath();
  for(let i=0;i<=200;i++){const t=i/200,v=Math.min(1,Math.max(0,f(t)));i?g.lineTo(gx(t),gy(v)):g.moveTo(gx(t),gy(v))} g.stroke();
  pts.forEach(([t,v],i)=>{const on=i===sel, hot=spc.hover&&spc.hover.name===name&&spc.hover.i===i;g.beginPath();g.arc(gx(t),gy(v),on?15:hot?13:10,0,7);
    g.fillStyle=col('--acc');g.fill();g.strokeStyle=on?'#fff':'#17181c';g.lineWidth=4;g.stroke()});
  if(wd){const mx=Math.max(...wd)||1, cy=SPC.b+88; g.fillStyle=col('--muted'); g.textAlign='right'; g.fillText('model',SPC.l-9,cy+7);
    g.strokeStyle='#c9b27a'; g.lineWidth=4; sp.positions.forEach((q,i)=>{const x=gx(q/L),h=24*wd[i]/mx;g.beginPath();g.moveTo(x,cy-h);g.lineTo(x,cy+h);g.stroke()})}
  const cap=box.querySelector('.cap');
  if(sp){const gaps=sp.positions.slice(1).map((q,i)=>q-sp.positions[i]);if(periodic)gaps.push(180-sp.positions[sp.positions.length-1]);
    const mn=Math.min(...gaps),mx=Math.max(...gaps), far=Math.abs(sp.scale-1)>0.5;
    cap.innerHTML=`<b>${sp.positions.length} ${deg?'planes':'slices'}</b> · ${deg?`${mn.toFixed(1)}°…${mx.toFixed(1)}°`:`${n3(inU(mn))}…${n3(inU(mx))} ${esc(ST.unit)}`} apart`+(state.spacing_fix==='count'?` · gaps drawn × <b>${far?'⚠ ':''}${sp.scale.toFixed(2)}</b> to fit the count`:'')}
  else cap.textContent='';
  // the selected point's two numbers, to type; not redrawn under the cursor while one is being typed
  const row=box.querySelector('.pt'), raw=state[name]||[], u=deg?'°':esc(ST.unit);
  if(!(sel>=0&&sel<raw.length)){row.dataset.sel='';row.innerHTML='<span class="hint">click a point to type its numbers</span>';return}
  const end=sel===0||sel===raw.length-1, at=deg?+(raw[sel][0]*180).toFixed(1):sp?n3(inU(raw[sel][0]*L)):null, gap=n3(deg?raw[sel][1]:inU(raw[sel][1])), key=`${sel}/${raw.length}/${at==null}`;
  // the same point still: its numbers change in place, so a button of the row is the same button from press to release
  if(row.dataset.sel===key){for(const [k,v] of [['t',at],['v',gap]]){const el=row.querySelector(`[data-spc=${k}]`);if(el&&el!==document.activeElement)el.value=v}return}
  row.dataset.sel=key;
  row.innerHTML=`<b>point ${sel+1}</b>${at==null?'':` at <input type="number" step="any" data-spc="t" value="${at}" ${end?'disabled':''}> ${u}`} · gap <input type="number" step="any" data-spc="v" value="${gap}"> ${u}
    <button class="small" data-spc="del" ${end?'disabled title="the first and the last point stay"':''}>✕ remove point</button>`;
}
function spcBind(c){
  const name=c.dataset.param, pos=e=>{const r=c.getBoundingClientRect();return [(e.clientX-r.left)*c.width/r.width,(e.clientY-r.top)*c.height/r.height]};
  const near=(pts,x,y)=>{const {gx,gy}=spcGeom(c);let b=-1,bd=28;pts.forEach(([t,v],i)=>{const d=Math.hypot(gx(t)-x,gy(v)-y);if(d<bd){bd=d;b=i}});return b};
  const frac=(x,y)=>[(x-SPC.l)/(c.width-SPC.l-SPC.r),Math.min(1,Math.max(0,(SPC.b-y)/(SPC.b-SPC.t)))];
  c.addEventListener('pointerdown',e=>{const [x,y]=pos(e),pts=spcPts(name),i=near(pts,x,y);
    if(i>=0&&e.altKey){spc.sel[name]=i;spcDo(name,'del');return}
    if(i>=0){spc.sel[name]=i;spc.drag={name,i};spc.pts[name]=pts;c.setPointerCapture(e.pointerId);c.style.cursor='grabbing';spcDraw(name)}});
  c.addEventListener('pointermove',e=>{const [x,y]=pos(e);
    if(!spc.drag||spc.drag.name!==name){const i=near(spcPts(name),x,y),h=i>=0?{name,i}:null;if(JSON.stringify(h)!==JSON.stringify(spc.hover)){spc.hover=h;c.style.cursor=h?'grab':'crosshair';spcDraw(name)}return}
    const pts=spc.pts[name],i=spc.drag.i,n=pts.length; let [t,v]=frac(x,y);
    t=i===0?0:i===n-1?1:Math.min(pts[i+1][0]-0.02,Math.max(pts[i-1][0]+0.02,t));
    pts[i]=[t,v]; if(spcDeg()&&(i===0||i===n-1)){pts[0][1]=v;pts[n-1][1]=v}   // the fan closes on itself
    spcDraw(name)});
  const done=()=>{if(!spc.drag||spc.drag.name!==name)return;const pts=spc.pts[name];spc.drag=null;c.style.cursor='grab';setVal(name,spcStore(name,pts));spcDraw(name)};
  c.addEventListener('pointerup',done); c.addEventListener('pointercancel',done);
  c.addEventListener('dblclick',e=>{const [x,y]=pos(e),pts=spcPts(name);if(near(pts,x,y)>=0)return;
    const [t0,v]=frac(x,y),t=Math.min(0.98,Math.max(0.02,t0));
    pts.push([t,v]);pts.sort((a,b)=>a[0]-b[0]);spc.sel[name]=pts.findIndex(q=>q[0]===t);setVal(name,spcStore(name,pts));spcDraw(name)});
}
// where a curve point (position 0…1, gap) is on the screen: for the tests and the media script
export const spcXY=(name,t,v)=>{const c=$(`.spc[data-param="${name}"] canvas`),r=c.getBoundingClientRect(),{gx,gy}=spcGeom(c),[lo,hi]=spcRange();return [r.left+gx(t)*r.width/c.width,r.top+gy((v-lo)/(hi-lo))*r.height/c.height]};
