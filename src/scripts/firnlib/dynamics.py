"""Vehicle dynamics: performance, stopping, collisions, cornering, weight transfer, springs, gearing, tyres.

Plain mechanics with stated assumptions. Results are estimates for comparing and sanity-checking,
not a substitute for a test track or a maker's data sheet.
"""
import math
import re
from datetime import date

from .core import G, command, die, fmt_dur, load_data, more, num, rec, table, trim, unprotect

HP_W = 745.69987
PS_W = 735.49875
RHO = 1.225

SURFACES = {"dry": 0.80, "wet": 0.50, "gravel": 0.55, "snow": 0.25, "ice": 0.10}
SURFACE_NAMES = {"dry": "dry asphalt", "wet": "wet asphalt", "gravel": "loose gravel", "snow": "packed snow", "ice": "ice"}

LOAD_INDEX = {
    60: 250, 61: 257, 62: 265, 63: 272, 64: 280, 65: 290, 66: 300, 67: 307, 68: 315, 69: 325, 70: 335, 71: 345,
    72: 355, 73: 365, 74: 375, 75: 387, 76: 400, 77: 412, 78: 425, 79: 437, 80: 450, 81: 462, 82: 475, 83: 487,
    84: 500, 85: 515, 86: 530, 87: 545, 88: 560, 89: 580, 90: 600, 91: 615, 92: 630, 93: 650, 94: 670, 95: 690,
    96: 710, 97: 730, 98: 750, 99: 775, 100: 800, 101: 825, 102: 850, 103: 875, 104: 900, 105: 925, 106: 950,
    107: 975, 108: 1000, 109: 1030, 110: 1060, 111: 1090, 112: 1120, 113: 1150, 114: 1180, 115: 1215, 116: 1250,
    117: 1285, 118: 1320, 119: 1360, 120: 1400, 121: 1450, 122: 1500, 123: 1550, 124: 1600, 125: 1650,
}
SPEED_SYMBOL = {"L": 120, "M": 130, "N": 140, "P": 150, "Q": 160, "R": 170, "S": 180, "T": 190, "U": 200,
                "H": 210, "V": 240, "W": 270, "Y": 300}

_SPEED_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(km/h|kmh|kph|mph|m/s|mps|kn|kt)?$", re.I)
_SPEED_F = {"km/h": 1.0, "kmh": 1.0, "kph": 1.0, "mph": 1.609344, "m/s": 3.6, "mps": 3.6, "kn": 1.852, "kt": 1.852}


def parse_speed(text):
    """'130', '130kmh', '100mph', '44.7m/s' -> km/h."""
    m = _SPEED_RE.match(unprotect(str(text)).strip())
    if not m:
        die("speed not understood: '%s' (try 130, 100mph, 44.7m/s)" % text)
    return float(m.group(1)) * _SPEED_F[(m.group(2) or "km/h").lower()]


def _power_w(a):
    given = [(a.kw, 1000.0), (getattr(a, "hp", None), HP_W), (getattr(a, "ps", None), PS_W)]
    vals = [v * f for v, f in given if v]
    if len(vals) != 1:
        return None
    return vals[0]


# ---- perf

def traction_force(m, mu, drive, cg, wheelbase, front_frac):
    """Peak forward force the tyres can pass, with weight transfer under acceleration (N)."""
    if drive == "awd":
        return mu * m * G
    k = mu * cg / wheelbase
    if drive == "rwd":
        return mu * m * G * (1.0 - front_frac) / (1.0 - k) if k < 0.95 else mu * m * G
    return mu * m * G * front_frac / (1.0 + k)


def accel_run(power, m, ftrac, cda, crr, eff, marks_kmh, dist_marks, v_cap=None, rho=RHO):
    """Integrate a standing start. Returns {mark: (time, speed m/s, distance)}."""
    out = {}
    v = x = t = 0.0
    dt = 0.002
    speeds = sorted(marks_kmh)
    dists = sorted(dist_marks)
    while t < 120.0 and (speeds or dists):
        drive = min(ftrac, power * eff / max(v, 0.5))
        f = drive - 0.5 * rho * cda * v * v - crr * m * G
        acc = f / (m * 1.04)
        if acc <= 1e-4 and v > 1.0:
            break
        v2 = v + acc * dt
        if v_cap and v2 > v_cap:
            v2 = v_cap
        x += (v + v2) / 2.0 * dt
        v = v2
        t += dt
        while speeds and v * 3.6 >= speeds[0]:
            out[("v", speeds.pop(0))] = (t, v, x)
        while dists and x >= dists[0]:
            out[("d", dists.pop(0))] = (t, v, x)
    return out


def top_speed(power, m, cda, crr, eff, rho=RHO):
    lo, hi = 1.0, 400.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if (0.5 * rho * cda * mid * mid + crr * m * G) * mid < power * eff:
            lo = mid
        else:
            hi = mid
    return lo


def road_load_kw(v, m, cda, crr, rho=RHO):
    return (0.5 * rho * cda * v * v + crr * m * G) * v / 1000.0


