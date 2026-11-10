"""Space: orbits, the rocket equation, transfers, signal lag, and Star Trek warp factors for the fiction desk."""
import math

from .core import command, die, fmt_dur, more, num, parse_duration, rec, trim

G0 = 9.80665
C_KM_S = 299792.458
AU_KM = 149597870.7
LY_KM = 9460730472580.8

# body: (GM km3/s2, mean radius km, sidereal day s or None, note)
BODIES = {
    "earth": (398600.4418, 6371.0, 86164.0905, ""),
    "moon": (4902.8, 1737.4, None, ""),
    "mars": (42828.37, 3389.5, 88642.66, ""),
    "venus": (324858.59, 6051.8, None, ""),
    "mercury": (22031.87, 2439.7, None, ""),
    "jupiter": (126686534.0, 69911.0, 35730.0, ""),
    "saturn": (37931187.0, 58232.0, None, ""),
    "sun": (132712440018.0, 695700.0, None, ""),
}
# one-way distance from Earth, au: (closest, farthest), approximate
FROM_EARTH = {
    "moon": (0.00243, 0.00272), "sun": (0.983, 1.017), "mercury": (0.52, 1.48), "venus": (0.26, 1.74), "mars": (0.37, 2.68),
    "jupiter": (3.93, 6.47), "saturn": (8.0, 11.1), "uranus": (17.2, 21.1), "neptune": (28.8, 31.3),
}
WARP_TNG_HIGH = [(9.0, 1516.0), (9.2, 1649.0), (9.6, 1909.0), (9.9, 3053.0), (9.99, 7912.0), (9.9999, 199516.0)]


def _body(name):
    key = (name or "earth").lower()
    if key not in BODIES:
        die("unknown body '%s'; known: %s" % (name, ", ".join(BODIES)))
    return key, BODIES[key]


def _orbit(mu, r):
    return math.sqrt(mu / r), 2 * math.pi * math.sqrt(r ** 3 / mu)


