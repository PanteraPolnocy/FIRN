"""Side-by-side vehicle comparison: the same rows for each vehicle, derived figures calculated, and who
leads each row as plain arithmetic.

The figures are the caller's: looked up, dated and named, or the driver's own. This never recalls a
specification. A lead is arithmetic on what was given, not a recommendation.
"""
import re

from .core import command, die, load_data, more, num, rec, table, trim

HP_KW = 0.74569987
PS_KW = 0.73549875

# key: (label, unit, which way leads: 1 higher, -1 lower, 0 neither, decimals)
FIELDS = [
    ("kw", "power", "kW", 1, 0),
    ("nm", "torque", "Nm", 1, 0),
    ("kg", "kerb mass", "kg", 0, 0),
    ("zero100", "0-100 km/h", "s", -1, 1),
    ("top", "top speed", "km/h", 1, 0),
    ("battery", "battery", "kWh", 0, 1),
    ("kwh100", "electricity", "kWh/100 km", -1, 1),
    ("tank", "tank", "l", 0, 0),
    ("l100", "fuel", "l/100 km", -1, 1),
    ("range", "range", "km", 1, 0),
    ("seats", "seats", "", 1, 0),
    ("boot", "boot", "l", 1, 0),
    ("payload", "payload", "kg", 1, 0),
    ("tow", "towing limit", "kg", 1, 0),
    ("length", "length", "mm", 0, 0),
    ("width", "width", "mm", 0, 0),
    ("height", "height", "mm", 0, 0),
    ("wheelbase", "wheelbase", "mm", 0, 0),
    ("clearance", "ground clearance", "mm", 0, 0),
    ("co2", "CO2", "g/km", -1, 0),
    ("price", "price", "", -1, 0),
    ("resale", "resale value", "", 1, 0),
    ("insurance", "insurance a year", "", -1, 0),
    ("service", "servicing a year", "", -1, 0),
    ("tax", "tax a year", "", -1, 0),
    ("other", "other costs a year", "", -1, 0),
    ("year", "year", "", 0, 0),
]
YEARLY = ("insurance", "service", "tax", "other")
FIELD = {f[0]: f for f in FIELDS}
# other spellings: name -> (key, factor)
ALIASES = {
    "power": ("kw", 1.0), "hp": ("kw", HP_KW), "bhp": ("kw", HP_KW), "ps": ("kw", PS_KW), "cv": ("kw", PS_KW),
    "torque": ("nm", 1.0), "mass": ("kg", 1.0), "weight": ("kg", 1.0), "kerb": ("kg", 1.0),
    "0-100": ("zero100", 1.0), "0_100": ("zero100", 1.0), "accel": ("zero100", 1.0),
    "kwh": ("battery", 1.0), "kwh/100km": ("kwh100", 1.0), "kwh_100": ("kwh100", 1.0), "wh/km": ("kwh100", 0.1),
    "wh_km": ("kwh100", 0.1), "l/100km": ("l100", 1.0), "l_100": ("l100", 1.0), "towing": ("tow", 1.0),
}
TEXT_KEYS = ("source", "drive", "fuel_type", "note")
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def parse_vehicle(text):
    """'Kestrel: kw=150, kg=1720, battery=64, kwh100=17.1, source=maker site 2026-11' -> (name, values, texts)."""
    name, sep, body = str(text).partition(":")
    if not sep or not name.strip() or not body.strip():
        die("a vehicle looks like  \"Name: kw=150, kg=1720, 0-100=7.9\"  (or the word firn for FIRN-01)")
    values, texts = {}, {}
    for part in re.split(r"[,;]", body):
        if not part.strip():
            continue
        key, eq, val = part.partition("=")
        key, val = key.strip().lower().replace(" ", "_"), val.strip()
        if not eq or not key or not val:
            die("could not read '%s' for %s (use key=value, values as plain numbers)" % (part.strip(), name.strip()))
        if key in TEXT_KEYS:
            texts[key] = val
            continue
        factor = 1.0
        if key in ALIASES:
            key, factor = ALIASES[key]
        if key not in FIELD:
            texts[key] = val
            continue
        if not _NUM_RE.match(val):
            die("%s for %s must be a plain number, without units or thousands separators: '%s'" % (key, name.strip(), val))
        if key in values:
            die("%s is given twice for %s" % (FIELD[key][1], name.strip()))
        values[key] = float(val) * factor
    if not values:
        die("%s has no figures to compare" % name.strip())
    return name.strip(), values, texts


def firn_vehicle():
    lore = load_data("lore")
    ch = lore["chassis"]
    values = {"kw": ch["power_hp"] * HP_KW, "kg": ch["kerb_kg"], "zero100": ch["zero_100_s"], "top": ch["top_kmh"],
              "range": ch["range_km"], "seats": ch["seats"], "length": ch["length_m"] * 1000.0, "width": ch["width_m"] * 1000.0,
              "height": ch["height_m"] * 1000.0, "wheelbase": ch["wheelbase_m"] * 1000.0}
    return lore["unit"], values, {"source": "his reference sheet and lore: fiction, not a production vehicle"}


