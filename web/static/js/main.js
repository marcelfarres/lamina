import * as THREE from 'three';
import {state, ST} from './state.js';
import {MACHINES, MATERIALS} from './catalog.js';
import {$, status, lsSet, ls, $$, CLIENT} from './util.js';
// edit3d first: it and scene.js import each other, and the one entered second runs first; edit3d's pointer handlers attach to the renderer scene.js makes, so scene.js must run before it
import {deselect, pivot3, rnd, hit, highlight, pick} from './edit3d.js';
import {fmtLen, DU, applyUnit} from './units.js';
import {step, undos, redos} from './history.js';
import {showNews, whatsNew, phoneNotice, news} from './news.js';
import {matOf, matThicks, machineOf, kind, applyMachine, shs, sameSheet, userMachines, syncPresetSelects, userMaterials, dens, fam, renderPresets, PKEYS} from './presets.js';
import {setMode, renderFields, schedule, resetTab, showTab, memo, MODEL_BOUND, allParams, sizeAxes} from './form.js';
import {slice, oops, popup, LOCAL_DOC} from './slice.js';
import {applyLook, controls, banner, parts, guides, gizmo, axes, rings, camera, renderer, applyFold, scene, ghost, ghostUrl, snapshot} from './scene.js';
import {renderWeight, renderDownloads, applyFix} from './results.js';
import {bump, projectObj, projName} from './project.js';
import * as lib from './library.js';
import {initLibraryPage} from './librarypage.js';

