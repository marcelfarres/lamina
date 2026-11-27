"""The staged build: a setting the parts do not read (a sheet size, a gap, a font for most techniques) takes the parts
the last build of the same model made and only lays them on the sheets again, and the plan comes out exactly as a
fresh build's. The parts hook hands them to the 3D view before they are nested. Real core.plan.build() runs on small
bundled examples."""
import json
import os
import pathlib

import pytest
import trimesh

import core.mesh
import core.progress
from core import plan as P
from core.plan import PARTS_STAGES, Params, build

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
PRESETS = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))

# One small job per technique: a bundled preset where there is one, else a test's own job
JOBS = {
    "radial": ("egg", None),
    "interlocked": ("torus", None),
    "stacked": ("tube", None),
    "folded": ("fold_box", None),
    "curve": ("hook", None),
    "plaque": ("ball", {"thickness": 3, "space": 3, "autofix": "off", "split": False, "sheet": [1000, 1000], "sink": 50, "plate": "circle"}),
    "bands": ("cube", {"autofix": "off", "thickness": 4, "nx": 3, "ny": 3, "nz": 3, "ring_wall": 12}),
}

# The settings only the sheets should need, each changed from the job's own value
SHEET_SIDE = {
    "sheet": lambda p: {"sheet": [s + 100 for s in p.get("sheet", [600, 400])]},
    "gap": lambda p: {"gap": p.get("gap", 3) + 3},
    "sheet_margin": lambda p: {"sheet_margin": p.get("sheet_margin", 5) + 4},
    "font": lambda p: {"font": p.get("font", 4.0) + 2},
    "labels": lambda p: {"labels": not p.get("labels", True)},
    "label_place": lambda p: {"label_place": "on" if p.get("label_place", "part") == "beside" else "beside"},
    "kerf": lambda p: {"compensate": True, "kerf": 0.15},
    "grain": lambda p: {"grain": not p.get("grain", False)},
    "one_sheet": lambda p: {"one_sheet": not p.get("one_sheet", False)},
}

# Read in making the parts, so a change of it makes them again (found by reading the techniques):
#   stacked: settle_marks places every dowel number at the font's size (core/modes/stacked.py:143)
#   folded: a net must fit the sheet inside its margin (core/modes/folded.py:1099), and seam numbers are placed at the
#   font's size (folded.py:598, 1138, 1149); one_sheet rewrites the sheet folded reads (core/plan.py, before the parts)
#   bands: guide_outlines cuts each band into pieces that fit the sheet (bands.py:550 → cut_band → shorten at
#   bands.py:767 → core/ringcut.py:129 reads sheet, sheet_margin and grain); one_sheet rewrites that sheet
# Every other pair here is asserted to be taken from the last build: no other technique reads these settings before
# the sheets (plaque's font is left unasserted: plaque.py:564 reads it only where a slot lands on a mark).
NOT_KEPT = {"stacked": {"font"}, "folded": {"sheet", "sheet_margin", "font", "one_sheet"},
            "bands": {"sheet", "sheet_margin", "grain", "one_sheet"}}
UNASSERTED = {("plaque", "font")}


@pytest.fixture(scope="module")
def jobs(tmp_path_factory):
    ball = tmp_path_factory.mktemp("stages") / "ball.stl"
    trimesh.creation.icosphere(4, 50.0).export(ball)
    out = {}
    for tech, (model, params) in JOBS.items():
        path = ball if model == "ball" else EXAMPLES / f"{model}.stl"
        out[tech] = (path, tech, params if params is not None else dict(PRESETS[model]["params"]))
        assert params is not None or PRESETS[model]["mode"] == tech
    return out


def plain(plan):
    """What two builds of one job must agree on: everything but the stage timing and which stages were taken."""
    return json.dumps({k: v for k, v in plan.items() if k not in ("timing", "reused")}, sort_keys=True)


def fresh(path, mode, params):
    """The job built with nothing taken from an earlier build."""
    os.environ["LAMINA_NO_REUSE"] = "1"
    try:
        return build(path, mode, params)
    finally:
        del os.environ["LAMINA_NO_REUSE"]


def kept_entry():
    hit = core.mesh._last
    return hit and hit[3].get("slices")


@pytest.mark.parametrize("name", list(SHEET_SIDE))
@pytest.mark.parametrize("tech", list(JOBS))
def test_a_sheet_setting_changed_gives_the_plan_a_fresh_build_gives(jobs, tech, name):
    path, mode, base = jobs[tech]
    build(path, mode, base)                             # the job's own parts, kept (or taken from the test before)
    job = {**base, **SHEET_SIDE[name](base)}
    got = build(path, mode, job)
    taken = got["reused"] == list(PARTS_STAGES)
    print(f"\n{tech:12s} {name:13s} {'taken' if taken else 'made again'}")
    assert plain(got) == plain(fresh(path, mode, job))
    if (tech, name) not in UNASSERTED:
        assert taken != (name in NOT_KEPT.get(tech, ()))


