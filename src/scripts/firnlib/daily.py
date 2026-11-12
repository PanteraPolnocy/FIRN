"""Everyday sums for a car that is used: stops on a route, warming the cabin, heat in a parked car, an overtake, a mileage log."""
import math
from types import SimpleNamespace

from . import chrono
from .core import command, die, fmt_hm, load_data, more, num, rec, trim


# ---- stops

def cmd_stops(a):
    """Where along a route the range runs out, how many stops that makes, and what they add."""
    from . import energy, geo
    pts = [geo.parse_point(p) for p in a.points]
    if len(pts) < 2:
        die("stops needs at least two points")
    if a.firn and a.range is not None:
        die("--firn uses his own range: leave out --range")
    if not a.firn and a.range is None:
        die("give --range, the km a full tank or charge takes this car, or --firn for FIRN-01")
    for name in ("start", "reserve", "fill"):
        if not 0 <= getattr(a, name) <= 100:
            die("--%s is a percentage, 0 to 100" % name)
    if a.fill <= a.reserve:
        die("--fill must be above --reserve, or a stop adds nothing")
    if a.start < a.reserve:
        die("--start is already below --reserve")
    lore = load_data("lore") if a.firn else None
    full = float(lore["chassis"]["range_km"]) if a.firn else a.range
    if full <= 0:
        die("--range is more than zero")
    battery = float(lore["chassis"]["bank_kwh"]) if a.firn else a.battery
    if a.kw is not None and a.kw <= 0:
        die("--kw is more than zero")
    if not a.firn and (a.kw is None) != (a.battery is None):
        die("a charging time needs both --battery and --kw; or give --stop-min for a fuel stop")
    kw = a.kw if a.kw is not None else (float(lore["recharge"]["road_kw"]) if a.firn else None)

    legs, total = [], 0.0
    estimated = False
    for i, (p1, p2) in enumerate(zip(pts, pts[1:]), 1):
        plan = geo.crossing.plan(p1, p2, a.mode, "sea")      # the car is the point: a crossing on file, or nothing
        if plan and plan["how"] != "ferry":
            die("leg %d has no road and no car crossing on file: plan the stops for each drive on its own" % i)
        _, km, _, tag, _ = geo.estimate_leg(p1, p2, a.mode, via="sea")
        estimated = estimated or tag == "estimate"
        legs.append((p1, p2, km))
        total += km
    rec("ROUTE", "%s: %s%s km by road%s" % (" -> ".join(p[0] for p in pts), "~" if estimated else "", num(total),
                                           " [estimate: straight line x %s]" % trim(geo.MODES[a.mode][1], 2) if estimated else " [checked legs]"))
    rec("RANGE", "%s km on a full %s [%s]; starting at %s%%, never below %s%%, each stop fills to %s%%" % (
        num(full), "bank" if a.firn else "tank or charge", "lore" if a.firn else "as given", trim(a.start, 0), trim(a.reserve, 0), trim(a.fill, 0)))

    def where(km_along):
        """The point a distance along the route, on the straight line of its leg, and the town nearest to it."""
        done = 0.0
        for n, (p1, p2, km) in enumerate(legs, 1):
            if km_along <= done + km or n == len(legs):
                f = 0.0 if km <= 0 else min(1.0, max(0.0, (km_along - done) / km))
                lat, lon = geo.intermediate(p1[1], p1[2], p2[1], p2[2], f)
                hit = geo.nearest(lat, lon, 60.0, lambda p: p.get("kind") in ("capital", "city"))
                town = "near %s" % hit[1]["name"] if hit else "no town on file within 60 km"
                return "leg %d, %s" % (n, town)
            done += km

    def minutes(pct_from, pct_to):
        if battery and kw:
            if a.firn:
                return battery * (pct_to - pct_from) / 100.0 / kw * 60.0
            profile = energy.charge_profile(SimpleNamespace(kw=kw, car_max=None, knee=50.0, tail=0.25, ac=False))
            return energy.charge_time_h(battery, pct_from, pct_to, profile) * 60.0
        return float(a.stop_min)

    at, pct, stops, added = 0.0, a.start, 0, 0.0
    while True:
        reach = full * (pct - a.reserve) / 100.0
        if at + reach >= total - 1e-9:
            break
        at += reach
        stops += 1
        if stops > 60:
            die("more than 60 stops: check --range against the distance")
        took = minutes(a.reserve, a.fill)
        added += took
        rec("STOP %d" % stops, "by km %s (%s): %s%% -> %s%%, %s" % (
            num(at), where(at), trim(a.reserve, 0), trim(a.fill, 0), fmt_hm(took / 60.0)))
        pct = a.fill
    left = pct - (total - at) / full * 100.0
    if stops:
        rec("STOPS", "%d, adding %s%s" % (stops, fmt_hm(added / 60.0),
                                         " [%s kW, %s]" % (trim(kw, 0), "steady: his recharge has no taper on file" if a.firn else
                                                           "tapering above 50% as 'ev charge' does") if battery and kw else " [%d min each, as given]" % a.stop_min))
    else:
        rec("STOPS", "none: the range covers it")
    rec("ARRIVE", "with %s%% (%s km of range)" % (trim(left, 0), num(full * left / 100.0)))
    if a.firn:
        rec("HOME", "on his own spine in the bay a full bank takes %s min [lore]; on the road he takes what the charger gives" % trim(
            lore["recharge"]["spine_min"], 0))
    rec("NOTE", "a stop is the last point the reserve allows: stop sooner, where there is a pump or a charger. The towns are the "
                "nearest on file to the straight line, so the road may pass others")


