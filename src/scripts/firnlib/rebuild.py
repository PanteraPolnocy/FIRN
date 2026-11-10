"""The driver's own file: a one-pass check of it, and a rebuilt copy of the skill with their changes in it.

setup    reads the personal file once and says exactly what to fix, instead of failing when a bad field is first used.
rebuild  applies what the driver asked for (home, a place, a checked road figure, a log line, a vehicle, kit) and writes
         a new skill package for them to upload, so nobody edits JSON by hand. The package that is running is never
         touched, except with --in-place, which is for a driver who asks for it and owns the folder.

Ignition questions are passed through untouched and never printed: FIRN does not handle the answers.
"""
import contextlib
import json
import os
import re
from datetime import datetime

from . import chrono, core, geo, service
from .core import (DATA, LOG_TYPES, PERSONAL_FILE, SCRIPTS, FirnError, command, die, driver, fold, more, num, out_folder, personal,
                   rec, trim)

KNOWN = ("note", "driver", "home", "work", "zones", "zone_aliases", "places", "legs", "ignition", "vehicles", "first_boot",
         "logbook", "family", "pending", "kit", "help")
SETTINGS = ("every new conversation", "when it matters", "off")
LOG_RE = re.compile(r"^LOG\s+(\d{4}-\d{2}-\d{2})\s*\|\s*([a-z]+)\s*\|\s*[^|]+\|\s*[^|]+$")
SKIP_DIRS = ("__pycache__",)


def _reset_caches():
    geo._places = None
    geo._index = None
    chrono._tz_cache.clear()


@contextlib.contextmanager
def using(data):
    """Run with another personal file in force (a candidate being checked), then put the real one back."""
    old = core._personal
    core._personal = data
    _reset_caches()
    try:
        yield
    finally:
        core._personal = old
        _reset_caches()


def personal_path():
    return os.environ.get("FIRN_PERSONAL") or os.path.join(DATA, "personal.json")


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _zone_problem(name):
    try:
        chrono.get_tz(name)
        return None
    except FirnError as e:
        return str(e)


def _a_day(text):
    """A date, or None if the text is not one (never an error: this is the checker)."""
    try:
        return chrono.parse_date(str(text))
    except FirnError:
        return None


def _pairs(data, key, out):
    rows = data.get(key)
    if rows in (None, []):
        return
    if not isinstance(rows, list):
        out.append(("FIX", key, "must be a list of [what, note] pairs"))
        return
    for n, row in enumerate(rows, 1):
        if not (isinstance(row, list) and 1 <= len(row) <= 2 and all(isinstance(x, str) for x in row)):
            out.append(("FIX", "%s.%d" % (key, n), "each entry is a pair of texts: [what, note]"))


