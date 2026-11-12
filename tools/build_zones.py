"""Generate src/scripts/data/zones.json: every zone's clock changes, straight from the IANA tz database.

FIRN uses the machine's own tz database when it has one. Stock Python on Windows has none, so the
tools fall back to this table. It is generated, never hand-written, so it cannot drift from the source.

Needs a Python that HAS tz data (Linux, macOS, or Windows with the tzdata package installed). The release
and the old alias names (some systems install no files for those) are read from the database's own tzdata.zi.
The table keeps a record of which zones changed from one release to the next, so that a machine whose own
database is older can tell which zones to read from the table.
Usage: python tools/build_zones.py [--from 2000] [--to 2046] [--force]
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "scripts", "data", "zones.json")
UTC = timezone.utc
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
KEEP = re.compile(r"^(Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific)/|^(UTC|GMT)$")
RELEASE = re.compile(r"^\d{4}[a-z]+$")


def minutes(dt):
    return int((dt - EPOCH).total_seconds() // 60)


def offset_min(dt, tz):
    return int(round(dt.astimezone(tz).utcoffset().total_seconds() / 60.0))


def zone_table(tz, start, end):
    """(offset at start, [[utc minute of change, new offset], ...])"""
    base = offset_min(start, tz)
    changes = []
    step = timedelta(hours=18)
    t0, off0 = start, base
    while t0 < end:
        t1 = min(t0 + step, end)
        off1 = offset_min(t1, tz)
        if off1 != off0:
            lo, hi = t0, t1
            while hi - lo > timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                mid = mid.replace(second=0, microsecond=0)
                if mid <= lo:
                    break
                if offset_min(mid, tz) == off0:
                    lo = mid
                else:
                    hi = mid
            changes.append([minutes(hi), off1])
        t0, off0 = t1, off1
    return base, changes


def database():
    """(folder, release, {alias: target}) of the tz database this Python reads; release is "" where it does not say."""
    import zoneinfo
    folders, packaged = list(zoneinfo.TZPATH), ""
    try:
        import tzdata
        folders.append(os.path.join(os.path.dirname(tzdata.__file__), "zoneinfo"))
        packaged = tzdata.IANA_VERSION
    except Exception:
        pass
    for folder in folders:
        if not os.path.isfile(os.path.join(folder, "Europe", "Warsaw")):
            continue
        release, links = packaged if folder == folders[-1] else "", {}
        try:
            with io.open(os.path.join(folder, "tzdata.zi"), encoding="utf-8") as f:
                for line in f:
                    p = line.split()
                    if p[:2] == ["#", "version"] and len(p) == 3:
                        release = p[2]
                    elif len(p) == 3 and p[0] == "L":
                        links[p[2]] = p[1]
        except (IOError, OSError):
            pass
        return folder, release, links
    return None, "", {}


def zone_sources():
    """{name to list: zone to read it from}, all from one folder: its files, then its links to them."""
    from zoneinfo import available_timezones
    folder, _, links = database()
    have = set(n for n in available_timezones() if os.path.isfile(os.path.join(folder, *n.split("/"))))
    sources = dict((n, n) for n in have if KEEP.match(n))
    for alias in links:
        target = links[alias]
        for _ in range(8):
            if target in have or target not in links:
                break
            target = links[target]
        if KEEP.match(alias) and alias not in sources and target in have:
            sources[alias] = target
    return sources


def on_file():
    """(the table as it stands, {name: [offset, changes]} from it); two empty dicts if there is none."""
    try:
        with io.open(OUT, encoding="utf-8") as f:
            old = json.load(f)
        return old, dict((n, old["tables"][i]) for n, i in old["zones"].items())
    except (IOError, OSError, ValueError, KeyError, IndexError):
        return {}, {}


def trail(old, release, window, changed):
    """The record of [release before, release after, zones whose tables changed], carried on from the old table."""
    was = old.get("source", "").split()[-1] if old else ""
    steps = [list(step) for step in old.get("changed", [])]
    if release == was:
        return steps
    if not (RELEASE.match(release) and RELEASE.match(was)) or release < was or old.get("window") != window:
        return []
    return steps + [[was, release, changed]] if changed else steps


def some(names):
    return ", ".join(names[:12]) + (" and %d more" % (len(names) - 12) if len(names) > 12 else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="first", type=int, default=2000)
    ap.add_argument("--to", dest="last", type=int, default=2046)
    ap.add_argument("--force", action="store_true",
                    help="write the table even if it would lose names or go back to an older release")
    a = ap.parse_args()
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Warsaw")
    except Exception:
        sys.exit("this Python has no tz database; use another interpreter or install the tzdata package")
    folder, release, _ = database()
    if not folder:
        sys.exit("cannot find the folder this Python reads its tz database from")
    sources = zone_sources()
    old, before = on_file()
    was = old.get("source", "").split()[-1] if old else ""
    if RELEASE.match(release) and RELEASE.match(was) and release < was and not a.force:
        sys.exit("the tz database in %s is %s, older than the table's %s; nothing written. "
                 "--force writes the table from it all the same" % (folder, release, was))
    lost = sorted(set(before) - set(sources))
    if lost and not a.force:
        sys.exit("the tz database in %s lacks %d of the names the table lists now (%s); nothing written. "
                 "--force writes the table without them" % (folder, len(lost), some(lost)))
    start = datetime(a.first, 1, 1, tzinfo=UTC)
    end = datetime(a.last, 1, 1, tzinfo=UTC)
    tables, index, zones, read = [], {}, {}, {}
    for name in sorted(sources):
        source = sources[name]
        if source not in read:
            read[source] = zone_table(ZoneInfo(source), start, end)
        base, changes = read[source]
        key = json.dumps([base, changes])
        if key not in index:
            index[key] = len(tables)
            tables.append([base, changes])
        zones[name] = index[key]
    changed = sorted(n for n in zones if n in before and before[n] != tables[zones[n]])
    data = {
        "note": "Generated by tools/build_zones.py from the IANA tz database. Do not edit by hand. "
                "changed: [release before, release after, zones whose tables changed between the two], oldest first. "
                "tables: [offset in minutes at the start of the window, [[minutes since 1970-01-01 UTC, new offset], ...]]. "
                "zones: zone name -> index into tables.",
        "source": "IANA tz database " + (release or "system copy, version unknown"),
        "window": [a.first, a.last],
        "changed": trail(old, release, [a.first, a.last], changed),
        "tables": tables,
        "zones": zones,
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("{\n")
        for k in ("note", "source", "window", "changed"):
            f.write("  %s: %s,\n" % (json.dumps(k), json.dumps(data[k])))
        f.write('  "tables": [\n')
        for i, t in enumerate(tables):
            f.write("    %s%s\n" % (json.dumps(t, separators=(",", ":")), "," if i < len(tables) - 1 else ""))
        f.write("  ],\n")
        f.write('  "zones": %s\n}\n' % json.dumps(zones, separators=(",", ":"), sort_keys=True))
    size = os.path.getsize(OUT)
    with_changes = sum(1 for t in tables if t[1])
    print("zones.json: %d zones, %d distinct tables (%d with clock changes), %d-%d, %s, %.0f KB" % (
        len(zones), len(tables), with_changes, a.first, a.last, data["source"], size / 1024.0))
    if before:
        for word, names in (("new", sorted(set(zones) - set(before))), ("dropped", lost), ("changed", changed)):
            print("%s: %s" % (word, "%d (%s)" % (len(names), some(names)) if names else "none"))


if __name__ == "__main__":
    main()