@pytest.mark.parametrize("change", [{"thickness": 3.5}, {"count": 9}])
def test_a_slicing_setting_changed_makes_the_parts_again(jobs, change):
    path, mode, base = jobs["radial"]
    build(path, mode, base)
    job = {**base, **change}
    got = build(path, mode, job)
    assert got["reused"] == []
    assert plain(got) == plain(fresh(path, mode, job))


def test_the_same_job_twice_takes_the_parts_and_another_model_or_technique_never_does(jobs):
    path, mode, base = jobs["radial"]
    a, b = build(path, mode, base), build(path, mode, base)
    assert b["reused"] == list(PARTS_STAGES) and plain(a) == plain(b)
    assert "placing slices and slots" not in b["timing"] and "nesting the parts on sheets" in b["timing"]
    other = build(*jobs["interlocked"])                 # another model in between: the egg's parts went with its model
    assert other["reused"] == []
    again = build(path, mode, base)
    assert again["reused"] == [] and plain(again) == plain(a)
    crossed = build(path, "interlocked", {"nx": 4, "ny": 3})   # the same prepared model, another technique
    assert crossed["reused"] == []
    assert plain(crossed) == plain(fresh(path, "interlocked", {"nx": 4, "ny": 3}))


def test_what_auto_fix_wrote_into_the_parameters_comes_back_with_the_parts():
    """Auto-fix adds crossing slices by writing their places into the parameters (extra_x, extra_y): taken from the
    last build, the parts come with those values, so the plan says what was added as a fresh build does."""
    job = {"thickness": 3, "slot_offset": 0.2, "min_feature": 2.0, "kerf": 0.15}
    first = build(EXAMPLES / "tube.stl", "interlocked", job)
    assert first["params_used"].get("extra_x") or first["params_used"].get("extra_y")
    got = build(EXAMPLES / "tube.stl", "interlocked", {**job, "gap": 7})
    assert got["reused"] == list(PARTS_STAGES)
    assert plain(got) == plain(fresh(EXAMPLES / "tube.stl", "interlocked", {**job, "gap": 7}))


def test_parts_that_read_the_parameters_whole_are_made_again_and_come_out_the_same(tmp_path):
    """A plaque's hanging pieces get their spacers through the parameters (a ChainMap in core/modes/plaque.py), not from
    a copy of them all: a copy reads every setting, and then no later slice could take these parts as they are."""
    stem = trimesh.creation.box([12, 60, 30]); stem.apply_translation([0, 0, 15])
    cap = trimesh.creation.box([48, 60, 30]); cap.apply_translation([0, 0, 45])
    path = tmp_path / "mushroom.stl"
    trimesh.boolean.union([stem, cap]).export(path)
    job = {"thickness": 3, "space": 3, "autofix": "off", "split": False, "sheet": [1000, 1000], "dowel_d": 8}
    first = build(path, "plaque", job)
    assert any(s["group"] == "P" for s in first["slices"])            # it has spacers
    got = build(path, "plaque", {**job, "gap": 7})
    assert got["reused"]
    assert plain(got) == plain(fresh(path, "plaque", {**job, "gap": 7}))


def test_no_reuse_switch_makes_the_parts_every_time(jobs, monkeypatch):
    path, mode, base = jobs["folded"]
    build(path, mode, base)
    monkeypatch.setenv("LAMINA_NO_REUSE", "1")
    assert build(path, mode, base)["reused"] == []


@pytest.mark.parametrize("tech", ["folded", "radial"])
def test_the_parts_hook_gets_the_parts_before_they_are_nested(jobs, tech, monkeypatch):
    path, mode, base = jobs[tech]
    seen = []
    monkeypatch.setattr(core.progress, "report", lambda text, frac, artifact=None: seen.append(text.split(" · ")[0]))
    monkeypatch.setattr(core.progress, "parts", lambda plan: seen.append(json.loads(json.dumps(plan))))
    for _ in range(2):                                  # made, then taken from the last build: the hook is called both times
        seen.clear()
        final = json.loads(json.dumps(build(path, mode, base)))
        early = [s for s in seen if isinstance(s, dict)]
        assert len(early) == 1
        early = early[0]
        at = seen.index(early)
        assert "nesting the parts on sheets" in seen[:at] and "measuring coverage" in seen[at:]
        assert early["partial"] is True and "partial" not in final
        for k in ("mode", "params", "bbox", "axes", "mid", "label_tag", "counts", "notes", "errors", "warnings", "fixes", "clip", "bounds3d", "edges3d", "faces3d"):
            assert k in early, k
        assert early["params"] == final["params"] and early["bbox"] == final["bbox"] and early["counts"]["parts"] == final["counts"]["parts"]
        assert [s["label"] for s in early["slices"]] == [s["label"] for s in final["slices"]]
        for s, f in zip(early["slices"], final["slices"]):
            for k in ("label", "group", "M", "thickness", "errors", "note"):     # what render3D reads of a slice
                assert k in s, k
            for pc, fpc in zip(s["pieces"], f["pieces"]):
                assert pc["place"] is None and "placed" not in pc and "label_pos" not in pc
                assert pc["label"] == fpc["label"] and pc["area"] == fpc["area"] and pc["bbox"] == fpc["bbox"]
                assert pc["facets"] == fpc["facets"]                            # M, rings, and folded's hinge, bevel, t, paper
    if tech == "folded":
        assert any(fc.get("hinge") for s in early["slices"] for pc in s["pieces"] for fc in pc["facets"])


