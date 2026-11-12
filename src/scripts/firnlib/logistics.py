"""Logistics: getting several people to one place at one time, checklists, reading the weather for the road, and the way
back to where the car was left."""
import math
from datetime import datetime

from . import chrono, geo, ical
from .core import command, die, driver, fmt_hm, load_data, more, num, rec, trim


def plan_hours(hours, mode):
    """Travel hours with the mode's breaks and buffer added: (total, breaks, break hours, buffer hours)."""
    _, _, every, brk_min, buffer_pct, _ = geo.MODES[mode]
    breaks = int(hours // every) if every > 0 else 0
    if every > 0 and breaks and abs(hours - breaks * every) < 1e-9:
        breaks -= 1
    break_h = breaks * brk_min / 60.0
    buffer_h = (hours + break_h) * buffer_pct / 100.0
    return hours + break_h + buffer_h, breaks, break_h, buffer_h


# ---- convoy

def cmd_convoy(a):
    dest = geo.parse_point(a.to)
    dest_tz = geo.place_tz(dest, a.tz)
    arrive, note = chrono.parse_when(a.arrive, dest_tz)
    target = chrono.add(arrive, -a.margin * 60)
    parties = []
    for spec in a.parties:
        name, sep, place = spec.partition(":")
        if not sep or not name.strip() or not place.strip():
            die("each traveller is NAME:PLACE, for example anna:krakow")
        mode = a.mode
        if "@" in place:
            place, _, mode = place.partition("@")
            if mode not in geo.MODES:
                die("mode after @ must be one of: %s" % ", ".join(sorted(geo.MODES)))
        start = geo.parse_point(place.strip())
        s, km, hours, tag, _ = geo.estimate_leg(start, dest, mode)
        total, breaks, break_h, buffer_h = plan_hours(hours, mode)
        leave = chrono.to_utc(chrono.add(target, -total * 3600)).astimezone(geo.place_tz(start, a.tz))
        parties.append({"name": name.strip(), "start": start, "km": km, "hours": hours, "total": total, "breaks": breaks,
                        "leave": leave, "tag": tag, "mode": mode})
    if not parties:
        die("convoy needs at least one traveller: NAME:PLACE")
    parties.sort(key=lambda p: chrono.to_utc(p["leave"]))
    rec("MEET", "%s by %s%s" % (dest[0], chrono.fmt_dt(arrive), " (aiming %d min early)" % a.margin if a.margin else ""))
    width = max(len(p["name"]) for p in parties)
    for p in parties:
        rec(p["name"].upper()[:10], "leaves %s by %s | %s%s km, %s on the move%s, %s in all [%s, %s]" % (
            p["start"][0], chrono.fmt_dt(p["leave"]), "~" if p["tag"] == "estimate" else "", num(p["km"]), fmt_hm(p["hours"]),
            " + %d break%s" % (p["breaks"], "" if p["breaks"] == 1 else "s") if p["breaks"] else "", fmt_hm(p["total"]),
            p["tag"], p["mode"]))
    if len(parties) > 1:
        first, last = parties[0], parties[-1]
        gap = (chrono.to_utc(last["leave"]) - chrono.to_utc(first["leave"])).total_seconds() / 3600.0
        rec("ORDER", "%s is first out, %s before %s" % (first["name"].title(), fmt_hm(gap), last["name"].title()))
        rec("ROAD", "%s km driven between them" % num(sum(p["km"] for p in parties)))
    if note:
        rec("NOTE", note)
    guessed = any(p["tag"] == "estimate" for p in parties)
    if guessed:
        rec("NOTE", "distances are straight-line estimates; check each leg on a live map (route PLACE PLACE gives the link)")
    if a.ics:
        entries = []
        for p in parties:
            text = "Leave %s by %s.\n%s%s km, %s in all [%s, %s].\nEveryone meets at %s at %s." % (
                p["start"][0], chrono.fmt_dt(p["leave"]), "~" if p["tag"] == "estimate" else "", num(p["km"]), fmt_hm(p["total"]),
                p["tag"], p["mode"], dest[0], chrono.fmt_dt(arrive))
            entries.append(ical.event("%s: leave %s for %s" % (p["name"].title(), p["start"][0], dest[0]), p["leave"], target,
                                      location=p["start"][0], description=text, alarm=ical.alarm_of(a)))
        who = ", ".join(p["name"].title() for p in parties)
        entries.append(ical.event("Meet: %s" % dest[0], arrive, location=dest[0], description="Arriving together: %s." % who))
        ical.deliver(a, entries, "convoy-%s" % arrive.date().isoformat(), estimate=guessed)


# ---- checklist

def cmd_checklist(a):
    data = load_data("checklists")["lists"]
    if not a.name:
        for key, item in data.items():
            rec(key.upper(), "%s (%d items)" % (item["title"], len(item["items"])))
        rec("USE", "checklist NAME")
        return
    key = a.name.lower()
    hits = [k for k in data if k.startswith(key)]
    if len(hits) != 1:
        die("no checklist called '%s'; there are: %s" % (a.name, ", ".join(data)))
    item = data[hits[0]]
    rec("CHECKLIST", "%s [table]" % item["title"])
    for i, line in enumerate(item["items"], 1):
        more("%d. %s" % (i, line))
    rec("NOTE", "a checklist is a floor, not a ceiling; where it says check the rule, look the rule up for that country and date")


# ---- weather for the road

def dew_point(temp, humidity):
    g = math.log(humidity / 100.0) + 17.625 * temp / (243.04 + temp)
    return 243.04 * g / (17.625 - g)


def wind_chill(temp, wind_kmh):
    if temp > 10 or wind_kmh < 4.8:
        return None
    v = wind_kmh ** 0.16
    return 13.12 + 0.6215 * temp - 11.37 * v + 0.3965 * temp * v


def road_flags(temp, dew, road, wind, wet):
    """What a set of weather figures means for a road: a list of plain warnings, most serious first."""
    flags = []
    if road <= 0:
        if wet or (dew is not None and dew >= road - 0.5):
            flags.append("ICE LIKELY: surface at or below freezing with moisture about")
        else:
            flags.append("freezing surface, dry for now: any damp patch is ice")
    elif road <= 3:
        flags.append("near freezing: bridges, shade and hollows may already be icy while the rest is only wet")
    if dew is not None and temp - dew <= 2.5 and temp <= 12:
        flags.append("air close to its dew point: fog or mist likely, more so at dawn and in valleys")
    if wet and temp > 3:
        flags.append("wet road: braking distance grows by about half; aquaplaning risk rises with speed, standing water and worn tread")
    if wind and wind >= 60:
        flags.append("strong wind: exposed bridges and gaps between trees or lorries will push the car sideways; high-sided "
                     "vehicles and trailers are at real risk")
    elif wind and wind >= 40:
        flags.append("fresh wind: expect sideways shoves on bridges and when passing lorries")
    return flags


def cmd_weather(a):
    if a.humidity is not None and not 1 <= a.humidity <= 100:
        die("--humidity is a percentage, 1 to 100")
    rec("AIR", "%s C%s%s [as given]" % (trim(a.temp, 1), ", wind %s km/h" % trim(a.wind, 0) if a.wind else "",
                                        ", humidity %s%%" % trim(a.humidity, 0) if a.humidity is not None else ""))
    dp = a.dew
    if dp is None and a.humidity is not None:
        dp = dew_point(a.temp, a.humidity)
        rec("DEW POINT", "%s C [derived]" % trim(dp, 1))
    if a.wind:
        wc = wind_chill(a.temp, a.wind)
        if wc is not None:
            rec("FEELS", "%s C in the wind [derived]; dress and plan stops for that, not for the thermometer" % trim(wc, 0))
    road = a.road_temp if a.road_temp is not None else a.temp
    flags = road_flags(a.temp, dp, road, a.wind, a.wet)
    if a.wind and a.wind_angle is not None:
        cross = abs(a.wind * math.sin(math.radians(a.wind_angle)))
        head = a.wind * math.cos(math.radians(a.wind_angle))
        rec("WIND", "%s km/h across, %s km/h %s [derived, angle %s deg off the nose]" % (
            trim(cross, 0), trim(abs(head), 0), "against" if head >= 0 else "behind", trim(a.wind_angle, 0)))
    for f in flags:
        rec("ROAD", f)
    if not flags:
        rec("ROAD", "nothing in these figures calls for more than ordinary care")
    if a.speed:
        from .dynamics import SURFACES, parse_speed
        v = parse_speed(a.speed) / 3.6
        surface = "ice" if road <= 0 and (a.wet or (dp is not None and dp >= road - 0.5)) else "snow" if a.snow else "wet" if a.wet else "dry"
        mu = SURFACES[surface]
        dist = v * 1.0 + v * v / (2 * mu * 9.80665)
        rec("STOP", "from %s km/h on %s: about %s m including a second to react [estimate, typical grip]" % (
            trim(v * 3.6, 0), surface, trim(dist, 0)))
    rec("SOURCE", "the figures are %s's or a forecast's, not sensor readings; name the forecast and its time when passing this on" % driver())


# ---- where the car was left

_STAMP = "%Y-%m-%dT%H:%MZ"


def _metres(km):
    return "%s m" % num(round(km * 1000.0)) if km < 1 else "%s km" % trim(km, 2)


def cmd_park(a):
    if a.find:
        if a.place or not a.spot or not a.frm:
            die("park --find needs --spot (it is on the STAMP line) and --from, where you are now")
        spot, here = geo.parse_point(a.spot), geo.parse_point(a.frm)
        km = geo.haversine_km(here[1], here[2], spot[1], spot[2])
        brg = geo.bearing_deg(here[1], here[2], spot[1], spot[2])
        if km * 1000.0 < 15:
            rec("CAR", "within about 15 m of %s: you are standing next to him [derived]" % here[0])
        else:
            rec("CAR", "%s away, bearing %03.0f %s from %s [derived, straight line]" % (_metres(km), brg, geo.compass(brg), here[0]))
            rec("WALK", "about %s at %s km/h if the way is straight [estimate]" % (
                fmt_hm(km / geo.MODES["walk"][0]), trim(geo.MODES["walk"][0], 1)))
        if a.at:
            try:
                then = datetime.strptime(a.at, _STAMP).replace(tzinfo=chrono.UTC)
            except ValueError:
                die("--at is the time from the STAMP line, like 2026-11-10T13:30Z")
            ago = (chrono.now_in(chrono.UTC) - then).total_seconds() / 3600.0
            if ago < 0:
                die("--at is in the future: copy it from the STAMP line as it stands")
            rec("PARKED", "%s ago" % fmt_hm(ago))
        if km > 3:
            rec("CHECK", "that is far for a car park: is the spot right, and is 'from' where you are?")
        rec("NOTE", "he has no fix on %s's position: both points are as given" % driver())
        return
    if not a.place or a.spot or a.frm or a.at:
        die("park SPOT when you leave the car; later, park --find --spot ... --from WHERE-YOU-ARE")
    spot = geo.parse_point(a.place)
    now = chrono.now_in(geo.place_tz(spot))
    rec("PARKED", "%s%s at %s" % (spot[0], " (%s)" % a.note if a.note else "", chrono.fmt_dt(now)))
    rec("STAMP", "park --find --spot %s,%s --at %s --from WHERE-YOU-ARE" % (
        trim(spot[1], 6), trim(spot[2], 6), chrono.to_utc(now).strftime(_STAMP)))
    more("keep that line: it is all that remembers the spot, and it lasts for this conversation unless %s saves it" % driver())
    if spot[3] is not None and spot[3].get("kind") not in ("home", "work", "poi"):
        more("a named town is good to a few kilometres: for a car park, give the pin from a phone map as lat,lon")


def register(sub):
    p = command(sub, "ground", "park", cmd_park,
                "where the car was left: stamp the spot, and later the distance and compass bearing back to it",
                ["park 50.26453,19.02372 --note \"level 2, row C\"",
                 "park --find --spot 50.26453,19.02372 --from 50.25990,19.02160 --at 2026-11-10T12:10Z"])
    p.add_argument("place", nargs="?", help="where the car is: lat,lon from a phone map, or a place")
    p.add_argument("--note", help="anything worth keeping with it: the level, the row, the street")
    p.add_argument("--find", action="store_true", help="the way back: needs --spot and --from")
    p.add_argument("--spot", help="with --find: the car's spot, from the STAMP line")
    p.add_argument("--from", dest="frm", help="with --find: where you are now, lat,lon or a place")
    p.add_argument("--at", help="with --find: when the car was parked, from the STAMP line")

    p = command(sub, "ground", "convoy", cmd_convoy,
                "several people, one place, one time: when each must leave to arrive together, and a calendar file",
                ['convoy anna:krakow bob:warsaw --to katowice --arrive "2026-12-20 18:00"',
                 'convoy anna:krakow@rail bob:wroclaw --to prague --arrive "2026-12-20 18:00" --margin 15',
                 'convoy anna:krakow bob:warsaw --to katowice --arrive "2026-12-20 18:00" --ics auto'])
    p.add_argument("parties", nargs="+", help="NAME:PLACE, or NAME:PLACE@MODE for someone not driving")
    p.add_argument("--to", required=True, help="where everyone meets")
    p.add_argument("--arrive", required=True, help="when, in the meeting place's own time")
    p.add_argument("--mode", default="car", choices=sorted(geo.MODES), help="how people travel unless they say otherwise (default car)")
    p.add_argument("--margin", type=int, default=0, help="aim to be there this many minutes early")
    p.add_argument("--tz", help="zone for places that have none")
    ical.add_option(p, "each traveller's departure and the meeting")

    p = command(sub, "desk", "checklist", cmd_checklist,
                "short lists worth reading out: predrive, winter, longhaul, airport, ev, breakdown, sim",
                ["checklist", "checklist winter", "checklist airport"])
    p.add_argument("name", nargs="?", help="which list (leave out to see them all)")

    p = command(sub, "sky", "weather", cmd_weather,
                "read forecast figures for the road: dew point, wind chill, ice, fog and wind flags, stopping distance",
                ["weather --temp -1 --humidity 95 --wind 30", "weather --temp 2 --road-temp -1 --wet --speed 90",
                 "weather --temp 8 --wind 70 --wind-angle 80"])
    p.add_argument("--temp", type=float, required=True, help="air temperature, C")
    p.add_argument("--humidity", type=float, help="relative humidity, percent")
    p.add_argument("--dew", type=float, help="dew point, C (instead of humidity)")
    p.add_argument("--road-temp", type=float, help="road surface temperature, C, if the forecast gives one")
    p.add_argument("--wind", type=float, help="wind speed, km/h")
    p.add_argument("--wind-angle", type=float, help="wind direction relative to the road: 0 head-on, 90 from the side")
    p.add_argument("--wet", action="store_true", help="the road is wet")
    p.add_argument("--snow", action="store_true", help="the road is snow-covered")
    p.add_argument("--speed", help="also give a stopping distance from this speed")
