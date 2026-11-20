"""Web UI + API.  Run from the repo root:   uv run uvicorn web.app:app --reload --port 8000

Every request carries a client id — a random secret the browser tab keeps — and everything that client makes lives
under working-files/jobs/<client>/, so several people can use one server without seeing each other's work.

POST /api/slice        multipart: client, mode, params=<json>, and one of  model=<file> | example=<name> | job=<id> (re-slice the same model)
                       → {job, plan (with 3D facets + sheet placement), sheets: [svg…], model: url of the processed mesh (STL)}
GET  /api/modes        mode schemas (drive the form)
GET  /api/examples     bundled test models
GET  /api/project      {version}: the project file layout this server writes (and the page saves)
GET  /api/session?client=<id>                                                  → what that client sliced last
GET  /api/progress?client=<id>                                                 → the stage the client's slice is in
GET  /api/job/{client}/{job}/export?fmt=svg,dxf,pdf,eps&labels=1&per_piece=0&grouped=1   → zip of cut files
GET  /api/job/{client}/{job}/stl?part=<label>                                  → assembled solid (or one part) as STL
GET  /api/job/{client}/{job}/step?part=<label>                                 → the same as STEP: true solids for CAD

Only with LAMINA_LIBRARY=<folder> set (the library kept by this server, for every browser; 404 without it):
GET    /api/library                      → {name, problem, files: [{file, size, mtime}]}: the project files in the folder
GET    /api/library/<file>               → {text, size, mtime}
PUT    /api/library/<file>   body=text   → {size, mtime}
DELETE /api/library/<file>[?size=&mtime=] → {removed}: with size and mtime, only while the file still has them
"""

from __future__ import annotations
import base64, contextlib, errno, hashlib, io, itertools, json, os, pathlib, re, shutil, sys, tempfile, threading, time, zipfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from core import progress as build_progress
from core.plan import build, MODES, swap_in
from core.mesh import CAD_SUFFIXES
from core.export import design_name, export, svg_doc, items_for_sheet, sheet_title
from core.solid import fit_set, fit_sheets, proto_plan, proto_set, solid_bytes

HERE = pathlib.Path(__file__).resolve().parent
# Jobs go under the folder Lamina is started from: the repo, /app in Docker and the browser, the starter's own folder.
JOBS = pathlib.Path("working-files", "jobs").resolve()
JOBS.mkdir(parents=True, exist_ok=True)


def bundled(name):
    """examples/ and CHANGELOG.md sit beside web/ in the repo; the installed package (uvx lamina3d) carries them inside web/."""
    return HERE / name if (HERE / name).exists() else HERE.parent / name


EXAMPLES = bundled("examples")
MESH_SUFFIXES = {".stl", ".obj", ".3mf", ".ply", ".off", ".glb", ".gltf"} | CAD_SUFFIXES
CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")  # long enough that nobody guesses somebody else's
JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")  # no dots: these two build every path under jobs/


def inside(base: pathlib.Path, *parts: str, status: int = 400) -> pathlib.Path:
    """A path under `base` built from request values. The ids are matched against CLIENT_ID / JOB_ID first, which admit
    neither a separator nor a dot; this then normalises the joined path and checks it still starts with the base — the
    one shape of check a code scanner recognises, so every path under jobs/ is seen to be safe, not only known to be."""
    p = os.path.normpath(os.path.join(base, *parts))
    if not p.startswith(os.path.normpath(base) + os.sep):
        raise HTTPException(status, "bad path")
    return pathlib.Path(p)


def client_dir(client: str) -> pathlib.Path:
    """The client's own directory. Its id is the only way in — nothing under jobs/ can be listed — so one person's
    models, cut files and session stay out of reach of everyone else on the server."""
    if not CLIENT_ID.fullmatch(client):
        raise HTTPException(400, "bad client id")
    return inside(JOBS, client)