# ---- precondition

def cmd_precondition(a):
    """When to start warming or cooling the cabin to leave on time, and what it costs."""
    if a.minutes <= 0 or a.minutes > 180:
        die("--minutes is how long the car needs, 1 to 180: from its handbook, or from timing it once")
    tz = chrono.get_tz(a.tz) if a.tz else chrono.home_tz()
    leave, note = chrono.parse_when(a.leave, tz)
    start = chrono.add(leave, -a.minutes * 60)
    rec("LEAVE", chrono.fmt_dt(leave))
    rec("START", "%s: %d min before [as given]" % (chrono.fmt_dt(start), a.minutes))
    if note:
        rec("NOTE", note)
    if a.kw is not None:
        if a.kw <= 0:
            die("--kw is more than zero")
        kwh = a.kw * a.minutes / 60.0
        rec("ENERGY", "%s kWh: %s kW for %d min [as given]" % (trim(kwh, 2), trim(a.kw, 1), a.minutes))
        if a.plugged:
            rec("RANGE", "none lost: on the cable the energy comes from the wall")
        elif a.kwh_100:
            rec("RANGE", "about %s km of range, at %s kWh per 100 km [derived]" % (trim(kwh / a.kwh_100 * 100.0, 0), trim(a.kwh_100, 1)))
        else:
            more("add --kwh-100 for the range it takes off the battery, or --plugged if it is on the cable")
        if a.price is not None:
            rec("COST", "%s [%s kWh x %s]" % (trim(kwh * a.price, 2), trim(kwh, 2), trim(a.price, 2)))
    else:
        more("add --kw, the heater or cooler's draw, for the energy and what it costs")
    if a.outside is not None and a.outside <= 3:
        rec("GLASS", "%s C outside: clear every window before you move, whatever the clock says" % trim(a.outside, 1))
    rec("NOTE", "the minutes are the car's, not a figure from here: a handbook or one timed morning gives them")


# ---- hotcar

def rise_f(table, minutes):
    """Degrees F a closed car's air has risen after so many minutes in the sun, between the study's points; None past the last."""
    pts = [(0.0, 0.0)] + [(float(m), float(r)) for m, r in table["rise_f"]]
    if minutes > pts[-1][0]:
        return None
    for (m1, r1), (m2, r2) in zip(pts, pts[1:]):
        if minutes <= m2:
            return r1 + (r2 - r1) * (minutes - m1) / (m2 - m1)


