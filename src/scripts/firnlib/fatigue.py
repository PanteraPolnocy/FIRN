"""Fatigue: the clock arithmetic behind 'route --fatigue' and 'trip --fatigue'.

Three things tire a driver: the hour, the time at the wheel and the time awake. This module works out where a
planned journey meets each of them, and every line it prints names the published figure it leans on.
It plans a journey. It cannot know how anyone slept, and it does not pretend to.
"""
import re
from datetime import datetime, timedelta

from . import chrono
from .core import die, fmt_hm, more, num, parse_clock, rec, trim, unprotect

DRIVEN = ("car", "motorway", "city")

# The Highway Code (Great Britain), rule 91: avoid long journeys between midnight and 6 am, when natural alertness
# is at its lowest; take a break of at least 15 minutes after every two hours of driving; if sleepy, stop in a safe
# place; two cups of caffeinated coffee and a short nap (at least 15 minutes) are the most effective stopgap.
LOW_HOURS = "00:00-06:00"
BREAK_EVERY_H, BREAK_MIN = 2.0, 15
RULE_91 = "Highway Code rule 91"
# Regulation (EC) No 561/2006, article 6(1): a professional driver's daily driving time shall not exceed nine hours.
DAY_AT_WHEEL_H = 9.0
EU_561 = "Regulation (EC) No 561/2006, art. 6"
# NIOSH (United States): after 17 hours awake, impairment is like a blood alcohol content of 0.05%; after 24 hours, 0.10%.
AWAKE_H, AWAKE_LONG_H = 17.0, 24.0
# A wait this long between two legs of a trip is taken as a chance to sleep, and the count of hours awake starts again.
REST_H = 7.0

_WINDOW_RE = re.compile(r"\s*(\d{1,2}[:.]\d{2})\s*-\s*(\d{1,2}[:.]\d{2})\s*")


def parse_window(text):
    """'00:00-06:00' -> (first minute, last minute) of the day. The window may run through midnight: 22:30-05:00."""
    m = _WINDOW_RE.fullmatch(unprotect(str(text)))
    if not m:
        die("--low-hours is two clock times: %s" % LOW_HOURS)
    (h1, m1), (h2, m2) = parse_clock(m.group(1)), parse_clock(m.group(2))
    start, end = h1 * 60 + m1, h2 * 60 + m2
    length = (end - start) % 1440
    if length == 0:
        die("--low-hours needs two different times: %s" % LOW_HOURS)
    if length > 12 * 60:
        die("--low-hours of more than 12 hours is most of the day: give the hours you would normally be asleep")
    return start, end


