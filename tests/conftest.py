import os

import pytest

import turn
from web import app as webapp


def pytest_sessionstart(session):
    """A run that takes every core (`-n`) or drives a browser waits for its turn on this machine (tests/turn.py).
    Not a focused run, not a worker of a run that has the turn already, and not CI, which has a machine of its own.
    LAMINA_NO_TURN=1 runs at once."""
    config = session.config
    heavy = getattr(config.option, "numprocesses", None) or os.environ.get("LAMINA_UI") or os.environ.get("LAMINA_E2E")
    if heavy and not hasattr(config, "workerinput") and not os.environ.get("CI") and not os.environ.get("LAMINA_NO_TURN"):
        config._lamina_turn = turn.take(say=config.pluginmanager.get_plugin("terminalreporter").write_line)   # kept open to the end of the run


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """Jobs go to the test's own directory, not the repo's."""
    monkeypatch.setattr(webapp, "JOBS", tmp_path)
    return tmp_path
