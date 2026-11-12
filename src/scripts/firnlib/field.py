"""FIRN-01 in the field: coming when called, catching a vehicle, the grapple, an escort on foot, deep water.

Lore sums for simulations and stories. Every figure is the maker's or the sheet's (lore.json); where she has
not ruled, the line says no figure.
"""
import math

from . import chrono
from .core import command, die, fmt_hm, load_data, more, num, rec, trim

G = 9.80665


def _lore():
    return load_data("lore")


def _clock(seconds):
    """'2m30s' for a short time, '1h05m' for a long one."""
    if seconds >= 3600:
        return fmt_hm(seconds / 3600.0)
    if seconds >= 60:
        return "%dm%02ds" % (int(seconds // 60), int(round(seconds % 60)) % 60)
    return "%s s" % trim(seconds, 1)


def _range(lore, km, left=None):
    full = float(lore["chassis"]["range_km"])
    have = full if left is None else left
    after = have - km
    rec("RANGE", "%s km of %s km%s -> %s km left%s" % (
        num(km, 1) if km < 100 else num(km), num(have), " [lore]" if left is None else " [as given]",
        num(after, 1) if after < 100 else num(after), "" if after >= 0 else "  OUT OF RANGE"))


# ---- summon

def cmd_summon(a):
    """He comes to the driver from where he was parked: how long, what it costs, and how he drives with nobody aboard."""
    from . import geo
    lore = _lore()
    spot = geo.parse_point(a.spot)
    if spot[3] is None:
        spot = ("the parked spot", spot[1], spot[2], None)
    to = geo.parse_point(a.to)
    top = float(lore["chassis"]["top_kmh"])
    if a.speed is not None and not a.urgent:
        die("--speed belongs to --urgent: without it he keeps the posted limits")
    if a.urgent and a.speed is None:
        die("--urgent needs --speed, the average he may hold: how far above the limits is the driver's word, not his")
    if a.speed is not None and not 0 < a.speed <= top:
        die("--speed is above zero and no more than his governor, %s km/h" % trim(top, 0))
    plan = geo.crossing.plan(spot, to, a.mode)
    straight, km, hours, tag, _ = geo.ground_leg(spot, to, a.mode)
    if plan:
        rec("NO ROAD", "%s. He does not fly, and whether he boards a ferry with nobody aboard has no ruling: he cannot come to you. "
                       "Go to him: park --find" % plan["why"])
        return
    rec("SUMMON", "%s -> %s: %s km straight, %s%s km by road%s" % (
        spot[0], to[0], trim(straight, 1), "~" if tag == "estimate" else "", num(km, 1) if km < 100 else num(km),
        " [estimate: straight line x %s]" % trim(geo.MODES[a.mode][1], 2) if tag == "estimate" else " [%s]" % tag))
    if a.urgent:
        hours = km / a.speed
        rec("ETA", "%s at %s km/h average: URGENT, above the posted limits on the driver's word, and he says so [lore]" % (
            _clock(hours * 3600), trim(a.speed, 0)))
    else:
        rec("ETA", "%s at %s km/h average [%s mode]: within the posted limits [lore]" % (
            _clock(hours * 3600), trim(geo.MODES[a.mode][0], 0), a.mode))
    tz = geo.place_tz(to)
    rec("THERE", "about %s, if he leaves now" % chrono.fmt_dt(chrono.add(chrono.now_in(tz), hours * 3600)))
    _range(lore, km, a.range_left)
    rec("RUNNING", "silent, as asked: bar dark, motors hushed, radar and lidar off, so he sees less on the way [lore]" if a.silent
        else "lights on, not silent: an empty car that behaves [lore]")
    rec("RULE", lore["unmanned"]["note"])
    rec("NOTE", "lore: on a real road he moves nothing, and says so (SKILL.md 8.6). For the real car: park --find")


# ---- intercept

def cmd_intercept(a):
    """Whether he catches a vehicle ahead, or reaches a junction before it: when, where, and at what cost in range."""
    lore = _lore()
    top = float(lore["chassis"]["top_kmh"])
    if not 0 < a.speed <= top:
        die("--speed is above zero and no more than his governor, %s km/h [maker]" % trim(top, 0))
    if a.target <= 0:
        die("--target is the other vehicle's speed, km/h, above zero")
    if (a.gap is None) == (a.junction is None):
        die("give --gap (it is ahead on your road) or --junction MINE THEIRS (two roads that meet), one of them")
    if a.junction is not None:
        mine, theirs = a.junction
        if mine < 0 or theirs < 0:
            die("--junction takes two distances in km: yours to the junction, then its")
        t_me, t_it = mine / a.speed * 3600.0, theirs / a.target * 3600.0
        need = mine / theirs * a.target if theirs > 0 else float("inf")
        if t_me <= t_it:
            rec("CUT OFF", "he is at the junction %s before it: there in %s, it in %s [derived: steady speeds]" % (
                _clock(t_it - t_me), _clock(t_me), _clock(t_it)))
        else:
            rec("TOO LATE", "it is through the junction %s before him: there in %s, he in %s [derived: steady speeds]" % (
                _clock(t_me - t_it), _clock(t_it), _clock(t_me)))
            rec("NEEDS", "%s km/h to be level with it there%s" % (
                trim(need, 0), "" if need <= top else ": more than his governor allows, so not by this road"))
        _range(lore, mine, a.range_left)
    else:
        if a.gap <= 0:
            die("--gap is how far ahead it is, km, above zero")
        closing = a.speed - a.target
        if closing <= 0:
            rec("NEVER", "at %s km/h he gains nothing on something doing %s: the gap stays %s km or grows" % (
                trim(a.speed, 0), trim(a.target, 0), trim(a.gap, 2)))
            rec("NEEDS", "more than %s km/h, or another road: intercept --junction" % trim(a.target, 0))
            return
        hours = a.gap / closing
        mine, theirs = a.speed * hours, a.target * hours
        rec("CATCH", "in %s: he covers %s km and it covers %s km, closing at %s km/h [derived: steady speeds]" % (
            _clock(hours * 3600), trim(mine, 1), trim(theirs, 1), trim(closing, 0)))
        if a.before is not None:
            if a.before <= 0:
                die("--before is the road it has left before it is out of reach, km, above zero")
            if theirs <= a.before:
                rec("IN TIME", "%s km before it gets there" % trim(a.before - theirs, 1))
            else:
                need = a.target * (1.0 + a.gap / a.before)
                rec("TOO LATE", "it has %s km left and he needs %s km of its road to close the gap" % (trim(a.before, 1), trim(theirs, 1)))
                rec("NEEDS", "%s km/h to catch it on the line%s" % (
                    trim(need, 0), "" if need <= top else ": more than his governor allows, so not by chasing"))
        _range(lore, mine, a.range_left)
    rec("RULE", "catching is not stopping. The least force that works, and the machine before the person in it (SKILL.md section 4)")


# ---- grapple

def cmd_grapple(a):
    """What the grapple must pull against what it can: a load on a slope, held by the ground or hanging free."""
    lore = _lore()
    cfg = lore["grapple"]
    limit, line = float(cfg["pull_kg"]), float(cfg["line_m"])
    if a.self and a.mass is not None:
        die("--self is his own mass: leave out --mass (use --load for what is aboard)")
    if not a.self and a.mass is None:
        die("give --mass, the kg to move, or --self to pull himself out")
    mass = float(lore["chassis"]["kerb_kg"]) + a.load if a.self else a.mass
    if mass <= 0 or a.load < 0:
        die("mass and load cannot be negative, and the mass is above zero")
    if not 0 <= a.slope <= 90:
        die("--slope is 0 (level) to 90 (straight up), degrees")
    if a.resist < 0:
        die("--resist cannot be negative")
    share = math.sin(math.radians(a.slope)) + a.resist * math.cos(math.radians(a.slope))
    need = mass * share
    rec("LOAD", "%s kg%s on %s deg%s -> a pull of %s kg [derived]" % (
        num(mass), " (his kerb mass%s)" % (" + %s kg aboard" % num(a.load) if a.load else "") if a.self else "", trim(a.slope, 1),
        ", the ground holding it with %s of its weight" % trim(a.resist, 2) if a.resist else ", rolling free", num(need)))
    if need <= limit + 1e-9:
        rec("HOLDS", "%s kg of the %s kg he pulls [lore]: %s%% of it" % (num(need), num(limit), trim(need / limit * 100.0, 0)))
    else:
        rec("TOO MUCH", "%s kg against the %s kg he pulls [lore]. On this slope and ground the most he moves is %s kg" % (
            num(need), num(limit), num(limit / share) if share > 0 else "anything"))
    if a.distance is not None:
        if a.distance < 0:
            die("--distance cannot be negative")
        if a.distance <= line:
            rec("REACH", "%s m of the %s m of line [lore]" % (trim(a.distance, 1), trim(line, 0)))
        else:
            rec("REACH", "OUT OF REACH: %s m, and the line is %s m [lore]. Close in by %s m" % (
                trim(a.distance, 1), trim(line, 0), trim(a.distance - line, 1)))
    if a.pull_m is not None:
        if a.pull_m <= 0:
            die("--pull-m is how far the load is dragged, m, above zero")
        kwh = min(need, limit) * G * a.pull_m / 3.6e6
        per_km = float(lore["chassis"]["bank_kwh"]) / float(lore["chassis"]["range_km"])
        rec("COST", "%s km of range for %s m of pull [derived: the work of the pull against the bank, as a climb would cost]" % (
            trim(kwh / per_km, 2), trim(a.pull_m, 1)))
    else:
        more("add --pull-m, how far the load is dragged, for what it costs in range")
    rec("RULES", "it cannot hold a powered armour [lore]. Whether he keeps his own footing while he pulls is the brief's to say: "
                 "his grip has no figure")


# ---- escort

def cmd_escort(a):
    """Walking someone to cover behind the hull: how long, what a Veil over them costs, and whether the emitters last."""
    from . import geo
    lore = _lore()
    lat, ch = lore["lattice"], lore["chassis"]
    if (a.minutes is None) == (a.distance is None):
        die("give --distance (metres to cover, at walking pace) or --minutes, one of them")
    if a.minutes is not None:
        if a.minutes <= 0:
            die("--minutes is above zero")
        secs, how = a.minutes * 60.0, "as given"
    else:
        pace = a.pace if a.pace is not None else geo.MODES["walk"][0]
        if a.distance <= 0 or pace <= 0:
            die("--distance and --pace are above zero")
        secs = a.distance / (pace / 3.6)
        how = "%s m at %s km/h%s" % (trim(a.distance, 0), trim(pace, 1), "" if a.pace is not None else ", route's walking average")
    rec("ESCORT", "%s with the hull between them and the threat [%s]" % (_clock(secs), how))
    rec("SHELTER", "side-on he is %s m long and %s m high; nose-on, %s m wide [sheet]" % (
        trim(ch["length_m"], 2), trim(ch["height_m"], 2), trim(ch["width_m"], 2)))
    if a.veil == "off":
        rec("VEIL", "down: the Scales and the Rime take what comes, and it costs no range [lore]")
        rec("LEDGER", "book the hits in a sim with: lattice --state ... hit=%s:heavy" % a.face)
    else:
        frac = 1.0 if a.veil == "full" else float(lat["veil_partial_fraction"])
        rate = float(lat["veil_km_per_min"]) * frac
        limit = float(lat["veil_overheat_s"])
        room = max(0.0, limit - a.heat)
        holds = room / frac
        held = min(secs, holds)
        what = "full" if a.veil == "full" else "over the %s face" % a.face
        rec("VEIL", "%s, %s km a minute: %s km for the %s it is up [lore]" % (what, trim(rate, 1), trim(rate * held / 60.0, 1), _clock(held)))
        if secs <= holds + 1e-9:
            rec("EMITTERS", "%s of heat by the end, of %d s: they hold [lore]" % (_clock(a.heat + secs * frac), limit))
        else:
            rec("EMITTERS", "they trip after %s: the last %s is on the armour alone, and the Veil stays down until they are cool [lore]" % (
                _clock(holds), _clock(secs - holds)))
        _range(lore, rate * held / 60.0, a.range_left)
        veil = "full" if a.veil == "full" else "partial:%s" % a.face
        rec("LEDGER", "book it in a sim with: lattice --state ... veil=%s wait=%s veil=off" % (veil, trim(held, 0)))
    rec("RULE", "say what a Veil costs before you raise it, unless there is no time. If moving would expose bystanders, "
                "stay and take it on the armour (SKILL.md section 4)")


# ---- ford

def cmd_ford(a):
    """Deep water: whether he wades it, what goes blind while he does, and what it leaves behind."""
    lore = _lore()
    limit = float(lore["ford"]["depth_m"])
    high = max(lore["chassis"]["clearance_mm"]) / 1000.0
    if a.depth <= 0:
        die("--depth is the water's depth, m, above zero")
    if a.depth > limit + 1e-9:
        rec("REFUSED", "%s m is deeper than the %s m he wades [lore], and amphibious gear is not fitted [sheet]" % (
            trim(a.depth, 2), trim(limit, 2)))
        rec("OFFER", "another crossing; or, for a narrow channel, a jump: jump --gap WIDTH")
        return
    if a.depth <= high + 1e-9:
        rec("SHALLOW", "%s m stays under his floor at full ride height (%s mm): he drives through, and nothing on file is spent" % (
            trim(a.depth, 2), trim(high * 1000, 0)))
    else:
        rec("WADES", "%s m of the %s m he wades [lore]: %s" % (
            trim(a.depth, 2), trim(limit, 2), "bonnet-deep, crawling" if a.depth > 0.9 else "crawling"))
        rec("CELL", "the water stands %s m above his floor at full ride height (%s mm): the cell is sealed, the cabin stays dry [lore]" % (
            trim(a.depth - high, 2), trim(high * 1000, 0)))
        rec("SENSES", "cameras and lidar low on the body are out while he is in it [lore]: radar, the thermal imager up high and the "
                      "microphones carry the watch")
        rec("AFTER", "the Rime takes longer to re-cool afterwards [lore]: how much longer has no figure, so the driver rules")
    if a.width is not None:
        if a.width <= 0:
            die("--width is above zero")
        if a.kmh is not None:
            if a.kmh <= 0:
                die("--kmh is above zero")
            rec("ACROSS", "%s m in %s at %s km/h [as given]" % (trim(a.width, 0), _clock(a.width / (a.kmh / 3.6)), trim(a.kmh, 1)))
        else:
            rec("ACROSS", "%s m: give --kmh for the time. His crawling pace in water has no figure" % trim(a.width, 0))
    rec("RULE", "he reads the depth before he commits, and says it. Moving water is not still water: a current is the brief's to give")


def register(sub):
    p = command(sub, "firn", "summon", cmd_summon,
                "FIRN-01 comes to you from where he was parked: how long, the range it costs, how he drives with nobody aboard",
                ["summon --spot 50.2599,19.0216 --to katowice", "summon --spot 50.2599,19.0216 --to gliwice --mode car --silent",
                 "summon --spot 50.2599,19.0216 --to gliwice --urgent --speed 140"])
    p.add_argument("--spot", required=True, help="where he stands: the LAT,LON from the park stamp, or a place")
    p.add_argument("--to", required=True, help="where you are")
    p.add_argument("--mode", default="city", choices=("city", "car", "motorway"), help="the roads between, as for 'route' (default city)")
    p.add_argument("--urgent", action="store_true", help="the driver calls it urgent: he may go above the posted limits, and says so")
    p.add_argument("--speed", type=float, help="with --urgent: the average he may hold, km/h, up to his governor")
    p.add_argument("--silent", action="store_true", help="he comes in silent running, because you asked")
    p.add_argument("--range-left", type=float, help="range he has now, km (default: a full bank)")

    p = command(sub, "firn", "intercept", cmd_intercept,
                "can FIRN-01 catch a vehicle ahead, or reach a junction before it: when, where, the speed it takes, the range it costs",
                ["intercept --gap 1.5 --target 110 --speed 180", "intercept --gap 4 --target 130 --speed 200 --before 12",
                 "intercept --junction 12 9 --target 90 --speed 140"])
    p.add_argument("--gap", type=float, help="it is this far ahead on the same road, km")
    p.add_argument("--junction", type=float, nargs=2, metavar=("MINE", "THEIRS"), help="km to a junction: his, then the other vehicle's")
    p.add_argument("--target", type=float, required=True, help="the other vehicle's speed, km/h")
    p.add_argument("--speed", type=float, required=True, help="the speed he holds, km/h")
    p.add_argument("--before", type=float, help="with --gap: km of road it has left before it is out of reach")
    p.add_argument("--range-left", type=float, help="range he has now, km (default: a full bank)")

    p = command(sub, "firn", "grapple", cmd_grapple,
                "FIRN-01's grapple: the pull a load needs on a slope against the 3 t he pulls, the reach of the line, the range it costs",
                ["grapple --mass 1800 --slope 20 --resist 0.3 --distance 22 --pull-m 15", "grapple --self --load 260 --slope 35 --resist 0.2",
                 "grapple --mass 2500 --slope 90"])
    p.add_argument("--mass", type=float, help="what is to be moved, kg")
    p.add_argument("--self", action="store_true", help="he pulls himself: his kerb mass, plus --load")
    p.add_argument("--load", type=float, default=0.0, help="with --self: people and cargo aboard, kg")
    p.add_argument("--slope", type=float, default=0.0, help="the slope it is pulled up, degrees; 90 is a straight lift (default 0)")
    p.add_argument("--resist", type=float, default=0.0, help="how hard the ground holds it, as a share of its weight: the brief's figure "
                                                               "(default 0: rolling free)")
    p.add_argument("--distance", type=float, help="how far away it is, m: checked against the line")
    p.add_argument("--pull-m", type=float, help="how far it is dragged, m: gives the cost in range")

    p = command(sub, "firn", "escort", cmd_escort,
                "FIRN-01 walks someone to cover behind his hull: how long, what a Veil over them costs, whether the emitters last",
                ["escort --distance 200", "escort --minutes 8 --veil full", "escort --distance 400 --pace 3 --face right --heat 60",
                 "escort --minutes 4 --veil off"])
    p.add_argument("--distance", type=float, help="metres to cover, at walking pace")
    p.add_argument("--pace", type=float, help="their pace, km/h (default: route's walking average)")
    p.add_argument("--minutes", type=float, help="or the time it takes, minutes")
    p.add_argument("--veil", default="face", choices=("face", "full", "off"), help="one face (default), all of him, or none")
    p.add_argument("--face", default="left", choices=("front", "rear", "left", "right"), help="the face turned to the threat (default left)")
    p.add_argument("--heat", type=float, default=0.0, help="emitter heat already on the ledger, s")
    p.add_argument("--range-left", type=float, help="range he has now, km (default: a full bank)")

    p = command(sub, "firn", "ford", cmd_ford,
                "deep water for FIRN-01: whether he wades it (to 1.5 m), what goes blind while he does, and what it leaves behind",
                ["ford --depth 0.8", "ford --depth 1.4 --width 60 --kmh 4", "ford --depth 2.2"])
    p.add_argument("--depth", type=float, required=True, help="the depth of the water, m")
    p.add_argument("--width", type=float, help="how far across, m")
    p.add_argument("--kmh", type=float, help="the pace he crawls at, km/h: the brief's figure")
