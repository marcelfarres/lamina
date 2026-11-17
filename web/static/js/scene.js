import * as THREE from 'three';
import {OrbitControls} from '../vendor/OrbitControls.js';
import {STLLoader} from '../vendor/STLLoader.js';
import {state, ST} from './state.js';
import {COLORS, LOOKS, PLANE_IDX} from './catalog.js';
import {$, status} from './util.js';
import {highlight, deselect, drawGizmo} from './edit3d.js';
import {renderSeams, showSeamLines} from './seams.js';

// ---------------------------------------------------------------- 3D view
export const view=$('#v3d'), renderer=new THREE.WebGLRenderer({antialias:true}); renderer.setPixelRatio(devicePixelRatio); view.appendChild(renderer.domElement);
export const scene=new THREE.Scene(); scene.background=new THREE.Color(0x141517);
export const camera=new THREE.PerspectiveCamera(40,1,1,100000); camera.position.set(300,-400,250); camera.up.set(0,0,1);
export const controls=new OrbitControls(camera,renderer.domElement); controls.enableDamping=true;
controls.zoomToCursor=true;   // the wheel zooms toward what is under the pointer, as a CAD program does, not into the model's middle
// One wheel event is one notch at most. A free-spinning wheel, a touchpad fling or Windows' "lines per notch" sends
// deltas of a thousand and more: five of them put the camera 1.5 mm from the model's centre, inside it and past the
// clipping plane, a hundred notches from the way back (reported). Firefox counts in lines: made pixels first.
view.addEventListener('wheel',e=>{if(e.target!==renderer.domElement||e.lamina)return;
  const px=e.deltaY*[1,33,800][e.deltaMode],y=Math.max(-100,Math.min(100,px)); if(y===e.deltaY)return;
  e.stopPropagation();e.preventDefault();
  const w=new WheelEvent('wheel',{deltaY:y,clientX:e.clientX,clientY:e.clientY,ctrlKey:e.ctrlKey,metaKey:e.metaKey,shiftKey:e.shiftKey,bubbles:true,cancelable:true});
  w.lamina=true;renderer.domElement.dispatchEvent(w)},{capture:true,passive:false});
const hemi=new THREE.HemisphereLight(0xffffff,0x334455,1.1); scene.add(hemi); const dl=new THREE.DirectionalLight(0xffffff,1.2); dl.position.set(1,-1,2); scene.add(dl);
export const parts=new THREE.Group(), ghost=new THREE.Group(), guides=new THREE.Group(), gizmo=new THREE.Group(), axes=new THREE.Group(), rings=new THREE.Group(); scene.add(parts,ghost,guides,gizmo,axes,rings);
rings.visible=true;   // turn rings belong to the Model tab; showTab() hides them elsewhere
export const ray=new THREE.Raycaster(); export let ghostUrl=null;
export const V3=a=>new THREE.Vector3(a[0],a[1],a[2]);
function resize(){const w=view.clientWidth,h=view.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();ST.dirty=true}
new ResizeObserver(resize).observe(view); resize();
controls.addEventListener('change',()=>ST.dirty=true);
// view cube: a small cube in the corner that turns with the camera; click a face for a flat view (top, front, right …)
const CUBE={size:92,pad:10}, cubeScene=new THREE.Scene(), cubeCam=new THREE.PerspectiveCamera(32,1,0.1,20), cubeRoot=new THREE.Group(); cubeCam.position.set(0,0,5.2); cubeScene.add(cubeRoot);
function faceTex(text){const c=document.createElement('canvas');c.width=c.height=128;const g=c.getContext('2d');g.fillStyle='#2a2c33';g.fillRect(0,0,128,128);g.strokeStyle='#62656f';g.lineWidth=5;g.strokeRect(3,3,122,122);
  g.fillStyle='#e6e6e3';g.font='bold 24px system-ui,sans-serif';g.textAlign='center';g.textBaseline='middle';g.fillText(text,64,66);const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;return t}
