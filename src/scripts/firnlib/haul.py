"""Loads: what a vehicle may carry, what it may tow, and whether a thing fits in a space.

The limits are the ones on the vehicle's own plate and papers; this does the sums. The two towing
ratios it comments on are advice from towing clubs, not law, and are labelled so. Spaces and items
are treated as boxes with straight walls: measure the narrowest points.
"""
import itertools
import math
import re

from .core import command, die, more, num, rec, trim

DRIVER_KG = 75.0
NOSE_LOW, NOSE_HIGH = 5.0, 7.0
RATIO_EASY, RATIO_MAX = 85.0, 100.0
EPS = 1e-6
NAMED_ITEMS = {
    "europallet": (1200.0, 800.0, 144.0),
    "halfpallet": (800.0, 600.0, 144.0),
}
UNIT_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
_WEIGHT_RE = re.compile(r"^\s*(?:(\d+)\s*[xX]\s*)?(\d+(?:\.\d+)?)\s*(?:kg)?\s*$")


def weights(tokens, what):
    """['80', '2x75'] -> [80.0, 75.0, 75.0]."""
    out = []
    for t in tokens or []:
        m = _WEIGHT_RE.match(str(t))
        if not m:
            die("%s: '%s' is not a weight in kg (use 80, or 2x75 for two of them)" % (what, t))
        out += [float(m.group(2))] * int(m.group(1) or 1)
    return out


def _pct(part, whole):
    return trim(part / whole * 100.0, 0)


# ---- load

def cmd_load(a):
    if a.payload is not None:
        payload, basis = a.payload, "as given"
    elif a.max is not None and a.kerb is not None:
        payload, basis = a.max - a.kerb, "%s kg maximum - %s kg kerb" % (num(a.max), num(a.kerb))
    else:
        die("load needs --max and --kerb from the vehicle's papers, or --payload")
    if payload <= 0:
        die("that leaves no payload at all: check the maximum and kerb figures")
    people = weights(a.people, "--people")
    cargo = weights(a.cargo, "--cargo")
    for name, value in (("--roof", a.roof), ("--roof-limit", a.roof_limit), ("--nose", a.nose), ("--nose-limit", a.nose_limit)):
        if value is not None and value < 0:
            die("%s cannot be negative" % name)
    people_kg = sum(people)
    counted = max(0.0, people_kg - DRIVER_KG) if (a.driver_included and people) else people_kg
    roof, nose = a.roof or 0.0, a.nose or 0.0
    rec("PAYLOAD", "%s kg (%s) [derived]" % (num(payload), basis))
    parts = []
    if people:
        note = " less the %s kg driver already in the kerb figure" % trim(DRIVER_KG, 0) if a.driver_included else ""
        parts.append("%d %s %s kg%s" % (len(people), "person" if len(people) == 1 else "people", num(people_kg), note))
    if cargo:
        parts.append("cargo %s kg" % num(sum(cargo)))
    if roof:
        parts.append("roof %s kg" % num(roof))
    if nose:
        parts.append("towball %s kg" % num(nose))
    on_board = counted + sum(cargo) + roof + nose
    if not parts:
        rec("ON BOARD", "nothing listed: add --people, --cargo, --roof or --nose")
    else:
        rec("ON BOARD", "%s = %s kg" % (" + ".join(parts), num(on_board)))
    margin = payload - on_board
    over = margin < -EPS
    if over:
        rec("OVER", "by %s kg: above the permitted maximum. Not legal to drive, and outside what the brakes, tyres and "
                    "suspension were approved for. Take something out" % num(-margin))
    elif parts:
        rec("MARGIN", "%s kg spare; %s%% of the payload used [derived]" % (num(margin), _pct(on_board, payload)))
    if a.max is not None and parts:
        rolling = a.max - margin
        rec("MASS", "%s kg on the road, %s%% of the %s kg maximum [derived]" % (num(rolling), _pct(rolling, a.max), num(a.max)))
    if roof:
        if a.roof_limit:
            state = "OVER the limit by %s kg" % num(roof - a.roof_limit) if roof > a.roof_limit + EPS else "within the limit"
            rec("ROOF", "%s kg of %s kg allowed (%s%%): %s. Bars and box count towards it" % (
                num(roof), num(a.roof_limit), _pct(roof, a.roof_limit), state))
        else:
            rec("ROOF", "%s kg up top: the roof limit is in the handbook, and the bars and the box count towards it" % num(roof))
    if nose:
        if a.nose_limit:
            state = "OVER the limit by %s kg" % num(nose - a.nose_limit) if nose > a.nose_limit + EPS else "within the limit"
            rec("TOWBALL", "%s kg of %s kg allowed: %s" % (num(nose), num(a.nose_limit), state))
        else:
            rec("TOWBALL", "%s kg on the ball counts as payload; its own limit is on the towbar plate" % num(nose))
    rec("NOTE", "kerb mass is defined differently from maker to maker. If the papers give a mass in running order, a %s kg "
                "driver is already in it: add --driver-included" % trim(DRIVER_KG, 0))
    rec("NOTE", "axle limits are separate from the total: heavy things low and between the axles. A loaded car wants the loaded "
                "tyre pressures from the door pillar, and more room to stop")


