import {$, ls, lsSet} from './util.js';
import {popup} from './slice.js';

// What's new. CHANGELOG.md is the one copy — the server serves it and the published build copies it beside the
// page, so the same relative path works either way, and its first `## x.y.z` heading *is* the version: nothing to
// bump in two places. The dialog opens itself once when that version is not the one this browser last saw, with every
// version since that one, and the header button opens the whole list, newest first. A browser that has never seen Lamina is not shown it: for them
// none of it is new.
const MDESC={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'};
// A picture is written from the repo root (web/static/news/…) so that GitHub shows it too; the page sits where web/
// does not (the server and the published build both serve static/ beside it). A link may be http(s) or a path only
const url=u=>/^[a-z][\w+.-]*:/i.test(u)&&!/^https?:/i.test(u)?'#':u.replace(/^web\//,'');
const img=(alt,src)=>`<img src="${url(src)}" alt="${alt}" title="${alt}" loading="lazy">`;
const a=(body,href)=>`<a href="${url(href)}" target="_blank" rel="noopener">${body}</a>`;
// a Windows checkout serves CHANGELOG.md with CRLF: a blank line is then \r\n\r\n, nothing split on /\n{2,}/, and a whole
// version came out as one paragraph with its - bullets inline (reported). The line endings are made one first
const md2html=s=>s.replace(/\r\n?/g,'\n').replace(/[&<>"]/g,c=>MDESC[c])
  .replace(/\[!\[([^\]]*)\]\(([^)\s]+)\)\]\(([^)\s]+)\)/g,(_,t,src,href)=>a(img(t,src),href))   // a clip: its poster, linked to the mp4
  .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,(_,t,src)=>img(t,src))
  .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,(_,t,href)=>a(t,href))
  .replace(/^### +(.+)$/gm,'\n<h4>$1</h4>\n')
  .replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(?<!\*)\*([^*]+)\*/g,'<i>$1</i>')
  .split(/\n{2,}/).map(b=>{
    b=b.trim(); if(!b)return '';
    if(b.startsWith('<h4>'))return b;
    if(b.startsWith('- '))return '<ul>'+b.split(/\n(?=- )/).map(li=>`<li>${li.replace(/^- /,'').replace(/\s*\n\s+/g,' ')}</li>`).join('')+'</ul>';
    return `<p>${b.replace(/\s*\n\s*/g,' ')}</p>`;
  }).join('');
let NEWS;
export async function news(){
  if(!NEWS){
    const txt=await (await fetch('changelog.md',{cache:'no-cache'})).text();
    NEWS=txt.split(/^## +/m).slice(1).map(p=>({v:p.slice(0,p.indexOf('\n')).trim(),body:p.slice(p.indexOf('\n')+1)}));
  }
  return NEWS;
}
export async function showNews(n){                              // the n newest versions (the header button: all of them)
  const vs=(await news()).slice(0,n); if(!vs.length)return;
  $('#news_title').textContent=vs.length>1?'What’s new':`What’s new in ${vs[0].v}`;
  $('#news_body').innerHTML=vs.map(s=>(vs.length>1?`<h5>Version ${s.v}</h5>`:'')+md2html(s.body)).join('');
  if(!$('#newsdlg').open)$('#newsdlg').showModal();
  $('#newsdlg').scrollTop=0;                             // focus lands on OK, which would otherwise open it at the end
}
export async function whatsNew(){
  try{
    const vs=await news(); if(!vs.length)return;
    const seen=ls('slicer_seen_version',null); lsSet('slicer_seen_version',vs[0].v);
    // every version since the one this browser last saw, not only the newest: a fix that came out a day later must
    // not hide the release it fixed. A version no longer in the list shows them all
    const i=vs.findIndex(s=>s.v===seen);
    if(seen&&i!==0)showNews(i<0?vs.length:i);
  }catch(e){}                                            // no changelog beside the page: the button still works
}
// A phone gets the whole app and, once, a word that it is made for a computer: the 3D view's editing wants a mouse and
// the panels a wide screen. The browser's own flag where it has one, else the user agent's; a tablet is not a phone.
export function phoneNotice(){
  const phone=navigator.userAgentData?.mobile??/iPhone|iPod|Android.+Mobile|Windows Phone/i.test(navigator.userAgent);
  if(!phone||ls('slicer_phone_told',false))return;
  try{lsSet('slicer_phone_told',true)}catch(e){}         // a private window may refuse it: then it says so each visit
  popup('Lamina is made for a computer','',`<p>It runs on a phone, but editing in the 3D view wants a mouse (drag, shift-drag,
    right-drag) and the panels a wide screen. For the best experience, open this page on a computer.</p>`,'Continue on this phone');
}