// each face: outward normal, which world direction reads as "up" on it (z for the sides, y from above and below), and the
// camera direction for its flat view — tilted a hair toward that up so the orbit never degenerates on top / bottom
for(const [name,n,up,dir] of [['TOP',[0,0,1],[0,1,0],[0,-1e-3,1]],['BOTTOM',[0,0,-1],[0,1,0],[0,1e-3,-1]],['FRONT',[0,-1,0],[0,0,1],[0,-1,0]],['BACK',[0,1,0],[0,0,1],[0,1,0]],['RIGHT',[1,0,0],[0,0,1],[1,0,0]],['LEFT',[-1,0,0],[0,0,1],[-1,0,0]]]){
  const f=new THREE.Mesh(new THREE.PlaneGeometry(1.7,1.7),new THREE.MeshBasicMaterial({map:faceTex(name)})),N=V3(n),U=V3(up);
  f.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(U.clone().cross(N),U,N));f.position.copy(N).multiplyScalar(0.85);f.userData.dir=dir;cubeRoot.add(f)}
cubeRoot.add(new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.7,1.7,1.7)),new THREE.LineBasicMaterial({color:0x9a9ba3})));
const cubeRect=()=>({x:view.clientWidth-CUBE.size-CUBE.pad,y:CUBE.pad,s:CUBE.size});   // viewport coordinates, y from the bottom
function drawCube(){const r=cubeRect();cubeRoot.quaternion.copy(camera.quaternion).invert();renderer.clearDepth();renderer.setScissorTest(true);renderer.setViewport(r.x,r.y,r.s,r.s);renderer.setScissor(r.x,r.y,r.s,r.s);
  renderer.render(cubeScene,cubeCam);renderer.setScissorTest(false);renderer.setViewport(0,0,view.clientWidth,view.clientHeight)}
export function cubeHit(ev){const b=renderer.domElement.getBoundingClientRect(),r=cubeRect(),x=ev.clientX-b.left-r.x,y=(b.bottom-ev.clientY)-r.y;if(x<0||y<0||x>r.s||y>r.s)return null;
  ray.setFromCamera(new THREE.Vector2(x/r.s*2-1,y/r.s*2-1),cubeCam);const h=ray.intersectObjects(cubeRoot.children.filter(o=>o.isMesh));return h.length?h[0].object.userData.dir:null}
export function viewFrom(dir){ // swing the camera round to look along -dir at the current target, keeping its distance
  const t=controls.target.clone(),d=camera.position.distanceTo(t),from=camera.position.clone(),to=t.clone().addScaledVector(V3(dir).normalize(),d),t0=performance.now();
  (function step(){const k=Math.min(1,(performance.now()-t0)/220),s=k*k*(3-2*k);camera.position.lerpVectors(from,to,s).sub(t).setLength(d).add(t);camera.lookAt(t);controls.update();ST.dirty=true;if(k<1)requestAnimationFrame(step)})()}
// Render only when something changed. The orbit's damping is a step per frame (5 % of what is left of the drag), so at
// a few frames a second — a model of hundreds of parts on a laptop, a headless CI browser — the view lagged the drag
// by seconds and glided on long after it: "rotating the model is difficult" (reported from a Mac). Steps per time
// instead: a slow frame takes as many as the frames it stood for, ten at most
let lastFrame=performance.now();
(function loop(t=lastFrame){requestAnimationFrame(loop);const n=Math.max(1,Math.min(10,Math.round((t-lastFrame)/16.7)));lastFrame=t;let moved=false;for(let i=0;i<n;i++)moved=controls.update()||moved;
  if(moved||ST.dirty){renderer.render(scene,camera);drawCube();ST.dirty=false}})();
export function mat4(M){return new THREE.Matrix4().set(...M[0],...M[1],...M[2],...M[3])}
function shape(rings){const s=new THREE.Shape(rings[0].map(([x,y])=>new THREE.Vector2(x,y)));for(const h of rings.slice(1))s.holes.push(new THREE.Path(h.map(([x,y])=>new THREE.Vector2(x,y))));return s}
export function applyLook(){const k=$('#look').value,op=+$('#opacity').value;for(const m of parts.children){if(m.userData.group==='B')continue;   // a lobe boundary is a guide, not material: it keeps its own look
  const [c,r,me]=k==='group'?[COLORS[m.userData.group]||0xaaaaaa,.7,.05]:LOOKS[k];m.material.color.set(m.userData.bad?0xff5555:c);m.material.roughness=r;m.material.metalness=me;
  const tr=m.userData.group==='F'&&op<1;m.material.transparent=tr;m.material.opacity=tr?op:1;m.material.depthWrite=!tr}ST.dirty=true}
