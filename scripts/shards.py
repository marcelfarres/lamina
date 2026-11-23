"""Split the long CI runs into parallel jobs of about the same time, by the times GitHub's runners took (shards.json).

    python scripts/shards.py ui 4 2               the page-test files of part 2 of 4, one a line (test.yml)
    python scripts/shards.py media 6              media.yml's scene groups, as a JSON list of space-separated names
    python scripts/shards.py media 6 axes lobes   one group of these scenes (a run by hand with scene names)
    python scripts/shards.py record ui-times-*.xml media.log     shards.json from a run's JUnit reports and log

The longest name goes first, each into the part with the least time so far, so every name runs in exactly one part.
A page-test file or a scene with no recorded time (new since the last record) counts as the mean, so it still runs.
Stdlib only: media.yml runs it before anything is installed. To refresh the times from a green run:
    gh run download <test.yml run> -p "ui-times-*" -D working-files/times
    gh run view <media.yml run> --log > working-files/times/media.log
    python scripts/shards.py record working-files/times/*/*.xml working-files/times/media.log
"""
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMES = ROOT / "scripts" / "shards.json"


def names(kind):
    if kind == "ui":
        return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests" / "ui").glob("test_*.py"))
    return re.findall(r"^S\.(\w+) = ", (ROOT / "scripts" / "media" / "capture.mjs").read_text(), re.M)


def split(kind, n):
    """`n` lists that hold every name once, each in the order the one-process run takes them."""
    every, known = names(kind), json.loads(TIMES.read_text())[kind]
    if n > len(every):
        sys.exit(f"{n} parts for {len(every)} {kind} names: an empty part would run everything")
    mean = sum(known.values()) / len(known) if known else 1
    t = {k: known.get(k, mean) for k in every}
    parts, load = [[] for _ in range(n)], [0.0] * n
    for k in sorted(every, key=lambda k: -t[k]):
        i = load.index(min(load))
        parts[i].append(k); load[i] += t[k]
    return [sorted(p, key=every.index) for p in parts]


def record(paths):
    """Each page-test file's seconds (JUnit's test times, summed) and each scene's (capture.mjs's "scene x took" lines)."""
    times = json.loads(TIMES.read_text())
    ui, media = {}, {}
    for p in map(pathlib.Path, paths):
        if p.suffix == ".xml":
            # our own test run's reports, not untrusted input. classname: tests.ui.test_library (.TestClass, if any)
            for case in ET.parse(p).iter("testcase"):  # noqa: S314
                mod = case.get("classname").split(".")
                f = next("/".join(mod[:k]) + ".py" for k in range(len(mod), 0, -1)
                         if (ROOT / ("/".join(mod[:k]) + ".py")).exists())
                ui[f] = ui.get(f, 0) + float(case.get("time") or 0)
        else:
            for name, s in re.findall(r"scene (\w+) took (\d+) s", p.read_text(errors="replace")):
                media[name] = int(s)
    times["ui"] = {k: round(v) for k, v in sorted(ui.items())} or times["ui"]
    times["media"] = dict(sorted(media.items())) or times["media"]
    TIMES.write_text(json.dumps(times, indent=1) + "\n")
    for kind in ("ui", "media"):
        print(kind, "longest part", round(max(sum(times[kind].get(k, 0) for k in p) for p in split(kind, 4 if kind == "ui" else 6)) / 60, 1), "min")


if __name__ == "__main__":
    kind, *rest = sys.argv[1:]
    if kind == "record":
        record(rest)
    elif kind == "ui":
        print("\n".join(split("ui", int(rest[0]))[int(rest[1]) - 1]))
    else:
        print(json.dumps([" ".join(rest[1:])] if rest[1:] else [" ".join(p) for p in split("media", int(rest[0]))]))
