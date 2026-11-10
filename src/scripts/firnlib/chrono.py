"""Clock work: zones, daylight saving, conversions, meeting windows, spans.

The machine's own tz database (zoneinfo) is used when it has one. Where it is missing
(stock Python on Windows), a table generated from the IANA database (data/zones.json) stands in.
All arithmetic is done in UTC, so an ETA that crosses a clock change stays exact.
"""
import bisect
import os
import re
from datetime import date, datetime, timedelta, timezone, tzinfo

from .core import (PERSONAL_FILE, SETUP_HINT, command, die, fmt_hm, load_data, more, parse_clock, parse_duration, personal,
                   rec, trim, unprotect)

UTC = timezone.utc
EPOCH = datetime(1970, 1, 1)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

BUILTIN_ALIASES = {
    "utc": "UTC", "gmt": "UTC", "z": "UTC", "zulu": "UTC",
    "slt": "America/Los_Angeles", "sl": "America/Los_Angeles", "pacific": "America/Los_Angeles",
    "mountain": "America/Denver", "central": "America/Chicago", "eastern": "America/New_York",
    "uk": "Europe/London",
}


def aliases():
    out = dict(BUILTIN_ALIASES)
    for k, v in (personal().get("zone_aliases") or {}).items():
        out[str(k).lower()] = v
    return out


def home_is_set():
    h = personal().get("home") or {}
    return h.get("lat") is not None and h.get("lon") is not None and bool(h.get("tz"))


def default_zones():
    """The clocks shown when none are named: the personal list, or home and UTC."""
    zones = [str(z) for z in (personal().get("zones") or ["home", "utc"])]
    if not home_is_set():
        zones = [z for z in zones if z.lower() != "home"]
    return zones or ["utc"]


def home_tz():
    """The driver's home zone, or UTC while the personal block is still a placeholder."""
    return get_tz("home") if home_is_set() else UTC


def home_label():
    return "home" if home_is_set() else "utc"


# ---- the generated zone table (fallback only)

class TableTZ(tzinfo):
    """A zone read from data/zones.json. Honours fold, like zoneinfo."""

    def __init__(self, key, base, changes):
        self.key = key
        self.base = base
        self.times = [c[0] for c in changes]
        self.offs = [c[1] for c in changes]
        self.all = sorted(set([base] + self.offs), reverse=True)

    def _off_utc(self, u):
        if not self.times:
            return self.base
        i = bisect.bisect_right(self.times, (u - EPOCH).total_seconds() / 60.0)
        return self.base if i == 0 else self.offs[i - 1]

    def utcoffset(self, dt):
        if dt is None or not self.times:
            return timedelta(minutes=self.base)
        local = dt.replace(tzinfo=None)
        valid = [off for off in self.all if self._off_utc(local - timedelta(minutes=off)) == off]
        if len(valid) == 1:
            return timedelta(minutes=valid[0])
        if len(valid) >= 2:
            return timedelta(minutes=valid[1] if dt.fold else valid[0])
        # a wall time that does not exist: fold 0 keeps the offset from before the change, fold 1 the one after
        before = self._off_utc(local - timedelta(minutes=self.all[0]))
        after = self._off_utc(local - timedelta(minutes=self.all[-1]))
        return timedelta(minutes=after if dt.fold else before)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return self.key

    def fromutc(self, dt):
        u = dt.replace(tzinfo=None)
        off = self._off_utc(u)
        local = u + timedelta(minutes=off)
        fold_flag = 0
        for other in self.all:
            if other > off and self._off_utc(local - timedelta(minutes=other)) == other:
                fold_flag = 1
        return local.replace(tzinfo=self, fold=fold_flag)

    def __repr__(self):
        return "TableTZ(%r)" % self.key


_table = None
_table_index = None
_zi_index = None
_tz_cache = {}
_FIXED_RE = re.compile(r"^(?:utc|gmt)?\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?$", re.I)


def _zones():
    global _table, _table_index
    if _table is None:
        _table = load_data("zones")
        _table_index = {k.lower(): k for k in _table["zones"]}
    return _table


def table_tz(key):
    """A TableTZ for a zone name (any case), or None."""
    data = _zones()
    real = _table_index.get(str(key).lower())
    if not real:
        return None
    base, changes = data["tables"][data["zones"][real]]
    return TableTZ(real, base, changes)


def table_window():
    return tuple(_zones()["window"])


_zi_state = {}


