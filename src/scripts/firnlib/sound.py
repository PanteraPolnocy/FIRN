"""Sound: the note an engine sings, the speed in a passing pitch, a soundtrack that ends as you arrive,
how long a level is safe to listen to, and the notes a cabin makes boom.

pitch     a frequency as a musical note; an engine's firing note from its revs; the interval between two
doppler   the speed of something from the drop in its pitch as it passes, or the other way about
playlist  pick and order tracks so the last one ends as the journey does
listen    a sound level and a time against the published limits for a day and for a week
cabin     the standing waves of a box the size of a cabin, as frequencies and as notes

The limits in 'listen' are the published ones, named where they are printed. They were written for workplaces
and for headphones, and they are used here as yardsticks: this is arithmetic, not a hearing test.
"""
import math
import re

from .core import command, die, fmt_dur, fold, more, num, parse_duration, parse_laptime, rec, table, trim, unprotect

NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
INTERVALS = ("a unison", "a semitone", "a tone", "a minor third", "a major third", "a fourth", "a tritone", "a fifth",
             "a minor sixth", "a major sixth", "a minor seventh", "a major seventh", "an octave")
INTERVAL_NAMES = {"semitone": 1, "tone": 2, "minor_third": 3, "major_third": 4, "fourth": 5, "tritone": 6, "fifth": 7,
                  "minor_sixth": 8, "major_sixth": 9, "minor_seventh": 10, "major_seventh": 11, "octave": 12}
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d{1,2})$")

# Published limits. Each is quoted with its source where it is printed.
NIOSH_LEVEL, NIOSH_HOURS, NIOSH_EXCHANGE = 85.0, 8.0, 3.0      # NIOSH recommended exposure limit (1998)
EU_LOWER, EU_UPPER, EU_LIMIT = 80.0, 85.0, 87.0                # Directive 2003/10/EC, Article 3: L_EX,8h in dB(A)
WHO_LEVEL, WHO_SENSITIVE, WHO_HOURS = 80.0, 75.0, 40.0         # ITU-T H.870 (2022), modes 1 and 2: a week's listening
P0 = 20e-6                                                     # reference sound pressure, Pa


# ---- notes

def speed_of_sound(temp_c):
    if temp_c <= -273.15:
        die("that is colder than anything gets")
    return 331.3 * math.sqrt(1.0 + temp_c / 273.15)


def note_of(hz, a4=440.0):
    """(name, cents off) for a frequency: the nearest note of the twelve, A4 at the pitch given."""
    n = 12.0 * math.log(hz / a4, 2) + 57.0
    nearest = int(math.floor(n + 0.5))
    cents = int(round((n - nearest) * 100.0))
    if cents == 50:
        nearest, cents = nearest + 1, -50
    return "%s%d" % (NOTES[nearest % 12], nearest // 12), cents


def note_text(hz, a4=440.0):
    name, cents = note_of(hz, a4)
    return name if cents == 0 else "%s %+d cent%s" % (name, cents, "" if abs(cents) == 1 else "s")


def hz_of(name, a4=440.0):
    """A note name such as A4, C#3 or Eb2 as a frequency, or None if it is not one."""
    m = _NOTE_RE.match(str(name).strip())
    if not m:
        return None
    # counted in semitones from C0, so that B#3 lands on C4 and Cb4 on B3 without special cases
    semitone = STEPS[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)] + 12 * int(m.group(3))
    return a4 * 2.0 ** ((semitone - 57) / 12.0)


def parse_pitch(text, a4=440.0):
    """'440', '440hz', 'A4' -> Hz."""
    t = unprotect(str(text)).strip()
    hz = hz_of(t, a4)
    if hz is None:
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(?:hz)?$", t, re.I)
        if not m:
            die("'%s' is neither a frequency in Hz nor a note such as A4, C#3 or Eb2" % text)
        hz = float(m.group(1))
    if not 1.0 <= hz <= 100000.0:
        die("a frequency between 1 Hz and 100 kHz, please: '%s'" % text)
    return hz


def interval_text(semitones):
    """7.02 -> 'a fifth'; 15.1 -> 'an octave and a minor third'."""
    whole = int(round(abs(semitones)))
    if whole <= 12:
        return INTERVALS[whole]
    octaves, rest = divmod(whole, 12)
    head = "an octave" if octaves == 1 else "%d octaves" % octaves
    return head if rest == 0 else "%s and %s" % (head, INTERVALS[rest])