def cmd_perf(a):
    tags = "as given"
    top_gov = a.top
    if a.firn:
        lore = load_data("lore")
        ch, mdl = lore["chassis"], lore["model"]
        power = ch["power_hp"] * HP_W
        m = float(ch["kerb_kg"])
        drive = "awd"
        mu = a.mu if a.mu is not None else mdl["grip_mu"]
        cda = a.cda or mdl["cd"] * mdl["frontal_area_factor"] * ch["width_m"] * ch["height_m"]
        crr = a.crr if a.crr is not None else mdl["crr"]
        eff = a.eff if a.eff is not None else mdl["drivetrain_efficiency"]
        wheelbase = ch["wheelbase_m"]
        top_gov = top_gov or ch["top_kmh"]
        tags = "sheet and lore figures; drag, tyres and grip are model assumptions, not canon"
    else:
        power = _power_w(a)
        if power is None or not a.kg:
            die("perf needs one of --kw, --hp, --ps and a mass --kg (or --firn)")
        m = a.kg
        drive = a.drive
        mu = a.mu if a.mu is not None else 1.0
        cda = a.cda or ((a.cd or 0.30) * (a.area or 2.2))
        crr = a.crr if a.crr is not None else 0.012
        eff = a.eff if a.eff is not None else 0.90
        wheelbase = a.wheelbase
    if m <= 0 or power <= 0 or not 0 < eff <= 1 or mu <= 0:
        die("power, mass, grip and efficiency must be positive")
    front = (a.front_pct if a.front_pct is not None else (60.0 if drive == "fwd" else 50.0)) / 100.0
    ftrac = traction_force(m, mu, drive, a.cg, wheelbase, front)
    rec("INPUT", "%s kW (%s hp), %s kg, %s, mu %s, CdA %s m2, Crr %s, driveline %s%% [%s]" % (
        num(power / 1000.0), num(power / HP_W), num(m), drive.upper(), trim(mu, 2), trim(cda, 2), trim(crr, 3),
        trim(eff * 100, 0), tags))
    rec("RATIO", "%s W/kg | %s hp per tonne [derived]" % (num(power / m), num(power / HP_W / (m / 1000.0))))
    res = accel_run(power, m, ftrac, cda, crr, eff, [100, 200], [402.336],
                    v_cap=(top_gov / 3.6 if top_gov else None))
    v_switch = power * eff / ftrac * 3.6
    if ("v", 100) in res:
        how = "grip-limited all the way" if v_switch >= 100 else "grip-limited to %s km/h, then power-limited" % num(v_switch)
        rec("0-100", "%s s [estimate: %s]" % (trim(res[("v", 100)][0], 1), how))
    else:
        rec("0-100", "does not reach 100 km/h")
    if ("v", 200) in res:
        rec("0-200", "%s s [estimate]" % trim(res[("v", 200)][0], 1))
    if ("d", 402.336) in res:
        t, v, _ = res[("d", 402.336)]
        rec("400 M", "%s s at %s km/h [estimate]" % (trim(t, 1), num(v * 3.6)))
    vmax = top_speed(power, m, cda, crr, eff) * 3.6
    if top_gov:
        need = road_load_kw(top_gov / 3.6, m, cda, crr) / eff
        rec("TOP", "governed %s km/h, which takes %s kW; power alone would give ~%s km/h [estimate]" % (
            num(top_gov), num(need), num(vmax)))
    else:
        rec("TOP", "~%s km/h on power alone, if gearing and tyres allow [estimate]" % num(vmax))
    rows = []
    acc_kw = load_data("lore")["model"]["accessory_kw"] if a.firn else 0.0
    for kmh in (a.speeds or [50, 90, 110, 130]):
        v = kmh / 3.6
        wheel = road_load_kw(v, m, cda, crr)
        src = wheel / eff + acc_kw
        rows.append(("%s km/h" % trim(kmh, 0), "%s kW at the wheels" % trim(wheel, 1), "%s Wh/km from the store" % num(src * 1000.0 / kmh)))
    rec("CRUISE", "steady level road, no wind [estimate]")
    table(rows, indent=11)
    if a.firn:
        cruise = mdl["cruise_kmh"]
        wh_km = (road_load_kw(cruise / 3.6, m, cda, crr) / eff + acc_kw) * 1000.0 / cruise
        kwh = wh_km * ch["range_km"] / 1000.0
        rec("BANK", "%s km at %s km/h implies ~%s kWh in the capacitor bank [derived from lore]" % (
            num(ch["range_km"]), num(cruise), num(kwh)))
        veil_kw = wh_km * lore["lattice"]["veil_km_per_min"] * 60.0 / 1000.0
        share = veil_kw / (power / 1000.0)
        more("a full Veil at %s km of range a minute is ~%s kW, %s" % (
            trim(lore["lattice"]["veil_km_per_min"], 1), num(veil_kw),
            "more than the motors' peak" if share > 1 else "%s%% of the motors' peak" % trim(share * 100.0, 0)))
        more("real supercapacitors hold roughly 5-10 Wh/kg, so that bank would weigh %s-%s t: lore physics, not ours" % (
            num(kwh / 10.0), num(kwh / 5.0)))
        sheet = ch["zero_100_s"]
        if ("v", 100) in res:
            got = res[("v", 100)][0]
            rec("CHECK", "sheet says 0-100 in %s s; this model gives %s s -> %s" % (
                trim(sheet, 1), trim(got, 1), "consistent" if abs(got - sheet) <= 0.5 else "not consistent: revisit grip or mass"))
    rec("NOTE", "a simple model: no gear changes, launch control, tyre heat or wind; expect 10-15% either way")


