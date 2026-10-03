// Drive the running app in headless Edge over CDP and record the stills and clip frames the landing page uses.
//     uv run python scripts/media/record.py [scene ...]     starts the server and the browser, runs this, encodes
//     node scripts/media/capture.mjs [scene ...]            this alone, against a browser already on CDP_PORT
// capture.ps1 starts the server (:8010) and the browser (CDP :9222) first. For a quick look during a review, run
// probe.ps1 once (Edge on CDP :9223 against the dev server on :8000) and then `$env:CDP_PORT=9223; node capture.mjs hero`.
// Every scene's parameters were searched with param_search.py: they slice with no error and no warning.
import fs from "node:fs";
const OUT = "working-files/shots";
fs.mkdirSync(OUT, { recursive: true });
const PORT = process.env.CDP_PORT || 9222;

const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
const page = list.find(t => t.type === "page" && /127\.0\.0\.1:\d+/.test(t.url));
if (!page) { console.log("no page tab", list.map(t => t.url)); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0; const pending = {};
const send = (method, params = {}) => new Promise(res => { pending[++id] = res; ws.send(JSON.stringify({ id, method, params })); });
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending[m.id]) { pending[m.id](m.result); delete pending[m.id]; } };
await new Promise(r => ws.onopen = r);
// same layout, twice the pixels: the page shows the stills at up to 1100 CSS px on HiDPI screens
await send("Emulation.setDeviceMetricsOverride", { width: 1574, height: 907, deviceScaleFactor: 2, mobile: false });

const js = async expr => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description || "") + "\n" + expr); return r.result.value; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const until = async (expr, tries = 400) => { for (let i = 0; i < tries; i++) { if (await js(expr)) return true; await sleep(500); } throw new Error("timeout: " + expr); };
const settle = async () => { await sleep(600); await until("!document.querySelector('#dot').classList.contains('busy')", 960); await sleep(400); };   // the fine-remeshed head takes ~30 s a slice
const png = async (name, clip) => { const s = await send("Page.captureScreenshot", { format: "png", ...(clip ? { clip } : {}) }); fs.writeFileSync(`${OUT}/${name}.png`, Buffer.from(s.data, "base64")); };
const shot = async name => { await png(name); await project(name); console.log("shot", name, await verdict()); };
// the scene as a project file (what "save project" writes, minus the model: it names the bundled example),
// so a reviewer can open it in the app and see exactly this
fs.mkdirSync("working-files/review", { recursive: true });
const project = async name => fs.writeFileSync(`working-files/review/${name}.lamina.json`, await js(`JSON.stringify({version:3,name:'Lamina demo ${name}',rev:'1.0',mode:location.hash.slice(1),unit:window.__t.state().units||'mm',state:window.__t.state(),example:document.querySelector('#example').value})`));

