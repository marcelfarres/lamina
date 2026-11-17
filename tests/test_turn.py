"""Heavy test runs take turns on one machine (tests/turn.py): real processes, the real lock."""
import pathlib
import subprocess
import sys
import time

import turn

TURN = pathlib.Path(turn.__file__)


def test_two_runs_do_not_overlap_and_a_dead_one_gives_the_turn_back(tmp_path):
    lock, log = tmp_path / "turn.lock", tmp_path / "log"
    runs = [subprocess.Popen([sys.executable, str(TURN), str(lock), "1.0", str(log)]) for _ in range(3)]
    assert [r.wait(timeout=60) for r in runs] == [0, 0, 0]
    spans = sorted(tuple(map(float, ln.split())) for ln in log.read_text().splitlines())
    assert len(spans) == 3
    assert all(nxt[0] >= prev[1] - 0.05 for prev, nxt in zip(spans, spans[1:]))     # each began when the one before ended
    # a run that is killed while it has the turn: the next one gets it at once
    hung = subprocess.Popen([sys.executable, str(TURN), str(lock), "60", str(log)])
    for _ in range(300):                                                             # until `hung` has it
        mine = turn.take(give_up=0, path=lock, say=lambda _: None)
        if mine is None:
            break
        mine.close(); time.sleep(0.1)
    assert mine is None
    hung.kill(); hung.wait()
    held = turn.take(give_up=5, path=lock)
    assert held is not None
    held.close()


def test_a_run_that_waits_too_long_goes_ahead_and_says_who_it_waited_for(tmp_path):
    lock = tmp_path / "turn.lock"
    held = turn.take(path=lock)
    other = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {str(TURN.parent)!r}); import turn, pathlib; "
                            f"print(turn.take(give_up=0, path=pathlib.Path({str(lock)!r})))"], capture_output=True, text=True, timeout=60)
    held.close()
    said = other.stdout.splitlines()
    assert said[-1] == "None" and "waiting for the test run that has this machine" in said[0] and "pid" in said[0]
    assert "going ahead beside it" in said[1]