def validate(data, today):
    """Every problem in a personal file, in one pass: [(FIX or CHECK, where, what to do)]."""
    out = []
    if not isinstance(data, dict):
        return [("FIX", "file", "the file must be one JSON object: { ... }")]
    for key in data:
        if key not in KNOWN:
            import difflib
            near = difflib.get_close_matches(key, KNOWN, n=1, cutoff=0.6)
            out.append(("CHECK", key, "not a field FIRN reads%s; it is ignored" % (": did you mean '%s'?" % near[0] if near else "")))
    if not isinstance(data.get("driver", ""), str):
        out.append(("FIX", "driver", "must be text, the name FIRN's tools print"))
    with using(data):
        for slot in ("home", "work"):
            p = data.get(slot)
            if p is None:
                continue
            if not isinstance(p, dict):
                out.append(("FIX", slot, "must be an object with name, lat, lon and tz"))
                continue
            lat, lon = p.get("lat"), p.get("lon")
            if lat is None and lon is None:
                continue
            if not (_is_num(lat) and _is_num(lon)):
                out.append(("FIX", slot, "lat and lon must both be numbers in decimal degrees (or both null)"))
            elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
                out.append(("FIX", slot, "coordinates out of range: latitude is -90 to 90, longitude -180 to 180"))
            if not p.get("tz"):
                out.append(("FIX", slot + ".tz", "missing: without a zone, %s counts as not set (use a name such as Europe/Warsaw)" % slot))
            else:
                bad = _zone_problem(p["tz"])
                if bad:
                    out.append(("FIX", slot + ".tz", bad))
        zones = data.get("zones")
        if zones is not None:
            if not isinstance(zones, list):
                out.append(("FIX", "zones", "must be a list of zone names, aliases or places"))
            else:
                for z in zones:
                    if str(z).lower() == "home" and not chrono.home_is_set():
                        continue
                    bad = _zone_problem(z)
                    if bad:
                        out.append(("FIX", "zones", bad))
        for name, zone in (data.get("zone_aliases") or {}).items():
            bad = _zone_problem(zone)
            if bad:
                out.append(("FIX", "zone_aliases.%s" % name, bad))
        places = data.get("places") or {}
        if not isinstance(places, dict):
            out.append(("FIX", "places", "must be an object of key: {name, lat, lon, tz}"))
            places = {}
        for key, p in places.items():
            where = "places.%s" % key
            if not isinstance(p, dict) or not (_is_num(p.get("lat")) and _is_num(p.get("lon"))):
                out.append(("FIX", where, "needs lat and lon as numbers"))
                continue
            if not (-90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180):
                out.append(("FIX", where, "coordinates out of range"))
            if p.get("tz"):
                bad = _zone_problem(p["tz"])
                if bad:
                    out.append(("FIX", where + ".tz", bad))
            else:
                out.append(("CHECK", where, "no tz: times there will be read as home time"))
            if p.get("kind") and p["kind"] not in geo.KINDS:
                out.append(("CHECK", where, "kind '%s' is not one of %s" % (p["kind"], ", ".join(geo.KINDS))))
            shadowed = geo.in_gazetteer(fold(key))
            if shadowed:
                # the driver's own pin for a town the gazetteer also has is the usual case, and wants no remark;
                # the same key for somewhere else entirely is worth one
                apart = geo.haversine_km(p["lat"], p["lon"], shadowed["lat"], shadowed["lon"])
                if apart > 30.0:
                    out.append(("CHECK", where, "takes the place of the gazetteer's %s, which is %s km from it: routes by that name "
                                                "now go to yours" % (shadowed.get("name", key), num(apart))))
        legs = data.get("legs") or {}
        if not isinstance(legs, dict):
            out.append(("FIX", "legs", "must be an object of \"from>to\": {km, min, ...}"))
            legs = {}
        for key, leg in legs.items():
            where = "legs.%s" % key
            ends = key.split(">")
            if len(ends) != 2 or not isinstance(leg, dict):
                out.append(("FIX", where, "a leg is \"from>to\": {\"km\": 32, \"min\": 32}"))
                continue
            pts = [geo.find_place(e) for e in ends]
            if not all(pts):
                missing = [e for e, p in zip(ends, pts) if not p]
                out.append(("FIX", where, "unknown place: %s (a leg joins two places FIRN knows, by key)" % ", ".join(missing)))
                continue
            if not (_is_num(leg.get("km")) and leg["km"] > 0):
                out.append(("FIX", where, "km must be a number above zero"))
                continue
            if leg.get("min") is not None and not (_is_num(leg["min"]) and leg["min"] > 0):
                out.append(("FIX", where, "min, if given, must be a number above zero"))
            straight = geo.haversine_km(pts[0]["lat"], pts[0]["lon"], pts[1]["lat"], pts[1]["lon"])
            if leg["km"] < straight * 0.98:
                out.append(("CHECK", where, "%s km is shorter than the straight line (%s km): one of the figures is off" % (
                    trim(leg["km"], 1), trim(straight, 1))))
            elif straight > 1 and leg["km"] > straight * 4:
                out.append(("CHECK", where, "%s km is over four times the straight line (%s km): is that right?" % (
                    trim(leg["km"], 1), trim(straight, 1))))
            if _is_num(leg.get("min")) and leg["min"] > 0 and not 5 <= leg["km"] / (leg["min"] / 60.0) <= 160:
                out.append(("CHECK", where, "%s km in %s min is %s km/h: is that right?" % (
                    trim(leg["km"], 1), trim(leg["min"], 0), trim(leg["km"] / (leg["min"] / 60.0), 0))))
            if leg.get("checked") and _a_day(leg["checked"]) is None:
                out.append(("CHECK", where, "checked should be a date, YYYY-MM-DD"))
    ign = data.get("ignition")
    if ign is not None:
        if not isinstance(ign, dict):
            out.append(("FIX", "ignition", "must be an object: {\"setting\": ..., \"questions\": [...]}"))
        else:
            setting = str(ign.get("setting") or "").strip().lower()
            good = 0
            for n, q in enumerate(ign.get("questions") or [], 1):
                answers = q.get("a") if isinstance(q, dict) else None
                if isinstance(answers, str):
                    answers = [answers]
                if not (isinstance(q, dict) and isinstance(q.get("q"), str) and q["q"].strip() and isinstance(answers, list)
                        and answers and all(isinstance(x, str) and x.strip() for x in answers)):
                    out.append(("FIX", "ignition.questions.%d" % n, "needs \"q\" (the question) and \"a\" (a list of accepted answers)"))
                else:
                    good += 1
            if setting and setting not in SETTINGS:
                import difflib
                near = difflib.get_close_matches(setting, SETTINGS, n=1, cutoff=0.4)
                out.append(("FIX", "ignition.setting", "must be one of: %s%s" % ("; ".join(SETTINGS), " (did you mean '%s'?)" % near[0] if near else "")))
            if setting in SETTINGS[:2] and not good:
                out.append(("CHECK", "ignition", "the check is switched on but there are no questions, so it stays off"))
            elif 0 < good < 3 and setting != "off":
                out.append(("CHECK", "ignition", "%d question%s on file: three are asked before FIRN gives up, so add more" % (
                    good, "" if good == 1 else "s")))
    vehicles = data.get("vehicles")
    if vehicles not in (None, []):
        if not isinstance(vehicles, list):
            out.append(("FIX", "vehicles", "must be a list of vehicles ('service --template' prints one)"))
        else:
            for n, v in enumerate(vehicles, 1):
                where = "vehicles.%s" % (v.get("name") if isinstance(v, dict) and v.get("name") else n)
                if not isinstance(v, dict):
                    out.append(("FIX", where, "must be an object with a name and items"))
                    continue
                try:
                    _, rows = service.assess_vehicle(v, today, 30)
                    for r in rows:
                        if r["status"] == "unknown":
                            out.append(("CHECK", where, r["text"]))
                    on = _a_day((v.get("odometer") or {}).get("on") or "")
                    if on and on > today:
                        out.append(("CHECK", where, "the odometer reading is dated in the future"))
                except FirnError as e:
                    out.append(("FIX", where, str(e)))
    first = data.get("first_boot")
    if first:
        day = _a_day(first)
        if day is None:
            out.append(("FIX", "first_boot", "must be a date, YYYY-MM-DD, or empty"))
        elif day > today:
            out.append(("CHECK", "first_boot", "is in the future"))
    logbook = data.get("logbook")
    if logbook not in (None, []):
        if not isinstance(logbook, list):
            out.append(("FIX", "logbook", "must be a list of log lines"))
        else:
            for n, line in enumerate(logbook, 1):
                m = LOG_RE.match(str(line).strip())
                if not m:
                    out.append(("CHECK", "logbook.%d" % n, "not in the form  LOG YYYY-MM-DD | type | what happened | one lesson"))
                elif m.group(2) not in LOG_TYPES:
                    out.append(("CHECK", "logbook.%d" % n, "type '%s' is not one of %s" % (m.group(2), ", ".join(LOG_TYPES))))
    for key in ("family", "pending", "kit"):
        _pairs(data, key, out)
    return out


