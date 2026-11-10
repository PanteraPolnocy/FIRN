"""Calendar files (iCalendar, RFC 5545) for journeys, meetings and service dates.

Times are written in UTC, so every calendar shows them in its owner's own zone and no zone table has to
travel with the file. An all-day entry (a service date) carries a date and no time. Plain text, no network.
"""
import os
from datetime import date, datetime, timedelta

from . import chrono
from .core import die, driver, more, out_folder, rec

PRODID = "-//FIRN-01//Project Chronos field tools//EN"
LINE_OCTETS = 75


def _esc(text):
    """Escape a text value: backslash, semicolon, comma and line breaks."""
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold_line(line):
    """Fold one content line at 75 octets, never inside a character. Returns the physical lines."""
    if len(line.encode("utf-8")) <= LINE_OCTETS:
        return [line]
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > LINE_OCTETS:
            out.append(cur)
            cur, size = " " + ch, 1 + n
        else:
            cur += ch
            size += n
    out.append(cur)
    return out


def _stamp(dt, up=False):
    """A moment as UTC, to the whole minute: a start is rounded down and an end up, so nobody leaves late."""
    u = chrono.to_utc(dt)
    if u.second or u.microsecond:
        u = u.replace(second=0, microsecond=0) + (timedelta(minutes=1) if up else timedelta(0))
    return u.strftime("%Y%m%dT%H%M%SZ")


def _is_day(value):
    return isinstance(value, date) and not isinstance(value, datetime)


def _trigger(before):
    """A timedelta before the start, as an iCalendar duration: -PT30M, -PT2H, -P14D."""
    secs = int(round(before.total_seconds()))
    if secs <= 0:
        return None
    if secs % 86400 == 0:
        return "-P%dD" % (secs // 86400)
    if secs % 3600 == 0:
        return "-PT%dH" % (secs // 3600)
    return "-PT%dM" % max(1, int(round(secs / 60.0)))


def event(summary, start, end=None, location="", description="", alarm=None):
    """One calendar entry. start and end are aware datetimes, or plain dates for an all-day entry.
    With no end, a timed entry is a moment and an all-day entry is that one day.
    alarm is a timedelta before the start, or None."""
    if _is_day(start) != (_is_day(end) if end is not None else _is_day(start)):
        die("a calendar entry cannot mix a date with a time")
    if not _is_day(start) and start.tzinfo is None:
        die("a calendar entry needs a time with a zone")
    return {"summary": summary, "start": start, "end": end, "location": location, "description": description, "alarm": alarm}


def _sort_key(ev):
    s = ev["start"]
    if _is_day(s):
        return datetime(s.year, s.month, s.day, tzinfo=chrono.UTC)
    return chrono.to_utc(s)


def build(events, now=None):
    """The text of a calendar file holding these entries, lines folded and ended as the format requires."""
    now = now or chrono.now_in(chrono.UTC)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:" + PRODID, "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for ev in sorted(events, key=_sort_key):
        start, end = ev["start"], ev["end"]
        if _is_day(start):
            s_txt = "DTSTART;VALUE=DATE:" + start.strftime("%Y%m%d")
            last = end if end is not None else start
            e_txt = "DTEND;VALUE=DATE:" + (last + timedelta(days=1)).strftime("%Y%m%d")
            key = start.isoformat()
        else:
            s_txt = "DTSTART:" + _stamp(start)
            e_txt = ("DTEND:" + _stamp(end, up=True)) if end is not None and chrono.to_utc(end) > chrono.to_utc(start) else None
            key = _stamp(start)
        import hashlib
        uid = hashlib.sha1(("%s|%s" % (ev["summary"], key)).encode("utf-8")).hexdigest()[:24]
        lines += ["BEGIN:VEVENT", "UID:%s@firn-01" % uid, "DTSTAMP:" + _stamp(now), s_txt]
        if e_txt:
            lines.append(e_txt)
        lines.append("SUMMARY:" + _esc(ev["summary"]))
        if ev["location"]:
            lines.append("LOCATION:" + _esc(ev["location"]))
        if ev["description"]:
            lines.append("DESCRIPTION:" + _esc(ev["description"]))
        trig = _trigger(ev["alarm"]) if ev["alarm"] else None
        if trig:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + _esc(ev["summary"]), "TRIGGER:" + trig, "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    physical = []
    for line in lines:
        physical.extend(fold_line(line))
    return "\r\n".join(physical) + "\r\n"


def add_option(p, what, alarm=True):
    p.add_argument("--ics", metavar="WHERE",
                   help="also write %s as a calendar file: 'auto' (the outputs folder if there is one, else the current folder), "
                        "a folder, or a name ending .ics" % what)
    if alarm:
        p.add_argument("--alarm", type=int, default=30, metavar="MIN",
                       help="minutes of warning in the calendar file before setting off (default 30; 0 for none)")


def alarm_of(a):
    mins = getattr(a, "alarm", 0) or 0
    if mins < 0:
        die("--alarm is minutes before the entry: zero or more")
    return timedelta(minutes=mins) if mins else None


def deliver(a, events, stem, estimate=False):
    """Write the calendar file if --ics was given, and say where it is. Returns the path, or None."""
    where = getattr(a, "ics", None)
    if not where:
        return None
    if not events:
        die("there is nothing to put in a calendar")
    if where.lower().endswith(".ics"):
        path = where
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            die("no such folder for the calendar file: %s" % folder)
    else:
        folder = out_folder(where)
        if not folder:
            die("no such folder for the calendar file: %s (use 'auto', a folder, or a name ending .ics)" % where)
        path = os.path.join(folder, "firn-%s.ics" % stem)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(build(events))
    except OSError as e:
        die("could not write the calendar file %s: %s" % (path, e.strerror or e))
    rec("CALENDAR", path)
    more("%d entr%s; times are stored in UTC, so each calendar shows them in its own zone" % (
        len(events), "y" if len(events) == 1 else "ies"))
    if estimate:
        more("it holds estimated times: say so when you hand it over")
    rec("NEXT", "present that file to %s (attach or link it); if this environment cannot show files, say so in one line" % driver())
    return path
