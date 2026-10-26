"""Lamina without a server. The page's requests reach `handle` (from web/static/browser-worker.js, where Pyodide runs
this) and it calls the very endpoint functions web/app.py serves — one code path whoever runs it. No ASGI, no
threads: a request is a plain function call whose answer is (status, headers, body)."""
from __future__ import annotations
import io, json, mimetypes, urllib.parse
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response
from web import app as A


def handle(method: str, path: str, query: str, form) -> tuple[int, dict, bytes]:
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
            # by name, as the server binds a query: a value in the wrong slot is a prototype with the wrong font
            F = lambda k, d: float(q.get(k, d)); I = lambda k, d: int(q.get(k, d))
            proto = dict(scale=F("scale", 1), size=F("size", 0), labels=q.get("labels", "groove"), font=F("font", 5),
                         min_thick=F("min_thick", 1.2), offset=F("offset", 0.2))
            routes = {"export": lambda: A.job_export(client, job, q.get("fmt", "svg,dxf"), I("labels", 1), I("per_piece", 0), I("key", 1), q.get("units", ""),
                                                     grouped=I("grouped", 1)),
                      "stl": lambda: A.job_stl(client, job, q.get("part", "")),
                      "source": lambda: A.job_source(client, job),
                      "proto": lambda: A.job_proto(client, job, **proto),
                      "fit": lambda: A.job_fit(client, job, **proto, step=F("step", 0.1)),
                      "fitcut": lambda: A.job_fitcut(client, job, q.get("fmt", "svg,dxf"), I("labels", 1), F("step", 0.1), q.get("units", ""))}
            if what not in routes:
                raise HTTPException(404)
            out = routes[what]()
        else:
            raise HTTPException(404)
    except HTTPException as e:
        return e.status_code, {"content-type": "application/json"}, json.dumps({"detail": e.detail}).encode()
    if isinstance(out, Response):
        return out.status_code, dict(out.headers), bytes(out.body)
    return 200, {"content-type": "application/json"}, json.dumps(out).encode()
