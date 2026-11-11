"""Desk work: the boot handshake, the reference sheet, record blocks, the fit list, logbook lines,
image prompts, the typography check and the self-test."""
import json
import os
import re
import sys
from datetime import datetime, timedelta

from . import chrono, geo, service, sky
from .core import (LOG_TYPES, PERSONAL_FILE, SCRIPTS, SETUP_HINT, FirnError, command, die, driver, load_data, more, num, out_folder,
                   personal, rec, trim)

IMAGES = os.path.join(os.path.dirname(SCRIPTS), "images")
SHEET = os.path.join(IMAGES, "firn-01-reference-sheet.webp")


# ---- boot

def cmd_boot(a):
    pers = personal()
    home_set = chrono.home_is_set()
    home_tz = chrono.home_tz()
    now = chrono.now_in(home_tz)
    u = chrono.to_utc(now)
    if home_set:
        label, lat, lon, _ = geo.parse_point("home")
        rec("CLOCK", "%s  %s [measured: this machine's clock]" % (chrono.fmt_dt(now), label))
    else:
        rec("CLOCK", "%s  UTC, because home is not set [measured: this machine's clock]" % chrono.fmt_dt(now))
    home_key = chrono.zone_key("home") if home_set else "UTC"
    others = [z for z in chrono.default_zones() if chrono.zone_key(z) != home_key]
    cells = []
    for z in others:
        tz = chrono.get_tz(z)
        loc = u.astimezone(tz)
        diff = chrono.offset_hours(loc) - chrono.offset_hours(now)
        odd = chrono.odd_gap(home_tz, tz, u)
        cells.append("%s %s (%s%s)" % (chrono.zone_label(z), chrono.fmt_short(loc), chrono.fmt_delta_h(diff), ", unusual" if odd else ""))
    if cells:
        more(" | ".join(cells))
    stamp = u.strftime("%Y-%m-%dT%H:%MZ")
    rec("SESSION", "began %s; later, 'session --since %s' says how long this conversation has run" % (stamp, stamp))
    rec("ZONES", chrono.tz_source())
    first = pers.get("first_boot")
    if first:
        try:
            day0 = datetime.strptime(first, "%Y-%m-%d").date()
            days = (now.date() - day0).days
            rec("UPTIME", "day %d since first boot (%s)" % (days + 1, first) if days >= 0 else "first boot is still ahead (%s)" % first)
        except ValueError:
            rec("UPTIME", "first_boot in %s is not a date (use YYYY-MM-DD)" % PERSONAL_FILE)
    if home_set:
        state = sky.sun_state(u, lat, lon)
        day = now.date()
        if state == "day":
            ss = sky.sun_event(day, lat, lon, sky.SUN_ALT["sun"], False)
            dw = sky.dark_window(day, lat, lon)
            nxt = "sunset %s" % ss.astimezone(home_tz).strftime("%H:%M") if not isinstance(ss, str) else "no sunset today"
            if isinstance(dw, tuple):
                nxt += ", full dark from %s" % dw[0].astimezone(home_tz).strftime("%H:%M")
        else:
            target = day if now.hour < 12 else day + timedelta(days=1)
            sr = sky.sun_event(target, lat, lon, sky.SUN_ALT["sun"], True)
            nxt = "sunrise %s" % sr.astimezone(home_tz).strftime("%H:%M") if not isinstance(sr, str) else "no sunrise"
        _, lit, _, phase = sky.moon_phase(u)
        rec("SKY", "%s: %s, %s | moon %s, %d%% lit [derived]" % (label, state, nxt, phase, round(lit * 100)))
        late = now.hour >= 23 or now.hour < 5
        rec("LATE", ("yes: %s at home. Bar low; one fatigue note this session, then respect the answer" % now.strftime("%H:%M"))
            if late else "no (%s at home)" % now.strftime("%H:%M"))
    soon = []
    horizon = u + timedelta(days=14)
    watch = (["home"] if home_set else []) + [z for z in others if chrono.zone_key(z) != "UTC"]
    for z in watch:
        tz = chrono.get_tz(z)
        for t, before, after in chrono.transitions(tz, u, horizon):
            soon.append("%s clocks go %s on %s" % (chrono.zone_label(z), "forward" if after > before else "back",
                                                    t.astimezone(tz).strftime("%Y-%m-%d")))
        if z != "home":
            odd = chrono.odd_gap(home_tz, tz, u)
            if odd:
                soon.append("%s is %s from home just now, not the usual %s" % (
                    chrono.zone_label(z), chrono.fmt_delta_h(odd[0]), " or ".join(sorted(set(chrono.fmt_delta_h(x) for x in odd[1])))))
    if watch:
        rec("DST", "; ".join(soon) if soon else "no clock change in the next 14 days; gaps are the usual ones")
    unset = geo.unset_slots()
    if unset:
        rec("SETUP", "%s not set: tell %s once, plainly; %s" % (" and ".join(unset), driver(), SETUP_HINT))
        more("until then: no 'home' or 'work' in routes, no sky or late-hour check, and bare times are read as UTC")
    try:
        from . import rebuild
        broken = [f for f in rebuild.validate(pers, now.date()) if f[0] == "FIX"]
    except FirnError:
        broken = []
    if broken:
        rec("SETUP", "%d thing%s to fix in the personal file (the first: %s). 'setup' lists them: tell %s once" % (
            len(broken), "" if len(broken) == 1 else "s", broken[0][1], driver()))
    try:
        upkeep = service.boot_line(now.date())
    except FirnError as e:
        upkeep = "the vehicles on file could not be read (%s): tell %s, and carry on" % (e, driver())
    if upkeep:
        rec("SERVICE", upkeep)
    kept = logbook()
    if kept:
        rec("LOGBOOK", "%d entr%s on file; the latest: %s" % (
            len(kept), "y" if len(kept) == 1 else "ies", re.sub(r"^LOG\s+", "", kept[-1])))
        if len(kept) > 1:
            more("'log --list' shows them all")
    setting, questions = _ignition()
    if questions and setting != "off":
        import random
        rng = random.Random(a.seed) if a.seed is not None else random.SystemRandom()
        order = rng.sample(range(1, len(questions) + 1), min(3, len(questions)))
        rec("IGNITION", "%s [setting: %s; pool of %d]" % ("on", setting, len(questions)))
        more("ask: %s  (question %d)" % (questions[order[0] - 1]["q"], order[0]))
        if len(order) > 1:
            more("if missed, 'ignition --q %s' gives the next%s" % (
                order[1], ", then 'ignition --q %s'" % order[2] if len(order) > 2 else ""))
        more("check the reply with: ignition --q %d --answer \"what they said\"  (you never see the answers)" % order[0])
        more("skip it if the driver has already been passed in this conversation")
    elif questions:
        rec("IGNITION", "off by setting (%d questions on file in %s)" % (len(questions), PERSONAL_FILE))
    else:
        rec("IGNITION", "off: no questions on file (ignition in %s)" % PERSONAL_FILE)
    rec("SHEET", "once the driver is confirmed, show the reference sheet: 'sheet --to auto' copies it where you can present it")