def job_dir(client: str, job: str) -> pathlib.Path:
    if not JOB_ID.fullmatch(job):
        raise HTTPException(400, "bad job id")
    return inside(client_dir(client), job)


TTL = float(os.environ.get("LAMINA_TTL_HOURS", 24)) * 3600  # 0 = never: only "clear my data" deletes
# No cap by default: this server is your own computer, and the only real limit is the memory the slice needs. Set
# LAMINA_MAX_UPLOAD_MB when you put it on a public address, where a stranger's 2 GB scan is not yours to hold.
MAX_UPLOAD = int(float(os.environ.get("LAMINA_MAX_UPLOAD_MB", 0)) * 1e6)
# The library kept by this server, for every browser that opens the page (a Docker volume above all). Unset, and in
# the browser build: the page keeps its projects in the browser or in a folder linked there, and no api/library
# answers. No accounts: whoever can open the page can read, change and delete the projects in this folder.
LIBRARY = pathlib.Path(os.environ["LAMINA_LIBRARY"]).expanduser().resolve() if os.environ.get("LAMINA_LIBRARY") else None


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


def model_b64(jd):
    """The uploaded model by name and as base64: what a project file embeds, so a cut file leads back to its model."""
    src = pathlib.Path((jd / "source.txt").read_text())
    return {"name": model_name(jd), "b64": base64.b64encode(src.read_bytes()).decode()}


app = FastAPI(title="Lamina")

# Where the build is up to, so the page can say "sectioning 12 / 29 · 48 %" instead of "slicing…" for a minute. A
# slice runs in the threadpool, one build per thread, so the file to write to rides on the thread that is building.
_building = threading.local()
# Each change on the page sends a slice, and the page throws away all but the newest answer. The server used to
# compute every one to the end anyway, so a slider dragged across five values ran five builds side by side, each five
# times slower under the GIL. Now a client's newer slice stops its older one at the older one's next stage.
_latest: dict[str, int] = {}                       # client → the number of the slice it sent last
_numbers = itertools.count()


class Superseded(Exception):
    """A newer slice of the same client started: nobody is waiting for this one's answer."""


def _report(text, frac, artifact=None):
    if getattr(_building, "client", None) and _latest.get(_building.client) != _building.n:
        raise Superseded
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


build_progress.report = _report


@app.get("/api/progress")
def progress(client: str):
    """The stage the client's slice is in. Nothing readable (no build yet, or a stage half written) = empty."""
    try:
        return json.loads((client_dir(client) / "progress.json").read_text())
    except (OSError, ValueError):
        return {}


@app.middleware("http")
async def refuse_oversize_bodies(request, call_next):
    """The upload cap before the body is read: the multipart parser spools the whole request to disk before a handler
    sees it, so a request that announces more than the cap (plus room for the form fields) is refused unread. The
    library has its own cap (library_cap): a project file carries its model as base64, a third bigger than the model."""
    if MAX_UPLOAD and "/api/library/" not in request.url.path and int(request.headers.get("content-length") or 0) > MAX_UPLOAD + 1_000_000:
        return Response("request too large", status_code=413)
    return await call_next(request)


app.mount("/jobs", StaticFiles(directory=JOBS), name="jobs")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/changelog.md")
def changelog():
    """What's new, read from the one CHANGELOG.md in the repo — the published build copies it here too, so the
    dialog fetches the same relative path whichever way Lamina is being run."""
    return FileResponse(bundled("CHANGELOG.md"), media_type="text/markdown")


@app.get("/api/modes")
def modes():
    return [m.schema() for m in MODES.values()]


# The project file's layout version. The page writes it when it saves, this server writes it into every export zip, and
# the page reads it back to tell an old project from a current one (before 4 a `size` ran along the view's axes, from
# 4 on along the model's): one number, here, so no writer can claim a layout it does not write. Bump it when the layout
# changes, and give the page's openProjectText (web/static/js/project.js) the migration for the version below.
PROJECT_VERSION = 4


