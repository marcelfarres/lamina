import * as THREE from 'three';
import {OrbitControls} from '../vendor/OrbitControls.js';
import {STLLoader} from '../vendor/STLLoader.js';
import {state, ST} from './state.js';
import {COLORS, LOOKS, PLANE_IDX, STRIPED} from './catalog.js';
import {$, status} from './util.js';
import {highlight, deselect, drawGizmo} from './edit3d.js';
import {renderSeams, showSeamLines} from './seams.js';
import {renderFaces, showFaces} from './faces.js';

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
let orbited=false; controls.addEventListener('change',()=>orbited=true);   // the camera alone: the lamp's shadows stay as they are
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
  if(moved||orbited||ST.dirty){renderer.shadowMap.needsUpdate=ST.dirty;renderer.render(scene,camera);drawCube();ST.dirty=orbited=false}})();
export function mat4(M){return new THREE.Matrix4().set(...M[0],...M[1],...M[2],...M[3])}
function shape(rings){const s=new THREE.Shape(rings[0].map(([x,y])=>new THREE.Vector2(x,y)));for(const h of rings.slice(1))s.holes.push(new THREE.Path(h.map(([x,y])=>new THREE.Vector2(x,y))));return s}
export function applyLook(){const k=$('#look').value,op=+$('#opacity').value;for(const m of parts.children){if(m.userData.group==='B')continue;   // a lobe boundary is a guide, not material: it keeps its own look
  const [c,r,me]=k==='group'?[COLORS[m.userData.group]||0xaaaaaa,.7,.05]:LOOKS[k],col=m.material.color.set(m.userData.bad?0xff5555:c);m.material.roughness=r;m.material.metalness=me;
  // a material look gives every part one colour: the striped family moves .3 in lightness away from it (lighter on a
  // dark look, darker on a light one), so it differs even on a cut edge seen end-on, where no stripe shows
  if(k!=='group'&&!m.userData.bad&&STRIPED.includes(m.userData.group)){const h={};col.getHSL(h,THREE.SRGBColorSpace);col.setHSL(h.h,h.s,h.l>.5?h.l-.3:h.l+.3,THREE.SRGBColorSpace)}
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
  const rod=(A,z,x,sec,len,color)=>{const m=new THREE.Mesh(new THREE.ExtrudeGeometry(new THREE.Shape(sec.map(([u,v])=>new THREE.Vector2(u,v))),{depth:len,bevelEnabled:false}),new THREE.MeshStandardMaterial({color,roughness:.6}));
    m.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,z.clone().cross(x),z));m.position.copy(A);axes.add(m)};
  for(const [a,b,,sec,xa] of ST.plan.rods||[]){const A=V3(a),z=V3(b).sub(A),len=z.length();rod(A,z.normalize(),V3(xa),sec,len,0xc8b48a)}
  // a printed standoff: a pin into each layer (a flush one where the hole is its own), and the body that keeps the two apart
  const so=ST.plan.standoffs, pin=f=>f?so.flush:so.pin;
  for(const e of so?.items||[]){const A=V3(e.at),z=V3(e.z),x=V3(e.x),at=d=>A.clone().addScaledVector(z,d);
    rod(at(-e.pins[0]),z,x,pin(e.flush[0]),e.pins[0],0xe8e8ee); rod(at(e.gap),z,x,pin(e.flush[1]),e.pins[1],0xe8e8ee); if(e.gap>0)rod(A,z,x,so.body,e.gap,0xe8e8ee)}
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
// Diagonal stripes on the second family of a technique (STRIPED): two families differ by pattern, not only by colour
// (the owner is colour-blind, and the old red rings between green half-slices were one colour to him). On the faces'
// own mm coordinates, about 20 stripes across the model whatever its size, so they read at the library's 320 × 240
// too. sRGB, so the band is the dark it is drawn as (read as linear it came out a light grey). The band lattice has a
// third family (Z): its stripes run the other way, as X and Z differ by hue only (and not at all under a material look)
const stripes=turn=>{const c=document.createElement('canvas');c.width=c.height=16;const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,16,16);g.fillStyle='#555';g.fillRect(0,0,16,8);
  const t=new THREE.CanvasTexture(c);t.colorSpace=THREE.SRGBColorSpace;t.wrapS=t.wrapT=THREE.RepeatWrapping;t.rotation=turn;return t};