# ---- tow

def cmd_tow(a):
    t = a.trailer
    if t <= 0:
        die("--trailer is the trailer's weight as loaded, in kg")
    for name, value in (("--trailer-max", a.trailer_max), ("--limit", a.limit), ("--unbraked-limit", a.unbraked_limit),
                        ("--kerb", a.kerb), ("--car", a.car), ("--car-max", a.car_max), ("--train-max", a.train_max),
                        ("--nose", a.nose), ("--nose-limit", a.nose_limit)):
        if value is not None and value <= 0:
            die("%s must be more than zero" % name)
    problems, unchecked, advice = [], [], []
    line = "%s kg as loaded, %s" % (num(t), "no brakes" if a.unbraked else "braked")
    if a.trailer_max:
        line += "; %s%% of its own %s kg plate" % (_pct(t, a.trailer_max), num(a.trailer_max))
        if t > a.trailer_max + EPS:
            problems.append("the trailer is %s kg over its own plate" % num(t - a.trailer_max))
    rec("TRAILER", line)
    limit = a.unbraked_limit if a.unbraked else a.limit
    kind = "unbraked" if a.unbraked else "braked"
    if limit is None:
        rec("LIMIT", "no %s towing limit given: it is in the registration papers and the handbook (--%s)" % (
            kind, "unbraked-limit" if a.unbraked else "limit"))
        unchecked.append("the car's %s towing limit" % kind)
    else:
        good = t <= limit + EPS
        rec("LIMIT", "%s kg of the car's %s kg %s towing limit (%s%%): %s" % (
            num(t), num(limit), kind, _pct(t, limit), "within" if good else "OVER by %s kg" % num(t - limit)))
        if not good:
            problems.append("the trailer is %s kg over the car's %s towing limit" % (num(t - limit), kind))
    if a.kerb:
        ratio = t / a.kerb * 100.0
        if ratio <= RATIO_EASY + EPS:
            say = "inside the %s%% that towing clubs advise for anyone new to it" % trim(RATIO_EASY, 0)
        elif ratio <= RATIO_MAX + EPS:
            say = "above the %s%% advised for beginners: for experienced towers only" % trim(RATIO_EASY, 0)
            advice.append("trailer above %s%% of the car's kerb mass" % trim(RATIO_EASY, 0))
        else:
            say = "heavier than the car, which towing clubs advise against whatever the plated limit says"
            advice.append("trailer heavier than the car")
        rec("RATIO", "trailer is %s%% of the car's %s kg kerb mass: %s [guideline from towing clubs, not law]" % (
            trim(ratio, 0), num(a.kerb), say))
    else:
        unchecked.append("the trailer against the car's kerb mass (--kerb)")
    lo, hi = t * NOSE_LOW / 100.0, t * NOSE_HIGH / 100.0
    if a.nose is None:
        cap = " and never above %s kg, the limit given" % num(a.nose_limit) if a.nose_limit else ", and never above the lowest of the car's, towbar's and hitch's limits"
        rec("NOSE", "aim for %s to %s kg on the ball (%s to %s%% of the trailer)%s [guideline]" % (
            num(lo), num(hi), trim(NOSE_LOW, 0), trim(NOSE_HIGH, 0), cap))
    else:
        share = a.nose / t * 100.0
        if share < NOSE_LOW - EPS:
            say = "lighter than the %s to %s%% guideline: too little weight on the ball lets a trailer sway. Move load forward" % (
                trim(NOSE_LOW, 0), trim(NOSE_HIGH, 0))
            advice.append("noseweight below the guideline")
        elif share <= NOSE_HIGH + EPS:
            say = "inside the %s to %s%% guideline" % (trim(NOSE_LOW, 0), trim(NOSE_HIGH, 0))
        else:
            say = "heavier than the %s to %s%% guideline: acceptable only under every limit, and it comes off the car's payload" % (
                trim(NOSE_LOW, 0), trim(NOSE_HIGH, 0))
        line = "%s kg on the ball, %s%% of the trailer: %s" % (num(a.nose), trim(share, 1), say)
        if a.nose_limit:
            if a.nose > a.nose_limit + EPS:
                line += ". OVER the %s kg limit by %s kg" % (num(a.nose_limit), num(a.nose - a.nose_limit))
                problems.append("the noseweight is %s kg over its limit" % num(a.nose - a.nose_limit))
            else:
                line += ". Within the %s kg limit" % num(a.nose_limit)
        else:
            unchecked.append("the noseweight limit (the lowest of the car's, the towbar's and the hitch's)")
        rec("NOSE", line + " [the percentage is a guideline, not law]")
    if a.car and a.train_max:
        train = a.car + t
        good = train <= a.train_max + EPS
        rec("TRAIN", "car %s kg + trailer %s kg = %s kg of the %s kg permitted train mass (%s%%): %s" % (
            num(a.car), num(t), num(train), num(a.train_max), _pct(train, a.train_max),
            "within" if good else "OVER by %s kg" % num(train - a.train_max)))
        if not good:
            problems.append("car and trailer together are %s kg over the permitted train mass" % num(train - a.train_max))
    else:
        unchecked.append("the train mass (--car as loaded, --train-max)")
    if a.car and a.car_max:
        with_nose = a.car + (a.nose or 0.0)
        good = with_nose <= a.car_max + EPS
        rec("CAR", "%s kg with the noseweight on the ball, %s%% of its %s kg maximum: %s" % (
            num(with_nose), _pct(with_nose, a.car_max), num(a.car_max), "within" if good else "OVER by %s kg" % num(with_nose - a.car_max)))
        if not good:
            problems.append("the car itself is %s kg over its maximum" % num(with_nose - a.car_max))
    if problems:
        rec("VERDICT", "NOT WITHIN LIMITS: %s" % "; ".join(problems))
    else:
        rec("VERDICT", "within every limit given%s" % ("; advice not met: " + "; ".join(advice) if advice else ""))
    if unchecked:
        rec("UNCHECKED", "; ".join(unchecked))
    rec("NOTE", "the limits are the ones on the papers and plates: this only does the sums. Licence category, speed limits, "
                "mirrors and breakaway cables for towing differ by country and change: look the current rule up")