# ---- stop

def _stop_numbers(v0, v1, decel, reaction):
    react = v0 * reaction
    brake = (v0 * v0 - v1 * v1) / (2.0 * decel)
    t = reaction + (v0 - v1) / decel
    return react, brake, t


def cmd_stop(a):
    v0 = parse_speed(a.frm) / 3.6
    v1 = parse_speed(a.to) / 3.6
    if v0 <= 0 or v1 < 0 or v1 >= v0:
        die("--from must be faster than --to, and both zero or more")
    grade = a.grade / 100.0
    reaction = a.reaction
    if a.motor_kw:
        if not a.kg:
            die("--motor-kw needs the vehicle mass: --kg")
        mu = a.mu if a.mu is not None else SURFACES[a.surface]
        p, m = a.motor_kw * 1000.0, a.kg
        a_grip = mu * G
        vc = p / (m * a_grip)
        hi_from, hi_to = v0, max(v1, min(v0, vc))
        d_power = m * (hi_from ** 3 - hi_to ** 3) / (3.0 * p)
        t_power = m * (hi_from ** 2 - hi_to ** 2) / (2.0 * p)
        lo_from = min(v0, vc)
        d_grip = max(0.0, (lo_from ** 2 - v1 ** 2) / (2.0 * a_grip)) if lo_from > v1 else 0.0
        t_grip = max(0.0, (lo_from - v1) / a_grip) if lo_from > v1 else 0.0
        react = v0 * reaction
        rec("SPEED", "%s -> %s km/h on the motors alone: %s kW of reverse torque, %s kg, mu %s" % (
            num(v0 * 3.6), num(v1 * 3.6), num(a.motor_kw), num(m), trim(mu, 2)))
        if reaction:
            rec("REACTION", "%s m in %s s" % (trim(react, 1), trim(reaction, 2)))
        if vc < v0:
            rec("PHASE 1", "%s -> %s km/h power-limited: %s m in %s (%s g rising to %s g)" % (
                num(v0 * 3.6), num(hi_to * 3.6), trim(d_power, 1), fmt_dur(t_power),
                trim(p / (m * v0) / G, 2), trim(p / (m * hi_to) / G, 2)))
        if d_grip > 0:
            rec("PHASE 2", "%s -> %s km/h grip-limited: %s m in %s (%s g)" % (
                num(lo_from * 3.6), num(v1 * 3.6), trim(d_grip, 1), fmt_dur(t_grip), trim(a_grip / G, 2)))
        total = react + d_power + d_grip
        rec("TOTAL", "%s m, %s [derived]" % (trim(total, 1), fmt_dur(reaction + t_power + t_grip)))
        friction = (v0 * v0 - v1 * v1) / (2.0 * a_grip) + react
        more("working friction brakes on the same surface: %s m" % trim(friction, 1))
        if a.obstacle is not None:
            rec("OBSTACLE", "at %s m: %s" % (trim(a.obstacle, 1), "stops %s m short" % trim(a.obstacle - total, 1)
                                             if total <= a.obstacle else "NOT ENOUGH ROAD by %s m: find another way to shed speed" % trim(total - a.obstacle, 1)))
        rec("NOTE", "motors can only brake as hard as their power allows at speed and the tyres allow at low speed; drag ignored")
        return

    def decel_for(key):
        if a.g is not None:
            return a.g * G, "%s g as given" % trim(a.g, 2)
        mu = a.mu if a.mu is not None else SURFACES[key]
        label = "mu %s" % trim(mu, 2) if a.mu is not None else "%s, mu %s [typical]" % (SURFACE_NAMES[key], trim(mu, 2))
        return (mu + grade) * G, label

    if a.table:
        rows = []
        for key in ("dry", "wet", "gravel", "snow", "ice"):
            mu = SURFACES[key]
            d = (mu + grade) * G
            if d <= 0:
                rows.append((SURFACE_NAMES[key], trim(mu, 2), "-", "-", "does not stop on this slope"))
                continue
            react, brake, t = _stop_numbers(v0, v1, d, reaction)
            rows.append((SURFACE_NAMES[key], trim(mu, 2), "%s m" % trim(react, 0), "%s m" % trim(brake, 0), "%s m in %s" % (trim(react + brake, 0), fmt_dur(t))))
        rec("SPEED", "%s -> %s km/h, reaction %s s%s [typical grip values]" % (
            num(v0 * 3.6), num(v1 * 3.6), trim(reaction, 2), ", grade %s%%" % trim(a.grade, 1) if grade else ""))
        table(rows, header=("surface", "mu", "reaction", "braking", "total"), indent=2, right=(1, 2, 3))
        rec("NOTE", "ice takes about eight times the braking distance of dry asphalt; leave the gap before you need it")
        return
    decel, label = decel_for(a.surface)
    if decel <= 0:
        die("on this slope and surface the vehicle does not stop: grip is less than the gradient")
    react, brake, t = _stop_numbers(v0, v1, decel, reaction)
    rec("SPEED", "%s -> %s km/h (%s)%s" % (num(v0 * 3.6), num(v1 * 3.6), label, ", grade %s%%" % trim(a.grade, 1) if grade else ""))
    if reaction:
        rec("REACTION", "%s m in %s s" % (trim(react, 1), trim(reaction, 2)))
    rec("BRAKING", "%s m in %s (%s g)" % (trim(brake, 1), fmt_dur(t - reaction), trim(decel / G, 2)))
    rec("TOTAL", "%s m, %s [derived]" % (trim(react + brake, 1), fmt_dur(t)))
    if a.obstacle is not None:
        if react + brake <= a.obstacle:
            rec("OBSTACLE", "at %s m: stops %s m short" % (trim(a.obstacle, 1), trim(a.obstacle - react - brake, 1)))
        else:
            room = max(0.0, a.obstacle - react)
            v_hit = math.sqrt(max(0.0, v0 * v0 - 2.0 * decel * room))
            rec("OBSTACLE", "at %s m: still doing %s km/h on arrival" % (trim(a.obstacle, 1), num(v_hit * 3.6)))
    if a.gap:
        rec("GAP", "%s s behind at %s km/h is %s m" % (trim(a.gap, 1), num(v0 * 3.6), trim(v0 * a.gap, 0)))


