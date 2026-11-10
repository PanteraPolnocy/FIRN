"""Armour and spotting arithmetic for tank games.

The geometry is exact and universal: a sloped plate presents nominal / cos(angle) of metal.
Everything else is a game rule. No game rule lives in this code. There are two ways to supply them:
  --shell ap|apcr|heat|he   FIRN's house rules from data/rulesets.json, inspired by World of Tanks
                            (its client as it stood in November 2026). Dated, editable, and labelled as such.
  explicit options          any value you pass (--norm, --ricochet, --overmatch, --two-cal, --rng ...) wins.
                            For a question about the real game, check the current patch and pass them in.

Order of operations in the house rules:
  1. the raw impact angle decides an automatic ricochet (unless the shell overmatches the plate)
  2. normalisation reduces the angle (more for a shell over twice the plate's thickness)
  3. effective thickness = nominal / cos(normalised angle)
  4. penetration is rolled inside its spread and compared

This is game maths. It says nothing about real armour and real shells.
"""
import math

from .core import command, die, load_data, more, num, rec, table, trim


SOURCE_LINE = ("geometry is exact; game values are the house rules shown above or the ones you passed in. "
               "For the real game, check the current patch.")


def apply_rules(a):
    """Fill in whatever the caller left out from the house rules, if a shell type was named. Returns a RULES line or None."""
    line = None
    if getattr(a, "shell", None):
        rules = load_data("rulesets")["house"]
        sh = rules["shells"][a.shell]
        for field in ("norm", "ricochet", "overmatch", "two_cal"):
            if getattr(a, field, None) is None and sh.get(field) is not None:
                setattr(a, field, sh[field])
        for field in ("rng", "sigma"):
            if getattr(a, field, None) is None:
                setattr(a, field, rules[field])
        if hasattr(a, "gap_loss") and a.gap_loss is None and sh.get("gap_loss") is not None:
            a.gap_loss = sh["gap_loss"]
        bits = ["normalisation %s deg" % trim(a.norm or 0, 1)]
        bits.append("ricochet at %s deg" % trim(a.ricochet, 1) if a.ricochet else "no ricochet")
        if a.overmatch:
            bits.append("overmatch over %s x" % trim(a.overmatch, 1))
        if a.two_cal:
            bits.append("2-calibre x %s" % trim(a.two_cal, 2))
        bits.append("spread +-%s%%" % trim(a.rng, 0))
        line = "%s shell: %s [%s; for the real game check the current patch]" % (sh["name"], ", ".join(bits), rules["label"])
    if getattr(a, "norm", None) is None:
        a.norm = 0.0
    return line


def impact_angle(slope, yaw, elev=0.0):
    """Angle from the plate normal for a plate sloped back by `slope`, a hull turned by `yaw`,
    and a shell coming down at `elev` degrees. All in degrees."""
    s, y, e = math.radians(slope), math.radians(yaw), math.radians(elev)
    c = math.cos(s) * math.cos(y) * math.cos(e) + math.sin(s) * math.sin(e)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def normalised(angle, norm, calibre, thickness, two_cal):
    """(normalised angle, normalisation used, True if the 2-calibre boost applied)."""
    boost = False
    n = norm or 0.0
    if n and two_cal and calibre and calibre > 2.0 * thickness > 0:
        n = n * two_cal * calibre / (2.0 * thickness)
        boost = True
    return max(0.0, angle - n), n, boost


def pen_chance(pen, eff, spread, sigma, uniform):
    """Chance that a penetration roll beats the effective thickness."""
    if not spread:
        return 1.0 if pen > eff else 0.0
    lo, hi = pen * (1 - spread), pen * (1 + spread)
    if eff <= lo:
        return 1.0
    if eff > hi:
        return 0.0
    if uniform or not sigma:
        return (hi - eff) / (hi - lo)
    sd = sigma * spread * pen
    return 0.5 * (1.0 - math.erf((eff - pen) / (sd * math.sqrt(2.0))))


def pct(p):
    return "%s%%" % trim(p * 100, 1)


def _pen_at(a):
    """(penetration at the range asked for, text explaining it) or (None, None)."""
    if a.pen_near is not None or a.pen_far is not None:
        if a.pen_near is None or a.pen_far is None or a.dist is None:
            die("for penetration by range give --pen-near, --pen-far and --dist (and --near/--far if not 50 and 500)")
        if a.far <= a.near:
            die("--far must be beyond --near")
        if a.dist <= a.near:
            p = a.pen_near
        else:
            p = a.pen_near + (a.pen_far - a.pen_near) * (a.dist - a.near) / (a.far - a.near)
        p = max(0.0, p)
        return p, "%s mm at %s m (from %s at %s m and %s at %s m, straight line, flat inside %s m)" % (
            trim(p, 0), trim(a.dist, 0), trim(a.pen_near, 0), trim(a.near, 0), trim(a.pen_far, 0), trim(a.far, 0), trim(a.near, 0))
    if a.pen is not None:
        return a.pen, "%s mm average, as given" % trim(a.pen, 0)
    return None, None


