import {state, ST} from './state.js';
import {$} from './util.js';
import {deselect} from './edit3d.js';
import {applyUnit} from './units.js';
import {setMode, schedule} from './form.js';
import {leaveSeams} from './seams.js';

// ---------------------------------------------------------------- undo / redo
// The design is `state` + the technique + the units, so history is a stack of snapshots of exactly that, one taken per
// change that reaches the slicer: a slider drag debounces into a single step instead of one per pixel.
// ponytail: parameters only — the model (upload / example) is not on the stack, undo never swaps the model under you.
export const undos=[],redos=[]; let cur=null,restoring=false;
const snapshot=()=>JSON.stringify({m:ST.mode.name,u:ST.unit,s:state});
export function record(){
  if(restoring){restoring=false;cur=snapshot();return}                       // the slice a restore triggered is not a new step
  const now=snapshot(); if(now===cur)return;
  if(cur!==null){undos.push(cur);if(undos.length>60)undos.shift();redos.length=0;changes(cur,now).forEach(act)}
  cur=now; syncUndo();
}
// schedule(), not slice(): holding Ctrl+Z walks back several steps, and one slice of the step you land on is the
// point — a slice per step queues minutes of work in the browser build and looks like a hang
export function step(from,to){if(!from.length)return;act((from===undos?'undo: ':'redo: ')+changes(cur,from.at(-1)).join(', '));to.push(cur);const j=from.pop();cur=j;restoring=true;
  const d=JSON.parse(j); if(d.m!==ST.mode.name)setMode(d.m,false);
  for(const k of Object.keys(state))delete state[k]; Object.assign(state,d.s);
  ST.unit=d.u; deselect(); applyUnit(); syncUndo(); schedule()}
function syncUndo(){$('#undo').disabled=!undos.length;$('#redo').disabled=!redos.length}

// ---------------------------------------------------------------- what happened since the model loaded
// The state at the end rarely says how somebody got there — an example's settings kept by an upload, a ring nudged
// to 85°, a technique switched in from another's memory. So every change, undo, fix, slice and page error since the
// model was loaded is kept here with its seconds, and a bug report carries all of it (`trail` in its project file,
// the last few in its text). A saved project does not. A new model (`fresh`, read by slice()) starts it over.
export const act=s=>ST.trail.push([+((Date.now()-ST.trailT0)/1000).toFixed(1),s]);
const short=v=>{const s=JSON.stringify(v)??'—';return s.length>60?s.slice(0,57)+'…':s};
function changes(a,b){const x=JSON.parse(a),y=JSON.parse(b),out=[];
  if(x.m!==y.m)out.push(`technique ${x.m} → ${y.m}`); if(x.u!==y.u)out.push(`units ${x.u} → ${y.u}`);
  for(const k of new Set([...Object.keys(x.s),...Object.keys(y.s)]))if(JSON.stringify(x.s[k])!==JSON.stringify(y.s[k]))out.push(`${k} ${short(x.s[k])} → ${short(y.s[k])}`);
  return out}
addEventListener('error',e=>act('page error: '+e.message));
addEventListener('unhandledrejection',e=>act('page error: '+(e.reason?.message||e.reason)));
addEventListener('keydown',e=>{
  const typing=e.target.type==='text'||e.target.tagName==='TEXTAREA';   // a text box keeps its own undo, and its own ?
  // the library is a page over the app: no key changes what is behind it. The keys are still taken: the browser's
  // own undo would reach back into a text box typed in before (it refocused the library's find box and put its text back)
  const over=!$('#library').hidden;
  if(e.key==='?'&&!typing&&!e.ctrlKey&&!e.metaKey){if(!over)$('#helpdlg').showModal();return e.preventDefault()}
  if(!over&&e.key==='Escape'&&!typing&&!document.querySelector('dialog[open]')&&leaveSeams())return;
  if(!(e.ctrlKey||e.metaKey)||typing)return;
  const k=e.key.toLowerCase();
  if(k==='z'&&!e.shiftKey){if(!over)step(undos,redos)} else if(k==='y'||(k==='z'&&e.shiftKey)){if(!over)step(redos,undos)} else return;
  e.preventDefault();
});

