"""Build src/scripts/data/airports.json: which of the gazetteer's airports a traveller can book a seat from.

  python tools/build_airports.py DATA_DIR

DATA_DIR must hold OurAirports' airports.csv (public domain):
  https://davidmegginson.github.io/ourairports-data/airports.csv

The gazetteer (places.db) holds every airfield with a code, grass strips and seaplane bases included, and
keeps neither their size nor whether an airline flies there. 'route' needs both to pick an airport for a
journey no road can make, so this script reads the two columns it lacks, 'type' and 'scheduled_service',
and files each gazetteer airport that has scheduled service under 'large' or 'scheduled' (every other size).
Airports are matched by ICAO code first, then by the code in brackets at the end of the gazetteer name.
Nothing here changes places.db.
"""
import csv
import datetime
import io
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "src", "scripts", "data")
NOTE = ("Which gazetteer airports have scheduled airline service, by gazetteer key: 'large' for the ones the source "
        "calls large airports, 'scheduled' for every other size. route picks from these when no road joins two "
        "places. It says where a seat can be booked at all, not where any one flight goes.")


def main(data_dir):
    with io.open(os.path.join(data_dir, "airports.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_icao, by_code = {}, {}
    for r in rows:
        for code in (r.get("icao_code"), r.get("gps_code"), r.get("ident")):
            if code:
                by_icao.setdefault(code, r)
        if r.get("iata_code"):
            by_code[r["iata_code"]] = r
    db = sqlite3.connect(os.path.join(DATA, "places.db"))
    large, scheduled, unmatched = [], [], 0
    for key, name, icao in db.execute("SELECT key, name, icao FROM place WHERE kind = 'airport' ORDER BY key"):
        r = by_icao.get(icao) if icao else None
        if r is None:
            m = re.search(r"\(([A-Z0-9]{3,4})\)$", name)
            r = by_code.get(m.group(1)) if m else None
        if r is None:
            unmatched += 1
            continue
        if r.get("scheduled_service") != "yes" or r.get("type") == "closed":
            continue
        (large if r["type"] == "large_airport" else scheduled).append(key)
    out = {"note": NOTE, "source": "OurAirports airports.csv (ourairports.com), public domain",
           "read": datetime.date.today().isoformat(), "large": " ".join(large), "scheduled": " ".join(scheduled)}
    path = os.path.join(DATA, "airports.json")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, indent=1, ensure_ascii=True) + "\n")
    print("wrote %s: %d large, %d other scheduled, %d gazetteer airports not in the source" % (
        os.path.normpath(path), len(large), len(scheduled), unmatched))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