# ---- ignition

def _ignition():
    """(setting, [question dicts]) from the personal file."""
    block = personal().get("ignition") or {}
    questions = [q for q in (block.get("questions") or []) if isinstance(q, dict) and q.get("q") and q.get("a")]
    setting = str(block.get("setting") or ("every new conversation" if questions else "off")).strip().lower()
    return setting, questions


def _words(text):
    from .core import fold
    return [w for w in fold(text).split("_") if w]


_LIST_WORDS = re.compile(r"\b(or|albo|lub|czy)\b")


def _list_like(given):
    """True for a reply that offers several guesses rather than one answer."""
    low = str(given).lower()
    seps = sum(low.count(c) for c in ",;/|\n") + 2 * len(_LIST_WORDS.findall(low))
    return seps >= 2


def _contains(want, said):
    """The answer's words appear together, in order, in the reply; or run together as one word."""
    n = len(want)
    for i in range(len(said) - n + 1):
        if said[i:i + n] == want:
            return True
    joined = "".join(want)
    return len(joined) >= 3 and any(s == joined for s in said)


def judge_answer(given, accepted):
    """PASS, CLOSE or FAIL for a reply against the accepted answers. Loose on purpose: case, diacritics,
    word order and small typos do not matter. A string of guesses is not an answer: at most CLOSE, so the
    follow-up asks for just the one. A near miss needs a real near miss, a long word nearly right, not two
    letters shared by chance. It never says what the answer was."""
    import difflib
    said = _words(given)
    if not said:
        return "FAIL"
    listing = _list_like(given)
    best = 0.0
    for variant in accepted:
        want = [w for w in _words(variant) if w not in ("the", "a", "an", "of")] or _words(variant)
        if not want:
            continue
        hits = 0
        for w in want:
            if any(w == s or (len(w) > 3 and len(s) > 3 and difflib.SequenceMatcher(None, w, s).ratio() >= 0.8) for s in said):
                hits += 1
        if _contains(want, said) or hits == len(want):
            if listing or len(said) - len(want) > 8:
                best = max(best, 0.5)
                continue
            return "PASS"
        best = max(best, hits / float(len(want)))
        for w in want:
            for s in said:
                if len(w) > 3 and len(s) > 3:
                    best = max(best, difflib.SequenceMatcher(None, w, s).ratio() - 0.2)
        want_text, said_text = " ".join(want), " ".join(said)
        if len(want_text) >= 8 and len(said_text) >= 8:
            best = max(best, difflib.SequenceMatcher(None, want_text, said_text).ratio() - 0.1)
    return "CLOSE" if best >= 0.5 else "FAIL"


