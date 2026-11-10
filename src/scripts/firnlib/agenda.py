"""Agenda: an event that repeats in another zone, and the clock of the conversation itself.

series   "every Saturday 12:00 SLT" as local time for the next weeks. Countries change their clocks on different
         dates, so for a few weeks a year the same event lands an hour early or late: those weeks are flagged.
session  how long this conversation has run, from the stamp 'boot' handed out. It is the only honest way to notice
         a long session: a mind in a conversation has no clock of its own.
"""
import re
from datetime import datetime, timedelta

from . import chrono, ical
from .core import command, die, fmt_hm, more, parse_clock, parse_duration, rec, table

DAY_NAMES = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3,
             "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}
FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_EVERY_RE = re.compile(r"^(\d+)?\s*(d|day|days|w|wk|week|weeks|fortnight|m|mo|month|months)$", re.I)
MAX_COUNT = 60


def parse_every(text):
    """'week', '2w', 'day', '3d', 'fortnight', 'month' -> (unit, n) with unit day or month."""
    m = _EVERY_RE.match(str(text).strip())
    if not m:
        die("--every is day, week, fortnight, month, or a count such as 2w or 3d")
    n = int(m.group(1) or 1)
    unit = m.group(2).lower()
    if n < 1:
        die("--every must be at least one")
    if unit == "fortnight":
        return "day", 14 * n
    if unit.startswith("w"):
        return "day", 7 * n
    if unit.startswith("d"):
        return "day", n
    return "month", n


def _add_months(d, n):
    from .service import add_months
    return add_months(d, n)


def occurrences(when, src, start, unit, step, count):
    """Wall-clock occurrences in the source zone: [(aware datetime, note)]."""
    tokens = when.lower().split()
    if len(tokens) == 2 and tokens[0] in DAY_NAMES:
        h, mi = parse_clock(tokens[1])
        first = start + timedelta(days=(DAY_NAMES[tokens[0]] - start.weekday()) % 7)
    elif len(tokens) == 2:
        day = chrono.parse_date(tokens[0], start)
        if day is None:
            die("the event is a weekday and a time (\"sat 12:00\"), a date and a time (\"2026-11-14 12:00\"), or a time alone")
        h, mi = parse_clock(tokens[1])
        first = day
    elif len(tokens) == 1:
        h, mi = parse_clock(tokens[0])
        first = start
    else:
        die("the event is a weekday and a time (\"sat 12:00\"), a date and a time (\"2026-11-14 12:00\"), or a time alone")
    out = []
    for n in range(count):
        day = first + timedelta(days=step * n) if unit == "day" else _add_months(first, step * n)
        out.append(chrono.localize(datetime(day.year, day.month, day.day, h, mi), src))
    return out


def cmd_series(a):
    source = a.source or chrono.home_label()
    src = chrono.get_tz(source)
    if not 1 <= a.count <= MAX_COUNT:
        die("--count is 1 to %d" % MAX_COUNT)
    unit, step = parse_every(a.every)
    today = chrono.now_in(src).date()
    start = chrono.parse_date(a.start, today) if a.start else today
    if start is None:
        die("--start is a date: YYYY-MM-DD")
    rows = occurrences(" ".join(a.when), src, start, unit, step, a.count)
    targets = a.to or [z for z in chrono.default_zones() if chrono.zone_key(z) != chrono.zone_key(source)][:1] or ["utc"]
    tzs = [chrono.get_tz(z) for z in targets]
    labels = [chrono.zone_label(z) for z in targets]
    src_label = chrono.zone_label(source)
    what = {("day", 1): "every day", ("day", 7): "every week", ("day", 14): "every two weeks", ("month", 1): "every month"}.get(
        (unit, step), "every %d %ss" % (step, unit))
    rec("SERIES", "%s%s, %s in %s time; %d occurrence%s from %s" % (
        (a.title + ": ") if a.title else "", " ".join(a.when), what, src_label, len(rows), "" if len(rows) == 1 else "s",
        rows[0][0].date().isoformat()))
    out, odd_rows, notes = [], [], []
    usual = {}
    for when, note in rows:
        u = chrono.to_utc(when)
        line = ["%s %s" % (when.strftime("%Y-%m-%d"), chrono.fmt_short(when)), src_label]
        flags = []
        for tz, label in zip(tzs, labels):
            local = u.astimezone(tz)
            day = (local.date() - when.date()).days
            line += ["%s%s" % (chrono.fmt_short(local), "" if day == 0 else " (%+d day)" % day), label]
            odd = chrono.odd_gap(src, tz, u)
            if odd:
                flags.append("%s is %s, not the usual %s" % (
                    label, chrono.fmt_delta_h(odd[0]), " or ".join(sorted(set(chrono.fmt_delta_h(x) for x in odd[1])))))
            usual.setdefault(label, []).append(local.strftime("%H:%M"))
        if flags:
            odd_rows.append(when.strftime("%Y-%m-%d"))
        line.append(("<- " + "; ".join(flags)) if flags else "")
        out.append(line)
        if note and note not in notes:
            notes.append(note)
    table(out, indent=2)
    for label in labels:
        clocks = usual[label]
        common = max(set(clocks), key=clocks.count)
        others = sorted(set(c for c in clocks if c != common))
        if others:
            rec("SHIFT", "in %s time it is usually %s, but %s on %d of these" % (label, common, " or ".join(others), len(clocks) - clocks.count(common)))
    if odd_rows:
        rec("GAP WEEKS", "%s: the two zones are out of step, because their clocks change on different dates" % ", ".join(odd_rows))
    elif not any(len(set(usual[label])) > 1 for label in labels):
        rec("STEADY", "the same local time on every one of these")
    for n in notes:
        rec("NOTE", n)
    if a.ics:
        dur = parse_duration(a.dur, default_unit="m") if a.dur else 0
        title = a.title or "%s %s" % (" ".join(a.when), src_label)
        entries = []
        for when, _ in rows:
            end = chrono.add(when, dur) if dur > 0 else None
            entries.append(ical.event(title, when, end, description="%s in %s time." % (chrono.fmt_dt(when), src_label),
                                      alarm=ical.alarm_of(a)))
        ical.deliver(a, entries, "series-%s" % rows[0][0].date().isoformat())


