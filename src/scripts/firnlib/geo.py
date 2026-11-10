"""Ground work: the gazetteer, great-circle geometry, routes, multi-leg trips.

Places come from two layers. The driver's own (home, work, places in personal.json) is a small dictionary and is
asked first. Under it lies the generated gazetteer, a read-only SQLite file that is asked one name at a time,
so a lookup costs the same whether it holds four thousand places or forty thousand.
"""
import json
import math
import os
import re
from datetime import datetime, timedelta

from . import chrono, ical
from .core import (DATA, PERSONAL_FILE, SAID, SETUP_HINT, command, die, fmt_hm, fold, load_data, more, num, parse_clock,
                   personal, rec, table, trim, unprotect)

EARTH_R_KM = 6371.0088
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

# mode: (average km/h, road factor, hours between breaks, break minutes, buffer percent, fixed overhead hours per leg)
MODES = {
    "car": (80.0, 1.25, 2.0, 15, 10.0, 0.0),
    "motorway": (105.0, 1.20, 2.0, 15, 10.0, 0.0),
    "city": (30.0, 1.35, 0.0, 0, 15.0, 0.0),
    "bike": (18.0, 1.30, 1.5, 10, 10.0, 0.0),
    "walk": (4.8, 1.25, 1.5, 10, 10.0, 0.0),
    "rail": (90.0, 1.30, 0.0, 0, 0.0, 0.0),
    "air": (800.0, 1.05, 0.0, 0, 0.0, 0.5),
}
GROUND_MODES = ("car", "motorway", "city", "bike", "walk")
MAP_MODE = {"car": "driving", "motorway": "driving", "city": "driving", "bike": "bicycling", "walk": "walking", "rail": "transit"}
TRIP_MODES = {"fly": "air", "air": "air", "flight": "air", "plane": "air",
              "rail": "rail", "train": "rail", "drive": "car", "car": "car",
              "bus": "bus", "coach": "bus", "ferry": "ferry", "walk": "walk"}
KINDS = ["capital", "city", "airport", "station", "home", "work", "poi"]

