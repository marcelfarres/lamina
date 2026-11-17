import * as THREE from 'three';
import {state, ST} from './state.js';
import {PLANE_IDX} from './catalog.js';
import {$, $$, status} from './util.js';
import {bounds, show, UNIT, toMM, inU, fmtLen, niceStep} from './units.js';
import {renderFields} from './form.js';
import {slice} from './slice.js';
import {renderer, ray, camera, gizmo, guides, parts, rings, mat4, V3, cubeHit, controls, placeRod, ghost, applyExplode, viewFrom} from './scene.js';
import {hlSheet} from './results.js';
import {seamClick} from './seams.js';

// selection, gizmo, drag editing
let down=null, drag=null;
function ndc(ev){const r=renderer.domElement.getBoundingClientRect();return new THREE.Vector2(((ev.clientX-r.left)/r.width)*2-1,-((ev.clientY-r.top)/r.height)*2+1)}
export function hit(ev){ray.setFromCamera(ndc(ev),camera);const g=ray.intersectObjects(gizmo.children);if(g.length)return g[0];   // the arrow wins even when a part is in front of it
  const cp=ray.intersectObjects(guides.children.filter(o=>o.userData.cp!==undefined||o.userData.ax!==undefined||o.userData.axline!==undefined));if(cp.length)return cp[0];   // curve points, axis rods and ends too: they draw on top, so they pick on top
  // rotation rings (Model tab only), and not while a slice runs: they are the last model's size then, and a drag meant
  // to turn the view caught one and stood the new model on its head (reported on the statue, picked from the list)
  const h=ray.intersectObjects(parts.children.filter(m=>m.visible))[0]||null;
  // A ring seen edge-on is a line through the model (every flat view from the cube has two): it cannot be seen to be
  // grabbed, yet a drag on the model caught one and turned the model over, with a slice to follow (reported from a
  // Mac). Face-on enough, a ring is grabbed wherever it shows — it draws through the model, so its far side too
  const d=ray.ray.direction, rg=rings.visible&&!ST.busy?ray.intersectObjects(rings.children).filter(x=>Math.abs(d.getComponent(x.object.userData.ring))>0.2):[];
  return rg[0]||h}