// ---------------------------------------------------------------- init
async function init(){
  ST.MODES=await (await fetch('api/modes')).json(); ST.PROJECT_VERSION=(await (await fetch('api/project')).json()).version; const ex=await (await fetch('api/examples')).json();
  const PRESETS=await fetch('api/presets').then(r=>r.ok?r.json():{}).catch(()=>({}));
  $('#example').innerHTML=ex.map(e=>`<option>${e}</option>`).join(''); $('#example').value=ST.example=ex.includes('blob')?'blob':ex[0];
  $('#modes').innerHTML=ST.MODES.map(m=>`<button data-m="${m.name}">${m.title}</button>`).join('');
  $('#modes').onclick=e=>{if(e.target.dataset.m){deselect();setMode(e.target.dataset.m);ST.countUse('technique',e.target.dataset.m);slice()}};
  $('#material').onchange=e=>{const n=e.target.value,m=matOf(n);state.material=n;
    if(m){const ts=matThicks(n);if(!ts.some(t=>Math.abs(t[0]-state.thickness)<1e-6))state.thickness=ts[Math.floor(ts.length/2)][0];   // a stock thickness of the new material
      if(!machineOf(state.machine)?.cuts.includes(kind(n)))applyMachine(m.machine);                                                       // a machine that cuts it
      if(!shs().some(([,s])=>sameSheet(s,state.sheet)))state.sheet=[...shs()[0][1]];                                                       // a sheet it comes in
      $('#look').value=m.look;applyLook()
      // a printed material is the job itself, not a model of it: its sheets are plates of the bed, printed full size
      state.printed=m.family==='print';if(state.printed){$('#pr_scale').value=1;$('#pr_size').value='';$('#pr_size').dataset.mm=''}}
    renderFields();schedule()};
  $('#machine').onchange=e=>{applyMachine(e.target.value);renderFields();schedule()};
  // a machine of your own: the compensation and sheet as they stand, cutting what the machine it was made from cuts
  $('#kadd').onclick=()=>{const b=machineOf(state.machine),n=prompt('machine name (make and model)',userMachines()[state.machine]?state.machine:'');if(!n)return;
    if(MACHINES[n])return status('that name is a built-in machine — pick another','err');
    const u=userMachines();u[n]={name:n,base:u[state.machine]?.base||state.machine,kerf:state.kerf,slot:state.slot_offset,relief:state.relief,tool:state.tool_d,cuts:b.cuts,beds:[[`${n} bed · ${fmtLen(state.sheet[0])} × ${fmtLen(state.sheet[1])}`,[...state.sheet]]]};
    lsSet('slicer_machines',u);state.machine=n;syncPresetSelects()};
  $('#kdel').onclick=()=>{const u=userMachines();if(!u[state.machine])return status('built-in machines cannot be deleted');delete u[state.machine];lsSet('slicer_machines',u);applyMachine(matOf(state.material).machine);renderFields();schedule()};
  // a material of your own: the one in use, kept under a name with the thickness and density as they stand — its sheets,
  // 3D look and machines are the ones of the built-in it was made from
  $('#matadd').onclick=()=>{const cur=state.material,n=prompt('material name (what it is, where it comes from)',userMaterials()[cur]?cur:'');if(!n)return;
    if(MATERIALS[n])return status('that name is a built-in material — pick another','err');
    const b=matOf(cur),u=userMaterials(),d=dens();
    u[n]={base:kind(cur),t:[...(u[n]?.t||[]),[state.thickness]],family:b.family,look:b.look,machine:b.machine,density:d};
    lsSet('slicer_materials',u);state.material=n;state.density={...state.density,[n]:d};renderFields();renderWeight();schedule()};
  $('#matdel').onclick=()=>{const u=userMaterials(),n=state.material;if(!u[n])return status('built-in materials cannot be deleted');
    state.material=u[n].base;delete u[n];lsSet('slicer_materials',u);renderFields();renderWeight();schedule()};
  // typed in the unit on show, stored in g/cm³ for this material — and with the material itself when it is one of yours
  $('#density').oninput=e=>{const v=+e.target.value;if(!(v>0))return;const d=+(v/DU()).toPrecision(12),n=state.material,u=userMaterials();
    state.density={...state.density,[n]:d};if(u[n]){u[n].density=d;lsSet('slicer_materials',u)}renderWeight()};
  $('#thicklist').onchange=e=>{if(e.target.value){state.thickness=+e.target.value;renderFields();schedule()}};
  $('#sheetpreset').onchange=e=>{const s=shs()[+e.target.value];if(s){state.sheet=[...s[1]];renderFields();schedule()}};
  $('#madd').onclick=()=>{const m=state.material||'cardboard',u=ls('slicer_thick',{});u[m]=[...new Set([...(u[m]||[]),state.thickness])];lsSet('slicer_thick',u);syncPresetSelects()};
  $('#mdel').onclick=()=>{const m=state.material||'cardboard',t=+$('#thicklist').value,u=ls('slicer_thick',{});if(u[m]&&u[m].includes(t)){u[m]=u[m].filter(x=>x!==t);lsSet('slicer_thick',u);syncPresetSelects()}else status('built-in thicknesses cannot be deleted')};
  $$('button.reset').forEach(b=>b.onclick=()=>resetTab(b.dataset.reset));
  $('#sadd').onclick=()=>{const n=prompt(`sheet preset name for ${fmtLen(state.sheet[0])} × ${fmtLen(state.sheet[1])}`);if(n){lsSet('slicer_sheets',[...ls('slicer_sheets',[]),[n,[...state.sheet],fam()]]);syncPresetSelects()}};
  $('#sdel').onclick=()=>{const idx=+$('#sheetpreset').value,u=ls('slicer_sheets',[]),mine=u.filter(s=>!s[2]||s[2]===fam()),s=mine[idx-(shs().length-mine.length)];   // user sizes come after the built-ins
    if(s){u.splice(u.indexOf(s),1);lsSet('slicer_sheets',u);syncPresetSelects()}else status('built-in sizes cannot be deleted')};
  renderPresets();
  $('#presets').onchange=e=>{const ps=ls('slicer_presets',{})[e.target.value];if(ps){Object.assign(state,structuredClone(ps));ST.unit=state.units||ST.unit;applyUnit();renderPresets(e.target.value);schedule()}};
  $('#psave').onclick=()=>{const n=prompt('preset name',$('#presets').value||'');if(!n)return;const ps=ls('slicer_presets',{});ps[n]=Object.fromEntries(PKEYS().map(k=>[k,state[k]]));lsSet('slicer_presets',ps);renderPresets(n)};
  $('#pdel').onclick=()=>{const n=$('#presets').value;if(!n)return;const ps=ls('slicer_presets',{});delete ps[n];lsSet('slicer_presets',ps);renderPresets()};
  $('#origsize').onclick=()=>{state.scale=1;state.size=[0,0,0];state.rotate=[0,0,0];state.up_axis='z';renderFields();ST.fitted=false;slice()};
  $('#undo').onclick=()=>step(undos,redos); $('#redo').onclick=()=>step(redos,undos);
  $('#helpbtn').onclick=()=>$('#helpdlg').showModal(); $('#help_go').onclick=()=>$('#helpdlg').close();
  $('#newsbtn').onclick=()=>showNews(Infinity); $('#news_go').onclick=()=>$('#newsdlg').close();
  whatsNew();
  $('#oops_go').onclick=()=>oops.close('go'); $('#oops_no').onclick=()=>oops.close('');
  phoneNotice();
  $('#clear').onclick=async()=>{if(!confirm('Delete everything this tab has sliced — uploaded models, cut files and the session? Presets are kept.'))return;await fetch(`api/session?client=${CLIENT}`,{method:'DELETE'});location.reload()};
  $('#pname').oninput=e=>{state.project=e.target.value;schedule();lib.changed()};
  // a bump straight after a refresh lists the library first, so it too lands on a free number
  $('#pminor').onclick=async()=>{await lib.listed();bump(false,lib.revsOf(state.project))}; $('#pmajor').onclick=async()=>{await lib.listed();bump(true,lib.revsOf(state.project))};
  $('#unit').onchange=e=>{ST.unit={mm:'mm',cm:'cm',in:'in'}[e.target.value]||'mm';applyUnit()};   // one of the three, never the box's own text
  $('#x_labels').onchange=()=>{if(ST.job)renderDownloads()}; $('#x_grouped').onchange=()=>{if(ST.job)renderDownloads()};
  $$('nav button').forEach(b=>b.onclick=()=>showTab(b.dataset.t));
  // A new model keeps none of the last one's geometry. These parameters are in its millimetres or under its part
  // labels — axis lines, curve points, dowels, per-slice edits — so they are cleared from the form *and* from the
  // per-technique memory. Without the second half, opening a model that slices stacked and then switching to radial
  // restored the fan of axes placed on some earlier model, instead of the single centred axis radial starts from.
  const newModel=()=>{ST.job=null;ST.srcFile=null;ST.fitted=false;deselect();
    for(const m of Object.values(memo))for(const k of MODEL_BOUND)delete m[k];
    for(const p of allParams())if(MODEL_BOUND.includes(p.name))state[p.name]=structuredClone(p.default);
    for(const k of MODEL_BOUND)if(!allParams().some(p=>p.name===k))delete state[k];   // another technique's: gone entirely
    renderFields()};
  // `model/example` vs `model/upload` says whether people bring real work or only try the samples — the file
  // itself never leaves the browser and its name is never sent, only which of the two it was.
  // a bundled example opens on its preset (examples/presets.json): its technique, standing the right way up, sliced
  // clean — the model preparation is reset first so nothing carries over from the previous shape. A preset that names a
  // material or a machine picks it as the selects would (its look, its compensation, its bed as the sheet); the caller
  // slices straight after, so the select's own delayed slice is dropped. Every other technique starts from its defaults
  // too: the memory kept the last example's preset, so the horse switched to stacked after the statue came back with
  // the statue's 2 mm square dowels on axis y, and its tab spacers were all "thinner than 2 mm" (reported).
  // The machine's kerf, slot fit and corners are not the model's: they stay as they were (the machine's, or what a fit
  // test gave you) while the machine does, and become the new machine's when an example or its material picks another.
  // Reset with everything else, the machine kept its name and lost its values: co2 sliced at slot offset 0 (reported)
  const applyPreset=()=>{const pr=PRESETS[ST.example];if(!pr)return;
    const FIT=[...new Set(ST.MODES.flatMap(m=>m.common).filter(p=>p.group==='fit').map(p=>p.name))];
    const was=state.machine, fit=Object.fromEntries(FIT.filter(k=>!(k in pr.params)).map(k=>[k,structuredClone(state[k])]));   // what the preset names, it sets
    setMode(pr.mode,false);for(const k of Object.keys(memo))delete memo[k];Object.assign(state,{rotate:[0,0,0],size:[0,0,0],scale:1,round:0,thicken:0,shrinkwrap:0,smooth:0,hollow:0},structuredClone(pr.params));   // the gap between slices is the technique's own default (setMode): a plaque's is 3 mm, and a forced 0 made its slices touch
    if(pr.params.material)$('#material').onchange({target:{value:pr.params.material}});
    const m=state.material||'cardboard', next=pr.params.machine||(machineOf(was)?.cuts.includes(kind(m))?was:matOf(m).machine);
    if(next===was)Object.assign(state,fit); else applyMachine(next);
    clearTimeout(ST.timer);ST.timer=null;renderFields()};
  // the file box lets go of the upload too: left holding it, choosing that same file again fires no change and loads nothing
  // every way into an example comes here (the dropdown, the library page); the dropdown follows it
  // its preset applied, an example is what unsaved changes count from (taken before the slice: nothing changes the form
  // while it runs, and an edit made meanwhile then counts as a change)
  const openExample=name=>{$('#example').value=ST.example=name;ST.pendingFile=null;$('#file').value='';newModel();applyPreset();lib.baseline();ST.countUse('model','example');ST.fresh='loaded example '+name;slice()};
  $('#example').onchange=()=>openExample($('#example').value);
  window.__t.openExample=openExample;   // window.__t is built below while init() awaits its first fetch
  initLibraryPage({openExample,examples:ex});
  // A big mesh in the browser build is slow but not refused — the ceiling is this tab's memory, and it is the
  // reporter's machine that knows better than a fixed number. So: say what it will cost, then do as they say.
  const BIG=50e6;   // ~1 M triangles: the point where a slice in Pyodide goes from a wait to a very long wait
  $('#file').onchange=e=>{const f=e.target.files[0]||null; ST.pendingFile=f; newModel(); if(!f)return; lib.setSaved(null);
    const go=()=>{ST.countUse('model','upload');ST.fresh=`uploaded ${f.name} (${(f.size/1e6).toFixed(1)} MB)`;slice()};
    if(document.documentElement.dataset.static&&f.size>BIG)
      popup(`${f.name} is ${(f.size/1e6).toFixed(0)} MB`,'',
        `<p>This published version slices inside your browser tab, and a model this size can take many minutes there — or run the tab out of memory.</p>
         <p>Running Lamina on your own computer has no limit and is far faster: <a href="${LOCAL_DOC}" target="_blank" rel="noopener">how to install it</a> (a double-click installer, or one command).</p>`,
        'Slice it here anyway',ok=>{if(ok)go();else{ST.pendingFile=null;e.target.value=''}});
    else go()};
  // the session belongs to this tab (mode, every parameter, the model's job, per-technique memory), so a refresh
  // resumes it instead of starting over; another tab is another session and sees nothing of this one
  const sess=await fetch(`api/session?client=${CLIENT}`).then(r=>r.ok?r.json():{}).catch(()=>({}));
  if(sess.mode){Object.assign(memo,sess.memo||{});setMode(sess.mode,false);Object.assign(state,sess.params||{});ST.unit=state.units||ST.unit;
    if(sess.example)$('#example').value=ST.example=sess.example; ST.job=sess.alive?sess.job:null;
    if(!sess.alive&&sess.job)status('the uploaded model of the last session is gone — upload it again or pick an example','err');
    // the library revision the session came from: unreadable, it stays null and the page shows unsaved changes (the safe side)
    try{ST.saved=JSON.parse(sessionStorage.lamina_saved||'null')}catch(e){ST.saved=null}}
  else{setMode(location.hash.slice(1)||'interlocked',false);applyMachine(matOf(state.material).machine);applyPreset()}   // a fresh start gets the machine's compensation and the example's preset (the #technique in the URL is the app's own mirror of its state, not a request)
  ST.fresh=sess.mode?'page reloaded, last session resumed':'page opened on example '+ST.example; applyUnit();
  if(!sess.mode)lib.baseline();   // a fresh start is an example as it opened; it also replaces a mirror left by a cleared session
  slice(); lib.listed();
}
init();