def cmd_space(a):
    what = a.what
    if what == "orbit":
        key, (mu, radius, day, note) = _body(a.body)
        if a.sync:
            if not day:
                die("no rotation period on file for %s" % key)
            r = (mu * (day / (2 * math.pi)) ** 2) ** (1.0 / 3.0)
            alt = r - radius
        elif a.period:
            r = (mu * (parse_duration(a.period, "m") / (2 * math.pi)) ** 2) ** (1.0 / 3.0)
            alt = r - radius
        elif a.alt is not None:
            alt = a.alt
            r = radius + alt
        else:
            die("orbit needs --alt KM, --period TIME or --sync")
        if r <= radius:
            die("that orbit is below the surface of %s" % key)
        v, t = _orbit(mu, r)
        rec("ORBIT", "%s km above %s%s: %s km/s, one lap in %s [derived, circular]" % (
            num(alt), key.title(), " (%s)" % note if note else "", trim(v, 3), fmt_dur(t)))
        more("escape from there needs %s km/s; surface gravity %s m/s2; surface escape %s km/s" % (
            trim(v * math.sqrt(2), 3), trim(mu / radius ** 2 * 1000.0, 2), trim(math.sqrt(2 * mu / radius), 2)))
        return
    if what == "hohmann":
        key, (mu, radius, _, note) = _body(a.body)
        if a.alt is None or a.to_alt is None:
            die("hohmann needs --alt KM and --to-alt KM")
        r1, r2 = radius + a.alt, radius + a.to_alt
        if min(r1, r2) <= radius:
            die("both orbits must be above the surface")
        at = (r1 + r2) / 2.0
        v1, v2 = math.sqrt(mu / r1), math.sqrt(mu / r2)
        vt1 = math.sqrt(mu * (2 / r1 - 1 / at))
        vt2 = math.sqrt(mu * (2 / r2 - 1 / at))
        dv1, dv2 = abs(vt1 - v1), abs(v2 - vt2)
        rec("TRANSFER", "%s -> %s km above %s: burn 1 %s m/s, burn 2 %s m/s, total %s m/s [derived, Hohmann]" % (
            num(a.alt), num(a.to_alt), key.title(), num(dv1 * 1000), num(dv2 * 1000), num((dv1 + dv2) * 1000)))
        more("coast time %s" % fmt_dur(math.pi * math.sqrt(at ** 3 / mu)))
        return
    if what == "dv":
        if not a.isp or a.isp <= 0:
            die("dv needs --isp (specific impulse, seconds)")
        ve = a.isp * G0
        if a.wet and a.dry:
            if a.dry <= 0 or a.wet <= a.dry:
                die("--wet must be larger than --dry, both positive")
            dv = ve * math.log(a.wet / a.dry)
            rec("DELTA-V", "%s m/s from mass ratio %s at %s s specific impulse [derived, rocket equation]" % (
                num(dv), trim(a.wet / a.dry, 2), trim(a.isp, 0)))
            more("propellant is %s%% of the start mass; exhaust velocity %s m/s" % (trim(100 * (1 - a.dry / a.wet), 1), num(ve)))
        elif a.dv:
            ratio = math.exp(a.dv / ve)
            rec("MASS", "%s m/s at %s s needs a mass ratio of %s: %s%% of the start mass is propellant [derived]" % (
                num(a.dv), trim(a.isp, 0), trim(ratio, 2), trim(100 * (1 - 1 / ratio), 1)))
            if a.dry:
                more("for %s of dry mass that is %s at ignition" % (num(a.dry, 1), num(a.dry * ratio, 1)))
        else:
            die("dv needs --wet and --dry (to get delta-v), or --dv (to get the mass ratio)")
        rec("GUIDE", "low Earth orbit from the ground costs about 9,400 m/s including losses [rule of thumb]")
        return
    if what == "lag":
        if a.to:
            key = a.to.lower()
            if key not in FROM_EARTH:
                die("no distance on file for '%s'; known: %s (or give --km, --au, --ly)" % (a.to, ", ".join(FROM_EARTH)))
            lo, hi = FROM_EARTH[key]
            rec("SIGNAL", "Earth to %s: %s one way at closest, %s at farthest [derived, approximate distances]" % (
                key.title(), fmt_dur(lo * AU_KM / C_KM_S), fmt_dur(hi * AU_KM / C_KM_S)))
            more("a question and its answer take %s to %s" % (fmt_dur(2 * lo * AU_KM / C_KM_S), fmt_dur(2 * hi * AU_KM / C_KM_S)))
            return
        km = a.km if a.km else a.au * AU_KM if a.au else a.ly * LY_KM if a.ly else None
        if not km:
            die("lag needs --to BODY, or a distance: --km, --au or --ly")
        secs = km / C_KM_S
        if secs > 86400 * 365:
            rec("SIGNAL", "%s years one way [derived]" % trim(secs / (86400 * 365.25), 2))
        else:
            rec("SIGNAL", "%s one way, %s for a question and its answer [derived]" % (fmt_dur(secs), fmt_dur(2 * secs)))
        return
    # warp
    if a.factor is None or a.factor <= 0:
        die("warp needs a factor: space warp 6")
    w = a.factor
    if a.scale == "tos":
        mult = w ** 3
        src = "Star Trek, original-series scale: warp factor cubed"
    else:
        if w >= 10:
            die("on the Next Generation scale warp 10 is infinite speed; nothing reaches it")
        if w <= 9:
            mult = w ** (10.0 / 3.0)
            src = "Star Trek, Next Generation scale: factor to the power 10/3"
        else:
            pts = WARP_TNG_HIGH
            mult = pts[-1][1]
            for (w1, m1), (w2, m2) in zip(pts, pts[1:]):
                if w1 <= w <= w2:
                    f = (math.log10(10 - w1) - math.log10(10 - w)) / (math.log10(10 - w1) - math.log10(10 - w2))
                    mult = 10 ** (math.log10(m1) + f * (math.log10(m2) - math.log10(m1)))
                    break
            src = "Star Trek, Next Generation scale above warp 9: interpolated between published chart values"
    rec("WARP", "factor %s = %s times light speed [lore: %s]" % (trim(w, 4), num(mult), src))
    if a.ly:
        days = a.ly / mult * 365.25
        rec("TRIP", "%s light years takes %s [derived from lore]" % (
            trim(a.ly, 2), "%s years" % trim(days / 365.25, 2) if days > 730 else "%s days" % trim(days, 1) if days > 2 else fmt_dur(days * 86400)))
    rec("NOTE", "fiction physics; on screen, ships travel at the speed of the plot")


def register(sub):
    p = command(sub, "space", "space", cmd_space,
                "orbits, the rocket equation, transfers, signal lag, and warp factors (lore)",
                ["space orbit --alt 400", "space orbit --sync", "space orbit --alt 300 --body mars",
                 "space hohmann --alt 400 --to-alt 35786", "space dv --isp 350 --wet 100 --dry 30",
                 "space lag --to mars", "space warp 6 --ly 16.5"])
    p.add_argument("what", choices=["orbit", "hohmann", "dv", "lag", "warp"])
    p.add_argument("factor", nargs="?", type=float, help="warp factor")
    p.add_argument("--body", help="earth, moon, mars, venus, mercury, jupiter, saturn, sun (default earth)")
    p.add_argument("--alt", type=float, help="altitude above the surface, km")
    p.add_argument("--to-alt", type=float, help="hohmann: target altitude, km")
    p.add_argument("--period", help="orbit: find the altitude for this period (e.g. 90m, 2h)")
    p.add_argument("--sync", action="store_true", help="orbit: the synchronous (stationary) orbit")
    p.add_argument("--isp", type=float, help="dv: specific impulse, s")
    p.add_argument("--wet", type=float, help="dv: mass at ignition")
    p.add_argument("--dry", type=float, help="dv: mass at burnout")
    p.add_argument("--dv", type=float, help="dv: a target delta-v, m/s")
    p.add_argument("--to", help="lag: moon, sun, mercury, venus, mars, jupiter, saturn, uranus, neptune")
    p.add_argument("--km", type=float)
    p.add_argument("--au", type=float)
    p.add_argument("--ly", type=float, help="lag: light years; warp: trip length in light years")
    p.add_argument("--scale", choices=["tng", "tos"], default="tng", help="warp scale (default tng)")