def _spread(a):
    spread = (a.rng or 0.0) / 100.0
    if not 0 <= spread < 1:
        die("--rng is the spread in percent, 0 to 99")
    return spread


def cmd_armour(a):
    if a.thickness <= 0:
        die("thickness must be positive")
    if not (0 <= a.slope < 90 and 0 <= a.yaw < 90 and -89 < a.elev < 90):
        die("angles are in degrees from the plate normal, 0 to under 90")
    rules_line = apply_rules(a)
    if rules_line:
        rec("RULES", rules_line)
    angle = impact_angle(a.slope, a.yaw, a.elev)
    parts = ["%s mm" % trim(a.thickness, 1), "slope %s deg" % trim(a.slope, 1)]
    if a.yaw:
        parts.append("hull yaw %s deg" % trim(a.yaw, 1))
    if a.elev:
        parts.append("shell descending %s deg" % trim(a.elev, 1))
    rec("PLATE", ", ".join(parts))
    rec("IMPACT", "%s deg from the normal [derived]" % trim(angle, 1))
    over = bool(a.caliber and a.overmatch and a.caliber > a.overmatch * a.thickness)
    if a.caliber and a.overmatch:
        rec("OVERMATCH", "%s: %s mm shell against %s x %s mm = %s mm [game rule]" % (
            "yes, no automatic ricochet" if over else "no", trim(a.caliber, 0), trim(a.overmatch, 1), trim(a.thickness, 1),
            trim(a.overmatch * a.thickness, 0)))
    if a.ricochet:
        if angle >= a.ricochet and not over:
            rec("RICOCHET", "yes: %s deg is at or past the %s deg limit [game rule]. The shell does not go in." % (
                trim(angle, 1), trim(a.ricochet, 1)))
            rec("SOURCE", SOURCE_LINE)
            return
        rec("RICOCHET", "no: %s" % ("overmatched" if angle >= a.ricochet else "%s deg is under the %s deg limit" % (
            trim(angle, 1), trim(a.ricochet, 1))))
    eff_angle, used, boost = normalised(angle, a.norm, a.caliber, a.thickness, a.two_cal)
    if a.norm:
        rec("NORMAL", "-%s deg -> %s deg%s [game rule]" % (
            trim(used, 1), trim(eff_angle, 1),
            " (2-calibre boost: %s mm is over twice %s mm)" % (trim(a.caliber, 0), trim(a.thickness, 1)) if boost else ""))
    eff = a.thickness / math.cos(math.radians(eff_angle))
    rec("EFFECTIVE", "%s mm [derived]" % trim(eff, 0))
    pen, how = _pen_at(a)
    if pen is not None:
        if a.screen:
            gap_loss = (a.gap or 0.0) / 100.0 * (a.gap_loss or 0.0) / 100.0
            left = max(0.0, (pen - a.screen) * (1.0 - gap_loss))
            rec("SCREEN", "%s mm of screen, then %s mm of air at %s%% lost per 100 mm: %s mm of penetration left [game rule]" % (
                trim(a.screen, 0), trim(a.gap or 0, 0), trim(a.gap_loss or 0, 1), trim(left, 0)))
            pen = left
        rec("PEN", how if not a.screen else "%s mm after the screen" % trim(pen, 0))
        spread = _spread(a)
        chance = pen_chance(pen, eff, spread, a.sigma, a.uniform)
        if spread:
            shape = "even spread" if (a.uniform or not a.sigma) else "bell curve, one sigma = %s of the spread" % trim(a.sigma, 2)
            rec("CHANCE", "%s to go through: rolls run %s to %s mm against %s mm (+-%s%%, %s) [game rule]" % (
                pct(chance), trim(pen * (1 - spread), 0), trim(pen * (1 + spread), 0), trim(eff, 0), trim(a.rng, 0), shape))
        else:
            rec("CHANCE", "%s on average penetration alone (%s vs %s mm); give --rng for the roll" % (
                "goes through" if chance else "does not go through", trim(pen, 0), trim(eff, 0)))
    rec("SOURCE", SOURCE_LINE)