def _show(key, x):
    _, _, unit, _, nd = FIELD[key]
    if key in ("kw",):
        return "%s kW (%s hp)" % (num(x), num(x / HP_KW))
    if key == "year":
        return "%d" % x
    body = num(x, nd) if abs(x) >= 1000 else trim(x, nd)
    return (body + " " + unit).strip()


def lead(names, vals, way, unit="", absolute=False):
    """Who leads a row, and by how much over the next one. vals: one number or None per vehicle."""
    have = [(v, n) for v, n in zip(vals, names) if v is not None]
    if way == 0 or len(have) < 2:
        return "-"
    ranked = sorted(have, key=lambda t: -t[0] * way)
    best, second = ranked[0], ranked[1]
    if abs(best[0] - second[0]) < 1e-9:
        return "level"
    if absolute or second[0] == 0:
        return "%s by %s%s" % (best[1], trim(abs(best[0] - second[0]), 1), (" " + unit) if unit else "")
    return "%s by %s%%" % (best[1], trim(abs(best[0] - second[0]) / abs(second[0]) * 100.0, 0))


def cmd_compare(a):
    cars = []
    for raw in a.vehicles:
        cars.append(firn_vehicle() if raw.strip().lower() in ("firn", "firn-01") else parse_vehicle(raw))
    if len(cars) < 2:
        die("compare takes two or more vehicles")
    names = [c[0] for c in cars]
    if len(set(n.lower() for n in names)) != len(names):
        die("vehicle names must differ")
    for name, value in (("--kwh-price", a.kwh_price), ("--fuel-price", a.fuel_price), ("--km-year", a.km_year)):
        if value is not None and value <= 0:
            die("%s must be more than zero" % name)
    rows = []

    def add(label, cells, vals, way, tag="", unit="", absolute=False):
        rows.append([label] + cells + [lead(names, vals, way, unit, absolute), tag])

    def col(key):
        return [c[1].get(key) for c in cars]

    def range_row():
        """Range as stated, else worked out from the store and the consumption."""
        ranges, cells, any_calc = [], [], False
        for c in cars:
            v = c[1]
            r = None
            if v.get("range") is not None:
                r = v["range"]
                cells.append("%s km" % num(r))
            elif v.get("battery") and v.get("kwh100"):
                r = v["battery"] / v["kwh100"] * 100.0
            elif v.get("tank") and v.get("l100"):
                r = v["tank"] / v["l100"] * 100.0
            if r is None:
                cells.append("-")
            elif v.get("range") is None:
                cells.append("~%s km" % num(r))
                any_calc = True
            ranges.append(r)
        if any(r is not None for r in ranges):
            add("range", cells, ranges, 1, "~ worked out from store and consumption" if any_calc else "")

    for key, label, unit, way, nd in FIELDS:
        if key == "range":
            range_row()
            continue
        vals = col(key)
        if all(v is None for v in vals):
            continue
        add(label, ["-" if v is None else _show(key, v) for v in vals], vals, way, unit=unit, absolute=key in ("zero100", "seats"))
        if key == "kg":
            ratio = [(c[1]["kw"] * 1000.0 / c[1]["kg"]) if c[1].get("kw") and c[1].get("kg") else None for c in cars]
            if any(r is not None for r in ratio):
                add("power to mass", ["-" if r is None else "%s W/kg" % num(r) for r in ratio], ratio, 1, "derived")
    # running cost
    costs, cells = [], []
    for c in cars:
        v = c[1]
        cost = None
        if v.get("kwh100") and a.kwh_price:
            cost = v["kwh100"] * a.kwh_price
        elif v.get("l100") and a.fuel_price:
            cost = v["l100"] * a.fuel_price
        costs.append(cost)
        cells.append("-" if cost is None else trim(cost, 2))
    yearly = [None] * len(cars)
    if any(c is not None for c in costs):
        add("energy per 100 km", cells, costs, -1, "derived")
        if a.km_year:
            yearly = [None if c is None else c * a.km_year / 100.0 for c in costs]
            add("energy per year", ["-" if y is None else num(y) for y in yearly], yearly, -1, "derived, %s km a year" % num(a.km_year))
    if a.km_year and any(c[1].get("co2") is not None for c in cars):
        tons = [None if c[1].get("co2") is None else c[1]["co2"] * a.km_year / 1e6 for c in cars]
        add("CO2 per year", ["-" if t is None else "%s t" % trim(t, 2) for t in tons], tons, -1, "derived, exhaust only")
    # what it costs to own: what it loses in value, what it burns, what it costs to keep on the road
    if a.years <= 0:
        die("--years must be more than zero")
    lost = [((c[1]["price"] - c[1]["resale"]) / a.years) if c[1].get("price") is not None and c[1].get("resale") is not None else None
            for c in cars]
    fixed = [sum(c[1][k] for k in YEARLY if c[1].get(k) is not None) if any(c[1].get(k) is not None for k in YEARLY) else None
             for c in cars]
    own_note = None
    if any(x is not None for x in lost):
        add("loss of value per year", ["-" if x is None else num(x) for x in lost], lost, -1, "derived, over %s years" % trim(a.years, 1))
    if any(x is not None for x in fixed):
        add("fixed costs per year", ["-" if x is None else num(x) for x in fixed], fixed, -1, "derived")
    parts = [(n, vals) for n, vals in (("loss of value", lost), ("energy", yearly), ("fixed costs", fixed)) if any(x is not None for x in vals)]
    whole = [(n, vals) for n, vals in parts if all(x is not None for x in vals)]
    if whole and any(n != "energy" for n, _ in whole):
        total = [sum(vals[i] for _, vals in whole) for i in range(len(cars))]
        tag = "derived: %s" % " + ".join(n for n, _ in whole)
        add("to own, per year", [num(t) for t in total], total, -1, tag)
        add("to own, per month", [num(t / 12.0) for t in total], [t / 12.0 for t in total], -1, "derived")
        if a.km_year:
            add("to own, per km", [trim(t / a.km_year, 2) for t in total], [t / a.km_year for t in total], -1, "derived")
        left = [n for n, _ in parts if n not in [w for w, _ in whole]]
        if left:
            own_note = "left out of the cost to own, because not every vehicle has the figure: %s" % ", ".join(left)
    extra = []
    for c in cars:
        for k in c[2]:
            if k not in TEXT_KEYS and k not in extra:
                extra.append(k)
    for k in ["drive", "fuel_type"] + extra:
        if any(k in c[2] for c in cars):
            rows.append([k.replace("_", " ")] + [c[2].get(k, "-") for c in cars] + ["-", ""])
    rec("COMPARE", " | ".join(names))
    out = [[r[0]] + r[1:-2] + [r[-2], ("[%s]" % r[-1]) if r[-1] else ""] for r in rows]
    table(out, header=["", ] + names + ["leads", ""], indent=2)
    for c in cars:
        src = c[2].get("source")
        rec("SOURCE", "%s: %s" % (c[0], src if src else "no source given: say where each figure came from, and its date, before passing this on"))
        if c[2].get("note"):
            more(c[2]["note"])
    prices = []
    if a.kwh_price:
        prices.append("electricity %s per kWh" % trim(a.kwh_price, 3))
    if a.fuel_price:
        prices.append("fuel %s per litre" % trim(a.fuel_price, 3))
    if prices:
        rec("PRICES", "%s [as given]" % "; ".join(prices))
    if own_note:
        rec("NOTE", own_note)
    rec("NOTE", "a lead is arithmetic on the figures given, not a recommendation. Makers measure range, consumption and mass "
                "in different ways: compare like with like")


