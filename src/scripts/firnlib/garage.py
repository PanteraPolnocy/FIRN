"""Garage: unit conversion for vehicle figures, OBD-II trouble codes, dashboard warning lights."""
import math
import re

from .core import G, command, die, fold, load_data, more, num, rec, table, trim, unprotect

# unit -> (dimension, factor to the dimension's base unit)
_UNITS = {}


def _add(dim, table_):
    for names, factor in table_:
        for n in names.split():
            _UNITS[n] = (dim, factor)


_add("length", [("mm", 0.001), ("cm", 0.01), ("m", 1.0), ("km", 1000.0), ("in inch inches", 0.0254), ("ft foot feet", 0.3048),
                ("yd", 0.9144), ("mi mile miles", 1609.344), ("nmi", 1852.0)])
_add("mass", [("gram grams", 0.001), ("kg", 1.0), ("t tonne tonnes", 1000.0), ("lb lbs", 0.45359237), ("oz", 0.028349523125),
              ("st stone", 6.35029318), ("ton-us short-ton", 907.18474), ("ton-uk long-ton", 1016.0469088)])
_add("speed", [("m/s mps", 1.0), ("km/h kmh kph", 1 / 3.6), ("mph", 0.44704), ("kt knot knots", 0.514444), ("ft/s fps", 0.3048)])
_add("power", [("w", 1.0), ("kw", 1000.0), ("mw", 1e6), ("hp bhp", 745.69987), ("ps cv pk", 735.49875)])
_add("torque", [("nm", 1.0), ("lb-ft lbft ft-lb ftlb", 1.3558179483), ("kgf-m kgm kgfm", G)])
_add("pressure", [("pa", 1.0), ("kpa", 1000.0), ("mpa", 1e6), ("bar", 1e5), ("psi", 6894.757293), ("atm", 101325.0)])
_add("volume", [("l litre litres liter liters", 1.0), ("ml cc cm3", 0.001), ("m3", 1000.0), ("gal gal-us", 3.785411784),
                ("gal-uk gal-imp", 4.54609), ("qt", 0.946352946), ("cu-in ci", 0.016387064)])
_add("energy", [("j", 1.0), ("kj", 1000.0), ("mj", 1e6), ("wh", 3600.0), ("kwh", 3.6e6), ("mwh", 3.6e9), ("kcal", 4184.0),
                ("btu", 1055.05585)])
_add("force", [("n", 1.0), ("kn", 1000.0), ("lbf", 4.4482216153), ("kgf", G)])
_add("accel", [("m/s2", 1.0), ("g", G), ("ft/s2", 0.3048)])

_SPECIAL = {
    "c": "temp", "f": "temp", "k": "temp", "degc": "temp", "degf": "temp",
    "l/100km": "fuel", "mpg": "fuel", "mpg-us": "fuel", "mpg-uk": "fuel", "mpg-imp": "fuel", "km/l": "fuel",
    "kwh/100km": "evuse", "wh/km": "evuse", "wh/mi": "evuse", "mi/kwh": "evuse", "km/kwh": "evuse",
    "%": "slope", "pct": "slope", "percent": "slope", "grade": "slope", "deg": "slope", "rad": "slope",
}
_SHOW = {
    "length": ["mm", "m", "km", "in", "ft", "mi"], "mass": ["kg", "t", "lb"], "speed": ["km/h", "mph", "m/s", "kt"],
    "power": ["kw", "hp", "ps"], "torque": ["nm", "lb-ft", "kgf-m"], "pressure": ["bar", "kpa", "psi"],
    "volume": ["l", "gal-us", "gal-uk", "cu-in"], "energy": ["kwh", "mj", "kcal"], "force": ["n", "kn", "lbf", "kgf"],
    "accel": ["m/s2", "g"], "temp": ["c", "f", "k"], "fuel": ["l/100km", "mpg-us", "mpg-uk", "km/l"],
    "evuse": ["kwh/100km", "wh/km", "wh/mi", "mi/kwh"], "slope": ["%", "deg"],
}
_L_GAL_US, _L_GAL_UK, _KM_MI = 3.785411784, 4.54609, 1.609344


def _dim(unit):
    u = unit.lower()
    if u in _SPECIAL:
        return _SPECIAL[u]
    if u in _UNITS:
        return _UNITS[u][0]
    die("unknown unit '%s'. Known: %s" % (unit, ", ".join(sorted(list(_UNITS) + list(_SPECIAL)))))