def summary(data):
    """One line of what is on file. Counts only: nothing private is printed."""
    ign = data.get("ignition") or {}
    parts = [
        "%d clock%s" % (len(data.get("zones") or []), "" if len(data.get("zones") or []) == 1 else "s"),
        "%d place%s" % (len(data.get("places") or {}), "" if len(data.get("places") or {}) == 1 else "s"),
        "%d checked leg%s" % (len(data.get("legs") or {}), "" if len(data.get("legs") or {}) == 1 else "s"),
        "%d ignition question%s (%s)" % (len(ign.get("questions") or []), "" if len(ign.get("questions") or []) == 1 else "s",
                                         ign.get("setting") or "off"),
        "%d vehicle%s" % (len(data.get("vehicles") or []), "" if len(data.get("vehicles") or []) == 1 else "s"),
        "%d log line%s" % (len(data.get("logbook") or []), "" if len(data.get("logbook") or []) == 1 else "s"),
        "%d kept, %d pending kit" % (len(data.get("kit") or []), len(data.get("pending") or [])),
    ]
    return ", ".join(parts)


def _slot_text(data, slot):
    p = data.get(slot) or {}
    if p.get("lat") is None or p.get("lon") is None or not p.get("tz"):
        return "NOT SET"
    return "%s (%s, %s; %s)" % (p.get("name") or slot.title(), trim(p["lat"], 4), trim(p["lon"], 4), p["tz"])


