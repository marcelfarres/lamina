import {$, esc} from './util.js';
import {state, ST} from './state.js';
import {showLibrary, hideLibrary} from './librarypage.js';

// A guided tour of the page. A ring round one part, the rest dimmed by the ring's shadow (it takes no clicks, so the
// page stays usable under it), and a bubble beside the part with its sentence, "n / N", skip, back and next. Nothing
// is said by colour: the part is the bright one, outlined, and the bubble's arrow points at it.
// A step is {target, title, text, over, open}. open() shows the part working and returns how to put it back; that runs
// before the next step and at the end. A step whose part is not on the page, or whose open() throws, is skipped: a
// tour never stops the page. The bubble is a non-modal dialog, so the page's own Esc handlers (the library, seams)
// stand down while it is open; a modal dialog that opens (help, an error) ends the tour.
const tab=t=>()=>{$(`nav button[data-t="${t}"]`).click()};   // the tab the tour started on comes back at the end
const library=async()=>{await showLibrary();return hideLibrary};

// What is new, version by version. A row names its CHANGELOG entry by the entry's bold title: the bubble's text is that
// entry (news.js), so the notes stay the one copy. tests/ui/test_tour.py fails a row whose entry or part has gone.
export const NEW={'0.4.0':[
  {note:'Your projects in a library.', target:'#library .lbbar', open:library},
  {note:'An easier lamp, and a lantern.', target:'#libexamples .card[data-example="fold_lantern"]', open:library},
  {note:'A tidy top bar, and a tour.', target:'details.menu:has(#helpbtn) .pop',
    open:()=>{const d=$('details.menu:has(#helpbtn)');d.open=true;return()=>{d.open=false}}},
  {note:'Band lattice.', target:'#modes button[data-m="bands"]', open:tab('technique')},
  {note:'Settings that are easy to read.', target:'#level', open:()=>{tab('technique')();   // the other of basic / all, pressed
    const b=$('#level button[aria-pressed="false"]');b.click();return()=>$(`#level button:not([data-level="${b.dataset.level}"])`).click()}},
  // lit with its shadows, a model of many parts is slow on a computer without a graphics card (bugs/071): there the
  // step only points at the tick. ponytail: a part count, not a measured frame time
  {note:'Light your model.', target:'label:has(#lamp)', open:()=>{tab('light')();if(state.light||!(ST.plan?.counts.parts<=100))return;
    state.light=true;ST.light();return()=>{delete state.light;ST.light()}}},
  {note:'Tool buttons in the 3D view.', target:'#tools'},
  {note:'Clear warnings, not only colour.', target:'#report', open:tab('checks')},
  // ponytail: the Export tab is rebuilt in 0.4.0 (feature/export-tab); its own buttons become these targets
  {note:'A short Export tab.', target:'nav button[data-t="export"]', open:tab('export')},
  {note:'Print files that print right.', target:'nav button[data-t="export"]', open:tab('export')}]};

let T=null;   // the tour on show: {steps, i, undo, tab, back (focused before it), skip (its button's word), busy, r}
const ring=Object.assign(document.createElement('div'),{id:'tourring',hidden:true}), dlg=Object.assign(document.createElement('dialog'),{id:'tourdlg'});
dlg.setAttribute('aria-live','polite'); document.body.append(ring,dlg);

export function start(steps,{skip='skip the tour'}={}){
  if(T)end(); if(!steps.length)return;
  T={steps,i:-1,undo:null,tab:$('nav button.on')?.dataset.t,back:document.activeElement,skip};
  addEventListener('keydown',keys,true); go(0,1); requestAnimationFrame(follow)}

export async function end(){const t=T; if(!t)return; T=null; removeEventListener('keydown',keys,true);
  ring.hidden=true; dlg.close(); await undo(t);
  if(t.tab&&!$(`nav button.on[data-t="${t.tab}"]`))tab(t.tab)();
  t.back?.focus?.({preventScroll:true})}

