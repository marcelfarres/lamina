import {state, ST} from './state.js';
import {$, CLIENT, status} from './util.js';
import {deselect} from './edit3d.js';
import {applyUnit} from './units.js';
import {memo, setMode, sizeToModel, schedule} from './form.js';
import {slice} from './slice.js';

// ---------------------------------------------------------------- project save / open
// everything needed to come back: technique, every parameter, per-technique memory, units, presets in use, the
// model itself. One definition of the data model, used by save project, by the export zips (web/app.py) and by a
// bug report — which is the only caller that ever leaves the model out, and only when its box is unticked.
export async function projectObj(withModel=true){
  const proj={version:ST.PROJECT_VERSION,name:state.project||'',rev:state.rev||'1.0',mode:ST.mode.name,unit:ST.unit,state,memo,example:ST.job&&!ST.job.startsWith('ex_')?'':$('#example').value};
  // the uploaded model travels inside the project file — when the server still has it. A job swept by the TTL, a
  // restarted server or a slice still in flight answers with nothing, and a project file without its model is far
  // better than a save that dies half way: whoever opens it is told which model to bring.
  // The model's own bytes are read here, not asked of the slicer: in the browser version one worker does all the
  // Python, so a slice that hangs held the report's request behind it and "gathering the report…" never ended
  // (reported) — and a hang is exactly when a report is written. A model still on its way in (its first slice not
  // back yet) is `pendingFile`; one already sliced is `srcFile`. Neither (a job left from before a reload): ask.
  const f=ST.pendingFile||(ST.job&&!ST.job.startsWith('ex_')?ST.srcFile:null);
  if(withModel&&f){
    const u8=new Uint8Array(await f.arrayBuffer());let bin='';for(let i=0;i<u8.length;i+=0x8000)bin+=String.fromCharCode(...u8.subarray(i,i+0x8000));
    proj.model={name:f.name,b64:btoa(bin)};
  }else if(withModel&&ST.job&&!ST.job.startsWith('ex_')){
    const r=await fetch(`api/job/${CLIENT}/${ST.job}/source`), src=r.ok?await r.json():null;
    if(src?.b64)proj.model={name:src.name,b64:src.b64}; else proj.missing_model=modelName();
  }
  return proj;
}
const modelName=()=>$('#file').files[0]?.name||ST.pendingFile?.name||'the uploaded model';
export async function saveProject(){
  const proj=await projectObj();
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(proj)],{type:'application/json'}));a.download=projName(proj);a.click();
}
export const projName=proj=>`${proj.name||proj.model?.name||proj.example||'model'}_v${proj.rev}.lamina.json`;
export async function openProject(f){
  const s=JSON.parse(await f.text()); Object.assign(memo,s.memo||{}); setMode(s.mode||'interlocked',false); Object.assign(state,s.state||{}); ST.unit=s.unit||state.units||'mm';
  if((s.version||0)<4&&(state.size||[]).some(Boolean))state.size=sizeToModel(state.size);   // before 0.3.2 size was along the view's axes
  state.project=s.name||state.project||''; state.rev=s.rev||state.rev||'1.0'; syncProject();
  ST.job=null; ST.pendingFile=null; ST.srcFile=null; ST.fitted=false; deselect(); $('#file').value='';   // as an example does: the upload box lets go
  if(s.model?.b64){const bin=atob(s.model.b64),u8=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u8[i]=bin.charCodeAt(i);ST.pendingFile=new File([u8],s.model.name)}
  else if(s.example)$('#example').value=s.example;
  else if(s.missing_model)status(`this project was saved without its model — the settings are here, upload ${s.missing_model} again`,'err');
  ST.fresh='opened project '+f.name; applyUnit(); slice();
}
export function syncProject(){$('#pname').value=state.project||'';$('#prev').textContent=state.rev||'1.0'}
export function bump(major){const [a,b]=(state.rev||'1.0').split('.').map(Number);state.rev=major?`${a+1}.0`:`${a}.${(b||0)+1}`;syncProject();schedule()}

