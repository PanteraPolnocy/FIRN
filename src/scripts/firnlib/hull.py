"""The hull as a tool: the Keen, his one fitted weapon, and what he can ram through.

Every figure is the maker's (lore.json). Both tools are for simulations: what it does, how far, and what it costs.
The ledger books them (lattice ... keen=high:2 / ram=brick@70).
"""
from .core import command, die, load_data, more, rec, trim

# what the Keen is pointed at: (how it is named, the setting that does the job, what happens)
KEEN_TARGETS = {
    "camera": ("a camera", "low", "blind"), "lidar": ("a lidar", "low", "blind"), "sensor": ("an optical sensor", "low", "blind"),
    "optics": ("an optical sensor", "low", "blind"), "lens": ("a camera lens", "low", "blind"),
    "glass": ("laminated glass", "high", "break"), "windscreen": ("laminated glass", "high", "break"),
    "window": ("laminated glass", "high", "break"),
    "drone": ("a drone's rotors", "high", "break"), "rotor": ("a drone's rotors", "high", "break"),
    "wood": ("a barricade of wood", "high", "break"), "plastic": ("a barricade of plastic", "high", "break"),
    "sheet": ("a barricade of sheet metal", "high", "break"), "masonry": ("a barricade of loose masonry", "high", "break"),
    "barricade": ("a barricade of wood, plastic, sheet metal or loose masonry", "high", "break"),
    "concrete": ("concrete", "high", "never"), "steel": ("steel plate", "high", "never"), "armour": ("armour", "high", "never"),
    "armor": ("armour", "high", "never"),
    "foam": ("heavy acoustic foam", "any", "blocked"), "composite": ("sealed composite armour", "any", "blocked"),
    "person": ("a person", "low", "people"), "people": ("people", "low", "people"),
}
KEEN_PEOPLE = ("never the high setting with anyone in the beam or behind the glass, short of the last resort (SKILL.md section 4), "
               "and he says so first [maker]")

# what is in his way: (how it is named, class). Classes are the maker's lists in lore.json.
RAM_THINGS = {
    "cardboard": ("cardboard", "free"), "tape": ("tape", "free"), "hedge": ("a hedge", "free"),
    "wood": ("wood", "light"), "plastic": ("plastic", "light"), "sheet": ("sheet metal", "light"),
    "masonry": ("loose masonry", "light"),
    "brick": ("a brick or block wall", "wall"), "block": ("a brick or block wall", "wall"), "wall": ("a brick or block wall", "wall"),
    "barrier": ("a concrete road barrier", "wall"), "gate": ("a steel gate or shutter", "wall"),
    "shutter": ("a steel gate or shutter", "wall"),
    "car": ("a car", "vehicle"), "van": ("a van", "vehicle"),
    "lorry": ("a lorry", "frame"), "truck": ("a lorry", "frame"),
    "reinforced": ("reinforced concrete", "rc"), "rc": ("reinforced concrete", "rc"),
    "bunker": ("a bunker wall", "stop"), "pier": ("a bridge pier", "stop"), "rock": ("rock", "stop"), "tank": ("a tank", "stop"),
    "concrete": ("concrete", "down-stop"), "steel": ("steel plate", "down-stop"), "armour": ("armour", "down-stop"),
    "armor": ("armour", "down-stop"),
}
ARMOUR_UP = "the Veil on his front face, the Scales stacked behind it"


def keen_cost(cfg, setting, seconds):
    """(km of range, seconds to cool) for a burst."""
    rate = cfg["high_km_s"] * (1.0 if setting == "high" else cfg["low_fraction"])
    return rate * seconds, cfg["cool_s"] * seconds / float(cfg["burst_s"])