@app.get("/api/project")
def project():
    """What the page needs to know about project files before it saves one, and with LAMINA_LIBRARY set, `library`:
    the server's folder by name, and what is wrong with it ('' when nothing). A field of this call, not a call of its
    own: the page asks it first thing, and web/static/browser.js takes a 404 from the first call for "no server here"
    and runs the page without one."""
    out = {"version": PROJECT_VERSION}
    if LIBRARY:
        out["library"] = {"name": LIBRARY.name, "problem": library_problem()}
    return out


# ---------------------------------------------------------------- the library kept by this server (LAMINA_LIBRARY)
# What the page's serverStore (web/static/js/store.js) calls: the same list, read, write, remove and conditional remove
# the browser's own store answers. The folder is flat, one <name>_v<rev>.lamina.json per revision, as a linked folder.
# What library.js's legal() leaves in a file name, with the ending every project file has; lib_path checks where it leads
LIB_FILE = re.compile(r'[^\\/:*?"<>|\x00-\x1f]+\.lamina\.json')


def library_cap() -> int:
    """The biggest project file the library takes. A project carries its model as base64 (4/3 of the model): with
    LAMINA_MAX_UPLOAD_MB set, the project of the biggest model the server takes, plus 1 MB for settings and picture.
    Unset, 2^29 bytes (537 MB): Chrome cannot build a longer text, so no project a page sends is refused, and a runaway
    request still cannot fill the disk."""
    return MAX_UPLOAD * 4 // 3 + 1_000_000 if MAX_UPLOAD else 1 << 29


def library_problem() -> str:
    """'' while the server can write into its library folder, else what is wrong and the fix, in plain words. Asked as
    the server starts (said once on its output), by api/project, by every listing and by a write that failed, so the
    page's folder line follows a fix without a restart."""
    try:
        LIBRARY.mkdir(parents=True, exist_ok=True)   # named but not made yet: a first run without Docker
        fd, probe = tempfile.mkstemp(dir=LIBRARY, prefix=".")
        os.close(fd)
        os.unlink(probe)
        return ""
    except OSError as e:
        uid = os.getuid() if hasattr(os, "getuid") else None   # 1000 in the Docker image (the Dockerfile's useradd)
        fix = ("It is mounted read-only: remove :ro from its volume line." if e.errno == errno.EROFS
               else f"On the host, give the folder to user {uid}: sudo chown -R {uid} /path/to/the/folder" if uid is not None
               else "Check that it exists and that the user who started Lamina may write to it.")
        return f"The server cannot write to its library folder {LIBRARY.name} ({e.strerror or e}). {fix}"


if LIBRARY and (_problem := library_problem()):
    print(f"Lamina: {_problem}", file=sys.stderr, flush=True)


def lib_path(file: str) -> pathlib.Path:
    """The library's file for a name the page sent: the library's own kind of name (no separator, no dot first, no
    `..`, the project ending), then where it leads, resolved: straight inside the folder, never through a link out."""
    if LIBRARY is None:
        raise HTTPException(404)
    ok = LIB_FILE.fullmatch(file) and not file.startswith(".") and ".." not in file
    p = (LIBRARY / file).resolve() if ok else None
    if p is None or p.parent != LIBRARY:
        raise HTTPException(400, f"{file!r} is not the name of a project file in the library")
    return p


@contextlib.contextmanager
def library_lock():
    """One change at a time in the folder, across every worker process (WEB_CONCURRENCY > 1): a write's swap and the
    size and time it answers, and a conditional remove's compare and delete, never interleave.
    ponytail: an OS lock on a file in the folder holds for the processes of one machine (the kernel lets go when one
    dies); servers on two machines sharing one network folder would need the file server's own locking."""
    with open(LIBRARY / ".lamina.lock", "a+b") as f:
        if os.name == "nt":
            import msvcrt                                    # imported here: the browser build has neither module
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)    # tries for 10 s, then OSError
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)                    # let go when the file closes
            yield


