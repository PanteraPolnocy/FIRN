"""Service and inspection dates: what is overdue, what is due soon, what comes next.

The intervals and the last dates are the driver's own records: the handbook, the last invoice, the
registration papers. This does the calendar and odometer arithmetic and nothing else. It knows no
country's inspection rules; those are looked up, never recalled.

A vehicle on file, under "vehicles" in the personal file:
  {"name": "the estate", "odometer": {"km": 84200, "on": "2026-11-01"}, "km_per_year": 12000,
   "items": [{"what": "inspection", "last": "2026-03-14", "every": "12 months"},
             {"what": "oil and filter", "last": "2026-03-14", "last_km": 78000, "every": "12 months", "every_km": 15000},
             {"what": "insurance", "due": "2027-01-10"}]}
An item is due on a date ("due", or "last" plus "every"), at a distance ("due_km", or "last_km" plus
"every_km"), or both, whichever comes first.
"""
import calendar
import json
import re
from datetime import date, timedelta

from . import chrono, ical
from .core import PERSONAL_FILE, command, die, driver, fold, more, num, personal, rec, trim

_IV_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-z]*)\s*$", re.I)
_IV_UNITS = {"": "month", "m": "month", "mo": "month", "mth": "month", "month": "month", "months": "month",
             "y": "year", "yr": "year", "yrs": "year", "year": "year", "years": "year",
             "w": "week", "wk": "week", "week": "week", "weeks": "week", "d": "day", "day": "day", "days": "day"}
ITEM_KEYS = ("last", "last_km", "every", "every_km", "due", "due_km")
SOON_KM = 1000.0
YEAR_DAYS = 365.25


def parse_interval(text):
    """'12 months', '12m', '12', '2y', '6 weeks', '90d' -> (months, days). A bare number, or m, means months."""
    m = _IV_RE.match(str(text))
    unit = _IV_UNITS.get(m.group(2).lower()) if m else None
    if not unit:
        die("interval not understood: '%s' (try 12 months, 2y, 6 weeks, 90d)" % text)
    n = float(m.group(1))
    if n <= 0:
        die("an interval must be more than nothing: '%s'" % text)
    if unit == "day":
        return 0, int(round(n))
    if unit == "week":
        return 0, int(round(n * 7))
    months = n * (12 if unit == "year" else 1)
    if abs(months - round(months)) > 1e-9:
        die("an interval in months or years must come to whole months: '%s'" % text)
    return int(round(months)), 0