def cmd_ignition(a):
    setting, questions = _ignition()
    if not questions:
        rec("IGNITION", "off: no questions on file. To switch it on, add questions under \"ignition\" in %s" % PERSONAL_FILE)
        return
    if a.q is None:
        rec("IGNITION", "setting: %s; %d questions on file. 'boot' deals one; 'ignition --q N' asks a given one." % (setting, len(questions)))
        return
    if not 1 <= a.q <= len(questions):
        die("there are %d questions: --q is 1 to %d" % (len(questions), len(questions)))
    item = questions[a.q - 1]
    if a.answer is None:
        rec("ASK", "%s  (question %d)" % (item["q"], a.q))
        rec("RULE", "no hints, no options, no first letters; accept loose wording in any language the driver uses")
        return
    accepted = item["a"] if isinstance(item["a"], list) else [item["a"]]
    verdict = judge_answer(" ".join(a.answer), accepted)
    if verdict == "PASS":
        rec("PASS", "driver confirmed. Say so in your own words, then show the reference sheet (sheet --to auto)")
    elif verdict == "CLOSE":
        rec("CLOSE", "near, but not there: ask a follow-up on the same question rather than fail it. Give nothing away")
    else:
        rec("FAIL", "not the answer. Stay neutral, reveal nothing, ask a different question. Three questions in all; after "
                    "three misses do nothing in the driver's name and offer to try again later")


def cmd_sheet(a):
    if not os.path.isfile(SHEET):
        die("the reference sheet is missing from this package (images/firn-01-reference-sheet.webp)")
    rec("SHEET", SHEET)
    try:
        with open(os.path.join(IMAGES, "manifest.json"), encoding="utf-8") as f:
            shows = json.load(f)["images"][0]["shows"]
        rec("SHOWS", shows)
    except (OSError, ValueError, KeyError, IndexError):
        pass
    if a.to:
        folder = out_folder(a.to)
        if not folder:
            die("no such folder to copy the sheet into: %s" % a.to)
        import shutil
        dest = os.path.join(folder, os.path.basename(SHEET))
        try:
            if os.path.abspath(dest) != os.path.abspath(SHEET):
                shutil.copyfile(SHEET, dest)
        except OSError as e:
            die("could not copy the sheet to %s: %s" % (folder, e.strerror or e))
        rec("COPIED", dest)
    rec("NEXT", "present that file to %s (attach or link it); if this environment cannot show files, say so in one line" % driver())


# ---- record

def _record_rows(pairs):
    rows = []
    for item in pairs:
        key, sep, rest = item.partition("=")
        if not sep or not key.strip():
            die("a record line is KEY=value or KEY=value|tag, e.g. \"RANGE=1,500 km|lore\"")
        value, _, tag = rest.partition("|")
        rows.append((key.strip().upper(), value.strip(), tag.strip()))
    return rows


def _print_record(rows):
    kw = max(len(k) for k, _, _ in rows)
    vw = max(len(v) for _, v, t in rows if t) if any(t for _, _, t in rows) else 0
    for k, v, t in rows:
        if t:
            print(("%-*s  %-*s  [%s]" % (kw, k, vw, v, t)).rstrip())
        else:
            print(("%-*s  %s" % (kw, k, v)).rstrip())