# ---- impact

def cmd_impact(a):
    m1, v1 = a.kg, parse_speed(a.speed) / 3.6
    if m1 <= 0 or v1 < 0:
        die("mass must be positive and speed zero or more")
    ke1 = 0.5 * m1 * v1 * v1
    rec("VEHICLE", "%s kg at %s km/h: %s kJ, momentum %s kN s [derived]" % (num(m1), num(v1 * 3.6), num(ke1 / 1000.0), num(m1 * v1 / 1000.0)))
    more("that energy is a fall from %s m" % trim(v1 * v1 / (2 * G), 1))
    if a.vs_kg:
        m2 = a.vs_kg
        v2 = parse_speed(a.vs_speed) / 3.6 if a.vs_speed else 0.0
        if m2 <= 0:
            die("--vs-kg must be positive")
        sign = 1.0 if a.same_way else -1.0
        u2 = sign * v2
        vc = (m1 * v1 + m2 * u2) / (m1 + m2)
        closing = abs(v1 - u2)
        dv1, dv2 = abs(v1 - vc), abs(u2 - vc)
        lost = 0.5 * (m1 * m2 / (m1 + m2)) * closing * closing
        rec("OTHER", "%s kg at %s km/h, %s" % (num(m2), num(v2 * 3.6), "same direction" if a.same_way else "head-on"))
        rec("CLOSING", "%s km/h; mass ratio 1 : %s" % (num(closing * 3.6), trim(m2 / m1, 2)))
        rec("AFTER", "both move at %s km/h %s [derived, bodies lock together]" % (
            num(abs(vc) * 3.6), "in the first vehicle's direction" if vc >= 0 else "in the other's direction"))
        rec("CHANGE", "first vehicle %s km/h, other %s km/h: the lighter one takes the larger change" % (num(dv1 * 3.6), num(dv2 * 3.6)))
        rec("ENERGY", "%s kJ goes into crushing metal" % num(lost / 1000.0))
        if a.crush:
            for name, dv in (("first", dv1), ("other", dv2)):
                g = dv * dv / (2.0 * a.crush) / G
                more("%s vehicle: about %s g average over %s m of crush" % (name, num(g), trim(a.crush, 2)))
    elif a.crush:
        g = v1 * v1 / (2.0 * a.crush) / G
        rec("BARRIER", "stopped in %s m of crush: about %s g average for %s ms" % (trim(a.crush, 2), num(g), num(2.0 * a.crush / max(v1, 0.1) * 1000.0)))
    rec("NOTE", "plain mechanics; a real outcome depends on structure, restraints, angle and what gives way first")


# ---- corner, transfer, spring

