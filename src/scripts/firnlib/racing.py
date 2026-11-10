"""Racing arithmetic: pit strategy for fuel and tyres, and lap-time pace maths.

Game values (fuel per lap, tyre life, pit loss, refuel rate) are passed in from the race settings or a
practice run. Nothing is built in for any game.
"""
import math

from .core import command, die, fmt_dur, fmt_lap, more, num, parse_laptime, rec, table, trim


def _stint_laps(total, stints):
    base, extra = divmod(total, stints)
    return [base + (1 if i < extra else 0) for i in range(stints)]


def _strategy_time(laps_total, stops, lap, fuel_lap, cfg):
    """(total seconds, stint list, fuel added per stop, reason-if-impossible)."""
    stints = _stint_laps(laps_total, stops + 1)
    if min(stints) < 1:
        return None, stints, [], "more stops than laps"
    longest = max(stints)
    if fuel_lap > 0:
        cap = int(math.floor(cfg["tank"] / fuel_lap - cfg["margin"] + 1e-9))
        if longest > cap:
            return None, stints, [], "a %d-lap stint needs %s of fuel, the tank holds %s (%d laps)" % (
                longest, trim((longest + cfg["margin"]) * fuel_lap, 1), trim(cfg["tank"], 1), cap)
    if cfg["tyre_life"] and longest > cfg["tyre_life"]:
        return None, stints, [], "a %d-lap stint outlasts the tyres (%d laps)" % (longest, cfg["tyre_life"])
    total = 0.0
    for n in stints:
        total += n * lap + cfg["deg"] * n * (n - 1) / 2.0
    adds = []
    for n in stints[1:]:
        add = n * fuel_lap
        adds.append(add)
        total += cfg["pit"] + cfg["tyre_change"] + (add / cfg["refuel_rate"] if cfg["refuel_rate"] else 0.0)
    return total, stints, adds, None


