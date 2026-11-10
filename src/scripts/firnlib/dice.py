"""Dice: honest rolls and exact odds.

Notation (case-insensitive, spaces ignored):
  3d6+2          three six-sided dice plus two
  d20  d%  4dF   one d20, a percentile die, four fudge dice (-1, 0, +1)
  2d20kh1        keep highest 1 (also k1); kl1 keep lowest; 4d6dl1 drop lowest 1; dh drop highest
  adv  dis       shorthand for 2d20kh1 and 2d20kl1 (adv+5 works)
  3d6!           exploding: a die showing its maximum rolls again and adds
  6d10>=7        a pool: counts the dice that meet the target (also > < <= =)
  2d6+1d4-1      terms add and subtract
"""
import math
import random
import re

from .core import command, die, more, rec, table, trim, unprotect

MAX_DICE = 1000
MAX_SIDES = 1000
EXPLODE_DEPTH = 5

_TERM_RE = re.compile(r"""^
    (?P<n>\d*)d(?P<sides>\d+|%|f)
    (?P<explode>!)?
    (?:(?P<kd>kh|kl|dh|dl|k)(?P<kn>\d+))?
    (?:(?P<cmp>>=|<=|>|<|=)(?P<target>\d+))?
    $""", re.X)
_SPLIT_RE = re.compile(r"([+-]?)([^+-]+)")
_OPS = {">=": lambda v, t: v >= t, "<=": lambda v, t: v <= t, ">": lambda v, t: v > t,
        "<": lambda v, t: v < t, "=": lambda v, t: v == t}
USAGE = "dice format: NdM, NdM+K, 2d20kh1, 4d6dl1, 3d6!, 6d10>=7, adv, dis, d%, 4dF (see 'roll -h')"


def parse(expr):
    """Parse a dice expression into a list of signed terms."""
    text = unprotect(str(expr)).replace(" ", "").lower()
    text = re.sub(r"\badv\b", "2d20kh1", text)
    text = re.sub(r"\bdis\b", "2d20kl1", text)
    if not text:
        die(USAGE)
    terms, pos = [], 0
    for m in _SPLIT_RE.finditer(text):
        if m.start() != pos:
            die("%s -- could not read '%s'" % (USAGE, expr))
        pos = m.end()
        sign = -1 if m.group(1) == "-" else 1
        body = m.group(2)
        if body.isdigit():
            terms.append({"kind": "const", "sign": sign, "value": int(body), "text": body})
            continue
        d = _TERM_RE.match(body)
        if not d:
            die("%s -- could not read '%s'" % (USAGE, body))
        n = int(d.group("n") or 1)
        sides = d.group("sides")
        if sides == "f":
            faces = [-1, 0, 1]
        else:
            count = 100 if sides == "%" else int(sides)
            if not 2 <= count <= MAX_SIDES:
                die("dice need 2 to %d sides" % MAX_SIDES)
            faces = list(range(1, count + 1))
        if not 1 <= n <= MAX_DICE:
            die("1 to %d dice per term" % MAX_DICE)
        explode = bool(d.group("explode"))
        if explode and sides == "f":
            die("fudge dice do not explode")
        keep = None
        if d.group("kd"):
            kn = int(d.group("kn"))
            mode = d.group("kd")
            if mode in ("k", "kh"):
                keep = ("high", kn)
            elif mode == "kl":
                keep = ("low", kn)
            elif mode == "dl":
                keep = ("high", n - kn)
            else:
                keep = ("low", n - kn)
            if not 1 <= keep[1] <= n:
                die("cannot keep %d of %d dice in '%s'" % (keep[1], n, body))
        cmp_ = None
        if d.group("cmp"):
            if explode or keep:
                die("a pool (%s) cannot also explode or keep/drop in this tool" % d.group("cmp"))
            cmp_ = (d.group("cmp"), int(d.group("target")))
        terms.append({"kind": "dice", "sign": sign, "n": n, "faces": faces, "explode": explode,
                      "keep": keep, "cmp": cmp_, "text": body})
    if pos != len(text) or not terms:
        die("%s -- could not read '%s'" % (USAGE, expr))
    return terms


# ---- rolling

def _roll_die(t, rng):
    lo, hi = t["faces"][0], t["faces"][-1]
    v = rng.randint(lo, hi)
    total, depth = v, 0
    while t["explode"] and v == hi and depth < 50:
        v = rng.randint(lo, hi)
        total += v
        depth += 1
    return total