# ---- fit

def rect_in_rect(p, q, big_p, big_q):
    """Can a p x q rectangle lie inside a big_p x big_q one, turned to any angle?
    Returns the turn in degrees (0 or 90 when it goes in square), or None if it cannot."""
    tol = 1e-7
    if p <= big_p + tol and q <= big_q + tol:
        return 0.0
    if q <= big_p + tol and p <= big_q + tol:
        return 90.0
    r = math.hypot(p, q)
    phi = math.atan2(q, p)
    cands = []
    if big_p < r:
        d = math.acos(big_p / r)
        cands += [phi - d, phi + d]
    if big_q < r:
        d = math.acos(big_q / r)
        cands += [math.pi / 2 - phi - d, math.pi / 2 - phi + d]
    for th in cands:
        if -1e-12 <= th <= math.pi / 2 + 1e-12:
            w = p * math.cos(th) + q * math.sin(th)
            h = p * math.sin(th) + q * math.cos(th)
            if w <= big_p + tol and h <= big_q + tol:
                return math.degrees(th)
    return None


def orientations(box, upright=False):
    """The distinct ways round a box can stand, flattest first."""
    seen = set()
    for perm in itertools.permutations((0, 1, 2)):
        if upright and perm[2] != 2:
            continue
        seen.add((box[perm[0]], box[perm[1]], box[perm[2]]))
    return sorted(seen, key=lambda d: (d[2], -d[0]))


