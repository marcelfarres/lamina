"""Web UI + API.  Run from the repo root:   uv run uvicorn web.app:app --reload --port 8000

Every request carries a client id — a random secret the browser tab keeps — and everything that client makes lives
under working-files/jobs/<client>/, so several people can use one server without seeing each other's work.

POST /api/slice        multipart: client, mode, params=<json>, and one of  model=<file> | example=<name> | job=<id> (re-slice the same model)
                       → {job, plan (with 3D facets + sheet placement), sheets: [svg…], model: url of the processed mesh (STL)}
GET  /api/modes        mode schemas (drive the form)
GET  /api/examples     bundled test models
GET  /api/session?client=<id>                                                  → what that client sliced last
GET  /api/progress?client=<id>                                                 → the stage the client's slice is in
GET  /api/job/{client}/{job}/export?fmt=svg,dxf,pdf,eps&labels=1&per_piece=0   → zip of cut files
GET  /api/job/{client}/{job}/stl?part=<label>                                  → assembled solid (or one part) as STL
"""

from __future__ import annotations
import base64, contextlib, hashlib, io, json, os, pathlib, re, shutil, tempfile, threading, time, zipfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from core import plan as plan_module
from core.plan import build, MODES, CAD_SUFFIXES
from core.export import export, svg_doc, items_for_sheet, sheet_title
from core.solid import assembled

ROOT = pathlib.Path(__file__).resolve().parent.parent
JOBS = ROOT / "working-files" / "jobs"
JOBS.mkdir(parents=True, exist_ok=True)
EXAMPLES = ROOT / "examples"
MESH_SUFFIXES = {".stl", ".obj", ".3mf", ".ply", ".off", ".glb", ".gltf"} | CAD_SUFFIXES
CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")  # long enough that nobody guesses somebody else's
JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # no dots: these two build every path under jobs/


def client_dir(client: str) -> pathlib.Path:
    """The client's own directory. Its id is the only way in — nothing under jobs/ can be listed — so one person's
    models, cut files and session stay out of reach of everyone else on the server."""
    if not CLIENT_ID.fullmatch(client):
        raise HTTPException(400, "bad client id")
    return JOBS / client


def job_dir(client: str, job: str) -> pathlib.Path:
    if not JOB_ID.fullmatch(job):
        raise HTTPException(400, "bad job id")
    return client_dir(client) / job


TTL = float(os.environ.get("LAMINA_TTL_HOURS", 24)) * 3600  # 0 = never: only "clear my data" deletes
# No cap by default: this server is your own computer, and the only real limit is the memory the slice needs. Set
# LAMINA_MAX_UPLOAD_MB when you put it on a public address, where a stranger's 2 GB scan is not yours to hold.
MAX_UPLOAD = int(float(os.environ.get("LAMINA_MAX_UPLOAD_MB", 0)) * 1e6)


def sweep():
    """Drop clients nobody has touched for LAMINA_TTL_HOURS. A closed tab cannot tell us it is gone (and a refresh
    would look the same), so the models, cut files and session of an idle one time out instead of piling up.
    Only directories that are client ids: anything else under jobs/ was put there by someone else and is not ours
    to delete."""
    if TTL <= 0:
        return
    for d in JOBS.iterdir():
        if d.is_dir() and CLIENT_ID.fullmatch(d.name) and d.stat().st_mtime < time.time() - TTL:
            shutil.rmtree(d, ignore_errors=True)


def model_name(jd):
    """The model's own file name: kept in name.txt for uploads (the copy itself is renamed), else the example's."""
    src = pathlib.Path((jd / "source.txt").read_text())
    return (jd / "name.txt").read_text().strip() if (jd / "name.txt").exists() else src.name


def file_base(jd, plan):
    """<project or model>_v<rev> for download names: the project name when there is one, otherwise the model's file
    name, so files from different models never collide."""
    p = plan["params"]
    stem = p.get("project") or pathlib.Path(model_name(jd)).stem or "model"
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem).strip("_.") or "model"
    return f"{stem}_v{p.get('rev') or '1.0'}"


app = FastAPI(title="Lamina")

# Where the build is up to, so the page can say "sectioning 12 / 29 · 48 %" instead of "slicing…" for a minute. A
# slice runs in the threadpool, one build per thread, so the file to write to rides on the thread that is building.
_building = threading.local()


def _report(text, frac, artifact=None):
    f = getattr(_building, "file", None)
    if f:
        if artifact:              # a file the build has already written, under the jobs tree: the page can fetch it
            rel = pathlib.Path(artifact).resolve().relative_to(JOBS.resolve()).as_posix()
            _building.model = f"/jobs/{rel}?v={int(time.time() * 1000)}"
        d = {"progress": text, "frac": frac}
        # it stays in every later stage too: the page reads this file twice a second, and the stage that wrote the
        # mesh is over in milliseconds — announced once, it would be missed nearly every time
        if getattr(_building, "model", None):
            d["model"] = _building.model
        # two slices of one client at once share this file, and a stage half written is not worth failing a build
        # over: all it ever does is draw a progress bar
        with contextlib.suppress(OSError):
            f.write_text(json.dumps(d))


