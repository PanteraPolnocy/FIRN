"""Arms for the simulation table: bows and thrown weapons, melee of every kind, blasts, beams, and plain guns.

Game mechanics only, which is FIRN's own line on weapons: dice, range bands, kinds of damage against classes of
armour as dated house rules, an area template for a blast, and schoolbook kinematics for an arc or a lead.
Nothing here sizes, makes or places a real explosive, and nothing says how to defeat real armour.

strike  one attack, resolved by the house rules or by the numbers a ruleset gives
blast   one explosion, and what it does at each distance
arc     the flight of a thrown or loosed thing: time, height, the angle that reaches a range
lead    how far ahead of a moving target to aim
"""
import math

from . import dice
from .core import G, command, die, fold, load_data, more, num, rec, table, trim

BANDS = ("short", "medium", "long")


def rules():
    return load_data("arms")


def weapon(name):
    data = rules()["weapons"]
    key = fold(name)
    if key in data:
        return key, data[key]
    import difflib
    near = difflib.get_close_matches(key, list(data), n=3, cutoff=0.6)
    die("no weapon called '%s' in the house rules.%s 'strike --list' shows them; or give --dice and --kind for one of your own" % (
        name, " Did you mean: %s?" % ", ".join(near) if near else ""))


def through(dist, factor):
    """A damage distribution after armour, air and intent: each value times the factor, rounded half up."""
    out = {}
    for v, p in dist.items():
        d = max(0, int(math.floor(v * factor + 0.5)))
        out[d] = out.get(d, 0.0) + p
    return out


def hits_to_down(dist, hp):
    """Expected number of hits to deal hp damage, or None if nothing ever gets through."""
    p0 = dist.get(0, 0.0)
    if p0 >= 1.0 - 1e-12:
        return None
    need = [0.0] * (hp + 1)
    for h in range(1, hp + 1):
        acc = 1.0
        for d, p in dist.items():
            if d > 0:
                acc += p * need[max(0, h - d)]
        need[h] = acc / (1.0 - p0)
    return need[hp]


def _armour(name):
    table_ = rules()["armour"]
    key = fold(name)
    if key not in table_:
        die("armour is one of: %s" % ", ".join(table_))
    return key, table_[key]


def _span(dist):
    st = dice.stats(dist)
    return "%d to %d, average %s" % (st["min"], st["max"], trim(st["mean"], 1))


