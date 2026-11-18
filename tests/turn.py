"""One heavy test run at a time on this machine.

Several worktrees are tested at once here, and a run that takes every core (`-n auto`) or drives a browser
(`LAMINA_UI`, `LAMINA_E2E`) beside four others does not finish in its 4 minutes: they fight for the cores and the
memory, single tests pass the 180 s timeout, and what fails is run again. In turn, each run has the machine and is
done before the next starts.

The turn is a lock the operating system holds on a file in the temp folder. It gives it back when the process ends,
however it ends, so there is nothing to clean up after a crash. A focused run (one file, no `-n`) takes no turn.
"""
import os
import pathlib
import sys
import tempfile
import time

LOCK = pathlib.Path(tempfile.gettempdir()) / "lamina-test-turn.lock"
GIVE_UP = 40 * 60          # s: longer than the longest run (the page suite, 31 min); a run that holds the turn this long is hung, and the next goes ahead beside it


def _lock(f):
    """Raises OSError when another process holds it."""
    f.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


def take(say=print, give_up=GIVE_UP, path=LOCK):
    """Waits until this process has the turn and returns the open file: keep it, the turn goes back when it is closed
    or the process ends. Says once who it waits for. After `give_up` seconds it returns None and the run goes ahead
    without the turn, as every run did before."""
    who = path.with_suffix(".who")              # the lock file itself cannot be read on Windows while it is held
    f = open(path, "a+")                        # noqa: SIM115  kept open: the open file is the turn
    start = time.monotonic()
    told = False
    while True:
        try:
            _lock(f)
            break
        except OSError:
            if not told:
                say(f"waiting for the test run that has this machine ({who.read_text() if who.exists() else 'unknown'})")
                told = True
            if time.monotonic() - start > give_up:
                say(f"it still runs after {give_up // 60} min: going ahead beside it")
                f.close()
                return None
            time.sleep(2)
    who.write_text(f"{os.getcwd()}, since {time.strftime('%H:%M')}, pid {os.getpid()}")
    return f


if __name__ == "__main__":                      # python tests/turn.py <lock file> <seconds> <log>: hold the turn, for the test
    held = take(path=pathlib.Path(sys.argv[1]))
    began = time.time()
    time.sleep(float(sys.argv[2]))
    with open(sys.argv[3], "a") as log:
        log.write(f"{began} {time.time()}\n")
    held.close()