plan_module.report = _report


@app.get("/api/progress")
def progress(client: str, job: str = ""):
    """The stage the client's slice is in. Nothing readable (no build yet, or a stage half written) = empty."""
    try:
        return json.loads((client_dir(client) / "progress.json").read_text())
    except (OSError, ValueError):
        return {}


@app.middleware("http")
async def refuse_oversize_bodies(request, call_next):
    """The upload cap before the body is read: the multipart parser spools the whole request to disk before a handler
    sees it, so a request that announces more than the cap (plus room for the form fields) is refused unread."""
    if MAX_UPLOAD and int(request.headers.get("content-length") or 0) > MAX_UPLOAD + 1_000_000:
        return Response("request too large", status_code=413)
    return await call_next(request)


app.mount("/jobs", StaticFiles(directory=JOBS), name="jobs")
app.mount("/static", StaticFiles(directory=ROOT / "web" / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "static" / "index.html")


@app.get("/changelog.md")
def changelog():
    """What's new, read from the one CHANGELOG.md in the repo — the published build copies it here too, so the
    dialog fetches the same relative path whichever way Lamina is being run."""
    return FileResponse(ROOT / "CHANGELOG.md", media_type="text/markdown")


@app.get("/api/modes")
def modes():
    return [m.schema() for m in MODES.values()]


@app.get("/api/examples")
def examples():
    return sorted(p.stem for p in EXAMPLES.glob("*.stl"))


@app.get("/api/presets")
def presets():
    """The technique and parameters each bundled example opens with (examples/presets.json): every one slices clean.
    No file (a build that did not ship it) = no presets, not a failed page."""
    f = EXAMPLES / "presets.json"
    return {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_")} if f.exists() else {}


@app.post("/api/slice")
def slice_model(client: str = Form(...), mode: str = Form(...), params: str = Form("{}"), example: str = Form(""), job: str = Form(""), memo: str = Form("{}"), model: UploadFile | None = File(None)):
    """A job = one source model (working-files/jobs/<client>/<id>/source.txt points at it); re-slicing reuses it.
    Plain `def`: slicing is CPU-bound and can take 15 s, so it runs in the threadpool and nobody else waits on it."""
    if mode not in MODES:
        raise HTTPException(400, f"unknown mode {mode}")
    cd = client_dir(client)
    sweep()  # sweep first: it may drop this client's own stale
    cd.mkdir(parents=True, exist_ok=True)
    os.utime(cd)  # directory, and a slice starts it afresh
    if model is not None and model.filename:
        data = model.file.read(MAX_UPLOAD + 1 if MAX_UPLOAD else -1)
        if MAX_UPLOAD and len(data) > MAX_UPLOAD:
            raise HTTPException(413, f"this server takes models up to {MAX_UPLOAD // 1_000_000} MB and yours is bigger. "
                                     f"Run Lamina on your own computer (no limit) or decimate the mesh first")
        job = hashlib.sha256(data).hexdigest()[:12]
        jd = job_dir(client, job)
        jd.mkdir(exist_ok=True)
        mpath = jd / ("upload" + pathlib.Path(model.filename).suffix.lower())
        if mpath.suffix not in MESH_SUFFIXES:
            raise HTTPException(400, f"unsupported file type {mpath.suffix}")
        mpath.write_bytes(data)
        (jd / "source.txt").write_text(str(mpath))
        (jd / "name.txt").write_text(model.filename)
    elif job and (job_dir(client, job) / "source.txt").exists():
        jd = job_dir(client, job)
        mpath = pathlib.Path((jd / "source.txt").read_text())
    elif example:
        job = "ex_" + example
        jd = job_dir(client, job)  # validates the name before it reaches the filesystem
        mpath = EXAMPLES / f"{example}.stl"
        if not mpath.exists():
            raise HTTPException(400, "unknown example")
        jd.mkdir(exist_ok=True)
        (jd / "source.txt").write_text(str(mpath))
    else:
        raise HTTPException(400, "upload a model or pick an example")
    t0 = time.time()
    _building.file = cd / "progress.json"          # this thread's build reports its stages here, for /api/progress
    _building.model = None                         # …and the preview mesh, once this build has written it
    try:
        prm = json.loads(params or "{}")
        plan = build(mpath, mode, prm, jd / "plan", mesh_out=jd / "model.stl")
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}") from e
    finally:
        _building.file = None
        with contextlib.suppress(OSError):        # another slice of this client's may still hold it open
            (cd / "progress.json").unlink(missing_ok=True)
    W, H = plan["sheet"]
    p = plan["params"]
    t1 = time.time()
    sheets = [svg_doc(items_for_sheet(plan, si), W, H, p["labels"], True, p["font"], p["units"], sheet_title(plan, si)) for si in range(plan["sheets"])]
    plan["timing"]["drawing the sheets"] = round(time.time() - t1, 3)
    took = round(time.time() - t0, 2)
    # the session belongs to the client, not to the server: what this tab sliced last, so its refresh resumes it
    session = {"mode": mode, "params": prm, "job": job, "example": example or (job[3:] if job.startswith("ex_") else ""), "memo": json.loads(memo or "{}")}
    (cd / "session.json").write_text(json.dumps(session))
    with open(ROOT / "working-files" / "timing.log", "a") as f:  # one server-side log, outside the served jobs tree
        stages = " ".join(f"{k.split(' ')[0]}={v:.1f}" for k, v in plan["timing"].items() if v >= 0.05)
        f.write(f"{time.strftime('%H:%M:%S')} {mode:12s} {mpath.name:16s} {plan['counts']['parts']:4d} parts {took:6.2f} s  {stages}{'  params=' + json.dumps(prm)[:300] if took > 5 else ''}\n")
    ghost = f"/jobs/{client}/{job}/model.stl?v={int((jd / 'model.stl').stat().st_mtime_ns // 1_000_000)}"  # new URL whenever the processed model changed
    return {"job": job, "plan": plan, "sheets": sheets, "model": ghost, "took": took}


@app.get("/api/session")
def session(client: str):
    """The last thing this client sliced — mode, parameters, model job, per-technique memory — so its refresh resumes
    it. `alive` says whether the job's model is still on disk."""
    f = client_dir(client) / "session.json"
    if not f.exists():
        return {}
    s = json.loads(f.read_text())
    s["alive"] = bool(s.get("job")) and (job_dir(client, s["job"]) / "source.txt").exists()
    return s


@app.delete("/api/session")
def clear(client: str):
    """The UI's "clear my data": everything this tab sliced — models, cut files, session — goes at once, whatever the TTL."""
    shutil.rmtree(client_dir(client), ignore_errors=True)
    return {}


def with_units(plan: dict, units: str) -> dict:
    """The cut files in the unit the page is showing. The unit is a label on the drawing, not a re-plan, so a download
    carries the unit picked since the last slice instead of the one that plan was made with."""
    if units in ("mm", "cm", "in"):
        plan["params"]["units"] = units
    return plan


def project_file(client: str, jd: pathlib.Path, plan: dict) -> tuple[str, str]:
    """The job as the project file the UI's "open project" reads back (technique, every parameter, per-technique
    memory, and an uploaded model itself), for the zips: a cut file or a printed part found later has to lead back
    to the model that made it. The session has the parameters as the form holds them; the plan's are the fallback."""
    sess = {}
    f = client_dir(client) / "session.json"
    if f.exists():
        sess = json.loads(f.read_text())
        if sess.get("job") != jd.name:
            sess = {}
    state = sess.get("params") or plan["params"]
    example = jd.name.startswith("ex_")  # a bundled example is named; an upload travels along
    proj = {
        "version": 3,
        "name": state.get("project", ""),
        "rev": state.get("rev", "1.0"),
        "mode": plan["mode"],
        "unit": state.get("units", "mm"),
        "state": state,
        "memo": sess.get("memo", {}),
        "example": jd.name[3:] if example else "",
    }
    if not example and (jd / "source.txt").exists():
        src = pathlib.Path((jd / "source.txt").read_text())
        proj["model"] = {"name": model_name(jd), "b64": base64.b64encode(src.read_bytes()).decode()}
    return f"{file_base(jd, plan)}.lamina.json", json.dumps(proj)


@app.get("/api/job/{client}/{job}/export")
def job_export(client: str, job: str, fmt: str = "svg,dxf", labels: int = 1, per_piece: int = 0, key: int = 1, units: str = ""):
    jd = job_dir(client, job)
    if not (jd / "plan.json").exists():
        raise HTTPException(404)
    plan = json.loads((jd / "plan.json").read_text())
    plan = with_units(plan, units)
    fmts = [f for f in fmt.split(",") if f in ("svg", "dxf", "pdf", "eps")]
    tmp = pathlib.Path(tempfile.mkdtemp(dir=jd))
    try:
        files = export(plan, tmp, fmts, bool(labels), bool(per_piece), key=bool(key))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.name)
            z.writestr(*project_file(client, jd, plan))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    name = f"{file_base(jd, plan)}_{plan['mode']}_{'pieces' if per_piece else 'sheets'}_{'-'.join(fmts)}{'' if labels else '_plain'}.zip"
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/job/{client}/{job}/source")
def job_source(client: str, job: str):
    """The uploaded model as base64 (for project files that embed it)."""
    jd = job_dir(client, job)
    if not (jd / "source.txt").exists():
        raise HTTPException(404)
    src = pathlib.Path((jd / "source.txt").read_text())
    import base64

    return {"name": model_name(jd), "b64": base64.b64encode(src.read_bytes()).decode()}


