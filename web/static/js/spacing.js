import {state, ST} from './state.js';
import {$, esc, nice} from './util.js';
import {toMM, inU, lenTxt} from './units.js';
import {allParams, setVal, renderFields} from './form.js';

// ---------------------------------------------------------------- the spacing curve editor, under the 3D view
// One graph per `curve` parameter of the technique: the distance between neighbouring slices against the position
// along the way (or the angle round the axis, periodic, for radial). Drag a point; double-click adds one; alt-click
// removes one. The ticks are where the plan actually put the slices. Lengths are shown in the unit on the toolbar.
const spc={drag:null,hover:null,pts:{}};
const curveParams=()=>ST.mode?ST.mode.params.filter(p=>p.type==='curve'):[];
const spcDeg=()=>(allParams().find(p=>p.name==='spacing_min')||{}).unit==='deg';
export function renderSpacing(){
  const box=$('#spacing'), cps=curveParams();
  if(!cps.length||!state.spacing_vary){box.hidden=true;box.innerHTML='';return}
  box.hidden=false;
  const deg=spcDeg(), u=deg?'°':ST.unit, pm=allParams().find(p=>p.name==='spacing_min'), px=allParams().find(p=>p.name==='spacing_max');
  if(!box.querySelector('.graphs')||box.dataset.mode!==ST.mode.name||box.dataset.n!==String(cps.length)){
    box.dataset.mode=ST.mode.name; box.dataset.n=cps.length;
    box.innerHTML=`<div class="hd"><b>spacing</b>
      <label>keep <select id="spc_fix"><option value="count">the count</option><option value="curve">the spacings as drawn</option></select></label>
      <label>from <input type="number" id="spc_min" step="any"> ${esc(u)}</label><label>to <input type="number" id="spc_max" step="any"> ${esc(u)}</label>
      <span class="hint">drag a point · double-click adds one · alt-click removes one</span></div>
      <div class="graphs">${cps.map(p=>`<div><canvas id="spc_${p.name}" width="900" height="300" data-param="${p.name}"></canvas><div class="cap" id="spcc_${p.name}"><span>${esc(p.label||nice(p.name))}</span><span></span></div></div>`).join('')}</div>`;
    $('#spc_fix').onchange=e=>{setVal('spacing_fix',{count:'count',curve:'curve'}[e.target.value]||'count');renderFields()};
    for(const [id,name] of [['#spc_min','spacing_min'],['#spc_max','spacing_max']])$(id).onchange=e=>{const v=deg?+e.target.value:toMM(+e.target.value);if(v>0){setVal(name,v);renderFields()}};
    for(const c of box.querySelectorAll('canvas'))spcBind(c);
  }
  $('#spc_fix').value=state.spacing_fix||'count'; $('#spc_min').value=deg?state.spacing_min:inU(state.spacing_min); $('#spc_max').value=deg?state.spacing_max:inU(state.spacing_max);
  for(const p of cps)spcDraw(p.name);
}
const SPAD={l:46,r:12,t:10,b:26};
function spcGeom(c){const W=c.width,H=c.height;return {W,H,gx:t=>SPAD.l+t*(W-SPAD.l-SPAD.r),gy:v=>H-SPAD.b-v*(H-SPAD.t-SPAD.b)}}
// the curve as drawn: y as a fraction of from…to, so the graph always shows the whole range
const spcPts=name=>{const lo=+state.spacing_min||0,hi=Math.max(lo+1e-6,+state.spacing_max||1);return (state[name]||[]).map(([t,s])=>[+t,Math.min(1,Math.max(0,(s-lo)/(hi-lo)))])};
const spcStore=(name,pts)=>{const lo=+state.spacing_min||0,hi=Math.max(lo+1e-6,+state.spacing_max||1);return pts.map(([t,v])=>[+t.toFixed(4),+(lo+(hi-lo)*v).toFixed(3)])};
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
  const c=$('#spc_'+name); if(!c)return; const g=c.getContext('2d'), {W,H,gx,gy}=spcGeom(c), deg=spcDeg(), periodic=deg;
  const pts=spc.drag&&spc.drag.name===name?spc.pts[name]:spcPts(name), lo=+state.spacing_min||0, hi=Math.max(lo+1e-6,+state.spacing_max||1);
  const col=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim();
  g.clearRect(0,0,W,H); g.fillStyle='#17181c'; g.fillRect(0,0,W,H);
  g.strokeStyle=col('--line'); g.lineWidth=1; g.font='11px system-ui,sans-serif'; g.fillStyle=col('--muted');
  const lab=v=>deg?`${v.toFixed(0)}°`:`${inU(v)}`;
  g.textAlign='right'; for(let i=0;i<=4;i++){const y=gy(i/4);g.beginPath();g.moveTo(SPAD.l,y);g.lineTo(W-SPAD.r,y);g.stroke();g.fillText(lab(lo+(hi-lo)*i/4),SPAD.l-5,y+4)}
  const sp=(ST.plan&&ST.plan.spacing||[]).find(s=>s.param===name), L=sp?sp.length:(deg?180:1);
  g.textAlign='center'; for(let i=0;i<=10;i++){const x=gx(i/10);g.beginPath();g.moveTo(x,SPAD.t);g.lineTo(x,H-SPAD.b);g.stroke();
    if(i%2===0)g.fillText(deg?`${18*i}°`:sp?`${lenTxt(L*i/10)} ${ST.unit}`:`${i*10}%`,x,H-SPAD.b+15)}
  if(sp){g.strokeStyle=col('--acc2')||'#f5b642';g.lineWidth=1.5;for(const p of sp.positions){const x=gx(p/L);g.beginPath();g.moveTo(x,H-SPAD.b);g.lineTo(x,H-SPAD.b-8);g.stroke()}}
  const f=spcSpline(pts,periodic); g.strokeStyle=col('--acc'); g.lineWidth=2.2; g.beginPath();
  for(let i=0;i<=200;i++){const t=i/200,v=Math.min(1,Math.max(0,f(t)));i?g.lineTo(gx(t),gy(v)):g.moveTo(gx(t),gy(v))} g.stroke();
  pts.forEach(([t,v],i)=>{g.beginPath();g.arc(gx(t),gy(v),spc.hover&&spc.hover.name===name&&spc.hover.i===i?7:5.5,0,7);
    g.fillStyle=periodic&&(i===0||i===pts.length-1)?(col('--acc2')||'#f5b642'):col('--acc');g.fill();g.strokeStyle='#17181c';g.lineWidth=2;g.stroke()});
  const cap=$('#spcc_'+name); if(cap&&sp){const gaps=sp.positions.slice(1).map((p,i)=>p-sp.positions[i]);if(periodic)gaps.push(180-sp.positions[sp.positions.length-1]);
    const mn=Math.min(...gaps),mx=Math.max(...gaps), far=Math.abs(sp.scale-1)>0.5;
    cap.lastElementChild.innerHTML=`${sp.positions.length} ${deg?'planes':'slices'} · ${deg?`${mn.toFixed(1)}°…${mx.toFixed(1)}°`:`${esc(lenTxt(mn))}…${esc(lenTxt(mx))} ${esc(ST.unit)}`} apart`+(state.spacing_fix==='count'?` · curve scaled <b${far?' style="color:var(--warn)"':''}>${sp.scale.toFixed(2)}×</b>`:'')}
}
function spcBind(c){
  const name=c.dataset.param, pos=e=>{const r=c.getBoundingClientRect();return [(e.clientX-r.left)*c.width/r.width,(e.clientY-r.top)*c.height/r.height]};
  const near=(pts,x,y)=>{const {gx,gy}=spcGeom(c);let b=-1,bd=14;pts.forEach(([t,v],i)=>{const d=Math.hypot(gx(t)-x,gy(v)-y);if(d<bd){bd=d;b=i}});return b};
  c.addEventListener('pointerdown',e=>{const [x,y]=pos(e),pts=spcPts(name),i=near(pts,x,y);
    if(i>=0&&e.altKey){if(pts.length>2&&i>0&&i<pts.length-1){pts.splice(i,1);setVal(name,spcStore(name,pts));spcDraw(name)}return}
    if(i>=0){spc.drag={name,i};spc.pts[name]=pts;c.setPointerCapture(e.pointerId);c.style.cursor='grabbing'}});
  c.addEventListener('pointermove',e=>{const [x,y]=pos(e),{W,H}=spcGeom(c);
    if(!spc.drag||spc.drag.name!==name){const i=near(spcPts(name),x,y),h=i>=0?{name,i}:null;if(JSON.stringify(h)!==JSON.stringify(spc.hover)){spc.hover=h;c.style.cursor=h?'grab':'crosshair';spcDraw(name)}return}
    const pts=spc.pts[name],i=spc.drag.i,n=pts.length;
    let t=(x-SPAD.l)/(W-SPAD.l-SPAD.r),v=Math.min(1,Math.max(0,(H-SPAD.b-y)/(H-SPAD.t-SPAD.b)));
    t=i===0?0:i===n-1?1:Math.min(pts[i+1][0]-0.02,Math.max(pts[i-1][0]+0.02,t));
    pts[i]=[t,v]; if(spcDeg()&&(i===0||i===n-1)){pts[0][1]=v;pts[n-1][1]=v}   // the fan closes on itself
    spcDraw(name)});
  const done=()=>{if(!spc.drag||spc.drag.name!==name)return;const pts=spc.pts[name];spc.drag=null;c.style.cursor='grab';setVal(name,spcStore(name,pts))};
  c.addEventListener('pointerup',done); c.addEventListener('pointercancel',done);
  c.addEventListener('dblclick',e=>{const [x,y]=pos(e),{W,H}=spcGeom(c),pts=spcPts(name);if(near(pts,x,y)>=0)return;
    const t=Math.min(0.98,Math.max(0.02,(x-SPAD.l)/(W-SPAD.l-SPAD.r))),v=Math.min(1,Math.max(0,(H-SPAD.b-y)/(H-SPAD.t-SPAD.b)));
    pts.push([t,v]);pts.sort((a,b)=>a[0]-b[0]);setVal(name,spcStore(name,pts));spcDraw(name)});
}
