// where the library's revisions live: the browser's own database, or a folder the person linked (Chrome, Edge).
// Both answer the same four calls, so the library does not care which one it has.
const EXT='.lamina.json';

// one connection per call, closed when its transaction ends: a long-held one would block a page in another tab
// that opens a newer version of the database. All three object stores are made the first time it is opened.
const open=()=>new Promise((ok,no)=>{const r=indexedDB.open('lamina_library',1);
  r.onupgradeneeded=()=>{const d=r.result;d.createObjectStore('revisions',{keyPath:'file'});d.createObjectStore('kv');d.createObjectStore('index')};
  r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});
async function tx(name,mode,fn){
  const d=await open();
  // a call that throws (a value that cannot be stored) still lets go of the database; an abort always rejects with an Error
  return new Promise((ok,no)=>{let r;try{const t=d.transaction(name,mode);
    t.oncomplete=()=>{d.close();ok(r?.result)};t.onerror=t.onabort=()=>{d.close();no(t.error??r?.error??new Error(`the browser's database refused to change ${name}`))};
    r=fn(t.objectStore(name))}catch(e){d.close();no(e)}});
}

export function browserStore(){
  return {kind:'browser',label:'this browser',
    // ponytail: getAll reads every revision's text to list them, fine for hundreds of small files; a cursor over a
    // size/mtime index if the library grows past that
    list:async()=>(await tx('revisions','readonly',s=>s.getAll())).filter(r=>r.file.endsWith(EXT)).map(({file,size,mtime})=>({file,size,mtime})),
    read:async file=>{const r=await tx('revisions','readonly',s=>s.get(file));if(!r)throw new Error(`${file} is not in this browser`);return r.text},
    // one transaction: either the whole new record is stored or the old one stays
    write:async(file,text)=>{const r={file,text,size:new Blob([text]).size,mtime:Date.now()};await tx('revisions','readwrite',s=>s.put(r));return {size:r.size,mtime:r.mtime}},
    remove:file=>tx('revisions','readwrite',s=>s.delete(file)).then(()=>{})};
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
    // a file this write created is removed again, not left behind empty
    async write(file,text){
      const made=await dir.getFileHandle(file).then(()=>false,()=>true), h=await dir.getFileHandle(file,{create:true}), w=await h.createWritable();
      try{await w.write(text);await w.close()}
      catch(e){await w.abort().catch(()=>{});if(made)await dir.removeEntry(file).catch(()=>{});throw e}
      const f=await h.getFile();return {size:f.size,mtime:f.lastModified}},
    remove:file=>dir.removeEntry(file)};
}

export const kvGet=key=>tx('kv','readonly',s=>s.get(key)), kvSet=(key,value)=>tx('kv','readwrite',s=>s.put(value,key)).then(()=>{}),
  kvDel=key=>tx('kv','readwrite',s=>s.delete(key)).then(()=>{});
export const idxGet=async kind=>(await tx('index','readonly',s=>s.get(kind)))??[],
  idxSet=(kind,entries)=>tx('index','readwrite',s=>s.put(entries,kind)).then(()=>{});