def roll_once(terms, rng):
    """Roll an expression. Returns (total, display text)."""
    total, shown = 0, []
    for i, t in enumerate(terms):
        lead = ("- " if t["sign"] < 0 else "+ ") if i else ("-" if t["sign"] < 0 else "")
        if t["kind"] == "const":
            total += t["sign"] * t["value"]
            shown.append(lead + str(t["value"]))
            continue
        rolls = [_roll_die(t, rng) for _ in range(t["n"])]
        text = str(rolls)
        if t["cmp"]:
            op, target = t["cmp"]
            value = sum(1 for r in rolls if _OPS[op](r, target))
            text += " -> %d success%s" % (value, "" if value == 1 else "es")
        elif t["keep"]:
            mode, k = t["keep"]
            kept = sorted(rolls, reverse=(mode == "high"))[:k]
            value = sum(kept)
            text += " keep %s" % kept
        else:
            value = sum(rolls)
        total += t["sign"] * value
        shown.append(lead + text)
    return total, " ".join(shown)


def make_rng(seed):
    return random.Random(seed) if seed is not None else random.SystemRandom()


# ---- exact distributions

def _convolve(a, b, sign=1):
    out = {}
    for va, pa in a.items():
        for vb, pb in b.items():
            k = va + sign * vb
            out[k] = out.get(k, 0.0) + pa * pb
    return out


def _face_dist(t):
    faces = t["faces"]
    p = 1.0 / len(faces)
    if not t["explode"]:
        return {v: p for v in faces}
    hi = faces[-1]
    out, mass, base = {}, 1.0, 0
    for depth in range(EXPLODE_DEPTH + 1):
        last = depth == EXPLODE_DEPTH
        for v in faces:
            if v == hi and not last:
                continue
            out[base + v] = out.get(base + v, 0.0) + mass * p
        mass *= p
        base += hi
    return out


def _keep_dist(n, face_dist, k, highest):
    """Distribution of the sum of the k highest (or lowest) of n dice, exact, by sorted-face conditioning."""
    order = sorted(face_dist, reverse=highest)
    remaining = 1.0
    states = {(n, 0): {0: 1.0}}
    for v in order:
        pv = face_dist[v]
        q = min(1.0, pv / remaining) if remaining > 1e-15 else 1.0
        remaining -= pv
        nxt = {}
        for (left, kept), sums in states.items():
            if left == 0:
                tgt = nxt.setdefault((0, kept), {})
                for s, pr in sums.items():
                    tgt[s] = tgt.get(s, 0.0) + pr
                continue
            for c in range(left + 1):
                w = math.comb(left, c) * (q ** c) * ((1.0 - q) ** (left - c))
                if w <= 0.0:
                    continue
                take = min(c, k - kept)
                tgt = nxt.setdefault((left - c, kept + take), {})
                add = take * v
                for s, pr in sums.items():
                    tgt[s + add] = tgt.get(s + add, 0.0) + pr * w
        states = nxt
    out = {}
    for (left, kept), sums in states.items():
        if left == 0:
            for s, pr in sums.items():
                out[s] = out.get(s, 0.0) + pr
    return out


def _term_dist(t):
    if t["kind"] == "const":
        return {t["value"]: 1.0}
    fd = _face_dist(t)
    n = t["n"]
    if t["cmp"]:
        op, target = t["cmp"]
        p = sum(pr for v, pr in fd.items() if _OPS[op](v, target))
        return {k: math.comb(n, k) * (p ** k) * ((1.0 - p) ** (n - k)) for k in range(n + 1)}
    if t["keep"] and t["keep"][1] < n:
        if n * len(fd) > 6000:
            die("too large for exact keep/drop odds (%d dice of %d faces); use fewer dice" % (n, len(fd)))
        return _keep_dist(n, fd, t["keep"][1], t["keep"][0] == "high")
    if n * n * len(fd) * len(fd) > 60000000:
        die("too large for exact odds (%d dice of %d faces); use 'roll --times' to sample instead" % (n, len(fd)))
    out = {0: 1.0}
    for _ in range(n):
        out = _convolve(out, fd)
    return out


def distribution(terms):
    """Exact probability of each total: {value: probability}."""
    out = {0: 1.0}
    for t in terms:
        out = _convolve(out, _term_dist(t), t["sign"])
    return out


def stats(dist):
    vals = sorted(dist)
    mean = sum(v * p for v, p in dist.items())
    var = sum((v - mean) ** 2 * p for v, p in dist.items())
    acc, median = 0.0, vals[-1]
    for v in vals:
        acc += dist[v]
        if acc >= 0.5 - 1e-12:
            median = v
            break
    top = max(dist.values())
    modes = [v for v in vals if abs(dist[v] - top) < 1e-12]
    return {"min": vals[0], "max": vals[-1], "mean": mean, "sd": math.sqrt(max(0.0, var)), "median": median, "modes": modes}


def at_least(dist, target):
    return sum(p for v, p in dist.items() if v >= target)


def pct(p):
    if p <= 0:
        return "0%"
    if p >= 1 - 1e-12:
        return "100%"
    if p < 0.0001:
        return "<0.01%"
    return ("%.2f" % (p * 100)).rstrip("0").rstrip(".") + "%"