const undo=async t=>{const u=t.undo;t.undo=null;try{await u?.()}catch(e){}};
// step i, or the next one on the page in the direction of travel; past either end the tour is over
async function go(i,dir){const t=T; if(!t||t.busy)return; t.busy=true; await undo(t);
  for(;i>=0&&i<t.steps.length;i+=dir){const s=t.steps[i];
    try{t.undo=await s.open?.()||null; if(T!==t)return undo(t);
      const el=$(s.target); if(!el?.getClientRects().length)throw new Error('not on the page');
      const text=typeof s.text==='function'?await s.text():s.text;
      t.i=i; t.busy=false; el.scrollIntoView({block:'center',inline:'nearest'}); return draw(s,text)}
    catch(e){console.warn('tour: step skipped,',s.target,e.message); await undo(t); if(T!==t)return}}
  t.busy=false; end()}

function draw(s,text){const t=T,n=t.i+1,N=t.steps.length;
  dlg.innerHTML=`${s.over?`<div class="ov">${esc(s.over)}</div>`:''}<h4>${esc(s.title||'')}</h4><div class="tx">${text||''}</div>
    <div class="row"><span class="n">${n} / ${N}</span><button class="skip" data-go="end">${t.skip}</button>${t.i>0?'<button data-go="-1">← back</button>':''}<button class="go" data-go="1">${n<N?'next →':'done'}</button></div>`;
  if(!dlg.open)dlg.show(); ring.hidden=false; t.r=null; place(); dlg.querySelector('.go').focus({preventScroll:true})}

// a click in the bubble stays in it: on the page it would shut the header menu a step has just opened (main.js)
dlg.addEventListener('click',e=>{e.stopPropagation(); const g=e.target.closest('[data-go]')?.dataset.go; if(!g||!T)return;
  if(g==='end')return end(); go(T.i+ +g,+g)});
// Esc ends the tour and only the tour (captured before the page's own Esc handlers); the arrows step, outside a box
function keys(e){if(!T)return;
  if(e.key==='Escape'){e.stopPropagation();e.preventDefault();return end()}
  const d={ArrowRight:1,ArrowLeft:-1}[e.key];
  if(d&&T.i+d>=0&&!e.target.closest?.('input,select,textarea')){e.stopPropagation();e.preventDefault();go(T.i+d,d)}}

// Every frame while it is open: the part is looked up again (the form is drawn anew on every change) and the ring and
// the bubble follow it through scrolling, resizing and the header wrapping. ponytail: a frame loop, observers if it
// ever shows in a profile
function follow(){if(!T)return; requestAnimationFrame(follow);
  if(document.querySelector('dialog:modal'))return end();
  if(!T.busy)place()}
function place(){const t=T,s=t?.steps[t.i],el=s&&$(s.target); if(!el)return;
  const r=el.getBoundingClientRect(),W=innerWidth,H=innerHeight,k=[r.left,r.top,r.width,r.height,W,H].join(); if(k===t.r)return; t.r=k;
  const x=Math.max(2,r.left-4),y=Math.max(2,r.top-4),X=Math.min(W-2,r.right+4),Y=Math.min(H-2,r.bottom+4);   // inside the window
  Object.assign(ring.style,{left:x+'px',top:y+'px',width:X-x+'px',height:Y-y+'px'});
  // beside the part where the bubble fits (on a phone over or under it), else inside the part at its foot
  const w=dlg.offsetWidth,h=dlg.offsetHeight,g=14,m=8,fit={right:W-X>w+g+m,left:x>w+g+m,below:H-Y>h+g+m,above:y>h+g+m};
  const side=(W<=760?['below','above']:['right','below','above','left']).find(q=>fit[q])||'inside';
  let L=side==='right'?X+g:side==='left'?x-g-w:(x+X-w)/2, U=side==='below'?Y+g:side==='above'?y-g-h:side==='inside'?Y-h-m:(y+Y-h)/2;
  L=Math.max(m,Math.min(W-w-m,L)); U=Math.max(m,Math.min(H-h-m,U));
  Object.assign(dlg.style,{left:L+'px',top:U+'px'}); dlg.dataset.side=side;
  dlg.style.setProperty('--a',(side==='right'||side==='left'?Math.max(14,Math.min(h-28,(y+Y)/2-U-7)):Math.max(14,Math.min(w-28,(x+X)/2-L-7)))+'px')}
