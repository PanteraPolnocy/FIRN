"""The board: honest books for everyone in a simulation, not only for FIRN-01.

'lattice' keeps FIRN's own costs. This keeps everyone else's: hit points, conditions, who is down, the round
counter and the scenario's deadline. State travels as a token, like the lattice ledger, so nothing is written.

A unit at zero is DOWN, not dead. A living unit that is down can still be reached: it is lost only if nobody
gets to it within the countdown, or if a single blow goes far past zero. A machine at zero is DISABLED and can
be rebuilt. Every side is counted the same way, the opposition included.

Events, applied in order:
  add=raider:12:red          a unit: name, hit points, side (default blue), kind after another colon
  add=drone:6:red:machine    kinds: living (default), machine, vehicle
  hit=raider:5               damage; hit=raider:5:subdue for a blow meant to stop, not to kill
  heal=anna:3  repair=drone:4
  aid=raider                 someone reaches a downed unit: it is stable, out of the fight, alive
  cond=raider:stunned:2      a condition for 2 rounds (no number: until cleared);  clear=raider:stunned
  out=raider:fled            leaves the board alive: fled, surrendered, captured, rescued
  round  round=3             one round passes, or three: conditions and countdowns tick
  deadline=10  deadline=off  rounds left for the scenario
  remove=raider              strike a unit from the books (a mistake, not a casualty)
"""
import re

from .core import command, die, more, rec, table, unprotect

VERSION_TAG = "B1"
KINDS = {"living": "l", "machine": "m", "vehicle": "v"}
KIND_WORD = {v: k for k, v in KINDS.items()}
KIND_ALIAS = {"person": "living", "human": "living", "animal": "living", "robot": "machine", "drone": "machine", "construct": "machine",
              "armour": "machine", "armor": "machine", "car": "vehicle", "tank": "vehicle", "truck": "vehicle"}
STATES = ("up", "down", "stable", "lost", "disabled", "wrecked", "out")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
MAX_UNITS = 40


def _name(text, what="a name"):
    name = str(text).strip().lower().replace(" ", "_")
    if not _NAME_RE.match(name):
        die("%s is letters, digits, _ and -, up to 24 characters: '%s'" % (what, text))
    return name


def _int(text, what):
    try:
        n = int(str(text).strip())
    except ValueError:
        die("%s must be a whole number: '%s'" % (what, text))
    return n


