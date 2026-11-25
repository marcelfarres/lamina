import {state, ST} from './state.js';
import {$, $$} from './util.js';
import {highlight} from './edit3d.js';
import {renderFields, lenBoxes} from './form.js';
import {parts} from './scene.js';
import {renderReport, renderSheets} from './results.js';

export const UNIT={mm:1,cm:0.1,in:1/25.4};
// ---------------------------------------------------------------- tooltips (one floating box, never clipped)
const tip=$('#tip');
// help is written in mm; it reads in the unit on show
document.addEventListener('mouseover',e=>{const k=e.target.closest('[data-tip]');if(!k)return;tip.textContent=inUnit(k.dataset.tip);tip.hidden=false;const r=k.getBoundingClientRect();tip.style.left=Math.min(r.left,innerWidth-340)+'px';tip.style.top=(r.bottom+6)+'px'});
document.addEventListener('mouseout',e=>{if(e.target.closest('[data-tip]'))tip.hidden=true});

export const isLen=p=>p.unit==='mm', fmt=v=>+(+v).toPrecision(5);
// ---------------------------------------------------------------- units
// Every length is held in mm, exactly as typed, and only shown in the unit on the toolbar. Nothing is ever read back
// from what is on screen, so switching units any number of times leaves every value exactly where it was.
const DEC={mm:3,cm:4,in:4};                                     // decimals shown: 0.001 mm, 0.0001 cm, 0.0001 in
export const inU=v=>+(+v*UNIT[ST.unit]).toFixed(DEC[ST.unit]);              // mm → the number shown
export const toMM=v=>+(v/UNIT[ST.unit]).toPrecision(12);                 // typed → mm, float noise off: 0.25 in is 6.35 mm, not 6.3500000000000005
export const show=(p,v)=>isLen(p)?inU(v):fmt(v), fromU=(p,v)=>isLen(p)?toMM(v):v;
// an inch length that is an exact 64th reads as the fraction it is sold by (1/8 in, 1 1/2 in); whole inches stay plain
function frac(x){const a=Math.abs(x)*64,n=Math.round(a);if(Math.abs(a-n)>1e-6||n%64===0)return null;
  let d=64,m=n;while(m%2===0){m/=2;d/=2}const w=Math.floor(m/d);return `${x<0?'−':''}${w?w+' ':''}${m%d}/${d}`}
export const lenTxt=v=>ST.unit==='in'&&frac(v*UNIT.in)||inU(v);          // a length in running text
export const fmtLen=v=>`${lenTxt(v)} ${ST.unit}`;
// Steps are the unit's own round numbers (1, 2 or 5 of a decade), never a converted 0.003937 in: the arrows then walk
// 0.12 → 0.125 → 0.13, and min and max are put on that grid so a round value like 0.25 in is never marked invalid.
export const niceStep=x=>{const e=10**Math.floor(Math.log10(x)),m=x/e;return +((m<1.5?1:m<3.5?2:m<7.5?5:10)*e).toPrecision(6)};
export function bounds(p){if(!isLen(p)||ST.unit==='mm')return {min:p.min,max:p.max,step:p.step};
  const f=UNIT[ST.unit],st=p.step?niceStep(p.step*f):null,
    g=(v,up)=>v==null?null:st?+(Math[up?'ceil':'floor'](v*f/st+(up?-1e-9:1e-9))*st).toPrecision(6):inU(v);   // inside the range, on the grid
  return {min:g(p.min,true),max:g(p.max,false),step:st}}
// Server messages and help texts are written in mm. A run of lengths joined by × or – ("79×149 mm", "3–6 mm") shares
// the one mm at its end; an area (mm², dm²) is not a length. The raw text stays what fix buttons are matched on.
const NUM='[-−]?\\d+(?:\\.\\d+)?', MMRUN=new RegExp(`(?<![\\w.])${NUM}(?:\\s*[×–]\\s*${NUM})*\\s*mm(?![²³\\w])`,'g');
export const inUnit=s=>ST.unit==='mm'?String(s??''):String(s??'').replace(MMRUN,run=>run.replace(/\s*mm$/,'')
  .replace(new RegExp(NUM,'g'),n=>{const v=+n.replace('−','-'),t=String(lenTxt(Math.abs(v)));return (v<0?n[0]:'')+t})+' '+ST.unit).replace(/\(mm\)/g,`(${ST.unit})`);
// the one way the unit is set: one of the three, never the text it came as (a shared project file's `unit` is somebody
// else's text, and the unit is written into the page as markup in many places)
export function applyUnit(u=ST.unit){ST.unit=Object.keys(UNIT).find(k=>k===u)||'mm'; state.units=ST.unit; $('#unit').value=ST.unit; renderFields(); lenBoxes();   // renderFields redraws the spacing graphs in the unit too
  if(ST.plan&&ST.job){renderReport(); renderSheets([...$$('#sheets svg')].map(s=>s.outerHTML))}   // a job of its own: the report links to one
  const m=ST.selected&&parts.children.find(c=>c.userData.slice===ST.selected); if(m)highlight(m);   // the selection panel is written in the unit too
}
export const DU=()=>ST.unit==='in'?0.0361273:1, DUNIT=()=>ST.unit==='in'?'lb/in³':'g/cm³';   // 1 g/cm³ = 0.0361273 lb/in³
export const fmtMass=g=>ST.unit==='in'?(g<453.59237?`${+(g/28.349523125).toPrecision(3)} oz`:`${+(g/453.59237).toPrecision(3)} lb`)
                            :(g<1000?`${+g.toPrecision(3)} g`:`${+(g/1000).toPrecision(3)} kg`);
export const fmtVol=mm3=>ST.unit==='in'?`${+(mm3/16387.064).toPrecision(3)} in³`:`${+(mm3/1000).toPrecision(3)} cm³`;
// Area for buying stock: square metres with the metric units, square feet in inches — and the smaller unit while a
// sheet is small enough that 0.00x m² would not tell the reader anything (mm²: 1 m² = 1e6, 1 ft² = 92903.04).
export const fmtArea=mm2=>ST.unit==='in'?(mm2<92903.04?`${+(mm2/645.16).toPrecision(3)} in²`:`${+(mm2/92903.04).toPrecision(3)} ft²`)
                            :(mm2<1e4?`${+(mm2/100).toPrecision(3)} cm²`:`${+(mm2/1e6).toPrecision(3)} m²`);