def mtime_ms(st) -> int:
    return st.st_mtime_ns // 1_000_000                       # the page's own unit (File.lastModified)


@app.get("/api/library")
def library_list():
    """Every project file straight in the folder, by name, size and time (links and sub-folders left out, so nothing
    outside shows even its size), with what is wrong with the folder for the page's folder line."""
    if LIBRARY is None:
        raise HTTPException(404)
    files = []
    try:
        with os.scandir(LIBRARY) as it:
            for e in it:
                with contextlib.suppress(OSError):           # gone between its name and its size: not there
                    if e.name.endswith(".lamina.json") and e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        files.append({"file": e.name, "size": st.st_size, "mtime": mtime_ms(st)})
    except OSError as err:
        raise HTTPException(503, library_problem() or f"The server cannot read its library folder {LIBRARY.name} ({err.strerror or err}).") from None
    return {"name": LIBRARY.name, "problem": library_problem(), "files": sorted(files, key=lambda f: f["file"])}


@app.get("/api/library/{file:path}")
def library_read(file: str):
    """A project file as text, with the size and time it had: both from one open file, so a write swapped in meanwhile
    cannot mix them (the page's record())."""
    p = lib_path(file)
    try:
        with open(p, "rb") as f:
            data, st = f.read(), os.fstat(f.fileno())
    except FileNotFoundError:
        raise HTTPException(404, f"{file} is not in the library") from None
    except OSError as e:
        raise HTTPException(503, f"{file} could not be read in {LIBRARY.name} ({e.strerror or e}).") from None
    return {"text": data.decode("utf-8", "replace"), "size": st.st_size, "mtime": mtime_ms(st)}


def _swap_in(tmp: str, p: pathlib.Path) -> dict:
    with library_lock():
        for wait in (0.05, 0.1, 0.2, 0.4, 0.8, None):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:                          # Windows refuses while a read still has the old file open
                if os.name != "nt" or wait is None:
                    raise
                time.sleep(wait)
        st = os.stat(p)
    return {"size": st.st_size, "mtime": mtime_ms(st)}


@app.put("/api/library/{file:path}")
async def library_write(file: str, request: Request):
    """The file swapped in whole: the body goes to a dot-file beside it first (no listing shows it), flushed to the
    disk, then swapped in, so a write that fails or stops half way leaves the old file as it was. Answers the size and
    time the listing will show. Counted as it comes: a body that announces no length is capped too."""
    p, cap = lib_path(file), library_cap()
    big = f"This project is bigger than the {cap // 1_000_000} MB this server's library takes. Use export to keep it as a file."
    if int(request.headers.get("content-length") or 0) > cap:
        raise HTTPException(413, big)
    try:
        fd, tmp = tempfile.mkstemp(dir=LIBRARY, prefix=".", suffix=".tmp")
    except OSError as e:
        raise HTTPException(503, library_problem() or f"{file} could not be written in {LIBRARY.name} ({e.strerror or e}).") from None
    try:
        with os.fdopen(fd, "wb") as f:
            n = 0
            async for chunk in request.stream():
                n += len(chunk)
                if n > cap:
                    raise HTTPException(413, big)
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)                                 # mkstemp's 0600 would keep the file from the host's own user
        return await run_in_threadpool(_swap_in, tmp, p)
    except OSError as e:
        raise HTTPException(503, library_problem() or f"{file} could not be written in {LIBRARY.name} ({e.strerror or e}).") from None
    finally:
        with contextlib.suppress(OSError):                   # swapped in, it is gone already
            os.unlink(tmp)