def cmd_hotcar(a):
    """How hot a closed, parked car gets in the sun, from the published study."""
    table = load_data("cabin_heat")
    lo_c, hi_c = [(f - 32.0) / 1.8 for f in table["ambient_f"]]
    rec("OUTSIDE", "%s C, in the sun, windows shut" % trim(a.temp, 1))
    rows = [(m, r) for m, r in table["rise_f"]]
    for m, r in rows:
        rec("%d MIN" % m, "about %s C inside (+%s C)" % (trim(a.temp + r / 1.8, 0), trim(r / 1.8, 0)))
    for label, r1, r2 in table["later_f"]:
        rec(label.upper(), "about %s to %s C inside (+%s to +%s C)" % (
            trim(a.temp + r1 / 1.8, 0), trim(a.temp + r2 / 1.8, 0), trim(r1 / 1.8, 0), trim(r2 / 1.8, 0)))
    if a.minutes is not None:
        if a.minutes <= 0:
            die("--minutes is more than zero")
        r = rise_f(table, a.minutes)
        if r is None:
            rec("AT", "%s min is past the study's hour: read the later rows" % trim(a.minutes, 0))
        else:
            rec("AT", "%s min: about %s C inside [between the study's points]" % (trim(a.minutes, 0), trim(a.temp + r / 1.8, 0)))
    rec("WINDOWS", "left open a crack they changed the rise by less than %s C [%s]" % (trim(table["cracked_f"] / 1.8, 1), table["tag"]))
    if not lo_c - 0.05 <= a.temp <= hi_c + 0.05:
        rec("CHECK", "the study measured days of %s to %s C: at %s C this is outside what it saw" % (trim(lo_c, 0), trim(hi_c, 0), trim(a.temp, 1)))
    rec("SOURCE", "%s [%s]" % (table["source"], table["tag"]))
    rec("RULE", "nobody waits in a parked car in the sun: not a child, not an animal, not for a minute's errand")


# ---- overtake