def box_fit(item, space, upright=False):
    """How one box goes into a space: ('square', ways), ('turned', where, degrees) or None."""
    ways = [d for d in orientations(item, upright) if all(d[k] <= space[k] + EPS for k in range(3))]
    if ways:
        return ("square", len(ways))
    best = None
    for i in range(3):
        for j in range(3):
            if upright and not (i == 2 and j == 2):
                continue
            if item[i] > space[j] + EPS:
                continue
            p, q = [item[k] for k in range(3) if k != i]
            big_p, big_q = [space[k] for k in range(3) if k != j]
            ang = rect_in_rect(p, q, big_p, big_q)
            if ang is None:
                continue
            cand = ("turned", "on the floor" if j == 2 else "leaning on a diagonal", min(ang, 90.0 - ang))
            if best is None or (cand[1] == "on the floor" and best[1] != "on the floor"):
                best = cand
    return best


def through_opening(item, opening, upright=False):
    """Can the box pass through a width x height opening, going in along one of its edges?"""
    w, h = opening
    for i in range(3):
        p, q = [item[k] for k in range(3) if k != i]
        if upright:
            if i == 2:
                continue
            across = item[1] if i == 0 else item[0]
            if across <= w + EPS and item[2] <= h + EPS:
                return True
        elif rect_in_rect(p, q, w, h) is not None:
            return True
    return False


def pack(boxes, space, upright=False):
    """A simple packer: biggest box first, each into the smallest free block that takes it, and what is left of
    the block is cut into three. True when every box found a place. False is not proof that no layout exists."""
    free = [(0.0, 0.0, 0.0, space[0], space[1], space[2])]
    for box in sorted(boxes, key=lambda b: -(b[0] * b[1] * b[2])):
        free.sort(key=lambda f: f[3] * f[4] * f[5])
        placed = False
        for idx, (fx, fy, fz, dx, dy, dz) in enumerate(free):
            for bx, by, bz in orientations(box, upright):
                if bx <= dx + EPS and by <= dy + EPS and bz <= dz + EPS:
                    del free[idx]
                    for block in ((fx + bx, fy, fz, dx - bx, dy, dz), (fx, fy + by, fz, bx, dy - by, dz),
                                  (fx, fy, fz + bz, bx, by, dz - bz)):
                        if block[3] > EPS and block[4] > EPS and block[5] > EPS:
                            free.append(block)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            return False
    return True


def _dims(text, factor, what):
    parts = re.split(r"\s*[xX]\s*", str(text).strip())
    try:
        vals = [float(p) * factor for p in parts]
    except ValueError:
        vals = []
    if len(vals) != 3 or any(v <= 0 for v in vals):
        die("%s is three sizes, length x width x height, such as 1200x800x144: '%s'" % (what, text))
    return tuple(vals)


def _item(text, factor):
    """'1200x800x144', '600x400x300:4', 'europallet:2' -> (label, dims in mm, count)."""
    body, _, count = str(text).partition(":")
    n = 1
    if count:
        if not count.strip().isdigit() or int(count) < 1:
            die("the count after ':' is a whole number of items: '%s'" % text)
        n = int(count)
    key = body.strip().lower()
    if key in NAMED_ITEMS:
        return key, NAMED_ITEMS[key], n
    return "", _dims(body, factor, "an item"), n


def _mm(d):
    return "%s x %s x %s mm" % (num(d[0]), num(d[1]), num(d[2]))


