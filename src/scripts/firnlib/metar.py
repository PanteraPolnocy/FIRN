"""Airport weather reports (METAR) decoded, then read for the road.

A METAR is the one kind of live weather that is published as plain text for almost every airport in the
gazetteer, and it decodes without guesswork. FIRN finds the report with search; this reads it. It is still an
airport's weather, not the road's: say where the report came from and how old it is.
"""
import re
from datetime import datetime, timedelta

from . import chrono, geo
from .core import command, die, fmt_hm, num, rec, trim, unprotect
from .logistics import road_flags

DESC = {"MI": "shallow", "BC": "patches of", "PR": "partial", "DR": "low drifting", "BL": "blowing", "SH": "showers of",
        "TS": "thunderstorm with", "FZ": "freezing"}
PHEN = {"DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains", "IC": "ice crystals", "PL": "ice pellets", "GR": "hail",
        "GS": "small hail", "UP": "precipitation of an unknown kind", "BR": "mist", "FG": "fog", "FU": "smoke", "VA": "volcanic ash",
        "DU": "dust", "SA": "sand", "HZ": "haze", "PY": "spray", "PO": "dust whirls", "SQ": "squalls", "FC": "a funnel cloud",
        "SS": "a sandstorm", "DS": "a duststorm"}
CLOUD = {"FEW": "few", "SCT": "scattered", "BKN": "broken", "OVC": "overcast", "VV": "sky hidden, vertical visibility"}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
WET = ("DZ", "RA", "UP")
WHITE = ("SN", "SG", "PL", "GS", "IC")

_TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")
_WIND_RE = re.compile(r"^(VRB|\d{3}|///)(\d{2,3}|//)(?:G(\d{2,3}))?(KT|MPS|KMH)$")
_VAR_RE = re.compile(r"^(\d{3})V(\d{3})$")
_VIS_RE = re.compile(r"^(\d{4})(NDV|[NSEW]{1,2})?$")
_SM_RE = re.compile(r"^(M)?(\d+)?(?:(\d)/(\d{1,2}))?SM$")
_WX_RE = re.compile(r"^(\+|-|VC)?((?:MI|BC|PR|DR|BL|SH|TS|FZ)*)((?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$")
_CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC|VV)(\d{3}|///)(CB|TCU|///)?$")
_TEMP_RE = re.compile(r"^(M?\d{2}|//)/(M?\d{2}|//)?$")
_SPEED = {"KT": 1.852, "MPS": 3.6, "KMH": 1.0}


def _deg(text):
    return -int(text[1:]) if text.startswith("M") else int(text)


def _pairs(code):
    return [code[i:i + 2] for i in range(0, len(code), 2)]


def weather_words(token):
    """'-SHRA' -> ('light showers of rain', ['SH'], ['RA']), or None if the token is not a weather group."""
    m = _WX_RE.match(token)
    if not m or not (m.group(2) or m.group(3)):
        return None
    desc, phen = _pairs(m.group(2)), _pairs(m.group(3))
    words = [DESC[d] for d in desc] + [" and ".join(PHEN[p] for p in phen)] if phen else [DESC[d] for d in desc]
    text = " ".join(w for w in words if w)
    if not phen:
        text = text.replace("showers of", "showers").replace("thunderstorm with", "thunderstorm").replace("patches of", "patches")
    lead = {"+": "heavy ", "-": "light ", "VC": ""}.get(m.group(1) or "", "")
    return lead + text + (" in the vicinity" if m.group(1) == "VC" else ""), desc, phen


def decode(text, now):
    """A METAR as a dict of what it says. Unknown groups are kept in 'unread' rather than guessed at."""
    tokens = [unprotect(t) for t in str(text).upper().replace("=", " ").split()]
    out = {"station": None, "time": None, "wind": None, "var": None, "vis_m": None, "cavok": False, "weather": [], "desc": [],
           "phen": [], "cloud": [], "temp": None, "dew": None, "qnh": None, "notes": [], "unread": []}
    i = 0
    while i < len(tokens) and tokens[i] in ("METAR", "SPECI", "COR", "AUTO"):
        i += 1
    if i < len(tokens) and re.match(r"^[A-Z][A-Z0-9]{3}$", tokens[i]) and not _TIME_RE.match(tokens[i]):
        out["station"] = tokens[i]
        i += 1
    while i < len(tokens):
        t = tokens[i]
        i += 1
        if t in ("AUTO", "COR", "NIL"):
            continue
        if t == "RMK":
            out["notes"].append("remarks follow and are not decoded")
            break
        if t in ("BECMG", "TEMPO"):
            out["notes"].append("a short forecast follows the report (%s): read the original for it" % t)
            break
        if t == "NOSIG":
            out["notes"].append("no significant change expected in the next two hours")
            continue
        m = _TIME_RE.match(t)
        if m and out["time"] is None:
            day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (1 <= day <= 31 and hour <= 23 and minute <= 59):
                die("the time group '%s' is not a day, hour and minute" % t)
            when = None
            year, month = now.year, now.month
            for _ in range(3):
                try:
                    cand = datetime(year, month, day, hour, minute, tzinfo=chrono.UTC)
                    if cand <= now + timedelta(hours=2):
                        when = cand
                        break
                except ValueError:
                    pass
                month -= 1
                if month == 0:
                    year, month = year - 1, 12
            out["time"] = when
            continue
        m = _WIND_RE.match(t)
        if m and out["wind"] is None:
            k = _SPEED[m.group(4)]
            calm = m.group(2).isdigit() and int(m.group(2)) == 0
            out["wind"] = {"dir": None if m.group(1) in ("VRB", "///") else int(m.group(1)), "vrb": m.group(1) == "VRB", "calm": calm,
                           "kmh": int(m.group(2)) * k if m.group(2).isdigit() else None,
                           "gust": int(m.group(3)) * k if m.group(3) else None, "raw": t}
            continue
        m = _VAR_RE.match(t)
        if m:
            out["var"] = (int(m.group(1)), int(m.group(2)))
            continue
        if t == "CAVOK":
            out["cavok"], out["vis_m"] = True, 10000
            continue
        m = _VIS_RE.match(t)
        if m and out["vis_m"] is None and out["temp"] is None:
            out["vis_m"] = int(m.group(1))
            continue
        if re.match(r"^\d{4}[NSEW]{1,2}$", t):
            continue
        if t.isdigit() and i < len(tokens) and _SM_RE.match(tokens[i]) and "/" in tokens[i]:
            t = t + tokens[i]
            m = re.match(r"^(\d+)(\d)/(\d{1,2})SM$", t)
            i += 1
            if m:
                out["vis_m"] = int(round((int(m.group(1)) + int(m.group(2)) / float(m.group(3))) * 1609.344))
                continue
        m = _SM_RE.match(t)
        if m and (m.group(2) or m.group(3)):
            miles = float(m.group(2) or 0) + (int(m.group(3)) / float(m.group(4)) if m.group(3) else 0.0)
            out["vis_m"] = int(round(miles * 1609.344))
            continue
        if re.match(r"^R\d{2}[LRC]?/", t):
            out["notes"].append("a runway visual range is given (%s): low visibility on the ground" % t)
            continue
        if t in ("NSC", "SKC", "CLR", "NCD"):
            out["cloud"].append("no cloud of note")
            continue
        if t == "NSW":
            continue
        m = _CLOUD_RE.match(t)
        if m:
            if m.group(2) == "///":
                out["cloud"].append("%s, height not measured" % CLOUD[m.group(1)])
            else:
                feet = int(m.group(2)) * 100
                extra = {"CB": ", cumulonimbus (storm cloud)", "TCU": ", towering cumulus"}.get(m.group(3) or "", "")
                out["cloud"].append("%s at %s m (%s ft)%s" % (CLOUD[m.group(1)], num(round(feet * 0.3048, -1)), num(feet), extra))
            continue
        m = _TEMP_RE.match(t)
        if m and out["temp"] is None and m.group(1) != "//":
            out["temp"] = _deg(m.group(1))
            if m.group(2) and m.group(2) != "//":
                out["dew"] = _deg(m.group(2))
            continue
        m = re.match(r"^Q(\d{4})$", t)
        if m:
            out["qnh"] = float(m.group(1))
            continue
        m = re.match(r"^A(\d{4})$", t)
        if m:
            out["qnh"] = int(m.group(1)) / 100.0 * 33.8639
            continue
        if t.startswith("RE") and weather_words(t[2:]):
            out["notes"].append("recently: %s" % weather_words(t[2:])[0])
            continue
        wx = weather_words(t)
        if wx:
            out["weather"].append(wx[0])
            out["desc"] += wx[1]
            out["phen"] += wx[2]
            continue
        out["unread"].append(t)
    return out


def cmd_metar(a):
    now = chrono.now_in(chrono.UTC)
    text = " ".join(a.report)
    d = decode(text, now)
    if d["temp"] is None and d["wind"] is None and d["vis_m"] is None:
        die("that does not read as a METAR. One looks like:  EPKT 101330Z 27012G22KT 9999 -SN BKN030 M01/M03 Q1015")
    place = geo.find_station(d["station"]) if d["station"] else None
    if d["station"]:
        rec("STATION", "%s%s" % (d["station"], " %s [gazetteer]" % place["name"] if place else " (not in the gazetteer)"))
    if d["time"] is not None:
        age = (now - d["time"]).total_seconds() / 3600.0
        local = ""
        if place and place.get("tz"):
            local = ", %s at the airport" % d["time"].astimezone(chrono.get_tz(place["tz"])).strftime("%H:%M")
        old = "" if age < 1.5 else " - OLD: reports come out every half hour or hour, so find the current one"
        rec("OBSERVED", "%s UTC%s; %s ago [as reported]%s" % (d["time"].strftime("%Y-%m-%d %H:%M"), local, fmt_hm(max(0.0, age)), old))
    wind_kmh = None
    w = d["wind"]
    if w:
        if w["calm"]:
            line = "calm"
        elif w["kmh"] is None:
            line = "not reported"
        else:
            wind_kmh = w["gust"] or w["kmh"]
            where = "variable in direction" if w["vrb"] else ("from %03d deg (%s)" % (w["dir"], COMPASS[int((w["dir"] % 360 + 11.25) // 22.5) % 16])
                                                             if w["dir"] is not None else "direction not reported")
            line = "%s at %s km/h%s" % (where, trim(w["kmh"], 0), ", gusting %s km/h" % trim(w["gust"], 0) if w["gust"] else "")
            if d["var"]:
                line += "; swinging between %03d and %03d deg" % d["var"]
        rec("WIND", "%s [%s]" % (line, w["raw"]))
    vis = d["vis_m"]
    if vis is not None:
        rec("VISIBILITY", "10 km or more%s" % (" (CAVOK: no cloud below 1,500 m, no weather of note)" if d["cavok"] else "")
            if vis >= 9999 else "%s m" % num(vis))
    if d["weather"]:
        rec("WEATHER", "; ".join(d["weather"]))
    if d["cloud"]:
        rec("CLOUD", "; ".join(d["cloud"]))
    if d["temp"] is not None:
        rec("AIR", "%s C%s" % (d["temp"], ", dew point %s C" % d["dew"] if d["dew"] is not None else ""))
    if d["qnh"] is not None:
        rec("PRESSURE", "%s hPa" % num(d["qnh"]))
    for n in d["notes"]:
        rec("NOTE", n)
    if d["unread"]:
        rec("UNREAD", "%s (not decoded: read the original for these)" % " ".join(d["unread"]))
    flags = []
    phen, desc = d["phen"], d["desc"]
    freezing = "FZ" in desc and any(p in phen for p in ("RA", "DZ", "UP"))
    wet = any(p in phen for p in WET)
    snow = any(p in phen for p in WHITE)
    if freezing:
        flags.append("FREEZING RAIN OR DRIZZLE REPORTED: glaze ice on anything untreated, whatever the thermometer says")
    if "FZ" in desc and "FG" in phen:
        flags.append("freezing fog: it lays ice on the road and on the windscreen")
    if "TS" in desc:
        flags.append("thunderstorm: sudden heavy rain, gusts and standing water; hail is possible")
    if any(p in phen for p in ("GR", "GS")):
        flags.append("hail: slow right down, it is ball bearings on the road")
    if snow:
        flags.append("snow or ice falling: the surface may be covered; leave room, brake early, and gently")
    if vis is not None and vis < 200:
        flags.append("dense fog, under 200 m: at 50 km/h that is about 14 seconds of road")
    elif vis is not None and vis < 1000:
        flags.append("fog, under 1 km: dipped lights, fog lights if fitted, and the speed your eyes can stop in")
    elif vis is not None and vis < 5000:
        flags.append("reduced visibility, under 5 km")
    if d["temp"] is not None:
        flags += [f for f in road_flags(d["temp"], d["dew"], d["temp"], wind_kmh, wet or snow) if f not in flags]
    for f in flags:
        rec("ROAD", f)
    if not flags and d["temp"] is not None:
        rec("ROAD", "nothing in this report calls for more than ordinary care")
    elif d["temp"] is None:
        rec("ROAD", "no temperature in the report, so ice and fog could not be judged")
    rec("SOURCE", "an airport's report, not the road's: bridges, hollows and higher ground nearby can differ. Say where it came from "
                  "and how old it is; it is not a sensor reading of yours")


def register(sub):
    p = command(sub, "sky", "metar", cmd_metar, "decode an airport weather report (METAR) and read it for the road: ice, fog, wind, wet",
                ['metar "EPKT 101300Z 27012G22KT 9999 -SN BKN030 OVC045 M01/M03 Q1015 NOSIG"',
                 'metar "KMSP 101253Z 32015G28KT 1 1/2SM -FZRA BR OVC008 M02/M03 A2992 RMK AO2"',
                 'metar "EGLL 101320Z VRB03KT CAVOK 12/06 Q1022"'])
    p.add_argument("report", nargs="+", help="the report, in quotes, as published (it starts with the airport's four-letter code)")
