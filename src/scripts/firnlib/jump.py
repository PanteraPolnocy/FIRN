"""The Squall: what a jump takes. Plain projectile physics for the flight, lore for the burst that lifts him.

The maker's rulings (SKILL.md section 2): the wheels alone do not push him upwards, a burst of air does; it costs
power, more for more mass and more distance; the suspension is built for the landing; and there is no limit on g short
of what would injure, knock out or kill someone aboard, where the driver is warned first if there is time for an answer.
The figures for the burst are hers as well (lore.json).
"""
import math

from .core import G, command, die, load_data, more, num, rec, trim
from .dynamics import SURFACE_NAMES, SURFACES

# published figures for people, named where each is printed
LOC_G, LOC_S = 4.7, 5.0             # StatPearls, 'G-LOC' (Whinnery and Forster, 888 episodes): none below 4.7 g, none sooner than 5 s
SEAT_G = (12.0, 14.0)               # Indian Journal of Aerospace Medicine, 'Ejection in unusual aircraft attitude': a current ejection seat
SPINE_G = (16.0, 13.0, 19.0)        # Stemper et al., J Orthop Res 36(6): even odds of injuring a lumbar spine, and the 95% interval
LOC_SOURCE = "StatPearls, G-LOC"
SEAT_SOURCE = "Indian Journal of Aerospace Medicine"
SPINE_SOURCE = "Stemper et al., J Orthop Res 36(6)"


def needed(reach, gap, h, vx):
    """Upward speed at take-off that lands him reach m on, at height h, and clears the far edge at gap m."""
    t = reach / vx
    vy = (h + 0.5 * G * t * t) / t
    if h > 0:
        t = gap / vx
        vy = max(vy, (h + 0.5 * G * t * t) / t)
    return vy


def flight(vy0, vx, h):
    """(seconds in the air, metres travelled, peak height, downward speed on landing) for a take-off at vy0."""
    down = math.sqrt(max(0.0, vy0 * vy0 - 2.0 * G * h))
    t = (vy0 + down) / G
    return t, vx * t, vy0 * vy0 / (2.0 * G), down


def ramp_speed(reach, gap, h, ramp, top):
    """The speed in m/s at which the ramp alone does it, or None if no speed up to top does."""
    sin, cos = math.sin(math.radians(ramp)), math.cos(math.radians(ramp))
    if top * sin < needed(reach, gap, h, top * cos):
        return None
    lo, hi = 0.1, top
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if mid * sin >= needed(reach, gap, h, mid * cos):
            hi = mid
        else:
            lo = mid
    return hi


def burst_g(dv, seconds):
    return dv / (seconds * G) + 1.0


def room_check(vy0, vx, gap, h, room, mu):
    """Where he comes down against the clear ground past the far edge, and whether he stops inside it.
    Returns a dict: fits, airborne (still flying where the room ends), up (m above the ground there), beyond (m past the
    end that he lands), into (m past the far edge that he lands), left, brake, end_kmh."""
    _, landed, _, _ = flight(vy0, vx, h)
    end = gap + room
    brake = vx * vx / (2.0 * mu * G)
    if landed > end + 1e-9:
        t = end / vx
        return {"fits": False, "airborne": True, "up": vy0 * t - 0.5 * G * t * t - h, "beyond": landed - end, "brake": brake}
    left = end - landed
    out = {"fits": brake <= left + 1e-9, "airborne": False, "into": landed - gap, "left": left, "brake": brake, "end_kmh": 0.0}
    if not out["fits"]:
        out["end_kmh"] = math.sqrt(max(0.0, vx * vx - 2.0 * mu * G * left)) * 3.6
    return out


def fastest_that_fits(reach, gap, h, ramp, room, mu, top_kmh, k_mass, range_km):
    """The highest whole km/h at take-off from which he clears the gap, lands inside the room and stops inside it.
    k_mass is km of range for each m/s of lift at his mass. None if no speed does."""
    sin, cos = math.sin(math.radians(ramp)), math.cos(math.radians(ramp))
    for kmh in range(int(top_kmh), 0, -1):
        v = kmh / 3.6
        vx, wheels = v * cos, v * sin
        need = needed(reach, gap, h, vx)
        if max(0.0, need - wheels) * k_mass > range_km:
            continue
        if room_check(max(need, wheels), vx, gap, h, room, mu)["fits"]:
            return kmh
    return None