def cmd_overtake(a):
    """Time and road an overtake takes, and the clear road it needs with something coming the other way."""
    lore = load_data("lore")["chassis"] if a.firn else None
    own = a.len if a.len is not None else (float(lore["length_m"]) if lore else None)
    if own is None:
        die("give --len, your own vehicle's length in metres, or --firn")
    accel = a.accel
    basis = "as given"
    if accel is None and a.zero_100 is not None:
        accel, basis = (100 / 3.6) / a.zero_100, "the average over 0-100 km/h in %s s" % trim(a.zero_100, 1)
    if accel is None and lore:
        accel, basis = (100 / 3.6) / float(lore["zero_100_s"]), "sheet: the average over his 0-100 km/h in %s s" % trim(lore["zero_100_s"], 1)
    other = a.other if a.other is not None else a.speed
    top = a.to if a.to is not None else a.speed
    for name, value in (("--speed", a.speed), ("--other", other), ("--to", top), ("--other-len", a.other_len), ("--len", own)):
        if value <= 0:
            die("%s is more than zero" % name)
    if top < a.speed:
        die("--to is the speed you pass at: not below --speed")
    if top > a.speed and (accel is None or accel <= 0):
        die("to speed up from %s to %s km/h give --accel (m/s2) or --zero-100 (s)" % (trim(a.speed, 0), trim(top, 0)))
    if top <= other:
        die("you pass at %s km/h and it does %s: you never get by. Raise --to" % (trim(top, 0), trim(other, 0)))
    v1, v2, v3 = a.speed / 3.6, other / 3.6, top / 3.6
    gap_out, gap_in = a.gap_s * v1, a.gap_s * v2
    gain = gap_out + a.other_len + own + gap_in        # how much further than the other vehicle you must travel
    t_acc = (v3 - v1) / accel if v3 > v1 else 0.0
    gained = (v1 - v2) * t_acc + 0.5 * (accel or 0.0) * t_acc ** 2
    if gained >= gain:      # done while still speeding up
        t = (-(v1 - v2) + math.sqrt((v1 - v2) ** 2 + 2 * accel * gain)) / accel
        dist = v1 * t + 0.5 * accel * t ** 2
        peak = v1 + accel * t
    else:
        t = t_acc + (gain - gained) / (v3 - v2)
        dist = v1 * t_acc + 0.5 * (accel or 0.0) * t_acc ** 2 + v3 * (t - t_acc)
        peak = v3
    rec("PASS", "%s km/h past %s km/h: %s s and %s m of road, from pulling out to back in lane [derived]" % (
        trim(peak * 3.6, 0), trim(other, 0), trim(t, 1), num(dist)))
    rec("GAIN", "%s m more than it travels: %s m behind it, its %s m, your %s m, %s m ahead of it (%s s gaps)" % (
        trim(gain, 0), trim(gap_out, 0), trim(a.other_len, 1), trim(own, 2), trim(gap_in, 0), trim(a.gap_s, 1)))
    if v3 > v1:
        rec("PACE", "%s -> %s km/h at %s m/s2 [%s]%s" % (trim(a.speed, 0), trim(peak * 3.6, 0), trim(accel, 2), basis,
                                                       "" if peak >= v3 - 1e-9 else ": back in lane before reaching %s" % trim(top, 0)))
    need = dist
    if a.oncoming is not None:
        if a.oncoming < 0:
            die("--oncoming is a speed, km/h")
        need = dist + a.oncoming / 3.6 * t
        rec("CLEAR", "%s m of empty road ahead when you pull out: your %s m and the %s m something at %s km/h covers towards you" % (
            num(need), num(dist), num(need - dist), trim(a.oncoming, 0)))
    if a.see is not None:
        if a.oncoming is None:
            more("--see is judged against oncoming traffic: add --oncoming, the speed of what may come")
        elif a.see >= need * 1.5:
            rec("VERDICT", "room: %s m in view against %s m needed, half as much again or better" % (num(a.see), num(need)))
        elif a.see >= need:
            rec("VERDICT", "bare: %s m in view against %s m needed leaves no margin. Wait" % (num(a.see), num(need)))
        else:
            rec("VERDICT", "NO: %s m needed, %s m in view" % (num(need), num(a.see)))
    rec("NOTE", "steady acceleration, then a steady speed, and the other vehicle holds its own: a model, not a promise. "
                "A hill, a load or a second lorry ahead of the first changes all of it")


# ---- mileage

def _trip(line):
    """'2026-11-03 | Tychy > Katowice | 18 | work' -> (date, label, km, estimated, purpose)."""
    from . import geo
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 2 or not parts[1]:
        die("a trip is 'DATE | FROM > TO | KM | PURPOSE' (km and purpose may be left out): %s" % line)
    day = chrono.parse_date(parts[0])
    if day is None:
        die("not a date (YYYY-MM-DD): %s" % parts[0])
    back = "<>" in parts[1]
    ends = [e.strip() for e in parts[1].replace("<>", ">").split(">")]
    if len(ends) < 2 or not all(ends):
        die("a trip names where from and where to, with > between (or <> for there and back): %s" % parts[1])
    km_text = parts[2] if len(parts) > 2 else ""
    purpose = (parts[3] if len(parts) > 3 else "").lower() or "unsorted"
    estimated = not km_text
    if km_text:
        try:
            km = float(km_text.lower().replace("km", "").replace(",", ".").strip())
        except ValueError:
            die("km must be a number: %s" % km_text)
        if km < 0:
            die("km cannot be negative: %s" % km_text)
    else:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):     # a town two countries share would print its ALSO line here
            pts = [geo.parse_point(e) for e in ends]
        km = 0.0
        for p1, p2 in zip(pts, pts[1:]):
            plan = geo.crossing.plan(p1, p2, "car", "sea")
            if plan and plan["how"] != "ferry":
                die("no road from %s to %s: give the km for that trip yourself" % (p1[0], p2[0]))
            km += geo.estimate_leg(p1, p2, "car", via="sea")[1]
        km *= 2 if back else 1
        ends = [p[0] for p in pts]
    return day, (" <> " if back else " > ").join(ends), km, estimated, purpose


