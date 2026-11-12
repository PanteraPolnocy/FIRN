"""Where no road joins two places: how a journey by car gets across.

In order: a car-carrying crossing on file (the car comes along), a plan by air (it stays behind), and as a last
resort a guess over water at the pace of the ferries on file. Everything here is an estimate from geometry:
which flight or which boat really runs is the airline's or the operator's to say.
"""
import re

from .core import fmt_hm, load_data, num, trim

DRIVEN = ("car", "motorway", "city")
VIAS = ("auto", "air", "sea")
AIR_BEFORE_MIN, AIR_AFTER_MIN = 120, 45     # the defaults 'trip' uses for a flight: be there before, get out after
LARGE_KM, ANY_KM = 150.0, 300.0             # how far to look for a large airport, and for any with scheduled flights

_sets = []


def _airports():
    if not _sets:
        table = load_data("airports")
        _sets.extend((frozenset(table["large"].split()), frozenset(table["scheduled"].split())))
    return _sets


def code(point):
    """'WAW' from 'Warsaw Chopin Airport (WAW)', or the whole label."""
    m = re.search(r"\(([A-Z0-9]{3,4})\)$", point[0])
    return m.group(1) if m else point[0]


def airport_for(point):
    """The airport a traveller at this point would leave from, as a parsed point, or None.
    The point itself if it is an airport; else the nearest large airport with scheduled flights within 150 km on the
    same land mass; else the nearest of any size with scheduled flights within 300 km."""
    from . import geo
    if (point[3] or {}).get("kind") == "airport":
        return point
    home = geo.land_of(point)
    if not home:
        return None
    large, scheduled = _airports()
    fallback = None
    for d, p in geo.near(point[1], point[2], ANY_KM, kinds=["airport"], with_own=False):
        if p["key"] not in large and p["key"] not in scheduled:
            continue
        port = (p["name"], p["lat"], p["lon"], p)
        land = geo.land_of(port)
        if not land or land[0] != home[0]:
            continue
        if p["key"] in large and d <= LARGE_KM:
            return port
        fallback = fallback or port
    return fallback


def sea_speed():
    """km/h for a guess over water: the median straight-line pace of the ferries on file."""
    from . import geo
    paces = sorted(geo.haversine_km(c["ends"][0][2], c["ends"][0][3], c["ends"][1][2], c["ends"][1][3]) / (c["board_min"] / 60.0)
                   for c in load_data("landmasses")["crossings"] if c["kind"] == "ferry")
    mid = len(paces) // 2
    return paces[mid] if len(paces) % 2 else (paces[mid - 1] + paces[mid]) / 2.0


def _drive(parts, p1, p2, mode, speed, road):
    from . import geo
    if geo.haversine_km(p1[1], p1[2], p2[1], p2[2]) < 0.05:
        return
    _, km, hours, tag, _ = geo.ground_leg(p1, p2, mode, speed, road)
    parts.append({"kind": "drive", "km": km, "hours": hours, "to": p2,
                  "text": "drive    %s -> %s: %s%s km, %s%s" % (p1[0], p2[0], "~" if tag == "estimate" else "", num(km), fmt_hm(hours),
                                                               "" if tag == "estimate" else " [%s]" % tag)})


def _finish(plan):
    parts = plan["parts"]
    plan["hours"] = sum(p["hours"] for p in parts)
    plan["wheel_h"] = sum(p["hours"] for p in parts if p["kind"] == "drive")
    plan["ground_km"] = sum(p["km"] for p in parts if p["kind"] == "drive")
    plan["carried_km"] = sum(p["km"] for p in parts if p["kind"] == "carried")
    return plan


def _by_ferry(p1, p2, a, b, mode, speed, road):
    """The quickest car crossing on file between two land masses, as a plan, or None."""
    best = None
    for c in load_data("landmasses")["crossings"]:
        ends = dict((e[0], (e[1], e[2], e[3], None)) for e in c["ends"])
        if set(ends) != set((a[0], b[0])):
            continue
        near_port, far_port = ends[a[0]], ends[b[0]]
        parts = []
        _drive(parts, p1, near_port, mode, speed, road)
        parts.append({"kind": "wait", "km": 0.0, "hours": c["before_min"] / 60.0,
                      "text": "terminal %s before departure [%s]" % (fmt_hm(c["before_min"] / 60.0), c["source"])})
        parts.append({"kind": "carried", "km": 0.0, "hours": c["board_min"] / 60.0,
                      "text": "%-8s %s -> %s: %s on board [%s]" % (c["kind"], near_port[0], far_port[0],
                                                                   fmt_hm(c["board_min"] / 60.0), c["source"])})
        _drive(parts, far_port, p2, mode, speed, road)
        plan = _finish({"how": "ferry", "key": "CROSSING", "parts": parts, "link": c, "ports": (near_port[0], far_port[0])})
        if best is None or plan["hours"] < best["hours"]:
            best = plan
    return best


