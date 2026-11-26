import * as THREE from 'three';
import {state, ST} from './state.js';
import {$, $$} from './util.js';
import {act} from './history.js';
import {schedule} from './form.js';
import {deselect} from './edit3d.js';
import {scene, parts, ray, camera, renderer, V3} from './scene.js';
import {foldUp, seamsFolded, sameEnds} from './seams.js';

// ---------------------------------------------------------------- selecting and removing faces (folded panels)
// To keep only a part of a model (a mask from a head), the `select faces` tool takes faces off its surface. A click or
// a drag on the model selects faces; `grow` adds the faces next to them, `connected` every face joined to them, and
// both stop at a seam the user chose, at a removed face and at the rim; `remove` takes the selected faces off.
// `merge` makes the selected faces one flat face (`merged`: a group of triangles each, kept by place as a removed face
// is; the plan says which group every face came from, faces3d.merged), `unmerge` gives the groups under the selection back.
// A removed face is kept by its place, not by a number: its triangle in the model file's coordinates (`removed`,
// through the plan's `frame`), so it stays removed when the faces are made again. The plan lists the faces that are
// left (faces3d: corners, faces, the two faces across each edge). Removed faces show as ghosts while the tool is on:
// a click on one puts it back.
// Three looks, never colour alone: selected = hatched, removed = a dashed outline, the user's seam = a thick line.
// As in seams.js, nothing here reaches into another module before initFaces().
// stripes in screen pixels, the same on every face; the 3D view hatches a paper part's window with it too (scene.js:
// it is made here, where it is used at load, and scene.js only draws with it: the two modules import each other)
export const hatched=new THREE.ShaderMaterial({transparent:true,side:THREE.DoubleSide,depthWrite:false,
  vertexShader:'void main(){gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
  fragmentShader:'void main(){gl_FragColor=vec4(0.94,0.89,0.26,mod(gl_FragCoord.x+gl_FragCoord.y,10.0)<4.0?0.95:0.3);}'});
const geo=()=>new THREE.BufferGeometry();
const selFill=new THREE.Mesh(geo(),hatched), selRim=new THREE.LineSegments(geo(),new THREE.LineBasicMaterial({color:0xF0E442}));
const ghostRim=new THREE.LineSegments(geo(),new THREE.LineDashedMaterial({color:0xE69F00}));
const ghostPick=new THREE.Mesh(geo(),new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,side:THREE.DoubleSide}));   // not seen, only hit: a click on a ghost
const layer=new THREE.Group(); layer.add(selFill,selRim,ghostRim,ghostPick); layer.visible=false;
for(const o of layer.children)o.frustumCulled=false;
let faceMode=false, sel=new Set(), tris=[], nb=[], gone=[], from=null;   // sel: the selected faces; tris: every face; nb: face → [[the face across an edge, the edge]]; gone: the removed faces, here in mm; from: where a drag began
const lift=()=>Math.max(...(ST.plan?.bbox||[100]))*0.002+0.05;           // a hair outside the surface, as the seam lines are
function corners(ts,o,rim){const p=[],n=new THREE.Vector3();   // the triangles' corners, lifted: three each, or their three edges
  for(const t of ts){t.getNormal(n).multiplyScalar(o);const q=[t.a,t.b,t.c].map(v=>[v.x+n.x,v.y+n.y,v.z+n.z]);
    p.push(...(rim?[q[0],q[1],q[1],q[2],q[2],q[0]]:q).flat())}
  return new THREE.Float32BufferAttribute(p,3)}
function put(obj,attr){obj.geometry.dispose();obj.geometry=geo().setAttribute('position',attr);if(obj.isLineSegments)obj.computeLineDistances()}
function draw(){const s=[...sel].map(i=>tris[i]),o=lift();put(selFill,corners(s,o));put(selRim,corners(s,o,true));syncFaces();ST.dirty=true}
export function showFaces(){layer.visible=faceMode&&seamsFolded();$('#face_off').hidden=!faceMode||layer.visible}
export function renderFaces(){   // the faces of the plan just drawn, and the removed ones where they are on this model
  const F=ST.plan?.faces3d, big=Math.max(...(ST.plan?.bbox||[100])); sel=new Set(); tris=[]; nb=[];
  if(F){const v=F.v.map(V3);tris=F.f.map(f=>new THREE.Triangle(v[f[0]],v[f[1]],v[f[2]]));nb=F.f.map(()=>[]);F.adj.forEach(([a,b],k)=>{nb[a].push([b,k]);nb[b].push([a,k])})}
  const M=ST.plan?.frame&&new THREE.Matrix4().set(...ST.plan.frame.flat());
  gone=M?(state.removed||[]).map(t=>new THREE.Triangle(...t.map(p=>V3(p).applyMatrix4(M)))):[];
  ghostRim.material.dashSize=big*0.012+0.4; ghostRim.material.gapSize=big*0.008+0.3;
  put(ghostRim,corners(gone,lift(),true)); put(ghostPick,corners(gone,0));
  if(faceMode&&!F)faceMode=false; $('#facebar').hidden=!faceMode; showFaces(); draw()}