def _to_base(value, unit, dim):
    u = unit.lower()
    if dim == "temp":
        return value if u in ("c", "degc") else (value - 32.0) / 1.8 if u in ("f", "degf") else value - 273.15
    if dim == "fuel":
        if value <= 0:
            die("fuel economy must be positive")
        return {"l/100km": value, "mpg": 100.0 * _L_GAL_US / (value * _KM_MI), "mpg-us": 100.0 * _L_GAL_US / (value * _KM_MI),
                "mpg-uk": 100.0 * _L_GAL_UK / (value * _KM_MI), "mpg-imp": 100.0 * _L_GAL_UK / (value * _KM_MI),
                "km/l": 100.0 / value}[u]
    if dim == "evuse":
        if value <= 0:
            die("consumption must be positive")
        return {"kwh/100km": value * 10.0, "wh/km": value, "wh/mi": value / _KM_MI, "mi/kwh": 1000.0 / (value * _KM_MI),
                "km/kwh": 1000.0 / value}[u]
    if dim == "slope":
        if u == "deg":
            return math.tan(math.radians(value)) * 100.0
        if u == "rad":
            return math.tan(value) * 100.0
        return value
    return value * _UNITS[u][1]


def _from_base(base, unit, dim):
    u = unit.lower()
    if dim == "temp":
        return base if u in ("c", "degc") else base * 1.8 + 32.0 if u in ("f", "degf") else base + 273.15
    if dim == "fuel":
        return {"l/100km": base, "mpg": 100.0 * _L_GAL_US / (base * _KM_MI), "mpg-us": 100.0 * _L_GAL_US / (base * _KM_MI),
                "mpg-uk": 100.0 * _L_GAL_UK / (base * _KM_MI), "mpg-imp": 100.0 * _L_GAL_UK / (base * _KM_MI),
                "km/l": 100.0 / base}[u]
    if dim == "evuse":
        return {"kwh/100km": base / 10.0, "wh/km": base, "wh/mi": base * _KM_MI, "mi/kwh": 1000.0 / (base * _KM_MI),
                "km/kwh": 1000.0 / base}[u]
    if dim == "slope":
        if u == "deg":
            return math.degrees(math.atan(base / 100.0))
        if u == "rad":
            return math.atan(base / 100.0)
        return base
    return base / _UNITS[u][1]


def _fmt(x):
    ax = abs(x)
    if ax == 0:
        return "0"
    if ax >= 1000:
        return num(x, 0) if ax >= 10000 else num(x, 1).replace(".0", "")
    if ax >= 100:
        return trim(x, 1)
    if ax >= 1:
        return trim(x, 2)
    return trim(x, 4)


def cmd_convert(a):
    try:
        value = float(unprotect(a.value).replace(",", "."))
    except ValueError:
        die("the first argument is the number: convert 1150 hp kw")
    dim = _dim(a.unit)
    base = _to_base(value, a.unit, dim)
    targets = [a.to] if a.to else [u for u in _SHOW[dim] if u != a.unit.lower()]
    for t in targets:
        if _dim(t) != dim:
            die("'%s' and '%s' measure different things (%s and %s)" % (a.unit, t, dim, _dim(t)))
        rec("CONVERT", "%s %s = %s %s [derived]" % (_fmt(value), a.unit, _fmt(_from_base(base, t, dim)), t))
    if dim == "power" and a.unit.lower() in ("hp", "bhp", "ps", "cv", "pk"):
        rec("NOTE", "hp here is mechanical horsepower (745.7 W); ps is metric horsepower (735.5 W), the Polish KM and German PS")
    if dim == "fuel" and a.unit.lower() == "mpg":
        rec("NOTE", "mpg read as US gallons; use mpg-uk for imperial")


# ---- OBD

_CODE_RE = re.compile(r"^([PBCU])([0-3])([0-9A-F])([0-9A-F]{2})$")


def _obd_lookup(code, data):
    if code in data["codes"]:
        return data["codes"][code]
    for lo, hi, text, urg in data["ranges"]:
        if lo[:3] == code[:3] and lo <= code <= hi:
            n = int(code[3:], 16) - int(lo[3:], 16) + 1
            return [text.replace("{n}", str(n)).replace("{letter}", "ABCDEFGHIJKL"[n - 1]), urg]
    return None