def one_in(p):
    return "" if p <= 0 or p >= 1 else " (1 in %s)" % trim(1.0 / p, 1)


# ---- commands

def cmd_roll(a):
    rng = make_rng(a.seed)
    parsed = [(spec, parse(spec)) for spec in a.dice]
    if a.times < 1 or a.times > 1000:
        die("--times must be 1 to 1000")
    width = max(len(spec) for spec, _ in parsed)
    grand = 0
    for n in range(a.times):
        for spec, terms in parsed:
            total, shown = roll_once(terms, rng)
            grand += total
            verdict = ""
            if a.target is not None:
                verdict = "  -> %s (needs %d+)" % ("PASS" if total >= a.target else "FAIL", a.target)
            key = "ROLL" if a.times == 1 else "ROLL %d" % (n + 1)
            rec(key, "%-*s %s = %d%s" % (width, spec, shown, total, verdict))
    if len(parsed) * a.times > 1:
        rec("TOTAL", "%d" % grand)
    rec("SEED", "%d (repeatable)" % a.seed if a.seed is not None else "none: system randomness, not repeatable")


def cmd_odds(a):
    terms = parse(a.expr)
    dist = distribution(terms)
    st = stats(dist)
    rec("EXPR", "%s [derived, exact%s]" % (a.expr, "; explosions counted %d deep" % EXPLODE_DEPTH
                                           if any(t.get("explode") for t in terms) else ""))
    rec("RANGE", "%d to %d | mean %s | sd %s | median %d | most likely %s" % (
        st["min"], st["max"], trim(st["mean"], 2), trim(st["sd"], 2), st["median"],
        ", ".join(str(m) for m in st["modes"][:4]) + (" ..." if len(st["modes"]) > 4 else "")))
    if a.target is not None:
        ge = at_least(dist, a.target)
        eq = dist.get(a.target, 0.0)
        le = sum(p for v, p in dist.items() if v <= a.target)
        rec("TARGET", "%d or more: %s%s | exactly %d: %s | %d or less: %s" % (
            a.target, pct(ge), one_in(ge), a.target, pct(eq), a.target, pct(le)))
    if a.vs:
        other = distribution(parse(a.vs))
        win = tie = 0.0
        for va, pa in dist.items():
            for vb, pb in other.items():
                if va > vb:
                    win += pa * pb
                elif va == vb:
                    tie += pa * pb
        rec("VS", "%s against %s: first higher %s | tie %s | second higher %s" % (
            a.expr, a.vs, pct(win), pct(tie), pct(max(0.0, 1.0 - win - tie))))
    vals = sorted(dist)
    if len(vals) <= 30 or a.full:
        top = max(dist.values())
        rows, acc = [], 1.0
        for v in vals:
            rows.append((v, pct(dist[v]), pct(acc), "#" * max(1 if dist[v] > 0 else 0, int(round(dist[v] / top * 24)))))
            acc -= dist[v]
        table(rows, header=("total", "exactly", "or more", ""), indent=2, right=(0, 1, 2))
    else:
        marks, acc, i = [], 0.0, 0
        want = [0.05, 0.25, 0.5, 0.75, 0.95]
        for v in vals:
            acc += dist[v]
            while i < len(want) and acc >= want[i] - 1e-12:
                marks.append("%d%%: %d" % (int(want[i] * 100), v))
                i += 1
        rec("SPREAD", " | ".join(marks) + "  (use --full for every value)")


def register(sub):
    p = command(sub, "combat", "roll", cmd_roll, "dice for sims and tabletop, with system randomness or a seed",
                ["roll 3d6+2", "roll adv+5 --target 15", "roll 4d6dl1 --times 6", "roll 6d10>=7", "roll 2d6 d20 --seed 7"])
    p.add_argument("dice", nargs="+", help="expressions: 3d6+2, 2d20kh1, 4d6dl1, 3d6!, 6d10>=7, adv, dis, d%%, 4dF")
    p.add_argument("--seed", type=int, help="seed for a repeatable roll (omit for real randomness)")
    p.add_argument("--times", type=int, default=1, help="repeat the whole roll this many times")
    p.add_argument("--target", type=int, help="mark each roll PASS or FAIL against this total")

    p = command(sub, "combat", "odds", cmd_odds, "exact odds of a dice expression: spread, target chance, contests",
                ["odds 3d6", "odds 2d20kh1+5 --target 15", "odds 4d6dl1 --full", "odds 2d6+3 --vs d20", "odds 8d10>=7 --target 3"])
    p.add_argument("expr", help="a dice expression, as for roll")
    p.add_argument("--target", type=int, help="chance of this total or more (and exactly, and or less)")
    p.add_argument("--vs", help="a second expression: chance the first beats it")
    p.add_argument("--full", action="store_true", help="print every value even when there are many")