// one parameter by its name: number / range / select / checkbox; a vector sets p_name_0, p_name_1, ...
// (the form listens for 'input' delegated, the view controls for 'change' — fire both)
const set = async (name, v) => {
    if (Array.isArray(v)) { for (let i = 0; i < v.length; i++) await set(`${name}_${i}`, v[i]); return; }
    await js(`(()=>{const s=document.querySelector('#p_${name}')||document.querySelector('#${name}');if(!s)throw new Error('no field ${name}');
        if(s.type==='checkbox')s.checked=${JSON.stringify(!!v)};else s.value=${JSON.stringify(String(v))};
        for(const e of ['input','change'])s.dispatchEvent(new Event(e,{bubbles:true}))})()`);
};
// every scene starts from the same model preparation, so nothing leaks from the scene before (rotate, size, per-slice fixes)
const BASE = { rotate: [0, 0, 0], size: [0, 0, 0], round: 0, thicken: 0, shrinkwrap: 0, smooth: 0, thickness: 3, autofix: "add" };
const params = async p => {
    // every per-slice edit and every slice autofix added: none of it belongs to the next scene or sweep state
    await js("Object.assign(window.__t.state(),{grow:{},offset:{},tilt:{},roll:{},thick:{},skip:[],extra_x:[],extra_y:[],dowels:[],axes:[]})");   // axes: the snowman's preset has three; a scene asks for its own
    for (const [k, v] of Object.entries({ ...BASE, ...p })) await set(k, v);
    await settle();
};
// what the fix buttons do (grow an outline, move a slice) and the curve control points, applied as the app applies them
const fix = async set => { await js(`window.__t.applyFix(${JSON.stringify(set)})`); await settle(); };
// whatever warning is left on screen, take the app's own first offer for it (grow the outline, move the slice),
// one at a time, as a user would: the project file then carries those fixes too
const heal = async (rounds = 12) => {
    const seen = {};
    for (let r = 0; r < rounds; r++) {
        const b = await js(`(()=>{const b=[...document.querySelectorAll('#lower .msg .fix')].find(x=>/^(grow|move) /.test(x.textContent));return b?{text:b.textContent,set:JSON.parse(b.dataset.fix)}:null})()`);
        if (!b) break;
        // a button sets its value rather than adding to it, so the same offer a second time is applied doubled
        const n = seen[b.text] = (seen[b.text] || 0) + 1;
        if (n > 1) for (const v of Object.values(b.set)) if (v && typeof v === "object") for (const k of Object.keys(v)) v[k] *= n;
        console.log("  fix:", b.text, n > 1 ? `x${n}` : ""); await fix(b.set);
    }
};
// the base preparation goes in before the switch: the new mode slices at once with its remembered parameters, and
// e.g. round 3 + a remembered facet 0 would unfold a remeshed 100k-triangle cube (never finishes)
const mode = async m => { await params({}); await js(`document.querySelector('#modes button[data-m=${m}]').click()`); await settle(); };
const example = async e => { await js(`(()=>{const s=document.querySelector('#example');s.value='${e}';s.dispatchEvent(new Event('change'))})()`); await settle(); };
const tab = async t => { await js(`document.querySelector('nav button[data-t=${t}]').click()`); await sleep(300); };
const cam = (az, el, d) => js(`window.__t.cam(${az},${el},${d ?? "null"})`);
const fit = async () => { await js("document.querySelector('#fit').click()"); await sleep(300); };
// fit, then pull the camera in so the model fills the frame, optionally pulling the parts apart a little
const view = async (az, el, zoom = 1.0, explode = 1) => {
    await fit();
    await set("explode", explode);
    const d = await js("window.__t.camera.position.length()");
    await cam(az, el, d * zoom); await sleep(400);
};
// errors / warnings of the plan on screen, and the prototype scale that keeps every piece inside a Bambu H2C bed
// (325 x 320 mm; 300 used so there is a margin)
const verdict = () => js(`(()=>{const p=window.__t.plan(),c=p.counts;const big=Math.max(...p.slices.flatMap(s=>s.pieces.map(q=>Math.max(q.bbox[2]-q.bbox[0],q.bbox[3]-q.bbox[1]))));
    return c.parts+' parts E'+c.errors+' W'+c.warnings+' biggest '+big.toFixed(0)+' mm, H2C prototype scale <= '+(300/big).toFixed(2)})()`);
