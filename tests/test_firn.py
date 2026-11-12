"""Tests for the FIRN field tools. Standard library only.

Run:  python tests/test_firn.py            (from the repository root)
      python tests/test_firn.py -v

The clock is pinned with FIRN_NOW, and a made-up driver (tests/personal.test.json) stands in for the
personal file, so results do not depend on the day or on anyone's real data. Files the tools write
(calendar files) go to a temporary folder that is removed afterwards.
"""
import atexit
import contextlib
import io
import itertools
import json
import math
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "src", "scripts")
FIXTURE = os.path.join(ROOT, "tests", "personal.test.json")
OUTPUTS = tempfile.mkdtemp(prefix="firn-tests-")
atexit.register(shutil.rmtree, OUTPUTS, True)
sys.path.insert(0, SCRIPTS)
os.environ["FIRN_NOW"] = "2026-11-10T13:30"
os.environ["FIRN_PERSONAL"] = FIXTURE
os.environ["FIRN_OUTPUTS"] = OUTPUTS

import firn  # noqa: E402
import firnlib  # noqa: E402
from firnlib import (agenda, armour, arms, board, chrono, core, desk, dice, dynamics, fatigue, geo, haul, ical, index, jump,  # noqa: E402
                     lattice, metar, rebuild, sensors, service, sky, sl, sound, things, tours)

UTC = timezone.utc
KRAKOW = (50.0619, 19.9581)
WARSAW = (52.2519, 20.9981)


def zone_builder():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    try:
        import build_zones
    finally:
        sys.path.pop(0)
    return build_zones


def use_personal(path):
    """Switch the personal file (None = the placeholder file shipped in src) and drop every cache built on it."""
    if path:
        os.environ["FIRN_PERSONAL"] = path
    else:
        os.environ.pop("FIRN_PERSONAL", None)
    core._personal = None
    core._cache.pop("personal", None)
    geo._places = None
    geo._index = None
    chrono._tz_cache.clear()


def run(*args):
    """Run a command; return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = firn.main([str(a) for a in args])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


def ok(*args):
    code, out, err = run(*args)
    assert code == 0, "firn.py %s -> exit %s\n%s%s" % (" ".join(map(str, args)), code, out, err)
    return out


def field(out, key):
    for line in out.splitlines():
        if line.startswith(key + " ") or line == key:
            return line[len(key):].strip()
    raise AssertionError("no %s line in:\n%s" % (key, out))


def hm(text):
    m = re.search(r"(\d+)h(\d\d)m", text)
    return int(m.group(1)) * 60 + int(m.group(2))


class ClockTests(unittest.TestCase):
    def test_default_zones_and_gap_week(self):
        out = ok("time", "2026-10-28 12:00")
        self.assertIn("HOME       2026-10-28 12:00 Wed UTC+01:00", out)
        self.assertIn("SLT        2026-10-28 04:00 Wed UTC-07:00  (-8 h)", out)
        self.assertIn("unusual: ordinarily -9 h", out)
        out = ok("time", "2026-07-01 12:00")
        self.assertIn("SLT        2026-07-01 03:00 Wed UTC-07:00  (-9 h)", out)
        self.assertNotIn("unusual", out)

    def test_named_zones(self):
        out = ok("time", "2026-07-01 12:00", "--to", "America/New_York", "tokyo", "sydney", "Asia/Kolkata", "gran")
        self.assertIn("06:00 Wed UTC-04:00", out)
        self.assertIn("19:00 Wed UTC+09:00", out)
        self.assertIn("20:00 Wed UTC+10:00", out)
        self.assertIn("15:30 Wed UTC+05:30", out)
        self.assertIn("GRAN       2026-07-01 05:00 Wed UTC-05:00", out)

    def test_clock_change_wall_times(self):
        self.assertIn("does not exist", ok("time", "2026-03-29 02:30"))
        self.assertIn("happens twice", ok("time", "2026-10-25 02:30"))

    def test_relative_and_other_date_forms(self):
        self.assertIn("HOME       2026-11-10 12:30 Tue", ok("time", "-2h"))
        self.assertIn("HOME       2026-11-08 21:00 Sun", ok("time", "08.11.2026 21:00"))
        self.assertIn("HOME       2026-11-11 07:30 Wed", ok("time", "tomorrow", "07:30"))

    def test_source_zone(self):
        out = ok("time", "2026-11-10 12:00", "--from", "slt")
        self.assertIn("HOME       2026-11-10 21:00 Tue UTC+01:00  (+9 h)", out)

    def test_unknown_zone_is_an_error(self):
        code, _, err = run("time", "now", "--to", "Mars/Olympus")
        self.assertEqual(code, 2)
        self.assertIn("ERROR unknown zone", err)

    def test_dst_and_gap_windows(self):
        out = ok("dst", "warsaw", "slt", "--year", "2026")
        self.assertIn("2026-03-29 Sun  02:00 -> 03:00  clocks forward", out)
        self.assertIn("2026-11-01 Sun  02:00 -> 01:00  clocks back", out)
        self.assertIn("SLT vs WARSAW: -8 h instead of -9 h, from 2026-03-08", out)
        self.assertIn("(21 days)", out)
        self.assertIn("(7 days)", out)

    def test_meet(self):
        out = ok("meet", "warsaw", "chicago", "slt", "--day", "2026-11-10")
        self.assertIn("WARSAW 17:00-22:00 Tue | CHICAGO 10:00-15:00 Tue | SLT 08:00-13:00 Tue | 5h00m", out)

    def test_span(self):
        out = ok("span", "2000-01-01", "2026-11-10 14:30", "--tz", "warsaw")
        self.assertIn("26 y 10 mo 9 d", out)
        self.assertIn("9,810 d 14h30m", out)

    def test_eta_across_clock_change(self):
        w = chrono.get_tz("Europe/Warsaw")
        dep, _ = chrono.localize(datetime(2026, 10, 24, 23, 30), w)
        self.assertEqual(chrono.add(dep, 5 * 3600 + 15 * 60).strftime("%Y-%m-%d %H:%M"), "2026-10-25 03:45")
        dep, _ = chrono.localize(datetime(2026, 3, 28, 23, 30), w)
        self.assertEqual(chrono.add(dep, 5 * 3600).strftime("%Y-%m-%d %H:%M"), "2026-03-29 05:30")

    def test_zone_table_matches_tz_database(self):
        """The generated table must agree with the real tz database wherever both exist."""
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            ZoneInfo("Europe/Warsaw")
        except Exception:
            self.skipTest("no tz database on this interpreter")
        here, made_from = chrono._machine_release(), chrono._zones()["source"].split()[-1]
        behind = chrono._stale()        # zones changed in releases newer than this machine's: its database has those wrong
        if behind is None:
            self.skipTest("this machine's tz database (%s) is older than the table's record of changes reaches" % here)
        hint = ""
        if chrono._RELEASE_RE.match(here) and chrono._RELEASE_RE.match(made_from) and here > made_from:
            hint = "; the table is from %s and this machine has %s: run  python tools/build_zones.py" % (made_from, here)
        checked = 0
        names = sorted(chrono._zones()["zones"])
        self.assertGreater(len(names), 400)
        for key in names:
            if key.lower() in behind:
                continue
            try:
                real = ZoneInfo(key)
            except ZoneInfoNotFoundError:
                continue                # some systems install no files for the old alias names
            mine = chrono.table_tz(key)
            t = datetime(2024, 1, 1, tzinfo=UTC)
            end = datetime(2031, 1, 1, tzinfo=UTC)
            while t < end:
                checked += 1
                if t.astimezone(real).utcoffset() != t.astimezone(mine).utcoffset():
                    self.fail("%s differs from the tz database at %s%s" % (key, t.isoformat(), hint))
                t += timedelta(hours=31)
        self.assertGreater(checked, 500000)

    def test_zone_builder_reads_the_old_names_from_links(self):
        """Some systems install no files for the old alias names; the builder must still list them."""
        try:
            import zoneinfo
            zoneinfo.ZoneInfo("Europe/Warsaw")
        except Exception:
            self.skipTest("no tz database on this interpreter")
        build = zone_builder()
        real = build.database()[0]
        folder = tempfile.mkdtemp(dir=OUTPUTS)
        for name in ("Europe/Warsaw", "Asia/Kolkata", "Etc/UTC"):
            os.makedirs(os.path.join(folder, name.split("/")[0]), exist_ok=True)
            shutil.copy(os.path.join(real, *name.split("/")), os.path.join(folder, *name.split("/")))
        with open(os.path.join(folder, "tzdata.zi"), "w") as f:
            f.write("# version 2031c\n# dataform main\nL Asia/Kolkata Asia/Calcutta\nL Asia/Calcutta Asia/Older\n"
                    "L Etc/UTC UTC\nL Etc/UTC Etc/Zulu\nL Europe/Gone Europe/Lost\n")
        zoneinfo.reset_tzpath(to=[folder])
        try:
            self.assertEqual(build.database()[:2], (folder, "2031c"))
            self.assertEqual(build.zone_sources(), {"Europe/Warsaw": "Europe/Warsaw", "Asia/Kolkata": "Asia/Kolkata",
                                                    "Asia/Calcutta": "Asia/Kolkata", "Asia/Older": "Asia/Kolkata", "UTC": "Etc/UTC"})
        finally:
            zoneinfo.reset_tzpath()

    def test_zone_builder_keeps_a_record_of_changes(self):
        trail = zone_builder().trail
        old = {"source": "IANA tz database 2026e", "window": [2000, 2046], "changed": [["2026d", "2026e", ["A/B"]]]}
        self.assertEqual(trail(old, "2026f", [2000, 2046], ["C/D"]), [["2026d", "2026e", ["A/B"]], ["2026e", "2026f", ["C/D"]]])
        self.assertEqual(trail(old, "2026f", [2000, 2046], []), old["changed"])     # nothing changed inside the window
        self.assertEqual(trail(old, "2026e", [2000, 2046], []), old["changed"])     # the same release again
        for release, window in (("2026f", [1990, 2046]), ("2026d", [2000, 2046]), ("", [2000, 2046])):
            self.assertEqual(trail(old, release, window, ["C/D"]), [])               # the trail is broken: it starts again
        self.assertEqual(trail({}, "2026f", [2000, 2046], []), [])
        data = chrono._zones()
        steps = data["changed"]
        self.assertEqual(steps[0], ["2026d", "2026e", ["America/Rainy_River", "America/Winnipeg"]])
        self.assertEqual([step[1] for step in steps], sorted(step[1] for step in steps))
        self.assertLessEqual(steps[-1][1], data["source"].split()[-1])
        for was, now, names in steps:
            self.assertLess(was, now)
            self.assertTrue(names and all(n in data["zones"] for n in names), names)

    def test_table_is_read_where_the_tz_database_is_behind(self):
        """Zones that changed in a release newer than the machine's tz database come from the table; the rest do not."""
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo("Europe/Warsaw")
        except Exception:
            self.skipTest("no tz database on this interpreter")
        real, forced = chrono._machine_release, os.environ.pop("FIRN_TZ", None)
        try:
            for here, winnipeg, warsaw, says in (("2026d", True, False, "tz database 2026d, and the built-in zone table"),
                                                 ("2026c", True, True, "(this machine's tz database is older, 2026c)"),
                                                 ("2099z", False, False, "tz database"), ("", False, False, "tz database")):
                chrono._machine_release = lambda: here
                chrono._zi_state.clear()
                chrono._tz_cache.clear()
                self.assertEqual(isinstance(chrono.get_tz("America/Winnipeg"), chrono.TableTZ), winnipeg, here)
                self.assertEqual(isinstance(chrono.get_tz("america/rainy_river"), chrono.TableTZ), winnipeg, here)
                self.assertEqual(isinstance(chrono.get_tz("Europe/Warsaw"), chrono.TableTZ), warsaw, here)
                self.assertFalse(isinstance(chrono.get_tz("Etc/GMT+5"), chrono.TableTZ), here)     # not a name the table lists
                source = chrono.tz_source()
                self.assertTrue(source.endswith(says) if warsaw or not winnipeg else source.startswith(says), source)
                self.assertEqual("changed since" in source, winnipeg and not warsaw, source)
        finally:
            chrono._machine_release = real
            if forced is not None:
                os.environ["FIRN_TZ"] = forced
            chrono._zi_state.clear()
            chrono._tz_cache.clear()

    def test_zone_table_fold_and_gap(self):
        tz = chrono.table_tz("Europe/Warsaw")
        self.assertEqual(datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=0).utcoffset(), timedelta(hours=2))
        self.assertEqual(datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=1).utcoffset(), timedelta(hours=1))
        self.assertEqual(datetime(2026, 3, 29, 2, 30, tzinfo=tz, fold=0).utcoffset(), timedelta(hours=1))
        back = datetime(2026, 10, 25, 0, 30, tzinfo=UTC).astimezone(tz)
        self.assertEqual((back.hour, back.fold), (2, 0))
        back = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).astimezone(tz)
        self.assertEqual((back.hour, back.fold), (2, 1))

    def test_zone_table_is_current(self):
        """Three zones stopped changing their clocks in 2026 and Cuba skipped its autumn change (tz 2026b to 2026f):
        a hand-written rule table had this wrong, and so has a table built from an older release."""
        old = "the zone table is behind tz 2026f: run  python tools/build_zones.py  where the tz database is that or newer"
        for key, off in (("America/Vancouver", -7), ("America/Edmonton", -6), ("America/Winnipeg", -5), ("America/Havana", -4)):
            tz = chrono.table_tz(key)
            self.assertEqual(chrono.offset_hours(datetime(2026, 12, 1, 12, tzinfo=UTC).astimezone(tz)), off, "%s: %s" % (key, old))
            self.assertEqual(chrono.offset_hours(datetime(2025, 12, 1, 12, tzinfo=UTC).astimezone(tz)), off - 1, key)

    def test_outside_the_table_window_is_flagged(self):
        tz = chrono.table_tz("Europe/Warsaw")
        _, note = chrono.localize(datetime(1990, 6, 1, 12, 0), tz)
        self.assertIn("only approximate", note)


class SetupTests(unittest.TestCase):
    """What the tools do while the personal file is still the placeholder."""

    def setUp(self):
        use_personal(None)

    def tearDown(self):
        use_personal(FIXTURE)

    def test_placeholder_file_is_a_placeholder(self):
        p = core.personal()
        self.assertIsNone(p["home"]["lat"])
        self.assertIsNone(p["work"]["lat"])
        self.assertEqual(p["ignition"], {"setting": "off", "questions": []})
        self.assertEqual((p["places"], p["legs"], p["family"], p["pending"], p["vehicles"], p["logbook"]), ({}, {}, [], [], [], []))

    def test_boot_says_what_to_do(self):
        out = ok("boot")
        self.assertIn("UTC, because home is not set", out)
        self.assertIn("SETUP      home and work not set", out)
        self.assertIn("scripts/data/personal.json", out)
        self.assertIn("IGNITION   off", out)
        self.assertNotIn("UPTIME", out)
        self.assertNotIn("SERVICE", out)
        self.assertNotIn("LOGBOOK", out)
        self.assertIn("no vehicle on file", ok("service"))
        self.assertIn("no entries on file", ok("log", "--list"))
        self.assertIn("off: no questions on file", ok("ignition"))

    def test_home_and_work_fail_with_the_remedy(self):
        code, _, err = run("route", "home", "work")
        self.assertEqual(code, 2)
        self.assertIn("home is not set yet", err)
        self.assertIn("personal.json", err)
        self.assertEqual(run("moon")[0], 2)

    def test_everything_else_still_works(self):
        self.assertIn("NOTE       home is not set", ok("time", "12:00"))
        self.assertIn("ARRIVE", ok("route", "krakow", "warsaw", "--depart", "2026-11-12 07:00"))
        self.assertIn("SELFTEST   12 of 12 passed", ok("selftest"))
        self.assertIn("no physical facts on file", ok("record", "--family"))
        self.assertNotIn("PENDING", ok("record", "--fit"))