const STRIPES=stripes(Math.PI/4), ACROSS=stripes(-Math.PI/4), stripesOf=g=>g==='Z'?ACROSS:STRIPED.includes(g)?STRIPES:null;
// Lamp: a bulb inside the model, in a room whose floor, walls and ceiling catch its light and the shadows the parts
// throw — as a camera sees a lamp in a dark room. The light falls off with the square of the distance, the picture is
// tone-mapped (AgX) so the bright inside of the shade does not clip to flat colour, and the room gives a little of the
// light back. A bulb is a ball, not a point, and its shadows are soft: the point light's shadow test is replaced (PCSS)
// by one that finds how far the part between the bulb and a point is, and blurs by the bulb's size times how much
// farther the point is than that part — sharp where a panel meets the floor, wide on a far wall, as a real bulb gives.
// The room is a box drawn from the inside: a wall between the camera and the model is seen from behind and not drawn,
// so the room can be looked into from any side. Off, nothing of it is on the scene and the view is the one without it.
// ponytail: paper that glows through, and a bulb dragged in 3D, are not here
const BULB={led:.04,frosted:.1};   // the bulb's radius, a share of the model's narrower width: a small LED, a frosted bulb
const lamp=new THREE.Group(), bulb=new THREE.PointLight(0xffcf9e,1,0,2),   // a warm white, as a camera balanced for the room shows a 3000 K bulb
  bulbMark=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),new THREE.MeshBasicMaterial({color:0xfff6e8,toneMapped:false})),
  glow=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex(),color:0xffc890,blending:THREE.AdditiveBlending,depthWrite:false,toneMapped:false})),
  bounce=new THREE.HemisphereLight(0xffd6a8,0x5a4a3c,.1),   // what the lit walls give back, from above more than below
  wallMat=new THREE.MeshStandardMaterial({color:0xf0eeea,roughness:.95,side:THREE.BackSide}), floorMat=new THREE.MeshStandardMaterial({color:0xc9c2b8,roughness:.9,side:THREE.BackSide}),
  room=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),[wallMat,wallMat,wallMat,wallMat,wallMat,floorMat]); let lampOn=false;   // faces +x −x +y −y, ceiling, floor
