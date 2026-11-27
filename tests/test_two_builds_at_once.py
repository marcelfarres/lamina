"""The server slices on request threads, so two slices can run at once: both then share the one pool that fits labels,
checks slices and nests rotations (core.geometry.each). Each must come out as it does alone, to the byte."""
import json
import pathlib
from concurrent.futures import ThreadPoolExecutor

from core.plan import build

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"
PRESETS = json.loads((EXAMPLES / "presets.json").read_text(encoding="utf-8"))
# tube at a 4 mm min feature: a thin-spot warning on 14 of its 22 slices; horse_statue: 93 parts on 3 sheets, 35 of
# their labels beside the part, so the in-order search beside runs while the other parts are fitted
JOBS = (("tube", {"min_feature": 4}), ("horse_statue", {}))


def plan_of(job):
    ex, extra = job
    pr = PRESETS[ex]
    plan = build(EXAMPLES / f"{ex}.stl", pr["mode"], {**pr["params"], **extra})
    # the model path names the checkout, `reused` the stages taken from the last build, timing the clock
    return json.dumps({**plan, "model": None, "reused": None, "timing": None}, sort_keys=True, default=str)


def test_two_slices_at_once_come_out_as_each_alone():
    alone = [plan_of(ex) for ex in JOBS]
    with ThreadPoolExecutor(len(JOBS)) as pool:
        for _ in range(3):                                  # a race shows on some runs only
            assert list(pool.map(plan_of, JOBS)) == alone