function screenAngle(ev,centre){const r=renderer.domElement.getBoundingClientRect(),c=centre.clone().project(camera);return Math.atan2(-(ev.clientY-r.top)+(1-c.y)/2*r.height*-1+r.height-(1-c.y)/2*r.height,(ev.clientX-r.left)-(c.x+1)/2*r.width)}
export const pick=ev=>{const h=hit(ev);return h&&!h.object.userData.gizmo?h.object:null};
const __screen=p=>{const r=renderer.domElement.getBoundingClientRect(),q=p.clone().project(camera);return [r.left+(q.x+1)/2*r.width,r.top+(1-q.y)/2*r.height]};
// How far to move along two world directions so a point follows the pointer across the screen. Dragging used to work
// the other way — the mouse ray was intersected with the plane the point lives in — and seen edge-on that plane
// turned a few pixels into hundreds of millimetres along a direction you could not even see. This reads the pointer
// instead: how many pixels a millimetre along U and along V is worth right now, then the least-squares answer. The
// damping is what makes an edge-on view safe: a direction worth almost no pixels gets almost no movement.
function inPlane(P0,U,V,dx,dy,s){
  const o=__screen(P0),a=__screen(P0.clone().addScaledVector(U,s)),b=__screen(P0.clone().addScaledVector(V,s));
  const A=[[(a[0]-o[0])/s,(b[0]-o[0])/s],[(a[1]-o[1])/s,(b[1]-o[1])/s]];
  const g11=A[0][0]**2+A[1][0]**2, g22=A[0][1]**2+A[1][1]**2, g12=A[0][0]*A[0][1]+A[1][0]*A[1][1];
  const lam=0.02*(g11+g22), det=(g11+lam)*(g22+lam)-g12*g12;
  if(!(Math.abs(det)>1e-12))return [0,0];
  const r1=A[0][0]*dx+A[1][0]*dy, r2=A[0][1]*dx+A[1][1]*dy;
  return [((g22+lam)*r1-g12*r2)/det,((g11+lam)*r2-g12*r1)/det];
}
// The selected plane's own middle, on the plane itself: where its handles sit and what it turns about. Not the
// middle of its bounding box — for a half-slice or a crescent that lands off the material — but the centroid of the
// outline the part is cut to, which is where a person points when they say "the middle of this piece".
export let pivot3=null;
function partCentre(m){
  const S=slicePlan(m.userData.slice), o=m.userData.origin, n=m.userData.normal;
  const rings=(S?.pieces||[]).flatMap(pc=>pc.facets.map(fc=>[fc.M,fc.rings[0]])).filter(([,r])=>r&&r.length>2);
  let A=0,cx=0,cy=0,M0=null;
  for(const [M,r] of rings){                       // shoelace in the facet's own 2D, so the areas add up honestly
    M0=M0||M;
    for(let i=0;i<r.length;i++){const [x0,y0]=r[i],[x1,y1]=r[(i+1)%r.length],w=x0*y1-x1*y0;A+=w;cx+=(x0+x1)*w;cy+=(y0+y1)*w}
  }
  if(!M0||Math.abs(A)<1e-9){                       // no outline to speak of: fall back to the box
    m.geometry.computeBoundingBox();
    const C=m.geometry.boundingBox.getCenter(new THREE.Vector3());
    return C.addScaledVector(n,-C.clone().sub(o).dot(n));
  }
  const u=cx/(3*A), v=cy/(3*A), F=mat4(M0);
  const C=new THREE.Vector3(u,v,0).applyMatrix4(F);
  return C.addScaledVector(n,-C.clone().sub(o).dot(n));   // and onto the plane, where the handles belong
}
function partSize(m){m.geometry.computeBoundingBox();return m.geometry.boundingBox.getSize(new THREE.Vector3()).length()}
// A plane has three handles and no more, because a plane has no more: the arrow slides it along its normal (sideways
// would not change the part at all), and the two rings tilt and roll it about its own middle.
export function drawGizmo(m){
  gizmo.clear(); if(!m)return;
  pivot3=partCentre(m);
  const c=pivot3.clone().add(m.position);                      // where it is drawn: the part's spot, exploded or not
  // Sized to the part, not to the model: the arrow stands a little way off each face of this piece, which is the
  // distance it can be slid, and the rings sit just inside its outline.
  const n=m.userData.normal, R=Math.max(partSize(m)*0.36,Math.max(...ST.plan.bbox)*0.04), L=R*0.95;
  const mat=col=>new THREE.MeshBasicMaterial({color:col,depthTest:false,transparent:true,opacity:.95});
  const arrow=mat(0xffd84a);
  for(const s of [1,-1]){const cy=new THREE.Mesh(new THREE.CylinderGeometry(L*.022,L*.022,L*.7,10),arrow);const k=new THREE.Mesh(new THREE.ConeGeometry(L*.075,L*.26,14),arrow);
    const q=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),n.clone().multiplyScalar(s));
    cy.position.copy(c).addScaledVector(n,s*L*.35);cy.quaternion.copy(q);k.position.copy(c).addScaledVector(n,s*L*.83);k.quaternion.copy(q);
    cy.renderOrder=k.renderOrder=10;cy.userData.gizmo=k.userData.gizmo=true;cy.userData.grab=k.userData.grab='offset';gizmo.add(cy,k)}
  const dot=new THREE.Mesh(new THREE.SphereGeometry(R*.05,12,10),arrow);     // the point everything turns about
  dot.position.copy(c);dot.renderOrder=10;dot.userData.gizmo=true;gizmo.add(dot);
  const S=slicePlan(m.userData.slice); if(!S)return void(ST.dirty=true);
  // Two rings of the same radius meet at two points, and the ray picks whichever is in front — you reach for roll
  // and get tilt. Different radii never touch, so each one is always the one you grabbed.
  for(const [k,ax,col,rr] of [['tilt',0,0x5fcf80,1],['roll',1,0x4f8cff,0.78]]){
    const axis=new THREE.Vector3(S.M[0][ax],S.M[1][ax],S.M[2][ax]).normalize();
    const ring=new THREE.Mesh(new THREE.TorusGeometry(R*rr,R*.045,8,72),mat(col));
    ring.position.copy(c); ring.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),axis);
    ring.renderOrder=10; ring.userData.gizmo=true; ring.userData.grab=k; gizmo.add(ring);
  }
  ST.dirty=true;
}
const slicePlan=l=>ST.plan.slices.find(x=>x.label===l)||(ST.plan.bounds3d||[]).find(x=>x.label===l);
export function highlight(m){for(const c of parts.children)c.material.emissive.set(c.userData.slice===m.userData.slice?0x664400:0x000000);ST.selected=m.userData.slice;drawGizmo(m);ST.dirty=true;
  const g=k=>state[k]?.[ST.selected], synthetic='JPB'.includes(m.userData.group), bound=m.userData.group==='B', ext=Math.max(...ST.plan.bbox), s=ST.plan.slices.find(x=>x.label===ST.selected);
  // the same show / bounds as the form, so a slice's thickness reads and steps exactly like the thickness field
  const row=(k,lab,v,p,u)=>{const b=bounds(p);return `<div class="row"><span>${lab}</span><input type="range" id="r_${k}" min="${b.min}" max="${b.max}" step="${b.step}" value="${show(p,v)}"><input type="number" id="n_${k}" step="${b.step}" value="${show(p,v)}"><span class="hint" style="grid-column:2/4">${u}</span></div>`};
  const LEN=(min,max,step)=>({unit:'mm',min,max,step}), DEG={min:-60,max:60,step:1};
  $('#sel').hidden=false;$('#sel').innerHTML=`<b>${ST.selected}</b> <span class="hint">${m.userData.piece!==ST.selected?'('+m.userData.piece+')':''} ${s?.note||''}</span>
   ${row('offset','offset',g('offset')||0,LEN(-ext/2,ext/2,0.5),ST.unit)}${row('tilt','tilt',g('tilt')||0,DEG,'°')}${row('roll','roll',g('roll')||0,DEG,'°')}
   ${bound?'':row('thick','thick',g('thick')||state.thickness,LEN(0.1,20,0.1),ST.unit)}
   <div class="row"><span></span><span style="grid-column:2/4"><button class="small" id="s_reset">reset</button> ${synthetic?'':'<button class="small" id="s_del" style="color:var(--err)">delete</button>'} <button class="small" id="s_close">close</button></span></div>
   <small>slide or type · drag the yellow arrow to move it along its normal · drag the <b style="color:#5fcf80">green</b> ring to tilt, the <b style="color:#4f8cff">blue</b> one to roll — it turns where it stands</small>`;
  for(const k of ['offset','tilt','roll','thick']){const r=$('#r_'+k),n=$('#n_'+k);if(!r)continue;   // a lobe boundary has no thickness row
    r.oninput=()=>{n.value=r.value;preview(k,+r.value)}; r.onchange=()=>commit(k,+r.value); n.onchange=()=>{r.value=n.value;commit(k,+n.value)}}
  $('#s_reset').onclick=()=>{for(const k of ['offset','tilt','roll','thick','pivot'])delete state[k]?.[ST.selected];syncEdits();slice()}; $('#s_close').onclick=deselect;
  if($('#s_del'))$('#s_del').onclick=()=>{state.skip=[...(state.skip||[]),ST.selected];syncEdits();deselect();slice()};
  hlSheet(ST.selected); status(`${$('#status').textContent.replace(/ · selected.*$/,'')} · selected ${ST.selected}`,$('#dot').className);
}
function preview(k,v){ // live feedback while sliding, before the re-slice
  const ms=parts.children.filter(c=>c.userData.slice===ST.selected), M=(ST.plan.slices.find(x=>x.label===ST.selected)||ST.plan.bounds3d.find(x=>x.label===ST.selected)).M, f=UNIT[ST.unit];
  for(const m of ms){m.matrixAutoUpdate=true;m.position.set(0,0,0);m.rotation.set(0,0,0);
    if(k==='offset'){m.position.copy(m.userData.normal).multiplyScalar(v/f-(state.offset?.[ST.selected]||0))}
    else if(k!=='thick'){const ax=k==='tilt'?0:1,axis=new THREE.Vector3(M[0][ax],M[1][ax],M[2][ax]),o=pivot3||m.userData.origin,   // about the part's own middle, like the server
      T=new THREE.Matrix4().makeTranslation(o.x,o.y,o.z),R=new THREE.Matrix4().makeRotationAxis(axis,(v-(state[k]?.[ST.selected]||0))*Math.PI/180);m.matrixAutoUpdate=false;m.matrix.copy(T).multiply(R).multiply(T.clone().invert())}}
  ST.dirty=true;
}
function commit(k,v){setEdit(k,k==='offset'||k==='thick'?toMM(v):v,k==='thick'?state.thickness:0)}
export function deselect(){ST.selected=null;$('#sel').hidden=true;gizmo.clear();for(const c of parts.children)c.material.emissive.set(0);hlSheet(null);ST.dirty=true}
// stored as given: rounding here to 0.01 mm turned 1/16 in (1.5875 mm) into 1.59 mm; toPrecision(12) only drops float noise
function setEdit(k,v,neutral=0){state[k]=state[k]||{};if(Math.abs(v-neutral)>1e-9)state[k][ST.selected]=+v.toPrecision(12);else delete state[k][ST.selected];
  keepPivot(); syncEdits(); slice()}