def keen_plan(cfg, target, dist, setting=None, hold=None):
    """What the Keen does to a target at a distance: a dict with name, setting, works, seconds, why."""
    if target not in KEEN_TARGETS:
        die("the Keen is pointed at one of: %s" % ", ".join(sorted(KEEN_TARGETS)))
    name, needs, what = KEEN_TARGETS[target]
    use = setting or ("high" if needs == "any" else needs)
    out = {"name": name, "setting": use, "works": False, "seconds": 0.0, "blind_s": 0.0, "why": ""}
    burst = float(cfg["burst_s"])
    if what == "people":
        out["why"] = ("the low setting does nothing to people, and the high setting is never fired with anyone in the beam, short "
                      "of the last resort [maker]")
    elif what == "blocked":
        out["why"] = "heavy acoustic foam and sealed composite armour block it completely [maker]"
    elif what == "never":
        out["why"] = "the high setting does not break concrete, steel plate or armour [maker]"
    elif what == "break" and use == "low":
        out["why"] = "that is a job for the high setting: the low one only blinds cameras and lidar [maker]"
    elif what == "blind":
        reach = float(cfg["low_reach_m"] if use == "low" else cfg["high_reach_m"])
        if use == "high":
            out["why"] = "blinding is the low setting's job, out to %s m: the high one is for breaking things, out to %s m [maker]" % (
                trim(cfg["low_reach_m"], 0), trim(reach, 0))
        elif dist > reach + 1e-9:
            out["why"] = "at %s m it has %s%% of what the job needs [derived: inverse square from its %s m reach]" % (
                trim(dist, 1), trim((reach / dist) ** 2 * 100.0, 0), trim(reach, 0))
        else:
            secs = burst if hold is None else hold
            out.update(works=True, seconds=secs, blind_s=secs + cfg["linger_s"],
                       why="blind while the beam is on it and for %s s after: %s s for a %s s burst [maker]" % (
                           trim(cfg["linger_s"], 1), trim(secs + cfg["linger_s"], 1), trim(secs, 1)))
    else:
        reach = float(cfg["high_reach_m"])
        if dist > reach + 1e-9:
            out["why"] = "at %s m it has %s%% of what the job needs [derived: inverse square from its %s m reach]" % (
                trim(dist, 1), trim((reach / dist) ** 2 * 100.0, 0), trim(reach, 0))
        else:
            secs = max(0.1, round(burst * (dist / reach) ** 2 + 0.04999, 1))
            out.update(works=True, seconds=min(burst, secs),
                       why="it goes inside %s s of the %s s burst [derived: the full burst at the %s m reach, less by the square "
                           "of the distance closer in]" % (trim(min(burst, secs), 1), trim(burst, 0), trim(reach, 0)))
    return out


def cmd_keen(a):
    cfg = load_data("lore")["keen"]
    burst, half = float(cfg["burst_s"]), cfg["arc_deg"] / 2.0
    if not a.target:
        rec("KEEN", "his one fitted weapon: a phased ultrasonic array in the lower front apron, steered by phasing over the front "
                    "%d degrees [maker]" % cfg["arc_deg"])
        rec("LOW", "blinds a camera or a lidar out to %d m, while the beam is on it and %s s after; nothing to people; %s km of "
                   "range a second; silent running holds" % (cfg["low_reach_m"], trim(cfg["linger_s"], 1),
                                                             trim(cfg["high_km_s"] * cfg["low_fraction"], 2)))
        rec("HIGH", "out to %d m: laminated glass, a drone's rotors, a barricade of wood, plastic, sheet metal or loose masonry; "
                    "%s km of range a second; ends silent running" % (cfg["high_reach_m"], trim(cfg["high_km_s"], 1)))
        rec("NOT", "concrete, steel plate or armour; heavy acoustic foam or sealed composite armour blocks it completely; it "
                   "weakens with the square of the distance")
        rec("LIMIT", "%s s at most; a full burst cools in %d s, a shorter one in proportion" % (trim(burst, 0), cfg["cool_s"]))
        rec("PEOPLE", KEEN_PEOPLE)
        rec("NEXT", "keen --target glass --at 20, or camera, lidar, drone, wood, plastic, sheet, masonry, concrete, steel, armour, "
                    "foam, composite, person")
        return
    if a.at is None or a.at <= 0:
        die("--at is the distance to the target in metres, more than 0")
    if a.hold is not None and not 0 < a.hold <= burst:
        die("--hold is seconds on the target, more than 0 and at most %s: that is its thermal limit" % trim(burst, 0))
    if not -180 <= a.bearing <= 180:
        die("--bearing is degrees off his nose, -180 to 180")
    plan = keen_plan(cfg, a.target.lower(), a.at, a.setting, a.hold)
    rec("KEEN", "the %s setting on %s at %s m" % (plan["setting"], plan["name"], trim(a.at, 1)))
    if abs(a.bearing) > half + 1e-9:
        rec("ARC", "%s degrees off his nose is outside the front %d: he turns first [maker]" % (trim(abs(a.bearing), 0), cfg["arc_deg"]))
    if not plan["works"]:
        rec("WORKS", "no: " + plan["why"])
        return
    km, cool = keen_cost(cfg, plan["setting"], plan["seconds"])
    rec("WORKS", "yes: " + plan["why"])
    rec("COST", "%s km of range, and %s s to cool before a full burst is ready again [lore: %s km a second on this setting; a full "
                "%s s burst cools in %d s]" % (trim(km, 1), trim(cool, 1),
                                               trim(cfg["high_km_s"] * (1.0 if plan["setting"] == "high" else cfg["low_fraction"]), 2),
                                               trim(burst, 0), cfg["cool_s"]))
    if plan["setting"] == "high":
        rec("SILENT", "the high setting ends silent running [lore]")
        rec("PEOPLE", KEEN_PEOPLE)
    else:
        rec("SILENT", "the low setting does not end silent running [lore]")
        rec("PEOPLE", "the low setting does nothing to people [maker]")
    rec("LEDGER", "book it in a sim with: lattice --state ... keen=%s:%s" % (plan["setting"], trim(plan["seconds"], 1)))