def _hz(hz):
    return trim(hz, 1 if hz >= 100 else 2)


def cmd_pitch(a):
    a4 = a.a4
    if not 380.0 <= a4 <= 480.0:
        die("--a4 is the pitch of the A above middle C, somewhere near 440 Hz")
    if a.rpm or a.note:
        if a.values:
            die("give revs (--rpm), or frequencies and notes, not both")
        if a.order is not None:
            if a.order <= 0:
                die("--order is how many times it happens in one turn, more than zero")
            per_turn, what = a.order, "%s to a turn" % trim(a.order, 2)
            formula = "rpm / 60 x %s" % trim(a.order, 2)
        else:
            if a.cyl is None or a.cyl < 1:
                die("an engine's note needs its cylinders: --cyl 4 (or --order N for anything else that turns)")
            if a.stroke not in (2, 4):
                die("--stroke is 4 or 2")
            per_turn = a.cyl / 2.0 if a.stroke == 4 else float(a.cyl)
            what = "%d cylinder%s, %s-stroke" % (a.cyl, "" if a.cyl == 1 else "s", "four" if a.stroke == 4 else "two")
            formula = "rpm / 60 x cylinders%s" % (" / 2" if a.stroke == 4 else "")
        if a.note:
            hz = parse_pitch(a.note, a4)
            rec("NOTE", "%s is %s Hz" % (note_text(hz, a4), _hz(hz)))
            rec("REVS", "%s rpm sings it: %s [derived: note x 60 / %s]" % (num(hz * 60.0 / per_turn), what, trim(per_turn, 2)))
            return
        if len(a.rpm) > 2 or any(r <= 0 for r in a.rpm):
            die("--rpm is one engine speed, or two for the interval between them")
        rec("TURNING", "%s, %s rpm" % (what, " and ".join(num(r) for r in a.rpm)))
        tones = []
        for r in a.rpm:
            hz = r / 60.0 * per_turn
            tones.append(hz)
            rec("FIRING" if a.order is None else "SINGS", "%s rpm: %s Hz, %s [derived: %s]" % (num(r), _hz(hz), note_text(hz, a4), formula))
        if a.order is None and len(a.rpm) == 1:
            turn = a.rpm[0] / 60.0
            more("the crankshaft itself turns at %s Hz (%s): the rumble under the note" % (_hz(turn), note_text(turn, a4)))
        if len(tones) == 2:
            semis = 12.0 * math.log(tones[1] / tones[0], 2)
            rec("STEP", "%s rpm to %s: the note %s %s semitones, about %s [derived]" % (
                num(a.rpm[0]), num(a.rpm[1]), "falls" if semis < 0 else "rises", trim(abs(semis), 1), interval_text(semis)))
        if a.order is None:
            rec("NOTE", "the firing note is the loudest of several an engine makes; the exhaust, the intake and the cylinder layout "
                        "colour it, so two engines on the same note do not sound alike")
        return
    if not a.values:
        die("give a frequency (440), a note (A4), two of them for the interval, or --rpm with --cyl for an engine")
    if len(a.values) > 2:
        die("one value, or two for the interval between them")
    tones = [parse_pitch(v, a4) for v in a.values]
    c = speed_of_sound(a.temp)
    for hz in tones:
        rec("PITCH", "%s Hz is %s; one wave is %s m long in air at %s C [derived]" % (_hz(hz), note_text(hz, a4), trim(c / hz, 2), trim(a.temp, 0)))
    if len(tones) == 2:
        semis = 12.0 * math.log(tones[1] / tones[0], 2)
        rec("INTERVAL", "%s semitone%s %s, about %s; ratio %s [derived]" % (
            trim(abs(semis), 2), "" if trim(abs(semis), 2) == "1" else "s", "up" if semis >= 0 else "down", interval_text(semis),
            trim(max(tones) / min(tones), 3)))
    if abs(a4 - 440.0) > 1e-9:
        rec("TUNING", "A4 = %s Hz, as given" % trim(a4, 1))


# ---- doppler

def _semitones(text):
    t = fold(unprotect(str(text)))
    if t in INTERVAL_NAMES:
        return float(INTERVAL_NAMES[t])
    try:
        return float(t.replace("_", "."))
    except ValueError:
        die("--drop is a number of semitones (2.5), or one of: %s" % ", ".join(k.replace("_", "-") for k in INTERVAL_NAMES))