def cmd_mileage(a):
    """Totals for trip lines the driver keeps: by month and by purpose, and what they come to at a rate per km."""
    if a.rate is not None and a.rate < 0:
        die("--rate cannot be negative")
    trips = sorted((_trip(line) for line in a.trips), key=lambda t: t[0])
    months, purposes = {}, {}
    for day, label, km, estimated, purpose in trips:
        rec("TRIP", "%s | %s | %s%s km | %s" % (day.isoformat(), label, "~" if estimated else "", trim(km, 1), purpose))
        month = months.setdefault(day.strftime("%Y-%m"), {})
        month[purpose] = month.get(purpose, 0.0) + km
        purposes[purpose] = purposes.get(purpose, 0.0) + km
    for key in sorted(months):
        split = months[key]
        rec("MONTH", "%s: %s km (%s)" % (key, trim(sum(split.values()), 1), ", ".join("%s %s" % (p, trim(split[p], 1)) for p in sorted(split))))
    total = sum(t[2] for t in trips)
    guessed = sum(1 for t in trips if t[3])
    rec("TOTAL", "%d trip%s, %s km%s" % (len(trips), "" if len(trips) == 1 else "s", trim(total, 1),
                                          " [%d estimated from the straight line: put the odometer's figure in]" % guessed if guessed else ""))
    if len(purposes) > 1:
        rec("BY PURPOSE", ", ".join("%s %s km" % (p, trim(purposes[p], 1)) for p in sorted(purposes)))
    if a.rate is not None:
        only = a.only.lower() if a.only else None
        if only and only not in purposes:
            die("no trip has the purpose '%s': there is %s" % (a.only, ", ".join(sorted(purposes))))
        base = purposes[only] if only else total
        rec("CLAIM", "%s%s [%s km%s x %s, rate as given]" % (trim(base * a.rate, 2), " " + a.currency if a.currency else "",
                                                           trim(base, 1), " of %s" % only if only else "", trim(a.rate, 4)))
    rec("KEEP", "the tools hold nothing between conversations: these lines are the log, so keep them where you keep records")