def test_no_partial_plan_is_made_when_nobody_listens(jobs, monkeypatch):
    calls = []
    real = P._slice_json
    monkeypatch.setattr(P, "_slice_json", lambda sl, placed=True: calls.append(placed) or real(sl, placed))
    build(*jobs["folded"])
    assert calls and all(calls)


class Stop(Exception):
    pass


def stop_at(monkeypatch, stage):
    def report(text, frac, artifact=None):
        if text.startswith(stage):
            raise Stop
    monkeypatch.setattr(core.progress, "report", report)


@pytest.mark.parametrize("stage", ["sectioning", "nesting the parts on sheets", "measuring coverage"])
def test_a_build_stopped_in_either_phase_leaves_the_next_one_right(jobs, stage, monkeypatch):
    """The server stops an older slice of a page from inside report() (Superseded): what it was making is never
    kept, and what the last finished build kept stays as it was."""
    path, mode, base = jobs["stacked"]
    core.mesh._last = None                              # a model nobody has made parts of yet
    with monkeypatch.context() as m:
        stop_at(m, stage)
        with pytest.raises(Stop):
            build(path, mode, base)
    assert kept_entry() is None
    good = build(path, mode, base)
    assert good["reused"] == [] and plain(good) == plain(fresh(path, mode, base))
    entry = kept_entry()
    thicker, gap = {**base, "thickness": base.get("thickness", 3) + 1}, {**base, "gap": 8}
    for job in (thicker, gap):                          # stopped while making new parts, and while taking the kept ones
        with monkeypatch.context() as m:
            stop_at(m, stage)
            if stage == "sectioning" and job is gap:    # taken parts are not sectioned again: it runs to the end
                build(path, mode, job)
            else:
                with pytest.raises(Stop):
                    build(path, mode, job)
        assert kept_entry() is entry
    got = build(path, mode, gap)
    assert got["reused"] == list(PARTS_STAGES) and plain(got) == plain(fresh(path, mode, gap))
    got = build(path, mode, thicker)
    assert got["reused"] == [] and plain(got) == plain(fresh(path, mode, thicker))


def test_parameters_read_whole_are_noted_and_the_plan_gets_a_plain_dict(jobs):
    for whole in (lambda p: {**p}, dict, json.dumps, list, lambda p: p.items(), lambda p: p.copy(), repr, len,
                  lambda p: p.update(a=2), lambda p: p.pop("a"), lambda p: p == {}):
        p = Params(a=1, b=[1, 2])
        p.seen, p.whole = set(), False
        whole(p)
        assert p.whole, whole
    p = Params(a=1, b=[1, 2])
    p.seen = set()
    _ = p["a"], p.get("b"), "c" in p
    p["d"] = 4
    assert p.seen == {"a", "b", "c", "d"} and not p.whole
    p.seen = None                                       # not noting: a plain dict
    assert json.dumps(p) == json.dumps({"a": 1, "b": [1, 2], "d": 4}) and dict(p) == {"a": 1, "b": [1, 2], "d": 4}
    plan = build(*jobs["folded"])
    assert type(plan["params"]) is dict


def test_the_same_value_is_the_same_type_all_the_way_down():
    same, differ = P._same, lambda a, b: not P._same(a, b)
    assert same([600, 400], [600, 400]) and same({"Z-1": 3.0, "Z-2": [1, "a"]}, {"Z-1": 3.0, "Z-2": [1, "a"]})
    assert same(None, None) and same(P._MISSING, P._MISSING) and same("x", "x") and same(True, True)
    assert differ(1, 1.0) and differ(True, 1) and differ((1, 2), [1, 2]) and differ([600, 400], [600.0, 400.0])
    assert differ({"a": 1, "b": 2}, {"b": 2, "a": 1}) and differ([[1, 2]], [[1, 3]]) and differ(0.0, -0.0)
    assert same(float("nan"), float("nan"))             # the same setting, so the same parts: compared by repr, not ==
    assert differ(None, P._MISSING) and differ(object(), object())


def test_a_result_that_does_not_pickle_keeps_nothing():
    """A technique that keeps a lambda on its parts: that build keeps nothing, and the next one makes them again."""
    p = Params({"a": 1})
    before = P._noting(p)
    _ = p["a"]
    assert P._keep(before, "radial", object(), p, (lambda: 0,)) is None and p.seen is None
    assert P._noting(Params({"a": lambda: 0})) is None
