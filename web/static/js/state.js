export const state={};   // the form's values: mutated in place, never reassigned
// Everything that is reassigned while the page runs, and read or written from more than one module: ES modules cannot
// reassign another module's binding, so these are properties of one shared object.
export const ST={
  MODES:[],
  PROJECT_VERSION:0,
  mode:null,
  job:null,
  plan:null,
  seq:0,
  timer:null,
  pendingFile:null,
  srcFile:null,
  unit:'mm',
  selected:null,
  busy:false,
  busySince:0,
  trail:[],
  trailT0:Date.now(),
  fresh:'',
  ghostLive:false,
  fitted:false,
  dirty:true,
  countUse:()=>{}};