// The server cannot know where a part's middle is — the plane it cuts on passes through the whole model — so the
// view tells it, and only while the part is actually tilted. Back at 0° it goes, and the plane turns about its frame
// origin again, exactly as it did before any of this.
function keepPivot(){state.pivot=state.pivot||{};
  if(pivot3&&((state.tilt?.[ST.selected]||0)||(state.roll?.[ST.selected]||0)))state.pivot[ST.selected]=rnd(pivot3);
  else delete state.pivot[ST.selected]}
function syncEdits(){renderFields()}
// the rods in the 3D view are radial's axes or curve's branches
const lineParam=()=>ST.mode.params.some(p=>p.name==='branches')?'branches':'axes';
// the rods as the form holds them (mm), falling back to the ones the plan used — so the default axis can be
// dragged before `axes` has ever been filled in
export const axisList=()=>{const v=state[lineParam()];return (v&&v.length?v:(ST.plan&&ST.plan.axes3d)||[]).map(l=>l.map(q=>q.map(v=>+(+v).toFixed(1))))};
// the curve's points as the form holds them, else the ones the plan drew, in-plane only (the plan's carry a third value)
export const curveList=()=>(state.curve&&state.curve.length?state.curve:(ST.plan&&ST.plan.curve_pts)||[]).map(x=>[x[0],x[1]]);
// a branch out to P from the nearest point of the curve, its joint a third of the way out, inside the body — moved
// across the curve's plane to P's own side, so a leg splayed to the side of the curve has its joint in the leg, not
// in the air between the legs. Measured on the horse: all four legs held, no errors. An arm, out to the side of the
// curve rather than below it, keeps the straight line
export const branchTo=P=>{const c=V3(ST.plan.curve3d.reduce((a,q)=>V3(q).distanceTo(P)<V3(a).distanceTo(P)?q:a)),[ui,vi]=PLANE_IDX[state.plane||'xz'];
  const w=V3(ST.plan.axes[3-ui-vi]), v=P.clone().sub(c), inP=v.clone().addScaledVector(w,-v.dot(w));
  return [rnd(P.clone().addScaledVector(inP.length()>v.length()/2?inP:v,-.65)),rnd(P)]};
