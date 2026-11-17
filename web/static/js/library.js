// ---------------------------------------------------------------- the library's rules
// What save, open, bump and delete mean for the projects kept in the library, and when the page has unsaved changes.
// No page here (librarypage.js draws it): every rule is reachable through window.__t.lib.
import {state, ST} from './state.js';
import {browserStore, folderStore, idxGet, idxSet, kvGet, kvSet, kvDel} from './store.js';
import {projectObj, openProjectText, syncProject, nextFree, nameOf, revOf as revText} from './project.js';
import {snapshot} from './scene.js';
import {memo, schedule} from './form.js';
import {zip, unzip} from './zip.js';
export {nextFree};

const EXT='.lamina.json';
// Windows refuses these in a file name; the name inside the file is the project's, the file name is only where it lives
const legal=s=>String(s).replace(/[\\/:*?"<>|\x00-\x1f]/g,'_');
export const fileName=(name,rev)=>`${legal(name)}_v${legal(rev)}${EXT}`;
// a file named by hand can lack the _v: its stem is then the whole name, and its revision empty
const cut=file=>file.lastIndexOf('_v'), stemOf=file=>cut(file)<0?file.slice(0,-EXT.length):file.slice(0,cut(file)),
  revOf=file=>cut(file)<0?'':file.slice(cut(file)+2,-EXT.length);
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
const isDate=v=>typeof v==='string'&&!isNaN(Date.parse(v));
// The index entry of a project file, for a listing and an import alike: every field text, whatever the file holds. A
// number as `saved` made the newest-first sort throw, and with it every listing after: no page, no save, no export.
// A date is kept as ISO text, so newest-first compares dates, not "Nov 5 2023" as text
const entryOf=(at,p)=>({...at,name:nameOf(p),rev:revText(p),saved:isDate(p.saved)?new Date(p.saved).toISOString():at.saved,preview:typeof p.preview==='string'?p.preview:''});
// an index entry is trusted only as entryOf makes them: one stored before this rule is read again
const sane=e=>['name','rev','saved','preview'].every(k=>typeof e?.[k]==='string');
// one index entry per revision file: what a card needs, without reading the file again
async function readEntry(s,f){
  const at={file:f.file,size:f.size,mtime:f.mtime,saved:new Date(f.mtime).toISOString(),preview:''};
  try{return entryOf(at,parse(await s.read(f.file)))}
  catch(e){return {...at,name:f.file,rev:'',bad:true}}   // listed by its file name; Lamina never writes onto it or deletes it
}
const group=()=>{const by=new Map();
  for(const r of rows){if(!by.has(r.name))by.set(r.name,[]);by.get(r.name).push({rev:r.rev,file:r.file,saved:r.saved,preview:r.preview,bad:!!r.bad})}
  const newest=p=>p.revs.reduce((m,r)=>r.saved>m?r.saved:m,'');
  return last=[...by].map(([name,revs])=>({name,revs:revs.sort(byRev)})).sort((a,b)=>newest(b).localeCompare(newest(a)))};
// The folder's index is kept with the folder's handle: the entries of a folder linked before are never trusted for this one
async function idxOf(s){const v=await idxGet(s.kind);if(s.kind!=='folder')return v;
  return v?.dir&&kept&&await v.dir.isSameEntry(kept).catch(()=>false)?v.entries:[]}
const idxPut=(s,e)=>idxSet(s.kind,s.kind==='folder'?{dir:kept,entries:e}:e);
export async function entries(){
  await ready;const s=store, idx=new Map((await idxOf(s)).map(e=>[e.file,e])), files=await s.list();
  let changed=files.length!==idx.size;
  // an entry is trusted while its file's size and mtime are unchanged: a library of big models opens without reading them
  const out=[];for(const f of files){let e=idx.get(f.file);if(!sane(e)||e.size!==f.size||e.mtime!==f.mtime){e=await readEntry(s,f);changed=true}out.push(e)}
  if(s!==store)return last;   // useStore() overtook this listing: it is not the current store's, and changes nothing
  rows=out;seen=new Map(files.map(f=>[lc(f.file),f]));
  if(changed)await idxPut(s,rows);
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
  const i=(await idxOf(store)).filter(e=>e.file!==file);if(entry)i.push(entry);await idxPut(store,i);
}

// ST.saved = {name, rev, snap, file, store, mtime, size}: what this tab opened or last saved (state.js mirrors it in sessionStorage)
export function setSaved(v){ST.saved=v;changed()}
// the revision in hand when it is one of this store's (what the library page marks "open now")
export const inHand=()=>ST.saved?.file&&sameStore()?ST.saved:null;
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

// Where a revision of `name` lands in the library as last listed, for a save and an import alike. A project keeps the
// file-name stem it has (`own`, else its first readable file: two files can hold one name); a new one whose stem
// belongs to another file (a/b and a_b, Lamp and lamp) takes ~2, ~3… `hit`: the file already there; `taken`: the
// stem's revisions, unreadable ones too
function place(name,rev,own){
  own=own||rows.find(r=>r.name===name&&!r.bad)?.file;let stem=own&&stemOf(own);
  if(!stem){const other=new Set(rows.map(r=>lc(stemOf(r.file)))),base=legal(name);stem=base;for(let k=2;other.has(lc(stem));k++)stem=`${base}~${k}`}
  const file=fileName(stem,rev);
  return {file,hit:rows.find(r=>lc(r.file)===lc(file)),taken:rows.filter(r=>lc(stemOf(r.file))===lc(stem)).map(r=>revOf(r.file))};
}

// Save, link, import, open, delete, unlink and reconnect run one at a time, after start-up has picked the store: a save that
// lands while a link moves the files is removed with the browser copy, or stays behind in the browser unseen
// `ready` stays pending until restoreStore() has picked the store (main.js starts it first thing), so no call reaches
// the browser store while a folder is kept
let queue=Promise.resolve(), start, ready=new Promise(ok=>start=ok);
const one=fn=>{const r=queue.then(()=>ready).then(fn);queue=r.catch(()=>{});return r};
// one save at a time: a second press while one runs gets the first one's answer
export function saveCurrent(ask){if(saving)return saving;
  let run;try{run=fixed(ask)}catch(e){return Promise.reject(e)}   // a state that cannot be copied: the caller hears it
  return saving=one(run).finally(()=>{saving=null})}
// What is written is fixed at the press, before the queue and before the model is read (both can take seconds, and a
// change made meanwhile is the next save's): projectObj takes name, revision and technique as it starts, and the
// preview is the scene of the press
function fixed(ask){
  // the fallback name: the model's file name, or the example's ('model' for an upload whose name this tab never saw)
  if(!state.project){const id=modelId();state.project=(Array.isArray(id)?id[0].replace(/\.[^.]*$/,''):held().up?'':id)||'model';syncProject();schedule()}
  const st=structuredClone(state), me=structuredClone(memo), model=modelId(), preview=snapshot(), obj=projectObj();
  obj.catch(()=>{});   // answered in save(), once the queue lets it run
  return ()=>save(ask,obj,st,me,model,preview);
}
// The listing, the checks and the write follow with no wait between them but the question, and after an answer the
// library is listed and checked again
async function save(ask,obj,st,me,model,preview){
  const proj=await obj;
  proj.state=st;proj.memo=me;if(preview)proj.preview=preview;
  const name=proj.name;let consented='';
  for(;;){
    await entries();
    const {file,hit,taken}=place(name,proj.rev,ST.saved?.file&&ST.saved.name===name&&sameStore()&&ST.saved.file);   // the file in hand first
    if(hit?.bad)throw new Error(`${hit.file} in ${store.label} cannot be read, and Lamina does not write onto it: bump the revision, or use export to keep a copy of this project.`);
    // without asking only onto the file this tab opened or last saved, in this store, as it was then: another tab, or a
    // hand in the linked folder, can have changed it since (the index is no help here: listing just rebuilt it)
    const s=ST.saved, now=seen.get(lc(file)), mine=!!s?.file&&lc(s.file)===lc(file)&&sameStore()&&now?.mtime===s.mtime&&now.size===s.size;
    if(!hit||mine||lc(file)===consented)return write(hit?.file||file,proj,model);
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
  setSaved({name,rev,snap:snapOf(proj,model),file,store:here(),mtime:w.mtime,size:w.size});   // the snap of what the file holds
  // the file is written: an index that cannot follow is said as such. A new file has no entry and is read at the next
  // listing; an overwritten one keeps its old card until Task 7's size and mtime check sees the change
  try{await reindex(file,entryOf({file,size:w.size,mtime:w.mtime,saved:proj.saved},proj))}
  catch(e){throw new Error(`${name} v${rev} was saved in ${store.label}, but the library's list could not be updated (${e.message||e.name}).`)}
  return {file};
}

export const openRevision=file=>one(async()=>{
  await entries();const f=seen.get(lc(file));   // listed before it is read: a change after this makes the next save ask
  const text=await store.read(file), p=parse(text);
  await openProjectText(text,file);
  setSaved({name:nameOf(p),rev:revText(p),snap:snap(),file,store:here(),mtime:f?.mtime,size:f?.size});
});

const unreadable=file=>new Error(`${file} cannot be read, and Lamina does not delete a file it cannot read. Delete it in ${store.label} yourself if you do not need it.`);
async function drop(file){
  await store.remove(file);await reindex(file,null);
  if(ST.saved?.file&&lc(ST.saved.file)===lc(file)&&sameStore())setSaved(null);   // the revision in hand is no longer saved
}
export const removeRevision=file=>one(async()=>{
  await entries();if(rows.find(r=>r.file===file)?.bad)throw unreadable(file);
  await drop(file);
});
export const removeProject=name=>one(async()=>{
  const p=(await entries()).find(p=>p.name===name);if(!p)return;
  const bad=p.revs.find(r=>r.bad);if(bad)throw unreadable(bad.file);
  for(const r of p.revs)await drop(r.file);   // listed once, above
});

// ---------------------------------------------------------------- export and import
// Export gives the files as the library holds them. A file whose text is no project goes too, as it is: a backup
// loses nothing, and it is somebody's file. Export all leaves out, and names, only a file the store cannot read at all.
// ponytail: a store gives text, so a folder file that is not UTF-8 is exported with its odd bytes replaced; a read as
// bytes in both stores if that ever matters
export async function exportRevision(file){await ready;return {name:file,blob:new Blob([await store.read(file)],{type:'application/json'})}}
export async function exportProject(name){const p=(await entries()).find(p=>p.name===name), s=store, files=[];
  if(!p)throw new Error(`${name} is not in ${s.label}`);
  for(const r of p.revs)files.push({name:r.file,text:await s.read(r.file)});
  return {name:`${legal(name)}.lamina.zip`,blob:zip(files)}}
export async function exportAll(){await entries();const s=store, files=[], skipped=[];
  for(const {file} of rows)try{files.push({name:file,text:await s.read(file)})}catch(e){skipped.push(file)}
  return {name:'lamina-library.zip',blob:zip(files),skipped}}

// .lamina.json files and the zips export makes. A file or zip entry that is no project is named in `bad` and nothing
// is written for it. Each revision lands where a save of it would (place); a clash asks as a link does, and
// {answer, rest:true} answers the rest of them. keep takes a number free in the library and among the files still to
// come in this call; replace never lands on a file that cannot be read, nor on one this import has just written (two
// files of one revision): both are kept instead, and named in `kept` with the reason. A skip changes nothing and is
// named in `skipped`
export const importFiles=(files,ask)=>one(async()=>{
  const todo=[], bad=[], imported=[], skipped=[], both=[];
  for(const f of files){let got;
    try{got=/\.zip$/i.test(f.name)?await unzip(await f.arrayBuffer()):[{name:f.name,text:await f.text()}]}catch(e){bad.push(f.name);continue}
    bad.push(...got.bad||[]);
    // a file with a date in it is written as it is (as a link moves it); one without gets the File's date. Its name
    // and revision are made text here: a field that cannot be is this one bad file, not a stopped import
    for(const g of got)try{const p=parse(g.text), dated=isDate(p.saved);if(!dated)p.saved=new Date(f.lastModified).toISOString();
      todo.push({p,text:dated?g.text:null,name:nameOf(p),rev:revText(p)})}catch(e){bad.push(g.name)}
  }
  let rest;
  try{for(const [i,{p,text,name,rev:r0}] of todo.entries()){let rev=r0, out=text, consented='';
    for(;;){
      // listed before each file and after each question, with no wait but the question before the write: another tab
      // can save a revision of this name meanwhile
      await entries();const {file,hit,taken}=place(name,rev);
      if(!hit||!hit.bad&&lc(file)===consented){const dest=hit?.file||file, w=await store.write(dest,out??JSON.stringify(p));
        imported.push(dest);await reindex(dest,entryOf({file:dest,size:w.size,mtime:w.mtime,saved:p.saved},p));break}
      const next=nextFree([...taken,...todo.slice(i+1).filter(q=>q.name===name).map(q=>q.rev)],rev,false);
      let a=rest;if(a===undefined){const r=await ask({name,rev,next});a=typeof r==='object'&&r?r.answer:r;if(r?.rest)rest=a}
      const twice=imported.some(f=>lc(f)===lc(hit.file));
      if(a==='replace'&&!hit.bad&&!twice)consented=lc(file);
      else if(a==='replace'||a==='keep'){if(a==='replace')both.push({rev:`${name} v${rev}`,as:next,why:twice?'twice':'unreadable'});
        rev=p.rev=next;if(p.state&&typeof p.state==='object')p.state.rev=next;out=null}
      else{skipped.push(`${name} v${rev}`);break}
    }
  }}catch(e){throw new Error(`The import stopped (${e.message||e.name}). ${imported.length} of the files were written into ${store.label}; the others were not.`)}
  if(kept)await countBrowser();
  return {imported,bad,skipped,kept:both};
});

// ---------------------------------------------------------------- the linked folder
// While a folder is linked it is the library; the browser store is the library only when none is. A linked folder that
// cannot be reached is not swapped for the browser store (the library would split in two): every call on it rejects
const LOST='The linked folder cannot be reached. Reconnect it in the library, or export the project.';
const lost=dir=>{const no=()=>Promise.reject(new Error(LOST));return {kind:'folder',label:dir.name,list:no,read:no,write:no,remove:no}};
// kept: the linked folder's handle; reach: the folder line's state; left: the folder an unlink or a change of folder
// left the files in; inBrowser: the revisions still in the browser while a folder is linked (a link that skipped
// some), which nothing would show otherwise
let kept=null, reach='browser', left='', linking=null, inBrowser=0;
export const canLink=()=>'showDirectoryPicker' in window;
export const storeState=()=>({kind:store.kind,label:store.label,state:reach,files:rows.length,left,browser:kept?inBrowser:0});
const countBrowser=()=>browserStore().list().then(l=>{inBrowser=l.length},()=>{});
// permission taken away during a session (site settings) answers NotAllowedError: from then on the folder is not reachable
function guarded(s,dir){const g={...s};
  for(const k of ['list','read','write','remove'])g[k]=(...a)=>s[k](...a).catch(e=>{if(e?.name!=='NotAllowedError')throw e;if(store===g)linked(dir,false);throw new Error(LOST)});
  return g}
function linked(dir,ok){kept=dir;reach=!dir?'browser':ok?'folder':'needs-permission';useStore(!dir?browserStore():ok?guarded(folderStore(dir),dir):lost(dir));return reach}
// the private file system (the tests) has no permission calls: there, absent means granted. A folder deleted or moved
// away lists nothing: not reachable either
const allowed=ask=>{try{return Promise.resolve(ask()).then(p=>p===undefined||p==='granted')}catch(e){return Promise.resolve(false)}};
const reachable=(dir,asked)=>asked.then(ok=>ok&&dir.entries().next().then(()=>true)).catch(()=>false);
// at start-up, without a click: only asks whether permission is there. Every library call waits for it (`ready`)
export function restoreStore(){left='';
  const p=kvGet('folder').catch(()=>null).then(async dir=>{const r=linked(dir??null,!!dir&&await reachable(dir,allowed(()=>dir.queryPermission?.({mode:'readwrite'}))));
    if(dir)await countBrowser();return r});
  start(p);return ready=p}
// from a click only. The prompt is asked for here, at once: the click's permission to show it runs out in a few seconds,
// and a save or a link ahead in the queue can take longer. Only the check and the switch of store wait their turn
export function reconnect(){const dir=kept;if(!dir)return Promise.resolve(false);
  const asked=allowed(()=>dir.requestPermission?.({mode:'readwrite'}));
  return one(async()=>{const ok=await reachable(dir,asked)&&kept===dir;if(ok)linked(dir,true);return ok})}
export const unlink=()=>one(async()=>{left=kept?.name||'';await kvDel('folder');linked(null)});

// Every browser revision moves into the folder: written, read back and compared, and only then removed from the browser,
// so a failure half-way leaves each one in at least one of the two places. The bytes move as they are: a file that
// cannot be read goes too, unchanged. A clash asks as an import does; {answer, rest:true} answers the rest of them.
// One link at a time, and none while a save runs: a second call gets the running one's answer
export function linkFolder(dir,ask){return linking??=one(()=>link(dir,ask)).finally(()=>{linking=null})}
async function link(dir,ask){
  // skipped: left in the browser; changed: those of them another tab saved again while they were being moved
  const from=browserStore(), to=folderStore(dir), moved=[], skipped=[], changed=[];
  const there=new Map((await to.list()).map(f=>[lc(f.file),f.file])), files=await from.list();
  let rest;
  try{for(const f of files){
    // read with its own time and size: another tab can have saved it since the listing, and those bytes are the ones that move
    const {file}=f, got=await from.record(file);let text=got.text, dest=file;
    if(there.has(lc(file))){
      const stem=stemOf(file), rev=revOf(file);
      let p=null;try{p=parse(text)}catch(e){}
      // a kept revision lands on no revision of this name: those in the folder, nor those still to come from the browser
      const next=nextFree([...there.values(),...files.map(g=>g.file)].filter(g=>lc(stemOf(g))===lc(stem)).map(revOf),rev||'1.0',false);
      let a=rest;if(a===undefined){const r=await ask({name:p?.name||file,rev,next});a=typeof r==='object'&&r?r.answer:r;if(r?.rest)rest=a}
      // a file in the folder that cannot be read is never written onto: replace keeps both instead
      if(a==='replace'&&await to.read(there.get(lc(file))).then(parse).then(()=>false,()=>true))a='keep';
      if(a==='replace')dest=there.get(lc(file));   // the folder's own spelling of the name
      else if(a==='keep'){dest=`${stem}_v${next}${EXT}`;if(p){p.rev=next;if(p.state)p.state.rev=next;text=JSON.stringify(p)}}
      else{skipped.push(file);continue}   // left in the browser, where unlink finds it again
    }
    const w=await to.write(dest,text);
    if(await to.read(dest)!==text)throw new Error(`${dest} did not read back as it was written`);
    there.set(lc(dest),dest);
    // the browser copy goes only if it is still the one that was read: a newer save (another tab, during the question)
    // stays in the browser, and the folder holds the copy from before under `dest`
    if(!await from.removeIf(file,got)){skipped.push(file);changed.push(file);continue}
    moved.push(dest);
    // the revision in hand, moved as this tab last saw it (not as another tab saved it since): still this tab's to save without asking
    const s=ST.saved;
    if(s?.file===file&&dest===file&&s.store?.kind==='browser'&&s.mtime===got.mtime&&s.size===got.size)setSaved({...s,store:{kind:'folder',label:dir.name},mtime:w.mtime,size:w.size});
  }}catch(e){throw new Error(`Linking ${dir.name} stopped (${e.message||e.name}). ${moved.length} revisions were moved into ${dir.name}; the others are still in this browser.`)}
  try{await kvSet('folder',dir)}
  catch(e){throw new Error(`Linking ${dir.name} stopped (${e.message||e.name}). The revisions were moved into ${dir.name}, but the folder is not linked: link it again.`)}
  // another folder picked: the old one keeps its files, and the folder line says where
  left=kept&&!await kept.isSameEntry(dir).catch(()=>false)?kept.name:'';linked(dir,true);await countBrowser();
  return {moved,skipped,changed};
}