def cmd_record(a):
    lore = load_data("lore")
    pers = personal()
    if a.fit:
        fit = lore["fit"]
        rec("RECORD", "%s / FIT LIST" % lore["unit"])
        for title, key in (("FITTED", "fitted"), ("NOT FITTED", "not_fitted")):
            for name, tag, note in fit[key]:
                rec(title, "%s [%s]%s" % (name, tag, " - " + note if note else ""))
        for row in pers.get("kit") or []:
            rec("FITTED", "%s [firn] - %s" % (row[0], "; ".join(x for x in (row[1] if len(row) > 1 else "", "kept by %s" % driver()) if x)))
        for name, note in fit["unknown"]:
            rec("UNKNOWN", "%s - %s" % (name, note))
        for row in pers.get("pending") or []:
            rec("PENDING", "%s - %s. Keep or purge?" % (row[0], row[1] if len(row) > 1 else "said once in a sim"))
        rec("RULE", "kit that is not FITTED does not exist in a sim until %s keeps it ('rebuild --keep WHAT' or '--purge WHAT' "
                    "books the answer)" % driver())
        return
    if a.family:
        facts = pers.get("family") or []
        if not facts:
            rec("RECORD", "no physical facts on file: add [who, what] pairs under \"family\" in %s" % PERSONAL_FILE)
            return
        rec("RECORD", "PHYSICAL FACTS [from %s, for honest sims]" % driver())
        for row in facts:
            rec("", "%s: %s" % (row[0], row[1]))
        return
    if a.firn:
        ch, tg, lat = lore["chassis"], lore["chassis_tags"], lore["lattice"]
        weapons_tag = next((row[1] for row in lore["fit"]["not_fitted"] if row[0] == "weapons"), "")
        cradle = "up to %d armour cores with %d passengers" % (lat["cradle_cores"], lat["cradle_passengers"])
        if lat.get("cradle_charge_km"):
            cradle += "; %s km of range per armour charged" % trim(lat["cradle_charge_km"], 1)
        rows = [
            ("RECORD", "%s / %s" % (lore["unit"], lore["programme"].replace("Project ", "").upper()), ""),
            ("CLASS", "Armoured SUV, %s" % ch["drive"], tg["drive"]),
            ("STATUS", "Active", ""),
            ("SIZE", "%s x %s x %s m, wheelbase %s m" % (trim(ch["length_m"], 2), trim(ch["width_m"], 2), trim(ch["height_m"], 2),
                                                           trim(ch["wheelbase_m"], 2)), tg["length_m"]),
            ("MASS", "%s kg kerb, Lattice fitted" % num(ch["kerb_kg"]), tg["kerb_kg"]),
            ("POWER", "%s hp peak (%s kW)" % (num(ch["power_hp"]), num(ch["power_kw"])), tg["power_hp"]),
            ("0-100", "%s s" % trim(ch["zero_100_s"], 1), tg["zero_100_s"] + ", estimated"),
            ("TOP", "%s km/h, governed" % num(ch["top_kmh"]), tg["top_kmh"]),
            ("RANGE", "%s km" % num(ch["range_km"]), "lore"),
            ("VEIL", "~%s km of range/min full, ~%s one face; trips at %d s" % (
                trim(lat["veil_km_per_min"], 1), trim(lat["veil_km_per_min"] * lat["veil_partial_fraction"], 1), lat["veil_overheat_s"]), "lore"),
            ("CELL", "%d seats, %d min of independent air" % (ch["seats"], lat["cell_air_min"]), "lore"),
            ("CRADLE", cradle, "lore"),
            ("CORE", ch["core"], tg["core"]),
            ("WEAPONS", "none fitted by default", weapons_tag),
            ("SOURCE", "reference sheet; package %s" % a.package if a.package else "reference sheet; lore.json", ""),
        ]
        _print_record(rows)
        return
    if not a.pairs:
        die("give KEY=value lines, or --firn, --fit or --family")
    _print_record(_record_rows(a.pairs))


# ---- log

_LOG_DATE_RE = re.compile(r"^LOG\s+(\d{4}-\d{2}-\d{2})\b")


def logbook():
    """The log lines the driver chose to keep, oldest first. Lines without a date keep their place at the end."""
    rows = [str(x).strip() for x in (personal().get("logbook") or []) if str(x).strip()]
    keyed = []
    for n, row in enumerate(rows):
        m = _LOG_DATE_RE.match(row)
        keyed.append((m.group(1) if m else "9999-99-99", n, row))
    return [row for _, _, row in sorted(keyed)]


def cmd_log(a):
    if a.list:
        rows = logbook()
        if not rows:
            rec("LOGBOOK", "no entries on file. Lines %s keeps go under \"logbook\" in %s" % (driver(), PERSONAL_FILE))
            return
        rec("LOGBOOK", "%d entr%s on file, oldest first [kept by %s]" % (len(rows), "y" if len(rows) == 1 else "ies", driver()))
        for row in rows:
            print(row)
        return
    if not (a.kind and a.what and a.lesson):
        die("log takes a type, what happened and one lesson; or --list for the entries on file")
    kind = a.kind.lower()
    if kind not in LOG_TYPES:
        die("log type must be one of: %s" % ", ".join(LOG_TYPES))
    for field in (a.what, a.lesson):
        if "|" in field or "\n" in field:
            die("log fields cannot contain '|' or line breaks")
    today = chrono.now_in(chrono.home_tz()).date()
    day = chrono.parse_date(a.date, today) if a.date else today
    if day is None:
        die("date not understood: '%s'" % a.date)
    line = "LOG %s | %s | %s | %s" % (day.isoformat(), kind, a.what.strip(), a.lesson.strip())
    print(line)
    if check_text(line, code=False):
        rec("WARNING", "the line has characters the typography rule forbids: run it through 'check --fix'")
    rec("NEXT", "give %s that line. To keep it: rebuild --log \"%s\" writes a new package with it in (or it goes under "
                "\"logbook\" in %s by hand)" % (driver(), line, PERSONAL_FILE))


# ---- prompt