def cmd_strike(a):
    data = rules()
    if a.list:
        rows = []
        for key, w in data["weapons"].items():
            where = "reach %d m" % w["reach"] if "reach" in w else ("bands %s m" % "/".join(str(b) for b in w["bands"]) if "bands" in w
                                                                    else "radius %s m" % "/".join(str(b) for b in w["radius"]))
            extra = [x for x in ("to subdue" if w.get("subdue") else "", "reload %d" % w["reload"] if w.get("reload") else "",
                                 "heat %d of %d" % (w["heat"], w["capacity"]) if w.get("heat") else "") if x]
            rows.append((key, w["class"], w["dice"], w["kind"], where, ", ".join(extra)))
        rec("WEAPONS", "%d in the %s" % (len(rows), data["label"]))
        table(rows, header=("weapon", "class", "dice", "kind", "range", "notes"), indent=2)
        rec("ARMOUR", ", ".join(data["armour"]))
        rec("KINDS", "; ".join("%s (%s)" % (k, v) for k, v in data["kinds"].items()))
        rec("NOTE", "game mechanics for sims, yours to edit in scripts/data/arms.json; a blast goes through 'blast', not 'strike'")
        return
    if a.weapon:
        name, w = weapon(a.weapon)
        if w["class"] == "blast":
            die("%s is a blast: use 'blast %s --at DISTANCE ...'" % (name, name))
    elif a.dice and a.kind:
        name, w = "your own weapon", {"class": "own", "dice": a.dice, "kind": a.kind}
        if a.bands:
            w["bands"] = a.bands
        else:
            w["reach"] = 1
    else:
        die("name a weapon ('strike --list'), or give --dice and --kind for one of your own")
    if w["kind"] not in data["kinds"]:
        die("a kind of damage is one of: %s" % ", ".join(data["kinds"]))
    dmg_terms = dice.parse(a.dice or w["dice"])
    att = data["attack"]
    beam = w["kind"] == "beam"
    line = "%s: %s %s" % (name, a.dice or w["dice"], w["kind"])
    if "reach" in w:
        line += ", reach %d m" % w["reach"]
    else:
        line += ", bands %s m" % "/".join(trim(b, 0) for b in w["bands"])
    if w.get("reload"):
        line += ", %d round%s to reload" % (w["reload"], "" if w["reload"] == 1 else "s")
    rec("WEAPON", "%s [%s]" % (line, data["label"] if a.weapon else "as given"))
    # range band
    if "reach" in w:
        dist_m = a.range if a.range is not None else float(w["reach"])
        if dist_m > w["reach"] + 1e-9:
            rec("RANGE", "%s m: OUT OF REACH. A %s reaches %d m: close the distance first" % (trim(dist_m, 1), name, w["reach"]))
            return
        band, band_mod = "in reach", 0
    else:
        bands = w["bands"]
        if len(bands) != 3 or not bands[0] < bands[1] < bands[2]:
            die("range bands are three rising distances in metres: short medium long")
        dist_m = a.range if a.range is not None else float(bands[0])
        if dist_m > bands[2] + 1e-9:
            rec("RANGE", "%s m: OUT OF RANGE. The long band of a %s ends at %s m" % (trim(dist_m, 1), name, trim(bands[2], 0)))
            return
        band = BANDS[0] if dist_m <= bands[0] else BANDS[1] if dist_m <= bands[1] else BANDS[2]
        band_mod = (att["beam_band"] if beam else att["band"])[band]
    if a.cover not in att["cover"]:
        die("cover is one of: %s" % ", ".join(att["cover"]))
    if a.target is not None:
        target = a.target
        rec("RANGE", "%s m, %s; target number %d [as given]" % (trim(dist_m, 1), band if band == "in reach" else band + " band", target))
    else:
        target = att["base"] + band_mod + att["cover"][a.cover] + a.mod
        rec("RANGE", "%s m, %s%s; target number %d = %d base %+d range %+d cover%s" % (
            trim(dist_m, 1), band if band == "in reach" else band + " band", " (a beam does not drop: no penalty before the long band)"
            if beam and band == "medium" else "", target, att["base"], band_mod, att["cover"][a.cover],
            " %+d as given" % a.mod if a.mod else ""))
    expr = att["dice"] + ("%+d" % a.skill if a.skill else "")
    p_hit = dice.at_least(dice.distribution(dice.parse(expr)), target)
    rec("TO HIT", "%s against %d: %s%s [derived]" % (expr, target, dice.pct(p_hit), dice.one_in(p_hit)))
    # damage
    arm_key, arm = _armour(a.armour)
    factor = a.factor if a.factor is not None else arm[w["kind"]]
    parts = ["x %s through %s" % (trim(factor, 2), arm["is"] if a.factor is None else "armour, as given")]
    if beam:
        if a.air not in data["air"] or a.air == "note":
            die("--air is one of: %s" % ", ".join(k for k in data["air"] if k != "note"))
        if data["air"][a.air] != 1.0:
            factor *= data["air"][a.air]
            parts.append("x %s through %s" % (trim(data["air"][a.air], 2), "thick smoke" if a.air == "thick" else a.air))
    subdue = bool(a.subdue or w.get("subdue"))
    if subdue and not w.get("subdue"):
        factor *= 0.5
        parts.append("x 0.5 to subdue")
    got = through(dice.distribution(dmg_terms), factor)
    mean = dice.stats(got)["mean"]
    rec("DAMAGE", "%s %s %s: %s a hit; %s a shot at this chance [derived]" % (
        a.dice or w["dice"], w["kind"], ", ".join(parts), _span(got), trim(mean * p_hit, 2)))
    if subdue:
        more(data["subdue"])
    if a.hp:
        need = hits_to_down(got, a.hp)
        if need is None:
            rec("TO DOWN", "%d hit points: never. Nothing gets through this armour: change the weapon, not the effort" % a.hp)
        elif p_hit <= 0:
            rec("TO DOWN", "%d hit points: %s hits on average, but this shot cannot land" % (a.hp, trim(need, 1)))
        else:
            rec("TO DOWN", "%d hit points: %s hits on average, so about %s attacks [derived]" % (a.hp, trim(need, 1), trim(need / p_hit, 1)))
    if w.get("heat"):
        shots = w["capacity"] // w["heat"]
        rec("HEAT", "%d a shot of %d: %d shot%s, then a round to cool" % (w["heat"], w["capacity"], shots, "" if shots == 1 else "s"))
    if a.roll:
        rng = dice.make_rng(a.seed)
        total, shown = dice.roll_once(dice.parse(expr), rng)
        if total >= target:
            raw, dshown = dice.roll_once(dmg_terms, rng)
            dealt = max(0, int(math.floor(raw * factor + 0.5)))
            rec("ROLL", "%s = %d against %d: HIT. Damage %s = %d, %d gets through" % (shown, total, target, dshown, raw, dealt))
            rec("BOOK IT", "board --state ... hit=%s:%d%s" % (a.at or "NAME", dealt, ":subdue" if subdue else ""))
        else:
            rec("ROLL", "%s = %d against %d: MISS" % (shown, total, target))
        rec("SEED", "%d (repeatable)" % a.seed if a.seed is not None else "none: system randomness, not repeatable")
    rec("RULES", "%s: game mechanics, not ballistics. A ruleset the driver names outranks them: pass its numbers "
                 "(--dice, --target, --factor)" % data["label"])