class GroundTests(unittest.TestCase):
    def test_geometry(self):
        self.assertAlmostEqual(geo.haversine_km(*(KRAKOW + WARSAW)), 254.1, delta=0.1)
        self.assertAlmostEqual(geo.bearing_deg(*(WARSAW + KRAKOW)), 197.0, delta=1.0)
        self.assertAlmostEqual(geo.haversine_km(0, 0, 0, 180), math.pi * geo.EARTH_R_KM, delta=0.01)
        lat, lon = geo.intermediate(0, 0, 0, 90, 0.5)
        self.assertAlmostEqual(lon, 45.0, delta=1e-6)

    def test_route_estimate_and_eta_across_clock_change(self):
        out = ok("route", "krakow", "warsaw", "--depart", "2026-10-24 23:30")
        self.assertIn("254.1 km straight | ~318 km road", out)
        self.assertIn("TOTAL      4h39m [estimate]", out)
        self.assertIn("ARRIVE     2026-10-25 03:09 Sun UTC+01:00  Warsaw", out)
        self.assertIn("night 4h39m", out)
        self.assertIn("LIVE MAP   https://www.google.com/maps/dir/?api=1&origin=50.0619,19.9581&destination=52.2519,20.9981&travelmode=driving", out)

    def test_route_leave_by_is_consistent(self):
        out = ok("route", "krakow", "ktw", "--arrive", "2026-11-12 04:40")
        leave = datetime.strptime(field(out, "LEAVE BY")[:16], "%Y-%m-%d %H:%M")
        arrive = datetime.strptime(field(out, "ARRIVE")[:16], "%Y-%m-%d %H:%M")
        self.assertEqual((arrive - leave).total_seconds() / 60, hm(field(out, "TOTAL")))
        self.assertEqual(arrive, datetime(2026, 11, 12, 4, 40))

    def test_negative_coordinates(self):
        out = ok("route", "-33.87,151.21", "sydney", "--mode", "walk")
        self.assertIn("-33.87,151.21 -> Sydney", out)

    def test_ocean_crossing_is_flagged(self):
        out = ok("route", "krakow", "jfk")
        self.assertTrue(field(out, "NO ROAD").startswith("leg 1: Krak"))
        self.assertIn(" is on the mainland of Europe, Asia and Africa and John F. Kennedy International Airport (JFK) is in North "
                      "America. No road joins them, so this leg is planned by air and the car stays behind.", out)
        self.assertIn(" | no road: by air, KRK to JFK | ", field(out, "LEG 1"))
        self.assertNotIn("LIVE MAP", out)
        self.assertNotIn("is there a road", out)
        out = ok("route", "waw", "cdg", "jfk", "--mode", "air")
        self.assertNotIn("is there a road", out)
        self.assertNotIn("NO ROAD", out)
        self.assertNotIn("PLAN", out)

    def test_checked_leg_beats_the_estimate(self):
        out = ok("route", "home", "work")
        self.assertIn("80 km road", out)
        self.assertIn("checked 2026-11-08", out)
        self.assertIn("DRIVE      1h00m [checked time", out)
        self.assertIn("80 km road", ok("route", "praca", "dom"))

    def test_names_aliases_and_diacritics(self):
        self.assertEqual(geo.find_place("Krak\u00f3w")["key"], "krakow")
        self.assertEqual(geo.find_place("WARSZAWA")["key"], "warsaw")
        self.assertEqual(geo.find_place("Wiede\u0144")["name"], "Vienna")
        self.assertEqual(geo.find_place("praca")["key"], "work")
        self.assertEqual(geo.find_place("chata")["key"], "cabin")
        self.assertEqual(geo.find_place("KTW")["kind"], "airport")
        code, _, err = run("route", "krakov", "warsaw")
        self.assertEqual(code, 2)
        self.assertIn("Did you mean", err)
        self.assertIn("krakow", err)

    def test_glare(self):
        # mid-November, mid-afternoon: the sun is low in the south-west
        out = ok("route", "krakow", "ostrava", "--depart", "2026-11-10 15:00")
        self.assertIn("low sun ahead", out)
        # the same afternoon heading north puts the sun well off the nose
        self.assertNotIn("GLARE", ok("route", "krakow", "warsaw", "--depart", "2026-11-10 14:30"))
        # and at night there is nothing to be dazzled by
        self.assertNotIn("GLARE", ok("route", "krakow", "ostrava", "--depart", "2026-11-10 20:00"))

    def test_trip(self):
        out = ok("trip", "waw 2026-12-18 06:40 > cdg 09:05", "cdg 10:50 > jfk 13:10", "--home", "warsaw", "--onward", "new_york")
        self.assertIn("| 2h25m |", out)
        self.assertIn("| 8h20m |", out)
        self.assertIn("1h45m (minimum set: 60 min) ok", out)
        self.assertIn("2026-12-18 19:10 Fri UTC+01:00  (home time)", out)
        self.assertIn("SHIFT      -6 h (west)", out)
        self.assertIn("LEAVE BY   2026-12-18 0", out)
        self.assertIn("door to door", out)

    def test_no_road_between_land_masses(self):
        # by bike the leg keeps its straight-line figures and says where each end stands
        for pair, a_land, b_land in (
                (("dublin", "london"), "on the island of Ireland", "on Great Britain"),
                (("palermo", "rome"), "on Sicily", "on the mainland of Europe, Asia and Africa"),
                (("sapporo", "tokyo"), "on Hokkaido", "elsewhere in Japan"),
                (("hobart", "sydney"), "in Tasmania", "elsewhere in Australia"),
                (("honolulu", "washington"), "in Hawaii", "in North America"),
                (("tokyo", "warsaw"), "in Japan", "on the mainland of Europe, Asia and Africa"),
                (("52.2,21.0", "38.9,-77.0"), "on the mainland of Europe, Asia and Africa", "in North America")):
            out = ok("route", *pair, "--mode", "bike")
            self.assertIn(" is %s and " % a_land, field(out, "NO ROAD"), pair)
            self.assertIn(" is %s. No road joins them, so the crossing is by ship, where a ferry runs at all: the figures for "
                          "this leg are a straight line and not a journey. Plan it as a drive for a way across, or try --mode air."
                          % b_land, field(out, "NO ROAD"), pair)
            self.assertNotIn("LIVE MAP", out, pair)
            self.assertNotIn("PLAN", out, pair)
        # one land mass, however far: no warning, and the live map is back
        for pair in (("warsaw", "lisbon"), ("belfast", "dublin"), ("kuching", "pontianak"), ("lisbon", "singapore"),
                     ("anchorage", "panama"), ("reggio di calabria", "rome")):
            out = ok("route", *pair)
            for key in ("NO ROAD", "CROSSING", "CHECK", "PLAN"):
                self.assertNotIn(key, out, pair)
            self.assertIn("LIVE MAP", out, pair)
        # joined by land, not by road
        gap = ("North and South America are joined by land but not by road: the Pan-American Highway breaks at the Darien gap, "
               "roughly 106 km between Yaviza in Panama and Turbo in Colombia [Wikipedia, Darien Gap]")
        self.assertIn("NO ROAD    leg 1: %s, so the crossing is by ship" % gap, ok("route", "panama", "bogota", "--mode", "walk"))
        out = ok("route", "panama", "bogota")
        self.assertIn("NO ROAD    leg 1: %s, so this leg is planned by air and the car stays behind." % gap, out)
        self.assertIn("fly      PTY -> BOG: ", out)
        # by rail the table claims less, and in the air it has nothing to say
        self.assertIn("No road joins them, and this table knows of no railway that does", ok("route", "dublin", "london", "--mode", "rail"))
        self.assertNotIn("NO ROAD", ok("route", "dublin", "london", "--mode", "air"))
        # a point far from any place on file has no country: the old question still stands for a long leg
        out = ok("route", "0,-30", "40,-30")
        self.assertIn("CHECK      leg 1 is 4,448 km in a straight line: is there a road all the way? Try --mode air.", out)
        self.assertNotIn("NO ROAD", out)

    def test_a_drive_with_no_road_is_planned_by_air(self):
        home, far = geo.parse_point("warsaw"), geo.parse_point("washington")
        with contextlib.redirect_stdout(io.StringIO()):     # 'waw' is also a town: the ALSO line is not this test's business
            waw, dca = geo.parse_point("waw"), geo.parse_point("dca")
        d1 = geo.haversine_km(home[1], home[2], waw[1], waw[2]) * 1.25
        d2 = geo.haversine_km(dca[1], dca[2], far[1], far[2]) * 1.25
        flown = geo.haversine_km(waw[1], waw[2], dca[1], dca[2]) * 1.05
        block = flown / 800.0 + 0.5
        wheel, carried = (d1 + d2) / 80.0, 2.0 + block + 0.75
        out = ok("route", "warsaw", "washington", "--depart", "2026-11-14 08:00", "--firn", "--fatigue")
        self.assertIn(" | no road: by air, WAW to DCA | ", field(out, "LEG 1"))
        self.assertEqual(field(out, "PLAN"), "drive    Warsaw -> Warsaw Chopin Airport (WAW): ~%s km, %s" % (core.num(d1), core.fmt_hm(d1 / 80.0)))
        for line in ("airport  2h00m before the flight",
                     "fly      WAW -> DCA: ~%s km, %s as if flown direct" % (core.num(flown), core.fmt_hm(block)),
                     "airport  0h45m to get out",
                     "%s door to door [estimate]: as if flown direct at 800 km/h: which airports a real ticket uses, and any change "
                     "on the way, is the airline's to say. Look the flight up. No car ferry is on file between these two: if the car "
                     "must come, search for one" % core.fmt_hm(wheel + carried)):
            self.assertIn("\n           " + line + "\n", out)
        self.assertEqual(field(out, "ROAD"), "~%s km [estimate: straight line x 1.25]" % core.num(d1 + d2))
        self.assertEqual(field(out, "BY AIR"), "~%s km [estimate: great circle x 1.05, as if flown direct]" % core.num(flown))
        self.assertEqual(field(out, "DRIVE"), "%s at 80 km/h average, and %s for the flight and the airports [car mode]" % (
            core.fmt_hm(wheel), core.fmt_hm(carried)))
        self.assertEqual(field(out, "BREAKS"), "0 x 15 min = 0h00m (one every 2 h)")
        self.assertEqual(field(out, "TOTAL"), "%s [estimate]" % core.fmt_hm(round((wheel + carried) * 1.10 * 60) / 60.0))
        # the sun on the road and the low hours are a driver's matters, and the car does not fly
        self.assertIn("NOTE       light, glare and fatigue are worked out for a drive: with leg 1 in the way, check each drive on its own", out)
        for key in ("LIGHT", "GLARE", "FATIGUE", "LIVE MAP"):
            self.assertNotIn("\n" + key, out)
        self.assertEqual(field(out, "RANGE"), "%s km of 1,500 km [lore] -> %s km left" % (core.num(d1), core.num(1500 - d1)))
        self.assertIn("he does not fly or sail: this is his drive as far as Warsaw Chopin Airport (WAW), where he waits", out)
        code, _, err = run("route", "warsaw", "washington", "--window", "06:00-12:00")
        self.assertNotEqual(code, 0)
        self.assertIn("leg 1 is not a drive: give --depart or --arrive", err)
        # the hours every other command sees are door to door
        self.assertAlmostEqual(geo.estimate_leg(home, far, "car")[2], wheel + carried, places=9)
        self.assertAlmostEqual(geo.estimate_leg(home, far, "car")[1], d1 + d2, places=9)

    def test_which_airport(self):
        """The nearest large airport with scheduled flights within 150 km, before a nearer small one; else any within 300 km."""
        from firnlib import crossing
        for name, want in (("reykjavik", "KEF"), ("warsaw", "WAW"), ("honolulu", "HNL"), ("palermo", "PMO"), ("hobart", "HBA"),
                           ("krakow", "KRK"), ("lhr", "LHR")):
            with contextlib.redirect_stdout(io.StringIO()):
                here = geo.parse_point(name)
            self.assertEqual(crossing.code(crossing.airport_for(here)), want, name)
        self.assertIsNone(crossing.airport_for(geo.parse_point("adamstown")))
        self.assertIsNone(crossing.airport_for(geo.parse_point("0,-30")))
        # never one across the water: Messina's is on Sicily, not the nearer field at Reggio di Calabria
        port = crossing.airport_for(geo.parse_point("messina"))
        self.assertEqual(geo.land_of(port)[0], "sicily")
        table = core.load_data("airports")
        large, scheduled = set(table["large"].split()), set(table["scheduled"].split())
        self.assertFalse(large & scheduled)
        self.assertTrue(len(large) > 1000 and len(scheduled) > 2500)
        import sqlite3
        db = sqlite3.connect(os.path.join(SCRIPTS, "data", "places.db"))
        fields = set(row[0] for row in db.execute("SELECT key FROM place WHERE kind = 'airport'"))
        db.close()
        self.assertTrue(large <= fields and scheduled <= fields)
        self.assertIn("OurAirports", table["source"])

    def test_no_airport_no_boat_is_a_guess_over_water(self):
        from firnlib import crossing
        pace = crossing.sea_speed()
        self.assertTrue(20 < pace < 35)
        a, b = geo.parse_point("adamstown"), geo.parse_point("auckland")
        km = geo.haversine_km(a[1], a[2], b[1], b[2])
        out = ok("route", "adamstown", "auckland")
        self.assertIn("NO ROAD    leg 1: Adamstown is in the Pitcairn Islands and Auckland is in New Zealand. No road joins them, and no "
                      "car ferry between them is on file; no airport with scheduled flights is within 300 km of Adamstown.", out)
        self.assertEqual(field(out, "PLAN"), "by sea   Adamstown -> Auckland: %s km in a straight line at %s km/h, the pace of the "
                         "ferries on file: %s" % (core.num(km), core.trim(pace, 0), core.fmt_hm(km / pace)))
        self.assertIn("a guess, not a journey: no boat is known to run this way. Search for one, or try --mode air", out)
        self.assertEqual(field(out, "BY SEA"), "%s km [a guess: straight line]" % core.num(km))
        self.assertEqual(field(out, "DRIVE"), "0h00m at 80 km/h average, and %s for the water [car mode]" % core.fmt_hm(km / pace))
        # --via forces the one or the other
        out = ok("route", "warsaw", "washington", "--via", "sea")
        self.assertIn(" | no road: a guess over water | ", field(out, "LEG 1"))
        self.assertNotIn("no airport", out)
        out = ok("route", "london", "paris", "--via", "air")
        self.assertIn(" | no road: by air, LHR to ", field(out, "LEG 1"))
        self.assertIn("OR         with the car, by shuttle, Folkestone to Calais: ", out)
        code, _, err = run("route", "london", "paris", "--mode", "rail", "--via", "air")
        self.assertNotEqual(code, 0)
        self.assertIn("--via chooses how a drive gets across water", err)

    def test_channel_crossing_is_in_the_total(self):
        a, b = geo.parse_point("london"), geo.parse_point("paris")
        d1 = geo.haversine_km(a[1], a[2], 51.0817, 1.1673) * 1.25
        d2 = geo.haversine_km(50.9504, 1.8333, b[1], b[2]) * 1.25
        wheel = (d1 + d2) / 80.0
        out = ok("route", "london", "paris")
        self.assertIn(" | by shuttle, Folkestone to Calais | ", field(out, "LEG 1"))
        self.assertIn("CROSSING   leg 1: Great Britain has no road to the mainland. A car crosses on the shuttle train through "
                      "the Channel Tunnel, between Folkestone and Calais, or on a ferry.\n", out)
        self.assertEqual(field(out, "PLAN"), "drive    London -> Folkestone: ~%s km, %s" % (core.num(d1), core.fmt_hm(d1 / 80.0)))
        for line in ("terminal 1h00m before departure [LeShuttle]", "shuttle  Folkestone -> Calais: 0h35m on board [LeShuttle]",
                     "drive    Calais -> Paris: ~%s km, %s" % (core.num(d2), core.fmt_hm(d2 / 80.0)),
                     "%s door to door [estimate]: the quickest ferry is 90 min on board, and a queue at the terminal or the port "
                     "is not counted [LeShuttle]" % core.fmt_hm(wheel + 95 / 60.0)):
            self.assertIn("\n           " + line + "\n", out)
        self.assertTrue(field(out, "OR").startswith("by air, without the car: "))
        self.assertTrue(field(out, "OR").endswith(". Add --via air for that plan"))
        self.assertEqual(field(out, "ROAD"), "~%s km [estimate: straight line x 1.25]" % core.num(d1 + d2))
        self.assertEqual(field(out, "DRIVE"), "%s at 80 km/h average, and 1h35m for the crossing [car mode]" % core.fmt_hm(wheel))
        self.assertEqual(int(wheel // 2), 2)
        self.assertEqual(field(out, "BREAKS"), "2 x 15 min = 0h30m (one every 2 h)")       # the crossing earns no break
        total = round((wheel + 95 / 60.0 + 0.5) * 1.10 * 60) / 60.0
        self.assertEqual(field(out, "TOTAL"), "%s [estimate]" % core.fmt_hm(total))
        self.assertIn("LIVE MAP", out)
        self.assertNotIn("BY AIR", out)
        # he rides the shuttle with the car, so the range is the road on both sides
        self.assertEqual(field(ok("route", "london", "paris", "--firn"), "RANGE"),
                         "%s km of 1,500 km [lore] -> %s km left" % (core.num(d1 + d2), core.num(1500 - d1 - d2)))
        # a train goes through the tunnel; a bicycle does not
        out = ok("route", "london", "paris", "--mode", "rail")
        self.assertNotIn("CROSSING", out)
        self.assertNotIn("NO ROAD", out)
        self.assertIn("NO ROAD    leg 1: London is on Great Britain", ok("route", "london", "paris", "--mode", "bike"))
        # a checked leg already holds its crossing
        key, text, hours = geo.land_note(a, b, "car", checked=True)
        self.assertEqual((key, hours), ("CROSSING", 0.0))
        self.assertTrue(text.endswith("or on a ferry. The checked figure for this leg is taken to hold the crossing"))
        self.assertAlmostEqual(geo.estimate_leg(a, b, "car")[2], wheel + 95 / 60.0, places=9)
        self.assertAlmostEqual(geo.estimate_leg(a, b, "rail")[2], geo.haversine_km(a[1], a[2], b[1], b[2]) * 1.30 / 90.0, places=9)
        self.assertAlmostEqual(geo.ground_leg(a, b, "car")[2], geo.haversine_km(a[1], a[2], b[1], b[2]) * 1.25 / 80.0, places=9)

    def test_a_car_ferry_on_file_carries_the_car(self):
        out = ok("route", "dublin", "london")
        self.assertIn("CROSSING   leg 1: Dublin is on the island of Ireland and London is on Great Britain. No road joins them: a car "
                      "is carried, on the Irish Sea ferry.\n", out)
        self.assertEqual(field(out, "PLAN"), "terminal 0h30m before departure [Direct Ferries]")
        self.assertIn("\n           ferry    Dublin -> Holyhead: 3h15m on board [Direct Ferries]\n", out)
        self.assertIn("a queue at the terminal or the port is not counted [Direct Ferries]", out)
        self.assertIn(", and 3h45m for the crossing [car mode]", field(out, "DRIVE"))
        self.assertIn("LIVE MAP", out)
        # of two crossings between the same shores, the one that gets there sooner
        for pair, line in ((("belfast", "glasgow"), "ferry    Belfast -> Cairnryan: 2h15m on board [Stena Line timetable]"),
                           (("cork", "cardiff"), "ferry    Dublin -> Holyhead: 3h15m on board [Direct Ferries]"),
                           (("rome", "palermo"), "ferry    Villa San Giovanni -> Messina: 0h20m on board [Traghettilines]"),
                           (("wellington", "christchurch"), "ferry    Wellington -> Picton: 3h30m on board [Interislander]"),
                           (("sapporo", "tokyo"), "ferry    Hakodate -> Aomori: 3h40m on board [AFerry]"),
                           (("victoria_ca", "vancouver"), "ferry    Swartz Bay -> Tsawwassen: 1h35m on board [britishcolumbia.com]")):
            out = ok("route", *pair)
            self.assertIn("\n           " + line + "\n", out, pair)
            self.assertIn("CROSSING   leg 1: ", out, pair)
            self.assertNotIn("NO ROAD", out, pair)

    def test_the_sea_is_named_wherever_a_leg_is_estimated(self):
        out = ok("convoy", "anna:dublin", "ben:paris", "cy:leeds", "--to", "london", "--arrive", "2026-11-14 18:00")
        self.assertIn("CROSSING   Anna: Dublin is on the island of Ireland and London is on Great Britain. No road joins them: a car is "
                      "carried, on the Irish Sea ferry. By ferry, Dublin to Holyhead: 3h15m on board after 0h30m at the terminal, ", out)
        self.assertIn(" door to door, in the total. A queue at the terminal or the port is not counted [Direct Ferries].", out)
        self.assertIn("CROSSING   Ben: Great Britain has no road to the mainland.", out)
        self.assertIn("By shuttle, Calais to Folkestone: 0h35m on board after 1h00m at the terminal, ", out)
        self.assertIn("on the move + 2 breaks", field(out, "BEN"))
        self.assertEqual(out.count("NO ROAD") + out.count("CROSSING"), 2)
        out = ok("tour", "london", "paris", "brussels", "dublin")
        self.assertIn("CROSSING   leg 1: Great Britain has no road", out)
        self.assertIn("NO ROAD    leg 3: Paris is on the mainland of Europe, Asia and Africa and Dublin is on the island of Ireland. "
                      "No road joins them, so this leg is planned by air and the car stays behind. By air, ", out)
        out = ok("trip", "lhr 2026-12-18 10:40 > cdg 12:55", "--home", "paris", "--onward", "london")
        self.assertIn("CROSSING   the way to London Heathrow Airport (LHR): Great Britain has no road", out)
        self.assertIn("CROSSING   onward to London: Great Britain has no road", out)
        out = ok("brief", "warsaw", "washington")
        self.assertIn("NO ROAD    leg 1: Warsaw is on the mainland", out)
        self.assertIn("PLAN       drive    Warsaw -> Warsaw Chopin Airport (WAW): ", out)
        self.assertIn("\n           fly      WAW -> DCA: ", out)
        self.assertIn("BY AIR     ~", out)
        self.assertIn("OR         by air, without the car: ", ok("brief", "london", "paris"))

    def test_land_mass_table(self):
        table = core.load_data("landmasses")
        filed = [cc for ccs in table["countries"].values() for cc in ccs]
        self.assertEqual(len(filed), len(set(filed)))
        self.assertEqual(len(table["own"]), len(set(table["own"])))
        self.assertFalse(set(filed) & set(table["own"]))
        self.assertTrue(set(table["phrases"]) <= set(table["own"]))
        self.assertTrue(set(table["countries"]) <= set(table["masses"]))
        for mass, cc, south, north, west, east in table["boxes"]:
            self.assertIn(mass, table["masses"])
            self.assertTrue(-90 <= south < north <= 90 and -180 <= west < east <= 180, (mass, cc))
            self.assertNotEqual(table["countries"].get(mass), [cc], "%s is filed there already" % cc)
        lands = set(table["masses"]) | set(table["own"])
        tagged = lambda text: re.findall(r"\[([^\]]+)\]", text)
        for pair, modes in table["through"].items():
            self.assertTrue(set(pair.split("|")) <= lands and set(modes) <= set(geo.MODES), pair)
        for pair, text in table["gaps"].items():
            self.assertEqual(pair.split("|"), sorted(pair.split("|")))
            self.assertTrue(set(pair.split("|")) <= lands, pair)
            self.assertTrue(tagged(text) and set(tagged(text)) <= set(table["sources"]), pair)
        self.assertEqual(len(table["crossings"]), 7)
        for c in table["crossings"]:
            self.assertIn(c["kind"], ("ferry", "shuttle"))
            self.assertIn(c["source"], table["sources"], c["name"])
            self.assertTrue(0 < c["board_min"] < 24 * 60 and 0 < c["before_min"] <= 180, c["name"])
            self.assertEqual(len(c["ends"]), 2)
            self.assertNotEqual(c["ends"][0][0], c["ends"][1][0])
            for mass, port, lat, lon in c["ends"]:
                self.assertIn(mass, lands, port)
                self.assertTrue(-90 <= lat <= 90 and -180 <= lon <= 180, port)
            for tag in tagged(c.get("why", "") + c.get("more", "")):
                self.assertIn(tag, table["sources"])
        self.assertNotIn("links", table)
        with open(os.path.join(SCRIPTS, "data", "SOURCES.md"), encoding="utf-8") as f:
            self.assertIn("`landmasses.json`", f.read())
        # where the boxes end: the island in, the shore across the water out
        for name, mass in (("honolulu", "hawaii"), ("messina", "sicily"), ("reggio di calabria", "mainland"), ("ushuaia", "tierra-del-fuego"),
                           ("punta arenas", "south-america"), ("st. john's", "newfoundland"), ("vancouver", "north-america"),
                           ("victoria_ca", "vancouver-island"), ("powell river", "north-america"), ("belfast", "ireland"),
                           ("glasgow", "great-britain"), ("christchurch", "nz-south"), ("wellington", "NZ"), ("jayapura", "new-guinea"),
                           ("kupang", "timor"), ("dili", "timor"), ("jakarta", "ID"), ("copenhagen", "mainland"), ("singapore", "mainland"),
                           ("anchorage", "north-america"), ("reykjavik", "IS"), ("yuzhno sakhalinsk", "sakhalin"), ("vladivostok", "mainland")):
            with contextlib.redirect_stdout(io.StringIO()):     # a name two towns share prints an ALSO line
                point = geo.parse_point(name)
            self.assertEqual(geo.land_of(point)[0], mass, name)
        self.assertEqual(geo.land_of(geo.parse_point("reykjavik"))[1], "in Iceland")
        self.assertEqual(geo.land_of(geo.parse_point("manila"))[1], "in the Philippines")
        self.assertIsNone(geo.land_of(geo.parse_point("0,-30")))

    def test_trip_catches_nonsense(self):
        out = ok("trip", "waw 2026-12-18 06:40 > cdg 06:55", "cdg 07:20 > jfk 13:10")
        self.assertIn("CHECK      leg 1", out)
        self.assertIn("TIGHT", out)

    def test_trip_overnight_arrival(self):
        out = ok("trip", "jfk 2026-12-27 18:10 > cdg 07:30")
        self.assertIn("(+1 day)", out)
        self.assertIn("| 7h20m |", out)

    def test_places(self):
        out = ok("places")
        self.assertIn("capitals", out)
        self.assertIn("home set (Home base), work set (The workshop); 1 places of your own; 1 checked legs", out)
        out = ok("places", "--near", "home", "--km", "5")
        self.assertIn("home", out)
        self.assertIn("krakow", out)
        self.assertIn("warsaw", ok("places", "--kind", "capital", "--country", "pl"))
        out = ok("places", "--add", "Ustron", "49.7215", "18.8020", "Europe/Warsaw")
        self.assertIn('"ustron": {"name": "Ustron"', out)
        self.assertIn("personal.json", out)

    def test_gazetteer_is_sane(self):
        places = geo.select(with_own=False)
        self.assertGreater(len(places), 15000)
        self.assertEqual(len(places), int(geo.gazetteer_meta("places")))
        self.assertEqual(len(set(p["key"] for p in places)), len(places), "keys are not unique")
        kinds, zones = {}, set()
        for p in places:
            key = p["key"]
            self.assertEqual(key, core.fold(key), key)
            self.assertTrue(-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180, key)
            self.assertIn(p["kind"], geo.KINDS, key)
            zones.add(p["tz"])
            kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
            if not p["name"].isascii():
                self.assertEqual(desk.check_text(p["name"]), [], key)
        for zone in zones:
            self.assertIsNotNone(chrono.table_tz(zone), "zone %s is not in the zone table" % zone)
        self.assertEqual(kinds, geo.counts())
        self.assertGreaterEqual(kinds["capital"], 200)
        self.assertGreater(kinds["airport"], 10000)
        for name in ("Warsaw", "Tokyo", "Canberra", "Wellington", "Ottawa", "Brasilia", "Nairobi", "Reykjavik", "Funafuti",
                     "Vatican City", "Washington, D.C.", "Kyiv", "Prague", "Bratislava", "Vilnius"):
            p = geo.find_place(name)
            self.assertIsNotNone(p, name)
            self.assertEqual(p["kind"], "capital", name)

    def test_airport_zones(self):
        """Airports take the zone of the nearest listed city in their country. Check that against known answers."""
        expect = {
            "jfk": "America/New_York", "bos": "America/New_York", "ord": "America/Chicago", "msp": "America/Chicago",
            "den": "America/Denver", "phx": "America/Phoenix", "sea": "America/Los_Angeles", "lax": "America/Los_Angeles",
            "hnl": "Pacific/Honolulu", "anc": "America/Anchorage", "yyz": "America/Toronto", "yul": "America/Toronto",
            "yyc": "America/Edmonton", "yvr": "America/Vancouver", "yhz": "America/Halifax", "mex": "America/Mexico_City",
            "cun": "America/Cancun", "gru": "America/Sao_Paulo", "mao": "America/Manaus", "eze": "America/Argentina/Buenos_Aires",
            "scl": "America/Santiago", "lim": "America/Lima", "bog": "America/Bogota", "kef": "Atlantic/Reykjavik",
            "lhr": "Europe/London", "dub": "Europe/Dublin", "lis": "Europe/Lisbon", "mad": "Europe/Madrid", "cdg": "Europe/Paris",
            "ams": "Europe/Amsterdam", "fra": "Europe/Berlin", "waw": "Europe/Warsaw", "ktw": "Europe/Warsaw", "krk": "Europe/Warsaw",
            "prg": "Europe/Prague", "vie": "Europe/Vienna", "hel": "Europe/Helsinki", "ath": "Europe/Athens", "ist": "Europe/Istanbul",
            "svo": "Europe/Moscow", "svx": "Asia/Yekaterinburg", "ovb": "Asia/Novosibirsk", "vvo": "Asia/Vladivostok",
            "dxb": "Asia/Dubai", "doh": "Asia/Qatar", "del": "Asia/Kolkata", "bom": "Asia/Kolkata", "ktm": "Asia/Kathmandu",
            "bkk": "Asia/Bangkok", "sin": "Asia/Singapore", "hkg": "Asia/Hong_Kong", "pek": "Asia/Shanghai", "urc": "Asia/Shanghai",
            "hnd": "Asia/Tokyo", "nrt": "Asia/Tokyo", "icn": "Asia/Seoul", "syd": "Australia/Sydney", "mel": "Australia/Melbourne",
            "bne": "Australia/Brisbane", "adl": "Australia/Adelaide", "per": "Australia/Perth", "drw": "Australia/Darwin",
            "akl": "Pacific/Auckland", "jnb": "Africa/Johannesburg", "cpt": "Africa/Johannesburg", "cai": "Africa/Cairo",
            "nbo": "Africa/Nairobi", "los": "Africa/Lagos", "add": "Africa/Addis_Ababa", "cmn": "Africa/Casablanca",
        }
        wrong = []
        for code, zone in sorted(expect.items()):
            p = geo.find_place(code)
            self.assertIsNotNone(p, "airport %s is missing" % code)
            self.assertEqual(p["kind"], "airport", code)
            a, b = chrono.table_tz(p["tz"]), chrono.table_tz(zone)
            for month in (1, 4, 7, 10):
                t = datetime(2027, month, 15, 12, tzinfo=UTC)
                if t.astimezone(a).utcoffset() != t.astimezone(b).utcoffset():
                    wrong.append("%s has %s, expected the clock of %s" % (code, p["tz"], zone))
                    break
        self.assertEqual(wrong, [])

    def test_airports_sit_near_their_cities(self):
        for airport, city in (("ktw", "katowice"), ("krk", "krakow"), ("waw", "warsaw"), ("cdg", "paris"), ("lhr", "london"),
                              ("fra", "frankfurt"), ("ams", "amsterdam"), ("muc", "munich"), ("vie", "vienna"), ("prg", "prague"),
                              ("jfk", "new_york"), ("lax", "los_angeles"), ("ord", "chicago"), ("nrt", "tokyo"), ("syd", "sydney")):
            a, c = geo.in_gazetteer(airport), geo.find_place(city)
            self.assertIsNotNone(a, airport)
            self.assertIsNotNone(c, city)
            d = geo.haversine_km(a["lat"], a["lon"], c["lat"], c["lon"])
            self.assertTrue(2 <= d <= 75, "%s is %.0f km from %s" % (airport, d, city))

    def test_keys_from_before_the_gazetteer_grew_still_mean_the_same_place(self):
        """A checked leg in someone's personal file names two keys. They must go on meaning what they meant."""
        old = {"krakow": (50.0619, 19.9581, "city"), "warsaw": (52.2519, 20.9981, "capital"), "katowice": (50.2604, 19.02, "city"),
               "ktw": (50.4743, 19.08, "airport"), "waw": (52.1657, 20.9671, "airport"), "jfk": (40.6398, -73.7789, "airport"),
               "new_york": (40.7519, -73.9819, "city"), "tokyo": (35.6869, 139.7495, "capital"),
               "sydney": (-33.9181, 151.1852, "city"), "wellington": (-41.2981, 174.7832, "capital")}
        for key, (lat, lon, kind) in old.items():
            p = geo.in_gazetteer(key)
            self.assertIsNotNone(p, key)
            self.assertEqual(p["kind"], kind, key)
            self.assertLess(geo.haversine_km(lat, lon, p["lat"], p["lon"]), 0.5, key)

    def test_a_place_answers_to_its_names(self):
        self.assertEqual(geo.find_place("Krak\u00f3w")["key"], "krakow")
        self.assertEqual(geo.find_place("KRAKOW")["key"], "krakow")
        self.assertEqual(geo.find_place("monachium")["key"], "munich")          # the Polish name
        self.assertEqual(geo.find_place("kolonia")["key"], "cologne")           # and not the town of that name in Micronesia
        self.assertEqual(geo.find_place("EPKT")["key"], "ktw")
        self.assertEqual(geo.find_station("epkt")["key"], "ktw")
        self.assertIsNone(geo.find_station("ZZZZ"))
        self.assertIsNone(geo.find_place("no such place at all"))
        self.assertIsNone(geo.find_place(""))
        lima = geo.find_place("lima")
        self.assertEqual((lima["kind"], lima["cc"]), ("capital", "PE"))         # the capital, not the airfield coded LIMA
        self.assertEqual(geo.find_station("LIMA")["cc"], "IT")

    def test_a_name_with_a_comma_says_where(self):
        plain = geo.find_place("springfield")
        self.assertEqual(plain["key"], "springfield")
        there = geo.find_place("Springfield, Illinois")
        self.assertEqual(there["key"], "springfield_us_illinois")
        self.assertEqual(geo.find_place("springfield, illinois")["key"], there["key"])
        self.assertEqual(geo.find_place("London, CA")["key"], "london_ca")
        self.assertEqual(geo.find_place("london, gb")["key"], "london")
        self.assertIsNone(geo.find_place("London, Atlantis"))
        self.assertIn("LEG 1      Springfield, Illinois -> Chicago", ok("route", "Springfield, Illinois", "chicago"))

    def test_a_name_that_fits_two_places_is_flagged_once(self):
        out = ok("route", "san_jose", "san_jose", "panama_city")
        self.assertEqual(out.count("ALSO "), 1)
        self.assertIn("ALSO       'san_jose' is read as San Jos", out)
        self.assertIn("san_jose_us = San Jose, California (US)", out)
        self.assertIn("Give the key to choose", out)
        self.assertNotIn("ALSO", ok("route", "san_jose_us", "los_angeles"))     # a key is never ambiguous
        self.assertNotIn("ALSO", ok("route", "london", "paris"))                # London, Ontario is far too small to be meant
        self.assertNotIn("ALSO", ok("route", "krakow", "warsaw"))
        out = ok("time", "2026-07-01 12:00", "--to", "san_jose")
        self.assertIn("ALSO       'san_jose' is read as San Jos", out)          # the clock differs between them, so say so here too
        out = ok("route", "man", "lhr", "--mode", "air")
        self.assertIn("ALSO       'man' is read as Manchester Airport (MAN) (GB). Of the same name: man_ci = Man", out)

    def test_an_own_place_on_a_gazetteer_name_is_remarked_on_only_when_it_is_elsewhere(self):
        today = date(2026, 11, 10)
        base = json.loads(json.dumps(core.personal()))
        base["places"] = {"zakopane": {"name": "The chalet", "lat": 49.2992, "lon": 19.9496, "tz": "Europe/Warsaw"}}
        self.assertEqual([f for f in rebuild.validate(base, today) if f[1] == "places.zakopane"], [])
        base["places"] = {"zakopane": {"name": "A cafe called Zakopane", "lat": 52.23, "lon": 21.01, "tz": "Europe/Warsaw"}}
        found = [f for f in rebuild.validate(base, today) if f[1] == "places.zakopane"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "CHECK")
        self.assertIn("takes the place of the gazetteer's Zakopane, which is", found[0][2])

    def test_the_drivers_own_place_hides_the_gazetteers(self):
        self.assertEqual(geo.find_place("home")["kind"], "home")
        own = [k for k in geo.own_places() if k not in ("home", "work")]
        self.assertEqual(len(own), 1)
        self.assertEqual(geo.find_place(own[0])["key"], own[0])
        self.assertIs(geo.find_place(own[0]), geo.own_place(own[0]))
        near = geo.near(geo.own_place("home")["lat"], geo.own_place("home")["lon"], 1.0)
        self.assertEqual(near[0][1]["key"], "home")
        self.assertNotIn("home", [p["key"] for _, p in geo.near(50.0619, 19.9581, 1.0, with_own=False)])

    def test_near_agrees_with_measuring_everything(self):
        everything = geo.select(with_own=False)
        for lat, lon, km in ((50.0619, 19.9581, 120.0), (64.1466, -21.9426, 400.0), (-17.7, 178.9, 600.0), (89.0, 10.0, 1500.0),
                             (0.0, 0.0, 300.0), (-41.3, 174.8, 250.0)):
            want = sorted(p["key"] for p in everything if geo.haversine_km(lat, lon, p["lat"], p["lon"]) <= km)
            got = geo.near(lat, lon, km, with_own=False)
            self.assertEqual(sorted(p["key"] for _, p in got), want, (lat, lon, km))
            self.assertEqual([d for d, _ in got], sorted(d for d, _ in got))
        towns = geo.near(50.0619, 19.9581, 120.0, kinds=("capital", "city"), with_own=False)
        self.assertTrue(towns and all(p["kind"] in ("capital", "city") for _, p in towns))
        self.assertEqual(geo.nearest(50.0619, 19.9581, 300.0)[1]["key"], "krakow")
        self.assertIsNone(geo.nearest(-60.0, -140.0, 100.0))

    def test_the_gazetteer_cannot_be_written_to(self):
        import sqlite3
        with self.assertRaises(sqlite3.Error):
            geo._gaz().execute("DELETE FROM place")
        self.assertEqual(geo.zones_in("PL"), ["Europe/Warsaw"])
        self.assertGreater(len(geo.zones_in("US")), 5)
        self.assertIn("naturalearthdata.com", geo.gazetteer_meta("sources"))

    def test_places_search(self):
        out = ok("places", "--find", "krak")
        self.assertTrue(out.startswith("krakow "), out)
        self.assertIn("krk ", out)
        self.assertIn("[EPKK]", out)
        self.assertIn("NONE", ok("places", "--find", "qqqqqq"))
        out = ok("places", "--near", "krakow", "--km", "40", "--kind", "airport")
        self.assertIn("krk ", out)
        self.assertNotIn("  city  ", out)
        out = ok("places", "--country", "IS", "--kind", "capital")
        self.assertIn("reykjavik", out)
        self.assertIn("1 shown of 1 matching", out)
        code, _, err = run("route", "krakoww", "warsaw")
        self.assertEqual(code, 2)
        self.assertIn("Did you mean: krakow", err)


def usno_sun_event(day, lat, lon, zenith, rising):
    """The method FIRN 1.2.0 used (USNO Almanac for Computers), kept as an independent cross-check."""
    n = day.timetuple().tm_yday
    lng_h = lon / 15.0
    t = n + ((6 if rising else 18) - lng_h) / 24.0
    m = 0.9856 * t - 3.289
    l = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
    ra = (ra + (math.floor(l / 90) * 90 - math.floor(ra / 90) * 90)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (cos_dec * math.cos(math.radians(lat)))
    if cos_h > 1 or cos_h < -1:
        return None
    h = (360 - math.degrees(math.acos(cos_h)) if rising else math.degrees(math.acos(cos_h))) / 15.0
    ut = h + ra - 0.06571 * t - 6.622 - lng_h
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    expect = base + timedelta(hours=12 - lng_h + (-6 if rising else 6))
    cand = base + timedelta(hours=ut % 24)
    while cand - expect > timedelta(hours=12):
        cand -= timedelta(days=1)
    while expect - cand > timedelta(hours=12):
        cand += timedelta(days=1)
    return cand


class SkyTests(unittest.TestCase):
    def test_sun_agrees_with_independent_method(self):
        compared = 0
        for lat, lon in (KRAKOW, (41.88, -87.63), (-33.87, 151.21), (64.15, -21.94), (1.35, 103.82), (35.68, 139.65)):
            for month in range(1, 13):
                for dom in (1, 11, 21):
                    day = date(2026, month, dom)
                    for alt, zen in ((-0.833, 90.833), (-6.0, 96.0), (-18.0, 108.0)):
                        for rising in (True, False):
                            mine = sky.sun_event(day, lat, lon, alt, rising)
                            ref = usno_sun_event(day, lat, lon, zen, rising)
                            if isinstance(mine, str) or ref is None:
                                continue
                            compared += 1
                            diff = abs((mine - ref).total_seconds()) / 60.0
                            self.assertLess(diff, 12.0 if abs(lat) > 60 else 4.0,
                                            "%s %s alt %s rising %s: %s vs %s" % (day, (lat, lon), alt, rising, mine, ref))
        self.assertGreater(compared, 1000)

    def test_sun_known_values(self):
        out = ok("sun", "krakow", "--date", "2026-06-21")
        self.assertTrue("04:26" <= field(out, "SUNRISE") <= "04:36", field(out, "SUNRISE"))
        self.assertTrue("20:48" <= field(out, "SUNSET") <= "20:58", field(out, "SUNSET"))
        out = ok("sun", "chicago", "--date", "2026-12-21")
        self.assertIn("times in America/Chicago (UTC-06:00)", out)
        self.assertTrue("07:10" <= field(out, "SUNRISE") <= "07:20", field(out, "SUNRISE"))

    def test_sun_position(self):
        noon = sky.solar_noon(date(2026, 6, 21), *KRAKOW)
        elev, az = sky.sun_position(noon, *KRAKOW)
        self.assertAlmostEqual(elev, 90 - KRAKOW[0] + 23.44, delta=0.2)
        self.assertAlmostEqual(az, 180.0, delta=1.0)

    def test_polar_cases(self):
        out = ok("sun", "89,0", "--date", "2026-12-21", "--tz", "utc")
        self.assertIn("polar night", out)
        self.assertIn("DARK       all day", out)
        out = ok("sun", "69.65,18.96", "--date", "2026-06-21", "--tz", "Europe/Oslo")
        self.assertIn("midnight sun", out)
        self.assertIn("no full astronomical darkness", out)

    def test_moon_phases_at_eclipses(self):
        """Eclipses pin new and full moons to the minute."""
        for when, target in ((datetime(2024, 4, 8, 18, 21), 0.0), (datetime(2026, 8, 12, 17, 37), 0.0),
                             (datetime(2025, 3, 14, 6, 55), 180.0), (datetime(2026, 3, 3, 11, 38), 180.0)):
            elong = sky.moon_phase(when.replace(tzinfo=UTC))[0]
            err = abs((elong - target + 180) % 360 - 180)
            self.assertLess(err, 1.0, "%s: elongation off by %.2f deg" % (when, err))
        self.assertLess(sky.moon_phase(datetime(2026, 8, 12, 17, 37, tzinfo=UTC))[1], 0.01)
        self.assertGreater(sky.moon_phase(datetime(2026, 3, 3, 11, 38, tzinfo=UTC))[1], 0.99)

    def test_moon_command(self):
        out = ok("moon", "warsaw", "--date", "2026-11-24")
        self.assertIn("full moon", out)
        self.assertIn("MOONRISE", out)
        self.assertIn("Home base", ok("moon"))


class DiceTests(unittest.TestCase):
    def test_distributions(self):
        d = dice.distribution(dice.parse("3d6"))
        self.assertAlmostEqual(sum(d.values()), 1.0, places=12)
        self.assertAlmostEqual(dice.at_least(d, 15), 20 / 216.0, places=12)
        d = dice.distribution(dice.parse("2d20kh1+5"))
        self.assertAlmostEqual(dice.at_least(d, 15), 1 - (9 / 20.0) ** 2, places=12)
        d = dice.distribution(dice.parse("dis"))
        self.assertAlmostEqual(dice.at_least(d, 11), 0.25, places=12)
        d = dice.distribution(dice.parse("4d6dl1"))
        self.assertAlmostEqual(sum(v * p for v, p in d.items()), 15869 / 1296.0, places=9)
        self.assertAlmostEqual(d[18], 21 / 1296.0, places=12)
        d = dice.distribution(dice.parse("8d10>=7"))
        self.assertAlmostEqual(sum(v * p for v, p in d.items()), 3.2, places=9)
        d = dice.distribution(dice.parse("4dF"))
        self.assertAlmostEqual(d[0], 19 / 81.0, places=12)
        d = dice.distribution(dice.parse("2d6-1d4+3"))
        self.assertEqual((min(d), max(d)), (1, 14))

    def test_keep_matches_brute_force(self):
        for expr, n, sides, keep, high in (("5d6kh3", 5, 6, 3, True), ("4d8kl2", 4, 8, 2, False), ("3d10dh1", 3, 10, 2, False)):
            brute = {}
            for combo in itertools.product(range(1, sides + 1), repeat=n):
                s = sum(sorted(combo, reverse=high)[:keep])
                brute[s] = brute.get(s, 0) + 1
            d = dice.distribution(dice.parse(expr))
            for s, c in brute.items():
                self.assertAlmostEqual(d[s], c / float(sides ** n), places=12, msg="%s at %d" % (expr, s))

    def test_exploding(self):
        d = dice.distribution(dice.parse("1d6!"))
        self.assertAlmostEqual(d[1], 1 / 6.0, places=12)
        self.assertNotIn(6, d)
        self.assertAlmostEqual(d[7], 1 / 36.0, places=12)
        self.assertAlmostEqual(sum(d.values()), 1.0, places=9)

    def test_roll_is_repeatable_and_in_range(self):
        a = ok("roll", "3d6+2", "2d20kh1", "--seed", "7")
        self.assertEqual(a, ok("roll", "3d6+2", "2d20kh1", "--seed", "7"))
        self.assertIn("SEED       7 (repeatable)", a)
        for _ in range(40):
            total = int(re.search(r"= (\d+)", ok("roll", "4d6dl1")).group(1))
            self.assertTrue(3 <= total <= 18)

    def test_bad_dice(self):
        for bad in ("3x6", "d1", "0d6", "2d6kh5", "d6>=", ""):
            self.assertEqual(run("roll", bad)[0], 2, bad)

    def test_odds_output(self):
        self.assertIn("first higher 45% | tie 5% | second higher 50%", ok("odds", "2d6+3", "--vs", "d20"))
        self.assertIn("15 or more: 9.26%", ok("odds", "3d6", "--target", "15"))


class CombatTests(unittest.TestCase):
    def test_lanchester(self):
        self.assertIn("BLUE wins with ~5 of 10 left", ok("lanchester", "10", "15", "--blue-rate", "0.3", "--red-rate", "0.1"))
        out = ok("lanchester", "40", "60", "--blue-rate", "0.02", "--red-rate", "0.01", "--law", "linear", "--red-break", "50")
        self.assertIn("blue 25 | red 30 (broke off)", out)
        a = ok("lanchester", "12", "12", "--blue-rate", "0.1", "--red-rate", "0.1", "--runs", "500", "--seed", "7")
        self.assertEqual(a, ok("lanchester", "12", "12", "--blue-rate", "0.1", "--red-rate", "0.1", "--runs", "500", "--seed", "7"))
        self.assertTrue(40 <= float(re.search(r"blue holds ([\d.]+)%", a).group(1)) <= 60)

    def test_ttk(self):
        out = ok("ttk", "--hp", "1800", "--dmg", "390", "--reload", "7.5")
        self.assertIn("3,120 DPM", out)
        self.assertIn("5 damaging shots", out)
        self.assertIn("TTK        30 s", out)
        out = ok("ttk", "--hp", "2000", "--dmg", "400", "--reload", "24", "--clip", "4", "--intra", "2")
        self.assertIn("3,200 DPM", out)
        out = ok("ttk", "--hp", "1500", "--dmg", "320", "--reload", "6", "--hp-self", "1650", "--vs-dmg", "440", "--vs-reload", "9.5")
        self.assertIn("you win the trade by 4.5 s", out)

    def test_scenario(self):
        a = ok("scenario", "--seed", "4711", "--difficulty", "5")
        self.assertEqual(a, ok("scenario", "--seed", "4711", "--difficulty", "5"))
        self.assertEqual(a.count("SNAG"), 2)
        self.assertIn("TWIST", a)
        self.assertIn("with Ada", a)
        b = ok("scenario", "--seed", "4711", "--difficulty", "1")
        self.assertIn("none: the ground and the weather", b)
        self.assertEqual(field(a, "TERRAIN"), field(ok("scenario", "--seed", "4711", "--mission", "recon"), "TERRAIN"))


class ArmourTests(unittest.TestCase):
    def test_geometry(self):
        self.assertAlmostEqual(armour.impact_angle(45, 30), math.degrees(math.acos(math.cos(math.radians(45)) * math.cos(math.radians(30)))), places=9)
        self.assertAlmostEqual(armour.impact_angle(60, 0, 60), 0.0, places=6)
        self.assertAlmostEqual(armour.impact_angle(0, 0, 0), 0.0, places=9)

    def test_house_rules(self):
        out = ok("armour", "120", "45", "--yaw", "30", "--shell", "ap", "--caliber", "105", "--pen", "225")
        self.assertIn("inspired by World of Tanks", out)
        self.assertIn("EFFECTIVE  177 mm", out)
        self.assertIn("CHANCE     99.5%", out)
        out = ok("armour", "50", "60", "--shell", "ap", "--caliber", "130", "--pen", "260")
        self.assertIn("-9.1 deg -> 50.9 deg (2-calibre boost", out)
        self.assertIn("EFFECTIVE  79 mm", out)
        self.assertNotIn("2-calibre boost", ok("armour", "50", "60", "--shell", "ap", "--caliber", "100"))

    def test_ricochet_and_overmatch(self):
        out = ok("armour", "100", "72", "--shell", "ap", "--caliber", "100")
        self.assertIn("RICOCHET   yes", out)
        self.assertNotIn("EFFECTIVE", out)
        out = ok("armour", "30", "75", "--shell", "ap", "--caliber", "122")
        self.assertIn("OVERMATCH  yes", out)
        self.assertIn("RICOCHET   no: overmatched", out)
        self.assertIn("RICOCHET   no", ok("armour", "100", "80", "--shell", "heat"))
        self.assertIn("RICOCHET   yes", ok("armour", "100", "86", "--shell", "heat"))

    def test_explicit_values_win(self):
        out = ok("armour", "120", "45", "--yaw", "30", "--norm", "5", "--caliber", "105", "--overmatch", "3", "--ricochet", "70")
        self.assertNotIn("RULES", out)
        self.assertIn("EFFECTIVE  177 mm", out)
        self.assertIn("NORMAL     -8 deg", ok("armour", "120", "45", "--shell", "ap", "--norm", "8"))
        self.assertIn("EFFECTIVE  170 mm", ok("armour", "120", "45"))

    def test_range_screen_and_roll(self):
        out = ok("armour", "100", "55", "--shell", "apcr", "--caliber", "90", "--pen-near", "240", "--pen-far", "215", "--dist", "300")
        self.assertIn("226 mm at 300 m", out)
        self.assertIn("224 mm of penetration left", ok("armour", "80", "30", "--shell", "heat", "--pen", "300", "--screen", "20", "--gap", "400"))
        self.assertIn("CHANCE     50%", ok("armour", "100", "0", "--pen", "100", "--rng", "25", "--uniform"))
        self.assertAlmostEqual(armour.pen_chance(100, 87.5, 0.25, 0.33, False), 0.935, delta=0.002)
        self.assertEqual(armour.pen_chance(100, 126, 0.25, 0.33, False), 0.0)
        self.assertEqual(armour.pen_chance(100, 70, 0.25, 0.33, False), 1.0)

    def test_angle_window(self):
        out = ok("angle", "--front", "200", "--front-slope", "30", "--side", "80", "--shell", "ap", "--pen", "170", "--caliber", "100")
        self.assertIn("WINDOW     both plates hold or bounce at yaw 0 to 20 deg", out)
        out = ok("angle", "--front", "120", "--front-slope", "60", "--side", "80", "--shell", "ap", "--pen", "225", "--caliber", "105")
        self.assertIn("no hull angle keeps both plates safe", out)

    def test_spot(self):
        self.assertIn("SPOTTED    at 328 m", ok("spot", "--view", "420", "--camo", "25"))
        self.assertIn("SPOTTED    at 136 m", ok("spot", "--view", "480", "--camo", "30", "--foliage", "50", "--cap", "445", "--min", "50"))
        self.assertIn("SPOTTED    at 445 m", ok("spot", "--view", "600", "--camo", "0"))
        self.assertIn("SPOTTED    at 50 m", ok("spot", "--view", "400", "--camo", "100"))


class LatticeTests(unittest.TestCase):
    def state(self, out):
        return field(out, "STATE")

    def test_veil_cost_and_overheat(self):
        s0 = self.state(ok("lattice", "--temp", "-3"))
        out = ok("lattice", "--state", s0, "veil=full", "wait=45")
        self.assertIn("30 km of range a minute", out)
        self.assertIn("range 1,477.5 km", out)
        self.assertIn("heat 45/180 s", out)
        out = ok("lattice", "--state", s0, "veil=full", "wait=4m")
        self.assertIn("OVERHEAT   t=3:00.0", out)
        self.assertIn("Veil off (LOCKED), heat 120/180 s", out)
        self.assertIn("REFUSED", ok("lattice", "--state", self.state(out), "veil=full"))
        out = ok("lattice", "--state", s0, "veil=full", "wait=4m", "wait=2m", "veil=full")
        self.assertIn("COOL       t=6:00.0", out)
        self.assertNotIn("REFUSED", out)

    def test_partial_veil_is_a_quarter(self):
        out = ok("lattice", "veil=partial:front", "wait=4m")
        self.assertIn("7.5 km of range a minute", out)
        self.assertIn("range 1,470.0 km", out)
        self.assertIn("heat 60/180 s", out)

    def test_charging_a_docked_armour(self):
        out = ok("lattice", "armour=1")
        self.assertIn("one docked armour charged from empty: -100 km: range 1,500.0 -> 1,400.0 km", out)
        self.assertIn("how long charging takes has no figure", out)
        self.assertIn("range 1,350.0 km", ok("lattice", "armour=1.5"))
        out = ok("lattice", "--km", "40", "armour=1")
        self.assertIn("-40 km: range 40.0 -> 0.0 km", out)
        self.assertIn("only 40% of that charge was delivered", out)
        self.assertIn("costs 100 km", ok("lattice"))
        self.assertEqual(run("lattice", "armour=3")[0], 2)
        self.assertEqual(run("lattice", "armour=none")[0], 2)

    def test_weakness_rime_and_exposure(self):
        out = ok("lattice", "--temp", "-3", "hit=left:heavy", "wait=0.3", "hit=right:heavy", "wait=30", "hit=left:heavy")
        self.assertIn("the known weakness", out)
        self.assertIn("SOFT: no bloom", out)
        self.assertIn("soft until t=1:00.0", out)
        self.assertIn("soft until t=2:00.0", ok("lattice", "--temp", "25", "hit=left:heavy"))
        self.assertNotIn("known weakness", ok("lattice", "hit=left:heavy", "wait=0.6", "hit=right:heavy"))
        self.assertIn("EXPOSED", ok("lattice", "hit=front:heavy", "wait=0.2", "hit=rear:heavy", "wait=0.2", "hit=front:heavy:surprise"))

    def test_range_runs_out_and_air(self):
        out = ok("lattice", "--km", "31", "veil=full", "drive=20@60")
        self.assertIn("Veil dropped", out)
        self.assertIn("OUT OF RANGE: stopped 19 km short", out)
        self.assertIn("1 of 20 km", out)
        out = ok("lattice", "seal", "wait=50m", "unseal")
        self.assertIn("AIR        t=45:00.0", out)
        self.assertIn("45:00.0 of independent air used: the supply is exhausted", out)

    def test_state_round_trip_and_preview(self):
        s = self.state(ok("lattice", "--temp", "-5", "veil=partial:left", "wait=90", "hit=top:heavy", "seal", "wait=10", "silent=on"))
        led = lattice.Ledger(core.load_data("lore"))
        led.load(s)
        self.assertEqual(led.token(), s)
        self.assertTrue(led.silent)
        self.assertEqual(led.veil, "off")
        s0 = self.state(ok("lattice"))
        out = ok("lattice", "--state", s0, "cost=full:240")
        self.assertIn("NOT POSSIBLE: emitters trip after 3:00.0", out)
        self.assertEqual(self.state(out), s0)

    def test_bad_input(self):
        self.assertEqual(run("lattice", "--state", "garbage")[0], 2)
        self.assertEqual(run("lattice", "veil=sideways")[0], 2)
        self.assertEqual(run("lattice", "hit=nose:heavy")[0], 2)


class LatticeKindsTests(unittest.TestCase):
    def test_a_blast_gets_nothing_from_the_scales(self):
        out = ok("lattice", "--temp", "-3", "hit=under:heavy:blast", "wait=20", "hit=under:heavy:blast")
        self.assertIn("scales: unstacked, a blast gives them no point to stack against", out)
        self.assertIn("rime: bloomed and spread the load; soft until t=1:00.0", out)
        self.assertIn("-> spread by the Rime.", out)
        self.assertIn("-> EXPOSED: rime soft, nothing to stack against, no Veil on this face - only the cell stands behind this blast", out)
        self.assertIn("pressure, fragments and gas kept out", out)
        self.assertIn("stack=-", field(out, "STATE"), "a blast must not leave tiles stacked")
        self.assertIn("-> taken on the Veil.", ok("lattice", "veil=full", "hit=left:heavy:blast"))
        self.assertIn("-> shrugged off.", ok("lattice", "hit=left:light:explosion"))

    def test_a_beam_is_drunk_once(self):
        out = ok("lattice", "--temp", "-3", "hit=front:light:beam", "wait=5", "hit=front:heavy:beam")
        self.assertIn("scales: cannot stack in time against light | rime: drank the heat and boiled off; soft until t=1:00.0", out)
        self.assertIn("-> stopped by the Rime, once", out)
        self.assertIn("-> EXPOSED: a beam on a face that is already soft - only the cell stands behind it", out)
        out = ok("lattice", "veil=partial:right", "hit=right:heavy:laser", "hit=left:light:beam")
        self.assertIn("veil: up on this face, and it scatters the beam", out)
        self.assertIn("-> scattered by the Veil, at the Veil's usual cost", out)
        self.assertIn("veil: up, but not on this face | scales: cannot stack", out)
        out = ok("lattice", "smoke=on", "hit=rear:light:beam", "hit=rear:heavy:beam")
        self.assertIn("SMOKE      screen out from the sills", out)
        self.assertIn("-> lost in the smoke", out)
        self.assertIn("smoke: a quarter gets through | scales: cannot stack in time against light | rime: drank the heat", out)
        self.assertIn("| smoke out", field(out, "LEDGER"))
        state = field(out, "STATE")
        self.assertTrue(state.endswith("/smoke=1"))
        led = lattice.Ledger(core.load_data("lore"))
        led.load(state)
        self.assertTrue(led.smoke)
        self.assertEqual(led.token(), state)
        self.assertNotIn("smoke", field(ok("lattice", "--state", state, "smoke=off"), "STATE"))

    def test_a_hand_weapon_is_a_light_hit_at_most(self):
        out = ok("lattice", "hit=left:heavy:blade", "hit=left:heavy:arrow", "hit=left:light:club")
        self.assertEqual(out.count("a hand weapon: a light hit at most, whatever the arm behind it"), 3)
        self.assertEqual(out.count("rime: untouched (light hit)"), 3)
        self.assertNotIn("soft until", out)
        self.assertIn("soft until", ok("lattice", "hit=left:heavy:ram"))
        self.assertIn("(surprise) - a hand weapon", ok("lattice", "hit=left:light:hand:surprise"))
        self.assertEqual(run("lattice", "hit=left:heavy:nonsense")[0], 2)
        self.assertEqual(run("lattice", "hit=left:heavy:beam:blast")[0], 2)
        self.assertEqual(run("lattice", "smoke=maybe")[0], 2)

    def test_life_first_shows_in_the_tools(self):
        self.assertIn("LIVES      every life on the board counts the same, the opposition's included", ok("scenario", "--seed", "1"))
        self.assertIn("in his hands a module stops things, not people", ok("scenario", "--seed", "1"))
        self.assertIn("LIVES      every life counts the same here, whichever side it is on", ok("triage", "a: x=lost", "b: y=repair"))
        fit = ok("record", "--fit")
        self.assertIn("NOT FITTED weapons [maker] - none by default; mission modules only when listed on the brief, and in his hands", fit)
        lore = core.load_data("lore")
        self.assertEqual(sum(1 for line in lore["assumptions"] if "[maker]" in line), 18)


class TriageTests(unittest.TestCase):
    def test_ranking(self):
        out = ok("triage", "left: driver=lost", "right: construct=repair")
        self.assertIn("RANK 1     right", out)
        self.assertIn("loses nothing for good", out)
        out = ok("triage", "right: construct=repair", "left: driver=lost", "wall: self=repair")
        self.assertIn("RANK 1     wall", out)
        self.assertIn("spends the car instead of someone else", out)
        self.assertIn("RANK 1     hold", ok("triage", "hold: bystanders=fine, self=repair@80%", "run: bystanders=lost@60%"))
        self.assertIn("TIE on the physical facts", ok("triage", "a: x=hurt", "b: y=hurt"))

    def test_bad_option(self):
        self.assertEqual(run("triage", "only one: x=lost")[0], 2)
        self.assertEqual(run("triage", "a: x=vaporised", "b: y=fine")[0], 2)


class VehicleTests(unittest.TestCase):
    def test_perf(self):
        out = ok("perf", "--firn")
        self.assertIn("858 kW (1,150 hp), 2,940 kg, AWD", out)
        self.assertIn("-> consistent", out)
        self.assertIn("implies ~397 kWh in the capacitor bank [derived from lore]", out)
        self.assertIn("canon rounds that to 400 kWh [lore]", out)

    def test_canon_has_three_origins(self):
        """Since 2.3.2 a line of canon comes from the maker, the sheet or FIRN himself. 'derived' is left to the tools,
        where it means an exact sum."""
        lore = core.load_data("lore")
        origins = {"maker", "sheet", "firn"}
        self.assertEqual(set(lore["chassis_tags"].values()) | set(lore["lattice_tags"].values()), {"maker", "sheet"})
        self.assertEqual(set(row[1] for kind in ("fitted", "not_fitted") for row in lore["fit"][kind]), origins)
        for line in lore["assumptions"]:
            self.assertRegex(line, r"\[(maker|house rules, \d+ \w+ \d{4})\]$")
        self.assertNotIn("derived", lore["note"])
        self.assertEqual((lore["chassis"]["bank_kwh"], lore["chassis_tags"]["bank_kwh"]), (400, "maker"))
        self.assertEqual((lore["chassis"]["power_kw"], lore["chassis_tags"]["power_kw"]), (858, "sheet"))
        self.assertAlmostEqual(lore["chassis"]["power_hp"] * 0.7457, lore["chassis"]["power_kw"], delta=1)   # a plain conversion
        self.assertIn("NOT FITTED amphibious or flight gear [sheet] - not on the sheet", ok("record", "--fit"))
        with open(os.path.join(ROOT, "src", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        tags = skill[skill.index("Provenance tags:"):skill.index("Your driver")]
        self.assertEqual(re.findall(r"(?m)^- \[(\w+)\]", tags), ["maker", "sheet", "firn"])
        self.assertNotIn("[maker][derived]", skill)
        self.assertIn("Your bank holds about 400 kWh", skill)
        self.assertIn("derived (calculated)", skill)                # the confidence tag for a number stays

    def test_the_core_carries_no_history(self):
        """SKILL.md is read every time the skill loads: a fact and its tag, no dates and no story of who ruled what.
        The two dates it keeps are his first boot and the example of a log line."""
        with open(os.path.join(ROOT, "src", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        dated = [line for line in skill.splitlines() if re.search(r"\b\d{1,2} \w+ 20\d\d\b|\b20\d\d-\d\d-\d\d\b", line)]
        self.assertEqual(len(dated), 2, dated)
        self.assertTrue(dated[0].startswith("- First boot:"), dated[0])
        self.assertTrue(dated[1].startswith("`LOG "), dated[1])
        lore = core.load_data("lore")
        for text in [lore["squall"]["note"]] + lore["assumptions"]:
            self.assertNotRegex(text, r"\b\d{1,2} \w+ 20\d\d\b")
        t = float(field(ok("perf", "--kw", "283", "--kg", "1580", "--drive", "rwd", "--front-pct", "38", "--cd", "0.29", "--area", "2.0"), "0-100").split()[0])
        self.assertTrue(3.6 <= t <= 4.6, t)
        t = float(field(ok("perf", "--hp", "110", "--kg", "1300", "--drive", "fwd"), "0-100").split()[0])
        self.assertTrue(9.0 <= t <= 12.5, t)

    def test_stop(self):
        out = ok("stop", "--from", "130", "--surface", "wet")
        self.assertIn("REACTION   36.1 m", out)
        self.assertIn("BRAKING    133 m", out)
        self.assertIn("still doing 30 km/h", ok("stop", "--from", "60", "--obstacle", "30"))
        self.assertIn("TOTAL      152.9 m", ok("stop", "--from", "250", "--to", "90", "--g", "1.4", "--reaction", "0"))
        self.assertIn("TOTAL      115 m", ok("stop", "--from", "100mph", "--motor-kw", "858", "--kg", "2940", "--reaction", "0", "--mu", "1.05"))

    def test_impact_corner_transfer_spring(self):
        out = ok("impact", "--kg", "2940", "--speed", "80", "--vs-kg", "3100", "--vs-speed", "80")
        self.assertIn("726 kJ", out)
        self.assertIn("first vehicle 82 km/h, other 78 km/h", out)
        self.assertIn("115 km/h at 1.3 g", ok("corner", "--radius", "80", "--mu", "1.3"))
        out = ok("transfer", "--kg", "1300", "--cg", "0.45", "--wheelbase", "2.6", "--track", "1.6", "--front-pct", "48", "--ax", "-1.2", "--ay", "1.4")
        self.assertIn("moves 270 kg to the front", out)
        self.assertIn("LIFTS", out)
        self.assertIn("70.5 N/mm | 7.19 kgf/mm", ok("spring", "--hz", "2.4", "--corner-kg", "310"))
        self.assertIn("2.4 Hz", ok("spring", "--rate", "7.19kgf/mm", "--corner-kg", "310"))

    def test_gearing_and_tyre(self):
        out = ok("gearing", "--ratios", "2.9", "2.0", "1.5", "1.2", "1.0", "0.84", "--tyre", "305/30R20", "--redline", "8500", "--kph", "320")
        self.assertIn("FINAL      4.119", out)
        out = ok("tyre", "225/45R17 94W", "--vs", "205/55R16", "--bar", "2.4", "--set-temp", "20", "--now-temp", "-5")
        self.assertIn("diameter 634 mm", out)
        self.assertIn("index 94 = 670 kg", out)
        self.assertIn("symbol W = up to 270 km/h", out)
        self.assertIn("reads 2.11 bar at -5 C", out)
        self.assertEqual((dynamics.LOAD_INDEX[91], len(dynamics.LOAD_INDEX)), (615, 66))


class EnergyRacingTests(unittest.TestCase):
    def test_range(self):
        self.assertIn("LEFT       1,020 km", ok("range", "--veil-full", "2", "--distance", "420"))
        self.assertIn("HEAT", ok("range", "--veil-full", "4"))
        out = ok("range", "--battery-kwh", "77", "--kwh-per-100", "18", "--soc", "80", "--distance", "200")
        self.assertIn("~342 km", out)

    def test_ev_and_fuel(self):
        self.assertIn("~312 km", ok("ev", "range", "--battery", "77", "--kwh-100", "18.5", "--temp", "-5"))
        self.assertIn("+53.9 kWh in 0h25m", ok("ev", "charge", "--battery", "77", "--start", "10", "--to", "80", "--kw", "150"))
        self.assertIn("+61.6 kWh in 5h36m", ok("ev", "charge", "--battery", "77", "--start", "20", "--to", "100", "--kw", "11", "--ac"))
        out = ok("ev", "trip", "--battery", "77", "--kwh-100", "19", "--distance", "620", "--kw", "150", "--temp", "0")
        self.assertIn("STOPS      2", out)
        self.assertIn("arrive with 15%", out)
        out = ok("fuel", "--distance", "342", "--l-100", "6.5", "--price", "6.49", "--people", "2")
        self.assertIn("22.2 l of petrol", out)
        self.assertIn("72.14 each for 2", out)
        self.assertIn("7.4 l/100 km", ok("fuel", "--distance", "120", "--mpg-us", "32"))

    def test_stint_and_pace(self):
        out = ok("stint", "--laps", "40", "--lap", "1:42.5", "--fuel-lap", "3.2", "--tank", "100", "--pit", "28", "--tyre-life", "16", "--deg", "0.06")
        self.assertIn("push      2  14-13-13         40  1:09:30.820", out)
        self.assertIn("push, 1 stop: a 20-lap stint outlasts the tyres", out)
        out = ok("stint", "--laps", "30", "--lap", "1:40", "--fuel-lap", "4.2", "--tank", "100", "--pit", "30")
        self.assertIn("needs 3.3 per lap or less", out)
        out = ok("stint", "--minutes", "60", "--lap", "1:42.5", "--fuel-lap", "3.2", "--tank", "100", "--pit", "28", "--save", "1:43.4,2.7")
        self.assertIn("save 1      0  35", out)
        self.assertIn("204 km/h average", ok("pace", "--lap", "1:42.5", "--km", "5.807"))
        self.assertIn("1.25 s a lap faster", ok("pace", "--gap", "12.5", "--laps-left", "10"))
        self.assertEqual(run("pace")[0], 2)


class GarageSpaceTests(unittest.TestCase):
    def test_convert(self):
        self.assertIn("857.6 kw", ok("convert", "1150", "hp", "kw"))
        self.assertIn("7.84 l/100km", ok("convert", "30", "mpg-us", "l/100km"))
        self.assertIn("-40 c", ok("convert", "-40", "f", "c"))
        self.assertIn("2.21 bar", ok("convert", "32", "psi", "bar"))
        self.assertIn("112.7 km/h", ok("convert", "70", "mph", "km/h"))
        self.assertIn("15.53 kwh/100km", ok("convert", "250", "wh/mi", "kwh/100km"))
        self.assertIn("6.84 deg", ok("convert", "12", "%", "deg"))
        self.assertEqual(run("convert", "5", "kg", "km")[0], 2)

    def test_obd_and_lights(self):
        out = ok("obd", "P0420", "P0304", "P0353", "P1234")
        self.assertIn("Catalyst efficiency below threshold (bank 1)", out)
        self.assertIn("Cylinder 4 misfire detected", out)
        self.assertIn("Ignition coil C", out)
        self.assertIn("maker-specific", out)
        for code in core.load_data("obd")["codes"]:
            self.assertRegex(code, r"^[PBCU][0-3][0-9A-F]{3}$")
        self.assertIn("stop and switch the engine off at once", ok("lights", "oil"))
        self.assertIn("Flashing: a misfire is happening now", ok("lights", "check", "engine"))
        self.assertIn("NONE", ok("lights", "flux", "capacitor"))

    def test_space(self):
        self.assertIn("7.673 km/s, one lap in 1h32m", ok("space", "orbit", "--alt", "400"))
        self.assertIn("total 3,857 m/s", ok("space", "hohmann", "--alt", "400", "--to-alt", "35786"))
        self.assertIn("DELTA-V    4,132 m/s", ok("space", "dv", "--isp", "350", "--wet", "100", "--dry", "30"))
        self.assertIn("factor 6 = 392 times light speed [lore: Star Trek, Next Generation scale", ok("space", "warp", "6"))
        self.assertEqual(run("space", "orbit", "--alt", "80", "--body", "pluto")[0], 2)
        self.assertIn("1,909 times", ok("space", "warp", "9.6"))
        self.assertEqual(run("space", "warp", "10")[0], 2)


class SecondLifeTests(unittest.TestCase):
    def test_reference(self):
        out = ok("lsl", "defaults", "--type", "car")
        self.assertIn("VEHICLE_ANGULAR_MOTOR_DECAY_TIMESCALE   0.8", out)
        self.assertIn("VEHICLE_FLAG_HOVER_UP_ONLY        set", out)
        self.assertIn("VEHICLE_HOVER_HEIGHT", ok("lsl", "params", "--find", "hover"))
        self.assertIn("0x400", ok("lsl", "flags"))
        self.assertIn("about 30 m/s", ok("lsl", "limits"))
        data = core.load_data("lsl")
        self.assertEqual(len(data["float_params"]) + len(data["vector_params"]) + len(data["flags"]) + 6, 40)
        self.assertEqual((len(data["controls"]), len(data["camera"])), (10, 14))
        for name, vals in data["defaults"].items():
            self.assertEqual(sorted(vals), sorted(sl.TYPES), name)

    def test_skeletons_are_clean(self):
        for kind in ("car", "boat"):
            for camera in (True, False):
                src = sl.skeleton(kind, 22.0, 6.0, 2.2, "0.3,0.0,0.5", "drive", camera)
                self.assertEqual(sl.lint(src), [], "%s camera=%s" % (kind, camera))
                self.assertEqual(desk.check_text(src, code=True), [])
                self.assertEqual(src.count("{"), src.count("}"))
                self.assertIn("llTakeControls(", src)
                self.assertIn("run_time_permissions", src)
                self.assertEqual("camera()" in src, camera)
        self.assertEqual(run("lsl", "skeleton", "--speed", "45")[0], 2)
        self.assertEqual(run("lsl", "skeleton", "--sit", "0,0,0")[0], 2)

    def test_every_type_has_a_skeleton(self):
        for kind in sl.TYPES:
            for camera in (True, False):
                src = sl.skeleton(kind, None, None, None, "0.3,0.0,0.5", "", camera)
                self.assertEqual(sl.lint(src), [], "%s camera=%s" % (kind, camera))
                self.assertEqual(desk.check_text(src, code=True), [])
                for open_, close in ("{}", "()", "[]"):
                    self.assertEqual(src.count(open_), src.count(close), kind)
                self.assertIn("llSetVehicleType(VEHICLE_TYPE_%s);" % kind.upper(), src)
                self.assertIn("STATUS_PHYSICS, TRUE", src)
        plane = sl.skeleton("airplane", None, None, None, "0.3,0.0,0.5", "", True)
        for line in ("float FWD = 25.0;", "float ROLL = 2.0;", "CONTROL_UP | CONTROL_DOWN, TRUE, FALSE);",
                     "if (pressed & CONTROL_UP) gThrottle += 0.25;", "<FWD * gThrottle, 0.0, 0.0>", "VEHICLE_BANKING_EFFICIENCY, 1.0"):
            self.assertIn(line, plane)
        balloon = sl.skeleton("balloon", None, None, None, "0.3,0.0,0.5", "", True)
        for line in ("float FWD = 4.0;", "float gHeight = 5.0;", "llSetVehicleFloatParam(VEHICLE_HOVER_HEIGHT, gHeight);",
                     "VEHICLE_BUOYANCY, 1.0"):
            self.assertIn(line, balloon)
        sled = sl.skeleton("sled", None, None, 1.5, "0.3,0.0,0.5", "", True)
        for line in ("float TURN = 1.5;", "vector SLIDE = <30.0, 1.0, 1000.0>;", "integer brake = level & CONTROL_BACK;"):
            self.assertIn(line, sled)
        self.assertNotIn("FWD", sled)                                       # no motor
        self.assertNotIn("VEHICLE_LINEAR_MOTOR_DIRECTION, lin", sled)
        for flag, kind in (("--speed", "sled"), ("--reverse", "sled"), ("--reverse", "airplane")):
            code, out, err = run("lsl", "skeleton", "--type", kind, flag, "5")
            self.assertEqual((code, out), (2, ""), (flag, kind))
            self.assertIn("does not apply to a %s" % kind, err)
        self.assertEqual(run("lsl", "skeleton", "--type", "hovercraft")[0], 2)

    def test_new_skeletons_write_out_the_type_defaults(self):
        """Airplane, balloon and sled start from the type's own defaults, but for the settings their comments name."""
        data = core.load_data("lsl")["defaults"]
        own = {("sled", "VEHICLE_ANGULAR_MOTOR_TIMESCALE"): 0.5}
        names = {"gHeight": 5.0, "SLIDE": [30.0, 1.0, 1000.0]}
        for kind in ("airplane", "balloon", "sled"):
            for row in sl._TUNE[kind]:
                want = [float(x) for x in re.findall(r"-?\d+\.?\d*", str(data[row[1]][kind]))]
                got = names.get(row[2])
                if got is None:
                    got = [float(x) for x in re.findall(r"-?\d+\.?\d*", row[2])]
                got = got if isinstance(got, list) else [got]
                if (kind, row[1]) in own:
                    self.assertEqual(got, [own[(kind, row[1])]])
                    self.assertNotEqual(got, want[:1])
                    self.assertEqual(len(row), 4, "a setting that leaves the default says so in a comment")
                    continue
                if len(want) == 1 and len(got) == 3:                        # 'N on all axes'
                    want = want * 3
                self.assertEqual(got, want, "%s %s" % (kind, row[1]))

    def test_compiled_skeletons_are_the_ones_that_were_compiled(self):
        """Pantera compiled these six in-world on 12 November 2026. If the generator's output changes, the claim in
        sl.COMPILED no longer covers it: compile the new text in-world, then put its hash here."""
        import hashlib
        self.assertEqual(sl.COMPILED, dict((kind, "12 November 2026") for kind in sl.TYPES))
        for args, want in ((("--type", "car", "--speed", "22", "--turn", "2.2"), "2747c567f482f60b123679e84af07dddf570584c10399c48cb317533616b10b6"),
                           (("--type", "airplane"), "c4a6a0ada6412da64b25719bb3df4a5e99fa155cda696d311865113782397ed3"),
                           (("--type", "balloon"), "3e27775dec0e9b34445b04aba255a10b6be8dba689bb9f4a2e16e9575fa51d5c"),
                           (("--type", "sled"), "5dfe6a5d3480076f34d03f1e5330411f92c086f4296bf2aa5fdeb498f6b73945"),
                           (("--type", "boat"), "798be03423c5c2d01132d821111b9b0d73e2e8146d252d06cbb08eb4921aa83b"),
                           (("--type", "car", "--speed", "28", "--reverse", "8", "--turn", "3", "--sit", "0.2,0.4,0.6",
                             "--anim", "drive", "--no-camera"), "2b7bebf1b4ae708ddf33deab37dc3e6d6f4794d49cb2d56173ba587c18e4c8c2")):
            code, out, err = run("lsl", "skeleton", *args)
            self.assertEqual((code, err), (0, ""), args)                    # a compiled type prints no note
            self.assertEqual(hashlib.sha256(out.encode("utf-8")).hexdigest(), want, args)
        for kind in sl.TYPES:
            code, out, err = run("lsl", "skeleton", "--type", kind)
            self.assertEqual(code, 0)
            self.assertEqual("has not been compiled in-world yet" in err, kind not in sl.COMPILED, kind)
            self.assertTrue(out.startswith("// Vehicle core: %s." % kind))

    def test_lint_catches_a_member_read_off_an_expression(self):
        """Found on 12 November 2026: '(llGetVel() / llGetRot()).x' does not compile, and the lint let it through."""
        frame = "default\n{\n    state_entry()\n    {\n%s    }\n}\n"
        for line, member in (("        float v = (llGetVel() / llGetRot()).x;\n", "x"), ("        float z = llGetPos().z;\n", "z"),
                             ("        float s = llGetRot() .s;\n", "s"), ("        float y = <1.0, 2.0, 3.0>.y;\n", "y")):
            found = sl.lint(frame % line)
            self.assertEqual([(f[0], f[1]) for f in found], [(5, "WARN")], line)
            self.assertIn("'.%s' on an expression" % member, found[0][2])
        for line in ("        vector v = llGetVel() / llGetRot();\n        float x = v.x;\n",
                     "        vector a;\n        if (a.x > .5) a.y = (a.z);\n", "        llOwnerSay(\"llGetPos().x\");   // llGetPos().x\n"):
            self.assertEqual(sl.lint(frame % line), [], line)

    def test_lint_catches_the_usual_mistakes(self):
        bad = ("default\n{\n    state_entry()\n    {\n        llSetVehicleType(VEHICLE_TYPE_HOVERCRAFT);\n"
               "        llSetBuoyancy(1.0);\n        llTakeControls(CONTROL_FORWARD, TRUE, FALSE);\n    }\n"
               "    control(key id, integer l, integer e)\n    {\n        llOwnerSay(\"x\");\n    }\n}\n")
        text = " | ".join(f[2] for f in sl.lint(bad))
        for want in ("VEHICLE_TYPE_HOVERCRAFT is not an LSL constant", "CONTROL_FORWARD is not an LSL constant",
                     "llSetBuoyancy fights the vehicle engine", "without a run_time_permissions event",
                     "nothing turns STATUS_PHYSICS on", "chat in control() floods"):
            self.assertIn(want, text)
        self.assertEqual(sl.lint("// llSetBuoyancy in a comment\ndefault\n{\n    state_entry()\n    {\n        llOwnerSay(\"VEHICLE_TYPE_NOPE\");\n    }\n}\n"), [])
        with tempfile.NamedTemporaryFile("w", suffix=".lsl", delete=False, encoding="utf-8") as f:
            f.write(bad)
        try:
            self.assertEqual(run("lsl", "lint", f.name)[0], 1)
        finally:
            os.unlink(f.name)


class LogisticsTests(unittest.TestCase):
    def test_convoy(self):
        out = ok("convoy", "anna:krakow", "bob:warsaw", "--to", "katowice", "--arrive", "2026-12-20 18:00")
        self.assertIn("MEET       Katowice by 2026-12-20 18:00 Sun UTC+01:00", out)
        self.assertRegex(out, r"BOB        leaves Warsaw by 2026-12-20 12:5\d")
        self.assertIn("Bob is first out", out)
        self.assertIn("rail", ok("convoy", "anna:krakow@rail", "--to", "prague", "--arrive", "2026-12-20 18:00"))
        self.assertEqual(run("convoy", "anna", "--to", "prague", "--arrive", "18:00")[0], 2)

    def test_checklist(self):
        self.assertIn("WINTER", ok("checklist"))
        out = ok("checklist", "winter")
        self.assertIn("1. scraper and brush", out)
        self.assertEqual(run("checklist", "picnic")[0], 2)

    def test_weather(self):
        out = ok("weather", "--temp", "2", "--road-temp", "-1", "--wet", "--speed", "90")
        self.assertIn("ICE LIKELY", out)
        self.assertIn("on ice: about 344 m", out)
        out = ok("weather", "--temp", "-1", "--humidity", "95", "--wind", "30")
        self.assertIn("DEW POINT  -1.7 C", out)
        self.assertIn("FEELS      -8 C", out)
        self.assertIn("69 km/h across", ok("weather", "--temp", "8", "--wind", "70", "--wind-angle", "80"))
        self.assertIn("ordinary care", ok("weather", "--temp", "18"))


class DeskTests(unittest.TestCase):
    def test_boot(self):
        out = ok("boot", "--seed", "5")
        self.assertIn("CLOCK      2026-11-10 14:30 Tue UTC+01:00  Home base", out)
        self.assertIn("SLT 05:30 Tue (-9 h) | CHICAGO 07:30 Tue (-7 h) | UTC 13:30 Tue (-1 h)", out)
        self.assertIn("day 3 since first boot", out)
        self.assertIn("LATE       no", out)
        self.assertNotIn("SETUP", out)
        self.assertIn("IGNITION   on [setting: every new conversation; pool of 4]", out)
        first = int(re.search(r"ask: .+\?  \(question (\d)\)", out).group(1))
        later = [int(x) for x in re.findall(r"ignition --q (\d)'", out)]
        self.assertEqual(len(set([first] + later)), 3)
        seen = set(re.search(r"\(question (\d)\)", ok("boot")).group(1) for _ in range(60))
        self.assertEqual(seen, set("1234"))

    def test_ignition_never_shows_an_answer(self):
        answers = ["bottle", "butelkowa", "vistula", "wisla", "sprocket", "millimetre", "socket"]
        outputs = [ok("boot") for _ in range(12)] + [ok("ignition")] + [ok("ignition", "--q", str(n)) for n in (1, 2, 3, 4)]
        outputs += [ok("ignition", "--q", "2", "--answer", "the Oder"), ok("ignition", "--q", "1", "--answer", "green"),
                    ok("ignition", "--q", "3", "--answer", "Sprocket")]
        for out in outputs:
            for word in answers:
                self.assertNotIn(word, out.lower().replace("ignition --q 3 --answer", ""))

    def test_ignition_judges_loosely(self):
        def verdict(q, *said):
            return ok("ignition", "--q", str(q), "--answer", *said).split()[0]
        self.assertEqual(verdict(2, "the", "Vistula,", "obviously"), "PASS")
        self.assertEqual(verdict(2, "Wis\u0142a"), "PASS")
        self.assertEqual(verdict(2, "vistla"), "PASS")
        self.assertEqual(verdict(2, "the", "Oder"), "FAIL")
        self.assertEqual(verdict(1, "a", "sort", "of", "green"), "CLOSE")
        self.assertEqual(verdict(1, "GREEN,", "bottle"), "PASS")
        self.assertEqual(verdict(4, "the", "10mm", "socket"), "PASS")
        self.assertEqual(verdict(4, "ten", "millimetre", "socket"), "PASS")
        self.assertEqual(verdict(3, "sproket"), "PASS")
        self.assertEqual(verdict(3, "no", "idea"), "FAIL")
        self.assertEqual(run("ignition", "--q", "9")[0], 2)
        self.assertIn("What colour was the first test car?", ok("ignition", "--q", "1"))

    def test_sheet(self):
        out = ok("sheet")
        self.assertIn("firn-01-reference-sheet.webp", field(out, "SHEET"))
        self.assertIn("reference sheet", field(out, "SHOWS"))
        with tempfile.TemporaryDirectory() as d:
            out = ok("sheet", "--to", d)
            copy = field(out, "COPIED")
            self.assertTrue(os.path.isfile(copy))
            self.assertEqual(os.path.getsize(copy), os.path.getsize(desk.SHEET))
        self.assertEqual(run("sheet", "--to", os.path.join(ROOT, "no-such-folder"))[0], 2)

    def test_record_and_log(self):
        self.assertIn("POWER    1,150 hp peak (858 kW)", ok("record", "--firn"))
        self.assertIn("POWER   17 kW  [maker]", ok("record", "RECORD=City runabout", "POWER=17 kW|maker"))
        out = ok("record", "--fit")
        self.assertIn("grapple [maker]", out)
        self.assertIn("PENDING    a tow hook", out)
        self.assertIn("until Ada keeps it", out)
        self.assertIn("flesh and blood", ok("record", "--family"))
        out = ok("log", "sim", "convoy escort", "raise the Veil later", "--date", "2026-11-08")
        self.assertIn("LOG 2026-11-08 | sim | convoy escort | raise the Veil later", out)
        self.assertIn("give Ada that line", out)
        self.assertIn('under "logbook" in scripts/data/personal.json', out)
        self.assertEqual(run("log", "holiday", "a", "b")[0], 2)
        self.assertEqual(run("log")[0], 2)
        self.assertEqual(run("log", "sim", "only two")[0], 2)

    def test_logbook_on_file(self):
        out = ok("log", "--list")
        self.assertIn("LOGBOOK    2 entries on file, oldest first [kept by Ada]", out)
        self.assertLess(out.index("LOG 2026-11-08 | test"), out.index("LOG 2026-11-09 | sim"))
        boot = ok("boot", "--seed", "1")
        self.assertIn("LOGBOOK    2 entries on file; the latest: 2026-11-09 | sim | convoy escort in snow | raise the Veil later", boot)
        self.assertIn("'log --list' shows them all", boot)

    def test_prompt(self):
        out = ok("prompt", "--view", "side", "--veil")
        self.assertIn("Matte black armoured SUV", out)
        self.assertIn("frost-white", out)
        self.assertIn("no humanoid avatar", out)
        self.assertEqual(run("prompt", "--bar", "purple")[0], 2)

    def test_check(self):
        code, out, _ = run("check", "--text", "He said \u201chello\u201d \u2014 it\u2019s fine")
        self.assertEqual(code, 1)
        self.assertIn("4 to fix", out)
        self.assertIn("clean", ok("check", "--text", "Plain text - with 'straight' quotes. Za\u017c\u00f3\u0142\u0107."))
        self.assertEqual(run("check", "--code", "--text", "x = 1 // za\u017c\u00f3\u0142\u0107")[0], 1)
        self.assertEqual(ok("check", "--fix", "--text", "\u201cA\u201d \u2013 B\u2026").strip(), '"A" - B...')

    def test_selftest_and_tools(self):
        self.assertIn("SELFTEST   12 of 12 passed", ok("selftest"))
        out = ok("tools")
        for name in ("time", "dst", "meet", "span", "series", "route", "trip", "convoy", "places", "tour", "halfway", "country", "sun",
                     "moon", "weather", "metar", "range", "ev", "fuel", "perf", "stop", "impact", "corner", "transfer", "spring",
                     "gearing", "tyre", "stint", "pace", "laps", "roll", "odds", "lanchester", "ttk", "scenario", "strike", "blast",
                     "arc", "lead", "board", "armour", "angle", "spot", "scan", "lattice", "triage", "record", "convert", "obd", "lights",
                     "service", "compare", "load", "tow", "fit", "weigh", "measure", "analyse", "pitch", "doppler", "playlist", "listen",
                     "cabin", "lsl", "space", "boot", "session", "ignition", "sheet", "log", "prompt", "check", "checklist", "selftest",
                     "setup", "rebuild", "tools", "stops", "precondition", "hotcar", "overtake", "mileage",
                     "summon", "intercept", "grapple", "escort", "ford"):
            self.assertRegex(out, r"(?m)^  %s\s" % name)
        self.assertIn("90 commands.", out)
        self.assertIn("OBJECTS: WEIGHT, SIZE AND ANALYSIS", out)
        self.assertIn("SOUND", out)


class CalendarTests(unittest.TestCase):
    def calendar(self, out):
        path = field(out, "CALENDAR")
        with open(path, "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.endswith(b"END:VCALENDAR\r\n"), path)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), "every line must end CRLF")
        self.assertTrue(all(len(line) <= 75 for line in raw.split(b"\r\n")), "a line is longer than 75 octets")
        text = raw.decode("utf-8")
        for stamp in re.findall(r"DT(?:START|END):(\S+)", text):
            self.assertRegex(stamp, r"^\d{8}T\d{4}00Z$")
        self.assertEqual(text.count("BEGIN:VEVENT"), text.count("UID:"))
        return path, text, text.replace("\r\n ", "")

    def test_route(self):
        with tempfile.TemporaryDirectory() as d:
            out = ok("route", "krakow", "ktw", "--arrive", "2026-11-12 04:40", "--ics", d)
            path, text, flat = self.calendar(out)
            self.assertEqual(os.path.basename(path), "firn-route-2026-11-12.ics")
            self.assertIn("DTSTART:20261112T022000Z", text)
            self.assertIn("DTEND:20261112T034000Z", text)
            self.assertIn("TRIGGER:-PT30M", text)
            self.assertIn("SUMMARY:Drive: Krak\u00f3w to Katowice", flat)
            self.assertIn("estimates: check a live map", flat)
            self.assertIn("it holds estimated times", out)
            named = os.path.join(d, "thursday.ics")
            out = ok("route", "krakow", "ktw", "--depart", "2026-11-12 03:20", "--ics", named, "--alarm", "0")
            self.assertEqual(field(out, "CALENDAR"), named)
            self.assertNotIn("VALARM", self.calendar(out)[1])
        code, _, err = run("route", "krakow", "ktw", "--ics", "auto")
        self.assertEqual(code, 2)
        self.assertIn("needs a time", err)
        self.assertEqual(run("route", "krakow", "ktw", "--depart", "07:00", "--ics", os.path.join(ROOT, "no-such-folder"))[0], 2)

    def test_trip_and_convoy(self):
        with tempfile.TemporaryDirectory() as d:
            out = ok("trip", "waw 2026-12-18 06:40 > cdg 09:05", "cdg 10:50 > jfk 13:10", "--home", "warsaw", "--onward", "new_york",
                     "--ics", d)
            _, text, flat = self.calendar(out)
            self.assertEqual(text.count("BEGIN:VEVENT"), 4)
            self.assertEqual(text.count("BEGIN:VALARM"), 1)
            self.assertIn("DTSTART:20261218T054000Z", text)
            self.assertIn("DTEND:20261218T181000Z", text)
            self.assertIn("SUMMARY:Flight: Warsaw Chopin Airport (WAW) to Charles de Gaulle", flat)
            self.assertIn("SUMMARY:Onward to New York", flat)
            self.assertLess(text.index("Leave for Warsaw"), text.index("SUMMARY:Flight"))
            out = ok("convoy", "anna:krakow", "bob:warsaw", "--to", "katowice", "--arrive", "2026-12-20 18:00", "--ics", d)
            _, text, flat = self.calendar(out)
            self.assertEqual(text.count("BEGIN:VEVENT"), 3)
            self.assertEqual(text.count("DTEND:"), 2)
            self.assertIn("SUMMARY:Meet: Katowice", flat)
            self.assertIn("DTSTART:20261220T170000Z", text)
            self.assertIn("SUMMARY:Bob: leave Warsaw for Katowice", flat)

    def test_format(self):
        stamp = datetime(2026, 11, 10, tzinfo=UTC)
        long_title = "A, long; title \\ with every character that needs escaping, and enough words to run well past the limit"
        ev = ical.event(long_title, datetime(2026, 11, 12, 3, 15, 47, tzinfo=UTC), datetime(2026, 11, 12, 4, 0, 1, tzinfo=UTC),
                        description="one\ntwo")
        text = ical.build([ev], now=stamp)
        flat = text.replace("\r\n ", "")
        self.assertIn("SUMMARY:A\\, long\\; title \\\\ with every character", flat)
        self.assertIn("DESCRIPTION:one\\ntwo", flat)
        self.assertIn("DTSTART:20261112T031500Z", text)
        self.assertIn("DTEND:20261112T040100Z", text)
        self.assertEqual(text, ical.build([ev], now=stamp))
        accents = ical.build([ical.event("\u017b\u00f3\u0142\u0107 " * 30, datetime(2026, 11, 12, 3, tzinfo=UTC))], now=stamp)
        for line in accents.encode("utf-8").split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
            line.decode("utf-8")
        self.assertIn("\u017b\u00f3\u0142\u0107 " * 29, accents.replace("\r\n ", ""))
        day = ical.build([ical.event("Inspection", date(2027, 3, 14), alarm=timedelta(days=14))], now=stamp)
        self.assertIn("DTSTART;VALUE=DATE:20270314", day)
        self.assertIn("DTEND;VALUE=DATE:20270315", day)
        self.assertIn("TRIGGER:-P14D", day)
        with self.assertRaises(core.FirnError):
            ical.event("no zone", datetime(2026, 11, 12, 3))


class ServiceTests(unittest.TestCase):
    def test_vehicle_on_file(self):
        out = ok("service")
        self.assertIn("about 84,496 km today at 12,000 km a year", out)
        self.assertIn("OVERDUE    winter tyres on: was due 2026-11-01, 9 days ago", out)
        self.assertIn("DUE SOON   insurance: due 2026-11-28, in 18 days", out)
        self.assertIn("LATER      inspection: due 2027-03-14, in 124 days [12 months after 2026-03-14]", out)
        self.assertIn("or at 93,000 km, 8,504 km to go, about 2027-07-27 at this mileage; the date comes first", out)
        self.assertLess(out.index("OVERDUE"), out.index("DUE SOON"))
        self.assertLess(out.index("DUE SOON"), out.index("LATER"))
        self.assertIn("DUE SOON   inspection", ok("service", "--soon", "130"))
        self.assertIn("the test hatchback", ok("service", "--vehicle", "hatch"))
        self.assertEqual(run("service", "--vehicle", "lorry")[0], 2)

    def test_boot_says_what_is_due(self):
        out = field(ok("boot", "--seed", "1"), "SERVICE")
        self.assertIn("OVERDUE - the test hatchback, winter tyres on: was due 2026-11-01", out)
        self.assertIn("insurance: due 2026-11-28, in 18 days", out)
        self.assertNotIn("inspection", out)

    def test_intervals_and_month_ends(self):
        self.assertEqual(service.parse_interval("12 months"), (12, 0))
        self.assertEqual(service.parse_interval("12"), (12, 0))
        self.assertEqual(service.parse_interval("2y"), (24, 0))
        self.assertEqual(service.parse_interval("1.5 years"), (18, 0))
        self.assertEqual(service.parse_interval("6 weeks"), (0, 42))
        self.assertEqual(service.parse_interval("90d"), (0, 90))
        for bad in ("soon", "0 months", "1.3y", "12 parsecs"):
            with self.assertRaises(core.FirnError):
                service.parse_interval(bad)
        self.assertEqual(service.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(service.add_months(date(2024, 2, 29), 12), date(2025, 2, 28))
        self.assertEqual(service.add_months(date(2026, 11, 30), 3), date(2027, 2, 28))
        self.assertEqual(service.add_months(date(2026, 12, 15), 1), date(2027, 1, 15))

    def test_items_given_on_the_spot(self):
        belt = "timing belt: last_km=20000, every_km=100000"
        self.assertIn("LATER      timing belt: due at 120,000 km, 1,500 km to go", ok("service", "--item", belt, "--odo", "118500"))
        self.assertIn("DUE SOON   timing belt: due at 120,000 km, 600 km to go", ok("service", "--item", belt, "--odo", "119400"))
        self.assertIn("OVERDUE    timing belt: 1,000 km past its 120,000 km mark", ok("service", "--item", belt, "--odo", "121000"))
        out = ok("service", "--item", belt)
        self.assertIn("no odometer reading on file", out)
        self.assertIn('{"what": "timing belt", "last_km": 20000, "every_km": 100000}', out)
        out = ok("service", "--item", "inspection: last=2026-03-14, every=12 months", "--item", "insurance: due=2027-01-10", "--name", "the van")
        self.assertIn("VEHICLE    the van", out)
        self.assertIn("insurance: due 2027-01-10, in 61 days", out)
        self.assertIn("due today", ok("service", "--item", "wash: due=2026-11-10"))
        self.assertIn("UNKNOWN", ok("service", "--item", "mystery: every=12 months"))
        self.assertEqual(run("service", "--item", "nonsense")[0], 2)
        self.assertEqual(run("service", "--item", "x: when=tomorrow")[0], 2)
        self.assertEqual(run("service", "--item", "x: due=sometime")[0], 2)
        self.assertIn('"what": "inspection"', ok("service", "--template"))

    def test_calendar_of_due_dates(self):
        with tempfile.TemporaryDirectory() as d:
            out = ok("service", "--ics", d)
            with open(field(out, "CALENDAR"), encoding="utf-8", newline="") as f:
                text = f.read()
            self.assertEqual(text.count("BEGIN:VEVENT"), 3)
            self.assertIn("DTSTART;VALUE=DATE:20261128", text)
            self.assertIn("DTEND;VALUE=DATE:20261129", text)
            self.assertIn("TRIGGER:-P14D", text)
            self.assertNotIn("days", text.replace("\r\n ", "").replace("-P14D", ""))
            self.assertNotIn("winter tyres", text)
            with open(field(ok("service", "--ics", d, "--warn-days", "0"), "CALENDAR"), encoding="utf-8") as f:
                self.assertNotIn("VALARM", f.read())
        self.assertEqual(run("service", "--item", "old: due=2026-01-01", "--ics", "auto")[0], 2)


class HaulTests(unittest.TestCase):
    def test_load(self):
        out = ok("load", "--max", "2100", "--kerb", "1500", "--people", "80", "75", "2x35", "--cargo", "120", "--roof", "45", "--roof-limit", "75")
        self.assertIn("PAYLOAD    600 kg (2,100 kg maximum - 1,500 kg kerb)", out)
        self.assertIn("4 people 225 kg + cargo 120 kg + roof 45 kg = 390 kg", out)
        self.assertIn("MARGIN     210 kg spare; 65% of the payload used", out)
        self.assertIn("MASS       1,890 kg on the road, 90% of the 2,100 kg maximum", out)
        self.assertIn("45 kg of 75 kg allowed (60%): within the limit", out)
        out = ok("load", "--payload", "520", "--people", "2x80", "--cargo", "350", "--nose", "70", "--nose-limit", "60")
        self.assertIn("OVER       by 60 kg", out)
        self.assertIn("70 kg of 60 kg allowed: OVER the limit by 10 kg", out)
        self.assertNotIn("MARGIN", out)
        out = ok("load", "--max", "1950", "--kerb", "1420", "--driver-included", "--people", "90", "70", "--cargo", "200")
        self.assertIn("less the 75 kg driver already in the kerb figure", out)
        self.assertIn("MARGIN     245 kg spare; 54% of the payload used", out)
        self.assertIn("nothing listed", ok("load", "--payload", "500"))
        self.assertEqual(run("load", "--people", "80")[0], 2)
        self.assertEqual(run("load", "--payload", "500", "--people", "heavy")[0], 2)
        self.assertEqual(run("load", "--max", "1500", "--kerb", "1600")[0], 2)

    def test_tow(self):
        out = ok("tow", "--trailer", "1300", "--trailer-max", "1500", "--limit", "1500", "--kerb", "1650", "--car", "1900",
                 "--car-max", "2150", "--train-max", "3500", "--nose", "80")
        self.assertIn("87% of its own 1,500 kg plate", out)
        self.assertIn("1,300 kg of the car's 1,500 kg braked towing limit (87%): within", out)
        self.assertIn("trailer is 79% of the car's 1,650 kg kerb mass: inside the 85%", out)
        self.assertIn("80 kg on the ball, 6.2% of the trailer: inside the 5 to 7% guideline", out)
        self.assertIn("= 3,200 kg of the 3,500 kg permitted train mass (91%): within", out)
        self.assertIn("CAR        1,980 kg with the noseweight on the ball, 92% of its 2,150 kg maximum: within", out)
        self.assertIn("VERDICT    within every limit given", out)
        out = ok("tow", "--trailer", "1700", "--limit", "1500", "--kerb", "1650", "--nose", "60", "--nose-limit", "75")
        self.assertIn("(113%): OVER by 200 kg", out)
        self.assertIn("heavier than the car", out)
        self.assertIn("lighter than the 5 to 7% guideline", out)
        self.assertIn("VERDICT    NOT WITHIN LIMITS: the trailer is 200 kg over the car's braked towing limit", out)
        out = ok("tow", "--trailer", "1500", "--limit", "1600", "--kerb", "1650")
        self.assertIn("91% of the car's 1,650 kg kerb mass: above the 85% advised for beginners", out)
        self.assertIn("aim for 75 to 105 kg on the ball (5 to 7% of the trailer)", out)
        self.assertIn("within every limit given; advice not met: trailer above 85% of the car's kerb mass", out)
        out = ok("tow", "--trailer", "600", "--unbraked", "--unbraked-limit", "750", "--kerb", "1400")
        self.assertIn("600 kg as loaded, no brakes", out)
        self.assertIn("750 kg unbraked towing limit (80%): within", out)
        self.assertIn("no braked towing limit given", ok("tow", "--trailer", "900"))
        self.assertIn("OVER the 75 kg limit by 15 kg", ok("tow", "--trailer", "1500", "--limit", "1600", "--nose", "90", "--nose-limit", "75"))
        self.assertEqual(run("tow", "--trailer", "0")[0], 2)
        self.assertEqual(run("tow", "--trailer", "900", "--limit", "-5")[0], 2)

    def test_rectangle_in_rectangle_agrees_with_brute_force(self):
        rng = random.Random(7)
        angles = [math.pi / 2 * i / 2000 for i in range(2001)]
        found = 0
        for _ in range(500):
            p, q, big_p, big_q = [rng.uniform(1, 30) for _ in range(4)]
            got = haul.rect_in_rect(p, q, big_p, big_q)
            brute = any(p * math.cos(t) + q * math.sin(t) <= big_p and p * math.sin(t) + q * math.cos(t) <= big_q for t in angles)
            if brute:
                self.assertIsNotNone(got, (p, q, big_p, big_q))
            if got is not None:
                found += 1
                t = math.radians(got)
                self.assertLessEqual(p * math.cos(t) + q * math.sin(t), big_p + 1e-6)
                self.assertLessEqual(p * math.sin(t) + q * math.cos(t), big_q + 1e-6)
        self.assertTrue(100 < found < 450, found)
        self.assertEqual(haul.rect_in_rect(3, 2, 3, 2), 0.0)
        self.assertEqual(haul.rect_in_rect(2, 3, 3, 2), 90.0)
        self.assertIsNotNone(haul.rect_in_rect(10, 1, 8, 8))
        self.assertIsNone(haul.rect_in_rect(10, 4, 8, 8))

    def test_fit(self):
        out = ok("fit", "--space", "1800x1000x700", "--item", "europallet", "--item", "600x400x300:4")
        self.assertIn("1.26 m3; longest straight line 2,059 mm across the floor, 2,175 mm corner to corner", out)
        self.assertIn("ITEM 1     1,200 x 800 x 144 mm (europallet): fits, 1 way round", out)
        self.assertIn("ITEM 2     600 x 400 x 300 mm x 4: fits, 6 ways round", out)
        self.assertIn("5 items, 0.43 m3, 34% of the space; a simple packer found room for all of them", out)
        out = ok("fit", "--space", "1800x1000x700", "--item", "1900x150x100", "--long", "2100")
        self.assertIn("fits only on the floor, turned about 22 deg", out)
        self.assertIn("LONG       2,100 mm: goes in only corner to corner", out)
        self.assertIn("lies across the floor on the diagonal", ok("fit", "--space", "1800x1000x700", "--long", "2000"))
        self.assertIn("lies straight along the floor", ok("fit", "--space", "1800x1000x700", "--long", "1700"))
        self.assertIn("DOES NOT FIT: longer than the 2,175 mm", ok("fit", "--space", "1800x1000x700", "--long", "2300"))
        self.assertIn("DOES NOT FIT: not square on", ok("fit", "--space", "1800x1000x700", "--item", "900x900x800"))
        self.assertIn("fits, ", ok("fit", "--space", "1000x1000x700", "--item", "600x400x900"))
        self.assertIn("DOES NOT FIT upright", ok("fit", "--space", "1000x1000x700", "--item", "600x400x900", "--upright"))
        self.assertIn("DOES NOT PASS the 500 x 500 mm opening", ok("fit", "--space", "1800x1000x700", "--item", "900x600x600", "--opening", "500x500"))
        out = ok("fit", "--space", "180x100x70", "--unit", "cm", "--item", "90x60x60", "--upright", "--opening", "95x65")
        self.assertIn("sizes were given in cm", out)
        self.assertIn("900 x 600 x 600 mm: fits, 2 ways round kept upright; passes the opening", out)
        self.assertIn("did NOT find room", ok("fit", "--space", "1000x1000x1000", "--item", "600x600x600:2"))
        self.assertIn("more than the space holds", ok("fit", "--space", "1800x1000x700", "--item", "900x900x600:3"))
        self.assertIn("does not go in at all", ok("fit", "--space", "1800x1000x700", "--item", "900x900x800", "--item", "100x100x100"))
        self.assertTrue(haul.pack([(500.0, 500.0, 500.0)] * 8, (1000.0, 1000.0, 1000.0)))
        self.assertFalse(haul.pack([(500.0, 500.0, 500.0)] * 9, (1000.0, 1000.0, 1000.0)))
        self.assertEqual(run("fit", "--space", "100x100", "--item", "1x1x1")[0], 2)
        self.assertEqual(run("fit", "--space", "100x100x100", "--item", "10x10x10:0")[0], 2)
        self.assertEqual(run("fit", "--space", "100x100x100")[0], 2)
        self.assertEqual(run("fit", "--space", "100x100x100", "--item", "10x10x10", "--opening", "wide")[0], 2)


class CompareTests(unittest.TestCase):
    def test_rows_leads_and_derived_figures(self):
        out = ok("compare", "Kestrel: kw=150, kg=1720, 0-100=7.9, battery=64, kwh100=17.1, price=189000",
                 "Heron: kw=110, kg=1340, 0-100=9.4, tank=45, l100=5.8, price=121000",
                 "--kwh-price", "1.1", "--fuel-price", "6.5", "--km-year", "12000")
        self.assertRegex(out, r"power\s+150 kW \(201 hp\)\s+110 kW \(148 hp\)\s+Kestrel by 36%")
        self.assertRegex(out, r"kerb mass\s+1,720 kg\s+1,340 kg\s+-\n")
        self.assertRegex(out, r"power to mass\s+87 W/kg\s+82 W/kg\s+Kestrel by 6%\s+\[derived\]")
        self.assertRegex(out, r"0-100 km/h\s+7\.9 s\s+9\.4 s\s+Kestrel by 1\.5 s")
        self.assertRegex(out, r"range\s+~374 km\s+~776 km\s+Heron by 107%")
        self.assertRegex(out, r"price\s+189,000\s+121,000\s+Heron by 36%")
        self.assertRegex(out, r"energy per 100 km\s+18\.81\s+37\.7\s+Kestrel by 50%")
        self.assertRegex(out, r"energy per year\s+2,257\s+4,524\s+Kestrel by 50%")
        self.assertLess(out.index("  range"), out.index("  price"))
        self.assertEqual(out.count("no source given"), 2)
        self.assertIn("electricity 1.1 per kWh; fuel 6.5 per litre", out)

    def test_firn_units_and_more_than_two(self):
        out = ok("compare", "firn", "Heron: hp=148, kg=1340, 0-100=9.4, top=205, seats=5, source=maker brochure 2026")
        self.assertIn("858 kW (1,150 hp)", out)
        self.assertIn("110 kW (148 hp)", out)
        self.assertRegex(out, r"seats\s+4\s+5\s+Heron by 1\n")
        self.assertIn("fiction, not a production vehicle", out)
        self.assertIn("SOURCE     Heron: maker brochure 2026", out)
        out = ok("compare", "A: kw=100, kg=1000", "B: kw=100, kg=1250", "C: ps=150, kg=1000, drive=awd, co2=120", "--km-year", "10000")
        self.assertRegex(out, r"power\s+100 kW \(134 hp\)\s+100 kW \(134 hp\)\s+110 kW \(148 hp\)\s+C by 10%")
        self.assertRegex(out, r"power to mass\s+100 W/kg\s+80 W/kg\s+110 W/kg\s+C by 10%")
        self.assertRegex(out, r"drive\s+-\s+-\s+awd")
        self.assertRegex(out, r"CO2 per year\s+-\s+-\s+1\.2 t")
        self.assertRegex(ok("compare", "A: kw=100, kg=1000", "B: kw=100, kg=900"), r"power\s+100 kW \(134 hp\)\s+100 kW \(134 hp\)\s+level")

    def test_bad_input(self):
        self.assertEqual(run("compare", "A: kw=100")[0], 2)
        self.assertEqual(run("compare", "A: kw=fast", "B: kw=1")[0], 2)
        self.assertEqual(run("compare", "A: kw=1", "a: kw=2")[0], 2)
        self.assertEqual(run("compare", "A: kw=100, hp=134", "B: kw=1")[0], 2)
        self.assertEqual(run("compare", "A: kw=1", "B: kw=2", "--kwh-price", "0")[0], 2)
        self.assertEqual(run("compare", "A", "B: kw=2")[0], 2)


class SetupRebuildTests(unittest.TestCase):
    def tearDown(self):
        use_personal(FIXTURE)

    def fixture(self):
        with open(FIXTURE, encoding="utf-8") as f:
            return json.load(f)

    def test_setup_passes_a_good_file(self):
        out = ok("setup")
        self.assertIn("DRIVER     Ada", out)
        self.assertIn("HOME       Home base (50.0619, 19.9581; Europe/Warsaw)", out)
        self.assertIn("4 clocks, 1 place, 1 checked leg, 4 ignition questions (every new conversation), 1 vehicle, 2 log lines", out)
        self.assertIn("RESULT     nothing to fix", out)
        for answer in ("bottle green", "vistula", "Sprocket", "millimetre"):
            self.assertNotIn(answer, out)
        use_personal(None)
        self.assertIn("nothing to fix; home and work still to set", ok("setup"))

    def test_validate_finds_everything_in_one_pass(self):
        bad = self.fixture()
        bad["hmoe"] = {}
        bad["home"]["tz"] = "Europe/Warsw"
        bad["work"]["lon"] = 500
        bad["zones"] = ["utc", "Mars/Olympus"]
        bad["places"]["cabin"]["lat"] = 190
        bad["legs"]["home>nowhere"] = {"km": 5}
        bad["legs"]["home>work"] = {"km": 20, "min": 3}
        bad["ignition"]["setting"] = "sometimes"
        bad["ignition"]["questions"].append({"q": "Half a question?"})
        bad["vehicles"][0]["items"].append({"what": "belt", "last": "not a date", "every": "12 months"})
        bad["first_boot"] = "soon"
        bad["logbook"].append("went for a drive")
        bad["family"] = "none"
        found = rebuild.validate(bad, date(2026, 11, 10))
        levels = {}
        for lvl, w, text in found:
            levels.setdefault(w, set()).add(lvl)
        for key in ("home.tz", "work", "zones", "places.cabin", "legs.home>nowhere", "ignition.setting", "ignition.questions.5",
                    "vehicles.the test hatchback", "first_boot", "family"):
            self.assertEqual(levels.get(key), {"FIX"}, key)
        for key in ("hmoe", "legs.home>work", "logbook.3"):
            self.assertEqual(levels.get(key), {"CHECK"}, key)
        texts = " | ".join("%s: %s" % (w, text) for _, w, text in found)
        self.assertIn("hmoe: not a field FIRN reads: did you mean 'home'?", texts)
        self.assertIn("legs.home>work: 20 km is shorter than the straight line", texts)
        self.assertIn("legs.home>work: 20 km in 3 min is 400 km/h", texts)
        for answer in ("bottle green", "vistula", "Sprocket"):
            self.assertNotIn(answer, texts)
        self.assertEqual(rebuild.validate(self.fixture(), date(2026, 11, 10)), [])
        self.assertEqual(geo.find_place("home")["name"], "Home base", "the real file must be back in force after a check")

    def test_boot_and_setup_report_a_broken_file(self):
        bad = self.fixture()
        bad["zone_aliases"]["gran"] = "America/Chicgo"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "personal.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(bad, f)
            use_personal(path)
            self.assertIn("1 thing to fix in the personal file (the first: zone_aliases.gran)", ok("boot", "--seed", "1"))
            code, out, _ = run("setup")
            self.assertEqual(code, 1)
            self.assertIn("FIX        zone_aliases.gran: unknown zone 'America/Chicgo'", out)
            self.assertIn("RESULT     1 to fix, 0 to check", out)

    def test_dump_reads_back_the_same(self):
        for data in (self.fixture(), core.load_data("personal")):
            self.assertEqual(json.loads(rebuild.dump_personal(data)), data)
        text = rebuild.dump_personal(self.fixture())
        self.assertIn('\n    "home>work": {"km": 80', text)
        self.assertIn('\n      {"q": "What colour was the first test car?"', text)

    def test_rebuild_shows_what_would_change(self):
        out = ok("rebuild", "--home", "krakow", "--work", "katowice", "--driver", "Anna",
                 "--place", "The cabin: at=49.2992,19.9496, tz=Europe/Warsaw", "--leg", "home>work: km=82, min=61, via=A4",
                 "--log", "LOG 2026-11-10 | journey | first run to the coast | leave before six",
                 "--vehicle", "the estate: odo=84200, km_year=12000", "--item", "the estate / inspection: last=2026-03-14, every=12 months",
                 "--keep", "tow hook", "--alias", "nan=Europe/London", "--show")
        for line in ("CHANGE     driver: Anna", "CHANGE     place: the_cabin = The cabin (49.2992, 19.9496; Europe/Warsaw)",
                     "CHANGE     checked leg: home>work = 82 km, 61 min", "CHANGE     vehicle: the estate (new)",
                     "CHANGE     service item: the estate / inspection", "CHANGE     kit kept: a tow hook",
                     "CHANGE     alias: nan = Europe/London", "SHOWN      nothing was written"):
            self.assertIn(line, out)
        self.assertEqual(core.personal()["driver"], "Ada")
        self.assertIn("nothing to change was given", ok("rebuild"))

    def test_rebuild_writes_a_package(self):
        with tempfile.TemporaryDirectory() as d:
            out = ok("rebuild", "--home", "50.2,19.1", "--driver", "Zed", "--out", d)
            self.assertIn("zone Europe/Warsaw taken from", out)
            path = field(out, "PACKAGE").split(" (")[0]
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                new = json.loads(z.read("scripts/data/personal.json").decode("utf-8"))
                skill = z.read("SKILL.md").decode("utf-8")
            self.assertEqual(sorted(names), rebuild.skill_files(os.path.join(ROOT, "src")))
            self.assertIn("scripts/firnlib/rebuild.py", names)
            self.assertTrue(skill.startswith("---\nname: firn"))
            old = self.fixture()
            self.assertEqual((new["driver"], new["home"]["lat"], new["home"]["tz"], new["home"]["name"]), ("Zed", 50.2, "Europe/Warsaw", "Home base"))
            self.assertEqual(new["ignition"], old["ignition"], "ignition questions must pass through untouched")
            for key in ("work", "places", "vehicles", "logbook", "pending", "family", "zones"):
                self.assertEqual(new[key], old[key], key)
            for answer in ("bottle green", "vistula", "Sprocket"):
                self.assertNotIn(answer, out)
            out = ok("rebuild", "--driver", "Zed", "--json", "--out", d)
            with open(field(out, "PERSONAL"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["driver"], "Zed")

    def test_rebuild_in_place_and_kit(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "personal.json")
            shutil.copyfile(FIXTURE, path)
            use_personal(path)
            self.assertIn("WRITTEN", ok("rebuild", "--keep", "tow hook", "--pending", "roof rack: said in a sim", "--in-place"))
            use_personal(path)
            out = ok("record", "--fit")
            self.assertIn("FITTED     a tow hook [firn] - kept 2026-11-10; kept by Ada", out)
            self.assertIn("PENDING    roof rack", out)
            self.assertNotIn("PENDING    a tow hook", out)
            ok("rebuild", "--purge", "roof rack", "--drop", "places.cabin", "--drop", "logbook.1", "--drop", "legs.home>work", "--in-place")
            use_personal(path)
            p = core.personal()
            self.assertEqual((p["pending"], p["places"], p["legs"], len(p["logbook"])), ([], {}, {}, 1))
            self.assertEqual(run("route", "home", "cabin")[0], 2)

    def test_rebuild_refuses_what_it_cannot_do(self):
        self.assertEqual(run("rebuild", "--home", "nowhere_town", "--show")[0], 2)
        self.assertEqual(run("rebuild", "--leg", "home>nowhere: km=5", "--show")[0], 2)
        self.assertEqual(run("rebuild", "--ignition", "sometimes", "--show")[0], 2)
        self.assertEqual(run("rebuild", "--home", "50,19", "--home-tz", "Mars/Olympus", "--show")[0], 2)
        self.assertEqual(run("rebuild", "--keep", "a thing never said", "--show")[0], 2)
        self.assertEqual(run("rebuild", "--log", "went for a drive", "--show")[0], 2)
        self.assertEqual(run("rebuild", "--drop", "everything", "--show")[0], 2)
        code, _, err = run("rebuild", "--home", "-48.9,-123.4", "--show")
        self.assertEqual(code, 2)
        self.assertIn("give its time zone too", err)
        self.assertEqual(run("rebuild", "--driver", "Zed", "--out", os.path.join(ROOT, "no-such-folder"))[0], 2)


class AgendaTests(unittest.TestCase):
    def test_series_flags_the_weeks_out_of_step(self):
        out = ok("series", "sat", "12:00", "--from", "slt", "--start", "2027-03-01", "--count", "5", "--to", "home", "chicago")
        self.assertIn("5 occurrences from 2027-03-06", out)
        self.assertRegex(out, r"2027-03-13 12:00 Sat\s+SLT\s+21:00 Sat\s+HOME\s+14:00 Sat\s+CHICAGO\n")
        self.assertRegex(out, r"2027-03-20 12:00 Sat\s+SLT\s+20:00 Sat\s+HOME\s+14:00 Sat\s+CHICAGO\s+<- HOME is \+8 h, not the usual \+9 h")
        self.assertIn("SHIFT      in HOME time it is usually 21:00, but 20:00 on 2 of these", out)
        self.assertIn("GAP WEEKS  2027-03-20, 2027-03-27", out)
        self.assertIn("STEADY", ok("series", "09:00", "--from", "tokyo", "--every", "day", "--count", "5", "--to", "utc"))

    def test_series_steps_and_month_ends(self):
        out = ok("series", "2026-01-31 10:00", "--every", "month", "--count", "3", "--from", "utc", "--to", "utc")
        for day in ("2026-01-31 10:00 Sat", "2026-02-28 10:00 Sat", "2026-03-31 10:00 Tue"):
            self.assertIn(day, out)
        self.assertEqual(agenda.parse_every("week"), ("day", 7))
        self.assertEqual(agenda.parse_every("2w"), ("day", 14))
        self.assertEqual(agenda.parse_every("fortnight"), ("day", 14))
        self.assertEqual(agenda.parse_every("3d"), ("day", 3))
        self.assertEqual(agenda.parse_every("month"), ("month", 1))
        self.assertEqual(run("series", "sat", "12:00", "--every", "sometimes")[0], 2)
        self.assertEqual(run("series", "someday", "12:00")[0], 2)
        self.assertEqual(run("series", "sat", "12:00", "--count", "0")[0], 2)

    def test_series_calendar(self):
        with tempfile.TemporaryDirectory() as d:
            out = ok("series", "2026-11-12 19:30", "--from", "chicago", "--every", "2w", "--count", "4", "--title", "Call", "--dur", "45m",
                     "--ics", d)
            with open(field(out, "CALENDAR"), encoding="utf-8", newline="") as f:
                text = f.read()
            self.assertEqual(text.count("BEGIN:VEVENT"), 4)
            self.assertIn("DTSTART:20261113T013000Z", text)
            self.assertIn("DTEND:20261113T021500Z", text)
            self.assertIn("SUMMARY:Call", text)

    def test_session_clock(self):
        self.assertIn("SESSION    began 2026-11-10T13:30Z; later, 'session --since 2026-11-10T13:30Z'", ok("boot", "--seed", "1"))
        out = ok("session", "--since", "2026-11-10T09:15Z")
        self.assertIn("SESSION    running 4h15m, since 2026-11-10 10:15 Tue UTC+01:00", out)
        self.assertIn("LONG       yes: past 3h00m", out)
        self.assertIn("LATE       no (14:30 at home)", out)
        self.assertIn("SAY        one fatigue note", out)
        out = ok("session", "--since", "2026-11-10T13:00Z", "--long", "2h")
        self.assertIn("running 0h30m", out)
        self.assertIn("LONG       no (the mark is 2h00m)", out)
        self.assertNotIn("SAY", out)
        self.assertIn("no start given", ok("session"))
        self.assertEqual(run("session", "--since", "2026-11-11T09:00Z")[0], 2)
        self.assertEqual(run("session", "--since", "this morning")[0], 2)


class WindowAndTourTests(unittest.TestCase):
    def test_best_departure_in_a_window(self):
        out = ok("route", "krakow", "gdansk", "--window", "05:00-11:00", "--date", "2026-12-05", "--before-dark")
        self.assertIn("WINDOW     2026-12-05, departures 05:00 to 11:00 every 15 min: 25 tried", out)
        self.assertIn("LATEST     depart 06:00 to arrive 15:11, before sunset at 15:23", out)
        self.assertIn("BEST       depart 06:00, arrive 15:11 | night 0h45m", out)
        self.assertIn("WORST      depart 11:00", out)
        self.assertIn("DEPART     2026-12-05 06:00 Sat UTC+01:00", out)
        out = ok("route", "krakow", "katowice", "--window", "09:00-12:00", "--date", "2026-06-20")
        self.assertIn("13 tried", out)
        self.assertIn("every departure in the window is the same for light: the earliest is taken", out)
        self.assertIn("DEPART     2026-06-20 09:00", out)
        self.assertIn("this is tomorrow", ok("route", "krakow", "katowice", "--window", "06:00-08:00"))
        self.assertIn("DARK", ok("route", "krakow", "gdansk", "--window", "12:00-13:00", "--date", "2026-12-05", "--before-dark"))
        self.assertEqual(run("route", "krakow", "gdansk", "--window", "05:00-11:00", "--depart", "06:00")[0], 2)
        self.assertEqual(run("route", "krakow", "gdansk", "--before-dark")[0], 2)
        self.assertEqual(run("route", "krakow", "gdansk", "--window", "11:00-05:00")[0], 2)
        self.assertEqual(run("route", "krakow", "gdansk", "--window", "morning")[0], 2)

    def test_best_order_agrees_with_trying_them_all(self):
        rng = random.Random(11)
        for n in (3, 4, 5, 6, 7):
            for _ in range(6):
                cost = [[None if i == j else (rng.uniform(1, 9), 1.0, "estimate") for j in range(n)] for i in range(n)]

                def price(seq):
                    return sum(cost[x][y][0] for x, y in zip(seq, seq[1:]))

                for loop, end in ((True, None), (False, None), (False, n - 1)):
                    got = tours.best_order(cost, n, loop, end)
                    best = None
                    for perm in itertools.permutations(range(1, n)):
                        if end is not None and perm[-1] != end:
                            continue
                        seq = [0] + list(perm) + ([0] if loop else [])
                        if best is None or price(seq) < best:
                            best = price(seq)
                    self.assertAlmostEqual(price(got), best, places=9)
                    self.assertEqual(sorted(got[1:-1] if loop else got[1:]), list(range(1, n)))

    def test_tour(self):
        out = ok("tour", "krakow", "wroclaw", "katowice", "opole", "lodz", "--loop")
        order = field(out, "ORDER").split(" -> ")
        self.assertEqual((order[0], order[-1], len(order)), ("Krak\u00f3w", "Krak\u00f3w", 6))
        self.assertIn("SAVED      3h40m and 293.4 km against the order as given (28% of the driving)", out)
        self.assertIn("&waypoints=", field(out, "LIVE MAP"))
        out = ok("tour", "krakow", "wroclaw", "katowice", "opole", "--end", "wroclaw")
        self.assertEqual(field(out, "ORDER"), "Krak\u00f3w -> Katowice -> Opole -> Wroc\u0142aw")
        self.assertIn("ending at Wroc\u0142aw", out)
        out = ok("tour", "krakow", "katowice", "opole", "wroclaw", "--depart", "2026-11-14 09:00", "--stop-min", "20")
        self.assertIn("SAVED      nothing: the order as given was already the best", out)
        self.assertIn("| there 10:05", out)
        self.assertIn("2 x 20 min at the stops = 4h25m", out)
        self.assertIn("DONE       2026-11-14 13:24 Sat UTC+01:00", out)
        out = ok("tour", "krakow", "opole", "katowice", "--keep-order")
        self.assertIn("order kept as given", out)
        self.assertEqual(field(out, "ORDER"), "Krak\u00f3w -> Opole -> Katowice")
        self.assertIn("[checked 2026-11-08", ok("tour", "home", "work", "cabin", "--loop"))
        self.assertEqual(run("tour", "krakow", "katowice")[0], 2)
        self.assertEqual(run("tour", "krakow", "katowice", "opole", "--loop", "--end", "opole")[0], 2)
        self.assertEqual(run("tour", *(["krakow"] + ["katowice"] * 13))[0], 2)

    def test_halfway(self):
        out = ok("halfway", "anna:krakow", "bob:warsaw", "carol:wroclaw", "--top", "3")
        self.assertIn("3 travellers", out)
        self.assertIn("between them (towns of 50,000 people or more; --min-pop changes that)", out)
        worst = [hm(ln.split("longest ")[1]) for ln in out.splitlines() if re.match(r"^[123]\s", ln)]
        self.assertEqual(len(worst), 3)
        self.assertEqual(worst, sorted(worst))
        self.assertLessEqual(worst[0], 3 * 60 + 2)          # no worse than the best a gazetteer of big cities could offer
        self.assertIn("convoy anna:krakow bob:warsaw carol:wroclaw --to PLACE", out)
        big = ok("halfway", "anna:krakow", "bob:warsaw", "carol:wroclaw", "--min-pop", "500000")
        self.assertIn("1          \u0141\u00f3d\u017a | longest 3h02m (anna)", big)
        self.assertIn("LEAST      Krak\u00f3w has the least travel in all", big)

        def weighed(text):
            return int(re.search(r"(\d+) places? weighed", text).group(1))
        every = ok("halfway", "anna:krakow", "bob:warsaw", "carol:wroclaw", "--min-pop", "0")
        self.assertIn("between them (every town)", every)
        self.assertTrue(weighed(big) < weighed(out) < weighed(every), (weighed(big), weighed(out), weighed(every)))
        self.assertEqual(run("halfway", "anna:krakow", "bob:warsaw", "--min-pop", "-1")[0], 2)
        out = ok("halfway", "anna:krakow", "bob:gdansk@rail", "--candidates", "lodz", "warsaw", "bydgoszcz")
        self.assertIn("3 places weighed |", out)
        self.assertEqual(run("halfway", "anna:krakow")[0], 2)
        self.assertEqual(run("halfway", "anna", "bob:warsaw")[0], 2)


class FatigueTests(unittest.TestCase):
    def test_low_hours_follow_the_wall_clock(self):
        tz = chrono.get_tz("Europe/Warsaw")
        win = fatigue.parse_window("00:00-06:00")
        self.assertEqual(win, (0, 360))
        # twelve hours from 21:00 take in the whole of the night's low hours: six of them on an ordinary night,
        # seven on the night the clocks go back, five on the night they go forward
        for day, want in (((2026, 11, 11), 360.0), ((2026, 10, 24), 420.0), ((2026, 3, 28), 300.0)):
            dep, _ = chrono.localize(datetime(day[0], day[1], day[2], 21, 0), tz)
            self.assertEqual(fatigue.low_minutes(dep, 12, win), want, day)
        day_run, _ = chrono.localize(datetime(2026, 11, 11, 7, 0), tz)
        self.assertEqual(fatigue.low_minutes(day_run, 12, win), 0.0)
        # a window through midnight, and a journey long enough to meet two nights
        late = fatigue.parse_window("22:30-05:00")
        self.assertEqual(fatigue.label(late), "22:30-05:00")
        self.assertEqual(fatigue.length_h(late), 6.5)
        dep, _ = chrono.localize(datetime(2026, 11, 11, 21, 0), tz)
        self.assertEqual(fatigue.low_minutes(dep, 4, late), 150.0)
        self.assertEqual(fatigue.low_minutes(dep, 36, win), 720.0)
        found = fatigue.spans(dep, dep + timedelta(hours=36), tz, win)
        self.assertEqual(len(found), 2)
        # the clock that counts is the one the journey starts by, whatever zone the moments are handed over in
        self.assertEqual(fatigue.low_minutes(dep.astimezone(UTC).astimezone(tz), 12, win), 360.0)

    def test_route_through_the_night(self):
        out = ok("route", "krakow", "gdansk", "--depart", "2026-12-05 21:00", "--fatigue")
        self.assertIn("FATIGUE    6h00m of this 9h11m journey falls in the low hours: 00:00-06:00 on the clock at the start "
                      "(Europe/Warsaw), when alertness is lowest [derived; Highway Code rule 91]", out)
        self.assertIn("LOW HOURS  00:00-06:00 Sun, about km 199 to 596 of 608", out)
        self.assertIn("leave by 14:49 Sat and be there before 00:00, or set off at 06:00 Sun or later", out)
        self.assertIn("if sleepy, stop somewhere safe", out)
        self.assertNotIn("AT WHEEL", out)
        self.assertNotIn("BREAKS     thinner", out)
        self.assertEqual(desk.check_text(out), [])
        # the advice holds: the departure it names arrives exactly as the low hours begin, and is clear of them
        early = ok("route", "krakow", "gdansk", "--depart", "2026-12-05 14:49", "--fatigue")
        self.assertIn("ARRIVE     2026-12-06 00:00 Sun", early)
        self.assertIn("FATIGUE    clear of the low hours, 00:00-06:00 on the clock at the start [derived; Highway Code rule 91]", early)
        self.assertNotIn("LOW HOURS", early)
        self.assertIn("FATIGUE    clear", ok("route", "krakow", "gdansk", "--depart", "2026-12-06 06:00", "--fatigue"))
        # without the flag nothing changes
        self.assertNotIn("FATIGUE", ok("route", "krakow", "gdansk", "--depart", "2026-12-05 21:00"))

    def test_route_fixed_arrival_and_own_hours(self):
        out = ok("route", "krakow", "ktw", "--arrive", "2026-11-12 04:40", "--fatigue")
        self.assertIn("FATIGUE    all 1h20m of this journey falls in the low hours", out)
        self.assertIn("LOW HOURS  03:20-04:40 Thu, from the first kilometre to the last", out)
        self.assertIn("the arrival is fixed, so the hour is too", out)
        self.assertNotIn("to stay clear of them", out)
        # hours of the driver's own are used, and said to be theirs; --low-hours alone asks for the check
        out = ok("route", "krakow", "warsaw", "--depart", "2026-11-12 21:00", "--low-hours", "22:30-05:00")
        self.assertIn("falls in the low hours: 22:30-05:00 on the clock at the start (Europe/Warsaw) [derived; low hours as given]", out)
        self.assertNotIn("alertness is lowest", out)
        self.assertIn("or set off at 05:00 Fri or later", out)

    def test_long_day_and_thin_breaks(self):
        out = ok("route", "lisbon", "madrid", "paris", "berlin", "warsaw", "--mode", "motorway", "--depart", "2026-11-12 06:00", "--fatigue")
        self.assertIn("on the clock at the start (Europe/Lisbon)", out)
        self.assertIn(" on legs 2 to 3, about km ", out)
        self.assertIn("too long to fit between one night's low hours and the next: break it with an overnight stop", out)
        self.assertRegex(out, r"AT WHEEL   \d+h\d\dm of driving with no night's stop: more than the 9 h a professional driver may drive "
                              r"in a day in the EU \[Regulation \(EC\) No 561/2006, art\. 6\]")
        out = ok("route", "krakow", "gdansk", "--depart", "2026-12-05 08:00", "--break-every", "4", "--fatigue")
        self.assertIn("BREAKS     thinner than advised: at least 15 minutes after every 2 hours of driving [Highway Code rule 91]", out)
        self.assertNotIn("AT WHEEL", out)
        self.assertNotIn("BREAKS     thinner", ok("route", "krakow", "katowice", "--depart", "08:00", "--break-every", "0", "--fatigue"))

    def test_window_weighs_the_low_hours_first(self):
        out = ok("route", "krakow", "gdansk", "--window", "18:00-23:00", "--date", "2026-12-05", "--step", "60", "--fatigue")
        self.assertIn("BEST       depart 18:00, arrive 03:11 | night 9h11m, twilight 0h00m, low sun ahead 0h00m, low hours 3h11m", out)
        self.assertIn("WORST      depart 21:00", out)
        self.assertIn("LOW HOURS  00:00-03:11 Sun", out)
        # weighed for light alone, the same window sends the driver through the whole of the night for a little dawn at the end
        plain = ok("route", "krakow", "gdansk", "--window", "18:00-23:00", "--date", "2026-12-05", "--step", "60")
        self.assertIn("BEST       depart 23:00, arrive 08:11 | night 8h02m", plain)
        self.assertNotIn("low hours", plain)
        # where nothing in the window touches the low hours, the flag changes nothing and says so
        out = ok("route", "krakow", "katowice", "--window", "09:00-12:00", "--date", "2026-06-20", "--fatigue")
        self.assertIn("every departure in the window is the same for light and the low hours: the earliest is taken", out)
        self.assertIn("DEPART     2026-06-20 09:00", out)

    def test_trip_reads_the_driven_legs_on_the_body_clock(self):
        out = ok("trip", "ktw 2026-12-18 06:40 > cdg 08:55", "cdg 10:50 > msp 13:05", "--home", "krakow", "--onward", "rochester_us",
                 "--fatigue")
        self.assertIn("FATIGUE    2 drives checked on the body clock, the zone the trip starts in (Europe/Warsaw): low hours 00:00-06:00", out)
        self.assertIn("(KTW): 03:12-04:25 Fri body clock, all 1h13m of it in the low hours", out)
        self.assertIn("the onward drive to Rochester, Minnesota: 20:50-22:35 Fri body clock (13:50-15:35 local), clear", out)
        self.assertIn("AWAKE      the onward drive to Rochester, Minnesota ends 19h23m after you left Krak\u00f3w, and you were up before "
                      "that: after 17 h awake a driver is about as slowed as at 0.05% blood alcohol [NIOSH]", out)
        self.assertEqual(desk.check_text(out), [])
        # a westbound afternoon flight: the hire car at the far end is driven past the body's midnight
        out = ok("trip", "waw 2026-12-18 12:40 > jfk 16:05", "--home", "warsaw", "--onward", "philadelphia", "--fatigue")
        self.assertIn("the onward drive to Philadelphia: 22:50-00:59 Fri body clock (16:50-18:59 local), 0h59m of its 2h09m in the low hours", out)
        self.assertNotIn("AWAKE", out)
        self.assertNotIn("FATIGUE", ok("trip", "waw 2026-12-18 12:40 > jfk 16:05", "--home", "warsaw", "--onward", "philadelphia"))

    def test_trip_rest_and_nothing_driven(self):
        # a night in between is a chance to sleep: the count of hours awake starts again, and a leg marked 'drive' is checked
        out = ok("trip", "waw 2026-12-18 12:40 > jfk 16:05", "new_york 2026-12-19 09:00 > boston 13:30 drive", "--home", "warsaw", "--fatigue")
        self.assertIn("FATIGUE    2 drives checked", out)
        self.assertIn("the drive from New York to Boston: 15:00-19:30 Sat body clock (09:00-13:30 local), clear", out)
        self.assertNotIn("AWAKE", out)
        # the same two legs with no night between them
        out = ok("trip", "waw 2026-12-18 12:40 > jfk 16:05", "new_york 2026-12-18 18:00 > boston 22:30 drive", "--home", "warsaw", "--fatigue")
        self.assertIn("AWAKE      the drive from New York to Boston ends 18h14m after you left Warsaw", out)
        self.assertIn("00:00-04:30 Sat body clock (18:00-22:30 local), all 4h30m of it in the low hours", out)
        out = ok("trip", "krakow 08:02 > warsaw 10:28 rail", "--date", "2026-11-20", "--fatigue")
        self.assertIn("FATIGUE    nothing to check: nobody drives on this trip as given", out)

    def test_refusals(self):
        for args, word in ((("route", "krakow", "warsaw", "--fatigue"), "needs a time"),
                           (("route", "krakow", "warsaw", "--mode", "rail", "--depart", "21:00", "--fatigue"), "drive yourself"),
                           (("route", "waw", "cdg", "--mode", "air", "--depart", "21:00", "--fatigue"), "drive yourself"),
                           (("route", "krakow", "warsaw", "--depart", "21:00", "--low-hours", "06:00-06:00"), "two different times"),
                           (("route", "krakow", "warsaw", "--depart", "21:00", "--low-hours", "08:00-23:00"), "most of the day"),
                           (("route", "krakow", "warsaw", "--depart", "21:00", "--low-hours", "night"), "two clock times"),
                           (("trip", "waw 12:40 > jfk 16:05", "--low-hours", "25:00-06:00"), "out of range")):
            code, _, err = run(*args)
            self.assertEqual(code, 2, args)
            self.assertIn(word, err, args)

    def test_calendar_entry_carries_the_warning(self):
        with tempfile.TemporaryDirectory() as d:
            out = ok("route", "krakow", "ktw", "--arrive", "2026-11-12 04:40", "--fatigue", "--ics", d)
            with open(field(out, "CALENDAR"), "rb") as f:
                flat = f.read().decode("utf-8").replace("\r\n ", "")
            self.assertIn("Fatigue: 1h20m of this journey falls in the low hours\\, 00:00-06:00 on the clock at the start.", flat)
            out = ok("route", "krakow", "ktw", "--arrive", "2026-11-12 12:40", "--fatigue", "--ics", d)
            with open(field(out, "CALENDAR"), "rb") as f:
                self.assertNotIn(b"Fatigue:", f.read())

    def test_tools_find_names_route(self):
        for question in ("driving tired overnight", "fatigue"):
            self.assertEqual(ok("tools", "--find", *question.split()).splitlines()[1].split()[0], "route", question)


class JumpTests(unittest.TestCase):
    """The Squall: the flight is checked against the textbook, the burst against the maker's figures in lore.json."""

    def test_flat_jump_known_answer(self):
        out = ok("jump", "--gap", "20", "--speed", "50", "--load", "260")
        t = (20 + 4.85) / (50 / 3.6)
        vy = core.G * t / 2.0
        self.assertIn("JUMP       20 m gap, landing level, aiming 4.85 m past the far edge | 50 km/h, no ramp", out)
        self.assertIn("MASS       2,940 kg kerb [maker] + 260 kg aboard = 3,200 kg", out)
        self.assertIn("FLIGHT     %.2f s in the air, %.1f m up at the top, down 24.9 m on" % (t, vy * vy / (2 * core.G)), out)
        self.assertIn("the wheels give none, the Squall gives %.1f" % vy, out)
        self.assertIn("COST       %.1f km of range [lore: 0.18 km for each tonne and each m/s]" % (
            0.18 * 3.2 * vy), out)
        self.assertIn("G-LOAD     %.1f g for 0.25 s at the lift; %.1f g at the landing, a fall of 3.9 m, on the suspension, "
                      "which is built for it [maker]" % (vy / (0.25 * core.G) + 1, vy * vy / (2 * core.G * 0.5) + 1), out)
        self.assertIn("too brief to black anyone out: that takes about 5 s at 4.7 g or more [StatPearls, G-LOC]", out)
        self.assertIn("LEDGER     book it in a sim with: lattice --state ... squall=5.1 wait=1.8", out)
        self.assertNotIn("WARNING", out)

    def test_mass_and_distance_both_cost(self):
        def cost(*extra):
            return float(field(ok("jump", "--speed", "60", *extra), "COST").split()[0])
        light, heavy = cost("--gap", "40"), cost("--gap", "40", "--load", "2940")
        self.assertAlmostEqual(heavy / light, 2.0, places=1)                # twice the mass, twice the price
        self.assertGreater(cost("--gap", "40"), cost("--gap", "20"))
        faster = float(field(ok("jump", "--gap", "40", "--speed", "120"), "COST").split()[0])
        self.assertLess(faster, light)                                      # more speed, less lift

    def test_ramp_alone_and_ramp_with_speed(self):
        out = ok("jump", "--gap", "12", "--ramp", "15")
        v = math.sqrt(core.G * 16.85 / math.sin(math.radians(30)))
        self.assertIn("| %.0f km/h needed, off a 15 degree ramp" % (v * 3.6), out)
        self.assertIn("no burst [derived]", out)
        self.assertNotIn("COST", out)
        self.assertNotIn("LEDGER", out)
        out = ok("jump", "--gap", "30", "--speed", "90", "--ramp", "10", "--drop", "4")
        self.assertIn("landing 4 m lower", out)
        self.assertIn("m to spare", out)
        self.assertIn("no burst", out)
        out = ok("jump", "--gap", "30", "--speed", "60", "--ramp", "10")
        self.assertIn("the ramp gives 2.9, the Squall gives", out)
        self.assertIn("no speed under his 250 km/h governor", run("jump", "--gap", "900", "--ramp", "5")[2])

    def test_landing_higher_clears_the_edge(self):
        out = ok("jump", "--gap", "8", "--speed", "70", "--rise", "2")
        self.assertIn("landing 2 m higher", out)
        m = re.search(r"FLIGHT     ([\d.]+) s in the air, ([\d.]+) m up at the top, down ([\d.]+) m on", out)
        vy = float(re.search(r"the Squall gives ([\d.]+)", out).group(1))
        vx = 70 / 3.6
        at_edge = vy * (8 / vx) - 0.5 * core.G * (8 / vx) ** 2
        self.assertGreaterEqual(at_edge, 2.0 - 0.05)                        # above the far edge when he crosses it
        self.assertGreaterEqual(float(m.group(3)), 8 + 4.85 - 0.05)

    def test_warnings_follow_the_published_figures(self):
        out = ok("jump", "--gap", "32", "--speed", "60")
        self.assertIn("as hard as an ejection seat, 12 to 14 g [Indian Journal of Aerospace Medicine]", out)
        self.assertIn("warn the driver before the jump, unless there is no time for an answer; then it is his call, life first [maker]", out)
        self.assertIn("what would ease it: more speed (less lift is needed), a ramp, --catch for the landing", out)
        out = ok("jump", "--gap", "60", "--speed", "60", "--load", "400")
        self.assertIn("at 16 g half of lumbar spines are injured (13 to 19) [Stemper et al., J Orthop Res 36(6)]", out)
        self.assertIn("how much of that it survives has no figure, the driver rules", out)
        self.assertNotIn("which is built for it", out)
        out = ok("jump", "--gap", "60", "--speed", "60", "--load", "400", "--catch")
        self.assertIn("(11.5 to lift, 11.5 to catch the landing)", out)
        self.assertIn("8.8 g at the landing, a fall of 18.6 m, caught on a second burst", out)
        self.assertNotIn("WARNING", out)
        out = ok("jump", "--gap", "60", "--speed", "60", "--unmanned")
        self.assertIn("nobody aboard: it matters only to what is clamped in the cradle", out)
        self.assertNotIn("WARNING", out)

    def test_refusals(self):
        for args in (("--gap", "20"), ("--gap", "0", "--speed", "50"), ("--gap", "20", "--speed", "260"),
                     ("--gap", "20", "--speed", "50", "--drop", "1", "--rise", "1"), ("--gap", "20", "--speed", "50", "--ramp", "60"),
                     ("--gap", "20", "--speed", "50", "--load", "-1"), ("--gap", "20", "--speed", "0")):
            self.assertEqual(run("jump", *args)[0], 2, args)
        self.assertIn("does not lift it for a stunt", run("jump", "--gap", "20", "--speed", "260")[2])

    def test_ledger_books_a_burst(self):
        out = ok("lattice", "silent=on", "squall=5.1")
        self.assertIn("SILENT     ended: a Squall is heard a long way off", out)
        self.assertIn("SQUALL     burst fired at t=0:00.0: -5.1 km: range 1,500.0 -> 1,494.9 km [lore]", out)
        self.assertNotIn("| silent", field(out, "LEDGER"))
        out = ok("lattice", "--km", "3", "squall=5.1")
        self.assertIn("SQUALL     REFUSED: the burst needs 5.1 km of range and 3.0 km is left", out)
        self.assertIn("range 3.0 km", field(out, "LEDGER"))
        for bad in ("squall=x", "squall=0", "squall=-2"):
            self.assertEqual(run("lattice", bad)[0], 2, bad)
        state = field(ok("lattice", "squall=5.1"), "STATE")
        self.assertIn("range 1,494.9 km", field(ok("lattice", "--state", state, "wait=1"), "LEDGER"))

    def test_canon_and_fit_list(self):
        lore = core.load_data("lore")
        self.assertEqual(sorted(lore["squall"]), ["burst_s", "km_per_tonne_ms", "landing_stroke_m", "margin_m", "note"])
        self.assertNotIn("house rule", json.dumps(lore["squall"]) + " ".join(lore["assumptions"]))
        self.assertEqual((lore["squall"]["km_per_tonne_ms"], lore["squall"]["burst_s"], lore["squall"]["landing_stroke_m"]),
                         (0.18, 0.25, 0.5))
        self.assertEqual(lore["squall"]["margin_m"], lore["chassis"]["length_m"])
        fit = ok("record", "--fit")
        self.assertIn("FITTED     the Squall: ducts under the floor that throw a short burst of air downward [maker]", fit)
        self.assertIn("UNKNOWN    how soon the Squall can fire again - no figure", fit)
        self.assertIn("NOT FITTED amphibious or flight gear", fit)           # a leap is not flight
        with open(os.path.join(ROOT, "src", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        self.assertIn("The Squall [maker]:", skill)
        self.assertIn("Driver down. [maker]", skill)
        # the sound of his voice is the maker's: low, dry and close, a faint hum under it, British and measured, from the console
        self.assertIn("- How it sounds. [maker] Low, dry and close:", skill)
        for part in ("Standard southern British English at a measured pace", "the low tone of your motors, faint enough to miss",
                     "it comes from the console", "outside, from the light bar"):
            self.assertIn(part, skill)
        # the small print moved out of SKILL.md in 2.3.1: it must still ship, and SKILL.md must still point at it
        with open(os.path.join(ROOT, "src", "playbooks", "chassis.md"), encoding="utf-8") as f:
            small_print = f.read()
        for line in ("Radar and lidar send out a signal", "A Squall ends silent running", "A beam arrives with no warning",
                     "a deliberate burst of emissions"):
            self.assertIn(line, small_print)
            self.assertNotIn(line, skill)
        self.assertIn("`playbooks/chassis.md`", skill)

    def test_tools_find_names_jump(self):
        for question in ("jump over a gap", "clear a blown bridge"):
            self.assertEqual(ok("tools", "--find", *question.split()).splitlines()[1].split()[0], "jump", question)


class BriefTests(unittest.TestCase):
    """One record for a journey: every line in it is a line the command behind it printed."""

    FULL = ("brief", "krakow", "prague", "--depart", "2026-12-05 09:00", "--temp", "-1", "--humidity", "95", "--wind", "30",
            "--l-100", "6.5", "--price", "6.89")

    def test_it_says_what_the_commands_say(self):
        out = ok(*self.FULL)
        route = ok("route", "krakow", "prague", "--depart", "2026-12-05 09:00", "--fatigue")
        self.assertEqual(out.splitlines()[0], "BRIEF      Krak\u00f3w -> Prague [car; one way]")
        for key in ("ROAD", "DRIVE", "BREAKS", "TOTAL", "DEPART", "ARRIVE", "LIGHT", "FATIGUE", "LIVE MAP"):
            self.assertEqual(field(out, key), field(route, key), key)
        km = float(re.search(r"~([\d,]+) km", field(route, "ROAD")).group(1).replace(",", ""))
        fuel = ok("fuel", "--distance", km, "--l-100", "6.5", "--price", "6.89")
        self.assertAlmostEqual(float(field(out, "FUEL").split()[0]), float(field(fuel, "FUEL").split()[0]), delta=0.1)
        weather = ok("weather", "--temp", "-1", "--humidity", "95", "--wind", "30")
        self.assertEqual(field(out, "WEATHER"), field(weather, "AIR"))
        self.assertIn("SURFACE    freezing surface, dry for now: any damp patch is ice", out)
        self.assertIn("STOP       from 80 km/h on", out)
        self.assertEqual(field(out, "COUNTRY"), field(ok("country", "CZ", "--from", "PL"), "COUNTRY"))
        self.assertIn("EMERGENCY  112", out)
        for dropped in ("LEG 1", "STRAIGHT", "BUFFER", "DEW POINT", "DIAL", "CLOCKS", "TRIP "):
            self.assertNotIn("\n" + dropped, out)
        self.assertLess(len(out), len(route) + len(weather) + len(fuel) + len(ok("country", "CZ", "--from", "PL")))

    def test_fatigue_goes_in_unasked_and_says_so(self):
        out = ok("brief", "krakow", "gdansk", "--depart", "2026-12-05 21:00")
        self.assertIn("FATIGUE    6h00m of this 9h11m journey falls in the low hours", out)
        self.assertIn("LOW HOURS  00:00-06:00 Sun", out)
        offer = field(out, "OFFER")
        self.assertIn("the fatigue lines are here unasked, because this drive runs into the low hours", offer)
        self.assertIn("a word from them leaves the lines out (--no-fatigue)", offer)
        self.assertLess(out.index("OFFER"), out.index("LIVE MAP"))
        out = ok("brief", "krakow", "gdansk", "--depart", "2026-12-05 21:00", "--no-fatigue")
        for gone in ("FATIGUE", "LOW HOURS", "OFFER"):
            self.assertNotIn(gone, out)
        out = ok(*self.FULL)                                                # a clear check says so in one line and offers nothing
        self.assertIn("FATIGUE    clear of the low hours", out)
        self.assertNotIn("OFFER", out)
        out = ok("brief", "krakow", "prague", "--depart", "2026-12-05 06:00", "--speed", "45")
        self.assertIn("AT WHEEL", out)                                      # long, but clear of the low hours: still offered
        self.assertIn("because this drive is long or short of breaks", field(out, "OFFER"))
        out = ok("brief", "krakow", "gdansk", "--depart", "2026-12-05 21:00", "--low-hours", "01:00-05:00")
        self.assertIn("LOW HOURS  01:00-05:00 Sun", out)

    def test_what_is_not_given_is_not_checked(self):
        out = ok("brief", "warsaw", "krakow", "--firn")
        self.assertIn("TIME       none given: no arrival time, light or fatigue check", out)
        self.assertIn("WEATHER    not checked: no forecast figures given", out)
        self.assertIn("RANGE      318 km of 1,500 km [lore]", out)
        for absent in ("FATIGUE", "COUNTRY", "FUEL", "ARRIVE"):
            self.assertNotIn(absent, out)
        out = ok("brief", "krakow", "vienna", "48.2,16.37", "--mode", "rail", "--depart", "2026-12-05 09:00")
        self.assertIn("BRIEF      Krak\u00f3w -> 48.2,16.37 via Vienna [rail; one way]", out)
        self.assertIn("COUNTRY    not checked: 48.2,16.37 has no country on file", out)
        self.assertNotIn("FATIGUE", out)                                    # nobody drives a train they ride
        self.assertNotIn("STOP", ok("brief", "krakow", "vienna", "--mode", "rail", "--temp", "2", "--wet"))
        out = ok("brief", "krakow", "vienna", "bratislava", "--depart", "2026-12-05 09:00")
        self.assertIn("COUNTRY    Slovakia (SK)", out)
        self.assertIn("TRANSIT    also named on the way: AT", out)

    def test_window_and_refusals(self):
        out = ok("brief", "krakow", "gdansk", "--window", "05:00-11:00", "--date", "2026-12-05", "--before-dark", "--temp", "2", "--wet")
        self.assertIn("BEST       depart 06:00, arrive 15:11", out)
        self.assertIn("low hours 0h00m", out)
        self.assertIn("STOP       from 80 km/h on wet", out)
        for args in (("krakow",), ("krakow", "gdansk", "--wind", "30"), ("krakow", "gdansk", "--wet"),
                     ("krakow", "gdansk", "--l-100", "6", "--kwh-100", "18"), ("krakow", "gdansk", "--low-hours", "01:00-05:00"),
                     ("krakow", "gdansk", "--depart", "2026-12-05 21:00", "--no-fatigue", "--low-hours", "01:00-05:00"),
                     ("krakow", "nowhere-at-all")):
            self.assertEqual(run("brief", *args)[0], 2, args)
        self.assertEqual(run("brief", "krakow", "gdansk", "--wind", "30")[1], "")       # an error prints no half record

    def test_it_leaves_the_toolkit_as_it_found_it(self):
        ok(*self.FULL)
        self.assertIn("90 commands.", ok("tools"))
        self.assertEqual(ok("tools", "--find", "plan", "the", "whole", "journey").splitlines()[1].split()[0], "brief")


class ParkTests(unittest.TestCase):
    def test_stamp_and_way_back(self):
        out = ok("park", "50.26453,19.02372", "--note", "level 2, row C")
        self.assertIn("PARKED     50.2645,19.0237 (level 2, row C) at 2026-11-10 14:30 Tue UTC+01:00", out)
        stamp = field(out, "STAMP")
        self.assertEqual(stamp, "park --find --spot 50.26453,19.02372 --at 2026-11-10T13:30Z --from WHERE-YOU-ARE")
        self.assertIn("it lasts for this conversation unless", out)
        back = ok(*shlex.split(stamp.replace("WHERE-YOU-ARE", "50.25990,19.02160")))
        km = geo.haversine_km(50.2599, 19.0216, 50.26453, 19.02372)
        brg = geo.bearing_deg(50.2599, 19.0216, 50.26453, 19.02372)
        self.assertIn("CAR        %d m away, bearing %03.0f %s from 50.2599,19.0216 [derived, straight line]" % (
            round(km * 1000), brg, geo.compass(brg)), back)
        self.assertIn("WALK       about 0h07m at 4.8 km/h if the way is straight [estimate]", back)
        self.assertIn("PARKED     0h00m ago", back)
        self.assertIn("NOTE       he has no fix on", back)
        self.assertIn("PARKED     1h20m ago", ok("park", "--find", "--spot", "50.26453,19.02372", "--from", "50.2599,19.0216",
                                                 "--at", "2026-11-10T12:10Z"))

    def test_near_far_and_named_places(self):
        out = ok("park", "--find", "--spot", "50.26453,19.02372", "--from", "50.26455,19.02370")
        self.assertIn("within about 15 m of", out)
        self.assertNotIn("WALK", out)
        out = ok("park", "--find", "--spot", "50.26453,19.02372", "--from", "krakow")
        self.assertIn("km away, bearing", out)
        self.assertIn("CHECK      that is far for a car park", out)
        out = ok("park", "katowice")
        self.assertIn("a named town is good to a few kilometres", out)
        self.assertNotIn("a named town", ok("park", "50.26453,19.02372"))

    def test_refusals(self):
        for args in ((), ("--find",), ("--find", "--spot", "50.2,19.0"), ("--find", "--from", "50.2,19.0"),
                     ("50.2,19.0", "--spot", "50.2,19.0"), ("50.2,19.0", "--find", "--spot", "50.2,19.0", "--from", "50.2,19.0"),
                     ("--find", "--spot", "50.2,19.0", "--from", "50.2,19.0", "--at", "yesterday"),
                     ("--find", "--spot", "50.2,19.0", "--from", "50.2,19.0", "--at", "2026-11-11T09:00Z")):
            self.assertEqual(run("park", *args)[0], 2, args)

    def test_tools_find_names_park(self):
        for question in ("where did I leave the car", "find my parked car"):
            self.assertEqual(ok("tools", "--find", *question.split()).splitlines()[1].split()[0], "park", question)


class MetarTests(unittest.TestCase):
    def test_winter_report(self):
        out = ok("metar", "EPKT 101300Z 27012G22KT 9999 -SN BKN030 OVC045 M01/M03 Q1015 NOSIG")
        self.assertIn("STATION    EPKT Katowice", out)
        self.assertIn("OBSERVED   2026-11-10 13:00 UTC, 14:00 at the airport; 0h30m ago", out)
        self.assertIn("WIND       from 270 deg (W) at 22 km/h, gusting 41 km/h [27012G22KT]", out)
        self.assertIn("VISIBILITY 10 km or more", out)
        self.assertIn("WEATHER    light snow", out)
        self.assertIn("CLOUD      broken at 910 m (3,000 ft); overcast at 1,370 m (4,500 ft)", out)
        self.assertIn("AIR        -1 C, dew point -3 C", out)
        self.assertIn("PRESSURE   1,015 hPa", out)
        self.assertIn("ROAD       snow or ice falling", out)
        self.assertIn("ROAD       ICE LIKELY", out)
        self.assertIn("ROAD       fresh wind", out)
        self.assertIn("not a sensor reading of yours", out)

    def test_other_shapes(self):
        out = ok("metar", "KMSP", "101253Z", "32015G28KT", "1", "1/2SM", "-FZRA", "BR", "OVC008", "M02/M03", "A2992", "RMK", "AO2")
        self.assertIn("STATION    KMSP Minneapolis", out)
        self.assertIn("VISIBILITY 2,414 m", out)
        self.assertIn("WEATHER    light freezing rain; mist", out)
        self.assertIn("PRESSURE   1,013 hPa", out)
        self.assertIn("ROAD       FREEZING RAIN OR DRIZZLE REPORTED", out)
        self.assertIn("remarks follow", out)
        out = ok("metar", "EGLL 101320Z VRB03KT CAVOK 12/06 Q1022")
        self.assertIn("WIND       variable in direction at 6 km/h", out)
        self.assertIn("10 km or more (CAVOK", out)
        self.assertIn("nothing in this report calls for more than ordinary care", out)
        out = ok("metar", "EPKT 081300Z 00000KT 0150 FZFG VV001 M02/M02 Q1020")
        self.assertIn("48h30m ago", out)
        self.assertIn("OLD", out)
        self.assertIn("WIND       calm", out)
        self.assertIn("ROAD       dense fog, under 200 m", out)
        self.assertIn("ROAD       freezing fog", out)
        self.assertIn("OBSERVED   2026-10-30 06:00 UTC", ok("metar", "ZZZZ 300600Z 09005MPS 4000 RA 08/07 Q0998"))
        self.assertIn("(not in the gazetteer)", ok("metar", "ZZZZ 300600Z 09005MPS 4000 RA 08/07 Q0998"))
        self.assertIn("UNREAD     WS020/24045KT", ok("metar", "EPKT 101300Z 27012KT 9999 WS020/24045KT 05/01 Q1015"))
        self.assertEqual(run("metar", "good morning")[0], 2)

    def test_weather_groups_and_the_airport_codes(self):
        words = lambda t: metar.weather_words(t)[0]
        self.assertEqual(words("+TSRA"), "heavy thunderstorm with rain")
        self.assertEqual(words("VCSH"), "showers in the vicinity")
        self.assertEqual(words("FZFG"), "freezing fog")
        self.assertEqual(words("BCFG"), "patches of fog")
        self.assertEqual(words("-SHRASN"), "light showers of rain and snow")
        self.assertEqual(words("BLSN"), "blowing snow")
        self.assertIsNone(metar.weather_words("Q1015"))
        self.assertEqual(geo.find_place("EPWA")["key"], "waw")
        self.assertEqual(geo.find_place("kjfk")["key"], "jfk")
        airports = geo.select(kind="airport", with_own=False)
        self.assertTrue(all(len(p["icao"]) == 4 for p in airports if "icao" in p))
        self.assertGreater(sum(1 for p in airports if "icao" in p), 9000)
        self.assertIn("STATION    LIMA Torino", ok("metar", "LIMA 101250Z 00000KT 9999 FEW040 08/03 Q1021"))
        self.assertIn("LEG 1      Warsaw Chopin Airport (WAW) -> Katowice", ok("route", "EPWA", "EPKT"))


class BoardTests(unittest.TestCase):
    def state(self, out):
        return field(out, "STATE")

    def test_down_is_not_dead(self):
        s = self.state(ok("board", "add=anna:10", "add=raider:12:red", "add=drone:6:red:machine", "deadline=10"))
        self.assertEqual(s, "B1/r=1/dl=10/bl=3/u=anna:blue:l:10:10:up:0:-:-,raider:red:l:12:12:up:0:-:-,drone:red:m:6:6:up:0:-:-")
        out = ok("board", "--state", s, "hit=raider:12")
        self.assertIn("DOWN       raider is down, alive: 3 rounds for someone to reach them (aid=raider)", out)
        self.assertIn("REACH      raider (red) is down with 3 rounds left: aid=raider", out)
        down = self.state(out)
        out = ok("board", "--state", down, "round", "round")
        self.assertIn("DOWN, 1 round to reach", out)
        self.assertNotIn("LOST", out)
        out = ok("board", "--state", down, "round=3")
        self.assertIn("LOST       raider: nobody reached them in time", out)
        self.assertIn("LIVES      lost: raider. Every side is counted the same", out)
        self.assertIn("RED        1 up, 1 LOST", out)
        out = ok("board", "--state", down, "round", "aid=raider", "round=5")
        self.assertIn("AID        raider has been reached: stable, out of the fight, alive", out)
        self.assertIn("stable (aided)", out)
        self.assertNotIn("LOST", out)
        self.assertIn("LOST       raider was struck while down", ok("board", "--state", down, "hit=raider:1"))
        self.assertIn("raider: 12 of 12, up", ok("board", "--state", down, "heal=raider:20"))

    def test_subdue_machines_and_blows_far_past_zero(self):
        s = self.state(ok("board", "add=anna:10", "add=raider:12:red", "add=drone:6:red:machine"))
        out = ok("board", "--state", s, "hit=raider:15:subdue", "hit=drone:7")
        self.assertIn("DOWN       raider is subdued: out of the fight, alive, in no danger", out)
        self.assertIn("stable (subdued)", out)
        self.assertIn("DISABLED   drone is out of action: it can be rebuilt", out)
        self.assertNotIn("REACH", out)
        self.assertIn("LOST       anna: 25 from a single blow", ok("board", "--state", s, "hit=anna:25"))
        self.assertIn("WRECKED    drone is destroyed", ok("board", "--state", s, "hit=drone:12"))
        self.assertIn("OUT        raider has left the board, alive: surrendered", ok("board", "--state", s, "out=raider:surrendered"))

    def test_conditions_rounds_and_the_deadline(self):
        s = self.state(ok("board", "add=anna:10", "deadline=2", "cond=anna:stunned:2", "cond=anna:prone"))
        out = ok("board", "--state", s, "round")
        self.assertIn("round 2, 1 round left", out)
        self.assertIn("stunned 1, prone", out)
        out = ok("board", "--state", s, "round=3")
        self.assertIn("CLEARS     anna is no longer stunned", out)
        self.assertIn("DEADLINE   round 3: the scenario's time is up", out)
        self.assertIn("DEADLINE   round 4: 1 round past the limit", out)
        self.assertIn("round 4, time is up", out)
        self.assertIn("prone", out)
        self.assertNotIn("prone", ok("board", "--state", s, "clear=anna:prone", "round=2").split("BOARD")[1])

    def test_token_round_trip_and_bad_input(self):
        s = self.state(ok("board", "--bleed", "5", "add=a:9", "add=b:4:red:vehicle", "hit=a:9", "cond=b:on_fire:3", "deadline=6", "round"))
        b = board.Board()
        b.load(s)
        self.assertEqual(b.token(), s)
        self.assertEqual((b.bleed, b.round, b.deadline), (5, 2, 5))
        self.assertIn("nobody on it yet", ok("board"))
        self.assertEqual(run("board", "--state", "garbage")[0], 2)
        self.assertEqual(run("board", "--state", s, "hit=nobody:3")[0], 2)
        self.assertEqual(run("board", "--state", s, "add=a:5")[0], 2)
        self.assertEqual(run("board", "add=x:0")[0], 2)
        self.assertEqual(run("board", "add=x:5:red:ghost")[0], 2)
        self.assertEqual(run("board", "--state", s, "dance=a")[0], 2)


class ArmsTests(unittest.TestCase):
    def test_house_rules_hang_together(self):
        data = core.load_data("arms")
        kinds = set(data["kinds"])
        for name, w in data["weapons"].items():
            self.assertIn(w["kind"], kinds, name)
            self.assertTrue(dice.parse(w["dice"]), name)
            self.assertEqual(sum(1 for k in ("reach", "bands", "radius") if k in w), 1, name)
            for key in ("bands", "radius"):
                if key in w:
                    self.assertEqual(sorted(w[key]), w[key], name)
        for name, arm in data["armour"].items():
            self.assertEqual(set(k for k in arm if k != "is"), kinds, name)
            self.assertTrue(all(0 <= arm[k] <= 1 for k in kinds), name)
        listing = ok("strike", "--list")
        for name in data["weapons"]:
            self.assertIn(name, listing)

    def test_strike(self):
        out = ok("strike", "longbow", "--range", "120", "--armour", "mail", "--skill", "2", "--hp", "12")
        self.assertIn("120 m, long band; target number 11 = 7 base +4 range +0 cover", out)
        self.assertIn("TO HIT     2d6+2 against 11: 27.78% (1 in 3.6)", out)
        self.assertIn("1d8 pierce x 0.75 through mail: 1 to 6, average 3.5 a hit; 0.97 a shot", out)
        self.assertIn("TO DOWN    12 hit points: 3.9 hits on average, so about 14.1 attacks", out)
        self.assertIn("target number 9 = 7 base +0 range +2 cover", ok("strike", "sword", "--cover", "half"))
        self.assertIn("200 m: OUT OF RANGE. The long band of a longbow ends at 180 m", ok("strike", "longbow", "--range", "200"))
        self.assertIn("3 m: OUT OF REACH. A sword reaches 1 m", ok("strike", "sword", "--range", "3"))
        self.assertIn("never. Nothing gets through this armour", ok("strike", "sword", "--armour", "armoured", "--hp", "30"))
        out = ok("strike", "--dice", "2d10", "--kind", "cut", "--armour", "plate", "--target", "8")
        self.assertIn("target number 8 [as given]", out)
        self.assertIn("your own weapon: 2d10 cut", out)
        self.assertIn("x 0.4 through armour, as given", ok("strike", "sword", "--factor", "0.4"))
        code, _, err = run("strike", "longbo")
        self.assertEqual(code, 2)
        self.assertIn("Did you mean: longbow", err)
        self.assertEqual(run("strike", "grenade")[0], 2)
        self.assertEqual(run("strike", "sword", "--armour", "tinfoil")[0], 2)
        self.assertEqual(run("strike")[0], 2)

    def test_beams_and_blows_meant_to_stop(self):
        out = ok("strike", "laser_rifle", "--range", "400", "--air", "smoke", "--armour", "mirrored", "--hp", "20")
        self.assertIn("medium band (a beam does not drop: no penalty before the long band); target number 7", out)
        self.assertIn("x 0.5 through plate with a reflective finish, x 0.5 through smoke: 1 to 4", out)
        self.assertIn("HEAT       3 a shot of 12: 4 shots, then a round to cool", out)
        self.assertIn("target number 9", ok("strike", "laser_rifle", "--range", "900"))
        out = ok("strike", "stun_baton", "--armour", "padded", "--hp", "10")
        self.assertIn("1d6 crush x 0.75 through padded or leather: 1 to 5, average 2.8", out)
        self.assertIn("TO DOWN    10 hit points: 4 hits on average", out)
        self.assertIn("x 0.5 to subdue: 1 to 4, average 2.5", ok("strike", "sword", "--subdue"))

    def test_rolls_repeat(self):
        out = ok("strike", "sword", "--armour", "plate", "--skill", "1", "--roll", "--seed", "5", "--at", "raider")
        self.assertIn("ROLL       [5, 3] + 1 = 9 against 7: HIT. Damage [6] = 6, 2 gets through", out)
        self.assertIn("BOOK IT    board --state ... hit=raider:2", out)
        self.assertEqual(out, ok("strike", "sword", "--armour", "plate", "--skill", "1", "--roll", "--seed", "5", "--at", "raider"))
        self.assertIn("= 3 against 7: MISS", ok("strike", "sword", "--armour", "plate", "--skill", "1", "--roll", "--seed", "2"))
        self.assertIn("BOOK IT    board --state ... hit=raider:4:subdue",
                      ok("strike", "sword", "--subdue", "--skill", "9", "--roll", "--seed", "6", "--at", "raider"))

    def test_sums_behind_the_table(self):
        self.assertEqual(arms.through({1: 0.5, 4: 0.5}, 0.5), {1: 0.5, 2: 0.5})
        self.assertEqual(arms.through({3: 1.0}, 0.0), {0: 1.0})
        self.assertAlmostEqual(arms.hits_to_down({1: 1.0}, 5), 5.0)
        self.assertAlmostEqual(arms.hits_to_down({0: 0.5, 2: 0.5}, 2), 2.0)
        self.assertAlmostEqual(arms.hits_to_down({1: 0.5, 2: 0.5}, 2), 1.5)
        self.assertIsNone(arms.hits_to_down({0: 1.0}, 3))

    def test_blast(self):
        out = ok("blast", "blast_charge", "--at", "1.5", "4", "12", "--cover", "none", "half", "none", "--armour", "vest", "none", "none",
                 "--names", "anna", "raider", "guard", "--roll", "--seed", "3")
        self.assertIn("blast_charge: 4d6, full to 2 m, half to 5 m, a quarter to 10 m", out)
        self.assertIn("ROLL       [2, 5, 5, 2] = 14, one roll for the whole blast", out)
        self.assertIn("ANNA       1.5 m: full damage, a modern protective vest -> x 0.75: 3 to 18, average 10.6 | this blast: 11", out)
        self.assertIn("RAIDER     4 m: half damage, half cover -> x 0.25: 1 to 6, average 3.6 | this blast: 4", out)
        self.assertIn("GUARD      12 m: outside the blast", out)
        self.assertIn("BOOK IT    board --state ... hit=anna:11 hit=raider:4", out)
        self.assertIn("Everyone in it is counted", out)
        out = ok("blast", "flashbang", "--at", "2", "5", "--roll", "--seed", "3", "--names", "raider", "guard")
        self.assertIn("stuns, does not wound", out)
        self.assertIn("hit=raider:7:subdue hit=guard:4:subdue", out)
        self.assertIn("x 0.125", ok("blast", "--dice", "5d6", "--radius", "4", "8", "16", "--at", "12", "--armour", "armoured"))
        self.assertEqual(run("blast", "sword", "--at", "2")[0], 2)
        self.assertEqual(run("blast", "grenade", "--at", "2", "3", "--cover", "half", "none", "full")[0], 2)
        self.assertEqual(run("blast", "grenade", "--at", "2", "--radius", "9", "5", "1")[0], 2)

    def test_arc(self):
        out = ok("arc", "longbow", "--range", "120")
        self.assertIn("LAUNCH     55 m/s from 1.5 m up, target at 0 m [longbow", out)
        self.assertIn("FLAT       10.7 deg up: 2.22 s in the air", out)
        self.assertIn("LOBBED     78.6 deg up", out)
        self.assertIn("FURTHEST   310 m", out)
        out = ok("arc", "--speed", "20", "--angle", "45", "--height", "0")
        self.assertIn("lands %s m away" % core.trim(20 * 20 / core.G, 1), out)
        self.assertIn("OUT OF REACH", ok("arc", "longbow", "--range", "400"))
        self.assertIn("it never climbs to 50 m", ok("arc", "--speed", "10", "--angle", "20", "--target-height", "50"))
        self.assertEqual(run("arc", "--speed", "20")[0], 2)
        self.assertEqual(run("arc", "sword", "--range", "5")[0], 2)

    def test_lead(self):
        out = ok("lead", "--speed", "40", "--range", "300", "--shell", "850", "--length", "6.5")
        self.assertIn("FLIGHT     0.35 s", out)
        self.assertIn("LEAD       3.9 m ahead of where the target is now, 0.6 of its own lengths; aim 0.7 deg off it", out)
        self.assertIn("crossing square on", out)
        self.assertIn("LEAD       9.6 m ahead", ok("lead", "longbow", "--speed", "20", "--range", "90", "--angle", "60"))
        out = ok("lead", "--speed", "30", "--tof", "2.4", "--length", "4.5")
        self.assertIn("LEAD       20 m ahead of where the target is now, 4.4 of its own lengths", out)
        for args in (("lead", "--beam", "--range", "800"), ("lead", "laser_rifle", "--speed", "60", "--range", "800")):
            self.assertIn("LEAD       none. A beam crosses 800 m in about 2.7 microseconds", ok(*args))
        self.assertIn("straight away", ok("lead", "--speed", "40", "--range", "300", "--shell", "850", "--angle", "0"))
        self.assertEqual(run("lead", "--speed", "400", "--range", "300", "--shell", "90")[0], 2)
        self.assertEqual(run("lead", "--range", "300", "--shell", "850")[0], 2)

    def test_scenario_arms_leave_the_rest_alone(self):
        plain = ok("scenario", "--mission", "extraction", "--seed", "12")
        armed = ok("scenario", "--mission", "extraction", "--seed", "12", "--arms")
        self.assertIn("ARMS       a mine at a choke point, and nothing else", armed)
        self.assertEqual(plain, "".join(line for line in armed.splitlines(True) if not line.startswith("ARMS")))
        self.assertIn("ARMS       10 entries", ok("scenario", "--list"))


class LapsAndTuneTests(unittest.TestCase):
    def test_laps(self):
        out = ok("laps", "1:50.2", "1:42.5", "1:42.9", "1:49.9", "1:43.4", "1:43.6", "1:55.0", "--skip-first", "1", "--skip-last", "1",
                 "--fuel-gain", "0.03", "--sectors", "31.2 40.1 31.2", "--sectors", "31.0 40.6 31.3", "--sectors", "31.4 40.0 32.0")
        self.assertIn("7 given, 4 used, out and in laps left out; set aside as traffic or a mistake: lap 4 (1:49.900)", out)
        self.assertIn("BEST       1:42.500 on lap 2", out)
        self.assertIn("AVERAGE    1:43.100, 0.6 s off the best", out)
        self.assertIn("0.27 s a lap as measured; fuel burning off is worth 0.03 s a lap, so the tyres cost 0.3 s a lap", out)
        self.assertIn("stint ... --lap 1:42.560 --deg 0.3", out)
        self.assertIn("IDEAL LAP  1:42.200 from the best of each sector, 0.3 s quicker", out)
        self.assertIn("most time is being left in sector 3", out)
        out = ok("laps", "100.0", "100.1", "100.2", "100.3", "100.4")
        self.assertIn("PACE DROP  0.1 s a lap over the run", out)
        self.assertIn("--lap 1:40.000 --deg 0.1", out)
        self.assertIn("the laps got quicker", ok("laps", "100.4", "100.3", "100.2", "100.1"))
        self.assertIn("no drop to speak of", ok("laps", "100.0", "100.0", "100.0"))
        self.assertEqual(run("laps", "1:42.5", "1:42.9")[0], 2)
        self.assertEqual(run("laps", "1:42.5", "1:42.9", "1:43.0", "--skip-first", "2")[0], 2)
        self.assertEqual(run("laps", "1:42.5", "1:42.9", "1:43.0", "--sectors", "31.2 40.1", "--sectors", "31.0 40.6 31.3")[0], 2)

    def test_lsl_tune(self):
        out = ok("lsl", "tune", "--top", "100", "--reach", "80", "--in", "5", "--brake-from", "100", "--brake-m", "40",
                 "--turn-radius", "6", "--at", "30")
        self.assertIn("llSetVehicleFloatParam(VEHICLE_LINEAR_MOTOR_TIMESCALE, 3.21);", out)
        self.assertIn("llSetVehicleVectorParam(VEHICLE_LINEAR_MOTOR_DIRECTION, <28.67, 0.0, 0.0>);", out)
        self.assertIn("VEHICLE_LINEAR_FRICTION_TIMESCALE, <100.0, 2.0, 1000.0>);", out)
        self.assertIn("VEHICLE_LINEAR_FRICTION_TIMESCALE, <1.44, 2.0, 1000.0>);", out)
        self.assertIn("VEHICLE_ANGULAR_MOTOR_DIRECTION, <0.0, 0.0, 1.39>);", out)
        self.assertIn("NEXT       these are starting values", out)
        self.assertNotIn("UNTESTED", out)
        calls = [line.split(";")[0].split("  ")[-1].strip() + ";" for line in out.splitlines() if "llSetVehicle" in line]
        self.assertEqual(len(calls), 5)
        script = ("default\n{\n    state_entry()\n    {\n        llSetVehicleType(VEHICLE_TYPE_CAR);\n        %s\n"
                  "        llSetStatus(STATUS_PHYSICS, TRUE);\n    }\n}\n" % "\n        ".join(calls))
        self.assertEqual([f for f in sl.lint(script) if f[1] == "WARN"], [])
        # the model behind it, stepped through: 80 km/h after 5 s, and 100 km/h in the end
        tm, tf, target = 3.2063, 100.0, 28.668
        v, dt = 0.0, 0.0005
        for _ in range(int(5 / dt)):
            v += ((target - v) / tm - v / tf) * dt
        self.assertAlmostEqual(v * 3.6, 80.0, delta=0.15)
        for _ in range(int(60 / dt)):
            v += ((target - v) / tm - v / tf) * dt
        self.assertAlmostEqual(v * 3.6, 100.0, delta=0.15)
        out = ok("lsl", "tune", "--top", "180", "--reach", "100", "--in", "6")
        self.assertIn("past the engine's linear motor limit of about 30 m/s (108 km/h)", out)
        self.assertIn("<30.0, 0.0, 0.0>", out)
        self.assertEqual(run("lsl", "tune")[0], 2)
        self.assertEqual(run("lsl", "tune", "--top", "100", "--reach", "100", "--in", "5")[0], 2)
        self.assertEqual(run("lsl", "tune", "--top", "100", "--reach", "80", "--in", "5", "--coast", "2")[0], 2)
        self.assertEqual(run("lsl", "tune", "--top", "100", "--brake-from", "100")[0], 2)


class ReplyCompareCountryTests(unittest.TestCase):
    def reply(self, *lines):
        return run("check", "--reply", "--text", *lines)

    def test_reply_lint(self):
        code, out, _ = self.reply("Route set. Leave by 03:59.", "[bar: lock]")
        self.assertEqual(code, 0)
        self.assertIn("REPLY      clean", out)
        self.assertEqual(self.reply("Two states are fine.", "[bar: deep+trace]")[0], 0)
        code, out, _ = self.reply("My sensors detect no anomalies.", "*revs engine*", "[bar: purple]", "trailing line")
        self.assertEqual(code, 1)
        self.assertIn("CHECK L1   \"my sensors\" reads like a sensor reading", out)
        self.assertIn("CHECK L2   reads like a stage direction", out)
        self.assertIn("FIX L3     the bar line is not the last line of the reply", out)
        self.assertIn("FIX L3     bar state 'purple' is not one of: idle, sweep, lock", out)
        self.assertIn("REPLY      2 to fix, 2 to look at again", out)
        self.assertIn("no bar line", self.reply("Just words.")[1])
        self.assertIn("a bar line inside a code block", self.reply("Here.", "```", "[bar: idle]", "```", "[bar: idle]")[1])
        self.assertIn("2 bar lines", self.reply("[bar: idle]", "More.", "[bar: lock]")[1])
        self.assertIn("at most two bar states", self.reply("Hm.", "[bar: deep+trace+low]")[1])
        self.assertIn("not a bar line as written", self.reply("Hm.", "[Bar: Idle]")[1])
        self.assertIn("never closed", self.reply("```", "RECORD x", "[bar: idle]")[1])
        long_reply = ["Line %d of a reply that goes on." % n for n in range(13)] + ["[bar: idle]"]
        code, out, _ = self.reply(*long_reply)
        self.assertEqual(code, 0)
        self.assertIn("13 lines of prose", out)
        block = ["Short."] + ["```"] + ["ROW %d  value" % n for n in range(20)] + ["```", "[bar: lock]"]
        self.assertIn("REPLY      clean", self.reply(*block)[1])
        code, out, _ = self.reply("He said \u201cgo\u201d.", "[bar: idle]")
        self.assertEqual(code, 1)
        self.assertIn("FIX L1     col 9", out)

    def test_cost_to_own(self):
        out = ok("compare", "Kestrel: price=189000, resale=95000, kwh100=17.1, insurance=4200, service=900",
                 "Heron: price=121000, resale=60000, l100=5.8, insurance=3100, service=1600",
                 "--kwh-price", "1.1", "--fuel-price", "6.5", "--km-year", "12000", "--years", "5")
        self.assertRegex(out, r"loss of value per year\s+18,800\s+12,200\s+Heron by 35%\s+\[derived, over 5 years\]")
        self.assertRegex(out, r"fixed costs per year\s+5,100\s+4,700\s+Heron by 8%")
        self.assertRegex(out, r"to own, per year\s+26,157\s+21,424\s+Heron by 18%\s+\[derived: loss of value \+ energy \+ fixed costs\]")
        self.assertRegex(out, r"to own, per month\s+2,180\s+1,785")
        self.assertRegex(out, r"to own, per km\s+2\.18\s+1\.79")
        out = ok("compare", "A: price=100000, resale=50000, insurance=3000", "B: price=90000, insurance=2500")
        self.assertRegex(out, r"to own, per year\s+3,000\s+2,500\s+B by 17%\s+\[derived: fixed costs\]")
        self.assertIn("left out of the cost to own, because not every vehicle has the figure: loss of value", out)
        self.assertNotIn("to own", ok("compare", "A: kw=100, kwh100=17", "B: kw=90, kwh100=19", "--kwh-price", "1", "--km-year", "10000"))
        self.assertEqual(run("compare", "A: price=1", "B: price=2", "--years", "0")[0], 2)

    def test_country_card(self):
        out = ok("country", "GB", "--from", "PL")
        self.assertIn("COUNTRY    United Kingdom (GB), capital London", out)
        self.assertIn("DRIVES     on the left - the other side from Poland", out)
        self.assertIn("SPEED      limits are posted in miles an hour, not the km/h of Poland", out)
        self.assertIn("CURRENCY   GBP", out)
        self.assertIn("EMERGENCY  999; also on file, with no note of which service answers: 112 - not checked one by one", out)
        self.assertIn("PLUGS      type G; 230 V - none of Poland's (C, E) fit: take an adapter", out)
        self.assertIn("DIAL       +44", out)
        self.assertIn("CLOCKS     Europe/London 13:30", out)
        self.assertIn("Wikidata, read 2026-11-10", out)
        out = ok("country", "tokyo")
        self.assertIn("COUNTRY    Japan (JP), capital Tokyo", out)
        self.assertIn("the other side from Poland", out, "home is in Poland, so the difference is offered unasked")
        self.assertIn("EMERGENCY  110, 118, 119 on file, with no note of which service answers which", out)
        out = ok("country", "poland")
        self.assertIn("DRIVES     on the right\n", out)
        self.assertIn("EMERGENCY  112; also on file", out)
        for name in ("uk", "Great Britain", "gb"):
            self.assertIn("United Kingdom (GB)", ok("country", name))
        self.assertIn("reported to post limits in miles an hour: check", ok("country", "PR"))
        out = ok("country", "--left")
        self.assertIn("67 countries and territories drive on the left", out)
        self.assertIn("Japan (JP)", out)
        self.assertNotIn("Argentina", out)
        code, _, err = run("country", "polnd")
        self.assertEqual(code, 2)
        self.assertIn("Did you mean: Poland", err)
        self.assertEqual(run("country")[0], 2)

    def test_country_table(self):
        doc = core.load_data("countries")
        data = doc["countries"]
        self.assertGreater(len(data), 220)
        for code, c in data.items():
            self.assertEqual(set(c) - {"capital", "aka"}, {"name", "side", "speed", "currency", "emergency", "plugs", "volts", "dial"}, code)
            self.assertIn(c["side"], ("left", "right", ""), code)
            self.assertIn(c["speed"], ("km/h", "mph", "check"), code)
            self.assertTrue(all(e.isdigit() for e in c["emergency"]), code)
        left = set(code for code, c in data.items() if c["side"] == "left")
        for code in ("GB", "IE", "JP", "AU", "NZ", "IN", "ZA", "TH", "CY", "MT", "KE", "SG", "HK"):
            self.assertIn(code, left)
        for code in ("PL", "DE", "FR", "US", "CA", "CN", "AR", "SE", "BR", "RU"):
            self.assertNotIn(code, left)
        self.assertEqual([c for c, v in data.items() if v["speed"] == "mph"], ["GB", "US"])
        self.assertEqual(data["PL"]["currency"], ["PLN"])
        self.assertEqual([data[c]["emergency"][0] for c in ("US", "CA", "AU", "NZ", "GB", "CH")], ["911", "911", "000", "111", "999", "112"])
        for code in ("PL", "DE", "FR", "ES", "IT", "SE", "NL", "CZ", "AT", "IE", "PT", "GR", "FI", "DK", "BE", "HU", "RO", "SK", "LT"):
            self.assertEqual(data[code]["emergency"][0], "112", code)
        for code in set(p["cc"] for p in geo.select(kind="capital", with_own=False) if p.get("cc")):
            self.assertIn(code, data)


class DailyTests(unittest.TestCase):
    """Everyday sums: stops on a route, warming the cabin, heat in a parked car, an overtake, a mileage log."""

    def test_stops_fall_where_the_reserve_allows(self):
        a, b = geo.parse_point("warsaw"), geo.parse_point("lisbon")
        total = geo.haversine_km(a[1], a[2], b[1], b[2]) * 1.25
        out = ok("stops", "warsaw", "lisbon", "--range", "620", "--stop-min", "12")
        self.assertEqual(field(out, "ROUTE"), "Warsaw -> Lisbon: ~%s km by road [estimate: straight line x 1.25]" % core.num(total))
        self.assertEqual(field(out, "RANGE"), "620 km on a full tank or charge [as given]; starting at 100%, never below 10%, each stop fills to 100%")
        hop = 620 * 0.9
        stops = int(math.ceil(total / hop)) - 1
        self.assertEqual(stops, 6)
        self.assertTrue(field(out, "STOP 1").startswith("by km 558 (leg 1, near "))
        self.assertTrue(field(out, "STOP 6").endswith("): 10% -> 100%, 0h12m"))
        self.assertNotIn("STOP 7", out)
        self.assertEqual(field(out, "STOPS"), "6, adding 1h12m [12 min each, as given]")
        left = 100 - (total - stops * hop) / 620 * 100
        self.assertEqual(field(out, "ARRIVE"), "with %s%% (%s km of range)" % (core.trim(left, 0), core.num(620 * left / 100)))
        self.assertEqual(field(ok("stops", "krakow", "katowice", "--range", "500"), "STOPS"), "none: the range covers it")
        # an electric car: the stop time is the charge, with the same taper 'ev charge' uses
        from types import SimpleNamespace
        from firnlib import energy
        profile = energy.charge_profile(SimpleNamespace(kw=150.0, car_max=None, knee=50.0, tail=0.25, ac=False))
        took = energy.charge_time_h(77.0, 10.0, 80.0, profile)
        out = ok("stops", "krakow", "gdansk", "--range", "380", "--start", "80", "--fill", "80", "--battery", "77", "--kw", "150")
        self.assertTrue(field(out, "STOP 1").startswith("by km 266 (leg 1, near "))
        self.assertTrue(field(out, "STOP 1").endswith("): 10%% -> 80%%, %s" % core.fmt_hm(took)))
        self.assertEqual(field(out, "STOPS"), "2, adding %s [150 kW, tapering above 50%% as 'ev charge' does]" % core.fmt_hm(2 * took))
        # a car crossing is still a drive; a flight is not
        self.assertIn("ROUTE      London -> Paris: ~", ok("stops", "london", "paris", "--range", "300"))
        for args, word in ((("stops", "warsaw", "washington", "--range", "500"), "leg 1 has no road (by air, WAW to DCA"),
                           (("stops", "warsaw", "lisbon"), "give --range"),
                           (("stops", "warsaw", "lisbon", "--range", "500", "--firn"), "leave out --range"),
                           (("stops", "warsaw", "lisbon", "--range", "500", "--kw", "150"), "needs both --battery and --kw"),
                           (("stops", "warsaw", "lisbon", "--range", "500", "--fill", "10"), "--fill must be above --reserve")):
            code, _, err = run(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn(word, err, args)

    def test_his_own_recharge_is_the_makers(self):
        lore = core.load_data("lore")
        self.assertEqual((lore["recharge"]["spine_min"], lore["recharge"]["road_kw"]), (10, 350))
        self.assertTrue(lore["recharge"]["note"].startswith("[maker] "))
        out = ok("stops", "warsaw", "lisbon", "--firn")
        self.assertIn("RANGE      1,500 km on a full bank [lore]", out)
        hour = 400 * 0.9 / 350
        self.assertTrue(field(out, "STOP 1").startswith("by km 1,350 (leg 1, near "))
        self.assertTrue(field(out, "STOP 1").endswith("): 10%% -> 100%%, %s" % core.fmt_hm(hour)))
        self.assertEqual(field(out, "STOPS"), "2, adding %s [350 kW, steady: his recharge has no taper on file]" % core.fmt_hm(2 * hour))
        self.assertEqual(field(out, "HOME"), "on his own spine in the bay a full bank takes 10 min [lore]; on the road he takes what the charger gives")
        self.assertEqual(core.fmt_hm(400 / 350.0), "1h09m")     # 'a little over an hour from empty', as she ruled
        fit = ok("record", "--fit")
        self.assertIn("FITTED     charging spine in the bay [maker] - a full bank in 10 minutes", fit)
        self.assertNotIn("how the capacitor bank is recharged", fit)
        with open(os.path.join(ROOT, "src", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        self.assertIn("| Recharge | full in 10 minutes on your charging spine in the bay; on the road, what the charger gives: a little "
                      "over an hour from empty at 350 kW |", skill)

    def test_guest_driver(self):
        with open(os.path.join(ROOT, "src", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        self.assertIn("Guest driver. [maker] When someone other than the driver takes the wheel, the Veil, the Squall, the smoke, the "
                      "spike and any mission module stay locked to the driver. The Cell and the Scales protect the guest regardless. "
                      "You may open those systems to a commanding officer, provided the chain of command the driver has set is "
                      "followed.", skill)
        # what she did not pick stays out
        for word in ("geofence", "speed cap", "capped to"):
            self.assertNotIn(word, skill)

    def test_precondition(self):
        out = ok("precondition", "--leave", "2026-11-13 07:30", "--minutes", "25", "--kw", "3", "--kwh-100", "18", "--outside", "-5")
        self.assertTrue(field(out, "LEAVE").startswith("2026-11-13 07:30 Fri"))
        self.assertTrue(field(out, "START").startswith("2026-11-13 07:05 Fri"))
        self.assertTrue(field(out, "START").endswith(": 25 min before [as given]"))
        self.assertEqual(field(out, "ENERGY"), "1.25 kWh: 3 kW for 25 min [as given]")
        self.assertEqual(field(out, "RANGE"), "about 7 km of range, at 18 kWh per 100 km [derived]")
        self.assertEqual(field(out, "GLASS"), "-5 C outside: clear every window before you move, whatever the clock says")
        out = ok("precondition", "--leave", "16:00", "--minutes", "10", "--kw", "2", "--plugged", "--price", "1.1", "--outside", "30")
        self.assertEqual(field(out, "RANGE"), "none lost: on the cable the energy comes from the wall")
        self.assertEqual(field(out, "COST"), "0.37 [0.33 kWh x 1.1]")
        self.assertNotIn("GLASS", out)
        out = ok("precondition", "--leave", "07:30", "--minutes", "20")
        self.assertNotIn("ENERGY", out)
        self.assertIn("add --kw", out)
        code, _, err = run("precondition", "--leave", "07:30", "--minutes", "0")
        self.assertNotEqual(code, 0)
        self.assertIn("--minutes is how long the car needs", err)

    def test_hot_car_is_the_studys_figures(self):
        from firnlib import daily
        table = core.load_data("cabin_heat")
        self.assertEqual(table["rise_f"], [[10, 19], [20, 29], [30, 34], [60, 43]])
        self.assertEqual(table["later_f"], [["1-2 h", 45, 50], ["2-4 h", 50, 55]])
        self.assertEqual((table["ambient_f"], table["cracked_f"]), ([72, 96], 3))
        self.assertIn("noheatstroke.org", table["source"])
        self.assertAlmostEqual(daily.rise_f(table, 15), 24.0)
        self.assertAlmostEqual(daily.rise_f(table, 45), 38.5)
        self.assertAlmostEqual(daily.rise_f(table, 5), 9.5)
        self.assertIsNone(daily.rise_f(table, 61))
        out = ok("hotcar", "--temp", "26", "--minutes", "15")
        self.assertEqual(field(out, "10 MIN"), "about 37 C inside (+11 C)")
        self.assertEqual(field(out, "20 MIN"), "about 42 C inside (+16 C)")
        self.assertEqual(field(out, "30 MIN"), "about 45 C inside (+19 C)")
        self.assertEqual(field(out, "60 MIN"), "about 50 C inside (+24 C)")
        self.assertEqual(field(out, "1-2 H"), "about 51 to 54 C inside (+25 to +28 C)")
        self.assertEqual(field(out, "AT"), "15 min: about 39 C inside [between the study's points]")
        self.assertEqual(field(out, "WINDOWS"), "left open a crack they changed the rise by less than 1.7 C [NoHeatStroke.org]")
        self.assertIn("RULE       nobody waits in a parked car in the sun", out)
        self.assertNotIn("CHECK", out)
        out = ok("hotcar", "--temp", "10", "--minutes", "90")
        self.assertEqual(field(out, "CHECK"), "the study measured days of 22 to 36 C: at 10 C this is outside what it saw")
        self.assertEqual(field(out, "AT"), "90 min is past the study's hour: read the later rows")
        with open(os.path.join(SCRIPTS, "data", "SOURCES.md"), encoding="utf-8") as f:
            self.assertIn("`cabin_heat.json`", f.read())

    def test_overtake_known_answer(self):
        v1, v3, a = 80 / 3.6, 100 / 3.6, 1.5
        gain = 2 * v1 + 16.5 + 4.5 + 2 * v1
        t_acc = (v3 - v1) / a
        gained = 0.5 * a * t_acc ** 2
        t = t_acc + (gain - gained) / (v3 - v1)
        dist = v1 * t_acc + gained + v3 * (t - t_acc)
        need = dist + 90 / 3.6 * t
        out = ok("overtake", "--speed", "80", "--to", "100", "--accel", "1.5", "--len", "4.5", "--other-len", "16.5", "--oncoming", "90", "--see", "600")
        self.assertEqual(field(out, "PASS"), "100 km/h past 80 km/h: %s s and %s m of road, from pulling out to back in lane [derived]" % (
            core.trim(t, 1), core.num(dist)))
        self.assertEqual(field(out, "PASS"), "100 km/h past 80 km/h: 21.6 s and 591 m of road, from pulling out to back in lane [derived]")
        self.assertEqual(field(out, "GAIN"), "110 m more than it travels: 44 m behind it, its 16.5 m, your 4.5 m, 44 m ahead of it (2 s gaps)")
        self.assertEqual(field(out, "PACE"), "80 -> 100 km/h at 1.5 m/s2 [as given]")
        self.assertEqual(field(out, "CLEAR"), "%s m of empty road ahead when you pull out: your 591 m and the %s m something at 90 km/h "
                         "covers towards you" % (core.num(need), core.num(need - dist)))
        self.assertEqual(field(out, "VERDICT"), "NO: %s m needed, 600 m in view" % core.num(need))
        self.assertTrue(field(ok("overtake", "--speed", "80", "--to", "100", "--accel", "1.5", "--len", "4.5", "--other-len", "16.5",
                                 "--oncoming", "90", "--see", "1200"), "VERDICT").startswith("bare: "))
        self.assertTrue(field(ok("overtake", "--speed", "80", "--to", "100", "--accel", "1.5", "--len", "4.5", "--other-len", "16.5",
                                 "--oncoming", "90", "--see", "1800"), "VERDICT").startswith("room: "))
        # a steady pass of something slower needs no acceleration
        out = ok("overtake", "--speed", "90", "--other", "70", "--len", "4.5", "--other-len", "12")
        steady = (2 * 25.0 + 12 + 4.5 + 2 * 70 / 3.6) / (20 / 3.6)
        self.assertEqual(field(out, "PASS"), "90 km/h past 70 km/h: %s s and %s m of road, from pulling out to back in lane [derived]" % (
            core.trim(steady, 1), core.num(25.0 * steady)))
        self.assertNotIn("PACE", out)
        # hard acceleration can finish the pass before the target speed
        out = ok("overtake", "--speed", "90", "--to", "250", "--other-len", "5", "--firn")
        self.assertIn("at 8.68 m/s2 [sheet: the average over his 0-100 km/h in 3.2 s]: back in lane before reaching 250", field(out, "PACE"))
        self.assertIn("your 4.85 m", field(out, "GAIN"))
        for args, word in ((("overtake", "--speed", "80", "--other-len", "12", "--len", "4.5"), "you never get by"),
                           (("overtake", "--speed", "80", "--to", "100", "--other-len", "12", "--len", "4.5"), "give --accel"),
                           (("overtake", "--speed", "80", "--to", "100", "--accel", "1", "--other-len", "12"), "give --len"),
                           (("overtake", "--speed", "80", "--to", "60", "--accel", "1", "--other-len", "12", "--len", "4"), "not below --speed")):
            code, _, err = run(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn(word, err, args)

    def test_mileage(self):
        a, b = geo.parse_point("tychy"), geo.parse_point("krakow")
        there_and_back = geo.haversine_km(a[1], a[2], b[1], b[2]) * 1.25 * 2
        out = ok("mileage", "2026-12-01 | Tychy > Gliwice | 31.5 | work", "2026-11-03 | Tychy > Katowice | 18 | work",
                 "2026-11-05 | Tychy <> Krakow | | private", "--rate", "1.15", "--currency", "PLN", "--only", "work")
        trips = [line for line in out.splitlines() if line.startswith("TRIP ")]
        self.assertEqual(trips[0], "TRIP       2026-11-03 | Tychy > Katowice | 18 km | work")        # in date order
        self.assertTrue(trips[1].startswith("TRIP       2026-11-05 | Tychy <> Krak"))
        self.assertTrue(trips[1].endswith(" | ~%s km | private" % core.trim(there_and_back, 1)))
        self.assertEqual(trips[2], "TRIP       2026-12-01 | Tychy > Gliwice | 31.5 km | work")
        self.assertIn("MONTH      2026-11: %s km (private %s, work 18)" % (core.trim(there_and_back + 18, 1), core.trim(there_and_back, 1)), out)
        self.assertIn("MONTH      2026-12: 31.5 km (work 31.5)", out)
        self.assertEqual(field(out, "TOTAL"), "3 trips, %s km [1 estimated from the straight line: put the odometer's figure in]" % core.trim(
            there_and_back + 49.5, 1))
        self.assertEqual(field(out, "CLAIM"), "56.92 PLN [49.5 km of work x 1.15, rate as given]")
        self.assertIn("KEEP       the tools hold nothing between conversations", out)
        out = ok("mileage", "2026-11-03 | home > office | 12,5 km")
        self.assertIn("TRIP       2026-11-03 | home > office | 12.5 km | unsorted", out)
        self.assertNotIn("CLAIM", out)
        self.assertNotIn("BY PURPOSE", out)
        for args, word in ((("mileage", "Tychy > Katowice"), "a trip is 'DATE | FROM > TO | KM | PURPOSE'"),
                           (("mileage", "soon | Tychy > Katowice"), "not a date"),
                           (("mileage", "2026-11-03 | Tychy"), "names where from and where to"),
                           (("mileage", "2026-11-03 | Warsaw > Washington"), "no road from Warsaw to "),
                           (("mileage", "2026-11-03 | Tychy > Katowice | 18 | work", "--rate", "1", "--only", "play"), "no trip has the purpose 'play'")):
            code, _, err = run(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn(word, err, args)


class FieldTests(unittest.TestCase):
    """The hull at work: summon, intercept, the grapple, an escort, deep water, the spike. Every figure is the maker's."""

    def test_the_rulings_are_on_file(self):
        lore = core.load_data("lore")
        self.assertEqual((lore["spike"]["lock_s"], lore["spike"]["km"], lore["spike"]["again_s"]), (10, 10, 60))
        self.assertEqual((lore["grapple"]["line_m"], lore["grapple"]["pull_kg"]), (50, 3000))
        self.assertEqual(lore["ford"]["depth_m"], 1.5)
        for key in ("spike", "grapple", "ford", "unmanned", "recharge"):
            self.assertTrue(lore[key]["note"].startswith("[maker] "), key)
        fit = ok("record", "--fit")
        self.assertIn("FITTED     grapple [maker] - 50 m of line and a pull of 3 t, about his own weight; a hard pull costs range like a "
                      "climb; it cannot hold a powered armour", fit)
        self.assertIn("FITTED     wading to 1.5 m [maker] - bonnet-deep, crawling", fit)
        self.assertIn("FITTED     driving with nobody aboard [maker] - within the posted limits, lights on, not silent unless asked", fit)
        self.assertIn("it holds a lock for 10 s, costs 10 km of range, ends silent running, and needs a minute before the next", fit)
        self.assertIn("NOT FITTED amphibious or flight gear [sheet]", fit)
        self.assertIn("UNKNOWN    how much longer the Rime takes to re-cool after wading, and how fast he crawls in water - no figure", fit)
        for gone in ("grapple reach and strength", "what a signature spike costs"):
            self.assertNotIn(gone, fit)
        with open(os.path.join(ROOT, "src", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        for line in ("a grapple with 50 m of line and a pull of 3 t. You wade to 1.5 m, crawling, with your low cameras and lidar out "
                     "while you do. [maker]",
                     "The spike holds a lock for 10 s, costs 10 km of range, ends silent running, and needs a minute before the next "
                     "[maker]. The other three have no figure yet.",
                     "Nobody aboard. [maker] You keep the posted limits, lights on, and do not run silent unless asked. Faster only when "
                     "the driver calls it urgent, and you say so."):
            self.assertIn(line, skill)

    def test_spike_on_the_ledger(self):
        out = ok("lattice", "silent=on", "spike", "wait=20", "spike", "wait=45", "spike")
        self.assertIn("SILENT     ended: a spike is a shout on every band", out)
        self.assertIn("SPIKE      fired at t=0:00.0: it holds their lock until t=0:10.0; -10 km: range 1,500.0 -> 1,490.0 km; ready again "
                      "at t=1:00.0 [lore]", out)
        self.assertIn("SPIKE      REFUSED: the last one fired at t=0:00.0 and the next is not ready before t=1:00.0", out)
        self.assertIn("SPIKE      fired at t=1:05.0: it holds their lock until t=1:15.0; -10 km: range 1,490.0 -> 1,480.0 km", out)
        state = field(out, "STATE")
        self.assertTrue(state.endswith("/spike=125"))
        # the wait for the next one travels in the state token, and drops out of it once served
        self.assertIn("SPIKE      REFUSED", ok("lattice", "--state", state, "wait=30", "spike"))
        later = ok("lattice", "--state", state, "wait=60", "spike")
        self.assertIn("SPIKE      fired at t=2:05.0", later)
        self.assertNotIn("spike=", field(ok("lattice", "--state", state, "wait=2m"), "STATE"))
        self.assertIn("SPIKE      REFUSED: a spike needs 10 km of range and 4.0 km is left", ok("lattice", "--km", "4", "spike"))
        code, _, err = run("lattice", "spike=3")
        self.assertNotEqual(code, 0)
        self.assertIn("spike takes no value", err)

    def test_summon(self):
        spot, to = ("spot", 50.2599, 19.0216, None), geo.parse_point("gliwice")
        km = geo.haversine_km(spot[1], spot[2], to[1], to[2]) * 1.35
        out = ok("summon", "--spot", "50.2599,19.0216", "--to", "gliwice")
        self.assertTrue(field(out, "SUMMON").startswith("the parked spot -> Gliwice: "))
        self.assertTrue(field(out, "SUMMON").endswith(", ~%s km by road [estimate: straight line x 1.35]" % core.num(km, 1)))
        self.assertEqual(field(out, "ETA"), "%s at 30 km/h average [city mode]: within the posted limits [lore]" % core.fmt_hm(km / 30.0))
        self.assertEqual(field(out, "RANGE"), "%s km of 1,500 km [lore] -> %s km left" % (core.num(km, 1), core.num(1500 - km)))
        self.assertEqual(field(out, "RUNNING"), "lights on, not silent: an empty car that behaves [lore]")
        self.assertEqual(field(out, "RULE"), "[maker] With nobody aboard he keeps the posted limits, lights on, and does not run silent "
                         "unless asked. Faster only when the driver calls it urgent, and he says so.")
        self.assertIn("THERE      about 2026-11-10 ", out)
        out = ok("summon", "--spot", "50.2599,19.0216", "--to", "gliwice", "--urgent", "--speed", "140", "--silent", "--range-left", "200")
        secs = km / 140.0 * 3600
        self.assertEqual(field(out, "ETA"), "%dm%02ds at 140 km/h average: URGENT, above the posted limits on the driver's word, and he "
                         "says so [lore]" % (secs // 60, round(secs % 60)))
        self.assertTrue(field(out, "RUNNING").startswith("silent, as asked: "))
        self.assertEqual(field(out, "RANGE"), "%s km of 200 km [as given] -> %s km left" % (core.num(km, 1), core.num(200 - km)))
        # water between: he cannot come
        out = ok("summon", "--spot", "51.5,-0.12", "--to", "paris")
        self.assertIn("He does not fly, and whether he boards a ferry with nobody aboard has no ruling: he cannot come to you. "
                      "Go to him: park --find", field(out, "NO ROAD"))
        self.assertNotIn("ETA", out)
        for args, word in ((("summon", "--spot", "50.26,19.02", "--to", "gliwice", "--speed", "90"), "--speed belongs to --urgent"),
                           (("summon", "--spot", "50.26,19.02", "--to", "gliwice", "--urgent"), "--urgent needs --speed"),
                           (("summon", "--spot", "50.26,19.02", "--to", "gliwice", "--urgent", "--speed", "300"), "no more than his governor, 250")):
            code, _, err = run(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn(word, err, args)

    def test_intercept(self):
        out = ok("intercept", "--gap", "1.5", "--target", "110", "--speed", "180")
        self.assertEqual(field(out, "CATCH"), "in 1m17s: he covers 3.9 km and it covers 2.4 km, closing at 70 km/h [derived: steady speeds]")
        self.assertEqual(field(out, "RANGE"), "3.9 km of 1,500 km [lore] -> 1,496 km left")
        self.assertIn("RULE       catching is not stopping.", out)
        out = ok("intercept", "--gap", "4", "--target", "130", "--speed", "200", "--before", "6")
        self.assertEqual(field(out, "TOO LATE"), "it has 6 km left and he needs 7.4 km of its road to close the gap")
        self.assertEqual(field(out, "NEEDS"), "217 km/h to catch it on the line")      # 130 x (1 + 4/6)
        self.assertEqual(field(ok("intercept", "--gap", "4", "--target", "130", "--speed", "200", "--before", "12"), "IN TIME"),
                         "4.6 km before it gets there")
        self.assertIn("more than his governor allows, so not by chasing",
                      field(ok("intercept", "--gap", "4", "--target", "200", "--speed", "240", "--before", "10"), "NEEDS"))
        out = ok("intercept", "--gap", "2", "--target", "200", "--speed", "150")
        self.assertEqual(field(out, "NEVER"), "at 150 km/h he gains nothing on something doing 200: the gap stays 2 km or grows")
        self.assertNotIn("RANGE", out)
        out = ok("intercept", "--junction", "12", "9", "--target", "90", "--speed", "140")
        self.assertEqual(field(out, "CUT OFF"), "he is at the junction 51.4 s before it: there in 5m09s, it in 6m00s [derived: steady speeds]")
        out = ok("intercept", "--junction", "12", "9", "--target", "90", "--speed", "100")
        self.assertTrue(field(out, "TOO LATE").startswith("it is through the junction 1m12s before him"))
        self.assertEqual(field(out, "NEEDS"), "120 km/h to be level with it there")
        for args, word in ((("intercept", "--target", "100", "--speed", "150"), "give --gap"),
                           (("intercept", "--gap", "1", "--junction", "3", "2", "--target", "100", "--speed", "150"), "one of them"),
                           (("intercept", "--gap", "1", "--target", "100", "--speed", "260"), "his governor, 250 km/h [maker]")):
            code, _, err = run(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn(word, err, args)

    def test_grapple(self):
        need = 1800 * (math.sin(math.radians(20)) + 0.3 * math.cos(math.radians(20)))
        out = ok("grapple", "--mass", "1800", "--slope", "20", "--resist", "0.3", "--distance", "22", "--pull-m", "15")
        self.assertEqual(field(out, "LOAD"), "1,800 kg on 20 deg, the ground holding it with 0.3 of its weight -> a pull of %s kg [derived]" % core.num(need))
        self.assertEqual(field(out, "HOLDS"), "%s kg of the 3,000 kg he pulls [lore]: %s%% of it" % (core.num(need), core.trim(need / 30.0, 0)))
        self.assertEqual(field(out, "REACH"), "22 m of the 50 m of line [lore]")
        cost = need * 9.80665 * 15 / 3.6e6 / (400 / 1500.0)
        self.assertEqual(field(out, "COST"), "%s km of range for 15 m of pull [derived: the work of the pull against the bank, as a climb "
                         "would cost]" % core.trim(cost, 2))
        self.assertIn("it cannot hold a powered armour [lore]", field(out, "RULES"))
        out = ok("grapple", "--mass", "5000", "--slope", "90", "--distance", "70")
        self.assertEqual(field(out, "TOO MUCH"), "5,000 kg against the 3,000 kg he pulls [lore]. On this slope and ground the most he moves is 3,000 kg")
        self.assertEqual(field(out, "REACH"), "OUT OF REACH: 70 m, and the line is 50 m [lore]. Close in by 20 m")
        out = ok("grapple", "--self", "--load", "260", "--slope", "35", "--resist", "0.2")
        self.assertTrue(field(out, "LOAD").startswith("3,200 kg (his kerb mass + 260 kg aboard) on 35 deg"))
        self.assertIn("HOLDS", out)
        self.assertEqual(field(ok("grapple", "--mass", "3000", "--slope", "90"), "HOLDS"), "3,000 kg of the 3,000 kg he pulls [lore]: 100% of it")
        for args, word in ((("grapple", "--slope", "10"), "give --mass"), (("grapple", "--self", "--mass", "900"), "leave out --mass"),
                           (("grapple", "--mass", "900", "--slope", "120"), "0 (level) to 90")):
            code, _, err = run(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn(word, err, args)

    def test_escort(self):
        out = ok("escort", "--distance", "200")
        self.assertEqual(field(out, "ESCORT"), "2m30s with the hull between them and the threat [200 m at 4.8 km/h, route's walking average]")
        self.assertEqual(field(out, "SHELTER"), "side-on he is 4.85 m long and 1.72 m high; nose-on, 1.98 m wide [sheet]")
        self.assertEqual(field(out, "VEIL"), "over the left face, 7.5 km a minute: 18.8 km for the 2m30s it is up [lore]")
        self.assertEqual(field(out, "EMITTERS"), "37.5 s of heat by the end, of 180 s: they hold [lore]")
        self.assertEqual(field(out, "RANGE"), "18.8 km of 1,500 km [lore] -> 1,481 km left")
        self.assertEqual(field(out, "LEDGER"), "book it in a sim with: lattice --state ... veil=partial:left wait=150 veil=off")
        # the ledger agrees with the sum
        booked = ok("lattice", "veil=partial:left", "wait=150", "veil=off")
        self.assertIn("range 1,481.2 km", field(booked, "LEDGER"))
        # one face holds twelve minutes from cold, as the canon says; with heat already on, less
        self.assertIn("they hold", field(ok("escort", "--minutes", "12"), "EMITTERS"))
        out = ok("escort", "--minutes", "15", "--heat", "60", "--face", "right")
        self.assertEqual(field(out, "VEIL"), "over the right face, 7.5 km a minute: 60 km for the 8m00s it is up [lore]")
        self.assertEqual(field(out, "EMITTERS"), "they trip after 8m00s: the last 7m00s is on the armour alone, and the Veil stays down until "
                         "they are cool [lore]")
        out = ok("escort", "--minutes", "8", "--veil", "full")
        self.assertEqual(field(out, "VEIL"), "full, 30 km a minute: 90 km for the 3m00s it is up [lore]")
        out = ok("escort", "--minutes", "4", "--veil", "off")
        self.assertEqual(field(out, "VEIL"), "down: the Scales and the Rime take what comes, and it costs no range [lore]")
        self.assertNotIn("RANGE", out)
        code, _, err = run("escort", "--distance", "100", "--minutes", "2")
        self.assertNotEqual(code, 0)
        self.assertIn("one of them", err)

    def test_ford(self):
        out = ok("ford", "--depth", "1.4", "--width", "60", "--kmh", "4")
        self.assertEqual(field(out, "WADES"), "1.4 m of the 1.5 m he wades [lore]: bonnet-deep, crawling")
        self.assertEqual(field(out, "CELL"), "the water stands 1.12 m above his floor at full ride height (280 mm): the cell is sealed, "
                         "the cabin stays dry [lore]")
        self.assertTrue(field(out, "SENSES").startswith("cameras and lidar low on the body are out while he is in it [lore]"))
        self.assertEqual(field(out, "AFTER"), "the Rime takes longer to re-cool afterwards [lore]: how much longer has no figure, so the driver rules")
        self.assertEqual(field(out, "ACROSS"), "60 m in 54 s at 4 km/h [as given]")
        self.assertIn("WADES      1.5 m of the 1.5 m he wades", ok("ford", "--depth", "1.5"))
        self.assertEqual(field(ok("ford", "--depth", "0.9", "--width", "30"), "ACROSS"),
                         "30 m: give --kmh for the time. His crawling pace in water has no figure")
        out = ok("ford", "--depth", "1.51")
        self.assertEqual(field(out, "REFUSED"), "1.51 m is deeper than the 1.5 m he wades [lore], and amphibious gear is not fitted [sheet]")
        self.assertIn("OFFER      another crossing; or, for a narrow channel, a jump: jump --gap WIDTH", out)
        self.assertNotIn("WADES", out)
        out = ok("ford", "--depth", "0.2")
        self.assertEqual(field(out, "SHALLOW"), "0.2 m stays under his floor at full ride height (280 mm): he drives through, and nothing "
                         "on file is spent")
        for key in ("WADES", "SENSES", "AFTER"):
            self.assertNotIn(key, out)


class PackageTests(unittest.TestCase):

    def test_private_build_packs_its_history_beside_the_core(self):
        """An overlay's HISTORY.md ships in the package, so the record is kept without SKILL.md carrying it."""
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        try:
            import build
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as d:
            overlay, stage = os.path.join(d, "overlay"), os.path.join(d, "stage")
            os.makedirs(overlay)
            shutil.copy(os.path.join(ROOT, "tests", "personal.test.json"), os.path.join(overlay, "personal.json"))
            with open(os.path.join(overlay, "HISTORY.md"), "w", encoding="utf-8") as f:
                f.write("# history\n\n- 9.9.9: a line [maker]\n")
            with open(os.path.join(overlay, "build.json"), "w", encoding="utf-8") as f:
                f.write('{"tag": "ada"}')
            with open(os.path.join(overlay, "notes-for-me.md"), "w", encoding="utf-8") as f:
                f.write("not for the package\n")
            build.stage_private(overlay, stage)
            with open(os.path.join(stage, "HISTORY.md"), encoding="utf-8") as f:
                self.assertIn("- 9.9.9: a line [ada]", f.read())
            self.assertFalse(os.path.exists(os.path.join(stage, "notes-for-me.md")))
            self.assertTrue(os.path.exists(os.path.join(stage, "SKILL.md")))
    def test_every_example_in_the_help_runs(self):
        firn.build_parser()
        needs_file = 0
        for group, name, summary, examples in list(core.REGISTRY):
            self.assertTrue(summary and not summary.endswith(".") and len(summary) <= 125, name)
            self.assertTrue(examples, "%s has no examples" % name)
            for ex in examples:
                if "F2/..." in ex or "B1/..." in ex or re.search(r"\b(reply\.txt|draft\.txt|vehicle\.lsl)\b", ex):
                    needs_file += 1
                    continue
                code, out, err = run(*shlex.split(ex))
                self.assertEqual(code, 0, "example failed: firn.py %s\n%s%s" % (ex, out, err))
                self.assertTrue(out.strip(), ex)
        self.assertLessEqual(needs_file, 11)

    def test_output_obeys_the_typography_rule(self):
        samples = [("boot", "--seed", "1"), ("route", "krakow", "warsaw", "--depart", "2026-11-12 07:00", "--firn"), ("sun", "warsaw"),
                   ("moon", "warsaw"), ("perf", "--firn"), ("lattice", "veil=full", "wait=30", "hit=front:heavy"), ("record", "--fit"),
                   ("scenario", "--seed", "1"), ("stop", "--from", "50", "--table"), ("tools",), ("lights", "--colour", "red"),
                   ("dst", "warsaw", "slt"), ("triage", "a: x=lost", "b: y=repair"), ("places", "--kind", "airport", "--limit", "400"),
                   ("places", "--kind", "capital", "--limit", "300"), ("lsl", "caveats"), ("checklist", "airport"),
                   ("armour", "120", "45", "--shell", "ap", "--caliber", "105", "--pen", "225"), ("lsl", "skeleton"),
                   ("service",), ("service", "--template"), ("load", "--payload", "520", "--people", "2x80", "--cargo", "350", "--nose", "70"),
                   ("tow", "--trailer", "1700", "--limit", "1500", "--kerb", "1650", "--nose", "60"),
                   ("fit", "--space", "1800x1000x700", "--item", "europallet", "--item", "1900x150x100", "--long", "2100"),
                   ("compare", "firn", "Heron: hp=148, kg=1340, 0-100=9.4, tank=45, l100=5.8")]
        for args in samples:
            self.assertEqual(desk.check_text(ok(*args)), [], args)

    def test_sources_are_plain_ascii(self):
        for root in (SCRIPTS, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tests")):
            for folder, _, files in os.walk(root):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(folder, f), "rb") as fh:
                            data = fh.read()
                        self.assertTrue(all(b < 128 for b in data), "%s has non-ASCII bytes" % f)
                        self.assertNotIn(b"\t", data, f)

    def test_data_files(self):
        for name in ("zones", "lore", "scenarios", "obd", "lights", "lsl", "rulesets", "checklists", "arms", "countries", "landmasses", "airports", "commands"):
            self.assertTrue(core.load_data(name), name)
        self.assertTrue(os.path.isfile(os.path.join(SCRIPTS, "data", "places.db")))
        self.assertFalse(os.path.exists(os.path.join(SCRIPTS, "data", "places.json")), "the old gazetteer is still in the package")
        lore = core.load_data("lore")
        self.assertEqual(set(lore["chassis"]), set(lore["chassis_tags"]))
        self.assertEqual(set(lore["lattice"]), set(lore["lattice_tags"]))
        self.assertEqual(len(lore["bar"]), 13)
        for key in ("family", "first_boot", "ignition_pool", "home"):
            self.assertNotIn(key, lore, "personal data belongs in personal.json, not lore.json")

    def test_broken_pipe_is_quiet(self):
        class Closed(io.StringIO):
            def write(self, s):
                raise BrokenPipeError()
        err = io.StringIO()
        with contextlib.redirect_stdout(Closed()), contextlib.redirect_stderr(err):
            code = firn.main(["tools"])
            self.assertEqual(getattr(sys.stdout, "name", None), os.devnull)
            sys.stdout.close()          # main() left stdout on the null device; in a test nothing else closes it
        sys.stdout = sys.__stdout__
        self.assertEqual(code, 0)
        self.assertEqual(err.getvalue(), "")


class IndexTests(unittest.TestCase):
    def test_the_index_on_file_is_what_the_commands_say(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        try:
            import build_index
        finally:
            sys.path.pop(0)
        self.assertEqual(build_index.current(), build_index.render(SCRIPTS), "run  python tools/build_index.py")

    def test_every_command_has_a_module_and_everyday_words(self):
        data = index.load()
        names = [c["name"] for c in data["commands"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(index.ALSO), set(names))
        self.assertEqual(index.module_of("time"), "chrono")
        self.assertEqual(index.module_of("tools"), "index")
        self.assertEqual(index.module_of("playlist"), "sound")
        self.assertIsNone(index.module_of("no_such_command"))
        for c in data["commands"]:
            self.assertIn(c["module"], firnlib.MODULES, c["name"])
            self.assertIn(c["group"], [g for g, _ in core.GROUPS], c["name"])

    def test_a_call_loads_only_the_module_it_needs(self):
        code = ("import sys; sys.path.insert(0, %r); import firn; firn.main(['roll', '3d6', '--seed', '1']); "
                "print('LOADED', ' '.join(sorted(m for m in sys.modules if m.startswith('firnlib.'))))" % SCRIPTS)
        out = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        loaded = out.stdout.split("LOADED ")[1].split()
        self.assertEqual(loaded, ["firnlib.core", "firnlib.dice", "firnlib.index"])

    def test_a_missing_index_only_costs_time(self):
        kept, path = index._index, index.INDEX_FILE
        try:
            index._index, index.INDEX_FILE = None, os.path.join(OUTPUTS, "no-such-index.json")
            rebuilt = index.load()
            self.assertEqual([c["name"] for c in rebuilt["commands"]], [c["name"] for c in kept["commands"]])
            self.assertEqual(index.module_of("route"), "geo")
            self.assertIn("LEG 1", ok("route", "krakow", "warsaw"))
        finally:
            index._index, index.INDEX_FILE = kept, path

    def test_an_unknown_command_is_an_ordinary_error(self):
        code, out, err = run("frobnicate")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_find(self):
        out = ok("tools", "--find", "towing", "a", "caravan")
        self.assertIn('FIND       "towing a caravan": 1 command', out)
        self.assertEqual(out.splitlines()[1].split()[0], "tow")
        self.assertIn("firn.py tow --trailer", out)
        self.assertIn('READ       playbooks/garage.md', out)
        for question, first in (("fault code", "obd"), ("when is sunset", "sun"), ("how far on a charge", "ev"),
                                ("what time is it in tokyo", "time"), ("will the sofa fit in the boot", "fit"),
                                ("pit stop strategy", "stint"), ("meet in the middle", "halfway"), ("is it icy", "weather"),
                                ("what side do they drive on in japan", "country"), ("how loud is safe", "listen"),
                                ("what note is the engine", "pitch"), ("how heavy is an oak table", "weigh"),
                                ("size of a thing in a photo", "measure"), ("what can his sensors see", "scan"),
                                ("music that ends when we arrive", "playlist"), ("bass boom in the car", "cabin")):
            got = ok("tools", "--find", *question.split()).splitlines()[1].split()[0]
            self.assertEqual(got, first, question)
        self.assertIn("no command answers that", ok("tools", "--find", "zzzzqq"))
        self.assertEqual(len([ln for ln in ok("tools", "--find", "time", "--limit", "1").splitlines() if ln.startswith("   ") is False
                              and not ln.startswith(("FIND", "READ", "NEXT"))]), 1)
        self.assertEqual(run("tools", "--find", "time", "--limit", "0")[0], 2)

    def test_compiled_files_go_to_the_temp_folder_only_when_the_skill_is_read_only(self):
        kept = (sys.dont_write_bytecode, sys.pycache_prefix, os.access, dict(os.environ))
        try:
            sys.pycache_prefix = None
            sys.dont_write_bytecode = True
            self.assertIsNone(firn.cache_elsewhere(SCRIPTS))            # Python was told not to write them
            sys.dont_write_bytecode = False
            self.assertIsNone(firn.cache_elsewhere(SCRIPTS))            # the folder can be written to: leave Python alone
            self.assertIsNone(sys.pycache_prefix)
            os.access = lambda path, mode: False
            for name in ("TMPDIR", "TEMP", "TMP"):
                os.environ[name] = OUTPUTS
            os.environ["FIRN_NO_CACHE"] = "1"
            self.assertIsNone(firn.cache_elsewhere(SCRIPTS))
            del os.environ["FIRN_NO_CACHE"]
            path = firn.cache_elsewhere(SCRIPTS)
            self.assertTrue(path and os.path.isdir(path) and os.path.dirname(path) == OUTPUTS, path)
            self.assertEqual(sys.pycache_prefix, path)
            self.assertIsNone(firn.cache_elsewhere(SCRIPTS))            # already set: not ours to change
        finally:
            sys.dont_write_bytecode, sys.pycache_prefix, os.access = kept[0], kept[1], kept[2]
            os.environ.clear()
            os.environ.update(kept[3])


class SoundTests(unittest.TestCase):
    def test_notes(self):
        self.assertEqual(sound.note_of(440.0), ("A4", 0))
        self.assertEqual(sound.note_of(261.63)[0], "C4")
        self.assertEqual(sound.note_of(100.0), ("G2", 35))
        self.assertAlmostEqual(sound.hz_of("A4"), 440.0)
        self.assertAlmostEqual(sound.hz_of("C4"), 261.6256, places=3)
        self.assertAlmostEqual(sound.hz_of("a3"), 220.0)
        self.assertAlmostEqual(sound.hz_of("Bb3"), sound.hz_of("A#3"))
        self.assertAlmostEqual(sound.hz_of("B#3"), sound.hz_of("C4"))
        self.assertAlmostEqual(sound.hz_of("Cb4"), sound.hz_of("B3"))
        self.assertAlmostEqual(sound.hz_of("A4", 432.0), 432.0)
        self.assertIsNone(sound.hz_of("H4"))
        self.assertIsNone(sound.hz_of("440"))
        for hz in (27.5, 55.0, 82.41, 440.0, 1000.0, 4186.0):
            name, cents = sound.note_of(hz)
            self.assertLessEqual(abs(cents), 50)
            self.assertAlmostEqual(sound.hz_of(name) * 2.0 ** (cents / 1200.0), hz, delta=hz * 0.004)
        self.assertEqual(sound.interval_text(7.02), "a fifth")
        self.assertEqual(sound.interval_text(-12), "an octave")
        self.assertEqual(sound.interval_text(15.1), "an octave and a minor third")
        self.assertAlmostEqual(sound.speed_of_sound(20.0), 343.2, delta=0.2)
        self.assertAlmostEqual(sound.speed_of_sound(0.0), 331.3, delta=0.01)

    def test_pitch(self):
        self.assertIn("PITCH      440 Hz is A4; one wave is 0.78 m long", ok("pitch", "440"))
        out = ok("pitch", "A4", "E5")
        self.assertIn("659.3 Hz is E5", out)
        self.assertIn("INTERVAL   7 semitones up, about a fifth; ratio 1.498", out)
        out = ok("pitch", "--rpm", "3000", "--cyl", "4")
        self.assertIn("FIRING     3,000 rpm: 100 Hz, G2 +35 cents [derived: rpm / 60 x cylinders / 2]", out)
        self.assertIn("the crankshaft itself turns at 50 Hz", out)
        self.assertIn("3,000 rpm: 200 Hz", ok("pitch", "--rpm", "3000", "--cyl", "4", "--stroke", "2"))
        out = ok("pitch", "--rpm", "6500", "4800", "--cyl", "6")
        self.assertIn("STEP       6,500 rpm to 4,800: the note falls 5.2 semitones, about a fourth", out)
        self.assertIn("REVS       1,236 rpm sings it: 8 cylinders, four-stroke", ok("pitch", "--note", "E2", "--cyl", "8"))
        out = ok("pitch", "--rpm", "12000", "--order", "4")
        self.assertIn("SINGS      12,000 rpm: 800 Hz", out)
        self.assertNotIn("firing note", out)
        self.assertIn("TUNING     A4 = 432 Hz", ok("pitch", "A4", "--a4", "432"))
        for bad in (["pitch"], ["pitch", "H4"], ["pitch", "--rpm", "3000"], ["pitch", "440", "--rpm", "3000", "--cyl", "4"],
                    ["pitch", "1", "2", "3"], ["pitch", "--rpm", "3000", "--cyl", "4", "--stroke", "3"], ["pitch", "0.5"]):
            self.assertEqual(run(*bad)[0], 2, bad)

    def test_doppler_runs_both_ways(self):
        out = ok("doppler", "--speed", "90", "--hz", "440")
        coming = float(re.search(r"COMING\s+([\d.]+) Hz", out).group(1))
        going = float(re.search(r"GOING\s+([\d.]+) Hz", out).group(1))
        self.assertAlmostEqual(coming, 440.0 * 343.2 / (343.2 - 25.0), delta=0.1)
        self.assertAlmostEqual(going, 440.0 * 343.2 / (343.2 + 25.0), delta=0.1)
        back = ok("doppler", "--heard", str(coming), str(going))
        self.assertIn("SPEED      90 km/h", back)
        self.assertIn("SOURCE     440 Hz as it was made, A4", back)
        out = ok("doppler", "--drop", "3")
        self.assertIn("SPEED      107 km/h (29.7 m/s) [derived; sound at 343 m/s in air at 20 C]", out)
        self.assertIn("BAND       89 to 124 km/h if the ear is half a semitone out either way", out)
        self.assertIn("never a measurement of anyone's speed", out)
        self.assertEqual(field(ok("doppler", "--drop", "minor-third"), "SPEED"), field(out, "SPEED"))
        self.assertIn("SPEED      103 km/h", ok("doppler", "--drop", "3", "--temp", "0"))           # colder air, slower sound
        self.assertNotIn("BAND", ok("doppler", "--drop", "3", "--ear", "0"))
        for bad in (["doppler"], ["doppler", "--heard", "400", "480"], ["doppler", "--drop", "0"], ["doppler", "--drop", "nonsense"],
                    ["doppler", "--drop", "3", "--speed", "90"], ["doppler", "--speed", "2000"]):
            self.assertEqual(run(*bad)[0], 2, bad)

    def test_the_picker_finds_the_best_total(self):
        rng = random.Random(11)
        for _ in range(60):
            lengths = [rng.randint(1, 400) for _ in range(rng.randint(1, 11))]
            target = rng.randint(1, 1500)
            best = max(s for r in range(len(lengths) + 1) for combo in itertools.combinations(lengths, r)
                       for s in [sum(combo)] if s <= target)
            chosen, total = sound.pick_tracks(lengths, target)
            self.assertEqual(total, best, (lengths, target))
            self.assertEqual(sum(lengths[i] for i in chosen), total)
            self.assertEqual(chosen, sorted(set(chosen)))
        self.assertEqual(sound.pick_tracks([100, 100, 100], 200), ([0, 1], 200))        # equal totals: the earlier tracks stay
        self.assertEqual(sound.pick_tracks([500], 100), ([], 0))
        self.assertEqual(sound.pick_tracks([], 100), ([], 0))

    def test_playlist(self):
        out = ok("playlist", "3:45", "4:10", "2:58", "5:02", "3:30", "4:44", "6:15", "3:05", "--for", "20m")
        self.assertIn("JOURNEY    20m00s to fill (as given)", out)
        self.assertIn("PLAYLIST   5 of 8 tracks, 19m59s of music", out)
        self.assertIn("ENDS       as you arrive, if the first track starts 1 s after you set off", out)
        self.assertIn("LEFT OUT   3: track 2, track 7, track 8", out)
        out = ok("playlist", "A=5:00", "B=5:00", "C=5:00", "--for", "10m")
        self.assertIn("ENDS       as you arrive, to the second: press play as you set off", out)
        self.assertIn("LEFT OUT   1: C", out)
        out = ok("playlist", "Opener=3:45", "Long one=9:12", "Finale=5:02", "4:10", "2:58", "3:30", "--for", "18m", "--last", "finale")
        rows = [ln for ln in out.splitlines() if re.match(r"^\s+\d+\s", ln)]
        self.assertTrue(rows[-1].endswith("Finale"), rows)
        out = ok("playlist", "Opener=3:45", "4:10", "Finale=5:02", "--for", "15m", "--first", "3", "--last", "1")
        rows = [ln for ln in out.splitlines() if re.match(r"^\s+\d+\s", ln)]
        self.assertTrue(rows[0].endswith("Finale") and rows[-1].endswith("Opener"), rows)
        out = ok("playlist", "3:45", "4:10", "2:58", "5:02", "--for", "12m", "--all", "--gap", "2")
        self.assertIn("16m01s of music with 2 s between tracks", out)
        self.assertIn("ENDS       4m01s after you arrive: you get there 1:01 into track 4 (5:02 long)", out)
        self.assertIn("ENDS       2m00s before you arrive", ok("playlist", "5:00", "5:00", "--for", "12m", "--all"))
        out = ok("playlist", "3:45", "4:10", "2:58", "--route", "krakow", "katowice", "--depart", "2026-11-14 08:00")
        self.assertIn("JOURNEY    1h06m to fill (Krak", out)
        self.assertIn("[estimate])", out)
        self.assertIn("ARRIVE     2026-11-14 09:05", out)
        self.assertIn("every track together is 10m53s, which is 55m06s short of the journey", out)
        out = ok("playlist", "3:00", "3:00", "--depart", "2026-11-14 08:00", "--arrive", "2026-11-14 08:06")
        self.assertIn("  1  08:00:00", out)
        self.assertIn("  2  08:03:00", out)
        path = os.path.join(OUTPUTS, "tracks.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# my list\nFirst song - 3:45\nSecond song\t4:10\n\n225s\n")
        out = ok("playlist", "--file", path, "--for", "8m")
        self.assertIn("First song", out)
        self.assertIn("Second song", out)
        self.assertIn("PLAYLIST   2 of 3 tracks, 7m55s of music", out)
        self.assertIn("nothing fits", ok("playlist", "9:00", "--for", "5m"))
        for bad in (["playlist", "--for", "10m"], ["playlist", "3:45"], ["playlist", "abc", "--for", "10m"],
                    ["playlist", "3:45", "--for", "10m", "--route", "krakow", "warsaw"], ["playlist", "3:45", "--for", "10m", "--last", "zz"],
                    ["playlist", "3:45", "4:00", "--for", "10m", "--first", "1", "--last", "1"],
                    ["playlist", "9:00", "8:00", "--for", "10m", "--first", "1", "--last", "2"]):
            self.assertEqual(run(*bad)[0], 2, bad)

    def test_listen(self):
        out = ok("listen", "85")
        self.assertIn("DAY        8h00m at this level uses one day's allowance [NIOSH: 85 dB(A) for 8 h, halved for every 3 dB more]", out)
        self.assertIn("WEEK       12h39m uses one week's [WHO-ITU H.870: 80 dB(A) for 40 h a week]", out)
        self.assertIn("DAY        4h00m", ok("listen", "88"))
        self.assertIn("DAY        15m00s", ok("listen", "100"))
        self.assertIn("WEEK       1d16h uses one week's", ok("listen", "80"))
        self.assertIn("WEEK       1d16h uses one week's [WHO-ITU H.870: 75 dB(A)", ok("listen", "75", "--sensitive"))
        out = ok("listen", "94:1h")
        self.assertIn("DAY        100% of one day's allowance [", out)
        out = ok("listen", "85:2h", "94:30m", "100:10m")
        self.assertIn("DAY        142% of one day's allowance: OVER", out)
        self.assertIn("spread over a working day of 8 h this comes to 86.5 dB(A), which is at or above the upper action value of 85", out)
        self.assertIn("a day like it every day would be", out)
        self.assertNotIn("every day", ok("listen", "85:2h", "--week"))
        self.assertIn("not above the lower action value of 80", ok("listen", "80"))
        self.assertIn("above the lower action value of 80", ok("listen", "82"))
        self.assertIn("above the limit value of 87", ok("listen", "90"))
        out = ok("listen", "--for", "8h")
        self.assertIn("DAY        85 dB(A) or less for that long", out)
        self.assertIn("DAY        88 dB(A) or less", ok("listen", "--for", "4h"))
        self.assertIn("WEEK       80 dB(A) or less", ok("listen", "--for", "40h"))
        for bad in (["listen"], ["listen", "loud"], ["listen", "200"], ["listen", "85", "94:30m"], ["listen", "85:2h", "--for", "2h"],
                    ["listen", "85:0m"]):
            self.assertEqual(run(*bad)[0], 2, bad)

    def test_cabin(self):
        out = ok("cabin", "2.6x1.5x1.2")
        self.assertIn("CABIN      2.6 x 1.5 x 1.2 m inside, 4.68 m3; sound at 343 m/s in air at 20 C", out)
        rows = [ln for ln in out.splitlines() if ln.strip().endswith(("strongest", "weaker"))]
        self.assertEqual(len(rows), 8)
        self.assertIn("66 Hz  C2 +16 cents   along the length", rows[0])
        freqs = [float(r.split(" Hz")[0]) for r in rows]
        self.assertEqual(freqs, sorted(freqs))
        self.assertAlmostEqual(freqs[0], sound.speed_of_sound(20.0) / (2 * 2.6), delta=0.06)
        self.assertIn("LIFT       below about 66 Hz", out)
        self.assertEqual(ok("cabin", "260x150x120", "--unit", "cm"), out)
        self.assertEqual(len([ln for ln in ok("cabin", "2.6x1.5x1.2", "--modes", "12").splitlines()
                              if ln.strip().endswith(("strongest", "weaker"))]), 12)
        colder = ok("cabin", "2.6x1.5x1.2", "--temp", "-10")
        self.assertIn("62.53 Hz", colder)
        for bad in (["cabin", "2.6x1.5"], ["cabin", "big"], ["cabin", "0.01x1x1"], ["cabin", "2.6x1.5x1.2", "--modes", "0"]):
            self.assertEqual(run(*bad)[0], 2, bad)


class ThingsTests(unittest.TestCase):
    def test_the_material_table(self):
        data = core.load_data("materials")
        self.assertGreater(len(data["materials"]), 40)
        for key, m in data["materials"].items():
            self.assertEqual(key, core.fold(key))
            self.assertIn(m["kind"], data["kinds"], key)
            self.assertTrue(5 <= m["kg_m3"] <= 20000, key)
            self.assertEqual("low" in m, "high" in m, key)
            if "low" in m:
                self.assertTrue(m["low"] < m["kg_m3"] < m["high"] or m["low"] <= m["kg_m3"] <= m["high"], key)
                self.assertLess(m["low"], m["high"], key)
        self.assertEqual(data["materials"]["water"]["kg_m3"], 1000)
        self.assertEqual(data["materials"]["steel"]["kg_m3"], 7850)
        out = ok("weigh", "--list")
        self.assertIn("MATERIALS  %d, typical densities in kg/m3 [table]" % len(data["materials"]), out)

    def test_weigh_a_solid(self):
        out = ok("weigh", "box", "1200x800x600", "--material", "oak")
        self.assertIn("ITEM       box 1,200 x 800 x 600 mm; oak, air-dry, 720 kg/m3 (600 to 900) [table: typical]", out)
        self.assertIn("VOLUME     0.576 m3 (576 litres) [derived]", out)
        self.assertIn("MASS       415 kg (346 to 518) [derived]", out)
        self.assertIn("STANDS     600 mm tall; centre of gravity 300 mm up", out)
        self.assertIn("TIPS       over its long edge: 53 deg, or 1.33 g; over its short edge: 63 deg, or 2 g", out)
        self.assertIn("squat enough to stay upright", out)
        self.assertIn("HOLD       3,254 N forwards under braking, 2,034 N sideways", out)
        self.assertIn("as if dropped from 9.8 m", out)
        self.assertIn("LIFT       415 kg: above the highest of them; the reference masses for one person lifting in ideal conditions run from 15 to 25 kg by age and sex [ISO 11228-1]", out)
        self.assertIn("NEXT       load ... --cargo 415 | fit --space LxWxH --item 1200x800x600", out)
        self.assertEqual(ok("weigh", "box", "1.2x0.8x0.6", "--unit", "m", "--material", "oak"), out)
        self.assertIn("MASS       1,000 kg [derived]", ok("weigh", "box", "1x1x1", "--unit", "m", "--material", "water"))
        self.assertIn("MASS       38.2 kg (36.8 to 39.6)", ok("weigh", "sphere", "300", "--material", "granite"))
        self.assertIn("ROLLS      it has no flat to stand on:", ok("weigh", "sphere", "300", "--material", "granite"))
        out = ok("weigh", "volume", "80l", "--material", "gravel")
        self.assertIn("MASS       136 kg (120 to 148)", out)
        self.assertNotIn("TIPS", out)
        self.assertIn("MASS       1,600 kg", ok("weigh", "volume", "1m3", "--material", "sand"))
        self.assertIn("MASS       62.8 kg [derived]", ok("weigh", "cylinder", "200x1000", "--density", "2000"))
        self.assertIn("TOGETHER   4 of them: 251 kg", ok("weigh", "cylinder", "200x1000", "--density", "2000", "--count", "4"))

    def test_weigh_hollow_things_and_what_is_in_them(self):
        out = ok("weigh", "cylinder", "580x880", "--wall", "1.2", "--material", "steel", "--fill", "diesel:80")
        self.assertIn("230 litres inside", out)
        self.assertIn("MASS       174 kg (170 to 175): 20 kg empty, 154 kg of diesel, 184 litres at 835 kg/m3, 80% full", out)
        self.assertIn("centre of gravity 362 mm up, pulled down by what is in it", out)
        self.assertIn("TIPS       any way: 39 deg, or 0.8 g", out)
        out = ok("weigh", "cylinder", "580x880", "--wall", "1.2", "--material", "steel", "--fill", "water:50", "--lying")
        self.assertIn("LIES       580 mm high; centre of gravity 186 mm up, pulled down by what is in it", out)
        self.assertIn("ROLLS      it has no flat to stand on across its length", out)
        self.assertNotIn("TIPS", out)
        depth, up = things.segment(0.5)
        self.assertAlmostEqual(depth, 0.5, places=6)
        self.assertAlmostEqual(up, 0.5 - 2.0 / (3.0 * math.pi), places=6)
        self.assertEqual(things.segment(1.0), (1.0, 0.5))
        last = (0.0, 0.0)
        for share in (0.05, 0.2, 0.4, 0.6, 0.8, 0.95):
            got = things.segment(share)
            self.assertTrue(got[0] > last[0] and got[1] > last[1] and got[1] < got[0], share)
            last = got
        out = ok("weigh", "tube", "60x3000", "--wall", "4", "--material", "steel", "--lying", "--count", "6")
        self.assertIn("MASS       16.6 kg [derived]", out)
        self.assertIn("TOGETHER   6 of them: 99.4 kg", out)
        self.assertIn("LIFT       16.6 kg: within them for some people and above them for others", out)
        self.assertIn("LIFT       3.06 kg: under all of them", ok("weigh", "box", "300x200x100", "--material", "pine"))
        self.assertIn("--item 3000x60x60:6", out)

    def test_weigh_when_the_mass_is_known(self):
        out = ok("weigh", "box", "60x40x180", "--unit", "cm", "--mass", "85", "--mu", "0.3")
        self.assertIn("MASS       85 kg [as given]", out)
        self.assertIn("TIPS       over its long edge: 13 deg, or 0.22 g; over its short edge: 18 deg, or 0.33 g", out)
        self.assertIn("top-heavy", out)
        self.assertIn("SLIDES     not before it tips", out)
        self.assertIn("SLIDES     at 0.1 g, before it would tip", ok("weigh", "box", "60x40x180", "--unit", "cm", "--mass", "85", "--mu", "0.1"))
        out = ok("weigh", "box", "1000x1000x1000", "--material", "oak", "--mass", "5000")
        self.assertIn("that makes it 5,000 kg/m3, where oak runs near 720", out)
        self.assertNotIn("that makes it", ok("weigh", "box", "1000x1000x1000", "--material", "oak", "--mass", "700"))
        for bad in (["weigh"], ["weigh", "box", "1x2"], ["weigh", "box", "1x2x3"], ["weigh", "pyramid", "1x2x3", "--material", "oak"],
                    ["weigh", "box", "1x2x3", "--material", "unobtainium"], ["weigh", "tube", "60x3000", "--material", "steel"],
                    ["weigh", "box", "100x100x100", "--material", "steel", "--fill", "water"],
                    ["weigh", "box", "100x100x100", "--material", "steel", "--wall", "60"],
                    ["weigh", "sphere", "300", "--wall", "5", "--material", "steel", "--fill", "water:50"],
                    ["weigh", "box", "100x100x100", "--material", "oak", "--lying"], ["weigh", "volume", "lots", "--material", "sand"]):
            self.assertEqual(run(*bad)[0], 2, bad)
        self.assertIn("Did you mean: brass", run("weigh", "box", "1x2x3", "--material", "bras")[2])

    def test_measure(self):
        out = ok("measure", "--ref", "card=212", "--px", "wheel=1630")
        self.assertIn("SCALE      a bank or ID card, long side: 85.6 mm over 212 in the picture, so 1 in the picture is 0.4038 mm", out)
        self.assertIn("WHEEL      1630 in the picture = 658 mm, give or take 6.3 mm [measured from the picture]", out)
        self.assertIn("same distance from the camera", out)
        rel = math.sqrt((2.0 / 212) ** 2 + (2.0 / 1630) ** 2)
        self.assertAlmostEqual(1630 * 85.6 / 212 * rel, 6.3, delta=0.05)
        out = ok("measure", "--ref", "2.0m=412", "--px", "opening=265", "roof height=300", "--err", "0")
        self.assertIn("OPENING    265 in the picture = 1.29 m [measured from the picture]", out)
        self.assertIn("ROOF HEIGHT 300 in the picture = 1.46 m", out)
        self.assertIn("520 mm over 96", ok("measure", "--ref", "plate-eu=96", "--px", "length=1010"))
        self.assertIn("520 mm over 96", ok("measure", "--ref", "Plate_EU=96", "--px", "length=1010"))
        refs = core.load_data("references")["references"]
        out = ok("measure", "--list")
        self.assertIn("OBJECTS    %d things of a standard size [table]" % len(refs), out)
        for key, r in refs.items():
            self.assertTrue(r["mm"] > 0 and r["is"] and r["source"], key)
            self.assertEqual(key, key.lower())
        self.assertAlmostEqual(refs["card"]["mm"] / refs["card-short"]["mm"], 85.6 / 53.98, places=6)
        for bad in (["measure"], ["measure", "--ref", "card=212"], ["measure", "--ref", "card", "--px", "a=1"],
                    ["measure", "--ref", "banana=212", "--px", "a=1"], ["measure", "--ref", "card=212", "--px", "a"],
                    ["measure", "--ref", "card=212", "--px", "a=0"], ["measure", "--ref", "card=212", "--px", "a=5", "--err", "-1"]):
            self.assertEqual(run(*bad)[0], 2, bad)
        self.assertIn("Did you mean: card", run("measure", "--ref", "crad=212", "--px", "a=1")[2])

    def test_analyse_keeps_seeing_and_guessing_apart(self):
        out = ok("analyse", "white panel van, parked", "--seen", "roof rack with a ladder", "sliding door on the near side",
                 "--measured", "length=5.4 m, scaled from the number plate", "--decoded", "215/65R16C=a load-rated van tyre",
                 "--inferred", "long wheelbase, high roof, so likely a 3.5 t van: medium", "--unknown", "what it carries", "who runs it")
        keys = [ln.split()[0] for ln in out.splitlines() if ln and not ln.startswith(" ")]
        self.assertEqual(keys, ["ANALYSIS", "SOURCE", "SEEN", "SEEN", "MEASURED", "DECODED", "INFERRED", "UNKNOWN", "RULE"])
        self.assertIn("SOURCE     a photograph supplied by Ada; examined, not sensed: no instrument of FIRN's was on it", out)
        self.assertIn("INFERRED   long wheelbase, high roof, so likely a 3.5 t van [medium confidence]", out)
        self.assertIn("never a way to name a person", out)
        self.assertEqual(desk.reply_findings(out + "[bar: sweep]", list(core.load_data("lore")["bar"])), [])
        out = ok("analyse", "warning light", "--source", "description", "--seen", "amber engine outline, steady",
                 "--inferred", "a fault that is not urgent: low", "--next", "the fault code, read with a scanner")
        self.assertIn("SOURCE     a description given by Ada", out)
        self.assertIn("UNKNOWN    nothing listed, and there is always something the source does not show", out)
        self.assertIn("TO SETTLE  the fault code, read with a scanner", out)
        self.assertIn("(1 of these at low confidence)", out)
        self.assertNotIn("number plate", out)
        out = ok("analyse", "contact on the ridge", "--source", "sim", "--seen", "one vehicle, halted")
        self.assertIn("SOURCE     the simulation's own sensors, as the brief and 'scan' allow", out)
        self.assertNotIn("examined, not sensed", out)
        self.assertIn("supplied by a passer-by", ok("analyse", "a van", "--seen", "white", "--by", "a passer-by"))
        for bad in (["analyse"], ["analyse", "a van"], ["analyse", "a van", "--inferred", "it is a van: high"],
                    ["analyse", "a van", "--seen", "white", "--inferred", "probably stolen"],
                    ["analyse", "a van", "--seen", "white", "--inferred", "probably old: certain"],
                    ["analyse", "a van", "--seen", "white", "--measured", "length"],
                    ["analyse", "a van", "--seen", "white", "--decoded", "ABC"], ["analyse", "a van", "--seen", "white", "--source", "dream"]):
            self.assertEqual(run(*bad)[0], 2, bad)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.data = core.load_data("sensors")

    def test_the_table_is_sound(self):
        d = self.data
        shares = [d["levels"][lv]["share"] for lv in sensors.ORDER]
        self.assertEqual(shares, sorted(shares, reverse=True))
        self.assertEqual(shares[0], 1.0)
        for name, s in d["sensors"].items():
            self.assertGreater(s["reach"], 0, name)
            self.assertIn(s["best"], sensors.ORDER, name)
            self.assertIsInstance(s["active"], bool, name)
        for table_name in ("targets", "air", "light", "cover", "state"):
            for key, row in d[table_name].items():
                if not isinstance(row, dict):
                    continue
                for sensor, factor in row.items():
                    if sensor in ("is", "means", "living"):
                        continue
                    self.assertIn(sensor, d["sensors"], "%s.%s" % (table_name, key))
                    self.assertTrue(0 <= factor <= 5, "%s.%s.%s" % (table_name, key, sensor))
        for sensor in d["own"]["silent"]["off"]:
            self.assertTrue(d["sensors"][sensor]["active"], "silent running switches off only what sends a signal")
        self.assertEqual(sorted(n for n, s in d["sensors"].items() if s["active"]), sorted(d["own"]["silent"]["off"]))
        for lv in sensors.ORDER:
            self.assertTrue(d["levels"][lv]["thing"] and d["levels"][lv]["living"] and d["levels"][lv]["within"])
        self.assertIn("who they are, if he has met them or has them on file", d["levels"]["identify"]["living"])
        self.assertEqual(d["scale"], 1.0)
        self.assertEqual(sorted(d["sensors"]), ["acoustic", "lidar", "optical", "radar", "receiver", "thermal"])
        self.assertEqual(d["port"]["seconds"], 60)
        self.assertEqual(set(d["own"]["veil"]), {"why"})    # the maker ruled that his own Veil does not dim his sensors

    def test_reach_is_the_table_multiplied_out(self):
        d = self.data
        r, notes = sensors.reach_of("thermal", "vehicle", "fog", "night", "open", ["hot", "moving"], [], d)
        want = (d["sensors"]["thermal"]["reach"] * d["scale"] * d["targets"]["vehicle"]["thermal"] * d["air"]["fog"]["thermal"]
                * d["state"]["hot"]["thermal"])
        self.assertAlmostEqual(r, want)
        self.assertEqual(notes, [])
        out = ok("scan", "vehicle", "--range", "1200", "--air", "fog", "--light", "night", "--state", "hot", "moving")
        self.assertIn("THERMAL    reach %s m:" % core.num(want), out)
        self.assertEqual(sensors.reach_of("radar", "vehicle", "clear", "day", "open", [], ["silent"], d), (None, "off: silent running"))
        self.assertEqual(sensors.reach_of("receiver", "vehicle", "clear", "day", "open", [], [], d)[0], 0.0)
        self.assertGreater(sensors.reach_of("receiver", "vehicle", "clear", "day", "open", ["emitting"], [], d)[0], 0.0)
        for sensor in ("thermal", "radar"):                 # through a thin wall: a quarter strength, and only close to
            through, why = sensors.reach_of(sensor, "vehicle", "clear", "day", "thin", [], [], d)
            self.assertEqual((through, why), (float(d["cover"]["thin_reach_m"]), ["through a thin wall"]))
            self.assertEqual(sensors.reach_of(sensor, "vehicle", "clear", "day", "hidden", [], [], d)[0], 0.0)
        weak = sensors.reach_of("thermal", "animal", "thick", "day", "thin", [], [], d)[0]
        self.assertEqual(weak, 0.0)
        for sensor in ("optical", "lidar"):
            self.assertEqual(sensors.reach_of(sensor, "vehicle", "clear", "day", "thin", [], [], d)[0], 0.0)
        smoked, why = sensors.reach_of("optical", "vehicle", "clear", "day", "open", [], ["smoke"], d)
        self.assertEqual((smoked, why), (0.0, ["his own smoke"]))
        self.assertEqual(sensors.reach_of("radar", "vehicle", "clear", "day", "open", [], ["smoke"], d)[1], [])

    def test_distance_decides_how_much_is_known(self):
        d = self.data
        e = d["edge"]
        reach = 1000.0
        self.assertEqual(sensors.levels_at(reach, "read", 10.0, d), (["detect", "classify", "identify", "read"], [], []))
        self.assertEqual(sensors.levels_at(reach, "read", reach * e["sure"], d)[0], ["detect"])
        self.assertEqual(sensors.levels_at(reach, "read", reach, d), ([], ["detect"], []))
        self.assertEqual(sensors.levels_at(reach, "read", reach * e["glimpse"], d), ([], [], ["detect"]))
        self.assertEqual(sensors.levels_at(reach, "read", reach * e["glimpse"] + 1, d), ([], [], []))
        self.assertEqual(sensors.levels_at(reach, "classify", 10.0, d)[0], ["detect", "classify"])     # a sensor's best is its ceiling
        self.assertEqual(sensors.levels_at(0.0, "read", 10.0, d), ([], [], []))

    def test_scan(self):
        out = ok("scan", "vehicle", "--range", "1200", "--air", "fog", "--light", "night", "--state", "hot", "moving")
        self.assertIn("TARGET     a car or a van, 1,200 m off; fog; by night; running hot, moving [%s]" % self.data["label"], out)
        self.assertIn("RADAR      reach 9,000 m: sure of: classify (the most a radar can tell)", out)
        self.assertIn("RECEIVER   nothing to hear: the target sends nothing out", out)
        self.assertIn("KNOWN      what kind of thing it is", out)
        self.assertIn("NOT KNOWN  nothing at the level of identify or read: do not report any", out)
        self.assertIn("GIVES AWAY radar and lidar send out a signal", out)
        self.assertIn("game mechanics, not a model of any real sensor", out)
        out = ok("scan", "person", "--range", "80", "--cover", "partial", "--light", "dark", "--silent")
        self.assertIn("HIMSELF    silent running", out)
        self.assertIn("RADAR      off: silent running", out)
        self.assertIn("LIDAR      off: silent running", out)
        self.assertNotIn("GIVES AWAY", out)
        self.assertIn("and who they are, if he has met them or has them on file [identify, for certain]", out)
        self.assertIn("CHANCE     their state: whether they move and breathe", out)
        self.assertIn("[read: 58.33% on this look]", out)
        out = ok("scan", "person", "--range", "30", "--smoke")
        self.assertIn("OPTICAL    reach 0 m (his own smoke): nothing at this range", out)
        self.assertIn("RADAR      reach", out)
        hidden = ok("scan", "vehicle", "--range", "100", "--cover", "hidden")
        self.assertIn("OPTICAL    reach 0 m: nothing at this range", hidden)
        self.assertIn("THERMAL    reach 0 m: nothing at this range", hidden)
        self.assertIn("RADAR      reach 0 m: nothing at this range", hidden)
        thin = ok("scan", "person", "--range", "20", "--cover", "thin", "--state", "quiet")
        self.assertIn("behind a thin wall or a vehicle's skin; keeping quiet", thin)
        self.assertIn("THERMAL    reach 60 m (through a thin wall): sure of: detect", thin)
        self.assertIn("KNOWN      something alive is there", thin)
        self.assertIn("nothing at this range", ok("scan", "person", "--range", "200", "--cover", "thin").split("THERMAL")[1].splitlines()[0])
        port = ok("scan", "--port")
        self.assertIn("PORT       the sample port in the cabin: one sample at a time, put in by hand [lore]", port)
        self.assertIn("in about a minute [lore]", port)
        self.assertIn("NOT        where it came from, or who handled it", port)
        self.assertIn("wait=60s", port)
        self.assertIn("the Veil is up: it does not dim his own sensors", ok("scan", "--list"))
        veiled = ok("scan", "armour", "--range", "300", "--veil", "--state", "quiet")
        self.assertIn("HIMSELF    the Veil is up: it does not dim his own sensors", veiled)
        plain = ok("scan", "armour", "--range", "300", "--state", "quiet")
        self.assertEqual([ln for ln in veiled.splitlines() if not ln.startswith("HIMSELF")], plain.splitlines())
        only = ok("scan", "drone", "--range", "500", "--only", "radar", "acoustic", "--state", "loud", "--roll", "--seed", "4")
        self.assertNotIn("OPTICAL", only)
        self.assertIn("ROLL       [2, 3] = 5: something is there", only)
        self.assertIn("SEED       4 (repeatable)", only)
        self.assertEqual(only, ok("scan", "drone", "--range", "500", "--only", "radar", "acoustic", "--state", "loud", "--roll", "--seed", "4"))
        self.assertIn("GIVES AWAY radar sends out a signal", only)
        far = ok("scan", "person", "--range", "50000")
        self.assertIn("KNOWN      nothing for certain at this range", far)
        self.assertIn("SENSORS    %d in the" % len(self.data["sensors"]), ok("scan", "--list"))
        for bad in (["scan"], ["scan", "vehicle"], ["scan", "dragon", "--range", "10"], ["scan", "vehicle", "--range", "0"],
                    ["scan", "vehicle", "--range", "10", "--air", "soup"], ["scan", "vehicle", "--range", "10", "--state", "hot", "cold"],
                    ["scan", "vehicle", "--range", "10", "--cover", "thin_reach_m"], ["scan", "vehicle", "--range", "10", "--only", "nose"],
                    ["scan", "vehicle", "--range", "10", "--silent", "--veil"],
                    ["scan", "vehicle", "--range", "10", "--light", "note"]):
            self.assertEqual(run(*bad)[0], 2, bad)


class PublishedFiguresTests(unittest.TestCase):
    """Figures that were read from their sources on 10 November 2026. A change here should be a decision, not a slip."""

    def test_sound_limits(self):
        self.assertEqual((sound.NIOSH_LEVEL, sound.NIOSH_HOURS, sound.NIOSH_EXCHANGE), (85.0, 8.0, 3.0))
        self.assertEqual((sound.EU_LOWER, sound.EU_UPPER, sound.EU_LIMIT), (80.0, 85.0, 87.0))
        self.assertEqual((sound.WHO_LEVEL, sound.WHO_SENSITIVE, sound.WHO_HOURS), (80.0, 75.0, 40.0))
        # 80 dB(A) for 40 hours is the 1.6 Pa2h the listening standard gives; 75 dB(A) is its 0.51
        self.assertAlmostEqual((sound.P0 * 10 ** (80 / 20.0)) ** 2 * 40, 1.6, places=6)
        self.assertAlmostEqual((sound.P0 * 10 ** (75 / 20.0)) ** 2 * 40, 0.51, places=2)

    def test_load_and_lifting_figures(self):
        self.assertEqual((things.FORWARD_G, things.SIDEWAYS_G, things.REARWARD_G, things.TIPPING_G), (0.8, 0.5, 0.5, 0.6))
        self.assertEqual((things.LIFT_LOW_KG, things.LIFT_HIGH_KG), (15.0, 25.0))
        mats = core.load_data("materials")["materials"]
        self.assertEqual((mats["petrol"]["low"], mats["petrol"]["high"]), (720, 775))
        self.assertEqual((mats["diesel"]["low"], mats["diesel"]["high"]), (815, 845))

    def test_fatigue_figures(self):
        """Read from their sources on 12 November 2026: the Highway Code (rule 91), Regulation (EC) No 561/2006 (article 6), NIOSH."""
        self.assertEqual((fatigue.LOW_HOURS, fatigue.BREAK_EVERY_H, fatigue.BREAK_MIN), ("00:00-06:00", 2.0, 15))
        self.assertEqual(fatigue.DAY_AT_WHEEL_H, 9.0)
        self.assertEqual((fatigue.AWAKE_H, fatigue.AWAKE_LONG_H), (17.0, 24.0))
        self.assertEqual(fatigue.REST_H, 7.0)                       # a house rule, not a published figure
        self.assertEqual(fatigue.DRIVEN, ("car", "motorway", "city"))

    def test_g_figures(self):
        """Read from their sources on 12 November 2026: StatPearls on G-LOC; the Indian Journal of Aerospace Medicine on a
        current ejection seat; Stemper and others, Journal of Orthopaedic Research 36(6), on the lumbar spine."""
        self.assertEqual((jump.LOC_G, jump.LOC_S), (4.7, 5.0))
        self.assertEqual(jump.SEAT_G, (12.0, 14.0))
        self.assertEqual(jump.SPINE_G, (16.0, 13.0, 19.0))

    def test_reference_sizes(self):
        refs = core.load_data("references")["references"]
        want = {"card": 85.6, "card-short": 53.98, "a4": 297.0, "a4-short": 210.0, "plate-eu": 520.0, "plate-us": 304.8,
                "pallet": 1200.0, "pallet-short": 800.0, "pallet-height": 144.0, "container-20": 6058.0, "container-40": 12192.0,
                "container-width": 2438.0, "container-height": 2591.0, "rail-gauge": 1435.0, "euro-1": 23.25, "euro-2": 25.75,
                "euro-note-5": 120.0, "euro-note-10": 127.0, "euro-note-20": 133.0, "euro-note-50": 140.0, "cd": 120.0, "aa": 50.5,
                "golf-ball": 42.67, "table-tennis-ball": 40.0}
        self.assertEqual(dict((k, v["mm"]) for k, v in refs.items()), want)
        self.assertNotIn("United Kingdom", refs["plate-eu"]["source"])       # no plate size is set in law there

    def test_the_gazetteer_carries_the_credit_it_owes(self):
        with open(os.path.join(SCRIPTS, "data", "SOURCES.md"), encoding="utf-8") as f:
            sources = f.read()
        meta = geo.gazetteer_meta("sources")
        if geo.gazetteer_meta("geonames") == "yes":
            for where in (sources, meta):
                self.assertIn("GeoNames", where)
                self.assertIn("CC BY 4.0", where)
            self.assertIn("https://creativecommons.org/licenses/by/4.0/", sources)
            self.assertIn("What was changed", sources)
            with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
                self.assertIn("GeoNames", f.read())
        else:
            self.assertNotIn("GeoNames", sources)


if __name__ == "__main__":
    unittest.main()
