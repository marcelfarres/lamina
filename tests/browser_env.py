"""The pipeline the way the browser build has to run it: without the compiled extras Pyodide cannot ship (rtree,
fast-simplification, manifold3d, earcut, embree). Every technique, both example kinds, every download, an upload —
each must answer 200. Run by tests/test_browser.py in a fresh interpreter, so the blocks are in place before trimesh
loads:   python tests/browser_env.py <jobs dir>"""
import sys
for name in ("rtree", "fast_simplification", "manifold3d", "mapbox_earcut", "embreex", "triangle"):
    sys.modules[name] = None                            # import → ImportError, as in Pyodide

import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from web import app as A, browser                       # noqa: E402

MINE = "0" * 32


def call(method, path, query="", form=None):
    print(f"{method} {path}?{query}", flush=True)
    status, _, body = browser.handle(method, path, query, form)
    assert status == 200, f"{method} {path}?{query} → {status}: {body[-400:].decode(errors='replace')}"
    return body


def main(jobs):
    A.JOBS = pathlib.Path(jobs)
    modes = [m["name"] for m in json.loads(call("GET", "api/modes"))]
    def sliced(mode, example, params):
        form = [["client", MINE], ["mode", mode], ["params", json.dumps({"autofix": "off", **params})], ["example", example]]
        return json.loads(call("POST", "api/slice", "", form))["plan"]

    for mode in modes:
        for example in ("egg", "cube"):
            plan = sliced(mode, example, {})
            if plan["counts"]["parts"] == 0 and plan["fixes"]:   # bugs/060: the egg's round back only touches a plaque's plate:
                (fix,) = plan["fixes"]                           # the error and its one-click fixes, and each fix must stand
                assert "nothing stands on the plate" in fix["error"], (mode, example, plan["errors"])
                for o in fix["options"]:
                    fixed = sliced(mode, example, o["set"])
                    assert fixed["counts"]["parts"] > 0 and not fixed["errors"], (mode, example, o["title"], fixed["errors"])
                plan = fixed
            assert plan["counts"]["parts"] > 0, (mode, example)
            print(f"{mode:12s} {example:5s} {plan['counts']['parts']:4d} parts  {plan['counts']['errors']} errors")
    call("GET", f"api/job/{MINE}/ex_egg/export", "fmt=svg,dxf,pdf,eps&labels=1")
    call("GET", f"api/job/{MINE}/ex_egg/export", "fmt=svg&per_piece=1")
    call("GET", f"api/job/{MINE}/ex_egg/stl")
    assert call("GET", f"api/job/{MINE}/ex_egg/step").count(b"MANIFOLD_SOLID_BREP('") > 0
    call("GET", f"api/job/{MINE}/ex_egg/proto", "scale=0.5&labels=groove")
    call("GET", f"jobs/{MINE}/ex_egg/model.stl")
    data = (ROOT / "examples" / "pear.stl").read_bytes()   # an upload: not watertight, so it goes through the shrinkwrap
    for mode in modes:
        plan = json.loads(call("POST", "api/slice", "", [["client", MINE], ["mode", mode], ["params", '{"autofix":"off"}'], ["model", "pear.stl", data]]))["plan"]
        print(f"{mode:12s} pear  {plan['counts']['parts']:4d} parts  {plan['counts']['errors']} errors")
    print("ok")


if __name__ == "__main__":
    main(sys.argv[1])