def cmd_jump(a):
    lore = load_data("lore")
    sq, ch = lore["squall"], lore["chassis"]
    if a.gap <= 0:
        die("--gap is the width to clear in metres, more than 0")
    if not 0 <= a.ramp < 60:
        die("--ramp is the angle of the take-off in degrees, 0 (flat) to under 60")
    if a.load < 0:
        die("--load is what is aboard in kg, 0 or more")
    if a.drop and a.rise:
        die("give --drop (the far side is lower) or --rise (it is higher), not both")
    if a.drop < 0 or a.rise < 0:
        die("--drop and --rise are heights in metres, 0 or more")
    if a.speed is None and not a.ramp:
        die("give --speed; or --ramp alone, for the speed at which a ramp does it without a burst")
    margin = a.margin if a.margin is not None else float(sq["margin_m"])
    if margin < 0:
        die("--margin is how far past the far edge to aim, 0 or more")
    if a.room is not None and a.room <= margin:
        die("--room is the clear ground past the far edge in metres, and it must be more than the %s m he aims past the edge "
            "(--margin)" % trim(margin, 2))
    top = ch["top_kmh"] / 3.6
    h = a.rise - a.drop
    reach = a.gap + margin
    mass = ch["kerb_kg"] + a.load
    sin, cos = math.sin(math.radians(a.ramp)), math.cos(math.radians(a.ramp))
    if a.speed is None:
        v = ramp_speed(reach, a.gap, h, a.ramp, top)
        if v is None:
            die("no speed under his %d km/h governor clears that on a %s degree ramp alone: give --speed and the Squall makes up "
                "the rest" % (ch["top_kmh"], trim(a.ramp, 1)))
    else:
        if a.speed <= 0:
            die("--speed is km/h, more than 0")
        if a.speed > ch["top_kmh"] + 1e-9:
            die("his governor holds him to %d km/h, and he does not lift it for a stunt" % ch["top_kmh"])
        v = a.speed / 3.6
    vx, wheels = v * cos, v * sin
    need = needed(reach, a.gap, h, vx)
    lift = max(0.0, need - wheels)
    air, landed, peak, down = flight(max(need, wheels), vx, h)
    where = "level" if not h else "%s m %s" % (trim(abs(h), 1), "higher" if h > 0 else "lower")
    rec("JUMP", "%s m gap, landing %s, aiming %s m past the far edge | %s km/h%s%s" % (
        trim(a.gap, 1), where, trim(margin, 2), trim(v * 3.6, 0), "" if a.speed is not None else " needed",
        ", off a %s degree ramp" % trim(a.ramp, 1) if a.ramp else ", no ramp"))
    rec("MASS", "%s kg kerb [%s]%s = %s kg" % (num(ch["kerb_kg"]), lore["chassis_tags"]["kerb_kg"],
                                             " + %s kg aboard" % num(a.load) if a.load else ", nothing added", num(mass)))
    rec("FLIGHT", "%s s in the air, %s m up at the top, down %s m on%s [derived: no air drag, no steering once the wheels leave]" % (
        trim(air, 2), trim(peak, 1), trim(landed, 1),
        ", %s m past his mark" % trim(landed - reach, 1) if landed - reach > 0.05 else ""))
    if a.room is None:
        more("what lies past the far edge is not counted: --room M checks that he lands and stops inside M metres of clear ground")
    else:
        mu = SURFACES[a.surface]
        grip = "[derived: %s, mu %s typical; a model, not his figure]" % (SURFACE_NAMES[a.surface], trim(mu, 2))
        chk = room_check(max(need, wheels), vx, a.gap, h, a.room, mu)
        lead = "%s m of clear ground past the far edge: " % trim(a.room, 1)
        if chk["airborne"]:
            rec("ROOM", lead + "he is still %s m up where it ends, and comes down %s m beyond it [derived]" % (
                trim(chk["up"], 1), trim(chk["beyond"], 1)))
        elif chk["fits"]:
            rec("ROOM", lead + "down %s m in, %s m left; he stops in %s m, with %s m to spare %s" % (
                trim(chk["into"], 1), trim(chk["left"], 1), trim(chk["brake"], 1), trim(chk["left"] - chk["brake"], 1), grip))
        else:
            rec("ROOM", lead + "down %s m in, %s m left; he needs %s m to stop and is still doing %s km/h where it ends %s" % (
                trim(chk["into"], 1), trim(chk["left"], 1), trim(chk["brake"], 1), trim(chk["end_kmh"], 0), grip))
        if not chk["fits"]:
            rec("NO ROOM", "at %s km/h this jump does not fit the ground beyond it. What stands at the end of it decides what "
                           "that means: ask, or look, before you answer" % trim(v * 3.6, 0))
        best = fastest_that_fits(reach, a.gap, h, a.ramp, a.room, mu, ch["top_kmh"],
                                 sq["km_per_tonne_ms"] * mass / 1000.0, ch["range_km"])
        if best is None:
            rec("FASTEST", "no take-off speed lands and stops inside that room %s" % grip)
        else:
            bx, bw = best / 3.6 * cos, best / 3.6 * sin
            bneed = needed(reach, a.gap, h, bx)
            bdown = flight(max(bneed, bw), bx, h)[3]
            bg = max(burst_g(bneed - bw, sq["burst_s"]) if bneed - bw > 1e-9 else 1.0,
                     bdown * bdown / (2.0 * G * sq["landing_stroke_m"]) + 1.0)
            hurt = ("" if bg < SEAT_G[0] or a.unmanned else ": hard enough to hurt someone aboard" if bg < SPINE_G[0]
                    else ": past what a spine takes, so with anyone aboard no speed fits")
            rec("FASTEST", "%d km/h at take-off is the most that lands and stops inside it, at %s g at the worst%s %s" % (
                best, trim(bg, 1), hurt, grip))
            if abs(best - v * 3.6) > 0.5:
                more("run jump again with --speed %d for that sum" % best)
    if need <= 1e-9:
        rec("LIFT", "no upward speed is needed: the drop alone carries him over; no burst [derived]")
        km = 0.0
    elif lift <= 1e-9:
        rec("LIFT", "%s m/s upward is needed and the ramp gives %s: no burst [derived]" % (trim(need, 1), trim(wheels, 1)))
        km = 0.0
    else:
        km = sq["km_per_tonne_ms"] * mass / 1000.0 * lift
        rec("LIFT", "%s m/s upward is needed; %s, the Squall gives %s [derived]" % (
            trim(need, 1), "the ramp gives %s" % trim(wheels, 1) if a.ramp else "the wheels give none", trim(lift, 1)))
    catch = 0.0
    if a.catch and down > 1e-9:
        catch = sq["km_per_tonne_ms"] * mass / 1000.0 * down
    if km or catch:
        rule = "%s km for each tonne and each m/s" % trim(sq["km_per_tonne_ms"], 2)
        rec("COST", "%s km of range%s [lore: %s]" % (
            trim(km + catch, 1), " (%s to lift, %s to catch the landing)" % (trim(km, 1), trim(catch, 1)) if catch else "", rule))
        if km + catch > ch["range_km"]:
            more("that is more than a full bank holds: he cannot do it")
    launch = burst_g(lift, sq["burst_s"]) if lift > 1e-9 else 1.0
    if catch:
        land = burst_g(down, sq["burst_s"])
        land_how = "caught on a second burst"
    else:
        land = down * down / (2.0 * G * sq["landing_stroke_m"]) + 1.0
        land_how = "on the suspension, which is built for it [maker]"
        if land >= SPINE_G[0]:
            land_how = "on the suspension: how much of that it survives has no figure, the driver rules"
    parts = []
    if lift > 1e-9:
        parts.append("%s g for %s s at the lift" % (trim(launch, 1), trim(sq["burst_s"], 2)))
    parts.append("%s g at the landing, a fall of %s m, %s" % (trim(land, 1), trim(down * down / (2.0 * G), 1), land_how))
    rec("G-LOAD", "; ".join(parts) + " [lore: a %s s burst, %s m of travel on landing]" % (
        trim(sq["burst_s"], 2), trim(sq["landing_stroke_m"], 2)))
    worst = max(launch, land)
    if a.unmanned:
        more("nobody aboard: it matters only to what is clamped in the cradle")
    else:
        if worst >= LOC_G:
            more("too brief to black anyone out: that takes about %s s at %s g or more [%s]" % (trim(LOC_S, 0), trim(LOC_G, 1), LOC_SOURCE))
        if worst >= SPINE_G[0]:
            rec("WARNING", "%s g: at %s g half of lumbar spines are injured (%s to %s) [%s]. Someone aboard is likely to be hurt" % (
                trim(worst, 1), trim(SPINE_G[0], 0), trim(SPINE_G[1], 0), trim(SPINE_G[2], 0), SPINE_SOURCE))
        elif worst >= SEAT_G[0]:
            rec("WARNING", "%s g: as hard as an ejection seat, %s to %s g [%s], and those injure spines" % (
                trim(worst, 1), trim(SEAT_G[0], 0), trim(SEAT_G[1], 0), SEAT_SOURCE))
        if worst >= SEAT_G[0]:
            more("warn the driver before the jump, unless there is no time for an answer; then it is his call, life first [maker]")
            ease = ["more speed (less lift is needed)"]
            if not a.ramp:
                ease.append("a ramp")
            if not a.catch and land >= launch:
                ease.append("--catch for the landing")
            more("what would ease it: " + ", ".join(ease))
    if km or catch:
        rec("LEDGER", "book it in a sim with: lattice --state ... squall=%s wait=%s%s" % (
            trim(km, 1), trim(air, 1), " squall=%s" % trim(catch, 1) if catch else ""))
    rec("RULES", "a Squall is loud and ends silent running; a leap, not flight; everyone strapped in, nothing loose; two bursts "
                 "back to back, then 30 s for the ducts [lore]")