def register(sub):
    p = command(sub, "energy", "stops", cmd_stops,
                "fuel or charge stops along a route: where the range runs out, how many stops, the time they add; or FIRN-01's own",
                ["stops warsaw lisbon --range 620 --stop-min 12", "stops krakow gdansk --range 380 --start 80 --fill 80 --battery 77 --kw 150",
                 "stops warsaw lisbon --firn", "stops warsaw berlin paris --range 450 --reserve 15"])
    p.add_argument("points", nargs="+", help="places, as for 'route'")
    p.add_argument("--range", type=float, help="km this car covers on a full tank or charge, as you know it")
    p.add_argument("--firn", action="store_true", help="FIRN-01: his range and his recharge, from the lore")
    p.add_argument("--start", type=float, default=100.0, help="percent in the tank or battery at the start (default 100)")
    p.add_argument("--reserve", type=float, default=10.0, help="percent never to go below (default 10)")
    p.add_argument("--fill", type=float, default=100.0, help="percent each stop fills to (default 100; 80 suits a rapid charger)")
    p.add_argument("--stop-min", type=int, default=10, help="minutes a fuel stop takes (default 10)")
    p.add_argument("--battery", type=float, help="usable pack, kWh: with --kw the stop time is worked out")
    p.add_argument("--kw", type=float, help="charger power, kW")
    p.add_argument("--mode", default="car", choices=("car", "motorway", "city"), help="as for 'route' (default car)")

    p = command(sub, "energy", "precondition", cmd_precondition,
                "when to start warming or cooling the cabin to leave on time, and what it costs in energy, range and money",
                ['precondition --leave "2026-11-13 07:30" --minutes 20', 'precondition --leave 07:30 --minutes 25 --kw 3 --kwh-100 18 --outside -5',
                 "precondition --leave 16:00 --minutes 10 --kw 2 --plugged --price 1.1"])
    p.add_argument("--leave", required=True, help="when you want to drive off")
    p.add_argument("--minutes", type=int, required=True, help="how long this car needs: from its handbook, or timed once")
    p.add_argument("--kw", type=float, help="what the heater or cooler draws, kW")
    p.add_argument("--kwh-100", type=float, help="the car's consumption, kWh per 100 km: gives the range it costs")
    p.add_argument("--plugged", action="store_true", help="on the cable: the energy comes from the wall")
    p.add_argument("--price", type=float, help="price per kWh")
    p.add_argument("--outside", type=float, help="temperature outside, C")
    p.add_argument("--tz", help="zone for --leave (default: home)")

    p = command(sub, "sky", "hotcar", cmd_hotcar,
                "how hot a closed, parked car gets in the sun after 10, 20, 30 and 60 minutes, from the published study",
                ["hotcar --temp 26", "hotcar --temp 31 --minutes 15"])
    p.add_argument("--temp", type=float, required=True, help="temperature outside, C")
    p.add_argument("--minutes", type=float, help="how long the car has stood, for the figure in between")

    p = command(sub, "vehicle", "overtake", cmd_overtake,
                "an overtake in seconds and metres, and the clear road it needs against oncoming traffic",
                ["overtake --speed 80 --to 100 --accel 1.5 --len 4.5 --other-len 16.5 --oncoming 90 --see 600",
                 "overtake --speed 70 --other 60 --to 90 --zero-100 9.5 --len 4.4 --other-len 12", "overtake --speed 90 --to 120 --other-len 18 --firn --oncoming 90"])
    p.add_argument("--speed", type=float, required=True, help="your speed when you pull out, km/h")
    p.add_argument("--other", type=float, help="the speed of the vehicle ahead, km/h (default: the same as yours)")
    p.add_argument("--to", type=float, help="the speed you pass at, km/h (default: no speeding up)")
    p.add_argument("--accel", type=float, help="your acceleration while passing, m/s2")
    p.add_argument("--zero-100", type=float, help="or the car's 0-100 km/h time, s: its average is used")
    p.add_argument("--len", type=float, help="your vehicle's length, m")
    p.add_argument("--other-len", type=float, required=True, help="the length of what you pass, m: ask, or read it off the vehicle")
    p.add_argument("--gap-s", type=float, default=2.0, help="the gap you keep behind it and leave ahead of it, s (default 2)")
    p.add_argument("--oncoming", type=float, help="the speed of what may come the other way, km/h")
    p.add_argument("--see", type=float, help="the clear road you can see, m: gives a verdict")
    p.add_argument("--firn", action="store_true", help="FIRN-01: his length and his 0-100 time, from the sheet")

    p = command(sub, "garage", "mileage", cmd_mileage,
                "a mileage log from the trip lines you keep: totals by month and purpose, and the claim at a rate per km",
                ['mileage "2026-11-03 | Tychy > Katowice | 18 | work" "2026-11-05 | Tychy <> Krakow | | private"',
                 'mileage "2026-11-03 | Tychy > Katowice | 18 | work" "2026-11-09 | Tychy > Gliwice | 31.5 | work" --rate 1.15 --currency PLN --only work'])
    p.add_argument("trips", nargs="+", help="'DATE | FROM > TO | KM | PURPOSE': <> for there and back; leave KM empty for an estimate")
    p.add_argument("--rate", type=float, help="money per km, for the claim")
    p.add_argument("--currency", help="its currency, for the label")
    p.add_argument("--only", help="claim one purpose only")
