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


CASES = [pytest.param(mode.name, p.name, v, id=f"{mode.name}-{p.name}={v}")
         for mode in MODES.values()
         for p in mode.all_params() if p.name not in mode.hidden_common
         for v in values(p)]


def test_a_value_past_the_slider_is_held_to_the_slider(tmp_path):
    """The API takes any JSON; the range of the widget is the range of the parameter, so a million slices or a
    negative thickness is the slider's end, not a request the server has to survive."""
    plan = build(CUBE, "stacked", {"thickness": -5, "distribution": "count", "count": 10**6}, out=tmp_path / "plan")
    assert plan["params"]["count"] == 500 and plan["params"]["thickness"] == 0.05


@pytest.mark.parametrize("mode, name, value", CASES)
def test_every_setting_of_every_slider_slices(mode, name, value, tmp_path):
    # 6 mm stock: ten slices through the cube instead of forty, the same code paths at a quarter of the time
    plan = build(CUBE, mode, {"thickness": 6, name: value}, out=tmp_path / "plan")
    assert "counts" in plan and "errors" in plan["counts"]
