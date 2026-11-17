import pytest

from web import app as webapp


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """Jobs go to the test's own directory, not the repo's."""
    monkeypatch.setattr(webapp, "JOBS", tmp_path)
    return tmp_path
