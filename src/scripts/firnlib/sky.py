"""Sky work: sun position, twilight, dark windows, moon phase and moonrise.

Sun: NOAA solar calculator equations (after Meeus), good to about a minute away from the poles.
Moon: the Astronomical Almanac low-precision series, good to about 0.3 degrees,
which is a few minutes on rise and set and about an hour on a phase.
Terrain, buildings and weather are not in it.
"""
import math
from datetime import datetime, timedelta, timezone

from . import chrono, geo
from .core import SETUP_HINT, clamp, command, die, fmt_hm, rec, trim

UTC = timezone.utc
SUN_ALT = {"sun": -0.833, "civil": -6.0, "nautical": -12.0, "astro": -18.0}
SYNODIC = 29.530588853


def _jd(u):
    return u.timestamp() / 86400.0 + 2440587.5


def _sun_terms(jd):
    """Declination (deg), equation of time (min), apparent ecliptic longitude (deg), obliquity (deg)."""
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t) + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = l0 + c - 0.00569 - 0.00478 * math.sin(omega)
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(omega)
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam))))
    y = math.tan(math.radians(eps / 2.0)) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
                             - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eot, lam % 360.0, eps


def sun_position(u, lat, lon):
    """Geometric elevation and azimuth (degrees, azimuth clockwise from north) at aware UTC time u."""
    u = u.astimezone(UTC)
    decl, eot, _, _ = _sun_terms(_jd(u))
    minutes = u.hour * 60 + u.minute + u.second / 60.0
    tst = (minutes + eot + 4.0 * lon) % 1440.0
    ha = math.radians(tst / 4.0 - 180.0)
    la, de = math.radians(lat), math.radians(decl)
    cosz = clamp(math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha), -1.0, 1.0)
    elev = 90.0 - math.degrees(math.acos(cosz))
    az = (math.degrees(math.atan2(math.sin(ha), math.cos(ha) * math.sin(la) - math.tan(de) * math.cos(la))) + 180.0) % 360.0
    return elev, az


def sun_event(day, lat, lon, alt, rising):
    """UTC time the sun crosses altitude alt on this solar day, or 'never' (stays below) / 'always' (stays above)."""
    lat = clamp(lat, -89.99, 89.99)
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    m = 720.0 - 4.0 * lon + (-360.0 if rising else 360.0)
    la = math.radians(lat)
    for _ in range(5):
        decl, eot, _, _ = _sun_terms(_jd(base + timedelta(minutes=m)))
        de = math.radians(decl)
        cos_h = (math.sin(math.radians(alt)) - math.sin(la) * math.sin(de)) / (math.cos(la) * math.cos(de))
        if cos_h > 1.0:
            return "never"
        if cos_h < -1.0:
            return "always"
        h = math.degrees(math.acos(cos_h))
        m = 720.0 - 4.0 * (lon + (h if rising else -h)) - eot
    return base + timedelta(minutes=m)


def solar_noon(day, lat, lon):
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    m = 720.0 - 4.0 * lon
    for _ in range(3):
        _, eot, _, _ = _sun_terms(_jd(base + timedelta(minutes=m)))
        m = 720.0 - 4.0 * lon - eot
    return base + timedelta(minutes=m)


def sun_state(u, lat, lon):
    elev, _ = sun_position(u, lat, lon)
    if elev > SUN_ALT["sun"]:
        return "day"
    if elev > SUN_ALT["civil"]:
        return "civil twilight"
    if elev > SUN_ALT["nautical"]:
        return "nautical twilight"
    if elev > SUN_ALT["astro"]:
        return "astronomical twilight"
    return "night"


def dark_window(day, lat, lon):
    """Astronomical dusk on this day to astronomical dawn on the next: (start, end), 'all' or 'none'."""
    dusk = sun_event(day, lat, lon, SUN_ALT["astro"], False)
    if dusk == "never":
        return "all"
    if dusk == "always":
        return "none"
    dawn = sun_event(day + timedelta(days=1), lat, lon, SUN_ALT["astro"], True)
    if isinstance(dawn, str):
        return "all" if dawn == "never" else "none"
    return dusk, dawn


# ---- moon

