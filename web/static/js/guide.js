// The printable assembly guide: one card per build step, a 3D picture of the model as built so far from one fixed
// camera, with the part that goes in now framed and numbered. Built in the page from the plan and the 3D view's own
// parts, opened in a new tab as one self-contained HTML file (JPEG pictures inline). It changes nothing: the plan,
// the steps slider, the explode, the colours and the background are put back as they were.
import * as THREE from 'three';
import {state, ST} from './state.js';
import {esc, status} from './util.js';
import {fmtLen} from './units.js';
import {parts, renderer, camera, scene, ghost, rings, gizmo, guides, axes, banner, applyFold, fitPose} from './scene.js';

const W=600, H=304, PER_PAGE=6, PALE=0xd2d2d2, BLUE='#0072B2';   // Okabe-Ito blue; W:H is the shape of the card's picture

// The pictures: step k shows parts 1..k, earlier ones pale with edge lines, the new one as it looks in the 3D view.
// `box` is the new part's frame in picture pixels. One task, as snapshot() in scene.js: the renderer keeps no picture.
function pictures(){
  const P=parts.children.filter(m=>m.userData.group!=='B').sort((a,b)=>a.userData.i-b.userData.i);   // the build order, as the steps slider counts it
  if(!P.length)return [];
  const fold=document.getElementById('fold'), fv=fold.value, lit=!!state.light, bg=scene.background,
    helpers=[rings,gizmo,guides,banner,axes,ghost], helperWas=helpers.map(o=>o.visible),
    all=parts.children, was=all.map(m=>m.visible), pos=all.map(m=>m.position.clone()), glow=all.map(m=>m.material.emissive.getHex()),
    look=P.map(m=>[m.material.color.getHex(),m.material.map]), pane=P.map(m=>m.userData.pane?.visible),
    size=renderer.getSize(new THREE.Vector2()), pr=renderer.getPixelRatio(), out=[], lines=[], xray=new THREE.Mesh();
  try{
    if(lit){state.light=false;ST.light()}
    fold.value=1; applyFold();                                      // a folded job is shown folded: the guide has the parts' steps only
    helpers.forEach(o=>o.visible=false); all.forEach(m=>{m.position.set(0,0,0);m.material.emissive.set(0);m.visible=m.userData.group!=='B'});
    const p=fitPose(), cam=new THREE.PerspectiveCamera(camera.fov,W/H,p.s/200,p.s*20); cam.up.set(0,0,1); cam.position.copy(p.eye); cam.lookAt(p.c); cam.updateMatrixWorld();
    const corners=box=>[box.min.x,box.max.x].flatMap(x=>[box.min.y,box.max.y].flatMap(y=>[box.min.z,box.max.z].map(z=>new THREE.Vector3(x,y,z).project(cam))));
    const whole=corners(new THREE.Box3().setFromObject(parts));       // the whole model fills the frame, the same for every card
    cam.zoom=.92/Math.max(...whole.flatMap(v=>[Math.abs(v.x),Math.abs(v.y)])); cam.updateProjectionMatrix();
    const frames=P.map(m=>{const c=corners(new THREE.Box3().setFromObject(m)),xs=c.map(v=>(v.x+1)/2*W),ys=c.map(v=>(1-v.y)/2*H);return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]});
    for(const m of P){const l=new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry,25),new THREE.LineBasicMaterial({color:0x444444}));m.add(l);lines.push(l)}
    renderer.setPixelRatio(1); renderer.setSize(W,H,false);
    // where parts built before hide the new one (the back of a ring, inside a lattice), it shows through them as blue
    // stripes in screen pixels (a pattern, not only a colour, as faces.js hatches): drawn again only where something is
    // nearer (GreaterDepth), so a part in sight is unchanged; the offset towards the camera keeps its own faces, drawn
    // twice, from speckling it
    xray.material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,depthFunc:THREE.GreaterDepth,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-8,
      vertexShader:'void main(){gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader:'void main(){gl_FragColor=vec4(0.0,0.447,0.698,mod(gl_FragCoord.x+gl_FragCoord.y,8.0)<3.0?0.9:0.25);}'});   // BLUE
    P.forEach((_,k)=>{
      xray.geometry=P[k].geometry; P[k].add(xray);
      P.forEach((m,j)=>{const now=j===k; m.visible=j<=k;
        m.material.color.setHex(now?look[j][0]:PALE); m.material.map=now?look[j][1]:null; m.material.needsUpdate=true;
        lines[j].visible=!now; if(m.userData.pane)m.userData.pane.visible=now});
      scene.background=new THREE.Color(0xffffff); renderer.shadowMap.needsUpdate=true; renderer.render(scene,cam);   // the light resets the background: set it just before each render
      out.push({img:renderer.domElement.toDataURL('image/jpeg',.82),box:frames[k]}); xray.removeFromParent()});
  }finally{
    xray.removeFromParent(); xray.material.dispose();
    for(const l of lines){l.parent.remove(l);l.geometry.dispose();l.material.dispose()}
    P.forEach((m,j)=>{m.material.color.setHex(look[j][0]);m.material.map=look[j][1];m.material.needsUpdate=true;if(m.userData.pane)m.userData.pane.visible=pane[j]});
    fold.value=fv; applyFold(); helpers.forEach((o,i)=>o.visible=helperWas[i]); all.forEach((m,i)=>{m.visible=was[i];m.position.copy(pos[i]);m.material.emissive.setHex(glow[i])});
    scene.background=bg; if(lit){state.light=true;ST.light()}
    renderer.setPixelRatio(pr); renderer.setSize(size.x,size.y,false); ST.dirty=true}
  return out.map((o,k)=>({...o,mesh:P[k].userData}));
}