_places = None      # the driver's own layer: home, work, their own places. It sits on top of the gazetteer
_index = None       # every name that layer answers to -> key
_legs = None
_unset = None
_own = None
_db = None          # the generated gazetteer, data/places.db, opened read-only on first use
_zones = None
_looked = {}
_COORD_RE = re.compile(r"^\s*@?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_COLS = "p.id, p.key, p.name, p.lat, p.lon, p.zone, p.kind, p.cc, p.pop, p.icao"


# ---- the driver's own layer

def _load():
    """Home, work and the driver's own places. They come first, and a key of theirs hides the gazetteer's."""
    global _places, _legs, _unset, _own
    if _places is not None:
        return
    pers = personal()
    places, unset, own = {}, [], []
    for slot in ("home", "work"):
        p = pers.get(slot) or {}
        if p.get("lat") is not None and p.get("lon") is not None:
            e = dict(p)
            e.setdefault("name", slot.title())
            e["kind"] = slot
            places[slot] = e
            own.append(slot)
        else:
            unset.append(slot)
    for key, p in (pers.get("places") or {}).items():
        k = fold(key)
        if k and k not in places:
            places[k] = dict(p)
            own.append(k)
    legs = dict(pers.get("legs") or {})
    extra = os.environ.get("FIRN_PLACES")
    if extra:
        try:
            with open(extra, encoding="utf-8") as f:
                more_data = json.load(f)
        except OSError:
            die("FIRN_PLACES points at a file that cannot be read: %s" % extra)
        except ValueError as e:
            die("FIRN_PLACES file is not valid JSON: %s" % e)
        for key, p in (more_data.get("places") or {}).items():
            k = fold(key)
            if k and k not in places:
                places[k] = dict(p)
                own.append(k)
        legs.update(more_data.get("legs") or {})
    for key, p in places.items():
        p["key"] = key
    _places, _legs, _unset, _own = places, legs, unset, own


def _build_index():
    global _index
    _index = {}
    for key in _own:
        p = _places[key]
        _index.setdefault(key, key)
        f = fold(p.get("name", ""))
        if f:
            _index.setdefault(f, key)
        for alias in p.get("aka", ()):
            f = fold(alias)
            if f:
                _index.setdefault(f, key)


def unset_slots():
    """Which of home and work are still placeholders."""
    _load()
    return list(_unset)


def own_places():
    _load()
    return list(_own)


def own_place(key):
    """One of the driver's own places by its key, or None."""
    _load()
    return _places.get(key)


# ---- the gazetteer

def _gaz():
    """The gazetteer database, opened once and read-only. 'immutable' means no locks and no journal, so it
    reads from a folder nothing can be written to."""
    global _db, _zones
    if _db is None:
        path = os.path.join(DATA, "places.db")
        if not os.path.isfile(path):
            die("data file missing: scripts/data/places.db")
        try:
            import sqlite3
        except ImportError:
            die("this Python has no sqlite3 module, which the gazetteer needs. Until then give places as lat,lon")
        uri = path.replace("\\", "/").replace("%", "%25").replace("?", "%3f").replace("#", "%23")
        if re.match(r"^[A-Za-z]:", uri):
            uri = "/" + uri
        try:
            try:
                con = sqlite3.connect("file:%s?mode=ro&immutable=1" % uri, uri=True)
                con.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
            except sqlite3.Error:
                con = sqlite3.connect(path)       # a path the URI form cannot spell, such as a network share
                con.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
            _zones = dict(con.execute("SELECT id, name FROM zone").fetchall())
        except sqlite3.Error as e:
            die("scripts/data/places.db cannot be read (%s): the package is damaged, install it again" % e)
        import atexit
        atexit.register(con.close)
        _db = con
    return _db


def _place(row):
    p = {"rank": row[0], "key": row[1], "name": row[2], "lat": row[3] / 10000.0, "lon": row[4] / 10000.0, "tz": _zones[row[5]],
         "kind": row[6], "cc": row[7], "pop": row[8]}
    if row[9]:
        p["icao"] = row[9]
    return p


def gazetteer_meta(key):
    row = _gaz().execute("SELECT v FROM meta WHERE k = ?", (key,)).fetchone()
    return row[0] if row else ""


def counts():
    """How many places of each kind the gazetteer holds."""
    return json.loads(gazetteer_meta("kinds") or "{}")


def named(f, limit=8):
    """Gazetteer places that answer to a folded name: the owner of that key first, then the others, most notable first."""
    key = (f, limit)
    if key not in _looked:
        rows = _gaz().execute("SELECT %s FROM name n JOIN place p ON p.id = n.id WHERE n.k = ? ORDER BY n.r LIMIT ?" % _COLS,
                              (f, limit)).fetchall()
        _looked[key] = [_place(r) for r in rows]
    return _looked[key]


def in_gazetteer(key):
    """The gazetteer place that owns this key, or None."""
    row = _gaz().execute("SELECT %s FROM name n JOIN place p ON p.id = n.id WHERE n.k = ? AND n.r = 0" % _COLS, (key,)).fetchone()
    return _place(row) if row else None


def find_station(code):
    """An airport by its ICAO code (the station of a METAR), or None."""
    row = _gaz().execute("SELECT %s FROM place p WHERE p.icao = ? ORDER BY p.id LIMIT 1" % _COLS, (str(code).strip().upper(),)).fetchone()
    return _place(row) if row else None


def zones_in(cc):
    """The zones of the gazetteer's places in a country, sorted."""
    rows = _gaz().execute("SELECT DISTINCT z.name FROM place p JOIN zone z ON z.id = p.zone WHERE p.cc = ?", (cc,)).fetchall()
    return sorted(r[0] for r in rows)


def select(kind=None, country=None, find=None, with_own=True):
    """Places by kind, country and a piece of a name, sorted by key."""
    _load()
    where, args = [], []
    if kind:
        where.append("p.kind = ?")
        args.append(kind)
    if country:
        where.append("p.cc = ?")
        args.append(country.upper())
    if find:
        where.append("p.id IN (SELECT id FROM name WHERE instr(k, ?) > 0)")
        args.append(find)
    sql = "SELECT %s FROM place p%s" % (_COLS, " WHERE " + " AND ".join(where) if where else "")
    out = [_place(r) for r in _gaz().execute(sql, args).fetchall()]
    out = [p for p in out if p["key"] not in _places]
    if with_own:
        for key in _own:
            p = _places[key]
            if kind and p.get("kind", "city") != kind:
                continue
            if country and (p.get("cc") or "").upper() != country.upper():
                continue
            if find and find not in " ".join([key, fold(p.get("name", ""))] + [fold(x) for x in p.get("aka", [])]):
                continue
            out.append(p)
    return sorted(out, key=lambda p: p["key"])


def near(lat, lon, km, kinds=None, with_own=True):
    """[(km away, place)] within a radius, nearest first."""
    _load()
    dlat = km / 111.0
    lo, hi = lat - dlat, lat + dlat
    sql = "SELECT %s FROM place p WHERE p.lat BETWEEN ? AND ?" % _COLS
    args = [int(math.floor(lo * 10000)), int(math.ceil(hi * 10000))]
    width = km / (111.0 * max(0.01, math.cos(math.radians(min(89.9, max(abs(lo), abs(hi)))))))
    if width < 170 and -180 <= lon - width and lon + width <= 180:      # otherwise the box wraps: let the distance decide
        sql += " AND p.lon BETWEEN ? AND ?"
        args += [int(math.floor((lon - width) * 10000)), int(math.ceil((lon + width) * 10000))]
    if kinds:
        sql += " AND p.kind IN (%s)" % ", ".join("?" for _ in kinds)
        args += list(kinds)
    out = []
    for row in _gaz().execute(sql, args).fetchall():
        if row[1] in _places:
            continue
        d = haversine_km(lat, lon, row[3] / 10000.0, row[4] / 10000.0)
        if d <= km:
            out.append((d, _place(row)))
    if with_own:
        for key in _own:
            p = _places[key]
            if kinds and p.get("kind", "city") not in kinds:
                continue
            d = haversine_km(lat, lon, p["lat"], p["lon"])
            if d <= km:
                out.append((d, p))
    return sorted(out, key=lambda x: (x[0], x[1]["key"]))


def nearest(lat, lon, limit_km, want=None):
    """The nearest gazetteer place within a limit that passes a test, as (km, place), or None. Looks close by first."""
    for km in (60.0, 250.0, 1000.0, 20000.0):
        km = min(km, limit_km)
        for d, p in near(lat, lon, km, with_own=False):
            if want is None or want(p):
                return d, p
        if km >= limit_km:
            break
    return None


def _qualified(raw):
    """'Springfield, Illinois', 'San Jose, US': a name, then where. The place of that name that fits, or None."""
    head, _, tail = raw.partition(",")
    f, where = fold(head), fold(tail)
    if not f or not where:
        return None
    whole = fold(raw)
    cands = named(f, 60)
    for test in (lambda p: fold(p["name"]) == whole,
                 lambda p: p["cc"].lower() == where,
                 lambda p: ", " in p["name"] and fold(p["name"].split(", ", 1)[1]) == where,
                 lambda p: ", " in p["name"] and where in fold(p["name"].split(", ", 1)[1])):
        for p in cands:
            if test(p):
                return p
    return None


def _say_others(typed, f, place, others):
    """One ALSO line when a name could as well have meant another place: a town and an airport code that share
    their letters, or towns of the same name that are not very different in size."""
    if ("also", f) in SAID:
        return
    show = []
    for o in others:
        if o["key"] == place["key"]:
            continue
        if (o["kind"] == "airport") != (place["kind"] == "airport"):
            show.append(o)
        elif o["kind"] != "airport" and o["pop"] >= 15000 and o["pop"] >= 0.2 * place["pop"]:
            show.append(o)
    if not show:
        return
    SAID.add(("also", f))
    rec("ALSO", "'%s' is read as %s%s. Of the same name: %s. Give the key to choose" % (
        typed, place["name"], " (%s)" % place["cc"] if place["cc"] else "",
        "; ".join("%s = %s%s" % (o["key"], o["name"], " (%s)" % o["cc"] if o["cc"] else "") for o in show[:3])))


def find_place(text, say=False):
    """Look a place up by key, name or alias, diacritics and case ignored. None if unknown.
    The driver's own places come first. With say=True, a name that fits several places gets an ALSO line."""
    _load()
    raw = unprotect(str(text))
    f = fold(raw)
    if not f:
        return None
    if f in _places:
        return _places[f]
    if _index is None:
        _build_index()
    if f in _index:
        return _places[_index[f]]
    hits = named(f)
    if hits:
        if say and len(hits) > 1:
            _say_others(raw, f, hits[0], hits[1:])
        return hits[0]
    return _qualified(raw) if "," in raw else None


def suggest(text, n=3):
    import difflib
    _load()
    if _index is None:
        _build_index()
    f = fold(text)
    pool = list(_index)
    if len(f) >= 2:
        # near misses nearly always start the same way, and one stretch of the name table holds them all
        first = f[:2]
        pool += [r[0] for r in _gaz().execute("SELECT DISTINCT k FROM name WHERE k >= ? AND k < ?",
                                             (first, first[:-1] + chr(ord(first[-1]) + 1))).fetchall()]
    return difflib.get_close_matches(f, pool, n=n, cutoff=0.75)


def parse_point(text):
    """'warsaw', 'KTW', 'Wieden', 'Springfield, Illinois' or 'lat,lon' -> (label, lat, lon, place-or-None)."""
    text = unprotect(text)
    m = _COORD_RE.match(str(text))
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            die("coordinates out of range: %s (latitude -90..90, longitude -180..180)" % text)
        return "%s,%s" % (trim(lat, 4), trim(lon, 4)), lat, lon, None
    p = find_place(text, say=True)
    if not p:
        if fold(text) in ("home", "work"):
            die("%s is not set yet: %s. Until then, name a place or give lat,lon." % (fold(text), SETUP_HINT))
        near_names = suggest(text)
        hint = " Did you mean: %s?" % ", ".join(near_names) if near_names else ""
        die("unknown place '%s'.%s Give 'lat,lon' (find it with search), or try 'places --find TEXT'. "
            "To keep a place, 'places --add' prints the line for the driver's file." % (text, hint))
    return p.get("name", p["key"]), p["lat"], p["lon"], p


def place_tz(point, fallback=None):
    """Zone of a parsed point: its own, else the fallback, else home (or UTC while home is unset)."""
    name = (point[3] or {}).get("tz") or fallback
    return chrono.get_tz(name) if name else chrono.home_tz()


def known_leg(p1, p2):
    """A checked road figure for this pair, either direction, or None."""
    _load()
    if not p1 or not p2:
        return None
    for a, b in ((p1["key"], p2["key"]), (p2["key"], p1["key"])):
        leg = _legs.get("%s>%s" % (a, b))
        if leg and leg.get("km"):
            if (a, b) != (p1["key"], p2["key"]) and leg.get("oneway"):
                continue
            return leg
    return None


# ---- geometry

def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(deg):
    return COMPASS[int((deg % 360 + 11.25) // 22.5) % 16]


def intermediate(lat1, lon1, lat2, lon2, f):
    """Point a fraction f along the great circle from 1 to 2."""
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    d = haversine_km(lat1, lon1, lat2, lon2) / EARTH_R_KM
    if d < 1e-9:
        return lat1, lon1
    a = math.sin((1 - f) * d) / math.sin(d)
    b = math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def angle_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


def map_link(pts, mode):
    """A live-map directions link for these points, so the estimate can be checked in one click."""
    travel = MAP_MODE.get(mode)
    if not travel:
        return None
    def ll(p):
        return "%s,%s" % (trim(p[1], 5), trim(p[2], 5))
    url = "https://www.google.com/maps/dir/?api=1&origin=%s&destination=%s&travelmode=%s" % (ll(pts[0]), ll(pts[-1]), travel)
    if len(pts) > 2:
        url += "&waypoints=" + "%7C".join(ll(p) for p in pts[1:-1])
    return url


# ---- route

def estimate_leg(p1, p2, mode, speed=None, road=None):
    """(straight km, travel km, hours, tag, timed) for one leg between parsed points.
    timed is True when the hours come from a checked figure rather than from an average speed."""
    base_speed, base_road, _, _, _, overhead = MODES[mode]
    straight = haversine_km(p1[1], p1[2], p2[1], p2[2])
    leg = known_leg(p1[3], p2[3]) if mode in ("car", "motorway", "city") else None
    if leg and road is None:
        km = float(leg["km"])
        timed = bool(leg.get("min")) and speed is None
        if timed:
            hours = float(leg["min"]) / 60.0
        else:
            hours = km / (speed or base_speed)
        tag = "checked %s%s" % (leg.get("checked", "date unknown"), (", " + leg["source"]) if leg.get("source") else "")
        return straight, km, hours, tag, timed
    km = straight * (road if road is not None else base_road)
    hours = km / (speed or base_speed) + overhead
    return straight, km, hours, "estimate", False


def cmd_route(a):
    from . import sky
    pts = [parse_point(p) for p in a.points]
    if len(pts) < 2:
        die("route needs at least two points")
    base_speed, base_road, base_every, base_min, base_buffer, overhead = MODES[a.mode]
    speed = a.speed if a.speed is not None else base_speed
    if speed <= 0:
        die("speed must be positive")
    if a.depart and a.arrive:
        die("give --depart or --arrive, not both")
    if a.window and (a.depart or a.arrive):
        die("--window chooses the departure for you: leave out --depart and --arrive")
    if a.before_dark and not a.window:
        die("--before-dark works on a window of departures: add --window 06:00-12:00")
    if a.ics and not (a.depart or a.arrive or a.window):
        die("a calendar entry needs a time: add --depart, --arrive or --window")
    every = a.break_every if a.break_every is not None else base_every
    brk_min = a.break_min if a.break_min is not None else base_min
    buffer_pct = a.buffer if a.buffer is not None else base_buffer
    air = a.mode == "air"

    legs = []
    straight = travel = drive_h = 0.0
    any_estimate = False
    no_road = False
    timed_legs = 0
    for i, (p1, p2) in enumerate(zip(pts, pts[1:]), 1):
        s, km, hours, tag, timed = estimate_leg(p1, p2, a.mode, a.speed, a.road)
        timed_legs += 1 if timed else 0
        b = bearing_deg(p1[1], p1[2], p2[1], p2[2])
        legs.append((p1, p2, s, km, hours, b, tag))
        straight += s
        travel += km
        drive_h += hours
        any_estimate = any_estimate or tag == "estimate"
        what = "flown" if air else "track" if a.mode == "rail" else "road"
        rec("LEG %d" % i, "%s -> %s | %s km %s | %s%s km %s | %03.0f %s%s" % (
            p1[0], p2[0], trim(s, 1), "great circle" if air else "straight", "~" if tag == "estimate" else "", num(km), what,
            b, compass(b), "" if tag == "estimate" else " [%s]" % tag))
        if a.mode in GROUND_MODES and (s > 2000 or abs(p1[2] - p2[2]) > 50):
            no_road = True
            rec("CHECK", "leg %d is %s km in a straight line: is there a road all the way? Try --mode air." % (i, num(s)))
    breaks = int(drive_h // every) if every > 0 else 0
    if every > 0 and breaks and abs(drive_h - breaks * every) < 1e-9:
        breaks -= 1
    break_h = breaks * brk_min / 60.0
    buffer_h = (drive_h + break_h) * buffer_pct / 100.0
    total_h = round((drive_h + break_h + buffer_h) * 60.0) / 60.0
    rec("GREAT CIRCLE" if air else "STRAIGHT", "%s km [derived]" % trim(straight, 1))
    label = {"air": "FLOWN", "rail": "TRACK"}.get(a.mode, "ROAD")
    if any_estimate:
        factor = a.road if a.road is not None else base_road
        rec(label, "~%s km [estimate: %s x %s%s]" % (
            num(travel), "great circle" if air else "straight line", trim(factor, 2), " for routing and winds" if air else ""))
    else:
        rec(label, "%s km [checked legs]" % num(travel))
    verb = {"air": "BLOCK", "rail": "RIDE", "walk": "WALK", "bike": "RIDE"}.get(a.mode, "DRIVE")
    extra = " + %s per leg for taxi, climb and approach" % fmt_hm(overhead) if overhead else ""
    if timed_legs == len(legs):
        rec(verb, "%s [checked time for these legs; a snapshot, live traffic will differ]" % fmt_hm(drive_h))
    else:
        rec(verb, "%s at %s km/h average%s%s [%s mode]" % (
            fmt_hm(drive_h), trim(speed, 1), extra, " on the estimated legs" if timed_legs else "", a.mode))
    if every > 0:
        rec("BREAKS", "%d x %d min = %s (one every %s h)" % (breaks, brk_min, fmt_hm(break_h), trim(every, 1)))
    if buffer_pct:
        rec("BUFFER", "%s (%s%%)" % (fmt_hm(buffer_h), trim(buffer_pct, 1)))
    rec("TOTAL", "%s [estimate]" % fmt_hm(total_h))

    dep = arr = None
    note = None
    start_tz = place_tz(pts[0], a.tz)
    end_tz = place_tz(pts[-1], a.tz)
    if a.window:
        dep = pick_departure(a, pts, legs, total_h, start_tz, end_tz, sky)
        arr = chrono.to_utc(chrono.add(dep, total_h * 3600)).astimezone(end_tz)
    elif a.depart:
        dep, note = chrono.parse_when(a.depart, start_tz)
        arr = chrono.to_utc(chrono.add(dep, total_h * 3600)).astimezone(end_tz)
    elif a.arrive:
        arr, note = chrono.parse_when(a.arrive, end_tz)
        dep = chrono.to_utc(chrono.add(arr, -total_h * 3600)).astimezone(start_tz)
    if dep:
        rec("LEAVE BY" if a.arrive else "DEPART", chrono.fmt_dt(dep) + "  " + pts[0][0])
        rec("ARRIVE", chrono.fmt_dt(arr) + "  " + pts[-1][0])
        if chrono.home_is_set():
            at_home = chrono.to_utc(arr).astimezone(chrono.home_tz())
            if arr.utcoffset() != at_home.utcoffset():
                rec("", chrono.fmt_dt(at_home) + "  (home time)")
        if note:
            rec("NOTE", note)
        for p in (pts[0], pts[-1]):
            if not (p[3] or {}).get("tz") and not a.tz:
                rec("NOTE", "%s has no zone on file; %s assumed (set --tz)" % (
                    p[0], "home time" if chrono.home_is_set() else "UTC"))
                break
        _light(a, legs, dep, total_h, sky)
    if a.firn:
        full = load_data("lore")["chassis"]["range_km"]
        left = full - travel
        rec("RANGE", "%s km of %s km [lore] -> %s km left%s" % (
            num(travel), num(full), num(left), "" if left >= 0 else "  OUT OF RANGE: plan a recharge"))
    link = None if no_road else map_link(pts, a.mode)
    if link:
        rec("LIVE MAP", link)
    if a.mode in GROUND_MODES and any_estimate:
        rec("NOTE", "road distance is a straight-line estimate; open the live map before stating times as fact")
    if a.ics:
        word = {"air": "Fly", "rail": "Rail", "walk": "Walk", "bike": "Ride"}.get(a.mode, "Drive")
        how = "%s%s km, %s in all" % ("~" if any_estimate else "", num(travel), fmt_hm(total_h))
        extras = []
        if breaks:
            extras.append("%d break%s of %d min" % (breaks, "" if breaks == 1 else "s", brk_min))
        if buffer_pct:
            extras.append("a %s%% buffer" % trim(buffer_pct, 1))
        if extras:
            how += ", including " + " and ".join(extras)
        lines = ["Depart %s, %s." % (chrono.fmt_dt(dep), pts[0][0]), "Arrive %s, %s." % (chrono.fmt_dt(arr), pts[-1][0])]
        if len(pts) > 2:
            lines.append("Via %s." % ", ".join(p[0] for p in pts[1:-1]))
        lines.append(how + ".")
        lines.append("Distance and time are estimates: check a live map before relying on them." if any_estimate
                     else "Road figures were checked on the date given; live traffic will differ.")
        if link:
            lines.append("Live map: " + link)
        entry = ical.event("%s: %s to %s" % (word, pts[0][0], pts[-1][0]), dep, arr, location=pts[0][0],
                           description="\n".join(lines), alarm=ical.alarm_of(a))
        ical.deliver(a, [entry], "route-%s" % dep.date().isoformat(), estimate=any_estimate)


def pick_departure(a, pts, legs, total_h, start_tz, end_tz, sky):
    """Try every departure in the window and return the one with the least night driving, then the least low sun ahead."""
    m = re.match(r"^\s*(\d{1,2}[:.]\d{2})\s*-\s*(\d{1,2}[:.]\d{2})\s*$", unprotect(a.window))
    if not m:
        die("--window is two clock times at the start point: 06:00-12:00")
    (h1, m1), (h2, m2) = parse_clock(m.group(1)), parse_clock(m.group(2))
    first, last = h1 * 60 + m1, h2 * 60 + m2
    if last <= first:
        die("the window must end after it starts, on the same day")
    if not 5 <= a.step <= 120:
        die("--step is 5 to 120 minutes")
    now = chrono.now_in(start_tz)
    day = chrono.parse_date(a.date, now.date()) if a.date else now.date()
    if day is None:
        die("--date is a date: YYYY-MM-DD, today or tomorrow")
    moved = False
    if not a.date and now.hour * 60 + now.minute > last:
        day, moved = day + timedelta(days=1), True
    tried = []
    for minute in range(first, last + 1, a.step):
        dep, _ = chrono.localize(datetime(day.year, day.month, day.day, minute // 60, minute % 60), start_tz)
        profile = light_profile(a.mode, legs, dep, total_h, sky)
        if not profile:
            die("the journey is too long to weigh departures by daylight")
        bins, glare, dt_min = profile
        arr = chrono.to_utc(chrono.add(dep, total_h * 3600)).astimezone(end_tz)
        sunset = sky.sun_event(arr.date(), pts[-1][1], pts[-1][2], sky.SUN_ALT["sun"], False)
        lit = (not isinstance(sunset, str)) and chrono.to_utc(arr) <= chrono.to_utc(sunset)
        tried.append({"dep": dep, "arr": arr, "night": bins["night"], "twilight": bins["twilight"],
                      "glare": sum((g["end"] - g["start"]).total_seconds() / 60.0 + dt_min for g in glare), "lit": lit, "sunset": sunset})

    def score(c):
        return (round(c["night"] + 0.5 * c["twilight"], 3), round(c["glare"], 3), chrono.to_utc(c["dep"]))

    def show(c):
        return "depart %s, arrive %s | night %s, twilight %s, low sun ahead %s" % (
            c["dep"].strftime("%H:%M"), c["arr"].strftime("%H:%M"), fmt_hm(c["night"] / 60.0), fmt_hm(c["twilight"] / 60.0),
            fmt_hm(c["glare"] / 60.0))

    rec("WINDOW", "%s, departures %s to %s every %d min: %d tried [derived]%s" % (
        day.isoformat(), m.group(1), m.group(2), a.step, len(tried), " (today's window has passed: this is tomorrow)" if moved else ""))
    pool = tried
    if a.before_dark:
        pool = [c for c in tried if c["lit"]]
        if not pool:
            rec("DARK", "no departure in the window arrives before sunset; the best of them is shown")
            pool = tried
        else:
            late = max(pool, key=lambda c: chrono.to_utc(c["dep"]))
            rec("LATEST", "depart %s to arrive %s, before sunset at %s" % (
                late["dep"].strftime("%H:%M"), late["arr"].strftime("%H:%M"), late["sunset"].astimezone(end_tz).strftime("%H:%M")))
    ranked = sorted(pool, key=score)
    best = ranked[0]
    rec("BEST", show(best))
    others = [c for c in ranked[1:] if score(c)[:2] != score(best)[:2]]
    if others:
        rec("NEXT BEST", show(others[0]))
    worst = max(tried, key=score)
    if score(worst)[:2] != score(best)[:2]:
        rec("WORST", show(worst))
    else:
        more("every departure in the window is the same for light: the earliest is taken")
    return best["dep"]


def light_profile(mode, legs, dep, total_h, sky):
    """Minutes of day, twilight and night along the way, and the stretches of low sun ahead:
    (bins, glare windows, minutes per step), or None for a journey too long to sample."""
    if total_h <= 0 or total_h > 72:
        return None
    total_km = sum(l[3] for l in legs) or 1.0
    steps = int(min(720, max(24, math.ceil(total_h * 60 / 5.0))))
    dt_min = total_h * 60.0 / steps
    bins = {"day": 0.0, "twilight": 0.0, "night": 0.0}
    glare, cur = [], None
    dep_u = chrono.to_utc(dep)
    for i in range(steps):
        f = (i + 0.5) / steps
        target = f * total_km
        acc = 0.0
        for n, (p1, p2, s, km, hours, brg, tag) in enumerate(legs, 1):
            if target <= acc + km or n == len(legs):
                lf = 0.0 if km <= 0 else min(1.0, max(0.0, (target - acc) / km))
                lat, lon = intermediate(p1[1], p1[2], p2[1], p2[2], lf)
                heading = bearing_deg(lat, lon, p2[1], p2[2]) if lf < 0.98 else brg
                leg_no = n
                break
            acc += km
        when = dep_u + timedelta(minutes=f * total_h * 60.0)
        elev, az = sky.sun_position(when, lat, lon)
        kind = "day" if elev > -0.833 else "twilight" if elev > -6.0 else "night"
        bins[kind] += dt_min
        is_glare = mode in GROUND_MODES and 0.0 < elev < 12.0 and angle_diff(az, heading) <= 25.0
        if is_glare:
            if cur and cur["leg"] == leg_no:
                cur["end"] = when
                cur["elev"] = min(cur["elev"], elev)
            else:
                cur = {"leg": leg_no, "start": when, "end": when, "elev": elev, "az": az, "heading": heading}
                glare.append(cur)
        else:
            cur = None
    return bins, glare, dt_min


def _light(a, legs, dep, total_h, sky):
    """Print daylight, twilight, night and low-sun glare along the way."""
    profile = light_profile(a.mode, legs, dep, total_h, sky)
    if not profile:
        return
    bins, glare, dt_min = profile
    rec("LIGHT", "day %s | twilight %s | night %s [derived]" % (
        fmt_hm(bins["day"] / 60.0), fmt_hm(bins["twilight"] / 60.0), fmt_hm(bins["night"] / 60.0)))
    tz = dep.tzinfo
    for g in glare:
        half = timedelta(minutes=dt_min / 2.0)
        rec("GLARE", "%s-%s low sun ahead on leg %d (sun %03.0f deg, %s deg up; heading %03.0f %s)" % (
            (g["start"] - half).astimezone(tz).strftime("%H:%M"), (g["end"] + half).astimezone(tz).strftime("%H:%M"),
            g["leg"], g["az"], trim(g["elev"], 0), g["heading"], compass(g["heading"])))


# ---- places

def cmd_places(a):
    _load()
    if a.add:
        name, lat, lon, zone = a.add
        try:
            lat, lon = float(lat), float(lon)
        except ValueError:
            die("latitude and longitude must be numbers")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            die("coordinates out of range")
        key = fold(a.key or name)
        tzkey = chrono.zone_key(zone)
        chrono.get_tz(zone)
        entry = {"name": name, "lat": round(lat, 4), "lon": round(lon, 4), "tz": tzkey, "kind": a.kind or "city"}
        taken = _places.get(key) or in_gazetteer(key)
        if taken:
            rec("WARNING", "key '%s' already exists (%s); your entry would take its place" % (key, taken.get("name")))
        rec("PASTE", "into \"places\" in %s:" % PERSONAL_FILE)
        print('      "%s": %s' % (key, json.dumps(entry, ensure_ascii=False)))
        close = near(lat, lon, 150.0)[:2] or near(lat, lon, 2000.0)[:2]
        if close:
            rec("NEAREST", ", ".join("%s %s km" % (p["key"], trim(d, 1)) for d, p in close))
        rec("OR", "rebuild --place \"%s: at=%s,%s, tz=%s\" writes a new package with the place already in it" % (
            name, trim(lat, 4), trim(lon, 4), tzkey))
        rec("NEXT", "either way the skill is uploaded again, so the new place is there next time")
        return
    filtered = bool(a.near or a.find or a.kind or a.country)
    total = int(gazetteer_meta("places") or 0)
    if not filtered:
        kinds = counts()
        plural = {"capital": "capitals", "city": "cities and towns", "airport": "airports", "station": "stations", "poi": "other points"}
        rec("PLACES", "%s: %s [gazetteer]" % (num(total), ", ".join(
            "%s %s" % (num(kinds[k]), plural.get(k, k)) for k in KINDS if k in kinds)))
        unset = unset_slots()
        own = [k for k in own_places() if k not in ("home", "work")]
        rec("PERSONAL", "%s; %d places of your own; %d checked legs" % (
            ", ".join("%s %s" % (s, "NOT SET" if s in unset else "set (%s)" % _places[s]["name"]) for s in ("home", "work")),
            len(own), len(_legs)))
        if unset:
            rec("SETUP", "%s: %s" % (" and ".join(unset), SETUP_HINT))
        rec("SOURCE", gazetteer_meta("sources") or "see tools/build_places.py")
        rec("FIND", "places --find TEXT | --near PLACE --km 100 | --kind capital | --country PL | --add NAME LAT LON ZONE")
        return
    want = fold(a.find) if a.find else None
    if a.near:
        _, lat, lon, _ = parse_point(a.near)
        if a.km <= 0:
            die("--km is a radius, more than zero")
        rows = near(lat, lon, a.km, kinds=[a.kind] if a.kind else None)
        if a.country:
            rows = [r for r in rows if (r[1].get("cc") or "").upper() == a.country.upper()]
        if want:
            hits = set(p["key"] for p in select(a.kind, a.country, want))
            rows = [r for r in rows if r[1]["key"] in hits]
    else:
        found = select(a.kind, a.country, want)
        if want:
            # a name that is exactly the text first, then names that start with it, then the rest; notable before obscure
            found.sort(key=lambda p: (0 if (p["key"] == want or fold(p.get("name", "")) == want) else 1 if p["key"].startswith(want) else 2,
                                      p.get("rank", 0), p["key"]))
        rows = [(None, p) for p in found]
    if not rows:
        rec("NONE", "no place matches; 'places --add' prints the line for a place of your own")
        return
    if a.limit < 1:
        die("--limit is at least 1")
    out = []
    for d, p in rows[:a.limit]:
        line = [p["key"], "%.4f" % p["lat"], "%.4f" % p["lon"], p.get("kind", ""), p.get("cc", ""), p.get("tz", "?"),
                p.get("name", "") + (" [%s]" % p["icao"] if p.get("icao") else "")]
        if d is not None:
            line.insert(1, "%s km" % trim(d, 1))
        out.append(line)
    table(out, right=(1, 2, 3) if a.near else (1, 2))
    rec("COUNT", "%d shown of %d matching, %s in all; city points are good to a few km, airports to a few hundred metres [gazetteer]" % (
        len(out), len(rows), num(total + len(own_places()))))


# ---- trip

_SEP = (">", "->", "to", "=>")
_PLUS_RE = re.compile(r"^\+(\d)d?$")


def _parse_side(tokens, default_date, base_date, what):
    """[place, (date | +N)?, time] -> (date, (h, m))."""
    rest = tokens[1:]
    day = default_date
    if len(rest) >= 2:
        m = _PLUS_RE.match(rest[0])
        if m and base_date is not None:
            day = base_date + timedelta(days=int(m.group(1)))
        else:
            day = chrono.parse_date(rest[0], default_date)
            if day is None:
                die("date not understood in trip leg: '%s'" % rest[0])
        rest = rest[1:]
    if len(rest) != 1:
        die("trip leg %s not understood: '%s' (use: PLACE [DATE] HH:MM)" % (what, " ".join(tokens)))
    return day, parse_clock(rest[0])


def _leg_mode(tokens, p1, p2):
    if tokens and tokens[-1].lower() in TRIP_MODES:
        return TRIP_MODES[tokens[-1].lower()], tokens[:-1]
    k1, k2 = (p1[3] or {}).get("kind"), (p2[3] or {}).get("kind")
    if k1 == "airport" and k2 == "airport":
        return "air", tokens
    if k1 == "station" and k2 == "station":
        return "rail", tokens
    return "car", tokens


_SPEED_LIMITS = {"air": (None, None), "rail": (15.0, 330.0), "car": (10.0, 150.0), "bus": (10.0, 130.0),
                 "ferry": (5.0, 80.0), "walk": (1.0, 8.0)}
_MODE_WORD = {"air": "fly", "rail": "rail", "car": "drive", "bus": "bus", "ferry": "ferry", "walk": "walk"}
_LEG_TITLE = {"air": "Flight", "rail": "Train", "car": "Drive", "bus": "Bus", "ferry": "Ferry", "walk": "Walk"}


def cmd_trip(a):
    ref_name = a.ref or chrono.home_label()
    ref_tz = chrono.get_tz(ref_name)
    fallback = a.tz or None
    today = chrono.now_in(chrono.get_tz(a.tz) if a.tz else chrono.home_tz()).date()
    cur_date = chrono.parse_date(a.date, today) if a.date else today
    if cur_date is None:
        die("date not understood: '%s'" % a.date)
    legs, notes = [], []
    for raw in a.legs:
        tokens = raw.replace("->", " > ").replace("=>", " > ").split()
        idx = [i for i, t in enumerate(tokens) if t.lower() in _SEP]
        if len(idx) != 1:
            die("trip leg needs exactly one '>' between departure and arrival: '%s'" % raw)
        left, right = tokens[:idx[0]], tokens[idx[0] + 1:]
        if len(left) < 2 or len(right) < 2:
            die("trip leg not understood: '%s' (use: FROM [DATE] HH:MM > TO [DATE|+1] HH:MM [fly|rail|drive|bus|ferry])" % raw)
        p1 = parse_point(left[0])
        p2 = parse_point(right[0])
        mode, right = _leg_mode(right, p1, p2)
        d1, t1 = _parse_side(left, cur_date, None, "departure")
        tz1, tz2 = place_tz(p1, fallback), place_tz(p2, fallback)
        dep, n1 = chrono.localize(datetime(d1.year, d1.month, d1.day, t1[0], t1[1]), tz1)
        explicit = len(right) >= 3
        d2, t2 = _parse_side(right, d1, d1, "arrival")
        arr, n2 = chrono.localize(datetime(d2.year, d2.month, d2.day, t2[0], t2[1]), tz2)
        bumped = 0
        while not explicit and chrono.to_utc(arr) <= chrono.to_utc(dep) and bumped < 3:
            d2 = d2 + timedelta(days=1)
            arr, n2 = chrono.localize(datetime(d2.year, d2.month, d2.day, t2[0], t2[1]), tz2)
            bumped += 1
        if bumped:
            notes.append("%s -> %s: arrival read as %s (+%d day), since it cannot be before departure" % (
                p1[0], p2[0], d2.isoformat(), bumped))
        for n in (n1, n2):
            if n:
                notes.append(n)
        for p in (p1, p2):
            if not (p[3] or {}).get("tz") and not a.tz:
                notes.append("%s has no zone on file; %s assumed (set --tz)" % (p[0], "home time" if chrono.home_is_set() else "UTC"))
        legs.append({"p1": p1, "p2": p2, "dep": dep, "arr": arr, "mode": mode})
        cur_date = arr.date()

    first, last = legs[0], legs[-1]
    rec("TRIP", "%d timetabled leg%s, %d connection%s | reference zone %s" % (
        len(legs), "" if len(legs) == 1 else "s", len(legs) - 1, "" if len(legs) == 2 else "s", chrono.zone_label(ref_name)))

    door_start = chrono.to_utc(first["dep"])
    door_end = chrono.to_utc(last["arr"])
    entries, guessed = [], False
    if a.home:
        hp = parse_point(a.home)
        s, km, hours, tag, _ = estimate_leg(hp, first["p1"], a.home_mode)
        checkin = a.checkin if a.checkin is not None else (120 if first["mode"] == "air" else 20 if first["mode"] == "rail" else 0)
        be_there = chrono.add(first["dep"], -checkin * 60)
        leave = chrono.to_utc(chrono.add(be_there, -(hours * 3600 + a.margin * 60))).astimezone(place_tz(hp, fallback))
        rec("LEAVE BY", "%s  %s" % (chrono.fmt_dt(leave), hp[0]))
        more("%s %s%s km, %s [%s] + %d min margin; be at %s by %s (%d min before departure)" % (
            _MODE_WORD.get(a.home_mode, a.home_mode), "~" if tag == "estimate" else "", num(km), fmt_hm(hours), tag, a.margin,
            first["p1"][0], be_there.strftime("%H:%M"), checkin))
        door_start = chrono.to_utc(leave)
        guessed = guessed or tag == "estimate"
        entries.append(("Leave for %s" % first["p1"][0], leave, be_there, hp[0],
                        "Leave %s by %s.\n%s %s%s km, %s [%s], plus %d min margin.\nBe at %s by %s, %d min before departure." % (
                            hp[0], chrono.fmt_dt(leave), _MODE_WORD.get(a.home_mode, a.home_mode).capitalize(),
                            "~" if tag == "estimate" else "", num(km), fmt_hm(hours), tag, a.margin,
                            first["p1"][0], be_there.strftime("%H:%M"), checkin)))

    moving = {}
    wait_s = 0.0
    for i, leg in enumerate(legs, 1):
        p1, p2, dep, arr, mode = leg["p1"], leg["p2"], leg["dep"], leg["arr"], leg["mode"]
        dur_h = (chrono.to_utc(arr) - chrono.to_utc(dep)).total_seconds() / 3600.0
        gc = haversine_km(p1[1], p1[2], p2[1], p2[2])
        moving[mode] = moving.get(mode, 0.0) + dur_h
        speed = gc / dur_h if dur_h > 0 else 0.0
        days = (arr.date() - dep.date()).days
        day_mark = "" if days == 0 else " (%+d day)" % days
        rec("LEG %d" % i, "%s %s -> %s %s%s | %s | %s km | %s, avg %s km/h" % (
            p1[0], chrono.fmt_short(dep), p2[0], chrono.fmt_short(arr), day_mark, fmt_hm(dur_h), num(gc),
            _MODE_WORD.get(mode, mode), num(speed)))
        entries.append(("%s: %s to %s" % (_LEG_TITLE.get(mode, mode.capitalize()), p1[0], p2[0]), dep, arr, p1[0],
                        "Departs %s, %s.\nArrives %s, %s.\nTimes as given: check them with the carrier." % (
                            chrono.fmt_dt(dep), p1[0], chrono.fmt_dt(arr), p2[0])))
        problem = None
        if dur_h <= 0:
            problem = "arrives before it departs: check the dates and zones"
        elif mode == "air":
            expect = gc / 830.0 + 0.6
            if dur_h < 0.6 * expect or dur_h > 1.7 * expect:
                problem = "a flight of %s km should take about %s, not %s: check times, dates and zones" % (
                    num(gc), fmt_hm(expect), fmt_hm(dur_h))
        else:
            lo, hi = _SPEED_LIMITS.get(mode, (None, None))
            if gc > 5 and hi and speed > hi:
                problem = "%s km/h is too fast for %s: check times, dates and zones" % (num(speed), _MODE_WORD.get(mode, mode))
            elif gc > 5 and lo and speed < lo:
                problem = "%s km/h is very slow for %s: check times and dates" % (trim(speed, 1), _MODE_WORD.get(mode, mode))
        if problem:
            rec("CHECK", "leg %d: %s" % (i, problem))
        if i < len(legs):
            nxt = legs[i]
            gap_s = (chrono.to_utc(nxt["dep"]) - chrono.to_utc(arr)).total_seconds()
            wait_s += max(0.0, gap_s)
            moved = haversine_km(p2[1], p2[2], nxt["p1"][1], nxt["p1"][2])
            where = p2[0] if moved < 1.0 else "%s -> %s (%s km apart: needs a transfer)" % (p2[0], nxt["p1"][0], trim(moved, 0))
            need = a.min_connect
            if gap_s < 0:
                state = "IMPOSSIBLE: next leg leaves %s before this one arrives" % fmt_hm(-gap_s / 3600.0)
            elif gap_s < need * 60:
                state = "TIGHT: under %d min" % need
            elif gap_s > 8 * 3600:
                state = "long: time for a meal and a walk"
            else:
                state = "ok"
            rec("CONNECT", "%s %s (minimum set: %d min) %s" % (where, fmt_hm(gap_s / 3600.0), need, state))

    rec("ARRIVE", "%s  %s" % (chrono.fmt_dt(last["arr"]), last["p2"][0]))
    ref_arr = chrono.to_utc(last["arr"]).astimezone(ref_tz)
    if ref_arr.utcoffset() != last["arr"].utcoffset():
        more("%s  (%s time)" % (chrono.fmt_dt(ref_arr), chrono.zone_label(ref_name).lower()))
    if a.onward:
        op = parse_point(a.onward)
        s, km, hours, tag, _ = estimate_leg(last["p2"], op, a.home_mode)
        exit_min = a.exit if a.exit is not None else (45 if last["mode"] == "air" else 10 if last["mode"] == "rail" else 0)
        onward_tz = place_tz(op, (last["p2"][3] or {}).get("tz") or fallback)
        there = chrono.to_utc(chrono.add(last["arr"], exit_min * 60 + hours * 3600)).astimezone(onward_tz)
        rec("ONWARD", "%s  %s" % (chrono.fmt_dt(there), op[0]))
        more("%d min to get out + %s %s%s km, %s [%s]" % (
            exit_min, _MODE_WORD.get(a.home_mode, a.home_mode), "~" if tag == "estimate" else "", num(km), fmt_hm(hours), tag))
        door_end = chrono.to_utc(there)
        guessed = guessed or tag == "estimate"
        entries.append(("Onward to %s" % op[0], last["arr"], there, last["p2"][0],
                        "%d min to get out, then %s %s%s km, %s [%s].\nThere by %s." % (
                            exit_min, _MODE_WORD.get(a.home_mode, a.home_mode), "~" if tag == "estimate" else "", num(km),
                            fmt_hm(hours), tag, chrono.fmt_dt(there))))
    total_h = (door_end - door_start).total_seconds() / 3600.0
    parts = ["%s %s" % (_MODE_WORD.get(m, m), fmt_hm(h)) for m, h in moving.items()]
    rec("TOTAL", "%s %s | %s | waiting %s" % (
        "door to door" if (a.home or a.onward) else "first departure to last arrival", fmt_hm(total_h),
        ", ".join(parts), fmt_hm(wait_s / 3600.0)))
    shift = chrono.offset_hours(last["arr"]) - chrono.offset_hours(chrono.to_utc(last["arr"]).astimezone(first["dep"].tzinfo))
    if abs(shift) >= 1:
        body = chrono.to_utc(last["arr"]).astimezone(first["dep"].tzinfo)
        way = "east" if shift > 0 else "west"
        days = abs(shift) if shift > 0 else abs(shift) / 1.5
        rec("SHIFT", "%s (%s): body clock says %s on arrival, local says %s" % (
            chrono.fmt_delta_h(shift), way, body.strftime("%H:%M"), last["arr"].strftime("%H:%M")))
        more("allow about %s days to adjust [rule of thumb: a day per zone eastbound, less westbound]" % trim(days, 0))
    for n in dict.fromkeys(notes):
        rec("NOTE", n)
    rec("NOTE", "timetable times are as given; check them against the carrier before relying on this")
    if a.ics:
        entries.sort(key=lambda e: chrono.to_utc(e[1]))
        out = []
        for n, (title, start, end, where, text) in enumerate(entries):
            out.append(ical.event(title, start, end, location=where, description=text, alarm=ical.alarm_of(a) if n == 0 else None))
        ical.deliver(a, out, "trip-%s" % first["dep"].date().isoformat(), estimate=guessed)


def register(sub):
    p = command(sub, "ground", "route", cmd_route,
                "legs, bearings, travel time, breaks, buffer, ETA, daylight, low-sun glare, a live-map link, a calendar file",
                ['route krakow ktw --depart "2026-11-12 05:30"', 'route krakow ktw --arrive "2026-11-12 04:40"',
                 "route warsaw krakow --mode car --firn", "route waw cdg jfk --mode air",
                 "route 50.2599,19.0216 -33.87,151.21 --mode air",
                 'route krakow ktw --arrive "2026-11-12 04:40" --ics auto',
                 "route krakow gdansk --window 05:00-11:00 --date 2026-12-05 --before-dark"])
    p.add_argument("points", nargs="+", help="gazetteer places (key, name, alias or airport code), home, work, or lat,lon")
    p.add_argument("--mode", default="car", choices=sorted(MODES),
                   help="car 80 km/h, motorway 105, city 30, bike 18, walk 4.8, rail 90, air 800 (averages)")
    p.add_argument("--speed", type=float, help="average km/h, overrides the mode")
    p.add_argument("--road", type=float, help="travel distance / straight distance, overrides the mode (car 1.25)")
    p.add_argument("--break-every", type=float, help="hours between breaks (car 2; 0 for none)")
    p.add_argument("--break-min", type=int, help="minutes per break (car 15)")
    p.add_argument("--buffer", type=float, help="percent added on top (car 10)")
    p.add_argument("--depart", help="departure, as for 'time', in the origin's own zone")
    p.add_argument("--arrive", help="plan backwards: be there by this time, in the destination's own zone")
    p.add_argument("--window", metavar="HH:MM-HH:MM", help="choose the departure for me: the one with least night driving and low sun")
    p.add_argument("--date", help="the day for --window (default today, or tomorrow once the window has passed)")
    p.add_argument("--step", type=int, default=15, help="minutes between the departures tried in --window (default 15)")
    p.add_argument("--before-dark", action="store_true", help="with --window: only departures that arrive before sunset")
    p.add_argument("--tz", help="zone for points that have none (raw coordinates)")
    p.add_argument("--firn", action="store_true", help="also budget the leg against FIRN-01 lore range")
    ical.add_option(p, "the journey")

    p = command(sub, "ground", "trip", cmd_trip,
                "timetabled legs in local times: connections, leave-by, door to door, time shift, a calendar file",
                ['trip "waw 2026-12-18 06:40 > cdg 09:05" "cdg 10:50 > jfk 13:10" --home warsaw --onward new_york',
                 'trip "krakow 08:02 > warsaw 10:28 rail" --date 2026-11-20',
                 'trip "krakow 08:02 > warsaw 10:28 rail" --date 2026-11-20 --home krakow --ics auto'])
    p.add_argument("legs", nargs="+",
                   help='"FROM [DATE] HH:MM > TO [DATE|+1] HH:MM [fly|rail|drive|bus|ferry]", each in its own local time')
    p.add_argument("--date", help="date of the first departure when the leg gives none (default today)")
    p.add_argument("--home", help="start from here: adds the drive and a leave-by time")
    p.add_argument("--home-mode", default="car", choices=sorted(MODES), help="mode for the home and onward legs (default car)")
    p.add_argument("--checkin", type=int, help="minutes to be there before the first departure (fly 120, rail 20)")
    p.add_argument("--margin", type=int, default=15, help="extra minutes on the home leg (default 15)")
    p.add_argument("--onward", help="finish here: adds the ground leg after the last arrival")
    p.add_argument("--exit", type=int, help="minutes to get out after the last arrival (fly 45, rail 10)")
    p.add_argument("--min-connect", type=int, default=60, help="connections under this many minutes are flagged (default 60)")
    p.add_argument("--ref", help="reference zone for the arrival (default home)")
    p.add_argument("--tz", help="zone for places that have none")
    ical.add_option(p, "every leg")

    p = command(sub, "ground", "places", cmd_places, "the gazetteer: what is in it, search, nearest, or print a new entry of your own",
                ["places", "places --find krak", "places --near warsaw --km 60", "places --kind capital --country PL",
                 'places --add "Ustron" 49.7215 18.8020 Europe/Warsaw'])
    p.add_argument("--find", help="text to look for in keys, names and aliases")
    p.add_argument("--near", help="place or lat,lon to measure from")
    p.add_argument("--km", type=float, default=100.0, help="radius for --near (default 100)")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--country", help="two-letter country code, e.g. PL")
    p.add_argument("--limit", type=int, default=40, help="rows to show (default 40)")
    p.add_argument("--add", nargs=4, metavar=("NAME", "LAT", "LON", "ZONE"), help="print the places.json line for a place of your own")
    p.add_argument("--key", help="key for --add (default: from the name)")