// drop line i (a radial axis or a curve branch) with the per-slice edits made for its parts; a later line's parts
// move down a number (R3-2 → R2-2, J-4 → J-3, B-2-4 → B-2-3) and their edits go with them
export function dropLine(i){const n=i+1,re=x=>x>n?x-1:x;
  const name=l=>{let m;
    if((m=l.match(/^(J-|[RK])(\d+)(-.*)?$/)))return +m[2]===n?null:m[1]+re(+m[2])+(m[3]||'');
    if((m=l.match(/^B-(\d+)-(\d+)$/)))return +m[1]===n||+m[2]===n?null:`B-${re(+m[1])}-${re(+m[2])}`;
    return l};
  for(const k of ['offset','tilt','roll','thick','pivot'])if(state[k])state[k]=Object.fromEntries(Object.entries(state[k]).map(([l,v])=>[name(l),v]).filter(([l])=>l));
  if(state.skip)state.skip=state.skip.map(name).filter(Boolean);
  const list=axisList();list.splice(i,1);return list}
export const rnd=Q=>[+Q.x.toFixed(1),+Q.y.toFixed(1),+Q.z.toFixed(1)];
// The plane the other axes share (all of them but `skipI`), or null when they leave it free: on one line, the plane
// through that line and P; on one plane, that plane; already skew, or none, nothing. A dragged axis moves in it and
// a new one is put on it, so the spine — the one sheet through every axis — survives whatever the mouse does.
// Branches each have a spine of their own: nothing to keep.
function sharedPlane(skipI,P){
  if(lineParam()==='branches')return null;
  const pts=[]; (ST.plan?ST.plan.axes3d||[]:[]).forEach((seg,i)=>{if(i!==skipI)pts.push(V3(seg[0]),V3(seg[1]))});
  if(pts.length<2)return null;
  const tol=Math.max(...ST.plan.bbox)*0.01, c=pts.reduce((a,p)=>a.add(p),new THREE.Vector3()).multiplyScalar(1/pts.length);
  let u=null,best=0; for(const p of pts)for(const q of pts){const d=q.clone().sub(p);if(d.length()>best){best=d.length();u=d.normalize()}}
  if(best<tol)return null;
  const across=p=>{const d=p.clone().sub(c);return d.addScaledVector(u,-d.dot(u))};
  let w=null,wbest=0; for(const p of pts){const d=across(p);if(d.length()>wbest){wbest=d.length();w=d}}
  if(wbest<tol){const d=across(P);return d.length()<tol?null:new THREE.Plane().setFromNormalAndCoplanarPoint(new THREE.Vector3().crossVectors(u,d).normalize(),c)}
  const n=new THREE.Vector3().crossVectors(u,w).normalize();
  return pts.some(p=>Math.abs(p.clone().sub(c).dot(n))>tol)?null:new THREE.Plane().setFromNormalAndCoplanarPoint(n,c);
}
const seed=list=>list.length?list:[[[0,0,-((ST.plan&&ST.plan.bbox)||[100,100,100])[2]/2],[0,0,((ST.plan&&ST.plan.bbox)||[100,100,100])[2]/2]]];   // + can be clicked before the first slice lands
// + on the table: the longest axis is cut in two at its middle — a snowman: one fan per ball, drag the joint to
// the waist. A new fan never sits inside another one: two fans over the same stretch fight over every crossing.
export function splitAxis(list){
  list=seed(list); let i=0,longest=-1;
  list.forEach((l,k)=>{const L=new THREE.Vector3(...l[1]).distanceTo(new THREE.Vector3(...l[0]));if(L>longest){longest=L;i=k}});
  const A=new THREE.Vector3(...list[i][0]),B=new THREE.Vector3(...list[i][1]),M=A.clone().lerp(B,.5);
  const out=list.map(l=>l.map(q=>[...q])); out.splice(i,1,[rnd(A),rnd(M)],[rnd(M),rnd(B)]); return out;
}
// alt-click on the model: a new axis through the point you clicked, parallel to the nearest one and as long — a
// dumbbell: one per ball, then drag each to its ball's centre. Each axis owns the part of the model nearest to it.
function parallelAxis(list,P){
  list=seed(list); let near=null,best=Infinity;
  for(const l of list){const A=new THREE.Vector3(...l[0]),B=new THREE.Vector3(...l[1]),d=new THREE.Line3(A,B).closestPointToPoint(P,true,new THREE.Vector3()).distanceTo(P);if(d<best){best=d;near=[A,B]}}
  const u=near[1].clone().sub(near[0]),L=u.length(); u.normalize();
  const sp=sharedPlane(-1,P); if(sp)P=sp.projectPoint(P,new THREE.Vector3());   // on the plane the others share, so the spine reaches it
  return [...list.map(l=>l.map(q=>[...q])),[rnd(P.clone().addScaledVector(u,-L/2)),rnd(P.clone().addScaledVector(u,L/2))]];
}
// A line straight up the stack through p (model mm, 0,0,0 its middle), end face to end face: one dowel through every
// layer it meets. + line goes to one side of the middle and then the other, so two presses give the two dowels that
// hold a layer — the old 0,0,0 → 0,0,0 crossed nothing and placed nothing. How far out is whichever of a few
// distances passes through the most layers: a fixed sixth of the width fell in a torus's hole and crossed none
const upLine=p=>{const a='xyz'.indexOf(state.axis||'z'),h=(ST.plan?.bbox?.[a]||100)/2;return [-h,h].map(z=>p.map((v,j)=>j===a?+z.toFixed(1):v))};
export function newLine(){const a='xyz'.indexOf(state.axis||'z'),[b,c]=[(a+1)%3,(a+2)%3],bb=ST.plan?.bbox||[0,0,0],u=bb[b]>=bb[c]?b:c;
  const side=(state.lines||[]).length%2?1:-1, up=new THREE.Vector3().setComponent(a,1);
  const at=f=>{const p=[0,0,0];p[u]=+(side*f*bb[u]).toFixed(1);return p};
  const layers=p=>new THREE.Raycaster(V3(p).setComponent(a,-bb[a]),up).intersectObjects(parts.children).length;
  return upLine([1/6,1/4,1/8,1/3,0.4].map(at).reduce((x,y)=>layers(y)>layers(x)?y:x))}