def _laps_in_time(seconds, stops, lap, fuel_lap, cfg):
    """Laps completed when the clock runs out: the lap in progress is finished."""
    n = max(stops + 1, int(seconds // (lap + cfg["deg"] * 50)) - 2)
    while n < 100000:
        t, _, _, why = _strategy_time(n, stops, lap, fuel_lap, cfg)
        if why:
            return n, why
        if t >= seconds:
            return n, None
        n += 1
    return n, "no finish found"


def cmd_stint(a):
    if (a.laps is None) == (a.minutes is None):
        die("give the race length as --laps or --minutes")
    lap = parse_laptime(a.lap)
    if lap <= 0 or a.fuel_lap < 0 or a.tank <= 0:
        die("lap time and tank must be positive")
    cfg = {"tank": a.tank, "margin": a.margin, "tyre_life": a.tyre_life, "deg": a.deg, "pit": a.pit,
           "tyre_change": a.tyre_change, "refuel_rate": a.refuel_rate}
    modes = [("push", lap, a.fuel_lap)]
    for spec in a.save or []:
        parts = spec.split(",")
        if len(parts) != 2:
            die("--save takes LAPTIME,FUEL_PER_LAP, e.g. 1:43.4,2.8")
        try:
            modes.append(("save %d" % len(modes), parse_laptime(parts[0]), float(parts[1])))
        except ValueError:
            die("--save takes LAPTIME,FUEL_PER_LAP, e.g. 1:43.4,2.8")
    rec("RACE", "%s | lap %s | fuel %s per lap, tank %s | pit loss %s s%s%s%s [game values as given]" % (
        "%d laps" % a.laps if a.laps else "%s minutes" % trim(a.minutes, 1), fmt_lap(lap), trim(a.fuel_lap, 2), trim(a.tank, 1),
        trim(a.pit, 1), ", tyres good for %d laps" % a.tyre_life if a.tyre_life else "",
        ", %s s lost per lap of tyre age" % trim(a.deg, 3) if a.deg else "",
        ", refuel %s per s" % trim(a.refuel_rate, 2) if a.refuel_rate else ""))
    results, bad = [], []
    for name, mlap, mfuel in modes:
        for stops in range(0, a.max_stops + 1):
            if a.laps:
                t, stints, adds, why = _strategy_time(a.laps, stops, mlap, mfuel, cfg)
                laps = a.laps
            else:
                laps, why = _laps_in_time(a.minutes * 60.0, stops, mlap, mfuel, cfg)
                t, stints, adds, why2 = _strategy_time(laps, stops, mlap, mfuel, cfg)
                why = why or why2
            if why:
                bad.append((name, stops, why))
            else:
                results.append((laps, t, name, stops, stints, adds, mlap, mfuel))
    if not results:
        rec("RESULT", "no strategy fits within %d stops" % a.max_stops)
        for name, stops, why in bad[:6]:
            more("%s, %d stop%s: %s" % (name, stops, "" if stops == 1 else "s", why))
        return
    results.sort(key=lambda r: (-r[0], r[1]))
    best = results[0]
    rows = []
    for laps, t, name, stops, stints, adds, mlap, mfuel in results[:a.show]:
        if a.laps:
            delta = "best" if (laps, t) == (best[0], best[1]) else "+%s" % fmt_dur(t - best[1])
        else:
            delta = "best" if (laps, t) == (best[0], best[1]) else (
                "%d lap%s down" % (best[0] - laps, "" if best[0] - laps == 1 else "s") if laps < best[0] else "+%s at the flag" % fmt_dur(t - best[1]))
        rows.append((name, str(stops), "-".join(str(n) for n in stints), str(laps), fmt_lap(t),
                     " ".join("+" + trim(x, 1) for x in adds) or "-", delta))
    table(rows, header=("mode", "stops", "stints (laps)", "laps", "race time", "fuel at each stop", "against best"), indent=2, right=(1, 3))
    laps, t, name, stops, stints, adds, mlap, mfuel = best
    start_fuel = min(a.tank, (stints[0] + a.margin) * mfuel)
    rec("BEST", "%s, %d stop%s: stints %s; start with %s of fuel [derived]" % (
        name, stops, "" if stops == 1 else "s", "-".join(str(n) for n in stints), trim(start_fuel, 1)))
    if stops > 0 and mfuel > 0:
        longest = max(_stint_laps(laps, stops))
        need = a.tank / (longest + a.margin)
        if need < mfuel:
            saved = a.pit + a.tyre_change
            text = "dropping to %d stop%s needs %s per lap or less (%s%% less than now); it saves %s in the pits, " \
                   "so it pays if saving fuel costs under %s s a lap" % (
                       stops - 1, "" if stops - 1 == 1 else "s", trim(need, 2), trim(100.0 * (1 - need / mfuel), 0),
                       fmt_dur(saved), trim(saved / float(laps), 2))
            if a.tyre_life and longest > a.tyre_life:
                text += " - but the tyres would not last a %d-lap stint" % longest
            rec("ONE LESS", text + " [derived]")
    for name, stops, why in bad[:3]:
        rec("RULED OUT", "%s, %d stop%s: %s" % (name, stops, "" if stops == 1 else "s", why))
    rec("NOTE", "equal stints, steady pace, no traffic, safety car or weather; test the lap and fuel figures in practice first")


def cmd_pace(a):
    done = False
    lap = parse_laptime(a.lap) if a.lap else None
    if lap and a.km:
        rec("SPEED", "%s on a %s km lap is %s km/h average [derived]" % (fmt_lap(lap), trim(a.km, 3), trim(a.km / lap * 3600.0, 1)))
        done = True
    if lap and a.laps:
        rec("DISTANCE", "%d laps at %s take %s%s" % (a.laps, fmt_lap(lap), fmt_lap(lap * a.laps),
                                                      ", %s km" % num(a.km * a.laps, 1) if a.km else ""))
        done = True
    if a.gap is not None and a.laps_left:
        per = a.gap / a.laps_left
        text = "close %s s in %d laps: %s s a lap faster than the car ahead" % (trim(a.gap, 2), a.laps_left, trim(per, 3))
        if lap:
            text += ", so %s against their %s" % (fmt_lap(lap - per), fmt_lap(lap))
        rec("CHASE", text + " [derived]")
        done = True
    if a.delta is not None and a.laps:
        rec("DELTA", "%s s a lap over %d laps is %s s" % (trim(a.delta, 3), a.laps, trim(a.delta * a.laps, 2)))
        done = True
    if a.target and a.laps:
        tgt = parse_laptime(a.target)
        rec("TARGET", "%s over %d laps needs an average lap of %s" % (fmt_lap(tgt), a.laps, fmt_lap(tgt / a.laps)))
        done = True
    if a.used is not None and a.over:
        per = a.used / a.over
        rec("FUEL", "%s used over %d laps is %s per lap" % (trim(a.used, 2), a.over, trim(per, 3)))
        if a.tank:
            rec("", "a tank of %s lasts %s laps" % (trim(a.tank, 1), trim(a.tank / per, 1)))
        done = True
    if a.minutes and lap:
        rec("TIMED", "%s minutes at %s is %s laps, so the race is %d laps (the lap in progress is finished)" % (
            trim(a.minutes, 1), fmt_lap(lap), trim(a.minutes * 60.0 / lap, 2), int(math.floor(a.minutes * 60.0 / lap)) + 1))
        done = True
    if not done:
        die("pace needs a pair to work with: --lap with --km, --laps or --minutes; --gap with --laps-left; "
            "--delta with --laps; --target with --laps; --used with --over")


def _slope(xs, ys):
    """Least-squares slope and intercept of y on x."""
    n = float(len(xs))
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return 0.0, my
    k = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return k, my - k * mx


def cmd_laps(a):
    times = [parse_laptime(t) for t in a.times]
    if len(times) < 3:
        die("laps needs at least three lap times to say anything: laps 1:42.5 1:42.9 1:43.4 ...")
    if any(t <= 0 for t in times):
        die("a lap time must be above zero")
    if a.skip_first < 0 or a.skip_last < 0 or a.skip_first + a.skip_last > len(times) - 3:
        die("after skipping the out lap and the in lap there must be at least three laps left")
    numbered = list(enumerate(times, 1))
    run = numbered[a.skip_first:len(numbered) - a.skip_last if a.skip_last else None]
    ordered = sorted(t for _, t in run)
    median = ordered[len(ordered) // 2] if len(ordered) % 2 else (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2.0
    limit = median * (1.0 + a.outlier / 100.0)
    clean = [(n, t) for n, t in run if t <= limit]
    slow = [(n, t) for n, t in run if t > limit]
    if len(clean) < 3:
        die("fewer than three clean laps are left: raise --outlier, or give more laps")
    best_n, best = min(clean, key=lambda x: x[1])
    vals = [t for _, t in clean]
    mean = sum(vals) / len(vals)
    sd = math.sqrt(sum((t - mean) ** 2 for t in vals) / len(vals))
    rec("LAPS", "%d given, %d used%s%s" % (
        len(times), len(clean), ", out and in laps left out" if a.skip_first or a.skip_last else "",
        "; set aside as traffic or a mistake: %s" % ", ".join("lap %d (%s)" % (n, fmt_lap(t)) for n, t in slow) if slow else ""))
    rec("BEST", "%s on lap %d" % (fmt_lap(best), best_n))
    rec("AVERAGE", "%s, %s s off the best; median %s" % (fmt_lap(mean), trim(mean - best, 3), fmt_lap(median)))
    close = sum(1 for t in vals if t - best <= a.window)
    rec("STEADY", "+/- %s s around the average; %d of %d laps within %s s of the best [derived]" % (
        trim(sd, 3), close, len(vals), trim(a.window, 2)))
    k, c = _slope([n for n, _ in clean], vals)
    if a.fuel_gain:
        rec("PACE DROP", "%s s a lap as measured; fuel burning off is worth %s s a lap, so the tyres cost %s s a lap [derived]" % (
            trim(k, 3), trim(a.fuel_gain, 3), trim(k + a.fuel_gain, 3)))
        deg = k + a.fuel_gain
    else:
        rec("PACE DROP", "%s s a lap over the run [derived: a straight line through the clean laps]" % trim(k, 3))
        deg = k
    if deg > 0.0005:
        more("for the pit wall: stint ... --lap %s --deg %s" % (fmt_lap(c + k * clean[0][0]), trim(deg, 3)))
    elif deg < -0.0005:
        more("the laps got quicker, not slower: the track or the driver improved, so this run says nothing about tyre wear")
    else:
        more("no drop to speak of over this run")
    if a.sectors:
        rows = []
        for s in a.sectors:
            parts = [parse_laptime(x) for x in s.replace(",", " ").split()]
            if len(parts) < 2:
                die("--sectors takes one quoted lap of sector times at a time: --sectors \"31.2 40.1 31.0\"")
            rows.append(parts)
        if len(set(len(r) for r in rows)) != 1:
            die("every lap must have the same number of sectors")
        ideal = sum(min(r[i] for r in rows) for i in range(len(rows[0])))
        actual = min(sum(r) for r in rows)
        rec("IDEAL LAP", "%s from the best of each sector, %s s quicker than the best lap actually driven (%s) [derived]" % (
            fmt_lap(ideal), trim(actual - ideal, 3), fmt_lap(actual)))
        worst = max(range(len(rows[0])), key=lambda i: sum(r[i] for r in rows) / len(rows) - min(r[i] for r in rows))
        more("most time is being left in sector %d: on average %s s off its best there" % (
            worst + 1, trim(sum(r[worst] for r in rows) / len(rows) - min(r[worst] for r in rows), 3)))
    rec("NOTE", "a short run in clear air; traffic, fuel load and a changing track all move these numbers. Say how many laps it rests on")


def register(sub):
    p = command(sub, "racing", "laps", cmd_laps,
                "read a run of lap times: best, average, consistency, the pace drop per lap that feeds stint, the ideal lap from sectors",
                ["laps 1:42.5 1:42.7 1:42.9 1:43.4 1:43.3 1:43.8 1:44.1", "laps 1:50.2 1:42.5 1:42.9 1:49.9 1:43.4 1:43.6 1:55.0 --skip-first 1 --skip-last 1",
                 'laps 1:42.5 1:42.9 1:43.4 1:43.6 --fuel-gain 0.03 --sectors "31.2 40.1 31.2" --sectors "31.0 40.6 31.3" --sectors "31.4 40.0 32.0"'])
    p.add_argument("times", nargs="+", help="lap times in order: 1:42.5 or 102.5")
    p.add_argument("--skip-first", type=int, default=0, help="laps to leave out at the start (an out lap)")
    p.add_argument("--skip-last", type=int, default=0, help="laps to leave out at the end (an in lap)")
    p.add_argument("--outlier", type=float, default=3.0, help="a lap this many percent slower than the median is set aside (default 3)")
    p.add_argument("--window", type=float, default=0.5, help="how close to the best counts as on the pace, s (default 0.5)")
    p.add_argument("--fuel-gain", type=float, default=0.0, help="seconds a lap the car gains as fuel burns off, to separate that from tyre wear")
    p.add_argument("--sectors", action="append", help="one lap's sector times, quoted: \"31.2 40.1 31.0\" (repeat for each lap)")

    p = command(sub, "racing", "stint", cmd_stint,
                "pit strategy: how many stops, stint lengths, fuel to add, and what fuel saving would buy",
                ["stint --laps 40 --lap 1:42.5 --fuel-lap 3.2 --tank 100 --pit 28 --tyre-life 16 --deg 0.06",
                 "stint --minutes 60 --lap 1:42.5 --fuel-lap 3.2 --tank 100 --pit 28 --refuel-rate 2.5 --save 1:43.4,2.7"])
    p.add_argument("--laps", type=int, help="race length in laps")
    p.add_argument("--minutes", type=float, help="race length in minutes (timed race)")
    p.add_argument("--lap", required=True, help="representative lap on fresh tyres: 1:42.5")
    p.add_argument("--fuel-lap", type=float, required=True, help="fuel used per lap (litres, percent, any unit)")
    p.add_argument("--tank", type=float, default=100.0, help="tank size in the same unit (default 100)")
    p.add_argument("--pit", type=float, default=25.0, help="seconds lost per stop before fuel and tyres (default 25)")
    p.add_argument("--tyre-life", type=int, help="laps a set of tyres lasts")
    p.add_argument("--deg", type=float, default=0.0, help="seconds lost per lap for each lap of tyre age")
    p.add_argument("--tyre-change", type=float, default=0.0, help="extra seconds per stop for tyres")
    p.add_argument("--refuel-rate", type=float, help="fuel units per second at the pump")
    p.add_argument("--margin", type=float, default=0.3, help="laps of fuel kept in hand each stint (default 0.3)")
    p.add_argument("--max-stops", type=int, default=5)
    p.add_argument("--save", action="append", help="a fuel-saving mode to compare: LAPTIME,FUEL_PER_LAP (repeatable)")
    p.add_argument("--show", type=int, default=6, help="rows to list (default 6)")

    p = command(sub, "racing", "pace", cmd_pace, "lap-time arithmetic: average speed, race time, chasing a gap, fuel per lap",
                ["pace --lap 1:42.5 --km 5.807 --laps 30", "pace --gap 12.5 --laps-left 10 --lap 1:42.5",
                 "pace --used 38.4 --over 12 --tank 100", "pace --lap 1:42.5 --minutes 60"])
    p.add_argument("--lap", help="lap time: 1:42.5")
    p.add_argument("--km", type=float, help="lap length, km")
    p.add_argument("--laps", type=int)
    p.add_argument("--minutes", type=float, help="timed race length")
    p.add_argument("--gap", type=float, help="seconds to the car ahead")
    p.add_argument("--laps-left", type=int)
    p.add_argument("--delta", type=float, help="seconds per lap gained or lost")
    p.add_argument("--target", help="target race time: 1:08:20")
    p.add_argument("--used", type=float, help="fuel used")
    p.add_argument("--over", type=int, help="laps that fuel was used over")
    p.add_argument("--tank", type=float)