def register(sub):
    p = command(sub, "garage", "compare", cmd_compare,
                "two or more vehicles side by side: the same rows, derived figures, and who leads each row",
                ['compare "Kestrel: kw=150, kg=1720, 0-100=7.9, battery=64, kwh100=17.1, price=189000" '
                 '"Heron: kw=110, kg=1340, 0-100=9.4, tank=45, l100=5.8, price=121000" --kwh-price 1.1 --fuel-price 6.5 --km-year 12000',
                 'compare firn "Heron: hp=148, kg=1340, 0-100=9.4, top=205, seats=5, source=maker brochure 2026"',
                 'compare "Kestrel: price=189000, resale=95000, kwh100=17.1, insurance=4200, service=900" '
                 '"Heron: price=121000, resale=60000, l100=5.8, insurance=3100, service=1600" --kwh-price 1.1 --fuel-price 6.5 '
                 "--km-year 12000 --years 5"])
    p.add_argument("vehicles", nargs="+",
                   help='"Name: key=value, ..." with plain numbers, or firn. Keys: kw (or hp, ps), nm, kg, 0-100, top, battery, kwh100, '
                        "tank, l100, range, seats, boot, payload, tow, length, width, height, wheelbase, clearance, co2, price, resale, "
                        "insurance, service, tax, other (the last four per year), year, source, drive, note")
    p.add_argument("--kwh-price", type=float, help="price of a kWh, to turn consumption into cost")
    p.add_argument("--fuel-price", type=float, help="price of a litre of fuel")
    p.add_argument("--km-year", type=float, help="distance driven in a year, for yearly cost and CO2")
    p.add_argument("--years", type=float, default=5.0, help="how long it is kept, for the loss of value (default 5)")