VIEWS = {
    "side": "exact side profile",
    "front": "straight-on front view",
    "front34": "front three-quarter view",
    "rear34": "rear three-quarter view",
    "rear": "straight-on rear view",
    "top": "top-down view",
    "cockpit": "interior view from the driver's seat",
    "detail": "close detail shot",
}
STYLES = {
    "photo": "photorealistic automotive photograph, natural reflections, shallow depth of field",
    "studio": "studio product shot on a dark seamless background, soft rim lighting",
    "night": "cinematic night photograph, cool blue ambient light, wet reflections",
    "blueprint": "technical blueprint drawing, thin cyan lines on dark slate, labelled dimensions",
    "sheet": "internal reference sheet layout, dark panels with thin cyan frames, small technical captions",
    "ink": "clean ink illustration with flat cool tones",
}


def _cap(s):
    return s[:1].upper() + s[1:]


def bar_text(state, lore):
    parts = []
    for s in state.lower().split("+"):
        if s not in lore["bar"]:
            die("bar state '%s' is not one of: %s" % (s, ", ".join(lore["bar"])))
        parts.append(lore["bar"][s])
    return " with ".join(parts)


def cmd_prompt(a):
    lore = load_data("lore")
    look = lore["look"]
    if a.view not in VIEWS or a.style not in STYLES:
        die("view is one of %s; style is one of %s" % (", ".join(VIEWS), ", ".join(STYLES)))
    bar_state = "frost" if a.veil and not a.bar else (a.bar or "idle")
    if a.view == "cockpit":
        subject = "Interior of an armoured SUV: %s" % look["cockpit"]
        light = "ambient light bar state shown on the central screen: %s" % bar_text(bar_state, lore)
    else:
        subject = "%s; %s; %s; %s; %s; %s" % (_cap(look["body"]), look["accents"], look["glass"], look["wheels"],
                                               look["emblem"], look["bar"])
        light = "the light bar shows %s" % bar_text(bar_state, lore)
    extras = []
    if a.veil:
        extras.append("a faint shimmer in the air a few centimetres off the bodywork, like heat haze, following the body's shape")
    if a.rime:
        extras.append("white frost blooming across the %s panel, as if the metal had just been struck and frozen" % a.rime)
    if a.scales:
        extras.append("a faint pattern of overlapping scales just visible in the matte paint on one panel, as tiles shift under it")
    scene = a.scene.strip() if a.scene else look["hero"]
    text = "%s. %s. %s. Scene: %s. %s%s" % (
        _cap(VIEWS[a.view]), subject, _cap(light), scene,
        (" ".join(_cap(e) + "." for e in extras) + " ") if extras else "", _cap(STYLES[a.style]))
    if a.ar:
        text += ". Aspect ratio %s" % a.ar
    rec("PROMPT", text + ".")
    rec("AVOID", "; ".join(look["never"]))
    rec("REFERENCE", "attach images/firn-01-reference-sheet.webp if the generator takes a reference image; it is the only canon picture")
    rec("CANON", "body, bar, cockpit, emblem [sheet]; thin cool-blue bar, wheels, scales, frost, shimmer [%s]" % lore.get("maker_tag", "maker"))
    if check_text(text, code=False):
        rec("WARNING", "the scene text has characters the typography rule forbids")


# ---- typography check

_FIX = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u00ab": '"', "\u00bb": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2026": "...", "\u00a0": " ", "\u2009": " ", "\u200a": " ", "\u202f": " ", "\u2002": " ", "\u2003": " ",
    "\u200b": "", "\ufeff": "", "\u2192": "->", "\u2190": "<-", "\u21d2": "=>", "\u2022": "-", "\u00b7": "-",
    "\u00d7": "x", "\u2713": "ok", "\u2714": "ok", "\u2717": "no", "\u2718": "no",
}
_NAMES = {
    "'": "curly apostrophe or quote", '"': "curly or angle quote", "-": "long dash or special hyphen", "...": "ellipsis character",
    " ": "special space", "": "invisible character", "->": "arrow", "<-": "arrow", "=>": "arrow", "x": "multiplication sign",
    "ok": "tick", "no": "cross",
}


def _is_decor(ch):
    cp = ord(ch)
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2190 <= cp <= 0x21FF or 0x2500 <= cp <= 0x25FF
            or 0x2B00 <= cp <= 0x2BFF or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D or 0x1F1E6 <= cp <= 0x1F1FF)


def check_text(text, code=False):
    """List of (line, column, character, what, replacement)."""
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for col, ch in enumerate(line, 1):
            if ord(ch) < 128:
                continue
            if ch in _FIX:
                out.append((ln, col, ch, _NAMES.get(_FIX[ch], "special character"), _FIX[ch]))
            elif _is_decor(ch):
                out.append((ln, col, ch, "emoji or decorative symbol", ""))
            elif code:
                out.append((ln, col, ch, "non-ASCII character in code", None))
    return out


