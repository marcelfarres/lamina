// export and import of many projects as one file. Entries are stored, not deflated: project files are small and a
// deflater is a dependency. unzip reads only stored entries; anything else (a zip re-packed by an archiver) is named
// in .bad so the page can say which files it skipped.
const CRC=new Uint32Array(256).map((_,n)=>{let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;return c});
const crc32=b=>{let c=~0;for(const x of b)c=CRC[(c^x)&255]^(c>>>8);return ~c>>>0};
const enc=new TextEncoder();

export function zip(files){
  const d=new Date(), time=d.getHours()<<11|d.getMinutes()<<5|d.getSeconds()>>1,
    date=(d.getFullYear()-1980)<<9|(d.getMonth()+1)<<5|d.getDate(), parts=[], cd=[];
  let off=0;
  // the header both directories share, from "version needed" to the name length; flag bit 11 = UTF-8 name and text
  const head=(v,name,data,crc)=>{v.setUint16(0,20,true);v.setUint16(2,0x800,true);v.setUint16(4,0,true);v.setUint16(6,time,true);
    v.setUint16(8,date,true);v.setUint32(10,crc,true);v.setUint32(14,data.length,true);v.setUint32(18,data.length,true);v.setUint16(22,name.length,true)};
  for(const f of files){
    const name=enc.encode(f.name), data=enc.encode(f.text), crc=crc32(data), loc=new Uint8Array(30+name.length), c=new Uint8Array(46+name.length);
    const lv=new DataView(loc.buffer), cv=new DataView(c.buffer);
    lv.setUint32(0,0x04034b50,true);head(new DataView(loc.buffer,4),name,data,crc);loc.set(name,30);
    cv.setUint32(0,0x02014b50,true);cv.setUint16(4,20,true);head(new DataView(c.buffer,6),name,data,crc);cv.setUint32(42,off,true);c.set(name,46);
    parts.push(loc,data);cd.push(c);off+=loc.length+data.length;
    // a plain zip keeps every offset and size in 32 bits: past them it would wrap round into a broken file (Zip64 has more)
    if(off>0xffffffff)throw new Error('Export all is too big for one zip (over 4 GB). Export the projects one by one.');
  }
  const size=cd.reduce((s,c)=>s+c.length,0), end=new DataView(new ArrayBuffer(22));
  end.setUint32(0,0x06054b50,true);end.setUint16(8,files.length,true);end.setUint16(10,files.length,true);end.setUint32(12,size,true);end.setUint32(16,off,true);
  return new Blob([...parts,...cd,end],{type:'application/zip'});
}

export async function unzip(buf){
  const v=new DataView(buf), u=new Uint8Array(buf), len=buf.byteLength, dec=new TextDecoder('utf-8',{fatal:true}), out=[];
  // the end record sits behind an optional comment of up to 64 KB: looked for there only
  const stop=Math.max(0,len-22-0xffff);let e=len-22;
  while(e>=stop&&v.getUint32(e,true)!==0x06054b50)e--;
  if(e<stop)throw new Error('not a zip');
  out.bad=[];
  // a truncated or damaged zip points past its own end: every read is checked against the length first, so it is
  // "not a zip" (or one bad entry), never a RangeError
  for(let n=v.getUint16(e+10,true),p=v.getUint32(e+16,true);n--;){
    if(p+46>len||v.getUint32(p,true)!==0x02014b50||p+46+v.getUint16(p+28,true)>len)throw new Error('not a zip');
    // the name is read as UTF-8 whatever flag bit 11 says: an archiver's code-page name comes out garbled, and it is
    // only shown in the list of bad entries
    const nl=v.getUint16(p+28,true), name=new TextDecoder().decode(u.subarray(p+46,p+46+nl)),
      method=v.getUint16(p+10,true), crc=v.getUint32(p+16,true), size=v.getUint32(p+20,true), lo=v.getUint32(p+42,true);
    p+=46+nl+v.getUint16(p+30,true)+v.getUint16(p+32,true);
    if(name.endsWith('/'))continue;                      // a folder entry: nothing to read
    try{
      if(method!==0||lo+30>len||v.getUint32(lo,true)!==0x04034b50)throw 0;
      const at=lo+30+v.getUint16(lo+26,true)+v.getUint16(lo+28,true), data=u.subarray(at,at+size);
      if(data.length!==size||crc32(data)!==crc)throw 0;
      out.push({name,text:dec.decode(data)});
    }catch(_){out.bad.push(name)}
  }
  return out;
}
