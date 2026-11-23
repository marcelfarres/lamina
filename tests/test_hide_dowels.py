"""`hide dowels`: each dowel only where the layers beyond its pair cover both ends of its hole."""
import pytest
import numpy as np
from shapely.geometry import Point

from core.geometry import section_polygons
from core.mesh import load_mesh
from core.plan import MODES, build, coerce_params
from tests.test_modify import EXAMPLES

T = 3.0
JOB = {"connect": "dowel", "dowel_d": 4, "n_points": 2, "thickness": T, "min_feature": 2.0, "autofix": "off"}


def open_holes(name, job):
    """The plan of example `name`, and for each of its dowels (in pairs of layers that have a layer beyond them) whether
    an end of its hole is left open: the model sectioned at the layer under the pair and at the layer over it, as the
    stack is glued, and the hole not wholly inside one of them. Slices touch, so a layer is one thickness from the next."""
    plan = build(EXAMPLES / f"{name}.stl", "stacked", job)
    mesh = load_mesh(EXAMPLES / f"{name}.stl", coerce_params(MODES["stacked"], job), [])
    rods = [(np.asarray(a, float), float(b[2]), d) for a, b, d, *_ in plan["rods"]]
    planes = {round(z, 1) for a, zb, _ in rods for z in (a[2] + T / 2, zb - T / 2)}
    out = []
    for a, zb, d in rods:
        hole = Point(a[:2]).buffer(d / 2)
        beyond = [z for z in (a[2] - T / 2, zb + T / 2) if round(z, 1) in planes]
        if beyond:
            M = [np.eye(4) for _ in beyond]
            for m, z in zip(M, beyond):
                m[2, 3] = z
            out.append(not all(section_polygons(mesh, m).contains(hole) for m in M))
    return plan, out


@pytest.mark.parametrize("placement", ["random", "aligned"])
@pytest.mark.parametrize("name", ["sphere", "vase"])
def test_hidden_dowels_are_covered_by_the_layers_beyond_their_pair(name, placement):
    """A model that tapers leaves a step on every layer, and a dowel spread toward the edge of its pair lands on it:
    an open hole on the finished model. With `hide dowels` no hole is open but in a pair the notes name, and every
    pair still gets its dowels."""
    job = {**JOB, "placement": placement, "size": [0, 0, 120]}
    plain, was = open_holes(name, job)
    plan, now = open_holes(name, {**job, "hide_dowels": True})
    named = sum(n.count("/") for n in map(str, plan["notes"]) if "hide dowels:" in n)
    if placement == "random":       # aligned rods start in what every layer shares, so few of them are open to begin with
        assert sum(was) > 4, f"only {sum(was)} open holes without it: this model does not show the fault"
    assert sum(now) <= 2 * named, f"{sum(now)} of {len(now)} hidden dowels have an open end ({sum(was)} with it off); notes: {plan['notes']}"
    assert len(plan["rods"]) >= 0.8 * len(plain["rods"]), f"{len(plan['rods'])} dowels, {len(plain['rods'])} with it off"


def test_hide_dowels_off_is_the_plan_as_it_was():
    job = {**JOB, "placement": "random", "size": [0, 0, 120]}
    assert build(EXAMPLES / "cone.stl", "stacked", job)["rods"] == build(EXAMPLES / "cone.stl", "stacked", {**job, "hide_dowels": False})["rods"]