function togglePoint(h,shift){ // alt-click: dowel (stacked) in the clicked slice's plane, a curve control point in the curve plane (shift: a branch out to the click), or a radial axis at the click
  if(h.object.userData.group==='B')h=ray.intersectObjects(parts.children.filter(m=>m.visible)).find(x=>x.object.userData.group!=='B');   // a J / B plane is see-through: the click is for the part behind it
  const P=h?.point, s=h&&ST.plan.slices.find(x=>x.label===h.object.userData.slice); if(!s)return;
  if(ST.mode.params.some(p=>p.name==='lines')&&state.placement==='lines'){
    // a straight line through the click, the stack's whole height: a dowel exactly there. Alt-click on one removes
    // it: a click whose ray passes within a dowel of a line means that line — the surface point is no guide, since
    // the ray goes down the dowel's own hole and lands on a layer further on. Only the ray in front of what it hit
    // counts (and a dowel's depth past it): a line behind the part you clicked is not the one you meant
    const p=[P.x,P.y,P.z].map(v=>+v.toFixed(1)), d=state.dowel_d||6, list=state.lines||[], q=new THREE.Vector3();
    const i=list.findIndex(([s0,e0])=>ray.ray.distanceSqToSegment(V3(s0),V3(e0),q)<d*d&&q.distanceTo(ray.ray.origin)<h.distance+d);
    state.lines=i>=0?list.filter((_,k)=>k!==i):[...list,upLine(p)];
  }else if(ST.mode.params.some(p=>p.name==='dowels')){
    const L=P.clone().applyMatrix4(mat4(s.M).invert()), pt=[+L.x.toFixed(1),+L.y.toFixed(1)], d=state.dowel_d||6, list=state.dowels||[];
    const i=list.findIndex(([x,y])=>Math.hypot(x-pt[0],y-pt[1])<d); state.dowels=i>=0?list.filter((_,k)=>k!==i):[...list,pt];
    if(state.connect==='none')state.connect='tab'; state.placement='aligned';
  }else if(ST.mode.params.some(p=>p.name==='curve')&&shift){
    state.branches=[...state.branches||[],branchTo(P)];
  }else if(ST.mode.params.some(p=>p.name==='curve')){
    const idx=PLANE_IDX[state.plane||'xz'], Q=P.clone().sub(V3(ST.plan.mid)), pt=idx.map(i=>+Q.dot(V3(ST.plan.axes[i])).toFixed(1));
    const list=curveList(), i=list.findIndex(([u,v])=>Math.hypot(u-pt[0],v-pt[1])<Math.max(...ST.plan.bbox)*0.04);
    if(i>=0)list.splice(i,1); else{list.push(pt);list.sort((a,b)=>a[0]-b[0])}   // the curve runs along the plane's first axis: a new point goes where its position says
    state.curve=list;
  }else if(ST.mode.params.some(p=>p.name==='axes')){
    state.axes=parallelAxis(axisList(),P);      // a fan of its own through the click: drag it to the lobe's centre from there
  }else return;
  renderFields(); slice();
}
// The cube answers a click, on release: it used to snap on press while the orbit's own drag ran on under it, so a
// drag that began on the cube "moved a bit, then jumped to a face" (reported from a Mac). A drag on it now turns the
// view like a drag anywhere, and the cube turns with it
// The tool picked at the left of the view stands in for the key: a tablet has no alt, and nobody guesses shift-drag.
// The keys work as before, with any tool
const TOOL={alt:{altKey:true},branch:{altKey:true,shiftKey:true},tilt:{shiftKey:true},roll:{ctrlKey:true}};
const keys=ev=>({altKey:ev.altKey,shiftKey:ev.shiftKey,ctrlKey:ev.ctrlKey,...TOOL[ST.tool]});
function setTool(t){ST.tool=t;for(const b of $$('#tools button'))b.setAttribute('aria-pressed',b.dataset.tool===t)}
// the tools the technique in use has: a dowel, a curve point or an axis to add; a branch on a curve; slices to tilt
export function syncTools(){const has=n=>ST.mode.params.some(p=>p.name===n),what=has('dowels')?'a dowel':has('curve')?'a curve point':has('axes')?'an axis':'';
  const show={'':true,alt:!!what,branch:has('curve'),tilt:ST.mode.name!=='folded',roll:ST.mode.name!=='folded'};
  for(const b of $$('#tools button')){b.hidden=!show[b.dataset.tool];if(b.dataset.tool==='alt')b.querySelector('span').textContent=what}
  setTool('')}