@app.delete("/api/library/{file:path}")
def library_remove(file: str, size: int | None = None, mtime: int | None = None):
    """The file deleted. With `size` and `mtime`, only while it still has them (the page's removeIf), checked and
    deleted under the lock, so a write that lands meanwhile stays. `removed` is true when it is gone, also when it was."""
    p = lib_path(file)
    try:
        with library_lock():
            if size is not None or mtime is not None:
                try:
                    st = os.stat(p)
                except FileNotFoundError:
                    return {"removed": True}
                if (st.st_size, mtime_ms(st)) != (size, mtime):
                    return {"removed": False}
            p.unlink(missing_ok=True)
    except OSError as e:
        raise HTTPException(503, library_problem() or f"{file} could not be deleted in {LIBRARY.name} ({e.strerror or e}).") from None
    return {"removed": True}


@app.get("/api/examples")
def examples():
    return sorted(p.stem for p in EXAMPLES.glob("*.stl"))


@app.get("/api/presets")
def presets():
    """The technique and parameters each bundled example opens with (examples/presets.json): every one slices clean.
    No file (a build that did not ship it) = no presets, not a failed page."""
    f = EXAMPLES / "presets.json"
    return {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if not k.startswith("_")} if f.exists() else {}


def _source(client: str, model: UploadFile | None, job: str, example: str) -> tuple[str, pathlib.Path, pathlib.Path]:
    """Which model this slice is of — an upload (capped, then kept in a job named by its hash), a job the client already
    has, or a bundled example — as (job id, the job's directory, the model's path)."""
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
        mpath = inside(EXAMPLES, f"{example}.stl")
        if not mpath.exists():
            raise HTTPException(400, "unknown example")
        jd.mkdir(exist_ok=True)
        (jd / "source.txt").write_text(str(mpath))
    else:
        raise HTTPException(400, "upload a model or pick an example")
    return job, jd, mpath


def _log_timing(mode: str, mpath: pathlib.Path, plan: dict, took: float, prm: dict):
    """One line per slice in the server-side log, outside the served jobs tree; the parameters too when it was slow."""
    with open(JOBS.parent / "timing.log", "a") as f:
        stages = " ".join(f"{k.split(' ')[0]}={v:.1f}" for k, v in plan["timing"].items() if v >= 0.05)
        f.write(f"{time.strftime('%H:%M:%S')} {mode:12s} {mpath.name:16s} {plan['counts']['parts']:4d} parts {took:6.2f} s  {stages}{'  params=' + json.dumps(prm)[:300] if took > 5 else ''}\n")


@app.post("/api/slice")
def slice_model(client: str = Form(...), mode: str = Form(...), params: str = Form("{}"), example: str = Form(""), job: str = Form(""), memo: str = Form("{}"), model: UploadFile | None = File(None)):
    """A job = one source model (working-files/jobs/<client>/<id>/source.txt points at it); re-slicing reuses it.
    Plain `def`: slicing is CPU-bound and can take 15 s, so it runs in the threadpool and nobody else waits on it."""
    if mode not in MODES:
        raise HTTPException(400, f"unknown mode {mode}")
    n = _latest[client] = next(_numbers)           # from here on, this client's older slices stop
    cd = client_dir(client)
    sweep()  # sweep first: it may drop this client's own stale
    cd.mkdir(parents=True, exist_ok=True)
    os.utime(cd)  # directory, and a slice starts it afresh
    job, jd, mpath = _source(client, model, job, example)
    t0 = time.time()
    _building.file = cd / "progress.json"          # this thread's build reports its stages here, for /api/progress
    _building.model = None                         # …and the preview mesh, once this build has written it
    _building.client, _building.n = client, n      # …and which slice it is, so a newer one can stop it
    try:
        prm = json.loads(params or "{}")
        # the name as it was uploaded (the copy on disk is renamed), engraved before every label; not kept in the session
        plan = build(mpath, mode, {**prm, "model_name": pathlib.Path(model_name(jd)).stem}, jd / "plan", mesh_out=jd / "model.stl")
    except Superseded:
        raise HTTPException(409, "a newer slice of this page replaced this one") from None
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}") from e
    finally:
        _building.file = _building.client = None   # the thread goes back to the pool: the next request on it is not this one
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
    # written beside and swapped in, tried again while Windows holds the old file (042). The session is a convenience:
    # one that cannot be written is not a failed slice
    text = json.dumps(session)
    swap_in(lambda tmp: tmp.write_text(text), cd / "session.json")
    _log_timing(mode, mpath, plan, took, prm)
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
    """The job as the project file the library's import reads back (technique, every parameter, per-technique
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
        "version": PROJECT_VERSION,
        "name": state.get("project", ""),
        "rev": state.get("rev", "1.0"),
        "mode": plan["mode"],
        "unit": state.get("units", "mm"),
        "state": state,
        "memo": sess.get("memo", {}),
        "example": jd.name[3:] if example else "",
    }
    if not example and (jd / "source.txt").exists():
        proj["model"] = model_b64(jd)
    return f"{design_name(plan)}.lamina.json", json.dumps(proj)


def _plan(client: str, job: str) -> tuple[pathlib.Path, dict]:
    """The job's directory and its plan: what every download is made from. No plan.json = no such job."""
    jd = job_dir(client, job)
    if not (jd / "plan.json").exists():
        raise HTTPException(404)
    return jd, json.loads((jd / "plan.json").read_text())


