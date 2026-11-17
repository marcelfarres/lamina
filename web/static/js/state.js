export const state={};   // the form's values: mutated in place, never reassigned
// Everything that is reassigned while the page runs, and read or written from more than one module: ES modules cannot
// reassign another module's binding, so these are properties of one shared object.
export const ST={
  MODES:[],
  PROJECT_VERSION:0,
  mode:null,
  job:null,
  example:'',   // the bundled example last opened: the dropdown shows it, and is not what the page reads
  // {name, rev, snap, file, store, mtime}: what this tab opened or last saved (library.js); null for an upload. Mirrored in
  // sessionStorage on every change, whoever makes it, so a refresh restores it and a stale copy never outlives it
  _saved:null,
  get saved(){return this._saved},
  set saved(v){this._saved=v;try{sessionStorage.lamina_saved=JSON.stringify(v)}catch(e){}},
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