def _zoneinfo_probe():
    if os.name == "nt" and not os.environ.get("PYTHONTZPATH"):
        # Windows keeps no tz database of its own, so only the tzdata package can supply one. Looking for the package
        # costs nothing; asking zoneinfo for a zone that is not there costs a good part of a call.
        try:
            import importlib.util
            if importlib.util.find_spec("tzdata") is None:
                return False
        except (ImportError, ValueError):
            return False
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Warsaw")
        return True
    except Exception:
        return False


def _zoneinfo_ok():
    """Is there a tz database on this machine that zoneinfo can read? Asked once."""
    if os.environ.get("FIRN_TZ", "").lower() in ("table", "rules"):
        return False
    if "ok" not in _zi_state:
        _zi_state["ok"] = _zoneinfo_probe()
    return _zi_state["ok"]


def tz_source():
    if _zoneinfo_ok():
        return "tz database"
    first, last = table_window()
    return "built-in zone table from the %s, %d to %d (no tz database on this machine)" % (
        _zones()["source"], first, last - 1)


def _zi_lookup(key):
    """Case-insensitive match against the tz database, or None."""
    global _zi_index
    from zoneinfo import ZoneInfo, available_timezones
    try:
        return ZoneInfo(key)
    except Exception:
        pass
    if _zi_index is None:
        try:
            _zi_index = {n.lower(): n for n in available_timezones()}
        except Exception:
            _zi_index = {}
    real = _zi_index.get(key.lower())
    if real:
        try:
            return ZoneInfo(real)
        except Exception:
            return None
    return None


def zone_key(name):
    """Resolve an alias, 'home', a place name or an IANA name to a zone key (or a fixed offset string)."""
    text = str(name).strip()
    low = text.lower()
    al = aliases()
    if low in al:
        return al[low]
    if _FIXED_RE.match(low):
        return low.upper() if low.startswith(("utc", "gmt")) else "UTC" + low
    _zones()
    if low in _table_index:
        return _table_index[low]
    if "/" not in text:
        from . import geo
        place = geo.find_place(text, say=True)
        if place and place.get("tz"):
            return place["tz"]
        if low in ("home", "work"):
            die("%s is not set yet: %s. Until then, name a zone or a place." % (low, SETUP_HINT))
    return text


def get_tz(name):
    key = zone_key(name)
    if key in _tz_cache:
        return _tz_cache[key]
    tz = None
    m = _FIXED_RE.match(key)
    if m:
        minutes = int(m.group(2)) * 60 + int(m.group(3) or 0)
        if minutes > 14 * 60:
            die("offset out of range: '%s'" % name)
        tz = timezone(timedelta(minutes=minutes if m.group(1) == "+" else -minutes))
    else:
        if _zoneinfo_ok():
            tz = _zi_lookup(key)
        if tz is None:
            tz = table_tz(key)
    if tz is None:
        import difflib
        pool = sorted(set(list(aliases()) + list(_zones()["zones"])))
        near = difflib.get_close_matches(str(name), pool, n=3, cutoff=0.6)
        hint = (" Did you mean: %s?" % ", ".join(near)) if near else ""
        die("unknown zone '%s'. Use an alias (%s), a place from the gazetteer, an IANA name such as Europe/Berlin, "
            "or an offset such as UTC+2.%s" % (name, ", ".join(sorted(aliases())[:8]), hint))
    _tz_cache[key] = tz
    return tz


def zone_label(name):
    """Short display label for a zone as the user named it."""
    text = str(name).strip()
    if text.lower() in aliases() or text.lower() in ("home", "work"):
        return text.upper()
    if "/" in text:
        return text.split("/")[-1].replace("_", " ").upper()
    return text.replace("_", " ").upper()


# ---- conversions (always through UTC)

def from_utc(u, tz):
    """Naive or aware UTC datetime -> aware local time in tz."""
    if u.tzinfo is None:
        u = u.replace(tzinfo=UTC)
    return u.astimezone(tz)


def to_utc(aware):
    return aware.astimezone(UTC)