// a technique card clip: a slow orbit, then the parameters that matter, one value after another, still orbiting
// recorded in the "3D only" view, whose full-height viewport is nearly 4:3 (make_media crops it to exactly that)
const techClip = async (name, az, el, zoom, steps) => {
    await set("viewmode", "only3d"); await sleep(600); await fit();
    const d = await js("window.__t.camera.position.length()"); await cam(az, el, d * zoom); await sleep(300);
    fs.rmSync(`${OUT}/${name}`, { recursive: true, force: true });   // a shorter take must not keep the old one's tail
    fs.mkdirSync(`${OUT}/${name}`, { recursive: true }); let i = 0;
    const frame = async () => { await cam(az, el); az += 1.5; const s = await send("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(`${OUT}/${name}/${String(i++).padStart(3, "0")}.png`, Buffer.from(s.data, "base64")); };
    for (let k = 0; k < 30; k++) await frame();
    for (const [label, fn] of steps) {
        await fn(); await settle(); console.log(`  ${name}: ${label}`, await verdict());
        for (let k = 0; k < 16; k++) await frame();
    }
    console.log("clip", name, i, "frames");
    await set("viewmode", "both"); await sleep(400);
};
const clip = async (name, n, step) => {
    fs.rmSync(`${OUT}/${name}`, { recursive: true, force: true });
    fs.mkdirSync(`${OUT}/${name}`, { recursive: true });
    for (let i = 0; i < n; i++) {
        await step(i);
        const s = await send("Page.captureScreenshot", { format: "png" });
        fs.writeFileSync(`${OUT}/${name}/${String(i).padStart(3, "0")}.png`, Buffer.from(s.data, "base64"));
    }
    console.log("clip", name, n, "frames", await verdict());
};

// ---------------------------------------------------------------- scenes
// the head scan comes face-up with the neck along -y: rotate x 90° stands it up facing the camera
// round 3 drops the thin bits (ears, neck) no slot can hold — at 1 mm voxels plus Taubin smoothing, so the outlines
// stay as smooth as the scan instead of stair-stepping
const HEAD = { rotate: [90, 0, 0], round: 3, shrinkwrap: 1.0, smooth: 6 };
// interlocked head: the three edge slices through the ears keep a bridge under 2 mm; grown as the fix buttons do
const INTERLOCKED = { p: { ...HEAD, nx: 12, ny: 9 }, fix: {} };          // the thin bridges left are grown by heal()
const S = {};
S.hero = async () => {        // radial head, face forward: also the model tab and the export tab
    await example("head_igea"); await mode("radial"); await tab("technique");
    await params({ ...HEAD, count: 14, ring_count: 6 }); await heal();     // the example's preset
    await view(-60, 22, 0.95); await shot("hero");
    await tab("model"); await sleep(500); await view(-50, 16, 0.95); await shot("model");
    await tab("export"); await set("pr_size", 280); await sleep(400); await shot("export");   // 280 mm prototype: fits the H2C bed
    await tab("technique");
};
S.stacked = async () => {     // horse in layers with a gap, square dowels at random points; bigger so the dowels fit the legs
    await example("horse"); await mode("stacked"); await tab("technique");
    await params({ axis: "z", size: [0, 300, 0], connect: "dowel", dowel_shape: "square", placement: "random", space: 6, dowel_d: 3, n_points: 2, round: 3, thicken: 1 }); await heal();
    await view(-55, 14, 1.05, 1.0); await project("stacked");      // assembled, never exploded: a clip must show the finished object
    await techClip("stacked", -55, 14, 1.0, [["no gap", () => set("space", 0)], ["gap 12", () => set("space", 12)], ["gap 6", () => set("space", 6)]]);
};
S.interlocked = async () => {  // the torus: every vertical line meets the tube once, so the egg-crate assembles; the head's ears never let it
    await example("torus"); await mode("interlocked"); await tab("technique");
    await params({ nx: 9, ny: 7 }); await heal();
    await view(-55, 30, 0.9, 1.0); await project("interlocked");
    await techClip("interlocked", -55, 30, 0.9, [["6 x 5", async () => { await set("nx", 6); await set("ny", 5); }], ["12 x 9", async () => { await set("nx", 12); await set("ny", 9); }],
        ["9 x 7", async () => { await set("nx", 9); await set("ny", 7); }]]);
};
// One axis, on a shape that has one centre line and looks it: the scanned head. The snowman used to be here, and a
// shape with two bellies about a single axis is exactly the job the scene below is for — one card each, so neither
// picture teaches the wrong thing.
S.radial = async () => {
    await example("head_igea"); await mode("radial"); await tab("technique");
    await params({ ...HEAD, count: 10, ring_count: 6 }); await heal();
    await view(-50, 18, 1.05, 1.0); await project("radial");
    await techClip("radial", -50, 18, 1.0, [["6 slices", () => set("count", 6)], ["14 slices", () => set("count", 14)], ["10 slices", () => set("count", 10)],
        ["3 rings", () => set("ring_count", 3)], ["9 rings", () => set("ring_count", 9)], ["6 rings", () => set("ring_count", 6)]]);
};
// radial with an axis per lobe: the dumbbell's two balls, the plane between them at the neck (the bundled presets)
const DUMBBELL = [[[-72, 0, -108], [72, 0, -108]], [[0, 0, 36], [0, 0, 180]]];   // at right angles: across the lower ball, up the upper one
const SNOWMAN = [[[0.7, -2, -168], [0.7, -2, -5.7]], [[16.8, 3.6, -5.7], [16.8, 3.6, 97.6]], [[36.6, 10.4, 97.6], [36.6, 10.4, 168]]];
S.axes = async () => {        // technique card: the two-axis dumbbell orbiting, then one axis through both, back to two, the neck plane moved and tilted
    await example("dumbbell"); await mode("radial"); await tab("technique");
    await params({ count: 8, ring_count: 4 }); await fix({ axes: DUMBBELL });
    await view(-50, 18, 1.0, 1.0); await project("axes");
    await techClip("axes", -50, 18, 1.0, [["one axis through both balls", () => fix({ axes: [] })], ["an axis through each ball", () => fix({ axes: DUMBBELL })],
        ["the neck plane raised 30 mm", () => fix({ offset: { "B-1-2": 30 } })], ["and tilted 15 deg", () => fix({ tilt: { "B-1-2": 15 } })],
        ["back at the neck", () => fix({ offset: { "B-1-2": 0 }, tilt: { "B-1-2": 0 } })]]);
};
S.lobes = async () => {       // the plane between two lobes is a part: select it, slide it up the waist, tilt it — sliders and all in frame
    await example("snowman"); await mode("radial"); await tab("technique");
    await params({ count: 6, ring_count: 3 }); await fix({ axes: SNOWMAN });
    await view(-55, 16, 0.95); await sleep(200);
    await js("window.__t.select('B-1-2')"); await sleep(400);
    await clip("lobes", 46, async i => {
        if (i === 0) return;
        if (i < 15) { await js(`(()=>{const r=document.querySelector('#r_offset');r.value=${i};r.dispatchEvent(new Event('input'))})()`); }
        else if (i === 15) { await js("document.querySelector('#r_offset').dispatchEvent(new Event('change'))"); await settle(); }
        else if (i < 30) { await js(`(()=>{const r=document.querySelector('#r_tilt');r.value=${Math.round((i - 15) * 0.55)};r.dispatchEvent(new Event('input'))})()`); }
        else if (i === 30) { await js("document.querySelector('#r_tilt').dispatchEvent(new Event('change'))"); await settle(); }
        else await sleep(120);
    });
    await js("window.__t.deselect()"); await fix({ offset: { "B-1-2": 0 }, tilt: { "B-1-2": 0 } });
};
S.curve = async () => {       // the horse is long along y; the curve follows the back and climbs the neck to the head
    await example("horse"); await mode("curve"); await tab("technique");
    // 20 ribs on one spine: centred on the body the spine passes between the legs; a second one would cross a leg
    // and the body on one line, which no slot can assemble
    await params({ plane: "yz", count: 20, spines: 1, round: 2 });
    const CURVE = [[-85, 22], [-30, 32], [25, 30], [55, 55], [90, 74]];
    await fix({ curve: CURVE }); await heal();
    await view(-70, 16, 0.9, 1.0); await project("curve");
    await techClip("curve", -70, 16, 0.9, [["8 ribs", () => set("count", 8)], ["12 ribs", () => set("count", 12)], ["20 ribs", () => set("count", 20)],
        ["head point down", () => fix({ curve: [...CURVE.slice(0, 4), [90, 55]] })], ["head point up", () => fix({ curve: CURVE })]]);
};
S.folded = async () => {      // the cow mesh is y-up: rotate x 90° stands it up
    await example("cow"); await mode("folded"); await tab("technique");
    await params({ rotate: [90, 0, 0], joint: "tab", facet: 15, strategy: "area", thickness: 1 });
    await fix({ grow: { "P-1": 1, "P-6": 1 } }); await heal();
    await view(-60, 18, 0.85); await project("folded");
    await techClip("folded", -60, 18, 0.9, [["laced", () => set("joint", "laced")], ["rib", () => set("joint", "rib")], ["tab", () => set("joint", "tab")],
        ["facet 25", () => set("facet", 25)], ["facet 15", () => set("facet", 15)]]);
};
S.rib = async () => {         // rib closeup: a pyramid keeps every face, so five long ribs at real fold angles, and nothing else in the frame
    await example("pyramid"); await mode("folded"); await tab("technique");
    await params({ joint: "rib", facet: 0, rib_w: 40, inset: 15, thickness: 1.5 }); await heal();   // ribs big enough to read on a 240 mm pyramid
    await view(-35, 28, 1.3, 1.4);                           // pulled apart: the ribs float at their seams, each an angle piece
    await set("ghost", false); await sleep(600);
    await shot("folded_rib");
    await set("ghost", true); await set("explode", 1); await sleep(200);
    await set("facet", 15); await settle();                 // never leave facet 0 behind: the next model would unfold every raw triangle
};
// one closeup per joint: a 90 mm cube net keeps every triangle, so each joint sits on a full-size seam;
// the shot is the panel itself (its placed outline on the first sheet), not the whole sheet
const JOINTS = ["seam", "tab", "multitab", "diamond", "ticked", "gear", "tongue", "puzzle", "rivet", "laced", "loops", "strip", "rib"];
S.joints = async () => {
    await example("cube"); await mode("folded"); await tab("technique");
    // a taller viewport: at full pane width the 600 x 400 sheet runs past 907 px, and the nester puts the parts at its foot
    await send("Emulation.setDeviceMetricsOverride", { width: 1574, height: 1300, deviceScaleFactor: 2, mobile: false });
    await set("viewmode", "only2d"); await sleep(600);
    await js("(()=>{const s=document.createElement('style');s.id='jointcss';s.textContent='#sheets svg path{stroke-width:0.9!important}';document.head.append(s)})()");   // hairlines read at closeup size
    for (const j of JOINTS) {
        await params({ size: [90, 0, 0], joint: j, facet: 0, inset: 6, spacing: 30, thickness: 1 });
        // the pieces only (the scale-check bar carries a label too), on the first sheet
        const c = await js(`(()=>{const svg=document.querySelector('#sheets svg'),s=svg.getBoundingClientRect();const rs=[...svg.querySelectorAll('path[data-label]')].filter(p=>/^[A-Z]-\\d/.test(p.dataset.label)).map(p=>p.getBoundingClientRect());
            const x0=Math.max(s.left+2,Math.min(...rs.map(r=>r.left))-40),y0=Math.max(s.top+2,Math.min(...rs.map(r=>r.top))-20),x1=Math.min(s.right-2,Math.max(...rs.map(r=>r.right))+40),y1=Math.min(s.bottom-2,Math.max(...rs.map(r=>r.bottom))+20);   // room for the part labels beside the parts
            return {x:x0,y:y0,width:x1-x0,height:y1-y0,scale:1}})()`);
        await png(`joint_${j}`, c); console.log("shot joint_" + j, await verdict());
    }
    await js("document.getElementById('jointcss').remove()");
    await set("facet", 15); await settle();                 // leave a sane facet in the folded memory
    await set("viewmode", "both"); await sleep(400);
    await send("Emulation.setDeviceMetricsOverride", { width: 1574, height: 907, deviceScaleFactor: 2, mobile: false });
};
S.sheets = async () => {
    await example("egg"); await mode("interlocked"); await tab("technique"); await params({ nx: 5, ny: 4 });
    await set("viewmode", "only2d"); await sleep(700); await shot("sheets");
    await set("viewmode", "both"); await sleep(400);
};
S.checks = async () => {      // the one still that is meant to show errors: the checks tab with its fix buttons
    await example("cow_spot"); await mode("interlocked"); await tab("technique"); await params({ nx: 7, ny: 5, autofix: "off" });
    await tab("checks"); await sleep(400); await shot("checks");
    await set("autofix", "add"); await settle(); await tab("technique");
};
S.square = async () => {      // a cube left 8° off square cuts every straight edge as a staircase; one click squares it
    await example("cube"); await mode("stacked"); await tab("model");     // the note and its button sit under the rotate controls
    await params({ axis: "z", connect: "dowel", placement: "aligned", rotate: [8, 0, 0] });
    console.log("  square: tilted", await verdict(), await js("JSON.stringify(window.__t.plan().square)"));
    await view(-55, 16, 1.0);
    const d = await js("window.__t.camera.position.length()"); let az = -55;
    await clip("square", 56, async i => {
        await cam(az += 0.8, 16, d);
        if (i === 24) { await js("document.querySelector('#square button').click()"); await settle(); }
        else await sleep(60);
    });
    await project("square");
    await tab("technique");
};
S.orbit = async () => {       // orbit around the interlocked head, then build it up part by part and explode it
    await example("torus"); await mode("interlocked"); await tab("technique"); await params({ nx: 9, ny: 7 }); await heal();
    await set("viewmode", "only3d"); await sleep(600); await fit();
    const dist = (await js("window.__t.camera.position.length()")) * 0.95;
    await clip("orbit", 72, async i => { await cam(-60 + i * 5, 18 + 8 * Math.sin(i / 12), dist); });
    const nparts = await js("window.__t.parts().length");
    await cam(-60, 18, dist);
    await clip("assembly", 60, async i => {
        if (i < 34) { await set("steps", Math.round((i + 1) * nparts / 34)); }
        else { const t = (i - 34) / 25; await set("explode", (1 + 1.1 * Math.sin(t * Math.PI)).toFixed(2)); }
    });
    await set("explode", 1); await set("steps", nparts);
    await set("viewmode", "both"); await sleep(500);
};
S.edit = async () => {        // move the slice nearest the camera, so the whole part and its arrow stay in view
    await example("egg"); await mode("interlocked"); await tab("technique"); await params({ nx: 5, ny: 4 });
    await view(-55, 20, 0.95); await sleep(200);
    // camera sits on the -y side: the frontmost slice lying in the xz plane is the y-family part nearest the camera
    const lab = await js(`(()=>{const c=window.__t.camera.position;const ps=window.__t.parts().filter(m=>Math.abs(m.userData.normal.y)>0.9);
        ps.sort((a,b)=>a.userData.origin.distanceTo(c)-b.userData.origin.distanceTo(c));return ps[0].userData.slice})()`);
    await js(`window.__t.select('${lab}')`); await sleep(400);
    // slide it inward (outward it would leave the egg and be dropped), a little, then tilt it
    const sign = await js(`(()=>{const m=window.__t.parts().find(p=>p.userData.slice==='${lab}');const c=window.__t.camera.position.clone().sub(m.userData.origin);return -(Math.sign(c.dot(m.userData.normal))||1)})()`);
    console.log("edit clip moves", lab, "inward, sign", sign);
    await clip("edit", 40, async i => {
        if (i === 0) return;
        if (i < 14) { await js(`(()=>{const r=document.querySelector('#r_offset');r.value=${sign} * ${Math.round(i * 0.7)};r.dispatchEvent(new Event('input'))})()`); }
        else if (i === 14) { await js("document.querySelector('#r_offset').dispatchEvent(new Event('change'))"); await settle(); }
        else if (i < 28) { await js(`(()=>{const r=document.querySelector('#r_tilt');r.value=${Math.round((i - 14) * 0.55)};r.dispatchEvent(new Event('input'))})()`); }
        else if (i === 28) { await js("document.querySelector('#r_tilt').dispatchEvent(new Event('change'))"); await settle(); }
        else await sleep(120);
    });
    await js("window.__t.deselect()");
};

await send("Page.reload"); await sleep(4000);              // a fresh tab: the last run may have left it mid-request
await until("document.querySelector('#stats').textContent.includes('parts')");
await js("document.querySelector('#pname').value='Lamina demo';document.querySelector('#pname').dispatchEvent(new Event('input'))");
const want = process.argv.slice(2);
for (const name of want.length ? want : Object.keys(S)) {
    if (!S[name]) { console.log("no scene", name); continue; }
    try { await S[name](); } catch (e) { console.log("scene", name, "failed:", e.message); }
}
console.log("done");
ws.close(); process.exit(0);