class Board:
    def __init__(self, bleed=3):
        self.round = 1
        self.deadline = None
        self.bleed = bleed
        self.units = []
        self.lines = []

    # ---- token

    def token(self):
        units = []
        for u in self.units:
            conds = "+".join("%s%s" % (c, ".%d" % n if n else "") for c, n in u["conds"]) or "-"
            units.append(":".join([u["name"], u["side"], u["kind"], str(u["hp"]), str(u["max"]), u["state"], str(u["count"]),
                                   u["why"] or "-", conds]))
        return "/".join([VERSION_TAG, "r=%d" % self.round, "dl=%s" % ("-" if self.deadline is None else self.deadline),
                         "bl=%d" % self.bleed, "u=" + (",".join(units) or "-")])

    def load(self, token):
        parts = unprotect(token).strip().split("/")
        if not parts or parts[0] != VERSION_TAG:
            die("that is not a board state token (it should start with %s/); paste the STATE line exactly" % VERSION_TAG)
        try:
            kv = dict(p.split("=", 1) for p in parts[1:])
            self.round = int(kv["r"])
            self.deadline = None if kv["dl"] == "-" else int(kv["dl"])
            self.bleed = int(kv["bl"])
            self.units = []
            if kv["u"] != "-":
                for item in kv["u"].split(","):
                    name, side, kind, hp, top, state, count, why, conds = item.split(":")
                    if kind not in KIND_WORD or state not in STATES:
                        raise ValueError(item)
                    cl = []
                    if conds != "-":
                        for c in conds.split("+"):
                            word, _, n = c.partition(".")
                            cl.append((word, int(n) if n else 0))
                    self.units.append({"name": name, "side": side, "kind": kind, "hp": int(hp), "max": int(top), "state": state,
                                       "count": int(count), "why": None if why == "-" else why, "conds": cl})
        except (KeyError, ValueError):
            die("the board state token is damaged; paste the STATE line exactly as printed")

    # ---- helpers

    def say(self, key, text):
        self.lines.append((key, text))

    def unit(self, text):
        name = _name(text)
        hits = [u for u in self.units if u["name"] == name] or [u for u in self.units if u["name"].startswith(name)]
        if len(hits) != 1:
            die("%s on the board: '%s' (units: %s)" % ("no such unit" if not hits else "more than one unit matches", text,
                                                       ", ".join(u["name"] for u in self.units) or "none yet"))
        return hits[0]

    def _fall(self, u, blow, subdue):
        """A unit has reached zero or less."""
        living = u["kind"] == "l"
        past = u["hp"] <= -u["max"]
        u["conds"] = []
        if living:
            if subdue:
                u["hp"], u["state"], u["count"], u["why"] = 0, "stable", 0, "subdued"
                self.say("DOWN", "%s is subdued: out of the fight, alive, in no danger" % u["name"])
            elif past:
                u["state"], u["count"], u["why"] = "lost", 0, None
                self.say("LOST", "%s: %d from a single blow, far past zero. A life is gone, and the books say so" % (u["name"], blow))
            else:
                u["state"], u["count"] = "down", self.bleed
                self.say("DOWN", "%s is down, alive: %d round%s for someone to reach them (aid=%s)" % (
                    u["name"], self.bleed, "" if self.bleed == 1 else "s", u["name"]))
        elif past and not subdue:
            u["state"] = "wrecked"
            self.say("WRECKED", "%s is destroyed: past rebuilding" % u["name"])
        else:
            u["hp"], u["state"] = max(u["hp"], 0) if subdue else u["hp"], "disabled"
            self.say("DISABLED", "%s is out of action: it can be rebuilt" % u["name"])

    def tick(self):
        self.round += 1
        for u in self.units:
            kept = []
            for word, n in u["conds"]:
                if n == 1:
                    self.say("CLEARS", "%s is no longer %s" % (u["name"], word))
                else:
                    kept.append((word, n - 1 if n else 0))
            u["conds"] = kept
            if u["state"] == "down":
                u["count"] -= 1
                if u["count"] <= 0:
                    u["state"], u["count"] = "lost", 0
                    self.say("LOST", "%s: nobody reached them in time. A life is gone, and the books say so" % u["name"])
        if self.deadline is not None:
            self.deadline -= 1
            if self.deadline == 0:
                self.say("DEADLINE", "round %d: the scenario's time is up" % self.round)
            elif self.deadline < 0:
                self.say("DEADLINE", "round %d: %d round%s past the limit" % (self.round, -self.deadline, "" if self.deadline == -1 else "s"))

    # ---- events

    def apply(self, event):
        ev = unprotect(event).strip()
        key, _, val = ev.partition("=")
        key = key.lower()
        parts = [p.strip() for p in val.split(":")] if val else []
        if key == "add":
            if len(parts) < 2:
                die("add=NAME:HIT_POINTS, then :SIDE and :KIND if they are not blue and living")
            name, hp = _name(parts[0]), _int(parts[1], "hit points")
            if hp < 1:
                die("a unit starts with at least 1 hit point")
            if any(u["name"] == name for u in self.units):
                die("there is already a unit called %s" % name)
            if len(self.units) >= MAX_UNITS:
                die("the board holds up to %d units" % MAX_UNITS)
            side = _name(parts[2], "a side") if len(parts) > 2 and parts[2] else "blue"
            kind = (parts[3].lower() if len(parts) > 3 and parts[3] else "living")
            kind = KIND_ALIAS.get(kind, kind)
            if kind not in KINDS:
                die("a unit's kind is living, machine or vehicle")
            self.units.append({"name": name, "side": side, "kind": KINDS[kind], "hp": hp, "max": hp, "state": "up", "count": 0,
                               "why": None, "conds": []})
            self.say("ADD", "%s: %d hit points, %s, %s" % (name, hp, side, kind))
        elif key == "hit":
            if len(parts) < 2:
                die("hit=NAME:DAMAGE, with :subdue for a blow meant to stop rather than kill")
            u, dmg = self.unit(parts[0]), _int(parts[1], "damage")
            subdue = len(parts) > 2 and parts[2].lower() in ("subdue", "stun", "nonlethal")
            if dmg < 0:
                die("damage cannot be negative; use heal= or repair=")
            if u["state"] in ("lost", "wrecked", "out"):
                self.say("HIT", "%s is %s: nothing to hit" % (u["name"], u["state"]))
                return
            if u["state"] in ("down", "stable", "disabled"):
                if subdue or dmg == 0:
                    self.say("HIT", "%s is already %s" % (u["name"], u["state"]))
                    return
                self.say("HIT", "%s takes %d while %s" % (u["name"], dmg, u["state"]))
                if u["kind"] == "l":
                    u["state"], u["count"], u["why"] = "lost", 0, None
                    self.say("LOST", "%s was struck while down. A life is gone, and the books say so" % u["name"])
                else:
                    u["state"] = "wrecked"
                    self.say("WRECKED", "%s is destroyed: past rebuilding" % u["name"])
                return
            before = u["hp"]
            u["hp"] = before - dmg
            self.say("HIT", "%s takes %d%s: %d -> %d of %d" % (u["name"], dmg, " (to subdue)" if subdue else "", before, max(u["hp"], 0), u["max"]))
            if u["hp"] <= 0:
                self._fall(u, dmg, subdue)
                u["hp"] = max(u["hp"], 0)
        elif key in ("heal", "repair"):
            if len(parts) < 2:
                die("%s=NAME:POINTS" % key)
            u, n = self.unit(parts[0]), _int(parts[1], "points")
            if u["state"] in ("lost", "wrecked"):
                self.say(key.upper(), "%s is %s: beyond %s" % (u["name"], u["state"], "help" if u["state"] == "lost" else "repair"))
                return
            u["hp"] = min(u["max"], u["hp"] + max(0, n))
            if u["state"] in ("down", "stable", "disabled") and u["hp"] > 0:
                u["state"], u["count"], u["why"] = "up", 0, None
            self.say(key.upper(), "%s: %d of %d, %s" % (u["name"], u["hp"], u["max"], u["state"]))
        elif key == "aid":
            u = self.unit(val)
            if u["state"] != "down":
                self.say("AID", "%s is %s: aid is for a unit that is down" % (u["name"], u["state"]))
                return
            u["state"], u["count"], u["why"] = "stable", 0, "aided"
            self.say("AID", "%s has been reached: stable, out of the fight, alive" % u["name"])
        elif key == "cond":
            if len(parts) < 2:
                die("cond=NAME:WORD, with :ROUNDS if it wears off")
            u, word = self.unit(parts[0]), _name(parts[1], "a condition")
            n = _int(parts[2], "rounds") if len(parts) > 2 else 0
            u["conds"] = [(w, k) for w, k in u["conds"] if w != word] + [(word, max(0, n))]
            self.say("COND", "%s is %s%s" % (u["name"], word, " for %d round%s" % (n, "" if n == 1 else "s") if n else ""))
        elif key == "clear":
            if len(parts) < 2:
                die("clear=NAME:WORD")
            u, word = self.unit(parts[0]), _name(parts[1], "a condition")
            u["conds"] = [(w, k) for w, k in u["conds"] if w != word]
            self.say("CLEARS", "%s is no longer %s" % (u["name"], word))
        elif key == "out":
            if not parts:
                die("out=NAME, with :fled, :surrendered, :captured or :rescued")
            u = self.unit(parts[0])
            if u["state"] in ("lost", "wrecked"):
                self.say("OUT", "%s is %s" % (u["name"], u["state"]))
                return
            u["state"], u["count"], u["why"] = "out", 0, _name(parts[1], "a reason") if len(parts) > 1 and parts[1] else "left"
            self.say("OUT", "%s has left the board, alive: %s" % (u["name"], u["why"]))
        elif key == "round":
            n = _int(val, "rounds") if val else 1
            if not 1 <= n <= 100:
                die("round=N takes 1 to 100")
            for _ in range(n):
                self.tick()
        elif key == "deadline":
            if val.lower() in ("off", "none", "-"):
                self.deadline = None
                self.say("DEADLINE", "none")
            else:
                self.deadline = _int(val, "rounds")
                if self.deadline < 1:
                    die("deadline=N is a number of rounds from now, or off")
                self.say("DEADLINE", "%d round%s from now" % (self.deadline, "" if self.deadline == 1 else "s"))
        elif key == "remove":
            u = self.unit(val)
            self.units.remove(u)
            self.say("REMOVED", "%s struck from the books" % u["name"])
        else:
            die("unknown board event '%s'. Events: add= hit= heal= repair= aid= cond= clear= out= round deadline= remove=" % event)

    def show(self):
        if not self.units:
            rec("BOARD", "round %d, nobody on it yet: add=NAME:HIT_POINTS:SIDE" % self.round)
            return
        when = "no deadline" if self.deadline is None else (
            "%d round%s left" % (self.deadline, "" if self.deadline == 1 else "s") if self.deadline > 0 else "time is up")
        rec("BOARD", "round %d, %s" % (self.round, when))
        rows = []
        for u in sorted(self.units, key=lambda x: (x["side"], x["name"])):
            state = u["state"]
            if state == "down":
                state = "DOWN, %d round%s to reach" % (u["count"], "" if u["count"] == 1 else "s")
            elif state in ("stable", "out") and u["why"]:
                state = "%s (%s)" % (state, u["why"])
            elif state in ("lost", "wrecked"):
                state = state.upper()
            conds = ", ".join("%s%s" % (c, " %d" % n if n else "") for c, n in u["conds"])
            rows.append((u["name"], u["side"], KIND_WORD[u["kind"]], "%d/%d" % (u["hp"], u["max"]), state, conds))
        table(rows, header=("unit", "side", "kind", "hp", "state", "conditions"), indent=2)
        sides = sorted(set(u["side"] for u in self.units))
        for side in sides:
            mine = [u for u in self.units if u["side"] == side]
            count = {s: sum(1 for u in mine if u["state"] == s) for s in STATES}
            bits = ["%d up" % count["up"]]
            for s, word in (("down", "down"), ("stable", "stable"), ("disabled", "disabled"), ("out", "left"), ("wrecked", "wrecked"),
                            ("lost", "LOST")):
                if count[s]:
                    bits.append("%d %s" % (count[s], word))
            rec(side.upper()[:10], ", ".join(bits))
        down = [u for u in self.units if u["state"] == "down"]
        for u in down:
            rec("REACH", "%s (%s) is down with %d round%s left: aid=%s" % (
                u["name"], u["side"], u["count"], "" if u["count"] == 1 else "s", u["name"]))
        lost = [u["name"] for u in self.units if u["state"] == "lost"]
        if lost:
            rec("LIVES", "lost: %s. Every side is counted the same" % ", ".join(lost))