def _zip(client: str, jd: pathlib.Path, plan: dict, make_files, name: str) -> Response:
    """A download called `name`: the project file, then the files make_files(tmp) writes under tmp — a folder of its
    own inside the job, gone once zipped — each under its path there."""
    tmp = pathlib.Path(tempfile.mkdtemp(dir=jd))
    try:
        files = make_files(tmp)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(*project_file(client, jd, plan))
            for f in files:
                z.write(f, f.relative_to(tmp).as_posix())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _fmts(fmt: str) -> list[str]:
    """The cut-file formats asked for, in the order asked, unknown ones dropped."""
    return [f for f in fmt.split(",") if f in ("svg", "dxf", "pdf", "eps")]


def _engrave(labels: str) -> str:
    """How a printed part carries its label; anything but the three ways is a groove."""
    return labels if labels in ("none", "groove", "hole") else "groove"


def _scale(plan: dict, scale: float, size: float) -> float:
    """`size` > 0 is the printed model's longest side in mm, and overrides `scale`."""
    return size / max(plan["bbox"]) if size > 0 else scale


@app.get("/api/job/{client}/{job}/export")
def job_export(client: str, job: str, fmt: str = "svg,dxf", labels: int = 1, per_piece: int = 0, key: int = 1, units: str = "",
               grouped: int = 1):
    jd, plan = _plan(client, job)
    plan, fmts = with_units(plan, units), _fmts(fmt)
    name = f"{design_name(plan)}_{plan['mode']}_{'pieces' if per_piece else 'sheets'}_{'-'.join(fmts)}{'' if labels else '_plain'}.zip"
    return _zip(client, jd, plan, lambda tmp: export(plan, tmp, fmts, bool(labels), bool(per_piece), key=bool(key),
                                                    grouped=bool(grouped)), name)


@app.get("/api/job/{client}/{job}/source")
def job_source(client: str, job: str):
    """The uploaded model as base64 (for project files that embed it)."""
    jd = job_dir(client, job)
    if not (jd / "source.txt").exists():
        raise HTTPException(404)
    return model_b64(jd)


@app.get("/api/job/{client}/{job}/proto")
def job_proto(client: str, job: str, scale: float = 1.0, size: float = 0.0, labels: str = "groove", font: float = 5.0, min_thick: float = 1.2, offset: float = 0.2):
    """Prototyping set: every part flat as STL at `scale` (or scaled so the model's longest side = `size` mm), slots
    `offset` printed mm wider than the material, label engraved as a groove or cut as a hole, `font` mm tall at
    least, plus plate.3mf holding every part as a separate named object (OrcaSlicer / PrusaSlicer can then arrange
    them individually) — zipped, with the project file and a README saying how the print differs from the job."""
    jd, plan = _plan(client, job)
    scale = _scale(plan, scale, size)
    plan, note = proto_plan(plan, scale, min_thick, offset)  # thicker material and the print's own clearance, so the slots fit
    try:
        return _zip(client, jd, plan, lambda tmp: proto_set(plan, tmp, scale, _engrave(labels), font, min_thick, note=note),
                    f"{design_name(plan)}_{plan['mode']}_proto_x{scale:.3g}.zip")
    except RuntimeError as e:          # what the set cannot do on this computer, said in its own words (027: no scikit-image on 3.15)
        raise HTTPException(400, str(e)) from None