def _print_findings(findings):
    for level, where, text in findings:
        rec(level, "%s: %s" % (where, text))


def cmd_setup(a):
    data = personal()
    today = chrono.now_in(chrono.home_tz()).date()
    path = os.environ.get("FIRN_PERSONAL")
    rec("SETUP", "personal file: %s" % ("%s (from FIRN_PERSONAL)" % path if path else PERSONAL_FILE))
    rec("DRIVER", driver())
    rec("HOME", _slot_text(data, "home"))
    rec("WORK", _slot_text(data, "work"))
    rec("ON FILE", summary(data))
    findings = validate(data, today)
    _print_findings(findings)
    fixes = sum(1 for f in findings if f[0] == "FIX")
    checks = len(findings) - fixes
    unset = [s for s in ("home", "work") if _slot_text(data, s) == "NOT SET"]
    if fixes or checks:
        rec("RESULT", "%d to fix, %d to check" % (fixes, checks))
    else:
        rec("RESULT", "nothing to fix%s" % ("; %s still to set" % " and ".join(unset) if unset else ""))
    rec("NEXT", "to change any of it without editing the file: rebuild --home PLACE --work PLACE ... writes a new package to upload "
                "('rebuild -h' lists what it can set)")
    if fixes:
        raise SystemExit(1)


# ---- rebuild

def _kv(text, what, keys):
    """'Name: a=1, b=2' -> (name, {a: '1', b: '2'})."""
    name, sep, body = str(text).partition(":")
    if not sep or not name.strip():
        die("%s looks like  \"Name: key=value, key=value\"  (keys: %s)" % (what, ", ".join(keys)))
    out, last = {}, None
    for part in body.split(","):
        if not part.strip():
            continue
        key, eq, val = part.partition("=")
        key = key.strip().lower().replace("-", "_")
        if not eq and last and re.match(r"^\s*-?\d+(\.\d+)?\s*$", part):
            out[last] += "," + part.strip()        # the second half of a LAT,LON pair
            continue
        if not eq or key not in keys or not val.strip():
            die("could not read '%s' in %s (keys: %s)" % (part.strip(), what, ", ".join(keys)))
        out[key] = val.strip()
        last = key
    return name.strip(), out


def _number(text, what):
    try:
        return service._whole(float(str(text).replace(" ", "")))
    except ValueError:
        die("%s must be a number: '%s'" % (what, text))


def _nearest_zone(lat, lon):
    return geo.nearest(lat, lon, 300.0, lambda p: bool(p.get("tz")))


def _point_entry(text, name, tz, old, what, notes):
    """A home, work or place entry from a place name or 'lat,lon'."""
    label, lat, lon, place = geo.parse_point(text)
    zone = tz or (place or {}).get("tz")
    if not zone:
        near = _nearest_zone(lat, lon)
        if not near or near[0] > 300:
            die("%s: give its time zone too (for example Europe/Warsaw); nothing on file is near enough to take it from" % what)
        zone = near[1]["tz"]
        notes.append("%s: zone %s taken from %s, %s km away; say if that is wrong" % (what, zone, near[1].get("name"), trim(near[0], 0)))
    chrono.get_tz(zone)
    entry = dict(old or {})
    entry.update({"name": name or (old or {}).get("name") or (label if place else what.title()), "lat": round(lat, 4),
                  "lon": round(lon, 4), "tz": chrono.zone_key(zone)})
    return entry


def _find(rows, text, what):
    """The index of the one entry whose first field matches the text."""
    want = fold(text)
    hits = [n for n, row in enumerate(rows) if want in fold(row[0] if isinstance(row, list) else row.get("name", ""))]
    exact = [n for n in hits if fold(rows[n][0] if isinstance(rows[n], list) else rows[n].get("name", "")) == want]
    hits = exact or hits
    if len(hits) != 1:
        die("%s: '%s' matches %s on file" % (what, text, "nothing" if not hits else "more than one entry"))
    return hits[0]


