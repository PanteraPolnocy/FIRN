"""Generate the gazetteer in src/scripts/data/places.db (SQLite) from public datasets.

Sources (download them yourself; they are not kept in this repository):
  Natural Earth populated places, 10 m and 50 m (public domain)
    https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places.geojson
    https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_populated_places.geojson
  OurAirports airports.csv (public domain)
    https://davidmegginson.github.io/ourairports-data/airports.csv
  Optional, and only with --geonames: GeoNames (CC BY 4.0: whoever ships the result must credit GeoNames)
    https://download.geonames.org/export/dump/cities15000.zip
    https://download.geonames.org/export/dump/admin1CodesASCII.txt

What goes in:
  every place in Natural Earth's 10 m set that has a usable time zone; every airport and seaplane base with
  an IATA or ICAO code; and, with --geonames, every town of 15,000 people or more that Natural Earth lacks.
No coordinate here is typed by hand. Your own places live in personal.json, which this never touches.

Keys are stable. The places that were in the gazetteer before it grew (capitals, Natural Earth's notable
places, the big cities, the main airports) are keyed first, by the same rules as always, so a key that worked
keeps working and a checked leg in someone's personal file still joins the same two places. Everything
else is keyed after them and takes what is free.

Time zones are NOT taken on trust. Natural Earth's zone field is wrong for some places (it has put
Prague on Chicago time and Lagos on Athens time), so every zone is checked against the tz database's
own list of which zones belong to which country (zone.tab). A zone that does not keep the same clock
as one of its country's zones is thrown out and replaced, and the correction is reported.

Usage: python tools/build_places.py DATA_DIR [--geonames] [--out FILE]
       Needs a Python with the tzdata package (for zone.tab and for checking zone names).
"""
import argparse
import csv
import io
import json
import math
import os
import re
import sqlite3
import sys
import unicodedata
import zipfile
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "scripts"))
from firnlib.core import fold  # noqa: E402

OUT = os.path.join(ROOT, "src", "scripts", "data", "places.db")
EUROPE = set("AD AL AT AX BA BE BG BY CH CY CZ DE DK EE ES FI FO FR GB GG GI GR HR HU IE IM IS IT JE LI LT LU LV MC MD ME MK "
             "MT NL NO PL PT RO RS SE SI SJ SK SM UA VA XK".split())
# Places where the official clock is one zone for the whole country, whatever local habit says.
TZ_OVERRIDE = {"CN": "Asia/Shanghai"}
_PLAIN = {0x2013: "-", 0x2014: "-", 0x2012: "-", 0x2010: "-", 0x2011: "-", 0x2018: "'", 0x2019: "'",
          0x201c: '"', 0x201d: '"', 0x00a0: " ", 0x02bb: "'", 0x02bc: "'", 0x2032: "'"}
UTC = timezone.utc
AIRFIELDS = ("large_airport", "medium_airport", "small_airport", "seaplane_base")
TIER = {"capital": 0, "big": 1, "large_airport": 2, "notable": 3, "town": 4, "medium_airport": 5, "small_airport": 6, "seaplane_base": 6}
SCHEMA = """
PRAGMA page_size = 4096;
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE zone (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE place (
  id INTEGER PRIMARY KEY,      -- also the rank: 1 is the most notable place in the file
  key TEXT NOT NULL,           -- the one name that always means this place: krakow, san_jose_us, ktw
  name TEXT NOT NULL,
  lat INTEGER NOT NULL,        -- degrees times 10,000 (four decimals, about ten metres): half the bytes of a real
  lon INTEGER NOT NULL,
  zone INTEGER NOT NULL,
  kind TEXT NOT NULL,          -- capital, city, poi, airport
  cc TEXT NOT NULL,            -- ISO country code, or empty
  pop INTEGER NOT NULL,        -- people, where the source says; 0 where it does not
  icao TEXT                    -- an airport's ICAO code
);
CREATE INDEX place_icao ON place (icao) WHERE icao IS NOT NULL;
-- every name a place answers to. r is 0 for its own key, else its rank, so 'ORDER BY r' gives the key's owner
-- first and then the other places of that name, most notable first.
CREATE TABLE name (k TEXT NOT NULL, r INTEGER NOT NULL, id INTEGER NOT NULL, PRIMARY KEY (k, r, id)) WITHOUT ROWID;
"""