def add_months(d, n):
    """The same day n months on; the last day of the month where that day does not exist."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _interval_words(months, days):
    if months:
        return "%d month%s" % (months, "" if months == 1 else "s")
    return "%d day%s" % (days, "" if days == 1 else "s")


def _a_date(value, what, today):
    d = chrono.parse_date(str(value), today)
    if d is None:
        die("%s is not a date: '%s' (use YYYY-MM-DD)" % (what, value))
    return d


def _a_number(value, what):
    try:
        x = float(str(value).replace(" ", ""))
    except ValueError:
        die("%s is not a number: '%s' (plain digits, no thousands separator)" % (what, value))
    if x < 0:
        die("%s cannot be negative" % what)
    return x


def item_from_text(text):
    """'oil: last=2026-03-14, last_km=78000, every=12m, every_km=15000' -> an item as it would sit on file."""
    name, sep, body = str(text).partition(":")
    if not sep or not name.strip() or not body.strip():
        die("an item looks like  \"oil: last=2026-03-14, every=12 months\"  or  \"insurance: due=2027-01-10\"")
    item = {"what": name.strip()}
    for part in body.split(","):
        if not part.strip():
            continue
        key, eq, val = part.partition("=")
        key = key.strip().lower().replace("-", "_")
        if key == "km":
            key = "last_km"
        if not eq or key not in ITEM_KEYS or not val.strip():
            die("could not read '%s' in item '%s' (keys: %s)" % (part.strip(), name.strip(), ", ".join(ITEM_KEYS)))
        item[key] = _whole(_a_number(val, "%s of '%s'" % (key, name.strip()))) if key.endswith("_km") else val.strip()
    return item


def _whole(x):
    """84200.0 -> 84200, so a figure goes on file the way it would be typed."""
    return int(x) if float(x) == int(x) else x


def assess_item(item, today, odo_now, rate, soon_days):
    """Work out one item. Returns a dict with status (overdue, soon, ok, unknown), the days left and the wording."""
    what = str(item.get("what") or "").strip()
    if not what:
        die("a service item needs a name under \"what\"")
    by_date = basis = None
    if item.get("due"):
        by_date = _a_date(item["due"], "the due date of '%s'" % what, today)
        basis = "a fixed date"
    elif item.get("last") and item.get("every"):
        last = _a_date(item["last"], "the last date of '%s'" % what, today)
        months, days = parse_interval(item["every"])
        by_date = add_months(last, months) if months else last + timedelta(days=days)
        basis = "%s after %s" % (_interval_words(months, days), last.isoformat())
    due_km = None
    if item.get("due_km") is not None and str(item.get("due_km")) != "":
        due_km = _a_number(item["due_km"], "the due distance of '%s'" % what)
    elif item.get("every_km") is not None and item.get("last_km") is not None:
        due_km = _a_number(item["last_km"], "the last distance of '%s'" % what) + _a_number(item["every_km"], "the interval of '%s'" % what)
    if by_date is None and due_km is None:
        return {"what": what, "status": "unknown", "days": None, "when": None, "by": None,
                "text": "%s: no date or distance to work from (give last and every, or due)" % what}
    km_left = km_day = None
    if due_km is not None and odo_now is not None:
        km_left = due_km - odo_now
        if rate and rate > 0:
            km_day = today + timedelta(days=int(round(km_left / rate * YEAR_DAYS)))
    cands = [(d, how) for d, how in ((by_date, "date"), (km_day, "km")) if d is not None]
    when, by = min(cands, key=lambda c: c[0]) if cands else (None, None)
    days = (when - today).days if when is not None else None
    over = (by_date is not None and by_date < today) or (km_left is not None and km_left < 0)
    soon = (days is not None and days <= soon_days) or (km_left is not None and km_left <= SOON_KM)
    status = "overdue" if over else "soon" if soon else "ok"
    parts = []
    if by_date is not None:
        gap = (by_date - today).days
        if gap < 0:
            parts.append("was due %s, %d day%s ago" % (by_date.isoformat(), -gap, "" if gap == -1 else "s"))
        elif gap == 0:
            parts.append("due today, %s" % by_date.isoformat())
        else:
            parts.append("due %s, in %d day%s" % (by_date.isoformat(), gap, "" if gap == 1 else "s"))
    if due_km is not None:
        lead = "due " if by_date is None else "or "
        if km_left is None:
            parts.append("%sat %s km (no odometer reading on file to measure against)" % (lead, num(due_km)))
        elif km_left < 0:
            parts.append("%s%s km past its %s km mark" % ("" if by_date is None else "and ", num(-km_left), num(due_km)))
        else:
            guess = ", about %s at this mileage" % km_day.isoformat() if km_day is not None else ""
            parts.append("%sat %s km, %s km to go%s" % (lead, num(due_km), num(km_left), guess))
    text = "%s: %s" % (what, " ".join(parts))
    if by_date is not None and due_km is not None and km_day is not None and not over:
        text += "; the %s comes first" % ("date" if by == "date" else "distance")
    tags = []
    if basis and basis != "a fixed date":
        tags.append(basis)
    if km_day is not None:
        tags.append("distance figures are estimates")
    if tags:
        text += " [%s]" % "; ".join(tags)
    # the same facts without "in N days", for a calendar entry that will be read later
    note = []
    if by_date is not None:
        note.append("due %s%s" % (by_date.isoformat(), " (%s)" % basis if basis and basis != "a fixed date" else ""))
    if due_km is not None:
        note.append("at %s km%s" % (num(due_km), " (about %s at %s km a year: an estimate)" % (km_day.isoformat(), num(rate))
                                    if km_day is not None else ""))
    note = "%s: %s%s." % (what, " or ".join(note), ", whichever comes first" if len(note) == 2 else "")
    return {"what": what, "status": status, "days": days, "when": when, "by": by, "text": text, "km_left": km_left, "note": note}


def assess_vehicle(v, today, soon_days):
    """(heading line, rows) for one vehicle on file."""
    name = str(v.get("name") or "the vehicle")
    odo = v.get("odometer") or {}
    rate = v.get("km_per_year")
    rate = _a_number(rate, "km_per_year of %s" % name) if rate not in (None, "") else None
    odo_now, head = None, name
    if odo.get("km") is not None:
        km = _a_number(odo["km"], "the odometer of %s" % name)
        odo_now = km
        head += " | %s km" % num(km)
        if odo.get("on"):
            on = _a_date(odo["on"], "the odometer date of %s" % name, today)
            head += " on %s" % on.isoformat()
            gone = (today - on).days
            if rate and gone > 0:
                odo_now = km + rate * gone / YEAR_DAYS
                head += "; about %s km today at %s km a year [estimate]" % (num(odo_now), num(rate))
            elif gone > 60:
                head += "; that reading is %d days old and no yearly mileage is on file, so distances may be out" % gone
    elif rate:
        head += " | no odometer reading on file"
    rows = [assess_item(it, today, odo_now, rate, soon_days) for it in (v.get("items") or [])]
    order = {"overdue": 0, "soon": 1, "ok": 2, "unknown": 3}
    rows.sort(key=lambda r: (order[r["status"]], r["days"] if r["days"] is not None else 10 ** 6))
    return head, rows


def vehicles_on_file():
    return [v for v in (personal().get("vehicles") or []) if isinstance(v, dict)]


def boot_line(today, soon_days=30):
    """One short line for the boot record, or None when no vehicle is on file."""
    fleet = vehicles_on_file()
    if not fleet:
        return None
    hot, nxt = [], None
    for v in fleet:
        name = str(v.get("name") or "the vehicle")
        _, rows = assess_vehicle(v, today, soon_days)
        for r in rows:
            if r["status"] in ("overdue", "soon"):
                hot.append("%s%s, %s" % ("OVERDUE - " if r["status"] == "overdue" else "", name, r["text"].split(" [")[0]))
            elif r["status"] == "ok" and r["when"] is not None and (nxt is None or r["when"] < nxt[0]):
                nxt = (r["when"], name, r["what"])
    if hot:
        return "; ".join(hot) + ". Say it once, plainly; 'service' has the detail"
    if nxt:
        return "nothing due in the next %d days; next is %s on %s, %s" % (soon_days, nxt[2], nxt[1], nxt[0].isoformat())
    return "nothing with a date on file for %s" % ", ".join(str(v.get("name") or "the vehicle") for v in fleet)


TEMPLATE = {
    "name": "the estate",
    "odometer": {"km": 84200, "on": "2026-11-01"},
    "km_per_year": 12000,
    "items": [
        {"what": "inspection", "last": "2026-03-14", "every": "12 months"},
        {"what": "oil and filter", "last": "2026-03-14", "last_km": 78000, "every": "12 months", "every_km": 15000},
        {"what": "insurance", "due": "2027-01-10"},
    ],
}


def _paste(vehicle):
    """Print a vehicle the way it sits on file: its own figures on one line, then one item to a line."""
    rec("PASTE", "into \"vehicles\" in %s, to keep it:" % PERSONAL_FILE)
    head = [(k, vehicle[k]) for k in ("name", "odometer", "km_per_year") if vehicle.get(k) is not None]
    first = ", ".join("%s: %s" % (json.dumps(k), json.dumps(v, ensure_ascii=False)) for k, v in head)
    items = vehicle.get("items") or []
    print("    {%s%s\"items\": [" % (first, ", " if first else ""))
    for n, item in enumerate(items):
        print("      %s%s" % (json.dumps(item, ensure_ascii=False), "," if n < len(items) - 1 else ""))
    print("    ]}")


def cmd_service(a):
    today = chrono.now_in(chrono.home_tz()).date()
    if a.template:
        _paste(TEMPLATE)
        rec("FIELDS", "last + every (12 months, 2y, 6 weeks, 90d) and/or last_km + every_km; or a fixed due date or due_km")
        rec("NEXT", "edit the figures to match the handbook and the last invoice, then re-upload the skill")
        return
    if a.soon < 0:
        die("--soon is a number of days, zero or more")
    if a.item:
        v = {"name": a.name or "the vehicle", "items": [item_from_text(t) for t in a.item]}
        if a.odo is not None:
            v["odometer"] = {"km": _whole(a.odo), "on": _a_date(a.odo_date or "today", "--odo-date", today).isoformat()}
        if a.km_year is not None:
            v["km_per_year"] = _whole(a.km_year)
        fleet, adhoc = [v], True
    else:
        fleet, adhoc = vehicles_on_file(), False
        if a.vehicle:
            want = fold(a.vehicle)
            fleet = [v for v in fleet if want in fold(str(v.get("name") or ""))]
            if not fleet:
                die("no vehicle on file matches '%s'" % a.vehicle)
        if not fleet:
            rec("SERVICE", "no vehicle on file. 'service --template' prints a block to fill in and paste into %s," % PERSONAL_FILE)
            more("or work one out now: service --item \"inspection: last=2026-03-14, every=12 months\"")
            return
    entries, dated, guessed = [], 0, False
    for v in fleet:
        head, rows = assess_vehicle(v, today, a.soon)
        rec("VEHICLE", head)
        if not rows:
            more("no items on file for it")
        for r in rows:
            key = {"overdue": "OVERDUE", "soon": "DUE SOON", "ok": "LATER", "unknown": "UNKNOWN"}[r["status"]]
            rec(key, r["text"])
            if r["when"] is not None:
                dated += 1
                if r["when"] >= today:
                    name = str(v.get("name") or "the vehicle")
                    guessed = guessed or r["by"] == "km"
                    entries.append(ical.event("%s: %s due" % (name[:1].upper() + name[1:], r["what"]), r["when"],
                                              description=r["note"] + "\nFrom the driver's own records: the handbook and the law decide, not this file.",
                                              alarm=timedelta(days=a.warn_days) if a.warn_days > 0 else None))
    rec("TODAY", "%s; 'due soon' means within %d days or %s km" % (today.isoformat(), a.soon, num(SOON_KM)))
    rec("NOTE", "these are %s's own intervals and dates. The handbook and the law where the vehicle is registered decide what is "
                "required: look the current rule up before stating one" % driver())
    if adhoc:
        _paste(fleet[0])
        rec("OR", "rebuild --vehicle \"%s\" --item \"%s / ...\" for each item writes a new package with it on file" % (
            fleet[0]["name"], fleet[0]["name"]))
    if a.ics:
        if not entries:
            die("nothing still ahead has a date to put in a calendar" if dated else "nothing on file has a date to put in a calendar")
        ical.deliver(a, entries, "service-%s" % today.isoformat(), estimate=guessed)


def register(sub):
    p = command(sub, "garage", "service", cmd_service,
                "service and inspection dates from the driver's own records: overdue, due soon, later; a calendar file",
                ["service", "service --template",
                 'service --item "inspection: last=2026-03-14, every=12 months" --item "insurance: due=2027-01-10"',
                 'service --item "oil: last=2026-03-14, last_km=78000, every=12m, every_km=15000" --odo 84200 --odo-date 2026-11-01 --km-year 12000',
                 "service --soon 60 --ics auto"])
    p.add_argument("--vehicle", help="one vehicle on file, by name")
    p.add_argument("--item", action="append", metavar="\"NAME: key=value, ...\"",
                   help="work an item out now instead of reading the file; keys: last, every, last_km, every_km, due, due_km")
    p.add_argument("--name", help="what to call the vehicle the --item lines belong to")
    p.add_argument("--odo", type=float, help="odometer reading for the --item lines, km")
    p.add_argument("--odo-date", help="when that reading was taken (default: today)")
    p.add_argument("--km-year", type=float, help="distance driven in a year, to turn a distance into a date")
    p.add_argument("--soon", type=int, default=30, help="how many days ahead counts as due soon (default 30)")
    p.add_argument("--template", action="store_true", help="print a block to fill in and paste into the personal file")
    p.add_argument("--warn-days", type=int, default=14, help="days of warning in the calendar file (default 14; 0 for none)")
    ical.add_option(p, "every date still ahead, as all-day entries", alarm=False)