def register(sub):
    p = command(sub, "firn", "jump", cmd_jump,
                "FIRN-01's Squall: what a jump over a gap takes in speed, lift, range and g, by his mass and the distance",
                ["jump --gap 20 --speed 50 --load 260", "jump --gap 12 --ramp 15", "jump --gap 30 --speed 90 --ramp 10 --drop 4",
                 "jump --gap 60 --speed 60 --load 400 --catch", "jump --gap 30 --speed 200 --rise 5 --load 85 --room 40"])
    p.add_argument("--gap", type=float, required=True, help="the width to clear, m")
    p.add_argument("--speed", type=float, help="speed at take-off, km/h (leave out with --ramp for the speed a ramp alone needs)")
    p.add_argument("--ramp", type=float, default=0.0, help="angle of the take-off, degrees (default 0: flat ground)")
    p.add_argument("--drop", type=float, default=0.0, help="the far side is this much lower, m")
    p.add_argument("--rise", type=float, default=0.0, help="the far side is this much higher, m")
    p.add_argument("--load", type=float, default=0.0, help="people and cargo aboard, kg, on top of his kerb mass")
    p.add_argument("--margin", type=float, help="how far past the far edge to aim, m (default: his own length)")
    p.add_argument("--catch", action="store_true", help="spend a second burst to catch the landing: more range, less g")
    p.add_argument("--unmanned", action="store_true", help="nobody is aboard")
    p.add_argument("--room", type=float, help="clear ground past the far edge, m: checks that he lands and stops inside it, and "
                                              "names the fastest take-off speed that does")
    p.add_argument("--surface", choices=sorted(SURFACES), default="dry",
                   help="the ground he brakes on past the gap, with --room: typical grip, as the stop tool uses (default dry)")
