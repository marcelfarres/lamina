import {state, ST} from './state.js';
import {$, CLIENT, status} from './util.js';
import {deselect} from './edit3d.js';
import {applyUnit} from './units.js';
import {memo, setMode, sizeToModel, schedule} from './form.js';
import {slice} from './slice.js';

// ---------------------------------------------------------------- project save / open
// everything needed to come back: technique, every parameter, per-technique memory, units, presets in use, the
// model itself. One definition of the data model, used by the library's save, by the export zips (web/app.py) and by a
// bug report — which is the only caller that ever leaves the model out, and only when its box is unticked.
export async function projectObj(withModel=true){
  const proj={version:ST.PROJECT_VERSION,name:state.project||'',rev:state.rev||'1.0',mode:ST.mode.name,unit:ST.unit,state,memo,example:ST.job&&!ST.job.startsWith('ex_')?'':ST.example};
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
// a project's name and revision as text, the one way the library lists them and a project opens under them: a number
// or an object as name opens under the name its card shows, not as a second project on the next save. A file from
// before `name` existed has it in its settings only
export const nameOf=p=>String(p.name||p.state?.project||p.model?.name||p.example||'model'), revOf=p=>String(p.rev||'1.0');
export const projName=proj=>`${nameOf(proj)}_v${proj.rev}.lamina.json`;
// a project from its text: a file picked, or one the library holds (its `preview` and `saved` are the library's, not read here)
// Whatever was in hand stops being this tab's revision here: only openRevision() names one again, after this returns.
// Left in place, a file from disk named like the revision opened before was saved onto it without a question
export async function openProjectText(text,label){
  ST.saved=null; const s=JSON.parse(text); Object.assign(memo,s.memo||{}); setMode(s.mode||'interlocked',false);
  for(const k of ['light','lights','room','light_video'])delete state[k];   // the lights and the room are the file's, or none
  Object.assign(state,s.state||{});
  if((s.version||0)<4&&(state.size||[]).some(Boolean))state.size=sizeToModel(state.size);   // before 0.3.2 size was along the view's axes
  state.project=nameOf(s); state.rev=revOf(s); syncProject();
  ST.job=null; ST.pendingFile=null; ST.srcFile=null; ST.fitted=false; deselect(); $('#file').value='';   // as an example does: the upload box lets go
  if(s.model?.b64){const bin=atob(s.model.b64),u8=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u8[i]=bin.charCodeAt(i);ST.pendingFile=new File([u8],s.model.name)}
  else if(s.example)ST.example=s.example;
  else if(s.missing_model)status(`this project was saved without its model — the settings are here, upload ${s.missing_model} again`,'err');
  ST.fresh='opened project '+label; applyUnit(s.unit||state.units); slice();
}
export function syncProject(){$('#pname').value=state.project||'';$('#prev').textContent=state.rev||'1.0'}
// `taken`: the project's revisions in the library, so a bump from an old one lands on a free number, not onto a newer one
export function bump(major,taken=[]){state.rev=nextFree(taken,state.rev||'1.0',major);syncProject();schedule()}
// minor: the lowest a.n with n > b that is not taken; major: the lowest m.0 with m > a that is not taken
export const nextFree=(taken,cur,major)=>{const [a,b]=String(cur).split('.').map(x=>+x||0),has=new Set(taken);let n=major?a+1:b+1;
  while(has.has(major?`${n}.0`:`${a}.${n}`))n++;return major?`${n}.0`:`${a}.${n}`};