def cmd_session(a):
    home = chrono.home_tz()
    now = chrono.now_in(home)
    if not a.since:
        rec("SESSION", "no start given. 'boot' prints a SESSION stamp at the start of a conversation: pass it back as --since")
        rec("NOW", "%s [measured: this machine's clock]" % chrono.fmt_dt(now))
        return
    stamp = a.since.strip().rstrip("Zz")
    try:
        began = datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=chrono.UTC)
    except ValueError:
        die("--since takes the stamp 'boot' printed, such as 2026-11-10T13:30Z")
    ran = (chrono.to_utc(now) - began).total_seconds()
    if ran < -60:
        die("that stamp is in the future: pass the SESSION stamp from this conversation's 'boot'")
    ran = max(0.0, ran)
    limit = parse_duration(a.long, default_unit="h")
    rec("SESSION", "running %s, since %s [measured: this machine's clock]" % (fmt_hm(ran / 3600.0), chrono.fmt_dt(began.astimezone(home))))
    rec("NOW", chrono.fmt_dt(now))
    long_run = ran >= limit
    late = chrono.home_is_set() and (now.hour >= 23 or now.hour < 5)
    rec("LONG", ("yes: past %s" % fmt_hm(limit / 3600.0)) if long_run else "no (the mark is %s)" % fmt_hm(limit / 3600.0))
    if chrono.home_is_set():
        rec("LATE", ("yes: %s at home" % now.strftime("%H:%M")) if late else "no (%s at home)" % now.strftime("%H:%M"))
    if long_run or late:
        rec("SAY", "one fatigue note, plainly, if you have not given one this session; then respect the answer")
    else:
        more("nothing to say about it yet")


def register(sub):
    p = command(sub, "clock", "series", cmd_series,
                "an event that repeats in another zone, as local time week by week, with the out-of-step weeks flagged",
                ["series sat 12:00 --from slt --count 8", "series sat 12:00 --from slt --start 2027-03-01 --count 6 --to home chicago",
                 'series "2026-11-12 19:30" --from chicago --every 2w --count 4 --title "Call" --dur 45m --ics auto',
                 "series 09:00 --from tokyo --every day --count 5"])
    p.add_argument("when", nargs="+", help="a weekday and a time (sat 12:00), a date and a time, or a time alone, in the event's own zone")
    p.add_argument("--from", dest="source", help="the zone the event is fixed in (default home)")
    p.add_argument("--to", nargs="+", help="zones to show it in (default: home, or your first other clock)")
    p.add_argument("--every", default="week", help="day, week, fortnight, month, or a count such as 2w or 3d (default week)")
    p.add_argument("--count", type=int, default=8, help="how many occurrences (default 8)")
    p.add_argument("--start", help="first date to consider (default today)")
    p.add_argument("--title", help="what it is, for the heading and the calendar")
    p.add_argument("--dur", help="how long it lasts, for the calendar file (45m, 1h30m)")
    ical.add_option(p, "every occurrence")

    p = command(sub, "desk", "session", cmd_session, "how long this conversation has run, from the stamp boot printed, and whether to say so",
                ["session --since 2026-11-10T09:15Z", "session --since 2026-11-10T13:00Z --long 2h", "session"])
    p.add_argument("--since", help="the SESSION stamp from this conversation's boot")
    p.add_argument("--long", default="3h", help="how long counts as a long session (default 3h)")
