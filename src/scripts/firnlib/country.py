"""Country card: the few facts that change when a journey crosses a border.

Which side they drive on, how speed limits are posted, the currency, the plugs, the emergency number, the
dialling code. The table is generated from Wikidata (tools/build_countries.py) and is a starting point: it says
when it was read, and FIRN confirms anything that matters, emergency numbers above all.
"""
from . import chrono, geo
from .core import command, die, fold, load_data, more, personal, rec, trim

SIDE_NOTE = {"left": "on the left", "right": "on the right"}
GENERAL = ("112", "911", "999", "000", "111")      # numbers that reach every service; anything else is listed without a favourite


def table_():
    return load_data("countries")


def find(text):
    """A country by code, name, another name it goes by, or any place in the gazetteer that lies in it."""
    data = table_()["countries"]
    raw = str(text).strip()
    if len(raw) == 2 and raw.upper() in data:
        return raw.upper()
    want = fold(raw)
    names = {}
    for code, c in data.items():
        names[fold(c["name"])] = code
        for alias in c.get("aka", ()):
            names[fold(alias)] = code
    if want in names:
        return names[want]
    place = geo.find_place(raw, say=True)
    if place and place.get("cc") in data:
        return place["cc"]
    import difflib
    near = difflib.get_close_matches(want, list(names), n=3, cutoff=0.75)
    die("no country called '%s'.%s Give a name, a two-letter code, or a place in it" % (
        text, " Did you mean: %s?" % ", ".join(data[names[n]]["name"] for n in near) if near else ""))


def home_country():
    """The country home is in, taken from the nearest place in the gazetteer, or None."""
    if not chrono.home_is_set():
        return None
    h = personal().get("home") or {}
    best = geo.nearest(h["lat"], h["lon"], 150.0, lambda p: bool(p.get("cc")))
    return best[1]["cc"] if best and best[1]["cc"] in table_()["countries"] else None


def cmd_country(a):
    doc = table_()
    data = doc["countries"]
    if a.left:
        left = sorted((c["name"], code) for code, c in data.items() if c["side"] == "left")
        rec("LEFT", "%d countries and territories drive on the left [table, read %s]" % (len(left), doc["read"]))
        line = ""
        for name, code in left:
            piece = "%s (%s)" % (name, code)
            if len(line) + len(piece) > 96:
                more(line.rstrip(", "))
                line = ""
            line += piece + ", "
        if line:
            more(line.rstrip(", "))
        return
    if not a.place:
        die("which country? Give a name, a two-letter code, or a place in it; or --left for the list that drives on the left")
    code = find(" ".join(a.place))
    c = data[code]
    home = find(a.home) if a.home else home_country()
    h = data.get(home) if home and home != code else None
    rec("COUNTRY", "%s (%s)%s" % (c["name"], code, ", capital %s" % c["capital"] if c.get("capital") else ""))
    if c["side"]:
        rec("DRIVES", "%s%s" % (SIDE_NOTE[c["side"]], " - the other side from %s" % h["name"] if h and h["side"] and h["side"] != c["side"]
                                else ""))
    speed = {"km/h": "limits are posted in km/h", "mph": "limits are posted in miles an hour",
             "check": "reported to post limits in miles an hour: check before you drive"}[c["speed"]]
    if h and h["speed"] != c["speed"] and c["speed"] != "check":
        speed += ", not the %s of %s" % ("miles an hour" if h["speed"] == "mph" else "km/h", h["name"])
    rec("SPEED", speed)
    if c["currency"]:
        rec("CURRENCY", "%s%s" % (c["currency"][0], ", also %s" % ", ".join(c["currency"][1:]) if len(c["currency"]) > 1 else ""))
    if c["emergency"]:
        first, rest = c["emergency"][0], c["emergency"][1:]
        if first in GENERAL:
            line = "%s%s" % (first, "; also on file, with no note of which service answers: %s" % ", ".join(rest) if rest else "")
        else:
            line = "%s on file, with no note of which service answers which" % ", ".join(c["emergency"])
        rec("EMERGENCY", "%s - not checked one by one: confirm before you travel" % line)
    else:
        rec("EMERGENCY", "no number on file: find it before you travel")
    if c["plugs"] or c["volts"]:
        line = "type%s %s" % ("" if len(c["plugs"]) == 1 else "s", ", ".join(c["plugs"])) if c["plugs"] else "types not on file"
        if c["volts"]:
            line += "; %s V" % " or ".join(trim(v, 0) for v in c["volts"])
        if h and c["plugs"] and h["plugs"] and not set(h["plugs"]) & set(c["plugs"]):
            line += " - none of %s's (%s) fit: take an adapter" % (h["name"], ", ".join(h["plugs"]))
        rec("PLUGS", line)
    if c["dial"]:
        rec("DIAL", ", ".join(c["dial"]))
    zones = geo.zones_in(code)
    if zones:
        now = chrono.now_in(chrono.UTC)
        if len(zones) <= 4:
            rec("CLOCKS", "; ".join("%s %s" % (z, now.astimezone(chrono.get_tz(z)).strftime("%H:%M")) for z in zones))
        else:
            rec("CLOCKS", "%d zones across the country: 'time' with a place in it gives the right one" % len(zones))
    rec("SOURCE", "Wikidata, read %s [table]. A starting point, not an authority: rules of the road, tolls and what must be "
                  "carried in the car are not in it, and are searched for, never recalled" % doc["read"])


def register(sub):
    p = command(sub, "ground", "country", cmd_country,
                "a country at a glance: which side they drive on, speed units, currency, plugs, emergency number, clocks",
                ["country poland", "country GB --from PL", "country tokyo", "country --left"])
    p.add_argument("place", nargs="*", help="a country's name, its two-letter code, or any place in it")
    p.add_argument("--from", dest="home", help="the country you are coming from, for what differs (default: where home is)")
    p.add_argument("--left", action="store_true", help="list every country and territory that drives on the left")