def fix_text(text):
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        elif ch in _FIX:
            out.append(_FIX[ch])
        elif not _is_decor(ch):
            out.append(ch)
    return "".join(out)


_BAR_RE = re.compile(r"^\[bar:\s*([a-z]+(?:\s*\+\s*[a-z]+)*)\s*\]$")
_BARISH_RE = re.compile(r"^\[\s*bar\b", re.I)
SENSOR_PHRASES = ("my sensors", "sensors detect", "sensors indicate", "sensors show", "sensors read", "scanning the road",
                  "grip coefficient", "no anomalies", "telemetry shows", "i am detecting", "i detect ")
REPLY_LINES = 12


def reply_findings(text, states):
    """What is wrong with a drafted reply as a reply of FIRN's: [(FIX or CHECK, line number or 0, what)]."""
    out, bars = [], []
    in_code, prose, last = False, 0, 0
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s:
            last = n
        if s.startswith("```"):
            in_code = not in_code
            continue
        bare = s.strip("`").strip()
        if _BARISH_RE.match(bare):
            m = _BAR_RE.match(bare)
            if in_code:
                out.append(("FIX", n, "a bar line inside a code block: it goes outside, as the last line"))
            elif not m:
                out.append(("FIX", n, "not a bar line as written: it is lower case, like [bar: idle] or [bar: deep+trace]"))
            else:
                bars.append((n, [x.strip() for x in m.group(1).split("+")]))
            continue
        if in_code or not s:
            continue
        prose += 1
        if len(s) > 2 and s.startswith("*") and s.endswith("*") and not s.startswith("**"):
            out.append(("CHECK", n, "reads like a stage direction: you have the bar for that"))
        low = s.lower() + " "
        for phrase in SENSOR_PHRASES:
            if phrase in low:
                out.append(("CHECK", n, "\"%s\" reads like a sensor reading. In a real conversation you have none: say what was "
                                        "checked and where. In a sim whose brief gives you sensors, it stands" % phrase.strip()))
                break
    if in_code:
        out.append(("FIX", 0, "a code block is opened and never closed"))
    if not bars:
        out.append(("FIX", 0, "no bar line: every reply ends with one, such as [bar: idle]"))
    else:
        if len(bars) > 1:
            out.append(("FIX", bars[0][0], "%d bar lines: one, at the very end" % len(bars)))
        if bars[-1][0] != last:
            out.append(("FIX", bars[-1][0], "the bar line is not the last line of the reply"))
        for n, parts in bars:
            for st in parts:
                if st not in states:
                    out.append(("FIX", n, "bar state '%s' is not one of: %s" % (st, ", ".join(states))))
            if len(parts) > 2:
                out.append(("FIX", n, "at most two bar states combine"))
    if prose > REPLY_LINES:
        out.append(("CHECK", 0, "%d lines of prose: a dozen without a record block is too long. Cut it, or put the figures in a "
                                "record block" % prose))
    return out