// rotation rings (OrcaSlicer-style): drag a ring to turn the whole model about that axis
function renderRings(){
  rings.clear();
  const L=Math.max(...ST.plan.bbox)*0.62;
  for(const [i,col] of [[0,0xff5c5c],[1,0x5cff7a],[2,0x5c9cff]]){const r=new THREE.Mesh(new THREE.TorusGeometry(L,L*0.012,8,96),new THREE.MeshBasicMaterial({color:col,transparent:true,opacity:.55,depthTest:false}));
    if(i===0)r.rotation.y=Math.PI/2;else if(i===1)r.rotation.x=Math.PI/2; r.userData.ring=i;r.renderOrder=9;rings.add(r)}
}
function label3d(text,color,mid){const c=document.createElement('canvas');c.width=64;c.height=32;const g=c.getContext('2d');g.font='bold 26px sans-serif';g.fillStyle=color;g.textAlign=mid?'center':'left';g.fillText(text,mid?32:6,26);const s=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),depthTest:false}));return s}
function renderAxes(){ // world axes at the model's corner with X/Y/Z labels + dowel rods (stacked)
  axes.clear(); const L=Math.max(...ST.plan.bbox)*0.6, o=new THREE.Vector3(-ST.plan.bbox[0]/2,-ST.plan.bbox[1]/2,-ST.plan.bbox[2]/2).multiplyScalar(1.15);
  for(const [i,col,name] of [[0,0xff5c5c,'X'],[1,0x5cff7a,'Y'],[2,0x5c9cff,'Z']]){const dir=new THREE.Vector3(i===0?1:0,i===1?1:0,i===2?1:0);
    axes.add(new THREE.ArrowHelper(dir,o,L,col,L*.12,L*.06));const s=label3d(name,'#'+col.toString(16).padStart(6,'0'));s.position.copy(o).addScaledVector(dir,L*1.12);s.scale.set(L*.16,L*.08,1);axes.add(s)}
  // a rod is its hole's own section (round, square, hexagon, cross, slot) swept from end to end, turned as its slice is
  for(const [a,b,,sec,xa] of ST.plan.rods||[]){const A=V3(a),z=V3(b).sub(A),len=z.length(),x=V3(xa);z.normalize();
    const m=new THREE.Mesh(new THREE.ExtrudeGeometry(new THREE.Shape(sec.map(([u,v])=>new THREE.Vector2(u,v))),{depth:len,bevelEnabled:false}),new THREE.MeshStandardMaterial({color:0xc8b48a,roughness:.6}));
    m.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,z.clone().cross(x),z));m.position.copy(A);axes.add(m)}
  // where a connector that was asked for found no room (the warning says how many): a crossed ring, seen through the parts
  for(const q of ST.plan.left_out||[]){const s=label3d('⊗','#f5b642',true);s.position.copy(V3(q));s.scale.set(L*.2,L*.1,1);s.renderOrder=10;axes.add(s)}
  renderRings();
}
export function placeRod(rod,A,B){rod.position.copy(A).lerp(B,.5);rod.scale.set(1,Math.max(A.distanceTo(B),1e-3),1);rod.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),B.clone().sub(A).normalize())}
function renderGuides(){
  guides.clear(); renderAxes();
  // the curve and its control points run through the middle of the model, so they draw on top of it (like the gizmo):
  // otherwise the ribs hide the very thing alt-click edits
  const onTop=o=>{o.material.depthTest=false;o.renderOrder=2;return o};
  // radial's fan axes where they pass through the model, curve's branches — a rod you can drag whole, a handle at each end. The
  // plan sends the axes it actually used, so the single default one can be taken hold of before `axes` has ever
  // been filled in
  const hr=Math.max(...ST.plan.bbox)*0.014+1;
  (ST.plan.axes3d||[]).forEach((seg,i)=>{
    const A=V3(seg[0]),B=V3(seg[1]);
    const rod=onTop(new THREE.Mesh(new THREE.CylinderGeometry(hr*.35,hr*.35,1,8),new THREE.MeshBasicMaterial({color:0x4fd1ff,transparent:true,opacity:.8})));
    rod.userData.axline=i; placeRod(rod,A,B); guides.add(rod);
    for(const [e,P] of [[0,A],[1,B]]){
      const s=onTop(new THREE.Mesh(new THREE.SphereGeometry(hr,12,8),new THREE.MeshBasicMaterial({color:0x4fd1ff})));
      s.userData.ax={i,e}; s.position.copy(P); guides.add(s);
    }
  });
  if(!ST.plan.curve3d)return;
  guides.add(onTop(new THREE.Line(new THREE.BufferGeometry().setFromPoints(ST.plan.curve3d.map(V3)),new THREE.LineBasicMaterial({color:0xff9a3c}))));
  const idx=PLANE_IDX[state.plane||'xz'], mid=V3(ST.plan.mid), r=Math.max(...ST.plan.bbox)*0.012+1;
  const wi=3-idx[0]-idx[1];   // the plane's normal axis: the point sits where the body's centre is across the plane
  (ST.plan.curve_pts||[]).forEach(([u,v,w=0],i)=>{const s=onTop(new THREE.Mesh(new THREE.SphereGeometry(r*1.5,12,8),new THREE.MeshBasicMaterial({color:0x4f8cff})));s.userData.cp=i;   // a handle: drag it in the curve's plane
    s.position.copy(mid).addScaledVector(V3(ST.plan.axes[idx[0]]),u).addScaledVector(V3(ST.plan.axes[idx[1]]),v).addScaledVector(V3(ST.plan.axes[wi]),w);guides.add(s)})
}
// Lamp: a bulb inside the model, a floor and a wall that catch the shadows the parts throw (three.js shadow maps).
// Off, nothing of it is on the scene, the shadow pass is off and the view is the one without it.
// ponytail: one point light and two flat catchers; paper that glows through and a bulb dragged in 3D are not here
const lamp=new THREE.Group(), bulb=new THREE.PointLight(0xffb870,3,0,0), bulbMark=new THREE.Mesh(new THREE.SphereGeometry(1,16,12),new THREE.MeshBasicMaterial({color:0xfff0c0})),
  catcher=new THREE.MeshStandardMaterial({color:0xd0d0d0,roughness:1}), floor=new THREE.Mesh(new THREE.PlaneGeometry(1,1),catcher), wall=new THREE.Mesh(new THREE.PlaneGeometry(1,1),catcher); let lampOn=false;