def plain(name):
    """Names keep their letters, but typographic dashes and quotes become plain ones (FIRN's typography rule),
    and invisible formatting marks are dropped."""
    return "".join(_PLAIN.get(ord(c), c) for c in (name or "") if unicodedata.category(c) != "Cf").strip()


def hav(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def load_ne(path):
    with io.open(path, encoding="utf-8") as f:
        return [x["properties"] for x in json.load(f)["features"]]


def load_zone_tab():
    """country code -> [(zone, lat, lon)], from the tz database's zone.tab."""
    try:
        import tzdata
    except ImportError:
        sys.exit("this build needs the tzdata package (pip install tzdata) for zone.tab")
    path = os.path.join(os.path.dirname(tzdata.__file__), "zoneinfo", "zone.tab")
    out = {}
    rx = re.compile(r"^([+-])(\d\d)(\d\d)(\d\d)?([+-])(\d\d\d)(\d\d)(\d\d)?$")
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            cc, coords, zone = line.rstrip("\n").split("\t")[:3]
            m = rx.match(coords)
            lat = (int(m.group(2)) + int(m.group(3)) / 60.0 + int(m.group(4) or 0) / 3600.0) * (1 if m.group(1) == "+" else -1)
            lon = (int(m.group(6)) + int(m.group(7)) / 60.0 + int(m.group(8) or 0) / 3600.0) * (1 if m.group(5) == "+" else -1)
            out.setdefault(cc, []).append((zone, lat, lon))
    return out, tzdata.IANA_VERSION


def load_geonames(d):
    """Rows of cities15000 as dicts, and {country.code: region name}; or (None, None) if the files are not there."""
    rows = None
    zpath, tpath = os.path.join(d, "cities15000.zip"), os.path.join(d, "cities15000.txt")
    if os.path.exists(zpath):
        with zipfile.ZipFile(zpath) as z:
            rows = z.read("cities15000.txt").decode("utf-8").splitlines()
    elif os.path.exists(tpath):
        with io.open(tpath, encoding="utf-8") as f:
            rows = f.read().splitlines()
    if rows is None:
        return None, None
    out = []
    for line in rows:
        c = line.split("\t")
        if len(c) < 18 or c[7] in ("PPLQ", "PPLH", "PPLW", "PPLX"):      # abandoned, historical, destroyed; a district of a city
            continue
        out.append({"name": plain(c[1]), "ascii": c[2] or c[1], "alt": c[3], "lat": float(c[4]), "lon": float(c[5]), "code": c[7],
                    "cc": c[8], "adm": c[10], "pop": int(c[14] or 0), "tz": c[17]})
    regions = {}
    apath = os.path.join(d, "admin1CodesASCII.txt")
    if os.path.exists(apath):
        with io.open(apath, encoding="utf-8") as f:
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 3:
                    regions[c[0]] = plain(c[1])
    return out, regions


class Clocks:
    """Compares zones by the clock they actually keep, so old names and shared zones count as the same."""

    def __init__(self):
        from zoneinfo import ZoneInfo
        self.ZoneInfo = ZoneInfo
        self.cache = {}
        self.instants = [datetime(y, m, 15, 12, tzinfo=UTC) for y in (2025, 2027, 2029) for m in range(1, 13)]

    def sig(self, name):
        if name not in self.cache:
            try:
                tz = self.ZoneInfo(name)
                self.cache[name] = tuple(t.astimezone(tz).utcoffset() for t in self.instants)
            except Exception:
                self.cache[name] = None
        return self.cache[name]

    def std_hours(self, name):
        s = self.sig(name)
        return min(x.total_seconds() for x in s) / 3600.0 if s else None


class Grid:
    """Points in one-degree cells, for 'what is within a few kilometres of here'."""

    def __init__(self):
        self.cells = {}

    def add(self, lat, lon, item):
        self.cells.setdefault((int(math.floor(lat)), int(math.floor(lon))), []).append((lat, lon, item))

    def near(self, lat, lon, km):
        dlat = int(math.ceil(km / 111.0))
        dlon = int(math.ceil(km / (111.0 * max(0.05, math.cos(math.radians(lat))))))
        out = []
        for i in range(int(math.floor(lat)) - dlat, int(math.floor(lat)) + dlat + 1):
            for j in range(int(math.floor(lon)) - dlon, int(math.floor(lon)) + dlon + 1):
                for la, lo, item in self.cells.get((i, (j + 180) % 360 - 180), ()):
                    dist = hav(lat, lon, la, lo)
                    if dist <= km:
                        out.append((dist, item))
        return sorted(out, key=lambda x: x[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", help="folder holding the downloaded files")
    ap.add_argument("--geonames", action="store_true", help="add GeoNames towns (CC BY 4.0: the result must credit GeoNames)")
    ap.add_argument("--out", default=OUT, help="where to write the database (default: src/scripts/data/places.db)")
    ap.add_argument("--old", help="a places.json from before the gazetteer grew: check that every key in it still means the same place")
    a = ap.parse_args()
    d = a.data_dir
    ne10 = load_ne(os.path.join(d, "ne_10m_populated_places.geojson"))
    ne50 = load_ne(os.path.join(d, "ne_50m_populated_places.geojson"))
    country_zones, tz_version = load_zone_tab()
    clocks = Clocks()
    report, fixes = [], []
    gn_rows, regions = (load_geonames(d) if a.geonames else (None, None))
    if a.geonames and gn_rows is None:
        sys.exit("--geonames was asked for, but cities15000.zip (or .txt) is not in %s" % d)

    def cc_of(p):
        cc = p.get("ISO_A2")
        return cc if cc and cc != "-99" and len(cc) == 2 else ""

    def legit(cc, zone):
        """Does this zone keep the clock of one of the country's own zones?"""
        s = clocks.sig(zone) if zone else None
        return s is not None and any(clocks.sig(z) == s for z, _, _ in country_zones.get(cc, []))

    def one_clock(cc):
        sigs = set(clocks.sig(z) for z, _, _ in country_zones.get(cc, []))
        return len(sigs) == 1

    # ---- pass 1: which of Natural Earth's zones can be believed
    trusted = []
    for p in ne10:
        cc, zone = cc_of(p), p.get("TIMEZONE")
        if cc in country_zones:
            if legit(cc, zone):
                trusted.append(p)
        elif zone and clocks.sig(zone) is not None and abs(clocks.std_hours(zone) - p["LONGITUDE"] / 15.0) <= 3.0:
            trusted.append(p)
    by_cc = {}
    for p in trusted:
        by_cc.setdefault(cc_of(p), []).append(p)
    # In a country with several clocks a wrong zone can still happen to be one of that country's zones
    # (Natural Earth has Santiago de Chile on a clock that matches Punta Arenas). So each place must also
    # agree with its neighbours: if at least three trusted places lie within 400 km and none shares its
    # clock, it is an outlier.
    outliers = set()
    for cc, pool in by_cc.items():
        if cc not in country_zones or one_clock(cc) or len(pool) < 4:
            continue
        for p in pool:
            near = sorted(((hav(p["LATITUDE"], p["LONGITUDE"], q["LATITUDE"], q["LONGITUDE"]), n) for n, q in enumerate(pool) if q is not p))
            near = [pool[n] for dist, n in near[:6] if dist <= 400]
            if len(near) >= 3 and not any(clocks.sig(q["TIMEZONE"]) == clocks.sig(p["TIMEZONE"]) for q in near):
                outliers.add(id(p))
    if outliers:
        trusted = [p for p in trusted if id(p) not in outliers]
        by_cc = {}
        for p in trusted:
            by_cc.setdefault(cc_of(p), []).append(p)

    # With GeoNames there is a second, much denser set of places whose zones came from zone boundaries rather than
    # from a neighbour. It is used for places that are new to the gazetteer, never for the ones keyed first.
    dense = {}
    if gn_rows:
        for g in gn_rows:
            tz = TZ_OVERRIDE.get(g["cc"], g["tz"])
            if g["cc"] in country_zones and not legit(g["cc"], tz):
                continue
            if clocks.sig(tz) is None:
                continue
            g["tz_ok"] = tz
            dense.setdefault(g["cc"], Grid()).add(g["lat"], g["lon"], g)

    def assign(lat, lon, cc):
        """A zone for a point in a country: the country's only clock, else the nearest believable place in it."""
        if cc in TZ_OVERRIDE:
            return TZ_OVERRIDE[cc]
        if cc in country_zones and one_clock(cc):
            return country_zones[cc][0][0]
        pool = by_cc.get(cc) or []
        best = None
        for q in pool:
            dist = hav(lat, lon, q["LATITUDE"], q["LONGITUDE"])
            if best is None or dist < best[0]:
                best = (dist, q["TIMEZONE"])
        if best and (best[0] <= 900 or cc not in country_zones):
            return best[1]
        if cc in country_zones:
            return min(country_zones[cc], key=lambda z: hav(lat, lon, z[1], z[2]))[0]
        best = None
        for q in trusted:
            dist = hav(lat, lon, q["LATITUDE"], q["LONGITUDE"])
            if dist <= 400 and (best is None or dist < best[0]):
                best = (dist, q["TIMEZONE"])
        return best[1] if best else None

    def assign_new(lat, lon, cc):
        """As assign, but a GeoNames town within 150 km in the same country is believed first."""
        if cc in TZ_OVERRIDE or (cc in country_zones and one_clock(cc)) or cc not in dense:
            return assign(lat, lon, cc)
        near = dense[cc].near(lat, lon, 150.0)
        return near[0][1]["tz_ok"] if near else assign(lat, lon, cc)

    # ---- the places that were always in: capitals, Natural Earth's notable places, big cities
    def ident(p):
        return (p.get("NAMEASCII") or p.get("NAME"), round(p["LATITUDE"], 2), round(p["LONGITUDE"], 2))

    def ne_record(p, tz):
        cls = p.get("FEATURECLA") or ""
        cap = cls.startswith("Admin-0 capital")
        return {
            "p": p, "name": plain(p.get("NAME") or p["NAMEASCII"]), "ascii": p.get("NAMEASCII") or p["NAME"], "cap": cap,
            "pop": max(0, int(p.get("POP_MAX") or 0)), "cc": cc_of(p), "country": plain(p.get("ADM0NAME") or ""),
            "adm1": plain(p.get("ADM1NAME") or ""), "tz": tz,
            "kind": "capital" if cap else "poi" if ("station" in cls.lower() or "Historic" in cls) else "city",
            "lat": round(p["LATITUDE"], 4), "lon": round(p["LONGITUDE"], 4),
        }

    def ne_aka(p, key, base):
        aka = []
        for alt in [p.get("NAME_PL"), p.get("NAME"), p.get("NAME_EN")] + (p.get("NAMEALT") or "").split("|"):
            f = fold(plain(alt or ""))
            if len(f) >= 3 and f != key and f != base and f not in aka:
                aka.append(f)
        return aka

    in50 = set(ident(p) for p in ne50)
    trusted_ids = set(id(p) for p in trusted)
    chosen, later, dropped = [], [], 0
    for p in ne10:
        cls = p.get("FEATURECLA") or ""
        cap = cls.startswith("Admin-0 capital")
        pop = p.get("POP_MAX") or 0
        cc = cc_of(p)
        if not (p.get("NAMEASCII") or p.get("NAME")):
            continue
        want = cap or ident(p) in in50 or pop >= 300000 or (cc in EUROPE and pop >= 100000)
        given = p.get("TIMEZONE")
        if id(p) in trusted_ids:
            tz = TZ_OVERRIDE.get(cc, given)
        else:
            tz = assign(p["LATITUDE"], p["LONGITUDE"], cc) if want else assign_new(p["LATITUDE"], p["LONGITUDE"], cc)
            if want and tz and given and clocks.sig(given) != clocks.sig(tz):
                fixes.append("%s (%s): %s -> %s" % (p.get("NAMEASCII"), cc or p.get("ADM0NAME"), given, tz))
        if not tz:
            if cap:
                sys.exit("capital without a usable zone: %s (%s)" % (p.get("NAMEASCII"), p.get("ADM0NAME")))
            dropped += 1
            continue
        (chosen if want else later).append(ne_record(p, tz))
    report.append("the places that were always in: %d (capitals %d); Natural Earth places dropped for want of a zone: %d" % (
        len(chosen), sum(1 for c in chosen if c["cap"]), dropped))
    report.append("Natural Earth zones believed: %d of %d places; corrected among those: %d" % (len(trusted), len(ne10), len(fixes)))
    for line in fixes:
        report.append("  corrected: " + line)

    # keys: the capital or the biggest city gets the plain name, the rest get a country (and region) suffix
    chosen.sort(key=lambda c: (not c["cap"], -c["pop"], c["ascii"]))
    places, taken = {}, {}
    for c in chosen:
        base = fold(c["ascii"])
        if not base:
            continue
        key = base
        if key in places:
            key = "%s_%s" % (base, c["cc"].lower() or fold(c["country"]))
        if key in places:
            key = "%s_%s" % (key, fold(c["adm1"]) or "x")
        n = 2
        while key in places:
            key = "%s_%d" % (base, n)
            n += 1
        aka = ne_aka(c["p"], key, base)
        places[key] = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "tz": c["tz"], "kind": c["kind"], "cc": c["cc"],
                       "pop": c["pop"], "base": base,
                       "tier": "capital" if c["cap"] else "big" if c["pop"] >= 300000 else "notable"}
        if key != base:
            places[key]["name"] = "%s, %s" % (c["name"], c["adm1"] or c["country"])
        if aka:
            places[key]["aka"] = aka
        taken[key] = c

    # an alias must not shadow another place's key, or be claimed twice
    owner = {}
    for key, e in places.items():
        for alias in list(e.get("aka", [])):
            if alias in places or alias in owner:
                e["aka"].remove(alias)
            else:
                owner[alias] = key
        if "aka" in e and not e["aka"]:
            del e["aka"]

    # ---- the airports that were always in: every large one with an IATA code, and medium ones with scheduled
    # service in Europe
    with io.open(os.path.join(d, "airports.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    added = skipped = moved = 0
    done_rows = set()

    def airport_entry(r, code, lat, lon, tz):
        name = plain(r["name"]).split(" / ")[0].strip()
        e = {"name": "%s (%s)" % (name, code), "lat": round(lat, 4), "lon": round(lon, 4), "tz": tz, "kind": "airport",
             "cc": r.get("iso_country") or "", "pop": 0, "base": fold(name), "tier": r["type"], "codes": []}
        iata = (r.get("iata_code") or "").strip().upper()
        icao = (r.get("icao_code") or "").strip().upper()
        if len(iata) == 3 and iata.isalpha():
            e["codes"].append(iata.lower())
        if len(icao) == 4 and icao.isalnum():
            e["icao"] = icao
            e["codes"].append(icao.lower())
        return e

    for r in rows:
        code = (r.get("iata_code") or "").strip().upper()
        if len(code) != 3 or not code.isalpha():
            continue
        big = r["type"] == "large_airport"
        regional = r["type"] == "medium_airport" and r.get("scheduled_service") == "yes" and r.get("iso_country") in EUROPE
        if not (big or regional):
            continue
        try:
            lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
        except (TypeError, ValueError):
            continue
        cc = r.get("iso_country") or ""
        tz = assign(lat, lon, cc)
        if not tz:
            skipped += 1
            continue
        key = code.lower()
        if key in places:
            c = taken.get(key)
            if c and (c["cap"] or c["pop"] >= 300000):
                key = key + "_airport"
            else:
                new_key = "%s_%s" % (key, (places[key].get("cc") or "x").lower())
                if new_key in places:
                    skipped += 1
                    continue
                places[new_key] = places.pop(key)
                moved += 1
        places[key] = airport_entry(r, code, lat, lon, tz)
        done_rows.add(r["id"])
        added += 1
    report.append("the airports that were always in: %d; skipped: %d; city keys renamed to make way for an airport code: %d" % (
        added, skipped, moved))
    stable = len(places)

    # ---- now everything else, most notable first, each taking a key that is still free
    def free_key(base, cc, region, country=""):
        # a name that one of the older places already answers to (Kolonia is Cologne, in Polish) is not free either
        for cand in (base, "%s_%s" % (base, cc.lower() or fold(country) or "x")):
            if cand and cand not in places and cand not in owner:
                return cand
        cand = "%s_%s_%s" % (base, cc.lower() or fold(country) or "x", fold(region) or "x")
        n = 2
        while cand in places or cand in owner:
            cand = "%s_%s_%d" % (base, cc.lower() or fold(country) or "x", n)
            n += 1
        return cand

    new_towns = []
    for c in later:
        c["region"], c["src"] = c["adm1"], "ne"
        new_towns.append(c)

    # GeoNames towns that Natural Earth does not already have
    if gn_rows:
        grid = Grid()
        for c in chosen + later:
            p = c["p"]
            names = set(fold(plain(x or "")) for x in [p.get("NAME"), p.get("NAMEASCII"), p.get("NAME_EN")] + (p.get("NAMEALT") or "").split("|"))
            names.discard("")
            grid.add(c["lat"], c["lon"], (names, c))
        same = close = bad_zone = 0
        for g in gn_rows:
            if "tz_ok" not in g:
                bad_zone += 1
                continue
            mine = set([fold(g["name"]), fold(g["ascii"])])
            near = grid.near(g["lat"], g["lon"], 30.0)
            if any(names & mine for dist, (names, c) in near):
                same += 1
                continue
            alts = None
            hit = False
            for dist, (names, c) in near:
                if alts is None:
                    alts = set(fold(plain(x)) for x in g["alt"].split(",") if x)
                if names & alts or (dist <= 5.0 and c["pop"] and g["pop"] and 0.33 <= c["pop"] / float(g["pop"]) <= 3.0):
                    hit = True
                    break
            if hit:
                close += 1
                continue
            region = regions.get("%s.%s" % (g["cc"], g["adm"]), "")
            new_towns.append({"name": g["name"], "ascii": g["ascii"], "cap": False, "pop": g["pop"], "cc": g["cc"], "country": "",
                              "adm1": region, "region": region, "tz": g["tz_ok"], "kind": "city", "lat": round(g["lat"], 4),
                              "lon": round(g["lon"], 4), "src": "gn"})
        report.append("GeoNames towns: %d read; %d already here under the same name, %d under another name; %d with a zone "
                      "their country does not own, left out" % (len(gn_rows), same, close, bad_zone))

    new_towns.sort(key=lambda c: (-c["pop"], c["ascii"], c["cc"], c["lat"]))
    for c in new_towns:
        base = fold(c["ascii"])
        if not base:
            continue
        key = free_key(base, c["cc"], c["region"], c["country"])
        e = {"name": c["name"], "lat": c["lat"], "lon": c["lon"], "tz": c["tz"], "kind": c["kind"], "cc": c["cc"], "pop": c["pop"],
             "base": base, "tier": "town"}
        if key != base:
            e["name"] = "%s, %s" % (c["name"], c["region"] or c["country"] or c["cc"])
        if c["src"] == "ne":
            aka = [x for x in ne_aka(c["p"], key, base) if x not in places]
            if aka:
                e["aka"] = aka
        places[key] = e
    report.append("towns added after them: %d (Natural Earth %d, GeoNames %d)" % (
        len(new_towns), sum(1 for c in new_towns if c["src"] == "ne"), sum(1 for c in new_towns if c["src"] == "gn")))

    # every other airport and seaplane base with a code
    more_added = more_skipped = 0
    rest = [r for r in rows if r["id"] not in done_rows and r["type"] in AIRFIELDS]
    rest.sort(key=lambda r: (TIER[r["type"]], r.get("scheduled_service") != "yes", r.get("ident") or ""))
    for r in rest:
        iata = (r.get("iata_code") or "").strip().upper()
        icao = (r.get("icao_code") or "").strip().upper()
        code = iata if (len(iata) == 3 and iata.isalpha()) else icao if (len(icao) == 4 and icao.isalnum()) else ""
        if not code:
            continue
        try:
            lat, lon = float(r["latitude_deg"]), float(r["longitude_deg"])
        except (TypeError, ValueError):
            continue
        tz = assign_new(lat, lon, r.get("iso_country") or "")
        if not tz:
            more_skipped += 1
            continue
        key = code.lower()
        if key in places or key in owner:
            key += "_airport"
        if key in places or key in owner:
            more_skipped += 1
            continue
        places[key] = airport_entry(r, code, lat, lon, tz)
        more_added += 1
    report.append("airports added after them: %d; skipped: %d" % (more_added, more_skipped))

    # ---- last line of defence: nothing leaves with a zone its country does not own
    bad = [k for k, e in places.items() if e["cc"] in country_zones and e["cc"] not in TZ_OVERRIDE and not legit(e["cc"], e["tz"])]
    if bad:
        sys.exit("zones that do not belong to their country: %s" % ", ".join("%s=%s" % (k, places[k]["tz"]) for k in bad[:20]))

    # ---- rank, and write
    order = sorted(places, key=lambda k: (TIER[places[k]["tier"]], -places[k]["pop"], k))
    ids = dict((k, n) for n, k in enumerate(order, 1))
    zones = sorted(set(e["tz"] for e in places.values()))
    zone_id = dict((z, n) for n, z in enumerate(zones, 1))
    names = set()
    for k in order:
        e, pid = places[k], ids[k]
        names.add((k, 0, pid))
        # 'Springfield, Illinois' needs no row of its own: the tools read a name with a comma as name, then where
        for alias in [e["base"]] + e.get("aka", []) + e.get("codes", []) + ([] if ", " in e["name"] else [fold(e["name"].split(" (")[0])]):
            if alias and alias != k:
                names.add((alias, pid, pid))
    kinds = {}
    for e in places.values():
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    sources = ("Cities and capitals: Natural Earth populated places, 10 m and 50 m (public domain, naturalearthdata.com). "
               + ("Towns of 15,000 people or more: GeoNames cities15000 (CC BY 4.0, geonames.org). " if gn_rows else "")
               + "Airports: OurAirports (public domain, ourairports.com). Time zones: checked against the IANA tz database %s, "
               "country by country; a zone the country does not own was corrected or left out. Built %s. City points "
               "are label points, good to a few kilometres; airports to a few hundred metres. Verify before anything precise."
               % (tz_version, date.today().isoformat()))
    meta = {
        "note": "FIRN's gazetteer, generated by tools/build_places.py. Do not edit it: your home, work and places of your own "
                "go in personal.json, which a rebuild never touches.",
        "sources": sources, "built": date.today().isoformat(), "tz": tz_version, "places": str(len(places)),
        "kinds": json.dumps(kinds, sort_keys=True), "geonames": "yes" if gn_rows else "no",
    }
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        os.remove(out)
    con = sqlite3.connect(out)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
    con.executemany("INSERT INTO zone VALUES (?, ?)", [(n, z) for z, n in sorted(zone_id.items(), key=lambda x: x[1])])
    con.executemany("INSERT INTO place VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (ids[k], k, places[k]["name"], int(round(places[k]["lat"] * 10000)), int(round(places[k]["lon"] * 10000)),
         zone_id[places[k]["tz"]], places[k]["kind"],
         places[k]["cc"], places[k]["pop"], places[k].get("icao")) for k in order])
    con.executemany("INSERT INTO name VALUES (?, ?, ?)", sorted(names))
    con.commit()
    con.execute("VACUUM")
    con.close()
    report.append("places.db: %d places %s, %d names, %d of them keyed first; %.0f KB" % (
        len(places), json.dumps(kinds, sort_keys=True), len(names), stable, os.path.getsize(out) / 1024.0))

    if a.old:
        with io.open(a.old, encoding="utf-8") as f:
            old = json.load(f)["places"]
        gone, movedp, rezoned = [], [], []
        for k, o in old.items():
            e = places.get(k)
            if e is None:
                gone.append(k)
            elif abs(e["lat"] - o["lat"]) > 1e-6 or abs(e["lon"] - o["lon"]) > 1e-6 or e["name"] != o["name"]:
                movedp.append(k)
            elif e["tz"] != o["tz"]:
                rezoned.append("%s %s -> %s" % (k, o["tz"], e["tz"]))
        report.append("against %s: %d old keys; missing %d, now another place %d, another zone %d" % (
            os.path.basename(a.old), len(old), len(gone), len(movedp), len(rezoned)))
        for label, items in (("missing", gone), ("another place", movedp), ("another zone", rezoned)):
            if items:
                report.append("  %s: %s" % (label, ", ".join(items[:30])))
        if gone or movedp:
            print("\n".join(report))
            sys.exit("old keys have changed their meaning: not acceptable")
    print("\n".join(report))


if __name__ == "__main__":
    main()
