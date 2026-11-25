"""Lamina without a server. The page's requests reach `handle` (from web/static/browser-worker.js, where Pyodide runs
this) and it calls the very endpoint functions web/app.py serves — one code path whoever runs it. No ASGI, no
threads: a request is a plain function call whose answer is (status, headers, body)."""
from __future__ import annotations
import gc, inspect, io, json, mimetypes, urllib.parse
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response
from shapely.errors import GEOSException
from web import app as A

# This build's GEOS now and then fails on finite outlines with this, at a different step each run: its heap under
# pressure, not the model (bugs/038). After a collection the same request goes through.
ENGINE_NAN = "orientationIndex encountered NaN"


def call(endpoint, q: dict, **path):
    """The endpoint called as the server calls it: each parameter the query names, by name and coerced by its
    annotation, the rest left at the signature's default — a value can never land in the wrong slot."""
    params = inspect.signature(endpoint, eval_str=True).parameters
    return endpoint(**path, **{k: params[k].annotation(v) for k, v in q.items() if k in params and k not in path})


def handle(method: str, path: str, query: str, form) -> tuple[int, dict, bytes]:
    """The request's answer, tried once more after a collection when the engine failed with ENGINE_NAN. A failed slice
    comes back as a 500 answer (slice_model turns every error into one) and an export lets it out raw: both count."""
    try:
        out = _answer(method, path, query, form)
        if out[0] != 500 or ENGINE_NAN.encode() not in out[2]:
            return out
    except GEOSException as e:
        if ENGINE_NAN not in str(e):
            raise
    gc.collect()
    return _answer(method, path, query, form)


def _answer(method: str, path: str, query: str, form) -> tuple[int, dict, bytes]:
    q = dict(urllib.parse.parse_qsl(query)); f = {}; upload = None
    for item in form or []:
        if len(item) == 3:                                   # ["model", file name, bytes]
            upload = UploadFile(io.BytesIO(bytes(item[2])), filename=item[1])
        else:
            f[item[0]] = item[1]
    try:
        if path == "api/modes":
            out = A.modes()
        elif path == "api/examples":                         # the site ships the list; the models come one by one when picked
            idx = A.EXAMPLES / "index.json"
            out = json.loads(idx.read_text()) if idx.exists() else A.examples()
        elif path == "api/project":
            out = A.project()
        elif path == "api/presets":
            out = A.presets()
        elif path == "api/session":
            out = A.clear(q["client"]) if method == "DELETE" else A.session(q["client"])
        elif path == "api/slice":
            out = A.slice_model(client=f["client"], mode=f["mode"], params=f.get("params", "{}"), example=f.get("example", ""),
                                job=f.get("job", ""), memo=f.get("memo", "{}"), model=upload)
        elif path.startswith("jobs/"):                       # what StaticFiles serves on the server
            p = A.inside(A.JOBS, path[5:], status=404)
            if not p.is_file():
                raise HTTPException(404)
            return 200, {"content-type": mimetypes.guess_type(p.name)[0] or "application/octet-stream"}, p.read_bytes()
        elif path.startswith("api/job/"):
            _, _, client, job, what = path.split("/", 4)
            if what not in A.JOB_ROUTES:
                raise HTTPException(404)
            out = call(A.JOB_ROUTES[what], q, client=client, job=job)
        else:
            raise HTTPException(404)
    except HTTPException as e:
        return e.status_code, {"content-type": "application/json"}, json.dumps({"detail": e.detail}).encode()
    if isinstance(out, Response):
        return out.status_code, dict(out.headers), bytes(out.body)
    return 200, {"content-type": "application/json"}, json.dumps(out).encode()