bulb.castShadow=floor.receiveShadow=wall.receiveShadow=true; bulb.shadow.mapSize.set(2048,2048); bulb.shadow.bias=-.0005; bulb.shadow.normalBias=.3; wall.rotation.x=Math.PI/2; lamp.add(bulb,bulbMark,floor,wall); lamp.visible=false; scene.add(lamp);
export function applyLamp(){const on=$('#lamp').checked; $('#lampl').hidden=!on;
  if(on){const b=new THREE.Box3(); for(const m of parts.children)if(m.userData.group!=='B')b.expandByObject(m);   // every part, shown or not: the floor stays put while the steps run
    if(b.isEmpty())b.setFromObject(ghost); if(b.isEmpty())return;
    const c=b.getCenter(new THREE.Vector3()),S=b.getSize(new THREE.Vector3()),r=S.length(),z=b.min.z+$('#lampz').value*S.z;
    bulb.position.set(c.x,c.y,z); bulbMark.position.copy(bulb.position); bulbMark.scale.setScalar(r*.025); bulb.shadow.camera.far=r*4; bulb.shadow.camera.updateProjectionMatrix();
    floor.scale.setScalar(r*3); floor.position.set(c.x,c.y,b.min.z-r*.01); wall.scale.setScalar(r*3); wall.position.set(c.x,b.max.y+r*.6,b.min.z+r*1.5-r*.01)}
  for(const m of parts.children)m.castShadow=on&&m.userData.group!=='B';
  lamp.visible=on; renderer.shadowMap.enabled=on; hemi.intensity=on?.1:1.1; dl.intensity=on?0:1.2; scene.background.set(on?0x050506:0x141517);
  if(on!==lampOn){lampOn=on; for(const m of [...parts.children,floor])m.material.needsUpdate=true}   // the shaders gain or lose the shadow lookup
  ST.dirty=true}