def _moon_ecl(jd):
    """Geocentric ecliptic longitude, latitude and horizontal parallax, degrees."""
    t = (jd - 2451545.0) / 36525.0

    def s(a, b):
        return math.sin(math.radians(a + b * t))

    def c(a, b):
        return math.cos(math.radians(a + b * t))

    lam = (218.32 + 481267.881 * t + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
           + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74) - 0.19 * s(357.5, 35999.05)
           - 0.11 * s(186.5, 966404.03))
    beta = (5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89) - 0.28 * s(318.3, 6003.15)
            - 0.17 * s(217.6, -407332.21))
    par = (0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.36)
           + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.74))
    return lam % 360.0, beta, par


def moon_altitude(u, lat, lon):
    """Geocentric altitude of the moon and the altitude that counts as the horizon for rise and set (degrees)."""
    jd = _jd(u.astimezone(UTC))
    lam, beta, par = _moon_ecl(jd)
    eps = math.radians(_sun_terms(jd)[3])
    lr, br = math.radians(lam), math.radians(beta)
    x = math.cos(br) * math.cos(lr)
    y = math.cos(eps) * math.cos(br) * math.sin(lr) - math.sin(eps) * math.sin(br)
    z = math.sin(eps) * math.cos(br) * math.sin(lr) + math.cos(eps) * math.sin(br)
    ra = math.degrees(math.atan2(y, x))
    dec = math.asin(clamp(z, -1.0, 1.0))
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)) % 360.0
    lha = math.radians(gmst + lon - ra)
    la = math.radians(lat)
    alt = math.degrees(math.asin(clamp(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(lha), -1.0, 1.0)))
    return alt, 0.7275 * par - 0.5667


def moon_phase(u):
    """(elongation deg 0-360, lit fraction 0-1, age in days, name) at aware UTC time u."""
    jd = _jd(u.astimezone(UTC))
    lam, beta, par = _moon_ecl(jd)
    sun_lam = _sun_terms(jd)[2]
    elong = (lam - sun_lam) % 360.0
    psi = math.acos(clamp(math.cos(math.radians(beta)) * math.cos(math.radians(lam - sun_lam)), -1.0, 1.0))
    dist = 6378.14 / math.sin(math.radians(par))
    sun_dist = 149597870.7
    i = math.atan2(sun_dist * math.sin(psi), dist - sun_dist * math.cos(psi))
    lit = (1.0 + math.cos(i)) / 2.0
    age = elong / 360.0 * SYNODIC
    half_day = 360.0 / SYNODIC / 2.0
    name = None
    for target, label in ((0.0, "new moon"), (90.0, "first quarter"), (180.0, "full moon"), (270.0, "last quarter"), (360.0, "new moon")):
        if abs(elong - target) <= half_day:
            name = label
    if name is None:
        name = ("waxing crescent" if elong < 90 else "waxing gibbous" if elong < 180
                else "waning gibbous" if elong < 270 else "waning crescent")
    return elong, lit, age, name


def next_phase(u, target):
    """Next UTC time after u when the elongation reaches target degrees (0 new, 90, 180 full, 270)."""
    def off(t):
        return (moon_phase(t)[0] - target + 180.0) % 360.0 - 180.0

    step = timedelta(hours=6)
    t0, f0 = u, off(u)
    for _ in range(140):
        t1 = t0 + step
        f1 = off(t1)
        if f0 < 0 <= f1 and f1 - f0 < 180:
            lo, hi = t0, t1
            while hi - lo > timedelta(seconds=30):
                mid = lo + (hi - lo) / 2
                if off(mid) < 0:
                    lo = mid
                else:
                    hi = mid
            return hi
        t0, f0 = t1, f1
    return None


def moon_events(start_u, end_u, lat, lon):
    """Moonrise and moonset between two UTC instants: [('rise'|'set', utc)]."""
    def f(t):
        alt, h0 = moon_altitude(t, lat, lon)
        return alt - h0

    out = []
    step = timedelta(minutes=10)
    t0, f0 = start_u, f(start_u)
    while t0 < end_u:
        t1 = min(t0 + step, end_u)
        f1 = f(t1)
        if (f0 < 0) != (f1 < 0):
            lo, hi, flo = t0, t1, f0
            while hi - lo > timedelta(seconds=20):
                mid = lo + (hi - lo) / 2
                fm = f(mid)
                if (fm < 0) == (flo < 0):
                    lo, flo = mid, fm
                else:
                    hi = mid
            out.append(("rise" if f0 < 0 else "set", hi))
        t0, f0 = t1, f1
    return out


# ---- commands