// The step's cut outline from the kerfed rings (holes show: even-odd), 88 px square, and its size
function outline(kerfed,S=88){
  const pts=kerfed.flat(2), xs=pts.map(q=>q[0]), ys=pts.map(q=>q[1]); if(!pts.length)return {svg:'',w:0,h:0};
  const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys),k=(S-8)/Math.max(x1-x0,y1-y0,1e-6),ox=(S-(x1-x0)*k)/2,oy=(S-(y1-y0)*k)/2;
  const d=kerfed.flatMap(g=>g.map(r=>'M'+r.map(([x,y])=>`${((x-x0)*k+ox).toFixed(1)},${((y1-y)*k+oy).toFixed(1)}`).join('L')+'Z')).join(' ');
  return {svg:`<svg viewBox="0 0 ${S} ${S}" width="${S}" height="${S}"><rect x=".5" y=".5" width="${S-1}" height="${S-1}" fill="none" stroke="#bbb"/><path d="${d}" fill="#e3e3e3" fill-rule="evenodd" stroke="#111" stroke-width="1.4"/></svg>`,w:x1-x0,h:y1-y0};
}

// What the picture adds to the 3D shot: a dashed frame round the new part and a numbered arrow to it (never colour alone)
function marks(k,[x0,y0,x1,y1]){
  const cx=Math.max(24,Math.min(W-24,x0-38)), cy=Math.max(24,Math.min(H-24,y0-38)), tx=Math.max(x0,Math.min(x1,cx)), ty=Math.max(y0,Math.min(y1,cy)),
    d=Math.hypot(tx-cx,ty-cy)||1, ux=(tx-cx)/d, uy=(ty-cy)/d, bx=tx-ux*16, by=ty-uy*16;
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><rect x="${(x0-4).toFixed(0)}" y="${(y0-4).toFixed(0)}" width="${(x1-x0+8).toFixed(0)}" height="${(y1-y0+8).toFixed(0)}" fill="none" stroke="${BLUE}" stroke-width="4" stroke-dasharray="14 8"/>`
    +`<line x1="${cx}" y1="${cy}" x2="${bx.toFixed(1)}" y2="${by.toFixed(1)}" stroke="${BLUE}" stroke-width="4"/><polygon points="${tx.toFixed(1)},${ty.toFixed(1)} ${(bx-uy*9).toFixed(1)},${(by+ux*9).toFixed(1)} ${(bx+uy*9).toFixed(1)},${(by-ux*9).toFixed(1)}" fill="${BLUE}"/>`
    +`<circle cx="${cx}" cy="${cy}" r="21" fill="#fff" stroke="${BLUE}" stroke-width="4"/><text x="${cx}" y="${cy+8}" text-anchor="middle" font-size="${k>99?17:23}" font-weight="800" fill="#111">${k}</text></svg>`;
}

const CSS=`@page{size:A4;margin:0}*{box-sizing:border-box}body{margin:0;background:#888;font:12px/1.35 system-ui,Segoe UI,Arial,sans-serif;color:#111}
.bar{position:sticky;top:0;z-index:1;background:#222;color:#fff;padding:8px 16px;display:flex;gap:16px;align-items:center}.bar button,.bar a{font:inherit;color:#fff;background:#0072B2;border:0;border-radius:4px;padding:5px 12px;text-decoration:none;cursor:pointer}
.page{width:210mm;height:296mm;background:#fff;margin:12px auto;padding:28px;position:relative;overflow:hidden;break-after:page}
@media print{body{background:#fff}.bar{display:none}.page{margin:0}}
h1{font-size:22px;margin:0 0 2px}.sub{color:#333;font-size:13px;margin-bottom:8px}
.head{display:grid;grid-template-columns:1.15fr 1fr;gap:16px;height:156px;border-bottom:2px solid #111;padding-bottom:8px;margin-bottom:8px}
.facts{display:grid;grid-template-columns:auto 1fr;gap:1px 10px}.facts b{font-weight:600}
.how ol{margin:2px 0 4px 16px;padding:0}.leg{display:flex;flex-direction:column;gap:3px;font-size:11px}.leg span{display:inline-flex;gap:4px;align-items:center}
.grid{display:grid;grid-template-columns:1fr 1fr;grid-auto-rows:285px;gap:8px}
.card{border:1.5px solid #111;border-radius:6px;overflow:hidden;display:flex;flex-direction:column;background:#fff}
.pic{height:185px;position:relative;border-bottom:1px solid #999}.pic svg,.pic img{position:absolute;inset:0;width:100%;height:100%}
.info{flex:1;display:grid;grid-template-columns:auto 1fr 92px;gap:8px;padding:6px 8px;align-items:start}
.num{font-weight:800;border:2.5px solid #111;border-radius:50%;width:54px;height:54px;display:flex;align-items:center;justify-content:center;font-size:24px}
.t{font-size:15px;font-weight:700;overflow-wrap:anywhere}.m{font-size:11.5px;color:#222}.m b{font-weight:600}.cap{font-size:9.5px;color:#444;text-align:center;line-height:1.2}
.foot{position:absolute;left:28px;right:28px;bottom:10px;font-size:9.5px;color:#444;border-top:1px solid #bbb;padding-top:3px;display:flex;justify-content:space-between}`;

// Everything on one card comes from the plan's piece, found by the mesh's own slice and piece labels, never by position
function stepsOf(shots){
  const P=ST.plan, stacked=ST.mode?.name==='stacked', codes=P.codes||{}; let below=[], now=[], at=null;
  return shots.map((s,k)=>{
    const sl=P.slices.find(x=>x.label===s.mesh.slice), pc=sl.pieces.find(x=>x.label===s.mesh.piece);
    if(sl.label!==at){below=now;now=[];at=sl.label}; now.push(pc.label);                  // the layer before this one, for a stacked job
    const onto=stacked?(below.length?below.join(', '):'nothing: it is the first layer'):[...new Set(sl.engages||[])].join(', ');
    return {k:k+1,...s,label:pc.label,code:codes[pc.label],sheet:pc.place[0]+1,thickness:sl.thickness,onto:onto||'nothing in particular',...outline(pc.kerfed||[])}});
}

function card(s){
  const unit=state.printed?'Plate':'Sheet', engraved=s.code||s.label;
  return `<div class="card"><div class="pic"><img src="${s.img}" alt="step ${s.k}: ${esc(s.label)}">${marks(s.k,s.box)}</div><div class="info"><div class="num">${s.k}</div>`
    +`<div><div class="t">${esc(engraved)}</div>${s.code?`<div class="m"><b>Part</b> ${esc(s.label)}</div>`:''}<div class="m"><b>${unit}</b> ${s.sheet} &nbsp;·&nbsp; <b>${esc(fmtLen(s.thickness))}</b> thick</div>`
    +`<div class="m"><b>Goes onto</b> ${esc(s.onto)}</div></div><div>${s.svg}<div class="cap">cut outline · ${esc(fmtLen(s.w))} × ${esc(fmtLen(s.h))}</div></div></div></div>`;
}

export function guideHtml(){
  const shots=pictures(), steps=stepsOf(shots), n=steps.length, P=ST.plan, pages=Math.ceil(n/PER_PAGE),
    title=state.project||P.params.model_name||'Lamina', tech=ST.mode?.label||ST.mode?.title||ST.mode?.name||'', unit=state.printed?'plate':'sheet';
  const sw=(fill,dash)=>`<svg width="26" height="14"><rect x="1" y="1" width="24" height="12" fill="${fill}" stroke="#111" stroke-width="1.5" stroke-dasharray="${dash}"/></svg>`;
  const head=`<div class="head"><div><h1>Assembly guide: ${esc(title)}</h1><div class="sub">${esc(tech)} · ${n} parts · ${P.sheets} ${unit}(s)</div>`
    +`<div class="facts"><b>Project</b><span>${esc(title)}</span><b>Technique</b><span>${esc(tech)}</span><b>Parts</b><span>${n} (steps 1 to ${n})</span><b>${state.printed?'Plates':'Sheets'}</b><span>${P.sheets}</span></div></div>`
    +`<div class="how"><b>How to read this</b><ol><li>Build in step order, 1 to ${n}.</li><li>The picture shows the model as built so far: grey is done, the framed part goes in now.</li><li>Find the part by its engraving; the small drawing is its outline.</li></ol>`
    +`<div class="leg"><span>${sw('#d2d2d2','0')} already built (grey, edge lines)</span><span><svg width="26" height="14"><rect x="1" y="1" width="24" height="12" fill="#b58f4e" stroke="${BLUE}" stroke-width="2.5" stroke-dasharray="5 2"/></svg> added in this step (dashed frame, numbered arrow)</span><span><svg width="26" height="14"><defs><pattern id="hid" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill="${BLUE}"/></pattern></defs><rect x="1" y="1" width="24" height="12" fill="#d2d2d2" stroke="#111" stroke-width="1.5"/><rect x="1" y="1" width="24" height="12" fill="url(#hid)"/></svg> its part hidden behind built ones (stripes)</span></div></div></div>`;
  const body=Array.from({length:pages},(_,p)=>`<div class="page">${p?'':head}<div class="grid">${steps.slice(p*PER_PAGE,(p+1)*PER_PAGE).map(card).join('')}</div>`
    +`<div class="foot"><span>Lamina · assembly guide · ${esc(title)}</span><span>page ${p+1} / ${pages}</span></div></div>`).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Assembly guide: ${esc(title)}</title><style>${CSS}</style></head><body>`
    +`<div class="bar"><button onclick="print()">Print</button><a id="save" download="assembly-guide.html">Save this guide as HTML</a><span>${n} steps · ${pages} A4 page(s)</span></div>${body}`
    +`<script>document.getElementById('save').href=location.href</script></body></html>`;
}

// The row on the Export tab: a tab opened at the click (a pop-up blocker allows nothing later), filled when the pictures are done
export async function openGuide(el){
  if(!ST.plan?.slices?.length)return status('nothing to build yet');
  const tab=window.open('','_blank'); if(!tab)return status('the browser stopped the new tab: allow pop-ups for this page');
  const txt=el.textContent; el.textContent='building the guide…'; await new Promise(r=>setTimeout(r,30));   // the text shows before the pictures block the page
  while(ST.partial)await new Promise(r=>setTimeout(r,200));   // the 3D view has a slice's parts before its plan: the pictures wait for it
  try{const html=guideHtml(); tab.location.href=URL.createObjectURL(new Blob([html],{type:'text/html'})); ST.countUse?.('export','guide')}
  catch(e){tab.close(); status('could not build the guide: '+e.message)}
  finally{el.textContent=txt}
}