def cmd_corner(a):
    if a.radius is None or a.radius <= 0:
        die("corner needs a positive --radius in metres")
    bank = math.radians(a.bank)
    if a.speed:
        v = parse_speed(a.speed) / 3.6
        lat = v * v / (a.radius * G)
        rec("CORNER", "%s km/h on a %s m radius needs %s g of lateral grip [derived]" % (num(v * 3.6), trim(a.radius, 1), trim(lat, 2)))
        if a.bank:
            need = (lat * math.cos(bank) - math.sin(bank)) / (math.cos(bank) + lat * math.sin(bank))
            more("with %s deg of banking the tyres need mu %s" % (trim(a.bank, 1), trim(max(0.0, need), 2)))
        return
    if a.mu is None:
        die("corner needs --mu (tyre grip) for a speed limit, or --speed for the grip a speed needs")
    mu = a.mu
    den = 1.0 - mu * math.tan(bank)
    if den <= 0:
        rec("CORNER", "banked so steeply that grip never runs out at any speed")
        return
    grip = G * (mu + math.tan(bank)) / den
    v = math.sqrt(grip * a.radius)
    text = "%s km/h at %s g" % (num(v * 3.6), trim(v * v / (a.radius * G), 2))
    if a.cla and a.kg:
        k = 0.5 * RHO * a.cla
        den2 = a.kg / a.radius - mu * k
        if den2 <= 0:
            text += "; with that downforce grip outruns the corner at any speed"
        else:
            v_aero = math.sqrt(mu * a.kg * G / den2)
            text += "; with downforce (ClA %s m2) %s km/h at %s g" % (trim(a.cla, 2), num(v_aero * 3.6), trim(v_aero * v_aero / (a.radius * G), 2))
    rec("CORNER", "radius %s m, mu %s%s -> %s [derived]" % (trim(a.radius, 1), trim(mu, 2),
                                                             ", banked %s deg" % trim(a.bank, 1) if a.bank else "", text))
    rec("NOTE", "steady-state limit on a constant radius; real corners tighten, crest and change surface")


def cmd_transfer(a):
    m, h, wb, tr = a.kg, a.cg, a.wheelbase, a.track
    if min(m, h, wb, tr) <= 0:
        die("mass, centre of gravity height, wheelbase and track must be positive")
    front = m * a.front_pct / 100.0
    rear = m - front
    long_t = m * a.ax * h / wb
    f_axle, r_axle = front - long_t, rear + long_t
    lat_total = m * abs(a.ay) * h / tr
    lat_f = lat_total * a.roll_front / 100.0
    lat_r = lat_total - lat_f
    rec("STATIC", "front %s kg (%s%%), rear %s kg" % (num(front), trim(a.front_pct, 1), num(rear)))
    if a.ax:
        rec("LONG", "%s g %s moves %s kg to the %s: front %s kg, rear %s kg [derived]" % (
            trim(abs(a.ax), 2), "braking" if a.ax < 0 else "acceleration", num(abs(long_t)),
            "front" if a.ax < 0 else "rear", num(f_axle), num(r_axle)))
    if a.ay:
        rec("LATERAL", "%s g cornering moves %s kg to the outside: %s kg across the front, %s kg across the rear" % (
            trim(abs(a.ay), 2), num(lat_total), num(lat_f), num(lat_r)))
    wheels = [("front outside", f_axle / 2 + lat_f), ("front inside", f_axle / 2 - lat_f),
              ("rear outside", r_axle / 2 + lat_r), ("rear inside", r_axle / 2 - lat_r)]
    table([(n, "%s kg" % num(w), "LIFTS" if w <= 0 else "%s%%" % trim(100.0 * w / m, 1)) for n, w in wheels],
          header=("wheel", "load", "share"), indent=2, right=(1, 2))
    rec("NOTE", "rigid-body model; --roll-front is the share of roll stiffness at the front (more of it moves balance toward understeer)")


_RATE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(n/mm|kgf/mm|kg/mm|lb/in|lbs/in)?$", re.I)
_RATE_F = {"n/mm": 1.0, "kgf/mm": G, "kg/mm": G, "lb/in": 0.175127, "lbs/in": 0.175127}


def cmd_spring(a):
    if a.corner_kg <= 0 or a.motion_ratio <= 0:
        die("--corner-kg and --motion-ratio must be positive")
    if (a.hz is None) == (a.rate is None):
        die("give --hz (to get the spring rate) or --rate (to get the frequency)")
    mr2 = a.motion_ratio ** 2
    if a.hz is not None:
        wheel = (2 * math.pi * a.hz) ** 2 * a.corner_kg / 1000.0
        spring = wheel / mr2
        hz = a.hz
    else:
        m = _RATE_RE.match(str(a.rate).strip())
        if not m:
            die("rate not understood: '%s' (try 80, 80N/mm, 8kgf/mm, 450lb/in)" % a.rate)
        spring = float(m.group(1)) * _RATE_F[(m.group(2) or "n/mm").lower()]
        wheel = spring * mr2
        hz = math.sqrt(wheel * 1000.0 / a.corner_kg) / (2 * math.pi)
    rec("CORNER", "%s kg sprung on this wheel, motion ratio %s" % (num(a.corner_kg), trim(a.motion_ratio, 2)))
    rec("FREQUENCY", "%s Hz [derived]" % trim(hz, 2))
    rec("SPRING", "%s N/mm | %s kgf/mm | %s lb/in%s" % (
        trim(spring, 1), trim(spring / G, 2), num(spring / 0.175127),
        "" if a.motion_ratio == 1 else " (wheel rate %s N/mm)" % trim(wheel, 1)))
    rec("SAG", "%s mm of static compression at the wheel" % trim(a.corner_kg * G / wheel, 0))
    rec("GUIDE", "road cars ride near 1-1.5 Hz, sporty 1.5-2.5, downforce racers 3-5 and more [rule of thumb]")


# ---- gearing