$('#lamp').onchange=$('#lampz').oninput=applyLamp;
export function render3D(modelUrl){
  parts.clear(); let i=0;
  for(const s of ST.plan.slices)for(const pc of s.pieces){
    const geos=[],own=[];   // own: the facet each solid was extruded from, for the fold slider
    pc.facets.forEach((fc,fi)=>{for(const r of fc.rings){
      // a printed panel's face is drawn as it is exported: in layers, each set in from its grooved edges by what the V takes at that height
      const t=fc.t||s.thickness,n=fc.bevel?6:1,skin=ST.plan.params.hinge||0;   // fc.t: a thin printed tab
      for(let j=0;j<n;j++){const z=-t/2+(j+.5)*t/n;let ext=r[0];
        for(const [x0,y0,x1,y1,w,side] of fc.bevel||[]){const d=w*Math.min(1,Math.max(0,(side>0?t/2-skin-z:z+t/2-skin)/(t-skin)));if(d>1e-6)ext=clipEdge(ext,x0,y0,x1,y1,d)}
        if(ext.length<3)continue;
        const g=new THREE.ExtrudeGeometry(shape([ext,...r.slice(1)]),{depth:t/n,bevelEnabled:false});g.translate(0,0,-t/2+j*t/n);g.applyMatrix4(mat4(fc.M));geos.push(g);own.push(fi)}}});
    if(!geos.length)continue;
    const m=new THREE.Mesh(mergeGeos(geos),new THREE.MeshStandardMaterial({color:COLORS[s.group]||0xaaaaaa,roughness:.7,metalness:.05}));
    m.userData={slice:s.label,piece:pc.label,group:s.group,i:i++,origin:new THREE.Vector3(s.M[0][3],s.M[1][3],s.M[2][3]),normal:new THREE.Vector3(s.M[0][2],s.M[1][2],s.M[2][2]),bad:s.errors.length>0};
    if(pc.facets.some(f=>f.hinge)){let o=0;   // a folded panel: where each facet's vertices are, to swing them about their fold lines
      m.userData.fold={base:m.geometry.attributes.position.array.slice(),hinges:pc.facets.map(f=>f.hinge||null),
        ranges:geos.map((g,j)=>{const n=g.index?g.index.count:g.attributes.position.count,r=[o,n,own[j]];o+=n;return r})}}
    parts.add(m);
  }
  // the plane between two lobes, or at a branch's joint, is a part too — translucent, outside the build order (i = -1 keeps it on every
  // step) — so the one select / arrow / shift / ctrl-drag and the sliders move and tilt it, and the plan's per-slice
  // offset / tilt / roll carry the edit under its label
  for(const b of ST.plan.bounds3d||[]){
    // Into the geometry, exactly like the slices above — never onto the mesh. Everything that moves a part (the
    // gizmo, the sliders, the live preview) starts by clearing the mesh's own position and rotation, because for a
    // slice those hold nothing but the explode offset. A lobe plane that kept its frame there lost it at the first
    // drag: it snapped to the middle of the model, flat, and came back only when the re-slice rebuilt it.
    const g=new THREE.PlaneGeometry(b.size,b.size); g.applyMatrix4(mat4(b.M));
    const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:COLORS.B,transparent:true,opacity:.22,depthWrite:false,side:THREE.DoubleSide,roughness:.9}));
    m.renderOrder=1;
    m.userData={slice:b.label,piece:b.label,group:'B',i:-1,origin:new THREE.Vector3(b.M[0][3],b.M[1][3],b.M[2][3]),normal:new THREE.Vector3(b.M[0][2],b.M[1][2],b.M[2][2]),bad:false};
    parts.add(m);
  }
  applyLook(); renderGuides();
  // a folded job folds up at the end of its build order: FOLD_STEPS more steps after the last part is in
  nParts=i; const max=i+(parts.children.some(m=>m.userData.fold)?FOLD_STEPS:0);
  $('#steps').max=max; $('#steps').value=max; applyExplode(); applyFold();
  if(!ST.ghostLive)showGhost(modelUrl);   // already shown mid-build: the same mesh, and fetching it again is not free
  clipGhost();
  ghost.visible=$('#ghost').checked; applyLamp();
  if(ST.selected){const m=parts.children.find(c=>c.userData.slice===ST.selected);m?highlight(m):deselect()}
  renderSeams();
  if(!ST.fitted){fitView();ST.fitted=true}
}
// The translucent model behind the parts, loaded on its own: the build finishes with the mesh a second or two in and
// says so, so the 3D view fills with your model while the slices are still being worked out instead of staying empty
// until the last sheet is nested. Until there are parts, the view frames the model itself.
// A plaque leaves out what is behind its plate: the ghost is cut at the plate's front face (plan.clip = [point, normal]).
function clipGhost(){const c=ST.plan?.clip, pl=c?[new THREE.Plane(new THREE.Vector3(...c[1]),-(c[0][0]*c[1][0]+c[0][1]*c[1][1]+c[0][2]*c[1][2]))]:null;
  renderer.localClippingEnabled=true; for(const m of ghost.children){m.material.clippingPlanes=pl;m.material.needsUpdate=true} ST.dirty=true}
