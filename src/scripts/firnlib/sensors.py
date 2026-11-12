"""Sensors for the simulation table: what FIRN-01 can make out, at what range, in what air and light.

Game mechanics only, like the weapons table: each sensor has a reach, the target, the air, the light and
cover scale it, and the distance decides how much is known - that something is there, what kind of thing,
which one, and what state it is in. Near the edge of a reach it takes a roll. The figures are the maker's
(data/sensors.json) and model no real sensor; a brief that names its own figures outranks them.

In a real conversation FIRN has no sensors at all (SKILL.md section 8). This is for sims, where the brief
gives him his: it keeps him from knowing more than he could, which is the same honesty as the ledger.
"""
from . import dice
from .core import command, die, load_data, more, num, rec, table, trim

ORDER = ("detect", "classify", "identify", "read")


def rules():
    return load_data("sensors")


def _factor(table_, key, sensor, default=1.0):
    return float(table_.get(key, {}).get(sensor, default))


def reach_of(sensor, target, air, light, cover, states, own, data):
    """(effective reach in metres, notes) for one sensor against one target, or (None, why) when it is switched off."""
    s = data["sensors"][sensor]
    notes = []
    if "silent" in own and sensor in data["own"]["silent"]["off"]:
        return None, "off: silent running"
    r = float(s["reach"]) * float(data.get("scale", 1.0))
    r *= float(data["targets"][target].get(sensor, 1.0))
    if sensor == "receiver" and "emitting" not in states:
        return 0.0, ["the target sends nothing out"]
    air_f = _factor(data["air"], air, sensor)
    if "smoke" in own:
        thick = _factor(data["air"], data["own"]["smoke"]["air"], sensor)
        if thick < air_f:
            air_f = thick
            notes.append("his own smoke")
    r *= air_f
    r *= _factor(data["light"], light, sensor)
    r *= _factor(data["cover"], cover, sensor)
    for st in states:
        r *= float(data["state"][st].get(sensor, 1.0))
    if cover == "thin" and sensor in ("thermal", "radar") and r > 0:
        # through a light wall these two still read, weakly, and only close to
        r = min(r, float(data["cover"]["thin_reach_m"]))
        notes.append("through a thin wall")
    return r, notes


def levels_at(reach, best, dist_m, data):
    """For one sensor: (levels known for certain, levels on a roll, levels on a glimpse)."""
    edge = data["edge"]
    sure, roll, glimpse = [], [], []
    for level in ORDER[:ORDER.index(best) + 1]:
        r = reach * float(data["levels"][level]["share"])
        if r <= 0:
            continue
        if dist_m <= r * edge["sure"]:
            sure.append(level)
        elif dist_m <= r:
            roll.append(level)
        elif dist_m <= r * edge["glimpse"]:
            glimpse.append(level)
    return sure, roll, glimpse


def _top(levels):
    return max(levels, key=ORDER.index) if levels else None


