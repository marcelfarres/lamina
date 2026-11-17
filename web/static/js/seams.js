import * as THREE from 'three';
import {state, ST} from './state.js';
import {$, $$} from './util.js';
import {act} from './history.js';
import {schedule} from './form.js';
import {deselect, setTool} from './edit3d.js';
import {scene, parts, ray, camera, renderer, V3, applyExplode, applyFold} from './scene.js';

// ---------------------------------------------------------------- choosing the seams (folded panels)
// The unfolder decides which edges are folds and which are seams. The `put a seam` tool of the 3D view lets the user
// put a seam on an edge: the plan lists every edge (edges3d: [k, fold | seam | chosen, end, end, way out]) and where
// each lies on its sheet (a piece's `edges`: [k, x0, y0, x1, y1]). A click on an edge, on the model or on a sheet,
// adds it to `seams` by its two ends or takes it out again; a drag along edges of the model paints seams (it only
// adds); and the re-slice lays the panels out round the seams that are left. The edge under
// the pointer lights up in both views at once, so a seam picked on the net is seen on the model and the other way.
// Nothing here runs when the module loads but its own objects: the modules import each other in a ring, and what
// reaches into another one (the scene, the canvas, the sheets) waits for initSeams().
const SEAMC={fold:0xc9cad0,seam:0xE69F00,chosen:0x56B4E9,hover:0xF0E442};   // Okabe-Ito; the line style carries the meaning (thin, dashed, thick)
const SEAMTIP={fold:'<b>fold</b><br>click: put a seam here',seam:'<b>seam</b> the program chose<br>click: make it yours, so it stays a seam',chosen:'<b>your seam</b><br>click: the program decides this edge again'};
const edgeLines=new THREE.Group(), rodGeo=new THREE.CylinderGeometry(1,1,1,6), seamRod=new THREE.Mesh(rodGeo,new THREE.MeshBasicMaterial({color:SEAMC.hover,depthTest:false}));
seamRod.renderOrder=3; seamRod.matrixAutoUpdate=false; seamRod.visible=false; edgeLines.visible=false;   // the lit edge draws through the model: an edge picked on a sheet may be on the far side
let seamMode=false, seamHover=null, seamSegs=new Map(), seamR=1;   // seamHover: the edge under the pointer (its k); seamSegs: k → its line in the 3D view
let paintFrom=null, painted=0;                                     // a drag that paints seams: where it began, how many it has put
const rodAt=(A,B,r,M=new THREE.Matrix4())=>{const d=B.clone().sub(A),L=d.length()||1e-6;return M.compose(A.clone().lerp(B,.5),new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),d.divideScalar(L)),new THREE.Vector3(r,L,r))};
function rods(segs,r,color){const m=new THREE.InstancedMesh(rodGeo,new THREE.MeshBasicMaterial({color}),segs.length);segs.forEach(([A,B],i)=>m.setMatrixAt(i,rodAt(A,B,r)));m.frustumCulled=false;return m}   // one draw for every rod; its own bounds are the unit rod's, so never culled
const seamEdge=k=>ST.plan?.edges3d?.find(e=>e[0]===k);
const sameEnds=(l,e)=>{const n=(p,q)=>Math.max(...p.map((v,i)=>Math.abs(v-q[i])))<0.05;return n(l[0],e[2])&&n(l[1],e[3])||n(l[0],e[3])&&n(l[1],e[2])};   // a seam is kept by its two ends, either way round
export const seamsFolded=()=>+$('#fold').value===1&&+$('#explode').value===1&&+$('#steps').value===+$('#steps').max;   // the edges are the folded model's
export function showSeamLines(){edgeLines.visible=seamMode&&seamsFolded();$('#seam_off').hidden=!seamMode||edgeLines.visible;if(!edgeLines.visible)seamRod.visible=false}
export function renderSeams(){   // the edges on the model, from the plan just drawn
  for(const o of edgeLines.children){if(o.geometry!==rodGeo)o.geometry.dispose();o.material.dispose()} edgeLines.clear(); seamSegs=new Map(); seamLit(null);
  const E=ST.plan?.edges3d; if(!E){if(seamMode)setTool('');return syncSeams()}
  // a hair outside the surface, so a line is not half sunk in the sheet it lies on; rods as thick as the model is big
  const big=Math.max(...ST.plan.bbox), out=big*0.002+0.05, dash=big*0.03+1, by={fold:[],seam:[],chosen:[]}; seamR=big*0.004+0.15;
  for(const e of E){const n=V3(e[4]).multiplyScalar(out),A=V3(e[2]).add(n),B=V3(e[3]).add(n);seamSegs.set(e[0],new THREE.Line3(A,B));by[e[1]].push([A,B])}
  edgeLines.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(by.fold.flat()),new THREE.LineBasicMaterial({color:SEAMC.fold,transparent:true,opacity:.75})));
  const dashes=[];for(const [A,B] of by.seam){const n=Math.max(1,Math.round(A.distanceTo(B)/dash));for(let i=0;i<n;i++)dashes.push([A.clone().lerp(B,(i+.2)/n),A.clone().lerp(B,(i+.8)/n)])}
  if(dashes.length)edgeLines.add(rods(dashes,seamR*.6,SEAMC.seam)); if(by.chosen.length)edgeLines.add(rods(by.chosen,seamR*1.4,SEAMC.chosen));
  showSeamLines(); syncSeams(); ST.dirty=true}