bulb.castShadow=room.receiveShadow=true; bulb.shadow.mapSize.set(1024,1024); bulb.shadow.bias=-.001; bulb.shadow.normalBias=.3;
bounce.position.set(0,0,1); lamp.add(bulb,bulbMark,glow,bounce,room); lamp.visible=false; scene.add(lamp);
renderer.shadowMap.autoUpdate=false;   // the shadows are made again when something but the camera moved (the render loop)
renderer.toneMappingExposure=1.5;      // used only while the lamp tone-maps
// The soft test, for every point light (the lamp's bulb is the only one). shadow.radius carries the bulb's radius in mm.
// Both steps take samples on a spiral turned by a random angle at each pixel: a wide soft edge shows as fine grain, as
// in a photo. One fixed spiral drew a wide edge as 32 streaks; an angle from interleaved gradient noise, as diagonal
// hatching (it is made for renderers that average frames, and this view draws one).
const PCSS=`float getPointShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
	float texelY = 1.0 / ( shadowMapSize.y * 2.0 ), range = shadowCameraFar - shadowCameraNear, R = shadowRadius;
	float dr = length( shadowCoord.xyz ), dp = ( dr - shadowCameraNear ) / range + shadowBias;
	vec3 d = shadowCoord.xyz / dr, t = normalize( cross( d, abs( d.z ) < 0.9 ? vec3( 0.0, 0.0, 1.0 ) : vec3( 1.0, 0.0, 0.0 ) ) ), b = cross( d, t );
	float spin = 6.2831853 * fract( sin( dot( gl_FragCoord.xy, vec2( 12.9898, 78.233 ) ) ) * 43758.5453 );
	float search = 0.5 * max( 1.0 - 2.0 * R / dr, 0.0 ), sum = 0.0, n = 0.0;   // where a part at least 2 R from the bulb's centre can hide some of the bulb
	for ( int i = 0; i < 16; i ++ ) {
		float r = sqrt( ( float( i ) + 0.5 ) / 16.0 ) * search, a = float( i ) * 2.39996 + spin;
		float z = unpackRGBAToDepth( texture2D( shadowMap, cubeToUV( d + ( t * cos( a ) + b * sin( a ) ) * r, texelY ) ) );
		if ( z < dp ) { sum += z; n += 1.0; }
	}
	float lit = 1.0;   // nothing in the way: no return here, the quad's mean below needs every pixel of it to get there
	if ( n > 0.0 ) {
		float db = shadowCameraNear + sum / n * range, pen = max( R * ( dr - db ) / ( db * dr ), 6.0 * texelY );
		lit = 0.0;
		for ( int i = 0; i < 32; i ++ ) {
			float r = sqrt( ( float( i ) + 0.5 ) / 32.0 ) * pen, a = float( i ) * 2.39996 + spin;
			lit += texture2DCompare( shadowMap, cubeToUV( d + ( t * cos( a ) + b * sin( a ) ) * r, texelY ), dp );
		}
		lit /= 32.0;
	}
	// the mean of this pixel and its two neighbours in the GPU's 2x2 quad, read through the derivatives: three spirals'
	// worth of samples, so a third of the grain's variance, for no more lookups
	vec2 q = mod( floor( gl_FragCoord.xy ), 2.0 ) - 0.5;
	return lit - ( dFdx( lit ) * q.x + dFdy( lit ) * q.y ) * 0.6667;
}
#endif`, chunk=THREE.ShaderChunk.shadowmap_pars_fragment.replace(/float getPointShadow\([\s\S]*#endif$/,PCSS);
if(chunk===THREE.ShaderChunk.shadowmap_pars_fragment)console.error('lamp: the point-shadow code of three.js has changed; the soft shadows are off');
THREE.ShaderChunk.shadowmap_pars_fragment=chunk;
function glowTex(){const c=document.createElement('canvas');c.width=c.height=64;const g=c.getContext('2d'),r=g.createRadialGradient(32,32,0,32,32,32);
  r.addColorStop(0,'rgba(255,255,255,1)');r.addColorStop(.15,'rgba(255,255,255,.4)');r.addColorStop(1,'rgba(255,255,255,0)');g.fillStyle=r;g.fillRect(0,0,64,64);return new THREE.CanvasTexture(c)}
export function applyLamp(){const on=$('#lamp').checked; $('#lampl').hidden=!on;
  if(on){const b=new THREE.Box3(); for(const m of parts.children)if(m.userData.group!=='B')b.expandByObject(m);   // every part, shown or not: the room stays put while the steps run
    if(b.isEmpty())b.setFromObject(ghost); if(b.isEmpty())return;
    const c=b.getCenter(new THREE.Vector3()),S=b.getSize(new THREE.Vector3()),r=S.length(),br=Math.min(S.x,S.y)*BULB[$('#lampb').value],half=r*.9,high=r*1.6;
    bulb.position.set(b.min.x+$('#lampx').value*S.x,b.min.y+$('#lampy').value*S.y,b.min.z+$('#lampz').value*S.z);   // each slider from the model's one side to the other
    bulb.intensity=3*half*half; bulb.shadow.radius=br; bulb.shadow.camera.far=r*3; bulb.shadow.camera.updateProjectionMatrix();   // a wall as far as the room's half width is about as bright at any size
    bulbMark.position.copy(bulb.position); bulbMark.scale.setScalar(br); glow.position.copy(bulb.position); glow.scale.setScalar(br*7);
    room.scale.set(half*2,half*2,high); room.position.set(c.x,c.y,b.min.z-r*.002+high/2)}
  for(const m of parts.children)m.castShadow=m.receiveShadow=on&&m.userData.group!=='B';
  lamp.visible=on; renderer.shadowMap.enabled=on; renderer.toneMapping=on?THREE.AgXToneMapping:THREE.NoToneMapping;
  hemi.intensity=on?0:1.1; dl.intensity=on?0:1.2; scene.background.set(on?0x050506:0x141517);
  if(on!==lampOn){lampOn=on; for(const m of [...parts.children,room])for(const x of [m.material].flat())x.needsUpdate=true}   // the shaders gain or lose the shadow lookup
  ST.dirty=true}
$('#lamp').onchange=$('#lampb').onchange=$('#lampx').oninput=$('#lampy').oninput=$('#lampz').oninput=applyLamp;
export function render3D(modelUrl){
  parts.clear(); let i=0; for(const t of [STRIPES,ACROSS])t.repeat.setScalar(20/Math.max(...ST.plan.bbox));
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
    const m=new THREE.Mesh(mergeGeos(geos),new THREE.MeshStandardMaterial({color:COLORS[s.group]||0xaaaaaa,roughness:.7,metalness:.05,map:stripesOf(s.group)}));
    m.userData={slice:s.label,piece:pc.label,group:s.group,i:i++,origin:new THREE.Vector3(s.M[0][3],s.M[1][3],s.M[2][3]),normal:new THREE.Vector3(s.M[0][2],s.M[1][2],s.M[2][2]),bad:s.errors.length>0};
    // a part with errors is red and netted with dark lines (the ✗ of the results list): red alone is lost on a colour-blind
    // eye. The net shares the part's geometry, so it folds with it; it takes no clicks, the part does; the faces sit a
    // step back in depth so the net never fights them
    if(m.userData.bad){const net=new THREE.Mesh(m.geometry,new THREE.MeshBasicMaterial({color:0x111111,wireframe:true}));net.raycast=()=>{};m.add(net);
      Object.assign(m.material,{polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1})}
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
  renderSeams(); renderFaces();
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
function mergeGeos(geos){   // uv too: the extrusion's own, in mm, for the ring slices' stripes
  const ngs=geos.map(g=>g.index?g.toNonIndexed():g),g=new THREE.BufferGeometry();
  for(const [k,n] of [['position',3],['normal',3],['uv',2]]){const a=new Float32Array(ngs.reduce((s,x)=>s+x.attributes[k].array.length,0));let o=0;
    for(const x of ngs){a.set(x.attributes[k].array,o);o+=x.attributes[k].array.length}g.setAttribute(k,new THREE.BufferAttribute(a,n))}
  return g}
// the standard view of what is shown (the parts, or the model until there are any): its centre, its diagonal, the eye.
// A plaque is seen from the side away from its plate (the plan's `back`, an axis of the scene), so the fit button and
// the library's picture show the slices, not the plate's back. Only the parts are the plan's (render3D builds them from
// it): a model's ghost lands before its plan, while ST.plan is still the last model's, so the ghost alone is seen from
// the standard side
const EYE=new THREE.Vector3(.7,-1,.6);   // where the standard view looks from, before it is scaled to the model
function fitPose(){const P=parts.children.length, b=new THREE.Box3().setFromObject(P?parts:ghost);if(b.isEmpty())return null;const c=b.getCenter(new THREE.Vector3()),s=b.getSize(new THREE.Vector3()).length();
  const dir=EYE.clone(), back=P&&ST.plan?.mode==='plaque'&&ST.plan.params.back;
  if(back){const k='xyz'.indexOf(back[1]);dir.setComponent(k,(back[0]==='-'?1:-1)*Math.abs(dir.getComponent(k)))}
  return {c,s,eye:c.clone().add(dir.normalize().multiplyScalar(s*1.5))}}
function fitView(){const p=fitPose();if(!p)return;const {c,s,eye}=p;controls.target.copy(c);camera.position.copy(eye);
  // close enough to read a slot, never onto the point it turns about (from 0 no zoom ever comes back), never so far the
  // model is lost; the clipping planes outside both, so nothing is cut away at either end
  controls.minDistance=s/40;controls.maxDistance=s*8;camera.near=s/200;camera.far=s*20;camera.updateProjectionMatrix()}
// A w × h picture of the model as built, in the fitted view, for the library: a camera of its own, no view cube. The
// same picture whatever is selected, stepped, exploded, folded or ticked, so the cards are even: every part in place
// and folded up, no highlight, no lobe planes (a guide, not material), the see-through model only while there are no
// parts. The dowel rods stay: they are the axes group's meshes, its arrows and letters are the helper. The renderer
// keeps no picture between frames, so it is read in the same task it is drawn, and the view is drawn again at its own
// size before the task ends: the page never shows the small frame. '' when there is nothing to show. The lamp is off
// for it too (its dark room is a way to look at the model, not the model), and on again after.
export function snapshot(w=320,h=240){
  const P=parts.children,fold=$('#fold'),fv=fold.value,lampBox=$('#lamp'),lit=lampBox.checked,
    flags=[...[rings,gizmo,guides,banner,...axes.children.filter(o=>!o.isMesh)].map(o=>[o,false]),[ghost,!P.length],...P.map(m=>[m,m.userData.group!=='B'])],
    was=flags.map(([o])=>o.visible),pos=P.map(m=>m.position.clone()),glow=P.map(m=>m.material.emissive.getHex()),
    size=renderer.getSize(new THREE.Vector2()),pr=renderer.getPixelRatio(),dirty=ST.dirty;
  let url='';
  try{if(lit){lampBox.checked=false;applyLamp()}
    fold.value=1;applyFold(); flags.forEach(([o,v])=>o.visible=v); P.forEach(m=>{m.position.set(0,0,0);m.material.emissive.set(0)});
    const p=fitPose(); if(!p)return url;
    const cam=new THREE.PerspectiveCamera(camera.fov,w/h,p.s/200,p.s*20); cam.up.set(0,0,1); cam.position.copy(p.eye); cam.lookAt(p.c);
    renderer.setPixelRatio(1); renderer.setSize(w,h,false); renderer.render(scene,cam);
    url=renderer.domElement.toDataURL('image/webp',.8);   // a browser without WebP gives PNG
  }finally{fold.value=fv;applyFold(); flags.forEach(([o],i)=>o.visible=was[i]); P.forEach((m,i)=>{m.position.copy(pos[i]);m.material.emissive.setHex(glow[i])});
    if(lit){lampBox.checked=true;applyLamp()}   // after the parts are back: the room is fitted to them
    renderer.setPixelRatio(pr); renderer.setSize(size.x,size.y,false); renderer.render(scene,camera); drawCube(); ST.dirty=dirty||lit}   // lit: its shadows drawn again
  return url}
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
  $('#fold_val').textContent=Math.round(s*100)+' %'; showSeamLines(); showFaces(); ST.dirty=true}
const FOLD_STEPS=20; let nParts=0;   // the steps a folded job takes to fold up, and the parts in the build order before them
export function applyExplode(){const e=+$('#explode').value,st=$('#steps'),k=+st.value;for(const m of parts.children){if(m.userData.group==='B')continue;m.position.copy(m.userData.origin).multiplyScalar(e-1);m.visible=m.userData.i<k}
  const folding=+st.max>nParts, share=folding?Math.min(1,Math.max(0,(k-nParts)/FOLD_STEPS)):1;
  if(folding){$('#fold').value=share;applyFold()}   // the panels go in flat, then fold up
  const going=k<+st.max&&parts.children.find(m=>m.userData.i===k-1);
  showBanner(going?`step ${k} / ${+st.max}  ·  ${(ST.plan&&ST.plan.label_tag?ST.plan.label_tag+' ':'')}${going.userData.piece}`:folding&&k<+st.max?`step ${k} / ${+st.max}  ·  folding ${Math.round(share*100)} %`:'');
  $('#steps_val').textContent=`${k} / ${+st.max||0}`;   // the step counter, live while the slider is dragged
  const s=ST.selected&&parts.children.find(c=>c.userData.slice===ST.selected); if(s)drawGizmo(s);   // the handles ride with the part
  showSeamLines(); showFaces(); applyLamp()}
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

