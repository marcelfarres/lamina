"""The pipeline the way the browser build has to run it: without the compiled extras Pyodide cannot ship (rtree,
fast-simplification, manifold3d, earcut, embree). Every technique, both example kinds, every download, an upload —
each must answer 200. Run by tests/test_browser.py in a fresh interpreter, so the blocks are in place before trimesh
loads:   python tests/browser_env.py <jobs dir>
         python tests/browser_env.py presets            every example as a fresh page opens it"""
import sys
for name in ("rtree", "fast_simplification", "manifold3d", "mapbox_earcut", "embreex", "triangle"):
    sys.modules[name] = None                            # import → ImportError, as in Pyodide

import io, json, pathlib, zipfile
from concurrent.futures import ProcessPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from web import app as A, browser                       # noqa: E402
from test_presets import PRESETS, STILL_WARNS, opened   # noqa: E402

FOLD_NOTE = "cannot cut the fold grooves"                # the hinged folded examples: what this build cannot make is a note
HINGED = {"fold_box", "fold_lamp", "fold_test"}

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
    proto = zipfile.ZipFile(io.BytesIO(call("GET", f"api/job/{MINE}/ex_egg/proto", "scale=0.5&labels=groove")))
    plate = zipfile.ZipFile(io.BytesIO(proto.read("plate.3mf")))
    assert b'key="layer_height"' in plate.read("Metadata/model_settings.config")   # the print settings, without manifold3d too
    call("GET", f"jobs/{MINE}/ex_egg/model.stl")
    data = (ROOT / "examples" / "pear.stl").read_bytes()   # an upload: not watertight, so it goes through the shrinkwrap
    for mode in modes:
        plan = json.loads(call("POST", "api/slice", "", [["client", MINE], ["mode", mode], ["params", '{"autofix":"off"}'], ["model", "pear.stl", data]]))["plan"]
        print(f"{mode:12s} pear  {plan['counts']['parts']:4d} parts  {plan['counts']['errors']} errors")
    print("ok")


def _opened(name):
    plan, errs, warns = opened(name)
    return errs, warns, plan["notes"]


def presets():
    """Every example as a fresh page opens it (test_presets.opened) opens here as it does with the extras: no error and
    no warning but STILL_WARNS' (bug 079: the browser build is the first page most people see)."""
    names = sorted(PRESETS)
    with ProcessPoolExecutor(4) as ex:                  # the blocks above are in every worker: forked, or this file re-run
        for name, (errs, warns, notes) in zip(names, ex.map(_opened, names)):
            print(f"{name:13s} {len(errs)} errors {len(warns)} warnings", flush=True)
            assert not errs and bool(warns) == (name in STILL_WARNS), (name, errs[:3], warns[:3])
            assert any(FOLD_NOTE in n for n in notes) == (name in HINGED), (name, notes)
    print("ok")


if __name__ == "__main__":
    presets() if sys.argv[1] == "presets" else main(sys.argv[1])
