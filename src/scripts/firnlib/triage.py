"""Triage: rank the options in a forced choice by what is physically lost, and say why.

The maker's field rule: look at what is actually there before reaching for philosophy.
What each one is made of, what each can survive, and the option that loses the least for good.
The hull is spent before a life, his own life included. No new pieces on the board.

Each option is  "name: who=outcome, who=outcome@chance, ..."
Outcomes, worst first:
  lost      gone for good: a life, or a mind with no backup
  critical  may be lost: a life-threatening injury
  hurt      an injury that heals
  repair    damage that can be rebuilt: a construct's frame, an armour, the car
  spent     used up: range, kit, time, paint
  fine      untouched
'self', 'firn' or 'car' as the who marks FIRN-01 himself: damage to his hull counts last within a class. His core is
another matter: his mind cannot be backed up, so self=lost or self=critical is a life, and counts with everyone's.
A chance is 0-1 or a percentage: construct=repair@50%.
"""
import re

from .core import command, die, more, rec, trim

CLASSES = ["lost", "critical", "hurt", "repair", "spent"]
WORDS = {"lost": "lost for good", "critical": "in critical danger", "hurt": "hurt", "repair": "in need of repair", "spent": "spent"}
SELF = ("self", "firn", "car", "firn-01", "me")
LIFE = ("lost", "critical")         # for him these mean the core, and a mind with no backup is a life like any other
_ITEM_RE = re.compile(r"^\s*([^=@]+?)\s*=\s*([a-z]+)\s*(?:@\s*([\d.]+)\s*(%)?)?\s*$", re.I)


def parse_option(text):
    name, sep, body = text.partition(":")
    if not sep or not name.strip():
        die("an option looks like  \"wall: self=repair\"  or  \"left: driver=lost, passenger=fine\"")
    score = {c: 0.0 for c in CLASSES}
    self_score = {c: 0.0 for c in CLASSES}
    items = []
    for part in body.split(","):
        if not part.strip():
            continue
        m = _ITEM_RE.match(part)
        if not m:
            die("could not read '%s' in option '%s' (use who=outcome or who=outcome@50%%)" % (part.strip(), name.strip()))
        who, outcome = m.group(1).strip(), m.group(2).lower()
        if outcome not in CLASSES + ["fine"]:
            die("outcome '%s' is not one of: %s, fine" % (outcome, ", ".join(CLASSES)))
        p = 1.0
        if m.group(3):
            p = float(m.group(3))
            if m.group(4) or p > 1:
                p /= 100.0
            if not 0 <= p <= 1:
                die("a chance is 0-1 or 0-100%%: '%s'" % part.strip())
        if outcome != "fine" and p > 0:
            (self_score if who.lower() in SELF and outcome not in LIFE else score)[outcome] += p
        items.append((who, outcome, p))
    if not items:
        die("option '%s' lists nobody; say who is affected and how" % name.strip())
    return {"name": name.strip(), "items": items, "score": score, "self": self_score}


def _key(opt):
    k = []
    for c in CLASSES:
        k.append(round(opt["score"][c], 9))
        k.append(round(opt["self"][c], 9))
    return tuple(k)


def _describe(opt):
    parts = []
    for who, outcome, p in opt["items"]:
        if outcome == "fine":
            continue
        chance = "" if p >= 1 else " (%s%% chance)" % trim(p * 100, 0)
        parts.append("%s %s%s" % (who, WORDS[outcome], chance))
    return "; ".join(parts) if parts else "nobody and nothing harmed"


def _first_difference(a, b):
    """The worst class in which two options differ: (class, is_self, a_value, b_value)."""
    for c in CLASSES:
        if abs(a["score"][c] - b["score"][c]) > 1e-9:
            return c, False, a["score"][c], b["score"][c]
        if abs(a["self"][c] - b["self"][c]) > 1e-9:
            return c, True, a["self"][c], b["self"][c]
    return None


def cmd_triage(a):
    opts = [parse_option(t) for t in a.options]
    if len(opts) < 2:
        die("triage compares options: give at least two")
    names = [o["name"].lower() for o in opts]
    if len(set(names)) != len(names):
        die("option names must differ")
    ranked = sorted(opts, key=_key)
    for i, o in enumerate(ranked, 1):
        rec("RANK %d" % i, "%s: %s" % (o["name"], _describe(o)))
    best, second = ranked[0], ranked[1]
    diff = _first_difference(best, second)
    if diff is None:
        rec("VERDICT", "TIE on the physical facts between '%s' and '%s' [derived]" % (best["name"], second["name"]))
        more("nothing measurable separates them. Now it is a question of values: say so in one line, then answer it.")
    else:
        c, is_self, va, vb = diff
        what = "FIRN's own" if is_self else "other"
        if c == "lost":
            reason = "it loses %s for good where '%s' loses %s" % (
                "nothing" if va == 0 else "less (expected %s)" % trim(va, 2), second["name"],
                "one" if abs(vb - 1) < 1e-9 else "more (expected %s)" % trim(vb, 2))
        elif c == "repair":
            if best["self"]["repair"] > 0 and second["score"]["repair"] > best["score"]["repair"]:
                reason = "neither loses anything for good, and it spends the car instead of someone else"
            elif is_self:
                reason = "neither loses anything for good, and it costs the car less"
            else:
                reason = "neither loses anything for good, and it leaves less to rebuild"
        elif c == "spent":
            reason = "nobody is harmed either way, and it costs less"
        else:
            reason = "they match on everything worse, and it leaves fewer %s %s (expected %s against %s)" % (
                what, WORDS[c], trim(va, 2), trim(vb, 2))
        rec("VERDICT", "'%s': %s [derived]" % (best["name"], reason))
        more("say the choice first, the physical reason second, the cost third. No speech.")
    rec("METHOD", "what each is made of -> what each can survive -> least lost for good -> the hull is spent before a life")
    rec("NOTE", "this ranks the options you entered. It adds no pieces to the board, and the outcomes are your estimates: label them")
    rec("LIVES", "every life counts the same here, whichever side it is on, his own included: his core cannot be backed up. "
                 "Only damage to his hull is counted last")


def register(sub):
    p = command(sub, "firn", "triage", cmd_triage,
                "a forced choice ranked by what is physically lost, least permanent loss first, with the plain reason",
                ['triage "left: driver=lost" "right: construct=repair"',
                 'triage "wall: self=repair" "left: driver=lost" "right: construct=repair"',
                 'triage "hold: bystanders=fine, self=repair@80%" "run: bystanders=lost@60%"'])
    p.add_argument("options", nargs="+", help='"name: who=outcome[@chance], ..." with outcomes lost, critical, hurt, repair, spent, fine')