def cmd_blast(a):
    data = rules()
    if a.weapon:
        name, w = weapon(a.weapon)
        if w["class"] != "blast":
            die("%s is not a blast: use 'strike %s'" % (name, name))
    elif a.dice and a.radius:
        name, w = "your own charge", {"dice": a.dice, "radius": a.radius, "kind": "blast"}
    else:
        die("name a blast from the house rules ('strike --list'), or give --dice and --radius FULL HALF QUARTER")
    radius = a.radius or w["radius"]
    if len(radius) != 3 or not 0 < radius[0] <= radius[1] <= radius[2]:
        die("--radius is three rising distances in metres: full, half and quarter damage")
    terms = dice.parse(a.dice or w["dice"])
    base = dice.distribution(terms)
    n = len(a.at)

    def spread(values, default, what):
        values = values or [default]
        if len(values) == 1:
            return values * n
        if len(values) != n:
            die("%s: give one for all, or one for each of the %d distances" % (what, n))
        return values

    covers = spread(a.cover, "none", "--cover")
    armours = spread(a.armour, "none", "--armour")
    names = a.names or ["target %d" % (i + 1) for i in range(n)]
    if len(names) != n:
        die("--names: one for each of the %d distances" % n)
    subdue = bool(a.subdue or w.get("subdue"))
    rec("BLAST", "%s: %s, full to %s m, half to %s m, a quarter to %s m%s [%s]" % (
        name, a.dice or w["dice"], trim(radius[0], 1), trim(radius[1], 1), trim(radius[2], 1), "; stuns, does not wound" if subdue else "",
        data["label"] if a.weapon else "as given"))
    raw = None
    if a.roll:
        raw, shown = dice.roll_once(terms, dice.make_rng(a.seed))
        rec("ROLL", "%s = %d, one roll for the whole blast" % (shown, raw))
    events = []
    for name_i, d, cover, arm_name in zip(names, a.at, covers, armours):
        if d < 0:
            die("a distance cannot be negative")
        if cover not in data["blast_cover"]:
            die("cover is one of: %s" % ", ".join(data["blast_cover"]))
        _, arm = _armour(arm_name)
        band = "full" if d <= radius[0] else "half" if d <= radius[1] else "quarter" if d <= radius[2] else None
        if band is None:
            rec(name_i.upper()[:10], "%s m: outside the blast" % trim(d, 1))
            continue
        factor = data["blast_bands"][band] * data["blast_cover"][cover] * arm["blast"] * (0.5 if a.subdue and not w.get("subdue") else 1.0)
        got = through(base, factor)
        line = "%s m: %s damage%s%s -> x %s: %s" % (
            trim(d, 1), band, ", %s cover" % cover if cover != "none" else "", ", %s" % arm["is"] if arm_name != "none" else "",
            trim(factor, 3), _span(got))
        if raw is not None:
            dealt = max(0, int(math.floor(raw * factor + 0.5)))
            line += " | this blast: %d" % dealt
            if dealt:
                events.append("hit=%s:%d%s" % (fold(name_i), dealt, ":subdue" if subdue else ""))
        rec(name_i.upper()[:10], line + " [derived]")
    if raw is not None:
        rec("BOOK IT", "board --state ... %s" % (" ".join(events) if events else "(nobody was hurt)"))
        rec("SEED", "%d (repeatable)" % a.seed if a.seed is not None else "none: system randomness, not repeatable")
    rec("RULES", "%s: an area template for a game, not a model of a real explosion. Everyone in it is counted, whichever "
                 "side they are on" % data["label"])