def ram_plan(cfg, thing, covered, kmh=None, thick=None):
    """What happens when he drives the hull through something. covered: the Veil is up on his front face.
    Returns a dict: name, result (free, through, slow, nofigure, stop), need (km/h), km, heavy, frame, why."""
    if thing not in RAM_THINGS:
        die("what is in the way is one of: %s. Anything else has no figure: the driver or the brief rules" % ", ".join(sorted(RAM_THINGS)))
    name, cls = RAM_THINGS[thing]
    least = cfg["least_kmh"]
    out = {"name": name, "result": "through", "need": 0, "km": 0.0, "heavy": False, "frame": False, "why": ""}
    if cls == "rc":
        if thick is None:
            die("reinforced concrete needs its thickness in cm: up to %d he breaches clean with the armour up, to %d at a cost to "
                "his frame, and beyond that it stops him" % (cfg["rc_clean_cm"], cfg["rc_frame_cm"]))
        if thick <= 0:
            die("the thickness is in cm, more than 0")
        name = out["name"] = "%s cm of reinforced concrete" % trim(thick, 0)
        cls = "wall" if thick <= cfg["rc_clean_cm"] else "frame" if thick <= cfg["rc_frame_cm"] else "stop"
        if cls == "stop":
            out.update(result="stop", why="reinforced concrete over %d cm stops him, armour up or not [maker]" % cfg["rc_frame_cm"])
            return out
    if cls == "free":
        out.update(result="free", why="it costs nothing, at any speed [maker]")
        return out
    if cls == "stop":
        out.update(result="stop", why="bunker walls, bridge piers, rock and tanks stop him, armour up or not [maker]")
        return out
    if cls == "down-stop":
        if covered:
            out.update(result="nofigure", why="'%s' alone is not on his list for the armour up [maker]: name the thing (a road "
                                              "barrier, a gate, reinforced concrete and its thickness, a tank), or the driver rules" % name)
        else:
            out.update(result="stop", why="with the Veil down, concrete, steel plate and armour stop him [maker]")
        return out
    out["need"] = least["light"] if cls == "light" else least["wall"] if cls == "wall" else least["heavy"]
    if cls != "light" and not covered:
        out.update(result="nofigure",
                   why="with the Veil down there is none: his body is stronger than an ordinary SUV's, and how much stronger is "
                       "the driver's to rule [maker]. With the armour up he goes through at %d km/h or more, for %s km of range" % (
                           out["need"], trim(cfg["breach_km"], 1)))
        return out
    if kmh is not None and kmh < out["need"] - 1e-9:
        out.update(result="slow", why="at %s km/h he is too slow: this needs %d at least [maker]. What happens below that is the brief's to rule" % (
            trim(kmh, 0), out["need"]))
        return out
    if covered:
        out["km"] = float(cfg["breach_km"])
        out["frame"] = cls == "frame"
    else:
        out["heavy"] = True
    out["why"] = "it needs %d km/h at least%s [maker]" % (out["need"], "" if kmh is None else ", and he has %s" % trim(kmh, 0))
    return out