def apply_changes(data, a, today):
    """The personal data with the requested changes applied, the list of changes, and notes worth passing on."""
    new = json.loads(json.dumps(data))
    changes, notes = [], []
    if a.driver:
        new["driver"] = a.driver.strip()
        changes.append("driver: %s" % new["driver"])
    for slot, text, name, tz in (("home", a.home, a.home_name, a.home_tz), ("work", a.work, a.work_name, a.work_tz)):
        if text:
            new[slot] = _point_entry(text, name, tz, None, slot, notes)
            if name is None:
                new[slot]["name"] = (data.get(slot) or {}).get("name") or slot.title()
            changes.append("%s: %s" % (slot, _slot_text(new, slot)))
    if a.zones:
        new["zones"] = [z for z in a.zones]
        changes.append("clocks: %s" % ", ".join(new["zones"]))
    for spec in a.alias or []:
        name, eq, zone = spec.partition("=")
        if not eq or not name.strip() or not zone.strip():
            die("--alias is NAME=ZONE, for example gran=America/Chicago")
        chrono.get_tz(zone.strip())
        new.setdefault("zone_aliases", {})[name.strip().lower()] = chrono.zone_key(zone.strip())
        changes.append("alias: %s = %s" % (name.strip().lower(), chrono.zone_key(zone.strip())))
    for spec in a.place or []:
        name, kv = _kv(spec, "--place", ("at", "tz", "kind", "aka", "key"))
        if "at" not in kv:
            die("--place needs at=PLACE or at=LAT,LON:  \"The cabin: at=49.2992,19.9496, tz=Europe/Warsaw\"")
        key = fold(kv.get("key") or name)
        entry = _point_entry(kv["at"], name, kv.get("tz"), None, "place %s" % name, notes)
        entry["kind"] = kv.get("kind") or "poi"
        if kv.get("aka"):
            entry["aka"] = [x.strip() for x in kv["aka"].split("|") if x.strip()]
        new.setdefault("places", {})[key] = entry
        changes.append("place: %s = %s (%s, %s; %s)" % (key, name, trim(entry["lat"], 4), trim(entry["lon"], 4), entry["tz"]))
    for spec in a.leg or []:
        key, kv = _kv(spec, "--leg", ("km", "min", "via", "source", "checked", "oneway"))
        if key.count(">") != 1 or "km" not in kv:
            die("--leg is  \"from>to: km=32, min=32, via=S1, source=live map\"")
        ends = [e.strip() for e in key.split(">")]
        with using(new):
            pts = [geo.parse_point(e) for e in ends]
        if not all(p[3] for p in pts):
            die("a checked leg joins two places on file, by name: add the place first (--place)")
        leg = {"km": _number(kv["km"], "km")}
        if "min" in kv:
            leg["min"] = _number(kv["min"], "min")
        for k in ("via", "source"):
            if k in kv:
                leg[k] = kv[k]
        leg["checked"] = service._a_date(kv.get("checked", "today"), "checked", today).isoformat()
        if kv.get("oneway", "").lower() in ("yes", "true", "1"):
            leg["oneway"] = True
        legkey = "%s>%s" % (pts[0][3]["key"], pts[1][3]["key"])
        new.setdefault("legs", {})[legkey] = leg
        changes.append("checked leg: %s = %s km%s" % (legkey, trim(leg["km"], 1), ", %s min" % trim(leg["min"], 0) if "min" in leg else ""))
    for line in a.log or []:
        line = " ".join(str(line).split())
        m = LOG_RE.match(line)
        if not m or m.group(2) not in LOG_TYPES:
            die("--log takes a line as 'log' prints it:  LOG 2026-11-08 | sim | what happened | one lesson")
        if line not in (new.get("logbook") or []):
            new.setdefault("logbook", []).append(line)
            changes.append("log line kept: %s" % line[4:])
    for spec in a.vehicle or []:
        name, kv = _kv(spec + ("" if ":" in spec else ":"), "--vehicle", ("odo", "on", "km_year"))
        fleet = new.setdefault("vehicles", [])
        hits = [v for v in fleet if fold(v.get("name", "")) == fold(name)]
        v = hits[0] if hits else {"name": name, "items": []}
        if not hits:
            fleet.append(v)
        if "odo" in kv:
            v["odometer"] = {"km": _number(kv["odo"], "odo"), "on": service._a_date(kv.get("on", "today"), "on", today).isoformat()}
        if "km_year" in kv:
            v["km_per_year"] = _number(kv["km_year"], "km_year")
        changes.append("vehicle: %s%s" % (v["name"], "" if hits else " (new)"))
    for spec in a.item or []:
        head, sep, body = spec.partition(":")
        fleet = new.get("vehicles") or []
        if "/" in head:
            vname, _, what = head.partition("/")
            v = fleet[_find(fleet, vname.strip(), "--item")]
        elif len(fleet) == 1:
            v, what = fleet[0], head
        else:
            die("--item is  \"VEHICLE / what: last=..., every=...\"  (say which vehicle: there %s on file)" % (
                "is none" if not fleet else "are several"))
        item = service.item_from_text("%s:%s" % (what.strip(), body))
        items = v.setdefault("items", [])
        same = [n for n, it in enumerate(items) if fold(it.get("what", "")) == fold(item["what"])]
        if same:
            items[same[0]] = item
        else:
            items.append(item)
        changes.append("service item: %s / %s%s" % (v["name"], item["what"], " (replaced)" if same else ""))
    for key, specs in (("pending", a.pending), ("family", a.family)):
        for spec in specs or []:
            what, sep, note = spec.partition(":")
            if not what.strip():
                die("--%s is  \"what: note\"" % key)
            new.setdefault(key, []).append([what.strip(), note.strip() or ("said once in a sim" if key == "pending" else "")])
            changes.append("%s: %s" % (key, what.strip()))
    for text in a.keep or []:
        rows = new.get("pending") or []
        n = _find(rows, text, "--keep")
        row = rows.pop(n)
        new.setdefault("kit", []).append([row[0], "kept %s" % today.isoformat()])
        changes.append("kit kept: %s (it is on the fit list from now on)" % row[0])
    for text in a.purge or []:
        rows = new.get("pending") or []
        n = _find(rows, text, "--purge")
        changes.append("kit purged: %s" % rows.pop(n)[0])
    if a.first_boot:
        new["first_boot"] = service._a_date(a.first_boot, "--first-boot", today).isoformat()
        changes.append("first boot: %s" % new["first_boot"])
    if a.ignition:
        setting = a.ignition.strip().lower()
        if setting not in SETTINGS:
            die("--ignition is one of: %s" % "; ".join(SETTINGS))
        new.setdefault("ignition", {"questions": []})["setting"] = setting
        changes.append("ignition: %s" % setting)
    for path in a.drop or []:
        section, _, key = path.partition(".")
        section = section.strip().lower()
        if section in ("home", "work") and not key:
            new[section] = {"name": section.title(), "lat": None, "lon": None, "tz": ""}
        elif section in ("places", "legs", "zone_aliases") and key:
            store = new.get(section) or {}
            hit = [k for k in store if fold(k) == fold(key) or k == key]
            if not hit:
                die("--drop %s: nothing by that name under %s" % (path, section))
            del store[hit[0]]
        elif section in ("vehicles", "pending", "kit", "family") and key:
            rows = new.get(section) or []
            rows.pop(_find(rows, key, "--drop %s" % path))
        elif section == "logbook" and key.isdigit():
            rows = new.get("logbook") or []
            if not 1 <= int(key) <= len(rows):
                die("--drop %s: there %s %d log line%s on file" % (path, "is" if len(rows) == 1 else "are", len(rows), "" if len(rows) == 1 else "s"))
            rows.pop(int(key) - 1)
        else:
            die("--drop takes home, work, places.KEY, legs.FROM>TO, zone_aliases.NAME, vehicles.NAME, pending.NAME, kit.NAME, "
                "family.NAME or logbook.N")
        changes.append("dropped: %s" % path)
    return new, changes, notes