def cmd_scan(a):
    data = rules()
    label = data["label"]
    if a.list:
        rows = [(k, "%s m" % num(s["reach"] * data.get("scale", 1.0)), s["best"], "sends a signal" if s["active"] else "listens only", s["is"])
                for k, s in data["sensors"].items()]
        rec("SENSORS", "%d in the %s; reach is against a car in clear air by day" % (len(rows), label))
        table(rows, header=("sensor", "reach", "tells at best", "", "what"), indent=2, right=(1,))
        for level in ORDER:
            lv = data["levels"][level]
            rec(level.upper(), "%s. Of a machine or a building: %s" % (lv["within"], lv["thing"]))
            more("of a person or an animal: %s" % lv["living"])
        rec("TARGETS", ", ".join("%s (%s)" % (k, v["is"]) for k, v in data["targets"].items()))
        rec("AIR", ", ".join(k for k in data["air"] if k != "note"))
        rec("LIGHT", ", ".join(k for k in data["light"] if k != "note"))
        rec("COVER", "%s: %s" % (", ".join(k for k, v in data["cover"].items() if isinstance(v, dict)), data["cover"]["note"]))
        rec("HIMSELF", "%s; %s; %s" % (data["own"]["silent"]["why"], data["own"]["smoke"]["why"], data["own"]["veil"]["why"]))
        rec("PORT", "the sample port in the cabin: %s. 'scan --port' for what it tells" % data["port"]["rule"])
        rec("STATE", ", ".join("%s (%s)" % (k, v["means"]) for k, v in data["state"].items()))
        rec("EDGE", data["edge"]["note"])
        rec("NOTE", "game mechanics for sims, yours to edit in scripts/data/sensors.json. In a real conversation there are no sensors: "
                    "use 'analyse' for a picture or a description")
        return
    if a.port:
        port = data["port"]
        rec("PORT", "the sample port in the cabin: %s [lore]" % port["rule"])
        rec("TELLS", "%s, in about %s [lore]" % (port["tells"], "a minute" if port["seconds"] == 60 else "%d s" % port["seconds"]))
        rec("NOT", "%s: no figure for those, and he does not guess" % port["not"])
        rec("BOOK IT", "the wait is a cost like any other: lattice --state ... wait=%ds" % port["seconds"])
        rec("RULE", "the port says what a thing is; what the sample turns out to be is the brief's to decide, or the driver's. "
                    "Ask, or roll for it, before you report a result")
        return
    if not a.target:
        die("scan what? One of: %s ('scan --list')" % ", ".join(data["targets"]))
    target = a.target.lower()
    if target not in data["targets"]:
        die("a target is one of: %s" % ", ".join(data["targets"]))
    if a.range is None or a.range <= 0:
        die("scan needs the distance: --range 1200 (metres)")
    for name, value, table_ in (("--air", a.air, data["air"]), ("--light", a.light, data["light"]), ("--cover", a.cover, data["cover"])):
        if not isinstance(table_.get(value), dict):
            die("%s is one of: %s" % (name, ", ".join(k for k, v in table_.items() if isinstance(v, dict))))
    states = [s.lower() for s in (a.state or [])]
    for s in states:
        if s not in data["state"]:
            die("a state is one of: %s" % ", ".join(data["state"]))
    for x, y in (("hot", "cold"), ("moving", "still"), ("loud", "quiet")):
        if x in states and y in states:
            die("%s and %s cannot both be true" % (x, y))
    if a.silent and a.veil:
        die("silent running and the Veil exclude each other: the Veil lights the bar")
    own = [w for w, on in (("silent", a.silent), ("veil", a.veil), ("smoke", a.smoke)) if on]
    wanted = [s.lower() for s in (a.only or data["sensors"])]
    for s in wanted:
        if s not in data["sensors"]:
            die("a sensor is one of: %s" % ", ".join(data["sensors"]))
    scene = [a.air if a.air != "clear" else "clear air", "by %s" % a.light if a.light in ("day", "night") else "at dusk" if a.light == "dusk" else "in the dark"]
    if a.cover != "open":
        scene.append({"partial": "partly covered", "thin": "behind a thin wall or a vehicle's skin"}.get(a.cover, "hidden behind something solid"))
    if states:
        scene.append(", ".join(data["state"][s]["is"] for s in states))
    rec("TARGET", "%s, %s m off; %s [%s]" % (data["targets"][target]["is"], num(a.range), "; ".join(scene), label))
    kind = "living" if data["targets"][target].get("living") else "thing"

    def knows(level):
        return data["levels"][level][kind]
    for w in own:
        rec("HIMSELF", data["own"][w]["why"])
    p_roll = dice.at_least(dice.distribution(dice.parse(data["edge"]["dice"])), data["edge"]["roll"])
    p_glimpse = dice.at_least(dice.distribution(dice.parse(data["edge"]["dice"])), data["edge"]["glimpse_roll"])
    miss = dict((level, 1.0) for level in ORDER)        # chance that no sensor gets this level on this look
    certain = set()
    active_on = []
    per = {}
    for name in wanted:
        s = data["sensors"][name]
        r, notes = reach_of(name, target, a.air, a.light, a.cover, states, own, data)
        if r is None:
            rec(name.upper(), notes)
            continue
        if s["active"]:
            active_on.append(name)
        if name == "receiver" and r == 0:
            rec(name.upper(), "nothing to hear: the target sends nothing out")
            continue
        sure, roll, glimpse = levels_at(r, s["best"], a.range, data)
        per[name] = (sure, roll, glimpse)
        for level in sure:
            certain.add(level)
        for level in roll:
            miss[level] *= 1.0 - p_roll
        for level in glimpse:
            miss[level] *= 1.0 - p_glimpse
        parts = []
        if sure:
            parts.append("sure of: %s" % _top(sure))
        if roll:
            parts.append("on a %d+: %s" % (data["edge"]["roll"], _top(roll)))
        if glimpse:
            parts.append("a glimpse on %d+: %s" % (data["edge"]["glimpse_roll"], _top(glimpse)))
        if not parts:
            parts.append("nothing at this range")
        capped = _top(sure) == s["best"] and s["best"] != "read"
        rec(name.upper(), "reach %s m%s: %s%s" % (
            num(r), " (%s)" % ", ".join(notes) if notes else "", "; ".join(parts),
            " (the most a %s can tell)" % s["is"].split(",")[0] if capped else ""))
    known = _top(certain)
    if known:
        rec("KNOWN", "%s [%s, for certain]" % (knows(known), known))
    else:
        rec("KNOWN", "nothing for certain at this range")
    beyond = [level for level in ORDER if level not in certain and miss[level] < 1.0 and (known is None or ORDER.index(level) > ORDER.index(known))]
    for level in beyond:
        rec("CHANCE", "%s [%s: %s on this look]" % (knows(level), level, dice.pct(1.0 - miss[level])))
    top_possible = _top(list(certain) + beyond)
    not_known = [level for level in ORDER if top_possible is None or ORDER.index(level) > ORDER.index(top_possible)]
    if not_known:
        rec("NOT KNOWN", "nothing at the level of %s: do not report any" % " or ".join(not_known))
    if a.roll:
        rng = dice.make_rng(a.seed)
        total, shown = dice.roll_once(dice.parse(data["edge"]["dice"]), rng)
        got = set(certain)
        for name, (sure, roll, glimpse) in per.items():
            if total >= data["edge"]["roll"]:
                got.update(roll)
            if total >= data["edge"]["glimpse_roll"]:
                got.update(glimpse)
        best = _top(got)
        rec("ROLL", "%s = %d: %s" % (shown, total, "%s [%s]" % (knows(best), best) if best else "nothing made out"))
        rec("SEED", "%d (repeatable)" % a.seed if a.seed is not None else "none: system randomness, not repeatable")
    if active_on:
        far = max(data["sensors"][n]["reach"] for n in active_on) * data.get("scale", 1.0) * data["own"]["seen_by"]
        rec("GIVES AWAY", "%s send%s out a signal: anything that listens can hear it out to about %s m, %s as far as it sees. "
                          "Silent running switches %s off" % (
                              " and ".join(active_on), "s" if len(active_on) == 1 else "", num(far),
                              "twice" if data["own"]["seen_by"] == 2 else "%s times" % trim(data["own"]["seen_by"], 1),
                              "it" if len(active_on) == 1 else "them"))
    rec("RULES", "%s: game mechanics, not a model of any real sensor. Report what the level allows and no more; a brief that gives "
                 "its own figures outranks these" % label)