export function showGhost(modelUrl){
  if(!modelUrl||modelUrl===ghostUrl)return;
  if(ghostUrl?.startsWith('blob:'))URL.revokeObjectURL(ghostUrl);   // the browser build hands over the mesh itself
  ghostUrl=modelUrl; ghost.clear();
  new STLLoader().load(modelUrl,g=>{
    smoothNormals(g);
    ghost.clear(); ghost.add(new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:0x8899aa,transparent:true,opacity:.18,depthWrite:false})));
    ghost.visible=$('#ghost').checked; clipGhost();
    if(!ST.fitted&&!parts.children.length)fitView();       // not `fitted = true`: the parts get their own fit when they land
    ST.dirty=true});
}
// An STL carries one normal per triangle, so the model was shaded flat and looked faceted even when it was never
// remeshed. Shade across the triangles instead: each corner of a triangle takes the mean of the normals of the
// triangles meeting at that point that are within `crease` degrees of its own (a cube's corner stays a corner,
// and a flat base does not tilt the flank above it). What three.js's toCreasedNormals does, without its module.
function smoothNormals(g,crease=30){
  const p=g.attributes.position.array,n=g.attributes.normal.array,at=new Map(),cos=Math.cos(crease*Math.PI/180);
  const key=i=>`${p[i].toFixed(3)},${p[i+1].toFixed(3)},${p[i+2].toFixed(3)}`;
  for(let i=0;i<p.length;i+=3){const k=key(i);(at.get(k)||at.set(k,[]).get(k)).push(i)}
  const out=new Float32Array(n.length);
  for(let i=0;i<p.length;i+=3){let x=0,y=0,z=0;
    for(const j of at.get(key(i)))if(n[i]*n[j]+n[i+1]*n[j+1]+n[i+2]*n[j+2]>cos){x+=n[j];y+=n[j+1];z+=n[j+2]}
    const l=Math.hypot(x,y,z)||1;out[i]=x/l;out[i+1]=y/l;out[i+2]=z/l}
  g.setAttribute('normal',new THREE.BufferAttribute(out,3))}