@app.get("/api/job/{client}/{job}/proto")
def job_proto(client: str, job: str, scale: float = 1.0, size: float = 0.0, labels: str = "groove", font: float = 5.0, min_thick: float = 1.2, offset: float = 0.2):
    """Prototyping set: every part flat as STL at `scale` (or scaled so the model's longest side = `size` mm), slots
    `offset` printed mm wider than the material, label engraved as a groove or cut as a hole, `font` mm tall at
    least, plus plate.3mf holding every part as a separate named object (OrcaSlicer / PrusaSlicer can then arrange
    them individually) — zipped, with the project file and a README saying how the print differs from the job."""
    jd = job_dir(client, job)
    if not (jd / "plan.json").exists():
        raise HTTPException(404)
    plan = json.loads((jd / "plan.json").read_text())
    if size > 0:
        scale = size / max(plan["bbox"])
    from core.solid import proto_plan, proto_set

    plan, note = proto_plan(plan, scale, min_thick, offset)  # thicker material and the print's own clearance, so the slots fit
    tmp = pathlib.Path(tempfile.mkdtemp(dir=jd))
    try:
        files = proto_set(plan, tmp, scale, labels if labels in ("none", "groove", "hole") else "groove", font, min_thick, note=note)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(*project_file(client, jd, plan))
            for f in files:
                z.write(f, f.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{file_base(jd, plan)}_{plan["mode"]}_proto_x{scale:.3g}.zip"'})


@app.get("/api/job/{client}/{job}/fit")
def job_fit(client: str, job: str, scale: float = 1.0, size: float = 0.0, labels: str = "groove", font: float = 5.0, min_thick: float = 1.2, offset: float = 0.2, step: float = 0.1):
    """Print fit test: five small assemblies with the job's joints at print slot offsets around `offset` (printed
    mm), each part engraved with its value (see core.solid.fit_set) — plate.3mf, one STL per variant, README, zipped."""
    jd = job_dir(client, job)
    if not (jd / "plan.json").exists():
        raise HTTPException(404)
    plan = json.loads((jd / "plan.json").read_text())
    if size > 0:
        scale = size / max(plan["bbox"])
    from core.solid import fit_set

    tmp = pathlib.Path(tempfile.mkdtemp(dir=jd))
    try:
        files = fit_set(plan, tmp, scale, labels if labels in ("none", "groove", "hole") else "groove", font, min_thick, offset, step)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(*project_file(client, jd, plan))
            for f in files:
                z.write(f, f.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{file_base(jd, plan)}_{plan["mode"]}_printfit_x{scale:.3g}.zip"'})


@app.get("/api/job/{client}/{job}/fitcut")
def job_fitcut(client: str, job: str, fmt: str = "svg,dxf", labels: int = 1, step: float = 0.1, units: str = ""):
    """Fit test as cut files at 1:1 for the real machine and material: five small assemblies with the job's joints
    at slot offsets around its own, a folder of sheets each (see core.solid.fit_sheets) — zipped with a README."""
    jd = job_dir(client, job)
    if not (jd / "plan.json").exists():
        raise HTTPException(404)
    plan = with_units(json.loads((jd / "plan.json").read_text()), units)
    fmts = [f for f in fmt.split(",") if f in ("svg", "dxf", "pdf", "eps")]
    from core.solid import fit_sheets

    tmp = pathlib.Path(tempfile.mkdtemp(dir=jd))
    try:
        files = fit_sheets(plan, tmp, fmts, bool(labels), step)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(*project_file(client, jd, plan))
            for f in files:
                z.write(f, f.relative_to(tmp).as_posix())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{file_base(jd, plan)}_{plan["mode"]}_fit_{"-".join(fmts)}.zip"'})


@app.get("/api/job/{client}/{job}/stl")
def job_stl(client: str, job: str, part: str = ""):
    jd = job_dir(client, job)
    if not (jd / "plan.json").exists():
        raise HTTPException(404)
    plan = json.loads((jd / "plan.json").read_text())
    if part and part not in {pc["label"] for sl in plan["slices"] for pc in sl["pieces"]}:  # a label of the plan, or nothing: it names the file too
        raise HTTPException(404, "no such part")
    data = assembled(plan, part or None).export(file_type="stl")
    name = f"{file_base(jd, plan)}_{plan['mode']}_{part or 'assembled'}.stl"
    return Response(data, media_type="model/stl", headers={"Content-Disposition": f'attachment; filename="{name}"'})