// Counting, in two clearly separate halves. Only the published build carries <meta name="count-url">; a
// self-hosted or Docker copy has none, so neither half exists there and nothing can ever be sent.
//
//  1. A plain pageview, no opt-in. /app/ is a published web page like any other and this says only that it was
//     opened — the same fact the landing page records about itself. Treating the two differently was inconsistent.
//  2. What someone *does* in it — technique, where the model came from, which formats they export — while the box
//     is ticked, which it is until they untick it. Unticking stops it at once and is remembered (the loaded script
//     stays, but nothing calls it again).
const COUNT_URL=document.querySelector('meta[name="count-url"]')?.content;
if(COUNT_URL){
  const s=document.createElement('script');
  s.async=true;s.src='//gc.zgo.at/count.js';s.dataset.goatcounter=COUNT_URL;
  document.head.appendChild(s);                                    // pageview on load, nothing else
  const box=$('#usage_optin'); $('#optin').style.display='';
  box.checked=ls('usage_optin',true);
  box.onchange=()=>lsSet('usage_optin',box.checked);
  ST.countUse=(kind,name)=>{if(box.checked&&window.goatcounter?.count)
    goatcounter.count({path:kind+'/'+name,title:kind+': '+name,event:true})};
}

// ---------------------------------------------------------------- bug reports (static/feedback.js draws the dialog)
// What a report carries from here: the checks and the last steps in words — small enough to read in an issue — and
// the project file, which is the whole data model and reopens the job exactly as it was, plus every step since the
// model loaded (`trail`). The model is inside it only while the reporter leaves the box ticked.
function reportSummary(version){
  const where=`lamina         ${version}, ${document.documentElement.dataset.static?'in the browser (Pyodide)':'against a local server'}`;
  // a hang is reported while it hangs: the result below is then the slice before it, not this one
  const now=ST.busy?[`now            still slicing after ${Math.round((Date.now()-ST.busySince)/1000)} s: ${$('#busy_txt').textContent}`]:[];
  const steps=['',`steps since the model loaded${ST.trail.length>15?` (last 15 of ${ST.trail.length}, all in the attached file)`:''}`,
    ...ST.trail.slice(-15).map(([t,s])=>`${t} s  ${s}`)];
  if(!ST.plan)return [where,...now,'nothing sliced yet',...steps].join('\n');
  const p=ST.plan.params, c=ST.plan.counts, n=v=>+(+v).toPrecision(4);
  const msgs=[...ST.plan.notes.map(x=>'note: '+x),...ST.plan.errors.map(x=>'error: '+x),
    ...ST.plan.dropped.flatMap(s=>s.errors.map(e=>`error ${s.label}: ${e}`)),
    ...ST.plan.slices.flatMap(s=>[...s.errors.map(e=>`error ${s.label}: ${e}`),...s.warnings.map(w=>`warning ${s.label}: ${w}`)])];
  return [`technique      ${ST.plan.mode}`,
    `model          ${ST.job?.startsWith('ex_')?'bundled example '+ST.job.slice(3):'uploaded by the reporter'}, ${ST.plan.bbox.map(n).join(' × ')} mm, ${c.faces} faces`,
    `result         ${c.slices} slices, ${c.parts} parts, ${ST.plan.sheets} sheet(s) at ${n(ST.plan.sheet_usage*100)}% used, ${c.errors} errors, ${c.warnings} warnings`,
    `material       ${state.material} ${p.thickness} mm (${dens()} g/cm³) on ${state.machine}, kerf ${p.kerf}, slot offset ${p.slot_offset}, relief ${p.relief}`,   // material and machine are the form's own, not the planner's
    `sheet          ${ST.plan.sheet.map(n).join(' × ')} mm, units ${p.units}`,
    where, ...now, ...steps,
    '', `timing (s)     ${Object.entries(ST.plan.timing).map(([k,v])=>`${k}=${v}`).join(', ')}`,
    '', ...(msgs.length?msgs.slice(0,60):['the checks reported nothing'])].join('\n');
}
window.laminaFeedback?.({bug:async withModel=>{
  const proj={...await projectObj(withModel),trail:ST.trail};   // the report's copy only: a saved project has no trail
  const version=await news().then(v=>v[0]?.v,()=>'unknown');
  const gone=proj.missing_model?`\n(the model could not be attached: ${proj.missing_model} is no longer on the server)`:'';
  return {technique:ST.MODES.find(m=>m.name===ST.plan?.mode)?.title||'Not technique-specific (import, export, UI, install)', summary:reportSummary(version)+gone,
          file:new File([JSON.stringify(proj)],projName(proj),{type:'application/json'})};
 },
 // a machine to ship: what MACHINES holds for one — the compensation as it stands, and its bed when it has exactly one
 machine:async()=>{const x=machineOf(state.machine)||{};
  return {summary:JSON.stringify({name:x.name,base:x.base||state.machine,kerf:state.kerf,slot_offset:state.slot_offset,relief:state.relief,tool_d:state.tool_d,bed:x.beds?.length===1?x.beds[0][1]:state.sheet},null,1)}},
 // a material to ship: what MATERIALS and SHEETS hold for one — the thickness and sheet in use, and the ones added here
 material:async()=>({summary:JSON.stringify({material:state.material,base:kind(state.material),density_g_cm3:dens(),thickness:state.thickness,thicknesses:ls('slicer_thick',{})[state.material]||[],sheet:state.sheet,
  sheets:ls('slicer_sheets',[]).filter(s=>!s[2]||s[2]===fam()).map(([n,s])=>[n,s]),units:state.units},null,1)})});