const groupsOf=()=>new Set([...sel].map(i=>ST.plan?.faces3d?.merged?.[i]??-1).filter(g=>g>=0));   // the merged groups the selection touches
export function syncFaces(){const n=sel.size, kept=(state.removed||[]).length, off=ST.plan?.faces3d?.removed??kept, flat=(state.merged||[]).length;
  for(const b of $$('[data-faces="merge"]'))b.disabled=n<2;
  for(const b of $$('[data-faces="unmerge"]'))b.disabled=!groupsOf().size;
  for(const e of $$('.face_merged'))e.textContent=flat?`${flat} merged face${flat===1?'':'s'}`:'none merged';
  for(const b of $$('[data-faces="unmergeall"]'))b.disabled=!flat;
  $('#face_sel').textContent=`${n} face${n===1?'':'s'} selected`;
  for(const b of $$('[data-faces="grow"],[data-faces="connected"],[data-faces="remove"]'))b.disabled=!n;
  for(const e of $$('.face_gone'))e.textContent=kept?`${off} removed`:'none removed';
  for(const b of $$('[data-faces="back"]'))b.disabled=!kept}
function under(ev){   // what the pointer is on: {ghost} a removed face, {face} a face of the model, or null
  if(ST.partial)return null;   // the parts drawn are not the faces' plan yet
  const r=renderer.domElement.getBoundingClientRect(); ray.setFromCamera(new THREE.Vector2((ev.clientX-r.left)/r.width*2-1,-(ev.clientY-r.top)/r.height*2+1),camera);
  const g=ray.intersectObject(ghostPick)[0], h=ray.intersectObjects(parts.children.filter(m=>m.visible))[0];
  if(g&&(!h||g.distance<h.distance))return {ghost:g.faceIndex};
  if(!h||!tris.length)return null; let best=0,bd=Infinity;const q=new THREE.Vector3();   // a part is its panel's faces and tabs: the face is the one nearest the point hit
  tris.forEach((t,i)=>{const d=t.closestPointToPoint(h.point,q).distanceToSquared(h.point);if(d<bd){bd=d;best=i}});
  return {face:best}}
// a click in the 3D view while faces are selected is for a face, never for a part: true when it was taken
export function faceClick(ev){if(!faceMode||!layer.visible)return false;const p=under(ev);
  if(p?.ghost!==undefined){state.removed=state.removed.filter((_,i)=>i!==p.ghost);act('put a removed face back');renderFaces();schedule()}
  else if(p){sel.has(p.face)?sel.delete(p.face):sel.add(p.face);draw()}
  return true}
function grow(all){   // the faces across an edge of the selection: one ring, or (`all`) on until nothing is added
  const walls=new Set((ST.plan?.edges3d||[]).filter(e=>e[1]==='chosen').map(e=>e[0])); let edge=[...sel];
  do{const next=[];for(const i of edge)for(const [j,k] of nb[i])if(!walls.has(k)&&!sel.has(j)){sel.add(j);next.push(j)}edge=next}while(all&&edge.length);
  draw()}
function inFile(){const back=new THREE.Matrix4().set(...ST.plan.frame.flat()).invert(), p=new THREE.Vector3();   // the selected faces' triangles, in the model file's coordinates
  return [...sel].map(i=>[tris[i].a,tris[i].b,tris[i].c].map(q=>p.copy(q).applyMatrix4(back).toArray().map(v=>+v.toFixed(4))))}
// a merged group under the new one is taken up by it: its flat face is among the selected faces
function merge(){if(sel.size<2)return;const under=groupsOf(),add=inFile();
  state.merged=[...(state.merged||[]).filter((_,g)=>!under.has(g)),add]; act(`merged ${add.length} faces into one`); renderFaces(); schedule()}
function unmerge(all){const under=groupsOf(),n=all?(state.merged||[]).length:under.size;if(!n)return;
  state.merged=all?[]:state.merged.filter((_,g)=>!under.has(g)); act(`unmerged ${n} face${n===1?'':'s'}`); renderFaces(); schedule()}
function remove(){if(!sel.size)return;const add=inFile();
  // a seam of the user's on an edge of a face that goes has done its work: it goes with the face, and undo brings both back
  const dead=(ST.plan.edges3d||[]).filter(e=>e[1]==='chosen'&&ST.plan.faces3d.adj[e[0]].some(i=>sel.has(i)));
  if(dead.length)state.seams=(state.seams||[]).filter(l=>!dead.some(e=>sameEnds(l,e)));
  state.removed=[...(state.removed||[]),...add]; act(`removed ${add.length} face${add.length===1?'':'s'}`); renderFaces(); schedule()}
function putAllBack(){if(!(state.removed||[]).length)return;state.removed=[];act('put all the removed faces back');renderFaces();schedule()}
export function setFaceMode(on){faceMode=!!on&&!!ST.plan?.faces3d; if(faceMode){deselect();foldUp()} else sel.clear();
  $('#facebar').hidden=!faceMode; showFaces(); draw()}
export const facesNow=()=>({mode:faceMode,shown:layer.visible,selected:[...sel],faces:tris.length,ghosts:gone.length,under:(x,y)=>under({clientX:x,clientY:y})});   // for the tests
export function initFaces(){
  scene.add(layer);
  document.addEventListener('click',e=>{const b=e.target.closest('[data-faces]');if(b)({grow:()=>grow(false),connected:()=>grow(true),remove,merge,unmerge:()=>unmerge(false),unmergeall:()=>unmerge(true),back:putAllBack,fold:foldUp})[b.dataset.faces]()});
  const c=renderer.domElement;
  c.addEventListener('pointerdown',ev=>{from=faceMode&&ev.button===0?[ev.clientX,ev.clientY]:null});
  // a drag paints the selection, once it is a drag and not a click (10 px, as everywhere in the view)
  c.addEventListener('pointermove',ev=>{if(!from||!(ev.buttons&1)||!layer.visible||Math.hypot(ev.clientX-from[0],ev.clientY-from[1])<=10)return;
    const p=under(ev);if(p?.face!==undefined&&!sel.has(p.face)){sel.add(p.face);draw()}});
  addEventListener('pointerup',()=>{from=null})}