$('#tools').addEventListener('click',e=>{const b=e.target.closest('button');if(b)setTool(b.dataset.tool)});
addEventListener('keydown',e=>{if(e.key==='Escape'&&ST.tool)setTool('')});
renderer.domElement.addEventListener('pointerdown',ev=>{if(ev.button!==0)return;const k=keys(ev);down={x:ev.clientX,y:ev.clientY,cube:!!cubeHit(ev)};if(down.cube)return;const h=hit(ev);
  if(h&&h.object.userData.ring!==undefined){ // start turning the model about the ring's axis
    const i=h.object.userData.ring,centre=new THREE.Vector3(0,0,0),r=renderer.domElement.getBoundingClientRect(),c=centre.clone().project(camera),cx=r.left+(c.x+1)/2*r.width,cy=r.top+(1-c.y)/2*r.height;
    const axisDir=new THREE.Vector3(i===0?1:0,i===1?1:0,i===2?1:0),sign=axisDir.dot(camera.position.clone().sub(centre))>=0?1:-1;
    drag={mode:'ring',axis:i,cx,cy,sign,a0:Math.atan2(ev.clientY-cy,ev.clientX-cx),delta:0};controls.enabled=false;renderer.domElement.setPointerCapture(ev.pointerId);return}
  if(h&&(h.object.userData.ax!==undefined||h.object.userData.axline!==undefined)&&!k.altKey){ // drag a radial axis — whole, or one end — on a plane facing the camera, so it follows the pointer in 3D; orbit to reach the third direction
    const o=h.object, hs=guides.children.filter(g=>g.userData.ax!==undefined), i=o.userData.axline!==undefined?o.userData.axline:o.userData.ax.i;
    // the rod takes both ends with it; an end moves alone — every axis is its own two dots, even where two touch
    const ends=o.userData.axline!==undefined?hs.filter(g=>g.userData.ax.i===i):[o];
    // On the plane the other axes share while that plane faces the camera — you cannot see out-of-plane motion from
    // there, so none is meant, and the spine survives the drag. Seen edge-on (within 60° of it) the drag is on a plane
    // facing the camera instead: that is the view you take to move an axis *off* the plane on purpose, and a ray on
    // a plane seen edge-on would land anywhere along it. Both planes go through the handle's centre, not the point on
    // its surface the pointer hit: a plane through the surface point is tilted by the handle's radius
    const C=o.position.clone(), view=camera.getWorldDirection(new THREE.Vector3()), sp=sharedPlane(i,C);
    const shared=sp&&Math.abs(sp.normal.dot(view))>0.5?sp:null, plane=shared||new THREE.Plane().setFromNormalAndCoplanarPoint(view.negate(),C);
    const p0=new THREE.Vector3(); ray.setFromCamera(ndc(ev),camera); if(!ray.ray.intersectPlane(plane,p0))p0.copy(C);
    drag={mode:'axis',ends:ends.map(g=>({i:g.userData.ax.i,e:g.userData.ax.e,sphere:g,start:g.position.clone()})),plane,snap:!!shared,p0,delta:null};
    controls.enabled=false;renderer.domElement.setPointerCapture(ev.pointerId);return}
  if(h&&h.object.userData.cp!==undefined&&!k.altKey){ // drag a curve point: the pointer's movement on screen, read into the curve's own two directions
    const idx=PLANE_IDX[state.plane||'xz'], i=h.object.userData.cp;
    const list=curveList();
    drag={mode:'curve',i,sphere:h.object,idx,list,pt:null,P0:h.object.position.clone(),p0:list[i]||[0,0],
      U:V3(ST.plan.axes[idx[0]]),V:V3(ST.plan.axes[idx[1]]),step:Math.max(...ST.plan.bbox)/50};
    controls.enabled=false;renderer.domElement.setPointerCapture(ev.pointerId);return}
  if(h&&ST.selected&&(h.object.userData.grab==='tilt'||h.object.userData.grab==='roll')){   // a ring: turn the plane where it stands
    const k=h.object.userData.grab, S=slicePlan(ST.selected), ax=k==='tilt'?0:1;
    const axis=new THREE.Vector3(S.M[0][ax],S.M[1][ax],S.M[2][ax]).normalize(), c=h.object.position.clone();
    const [cx,cy]=__screen(c), sign=axis.dot(camera.position.clone().sub(c))>=0?1:-1;
    drag={mode:'spin',k,cx,cy,sign,a0:Math.atan2(ev.clientY-cy,ev.clientX-cx),base:state[k]?.[ST.selected]||0,delta:0,v:null};
    controls.enabled=false;renderer.domElement.setPointerCapture(ev.pointerId);return}
  // Only a handle moves a part — or shift / ctrl on the part itself, which say so. A plain drag on a selected part
  // used to slide it too, so turning the view after a click moved a layer by accident (reported)
  const m=h&&(h.object.userData.gizmo?parts.children.find(c=>c.userData.slice===ST.selected):(k.shiftKey||k.ctrlKey)&&!k.altKey&&h.object);   // shift+alt is a click: a branch
  if(m&&ST.selected&&m.userData.slice===ST.selected){const o=m.userData.origin.clone().project(camera),n=m.userData.origin.clone().add(m.userData.normal).project(camera);
    const r=renderer.domElement.getBoundingClientRect(),dir=new THREE.Vector2((n.x-o.x)*r.width/2,-(n.y-o.y)*r.height/2);if(dir.length()<1e-6)dir.set(1,0);dir.normalize();
    const dist=camera.position.distanceTo(m.userData.origin),mmPerPx=2*dist*Math.tan(camera.fov*Math.PI/360)/r.height;
    drag={mode:k.shiftKey?'tilt':k.ctrlKey?'roll':'offset',dir,mmPerPx,delta:0,meshes:parts.children.filter(c=>c.userData.slice===ST.selected)};controls.enabled=false;renderer.domElement.setPointerCapture(ev.pointerId)}});