def cmd_obd(a):
    data = load_data("obd")
    if a.find:
        want = a.find.lower()
        rows = [(c, v[0], v[1]) for c, v in sorted(data["codes"].items()) if want in v[0].lower()]
        rows += [("%s-%s" % (lo, hi), text.replace("{n}", "N").replace("{letter}", "X"), urg)
                 for lo, hi, text, urg in data["ranges"] if want in text.lower()]
        if not rows:
            rec("NONE", "no generic code in the table mentions '%s'" % a.find)
            return
        table(rows, header=("code", "meaning", "urgency"), indent=2)
        rec("COUNT", "%d of %d codes in the table [table]" % (len(rows), len(data["codes"])))
        return
    if not a.codes:
        die("give one or more codes (P0420), or --find TEXT")
    for raw in a.codes:
        code = unprotect(raw).upper().strip()
        m = _CODE_RE.match(code)
        if not m:
            rec(code or "?", "not an OBD-II code: one letter (P, B, C, U) and four characters, e.g. P0420")
            continue
        system, origin, group = m.group(1), m.group(2), m.group(3)
        generic = origin in ("0", "2") or (origin == "3" and system == "P" and code[2:] >= "400")
        rec(code, "%s | %s%s" % (data["systems"][system], "generic" if generic else "maker-specific",
                                 " | " + data["p_groups"].get(group, "") if system == "P" and generic else ""))
        hit = _obd_lookup(code, data)
        if hit:
            more("%s [table]" % hit[0])
            more("urgency: %s" % data["urgency"][hit[1]])
        elif generic:
            more("generic, but not in this table: look it up with search and name the source")
        else:
            more("the maker's own code: it needs that make's list; search with the make, model and year")
    rec("NOTE", "a code names a circuit or a symptom, not the broken part; a flashing engine light means stop soon")


# ---- warning lights

def cmd_lights(a):
    data = load_data("lights")
    items = data["lights"]
    if a.colour:
        items = [x for x in items if x["colour"] == a.colour]
    if a.text:
        want = fold(" ".join(a.text)).replace("_", " ")
        scored = []
        for x in items:
            hay = [fold(x["name"]).replace("_", " ")] + [fold(k).replace("_", " ") for k in x.get("aka", [])]
            if any(want == h for h in hay):
                scored.append((0, x))
            elif any(want in h or h in want for h in hay):
                scored.append((1, x))
            elif all(w in fold(x["means"]).replace("_", " ") + " " + " ".join(hay) for w in want.split()):
                scored.append((2, x))
        best = min([s for s, _ in scored] or [9])
        items = [x for s, x in scored if s == best]
    if not items:
        rec("NONE", "no light in the table matches; describe the colour and the symbol, or check the handbook")
        return
    if len(items) > 6 and not a.all:
        table([(x["name"], x["colour"], x["means"]) for x in items], header=("light", "colour", "means"), indent=2)
        rec("COUNT", "%d lights; name one for what to do, or add --all" % len(items))
    else:
        for x in items:
            rec("LIGHT", "%s (%s)" % (x["name"], x["colour"]))
            more("means: %s" % x["means"])
            more("do: %s" % x["do"])
    rec("RULE", "red: %s | amber: %s [table; the handbook wins]" % (data["colours"]["red"], data["colours"]["amber"]))


def register(sub):
    p = command(sub, "garage", "convert", cmd_convert, "vehicle units: power, torque, pressure, speed, economy, temperature and more",
                ["convert 1150 hp kw", "convert 32 psi bar", "convert 30 mpg-us l/100km", "convert 70 mph", "convert -40 f c",
                 "convert 250 wh/mi kwh/100km", "convert 12 % deg"])
    p.add_argument("value", help="the number")
    p.add_argument("unit", help="its unit: hp, ps, kw, nm, lb-ft, psi, bar, mph, km/h, l/100km, mpg-us, mpg-uk, c, f ...")
    p.add_argument("to", nargs="?", help="target unit (omit to see the usual counterparts)")

    p = command(sub, "garage", "obd", cmd_obd, "decode OBD-II trouble codes: system, generic or maker-specific, meaning, urgency",
                ["obd P0420", "obd P0301 P0171 U0100", "obd --find misfire"])
    p.add_argument("codes", nargs="*", help="codes such as P0420")
    p.add_argument("--find", help="search the table by text")

    p = command(sub, "garage", "lights", cmd_lights, "dashboard warning lights: what one means and what to do",
                ["lights oil", "lights engine", "lights --colour red", "lights"])
    p.add_argument("text", nargs="*", help="name or description: oil, battery, abs, tyre pressure ...")
    p.add_argument("--colour", choices=["red", "amber", "green", "blue", "white"])
    p.add_argument("--all", action="store_true", help="full detail for every match")
