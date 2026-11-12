"""Brief: one record for a journey, put together from the commands that already do each part.

Nothing is worked out twice: route, weather, country and fuel are run as they stand and their lines are thinned to what
a briefing needs. On a drive that has a time, the fatigue check runs unasked (the maker's ruling); when it has something
to say, the record says that it is there unasked and how to leave it out.
"""
import contextlib
import io

from . import geo
from .core import command, die, driver, trim

ROUTE_KEYS = ("ALSO", "CHECK", "ROAD", "FLOWN", "TRACK", "DRIVE", "BLOCK", "RIDE", "WALK", "BREAKS", "TOTAL", "BEST",
              "DEPART", "LEAVE BY", "ARRIVE", "NOTE", "LIGHT", "GLARE", "RANGE", "LIVE MAP")
WEATHER_KEYS = {"AIR": "WEATHER", "FEELS": "FEELS", "WIND": "WIND", "ROAD": "SURFACE", "STOP": "STOP", "SOURCE": "SOURCE"}
COUNTRY_DROP = ("DIAL", "CLOCKS")
FUEL_KEYS = ("FUEL", "ENERGY", "COST", "CO2", "TANK")
WEATHER_FLAGS = ("humidity", "dew", "road_temp", "wind", "wind_angle")
FUEL_FLAGS = ("l_100", "mpg_us", "mpg_uk", "kwh_100")


def _run(parser, argv):
    """Run one command and return what it printed as blocks: [key, first line, continuation lines...]."""
    ns = parser.parse_args([str(x) for x in argv])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns.func(ns)
    blocks = []
    for line in buf.getvalue().splitlines():
        if line.startswith(" ") and blocks:
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return blocks


def _key(block, keys):
    for k in keys:
        if block[0] == k or block[0].startswith(k + " "):
            return k
    return None


def _rekey(line, old, new):
    return "%-10s %s" % (new, line[len(old):].strip())


def cmd_brief(a):
    from . import fatigue, index
    if len(a.points) < 2:
        die("brief needs at least two points: where from and where to")
    weather_given = [f for f in WEATHER_FLAGS if getattr(a, f) is not None] + [f for f in ("wet", "snow") if getattr(a, f)]
    if weather_given and a.temp is None:
        die("the weather figures need --temp, the air temperature, with them")
    fuels = [f for f in FUEL_FLAGS if getattr(a, f)]
    if len(fuels) > 1:
        die("give one consumption figure: --l-100, --mpg-us, --mpg-uk or --kwh-100")
    parser = index.build_parser(["geo", "logistics", "country", "energy"])
    timed = bool(a.depart or a.arrive or a.window)
    check = timed and a.mode in fatigue.DRIVEN and not a.no_fatigue
    if a.low_hours and not check:
        die("--low-hours belongs to the fatigue check: a drive with a time, and no --no-fatigue")

    argv = ["route"] + list(a.points) + ["--mode", a.mode]
    for flag, value in (("--speed", a.speed), ("--road", a.road), ("--depart", a.depart), ("--arrive", a.arrive),
                        ("--window", a.window), ("--date", a.date), ("--tz", a.tz), ("--low-hours", a.low_hours)):
        if value is not None:
            argv.append("%s=%s" % (flag, value))
    argv += ["--before-dark"] if a.before_dark else []
    argv += ["--firn"] if a.firn else []
    argv += ["--fatigue"] if check else []
    route = _run(parser, argv)
    out, tired = [], []
    in_fatigue = False
    for block in route:
        if block[0].startswith("FATIGUE "):
            in_fatigue = True
        elif in_fatigue and _key(block, ("RANGE", "LIVE MAP", "NOTE")):
            in_fatigue = False
        if in_fatigue:
            tired.append(block)
        elif _key(block, ROUTE_KEYS):
            out.append(block)
    if not timed:
        out.append(["%-10s none given: no arrival time, light or fatigue check. Add --depart, --arrive or --window" % "TIME"])
    said = len(tired) > 1 or (tired and "clear of the low hours" not in tired[0][0])
    at = next((i for i, b in enumerate(out) if _key(b, ("RANGE", "LIVE MAP"))), len(out))
    if said:
        why = "this drive runs into the low hours" if "clear of the low hours" not in tired[0][0] else "this drive is long or short of breaks"
        tired.append(["%-10s the fatigue lines are here unasked, because %s. Tell %s so, and that a word from them leaves the lines "
                      "out (--no-fatigue)" % ("OFFER", why, driver())])
    out[at:at] = tired

    pts = [geo.parse_point(p) for p in a.points]
    if a.temp is None:
        out.append(["%-10s not checked: no forecast figures given. With --temp, and --humidity, --wind, --wet or --snow as the "
                    "forecast has them, the ice, fog and wind flags go in here" % "WEATHER"])
    else:
        argv = ["weather", "--temp=%s" % a.temp]
        for f in WEATHER_FLAGS:
            if getattr(a, f) is not None:
                argv.append("--%s=%s" % (f.replace("_", "-"), getattr(a, f)))
        argv += ["--wet"] if a.wet else []
        argv += ["--snow"] if a.snow else []
        if a.mode in fatigue.DRIVEN:
            argv.append("--speed=%s" % (a.speed if a.speed is not None else geo.MODES[a.mode][0]))
        for block in _run(parser, argv):
            k = _key(block, WEATHER_KEYS)
            if k:
                out.append([_rekey(block[0], k, WEATHER_KEYS[k])] + block[1:])

    ccs = [(p[3] or {}).get("cc") for p in pts]
    if ccs[0] and ccs[-1] and ccs[0] != ccs[-1]:
        for block in _run(parser, ["country", ccs[-1], "--from", ccs[0]]):
            if not _key(block, COUNTRY_DROP):
                out.append(block)
        between = []
        for cc in ccs[1:-1]:
            if cc and cc not in (ccs[0], ccs[-1]) and cc not in between:
                between.append(cc)
        if between:
            out.append(["%-10s also named on the way: %s. Run 'country' for each" % ("TRANSIT", ", ".join(between))])
    elif not (ccs[0] and ccs[-1]):
        out.append(["%-10s not checked: %s has no country on file (raw coordinates)" % (
            "COUNTRY", pts[0][0] if not ccs[0] else pts[-1][0])])

    if fuels:
        km = sum(geo.estimate_leg(p1, p2, a.mode, a.speed, a.road)[1] for p1, p2 in zip(pts, pts[1:]))
        argv = ["fuel", "--distance=%s" % trim(km, 1), "--%s=%s" % (fuels[0].replace("_", "-"), getattr(a, fuels[0])),
                "--fuel", a.fuel, "--people", a.people]
        for flag, value in (("--price", a.price), ("--tank", a.tank)):
            if value is not None:
                argv.append("%s=%s" % (flag, value))
        for block in _run(parser, argv):
            if _key(block, FUEL_KEYS):
                out.append(block)

    via = " via %s" % ", ".join(p[0] for p in pts[1:-1]) if len(pts) > 2 else ""
    print("%-10s %s -> %s%s [%s; one way]" % ("BRIEF", pts[0][0], pts[-1][0], via, a.mode))
    for block in out:
        print("\n".join(block))