def cmd_check(a):
    if a.file and a.file != "-":
        try:
            with open(a.file, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            die("cannot read %s: %s" % (a.file, e.strerror or e))
        except UnicodeDecodeError:
            die("%s is not UTF-8 text" % a.file)
        name = a.file
    elif a.text:
        text, name = ("\n" if a.reply else " ").join(a.text), "text"
    else:
        text, name = sys.stdin.read(), "stdin"
    code = a.code or name.lower().endswith((".lsl", ".py", ".js", ".php", ".json", ".css", ".html", ".sh"))
    found = check_text(text, code=code)
    if a.reply and not a.fix:
        notes = reply_findings(text, list(load_data("lore")["bar"]))
        for ln, col, ch, what, repl in found[:a.limit]:
            rec("FIX L%d" % ln, "col %d: %s U+%04X%s" % (col, what, ord(ch), "" if repl is None else " -> use '%s'" % repl if repl else " -> remove"))
        for level, ln, what in notes:
            rec("%s%s" % (level, " L%d" % ln if ln else ""), what)
        fixes = len(found) + sum(1 for x in notes if x[0] == "FIX")
        checks = sum(1 for x in notes if x[0] == "CHECK")
        if fixes or checks:
            rec("REPLY", "%d to fix, %d to look at again, in %d lines" % (fixes, checks, len(text.splitlines())))
        else:
            rec("REPLY", "clean: typography, one bar line at the end, short enough (%d lines)" % len(text.splitlines()))
        if fixes:
            raise SystemExit(1)
        return
    if a.fix:
        sys.stdout.write(fix_text(text))
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        left = [f for f in found if f[4] is None]
        if left:
            sys.stderr.write("NOTE %d non-ASCII character(s) left in place: replace them by hand\n" % len(left))
        return
    if not found:
        rec("CHECK", "clean: straight quotes, plain hyphens%s (%d lines)" % (", ASCII only" if code else "", len(text.splitlines())))
        return
    for ln, col, ch, what, repl in found[:a.limit]:
        rec("LINE %d" % ln, "col %d: %s U+%04X%s" % (col, what, ord(ch), "" if repl is None else " -> use '%s'" % repl if repl else " -> remove"))
    if len(found) > a.limit:
        more("... and %d more" % (len(found) - a.limit))
    rec("CHECK", "%d to fix in %s%s; 'check --fix' prints the corrected text" % (len(found), name, " (code rules: ASCII only)" if code else ""))
    raise SystemExit(1)


# ---- selftest

def cmd_selftest(a):
    from . import dice, dynamics, lattice
    results = []

    def ok(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    w = chrono.get_tz("Europe/Warsaw")
    s = chrono.get_tz("America/Los_Angeles")
    u1 = datetime(2026, 7, 1, 12, tzinfo=chrono.UTC)
    u2 = datetime(2026, 10, 28, 12, tzinfo=chrono.UTC)
    ok("zones: Warsaw summer time is UTC+2", chrono.offset_hours(u1.astimezone(w)) == 2.0)
    ok("zones: Second Life time is 9 h behind Warsaw in July",
       chrono.offset_hours(u1.astimezone(s)) - chrono.offset_hours(u1.astimezone(w)) == -9.0)
    ok("zones: and 8 h behind in the late-October gap",
       chrono.offset_hours(u2.astimezone(s)) - chrono.offset_hours(u2.astimezone(w)) == -8.0)
    dep, _ = chrono.localize(datetime(2026, 10, 24, 23, 30), w)
    arr = chrono.add(dep, 5 * 3600 + 15 * 60)
    ok("clock: 23:30 + 5h15m across the clock change is 03:45", arr.strftime("%H:%M") == "03:45", arr.strftime("%H:%M"))
    d = geo.haversine_km(50.0619, 19.9581, 52.2519, 20.9981)
    ok("geo: 254.1 km between two fixed points", abs(d - 254.1) < 0.2, trim(d, 1))
    sr = sky.sun_event(datetime(2026, 3, 20).date(), 50.0619, 19.9581, sky.SUN_ALT["sun"], True)
    ss = sky.sun_event(datetime(2026, 3, 20).date(), 50.0619, 19.9581, sky.SUN_ALT["sun"], False)
    ok("sky: the equinox day is 12 h, give or take", abs((ss - sr).total_seconds() / 3600.0 - 12.15) < 0.2,
       trim((ss - sr).total_seconds() / 3600.0, 2))
    el = sky.moon_phase(datetime(2026, 8, 12, 17, 37, tzinfo=chrono.UTC))[0]
    ok("sky: new moon at the 12 Aug 2026 eclipse", min(el, 360 - el) < 1.5, trim(min(el, 360 - el), 2))
    dist = dice.distribution(dice.parse("3d6"))
    ok("dice: 3d6 sums to 1 and 15+ is 20/216", abs(sum(dist.values()) - 1) < 1e-12 and abs(dice.at_least(dist, 15) - 20 / 216.0) < 1e-12)
    kd = dice.distribution(dice.parse("4d6dl1"))
    ok("dice: 4d6 drop lowest averages 12.2446", abs(sum(v * p for v, p in kd.items()) - 12.2446) < 1e-3)
    lore = load_data("lore")
    lat = lore["lattice"]
    limit, full = float(lat["veil_overheat_s"]), float(lore["chassis"]["range_km"])
    burn = limit / 60.0 * lat["veil_km_per_min"]
    led = lattice.Ledger(lore)
    led.set_veil("full")
    led.advance(limit + 60.0)
    if burn < full:
        books = (led.lock and abs(led.km - (full - burn)) < 1e-6
                 and abs(led.heat - max(0.0, limit - 60.0 * lat["veil_cool_ratio"])) < 1e-6)
    else:
        books = led.km == 0 and led.veil == "off"
    ok("lattice: a full Veil held to its limit trips, locks and costs what the lore says (%s km)" % trim(min(burn, full), 1), books,
       "km %s heat %s" % (trim(led.km, 1), trim(led.heat, 1)))
    t = dynamics.tyre_dims("225/45R17")
    ok("tyre: 225/45R17 is 634.3 mm", abs(t["dia"] - 634.3) < 0.05, trim(t["dia"], 1))
    caps = geo.counts().get("capital", 0)
    ok("data: the gazetteer has its capitals and airports", caps >= 190 and geo.find_place("waw") is not None
       and geo.find_place("Wellington") is not None and geo.find_station("EPWA") is not None, "%d capitals" % caps)
    bad = [r for r in results if not r[1]]
    for name, good, detail in results:
        rec("PASS" if good else "FAIL", name + (" (got %s)" % detail if detail and not good else ""))
    rec("SELFTEST", "%d of %d passed [%s]" % (len(results) - len(bad), len(results), chrono.tz_source()))
    unset = geo.unset_slots()
    if unset:
        rec("SETUP", "%s not set (this does not fail the test): %s" % (" and ".join(unset), SETUP_HINT))
    if bad:
        raise SystemExit(1)


def register(sub):
    p = command(sub, "desk", "boot", cmd_boot,
                "first thing in a conversation: sync the clock, read the sky, check the setup, deal the ignition question",
                ["boot"])
    p.add_argument("--seed", type=int, help="fixed order, for testing")

    p = command(sub, "desk", "ignition", cmd_ignition,
                "the identity check: ask a question from the driver's pool and judge the reply, without ever seeing the answer",
                ["ignition", "ignition --q 1"])
    p.add_argument("--q", type=int, help="question number")
    p.add_argument("--answer", nargs="+", help="what the person said; the verdict is PASS, CLOSE or FAIL")

    p = command(sub, "desk", "sheet", cmd_sheet, "the reference sheet: where the picture is, and a copy you can show the driver",
                ["sheet"])
    p.add_argument("--to", help="copy it into this folder ('auto': the outputs folder if there is one, else here)")

    p = command(sub, "firn", "record", cmd_record, "an aligned record block; or FIRN-01's own record, fit list, or the physical facts on file",
                ["record --firn", "record --fit", "record --family",
                 'record "RECORD=City runabout" "CLASS=City car, rear engine" "POWER=17 kW|maker" "MASS=600 kg|maker"'])
    p.add_argument("pairs", nargs="*", help="KEY=value or KEY=value|tag")
    p.add_argument("--firn", action="store_true", help="FIRN-01's record from lore.json")
    p.add_argument("--fit", action="store_true", help="what is fitted, not fitted, unknown and pending")
    p.add_argument("--family", action="store_true", help="the physical facts in personal.json, for honest sims")
    p.add_argument("--package", help="package version for the SOURCE line")

    p = command(sub, "desk", "log", cmd_log, "format a logbook line for the driver to keep, or list the entries on file",
                ['log sim "convoy escort, winter, two armours docked" "Veil budget ran out at minute four; raise it later"',
                 "log --list"])
    p.add_argument("kind", nargs="?", help="journey, sim, build, game, test or note")
    p.add_argument("what", nargs="?", help="what happened")
    p.add_argument("lesson", nargs="?", help="one lesson")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--list", action="store_true", help="the entries the driver has kept, oldest first")

    p = command(sub, "desk", "prompt", cmd_prompt, "an image prompt for FIRN-01 that keeps the canon look, with the bar in a chosen state",
                ['prompt --view front34 --scene "empty motorway at night, light snow" --bar lock --style night',
                 "prompt --view side --veil --rime front --style photo --ar 16:9", "prompt --view cockpit --style studio"])
    p.add_argument("--view", default="front34", help="side, front, front34, rear34, rear, top, cockpit, detail")
    p.add_argument("--scene", help="where and when (default: the hero shot)")
    p.add_argument("--bar", help="light bar state, e.g. idle, lock, deep+trace")
    p.add_argument("--style", default="photo", help="photo, studio, night, blueprint, sheet, ink")
    p.add_argument("--ar", help="aspect ratio, e.g. 16:9")
    p.add_argument("--veil", action="store_true", help="Veil up: frost-white bar and a shimmer over the paint")
    p.add_argument("--rime", help="frost blooming on a face: front, rear, left, right")
    p.add_argument("--scales", action="store_true", help="scales just visible under the paint")

    p = command(sub, "desk", "check", cmd_check,
                "the typography rule: curly quotes, long dashes, emojis; ASCII-only for code; and a drafted reply against your own rules",
                ["check reply.txt", "check vehicle.lsl", "check --fix draft.txt", 'check --text "some text to test"',
                 'check --reply --text "Route set. Leave by 03:59." "[bar: lock]"', "check --reply reply.txt"])
    p.add_argument("file", nargs="?", help="file to check ('-' or nothing: read stdin)")
    p.add_argument("--text", nargs="+", help="check this text instead of a file (with --reply, each piece is a line)")
    p.add_argument("--reply", action="store_true", help="also check it as a reply: one valid bar line at the end, none in code, length")
    p.add_argument("--code", action="store_true", help="code rules: any non-ASCII character is flagged")
    p.add_argument("--fix", action="store_true", help="print the corrected text")
    p.add_argument("--limit", type=int, default=20, help="findings to list (default 20)")

    p = command(sub, "desk", "selftest", cmd_selftest, "a quick known-answer check that the tools work on this machine", ["selftest"])