def cmd_arc(a):
    speed = a.speed
    label = "as given"
    if a.weapon:
        name, w = weapon(a.weapon)
        if speed is None:
            if "speed" not in w:
                die("%s has no launch speed in the house rules: give --speed in m/s" % name)
            speed, label = float(w["speed"]), "%s, %s" % (name, rules()["label"])
    if speed is None or speed <= 0:
        die("arc needs a launch speed in m/s: --speed 55, or a weapon from 'strike --list'")
    if (a.range is None) == (a.angle is None):
        die("give --range to find the angle, or --angle to find the range")
    drop = a.height - a.target_height
    reach = speed / G * math.sqrt(max(0.0, speed * speed + 2 * G * drop))
    rec("LAUNCH", "%s m/s from %s m up, target at %s m [%s]" % (trim(speed, 1), trim(a.height, 2), trim(a.target_height, 2), label))

    def flight(theta):
        vy, vx = speed * math.sin(theta), speed * math.cos(theta)
        t = (vy + math.sqrt(max(0.0, vy * vy + 2 * G * drop))) / G
        peak = a.height + (vy * vy / (2 * G) if vy > 0 else 0.0)
        down = math.degrees(math.atan2(abs(vy - G * t), vx))
        return t, vx * t, peak, down

    if a.angle is not None:
        if not -89 <= a.angle <= 89:
            die("--angle is degrees above the horizontal, -89 to 89")
        vy = speed * math.sin(math.radians(a.angle))
        if vy * vy + 2 * G * drop < 0:
            rec("ANGLE", "%s deg up: it never climbs to %s m [derived]" % (trim(a.angle, 1), trim(a.target_height, 2)))
        else:
            t, dist_m, peak, down = flight(math.radians(a.angle))
            rec("ANGLE", "%s deg up: lands %s m away after %s s, peak %s m, coming down at %s deg [derived]" % (
                trim(a.angle, 1), trim(dist_m, 1), trim(t, 2), trim(peak, 1), trim(down, 0)))
    else:
        r = a.range
        if r <= 0:
            die("--range is a distance in metres, above zero")
        disc = speed ** 4 - G * (G * r * r - 2 * drop * speed * speed)
        if disc < 0:
            rec("RANGE", "%s m is OUT OF REACH: at this speed the furthest is %s m [derived]" % (trim(r, 1), trim(reach, 1)))
        else:
            for word, sign in (("FLAT", -1), ("LOBBED", 1)):
                theta = math.atan2(speed * speed + sign * math.sqrt(disc), G * r)
                t, dist_m, peak, down = flight(theta)
                rec(word, "%s deg up: %s s in the air, peak %s m, coming down at %s deg [derived]" % (
                    trim(math.degrees(theta), 1), trim(t, 2), trim(peak, 1), trim(down, 0)))
            more("the flat shot is the quick one; the lobbed one clears cover and arrives late")
    rec("FURTHEST", "%s m at this speed [derived]" % trim(reach, 1))
    rec("NOTE", "no air in this sum. Air slows anything light, an arrow or a thrown thing most of all, so real flights fall "
                "short and drop more: read these as the best case. For a moving target, pass the flight time to 'lead --tof'")