def cmd_fit(a):
    factor = UNIT_MM[a.unit]
    space = _dims(a.space, factor, "--space")
    items = [_item(t, factor) for t in (a.item or [])]
    if not items and a.long is None:
        die("fit needs something to try: --item LxWxH (repeatable) or --long LENGTH")
    opening = None
    if a.opening:
        parts = re.split(r"\s*[xX]\s*", a.opening.strip())
        try:
            opening = (float(parts[0]) * factor, float(parts[1]) * factor)
        except (ValueError, IndexError):
            die("--opening is width x height, such as 1000x700")
        if len(parts) != 2 or min(opening) <= 0:
            die("--opening is width x height, such as 1000x700")
    volume = space[0] * space[1] * space[2] / 1e9
    floor_diag = math.hypot(space[0], space[1])
    full_diag = math.sqrt(sum(s * s for s in space))
    rec("SPACE", "%s = %s m3; longest straight line %s mm across the floor, %s mm corner to corner [derived]" % (
        _mm(space), trim(volume, 2), num(floor_diag), num(full_diag)))
    if a.unit != "mm":
        more("sizes were given in %s and are shown in mm" % a.unit)
    all_square, none_out, total, boxes = True, True, 0.0, []
    for n, (label, dims, count) in enumerate(items, 1):
        how = box_fit(dims, space, a.upright)
        name = "%s%s%s" % (_mm(dims), " (%s)" % label if label else "", " x %d" % count if count > 1 else "")
        total += dims[0] * dims[1] * dims[2] / 1e9 * count
        if how is None:
            all_square = none_out = False
            line = "%s: DOES NOT FIT%s: not square on, not turned on the floor%s" % (
                name, " upright" if a.upright else "", "" if a.upright else ", not leaned on a diagonal")
        elif how[0] == "square":
            line = "%s: fits, %d way%s round%s" % (name, how[1], "" if how[1] == 1 else "s", " kept upright" if a.upright else "")
            boxes += [dims] * count
        else:
            all_square = False
            line = "%s: fits only %s, turned about %s deg; nothing else will go beside it squarely" % (name, how[1], trim(how[2], 0))
        if opening and how is not None:
            line += "; passes the opening" if through_opening(dims, opening, a.upright) else "; but DOES NOT PASS the %s x %s mm opening" % (
                num(opening[0]), num(opening[1]))
        rec("ITEM %d" % n, line + " [derived]")
    if a.long is not None:
        length = a.long * factor
        if length <= 0:
            die("--long is a length, more than zero")
        longest_side = max(space[0], space[1])
        if length <= longest_side + EPS:
            say = "lies straight along the floor"
        elif length <= floor_diag + EPS:
            say = "lies across the floor on the diagonal"
        elif length <= full_diag + EPS:
            say = "goes in only corner to corner, floor to roof, and only if it is thin"
        else:
            say = "DOES NOT FIT: longer than the %s mm from corner to corner" % num(full_diag)
        rec("LONG", "%s mm: %s [derived; a thin, stiff item]" % (num(length), say))
    count_all = sum(c for _, _, c in items)
    if count_all > 1:
        share = total / volume * 100.0
        line = "%d items, %s m3, %s%% of the space" % (count_all, trim(total, 2), trim(share, 0))
        if not none_out:
            line += "; at least one of them does not go in at all, so the set cannot"
        elif share > 100.0:
            line += "; more than the space holds"
        elif not all_square:
            line += "; not tried together, because one of them only goes in turned"
        elif count_all > 400:
            line += "; too many to try a layout"
        elif pack(boxes, space, a.upright):
            line += "; a simple packer found room for all of them"
        else:
            line += "; a simple packer did NOT find room for all of them. That is not proof it cannot be done, but do not count on it"
        rec("TOGETHER", line + " [derived]")
    rec("NOTE", "boxes and straight walls: wheel arches, a sloping tailgate and seat backs take room this cannot see. "
                "Measure the narrowest points, and tie the load down")