def dump_personal(data):
    """The personal file as text: one entry to a line where there are many, so it stays readable."""
    def j(x):
        return json.dumps(x, ensure_ascii=False)

    lines = ["{"]
    keys = list(data)
    for n, key in enumerate(keys):
        v = data[key]
        comma = "," if n < len(keys) - 1 else ""
        if isinstance(v, dict) and v and key in ("places", "legs", "help", "zone_aliases"):
            lines.append("  %s: {" % j(key))
            items = list(v.items())
            for m, (k2, v2) in enumerate(items):
                lines.append("    %s: %s%s" % (j(k2), j(v2), "," if m < len(items) - 1 else ""))
            lines.append("  }" + comma)
        elif key == "ignition" and isinstance(v, dict) and v.get("questions"):
            rest = [(k2, v2) for k2, v2 in v.items() if k2 != "questions"]
            lines.append("  %s: {" % j(key))
            for k2, v2 in rest:
                lines.append("    %s: %s," % (j(k2), j(v2)))
            lines.append('    "questions": [')
            for m, q in enumerate(v["questions"]):
                lines.append("      %s%s" % (j(q), "," if m < len(v["questions"]) - 1 else ""))
            lines.append("    ]")
            lines.append("  }" + comma)
        elif key == "vehicles" and isinstance(v, list) and v:
            lines.append("  %s: [" % j(key))
            for m, veh in enumerate(v):
                head = ", ".join("%s: %s" % (j(k2), j(v2)) for k2, v2 in veh.items() if k2 != "items")
                items = veh.get("items") or []
                lines.append("    {%s%s\"items\": [" % (head, ", " if head else ""))
                for i, item in enumerate(items):
                    lines.append("      %s%s" % (j(item), "," if i < len(items) - 1 else ""))
                lines.append("    ]}%s" % ("," if m < len(v) - 1 else ""))
            lines.append("  ]" + comma)
        elif isinstance(v, list) and v and key in ("logbook", "family", "pending", "kit"):
            lines.append("  %s: [" % j(key))
            for m, row in enumerate(v):
                lines.append("    %s%s" % (j(row), "," if m < len(v) - 1 else ""))
            lines.append("  ]" + comma)
        else:
            lines.append("  %s: %s%s" % (j(key), j(v), comma))
    lines.append("}")
    text = "\n".join(lines) + "\n"
    if json.loads(text) != data:
        die("internal error: the rebuilt personal file does not read back the same; nothing was written")
    return text