def tyre_dims(size):
    """'225/45R17 94W' -> dict of section, aspect, rim, diameter mm, circumference mm, load index, speed symbol."""
    t = unprotect(str(size)).upper().replace(" ", "")
    m = re.match(r"^(?:P|LT)?(\d{3})/(\d{2})(?:ZR|R|D|B|-)?(\d{2}(?:\.\d)?)(?:C)?\(?(\d{2,3})?([A-Z])?\)?(XL|RF)?$", t)
    if not m:
        die("tyre size not understood: '%s' (try 225/45R17 or 225/45R17 94W)" % size)
    width, aspect, rim = float(m.group(1)), float(m.group(2)), float(m.group(3))
    side = width * aspect / 100.0
    dia = rim * 25.4 + 2 * side
    return {"text": "%d/%dR%s" % (width, aspect, trim(rim, 1)), "width": width, "aspect": aspect, "rim": rim,
            "side": side, "dia": dia, "circ": math.pi * dia,
            "li": int(m.group(4)) if m.group(4) else None, "sym": m.group(5), "xl": m.group(6)}


def cmd_gearing(a):
    if a.tyre:
        circ = tyre_dims(a.tyre)["circ"] / 1000.0
        wheel = "tyre %s" % a.tyre
    elif a.diameter_mm:
        circ = math.pi * a.diameter_mm / 1000.0
        wheel = "wheel %s mm" % trim(a.diameter_mm, 0)
    else:
        die("gearing needs --tyre SIZE or --diameter-mm")
    if not a.ratios or min(a.ratios) <= 0 or a.redline <= 0:
        die("gearing needs positive --ratios and --redline")
    shift = a.shift or a.redline
    final = a.final
    if a.kph:
        final = shift * circ * 60.0 / (a.ratios[-1] * 1000.0 * a.kph)
        rec("FINAL", "%s puts top gear at %s km/h at %s rpm [derived]" % (trim(final, 3), num(a.kph), num(shift)))
    if not final or final <= 0:
        die("gearing needs --final, or --kph to solve it")
    rec("SETUP", "%s (%s m per turn), final drive %s, shift at %s rpm" % (wheel, trim(circ, 3), trim(final, 3), num(shift)))
    rows = []
    for i, r in enumerate(a.ratios):
        per1000 = 1000.0 * circ * 60.0 / (r * final * 1000.0)
        top = per1000 * shift / 1000.0
        if i + 1 < len(a.ratios):
            after = shift * a.ratios[i + 1] / r
            drop = "%s rpm (-%s%%)" % (num(after), trim(100.0 * (1 - a.ratios[i + 1] / r), 0))
        else:
            drop = "-"
        row = [str(i + 1), trim(r, 3), trim(r * final, 2), trim(per1000, 1), num(top), drop]
        if a.at:
            rpm = parse_speed(a.at) / per1000 * 1000.0
            row.append(num(rpm) if rpm <= a.redline else "over")
        rows.append(row)
    header = ["gear", "ratio", "overall", "km/h per 1000", "km/h at shift", "rpm after upshift"]
    if a.at:
        header.append("rpm at %s" % num(parse_speed(a.at)))
    table(rows, header=header, indent=2, right=(0, 1, 2, 3, 4))
    rec("TOP", "%s km/h in top gear at %s rpm, if the power is there [derived]" % (
        num(1000.0 * circ * 60.0 / (a.ratios[-1] * final * 1000.0) * shift / 1000.0), num(shift)))


# ---- tyre

def cmd_tyre(a):
    t = tyre_dims(a.size)
    rec("TYRE", "%s: %s mm wide, sidewall %s mm, rim %s in" % (t["text"], trim(t["width"], 0), trim(t["side"], 1), trim(t["rim"], 1)))
    rec("SIZE", "diameter %s mm (%s in), circumference %s mm, %s turns per km [derived, unloaded]" % (
        trim(t["dia"], 0), trim(t["dia"] / 25.4, 1), num(t["circ"]), num(1e6 / t["circ"])))
    if t["li"]:
        kg = LOAD_INDEX.get(t["li"])
        rec("LOAD", "index %d = %s per tyre [table]%s" % (
            t["li"], "%s kg" % num(kg) if kg else "outside the table (60-125)", ", extra load" if t["xl"] == "XL" else ""))
    if t["sym"]:
        sp = SPEED_SYMBOL.get(t["sym"])
        rec("SPEED", "symbol %s = %s [table]" % (t["sym"], "up to %d km/h" % sp if sp else "not a symbol in the table (L-Y)"))
    if a.vs:
        o = tyre_dims(a.vs)
        diff = (o["dia"] - t["dia"]) / t["dia"] * 100.0
        rec("VERSUS", "%s: diameter %s mm, %s%s%% against the first" % (o["text"], trim(o["dia"], 0), "+" if diff >= 0 else "", trim(diff, 2)))
        more("when the speedometer shows 100 km/h the true speed is %s km/h" % trim(100.0 * o["dia"] / t["dia"], 1))
        more("ride height changes by %s mm; width by %s mm" % (trim((o["dia"] - t["dia"]) / 2.0, 1), trim(o["width"] - t["width"], 0)))
        if abs(diff) > 3:
            more("more than about 3% apart: expect speedometer, ABS and clearance trouble, and check the rules [rule of thumb]")
    if a.bar is not None:
        if a.set_temp is None or a.now_temp is None:
            die("--bar needs --set-temp and --now-temp (C)")
        p2 = (a.bar + 1.01325) * (a.now_temp + 273.15) / (a.set_temp + 273.15) - 1.01325
        rec("PRESSURE", "%s bar set at %s C reads %s bar at %s C (%s%s bar) [derived, same air]" % (
            trim(a.bar, 2), trim(a.set_temp, 0), trim(p2, 2), trim(a.now_temp, 0), "+" if p2 >= a.bar else "", trim(p2 - a.bar, 2)))
        more("set pressures cold, to the door-pillar figure; about 0.1 bar changes for every 10 C")
    if a.dot:
        m = re.match(r"^(\d{2})(\d{2})$", a.dot)
        if not m or not 1 <= int(m.group(1)) <= 53:
            die("--dot is the four-digit date code: week then year, e.g. 2319")
        week, year = int(m.group(1)), 2000 + int(m.group(2))
        today = date.today()
        made = date.fromisocalendar(year, min(week, 52), 1)
        age = (today - made).days / 365.25
        rec("DATE", "week %d of %d: %s years old [derived]" % (week, year, trim(max(0.0, age), 1)))
        more("makers commonly advise replacing tyres somewhere between 6 and 10 years whatever the tread; check yours")


