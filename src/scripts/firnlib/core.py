"""Shared helpers for the FIRN field tools: records, parsing, data files.

Python 3.9+, standard library only, no network.
"""
import json
import os
import re
import sys
import unicodedata

LIB = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(LIB)
DATA = os.path.join(SCRIPTS, "data")

G = 9.80665
KEY_WIDTH = 10


class FirnError(Exception):
    """A user-facing error: bad input, missing data. Printed as one ERROR line."""


def die(msg):
    raise FirnError(msg)


# ---- record output

def rec(key, value=""):
    """Print one KEY value line. Keys longer than the column simply push the value right."""
    key = str(key)
    if value == "" or value is None:
        print(key)
    else:
        print("%-*s %s" % (KEY_WIDTH, key, value))


def more(value):
    """Continuation line under the previous record."""
    print(" " * (KEY_WIDTH + 1) + str(value))


def table(rows, header=None, indent=0, right=()):
    """Print aligned columns. rows: list of sequences. right: column indexes to right-align."""
    rows = [[str(c) for c in r] for r in rows]
    if header:
        rows = [[str(c) for c in header]] + rows
    if not rows:
        return
    widths = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(max(len(r) for r in rows))]
    pad = " " * indent
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            cells.append(c.rjust(widths[i]) if i in right else c.ljust(widths[i]))
        print((pad + "  ".join(cells)).rstrip())


# ---- number and duration formatting

def num(x, nd=0):
    """1234.5 -> '1,234.5' with nd decimals; trims a negative zero."""
    s = "{:,.{nd}f}".format(x, nd=nd)
    if s.startswith("-") and float(s.replace(",", "")) == 0:
        s = s[1:]
    return s