// A ring with what lies within `d` of the line a→b cut off, on the ring's own side of it (Sutherland–Hodgman, one edge).
function clipEdge(ring,x0,y0,x1,y1,d){const L=Math.hypot(x1-x0,y1-y0);let nx=-(y1-y0)/L,ny=(x1-x0)/L,cx=0,cy=0;for(const [x,y] of ring){cx+=x;cy+=y}
  if(((cx/ring.length-x0)*nx+(cy/ring.length-y0)*ny)<0){nx=-nx;ny=-ny}
  const dist=([x,y])=>(x-x0)*nx+(y-y0)*ny-d,out=[];
  ring.forEach((p,i)=>{const q=ring[(i+1)%ring.length],a=dist(p),b=dist(q);if(a>=0)out.push(p);if((a>=0)!==(b>=0)){const k=a/(a-b);out.push([p[0]+(q[0]-p[0])*k,p[1]+(q[1]-p[1])*k])}});
  return out}
function mergeGeos(geos){
  const ngs=geos.map(g=>g.index?g.toNonIndexed():g),n=ngs.reduce((a,g)=>a+g.attributes.position.array.length,0),pos=new Float32Array(n),nor=new Float32Array(n);let o=0;
  for(const g of ngs){pos.set(g.attributes.position.array,o);nor.set(g.attributes.normal.array,o);o+=g.attributes.position.array.length}
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(pos,3));g.setAttribute('normal',new THREE.BufferAttribute(nor,3));return g}
function fitView(){const b=new THREE.Box3().setFromObject(parts.children.length?parts:ghost);if(b.isEmpty())return;const c=b.getCenter(new THREE.Vector3()),s=b.getSize(new THREE.Vector3()).length();controls.target.copy(c);camera.position.copy(c).add(new THREE.Vector3(.7,-1,.6).normalize().multiplyScalar(s*1.5));
  // close enough to read a slot, never onto the point it turns about (from 0 no zoom ever comes back), never so far the
  // model is lost; the clipping planes outside both, so nothing is cut away at either end
  controls.minDistance=s/40;controls.maxDistance=s*8;camera.near=s/200;camera.far=s*20;camera.updateProjectionMatrix()}
// The name of the part going in, at the top centre of the 3D view while the steps slider is short of the end: drawn
// into the canvas itself (a sprite riding with the camera), so the recorded video carries it — the video is the
// canvas, and an HTML caption over it would never reach the file.
export const banner=new THREE.Sprite(new THREE.SpriteMaterial({map:null,depthTest:false,transparent:true})); banner.visible=false; banner.renderOrder=9; camera.add(banner); scene.add(camera);
function showBanner(text){
  banner.userData.text=text; if(!text){banner.visible=false;return}
  const c=document.createElement('canvas');c.width=1024;c.height=96;const g=c.getContext('2d');
  g.fillStyle='rgba(20,21,23,.72)';g.beginPath();g.roundRect(8,8,1008,80,14);g.fill();
  g.fillStyle='#e6e6e3';g.font='bold 44px system-ui,sans-serif';g.textAlign='center';g.textBaseline='middle';g.fillText(text,512,50);
  if(banner.material.map)banner.material.map.dispose(); const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;banner.material.map=t;banner.material.needsUpdate=true;
  const dist=60,half=dist*Math.tan(camera.fov*Math.PI/360),w=half*2*camera.aspect;   // the view at `dist` in front of the camera
  banner.position.set(0,half*0.72,-dist); banner.scale.set(Math.min(w*0.9,half*2.4),Math.min(w*0.9,half*2.4)*96/1024,1); banner.visible=true;
}
// Folded panels from flat to folded: every face hangs from the face it was unfolded from and turns about the fold
// line between them, so at 0 a panel lies flat in the plane of its first face and at 1 it is the model. A face's
// parent always comes before it in the list, so one pass builds every face's motion from its parent's.
export function applyFold(){const s=+$('#fold').value,v=new THREE.Vector3();let any=false;
  for(const m of parts.children){const f=m.userData.fold;if(!f)continue;any=true;const D=[];
    f.hinges.forEach((h,i)=>{D[i]=new THREE.Matrix4();if(!h||!D[h[0]])return;
      D[i].copy(D[h[0]]).multiply(new THREE.Matrix4().makeTranslation(h[1],h[2],h[3])).multiply(new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(h[4],h[5],h[6]),(1-s)*h[7])).multiply(new THREE.Matrix4().makeTranslation(-h[1],-h[2],-h[3]))});
    const pos=m.geometry.attributes.position;
    for(const [o,n,fi] of f.ranges)for(let j=o;j<o+n;j++){v.fromArray(f.base,3*j).applyMatrix4(D[fi]);pos.setXYZ(j,v.x,v.y,v.z)}
    pos.needsUpdate=true;m.geometry.computeVertexNormals();m.geometry.computeBoundingSphere();m.geometry.computeBoundingBox()}
  $('#foldl').hidden=!any; ghost.visible=$('#ghost').checked&&!(any&&s<1);   // the model would stand in the unfolded panel
  $('#fold_val').textContent=Math.round(s*100)+' %'; showSeamLines(); ST.dirty=true}