def cmd_board(a):
    b = Board(bleed=a.bleed)
    fresh = not a.state
    if a.state:
        b.load(a.state)
    elif not 1 <= a.bleed <= 20:
        die("--bleed is 1 to 20 rounds")
    for ev in a.events:
        b.apply(ev)
    for key, text in b.lines:
        rec(key, text)
    b.show()
    rec("STATE", b.token())
    if fresh and not a.events:
        rec("NEXT", "pass that STATE back with --state and add events: add= hit= heal= repair= aid= cond= clear= out= round deadline=")
        rec("RULES", "a living unit at zero is down, not dead: %d round%s to reach it, then it is lost; a single blow that goes "
                     "past zero by its full hit points kills outright; a machine at zero is disabled and can be rebuilt [house rule]" % (
                         b.bleed, "" if b.bleed == 1 else "s"))
        more("damage comes from the dice and the ruleset ('strike', 'blast', 'roll'): this only keeps the books")


def register(sub):
    p = command(sub, "combat", "board", cmd_board,
                "books for everyone in a sim: hit points, conditions, who is down and can still be reached, rounds, the deadline",
                ["board add=anna:10 add=raider:12:red add=drone:6:red:machine deadline=10",
                 "board --state B1/... hit=raider:7 cond=raider:stunned:2 round",
                 "board --state B1/... hit=raider:5:subdue aid=anna out=drone:fled", "board"])
    p.add_argument("events", nargs="*", help="events in order: add= hit= heal= repair= aid= cond= clear= out= round deadline= remove=")
    p.add_argument("--state", help="the STATE token from the previous turn (omit to start a new board)")
    p.add_argument("--bleed", type=int, default=3, help="rounds a downed living unit can wait for aid (default 3; set when the board is started)")