def _place_and_zone(place, tz_arg):
    label, lat, lon, p = geo.parse_point(place)
    zone = tz_arg or (p or {}).get("tz")
    if zone:
        return label, lat, lon, chrono.get_tz(zone), chrono.zone_key(zone), False
    return label, lat, lon, chrono.home_tz(), "home time" if chrono.home_is_set() else "UTC", True


def _local_day(a_date, tz):
    today = chrono.now_in(tz).date()
    if not a_date:
        return today, True
    day = chrono.parse_date(a_date, today)
    if day is None:
        die("date not understood: '%s' (use YYYY-MM-DD)" % a_date)
    return day, day == today


def cmd_sun(a):
    label, lat, lon, tz, zkey, guessed = _place_and_zone(a.place, a.tz)
    day, is_today = _local_day(a.date, tz)
    noon = solar_noon(day, lat, lon)
    rec("PLACE", "%s (%.4f, %.4f) %s %s | times in %s (%s)" % (
        label, lat, lon, day.isoformat(), chrono.DAYS[day.weekday()], zkey, chrono.fmt_offset(noon.astimezone(tz))))
    rows = [("ASTRO DAWN", "astro", True), ("NAUT DAWN", "nautical", True), ("CIVIL DAWN", "civil", True),
            ("SUNRISE", "sun", True), ("SUNSET", "sun", False), ("CIVIL DUSK", "civil", False),
            ("NAUT DUSK", "nautical", False), ("ASTRO DUSK", "astro", False)]
    res = {}
    for name, key, rising in rows:
        ev = sun_event(day, lat, lon, SUN_ALT[key], rising)
        res[(key, rising)] = ev
        if name == "SUNSET":
            elev, _ = sun_position(noon, lat, lon)
            rec("NOON", "%s (sun %s deg %s the horizon)" % (
                noon.astimezone(tz).strftime("%H:%M"), trim(abs(elev), 1), "above" if elev >= 0 else "below"))
        if isinstance(ev, str):
            if key == "sun":
                why = "polar night" if ev == "never" else "midnight sun"
            else:
                why = "the sun stays below it all day" if ev == "never" else "the sun stays above it all night"
            rec(name, "none (%s)" % why)
        else:
            rec(name, ev.astimezone(tz).strftime("%H:%M"))
    sr, ss = res[("sun", True)], res[("sun", False)]
    if not isinstance(sr, str) and not isinstance(ss, str):
        rec("DAYLIGHT", fmt_hm((ss - sr).total_seconds() / 3600.0))
    dw = dark_window(day, lat, lon)
    if dw == "all":
        rec("DARK", "all day: the sun never climbs above 18 deg below the horizon")
    elif dw == "none":
        rec("DARK", "no full astronomical darkness tonight")
    else:
        rec("DARK", "%s to %s (%s)" % (dw[0].astimezone(tz).strftime("%H:%M"), dw[1].astimezone(tz).strftime("%H:%M"),
                                       fmt_hm((dw[1] - dw[0]).total_seconds() / 3600.0)))
    if a.photo:
        for name, hi_alt, lo_alt in (("GOLDEN", 6.0, -4.0), ("BLUE", -4.0, -6.0)):
            parts = []
            for rising, word in ((True, "morning"), (False, "evening")):
                e1 = sun_event(day, lat, lon, lo_alt if rising else hi_alt, rising)
                e2 = sun_event(day, lat, lon, hi_alt if rising else lo_alt, rising)
                if not isinstance(e1, str) and not isinstance(e2, str):
                    parts.append("%s %s-%s" % (word, e1.astimezone(tz).strftime("%H:%M"), e2.astimezone(tz).strftime("%H:%M")))
            rec(name, " | ".join(parts) if parts else "none today")
    if a.at or is_today:
        when, note = chrono.parse_when(a.at, tz) if a.at else (chrono.now_in(tz), None)
        if a.at and a.date:
            h, mi = when.hour, when.minute
            when, note = chrono.localize(datetime(day.year, day.month, day.day, h, mi), tz)
        elev, az = sun_position(chrono.to_utc(when), lat, lon)
        rec("SUN AT", "%s: %s deg %s the horizon, bearing %03.0f %s -> %s" % (
            when.strftime("%H:%M"), trim(abs(elev), 1), "above" if elev >= 0 else "below", az, geo.compass(az),
            sun_state(chrono.to_utc(when), lat, lon)))
        if note:
            rec("NOTE", note)
    if guessed:
        rec("NOTE", "no zone known for a raw coordinate; %s shown (set --tz)" % zkey)
    rec("NOTE", "[derived] good to about a minute; terrain, buildings and weather are not in it")


