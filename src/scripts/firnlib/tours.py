"""Two questions of order and fairness: in what order to run errands, and where several people should meet.

tour     the best order for a set of stops, by travel time. Every order is weighed, so the answer is exact for
         the leg figures used; the figures themselves are estimates unless a checked leg is on file.
halfway  towns ranked by how far the worst-placed traveller has to go, then by the travel of all of them together.
"""
import math

from . import chrono, geo
from .core import command, die, fmt_hm, more, num, rec, trim

MAX_STOPS = 12


def leg_matrix(pts, mode, via="auto"):
    """cost[i][j] = (hours, km, tag) for every ordered pair of points."""
    n = len(pts)
    cost = [[None] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                _, km, hours, tag, _ = geo.estimate_leg(pts[i], pts[j], mode, via=via)
                cost[i][j] = (hours, km, tag)
    return cost


def best_order(cost, n, loop, end):
    """Held-Karp: the cheapest order that starts at point 0 and visits 1..n-1.
    loop returns to 0; end (an index) fixes the last stop; otherwise the tour may end anywhere."""
    stops = list(range(1, n))
    if not stops:
        return [0]
    full = (1 << len(stops)) - 1
    best = {}
    for k, s in enumerate(stops):
        best[(1 << k, k)] = (cost[0][s][0], None)
    for mask in range(1, full + 1):
        for k in range(len(stops)):
            if not mask & (1 << k) or (mask, k) not in best:
                continue
            base = best[(mask, k)][0]
            for m in range(len(stops)):
                if mask & (1 << m):
                    continue
                new = (mask | (1 << m), m)
                value = base + cost[stops[k]][stops[m]][0]
                if new not in best or value < best[new][0] - 1e-12:
                    best[new] = (value, k)
    finals = []
    for k, s in enumerate(stops):
        if (full, k) not in best:
            continue
        if end is not None and s != end:
            continue
        finals.append((best[(full, k)][0] + (cost[s][0][0] if loop else 0.0), k))
    _, k = min(finals)
    order, mask = [], full
    while k is not None:
        order.append(stops[k])
        prev = best[(mask, k)][1]
        mask &= ~(1 << k)
        k = prev
    order.reverse()
    return [0] + order + ([0] if loop else [])


def cmd_tour(a):
    if a.loop and a.end:
        die("give --loop or --end, not both")
    names = list(a.points)
    end = None
    pts = [geo.parse_point(p) for p in names]
    if a.end:
        ep = geo.parse_point(a.end)
        same = [i for i, p in enumerate(pts) if i > 0 and abs(p[1] - ep[1]) < 1e-9 and abs(p[2] - ep[2]) < 1e-9]
        if same:
            end = same[0]
        else:
            pts.append(ep)
            end = len(pts) - 1
    n = len(pts)
    if n < 3:
        die("a tour is a start and at least two stops; for one stop, use 'route'")
    if n - 1 > MAX_STOPS:
        die("up to %d stops: every order is weighed, and that grows fast" % MAX_STOPS)
    if a.stop_min < 0:
        die("--stop-min cannot be negative")
    if a.via != "auto" and a.mode not in geo.crossing.DRIVEN:
        die("--via chooses how a drive gets across water: it goes with car, motorway or city mode")
    cost = leg_matrix(pts, a.mode, a.via)
    order = list(range(n)) + ([0] if a.loop else []) if a.keep_order else best_order(cost, n, a.loop, end)
    given = list(range(n)) + ([0] if a.loop else [])
    if end is not None and not a.keep_order:
        given = [i for i in range(n) if i != end] + [end]

    def total(seq):
        return (sum(cost[x][y][0] for x, y in zip(seq, seq[1:])), sum(cost[x][y][1] for x, y in zip(seq, seq[1:])))

    hours, km = total(order)
    guessed = any(cost[x][y][2] == "estimate" for x, y in zip(order, order[1:]))
    shape = "back to the start" if a.loop else ("ending at %s" % pts[end][0] if end is not None else "ending wherever is best")
    rec("TOUR", "%d stops from %s, %s | %s%s" % (n - 1, pts[0][0], shape, a.mode, " | order kept as given" if a.keep_order else ""))
    rec("ORDER", " -> ".join(pts[i][0] for i in order))
    dep = note = None
    if a.depart:
        dep, note = chrono.parse_when(a.depart, geo.place_tz(pts[0], a.tz))
    clock = dep
    for k, (x, y) in enumerate(zip(order, order[1:]), 1):
        h, d, tag = cost[x][y]
        line = "%s -> %s | %s%s km | %s [%s]" % (pts[x][0], pts[y][0], "~" if tag == "estimate" else "", trim(d, 1), fmt_hm(h), tag)
        if clock is not None:
            clock = chrono.add(clock, h * 3600)
            there = chrono.to_utc(clock).astimezone(geo.place_tz(pts[y], a.tz))
            line += " | there %s" % there.strftime("%H:%M")
            if k < len(order) - 1:
                clock = chrono.add(clock, a.stop_min * 60)
        rec("LEG %d" % k, line)
        geo.say_land(pts[x], pts[y], a.mode, tag, "leg %d" % k, a.via)
    visits = max(0, len(order) - 2)
    stop_h = visits * a.stop_min / 60.0
    rec("TOTAL", "%s%s km, %s on the move%s = %s [%s]" % (
        "~" if guessed else "", trim(km, 1), fmt_hm(hours),
        " + %d x %d min at the stops" % (visits, a.stop_min) if visits and a.stop_min else "", fmt_hm(hours + stop_h),
        "estimate" if guessed else "checked legs"))
    if dep is not None:
        rec("DEPART", "%s  %s" % (chrono.fmt_dt(dep), pts[0][0]))
        rec("DONE", "%s  %s" % (chrono.fmt_dt(chrono.to_utc(clock).astimezone(geo.place_tz(pts[order[-1]], a.tz))), pts[order[-1]][0]))
    if not a.keep_order:
        g_hours, g_km = total(given)
        if g_hours - hours > 1e-9:
            rec("SAVED", "%s and %s km against the order as given (%s%% of the driving)" % (
                fmt_hm(g_hours - hours), trim(g_km - km, 1), trim((g_hours - hours) / g_hours * 100.0, 0)))
        else:
            rec("SAVED", "nothing: the order as given was already the best")
    if note:
        rec("NOTE", note)
    link = geo.map_link([pts[i] for i in order], a.mode)
    if link:
        rec("LIVE MAP", link)
    rec("NOTE", "every order was weighed, so this is the best one for these leg figures%s" % (
        "; the figures are straight-line estimates, so two stops close together may swap on real roads" if guessed else ""))


def _centre(points):
    """The mean point of some places on the sphere: (lat, lon)."""
    x = y = z = 0.0
    for lat, lon in points:
        la, lo = math.radians(lat), math.radians(lon)
        x += math.cos(la) * math.cos(lo)
        y += math.cos(la) * math.sin(lo)
        z += math.sin(la)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def cmd_halfway(a):
    people = []
    for spec in a.parties:
        name, sep, place = spec.partition(":")
        if not sep or not name.strip() or not place.strip():
            die("each traveller is NAME:PLACE, for example anna:krakow")
        mode = a.mode
        if "@" in place:
            place, _, mode = place.partition("@")
            if mode not in geo.MODES:
                die("mode after @ must be one of: %s" % ", ".join(sorted(geo.MODES)))
        people.append((name.strip(), geo.parse_point(place.strip()), mode))
    if len(people) < 2:
        die("halfway needs at least two travellers")
    if a.top < 1:
        die("--top is at least 1")
    if a.candidates:
        cands = [geo.parse_point(c) for c in a.candidates]
    else:
        clat, clon = _centre([(p[1][1], p[1][2]) for p in people])
        reach = max(geo.haversine_km(clat, clon, p[1][1], p[1][2]) for p in people) * 1.1 + 25.0
        if a.min_pop < 0:
            die("--min-pop is a number of people, 0 for every town")
        near = geo.near(clat, clon, reach, kinds=("capital", "city"))
        # a place to meet wants somewhere to sit down: by default only towns of some size, capitals, and the driver's own places
        near = [r for r in near if r[1].get("kind") == "capital" or "pop" not in r[1] or r[1]["pop"] >= a.min_pop]
        if len(near) > 400:
            near = sorted(near, key=lambda r: (-(r[1].get("pop") or 0), r[0]))[:400]
        cands = [(pl.get("name", pl["key"]), pl["lat"], pl["lon"], pl) for _, pl in near]
        have = set((round(c[1], 4), round(c[2], 4)) for c in cands)
        for _, pt, _ in people:
            if (round(pt[1], 4), round(pt[2], 4)) not in have:
                cands.append(pt)
    if not cands:
        die("no town in the gazetteer lies between them; name some with --candidates")
    rows = []
    for c in cands:
        times = []
        for name, pt, mode in people:
            if abs(pt[1] - c[1]) < 1e-9 and abs(pt[2] - c[2]) < 1e-9:
                times.append(0.0)
            else:
                times.append(geo.estimate_leg(pt, c, mode)[2])
        rows.append((max(times), sum(times), c[0], times, c))
    rows.sort(key=lambda r: (round(r[0], 4), round(r[1], 4), r[2]))
    among = "" if a.candidates else " between them (%s)" % (
        "every town" if a.min_pop == 0 else "towns of %s people or more; --min-pop changes that" % num(a.min_pop))
    rec("HALFWAY", "%d travellers, %d place%s weighed%s | fairest first [estimate]" % (
        len(people), len(rows), "" if len(rows) == 1 else "s", among))
    for n, (worst, total, name, times, _) in enumerate(rows[:a.top], 1):
        who = people[times.index(worst)][0]
        rec(str(n), "%s | longest %s (%s) | all together %s | %s" % (
            name, fmt_hm(worst), who, fmt_hm(total), ", ".join("%s %s" % (p[0], fmt_hm(t)) for p, t in zip(people, times))))
    # water between a traveller and the fairest place is said, as route says it
    best = rows[0][4]
    for who, pt, mode in people:
        if abs(pt[1] - best[1]) > 1e-9 or abs(pt[2] - best[2]) > 1e-9:
            geo.say_land(pt, best, mode, geo.estimate_leg(pt, best, mode)[3], "%s to %s" % (who.title(), best[0]))
    quick = min(rows, key=lambda r: (round(r[1], 4), round(r[0], 4)))
    if quick[2] != rows[0][2]:
        rec("LEAST", "%s has the least travel in all, %s, but its longest trip is %s" % (quick[2], fmt_hm(quick[1]), fmt_hm(quick[0])))
    rec("NEXT", "convoy %s --to PLACE --arrive TIME gives each of them a leave-by time" % " ".join(a.parties))
    more("times are from straight-line distances unless a checked leg is on file: check the winner on a live map")


def register(sub):
    p = command(sub, "ground", "tour", cmd_tour, "the best order for a set of stops, with times at each and what the reordering saves",
                ["tour krakow katowice wroclaw opole lodz --loop", "tour krakow wroclaw katowice opole --end wroclaw",
                 'tour krakow katowice opole wroclaw --depart "2026-11-14 09:00" --stop-min 20', "tour krakow opole katowice --keep-order"])
    p.add_argument("points", nargs="+", help="the start, then every stop: gazetteer places, home, work, your own places, or lat,lon")
    p.add_argument("--loop", action="store_true", help="come back to the start")
    p.add_argument("--end", help="finish here (one of the stops, or another place)")
    p.add_argument("--mode", default="car", choices=sorted(geo.MODES), help="how you travel (default car)")
    p.add_argument("--via", default="auto", choices=geo.crossing.VIAS,
                   help="across water with a car: auto (the quicker way, and it asks), sea (the car comes along) or air (it stays behind)")
    p.add_argument("--depart", help="when you set off, to get a time at each stop")
    p.add_argument("--stop-min", type=int, default=10, help="minutes spent at each stop (default 10)")
    p.add_argument("--keep-order", action="store_true", help="do not reorder: just add it up as given")
    p.add_argument("--tz", help="zone for points that have none")

    p = command(sub, "ground", "halfway", cmd_halfway, "where several people should meet: towns ranked by the longest trip, then by all the travel",
                ["halfway anna:krakow bob:warsaw", "halfway anna:krakow bob:warsaw carol:wroclaw --top 3",
                 "halfway anna:krakow bob:gdansk@rail --candidates lodz warsaw bydgoszcz"])
    p.add_argument("parties", nargs="+", help="NAME:PLACE, or NAME:PLACE@MODE for someone not driving")
    p.add_argument("--candidates", nargs="+", help="weigh only these places (default: every town in the gazetteer between them)")
    p.add_argument("--mode", default="car", choices=sorted(geo.MODES), help="how people travel unless they say otherwise (default car)")
    p.add_argument("--top", type=int, default=5, help="how many to list (default 5)")
    p.add_argument("--min-pop", type=int, default=50000, help="leave out towns smaller than this (default 50,000; 0 for every town)")
