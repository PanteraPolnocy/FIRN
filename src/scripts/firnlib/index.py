"""The tool index: which module carries which command, the grouped list of them all, and a search.

firn.py asks this which one module a call needs and loads only that one, which is most of what a call costs.
The answers come from data/commands.json, which tools/build_index.py writes from the commands themselves.
If that file is missing or from another version, every module is loaded and asked instead: slower, same result.
"""
import argparse
import importlib
import json
import os
import re

from . import MODULES, VERSION, core
from .core import DATA, SCRIPTS, command, fold, more, rec

INDEX_FILE = os.path.join(DATA, "commands.json")
PLAYBOOKS = os.path.join(os.path.dirname(SCRIPTS), "playbooks")

# Everyday words for a job that the command's own help does not use. 'tools --find' reads these too.
ALSO = {
    "time": "timezone zone clock convert utc what time",
    "dst": "daylight saving summer winter clock change",
    "meet": "meeting call schedule overlap awake",
    "span": "countdown age elapsed between days until how long",
    "series": "recurring weekly repeat event stream",
    "route": "drive distance eta journey directions leave arrive departure how far tired sleepy fatigue overnight night drive",
    "trip": "flight train connection layover itinerary jet lag timetable",
    "places": "town city airport coordinates find where",
    "tour": "errands stops order visit shortest round",
    "halfway": "midpoint middle fair meet between",
    "country": "border abroad foreign plug socket currency emergency left side",
    "convoy": "group together pickup everyone",
    "brief": "briefing plan journey trip summary everything overview mission record whole",
    "park": "parked parking leave left car find lost back bearing spot",
    "sun": "sunrise sunset daylight dusk dawn dark",
    "moon": "phase full new night",
    "metar": "airport weather aviation report taf",
    "weather": "forecast ice icy slippery fog wind rain temperature frost black",
    "range": "veil budget lore capacitor how far",
    "ev": "electric battery charge charging charger kwh how far",
    "fuel": "petrol diesel gas cost litres mpg consumption co2 split share",
    "perf": "acceleration horsepower top speed quarter mile",
    "stop": "braking brake distance following gap tailgate",
    "impact": "crash collision energy",
    "corner": "bend curve grip lateral",
    "transfer": "weight shift balance pitch roll",
    "spring": "suspension frequency rate",
    "gearing": "gear ratio rpm final drive",
    "tyre": "tire wheel pressure size date rim",
    "laps": "lap times consistency sectors",
    "stint": "pit stop strategy race tyres",
    "pace": "lap average gap catch",
    "roll": "dice random",
    "odds": "probability chance dice",
    "lanchester": "battle force wargame attrition",
    "ttk": "time to kill dpm damage reload",
    "scenario": "mission brief generate random sim",
    "strike": "attack weapon bow sword gun laser melee hit damage arrow",
    "blast": "explosion explosive grenade mine charge bomb",
    "arc": "trajectory throw thrown arrow ballistic",
    "lead": "moving target aim ahead",
    "board": "hit points hp tracker units wounded initiative",
    "armour": "armor penetration slope plate shell ricochet",
    "angle": "angling hull tank sidescrape",
    "spot": "view range camo concealment spotted",
    "scan": "sensor sensors detect detection radar thermal lidar camera identify analyse see",
    "lattice": "shield shields veil rime scales ledger cost",
    "jump": "squall leap gap ramp stunt airborne burst clear chasm bridge out",
    "triage": "dilemma choice trolley who to save",
    "record": "spec sheet block fit list kit",
    "convert": "units hp kw nm psi bar mph",
    "obd": "fault code check engine dtc",
    "lights": "dashboard warning lamp symbol",
    "service": "inspection mot oil due reminder maintenance",
    "compare": "versus side by side which car cost to own",
    "load": "payload weight capacity roof overloaded passengers",
    "tow": "trailer caravan towbar hitch noseweight",
    "fit": "boot trunk space box cargo will it go in",
    "weigh": "weight mass heavy density material tip topple centre of gravity how much does",
    "measure": "photo picture size scale pixels how big how long",
    "analyse": "analysis analyze photo picture object item examine identify what is this",
    "pitch": "music note engine sound frequency hertz rpm tone",
    "doppler": "passing siren speed sound pitch drop horn",
    "playlist": "music songs tracks soundtrack album arrive",
    "listen": "loud volume decibel hearing noise safe ears",
    "cabin": "bass boom resonance speakers subwoofer acoustics",
    "lsl": "second life script vehicle",
    "space": "orbit delta-v rocket warp light lag",
    "session": "how long fatigue duration tired talking conversation",
    "checklist": "list before drive winter packing",
    "boot": "start startup first hello",
    "ignition": "identity password who driver check",
    "sheet": "picture image reference show",
    "log": "logbook diary entry remember",
    "prompt": "image picture draw generate art",
    "check": "typography quotes dashes reply lint",
    "selftest": "test broken working diagnose",
    "setup": "settings personal file validate",
    "rebuild": "settings home work change personal update package save",
    "tools": "help commands list index find search",
}

