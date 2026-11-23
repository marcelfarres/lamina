export const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
// this tab's own id: everything it slices lives under it on the server, so people sharing one server never meet.
// sessionStorage keeps it across a refresh but not into another tab; getRandomValues (not randomUUID) so it also
// works over plain http on a LAN.
export const CLIENT=sessionStorage.client||(sessionStorage.client=[...crypto.getRandomValues(new Uint8Array(16))].map(b=>b.toString(16).padStart(2,'0')).join(''));
export const ls=(k,d)=>{try{return JSON.parse(localStorage.getItem(k))??d}catch(e){return d}}, lsSet=(k,v)=>localStorage.setItem(k,JSON.stringify(v));

export const nice=n=>n.replace(/_/g,' ');
// a value from a project file is somebody else's text once a bug report is opened: it goes into the form as text, never as markup
export const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// the line is cut to fit the top bar: the whole of it is on hover
export function status(s,kind){const el=$('#status');el.textContent=el.title=s;$('#dot').className=kind||''}
