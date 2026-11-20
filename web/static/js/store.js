// where the library's revisions live: the browser's own database, a folder the person linked (Chrome, Edge), or a
// folder on the server (LAMINA_LIBRARY, every browser). All three answer the same calls, so the library does not care
// which one it has.
const EXT='.lamina.json';

// one connection per call, closed when its transaction ends: a long-held one would block a page in another tab
// that opens a newer version of the database. All three object stores are made the first time it is opened.
// Blocked (another tab holds the database while it must be made or deleted): said at once rather than waited for, so
// a caller such as the library's start-up never hangs on it; a connection that opens after that is closed again.
// Version 2 adds the revisions' size and mtime as an index, so a listing reads no text. A record without a number as
// either would be left out of the index, and so out of every listing, export and link: the upgrade gives it the size
// of its text and the date saved in it (now, if none)
const key=v=>typeof v==='number'&&!isNaN(v);
const savedIn=text=>{try{const t=Date.parse(JSON.parse(text).saved);if(key(t))return t}catch(e){}return Date.now()};
const open=()=>new Promise((ok,no)=>{const r=indexedDB.open('lamina_library',2);let late=false;
  r.onupgradeneeded=e=>{const d=r.result;
    if(e.oldVersion<1){d.createObjectStore('revisions',{keyPath:'file'});d.createObjectStore('kv');d.createObjectStore('index')}
    if(e.oldVersion<2){const s=r.transaction.objectStore('revisions');s.createIndex('meta',['size','mtime']);
      s.openCursor().onsuccess=ev=>{const c=ev.target.result;if(!c)return;const v=c.value, text=String(v.text??'');
        if(!key(v.size)||!key(v.mtime))c.update({...v,size:key(v.size)?v.size:new Blob([text]).size,mtime:key(v.mtime)?v.mtime:savedIn(text)});
        c.continue()}}};
  r.onblocked=()=>{late=true;no(new Error("the browser's database is in use by another Lamina tab: close it, then try again"))};
  r.onsuccess=()=>{if(late)r.result.close();else ok(r.result)};r.onerror=()=>no(r.error)});
async function tx(name,mode,fn){
  const d=await open();
  // a call that throws (a value that cannot be stored) still lets go of the database; an abort always rejects with an Error
  return new Promise((ok,no)=>{let r;try{const t=d.transaction(name,mode);
    t.oncomplete=()=>{d.close();ok(r?.result)};t.onerror=t.onabort=()=>{d.close();no(t.error??r?.error??new Error(`the browser's database refused to change ${name}`))};
    r=fn(t.objectStore(name))}catch(e){d.close();no(e)}});
}

export function browserStore(){
  // the whole record, {file, text, size, mtime}: the text with the time and size it was stored with (linkFolder)
  const record=async file=>{const r=await tx('revisions','readonly',s=>s.get(file));if(!r)throw new Error(`${file} is not in this browser`);return r};
  return {kind:'browser',label:'this browser',record,
    // the keys of the size/mtime index only: no revision's text is read. Sorted by file, as the records are kept
    list:async()=>(await tx('revisions','readonly',s=>{const out={result:[]}, c=s.index('meta').openKeyCursor();
      c.onsuccess=()=>{const k=c.result;if(!k)return;if(k.primaryKey.endsWith(EXT))out.result.push({file:k.primaryKey,size:k.key[0],mtime:k.key[1]});k.continue()};
      return out})).sort((a,b)=>a.file<b.file?-1:a.file>b.file?1:0),
    read:async file=>(await record(file)).text,
    // one transaction: either the whole new record is stored or the old one stays
    write:async(file,text)=>{const r={file,text,size:new Blob([text]).size,mtime:Date.now()};await tx('revisions','readwrite',s=>s.put(r));return {size:r.size,mtime:r.mtime}},
    remove:file=>tx('revisions','readwrite',s=>s.delete(file)).then(()=>{}),
    // removed only while it still has the time and size it was read with, checked and deleted in one transaction: a
    // newer save from another tab stays. True when it is gone (removed here, or already gone)
    removeIf:(file,{mtime,size})=>tx('revisions','readwrite',s=>{const g=s.get(file),out={result:false};
      g.onsuccess=()=>{const r=g.result;if(!r||r.mtime===mtime&&r.size===size){if(r)s.delete(file);out.result=true}};return out})};
}

export function folderStore(dir){
  return {kind:'folder',label:dir.name,
    async list(){const out=[];
      for await(const [file,h] of dir.entries())
        if(h.kind==='file'&&file.endsWith(EXT)){   // a file deleted between its name and its read is simply not there
          const f=await h.getFile().catch(e=>{if(e.name!=='NotFoundError')throw e});if(f)out.push({file,size:f.size,mtime:f.lastModified})}
      return out},
    read:async file=>(await (await dir.getFileHandle(file)).getFile()).text(),
    // createWritable writes to a side file that close() swaps in, so a write that fails leaves the old file whole;
    // a file this write created is removed again, not left behind empty. Only "not found" makes it new: any other
    // error stops the write, so a file that was there is never taken for one this write made
    async write(file,text){
      const made=await dir.getFileHandle(file).then(()=>false,e=>{if(e.name!=='NotFoundError')throw e;return true}), h=await dir.getFileHandle(file,{create:true}), w=await h.createWritable();
      try{await w.write(text);await w.close()}
      catch(e){await w.abort().catch(()=>{});if(made)await dir.removeEntry(file).catch(()=>{});throw e}
      // ponytail: time and size are read after close(), so a write from outside in those few milliseconds is taken as this
      // tab's own (its next save does not ask); the File System API gives no way to read them in the same step
      const f=await h.getFile();return {size:f.size,mtime:f.lastModified}},
    remove:file=>dir.removeEntry(file)};
}

// the folder the server keeps (web/app.py's api/library): info is api/project's `library`, {name, problem}. The server
// swaps a write in whole and checks a removeIf under its lock. `problem` is what the server says is wrong with its
// folder ('' when nothing), as of the last listing or write, for the folder line; a write it refuses rejects with it
// (503: the folder, not one file, is the trouble)
export function serverStore(info){
  const call=async(file,o,q)=>{const r=await fetch(`api/library${file?'/'+encodeURIComponent(file):''}${q?'?'+new URLSearchParams(q):''}`,o),
      j=await r.json().catch(()=>({}));
    if(r.status===503&&(!file||o?.method==='PUT'))s.problem=j.detail||'';
    if(!r.ok)throw new Error(j.detail||`the server answered ${r.status}`);return j};
  const s={kind:'server',label:info.name,problem:info.problem||'',
    list:async()=>{const j=await call('');s.problem=j.problem;return j.files},
    record:async file=>({file,...await call(file)}),
    read:async file=>(await call(file)).text,
    write:async(file,text)=>{const j=await call(file,{method:'PUT',body:text});s.problem='';return j},
    remove:file=>call(file,{method:'DELETE'}).then(()=>{}),
    removeIf:(file,{mtime,size})=>call(file,{method:'DELETE'},{size,mtime}).then(j=>j.removed)};
  return s;
}

export const kvGet=key=>tx('kv','readonly',s=>s.get(key)), kvSet=(key,value)=>tx('kv','readwrite',s=>s.put(value,key)).then(()=>{}),
  kvDel=key=>tx('kv','readwrite',s=>s.delete(key)).then(()=>{});
export const idxGet=async kind=>(await tx('index','readonly',s=>s.get(kind)))??[],
  idxSet=(kind,entries)=>tx('index','readwrite',s=>s.put(entries,kind)).then(()=>{});