_index = None
_built = {}


def build_parser(only=None):
    """The command-line parser: every command, or only those of the modules named."""
    core.REGISTRY[:] = []
    _built.clear()
    p = argparse.ArgumentParser(
        prog="firn.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="FIRN field tools (stdlib only, no network). Run 'firn.py tools' for the grouped index.")
    p.add_argument("--version", action="version", version="firn field tools " + VERSION)
    sub = p.add_subparsers(dest="cmd", metavar="<command>")
    for name in (MODULES if only is None else only):
        seen = len(core.REGISTRY)
        importlib.import_module("firnlib." + name).register(sub)
        for row in core.REGISTRY[seen:]:
            _built[row[1]] = name
    return p


def collect():
    """Load every module and ask it: the index, exactly as tools/build_index.py writes it."""
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    rows = []
    for group, name, summary, examples in core.REGISTRY:
        options = []
        for act in sub.choices[name]._actions:
            if isinstance(act, argparse._HelpAction):
                continue
            flags = " ".join(act.option_strings) or (act.metavar if isinstance(act.metavar, str) else act.dest)
            options.append([flags, act.help or ""])
        rows.append({"name": name, "module": _built[name], "group": group, "summary": summary, "examples": list(examples),
                     "also": ALSO.get(name, ""), "options": options})
    return {
        "note": "Generated by tools/build_index.py from the commands themselves. Do not edit: firn.py reads it to load only the "
                "module a command needs, and 'tools --find' searches it.",
        "version": VERSION,
        "commands": rows,
    }


def load():
    global _index
    if _index is None:
        try:
            with open(INDEX_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("version") != VERSION or not data.get("commands"):
                raise ValueError("stale")
        except (OSError, ValueError):
            data = collect()
        _index = data
    return _index


def module_of(name):
    """The one module that carries this command, or None if it is not in the index."""
    for c in load()["commands"]:
        if c["name"] == name:
            return c["module"]
    return None


# ---- search

_STOP = set("a an the of to for in on and or with is it my me i how do does what which can will be at from by this that "
            "much many get need want should would about into when go have we been are was they there any some up out if so "
            "than then you your our us am".split())
_WORD_RE = re.compile(r"[a-z0-9]+")


def _stem(word):
    for suffix in ("ing", "ed", "s"):
        if len(word) - len(suffix) >= 3 and word.endswith(suffix) and not word.endswith("ss"):
            return word[:-len(suffix)]
    return word


def _stems(text):
    return [_stem(w) for w in _WORD_RE.findall(fold(text).replace("_", " "))]


def _hit(want, have):
    """How well one word of the question matches a set of stems: 1 exact, 0.5 a prefix either way, 0 none."""
    if want in have:
        return 1.0
    for h in have:
        if (len(want) >= 4 and h.startswith(want)) or (len(h) >= 4 and want.startswith(h)):
            return 0.5
    return 0.0


def playbook_sections():
    """[(file, heading, stems of its text, commands it shows)] for every section of every playbook."""
    names = set(c["name"] for c in load()["commands"])
    out = []
    try:
        files = sorted(f for f in os.listdir(PLAYBOOKS) if f.endswith(".md"))
    except OSError:
        return out
    for fname in files:
        try:
            with open(os.path.join(PLAYBOOKS, fname), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        for part in re.split(r"(?m)^(?=#{1,3} )", text):
            m = re.match(r"#{1,3} (.+)", part)
            if not m:
                continue
            shown = []
            for span in re.findall(r"`([^`\n]+)`", part):
                first = span.split()[0] if span.split() else ""
                if first in names and first not in shown:
                    shown.append(first)
            out.append((fname, m.group(1).strip(), set(_stems(part)), shown, set(_stems(m.group(1)))))
    return out


def search(words):
    """Commands and playbook sections that answer the words, best first.

    Each word of the question counts for more the fewer commands it fits: 'caravan' points at one tool,
    'time' at a dozen. A command's score is the sum over the words of that weight times the best place
    the word was found in (its name, its everyday words, its summary, its options, its examples)."""
    import math
    wanted = [w for w in _stems(" ".join(words)) if w not in _STOP] or _stems(" ".join(words))
    fields = (("name", 12.0), ("also", 7.0), ("summary", 6.0), ("group", 2.0), ("options", 3.0), ("examples", 1.5))
    commands = load()["commands"]
    found = {}
    for c in commands:
        text = {"name": c["name"], "also": c.get("also", ""), "summary": c["summary"], "group": c["group"],
                "options": " ".join("%s %s" % (o[0], o[1]) for o in c.get("options", [])),
                # the finder's own examples are questions, not a description of what it does
                "examples": "" if c["name"] == "tools" else " ".join(c.get("examples", []))}
        stems = dict((k, set(_stems(v))) for k, v in text.items())
        found[c["name"]] = [max(weight * _hit(w, stems[k]) for k, weight in fields) for w in wanted]
    rarity = []
    for n in range(len(wanted)):
        fits = sum(1 for hits in found.values() if hits[n] > 0)
        rarity.append(math.log(1.0 + len(commands) / float(fits)) if fits else 0.0)
    scores = {}
    for name, hits in found.items():
        total = sum(h * r for h, r in zip(hits, rarity))
        if total > 0:
            scores[name] = total
    sections = []
    for fname, heading, stems, shown, head_stems in playbook_sections():
        in_heading = sum(_hit(w, head_stems) * r for w, r in zip(wanted, rarity))
        words_hit = sum(1 for w in wanted if _hit(w, stems) > 0)
        if in_heading > 0 or (words_hit == len(wanted) and len(wanted) > 1):
            sections.append((in_heading, words_hit, fname, heading, shown))
            for name in shown:
                if name in scores:      # a playbook backs up a command that already answers; it does not nominate one
                    scores[name] += 1.5 * in_heading
    ranked = sorted(scores, key=lambda n: (-scores[n], n))
    if ranked:
        ranked = [n for n in ranked if scores[n] >= 0.55 * scores[ranked[0]]]
    # a section is worth reading for this question only if it shows one of the commands that answered it
    sections = [s[:4] for s in sections if set(s[4]) & set(ranked[:3])]
    sections.sort(key=lambda s: (-s[0], -s[1], s[2], s[3]))
    return wanted, ranked, sections


def cmd_tools(a):
    data = load()
    if a.find:
        wanted, ranked, sections = search(a.find)
        by_name = dict((c["name"], c) for c in data["commands"])
        question = " ".join(a.find)
        if not ranked:
            rec("FIND", "\"%s\": no command answers that" % question)
            more("try another word for the job, or 'tools' for every command by group")
            return
        if a.limit < 1:
            core.die("--limit is at least 1")
        rec("FIND", "\"%s\": %d command%s, best first" % (question, len(ranked), "" if len(ranked) == 1 else "s"))
        for name in ranked[:a.limit]:
            c = by_name[name]
            rec(name, c["summary"])
            if c["examples"]:
                more("firn.py " + c["examples"][0])
        if len(ranked) > a.limit:
            more("... and %d more: %s" % (len(ranked) - a.limit, ", ".join(ranked[a.limit:a.limit + 8])))
        for _, _, fname, heading in sections[:2]:
            rec("READ", "playbooks/%s, \"%s\"" % (fname, heading))
        rec("NEXT", "'firn.py <command> -h' for the options and more examples")
        return
    by_group = {}
    for c in data["commands"]:
        by_group.setdefault(c["group"], []).append(c)
    want = a.group.lower() if a.group else None
    shown = 0
    for key, title in core.GROUPS:
        items = by_group.get(key)
        if not items or (want and want not in (key, title.lower())):
            continue
        print(title.upper())
        for c in items:
            print("  %-11s %s" % (c["name"], c["summary"]))
            if a.examples:
                for e in c["examples"]:
                    print("  %-11s   firn.py %s" % ("", e))
            shown += 1
    if not shown:
        core.die("no such group; groups are: %s" % ", ".join(k for k, _ in core.GROUPS if k in by_group))
    print("%d commands. 'firn.py <command> -h' for options and examples; 'firn.py tools --find WORDS' finds one by the job." % shown)


def register(sub):
    p = command(sub, "desk", "tools", cmd_tools, "the index of every command, grouped; or find the command for a job",
                ["tools", "tools --group racing --examples", "tools --find towing a caravan", "tools --find how loud is safe"])
    p.add_argument("--group", help="one group only")
    p.add_argument("--examples", action="store_true", help="include example invocations")
    p.add_argument("--find", nargs="+", metavar="WORD", help="the job in a few words: the commands that do it, best first")
    p.add_argument("--limit", type=int, default=5, help="how many commands --find lists (default 5)")