def cmd_angle(a):
    if a.front <= 0 or a.side <= 0:
        die("--front and --side thicknesses must be positive")
    if a.step <= 0 or a.max <= 0 or a.max >= 90:
        die("--step must be positive and --max under 90")
    rules_line = apply_rules(a)
    if rules_line:
        rec("RULES", rules_line)
    spread = _spread(a)
    rows, safe = [], []

    def judge(thickness, angle):
        over = bool(a.caliber and a.overmatch and a.caliber > a.overmatch * thickness)
        if angle >= 89.5:
            return "-", "edge-on", True
        if a.ricochet and angle >= a.ricochet and not over:
            return "-", "bounce", True
        eff_angle, _, _ = normalised(angle, a.norm, a.caliber, thickness, a.two_cal)
        eff = thickness / math.cos(math.radians(eff_angle))
        if a.pen is None:
            return trim(eff, 0), "", None
        chance = pen_chance(a.pen, eff, spread, a.sigma, a.uniform)
        if chance <= 0.0:
            return trim(eff, 0), "holds", True
        if chance >= 1.0:
            return trim(eff, 0), "PEN" + (" (overmatch)" if over else ""), False
        return trim(eff, 0), "%s pen" % pct(chance), False

    yaw = 0.0
    while yaw <= a.max + 1e-9:
        fa = impact_angle(a.front_slope, yaw)
        sa = impact_angle(a.side_slope, 90.0 - yaw)
        fe, fs, fok = judge(a.front, fa)
        se, ss, sok = judge(a.side, sa)
        rows.append((trim(yaw, 1), trim(fa, 1), fe, fs, trim(sa, 1), se, ss))
        if fok and sok:
            safe.append(yaw)
        yaw += a.step
    rec("HULL", "front %s mm at %s deg, side %s mm at %s deg%s [geometry derived; game rules as passed in]" % (
        trim(a.front, 0), trim(a.front_slope, 1), trim(a.side, 0), trim(a.side_slope, 1),
        " | against %s mm pen%s" % (trim(a.pen, 0), ", %s mm shell" % trim(a.caliber, 0) if a.caliber else "") if a.pen else ""))
    table(rows, header=("yaw", "front deg", "front mm", "front", "side deg", "side mm", "side"), indent=2, right=(0, 1, 2, 4, 5))
    if a.pen is not None:
        if safe:
            runs, start, prev = [], safe[0], safe[0]
            for y in safe[1:]:
                if y - prev > a.step + 1e-9:
                    runs.append((start, prev))
                    start = y
                prev = y
            runs.append((start, prev))
            rec("WINDOW", "both plates hold or bounce at yaw %s deg [to the %s deg step]" % (
                ", ".join("%s to %s" % (trim(s, 1), trim(e, 1)) if e > s else trim(s, 1) for s, e in runs), trim(a.step, 1)))
        else:
            rec("WINDOW", "no hull angle keeps both plates safe from this shell; show less of yourself instead")
    rec("SOURCE", "check the current patch for normalisation, ricochet angle, the calibre rules and the spread")


def cmd_spot(a):
    if a.cap is None or a.min is None:
        rules = load_data("rulesets")["house"]
        a.cap = rules["spot_cap"] if a.cap is None else a.cap
        a.min = rules["spot_min"] if a.min is None else a.min
        rec("RULES", "cap %s m, always spotted inside %s m [%s; for the real game check the current patch]" % (
            trim(a.cap, 0), trim(a.min, 0), rules["label"]))
    if a.view <= 0 or a.cap <= 0 or a.min < 0:
        die("--view, --cap and --min must be positive")
    camo = (a.camo + (a.foliage or 0.0)) / 100.0
    camo = max(0.0, min(1.0, camo))
    raw = a.view - (a.view - a.min) * camo
    spot = max(a.min, min(a.cap, raw))
    rec("SPOTTER", "view range %s m (cap %s m, always spotted inside %s m) [game rules as passed in]" % (
        trim(a.view, 0), trim(a.cap, 0), trim(a.min, 0)))
    rec("TARGET", "concealment %s%%%s = %s%% in all" % (
        trim(a.camo, 1), " + %s%% from foliage" % trim(a.foliage, 1) if a.foliage else "", trim(camo * 100, 1)))
    rec("SPOTTED", "at %s m or closer [derived: view - (view - %s) x concealment%s]" % (
        trim(spot, 0), trim(a.min, 0), ", then capped" if raw > a.cap else ""))
    if a.view > a.cap:
        more("view range past the cap is not wasted: it is what cuts through concealment inside the cap")
    rec("SOURCE", "the shape of the formula is long-standing; the cap, the minimum and every concealment value come from the current patch")