def label(win):
    return "%02d:%02d-%02d:%02d" % (win[0] // 60, win[0] % 60, win[1] // 60, win[1] % 60)


def basis(win):
    """The tag for a line about the low hours: the published window, or the driver's own."""
    return RULE_91 if label(win) == LOW_HOURS else "low hours as given"


def length_h(win):
    return ((win[1] - win[0]) % 1440) / 60.0


def zone_name(tz, at):
    """A zone as text: its key where it has one, otherwise its offset at that moment."""
    return getattr(tz, "key", None) or chrono.fmt_offset(at.astimezone(tz))


def spans(start, end, tz, win):
    """Every stretch between two moments that falls inside the low hours on the clock of tz:
    [(from, to, window start, window end)], all in UTC. Clock changes are honoured: the window is taken from
    the wall clock, so on the night the clocks go back it lasts an hour longer."""
    start_u, end_u = chrono.to_utc(start), chrono.to_utc(end)
    out = []
    day = start_u.astimezone(tz).date() - timedelta(days=1)
    last = end_u.astimezone(tz).date() + timedelta(days=1)
    while day <= last:
        nxt = day + timedelta(days=1) if win[1] <= win[0] else day
        a, _ = chrono.localize(datetime(day.year, day.month, day.day, win[0] // 60, win[0] % 60), tz)
        b, _ = chrono.localize(datetime(nxt.year, nxt.month, nxt.day, win[1] // 60, win[1] % 60), tz)
        w0, w1 = chrono.to_utc(a), chrono.to_utc(b)
        lo, hi = max(w0, start_u), min(w1, end_u)
        if hi > lo:
            out.append((lo, hi, w0, w1))
        day += timedelta(days=1)
    return out


def minutes(found):
    return sum((hi - lo).total_seconds() for lo, hi, _, _ in found) / 60.0


def low_minutes(dep, total_h, win):
    """Minutes of a journey of total_h hours, starting at dep, that fall in the low hours on the clock it starts by."""
    start = chrono.to_utc(dep)
    return minutes(spans(start, start + timedelta(hours=total_h), dep.tzinfo, win))


def _at(legs, f):
    """(leg number, km from the start) a fraction f of the way along, by distance."""
    total = sum(leg[3] for leg in legs)
    target, acc = f * total, 0.0
    for n, leg in enumerate(legs, 1):
        if target <= acc + leg[3] + 1e-9 or n == len(legs):
            return n, target
        acc += leg[3]
    return len(legs), target


def _sleepy():
    more("if sleepy, stop somewhere safe: coffee and a nap of 15 minutes or more buy a little time, "
         "not a night's sleep [%s; NIOSH]" % RULE_91)


def _stretch(lo, hi, tz):
    """'00:00-06:00 Sun' for a stretch, on the clock of tz; the day is the one it starts on."""
    a, b = lo.astimezone(tz), hi.astimezone(tz)
    return "%s-%s %s" % (a.strftime("%H:%M"), b.strftime("%H:%M"), chrono.DAYS[a.weekday()])


def route_report(legs, dep, total_h, drive_h, every, brk_min, win, fixed_arrival=False):
    """Print the fatigue lines for a journey driven in one go; return the minutes of it that fall in the low hours.
    legs are route's own: (from, to, straight km, travel km, hours, bearing, tag)."""
    tz = dep.tzinfo
    start = chrono.to_utc(dep)
    end = start + timedelta(hours=total_h)
    found = spans(start, end, tz, win)
    low = minutes(found)
    name = label(win)
    if not found:
        rec("FATIGUE", "clear of the low hours, %s on the clock at the start [derived; %s]" % (name, basis(win)))
    else:
        whole = low >= total_h * 60.0 - 0.5
        rec("FATIGUE", "%s journey falls in the low hours: %s on the clock at the start (%s)%s [derived; %s]" % (
            "all %s of this" % fmt_hm(total_h) if whole else "%s of this %s" % (fmt_hm(low / 60.0), fmt_hm(total_h)),
            name, zone_name(tz, start), ", when alertness is lowest" if label(win) == LOW_HOURS else "", basis(win)))
        total_km = sum(leg[3] for leg in legs)
        span_s = (end - start).total_seconds()
        for lo, hi, _, _ in found:
            if whole:
                rec("LOW HOURS", "%s, from the first kilometre to the last" % _stretch(lo, hi, tz))
                continue
            n1, km1 = _at(legs, (lo - start).total_seconds() / span_s)
            n2, km2 = _at(legs, (hi - start).total_seconds() / span_s)
            where = "" if len(legs) == 1 else " on leg %d" % n1 if n1 == n2 else " on legs %d to %d" % (n1, n2)
            rec("LOW HOURS", "%s%s, about km %s to %s of %s" % (_stretch(lo, hi, tz), where, num(km1), num(km2), num(total_km)))
        if fixed_arrival:
            more("the arrival is fixed, so the hour is too: sleep beforehand, or let someone rested drive")
        elif total_h <= 24.0 - length_h(win):
            w0, w1 = found[0][2], found[0][3]
            leave = (w0 - timedelta(hours=total_h)).astimezone(tz)
            more("to stay clear of them: leave by %s and be there before %s, or set off at %s or later" % (
                chrono.fmt_short(leave), w0.astimezone(tz).strftime("%H:%M"), chrono.fmt_short(w1.astimezone(tz))))
        else:
            more("too long to fit between one night's low hours and the next: break it with an overnight stop")
        _sleepy()
    if drive_h > DAY_AT_WHEEL_H:
        rec("AT WHEEL", "%s of driving with no night's stop: more than the %s h a professional driver may drive in a day "
                        "in the EU [%s]. Split it, or share the driving" % (fmt_hm(drive_h), trim(DAY_AT_WHEEL_H, 0), EU_561))
    if drive_h > BREAK_EVERY_H and (every <= 0 or every > BREAK_EVERY_H + 1e-9 or brk_min < BREAK_MIN):
        rec("BREAKS", "thinner than advised: at least %d minutes after every %s hours of driving [%s]" % (
            BREAK_MIN, trim(BREAK_EVERY_H, 0), RULE_91))
    return low


def trip_report(drives, set_off, origin, resets, body_tz, win):
    """Print the fatigue lines for a trip.

    drives   [(what, start, end)] the stretches someone drives themselves, aware datetimes, in order
    set_off  when the travelling began (aware); origin says what that moment was, e.g. 'you left Home'
    resets   [(moment, where)] waits long enough to sleep in; hours awake are counted from the latest one
    body_tz  the zone the traveller's body is still keeping: where the trip started
    """
    name = label(win)
    if not drives:
        rec("FATIGUE", "nothing to check: nobody drives on this trip as given (add --home or --onward, or mark a leg 'drive')")
        return
    rec("FATIGUE", "%d drive%s checked on the body clock, the zone the trip starts in (%s): low hours %s [derived; %s]" % (
        len(drives), "" if len(drives) == 1 else "s", zone_name(body_tz, set_off), name, basis(win)))
    any_low = False
    worst = None
    for what, start, end in drives:
        start, end = start.replace(second=0, microsecond=0), end.replace(second=0, microsecond=0)     # as the clock shows them
        b0 = start.astimezone(body_tz)
        low = minutes(spans(start, end, body_tz, win))
        length = (chrono.to_utc(end) - chrono.to_utc(start)).total_seconds() / 60.0
        local = ""
        if start.utcoffset() != b0.utcoffset():
            local = " (%s-%s local)" % (start.strftime("%H:%M"), end.strftime("%H:%M"))
        if low <= 0:
            verdict = "clear"
        elif low >= length - 0.5:
            verdict = "all %s of it in the low hours" % fmt_hm(length / 60.0)
            any_low = True
        else:
            verdict = "%s of its %s in the low hours" % (fmt_hm(low / 60.0), fmt_hm(length / 60.0))
            any_low = True
        more("%s: %s body clock%s, %s" % (what, _stretch(start, end, body_tz), local, verdict))
        since, why = set_off, origin
        for moment, where in resets:
            if chrono.to_utc(moment) <= chrono.to_utc(start) and chrono.to_utc(moment) > chrono.to_utc(since):
                since, why = moment, "the long stop at %s" % where
        awake = (chrono.to_utc(end) - chrono.to_utc(since)).total_seconds() / 3600.0
        if awake >= AWAKE_H and (worst is None or awake > worst[0]):
            worst = (awake, what, why)
    if worst:
        awake, what, why = worst
        if awake >= AWAKE_LONG_H:
            like = "after %s h awake a driver is about as slowed as at 0.10%% blood alcohol" % trim(AWAKE_LONG_H, 0)
        else:
            like = "after %s h awake a driver is about as slowed as at 0.05%% blood alcohol" % trim(AWAKE_H, 0)
        rec("AWAKE", "%s ends %s after %s, and you were up before that: %s [NIOSH]" % (what, fmt_hm(awake), why, like))
        more("sleep on the way counts in your favour; a lift, a taxi or a night's sleep before that drive counts for more")
    if any_low:
        _sleepy()