renderer.domElement.addEventListener('pointermove',ev=>{if(!drag)return;const dx=ev.clientX-down.x,dy=ev.clientY-down.y,f=UNIT[ST.unit];
  if(drag.mode==='axis'){ray.setFromCamera(ndc(ev),camera);const P=new THREE.Vector3();if(!ray.ray.intersectPlane(drag.plane,P))return;
    drag.delta=P.sub(drag.p0);
    for(const d of drag.ends){d.sphere.position.copy(d.start).add(drag.delta);if(drag.snap)drag.plane.projectPoint(d.sphere.position,d.sphere.position)}
    for(const rod of guides.children.filter(g=>g.userData.axline!==undefined)){const end=e=>guides.children.find(g=>g.userData.ax&&g.userData.ax.i===rod.userData.axline&&g.userData.ax.e===e).position;placeRod(rod,end(0),end(1))}   // the rods follow their ends
    const d0=drag.ends[0],q=d0.sphere.position,whole=drag.ends.length>1&&drag.ends.every(x=>x.i===d0.i);
    status(`${lineParam()==='axes'?'axis':'branch'} ${d0.i+1}${whole?'':d0.e?' end':' start'}: ${[q.x,q.y,q.z].map(inU).join(', ')} ${ST.unit}`,'busy');ST.dirty=true;return}
  if(drag.mode==='curve'){const [du,dv]=inPlane(drag.P0,drag.U,drag.V,dx,dy,drag.step);
    drag.pt=[+(drag.p0[0]+du).toFixed(1),+(drag.p0[1]+dv).toFixed(1)];
    drag.sphere.position.copy(drag.P0).addScaledVector(drag.U,du).addScaledVector(drag.V,dv);
    status(`curve point ${drag.i+1}: ${inU(drag.pt[0])}, ${inU(drag.pt[1])} ${ST.unit}`,'busy');ST.dirty=true;return}
  if(drag.mode==='spin'){let a=Math.atan2(ev.clientY-drag.cy,ev.clientX-drag.cx)-drag.a0;a=Math.atan2(Math.sin(a),Math.cos(a));
    drag.v=Math.max(-60,Math.min(60,Math.round(drag.base-drag.sign*a*180/Math.PI)));   // the sliders' own range
    preview(drag.k,drag.v); status(`${drag.k} ${ST.selected}: ${drag.v}°`,'busy'); return}
  if(drag.mode==='ring'){let a=Math.atan2(ev.clientY-drag.cy,ev.clientX-drag.cx)-drag.a0;a=Math.atan2(Math.sin(a),Math.cos(a));drag.delta=-drag.sign*a*180/Math.PI;
    const axis=new THREE.Vector3(drag.axis===0?1:0,drag.axis===1?1:0,drag.axis===2?1:0);for(const g of [parts,ghost,guides])g.quaternion.setFromAxisAngle(axis,drag.delta*Math.PI/180);
    status(`turn about ${'xyz'[drag.axis]}: ${drag.delta.toFixed(0)}°`,'busy');ST.dirty=true;return}
  if(drag.mode==='offset'){drag.delta=(dx*drag.dir.x+dy*drag.dir.y)*drag.mmPerPx;preview('offset',((state.offset?.[ST.selected]||0)+drag.delta)*f);gizmo.position.copy(drag.meshes[0].userData.normal).multiplyScalar(drag.delta);ST.dirty=true}
  else{drag.delta=dx*0.4;preview(drag.mode,(state[drag.mode]?.[ST.selected]||0)+drag.delta)}
  status(`${drag.mode} ${ST.selected}: ${drag.mode==='offset'?fmtLen(drag.delta):drag.delta.toFixed(1)+'°'}`,'busy')});