def cmd_doppler(a):
    from .dynamics import parse_speed
    c = speed_of_sound(a.temp)
    air = "sound at %s m/s in air at %s C" % (trim(c, 0), trim(a.temp, 0))
    ways = sum(1 for x in (a.heard, a.drop, a.speed) if x is not None)
    if ways != 1:
        die("give one of: --heard COMING GOING (two pitches), --drop SEMITONES (how far the pitch fell), or --speed with --hz")
    if a.speed is not None:
        v = parse_speed(a.speed) / 3.6
        if not 0 < v < c:
            die("the speed must be above zero and below the speed of sound (%s km/h here)" % num(c * 3.6))
        f0 = parse_pitch(a.hz, a.a4) if a.hz else 440.0
        coming, going = f0 * c / (c - v), f0 * c / (c + v)
        semis = 12.0 * math.log(coming / going, 2)
        rec("SOURCE", "%s Hz (%s) passing at %s km/h%s" % (_hz(f0), note_text(f0, a.a4), trim(v * 3.6, 0), "" if a.hz else " [a 440 Hz tone, since none was given]"))
        rec("COMING", "%s Hz, %s [derived]" % (_hz(coming), note_text(coming, a.a4)))
        rec("GOING", "%s Hz, %s [derived]" % (_hz(going), note_text(going, a.a4)))
        rec("DROP", "%s semitones as it passes, about %s [%s]" % (trim(semis, 2), interval_text(semis), air))
        return
    if a.heard is not None:
        coming, going = parse_pitch(a.heard[0], a.a4), parse_pitch(a.heard[1], a.a4)
        if coming <= going:
            die("the pitch coming towards you is the higher of the two: give it first")
        semis = 12.0 * math.log(coming / going, 2)
        rec("HEARD", "%s Hz coming (%s), %s Hz going (%s): a drop of %s semitones, about %s" % (
            _hz(coming), note_text(coming, a.a4), _hz(going), note_text(going, a.a4), trim(semis, 2), interval_text(semis)))
    else:
        semis = _semitones(a.drop)
        if not 0 < semis <= 36:
            die("--drop is how far the pitch fell, in semitones: more than zero, and three octaves at the very most")
        coming = going = None
        rec("HEARD", "a drop of %s semitones as it passed, about %s" % (trim(semis, 2), interval_text(semis)))

    def speed_for(s):
        ratio = 2.0 ** (s / 12.0)
        return c * (ratio - 1.0) / (ratio + 1.0)

    v = speed_for(semis)
    rec("SPEED", "%s km/h (%s m/s) [derived; %s]" % (trim(v * 3.6, 0), trim(v, 1), air))
    if coming:
        f0 = 2.0 * coming * going / (coming + going)
        rec("SOURCE", "%s Hz as it was made, %s [derived]" % (_hz(f0), note_text(f0, a.a4)))
    if a.ear < 0:
        die("--ear is how far out the ear might be, in semitones")
    if a.ear:
        lo, hi = speed_for(max(0.01, semis - a.ear)), speed_for(semis + a.ear)
        off = "half a semitone" if a.ear == 0.5 else "a semitone" if a.ear == 1 else "%s semitones" % trim(a.ear, 2)
        rec("BAND", "%s to %s km/h if the ear is %s out either way" % (trim(lo * 3.6, 0), trim(hi * 3.6, 0), off))
    rec("NOTE", "worked out from what was heard, so only as good as the ear: an estimate, never a measurement of anyone's speed. "
                "It assumes you stood still and it passed close by; from a moving car the figure is nearer the two speeds added")


# ---- playlist

_TRACK_TAIL = re.compile(r"(\d+:\d{2}(?::\d{2})?)\s*$")


def _track(text, n):
    """'3:45', 'Name=3:45', 'Name - 3:45' -> (name, seconds)."""
    t = str(text).strip()
    name, sep, dur = t.rpartition("=")
    if not sep:
        m = _TRACK_TAIL.search(t)
        if m and m.start() > 0:
            name, dur = t[:m.start()].rstrip(" -\t|,;"), m.group(1)
        else:
            name, dur = "", t
    dur = dur.strip()
    try:
        secs = parse_laptime(dur) if re.match(r"^\d+(:\d{1,2}){1,2}(\.\d+)?$", dur) else parse_duration(dur, default_unit="s")
    except Exception:
        die("track %d: '%s' is not a length (use 3:45, 1:02:10 or 225s; a name goes in front: \"Name=3:45\")" % (n, text))
    secs = int(round(secs))
    if not 1 <= secs <= 12 * 3600:
        die("track %d: a length between one second and twelve hours, please: '%s'" % (n, text))
    return name.strip() or "track %d" % n, secs