def register(sub):
    p = command(sub, "ground", "brief", cmd_brief,
                "one record for a journey: route, arrival, light, fatigue, weather from forecast figures, the country ahead, fuel",
                ['brief krakow prague --depart "2026-12-05 09:00" --temp -1 --humidity 95 --wind 30 --l-100 6.5 --price 6.89',
                 'brief krakow gdansk --depart "2026-12-05 21:00"', 'brief krakow gdansk --depart "2026-12-05 21:00" --no-fatigue',
                 "brief krakow gdansk --window 05:00-11:00 --date 2026-12-05 --before-dark --temp 2 --wet",
                 "brief warsaw krakow --firn"])
    p.add_argument("points", nargs="+", help="from, any stops, to: as for 'route'")
    p.add_argument("--mode", default="car", choices=sorted(geo.MODES), help="as for 'route' (default car)")
    p.add_argument("--speed", type=float, help="average km/h, overrides the mode")
    p.add_argument("--road", type=float, help="travel distance / straight distance, overrides the mode")
    p.add_argument("--depart", help="departure, in the origin's own zone")
    p.add_argument("--arrive", help="plan backwards: be there by this time, in the destination's own zone")
    p.add_argument("--window", metavar="HH:MM-HH:MM", help="choose the departure for me, as 'route --window' does")
    p.add_argument("--date", help="the day for --window")
    p.add_argument("--before-dark", action="store_true", help="with --window: only departures that arrive before sunset")
    p.add_argument("--no-fatigue", action="store_true", help="leave the fatigue check out (a drive with a time gets it unasked)")
    p.add_argument("--low-hours", metavar="HH:MM-HH:MM", help="the low hours for the fatigue check (default 00:00-06:00)")
    p.add_argument("--tz", help="zone for points that have none (raw coordinates)")
    p.add_argument("--firn", action="store_true", help="also budget the journey against FIRN-01 lore range")
    p.add_argument("--temp", type=float, help="forecast: air temperature, C (needed for any weather line)")
    p.add_argument("--humidity", type=float, help="forecast: relative humidity, percent")
    p.add_argument("--dew", type=float, help="forecast: dew point, C (instead of humidity)")
    p.add_argument("--road-temp", type=float, help="forecast: road surface temperature, C")
    p.add_argument("--wind", type=float, help="forecast: wind speed, km/h")
    p.add_argument("--wind-angle", type=float, help="wind direction relative to the road: 0 head-on, 90 from the side")
    p.add_argument("--wet", action="store_true", help="the road is wet")
    p.add_argument("--snow", action="store_true", help="the road is snow-covered")
    p.add_argument("--l-100", type=float, help="fuel: litres per 100 km")
    p.add_argument("--mpg-us", type=float, help="fuel: miles per US gallon")
    p.add_argument("--mpg-uk", type=float, help="fuel: miles per imperial gallon")
    p.add_argument("--kwh-100", type=float, help="electric: kWh per 100 km")
    p.add_argument("--fuel", default="petrol", help="petrol (default), diesel or another fuel 'fuel' knows")
    p.add_argument("--price", type=float, help="price per litre (or per kWh)")
    p.add_argument("--people", type=int, default=1, help="split the cost between this many")
    p.add_argument("--tank", type=float, help="tank size, litres")
