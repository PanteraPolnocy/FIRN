"""Build src/scripts/data/countries.json, the table behind 'firn.py country'.

  python tools/build_countries.py DATA_DIR

DATA_DIR must hold countries.wikidata.json: the result of the SPARQL query below, run against
https://query.wikidata.org/sparql (Wikidata is CC0, so the table can ship under any licence).
The query asks for statements that have not ended and are not deprecated.

  SELECT ?iso ?countryLabel (GROUP_CONCAT(DISTINCT ?sideLabel; separator="|") AS ?side)
         (GROUP_CONCAT(DISTINCT ?cur; separator="|") AS ?currency) (GROUP_CONCAT(DISTINCT ?emer; separator="|") AS ?emergency)
         (GROUP_CONCAT(DISTINCT ?plugLabel; separator="|") AS ?plugs) (GROUP_CONCAT(DISTINCT ?volt; separator="|") AS ?voltage)
         (GROUP_CONCAT(DISTINCT ?call; separator="|") AS ?calling)
  WHERE { ?country wdt:P297 ?iso .
    OPTIONAL { ?country p:P1622 ?ss . ?ss ps:P1622 ?sideItem . ?sideItem rdfs:label ?sideLabel . FILTER(LANG(?sideLabel) = "en")
               FILTER NOT EXISTS { ?ss pq:P582 ?se } FILTER NOT EXISTS { ?ss wikibase:rank wikibase:DeprecatedRank } }
    OPTIONAL { ?country p:P38 ?cs . ?cs ps:P38 ?curItem . ?curItem wdt:P498 ?cur .
               FILTER NOT EXISTS { ?cs pq:P582 ?ce } FILTER NOT EXISTS { ?cs wikibase:rank wikibase:DeprecatedRank } }
    OPTIONAL { ?country p:P2852 ?es . ?es ps:P2852 ?emerItem . ?emerItem rdfs:label ?emer . FILTER(LANG(?emer) = "en")
               FILTER NOT EXISTS { ?es pq:P582 ?ee } FILTER NOT EXISTS { ?es wikibase:rank wikibase:DeprecatedRank } }
    OPTIONAL { ?country p:P2853 ?ps . ?ps ps:P2853 ?plugItem . ?plugItem rdfs:label ?plugLabel . FILTER(LANG(?plugLabel) = "en")
               FILTER NOT EXISTS { ?ps pq:P582 ?pe } FILTER NOT EXISTS { ?ps wikibase:rank wikibase:DeprecatedRank } }
    OPTIONAL { ?country wdt:P2884 ?volt }  OPTIONAL { ?country wdt:P474 ?call }
    SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }
  GROUP BY ?iso ?countryLabel ORDER BY ?iso

What this script adds on top, and why:
  - only countries and territories that have a place in the gazetteer are kept;
  - the driving side of every United Nations member that drives on the left is checked against a list
    kept here, and the build stops if the two disagree;
  - plug standards are turned into the letters travellers use (Europlug is C, BS 1363 is G, and so on);
  - where the source lists several currencies, the one in everyday use is put first by hand;
  - speed limits: miles an hour is stated only for the United States and the United Kingdom; for the small
    states and territories that are commonly reported to post limits in miles an hour, the card says to check;
  - emergency numbers are passed through as listed, with 112 first where it is among them. They are not
    verified one by one, and the card says so.
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "scripts", "data", "countries.json")
PLACES = os.path.join(ROOT, "src", "scripts", "data", "places.json")
READ = "2026-11-10"

# United Nations members that drive on the left: the cross-check.
LEFT_UN = set("""AG AU BS BD BB BT BW BN CY DM SZ FJ GD GY IN ID IE JM JP KE KI LS MW MY MV MT MU MZ NA NR NP NZ PK PG KN LC VC
WS SC SG SB ZA LK SR TZ TH TL TO TT TV UG GB ZM ZW""".split())

PLUG = {"Europlug": "C", "Schuko": "F", "BS 1363": "G", "NEMA 1-15": "A", "NEMA 5-15": "B", "Type E": "E", "AS/NZS 3112": "I",
        "BS 546": "D/M", "Type L": "L", "Type K": "K", "SN 441011": "J", "IEC 60906-1": "N", "Type H": "H"}
PLUG_SKIP = ("AC power plugs and sockets: British and related types",)

# The currency in everyday use first, where the source gives several or a code that is not a currency.
CURRENCY = {"CL": ["CLP"], "CZ": ["CZK"], "FR": ["EUR"], "IO": ["USD"], "LR": ["LRD", "USD"], "LS": ["LSL", "ZAR"], "LT": ["EUR"],
            "MO": ["MOP", "HKD"], "NA": ["NAD", "ZAR"], "NL": ["EUR"], "PA": ["PAB", "USD"], "PL": ["PLN"], "PS": ["ILS", "JOD"],
            "RE": ["EUR"], "SH": ["SHP", "GBP"], "ZW": ["ZWG", "USD"]}

MPH_SURE = {"US", "GB"}
MPH_REPORTED = set("AG BS BZ DM GD KN LC VC LR MM WS PR VI GU AS MP VG KY TC AI MS BM FK SH IM JE GG".split())

NAMES = {"CN": "China", "NL": "Netherlands", "DK": "Denmark", "US": "United States", "GB": "United Kingdom", "CD": "DR Congo",
         "CG": "Republic of the Congo", "KR": "South Korea", "KP": "North Korea", "FM": "Micronesia", "GM": "The Gambia",
         "BS": "The Bahamas", "PS": "Palestine", "TL": "Timor-Leste", "CZ": "Czechia", "MK": "North Macedonia", "IE": "Ireland"}
AKA = {"US": ["usa", "america", "united states of america", "the states"], "GB": ["uk", "britain", "great britain", "england", "scotland", "wales"],
       "CN": ["prc", "peoples republic of china"], "CZ": ["czech republic"], "NL": ["holland", "the netherlands"], "KR": ["korea"],
       "RU": ["russian federation"], "AE": ["uae", "emirates"], "TR": ["turkiye"], "CI": ["ivory coast"], "CD": ["drc", "congo kinshasa"],
       "CG": ["congo brazzaville"], "MM": ["burma"], "SZ": ["swaziland"], "TL": ["east timor"], "CV": ["cape verde"], "VA": ["vatican"],
       "BA": ["bosnia"], "MK": ["macedonia"], "PL": ["polska"], "DE": ["deutschland"]}
FIRST = ("112", "911", "999", "000", "111")
# 112 reaches the emergency services in every member state of the European Union, by European law: it is put first there.
EU = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split())


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def val(row, key):
    return row.get(key, {}).get("value", "")


def main(data_dir):
    rows = read(os.path.join(data_dir, "countries.wikidata.json"))["results"]["bindings"]
    places = read(PLACES)["places"]
    in_gazetteer = set(p.get("cc") for p in places.values() if p.get("cc"))
    capitals = {p["cc"]: p["name"] for p in places.values() if p.get("kind") == "capital" and p.get("cc")}
    out, report, seen = {}, [], set()
    for row in rows:
        code = val(row, "iso")
        if code in seen or code not in in_gazetteer:
            continue
        seen.add(code)
        side = val(row, "side")
        if side not in ("left", "right"):
            report.append("%s: driving side '%s' in the source, left out" % (code, side))
            side = ""
        cur =CURRENCY.get(code) or [c for c in val(row, "currency").split("|") if c and c.isalpha() and len(c) == 3]
        if len(cur) > 1 and code not in CURRENCY:
            report.append("%s: several currencies and no ruling here: %s" % (code, cur))
        emer = [e for e in val(row, "emergency").split("|") if e and e.replace(" ", "").isdigit()]
        if code in EU and "112" not in emer:
            emer.append("112")
            report.append("%s: 112 added (a member state of the European Union)" % code)
        # first: 112 inside the European Union; elsewhere the country's own general number, then 112, then the rest
        emer.sort(key=lambda e: (0 if e == "112" and code in EU else 1 if e in FIRST[1:] else 2 if e == "112" else 3, len(e), e))
        plugs = []
        for label in val(row, "plugs").split("|"):
            if label in PLUG:
                for letter in PLUG[label].split("/"):
                    if letter not in plugs:
                        plugs.append(letter)
            elif label and label not in PLUG_SKIP:
                report.append("%s: plug standard '%s' has no letter here, left out" % (code, label))
        volts = sorted(set(int(float(v)) for v in val(row, "voltage").split("|") if v and 90 <= float(v) <= 260))
        speed = "mph" if code in MPH_SURE else "check" if code in MPH_REPORTED else "km/h"
        entry = {"name": NAMES.get(code, val(row, "countryLabel")), "side": side, "speed": speed, "currency": cur, "emergency": emer,
                 "plugs": sorted(plugs), "volts": volts, "dial": [d for d in val(row, "calling").split("|") if d]}
        if code in capitals:
            entry["capital"] = " ".join(capitals[code].split())
        if code in AKA:
            entry["aka"] = AKA[code]
        out[code] = entry
    missing = sorted(in_gazetteer - set(out))
    left_missing = sorted(c for c in LEFT_UN if c in in_gazetteer and out.get(c, {}).get("side") != "left")
    if left_missing:
        sys.exit("these should drive on the left and do not: %s" % left_missing)
    doc = {
        "note": "Country facts for 'firn.py country'. A starting point for a trip, not an authority: confirm anything you will "
                "rely on, emergency numbers above all. Regenerate with tools/build_countries.py.",
        "source": "Wikidata (CC0), read %s: driving side, currency, emergency numbers, plug standards, mains voltage, dialling code. "
                  "Driving side cross-checked for every United Nations member that drives on the left. Speed-limit units: miles an "
                  "hour is stated only for the United States and the United Kingdom; 'check' marks places commonly reported to post "
                  "limits in miles an hour." % READ,
        "read": READ,
        "countries": dict(sorted(out.items())),
    }
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("{\n")
        for key in ("note", "source", "read"):
            f.write("  %s: %s,\n" % (json.dumps(key), json.dumps(doc[key], ensure_ascii=False)))
        f.write('  "countries": {\n')
        items = list(doc["countries"].items())
        for n, (code, entry) in enumerate(items):
            f.write("    %s: %s%s\n" % (json.dumps(code), json.dumps(entry, ensure_ascii=False), "," if n < len(items) - 1 else ""))
        f.write("  }\n}\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print("countries.json: %d countries and territories; %d drive on the left; %d kB" % (
        len(out), sum(1 for e in out.values() if e["side"] == "left"), os.path.getsize(OUT) // 1024))
    print("left, and not on the United Nations list (territories are expected here, a member state is not): %s" % sorted(
        c for c, e in out.items() if e["side"] == "left" and c not in LEFT_UN))
    print("no row for these gazetteer codes: %s" % (missing or "none"))
    print("without emergency numbers: %s" % sorted(c for c, e in out.items() if not e["emergency"]))
    print("without plugs: %s" % sorted(c for c, e in out.items() if not e["plugs"]))
    print("without currency: %s" % sorted(c for c, e in out.items() if not e["currency"]))
    for line in report:
        print("  " + line)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