def cmd_ram(a):
    lore = load_data("lore")
    cfg, lat = lore["ram"], lore["lattice"]
    if a.speed is not None and a.speed <= 0:
        die("--speed is km/h, more than 0")
    if a.speed is not None and a.speed > lore["chassis"]["top_kmh"] + 1e-9:
        die("his governor holds him to %d km/h" % lore["chassis"]["top_kmh"])
    thing = a.through.lower()
    plan = ram_plan(cfg, thing, a.veil, a.speed, a.thick)
    state = "armour up: %s" % ARMOUR_UP if a.veil else "the Veil down"
    rec("RAM", "%s%s, %s" % (plan["name"], "" if a.speed is None else " at %s km/h" % trim(a.speed, 0), state))
    word = {"free": "yes", "through": "yes", "slow": "no", "nofigure": "no figure", "stop": "no"}[plan["result"]]
    rec("THROUGH", "%s: %s" % (word, plan["why"]))
    if plan["result"] not in ("free", "through"):
        return
    veil_rate = lat["veil_km_per_min"] * lat["veil_partial_fraction"]
    if plan["result"] == "free":
        rec("COST", "none")
    elif plan["km"]:
        rec("COST", "%s km of range for the breach: the Veil takes the blow and holds, and the face behind it stays fresh [lore]. "
                    "The Veil's own %s km a minute runs besides" % (trim(plan["km"], 1), trim(veil_rate, 1)))
        if plan["frame"]:
            rec("FRAME", "it damages his frame [maker]: how much has no figure, the driver rules")
    else:
        rec("COST", "one heavy hit on his front face: the Rime there is soft until it re-cools [lore]")
    if plan["result"] == "through":
        rec("ABOARD", "what a breach does to the people inside has no figure: the driver rules")
        tail = ":%s" % trim(a.thick, 0) if RAM_THINGS[thing][1] == "rc" else ""
        rec("LEDGER", "book it in a sim with: lattice --state ... %sram=%s%s%s" % (
            "veil=partial:front " if a.veil else "", thing, tail, "" if a.speed is None else "@%s" % trim(a.speed, 0)))
        if a.speed is None:
            more("give --speed to check it against the %d km/h this needs" % plan["need"])


def register(sub):
    p = command(sub, "firn", "keen", cmd_keen,
                "FIRN-01's one fitted weapon, the Keen: whether it blinds or breaks a target at a distance, for how long, and the cost",
                ["keen", "keen --target glass --at 20", "keen --target camera --at 120 --hold 3", "keen --target drone --at 25 --bearing 70",
                 "keen --target concrete --at 10"])
    p.add_argument("--target", help="what it is pointed at: camera, lidar, glass, drone, wood, plastic, sheet, masonry, barricade, "
                                    "concrete, steel, armour, foam, composite, person")
    p.add_argument("--at", type=float, help="distance to the target, m")
    p.add_argument("--setting", choices=["low", "high"], help="force a setting (default: the one the job needs)")
    p.add_argument("--hold", type=float, help="low setting: seconds on the sensor (default the full 4)")
    p.add_argument("--bearing", type=float, default=0.0, help="degrees off his nose (default 0); it covers the front 120")

    p = command(sub, "firn", "ram", cmd_ram,
                "what FIRN-01 can drive through with the hull, Veil down or armour up: the least speed, the cost, what stops him",
                ["ram --through wood --speed 40", "ram --through brick --speed 70 --veil", "ram --through reinforced --thick 40 --speed 95 --veil",
                 "ram --through rock --veil"])
    p.add_argument("--through", required=True,
                   help="what is in the way: cardboard, tape, hedge, wood, plastic, sheet, masonry, brick, barrier, gate, car, van, "
                        "lorry, reinforced, bunker, pier, rock, tank, concrete, steel, armour")
    p.add_argument("--speed", type=float, help="his speed when he meets it, km/h")
    p.add_argument("--veil", action="store_true", help="armour up: the Veil on his front face, the Scales stacked behind it")
    p.add_argument("--thick", type=float, help="for reinforced concrete: its thickness, cm")