const FOLD_STEPS=20; let nParts=0;   // the steps a folded job takes to fold up, and the parts in the build order before them
export function applyExplode(){const e=+$('#explode').value,st=$('#steps'),k=+st.value;for(const m of parts.children){if(m.userData.group==='B')continue;m.position.copy(m.userData.origin).multiplyScalar(e-1);m.visible=m.userData.i<k}
  const folding=+st.max>nParts, share=folding?Math.min(1,Math.max(0,(k-nParts)/FOLD_STEPS)):1;
  if(folding){$('#fold').value=share;applyFold()}   // the panels go in flat, then fold up
  const going=k<+st.max&&parts.children.find(m=>m.userData.i===k-1);
  showBanner(going?`step ${k} / ${+st.max}  ·  ${(ST.plan&&ST.plan.label_tag?ST.plan.label_tag+' ':'')}${going.userData.piece}`:folding&&k<+st.max?`step ${k} / ${+st.max}  ·  folding ${Math.round(share*100)} %`:'');
  $('#steps_val').textContent=`${k} / ${+st.max||0}`;   // the step counter, live while the slider is dragged
  const s=ST.selected&&parts.children.find(c=>c.userData.slice===ST.selected); if(s)drawGizmo(s);   // the handles ride with the part
  showSeamLines(); applyLamp()}
$('#explode').oninput=$('#steps').oninput=applyExplode; $('#fold').oninput=applyFold; $('#ghost').onchange=()=>{ghost.visible=$('#ghost').checked;ST.dirty=true}; $('#fit').onclick=()=>{fitView();ST.dirty=true}; $('#look').onchange=$('#opacity').oninput=applyLook;
// The build order as a video: the steps slider played into a MediaRecorder reading the canvas the view already
// draws. Nothing is uploaded and nothing is rendered twice — the file is made in the page and saved from it.
async function recordAssembly(el){
  const st=$('#steps'), max=+st.max, cv=renderer.domElement;
  if(!max)return status('nothing to record yet');
  if(!cv.captureStream||!window.MediaRecorder)return status('this browser cannot record the canvas — use the steps slider');
  const rec=new MediaRecorder(cv.captureStream(30),{mimeType:'video/webm'}), chunks=[], was=st.value, txt=el.textContent;
  rec.ondataavailable=e=>e.data.size&&chunks.push(e.data);
  const done=new Promise(r=>rec.onstop=r);
  el.textContent='recording the assembly…'; rec.start();
  const hold=Math.min(700,Math.max(90,4000/max));
  for(let k=0;k<=max;k++){st.value=k;applyExplode();await new Promise(r=>setTimeout(r,hold))}
  await new Promise(r=>setTimeout(r,700)); rec.stop(); await done;
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob(chunks,{type:'video/webm'}));
  a.download=`${(state.project||'lamina').replace(/\W+/g,'_')}_${ST.mode.name}_assembly.webm`; a.click();
  URL.revokeObjectURL(a.href); st.value=was; applyExplode(); el.textContent=txt; ST.countUse('export','video');
}
$('#vid_go').onclick=e=>{e.preventDefault();recordAssembly(e.currentTarget)};
$('#viewmode').onchange=e=>{$('#view').className='view '+(e.target.value==='both'?'':e.target.value);resize();ST.dirty=true};