renderer.domElement.addEventListener('pointerup',ev=>{const k=keys(ev);
  if(drag&&drag.mode==='spin'){controls.enabled=true;const d=drag;drag=null;
    if(d.v!==null&&d.v!==d.base)commit(d.k,d.v); else applyExplode();return}
  if(drag&&drag.mode==='axis'){controls.enabled=true;const d=drag;drag=null;
    if(d.delta&&d.delta.length()>0.05){const list=axisList();for(const x of d.ends){const q=x.start.clone().add(d.delta);if(d.snap)d.plane.projectPoint(q,q);list[x.i][x.e]=rnd(q)}state[lineParam()]=list;renderFields();slice()}return}
  if(drag&&drag.mode==='curve'){controls.enabled=true;const d=drag;drag=null;
    if(d.pt){d.list[d.i]=d.pt;d.list.sort((a,b)=>a[0]-b[0]);state.curve=d.list;renderFields();slice()}return}   // a point dragged past its neighbour swaps places with it: the curve never folds back
  if(drag&&drag.mode==='ring'){controls.enabled=true;const d=drag;drag=null;for(const g of [parts,ghost,guides])g.quaternion.identity();ST.dirty=true;
    if(Math.abs(d.delta)>1){const r=[...(state.rotate||[0,0,0])];r[d.axis]=Math.round(((r[d.axis]+d.delta+180)%360+360)%360-180);state.rotate=r;ST.fitted=false;renderFields();slice()}return}
  if(drag){controls.enabled=true;const d=drag;drag=null;gizmo.position.set(0,0,0);for(const m of d.meshes){m.matrixAutoUpdate=true;m.matrix.identity()}
    // a dragged offset lands on a round step of the unit on show (0.1 mm, 0.01 cm, 0.005 in), never on 0.4843 in
    if(Math.abs(d.delta)>0.05){const k=d.mode,cur=state[k]?.[ST.selected]||0,st=niceStep(0.1*UNIT[ST.unit]);setEdit(k,cur+(k==='offset'?toMM(Math.round(d.delta*UNIT[ST.unit]/st)*st):Math.round(d.delta)))}else applyExplode();return}
  if(!down||Math.hypot(ev.clientX-down.x,ev.clientY-down.y)>10)return;
  if(down.cube){const cv=cubeHit(ev);if(cv)viewFrom(cv);return}
  if(seamClick(ev))return;   // choosing seams: a click is for an edge, never for a part
  const h=hit(ev);if(h&&(h.object.userData.gizmo||h.object.userData.ring!==undefined))return;
  if(h&&(h.object.userData.ax!==undefined||h.object.userData.axline!==undefined)){if(k.altKey){const list=axisList(),i=h.object.userData.ax?h.object.userData.ax.i:h.object.userData.axline;   // alt-click an axis or its end: drop that fan (the last one stays — a radial job has to turn about something) or that branch
      if(list.length>1||lineParam()==='branches'){state[lineParam()]=dropLine(i);renderFields();slice()}
      else status('the last axis stays — alt-click the model to add another first');}return}
  if(h&&h.object.userData.cp!==undefined){if(k.altKey){const list=curveList();if(list.length>2){list.splice(h.object.userData.cp,1);state.curve=list;renderFields();slice()}}return}   // alt-click a dot: remove it (a curve keeps two)
  if(h&&k.altKey)togglePoint(h,k.shiftKey);else if(h)highlight(h.object);else deselect()});