def register(sub):
    p = command(sub, "combat", "armour", cmd_armour,
                "a sloped plate against a shell: impact angle, ricochet, normalisation, effective thickness, chance to go through",
                ["armour 120 45 --yaw 30 --shell ap --caliber 105 --pen 225",
                 "armour 50 60 --shell ap --caliber 130 --pen 260",
                 "armour 100 55 --shell apcr --caliber 90 --pen-near 240 --pen-far 215 --dist 300",
                 "armour 120 45 --yaw 30 --norm 5 --caliber 105 --overmatch 3 --ricochet 70"])
    p.add_argument("thickness", type=float, help="nominal plate thickness, mm")
    p.add_argument("slope", type=float, help="plate slope, degrees from the normal (0 = upright)")
    p.add_argument("--shell", choices=["ap", "apcr", "heat", "he"],
                   help="take the game rules for this shell type from the house rules (data/rulesets.json)")
    p.add_argument("--yaw", type=float, default=0.0, help="hull angling, degrees")
    p.add_argument("--elev", type=float, default=0.0, help="shell's angle of descent, degrees (plunging fire)")
    p.add_argument("--norm", type=float, help="normalisation for this shell type, degrees [game rule]")
    p.add_argument("--caliber", "--calibre", dest="caliber", type=float, help="shell calibre, mm")
    p.add_argument("--two-cal", type=float, help="2-calibre multiplier: over twice the plate, normalisation x this x calibre / (2 x plate) [game rule]")
    p.add_argument("--overmatch", type=float, help="overmatch multiple: over this many times the plate, no automatic ricochet [game rule]")
    p.add_argument("--ricochet", type=float, help="automatic ricochet angle, degrees [game rule]")
    p.add_argument("--pen", type=float, help="average penetration at this range, mm")
    p.add_argument("--pen-near", type=float, help="penetration at the near range, mm (instead of --pen)")
    p.add_argument("--pen-far", type=float, help="penetration at the far range, mm")
    p.add_argument("--dist", type=float, help="range to the target, m")
    p.add_argument("--near", type=float, default=50.0, help="near range for the two figures, m (default 50) [game rule]")
    p.add_argument("--far", type=float, default=500.0, help="far range for the two figures, m (default 500) [game rule]")
    p.add_argument("--rng", type=float, help="penetration spread, plus or minus percent [game rule]")
    p.add_argument("--sigma", type=float, help="bell curve: one standard deviation as a fraction of the spread [game rule]")
    p.add_argument("--uniform", action="store_true", help="treat the roll as evenly spread instead of a bell curve")
    p.add_argument("--screen", type=float, help="effective thickness of a spaced screen hit first, mm")
    p.add_argument("--gap", type=float, help="air gap behind the screen, mm")
    p.add_argument("--gap-loss", type=float, help="penetration lost per 100 mm of gap, percent [game rule]")

    p = command(sub, "combat", "angle", cmd_angle,
                "hull angling: front and side plates against one shell across a sweep of yaw, and the safe window",
                ["angle --front 120 --front-slope 60 --side 80 --shell ap --pen 225 --caliber 105",
                 "angle --front 200 --front-slope 30 --side 60 --step 2.5 --max 40"])
    p.add_argument("--shell", choices=["ap", "apcr", "heat", "he"], help="take the game rules for this shell type from the house rules")
    p.add_argument("--front", type=float, required=True, help="front plate, mm")
    p.add_argument("--front-slope", type=float, default=0.0, help="front plate slope, degrees from the normal")
    p.add_argument("--side", type=float, required=True, help="side plate, mm")
    p.add_argument("--side-slope", type=float, default=0.0, help="side plate slope, degrees")
    p.add_argument("--pen", type=float, help="the shell's average penetration, mm")
    p.add_argument("--caliber", "--calibre", dest="caliber", type=float)
    p.add_argument("--norm", type=float)
    p.add_argument("--two-cal", type=float)
    p.add_argument("--overmatch", type=float)
    p.add_argument("--ricochet", type=float)
    p.add_argument("--rng", type=float)
    p.add_argument("--sigma", type=float)
    p.add_argument("--uniform", action="store_true")
    p.add_argument("--step", type=float, default=5.0, help="yaw step, degrees (default 5)")
    p.add_argument("--max", type=float, default=60.0, help="largest yaw to try (default 60)")

    p = command(sub, "combat", "spot", cmd_spot,
                "spotting distance from view range and the target's concealment",
                ["spot --view 420 --camo 25", "spot --view 480 --camo 30 --foliage 50 --cap 445 --min 50"])
    p.add_argument("--view", type=float, required=True, help="the spotter's view range, m")
    p.add_argument("--camo", type=float, required=True, help="the target's concealment right now, percent")
    p.add_argument("--foliage", type=float, help="extra concealment from bushes or trees in the line of sight, percent")
    p.add_argument("--cap", type=float, help="maximum spotting distance, m (default: house rules) [game rule]")
    p.add_argument("--min", type=float, help="distance inside which everything is spotted, m (default: house rules) [game rule]")
