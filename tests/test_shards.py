"""scripts/shards.py, which splits the page tests and the media recording over parallel CI jobs: every page test and
every scene goes into exactly one part, so a split run runs the same tests and records the same files as one job."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import shards  # noqa: E402


def collect(part=None):
    """The page tests pytest collects, as test.yml's parts collect them (tests/ui/conftest.py)."""
    env = {**os.environ, "LAMINA_UI": "1", **({"LAMINA_UI_PART": part} if part else {})}
    env.pop("PYTEST_XDIST_WORKER", None)
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/ui", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if "::" in ln]


def test_the_four_parts_run_every_page_test_once():
    every = collect()
    parts = [collect(f"{i}/4") for i in (1, 2, 3, 4)]
    assert all(parts) and sorted(sum(parts, [])) == sorted(every)
    assert all(p == [i for i in every if i in p] for p in parts)       # in the order one run takes them


def test_a_new_test_and_a_long_file_are_split_too():
    ids = list(json.loads(shards.TIMES.read_text())["ui"]) + ["tests/ui/test_new.py::test_not_timed_yet"]
    parts = shards.ui_parts(ids, 4)
    assert sorted(sum(parts, [])) == sorted(ids)
    t = shards.seconds("ui", ids)
    load = [sum(t[i] for i in p) for p in parts]
    assert max(load) < 1.15 * sum(load) / 4          # about the same time each: one file no longer sets the floor


@pytest.mark.parametrize("n", [1, 6])
def test_every_scene_is_recorded_once(n):
    groups = shards.media_groups(n)
    assert len(groups) == n and sorted(sum(groups, [])) == sorted(shards.scenes())


def test_the_command_lines_media_yml_runs():
    run = lambda *a: json.loads(subprocess.run([sys.executable, "scripts/shards.py", "media", *a], cwd=ROOT,
                                               capture_output=True, text=True, check=True).stdout)
    assert sorted(" ".join(run("6")).split()) == sorted(shards.scenes())
    assert run("6", "axes", "lobes") == ["axes lobes"]        # scene names given: one job


def test_a_part_is_never_empty():
    with pytest.raises(SystemExit):
        shards.media_groups(len(shards.scenes()) + 1)