def _by_air(p1, p2, mode, speed, road):
    """Drive to an airport, fly as if direct, drive on: a plan, or None when either end has no airport to use."""
    from . import geo
    a1, a2 = airport_for(p1), airport_for(p2)
    if not a1 or not a2 or a1[3]["key"] == a2[3]["key"]:
        return None
    air_speed, stretch, _, _, _, overhead = geo.MODES["air"]
    km = geo.haversine_km(a1[1], a1[2], a2[1], a2[2]) * stretch
    parts = []
    _drive(parts, p1, a1, mode, speed, road)
    parts.append({"kind": "wait", "km": 0.0, "hours": AIR_BEFORE_MIN / 60.0,
                  "text": "airport  %s before the flight" % fmt_hm(AIR_BEFORE_MIN / 60.0)})
    parts.append({"kind": "carried", "km": km, "hours": km / air_speed + overhead,
                  "text": "fly      %s -> %s: ~%s km, %s as if flown direct" % (code(a1), code(a2), num(km), fmt_hm(km / air_speed + overhead))})
    parts.append({"kind": "wait", "km": 0.0, "hours": AIR_AFTER_MIN / 60.0,
                  "text": "airport  %s to get out" % fmt_hm(AIR_AFTER_MIN / 60.0)})
    _drive(parts, a2, p2, mode, speed, road)
    return _finish({"how": "air", "key": "NO ROAD", "parts": parts, "ports": (code(a1), code(a2)), "airports": (a1, a2)})


def _by_guess(p1, p2):
    from . import geo
    km = geo.haversine_km(p1[1], p1[2], p2[1], p2[2])
    pace = sea_speed()
    part = {"kind": "carried", "km": km, "hours": km / pace,
            "text": "by sea   %s -> %s: %s km in a straight line at %s km/h, the pace of the ferries on file: %s" % (
                p1[0], p2[0], num(km), trim(pace, 0), fmt_hm(km / pace))}
    return _finish({"how": "sea", "key": "NO ROAD", "parts": [part], "ports": (p1[0], p2[0])})


def plan(p1, p2, mode, via="auto", speed=None, road=None):
    """How a drive gets from p1 to p2 when no road joins them, or None when one does (or the mode is not a drive).
    A dict: how (ferry, air, sea), key (CROSSING when the car is carried, else NO ROAD), parts, hours, wheel_h,
    ground_km, carried_km, why, summary, and 'also' when a second way is worth naming."""
    from . import geo
    if mode not in DRIVEN:
        return None
    a, b = geo.land_of(p1), geo.land_of(p2)
    if not a or not b or a[0] == b[0]:
        return None
    table = load_data("landmasses")
    ferry = _by_ferry(p1, p2, a, b, mode, speed, road)
    air = _by_air(p1, p2, mode, speed, road) if via != "sea" else None
    if via == "air":
        chosen = air or ferry or _by_guess(p1, p2)
    else:
        chosen = ferry or air or _by_guess(p1, p2)
    gap = table["gaps"].get("|".join(sorted((a[0], b[0]))))
    where = geo.land_phrases(a, b)
    apart = gap or "%s is %s and %s is %s. No road joins them" % (p1[0], where[0], p2[0], where[1])
    total = fmt_hm(chosen["hours"])
    if chosen["how"] == "ferry":
        link = chosen["link"]
        chosen["why"] = link.get("why") or "%s: a car is carried, on %s" % (apart, link["name"])
        chosen["summary"] = "by %s, %s to %s: %s on board after %s at the terminal, %s door to door" % (
            link["kind"], chosen["ports"][0], chosen["ports"][1], fmt_hm(link["board_min"] / 60.0), fmt_hm(link["before_min"] / 60.0), total)
        chosen["short"] = "by %s, %s to %s" % (link["kind"], chosen["ports"][0], chosen["ports"][1])
        chosen["small"] = "%sa queue at the terminal or the port is not counted [%s]" % (
            link["more"] + ", and " if link.get("more") else "", link["source"])
        if air and via == "auto":
            chosen["also"] = "by air, without the car: %s door to door, %s to %s. Add --via air for that plan" % (
                fmt_hm(air["hours"]), air["ports"][0], air["ports"][1])
    elif chosen["how"] == "air":
        chosen["why"] = "%s, so this leg is planned by air and the car stays behind" % apart
        chosen["summary"] = "by air, %s to %s: %s door to door" % (chosen["ports"][0], chosen["ports"][1], total)
        chosen["short"] = "no road: by air, %s to %s" % (chosen["ports"][0], chosen["ports"][1])
        chosen["small"] = ("as if flown direct at %s km/h: which airports a real ticket uses, and any change on the way, is the "
                           "airline's to say. Look the flight up" % trim(geo.MODES["air"][0], 0))
        if not ferry:
            chosen["small"] += ". No car ferry is on file between these two: if the car must come, search for one"
        elif via == "air":
            chosen["also"] = "with the car, by %s, %s to %s: %s door to door. Leave out --via air for that plan" % (
                ferry["link"]["kind"], ferry["ports"][0], ferry["ports"][1], fmt_hm(ferry["hours"]))
    else:
        short = [p[0] for p, port in ((p1, airport_for(p1)), (p2, airport_for(p2))) if not port]
        chosen["why"] = "%s, and no car ferry between them is on file%s" % (
            apart, "" if via == "sea" or not short else "; no airport with scheduled flights is within %s km of %s" % (
                trim(ANY_KM, 0), " or ".join(short)))
        chosen["summary"] = "a guess over water: %s" % total
        chosen["short"] = "no road: a guess over water"
        chosen["small"] = "a guess, not a journey: no boat is known to run this way. Search for one, or try --mode air"
    return chosen