// test and capture hook (tests/ui, scripts/media/capture.mjs)
window.__t={project:()=>projectObj(false),sizeAxes:()=>sizeAxes(),target:()=>controls.target,banner:()=>banner.visible?banner.userData.text:'',parts:()=>parts.children,guides:()=>guides.children,gizmo:()=>gizmo.children,axes:()=>[...axes.children,...rings.children],camera,canvas:()=>renderer.domElement,state:()=>state,plan:()=>ST.plan,job:()=>ST.job,
  fold:s=>{$('#fold').value=s;applyFold();renderer.render(scene,camera)},
  idle:()=>!ST.timer&&!ST.busy,   // no change waiting out its debounce, no slice running: what a test or a capture waits for
  ghost:()=>ghost.children,ghostUrl:()=>ghostUrl,pivot:()=>pivot3&&rnd(pivot3),
  screen:p=>{const q=new THREE.Vector3(p[0],p[1],p[2]).project(camera),r=renderer.domElement.getBoundingClientRect();
    return [r.left+(q.x+1)/2*r.width,r.top+(1-q.y)/2*r.height]},   // world point → the pixel to click, for drag tests
  hit,
  select:l=>{const m=parts.children.find(c=>c.userData.slice===l);if(m)highlight(m)},deselect,applyFix,
  pickAt:(x,y)=>pick({clientX:x,clientY:y})?.userData.slice,
  hitAt:(x,y)=>{const h=hit({clientX:x,clientY:y});return h?(h.object.userData.gizmo?'gizmo':h.object.userData.slice):null},
  cam:(az,el,dist)=>{const t=controls.target,r=dist||camera.position.distanceTo(t),a=az*Math.PI/180,e=el*Math.PI/180;
    camera.position.set(t.x+r*Math.cos(e)*Math.cos(a),t.y+r*Math.cos(e)*Math.sin(a),t.z+r*Math.sin(e));camera.lookAt(t);controls.update();ST.dirty=true;renderer.render(scene,camera)},
  frame:()=>{ST.dirty=true;renderer.render(scene,camera)},snapshot,lib};
