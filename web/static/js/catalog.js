// materials: stock thicknesses as [mm, stock name] — sheet steel by Manufacturers' Standard Gauge (the Canadian and US
// standard), aluminium by Brown & Sharpe gauge, plate / plywood / acrylic by fraction of an inch — the family that
// decides the sheet sizes, the 3D look, and the machine that usually cuts it — and its density in g/cm³, a typical
// figure for the Export tab's weight (cardboard is corrugated; solid board is greyboard), editable on the Sheet tab.
// Checked 2026-09 against suppliers and references: corrugated single-wall 0.09–0.2 by flute (grammage ÷ caliper),
// greyboard 0.62–0.75 (Golden Paper's gsm table), EVA "high density" 0.085 (the Foamory's 85 kg/m³), PS foam board
// about 0.1 (≈ 500 g/m² at 5 mm, most of it the paper faces), basswood 0.415 and balsa 0.16 (Wood Database, Timber
// Development UK), firm veg-tan leather 0.7–0.95 (IS 579 puts sole leather at ≥ 0.9)
export const IN=25.4, ga=(g,inch)=>[+(inch*IN).toFixed(3),`${g} ga`], fr=(txt,inch)=>[+(inch*IN).toFixed(3),`${txt}″`],
  oz=(n,inch)=>[+(inch*IN).toFixed(3),`${n} oz`], pt=n=>[+(n/1000*IN).toFixed(3),`${n} pt`];
export const MATERIALS={
  paper:{t:[[0.2],[0.3],[0.5]],family:'paper',look:'paper',machine:'co2',density:0.8},
  card:{t:[[0.8],[1],[1.5]],family:'paper',look:'paper',machine:'co2',density:0.75},
  cardboard:{t:[[1.5],[2],[3],[4],[5],[7]],family:'paper',look:'cardboard',machine:'co2',density:0.12},
  plywood:{t:[[3],fr('1/8',0.125),[4],[5],[6],fr('1/4',0.25),[9],fr('3/8',0.375),[12],fr('1/2',0.5),fr('5/8',0.625),[18],fr('3/4',0.75)],family:'wood',look:'plywood',machine:'co2',density:0.68},
  mdf:{t:[[3],fr('1/8',0.125),[6],fr('1/4',0.25),[9],[12],fr('1/2',0.5),[18],fr('3/4',0.75),[25]],family:'wood',look:'plywood',machine:'co2',density:0.75},
  acrylic:{t:[fr('1/16',0.0625),[2],[3],fr('1/8',0.125),[4],[5],fr('3/16',0.1875),[6],fr('1/4',0.25),[8],[10],fr('3/8',0.375),fr('1/2',0.5)],family:'plastic',look:'plastic',machine:'co2',density:1.19},
  steel:{t:[ga(22,0.0299),ga(20,0.0359),ga(18,0.0478),ga(16,0.0598),ga(14,0.0747),ga(12,0.1046),ga(11,0.1196),ga(10,0.1345),fr('3/16',0.1875),fr('1/4',0.25),fr('3/8',0.375),fr('1/2',0.5)],family:'metal',look:'steel',machine:'fiber',density:7.85},
  aluminium:{t:[ga(16,0.0508),ga(14,0.0641),ga(12,0.0808),ga(10,0.1019),fr('1/8',0.125),fr('3/16',0.1875),fr('1/4',0.25)],family:'metal',look:'steel',machine:'fiber',density:2.7},
  leather:{t:[[1.5],[2],[3]],family:'paper',look:'cardboard',machine:'co2',density:0.86},
  fabric:{t:[[0.5],[1],[2]],family:'paper',look:'paper',machine:'knife',density:0.4},
  // stainless has a gauge table of its own: 14 ga is 1.984 mm, where carbon steel's is 1.897 — a slot cut for one is
  // wrong for the other. This is the fractional-inch table most mills use (RMFG, Fabworks); some suppliers (Ryerson)
  // sell stainless on carbon steel's numbers, which is why a gauge is always worth checking with a caliper
  'stainless steel':{t:[ga(24,0.025),ga(22,0.0312),ga(20,0.0375),ga(18,0.05),ga(16,0.0625),ga(14,0.0781),ga(12,0.1094),ga(11,0.125),ga(10,0.1406),[1],[1.5],[2],[3],fr('3/16',0.1875),fr('1/4',0.25),fr('3/8',0.375)],family:'metal',look:'steel',machine:'fiber',density:7.93},
  brass:{t:[fr('0.020',0.02),fr('0.032',0.032),fr('0.040',0.04),fr('0.064',0.064),fr('1/8',0.125),[0.5],[1],[1.5],[2],[3]],family:'metal',look:'brass',machine:'fiber',density:8.5},
  // copper sheet is sold by weight: ounces per square foot, at the thicknesses of Alaskan Copper's chart
  copper:{t:[oz(16,0.0216),oz(20,0.027),oz(24,0.032),oz(32,0.043),oz(48,0.0647),[0.5],[1],[1.5],[2],[3]],family:'metal',look:'copper',machine:'fiber',density:8.96},
  // chipboard in North America is sold by points (thousandths of an inch), greyboard in Europe by millimetres
  greyboard:{t:[[1],pt(50),[1.5],[2],pt(80),[2.5],[3]],family:'paper',look:'cardboard',machine:'co2',density:0.7},
  polypropylene:{t:[[0.5],[0.8],[1],[1.5],[2],[3],fr('1/8',0.125),[5],[6],fr('1/4',0.25),[10]],family:'plastic',look:'plastic',machine:'co2',density:0.9},
  // foam board's polystyrene core melts and burns under a laser, so it is cut by hand
  'foam board':{t:[[3],fr('3/16',0.1875),[5],[10],fr('1/2',0.5)],family:'foam',look:'paper',machine:'hand',density:0.1},
  'EVA foam':{t:[[2],[3],[4],[5],[6],[8],[10]],family:'foam',look:'foam',machine:'co2',density:0.085},
  basswood:{t:[fr('1/32',0.03125),fr('1/16',0.0625),fr('3/32',0.09375),fr('1/8',0.125),fr('3/16',0.1875),fr('1/4',0.25),[1],[1.5],[2],[3]],family:'craft',look:'plywood',machine:'co2',density:0.42},
  balsa:{t:[fr('1/32',0.03125),fr('1/16',0.0625),fr('3/32',0.09375),fr('1/8',0.125),fr('3/16',0.1875),fr('1/4',0.25),fr('3/8',0.375),[1],[2],[3],[5]],family:'craft',look:'plywood',machine:'co2',density:0.16},
  // printed, not cut: every part flat on the bed at full size. The thicknesses are whole layers of a 0.4 mm nozzle
  // at 0.2 mm, and the densities are the solid plastic's (PLA 1.24, PETG 1.27) — a plate a few mm thick prints solid
  // from its walls and top and bottom layers; a thicker one at low infill weighs less, so lower the density for it
  PLA:{t:[[0.8],[1.2],[1.6],[2],[2.4],[3],[4],[5],[6]],family:'print',look:'plastic',machine:'fdm',density:1.24},
  PETG:{t:[[0.8],[1.2],[1.6],[2],[2.4],[3],[4],[5],[6]],family:'print',look:'plastic',machine:'fdm',density:1.27}};
