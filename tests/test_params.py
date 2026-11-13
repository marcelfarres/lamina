"""Every parameter the UI offers — both ends of every slider, every choice, both states of every toggle — through
the real pipeline, one at a time, on the small cube. The plan may report errors (a sheet too small, a wall too thin);
the pipeline must not raise. This is what "stable" means when someone drags a slider to its end."""
import pathlib

import pytest

from core.plan import MODES, build

CUBE = pathlib.Path(__file__).resolve().parent.parent / "examples" / "cube.stl"


def values(p):
    """The settings a user can reach with the widget: slider ends, choices, on/off. Tables of labels and points are
    edited from the 3D view and need a plan first — covered by the pipeline tests."""
    if p.type == "choice":
        return p.choices
    if p.type == "bool":
        return [True, False]
    if p.type in ("number", "int") and p.min is not None and p.max is not None:
        return [p.min, p.max]
    if p.type in ("vec2", "vec3") and p.min is not None and p.max is not None:
        n = 2 if p.type == "vec2" else 3
        return [[p.min] * n, [p.max] * n]
    return []


# The smallest sheet the slider allows (10 × 10 mm) splits every part of the cube into fragments: 145 s alone for
# radial, past the 180 s cap when twelve workers share the cores (035, as 025 was). Those cases get the budget they
# need; every other case keeps the cap, so a hang there is still caught in three minutes.
TINY_SHEET = pytest.mark.timeout(600)

CASES = [pytest.param(mode.name, p.name, v, id=f"{mode.name}-{p.name}={v}",
                      marks=[TINY_SHEET] if p.name == "sheet" and v == values(p)[0] else [])
         for mode in MODES.values()
         for p in mode.all_params() if p.name not in mode.hidden_common
         for v in values(p)]


def test_a_value_past_the_slider_is_held_to_the_slider(tmp_path):
    """The API takes any JSON; the range of the widget is the range of the parameter, so a million slices or a
    negative thickness is the slider's end, not a request the server has to survive."""
    plan = build(CUBE, "stacked", {"thickness": -5, "distribution": "count", "count": 10**6}, out=tmp_path / "plan")
    assert plan["params"]["count"] == 500 and plan["params"]["thickness"] == 0.05


def test_two_slices_at_once_do_not_share_a_technique():
    """The server runs one build per request thread. A technique keeps the build's state on itself (folded panels:
    the simplified mesh, the frames, the cuts of each face), so every build has to have a technique instance of its
    own: with one shared, two folded jobs sliced at the same moment unfolded each other's mesh."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(CUBE, {"facet": 0, "joint": "laced"}), (CUBE.with_name("egg.stl"), {"facet": 25, "joint": "tab"})] * 2
    parts = lambda plan: [(s["label"], [pc["kerfed"] for pc in s["pieces"]]) for s in plan["slices"]]   # noqa: E731
    alone = [parts(build(model, "folded", prm)) for model, prm in jobs[:2]] * 2
    with ThreadPoolExecutor(4) as pool:
        together = list(pool.map(lambda job: parts(build(job[0], "folded", job[1])), jobs))
    assert together == alone


@pytest.mark.parametrize("mode, name, value", CASES)
def test_every_setting_of_every_slider_slices(mode, name, value, tmp_path):
    # 6 mm stock: ten slices through the cube instead of forty, the same code paths at a quarter of the time
    plan = build(CUBE, mode, {"thickness": 6, name: value}, out=tmp_path / "plan")
    assert "counts" in plan and "errors" in plan["counts"]