export function sheetSeams(){   // the same edges on the sheets just drawn: a line to pick each by, and a mark on the user's seams
  for(const g of $$('#sheets g.seams'))g.remove(); $('#sheets').classList.toggle('choosing',seamMode); if(!ST.plan?.edges3d)return;
  const kind=new Map(ST.plan.edges3d.map(e=>[e[0],e[1]])), svgs=$$('#sheets svg'), out=svgs.map(()=>['','']);
  for(const s of ST.plan.slices)for(const pc of s.pieces){const i=pc.place[0],H=svgs[i]?.viewBox.baseVal.height;if(!H)continue;   // the sheet is drawn y up: y → height − y
    for(const [k,x0,y0,x1,y1] of pc.edges||[]){const at=`data-k="${k}" x1="${x0}" y1="${+(H-y0).toFixed(3)}" x2="${x1}" y2="${+(H-y1).toFixed(3)}"`;
      out[i][0]+=`<line class="hit" ${at}/>`;if(kind.get(k)==='chosen')out[i][1]+=`<line class="mine" ${at}/>`}}
  svgs.forEach((svg,i)=>svg.insertAdjacentHTML('beforeend',`<g class="seams">${out[i][1]}${out[i][0]}</g>`))}
export function syncSeams(){const E=ST.plan?.edges3d||[], n=k=>E.filter(e=>e[1]===k).length, mine=n('chosen'), lost=Math.max(0,(state.seams||[]).length-mine), c=$('#seam_n');
  if(c)c.textContent=E.length?`${mine} chosen by you · ${n('seam')} by the program${lost?` · ${lost} of yours on no edge now`:''}`:'no edges yet';
  for(const b of $$('[data-seams="clear"]'))b.disabled=!(state.seams||[]).length;
  for(const k of ['fold','seam','chosen'])$('#sl_'+k).textContent=`(${n(k)})`}
function seamLit(k,ev){   // the edge under the pointer, lit on the model and on every sheet it lies on, with what a click will do
  if(k!==seamHover){seamHover=k; for(const l of $$('#sheets line.hov'))l.remove();
    if(k!==null)for(const l of $$(`#sheets line.hit[data-k="${k}"]`)){const c=l.cloneNode();c.setAttribute('class','hov');l.parentNode.append(c)}
    const L=k!==null&&edgeLines.visible&&seamSegs.get(k); seamRod.visible=!!L; if(L)rodAt(L.start,L.end,seamR*2,seamRod.matrix); ST.dirty=true}
  const t=$('#seamtip'), e=k!==null&&ev&&seamEdge(k); t.hidden=!e; if(e){t.innerHTML=SEAMTIP[e[1]];t.style.left=ev.clientX+16+'px';t.style.top=ev.clientY+14+'px'}}