def cmd_moon(a):
    if not a.place and not chrono.home_is_set():
        die("give a place: home is not set yet (%s)" % SETUP_HINT)
    label, lat, lon, tz, zkey, guessed = _place_and_zone(a.place or "home", a.tz)
    day, is_today = _local_day(a.date, tz)
    start, _ = chrono.localize(datetime(day.year, day.month, day.day), tz)
    start_u = chrono.to_utc(start)
    end_u = start_u + timedelta(days=1)
    ref = chrono.to_utc(chrono.now_in(tz)) if is_today else start_u + timedelta(hours=12)
    elong, lit, age, name = moon_phase(ref)
    rec("PLACE", "%s %s %s | times in %s" % (label, day.isoformat(), chrono.DAYS[day.weekday()], zkey))
    rec("PHASE", "%s, %d%% lit, %s days into the cycle [derived, %s]" % (
        name, round(lit * 100), trim(age, 1), "now" if is_today else "at local noon"))
    events = moon_events(start_u, end_u, lat, lon)
    rises = [t for k, t in events if k == "rise"]
    sets = [t for k, t in events if k == "set"]
    rec("MOONRISE", ", ".join(t.astimezone(tz).strftime("%H:%M") for t in rises) or "none this day")
    rec("MOONSET", ", ".join(t.astimezone(tz).strftime("%H:%M") for t in sets) or "none this day")
    nxt = []
    for target, word in ((0.0, "new"), (90.0, "first quarter"), (180.0, "full"), (270.0, "last quarter")):
        t = next_phase(ref, target)
        if t:
            nxt.append((t, word))
    nxt.sort()
    rec("NEXT", " | ".join("%s %s" % (w, t.astimezone(tz).strftime("%Y-%m-%d %H:%M")) for t, w in nxt))
    dw = dark_window(day, lat, lon)
    if isinstance(dw, tuple):
        up = total = 0
        t = dw[0]
        while t < dw[1]:
            alt, h0 = moon_altitude(t, lat, lon)
            up += 1 if alt > h0 else 0
            total += 1
            t += timedelta(minutes=10)
        hours = (dw[1] - dw[0]).total_seconds() / 3600.0
        up_h = hours * up / max(1, total)
        mid_lit = moon_phase(dw[0] + (dw[1] - dw[0]) / 2)[1]
        if up == 0:
            verdict = "moon down for all of it: properly dark"
        else:
            verdict = "moon up for %s of it at %d%% lit" % (fmt_hm(up_h), round(mid_lit * 100))
        rec("NIGHT", "dark window %s-%s (%s); %s" % (dw[0].astimezone(tz).strftime("%H:%M"),
                                                     dw[1].astimezone(tz).strftime("%H:%M"), fmt_hm(hours), verdict))
    elif dw == "none":
        rec("NIGHT", "no full astronomical darkness tonight")
    else:
        rec("NIGHT", "dark all day")
    if guessed:
        rec("NOTE", "no zone known for a raw coordinate; %s shown (set --tz)" % zkey)
    rec("NOTE", "[derived] rise and set good to about 5 min, phases to about an hour; terrain not in it")


def register(sub):
    p = command(sub, "sky", "sun", cmd_sun,
                "dawn, sunrise, noon, sunset, dusk, the dark window, and where the sun is",
                ["sun warsaw", "sun chicago --date 2026-12-21", "sun krakow --at 15:30", "sun 69.65,18.96 --tz Europe/Oslo --photo"])
    p.add_argument("place", help="gazetteer place or lat,lon")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--tz", help="zone for the output (default: the place's own zone)")
    p.add_argument("--at", help="also give the sun's elevation and bearing at this local time (HH:MM)")
    p.add_argument("--photo", action="store_true", help="add golden hour and blue hour")

    p = command(sub, "sky", "moon", cmd_moon, "phase, moonrise, moonset, next phases, and how dark the night is",
                ["moon warsaw", "moon krakow --date 2026-11-24", "moon reykjavik"])
    p.add_argument("place", nargs="?", help="gazetteer place or lat,lon (default home)")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--tz", help="zone for the output (default: the place's own zone)")
