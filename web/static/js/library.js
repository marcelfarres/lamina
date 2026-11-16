// ---------------------------------------------------------------- the library's rules
// What save, open, bump and delete mean for the projects kept in the library, and when the page has unsaved changes.
// No page here (librarypage.js draws it): every rule is reachable through window.__t.lib.
import {state, ST} from './state.js';
import {browserStore, idxGet, idxSet} from './store.js';
import {projectObj, openProjectText, syncProject} from './project.js';
import {snapshot} from './scene.js';
import {schedule} from './form.js';

const EXT='.lamina.json';
// Windows refuses these in a file name; the name inside the file is the project's, the file name is only where it lives
const legal=s=>String(s).replace(/[\\/:*?"<>|\x00-\x1f]/g,'_');
export const fileName=(name,rev)=>`${legal(name)}_v${legal(rev)}${EXT}`;
const stemOf=file=>file.slice(0,file.lastIndexOf('_v'));
const num=r=>String(r).split('.').map(x=>+x||0);
const byRev=(a,b)=>{const [x,y]=num(a.rev),[u,v]=num(b.rev);return u-x||v-y};   // newest first
export const nextFree=(taken,cur,major)=>{const [a,b]=num(cur),has=new Set(taken);let n=major?a+1:b+1;
  while(has.has(major?`${n}.0`:`${a}.${n}`))n++;return major?`${n}.0`:`${a}.${n}`};

let store=browserStore(), rows=[], last=[], persisted=false;   // rows: the index entries of the last listing; last: them grouped
export function useStore(s){store=s;rows=[];last=[]}

// one index entry per revision file: what a card needs, without reading the file again
async function readEntry(f){
  const at={file:f.file,size:f.size,mtime:f.mtime,saved:new Date(f.mtime).toISOString(),preview:''};
  try{const p=JSON.parse(await store.read(f.file));
    return {...at,name:p.name||p.model?.name||p.example||'model',rev:p.rev||'1.0',saved:p.saved||at.saved,preview:p.preview||''}}
  catch(e){return {...at,name:f.file,rev:'',bad:true}}   // listed by its file name; Lamina never writes onto it
}
const group=()=>{const by=new Map();
  for(const r of rows){if(!by.has(r.name))by.set(r.name,[]);by.get(r.name).push({rev:r.rev,file:r.file,saved:r.saved,preview:r.preview,bad:!!r.bad})}
  const newest=p=>p.revs.reduce((m,r)=>r.saved>m?r.saved:m,'');
  return last=[...by].map(([name,revs])=>({name,revs:revs.sort(byRev)})).sort((a,b)=>newest(b).localeCompare(newest(a)))};
export async function entries(){
  const idx=new Map((await idxGet(store.kind)).map(e=>[e.file,e])), files=await store.list();
  let changed=files.length!==idx.size;
  // Task 7 puts its trust rule here: an entry is used while its file's size and mtime are unchanged
  rows=[];for(const f of files){let e=idx.get(f.file);if(!e){e=await readEntry(f);changed=true}rows.push(e)}
  if(changed)await idxSet(store.kind,rows);
  return group();
}
export const revsOf=name=>last.find(p=>p.name===name)?.revs.map(r=>r.rev)||[];

// the index is read again before each change, not taken from `rows`: a listing made before useStore() is not this store's
async function reindex(file,entry){
  const i=(await idxGet(store.kind)).filter(e=>e.file!==file);if(entry)i.push(entry);await idxSet(store.kind,i);
  rows=rows.filter(e=>e.file!==file);if(entry)rows.push(entry);group();
}

// what this tab opened or last saved, kept across a refresh (main.js restores it with the session)
export function setSaved(v){ST.saved=v;try{sessionStorage.lamina_saved=JSON.stringify(v)}catch(e){}changed()}
const listeners=[];
export const onChange=fn=>listeners.push(fn), changed=()=>listeners.forEach(fn=>fn());
// the project as saved, without the parts the library adds: what "unsaved changes" compares. The model is the
// example's name, or the uploaded file's name and size (whichever File the page holds, as projectObj reads it)
const held=()=>{const up=!!ST.job&&!ST.job.startsWith('ex_');return {up,f:ST.pendingFile||(up?ST.srcFile:null)}};
// ponytail: after a refresh an upload has no File, only its job, so it reads as unsaved until saved again (the safe side)
// A state resumed after a refresh holds the same values in another order, so keys are sorted; and material_kind
// comes back as the one slice() derived from the material for the server, where the form holds '': left out
const sorted=(k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a<b?-1:a>b?1:0)):v;
export const snap=()=>{const {up,f}=held();
  return JSON.stringify({m:ST.mode.name,u:ST.unit,s:{...state,material_kind:undefined},model:f?[f.name,f.size]:up?ST.job:ST.example},sorted)};
export const unsaved=()=>snap()!==ST.saved?.snap;   // nothing saved or opened (an example, a fresh upload): unsaved

export async function saveCurrent(ask){
  await entries();   // the files as they are now, not as the page last listed them
  if(!state.project){const {up,f}=held();state.project=(f?f.name.replace(/\.[^.]*$/,''):up?'':ST.example)||'model';syncProject();schedule()}
  const name=state.project;let rev=state.rev||'1.0';
  // a project keeps the file-name stem it already has; a new one whose stem belongs to another name (a/b and a_b) takes ~2, ~3…
  const own=rows.find(r=>r.name===name&&!r.bad);let stem=own&&stemOf(own.file);
  if(!stem){const other=new Set(rows.map(r=>stemOf(r.file))),base=legal(name);stem=base;for(let k=2;other.has(stem);k++)stem=`${base}~${k}`}
  const at=r=>`${stem}_v${legal(r)}${EXT}`;let file=at(rev);
  // the revisions under this stem by their file names, the unreadable ones too: `next` never lands on a file Lamina cannot read
  const taken=rows.filter(r=>stemOf(r.file)===stem).map(r=>r.file.slice(stem.length+2,-EXT.length));
  if(rows.find(r=>r.file===file)?.bad)throw new Error(`${file} in ${store.label} cannot be read, and Lamina does not write onto it: bump the revision, or use export to keep a copy of this project.`);
  // only the revision this tab opened or last saved is overwritten without asking
  if(!(ST.saved?.name===name&&ST.saved?.rev===rev)&&rows.some(r=>r.file===file)){
    const next=nextFree(taken,rev,false), c=await ask({name,rev,next});
    if(c!=='replace'&&c!=='keep')return null;
    if(c==='keep'){rev=state.rev=next;file=at(rev);syncProject();schedule()}
  }
  const now=snap();   // before any await: a change made while the save runs is not part of what was saved
  const proj=await projectObj(), preview=snapshot();if(preview)proj.preview=preview;proj.saved=new Date().toISOString();
  // so a full disk does not evict the library: asked once, never waited for, its answer changes nothing here
  if(store.kind==='browser'&&!persisted){persisted=true;Promise.resolve().then(()=>navigator.storage?.persist?.()).catch(()=>{})}
  let w;
  try{w=await store.write(file,JSON.stringify(proj))}
  catch(e){throw new Error(`${name} v${rev} could not be saved in ${store.label} (${e.message||e.name}). Nothing in the library changed; use export to keep a copy of this project.`)}
  await reindex(file,{file,size:w.size,mtime:w.mtime,name,rev,saved:proj.saved,preview:proj.preview||''});
  setSaved({name,rev,snap:now});
  return {file};
}

export async function openRevision(file){
  const text=await store.read(file), p=JSON.parse(text);
  await openProjectText(text,file);
  setSaved({name:p.name||'',rev:p.rev||'1.0',snap:snap()});
}

export async function removeRevision(file){
  const e=rows.find(r=>r.file===file);
  await store.remove(file);await reindex(file,null);
  if(e&&ST.saved?.name===e.name&&ST.saved?.rev===e.rev)setSaved(null);   // the revision in hand is no longer saved
}
export async function removeProject(name){
  for(const p of await entries())if(p.name===name)for(const r of p.revs)await removeRevision(r.file);
}