def register(sub):
    p = command(sub, "vehicle", "perf", cmd_perf,
                "0-100, quarter mile, top speed and cruise consumption from power, mass and drag; or FIRN-01 against his sheet",
                ["perf --firn", "perf --kw 283 --kg 1580 --drive rwd --front-pct 38 --cd 0.29 --area 2.0",
                 "perf --hp 150 --kg 1400 --drive fwd"])
    p.add_argument("--firn", action="store_true", help="use FIRN-01's sheet and lore figures")
    p.add_argument("--kw", type=float)
    p.add_argument("--hp", type=float, help="mechanical horsepower")
    p.add_argument("--ps", type=float, help="metric horsepower (PS, CV, the Polish KM)")
    p.add_argument("--kg", type=float, help="mass with driver")
    p.add_argument("--drive", choices=["awd", "rwd", "fwd"], default="awd")
    p.add_argument("--mu", type=float, help="tyre grip (road tyres about 1.0)")
    p.add_argument("--cd", type=float, help="drag coefficient (default 0.30)")
    p.add_argument("--area", type=float, help="frontal area, m2 (default 2.2)")
    p.add_argument("--cda", type=float, help="drag area Cd x A, m2 (instead of --cd and --area)")
    p.add_argument("--crr", type=float, help="rolling resistance coefficient (default 0.012)")
    p.add_argument("--eff", type=float, help="driveline efficiency 0-1 (default 0.90)")
    p.add_argument("--cg", type=float, default=0.55, help="centre of gravity height, m (default 0.55)")
    p.add_argument("--wheelbase", type=float, default=2.8, help="m (default 2.8)")
    p.add_argument("--front-pct", type=float, help="static weight on the front axle, percent (default 50, fwd 60)")
    p.add_argument("--top", type=float, help="governed top speed, km/h")
    p.add_argument("--speeds", type=float, nargs="+", help="cruise speeds to list, km/h")

    p = command(sub, "vehicle", "stop", cmd_stop,
                "stopping distance by speed and surface, speed at an obstacle, following gap, or braking on the motors alone",
                ["stop --from 130 --surface wet", "stop --from 50 --table", "stop --from 60 --obstacle 30",
                 "stop --from 250 --to 90 --g 1.4 --reaction 0", "stop --from 100mph --motor-kw 858 --kg 2940 --reaction 0"])
    p.add_argument("--from", dest="frm", required=True, help="starting speed: 130, 100mph, 44.7m/s")
    p.add_argument("--to", default="0", help="final speed (default 0)")
    p.add_argument("--surface", choices=sorted(SURFACES), default="dry", help="typical grip: dry 0.8, wet 0.5, gravel 0.55, snow 0.25, ice 0.1")
    p.add_argument("--mu", type=float, help="grip coefficient, overrides --surface")
    p.add_argument("--g", type=float, help="deceleration in g, overrides grip (racing: 1.2-1.6, more with downforce)")
    p.add_argument("--reaction", type=float, default=1.0, help="reaction time, s (default 1.0; 0 for a braking zone)")
    p.add_argument("--grade", type=float, default=0.0, help="slope percent, positive uphill")
    p.add_argument("--obstacle", type=float, help="metres to something in the way")
    p.add_argument("--gap", type=float, help="following gap in seconds, shown in metres")
    p.add_argument("--table", action="store_true", help="compare all surfaces")
    p.add_argument("--motor-kw", type=float, help="no friction brakes: slow on reverse motor torque of this power")
    p.add_argument("--kg", type=float, help="vehicle mass for --motor-kw")

    p = command(sub, "vehicle", "impact", cmd_impact,
                "collision mechanics: energy, speed change for each vehicle, crush loads",
                ["impact --kg 2940 --speed 80", "impact --kg 2940 --speed 80 --vs-kg 3100 --vs-speed 80 --crush 0.7",
                 "impact --kg 1500 --speed 50 --crush 0.6"])
    p.add_argument("--kg", type=float, required=True)
    p.add_argument("--speed", required=True, help="speed: 80, 50mph")
    p.add_argument("--vs-kg", type=float, help="the other vehicle's mass")
    p.add_argument("--vs-speed", help="the other vehicle's speed (default 0: parked)")
    p.add_argument("--same-way", action="store_true", help="the other vehicle is moving the same way (default head-on)")
    p.add_argument("--crush", type=float, help="crush distance, m, for average g")

    p = command(sub, "vehicle", "corner", cmd_corner, "cornering speed for a radius and grip, or the grip a speed needs",
                ["corner --radius 80 --mu 1.3", "corner --radius 120 --speed 150", "corner --radius 60 --mu 1.5 --cla 3.2 --kg 1250"])
    p.add_argument("--radius", type=float, help="corner radius, m")
    p.add_argument("--mu", type=float, help="tyre grip")
    p.add_argument("--speed", help="a speed to test instead")
    p.add_argument("--bank", type=float, default=0.0, help="banking, degrees")
    p.add_argument("--cla", type=float, help="downforce area Cl x A, m2")
    p.add_argument("--kg", type=float, help="mass, for downforce")

    p = command(sub, "vehicle", "transfer", cmd_transfer, "weight transfer under braking, acceleration and cornering, wheel by wheel",
                ["transfer --kg 1300 --cg 0.45 --wheelbase 2.6 --track 1.6 --front-pct 48 --ax -1.2 --ay 1.4"])
    p.add_argument("--kg", type=float, required=True)
    p.add_argument("--cg", type=float, required=True, help="centre of gravity height, m")
    p.add_argument("--wheelbase", type=float, required=True, help="m")
    p.add_argument("--track", type=float, required=True, help="m")
    p.add_argument("--front-pct", type=float, default=50.0, help="static weight on the front axle, percent")
    p.add_argument("--ax", type=float, default=0.0, help="longitudinal g: negative braking, positive accelerating")
    p.add_argument("--ay", type=float, default=0.0, help="lateral g")
    p.add_argument("--roll-front", type=float, default=50.0, help="share of roll stiffness at the front, percent")

    p = command(sub, "vehicle", "spring", cmd_spring, "spring rate from ride frequency, or frequency from rate (some racing sims ask for Hz)",
                ["spring --hz 2.4 --corner-kg 310", "spring --rate 8kgf/mm --corner-kg 290 --motion-ratio 0.9"])
    p.add_argument("--hz", type=float, help="natural frequency, Hz")
    p.add_argument("--rate", help="spring rate: 80 (N/mm), 8kgf/mm, 450lb/in")
    p.add_argument("--corner-kg", type=float, required=True, help="sprung mass carried by this wheel, kg")
    p.add_argument("--motion-ratio", type=float, default=1.0, help="wheel travel per spring travel (default 1)")

    p = command(sub, "vehicle", "gearing", cmd_gearing, "speed in each gear, rpm drop on upshift, final drive for a target top speed",
                ["gearing --ratios 3.2 2.1 1.5 1.2 1.0 0.85 --final 3.9 --tyre 305/30R20 --redline 8000",
                 "gearing --ratios 2.9 2.0 1.5 1.2 1.0 0.84 --tyre 305/30R20 --redline 8500 --kph 320 --at 130"])
    p.add_argument("--ratios", type=float, nargs="+", help="gear ratios, first to top")
    p.add_argument("--final", type=float, help="final drive ratio")
    p.add_argument("--tyre", help="driven tyre size, e.g. 305/30R20")
    p.add_argument("--diameter-mm", type=float, help="driven wheel diameter instead of a tyre size")
    p.add_argument("--redline", type=float, default=7000.0, help="rpm (default 7000)")
    p.add_argument("--shift", type=float, help="shift rpm (default the redline)")
    p.add_argument("--kph", type=float, help="solve the final drive for this top speed in top gear")
    p.add_argument("--at", help="also show rpm in each gear at this speed")

    p = command(sub, "vehicle", "tyre", cmd_tyre, "decode a tyre size, compare two, correct pressure for temperature, read a date code",
                ['tyre "225/45R17 94W"', "tyre 205/55R16 --vs 225/45R17", "tyre 225/45R17 --bar 2.4 --set-temp 20 --now-temp -5",
                 "tyre 225/45R17 --dot 2319"])
    p.add_argument("size", help="e.g. 225/45R17, or with load and speed: '225/45R17 94W'")
    p.add_argument("--vs", help="a second size to compare")
    p.add_argument("--bar", type=float, help="cold pressure as set, bar")
    p.add_argument("--set-temp", type=float, help="temperature when it was set, C")
    p.add_argument("--now-temp", type=float, help="temperature now, C")
    p.add_argument("--dot", help="four-digit date code from the sidewall: WWYY")