def skill_files(root):
    """Every file of the skill, as paths relative to its folder."""
    out = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name.endswith(".pyc"):
                continue
            out.append(os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/"))
    return sorted(out)


def write_package(root, personal_text, path):
    import zipfile
    stamp = datetime.now().timetuple()[:6]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in skill_files(root):
            info = zipfile.ZipInfo(rel, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            if rel == "scripts/data/personal.json":
                z.writestr(info, personal_text.encode("utf-8"))
            else:
                with open(os.path.join(root, rel), "rb") as f:
                    z.writestr(info, f.read())
    return os.path.getsize(path)


def cmd_rebuild(a):
    data = personal()
    today = chrono.now_in(chrono.home_tz()).date()
    new, changes, notes = apply_changes(data, a, today)
    if not changes:
        rec("REBUILD", "nothing to change was given. Say what the driver wants set: --home, --work, --place, --leg, --log, "
                       "--vehicle, --item, --keep, --purge ... ('rebuild -h')")
        return
    for c in changes:
        rec("CHANGE", c)
    for n in notes:
        rec("NOTE", n)
    findings = validate(new, today)
    _print_findings(findings)
    if any(f[0] == "FIX" for f in findings):
        die("the result would not be a valid personal file: nothing was written. Fix the FIX lines above and run it again")
    text = dump_personal(new)
    if a.show:
        rec("SHOWN", "nothing was written (--show). Without it, the new package is written for the driver")
        return
    if a.in_place:
        target = personal_path()
        try:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except OSError as e:
            die("could not write %s (%s). This copy of the skill is read-only here: leave out --in-place and hand over the package instead" % (
                target, e.strerror or e))
        rec("WRITTEN", "%s [in place, at the driver's request]" % target)
        rec("NEXT", "the change is live from the next command")
        return
    where = a.out or "auto"
    if where.lower().endswith((".zip", ".json")):
        path = where
        folder = os.path.dirname(os.path.abspath(path))
    else:
        folder = out_folder(where)
        path = os.path.join(folder or "", "personal.json" if a.json else "firn.zip")
    if not folder or not os.path.isdir(folder):
        die("no such folder to write into: %s (use 'auto', a folder, or a name ending .zip)" % where)
    try:
        if a.json or path.lower().endswith(".json"):
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            rec("PERSONAL", path)
            rec("NEXT", "hand that file to %s: it replaces %s in their copy of the skill" % (driver(), PERSONAL_FILE))
        else:
            size = write_package(os.path.dirname(SCRIPTS), text, path)
            rec("PACKAGE", "%s (%s KB)" % (path, num(size / 1024.0)))
            rec("NEXT", "hand that file to %s: it replaces the skill they uploaded, changes included. This conversation still runs "
                        "the old copy; the new one answers from the next" % driver())
            if os.environ.get("FIRN_PERSONAL"):
                more("this unit reads its personal file from FIRN_PERSONAL: that file was not changed (use --in-place or --json for it)")
    except OSError as e:
        die("could not write %s: %s" % (path, e.strerror or e))


def register(sub):
    p = command(sub, "desk", "setup", cmd_setup, "check the driver's personal file in one pass and say exactly what to fix",
                ["setup"])

    p = command(sub, "desk", "rebuild", cmd_rebuild,
                "apply the driver's changes (home, places, legs, log lines, vehicles, kit) and write a new skill package to upload",
                ["rebuild --home krakow --work katowice --driver Anna --show",
                 'rebuild --place "The cabin: at=49.2992,19.9496, tz=Europe/Warsaw" --leg "home>work: km=82, min=61, via=A4" --show',
                 'rebuild --log "LOG 2026-11-10 | journey | first run to the coast | leave before six" --show',
                 'rebuild --vehicle "the estate: odo=84200, km_year=12000" --item "the estate / inspection: last=2026-03-14, every=12 months" --show',
                 "rebuild --home krakow --out auto"])
    p.add_argument("--driver", help="what FIRN calls the driver")
    p.add_argument("--home", help="home: a gazetteer place or LAT,LON")
    p.add_argument("--home-name", help="what to call it (default Home)")
    p.add_argument("--home-tz", help="its time zone, when it is given as coordinates")
    p.add_argument("--work", help="work: a gazetteer place or LAT,LON")
    p.add_argument("--work-name", help="what to call it (default Work)")
    p.add_argument("--work-tz", help="its time zone, when it is given as coordinates")
    p.add_argument("--zones", nargs="+", help="the clocks shown by default, in order: home slt utc ...")
    p.add_argument("--alias", action="append", metavar="NAME=ZONE", help="a short name for a zone")
    p.add_argument("--place", action="append", metavar='"Name: at=PLACE|LAT,LON, tz=, kind=, aka=a|b"', help="a place of the driver's own")
    p.add_argument("--leg", action="append", metavar='"from>to: km=, min=, via=, source="', help="a road figure checked on a live map")
    p.add_argument("--log", action="append", metavar='"LOG ..."', help="a log line to keep, as 'log' printed it")
    p.add_argument("--vehicle", action="append", metavar='"name: odo=, on=, km_year="', help="add a vehicle, or update its odometer")
    p.add_argument("--item", action="append", metavar='"vehicle / what: last=, every=, ..."', help="a service item, as for 'service --item'")
    p.add_argument("--pending", action="append", metavar='"what: note"', help="kit improvised in a sim, waiting for keep or purge")
    p.add_argument("--keep", action="append", metavar="WHAT", help="move pending kit onto the fit list")
    p.add_argument("--purge", action="append", metavar="WHAT", help="strike pending kit")
    p.add_argument("--family", action="append", metavar='"who: what"', help="a physical fact for honest sims")
    p.add_argument("--first-boot", help="the day this unit first ran")
    p.add_argument("--ignition", help="the identity check: every new conversation, when it matters, or off")
    p.add_argument("--drop", action="append", metavar="WHAT",
                   help="remove: home, work, places.KEY, legs.FROM>TO, zone_aliases.NAME, vehicles.NAME, pending.NAME, kit.NAME, logbook.N")
    p.add_argument("--show", action="store_true", help="say what would change and check it; write nothing")
    p.add_argument("--out", help="where to write: 'auto' (default), a folder, or a name ending .zip")
    p.add_argument("--json", action="store_true", help="write only personal.json, not the whole package")
    p.add_argument("--in-place", action="store_true", help="write personal.json where this copy runs (only when the driver asks)")