function edgeAt(ev){   // the edge nearest the point of the model under the pointer, within 14 px of it
  if(!edgeLines.visible)return null; const r=renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2((ev.clientX-r.left)/r.width*2-1,-(ev.clientY-r.top)/r.height*2+1),camera);const h=ray.intersectObjects(parts.children.filter(m=>m.visible))[0];if(!h)return null;
  let best=null,bd=14*2*h.distance*Math.tan(camera.fov*Math.PI/360)/r.height;const q=new THREE.Vector3();
  for(const [k,L] of seamSegs){const d=L.closestPointToPoint(h.point,true,q).distanceTo(h.point);if(d<bd){bd=d;best=k}}
  return best}
export function toggleSeam(k){const e=seamEdge(k);if(!e)return;const list=state.seams||[],was=list.some(l=>sameEnds(l,e));
  state.seams=was?list.filter(l=>!sameEnds(l,e)):[...list,[e[2],e[3]]];
  e[1]=was?'seam':'chosen';   // shown at once on both views; the slice that follows lays the panels out again and says what the other edges became
  act(`${was?'gave back':'chose'} a seam (${state.seams.length} chosen)`); renderSeams(); sheetSeams(); schedule()}
function clearSeams(){if(!(state.seams||[]).length)return;state.seams=[];for(const e of ST.plan?.edges3d||[])if(e[1]==='chosen')e[1]='seam';act('cleared the chosen seams');renderSeams();sheetSeams();schedule()}
export function foldUp(){$('#explode').value=1;$('#steps').value=$('#steps').max;$('#fold').value=1;applyExplode();applyFold()}
export function setSeamMode(on){seamMode=!!on&&!!ST.plan?.edges3d; if(seamMode){deselect();foldUp()} else seamLit(null);
  $('#seampanel').hidden=!seamMode; $('#sheets').classList.toggle('choosing',seamMode); showSeamLines(); syncSeams(); ST.dirty=true}
// a click in the 3D view while seams are chosen is for an edge, never for a part: true when it was taken
export function seamClick(ev){if(!seamMode||!edgeLines.visible)return false;const k=edgeAt(ev);if(k!==null)toggleSeam(k);return true}
export const leaveSeams=()=>seamMode&&(setTool(''),true);   // Esc
export const seamsNow=()=>({mode:seamMode,hover:seamHover,shown:edgeLines.visible,segs:seamSegs});   // for the tests
export function initSeams(){
  scene.add(edgeLines,seamRod);
  document.addEventListener('click',e=>{const b=e.target.closest('[data-seams]');if(!b)return;const a=b.dataset.seams;a==='mode'?setTool(seamMode?'':'seam'):a==='clear'?clearSeams():foldUp()});
  renderer.domElement.addEventListener('pointerdown',ev=>{paintFrom=seamMode&&ev.button===0?[ev.clientX,ev.clientY]:null;painted=0});
  renderer.domElement.addEventListener('pointermove',ev=>{if(!seamMode)return;if(!ev.buttons)return seamLit(edgeAt(ev),ev);   // no button down: the edge under the pointer is lit
    // a drag with the left button paints: every edge it passes becomes a seam of the user's, once it is a drag and not a click (10 px)
    if(!paintFrom||!(ev.buttons&1)||Math.hypot(ev.clientX-paintFrom[0],ev.clientY-paintFrom[1])<=10)return;
    const e=seamEdge(edgeAt(ev));if(!e||e[1]==='chosen')return;
    state.seams=[...(state.seams||[]),[e[2],e[3]]];e[1]='chosen';painted++;renderSeams();sheetSeams()});
  addEventListener('pointerup',()=>{if(paintFrom&&painted){act(`painted ${painted} seam${painted===1?'':'s'} (${state.seams.length} chosen)`);schedule()}paintFrom=null});   // one slice for the whole stroke
  renderer.domElement.addEventListener('pointerleave',()=>seamLit(null));
  $('#sheets').addEventListener('pointermove',e=>{if(seamMode){const l=e.target.closest?.('line.hit');seamLit(l?+l.dataset.k:null,e)}});
  $('#sheets').addEventListener('pointerleave',()=>seamLit(null))}