@app.get("/api/job/{client}/{job}/fit")
def job_fit(client: str, job: str, scale: float = 1.0, size: float = 0.0, labels: str = "groove", font: float = 5.0, min_thick: float = 1.2, offset: float = 0.2, step: float = 0.1):
    """Print fit test: five small assemblies with the job's joints at print slot offsets around `offset` (printed
    mm), each part engraved with its value (see core.solid.fit_set) — plate.3mf, one STL per variant, README, zipped."""
    jd, plan = _plan(client, job)
    scale = _scale(plan, scale, size)
    return _zip(client, jd, plan, lambda tmp: fit_set(plan, tmp, scale, _engrave(labels), font, min_thick, offset, step),
                f"{design_name(plan)}_{plan['mode']}_printfit_x{scale:.3g}.zip")


@app.get("/api/job/{client}/{job}/fitcut")
def job_fitcut(client: str, job: str, fmt: str = "svg,dxf", labels: int = 1, step: float = 0.1, units: str = ""):
    """Fit test as cut files at 1:1 for the real machine and material: five small assemblies with the job's joints
    at slot offsets around its own, a folder of sheets each (see core.solid.fit_sheets) — zipped with a README."""
    jd, plan = _plan(client, job)
    plan, fmts = with_units(plan, units), _fmts(fmt)
    return _zip(client, jd, plan, lambda tmp: fit_sheets(plan, tmp, fmts, bool(labels), step), f"{design_name(plan)}_{plan['mode']}_fit_{'-'.join(fmts)}.zip")


@app.get("/api/job/{client}/{job}/stl")
def job_stl(client: str, job: str, part: str = ""):
    return _solid_file(client, job, part, "stl")


@app.get("/api/job/{client}/{job}/step")
def job_step(client: str, job: str, part: str = ""):
    """The same model as true solids for CAD: flat faces, no triangles (see core.step)."""
    return _solid_file(client, job, part, "step")


def _solid_file(client, job, part, fmt):
    _, plan = _plan(client, job)
    try:
        data = solid_bytes(plan, part or None, fmt)
    except LookupError:                                       # a label of the plan, or nothing: it names the file too
        raise HTTPException(404, "no such part") from None
    name = f"{design_name(plan)}_{plan['mode']}_{part or 'assembled'}.{fmt}"
    return Response(data, media_type=f"model/{fmt}", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# The downloads by the name the page asks for (/api/job/{client}/{job}/<name>): the browser build binds a query to these
# signatures (web/browser.py), so a download's parameters are written once, here, and nowhere else.
JOB_ROUTES = {"export": job_export, "stl": job_stl, "step": job_step, "source": job_source, "proto": job_proto, "fit": job_fit, "fitcut": job_fitcut}


def main():
    """`lamina3d` — what the starters and `uvx lamina3d` run: this app on this computer, with the browser opened on it.
    If the port is taken it is most likely Lamina started earlier, so the browser still lands on something useful."""
    import argparse, uvicorn, webbrowser
    ap = argparse.ArgumentParser(prog="lamina3d", description="Lamina on this computer, at http://localhost:PORT")
    ap.add_argument("--port", type=int, default=8000)
    port = ap.parse_args().port
    threading.Timer(1, webbrowser.open, [f"http://localhost:{port}"]).start()
    uvicorn.run(app, port=port)