def register(sub):
    p = command(sub, "garage", "load", cmd_load,
                "payload: what is on board against what the vehicle may carry, with roof and towball limits",
                ["load --max 2100 --kerb 1500 --people 80 75 2x35 --cargo 120 --roof 45 --roof-limit 75",
                 "load --payload 520 --people 2x80 --cargo 150 --nose 70 --nose-limit 80",
                 "load --max 1950 --kerb 1420 --driver-included --people 90 70 --cargo 200"])
    p.add_argument("--max", type=float, help="permitted maximum mass of the vehicle, kg (from its papers or plate)")
    p.add_argument("--kerb", type=float, help="kerb mass, kg")
    p.add_argument("--payload", type=float, help="the payload itself, kg, instead of --max and --kerb")
    p.add_argument("--driver-included", action="store_true", help="the kerb figure already includes a 75 kg driver (mass in running order)")
    p.add_argument("--people", nargs="*", help="each person's weight in kg; 2x75 for two of them")
    p.add_argument("--cargo", nargs="*", help="cargo weights in kg")
    p.add_argument("--roof", type=float, help="load on the roof, kg, bars and box included")
    p.add_argument("--roof-limit", type=float, help="the roof load limit from the handbook, kg")
    p.add_argument("--nose", type=float, help="weight on the towball, kg (a trailer's nose, or a bike carrier)")
    p.add_argument("--nose-limit", type=float, help="the towball limit, kg")

    p = command(sub, "garage", "tow", cmd_tow,
                "towing sums: trailer against the car's limits, the kerb-mass ratio, noseweight and train mass",
                ["tow --trailer 1300 --limit 1500 --kerb 1650 --nose 75 --nose-limit 80",
                 "tow --trailer 1300 --trailer-max 1500 --limit 1500 --kerb 1650 --car 1900 --car-max 2150 --train-max 3500 --nose 80",
                 "tow --trailer 600 --unbraked --unbraked-limit 750 --kerb 1400"])
    p.add_argument("--trailer", type=float, required=True, help="the trailer's weight as loaded, kg")
    p.add_argument("--trailer-max", type=float, help="the trailer's own plated maximum, kg")
    p.add_argument("--limit", type=float, help="the car's towing limit for a braked trailer, kg")
    p.add_argument("--unbraked-limit", type=float, help="the car's towing limit for a trailer without brakes, kg")
    p.add_argument("--unbraked", action="store_true", help="the trailer has no brakes")
    p.add_argument("--kerb", type=float, help="the car's kerb mass, kg, for the ratio towing clubs advise on")
    p.add_argument("--car", type=float, help="the car's weight as loaded, without the trailer, kg")
    p.add_argument("--car-max", type=float, help="the car's own permitted maximum, kg")
    p.add_argument("--train-max", type=float, help="the permitted mass of car and trailer together, kg")
    p.add_argument("--nose", type=float, help="the weight on the towball, kg")
    p.add_argument("--nose-limit", type=float, help="the lowest of the car's, the towbar's and the hitch's noseweight limits, kg")

    p = command(sub, "garage", "fit", cmd_fit,
                "will it go in: boxes against a load space, turned if need be, a long item, several items together",
                ["fit --space 1800x1000x700 --item 1200x800x144", "fit --space 1800x1000x700 --item europallet --item 600x400x300:4",
                 "fit --space 1800x1000x700 --item 1900x150x100 --long 2100",
                 "fit --space 180x100x70 --unit cm --item 90x60x60 --upright --opening 95x65"])
    p.add_argument("--space", required=True, help="the load space, length x width x height (mm unless --unit says otherwise)")
    p.add_argument("--item", action="append", help="a box, LxWxH; add :N for N of them; or europallet, halfpallet. Repeatable")
    p.add_argument("--long", type=float, help="a long thin item (skis, a pipe, a plank): its length")
    p.add_argument("--opening", help="the opening it must pass through, width x height")
    p.add_argument("--upright", action="store_true", help="items must stay the right way up")
    p.add_argument("--unit", choices=sorted(UNIT_MM), default="mm", help="unit of every size given (default mm)")