// machines: the cut compensation belongs here, not to the material (kerf and slot offset in mm)
const CO2_CUTS=['paper','card','cardboard','greyboard','plywood','mdf','basswood','balsa','acrylic','polypropylene','EVA foam','leather','fabric'];
// diode lasers: they cut thin wood, card, foam and leather slowly and do not cut clear or translucent plastic at all
// (it passes the blue light straight through), so acrylic and polypropylene are deliberately not in their list
const DIODE_CUTS=['paper','card','cardboard','greyboard','plywood','mdf','basswood','balsa','EVA foam','leather','fabric'];
const METAL_CUTS=['steel','stainless steel','aluminium','brass','copper'];     // fiber and plasma: anything that conducts
const ROUTER_CUTS=['plywood','mdf','basswood','acrylic','polypropylene'];
// the deep-cut blade of a Cricut Maker or Cameo takes board, balsa and foam up to about 2.4 mm
const KNIFE_CUTS=['paper','card','greyboard','balsa','polypropylene','EVA foam','fabric','leather'];
const PRINT_CUTS=Object.keys(MATERIALS).filter(k=>MATERIALS[k].family==='print');   // a printer makes these, nothing cuts them
export const MACHINES={
  co2:{name:'CO2 laser',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,
    beds:[['300 × 200 mm bed',[300,200]],['400 × 400 mm bed',[400,400]],['510 × 300 mm bed',[510,300]],
          ['600 × 400 mm bed',[600,400]],['700 × 500 mm bed',[700,500]],['900 × 600 mm bed',[900,600]],['1300 × 900 mm bed',[1300,900]]]},
  fiber:{name:'fiber laser (metal)',kerf:0.2,slot:0.15,relief:'square',tool:0,cuts:METAL_CUTS,beds:[]},
  plasma:{name:'plasma (metal)',kerf:1.5,slot:0.3,relief:'square',tool:0,cuts:METAL_CUTS,beds:[]},
  router:{name:'CNC router',kerf:3.175,slot:0.2,relief:'dogbone',tool:3.175,cuts:ROUTER_CUTS,beds:[]},
  knife:{name:'knife / vinyl cutter',kerf:0,slot:0.05,relief:'square',tool:0,cuts:KNIFE_CUTS,beds:[['12 in roll',[304.8,914.4]],['24 in roll',[609.6,1219.2]]]},
  hand:{name:'by hand',kerf:0,slot:0.1,relief:'square',tool:0,cuts:Object.keys(MATERIALS).filter(k=>!PRINT_CUTS.includes(k)),beds:[]},
  fdm:{name:'3D printer (FDM)',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[]},   // no kerf; 0.2 mm slides on most FDM printers
  // Machines by name, so nobody has to translate their machine into a process first. A * means the bed size is the
  // manufacturer's published one and the kerf is an educated guess for that class of machine — nobody has measured
  // this one on your material. Pick it, then cut the fit test (Export tab) and correct kerf and slot offset: two
  // numbers, and they belong to the machine, not to us. Everything else can be typed in and saved with `+`.
  glowforge:{name:'Glowforge Basic / Plus / Pro *',kerf:0.2,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['Glowforge bed · 495 × 279 mm',[495,279]]]},
  xtool_p2:{name:'xTool P2 (55 W CO2) *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['xTool P2 bed · 600 × 308 mm',[600,308]]]},
  omtech_polar:{name:'OMTech Polar / Polar+ *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['OMTech Polar bed · 510 × 300 mm',[510,300]]]},
  k40:{name:'K40 desktop laser *',kerf:0.2,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['K40 bed · 300 × 200 mm',[300,200]]]},
  epilog:{name:'Epilog Fusion Maker 24 *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['Epilog Maker 24 bed · 610 × 305 mm',[610,305]]]},
  thunder:{name:'Thunder Laser Nova 35 *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['Nova 35 bed · 900 × 600 mm',[900,600]]]},
  trotec:{name:'Trotec Speedy 400 *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:CO2_CUTS,beds:[['Speedy 400 bed · 1000 × 610 mm',[1000,610]]]},
  xtool_s1:{name:'xTool S1 (diode) *',kerf:0.12,slot:0.1,relief:'square',tool:0,cuts:DIODE_CUTS,beds:[['xTool S1 bed · 498 × 319 mm',[498,319]]]},
  xtool_d1:{name:'xTool D1 Pro (diode) *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:DIODE_CUTS,beds:[['xTool D1 Pro bed · 430 × 400 mm',[430,400]]]},
  diode400:{name:'Atomstack / Ortur / Falcon (diode) *',kerf:0.15,slot:0.1,relief:'square',tool:0,cuts:DIODE_CUTS,beds:[['400 × 400 mm frame',[400,400]]]},
  shapeoko:{name:'Shapeoko 4 XXL (CNC) *',kerf:3.175,slot:0.2,relief:'dogbone',tool:3.175,cuts:ROUTER_CUTS,beds:[['Shapeoko 4 XXL · 838 × 838 mm',[838,838]]]},
  xcarve:{name:'X-Carve / Onefinity (CNC) *',kerf:3.175,slot:0.2,relief:'dogbone',tool:3.175,cuts:ROUTER_CUTS,beds:[['750 × 750 mm bed',[750,750]]]},
  genmitsu:{name:'Genmitsu 3018 (desktop CNC) *',kerf:3.175,slot:0.2,relief:'dogbone',tool:3.175,cuts:ROUTER_CUTS,beds:[['3018 bed · 300 × 180 mm',[300,180]]]},
  cricut:{name:'Cricut Maker / Explore *',kerf:0,slot:0.05,relief:'square',tool:0,cuts:KNIFE_CUTS,beds:[['12 × 12 in mat · 305 × 305 mm',[305,305]],['12 × 24 in mat · 305 × 610 mm',[305,610]]]},
  cameo:{name:'Silhouette Cameo 4 *',kerf:0,slot:0.05,relief:'square',tool:0,cuts:KNIFE_CUTS,beds:[['12 × 12 in mat · 305 × 305 mm',[305,305]],['12 × 24 in mat · 305 × 610 mm',[305,610]]]},
  // printers by name: the bed is the sheet, so a job nests into plates the printer can take
  bambu_h2c:{name:'Bambu Lab H2C *',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[['H2C bed · 325 × 320 mm (300 × 320 with both nozzles)',[325,320]]]},
  bambu_x1:{name:'Bambu Lab X1 / P1 / A1 *',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[['X1 / P1 / A1 bed · 256 × 256 mm',[256,256]]]},
  bambu_a1mini:{name:'Bambu Lab A1 mini *',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[['A1 mini bed · 180 × 180 mm',[180,180]]]},
  prusa_mk4:{name:'Prusa MK4S *',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[['MK4S bed · 250 × 210 mm',[250,210]]]},
  prusa_core:{name:'Prusa CORE One *',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[['CORE One bed · 250 × 220 mm',[250,220]]]},
  ender3:{name:'Creality Ender-3 V3 *',kerf:0,slot:0.2,relief:'square',tool:0,cuts:PRINT_CUTS,beds:[['Ender-3 V3 bed · 220 × 220 mm',[220,220]]]}};
// stock sheet sizes per material family: imperial stock as sold in Canada, with its mm size
const ft=(w,h)=>[w*12*IN,h*12*IN], inch=(w,h)=>[w*IN,h*IN];
export const SHEETS={
  metal:[['4 × 8 ft · 1219 × 2438 mm',ft(4,8)],['4 × 10 ft · 1219 × 3048 mm',ft(4,10)],['5 × 10 ft · 1524 × 3048 mm',ft(5,10)],['2 × 4 ft · 610 × 1219 mm',ft(2,4)],['1000 × 2000 mm',[1000,2000]],['1250 × 2500 mm',[1250,2500]],['12 × 24 in · 305 × 610 mm',inch(12,24)],['12 × 12 in · 305 × 305 mm',inch(12,12)]],
  wood:[['4 × 8 ft · 1219 × 2438 mm',ft(4,8)],['5 × 5 ft · 1524 × 1524 mm (baltic birch)',ft(5,5)],['4 × 4 ft · 1219 × 1219 mm',ft(4,4)],['2 × 4 ft · 610 × 1219 mm',ft(2,4)],['2 × 2 ft · 610 × 610 mm',ft(2,2)]],
  plastic:[['4 × 8 ft · 1219 × 2438 mm',ft(4,8)],['2 × 4 ft · 610 × 1219 mm',ft(2,4)],['24 × 24 in · 610 × 610 mm',inch(24,24)],['12 × 24 in · 305 × 610 mm',inch(12,24)],['12 × 12 in · 305 × 305 mm',inch(12,12)]],
  paper:[['A4 · 297 × 210 mm',[297,210]],['A3 · 420 × 297 mm',[420,297]],['A2 · 594 × 420 mm',[594,420]],['A1 · 841 × 594 mm',[841,594]],['A0 · 1189 × 841 mm',[1189,841]],['letter · 11 × 8.5 in',inch(11,8.5)],['tabloid · 17 × 11 in',inch(17,11)],['24 × 18 in · 610 × 457 mm',inch(24,18)],['24 × 36 in · 610 × 914 mm',inch(24,36)],['32 × 40 in · 813 × 1016 mm',inch(32,40)],['4 × 8 ft · 1219 × 2438 mm',ft(4,8)]],
  // model-making wood: balsa and basswood come in strips and small sheets, not in plywood's panels
  craft:[['12 × 24 in · 305 × 610 mm',inch(12,24)],['12 × 12 in · 305 × 305 mm',inch(12,12)],['3 × 36 in · 76 × 914 mm',inch(3,36)],['4 × 36 in · 102 × 914 mm',inch(4,36)],['6 × 24 in · 152 × 610 mm',inch(6,24)],['100 × 1000 mm',[100,1000]],['300 × 300 mm',[300,300]]],
  foam:[['20 × 30 in · 508 × 762 mm',inch(20,30)],['32 × 40 in · 813 × 1016 mm',inch(32,40)],['40 × 60 in · 1016 × 1524 mm',inch(40,60)],['A2 · 594 × 420 mm',[594,420]],['A1 · 841 × 594 mm',[841,594]],['A0 · 1189 × 841 mm',[1189,841]],['1000 × 2000 mm',[1000,2000]]],
  // print beds: one sheet is one plate
  print:[['180 × 180 mm bed',[180,180]],['220 × 220 mm bed',[220,220]],['250 × 210 mm bed',[250,210]],['256 × 256 mm bed',[256,256]],['300 × 300 mm bed',[300,300]],['325 × 320 mm bed',[325,320]],['350 × 350 mm bed',[350,350]]]};
// Z: the band lattice's third family, Okabe-Ito reddish purple; its label (Z-1) tells it apart as X-1 and Y-1 do
export const COLORS={X:0xd9a760,Y:0x7fb0d9,Z:0xcc79a7,S:0xd9c080,R:0x8fd08f,C:0x0072b2,F:0xc9a0e0,J:0xf0c060,P:0x9a9a9a,B:0x4fd1ff,W:0x0072b2};
// the second family of a two-family technique (radial's rings, interlocked's, curve's and a plaque's Y, folded's joint
// parts): striped, and under a material look set apart in lightness, so the two never differ by hue alone (the owner
// is colour-blind)
export const STRIPED='CYJ';
export const LOOKS={cardboard:[0xb98a5a,.9,0],paper:[0xf2f0e6,.95,0],plywood:[0xd9b98a,.7,0],steel:[0xaab2bb,.35,.8],plastic:[0x6fb7e8,.25,.05],brass:[0xc9a44c,.3,.85],copper:[0xc27a52,.3,.85],foam:[0x45484f,.95,0]};
export const PLANE_IDX={xz:[0,2],yz:[1,2],xy:[0,1]};