def cmd_lead(a):
    from .dynamics import parse_speed
    w = None
    if a.weapon:
        name, w = weapon(a.weapon)
    if a.beam or (w and w.get("kind") == "beam"):
        rec("LEAD", "none. A beam crosses %s m in about %s microseconds: aim at the target, not ahead of it [derived]" % (
            trim(a.range or 300.0, 0), trim((a.range or 300.0) / 299792458.0 * 1e6, 1)))
        more("what a beam needs is time on one spot: a target that keeps turning the struck face away spoils it")
        return
    shell, label = a.shell, "as given"
    if w:
        if shell is None and a.tof is None:
            if "speed" not in w:
                die("%s has no speed in the house rules: give --shell in m/s" % name)
            shell, label = float(w["speed"]), "%s, %s" % (name, rules()["label"])
    if a.speed is None:
        die("lead needs the target's speed: --speed 40 (km/h; 25mph and 11m/s are read too)")
    v = parse_speed(a.speed) / 3.6
    if v < 0:
        die("the target's speed cannot be negative; use --angle for its direction")
    if a.tof is not None:
        if a.tof <= 0:
            die("--tof is the flight time in seconds, above zero")
        t = a.tof
        angle = None
        rec("FLIGHT", "%s s [as given]" % trim(t, 2))
    else:
        if shell is None or shell <= 0 or a.range is None or a.range <= 0:
            die("lead needs the projectile's speed and the range: --shell 850 --range 300 (or --tof SECONDS, or a weapon)")
        if shell <= v:
            die("the target is as fast as the shot: it cannot be caught from here")
        phi = math.radians(a.angle)
        t = a.range * (v * math.cos(phi) + math.sqrt(shell * shell - (v * math.sin(phi)) ** 2)) / (shell * shell - v * v)
        angle = math.degrees(math.asin(min(1.0, v * math.sin(phi) / shell)))
        rec("FLIGHT", "%s s to cover the distance at %s m/s [%s; speed taken as constant]" % (trim(t, 2), num(shell), label))
    lead = v * t
    line = "%s m ahead of where the target is now" % trim(lead, 1)
    if a.length:
        line += ", %s of its own lengths" % trim(lead / a.length, 1)
    if angle is not None:
        line += "; aim %s deg off it" % trim(angle, 1)
    rec("LEAD", line + " [derived]")
    rec("TARGET", "%s km/h, %s" % (trim(v * 3.6, 0), "crossing square on" if abs(a.angle - 90) < 1e-9 else
                                   "straight away" if a.angle == 0 else "straight towards" if a.angle == 180 else
                                   "%s deg off the line of fire" % trim(a.angle, 0)))
    rec("NOTE", "steady speed and course assumed. A real shot slows on the way, so a little more lead than this; a target that "
                "turns or brakes after the shot is missed, which is the point of weaving")