def localize(naive, tz):
    """Attach a zone to a wall-clock time. Returns (aware, note); the note flags clock-change oddities."""
    cands = []
    for f in (0, 1):
        a = naive.replace(tzinfo=tz, fold=f)
        u = (naive - a.utcoffset()).replace(tzinfo=UTC)
        back = u.astimezone(tz).replace(tzinfo=None)
        cands.append((a, u, back == naive))
    (a0, u0, ok0), (a1, u1, ok1) = cands
    note = None
    if isinstance(tz, TableTZ):
        first, last = table_window()
        if not first <= naive.year < last:
            note = "the built-in zone table covers %d to %d; outside it the offset is only approximate" % (first, last - 1)
    if ok0 and ok1 and u0 != u1:
        return a0, "that wall time happens twice (clocks go back); using the first, summer-time one"
    if ok0:
        return a0, note
    if ok1:
        return a1, note
    real = u0.astimezone(tz)
    return real, "that wall time does not exist (clocks go forward); read as %s" % real.strftime("%H:%M")


def add(aware, seconds):
    """Add elapsed time. Done in UTC so a clock change inside the span cannot skew it."""
    return (to_utc(aware) + timedelta(seconds=seconds)).astimezone(aware.tzinfo)


def now_in(tz):
    fixed = os.environ.get("FIRN_NOW")
    if fixed:
        u = datetime.strptime(fixed, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
    else:
        u = datetime.now(UTC)
    return u.astimezone(tz)


_REL_RE = re.compile(r"^([+-])\s*(.+)$")
_DATE_RES = [
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$"), (3, 2, 1)),
    (re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"), (1, 2, 3)),
]


def parse_date(text, today=None):
    """'2026-11-08', '08.11.2026', 'today', 'tomorrow', 'yesterday' -> date, or None if it is not a date."""
    t = str(text).strip().lower()
    if today is not None and t in ("today", "tomorrow", "yesterday"):
        return today + timedelta(days={"today": 0, "tomorrow": 1, "yesterday": -1}[t])
    for rx, order in _DATE_RES:
        m = rx.match(t)
        if m:
            try:
                return date(int(m.group(order[0])), int(m.group(order[1])), int(m.group(order[2])))
            except ValueError:
                die("no such date: '%s'" % text)
    return None


def parse_when(text, tz):
    """Parse a moment in zone tz. Returns (aware, note).

    Accepts: now | HH:MM | today/tomorrow/yesterday [HH:MM] | YYYY-MM-DD [HH:MM] | DD.MM.YYYY [HH:MM]
             | YYYY-MM-DDTHH:MM | +90m / -2h (relative to now).
    """
    now = now_in(tz)
    t = unprotect(" ".join(str(text or "now").split()).strip())
    low = t.lower()
    if low in ("", "now"):
        return now, None
    m = _REL_RE.match(low)
    if m and not parse_date(low.split(" ")[0], now.date()):
        secs = parse_duration(m.group(2), default_unit="m")
        return add(now, secs if m.group(1) == "+" else -secs), None
    parts = low.replace("t", " ", 1).split(" ") if re.match(r"^\d{4}-\d{1,2}-\d{1,2}t\d", low) else low.split(" ")
    day, clock = None, None
    if len(parts) == 1:
        day = parse_date(parts[0], now.date())
        if day is None:
            clock = parts[0]
            day = now.date()
    elif len(parts) == 2:
        day = parse_date(parts[0], now.date())
        clock = parts[1]
    if day is None or len(parts) > 2:
        die("time not understood: '%s'. Use 'YYYY-MM-DD HH:MM', 'DD.MM.YYYY HH:MM', 'HH:MM', "
            "'tomorrow 07:30', '+90m' or 'now'." % text)
    h, mi = (0, 0)
    if clock is not None:
        clock = re.sub(r":\d{2}$", "", clock) if clock.count(":") == 2 else clock
        h, mi = parse_clock(clock)
    return localize(datetime(day.year, day.month, day.day, h, mi), tz)


def fmt_offset(dt):
    mins = int(dt.utcoffset().total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return "UTC%s%02d:%02d" % (sign, mins // 60, mins % 60)


def fmt_dt(dt):
    return "%s %s %s" % (dt.strftime("%Y-%m-%d %H:%M"), DAYS[dt.weekday()], fmt_offset(dt))


def fmt_short(dt):
    return "%s %s" % (dt.strftime("%H:%M"), DAYS[dt.weekday()])


def offset_hours(dt):
    return dt.utcoffset().total_seconds() / 3600.0


def fmt_delta_h(hours):
    if abs(hours) < 1e-9:
        return "same time"
    return "%s%s h" % ("+" if hours >= 0 else "-", trim(abs(hours), 2))


# ---- transitions

def transitions(tz, start_utc, end_utc):
    """Every UTC-offset change of tz between two aware UTC datetimes: [(utc_instant, before, after)]."""
    out = []
    step = timedelta(hours=12)
    t0 = start_utc
    off0 = t0.astimezone(tz).utcoffset()
    while t0 < end_utc:
        t1 = min(t0 + step, end_utc)
        off1 = t1.astimezone(tz).utcoffset()
        if off1 != off0:
            lo, hi = t0, t1
            while hi - lo > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == off0:
                    lo = mid
                else:
                    hi = mid
            out.append((hi.replace(microsecond=0), off0, off1))
        t0, off0 = t1, off1
    return out


def usual_gaps(tz_a, tz_b, year):
    """The two ordinary offset differences (hours, b minus a) of a year: mid-January and mid-July."""
    res = []
    for month in (1, 7):
        u = datetime(year, month, 15, 12, tzinfo=UTC)
        res.append(offset_hours(u.astimezone(tz_b)) - offset_hours(u.astimezone(tz_a)))
    return res


def odd_gap(tz_a, tz_b, u):
    """If the a-b difference at UTC instant u is not one of the year's two ordinary values, return (now, usual)."""
    diff = offset_hours(u.astimezone(tz_b)) - offset_hours(u.astimezone(tz_a))
    usual = usual_gaps(tz_a, tz_b, u.year)
    if all(abs(diff - x) > 1e-9 for x in usual):
        return diff, usual
    return None


def gap_windows(tz_a, tz_b, year):
    """Periods in a year when b minus a is not at an ordinary value: [(start_utc, end_utc, diff, usual)]."""
    start = datetime(year, 1, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC)
    edges = sorted(set([start, end] + [t for t, _, _ in transitions(tz_a, start, end)] +
                       [t for t, _, _ in transitions(tz_b, start, end)]))
    usual = usual_gaps(tz_a, tz_b, year)
    out = []
    for s, e in zip(edges, edges[1:]):
        mid = s + (e - s) / 2
        diff = offset_hours(mid.astimezone(tz_b)) - offset_hours(mid.astimezone(tz_a))
        if all(abs(diff - x) > 1e-9 for x in usual):
            out.append((s, e, diff, usual))
    return out


# ---- commands

def cmd_time(a):
    source = a.source or home_label()
    src = get_tz(source)
    when, note = parse_when(" ".join(a.when) if a.when else "now", src)
    zones = a.to or default_zones()
    labels = [zone_label(z) for z in zones]
    src_label = zone_label(source)
    width = max([len(x) for x in labels + [src_label]] + [10])
    src_key = zone_key(source)
    u = to_utc(when)
    shown_src = False
    rows = []
    for z, label in zip(zones, labels):
        tz = get_tz(z)
        local = u.astimezone(tz)
        if zone_key(z) == src_key and not shown_src:
            shown_src = True
            rows.append((label, fmt_dt(local), "", ""))
            continue
        diff = offset_hours(local) - offset_hours(when)
        day = (local.date() - when.date()).days
        mark = "" if day == 0 else (" next day" if day > 0 else " previous day")
        odd = odd_gap(src, tz, u)
        flag = ""
        if odd:
            flag = "  <- unusual: ordinarily %s" % " or ".join(sorted(set(fmt_delta_h(x) for x in odd[1])))
        rows.append((label, fmt_dt(local), "(%s%s)" % (fmt_delta_h(diff), mark), flag))
    if not shown_src:
        rows.insert(0, (src_label, fmt_dt(when), "", ""))
    for label, text, diff, flag in rows:
        print(("%-*s %s  %s%s" % (width, label, text, diff, flag)).rstrip())
    if note:
        rec("NOTE", note)
    if any(r[3] for r in rows):
        rec("NOTE", "clocks change on different dates in different countries; the usual gap returns within weeks")
    if not a.source and not home_is_set():
        rec("NOTE", "home is not set, so the time was read as UTC; set it in %s" % PERSONAL_FILE)


def cmd_dst(a):
    zones = a.zones or [z for z in default_zones() if zone_key(z) != "UTC"] or ["utc"]
    year = a.year or now_in(UTC).year
    start = datetime(year, 1, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC)
    rec("YEAR", "%d [%s]" % (year, tz_source()))
    for z in zones:
        tz = get_tz(z)
        trans = transitions(tz, start, end)
        rec("ZONE", "%s (%s)" % (zone_label(z), zone_key(z)))
        if not trans:
            more("no clock changes; fixed at %s" % fmt_offset(start.astimezone(tz)))
        for t, before, after in trans:
            lb = (t - timedelta(seconds=1)).astimezone(tz) + timedelta(seconds=1)
            la = t.astimezone(tz)
            way = "forward" if after > before else "back"
            more("%s %s  %s -> %s  clocks %s" % (la.strftime("%Y-%m-%d"), DAYS[la.weekday()],
                                                  lb.strftime("%H:%M"), la.strftime("%H:%M"), way))
    base = get_tz(zones[0])
    for z in zones[1:]:
        tz = get_tz(z)
        wins = gap_windows(base, tz, year)
        usual = sorted(set(fmt_delta_h(x) for x in usual_gaps(base, tz, year)))
        if not wins:
            rec("GAP", "%s vs %s: %s all year" % (zone_label(z), zone_label(zones[0]), " or ".join(usual)))
        for s, e, diff, _ in wins:
            ls, le = s.astimezone(base), e.astimezone(base)
            rec("GAP", "%s vs %s: %s instead of %s, from %s to %s (%d days)" % (
                zone_label(z), zone_label(zones[0]), fmt_delta_h(diff), " or ".join(usual),
                ls.strftime("%Y-%m-%d %H:%M"), le.strftime("%Y-%m-%d %H:%M"), round((e - s).total_seconds() / 86400.0)))


def _parse_window(text):
    m = re.fullmatch(r"\s*(\d{1,2}[:.]\d{2})\s*-\s*(\d{1,2}[:.]\d{2})\s*", text)
    if not m:
        die("window not understood: '%s' (use HH:MM-HH:MM, e.g. 08:00-22:30)" % text)
    (h1, m1), (h2, m2) = parse_clock(m.group(1)), parse_clock(m.group(2))
    return h1 * 60 + m1, h2 * 60 + m2


def _in_window(minute_of_day, win):
    s, e = win
    if s == e:
        return True
    return s <= minute_of_day < e if s < e else (minute_of_day >= s or minute_of_day < e)


def cmd_meet(a):
    default_win = _parse_window(a.awake)
    parties = []
    for spec in a.zones:
        name, _, win = spec.partition("=")
        parties.append((name, get_tz(name), _parse_window(win) if win else default_win))
    if len(parties) < 2:
        die("meet needs at least two zones")
    base_tz = parties[0][1]
    day = parse_date(a.day, now_in(base_tz).date()) if a.day else now_in(base_tz).date()
    if day is None:
        die("day not understood: '%s'" % a.day)
    start, _ = localize(datetime(day.year, day.month, day.day), base_tz)
    start_u = to_utc(start)
    step = max(1, a.step)
    spans, cur = [], None
    total = 24 * 60
    for minute in range(0, total + step, step):
        u = start_u + timedelta(minutes=minute)
        ok = minute < total
        if ok:
            for _, tz, win in parties:
                loc = u.astimezone(tz)
                if not _in_window(loc.hour * 60 + loc.minute, win):
                    ok = False
                    break
        if ok and cur is None:
            cur = minute
        elif not ok and cur is not None:
            spans.append((cur, minute))
            cur = None
    rec("DAY", "%s %s (%s)" % (day.isoformat(), DAYS[day.weekday()], zone_label(parties[0][0])))
    for name, tz, win in parties:
        rec("AWAKE", "%-10s %02d:%02d-%02d:%02d local" % (zone_label(name), win[0] // 60, win[0] % 60, win[1] // 60, win[1] % 60))
    spans = [(s, e) for s, e in spans if e - s >= a.min]
    if not spans:
        rec("WINDOW", "none of %d min or more on this day" % a.min)
        return
    for s, e in spans:
        cells = []
        for name, tz, _ in parties:
            ls = (start_u + timedelta(minutes=s)).astimezone(tz)
            le = (start_u + timedelta(minutes=e)).astimezone(tz)
            cells.append("%s %s-%s %s" % (zone_label(name), ls.strftime("%H:%M"), le.strftime("%H:%M"), DAYS[ls.weekday()]))
        rec("WINDOW", " | ".join(cells) + " | " + fmt_hm((e - s) / 60.0))
    best = max(spans, key=lambda x: x[1] - x[0])
    mid = start_u + timedelta(minutes=(best[0] + best[1]) / 2.0)
    rec("MIDPOINT", " | ".join("%s %s" % (zone_label(n), mid.astimezone(tz).strftime("%H:%M")) for n, tz, _ in parties))


def _calendar_diff(d1, d2):
    """Whole years, months, days from d1 to d2 (d1 <= d2)."""
    y = d2.year - d1.year
    m = d2.month - d1.month
    d = d2.day - d1.day
    if d < 0:
        m -= 1
        prev_month_end = date(d2.year, d2.month, 1) - timedelta(days=1)
        d += prev_month_end.day
        if d < 0:
            d = 0
    if m < 0:
        y -= 1
        m += 12
    return y, m, d


def cmd_span(a):
    zone = a.tz or home_label()
    tz_a = get_tz(a.a_tz or zone)
    tz_b = get_tz(a.b_tz or zone)
    start, n1 = parse_when(a.start, tz_a)
    end, n2 = parse_when(a.end or "now", tz_b)
    secs = (to_utc(end) - to_utc(start)).total_seconds()
    rec("FROM", "%s (%s)" % (fmt_dt(start), zone_label(a.a_tz or zone)))
    rec("TO", "%s (%s)" % (fmt_dt(end), zone_label(a.b_tz or zone)))
    sign = "" if secs >= 0 else "-"
    s = abs(secs)
    days, rem = divmod(int(round(s)), 86400)
    rec("SPAN", "%s%s d %s | %s h | %s min [derived]" % (
        sign, "{:,}".format(days), fmt_hm(rem / 3600.0), "{:,.1f}".format(s / 3600.0), "{:,.0f}".format(s / 60.0)))
    lo, hi = (start, end) if secs >= 0 else (end, start)
    d1, d2 = lo.date(), hi.astimezone(lo.tzinfo).date()
    y, m, d = _calendar_diff(d1, d2)
    rec("CALENDAR", "%s%d y %d mo %d d | %s weeks %d d" % (sign, y, m, d, "{:,}".format((d2 - d1).days // 7), (d2 - d1).days % 7))
    if secs < 0:
        rec("NOTE", "the second moment is before the first")
    for n in dict.fromkeys(x for x in (n1, n2) if x):
        rec("NOTE", n)


def register(sub):
    p = command(sub, "clock", "time", cmd_time, "one moment across zones (default: your own list of clocks)",
                ['time "2026-11-08 21:00" --from warsaw --to slt tokyo', "time 18:00 --from slt", "time now --to tokyo sydney",
                 "time +90m --from utc"])
    p.add_argument("when", nargs="*",
                   help="now | HH:MM | 'YYYY-MM-DD HH:MM' | 'DD.MM.YYYY HH:MM' | tomorrow 07:30 | +90m (default now)")
    p.add_argument("--from", dest="source",
                   help="zone of WHEN: alias, gazetteer place, IANA name or UTC+2 (default: home)")
    p.add_argument("--to", nargs="+", help="target zones (default: the zones list in personal.json)")

    p = command(sub, "clock", "dst", cmd_dst,
                "clock changes in a year, and the weeks when the usual gap between zones is off",
                ["dst warsaw slt", "dst warsaw new_york sydney --year 2027"])
    p.add_argument("zones", nargs="*", help="first zone is the reference (default: your own list)")
    p.add_argument("--year", type=int, help="default: this year")

    p = command(sub, "clock", "meet", cmd_meet, "the hours when everyone is awake, across zones",
                ["meet warsaw chicago", "meet warsaw=07:00-23:30 chicago=08:00-22:00 slt --day 2026-11-14"])
    p.add_argument("zones", nargs="+", help="ZONE, or ZONE=HH:MM-HH:MM for that zone's own waking window")
    p.add_argument("--day", help="date in the first zone (default today)")
    p.add_argument("--awake", default="08:00-22:00", help="waking window for zones without their own (default 08:00-22:00)")
    p.add_argument("--min", type=int, default=30, help="shortest window worth listing, minutes (default 30)")
    p.add_argument("--step", type=int, default=5, help="resolution, minutes (default 5)")

    p = command(sub, "clock", "span", cmd_span, "exact time between two moments: countdowns, ages, session length",
                ["span 2000-01-01 --tz utc", 'span "2026-12-18 06:40" "2026-12-18 13:05" --a-tz warsaw --b-tz chicago',
                 'span now "2026-12-24 18:00" --tz warsaw'])
    p.add_argument("start", help="first moment, as for 'time'")
    p.add_argument("end", nargs="?", help="second moment (default now)")
    p.add_argument("--tz", help="zone for both (default: home)")
    p.add_argument("--a-tz", help="zone of the first moment")
    p.add_argument("--b-tz", help="zone of the second moment")