def trim(x, nd=2):
    """Format with up to nd decimals, trailing zeros removed."""
    s = "{:.{nd}f}".format(x, nd=nd)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fmt_hm(hours):
    """Hours as 5h15m (minutes rounded)."""
    total = int(round(hours * 60))
    sign = "-" if total < 0 else ""
    total = abs(total)
    return "%s%dh%02dm" % (sign, total // 60, total % 60)


def fmt_dur(seconds):
    """Seconds as the shortest honest form: 42 s, 3m05s, 2h10m, 3d04h."""
    sign = "-" if seconds < 0 else ""
    s = abs(seconds)
    if s < 60:
        return sign + (trim(s, 1) + " s")
    s = int(round(s))
    if s < 3600:
        return "%s%dm%02ds" % (sign, s // 60, s % 60)
    m = int(round(s / 60.0))
    if m < 24 * 60:
        return "%s%dh%02dm" % (sign, m // 60, m % 60)
    h = int(round(s / 3600.0))
    return "%s%dd%02dh" % (sign, h // 24, h % 24)


def fmt_lap(seconds):
    """Seconds as a lap time m:ss.mmm (or h:mm:ss.mmm past an hour)."""
    sign = "-" if seconds < 0 else ""
    ms = int(round(abs(seconds) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    if h:
        return "%s%d:%02d:%02d.%03d" % (sign, h, m, s, ms)
    return "%s%d:%02d.%03d" % (sign, m, s, ms)


# ---- parsing

_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|min|sec|d|h|m|s)?", re.I)
_DUR_UNITS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "min": 60.0, "s": 1.0, "sec": 1.0, "ms": 0.001}


def parse_duration(text, default_unit="s"):
    """'90' (default unit), '45s', '20m', '2h', '2h30m', '1d6h', '1:30' (h:mm), '1:30:15' -> seconds."""
    t = unprotect(str(text).strip()).lower()
    if not t:
        die("empty duration")
    neg = t.startswith("-")
    if neg:
        t = t[1:]
    if re.fullmatch(r"\d+:\d{1,2}(:\d{1,2}(\.\d+)?)?", t):
        parts = t.split(":")
        secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + (float(parts[2]) if len(parts) > 2 else 0.0)
        return -secs if neg else secs
    pos, total, seen = 0, 0.0, False
    for m in _DUR_RE.finditer(t):
        if m.start() != pos and t[pos:m.start()].strip():
            die("duration not understood: '%s' (try 90s, 20m, 2h30m, 1:30)" % text)
        if not m.group(0):
            break
        unit = (m.group(2) or default_unit).lower()
        total += float(m.group(1)) * _DUR_UNITS[unit]
        pos, seen = m.end(), True
    if not seen or t[pos:].strip():
        die("duration not understood: '%s' (try 90s, 20m, 2h30m, 1:30)" % text)
    return -total if neg else total


def parse_laptime(text):
    """'1:42.5', '102.5', '1:02:03.4' -> seconds."""
    t = str(text).strip()
    try:
        parts = [float(p) for p in t.split(":")]
    except ValueError:
        die("lap time not understood: '%s' (try 1:42.5 or 102.5)" % text)
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        die("lap time not understood: '%s' (try 1:42.5 or 102.5)" % text)
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def parse_clock(text):
    """'06:40' or '6.40' or '0640' -> (hour, minute)."""
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(text)) or re.fullmatch(r"\s*(\d{2})(\d{2})\s*", str(text))
    if not m:
        die("clock time not understood: '%s' (use HH:MM)" % text)
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        die("clock time out of range: '%s'" % text)
    return h, mi


def fold(text):
    """Lower-case, strip diacritics, collapse spaces/hyphens/dots to underscores: 'Bielsko-Biala' -> 'bielsko_biala'."""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("\u0142", "l").replace("\u0141", "L").replace("\u00df", "ss").replace("\u00f8", "o").replace("\u00d8", "O")
    t = re.sub(r"[\s\-./']+", "_", t.strip().lower())
    return re.sub(r"_+", "_", t).strip("_")


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


# ---- data files

_cache = {}


def load_data(name, required=True):
    """Load scripts/data/<name>.json once. A broken file is an error, never a silent empty."""
    if name in _cache:
        return _cache[name]
    path = os.path.join(DATA, name + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        if required:
            die("data file missing: scripts/data/%s.json" % name)
        data = None
    except ValueError as e:
        die("data file scripts/data/%s.json is not valid JSON: %s" % (name, e))
    _cache[name] = data
    return data


def unprotect(text):
    """Strip the marker firn.py puts on arguments that start with a minus sign but are not options."""
    t = str(text)
    return t[1:] if t.startswith("@") else t


def out_folder(to):
    """The folder for a file that is to be handed to the driver, or None if there is no such folder.
    'auto' takes the first that exists: the FIRN_OUTPUTS environment variable, /mnt/user-data/outputs,
    then the current folder."""
    if str(to).lower() == "auto":
        cands = [os.environ.get("FIRN_OUTPUTS"), "/mnt/user-data/outputs", os.getcwd()]
        return next((c for c in cands if c and os.path.isdir(c)), None)
    return to if os.path.isdir(to) else None


PERSONAL_FILE = "scripts/data/personal.json"
SETUP_HINT = ("ask where they are, then 'rebuild --home PLACE --work PLACE' writes a new package to upload "
              "(or they can fill in home and work in %s themselves)" % PERSONAL_FILE)
LOG_TYPES = ["journey", "sim", "build", "game", "test", "note"]


_personal = None


def personal():
    """The driver's own file: name, home, work, clocks, own places, checked legs, and this unit's private history.

    Read from the path in the FIRN_PERSONAL environment variable if it is set (so the file can live outside
    the skill and survive updates), else from data/personal.json. Everything in it is optional; a missing
    file means all defaults."""
    global _personal
    if _personal is None:
        path = os.environ.get("FIRN_PERSONAL")
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    _personal = json.load(f)
            except OSError:
                die("FIRN_PERSONAL points at a file that cannot be read: %s" % path)
            except ValueError as e:
                die("the FIRN_PERSONAL file is not valid JSON: %s" % e)
        else:
            _personal = load_data("personal", required=False) or {}
    return _personal


def driver():
    """What to call the driver in tool output: their name if the personal block gives one."""
    return str(personal().get("driver") or "the driver")


# ---- command registry (each module declares its own commands)

REGISTRY = []
SAID = set()        # notes already printed in this call, so that one is not repeated for every leg of a route
GROUPS = [
    ("clock", "Clock"),
    ("ground", "Ground: routes and trips"),
    ("sky", "Sky"),
    ("energy", "Energy and range"),
    ("vehicle", "Vehicle dynamics"),
    ("racing", "Racing"),
    ("combat", "Combat, dice and wargames"),
    ("firn", "FIRN-01"),
    ("garage", "Garage"),
    ("things", "Objects: weight, size and analysis"),
    ("sound", "Sound"),
    ("sl", "Second Life"),
    ("space", "Space"),
    ("desk", "Desk"),
]


def command(sub, group, name, func, summary, examples=()):
    """Add a subcommand with examples in its -h text, and list it in the tool index."""
    import argparse
    epilog = None
    if examples:
        epilog = "examples:\n" + "\n".join("  firn.py " + e for e in examples)
    p = sub.add_parser(name, help=summary, description=summary[:1].upper() + summary[1:] + ".", epilog=epilog,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=func)
    REGISTRY.append((group, name, summary, list(examples)))
    return p


def setup_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
