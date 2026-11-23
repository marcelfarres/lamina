import {state, ST} from './state.js';
import {MATERIALS, SHEETS, IN, MACHINES} from './catalog.js';
import {ls, $, esc} from './util.js';
import {DU, DUNIT} from './units.js';
import {applyLook} from './scene.js';

// presets: manufacturing (sheet+fit params), materials, sheets — builtin + user (this browser)
export const PKEYS=()=>['material','density','machine',...ST.mode.common.filter(p=>p.group==='sheet'||p.group==='fit').map(p=>p.name)];
export function renderPresets(sel=''){const ps=ls('slicer_presets',{});$('#presets').innerHTML='<option value="">— none —</option>'+Object.keys(ps).sort().map(n=>`<option ${n===sel?'selected':''}>${n}</option>`).join('')}
// materials of your own (this browser) sit beside the built-ins in the same shape, keyed by the name you gave them;
// `base` is the built-in they were made from, which is what the machines' `cuts` lists name. A material nobody here
// knows (a stranger's project file) is handled like cardboard, but keeps its own name and the density it came with.
export const userMaterials=()=>ls('slicer_materials',{});
export const matOf=k=>MATERIALS[k]||userMaterials()[k]||MATERIALS.cardboard, kind=k=>userMaterials()[k]?.base||k;
// density in g/cm³: what this job set for its material, else the list's figure — keyed by material, so a preset or a
// project that switches the material can never carry another material's density with it
export const dens=()=>state.density?.[state.material]??matOf(state.material).density;
export const fam=()=>matOf(state.material).family||'paper';
// sheets for the current material: its family's stock sizes, the beds of the machine in use, and the user's own for that family
export const shs=()=>[...(SHEETS[fam()]||[]),...(machineOf(state.machine)?.beds||[]),...ls('slicer_sheets',[]).filter(s=>!s[2]||s[2]===fam())];
const thickLabel=([mm,name])=>`${name?name+' · ':''}${+mm.toFixed(3)} mm · ${(mm/IN).toFixed(3)} in`;
export const matThicks=m=>{const seen=new Map();for(const e of [...(matOf(m).t||[]),...(ls('slicer_thick',{})[m]||[]).map(t=>[t])])if(!seen.has(e[0]))seen.set(e[0],e);return [...seen.values()].sort((a,b)=>a[0]-b[0])};
// machines of your own (this browser) sit beside the built-ins in the same shape, keyed by the name you gave them
export const userMachines=()=>ls('slicer_machines',{});
export const machineOf=k=>MACHINES[k]||userMachines()[k];
const machinesFor=m=>[...Object.keys(MACHINES),...Object.keys(userMachines())].filter(k=>machineOf(k).cuts.includes(m));
export const sameSheet=(a,b)=>a&&b&&Math.abs(a[0]-b[0])<0.01&&Math.abs(a[1]-b[1])<0.01;
export function applyMachine(k){const x=machineOf(k);if(!x)return;state.machine=k;state.kerf=x.kerf;state.slot_offset=x.slot;state.relief=x.relief;state.tool_d=x.tool;
  gapForBit();if(x.beds.length===1)state.sheet=[...x.beds[0][1]]}    // a machine by name has one bed, and that is the sheet
// a bit cuts its own width round each part: parts closer than that are cut into by their neighbour's path. Twice the
// bit leaves room for both paths and a holding tab; the plan warns below one bit
export const gapForBit=()=>{if(state.tool_d>0)state.gap=Math.max(state.gap??0,2*state.tool_d)};
export function syncPresetSelects(){
  const m=state.material||(state.material='cardboard'); if(!machineOf(state.machine)?.cuts.includes(kind(m)))state.machine=matOf(m).machine;
  // the 3D look follows the material however it changed (an example, a project, undo): cardboard, the default, shows
  // by family as a fresh page does, any other material its own look. The picker sets the look itself and notes it in
  // ST.lookOf, so a look chosen by hand stays while the material does. Left to the picker alone, a cardboard job
  // opened after fold_lamp (PETG) showed as blue plastic (bug 057)
  if(m!==ST.lookOf){ST.lookOf=m;$('#look').value=m==='cardboard'?'group':matOf(m).look;applyLook()}
  const names=[...new Set([...Object.keys(MATERIALS),...Object.keys(userMaterials()),m])];   // m last: kept even when nobody here knows it
  $('#material').innerHTML=names.map(n=>`<option value="${esc(n)}" ${n===m?'selected':''}>${esc(n)}</option>`).join('');
  // the density box shows the stored g/cm³ in the unit on show and is never read back, so switching units cannot drift it
  $('#density').value=+(dens()*DU()).toPrecision(4); $('#density').previousElementSibling.textContent=`density (${DUNIT()})`;
  $('#machine').innerHTML=machinesFor(kind(m)).map(k=>`<option value="${esc(k)}" ${k===state.machine?'selected':''}>${esc(machineOf(k).name)}</option>`).join('');
  $('#thicklist').innerHTML='<option value="">— pick —</option>'+matThicks(m).map(e=>`<option value="${e[0]}" ${Math.abs(e[0]-state.thickness)<1e-6?'selected':''}>${thickLabel(e)}</option>`).join('');
  $('#sheetpreset').innerHTML='<option value="">— pick —</option>'+shs().map(([n,s],i)=>`<option value="${i}" ${sameSheet(s,state.sheet)?'selected':''}>${n}</option>`).join('');
}

