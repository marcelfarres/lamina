// ---------------------------------------------------------------- the library's rules
// What save, open, bump and delete mean for the projects kept in the library, and when the page has unsaved changes.
// No page here (librarypage.js draws it): every rule is reachable through window.__t.lib.
import {state, ST} from './state.js';
import {browserStore, folderStore, idxGet, idxSet, kvGet, kvSet, kvDel} from './store.js';
import {projectObj, openProjectText, syncProject, nextFree} from './project.js';
import {snapshot} from './scene.js';
import {memo, schedule} from './form.js';
export {nextFree};

const EXT='.lamina.json';
// Windows refuses these in a file name; the name inside the file is the project's, the file name is only where it lives
const legal=s=>String(s).replace(/[\\/:*?"<>|\x00-\x1f]/g,'_');
export const fileName=(name,rev)=>`${legal(name)}_v${legal(rev)}${EXT}`;
const stemOf=file=>file.slice(0,file.lastIndexOf('_v'));
// a folder on Windows or macOS does not tell Lamp_v1.0 from lamp_v1.0, so file names are compared the way it does
const lc=s=>s.toLowerCase();
const num=r=>String(r).split('.').map(x=>+x||0);
const byRev=(a,b)=>{const [x,y]=num(a.rev),[u,v]=num(b.rev);return u-x||v-y};   // newest first

// rows: the index entries of the last listing; last: them grouped; seen: the listing itself (lower-cased file name → its size and mtime)
let store=browserStore(), rows=[], last=[], seen=new Map(), first=null, saving=null, persisted=false;
export function useStore(s){store=s;rows=[];last=[];seen=new Map();first=null}
const here=()=>({kind:store.kind,label:store.label});
const sameStore=()=>ST.saved?.store?.kind===store.kind&&ST.saved.store.label===store.label;

// a file is a project when it is an object with a technique or settings: `{}` or `42` parses, and is not one
function parse(text){const p=JSON.parse(text);
  if(!p||typeof p!=='object'||Array.isArray(p)||!('state' in p||'mode' in p))throw new Error('not a Lamina project');return p}
// one index entry per revision file: what a card needs, without reading the file again
async function readEntry(f){
  const at={file:f.file,size:f.size,mtime:f.mtime,saved:new Date(f.mtime).toISOString(),preview:''};
  try{const p=parse(await store.read(f.file));
    return {...at,name:p.name||p.model?.name||p.example||'model',rev:p.rev||'1.0',saved:p.saved||at.saved,preview:p.preview||''}}
  catch(e){return {...at,name:f.file,rev:'',bad:true}}   // listed by its file name; Lamina never writes onto it or deletes it
}
const group=()=>{const by=new Map();
  for(const r of rows){if(!by.has(r.name))by.set(r.name,[]);by.get(r.name).push({rev:r.rev,file:r.file,saved:r.saved,preview:r.preview,bad:!!r.bad})}
  const newest=p=>p.revs.reduce((m,r)=>r.saved>m?r.saved:m,'');
  return last=[...by].map(([name,revs])=>({name,revs:revs.sort(byRev)})).sort((a,b)=>newest(b).localeCompare(newest(a)))};
export async function entries(){
  const idx=new Map((await idxGet(store.kind)).map(e=>[e.file,e])), files=await store.list();
  seen=new Map(files.map(f=>[lc(f.file),f]));
  let changed=files.length!==idx.size;
  // an entry is trusted while its file's size and mtime are unchanged: a library of big models opens without reading them
  rows=[];for(const f of files){let e=idx.get(f.file);if(e?.size!==f.size||e.mtime!==f.mtime){e=await readEntry(f);changed=true}rows.push(e)}
  if(changed)await idxSet(store.kind,rows);
  return group();
}
export const revsOf=name=>last.find(p=>p.name===name)?.revs.map(r=>r.rev)||[];
// listed once when nothing has listed it yet (a bump straight after a refresh); a store that cannot be listed gives what
// is known, and is listed again on the next call
export const listed=()=>first??=entries().catch(()=>{first=null;return last});

// the cached listing first, then the index, read again before it is changed: a listing made before useStore() is not this store's.
// Ordered so that an index that cannot be written leaves the page's own listing right
async function reindex(file,entry){
  rows=rows.filter(e=>e.file!==file);if(entry)rows.push(entry);group();
  const i=(await idxGet(store.kind)).filter(e=>e.file!==file);if(entry)i.push(entry);await idxSet(store.kind,i);
}

// ST.saved = {name, rev, snap, file, store, mtime}: what this tab opened or last saved (state.js mirrors it in sessionStorage)
export function setSaved(v){ST.saved=v;changed()}
const listeners=[];
export const onChange=fn=>listeners.push(fn), changed=()=>{remember();listeners.forEach(fn=>fn())};

// the model in the snap: the example's name, or the upload's name and size. The File is gone after a refresh and the
// job stays (re-slicing reuses it), so the name and size are kept with the job for this tab
const held=()=>{const up=!!ST.job&&!ST.job.startsWith('ex_');return {up,f:ST.pendingFile||(up?ST.srcFile:null)}};
function remember(){const {up,f}=held();if(up&&f)try{sessionStorage.lamina_model=JSON.stringify({job:ST.job,id:[f.name,f.size]})}catch(e){}}
function modelId(){const {up,f}=held();if(f)return [f.name,f.size];if(!up)return ST.example;
  try{const m=JSON.parse(sessionStorage.lamina_model||'null');if(m?.job===ST.job)return m.id}catch(e){}
  return ST.job}   // an upload whose name was never seen in this tab: reads as unsaved, the safe side
// The project as a save writes it, without what the library adds: what "unsaved changes" compares. Keys are sorted (a
// state resumed after a refresh holds the same values in another order), and material_kind is left out: it comes back
// as the one slice() derived from the material for the server, where the form holds ''
const sorted=(k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a<b?-1:a>b?1:0)):v;
const snapOf=(p,model)=>JSON.stringify({m:p.mode,u:p.unit,s:{...p.state,material_kind:undefined},memo:p.memo,model},sorted);
export const snap=()=>snapOf({mode:ST.mode.name,unit:ST.unit,state,memo},modelId());
export const unsaved=()=>snap()!==ST.saved?.snap;   // a fresh upload, or a session whose mirror is gone: unsaved
// an example as it opened: unsaved changes count from here, but it is nobody's revision, so a save of it is a new project
export const baseline=()=>setSaved({name:'',rev:'',snap:snap(),file:null,store:null});

// one save at a time: a second press while one runs gets the first one's answer
export function saveCurrent(ask){return saving??=save(ask).finally(()=>{saving=null})}
async function save(ask){
  // the fallback name: the model's file name, or the example's ('model' for an upload whose name this tab never saw)
  if(!state.project){const id=modelId();state.project=(Array.isArray(id)?id[0].replace(/\.[^.]*$/,''):held().up?'':id)||'model';syncProject();schedule()}
  // What is written is fixed first, before the model is read (that can take seconds, and a change made meanwhile is the
  // next save's). The listing, the checks and the write follow with no wait between them but the question, and after
  // an answer the library is listed and checked again
  const st=structuredClone(state), me=structuredClone(memo), model=modelId(), proj=await projectObj(), preview=snapshot();
  proj.state=st;proj.memo=me;if(preview)proj.preview=preview;
  const name=proj.name;let consented='';
  for(;;){
    await entries();
    // a project keeps the file-name stem it has (the one of the file in hand first: two files can hold one name);
    // a new one whose stem belongs to another file (a/b and a_b, Lamp and lamp) takes ~2, ~3…
    const own=ST.saved?.file&&ST.saved.name===name&&sameStore()?ST.saved.file:rows.find(r=>r.name===name&&!r.bad)?.file;
    let stem=own&&stemOf(own);
    if(!stem){const other=new Set(rows.map(r=>lc(stemOf(r.file)))),base=legal(name);stem=base;for(let k=2;other.has(lc(stem));k++)stem=`${base}~${k}`}
    const file=fileName(stem,proj.rev), hit=rows.find(r=>lc(r.file)===lc(file));
    if(hit?.bad)throw new Error(`${hit.file} in ${store.label} cannot be read, and Lamina does not write onto it: bump the revision, or use export to keep a copy of this project.`);
    // without asking only onto the file this tab opened or last saved, in this store, as it was then: another tab, or a
    // hand in the linked folder, can have changed it since (the index is no help here: listing just rebuilt it)
    const s=ST.saved, mine=!!s?.file&&lc(s.file)===lc(file)&&sameStore()&&seen.get(lc(file))?.mtime===s.mtime;
    if(!hit||mine||lc(file)===consented)return write(hit?.file||file,proj,model);
    const taken=rows.filter(r=>lc(stemOf(r.file))===lc(stem)).map(r=>r.file.slice(stem.length+2,-EXT.length));   // unreadable ones too
    const next=nextFree(taken,proj.rev,false), c=await ask({name,rev:proj.rev,next});
    if(c==='replace')consented=lc(file);
    else if(c==='keep'){proj.rev=proj.state.rev=state.rev=next;syncProject();schedule()}
    else return null;
  }
}
async function write(file,proj,model){
  const {name,rev}=proj;proj.saved=new Date().toISOString();
  // so a full disk does not evict the library: asked once, never waited for, its answer changes nothing here
  if(store.kind==='browser'&&!persisted){persisted=true;Promise.resolve().then(()=>navigator.storage?.persist?.()).catch(()=>{})}
  let w;
  try{w=await store.write(file,JSON.stringify(proj))}
  catch(e){throw new Error(`${name} v${rev} could not be saved in ${store.label} (${e.message||e.name}). Nothing in the library changed; use export to keep a copy of this project.`)}
  setSaved({name,rev,snap:snapOf(proj,model),file,store:here(),mtime:w.mtime});   // the snap of what the file holds
  // the file is written: an index that cannot follow is said as such. A new file has no entry and is read at the next
  // listing; an overwritten one keeps its old card until Task 7's size and mtime check sees the change
  try{await reindex(file,{file,size:w.size,mtime:w.mtime,name,rev,saved:proj.saved,preview:proj.preview||''})}
  catch(e){throw new Error(`${name} v${rev} was saved in ${store.label}, but the library's list could not be updated (${e.message||e.name}).`)}
  return {file};
}

export async function openRevision(file){
  await entries();const f=seen.get(lc(file));   // listed before it is read: a change after this makes the next save ask
  const text=await store.read(file), p=parse(text);
  await openProjectText(text,file);
  setSaved({name:p.name||'',rev:p.rev||'1.0',snap:snap(),file,store:here(),mtime:f?.mtime});
}

const unreadable=file=>new Error(`${file} cannot be read, and Lamina does not delete a file it cannot read. Delete it in ${store.label} yourself if you do not need it.`);
async function drop(file){
  await store.remove(file);await reindex(file,null);
  if(ST.saved?.file&&lc(ST.saved.file)===lc(file)&&sameStore())setSaved(null);   // the revision in hand is no longer saved
}
export async function removeRevision(file){
  await entries();if(rows.find(r=>r.file===file)?.bad)throw unreadable(file);
  await drop(file);
}
export async function removeProject(name){
  const p=(await entries()).find(p=>p.name===name);if(!p)return;
  const bad=p.revs.find(r=>r.bad);if(bad)throw unreadable(bad.file);
  for(const r of p.revs)await drop(r.file);   // listed once, above
}

// ---------------------------------------------------------------- the linked folder
// While a folder is linked it is the library; the browser store is the library only when none is. A linked folder that
// cannot be reached is not swapped for the browser store (the library would split in two): every call on it rejects
const LOST='The linked folder cannot be reached. Reconnect it in the library, or export the project.';
const lost=dir=>{const no=()=>Promise.reject(new Error(LOST));return {kind:'folder',label:dir.name,list:no,read:no,write:no,remove:no}};
// kept: the linked folder's handle; reach: the folder line's state; left: the folder an unlink left the files in
let kept=null, reach='browser', left='';
export const canLink=()=>'showDirectoryPicker' in window;
export const storeState=()=>({kind:store.kind,label:store.label,state:reach,files:rows.length,left});
function linked(dir,ok){kept=dir;reach=!dir?'browser':ok?'folder':'needs-permission';useStore(!dir?browserStore():ok?folderStore(dir):lost(dir));return reach}
// the private file system (the tests) has no permission calls: there, absent means granted
const granted=async(dir,request)=>{const f=request?dir.requestPermission:dir.queryPermission;return !f||await f.call(dir,{mode:'readwrite'})==='granted'};
// at start-up, without a click: only asks whether permission is there. A folder deleted or moved away lists nothing: not reachable either
export async function restoreStore(){left='';
  const dir=await kvGet('folder').catch(()=>null)??null;
  return linked(dir,!!dir&&await granted(dir,false).then(ok=>ok&&dir.entries().next().then(()=>true)).catch(()=>false))}
// from a click only: the browser shows its prompt
export async function reconnect(){if(!kept)return false;const ok=await granted(kept,true).catch(()=>false);if(ok)linked(kept,true);return ok}
export async function unlink(){left=kept?.name||'';await kvDel('folder');linked(null)}

// Every browser revision moves into the folder: written, read back and compared, and only then removed from the browser,
// so a failure half-way leaves each one in at least one of the two places. The bytes move as they are: a file that
// cannot be read goes too, unchanged. A clash asks as an import does; {answer, rest:true} answers the rest of them
export async function linkFolder(dir,ask){
  const from=browserStore(), to=folderStore(dir), moved=[], skipped=[];
  const there=new Map((await to.list()).map(f=>[lc(f.file),f.file]));
  let rest;
  try{for(const {file} of await from.list()){
    let text=await from.read(file), dest=file;
    if(there.has(lc(file))){
      const stem=stemOf(file), revOf=f=>f.slice(stem.length+2,-EXT.length), rev=revOf(file);
      let p=null;try{p=parse(text)}catch(e){}
      const next=nextFree([...there.values()].filter(f=>lc(stemOf(f))===lc(stem)).map(revOf),rev,false);
      let a=rest;if(a===undefined){const r=await ask({name:p?.name||file,rev,next});a=r?.answer??r;if(r?.rest)rest=a}
      // a file in the folder that cannot be read is never written onto: replace keeps both instead
      if(a==='replace'&&await to.read(there.get(lc(file))).then(parse).then(()=>false,()=>true))a='keep';
      if(a==='replace')dest=there.get(lc(file));   // the folder's own spelling of the name
      else if(a==='keep'){dest=`${stem}_v${next}${EXT}`;if(p){p.rev=next;if(p.state)p.state.rev=next;text=JSON.stringify(p)}}
      else{skipped.push(file);continue}   // left in the browser, where unlink finds it again
    }
    const w=await to.write(dest,text);
    if(await to.read(dest)!==text)throw new Error(`${dest} did not read back as it was written`);
    await from.remove(file);there.set(lc(dest),dest);moved.push(dest);
    // the revision in hand moved as it was: still this tab's to save without asking
    if(ST.saved?.file===file&&dest===file&&ST.saved.store?.kind==='browser')setSaved({...ST.saved,store:{kind:'folder',label:dir.name},mtime:w.mtime});
  }}catch(e){throw new Error(`Linking ${dir.name} stopped (${e.message||e.name}). ${moved.length} revisions were moved into ${dir.name}; the others are still in this browser.`)}
  await idxSet('folder',[]);   // the index of a folder linked before: not this one's
  await kvSet('folder',dir);left='';linked(dir,true);
  return {moved,skipped};
}