def register(sub):
    p = command(sub, "combat", "scan", cmd_scan,
                "what FIRN-01's sensors make out in a sim: by range, air, light and cover, what is known for certain and what takes a roll",
                ["scan --list", "scan vehicle --range 1200 --air fog --light night --state hot moving",
                 "scan person --range 80 --cover partial --light dark --silent", "scan person --range 20 --cover thin --state quiet",
                 "scan drone --range 500 --only radar acoustic --state loud --roll --seed 4", "scan --port"])
    p.add_argument("target", nargs="?", help="person, animal, vehicle, heavy, armour, drone, aircraft or structure")
    p.add_argument("--range", type=float, help="distance to it, m")
    p.add_argument("--air", default="clear", help="clear, rain, snow, fog, dust, smoke, thick")
    p.add_argument("--light", default="day", help="day, dusk, night, dark")
    p.add_argument("--cover", default="open", help="open, partial (a hedge, a window), thin (a light wall, a vehicle's skin), hidden (a solid wall)")
    p.add_argument("--state", nargs="+", help="what the target is doing: hot, cold, moving, still, loud, quiet, emitting")
    p.add_argument("--silent", action="store_true", help="he is running silent: nothing that sends out a signal is on")
    p.add_argument("--veil", action="store_true", help="his Veil is up: it costs him no sight, and it rules out silent running")
    p.add_argument("--smoke", action="store_true", help="he is inside his own smoke")
    p.add_argument("--port", action="store_true", help="the sample port in the cabin: what it tells of a sample, and how long it takes")
    p.add_argument("--only", nargs="+", help="use only these sensors")
    p.add_argument("--roll", action="store_true", help="roll the look")
    p.add_argument("--seed", type=int, help="fixed seed, to repeat a roll")
    p.add_argument("--list", action="store_true", help="the sensors, the targets and everything that scales a reach")