def register(sub):
    p = command(sub, "combat", "strike", cmd_strike,
                "one attack in a sim: bow, blade, club, gun or beam against armour, with the odds, the damage and an honest roll",
                ["strike --list", "strike longbow --range 120 --armour mail --skill 2 --hp 12",
                 "strike sword --armour plate --skill 1 --roll --seed 7 --at raider",
                 "strike laser_rifle --range 400 --air smoke --armour mirrored --hp 20",
                 "strike stun_baton --armour padded --hp 10", "strike --dice 2d10 --kind cut --armour plate --target 8"])
    p.add_argument("weapon", nargs="?", help="a weapon from the house rules (strike --list)")
    p.add_argument("--list", action="store_true", help="the weapons, armour classes and kinds of damage in the house rules")
    p.add_argument("--range", type=float, help="distance to the target, m (default: in reach, or the short band)")
    p.add_argument("--cover", default="none", help="the target's cover: none, light, half, full")
    p.add_argument("--armour", default="none", help="the target's armour class (strike --list)")
    p.add_argument("--skill", type=int, default=0, help="added to the attack roll")
    p.add_argument("--mod", type=int, default=0, help="added to the target number, for anything else the scene calls for")
    p.add_argument("--hp", type=int, help="the target's hit points, for how many hits it takes")
    p.add_argument("--air", default="clear", help="for a beam: clear, rain, fog, smoke, dust, thick")
    p.add_argument("--subdue", action="store_true", help="strike to stop, not to kill: half damage, and zero means subdued")
    p.add_argument("--roll", action="store_true", help="roll it")
    p.add_argument("--seed", type=int, help="fixed seed, to repeat a roll")
    p.add_argument("--at", help="the unit's name on the board, for the line to book")
    p.add_argument("--dice", help="damage dice, to override or for a weapon of your own")
    p.add_argument("--kind", help="kind of damage for a weapon of your own: shot, pierce, cut, crush, beam")
    p.add_argument("--bands", type=float, nargs=3, metavar=("SHORT", "MEDIUM", "LONG"), help="range bands in metres for a weapon of your own")
    p.add_argument("--target", type=int, help="the target number, straight from another ruleset")
    p.add_argument("--factor", type=float, help="the share of damage the armour lets through, straight from another ruleset")

    p = command(sub, "combat", "blast", cmd_blast,
                "one explosion in a sim: who is inside it, at what distance, behind what, and what each takes",
                ["blast grenade --at 2 5 11", "blast blast_charge --at 1.5 4 --cover none half --armour vest none --names anna raider",
                 "blast flashbang --at 2 5 --roll --seed 3 --names raider guard", "blast --dice 5d6 --radius 4 8 16 --at 6 --armour armoured"])
    p.add_argument("weapon", nargs="?", help="a blast from the house rules: flashbang, grenade, mine, blast_charge, heavy_charge")
    p.add_argument("--at", type=float, nargs="+", required=True, help="distance of each target from the blast, m")
    p.add_argument("--cover", nargs="+", help="cover of each target (or one for all): none, light, half, full")
    p.add_argument("--armour", nargs="+", help="armour class of each target (or one for all)")
    p.add_argument("--names", nargs="+", help="a name for each target, as on the board")
    p.add_argument("--dice", help="damage dice, to override or for a charge of your own")
    p.add_argument("--radius", type=float, nargs=3, metavar=("FULL", "HALF", "QUARTER"), help="the three radii in metres")
    p.add_argument("--subdue", action="store_true", help="it stuns rather than wounds")
    p.add_argument("--roll", action="store_true", help="roll it, once for the whole blast")
    p.add_argument("--seed", type=int, help="fixed seed, to repeat a roll")

    p = command(sub, "combat", "arc", cmd_arc, "the flight of an arrow, a bolt or a thrown thing: time in the air, peak, the angle for a range",
                ["arc longbow --range 120", "arc --speed 25 --angle 30", "arc javelin --range 30 --height 1.8 --target-height 1"])
    p.add_argument("weapon", nargs="?", help="a weapon from the house rules, for its launch speed")
    p.add_argument("--speed", type=float, help="launch speed, m/s")
    p.add_argument("--range", type=float, help="distance to reach, m")
    p.add_argument("--angle", type=float, help="launch angle above the horizontal, degrees")
    p.add_argument("--height", type=float, default=1.5, help="height it leaves from, m (default 1.5)")
    p.add_argument("--target-height", type=float, default=0.0, help="height it lands at, m (default 0, the ground)")

    p = command(sub, "combat", "lead", cmd_lead, "how far ahead of a moving target to aim: flight time, lead in metres and in target lengths",
                ["lead --speed 40 --range 300 --shell 850 --length 6.5", "lead longbow --speed 20 --range 90 --angle 60",
                 "lead --speed 30 --tof 2.4 --length 4.5", "lead --beam --range 800"])
    p.add_argument("weapon", nargs="?", help="a weapon from the house rules, for its speed")
    p.add_argument("--speed", help="the target's speed: km/h, or 25mph, 11m/s")
    p.add_argument("--range", type=float, help="distance to the target now, m")
    p.add_argument("--shell", type=float, help="the projectile's speed, m/s")
    p.add_argument("--angle", type=float, default=90.0, help="the target's course off the line of fire: 90 crossing (default), 0 away, 180 towards")
    p.add_argument("--length", type=float, help="the target's length, m, to count the lead in lengths")
    p.add_argument("--tof", type=float, help="flight time in seconds, instead of a speed and a range (from 'arc')")
    p.add_argument("--beam", action="store_true", help="a laser or other beam")
