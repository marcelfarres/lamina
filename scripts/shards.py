"""Split the long CI runs into parallel jobs of about the same time, by the times GitHub's runners took (shards.json).

    LAMINA_UI=1 LAMINA_UI_PART=2/4 uv run pytest tests/ui     part 2 of 4 of the page tests (tests/ui/conftest.py)
    python scripts/shards.py media 6              media.yml's scene groups, as a JSON list of space-separated names
    python scripts/shards.py media 6 axes lobes   one group of these scenes (a run by hand with scene names)
    python scripts/shards.py record ui-times-*.xml media.log     shards.json from a run's JUnit reports and log

The longest goes first, each into the part with the least time so far. The page tests go in whole files, in their
order, as one run takes them; only a file longer than a part is cut into runs of consecutive tests. Every test and
every scene goes into exactly one part. One with no recorded time (new since the last record) counts as the mean.
Stdlib only: media.yml runs it before anything is installed. To refresh the times from a green run:
    gh run download <test.yml run> -p "ui-times-*" -D working-files/times
    gh run view <media.yml run> --log > working-files/times/media.log
    python scripts/shards.py record working-files/times/*/*.xml working-files/times/media.log
"""
import json
import math
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
TIMES = ROOT / "scripts" / "shards.json"


def scenes():
    return re.findall(r"^S\.(\w+) = ", (ROOT / "scripts" / "media" / "capture.mjs").read_text(), re.M)


def seconds(kind, names):
    known = json.loads(TIMES.read_text())[kind]
    mean = sum(known.values()) / len(known) if known else 1
    return {k: known.get(k, mean) for k in names}


def split(units, n, order):
    """`units` [(seconds, [name, …])] in `n` parts of about the same time, each part's names in `order`."""
    if n > len(units):
        sys.exit(f"{n} parts for {len(units)} pieces of work: a part would be empty")
    parts, load = [[] for _ in range(n)], [0.0] * n
    for s, names in sorted(units, key=lambda u: -u[0]):
        i = load.index(min(load))
        parts[i] += names; load[i] += s
    return [sorted(p, key=order.index) for p in parts]


def ui_parts(ids, n):
    """The page tests `ids` (pytest node ids, in run order) in `n` parts."""
    t = seconds("ui", ids)
    longest = sum(t.values()) / n or 1
    units = []
    for f in dict.fromkeys(i.split("::")[0] for i in ids):
        tests = [i for i in ids if i.split("::")[0] == f]
        total = sum(t[i] for i in tests)
        k, done, runs = max(1, math.ceil(total / longest)), 0, {}
        for i in tests:                        # k runs of consecutive tests, each about total / k
            j = min(k - 1, int((done + t[i] / 2) * k / total)) if k > 1 else 0
            runs.setdefault(j, []).append(i); done += t[i]
        units += [(sum(t[i] for i in r), r) for r in runs.values()]
    return split(units, n, ids)


def media_groups(n):
    every = scenes()
    t = seconds("media", every)
    return split([(t[s], [s]) for s in every], n, every)


def record(paths):
    """Each page test's seconds (JUnit's) and each scene's (capture.mjs's "scene x took" lines)."""
    times = json.loads(TIMES.read_text())
    ui, media = {}, {}
    for p in map(pathlib.Path, paths):
        if p.suffix == ".xml":
            # our own test run's reports, not untrusted input. classname: tests.ui.test_library (.TestClass, if any)
            for case in ET.parse(p).iter("testcase"):  # noqa: S314
                c = case.get("classname").split(".")
                k = next(k for k in range(len(c), 0, -1) if (ROOT / ("/".join(c[:k]) + ".py")).exists())
                ui["::".join(["/".join(c[:k]) + ".py", *c[k:], case.get("name")])] = round(float(case.get("time") or 0), 1)
        else:
            for name, s in re.findall(r"scene (\w+) took (\d+) s", p.read_text(errors="replace")):
                media[name] = int(s)
    times["ui"] = ui or times["ui"]
    times["media"] = dict(sorted(media.items())) or times["media"]
    TIMES.write_text(json.dumps(times, indent=1) + "\n")
    for kind, parts in (("ui", ui_parts(list(times["ui"]), 4)), ("media", media_groups(6))):
        print(kind, "longest part", round(max(sum(times[kind].get(k, 0) for k in p) for p in parts) / 60, 1), "min")


if __name__ == "__main__":
    kind, *rest = sys.argv[1:]
    if kind == "record":
        record(rest)
    elif kind == "media":
        print(json.dumps([" ".join(rest[1:])] if rest[1:] else [" ".join(p) for p in media_groups(int(rest[0]))]))
    else:
        sys.exit(__doc__)