def pick_tracks(lengths, target):
    """The tracks whose lengths add up as near to the target as they can without passing it.
    Among equal totals the earlier tracks are kept. Returns (indexes in order, total)."""
    if target <= 0:
        return [], 0
    mask = (1 << (target + 1)) - 1
    reach = [1]                                  # bit s is set when a total of s can be made from the tracks so far
    for d in lengths:
        reach.append((reach[-1] | (reach[-1] << d)) & mask)
    total = reach[-1].bit_length() - 1
    chosen, s = [], total
    for i in range(len(lengths) - 1, -1, -1):
        if not (reach[i] >> s) & 1:              # this total cannot be made without track i
            chosen.append(i)
            s -= lengths[i]
    return sorted(chosen), total


def _clock(seconds):
    s = int(round(seconds))
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


def _mmss(seconds):
    s = int(round(seconds))
    return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60) if s >= 3600 else "%d:%02d" % (s // 60, s % 60)


def cmd_playlist(a):
    raw = list(a.tracks or [])
    if a.file:
        import sys
        try:
            if a.file == "-":
                lines = sys.stdin.read().splitlines()
            else:
                with open(a.file, encoding="utf-8") as f:
                    lines = f.read().splitlines()
        except OSError as e:
            die("cannot read %s: %s" % (a.file, e.strerror or e))
        except UnicodeDecodeError:
            die("%s is not UTF-8 text" % a.file)
        raw += [ln for ln in (x.strip() for x in lines) if ln and not ln.startswith("#")]
    if not raw:
        die("playlist needs tracks: lengths such as 3:45, or \"Name=3:45\", or --file with one to a line")
    if len(raw) > 2000:
        die("two thousand tracks at the most")
    tracks = [_track(t, n) for n, t in enumerate(raw, 1)]
    if a.gap < 0 or a.gap > 600:
        die("--gap is the silence between tracks in seconds, 0 to 600")
    gap = int(round(a.gap))

    # how long there is to fill
    dep = arr = None
    basis = "as given"
    target = None
    if a.route:
        from . import geo
        p1, p2 = geo.parse_point(a.route[0]), geo.parse_point(a.route[1])
        _, km, hours, tag, _ = geo.estimate_leg(p1, p2, a.mode)
        target = hours * 3600.0
        basis = "%s to %s, %s%s km %s [%s]" % (p1[0], p2[0], "~" if tag == "estimate" else "", num(km),
                                              "by " + a.mode if a.mode != "car" else "by road", tag)
    if a.length:
        if target is not None:
            die("give --for or --route, not both")
        target = parse_duration(a.length, default_unit="m")
    chrono = None
    if a.depart or a.arrive:
        from . import chrono
        tz = chrono.home_tz()
        if a.depart:
            dep, _ = chrono.parse_when(a.depart, tz)
        if a.arrive:
            arr, _ = chrono.parse_when(a.arrive, tz)
        if dep and arr:
            if target is not None:
                die("--depart with --arrive already says how long: leave out --for and --route")
            target = (chrono.to_utc(arr) - chrono.to_utc(dep)).total_seconds()
            basis = "from the two times given"
        elif target is not None:
            if dep:
                arr = chrono.add(dep, target)
            else:
                dep = chrono.add(arr, -target)
    if target is None:
        die("how long is the journey? --for 1h52m, --route FROM TO, or --depart with --arrive")
    target = int(round(target))
    if not 60 <= target <= 24 * 3600:
        die("a journey between a minute and a day, please")
    rec("JOURNEY", "%s to fill (%s)" % (fmt_dur(target), basis))

    def find(name, what):
        want = fold(name)
        hits = [n for n, (nm, _) in enumerate(tracks) if fold(nm) == want] or [n for n, (nm, _) in enumerate(tracks) if want in fold(nm)]
        if not hits and str(name).isdigit() and 1 <= int(name) <= len(tracks):
            hits = [int(name) - 1]
        if len(hits) != 1:
            die("%s '%s' matches %s of the tracks: give its name, or its number in the list" % (what, name, "none" if not hits else "more than one"))
        return hits[0]

    first = find(a.first, "--first") if a.first else None
    last = find(a.last, "--last") if a.last else None
    if first is not None and first == last:
        die("the same track cannot open and close the list")
    everything = sum(d for _, d in tracks) + gap * (len(tracks) - 1)
    if a.all:
        order = [n for n in range(len(tracks)) if n not in (first, last)]
        order = ([first] if first is not None else []) + order + ([last] if last is not None else [])
    else:
        fixed = [n for n in (first, last) if n is not None]
        room = target + gap - sum(tracks[n][1] + gap for n in fixed)
        if room < 0:
            die("the track%s you fixed run%s longer than the journey" % ("s" if len(fixed) > 1 else "", "" if len(fixed) > 1 else "s"))
        free = [n for n in range(len(tracks)) if n not in fixed]
        picked, _ = pick_tracks([tracks[n][1] + gap for n in free], room)
        order = ([first] if first is not None else []) + [free[i] for i in picked] + ([last] if last is not None else [])
    if not order:
        rec("PLAYLIST", "nothing fits: every track is longer than the journey")
        return
    playing = sum(tracks[n][1] for n in order) + gap * (len(order) - 1)
    spare = target - playing
    wait = max(0, spare) if not a.all else 0
    rec("PLAYLIST", "%d of %d tracks, %s of music%s [derived]" % (
        len(order), len(tracks), fmt_dur(playing), " with %d s between tracks" % gap if gap else ""))
    rows, at = [], wait
    over_at = None
    for pos, n in enumerate(order, 1):
        name, secs = tracks[n]
        start = chrono.add(dep, at).strftime("%H:%M:%S") if dep else _clock(at)
        rows.append((pos, start, _mmss(secs), name))
        if over_at is None and at + secs > target:
            over_at = (pos, name, target - at, secs)
        at += secs + gap
    table(rows, header=("#", "starts" if dep else "starts at", "length", "track"), indent=2, right=(0, 2))
    if a.all:
        if spare >= 0:
            rec("ENDS", "%s before you arrive: the list is too short by that much" % fmt_dur(spare))
        else:
            pos, name, into, secs = over_at
            rec("ENDS", "%s after you arrive: you get there %s into track %d%s (%s long)" % (
                fmt_dur(-spare), _mmss(max(0, into)), pos, "" if name == "track %d" % (order[pos - 1] + 1) else ", " + name, _mmss(secs)))
    else:
        if spare == 0:
            rec("ENDS", "as you arrive, to the second: press play as you set off")
        else:
            rec("ENDS", "as you arrive, if the first track starts %s after you set off%s" % (
                fmt_dur(spare), " (at %s)" % chrono.add(dep, spare).strftime("%H:%M:%S") if dep else ""))
        left = [tracks[n][0] for n in range(len(tracks)) if n not in order]
        if left:
            rec("LEFT OUT", "%d: %s%s" % (len(left), ", ".join(left[:8]), " ..." if len(left) > 8 else ""))
        if everything < target:
            more("every track together is %s, which is %s short of the journey: add music, or play it round again" % (
                fmt_dur(everything), fmt_dur(target - everything)))
    if arr:
        rec("ARRIVE", arr.strftime("%Y-%m-%d %H:%M"))
    rec("NOTE", "the road decides when you arrive, not the list. A journey time from 'route' is an estimate unless the leg was "
                "checked on a live map, and traffic moves it either way. Choosing tracks is a job for a passenger, not for whoever is driving")


# ---- listen

def _safe_hours(level):
    """Hours at a level that use one day's allowance by the NIOSH rule."""
    return NIOSH_HOURS / 2.0 ** ((level - NIOSH_LEVEL) / NIOSH_EXCHANGE)


def _week_hours(level, allowance_level):
    """Hours at a level that use one week's allowance by the WHO-ITU rule (equal energy)."""
    return WHO_HOURS / 10.0 ** ((level - allowance_level) / 10.0)


def _span_text(hours):
    if hours >= 24 * 14:
        return "no practical limit"
    if hours < 1.0 / 3600:
        return "under a second"
    return fmt_dur(hours * 3600.0)


def cmd_listen(a):
    week_level = WHO_SENSITIVE if a.sensitive else WHO_LEVEL
    who = "WHO-ITU H.870: %s dB(A) for %s h a week%s" % (trim(week_level, 0), trim(WHO_HOURS, 0), ", the lower allowance, meant for "
                                                        "children and for anyone who wants more margin" if a.sensitive else "")
    niosh = "NIOSH: %s dB(A) for %s h, halved for every %s dB more" % (trim(NIOSH_LEVEL, 0), trim(NIOSH_HOURS, 0), trim(NIOSH_EXCHANGE, 0))
    if a.length:
        if a.spans:
            die("give --for on its own (how loud for that long), or levels with their times")
        hours = parse_duration(a.length, default_unit="m") / 3600.0
        if not 0 < hours <= 24 * 7:
            die("--for is a time, up to a week")
        day = NIOSH_LEVEL + NIOSH_EXCHANGE * math.log(NIOSH_HOURS / hours, 2)
        week = week_level + 10.0 * math.log10(WHO_HOURS / hours)
        rec("TIME", fmt_dur(hours * 3600.0))
        rec("DAY", "%s dB(A) or less for that long stays inside one day's allowance [%s]" % (trim(day, 1), niosh))
        rec("WEEK", "%s dB(A) or less, if it were all the week's listening [%s]" % (trim(week, 1), who))
        _listen_notes()
        return
    if not a.spans:
        die("give a level in dB(A) (listen 94), levels with times (listen 85:2h 94:30m), or --for a time")
    spans = []
    for text in a.spans:
        level, sep, dur = unprotect(str(text)).partition(":")
        try:
            db = float(level.lower().replace("db(a)", "").replace("dba", "").replace("db", ""))
        except ValueError:
            die("'%s' is not a level: use 94 or 94:30m (level:time)" % text)
        if not 30.0 <= db <= 140.0:
            die("a level between 30 and 140 dB(A), please: '%s'" % text)
        spans.append((db, parse_duration(dur, default_unit="m") / 3600.0 if sep else None))
    if any(h is None for _, h in spans):
        if len(spans) > 1:
            die("with several levels each needs its time: 85:2h 94:30m")
        db = spans[0][0]
        rec("LEVEL", "%s dB(A)" % trim(db, 1))
        rec("DAY", "%s at this level uses one day's allowance [%s]" % (_span_text(_safe_hours(db)), niosh))
        rec("WEEK", "%s uses one week's [%s]" % (_span_text(_week_hours(db, week_level)), who))
        _eu_line(db, "kept up for a working day of 8 h, %s dB(A) is")
        _listen_notes()
        return
    total_h = sum(h for _, h in spans)
    if total_h <= 0 or any(h <= 0 for _, h in spans):
        die("each time must be more than zero")
    rec("HEARD", "; ".join("%s dB(A) for %s" % (trim(db, 1), fmt_dur(h * 3600.0)) for db, h in spans))
    dose = sum(h / _safe_hours(db) for db, h in spans) * 100.0
    energy = sum(h * 10.0 ** (db / 10.0) for db, h in spans)
    over_8h = 10.0 * math.log10(energy / 8.0)
    rec("DAY", "%s%% of one day's allowance%s [%s]" % (
        num(dose) if dose >= 10 else trim(dose, 1), ": OVER" if dose > 100.0 else "", niosh))
    week = sum((P0 * 10.0 ** (db / 20.0)) ** 2 * h for db, h in spans) / ((P0 * 10.0 ** (week_level / 20.0)) ** 2 * WHO_HOURS) * 100.0
    if a.week:
        rec("WEEK", "%s%% of one week's allowance%s [%s]" % (num(week) if week >= 10 else trim(week, 1), ": OVER" if week > 100.0 else "", who))
    else:
        rec("WEEK", "%s%% of one week's allowance, from this alone; a day like it every day would be %s%% [%s]" % (
            num(week) if week >= 10 else trim(week, 1), num(week * 7.0) if week * 7 >= 10 else trim(week * 7.0, 1), who))
    _eu_line(over_8h, "spread over a working day of 8 h this comes to %s dB(A), which is")
    _listen_notes()


def _eu_line(level, how):
    if level > EU_LIMIT:
        state = "above the limit value of %s, which at work may not be exceeded at the ear" % trim(EU_LIMIT, 0)
    elif level >= EU_UPPER:
        state = "at or above the upper action value of %s, where hearing protection must be worn at work" % trim(EU_UPPER, 0)
    elif level > EU_LOWER:
        state = "above the lower action value of %s, where hearing protection must be on offer at work" % trim(EU_LOWER, 0)
    else:
        state = "not above the lower action value of %s" % trim(EU_LOWER, 0)
    rec("AT WORK", "%s %s [EU Directive 2003/10/EC; a workplace rule, used as a yardstick]" % (how % trim(level, 1), state))


def _listen_notes():
    rec("NOTE", "a phone app or a car's own meter reads within a few dB at best, and 3 dB is twice the sound energy: treat the "
                "figures as a guide. The limits are for a working life and for headphones; they are not a promise of safety "
                "below them, and ears that ring or sound dull afterwards have had too much")


# ---- cabin

def cmd_cabin(a):
    parts = re.split(r"\s*[xX]\s*", unprotect(str(a.size)).strip())
    factor = {"m": 1.0, "cm": 0.01, "mm": 0.001}[a.unit]
    try:
        dims = [float(p) * factor for p in parts]
    except ValueError:
        dims = []
    if len(dims) != 3 or any(not 0.2 <= d <= 30.0 for d in dims):
        die("the cabin is length x width x height on the inside, such as 2.6x1.5x1.2 (metres unless --unit says otherwise)")
    if not 1 <= a.modes <= 40:
        die("--modes is how many to list, 1 to 40")
    c = speed_of_sound(a.temp)
    length, width, height = dims
    rec("CABIN", "%s x %s x %s m inside, %s m3; sound at %s m/s in air at %s C" % (
        trim(length, 2), trim(width, 2), trim(height, 2), trim(length * width * height, 2), trim(c, 0), trim(a.temp, 0)))
    axis = ("along the length", "across the width", "floor to roof")
    modes = []
    for nx in range(0, 7):
        for ny in range(0, 7):
            for nz in range(0, 7):
                if nx == ny == nz == 0:
                    continue
                f = c / 2.0 * math.sqrt((nx / length) ** 2 + (ny / width) ** 2 + (nz / height) ** 2)
                used = [(n, k) for k, n in enumerate((nx, ny, nz)) if n]
                if len(used) == 1:
                    n, k = used[0]
                    kind = axis[k] + ("" if n == 1 else ", %s" % ("second", "third", "fourth", "fifth", "sixth")[n - 2])
                    weight = 0
                else:
                    kind = "between %d pairs of walls at once" % len(used)
                    weight = len(used) - 1
                modes.append((f, weight, kind, (nx, ny, nz)))
    modes.sort()
    rows = []
    for f, weight, kind, n in modes[:a.modes]:
        rows.append(("%s Hz" % _hz(f), note_text(f, a.a4), kind, "strongest" if weight == 0 else "weaker"))
    table(rows, header=("mode", "note", "the wave stands", ""), indent=2, right=(0,))
    first = modes[0][0]
    strong = [m for m in modes[:a.modes] if m[1] == 0][:4]
    rec("BOOM", "the bass notes this box makes most of: %s [derived]" % ", ".join("%s Hz (%s)" % (_hz(f), note_of(f, a.a4)[0]) for f, _, _, _ in strong))
    rec("LIFT", "below about %s Hz the cabin is shorter than half a wave, and the air in it is squeezed as one: bass gets a lift there, "
                "up to 12 dB an octave in a sealed box and less in a real cabin, which leaks and flexes [estimate]" % _hz(first))
    rec("NOTE", "a bare box with hard, square walls. Seats, people, sloping glass and soft trim move a real cabin's modes and damp "
                "them: this says where to listen, and a measurement says what is there")


def register(sub):
    p = command(sub, "sound", "pitch", cmd_pitch,
                "a frequency as a musical note, an engine's firing note from its revs, or the interval between two",
                ["pitch 440", "pitch A4 E5", "pitch --rpm 3000 --cyl 4", "pitch --rpm 6500 4800 --cyl 6",
                 "pitch --note E2 --cyl 8", "pitch --rpm 12000 --order 4"])
    p.add_argument("values", nargs="*", help="a frequency in Hz or a note (A4, C#3, Eb2); two for the interval between them")
    p.add_argument("--rpm", type=float, nargs="+", help="engine speed; two speeds give the step between their notes")
    p.add_argument("--cyl", type=int, help="number of cylinders")
    p.add_argument("--stroke", type=int, default=4, help="4 (default) or 2")
    p.add_argument("--order", type=float, help="instead of cylinders: how many times it happens in one turn (a motor's poles, a fan's blades)")
    p.add_argument("--note", help="with --cyl or --order: the revs at which it sings this note")
    p.add_argument("--a4", type=float, default=440.0, help="tuning: the pitch of A4 in Hz (default 440)")
    p.add_argument("--temp", type=float, default=20.0, help="air temperature in C, for the wavelength (default 20)")

    p = command(sub, "sound", "doppler", cmd_doppler,
                "the speed of something from the drop in its pitch as it passes, or the pitch drop from its speed",
                ["doppler --drop 3", "doppler --drop minor-third --ear 1", "doppler --heard 480 400", "doppler --heard A4 G4 --temp 0",
                 "doppler --speed 90 --hz 440"])
    p.add_argument("--heard", nargs=2, metavar=("COMING", "GOING"), help="the pitch as it came and as it went: Hz or notes")
    p.add_argument("--drop", help="how far the pitch fell as it passed: semitones, or minor-third, fourth, fifth ...")
    p.add_argument("--speed", help="the other way: its speed (km/h, or 25mph, 11m/s), for the pitches a listener hears")
    p.add_argument("--hz", help="with --speed: the pitch it makes, Hz or a note (default 440)")
    p.add_argument("--temp", type=float, default=20.0, help="air temperature in C (default 20)")
    p.add_argument("--ear", type=float, default=0.5, help="how far out the ear might be, in semitones, for the band (default 0.5)")
    p.add_argument("--a4", type=float, default=440.0, help="tuning: the pitch of A4 in Hz (default 440)")

    p = command(sub, "sound", "playlist", cmd_playlist,
                "pick and order tracks so the last one ends as the journey does: a soundtrack to the minute",
                ['playlist 3:45 4:10 2:58 5:02 3:30 4:44 6:15 3:05 --for 20m',
                 'playlist "Opener=3:45" "Long one=9:12" "Finale=5:02" 4:10 2:58 3:30 --for 18m --last finale',
                 'playlist 3:45 4:10 2:58 5:02 3:30 4:44 6:15 --route krakow katowice --depart "2026-11-14 08:00"',
                 "playlist 3:45 4:10 2:58 5:02 --for 12m --all --gap 2"])
    p.add_argument("tracks", nargs="*", help='track lengths: 3:45, 1:02:10 or 225s; with a name, "Name=3:45"')
    p.add_argument("--file", help="a text file with one track to a line, its length last ('-' reads what is piped in)")
    p.add_argument("--for", dest="length", help="how long the journey is: 1h52m, 112m, 1:52 (hours:minutes)")
    p.add_argument("--route", nargs=2, metavar=("FROM", "TO"), help="take the driving time between two places instead")
    p.add_argument("--mode", default="car", choices=["car", "motorway", "city", "bike", "walk", "rail", "air"], help="for --route (default car)")
    p.add_argument("--depart", help="when you set off, for clock times beside each track")
    p.add_argument("--arrive", help="when you must be there; with --depart it also gives the length")
    p.add_argument("--last", help="the track to end on, by name or number")
    p.add_argument("--first", help="the track to open with, by name or number")
    p.add_argument("--all", action="store_true", help="play every track in the order given, and say where arrival falls")
    p.add_argument("--gap", type=float, default=0.0, help="seconds of silence between tracks (default 0)")

    p = command(sub, "sound", "listen", cmd_listen,
                "a sound level and a time against the published limits: how long is safe, or how loud for how long",
                ["listen 94", "listen 85:2h 94:30m 100:10m", "listen --for 5h", "listen 88:3h --week --sensitive"])
    p.add_argument("spans", nargs="*", help="a level in dB(A), or LEVEL:TIME pairs such as 85:2h 94:30m")
    p.add_argument("--for", dest="length", help="a time on its own: the level that keeps inside the allowance for that long")
    p.add_argument("--week", action="store_true", help="the spans are the whole week's listening")
    p.add_argument("--sensitive", action="store_true", help="use the lower weekly allowance, meant for children and for more margin")

    p = command(sub, "sound", "cabin", cmd_cabin,
                "the standing waves of a box the size of a cabin: which bass notes boom, and where the bass lift begins",
                ["cabin 2.6x1.5x1.2", "cabin 260x150x120 --unit cm --modes 12", "cabin 3.1x1.7x1.3 --temp 0"])
    p.add_argument("size", help="length x width x height on the inside (metres unless --unit says otherwise)")
    p.add_argument("--unit", choices=["m", "cm", "mm"], default="m", help="unit of the sizes (default m)")
    p.add_argument("--modes", type=int, default=8, help="how many to list (default 8)")
    p.add_argument("--temp", type=float, default=20.0, help="air temperature in C (default 20)")
    p.add_argument("--a4", type=float, default=440.0, help="tuning: the pitch of A4 in Hz (default 440)")
