"""scripts/shards.py, which splits the page tests and the media recording over parallel CI jobs: every page-test file
and every scene goes into exactly one part, so a split run runs the same tests and records the same files as one job."""
import json
import subprocess
import sys

import pytest

sys.path.insert(0, "scripts")
import shards  # noqa: E402


@pytest.mark.parametrize("kind,n", [("ui", 1), ("ui", 4), ("ui", 5), ("media", 1), ("media", 6)])
def test_every_name_runs_once(kind, n):
    parts = shards.split(kind, n)
    every = shards.names(kind)
    assert len(parts) == n and all(parts)
    assert sorted(sum(parts, [])) == sorted(every)
    assert all(p == sorted(p, key=every.index) for p in parts)     # in the order one job takes them


def test_the_command_lines_the_workflows_run():
    run = lambda *a: subprocess.run([sys.executable, "scripts/shards.py", *a], capture_output=True, text=True, check=True).stdout
    assert sorted(sum((run("ui", "4", str(i)).split() for i in (1, 2, 3, 4)), [])) == shards.names("ui")
    assert sorted(" ".join(json.loads(run("media", "6"))).split()) == sorted(shards.names("media"))
    assert json.loads(run("media", "6", "axes", "lobes")) == ["axes lobes"]       # scene names given: one job


def test_a_part_is_never_empty():
    with pytest.raises(SystemExit):
        shards.split("ui", len(shards.names("ui")) + 1)
