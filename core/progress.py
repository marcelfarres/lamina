"""Progress of the build under way: what stage it is at, how far along, and the seconds each stage took."""
from __future__ import annotations
import threading
import time


def report(text, frac, artifact=None):
    """Where progress() forwards each stage of build(): what is happening, how far along (0..1), and — when a stage
    has just finished something worth looking at before the rest — the file it wrote. A no-op here; the server and
    the browser worker point it at the page, where a slice of a big model takes long enough to look stuck."""


class _Run(threading.local):
    """The build under way on this thread: a server runs several at once (one per request thread), and with these
    shared, one build's start wiped another's stage marks — the timing log then put 72 s slices down as 10."""
    def __init__(self):
        self.stages: list[tuple[str, float]] = []   # (stage text, clock) marks
        self.band = (0.0, 1.0)                      # the slice of the bar this pass owns (see the autofix loop in build)


_run = _Run()
DETAIL = " · "                            # everything after it is detail of the stage, not a stage of its own


def progress(text, frac):
    _run.stages.append((text, time.perf_counter()))
    lo, hi = _run.band
    report(text, lo + frac * (hi - lo))


def timing() -> dict[str, float]:
    """Seconds per stage of the build, read off the progress marks; a stage's detail ("sectioning · 3 / 16",
    "· pass 2 of 3") folds into one row. This is what an optimisation has to move, so it rides in the plan and in
    the server's timing log."""
    out = {}
    for (text, t0), (_, t1) in zip(_run.stages, _run.stages[1:]):
        k = text.split(DETAIL)[0]
        out[k] = round(out.get(k, 0.0) + t1 - t0, 3)
    return out


def start():
    """A new build on this thread: no stage marks yet, the whole bar its own."""
    _run.__init__()


def band(lo, hi):
    """The slice of the bar the stages to come own (see the autofix loop in plan.build)."""
    _run.band = (lo, hi)


def show(artifact, frac):
    """A file worth looking at before the rest is done: not a stage of its own, the stage line stays put."""
    report("", frac, artifact)
